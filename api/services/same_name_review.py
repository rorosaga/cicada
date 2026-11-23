"""The second look at two people who share a first name: a page that holds two, two held in doubt (2026-11-23).

`same_name_people.plan` places the conversations of one batch and never changes a page that exists. When its re-read
shows that a person on record may be two people, or that two people held apart in doubt may be one, it only flags the
name. This module is the pure half of what acts on the flag (`same_name_tend` is the disk half): a stronger model reads
the whole record of the people involved, conversation by conversation, and answers only when what it copies from the
descriptions is there.

* :func:`holds_two`: one page's conversations, read together. Two people only on a located contrast between two groups of
  its conversations (:func:`same_name_people.read`, the same bar as a new person: two facts that cannot both be true,
  copied word for word); never on a doubt. The answer says which conversations leave and the facts that justify it.
* :func:`settle_pair`: two people held in doubt. **Different** on a located contrast (kept apart for good); **the same**
  only with a located link (a fact each side states that is the same fact, or one that continues the other), which
  `same_name_tend` acts on when a second read agrees (owner 2026-11-23: Cicada joins them itself; ruling 74a).
  Otherwise they stay in doubt, and a plain "cannot tell" says how it reads (``leaning``): like two people (they wait
  apart and nobody is asked), like one, or neither. A judge that fails, answers unreadably or quotes words that are
  not there has read nothing (``answered`` false): the doubt stays where it was and nothing is asked on the strength
  of it.

Engine-free apart from the injected ``judge(system, prompt)``.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from loguru import logger

from api.services import engine_errors, same_name_people as snp

Judge = Callable[[str, str], Awaitable[object]]

#: Conversations of each person one pair call reads, newest first; the rest are left out of the call, never judged.
MAX_PER_SIDE = 10

PAIR_SYSTEM = ("You decide, from the descriptions you are given, whether two people who share a single name are one "
               "real person, two people, or whether the record cannot tell, and you answer in JSON.")

PAIR_PROMPT = """In one person's private conversations, two people are called "{name}" with no surname. The record has kept them apart so far because it could not tell whether they are one person. Everything it holds about each, conversation by conversation, headed by that conversation's date:

PERSON 1
{one}

PERSON 2
{two}

