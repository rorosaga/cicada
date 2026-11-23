"""A stated value said again in other words replaces the old one (G148, 2026-11-23).

A stated value is the literal claim ``value-of-<attribute>``, one at a time (`claims.same_value_attribute`). Stage 1 reads
each conversation alone, so the attribute is worded each time: "price per postcard: 4 euros", then, three weeks later
and in French, "prix des cartes: 5 euros". Two sets of words with nothing in common never meet, so both stayed current
(`benchmarks/consolidation` V2, 3 of 3 key runs) — a stale value read as current, the classic memory failure.

Words cannot decide it in any language, and a list of spellings fits one case. What decides it is meaning, read where
the page is: after Stage 1 and before Stage 3, for each page that gains an attribute no value on it is worded like
(`orphans`), ONE call to Sleep's small judge lists that page's values and asks which lines state the same attribute.
A line it joins to another is renamed to that line's predicate, and Stage 3 does the rest as it always has: the newer
value closes the older (`valid_to`, `superseded_by`), nothing is deleted, and the trust rules still decide who may close
whom. The judge never edits a claim; it only names which attribute a new value belongs to.

**A false join is as bad as a miss** (a postcard's price and a print's price are two values), so the prompt says to
keep apart anything that could be true at once, and the code adds two rails the model cannot talk its way past: a pair
that one conversation stated together is never one attribute, and only a newly read value is ever renamed.

**Calls:** none on a page that gains no new attribute or has nothing to join it to; otherwise one per page per batch,
at most `MAX_ASKS` pages a batch, at most `MAX_LINES` lines a call (`questions`). Never on the capture path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from loguru import logger

from api.services import claim_reconciler as reconciler
from api.services.claims import VALUE_PREFIX, is_value_claim, same_value_attribute

STAGE = "value_match"
#: Pages asked per batch, and lines (distinct attributes) listed per page. A page of fifty values costs one call that
#: lists the newest forty; past MAX_ASKS the remaining pages keep what Stage 3 would have done without this step.
MAX_ASKS = 24
MAX_LINES = 40
MAX_LINE_CHARS = 160

PROMPT = """One person's memory page for ONE thing lists values stated about it, one line each: the attribute as it was \
worded when stated (conversations word it differently, sometimes in another language), its value, and the date it was \
said. Find the lines that state the SAME attribute of this thing, so that a later value replaces an earlier one.

Lines are the SAME only when they measure one and the same property of this thing and the later value would make the \
earlier one obsolete. Lines are DIFFERENT when anything about what is measured differs: what it is of (a card or a \
print), what it includes (with or without flights), its scope, period or distance (5k or 10k), its role (a goal or a \
result, a minimum or a maximum), or its kind (a price, a count, a date). Two lines that can both be true at once are \
DIFFERENT. When unsure, they are DIFFERENT.

THING: {name}
LINES:
{lines}

Reply with JSON only: {{"same": [[line numbers stating one attribute], ...]}}. Leave out a line with no match. \
{{"same": []}} when none."""


@dataclass
class Line:
    """One attribute on a page: every open value claim sharing a predicate, context and observer."""

    n: int
    predicate: str
    key: tuple[str, str]                  # (context, slot observer): only values of one slot can replace each other
    claims: list = field(default_factory=list)
    incoming: bool = False                # true when every claim is one this batch brings

    @property
    def latest(self):
        return max(self.claims, key=lambda c: str(c.valid_from or ""))

    @property
    def episodes(self) -> set[str]:
        return {e for c in self.claims for e in (c.source_episodes or [])}


@dataclass
class Ask:
    subject: str
    lines: list[Line]


def _label(predicate: str) -> str:
    return predicate[len(VALUE_PREFIX):].replace("-", " ").strip()


def _open_value(c) -> bool:
    return is_value_claim(c) and not getattr(c, "valid_to", None) and not getattr(c, "superseded_by", None)


def _lines(incoming: list, existing: list) -> list[Line]:
    """One page's attributes, one line per predicate, context and observer: what its open values name, then what this
    batch brings. A value read again (its id already on the page) is the page's own, never new."""
    by_key: dict[tuple, Line] = {}
    known = {c.id for c in existing}
    for fresh, claims in ((False, existing), (True, [c for c in incoming if c.id not in known])):
        for c in claims:
            if not _open_value(c):
                continue
            slot = (c.context, reconciler.slot_observer(c))
            line = by_key.setdefault((c.predicate, *slot), Line(0, c.predicate, slot, [], True))
            line.claims.append(c)
            line.incoming = line.incoming and fresh
    out = sorted(by_key.values(), key=lambda ln: (ln.incoming, str(ln.latest.valid_from or "")))
    for i, line in enumerate(out, 1):
        line.n = i
    return out


