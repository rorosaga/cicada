"""A value that names what the same page's link to it dropped is read with that drop (G148, 2026-11-23).

A page already knows a thing was replaced when a conversation said it dropped X: Stage 3 closes the page's link to X
(``claim_reconciler._place_ending``) and, since #779, a value whose WHOLE literal is X ("implementation language:
Python"). A value that carries X with something more ("Python with Pillow") was left open beside the new one, and an
agent read two languages as current (`benchmarks/consolidation` U3, 4 of 12 runs, 40 replays: 24 refused).

Why the join step could not do it (`value_alignment`): it compares two VALUES, and a later "core language: TypeScript"
beside "implementation language: Python with Pillow" reads, fairly, as a part against a whole ("the core is narrower, the
rest may still be Python": 24 of 24 refusals said so). What settles it is not in either value. It is the person's line
that dropped the thing ("and dropped the Python version entirely"), which the page already holds as the ending.

So, for each ending an incoming claim brings (an ``over`` label on a node: "dropped", "replaced", "stopped using"), the
open values on that page whose literal NAMES the dropped thing — its id's words, contiguous, in the literal — are
candidates; no word list, no attribute words, any language. ONE judge call per candidate shows the value, the ending and
the person's own words behind each (`value_alignment.Words`), and asks whether the ending makes the value out of date
or the value can still hold (a part, another purpose, a passing mention). Only a yes goes to Stage 3, which closes it
exactly as it closes the link (`valid_to`, `superseded_by`; nothing deleted; an agent's ending never closes the person's
own value; an ending older than the value closes nothing).

**What rested on the thing that ended (2026-11-24).** A person who leaves an employer names no new title, and "job
title at <employer>: data engineer" stayed current; "leads the <employer> migration" stayed current beside "left
<employer>" in all 145 stored runs of the benchmark's Ines (`benchmarks/consolidation`, scan 2026-11-24). Nothing ties
such a claim to the job except what it NAMES, so the same candidate rule reads one step further, structurally and in any
language (the id's words, contiguous, in the claim's own words, never a word list): an open claim of the ending's
subject whose attribute, object or text names the ended thing, whose object is another thing the memory ties to it (that
page holds an open line naming it), or another page's line naming the subject on a page so tied. The ties and the
ending's own words go to ONE judge call each, which may say the fact can still hold (a skill, a friend who is still
there, the employer's own fact). Nothing but a plain yes closes, dated from when the ending was said, undoably, like a
value; a person's own claim is never closed by an agent's ending; at most ``MAX_ASKS`` per batch, values first.

**Never re-asked:** a candidate exists only while the ending is incoming — the batch that reads the conversation that
said it — so a refused pair is not asked again on a later Sleep unless a conversation drops the thing again (new
evidence). **Calls:** none unless an ending has a candidate; otherwise one per (ending, value), at most ``MAX_ASKS`` a
batch. Never on the capture path.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import yaml
from loguru import logger

from api.services import claim_reconciler as reconciler
from api.services import predicates
from api.services.claims import VALUE_PREFIX, is_event, is_record, is_value_claim
from api.services.id_utils import sanitize_id
from api.services.value_alignment import MAX_LINE_CHARS, Words

STAGE = "value_match"
#: Judge calls per batch; past it a candidate keeps what Stage 3 would have done without this step (stays open).
MAX_ASKS = 24

PROMPT = """One person's memory page for ONE thing holds a value stated about it, and a later conversation said the \
thing dropped something that value names.

THING: {name}
VALUE: {value}
{value_words}LATER: {ending}
{ending_words}
{note}Does LATER make VALUE out of date, because VALUE says the thing is, uses or is made with what was dropped? Or can \
VALUE still be true: it is about a part of the thing, another purpose of what was dropped, something else that only \
mentions it, or it says more than what was dropped? When unsure, it can still be true.

Reply with JSON only: {{"why": "<what VALUE says and what was dropped, a few words>", "out_of_date": true or false}}"""

NOTE = """The person's own words follow a line where known: they show what was dropped and from what. They may name \
something broader or narrower than the wording of the line.

"""


SCOPE_PROMPT = """One person's memory holds a fact, and a later conversation said {name} left, dropped or ended \
something the fact may depend on.

