"""A stated value said again in other words replaces the old one (G148, 2026-11-23).

A stated value is the literal claim ``value-of-<attribute>``, one at a time (`claims.same_value_attribute`). Stage 1 reads
each conversation alone, so the attribute is worded each time: "price per postcard: 4 euros", then, three weeks later
and in French, "prix des cartes: 5 euros". Two sets of words with nothing in common never meet, so both stayed current
(`benchmarks/consolidation` V2, 3 of 3 key runs) — a stale value read as current, the classic memory failure.

Words cannot decide it in any language, and a list of spellings fits one case. What decides it is meaning, read where
the page is: after Stage 1 and before Stage 3, for each page that gains an attribute no value on it is worded like
(`orphans`), ONE call to Sleep's small judge shows that page's values and asks, for each new line, which other line
states the same attribute (`proposals`). Each proposed join is then put to the judge once more, alone, as a correction
or not (`confirmed`): a join needs both to say yes, because **a false join is as bad as a miss** — a study's start date
once joined its readout date on one wrong answer, and the newer closed the older. A joined line is renamed to the other's
predicate, and Stage 3 does the rest as it always has: the newer value closes the older (`valid_to`, `superseded_by`),
nothing is deleted, and the trust rules still decide who may close whom. The judge never edits a claim.

Each line carries the person's own words (`Words`): the claim's sentence names the attribute but not what the person did
("I rewrote it in Go and dropped the old version"), which is what shows a replacement. A span that does not locate is
absent — never searched for.

Two rails the model cannot talk its way past: values one conversation stated together are never one attribute, and only a
newly read value is ever renamed.

**Calls:** none on a page that gains no new attribute or has nothing to join it to; otherwise one per page per batch (at
most `MAX_ASKS` pages, `MAX_LINES` lines each) plus one check per proposed join (at most `MAX_CHECKS` a batch). Joins are
rare, so checks are few. Never on the capture path.

**A second reading (2026-11-24):** a pair this step refuses is never seen again (only a NEW attribute is asked about,
and the newer value is not new next time), so when the first reading and its check leave a NEW line alone, the page is
read once more by a second reader (`REREAD`; the cycle's main model) and each join it proposes is checked by that same
reader: one more call per such page (at most `MAX_REREADS`) and one per proposal (at most `MAX_REREAD_CHECKS`). Nothing
is stored: the value is old after this batch, so each pair is read twice at most.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
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
#: Proposed joins checked per batch (each is one more call); a batch past it keeps what Stage 3 would have done.
MAX_CHECKS = 40
#: The person's own words shown beside a value: one located span, cut to this many characters.
MAX_WORDS_CHARS = 240
#: The second reading (2026-11-24): pages whose refused new lines are read once more, and the joins it proposes that
#: are checked, per batch. Past either the rest keep what the first reading decided.
MAX_REREADS = 24
MAX_REREAD_CHECKS = 24

PROMPT = """One person's memory page for ONE thing lists values stated about it, one line each: the attribute as it was \
worded when stated (conversations word it differently, sometimes in another language), its value, and the date it was \
said. Lines marked NEW were just read; the others are already on the page.

{note}For each NEW line, name the OTHER line, if any, that states the same attribute of this thing in other words: the \
later value would then replace the earlier one. A second reader checks every answer you give, so name the closest \
line whenever the NEW line could be that attribute reworded, translated or shortened; answer null only when no line \
could be it. Attributes that differ in anything measured are not the same: what it is of (a flat or its garage), what \
it includes (with or without tax), its scope or period (this year or last), its role (a target or an actual, a start \
or an end, a minimum or a maximum).

THING: {name}
LINES:
{lines}