def _worded_alike(a: Line, b: Line) -> bool:
    return a.key == b.key and (a.predicate == b.predicate or same_value_attribute(a.predicate, b.predicate))


def _joinable(new: Line, other: Line) -> bool:
    """Could ``new`` be ``other`` said again? Same slot (only values of one slot ever replace each other), and never two
    values one conversation stated together: said side by side, they are two things."""
    return (other is not new and new.key == other.key and new.predicate != other.predicate
            and not (new.episodes & other.episodes))


def orphans(lines: list[Line]) -> list[Line]:
    """New attributes with something to join: no value on the page is worded like them (Stage 3 joins those itself), but
    another line could be them."""
    return [ln for ln in lines if ln.incoming
            and not any(not o.incoming and _worded_alike(ln, o) for o in lines)
            and any(_joinable(ln, o) and not _worded_alike(ln, o) for o in lines)]


def questions(incoming: list, existing_by_subject: dict) -> list[Ask]:
    """The pages this batch needs one call for, the most new attributes first, at most ``MAX_ASKS``."""
    by_subject: dict[str, list] = {}
    for c in incoming:
        if _open_value(c):
            by_subject.setdefault(c.subject, []).append(c)
    asks: list[tuple[int, str, Ask]] = []
    for subject, fresh in by_subject.items():
        lines = _lines(fresh, list(existing_by_subject.get(subject) or []))
        wanted = orphans(lines)
        if not wanted:
            continue
        # Listed: the new attributes with something to join, then what they could join, newest first, bounded.
        listed = list(wanted)
        for o in sorted(lines, key=lambda ln: str(ln.latest.valid_from or ""), reverse=True):
            if o not in listed and any(_joinable(w, o) for w in wanted):
                listed.append(o)
        listed = [Line(i, ln.predicate, ln.key, ln.claims, ln.incoming) for i, ln in enumerate(listed[:MAX_LINES], 1)]
        asks.append((-len(wanted), subject, Ask(subject, listed)))
    asks.sort(key=lambda t: (t[0], t[1]))
    return [a for _, _, a in asks[:MAX_ASKS]]


def prompt(ask: Ask) -> str:
    rows = []
    for line in ask.lines:
        c = line.latest
        said = str(c.valid_from or "")[:10]
        # The claim's own sentence keeps the attribute's spelling as said ("Teamgröße"); the predicate's slug folds
        # accents away. Without a sentence, the slug and the value.
        said_as = " ".join((c.text or "").split()) or f"{_label(line.predicate)}: {' '.join(str(c.object).split())}"
        rows.append(f"{line.n}. {said_as[:MAX_LINE_CHARS]}" + (f" ({said})" if said else ""))
    return PROMPT.format(name=ask.subject.replace("-", " "), lines="\n".join(rows))