FACT: {fact}
{fact_words}{tie}LATER: {ending}
{ending_words}
Does LATER make FACT out of date, because FACT only held while {name} was with {what}: a role, title, project, place, \
arrangement or use that belonged to it and ended with it? Or can FACT still be true: it is the person's own skill or \
field, the history of an earlier time, someone who is still there and the person's own tie to them (a friend, someone they \
mentor), something about {what} itself, or it holds with or without it? When unsure, it can still be true.

Reply with JSON only: {{"why": "<what FACT depends on and what ended, a few words>", "out_of_date": true or false}}"""

#: The order the structural reasons are asked in (and the bound is spent in): the closest tie first.
KINDS = ("attribute", "same-object", "names-it", "on-a-thing-of", "other-page")


def names(literal, thing_id: str) -> bool:
    """Does ``literal`` name the thing whose page id is ``thing_id``: the id's words, in order and whole, among the
    literal's own (``python`` in "Python with Pillow"; never inside a longer word, never the same literal alone: that is
    `claim_reconciler._place_ending`'s own rule)."""
    want = [w for w in sanitize_id(thing_id).split("-") if w]
    have = [w for w in sanitize_id(str(literal or "")).split("-") if w]
    if not want or have == want:
        return False
    return any(have[i:i + len(want)] == want for i in range(len(have) - len(want) + 1))


def candidates(incoming: list, existing_by_subject: dict, endings_fn) -> list[tuple]:
    """``(ending claim, value claim)`` pairs: an incoming ending of a node, and an open value on its page, older than
    it, that names the dropped thing and that the ending's own trust may close."""
    out = []
    for new in incoming:
        if getattr(new, "object_kind", "") != "node":
            continue
        try:
            ending = endings_fn(str(getattr(new, "predicate_raw", None) or new.predicate))
        except Exception:  # noqa: BLE001 - a label the oracle cannot read ends nothing
            ending = None
        if ending is None or ending.mode != predicates.ENDING_OVER:
            continue
        said = str(new.valid_from or "")
        for c in existing_by_subject.get(new.subject) or []:
            if (is_value_claim(c) and reconciler.open_(c) and not c.superseded_by and names(c.object, new.object)
                    and str(c.valid_from or "") <= said and not (reconciler.is_human(c) and not reconciler.is_human(new))
                    and not (set(c.source_episodes or []) & set(new.source_episodes or []))):
                out.append((new, c))
    return out


def _words(text) -> list[str]:
    return [w for w in sanitize_id(str(text or "")).split("-") if w]


def _within(have: list[str], want: list[str]) -> bool:
    return bool(want) and any(have[i:i + len(want)] == want for i in range(len(have) - len(want) + 1))


def _tie(page: str, thing: list[str], pool: dict, exclude: set[str]):
    """An open line on ``page`` that names ``thing`` (its object, or its text's words), or ``None``: what the memory
    already says about the page that ties it to the thing ("Snowflake migration belongs to Halvard")."""
    needle = thing[0] if thing else ""
    for x in pool.get(page) or []:
        if needle not in f"{x.text} {x.object}".lower():
            continue          # cheap first: most lines never carry the thing's first word
        if x.valid_to is None and x.id not in exclude and not is_event(x) and not is_record(x) and (
                (x.object_kind == "node" and _words(x.object) == thing) or _within(_words(x.text), thing)):
            return x
    return None


def _alias_pages(memory_path) -> dict[str, str]:
    """``{alias or name, slugged: page id}`` from the pages' own frontmatter, read once per call and only when a claim's
    object names no page by id (an edge Stage 2 wrote under an alias: "Warehouse migration" on the page "Snowflake
    migration"). Frontmatter only; a page that does not read adds nothing."""
    out: dict[str, str] = {}
    entities = Path(memory_path) / "entities" if memory_path else None
    if entities is None or not entities.is_dir():
        return out
    for path in sorted(entities.glob("*.md")):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                head = fh.read(65536)
            if not head.startswith("---"):
                continue
            block = head[3:head.index("\n---", 3)]
            meta = yaml.safe_load(block) or {}
            for label in [meta.get("name"), *(meta.get("aliases") or [])]:
                slug = sanitize_id(str(label or ""))
                if slug:
                    out.setdefault(slug, path.stem)
        except Exception:  # noqa: BLE001 - one unreadable page is one alias fewer
            continue
    return out


