"""Two people known only by the same first name are two people (2026-11-23).

Most people in a memory are named by a first name alone, and first names repeat: a friend and a colleague, a cousin and
a client. Stage 2 keyed every mention by its lowercased name, so inside one batch a name could only ever be one thing,
and across batches a mention joined the page titled the same on the name alone. "Marc" the brother-in-law in two family
chats and "Marc" the colleague in three meetings became one page that told an agent the brother-in-law was moving to the
Berlin office. A wrong join is the worst memory error, because nothing downstream can see it.

This module decides, for one bare person name at a time, which of the conversations naming it are the same person. It is
the pure half (no model, no disk): :func:`plan` takes the conversations, the people already on record under that name
(a page, or a held line waiting below the promotion bar) and a ``judge`` the caller injects, and says where each
conversation goes. `entity_resolver` asks, then gives the other people pages and lines of their own (ids ``marc-2``, ``marc-3``,
the same clean title: G227's ``_another_id``) and pins each conversation's edges and claims to the right one.

The rule is positive evidence only. A different setting, topic or time says nothing about who a person is; a person is
met at home, at work, on a trip. Two conversations are two people only when the descriptions give each a fact the other
cannot share (a different trade or employer, a different home town, a different generation). Anything else, a thin
description, a judge that fails or answers unreadably, is the old behaviour: the name stays one person. Nothing is
asked of the person: a split is a plain decision the next conversation can see on the pages, and the person's own
"these are one" (a merge) stands as it always did.

Bound: one judge call per bare name that has something to compare, at most :data:`MAX_NAMES` names a batch, and
:data:`MAX_MENTIONS` conversations and :data:`MAX_IDENTITIES` known people in a call; what is over is left as it was.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable

from loguru import logger

from api.services import engine_errors

#: Names judged in one batch, those with the most conversations first. A batch over the cap keeps the old behaviour for
#: the rest.
MAX_NAMES = 20
#: Conversations one call compares, and known people it is shown.
MAX_MENTIONS = 12
MAX_IDENTITIES = 6
#: What of one conversation's description, and of a known person's, the judge reads.
TEXT_CHARS = 600
IDENTITY_CHARS = 900
#: Words of description each side of a split needs: a description that says one thing has nothing to contradict.
MIN_WORDS = 15

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

SYSTEM = ("You decide, from the descriptions you are given, whether conversations that name someone by the same single "
          "name are about one real person or about several, and you answer in JSON.")

PROMPT = """In one person's private conversations, someone is called "{name}" with no surname. Several conversations name a "{name}". Decide which of them are the same real person.
{known}
CONVERSATIONS (each is what that one conversation says about the "{name}" it names)
{conversations}
Rules:
- A wrong join is a serious memory error: it tells the person things about someone that are true of another. A wrong split is an error too. Decide only from what the descriptions say.
- Put two conversations in different groups ONLY when the descriptions give each person a fact the other cannot share: a different trade or employer, a different home town or country, a different generation, a relationship one person cannot hold to the speaker. Name that contrast in "reason".
- A different setting, topic or time is NOT a difference: one person is met at home, at work, on a trip, at a race, and a description that only mentions its setting says nothing about who they are. People also change: a promotion, a new job, a move, a new role in the speaker's life. A description that says less than another, or says something else about the same person, is no contradiction. When a description is thin, or everything said could be true of one person, they are the same person.
- A conversation that fits a known person goes with them ("same_as": that person's number). A conversation that fits none of them is a person not on record yet ("same_as": null); conversations that fit each other go in one group.

Answer in JSON only, every conversation in exactly one group:
{{"people": [{{"conversations": ["A", "C"], "same_as": 1, "reason": "one short sentence"}}]}}
"""


@dataclass(frozen=True)
class Mention:
    """One conversation's own account of the person it calls by the name."""

    episode: str
    text: str


@dataclass(frozen=True)
class Identity:
    """A person already on record under the name: a page (``kind="page"``, ``ref`` its id) or a line held below the
    promotion bar (``kind="line"``, ``ref`` its name). ``plain`` is the one the bare name itself reaches: the page whose
    id is the name's slug, or the line named so."""

    kind: str
    ref: str
    plain: bool
    text: str
    episodes: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Destination:
    """Where a conversation's mention goes when it is not the plain one: a known ``page`` (``ref`` its id), a known
    ``line`` (``ref`` its name) or a person not on record yet (``new``; ``ref`` a label the conversations of one new
    person share)."""

    kind: str
    ref: str


@dataclass
class Plan:
    """One name's decision: ``moves`` maps a conversation (episode id) to where it goes; a conversation not in it stays
    with the plain name, as before. ``called`` says a judge was asked."""

    moves: dict[str, Destination] = field(default_factory=dict)
    called: bool = False
    thin: int = 0   # people the grouping would have made new, kept with the plain name for want of a description


def is_bare(name: str) -> bool:
    """A name with one word and nothing else in it: the only kind two people can share without anyone noticing. A
    full name two people share is rare and its surname is evidence; a bare name carries none."""
    words = str(name or "").split()
    return len(words) == 1 and len(words[0]) >= 2 and not re.search(r"[\d@/:()]", words[0])


def describe(entity: dict) -> str:
    """What one extraction says about its person: its summary and its first facts, cut, dated when the conversation is."""
    summary = str(entity.get("summary") or entity.get("description") or "").strip()
    facts = [str(f).strip() for f in (entity.get("key_facts") or [])[:4] if str(f).strip()]
    text = " ".join(summary.split())
    if facts:
        text = (text + " Facts: " + "; ".join(" ".join(f.split()) for f in facts)).strip()
    day = str(entity.get("source_episode_timestamp") or "")[:10]
    return (f"({day}) {text}" if day and text else text)[:TEXT_CHARS]


def words(text: str) -> int:
    """How many words a description says, its date aside."""
    return len(re.sub(r"^\(\d{4}-\d{2}-\d{2}\)\s*", "", str(text or "")).split())


def _known_block(identities: list[Identity]) -> str:
    if not identities:
        return "\nNo one called that is on record yet.\n"
    rows = "\n".join(f"[{i}] {identity.text[:IDENTITY_CHARS] or '(nothing recorded)'}" for i, identity in enumerate(identities, 1))
    return f"\nKNOWN PEOPLE with this name (each one person, from earlier conversations)\n{rows}\n"


def build_prompt(name: str, mentions: list[Mention], identities: list[Identity]) -> str:
    rows = "\n".join(f"({_LETTERS[i]}) {mention.text}" for i, mention in enumerate(mentions))
    return PROMPT.format(name=name, known=_known_block(identities), conversations=rows)


def read(parsed: object, mentions: list[Mention], identities: list[Identity]) -> dict[str, tuple[str, str]] | None:
    """The judge's groups as ``{episode: ("known", index) | ("new", group)}``; ``None`` for an answer that does not
    line up (never a guess: the caller keeps the old behaviour). A conversation the answer leaves out, or lists twice
    beyond its first group, is not assigned. A group that is a person not on record yet must state the contrast
    that makes it one; one that does not makes the whole answer unreadable."""
    groups = parsed.get("people") if isinstance(parsed, dict) else None
    if not isinstance(groups, list) or not groups:
        return None
    out: dict[str, tuple[str, str]] = {}
    for g, group in enumerate(groups):
        if not isinstance(group, dict):
            return None
        letters = [str(x).strip().strip("()").upper() for x in group.get("conversations") or []]
        same_as = group.get("same_as")
        known = None
        if isinstance(same_as, bool):
            same_as = None
        if isinstance(same_as, (int, str)) and str(same_as).strip().isdigit():
            number = int(str(same_as).strip())
            if not 1 <= number <= len(identities):
                return None
            known = number - 1
        reason = str(group.get("reason") or "").strip()
        if known is None and not reason:
            return None
        for letter in letters:
            index = _LETTERS.find(letter) if len(letter) == 1 else -1
            if not 0 <= index < len(mentions):
                continue
            episode = mentions[index].episode
            if episode in out:
                continue
            if known is not None:
                out[episode] = ("known", str(known))
            else:
                out[episode] = ("new", f"g{g}")
    return out


def decide(assigned: dict[str, tuple[str, str]], identities: list[Identity],
           first_seen: dict[str, int]) -> dict[str, Destination]:
    """``assigned`` (:func:`read`) → where each conversation that is not the plain person goes.

    A conversation judged the same as the plain identity, or that the judge left out, stays. With no plain identity on
    record, the new group with the most conversations (the earliest on a tie) is the plain person; the others are
    people of their own."""
    plain = any(identity.plain for identity in identities)
    news: dict[str, list[str]] = {}
    moves: dict[str, Destination] = {}
    for episode, (kind, ref) in assigned.items():
        if kind == "known":
            identity = identities[int(ref)]
            if not identity.plain:
                moves[episode] = Destination(identity.kind, identity.ref)
        else:
            news.setdefault(ref, []).append(episode)
    if news:
        ranked = sorted(news.items(), key=lambda item: (-len(item[1]), min(first_seen.get(e, 0) for e in item[1])))
        for position, (label, episodes) in enumerate(ranked):
            if position == 0 and not plain:
                continue   # the plain person, with nothing on record to say otherwise
            for episode in episodes:
                moves[episode] = Destination("new", label)
    return moves


async def plan(name: str, mentions: list[Mention], identities: list[Identity],
               judge: Callable[[str, str], Awaitable[object]]) -> Plan:
    """Decide one name. ``judge(system, prompt)`` answers the parsed JSON (an injected, engine-free seam); a failure or
    an answer that does not line up is the old behaviour — one person."""
    result = Plan()
    shown = list(identities[:MAX_IDENTITIES])
    judged = [m for m in mentions[:MAX_MENTIONS]]
    if not judged or (len(judged) < 2 and not shown):
        return result
    result.called = True
    prompt = build_prompt(name, judged, shown)
    try:
        parsed = await judge(SYSTEM, prompt)
    except asyncio.CancelledError:
        raise
    except engine_errors.EngineError:
        raise   # G74(a): an engine failure is never a model's answer
    except Exception as e:  # noqa: BLE001 - anything else is "one person"
        logger.debug(f"Same-name judge failed: {type(e).__name__}")
        return result
    assigned = read(parsed, judged, shown)
    if assigned is None:
        return result
    moves = decide(assigned, shown, {m.episode: i for i, m in enumerate(judged)})
    # A split is a claim that two descriptions give one person facts the other cannot share, and a description that
    # says one thing (a person who "put in a word", a "colleague") has nothing to contradict: the model reads a thin
    # description as a different person when a later, richer one says more. Each person the grouping would make new
    # needs a description of at least MIN_WORDS words on both sides (the plain person's, and their own); one that has
    # less goes back to the plain name.
    text_of = {m.episode: m.text for m in judged}
    plain_text = next((i.text for i in shown if i.plain), "")
    if not plain_text:
        plain_text = " ".join(text_of[e] for e in assigned if e not in moves and e in text_of)
    news: dict[str, list[str]] = {}
    for episode, destination in moves.items():
        if destination.kind == "new":
            news.setdefault(destination.ref, []).append(episode)
    for episodes in news.values():
        if words(plain_text) < MIN_WORDS or words(" ".join(text_of[e] for e in episodes)) < MIN_WORDS:
            result.thin += 1
            for episode in episodes:
                del moves[episode]
    result.moves = moves
    return result


def identity_for_episode(episode: str, identities: Iterable[Identity]) -> Identity | None:
    """The one known person whose conversations already include ``episode`` (a conversation read again is the person it
    was); ``None`` when none does, or two do."""
    holders = [identity for identity in identities if episode in identity.episodes]
    return holders[0] if len(holders) == 1 else None


def free_id(name_slug: str, taken: set[str]) -> str:
    """``<slug>-2``, ``-3`` … the first not in ``taken`` (G227's ``_another_id``, which a page of the same title gets)."""
    n = 2
    while f"{name_slug}-{n}" in taken:
        n += 1
    return f"{name_slug}-{n}"