def groups(reply: dict, ask: Ask) -> list[list[Line]]:
    """The judge's groups as lines: real line numbers only, two or more each, no line twice (a model that puts one
    attribute in two groups has not decided, so the later group is dropped)."""
    by_n = {line.n: line for line in ask.lines}
    seen: set[int] = set()
    out: list[list[Line]] = []
    raw = reply.get("same") if isinstance(reply, dict) else None
    for group in raw if isinstance(raw, list) else []:
        nums: list[int] = []
        for item in group if isinstance(group, list) else []:
            try:
                n = int(re.sub(r"\D", "", str(item)) or 0)
            except ValueError:
                continue
            if n in by_n and n not in nums:
                nums.append(n)
        if len(nums) >= 2 and not seen & set(nums):
            seen |= set(nums)
            out.append([by_n[n] for n in nums])
    return out


def rename(group: list[Line]) -> list[tuple[str, str, str]]:
    """Give each new attribute of ``group`` the predicate of the line it restates; ``(claim id, was, now)`` per claim.

    The canonical line is an existing one (the most recently said), else the earliest of this batch's: the newer value
    then closes the older, whichever order the conversations were read in. A new line joins it only when they share a
    slot and no conversation, and only new claims are ever renamed — a value already on the page keeps its predicate."""
    def said(ln: Line) -> str:
        return str(ln.latest.valid_from or "")

    existing = [ln for ln in group if not ln.incoming]
    canon = max(existing, key=said) if existing else min(group, key=said)
    moved: list[tuple[str, str, str]] = []
    for line in group:
        if line is canon or not line.incoming or not _joinable(line, canon):
            continue
        for c in line.claims:
            moved.append((c.id, c.predicate, canon.predicate))
            c.predicate = canon.predicate
    return moved


def align(incoming: list, existing_by_subject: dict, judge: Callable[[str], dict] | None) -> list[dict]:
    """Rename the batch's new values onto the attribute they restate, one judge call per page that needs it. ``judge``
    takes a prompt and returns the parsed JSON object (``{}`` for none). Mutates ``incoming``; returns audit entries.
    A failed call costs that page its alignment, never the batch (Stage 3 then runs as it did before this step)."""
    if judge is None:
        return []
    audit: list[dict] = []
    for ask in questions(incoming, existing_by_subject):
        try:
            reply = judge(prompt(ask))
        except Exception as exc:  # noqa: BLE001 - no judge answer means no alignment, never a lost batch
            logger.info(f"value alignment: a call failed ({type(exc).__name__}); the rest of the batch keeps its words")
            break
        for group in groups(reply, ask):
            for claim_id, was, now in rename(group):
                audit.append({"action": "value_aligned", "claim": claim_id, "from": was, "to": now})
    return audit


def judge_for(settings) -> Callable[[str], dict] | None:
    """Sleep's small judge as a ``prompt -> dict`` call, or ``None`` when no engine can answer. The engine the cycle
    resolved, on its small tier (`in_short.small_tier`): the same bill as Stage 2's judge, never a different one."""
    try:
        from api.services import in_short, providers
        from api.services.engine_select import CLI_MODES

        small = in_short.small_tier(settings)
        if str(getattr(small, "llm_mode", "")).lower() in CLI_MODES:
            llm_fn = providers.resolve_llm_fn(small, stage=STAGE, is_async=False)
        else:
            import litellm

            llm_fn = providers.resolve_llm_fn(small, model=small.litellm_model, completion=litellm.completion,
                                              stage=STAGE)
    except Exception as exc:  # noqa: BLE001 - no engine: values keep the words Stage 1 gave them
        logger.info(f"value alignment: no engine ({type(exc).__name__})")
        return None

    def judge(text: str) -> dict:
        from api.services import json_parse

        resp = llm_fn(messages=[{"role": "user", "content": text}], response_format={"type": "json_object"})
        try:
            raw = resp.choices[0].message.content
        except (AttributeError, IndexError, TypeError):
            raw = resp.get("choices", [{}])[0].get("message", {}).get("content") if isinstance(resp, dict) else ""
        return json_parse.parse_json_object_or(raw or "", {})

    return judge