Decide which is true, from what is written and nothing else:
- "same": they are one real person. You must copy, word for word, one fact from each person's descriptions that is the SAME fact (the same employer, place, event, relative, project or detail) or that one continues (one says something changed that the other describes before it). "here" from person 1, "there" from person 2. A different setting, topic or time is not a link, and neither is two things merely being possible for one person.
- "different": they are two people. You must copy, word for word, one fact from each side that cannot both be true of one person at the same time (dates decide: a new job, a move, a promotion, a retirement or a marriage is one person's life moving on, never a contrast; a different generation, or a relationship to the speaker that cannot be held beside the other, is). "here" from person 1, "there" from person 2.
- "cannot_tell": neither. Say it whenever you cannot copy the facts that the other two answers need. Then also say how it reads, as "leaning": "two" when the descriptions read like two different people (different worlds with nothing in common: a relative and a colleague, a child and an adult, a neighbour in one town and someone who works in another), "one" when they read like one person although no single fact is stated on both sides (the same circle, the same work, the same place, one picking up where the other stops), "none" when nothing points either way.
A wrong join tells the person things about someone that are true of another; a wrong split cuts one person's history in two. Do not choose either without the quoted facts.

Answer in JSON only: {{"verdict": "same" | "different" | "cannot_tell", "leaning": "one" | "two" | "none", "here": "words copied from person 1", "there": "words copied from person 2", "reason": "one short sentence"}}
"""


@dataclass(frozen=True)
class Page:
    """A page's account of the person, conversation by conversation (``items``), or blended (one item with every
    conversation)."""

    ref: str
    items: tuple[snp.Item, ...]


@dataclass
class Pair:
    """``verdict``: ``"same"`` (``here``/``there`` the located link), ``"apart"`` (the located contrast), or
    ``"doubt"``; ``called``: a judge was asked; ``answered``: it gave a verdict the code could read and stand on (a
    located link, a located contrast, or a plain "cannot tell"), so "the record was read and does not say" is true."""

    verdict: str = "doubt"
    here: str = ""
    there: str = ""
    called: bool = False
    answered: bool = False
    leaning: str = ""   # for a plain "cannot tell": "one", "two" or "" (nothing points either way)


def _side(page: Page) -> str:
    items = list(page.items)[-MAX_PER_SIDE:]
    return "\n".join(f"- {item.text}" for item in items) or "- (nothing recorded)"


async def settle_pair(name: str, one: Page, two: Page, judge: Judge) -> Pair:
    """Two people held in doubt, read again with everything the record has on each. A pair with nothing on either side
    is not asked. Never raises but for an engine failure (G74(a))."""
    result = Pair()
    if not one.items or not two.items:
        return result
    result.called = True
    prompt = PAIR_PROMPT.format(name=name, one=_side(one), two=_side(two))
    try:
        parsed = await judge(PAIR_SYSTEM, prompt)
    except asyncio.CancelledError:
        raise
    except engine_errors.EngineError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Same-name pair judge failed: {type(e).__name__}")
        return result
    if not isinstance(parsed, dict):
        return result
    verdict = str(parsed.get("verdict") or "").strip().lower().replace(" ", "_")
    one_texts, two_texts = [i.text for i in one.items], [i.text for i in two.items]
    here, there = parsed.get("here"), parsed.get("there")
    if verdict == "cannot_tell":
        result.answered = True   # read, and the record does not say
        leaning = str(parsed.get("leaning") or "").strip().lower()
        result.leaning = leaning if leaning in ("one", "two") else ""
        return result
    if verdict == "different":
        if not snp.quotes_located(here, there, one_texts, two_texts, name):
            return result   # a contrast with no facts to point at is no verdict
        result.verdict = "apart"
    elif verdict == "same":
        # A link is one fact on both sides, so the two quotes may be the same words; each must be there and say more
        # than the name.
        linked = ((snp._located(here, one_texts) and snp._located(there, two_texts))
                  or (snp._located(there, one_texts) and snp._located(here, two_texts)))
        if not (linked and snp._says(here, name) and snp._says(there, name)):
            return result
        result.verdict = "same"
    else:
        return result
    result.answered = True
    result.here, result.there = str(here or ""), str(there or "")
    return result


@dataclass
class Split:
    """A page that holds two people: the conversations that leave it (``episodes``), and the located contrast."""

    page: str
    episodes: frozenset[str] = frozenset()
    here: str = ""
    there: str = ""
    called: bool = False


async def holds_two(name: str, page: Page, judge: Judge) -> Split:
    """One page's conversations read together, the same prompt a batch is judged with and nothing new in it: two groups
    that are different people (a located contrast, `same_name_people.read`) mean the conversations of the smaller group
    leave (the group with more of the page's conversations stays; a tie keeps the one with the earliest). A doubt is no
    split: only a contrast moves content. A page with one conversation, or one the answer calls one person, is not split."""
    result = Split(page.ref)
    identity = snp.Identity("page", page.ref, True, "", frozenset(e for i in page.items for e in i.episodes), page.items)
    if len(page.items) < 2:
        return result
    entries = snp.entries_for([], [identity])
    if len(entries) < 2:
        return result
    result.called = True
    try:
        parsed = await judge(snp.SYSTEM, snp.build_prompt(name, entries, [identity]))
    except asyncio.CancelledError:
        raise
    except engine_errors.EngineError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Same-name page judge failed: {type(e).__name__}")
        return result
    reading = snp.read(parsed, entries, name)
    if reading is None or reading.single:
        return result
    apart = {key: found for key, found in reading.relation.items() if found[0] == "apart"}
    if not apart:
        return result
    sizes: dict[int, int] = {}
    earliest: dict[int, str] = {}
    for e in entries:
        c = reading.cluster_of.get(e.letter)
        if c is not None:
            sizes[c] = sizes.get(c, 0) + 1
            day = (re.match(r"\((\d{4}-\d{2}-\d{2})\)", e.text) or [None, "9999"])[1]
            earliest[c] = min(earliest.get(c, day), day)
    # The group that stays: most conversations, then the one whose conversations begin earliest.
    stay = min(sizes, key=lambda c: (-sizes[c], earliest[c], c))
    leaving = {c for c in sizes if c != stay and (min(c, stay), max(c, stay)) in apart}
    if not leaving:
        return result
    out = frozenset(ep for e in entries if reading.cluster_of.get(e.letter) in leaving for ep in e.episodes)
    result.episodes = out
    key = next(iter((min(c, stay), max(c, stay)) for c in leaving))
    result.here, result.there = apart[key][1], apart[key][2]
    return result