Reply with JSON only, one answer per NEW line: {{"answers": [{{"line": <NEW line number>, "same_as": <the other \
line's number, or null>}}]}}"""

#: Added only when a line carries the person's words (the prompts are otherwise exactly what they were before).
WORDS_NOTE = """A line may be followed by the person's own words that gave that value: they show what the value is of \
and whether the person was replacing an earlier value (a rewrite, a rise, a move, a new job). Words that report a \
change never make two lines one attribute: a person can change two different things in the same way.

"""
CHECK_NOTE = """The person's own words follow a value where known: they show what the value is of and whether the \
person was replacing the earlier one. The attribute names are only wording. Words that report a change never make \
two values one attribute: a person can change two different things in the same way.

"""

CHECK = """One person's memory holds two values stated about the same thing ({name}), said at different times.

EARLIER: {earlier}
LATER: {later}

{note}Is LATER a new value for the very same attribute as EARLIER (reworded or translated), so that EARLIER is now out of \
date? Or do they measure different things that can both be true at once: what it is of (a flat or its garage), what it \
includes (with or without tax), its scope or period (this year or last), its role (a target or an actual, a start or an \
end, a minimum or a maximum), or its kind (a price, a count, a date)? When unsure, they are different.

Reply with JSON only: {{"why": "<what is measured in each, a few words>", "same_attribute": true or false}}"""


#: The second reading's prompt: the same lines, but the first reading found no line for the NEW ones, so it is asked to
#: look again for the one way it errs: a different name for the same property. The rails are the same as the first's.
REREAD = """One person's memory page for ONE thing lists values stated about it, one line each: the attribute as it was \
worded when stated (conversations word it differently, sometimes in another language), its value, and the date it was \
said. Lines marked NEW were just read; the others are already on the page.

A first reading found no other line for the NEW lines below. Read them again. A property of a thing is often named in \
quite different words each time it is stated (a price and a cost, a language and a stack, a place of work and an \
employer, a launch and a release), and a person who says it again with a different value is replacing the old value, \
whether or not they say so. For each NEW line, name the OTHER line that states the very same property of this thing, \
so that the later value makes the earlier one out of date. Do not name a line that measures something else: what it is \
of (a flat or its garage), what it includes (with or without tax or flights), its scope or period (this year or last), \
its role (a target or an actual, a start or an end, a minimum or a maximum, a current value or an offer), or its kind \
(a price, a count, a date). When truly unsure, answer null.

{note}THING: {name}
LINES:
{lines}

Reply with JSON only, one answer per NEW line: {{"answers": [{{"line": <NEW line number>, "same_as": <the other \
line's number, or null>}}]}}"""


@dataclass
class Line:
    """One attribute on a page: every open value claim sharing a predicate, context and observer."""

    n: int
    predicate: str
    key: tuple[str, str]                  # (context, slot observer): only values of one slot can replace each other
    claims: list = field(default_factory=list)
    incoming: bool = False                # true when every claim is one this batch brings
    words: str = ""                       # the person's own words behind its latest claim (`Words.of`), "" when none locate

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


class Words:
    """The person's own words behind a value, read back from the span the claim carries (G118): what the judge needs
    to tell a replacement ("I rewrote it in Go", "j'ai monté le prix à 5 euros") from two things said alike.

    Only a span of the person's own turn that locates now (`source_spans.Source.status`: the offsets hold under the
    stored hash, no gap line, nothing `sensitive_text` is sure of) is ever shown, cut to ``MAX_WORDS_CHARS``; an
    inference, an assistant's or another speaker's words, a stale span or one that does not locate is simply absent —
    never searched for, never fuzzy. One read of each conversation per call, whatever the number of values."""

    def __init__(self, memory_path):
        self.memory_path = Path(memory_path) if memory_path else None
        self._sources: dict = {}

    def of(self, claim) -> str:
        if self.memory_path is None:
            return ""
        try:
            return next(filter(None, (self._one(ev) for ev in claim.evidence or [])), "")
        except Exception as exc:  # noqa: BLE001 - words are an aid; without them the judge sees what it always saw
            logger.info(f"value alignment: a span was not read ({type(exc).__name__})")
            return ""

    def _one(self, ev) -> str:
        from api.services import source_spans

        if getattr(ev, "kind", "") != "user" or not ev.is_span():
            return ""
        if ev.episode not in self._sources:
            self._sources[ev.episode] = source_spans.Source.open(self.memory_path, ev.episode)
        source = self._sources[ev.episode]
        if source is None or source.status(ev.start, ev.end, ev.hash) not in (source_spans.CURRENT, source_spans.GROWN):
            return ""
        said = " ".join(source.text[ev.start:ev.end].split())
        return said if len(said) <= MAX_WORDS_CHARS else said[:MAX_WORDS_CHARS].rstrip() + "…"


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


def questions(incoming: list, existing_by_subject: dict, words: Words | None = None) -> list[Ask]:
    """The pages this batch needs one call for, the most new attributes first, at most ``MAX_ASKS``. ``words`` reads the
    person's own words behind each listed line (none when ``None``)."""
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
        listed = [Line(i, ln.predicate, ln.key, ln.claims, ln.incoming, words.of(ln.latest) if words else "")
                  for i, ln in enumerate(listed[:MAX_LINES], 1)]
        asks.append((-len(wanted), subject, Ask(subject, listed)))
    asks.sort(key=lambda t: (t[0], t[1]))
    return [a for _, _, a in asks[:MAX_ASKS]]


def _sentence(line: Line) -> str:
    """What one line says: the claim's own sentence, which keeps the attribute's spelling as said ("Teamgröße") where the
    predicate's slug folds accents away; without a sentence, the slug and the value. Then the day it was said."""
    c = line.latest
    said = str(c.valid_from or "")[:10]
    text = " ".join((c.text or "").split()) or f"{_label(line.predicate)}: {' '.join(str(c.object).split())}"
    out = text[:MAX_LINE_CHARS] + (f" ({said})" if said else "")
    return out + (f'\n   they said: "{line.words}"' if line.words else "")


def prompt(ask: Ask, template: str = PROMPT) -> str:
    rows = [f"{line.n}. {'NEW ' if line.incoming else ''}{_sentence(line)}" for line in ask.lines]
    note = WORDS_NOTE if any(line.words for line in ask.lines) else ""
    return template.format(name=ask.subject.replace("-", " "), lines="\n".join(rows), note=note)


def refused(ask: Ask) -> Ask | None:
    """The page as it stands after the first reading, for a second one: the NEW lines no join took (their claims still
    carry the predicate they came with) stay NEW, every other line is listed as it is, a joined NEW line left out
    (it is the older one's now). ``None`` when no NEW line was refused, or nothing is left for one to be. Copies, so
    the first reading's lines are never renumbered; each keeps its claims, so a join renames the real ones."""
    kept = [ln for ln in ask.lines if not ln.incoming or all(c.predicate == ln.predicate for c in ln.claims)]
    if not any(ln.incoming for ln in kept) or len(kept) < 2:
        return None
    lines = [Line(i, ln.predicate, ln.key, ln.claims, ln.incoming, ln.words) for i, ln in enumerate(kept, 1)]
    return Ask(ask.subject, lines)


def proposals(reply: dict, ask: Ask) -> list[tuple[Line, Line]]:
    """The judge's answers as ``(new line, the line it restates)``: real line numbers only, a NEW line once, never itself.
    An answer that is null, missing or confused proposes nothing."""
    by_n = {line.n: line for line in ask.lines}
    seen: set[int] = set()
    out: list[tuple[Line, Line]] = []
    raw = reply.get("answers") if isinstance(reply, dict) else None
    for answer in raw if isinstance(raw, list) else []:
        if not isinstance(answer, dict):
            continue
        try:
            n, m = int(answer.get("line")), int(answer.get("same_as"))
        except (TypeError, ValueError):
            continue
        new, other = by_n.get(n), by_n.get(m)
        if new is None or other is None or new is other or not new.incoming or n in seen or not _joinable(new, other):
            continue
        seen.add(n)
        out.append((new, other))
    return out


def confirmed(new: Line, other: Line, ask: Ask, judge: Callable[[str], dict]) -> bool:
    """A second, narrower opinion on one proposed join: is the later a correction of the earlier, or can both stand? A
    join needs both to say so, so one wrong answer in a page of values never closes a true one (a study's start date was
    once joined to its readout date). Costs one call per proposal, and proposals are rare."""
    first, second = sorted((new, other), key=lambda ln: (str(ln.latest.valid_from or ""), ln.incoming))
    note = CHECK_NOTE if first.words or second.words else ""
    reply = judge(CHECK.format(name=ask.subject.replace("-", " "), earlier=_sentence(first), later=_sentence(second),
                               note=note))
    return isinstance(reply, dict) and reply.get("same_attribute") is True


def groups(pairs: list[tuple[Line, Line]]) -> list[list[Line]]:
    """Confirmed pairs as groups of lines that are one attribute (a line joined to a line that is itself joined to a
    third is one group of three)."""
    parent: dict[int, int] = {}

    def find(i: int) -> int:
        while parent.setdefault(i, i) != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    lines: dict[int, Line] = {}
    for new, other in pairs:
        lines[new.n], lines[other.n] = new, other
        parent[find(new.n)] = find(other.n)
    by_root: dict[int, list[Line]] = {}
    for n, line in lines.items():
        by_root.setdefault(find(n), []).append(line)
    return list(by_root.values())


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


def align(incoming: list, existing_by_subject: dict, judge: Callable[[str], dict] | None,
          memory_path=None, reread: Callable[[str], dict] | None = None) -> list[dict]:
    """Rename the batch's new values onto the attribute they restate: one judge call per page that needs it, then one
    check per join it proposes. ``judge`` takes a prompt and returns the parsed JSON object (``{}`` for none). Mutates
    ``incoming``; returns audit entries. ``memory_path`` lets each listed value carry the person's own words from its
    span (`Words`); without it the judge reads the claims' sentences alone. A failed call costs the batch its joins from then on, never a claim (Stage 3
    then runs as it did before this step).

    ``reread`` (2026-11-24) is a second reader, the cycle's main model: a page whose NEW lines the first reading and
    its check left alone is read once more, the lines it proposes are checked by the same reader, and a join needs its
    yes to both. The newer value is then no longer new, so no later batch asks about the pair again: each pair is read
    twice at most, ever, and nothing is stored to know it."""
    if judge is None:
        return []
    audit: list[dict] = []
    asked = checked = reread_asks = reread_checked = reread_joined = 0
    try:
        for ask in questions(incoming, existing_by_subject, Words(memory_path) if memory_path else None):
            asked += 1
            kept = []
            for new, other in proposals(judge(prompt(ask)), ask):
                if checked >= MAX_CHECKS:
                    break
                checked += 1
                if confirmed(new, other, ask, judge):
                    kept.append((new, other))
            for group in groups(kept):
                for claim_id, was, now in rename(group):
                    audit.append({"action": "value_aligned", "claim": claim_id, "from": was, "to": now})
            second = refused(ask) if reread is not None and reread_asks < MAX_REREADS else None
            if second is None:
                continue
            reread_asks += 1
            kept = []
            for new, other in proposals(reread(prompt(second, REREAD)), second):
                if reread_checked >= MAX_REREAD_CHECKS:
                    break
                reread_checked += 1
                if confirmed(new, other, second, reread):
                    kept.append((new, other))
            for group in groups(kept):
                for claim_id, was, now in rename(group):
                    reread_joined += 1
                    audit.append({"action": "value_aligned", "claim": claim_id, "from": was, "to": now,
                                  "reading": "second"})
    except Exception as exc:  # noqa: BLE001 - no judge answer means no alignment, never a lost batch
        logger.info(f"value alignment: a call failed ({type(exc).__name__}); the rest of the batch keeps its words")
    if asked:
        logger.info(f"value alignment: {asked} page(s) asked, {checked} join(s) checked, {len(audit) - reread_joined} "
                    f"value(s) joined; second reading: {reread_asks} page(s), {reread_checked} checked, "
                    f"{reread_joined} joined")
    return audit


def judge_for(settings, *, main: bool = False, stage: str = STAGE) -> Callable[[str], dict] | None:
    """Sleep's small judge as a ``prompt -> dict`` call, or ``None`` when no engine can answer. The engine the cycle
    resolved, on its small tier (`in_short.small_tier`): the same bill as Stage 2's judge, never a different one.
    ``main=True`` is the same engine on the model the cycle itself reads with (the second reading's). ``stage`` labels the
    calls in the ledger (`sleep_spend.LINE_STAGES` knows the ones that count against the person's line)."""
    try:
        from api.services import in_short, providers
        from api.services.engine_select import CLI_MODES

        small = settings if main else in_short.small_tier(settings)
        if str(getattr(small, "llm_mode", "")).lower() in CLI_MODES:
            llm_fn = providers.resolve_llm_fn(small, stage=stage, is_async=False)
        else:
            import litellm

            llm_fn = providers.resolve_llm_fn(small, model=small.litellm_model, completion=litellm.completion,
                                              stage=stage)
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