def _open_older(c, ending, said: str) -> bool:
    """May ``ending`` ask about ``c`` at all: open, said before it and in another conversation, a plain claim, and not
    the person's own under an agent's word (the guards of ``candidates``)."""
    return (reconciler.open_(c) and not c.superseded_by and not is_event(c) and not is_record(c) and c.id != ending.id
            and str(c.valid_from or "") <= said and not (reconciler.is_human(c) and not reconciler.is_human(ending))
            and not (set(c.source_episodes or []) & set(ending.source_episodes or [])))


def scope_candidates(incoming: list, existing_by_subject: dict, endings_fn, memory_path=None) -> list[tuple]:
    """``(ending, claim, kind, tie)``: what an ending of a node ("left Halvard", "dropped Python") may have ended with
    it, by one of ``KINDS``. ``tie`` is the line on another page that ties the claim to the thing, or ``None``. Never
    the values ``candidates`` asks about, nor the beliefs Stage 3 closes with the ending itself."""
    pool = {sub: list(claims) for sub, claims in existing_by_subject.items()}
    for c in incoming:
        pool.setdefault(c.subject, []).append(c)
    aliases: list[dict] = []

    def page_of(object_id: str) -> str:
        """The page an object id keys to: itself when a page holds claims under it, else the page that bears it as a
        name or alias."""
        if object_id in pool or not memory_path:
            return object_id
        if not aliases:
            aliases.append(_alias_pages(memory_path))
        return aliases[0].get(object_id, object_id)

    def pages_named_in(*texts) -> list[str]:
        """The pages a value's attribute or literal names: any run of its words that is a page's id, name or alias."""
        if not aliases:
            aliases.append(_alias_pages(memory_path) if memory_path else {})
        found: list[str] = []
        for text in texts:
            ws = _words(text)
            for i in range(len(ws)):
                for j in range(i + 1, min(len(ws), i + 6) + 1):
                    key = "-".join(ws[i:j])
                    page = key if key in pool else aliases[0].get(key)
                    if page and page not in found:
                        found.append(page)
        return found

    out = []
    for new in incoming:
        if getattr(new, "object_kind", "") != "node":
            continue
        try:
            ending = endings_fn(str(getattr(new, "predicate_raw", None) or new.predicate))
        except Exception:  # noqa: BLE001 - a label the oracle cannot read ends nothing
            ending = None
        if ending is None or ending.mode != predicates.ENDING_OVER:
            continue
        ended_by = getattr(endings_fn, "ended_by", None)
        thing, who, said = _words(new.object), _words(new.subject), str(new.valid_from or "")
        thing_id = sanitize_id(str(new.object or ""))
        found: dict[str, tuple] = {}

        def add(c, kind, tie=None):
            if c.id not in found:
                found[c.id] = (new, c, kind, tie)

        def stage3s(c) -> bool:      # a belief `_place_ending` closes with this ending: asked of nobody
            return sanitize_id(str(c.object or "")) == thing_id and (
                c.predicate == ending.canonical or (ended_by is not None and ended_by(c.predicate) == ending.canonical))

        for c in pool.get(new.subject) or []:
            if c is new or not _open_older(c, new, said) or stage3s(c):
                continue
            if is_value_claim(c):
                if names(c.object, new.object):
                    continue         # `candidates`' own
                if _within(_words(c.predicate[len(VALUE_PREFIX):]), thing):
                    add(c, "attribute")
                else:
                    for page in pages_named_in(c.predicate[len(VALUE_PREFIX):], c.object):
                        tie = _tie(page, thing, pool, {c.id}) if page not in (new.subject, thing_id) else None
                        if tie is not None:
                            add(c, "on-a-thing-of", tie)
                            break
            elif c.object_kind == "node":
                page = sanitize_id(str(c.object or ""))
                if page == thing_id:
                    add(c, "same-object")
                elif _within(_words(page), thing) or _within(_words(c.text), thing):
                    add(c, "names-it")
                elif page and page != sanitize_id(new.subject):
                    page = page_of(page)
                    tie = _tie(page, thing, pool, {c.id})
                    if tie is not None:
                        add(c, "on-a-thing-of", tie)
        # Another page's line naming the subject, on a page the memory ties to the thing.
        for page, claims in pool.items():
            if page in (new.subject, thing_id) or not claims:
                continue
            tie = _tie(page, thing, pool, set())
            if tie is None:
                continue
            for c in claims:
                if (c is not tie and _open_older(c, new, said)
                        and ((c.object_kind == "node" and _words(c.object) == who) or _within(_words(c.object), who)
                             or _within(_words(c.text), who))):
                    add(c, "other-page", tie)
        out.extend(found.values())
    out.sort(key=lambda t: (KINDS.index(t[2]), str(t[1].valid_from or ""), t[1].id))
    return out


