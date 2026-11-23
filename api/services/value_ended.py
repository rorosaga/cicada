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

**Never re-asked:** a candidate exists only while the ending is incoming — the batch that reads the conversation that
said it — so a refused pair is not asked again on a later Sleep unless a conversation drops the thing again (new
evidence). **Calls:** none unless an ending has a candidate; otherwise one per (ending, value), at most ``MAX_ASKS`` a
batch. Never on the capture path.
"""
from __future__ import annotations

from typing import Callable

from loguru import logger

from api.services import claim_reconciler as reconciler
from api.services import predicates
from api.services.claims import is_value_claim
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


def plan(incoming: list, existing_by_subject: dict, judge: Callable[[str], dict] | None, memory_path=None,
         endings_fn=None) -> tuple[dict[str, set[str]], list[dict]]:
    """``({ending claim id: {value claim ids it closes}}, audit)``: only a judge's plain yes closes one. Mutates
    nothing; Stage 3 takes the map (`reconcile_stage3(ended_values=)`). A failed call keeps the rest of the batch's
    values open, never loses a claim."""
    if judge is None or not incoming:
        return {}, []
    try:
        pairs = candidates(incoming, existing_by_subject, endings_fn or predicates.build_endings_fn(memory_path))
    except Exception as exc:  # noqa: BLE001
        logger.info(f"value ended: candidates not read ({type(exc).__name__})")
        return {}, []
    if not pairs:
        return {}, []
    words = Words(memory_path) if memory_path else None
    closes: dict[str, set[str]] = {}
    audit: list[dict] = []
    asked = 0
    try:
        for ending, value in pairs[:MAX_ASKS]:
            asked += 1
            reply = judge(prompt(ending, value, words))
            if isinstance(reply, dict) and reply.get("out_of_date") is True:
                closes.setdefault(ending.id, set()).add(value.id)
                audit.append({"action": "value_ended_by", "claim": value.id, "by": ending.id})
    except Exception as exc:  # noqa: BLE001 - no answer means the value stays open, as before this step
        logger.info(f"value ended: a call failed ({type(exc).__name__}); the rest of the batch keeps its values")
    logger.info(f"value ended: {asked} value(s) asked, {len(audit)} ended")
    return closes, audit