def _said(claim) -> str:
    day = str(claim.valid_from or "")[:10]
    text = " ".join((claim.text or "").split())[:MAX_LINE_CHARS]
    return f"{text} ({day})" if day else text


def prompt(ending, value, words: Words | None) -> str:
    said_v, said_e = (words.of(value) if words else ""), (words.of(ending) if words else "")
    return PROMPT.format(
        name=ending.subject.replace("-", " "), value=_said(value), ending=_said(ending),
        value_words=f'   they said: "{said_v}"\n' if said_v else "",
        ending_words=f'   they said: "{said_e}"\n' if said_e else "",
        note=NOTE if said_v or said_e else "")


def scope_prompt(ending, claim, tie, words: Words | None) -> str:
    said_v, said_e = (words.of(claim) if words else ""), (words.of(ending) if words else "")
    return SCOPE_PROMPT.format(
        name=ending.subject.replace("-", " "), what=ending.object.replace("-", " "), fact=_said(claim),
        ending=_said(ending),
        fact_words=f'   they said: "{said_v}"\n' if said_v else "",
        ending_words=f'   they said: "{said_e}"\n' if said_e else "",
        tie=f'   the memory also holds, on the page for {tie.subject.replace("-", " ")}: {_said(tie)}\n' if tie else "")


def plan(incoming: list, existing_by_subject: dict, judge: Callable[[str], dict] | None, memory_path=None,
         endings_fn=None) -> tuple[dict[str, set[str]], list[dict]]:
    """``({ending claim id: {value claim ids it closes}}, audit)``: only a judge's plain yes closes one. Mutates
    nothing; Stage 3 takes the map (`reconcile_stage3(ended_values=)`). A failed call keeps the rest of the batch's
    values open, never loses a claim."""
    if judge is None or not incoming:
        return {}, []
    kinds = endings_fn or predicates.build_endings_fn(memory_path)
    try:
        pairs = candidates(incoming, existing_by_subject, kinds)
    except Exception as exc:  # noqa: BLE001
        logger.info(f"value ended: candidates not read ({type(exc).__name__})")
        return {}, []
    try:
        scoped = scope_candidates(incoming, existing_by_subject, kinds, memory_path)
    except Exception as exc:  # noqa: BLE001 - what rested on it stays open, as before this step
        logger.info(f"value ended: scope not read ({type(exc).__name__})")
        scoped = []
    if not pairs and not scoped:
        return {}, []
    words = Words(memory_path) if memory_path else None
    closes: dict[str, set[str]] = {}
    audit: list[dict] = []
    asked = 0
    try:
        asks = [(ending, value, prompt(ending, value, words)) for ending, value in pairs]
        asks += [(ending, claim, scope_prompt(ending, claim, tie, words)) for ending, claim, _kind, tie in scoped]
        for ending, value, text in asks[:MAX_ASKS]:
            asked += 1
            reply = judge(text)
            if isinstance(reply, dict) and reply.get("out_of_date") is True:
                closes.setdefault(ending.id, set()).add(value.id)
                audit.append({"action": "value_ended_by", "claim": value.id, "by": ending.id})
    except Exception as exc:  # noqa: BLE001 - no answer means the value stays open, as before this step
        logger.info(f"value ended: a call failed ({type(exc).__name__}); the rest of the batch keeps its values")
    logger.info(f"value ended: {asked} value(s) asked, {len(audit)} ended")
    return closes, audit
