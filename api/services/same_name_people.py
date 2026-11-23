"""Two people known only by the same first name: told apart when the record can, held in doubt when it cannot
(2026-11-23).

Most people in a memory are named by a first name alone, and first names repeat: a friend and a colleague, a cousin and
a client. Stage 2 keyed every mention by its lowercased name, so inside one batch a name could only ever be one thing,
and across batches a mention joined the page titled the same on the name alone. "Marc" the brother-in-law in two family
chats and "Marc" the colleague in three meetings became one page that told an agent the brother-in-law was moving to the
Berlin office. A wrong join is the worst memory error, because nothing downstream can see it.

This module is the pure half (no model, no disk). For one bare person name it reads what the record says about every
conversation that names it, **each conversation on its own** (a person already on record is shown conversation by
conversation, not as one blended summary, which after a wrong join is a mixture of two people), and answers three things
about any two of them:

* **the same person**, the default: a different setting, topic or time says nothing about who a person is; a person is
  met at home, at work, on a trip; and a life moves on (a new job, a move, a promotion, a retirement), the same person
  later, never another;
* **two people**, only when the conversations state something that cannot be true of one person at the same time, and the
  judge copies the two facts from the descriptions (`_located`: words that occur in none are no contrast, the first
  version of this rule split one real person whose life had moved on in 13% of replayed calls);
* **cannot tell** (a *doubt*), when the descriptions are of two different kinds of person (a relative and a colleague,
  a child and an adult) and nothing says both could not be one person and nothing connects them: the judge copies the
  two facts that make them look like two, and the code checks they are there. A doubt is a state the record holds, not
  a guess made as "same": the mention waits on a person of its own (never blended into the other's page) until a later
  conversation settles it, and only after the whole record has been read and cannot settle it is it asked (`same_name_tend`).

`plan` places the mentions of one batch. A mention that fits a person on record goes to that person; one that contrasts
goes to a person of its own (``<slug>-2``, the same clean title: G227's ``_another_id``), as does one in doubt, with the
pair recorded as a doubt and not as a split. It never changes a page that exists: when the re-read shows that a page
already holds two people, or that two people in doubt are one, it only *flags the name for review* (`same_name_tend`),
which acts once the batch has committed, on located facts, as one undoable commit.

Anything else (a thin description, a judge that fails or answers unreadably, a pair with no located quote) is the old
behaviour: the name stays one person, and nothing is asked.

Bound: one judge call per bare name that has something to compare, at most :data:`MAX_NAMES` names a batch, and
:data:`MAX_ENTRIES` descriptions in a call; what is over is left as it was.
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
#: Conversations of this batch one call compares, and known people it is shown.
MAX_MENTIONS = 10
MAX_IDENTITIES = 6
#: Descriptions in one call, new and filed together (a letter each).
MAX_ENTRIES = 20
#: What of one conversation's description reads, and of a known person's single blended text.
TEXT_CHARS = 600
IDENTITY_CHARS = 900
#: Words of description each side of a split needs: a description that says one thing has nothing to contradict.
MIN_WORDS = 15
#: Letters a quoted contrast needs, taken together: "a colleague" says something, "is" does not.
MIN_QUOTE_CHARS = 6

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

SYSTEM = ("You decide, from the descriptions you are given, whether conversations that name someone by the same single "
          "name are about one real person or about several, and you answer in JSON.")

PROMPT = """In one person's private conversations, someone is called "{name}" with no surname. Several conversations name a "{name}". Decide which of them are the same real person, which are different people, and where you cannot tell.
{filed}
{new}
Rules:
- A wrong join is a serious memory error: it tells the person things about someone that are true of another. A wrong split is just as serious: one person's history is cut in two, and the part nobody sees is lost. Decide only from what the descriptions say.
- People change. A new job or employer, a promotion, a move to another city or country, a graduation, a retirement, a marriage, a baby, a new home: the same person says different things about their work or home in a later conversation than in an earlier one. A later description that differs from an earlier one is that person's life moving on, NOT a different person. Dates matter: ask whether the later description could be the same person after an ordinary change since the earlier one. If it could, they are the same person.
- "different" ONLY when two descriptions state something that cannot be true of one person at the same time. Dates decide. Descriptions dated within a few weeks of each other describe the person at the same moment: if they give different jobs or employers, or different home towns or countries, and neither says that something changed, they are two people (one person does not have two employers and two home towns in the same month). Descriptions months or years apart may be one person after an ordinary change, and a description that itself says something changed (a new job, a move, a promotion, a retirement) is a change, not a second person. Two more things one person cannot be: of a different generation (a nine-year-old and a retired person), and held in a relationship to the speaker that cannot be held beside the other (a grandmother and an intern). A description that is silent about something says nothing about it: a person with no job on record may well have one.
- "cannot_tell" when the descriptions point to two different kinds of person: one is the speaker's relative and the other the speaker's colleague, friend or neighbour; one is a child and the other an adult; one is a tradesperson in one town and the other works in an office somewhere else. Use it even though one person could, in theory, be both: what matters is that the descriptions name different worlds and nothing connects them, no shared employer, place, event, person or detail, and no statement that something changed. Every conversation is the speaker's own, so the speaker appearing in two descriptions, or being named in both, connects nothing. Do not use it when the descriptions share a fact, when one says something changed, when a description is thin, or for a different setting, topic or time.
- A different setting, topic or time is NOT a difference: one person is met at home, at work, on a trip, at a race. When a description is thin, or everything said could be true of one person, they are the same person. When unsure between "the same person" and "different", say "same".
- Conversations that fit each other go in one group; every conversation is in exactly one group. Several groups are several people. For every two groups, say how they stand: "different" or "cannot_tell", and copy, word for word, "here" from a description in one group and "there" from a description in the other: for "different" the two facts that cannot both be true of one person, for "cannot_tell" the two facts that make them look like two different people. Quotes you cannot copy from the descriptions are no answer: put the conversations in one group. Two groups you give no entry for are the same person.

Answer in JSON only:
{{"people": [{{"conversations": ["A", "C"], "reason": "one short sentence"}}, {{"conversations": ["B"], "reason": "one short sentence"}}], "pairs": [{{"people": [1, 2], "verdict": "different", "here": "words copied from a description in group 1", "there": "words copied from a description in group 2", "reason": "one short sentence"}}]}}
"""


@dataclass(frozen=True)
class Mention:
    """One conversation's own account of the person it calls by the name."""

    episode: str
    text: str


@dataclass(frozen=True)
class Item:
    """What one earlier conversation said about a person on record: ``episodes`` are the conversations the text covers
    (one for a page read conversation by conversation; every one for a person only a blended text is kept for)."""

    text: str
    episodes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Identity:
    """A person already on record under the name: a page (``kind="page"``, ``ref`` its id) or a line held below the
    promotion bar (``kind="line"``, ``ref`` its name). ``plain`` is the one the bare name itself reaches: the page whose
    id is the name's slug, or the line named so. ``items`` are what each of its conversations says (empty: ``text`` is
    all there is). ``doubt_with`` are the refs of the people Sleep holds in doubt against this one."""

    kind: str
    ref: str
    plain: bool
    text: str
    episodes: frozenset[str] = frozenset()
    items: tuple[Item, ...] = ()
    doubt_with: frozenset[str] = frozenset()

    def shown(self) -> tuple[Item, ...]:
        return self.items or ((Item(self.text[:IDENTITY_CHARS] or "(nothing recorded)", tuple(sorted(self.episodes))),))


@dataclass(frozen=True)
class Destination:
    """Where a conversation's mention goes when it is not the plain one: a known ``page`` (``ref`` its id), a known
    ``line`` (``ref`` its name) or a person not on record yet (``new``; ``ref`` a label the conversations of one new
    person share). ``doubt``: that person is held in doubt against the others, not decided to be another person."""

    kind: str
    ref: str
    doubt: bool = False


@dataclass
class Plan:
    """One name's decision: ``moves`` maps a conversation (episode id) to where it goes; a conversation not in it stays
    with the plain name, as before. ``called`` says a judge was asked. ``review``: the re-read found something only a
    review of the pages can act on (a page that holds two people, two people in doubt that look like one, a doubt).
    ``review_reasons`` names which, for the log."""

    moves: dict[str, Destination] = field(default_factory=dict)
    called: bool = False
    thin: int = 0   # people the grouping would have made new, kept with the plain name for want of a description
    review: bool = False
    review_reasons: list[str] = field(default_factory=list)
    second: bool = False   # the main model read it again
    review_pages: set[str] = field(default_factory=set)             # pages that may hold two people
    review_pairs: set[tuple[str, str]] = field(default_factory=set)  # people in doubt that may be one


@dataclass(frozen=True)
class Entry:
    """One lettered description in a call: ``identity`` the index of the known person it is filed under, ``None`` for a
    conversation of this batch."""

    letter: str
    text: str
    identity: int | None
    episodes: tuple[str, ...]


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


# ---------------------------------------------------------------- the call


def entries_for(mentions: list[Mention], identities: list[Identity]) -> list[Entry]:
    """The lettered descriptions of one call: this batch's conversations first, then what each known person's own
    conversations say, newest first and in turn between the people, until :data:`MAX_ENTRIES`. A known person with
    nothing but a blended text is one description."""
    out: list[Entry] = []
    for m in mentions[:MAX_MENTIONS]:
        out.append(Entry(_LETTERS[len(out)], m.text, None, (m.episode,)))
    pools = [list(reversed(identity.shown())) for identity in identities]
    turn = 0
    while len(out) < MAX_ENTRIES and any(pools):
        for k, pool in enumerate(pools):
            if pool and len(out) < MAX_ENTRIES:
                item = pool.pop(0)
                out.append(Entry(_LETTERS[len(out)], item.text, k, item.episodes))
        turn += 1
    return out


def _by_date(entries: list[Entry]) -> list[Entry]:
    return sorted(entries, key=lambda e: (re.match(r"\((\d{4}-\d{2}-\d{2})\)", e.text) or [None, "~"])[1] if e.text else "~")


def build_prompt(name: str, entries: list[Entry], identities: list[Identity]) -> str:
    filed = ""
    if identities:
        blocks = []
        for k, identity in enumerate(identities):
            rows = "\n".join(f"  ({e.letter}) {e.text}" for e in _by_date([e for e in entries if e.identity == k]))
            blocks.append(f"[person {k + 1}]\n{rows or '  (nothing recorded)'}")
        filed = ("\nCONVERSATIONS FILED UNDER PEOPLE ALREADY ON RECORD (each person is shown by what each of their "
                 "conversations says, headed by its date; they may have been filed together wrongly)\n"
                 + "\n".join(blocks) + "\n")
    fresh = [e for e in entries if e.identity is None]
    new = ""
    if fresh:
        new = "\nNEW CONVERSATIONS (not filed under anyone yet)\n" + "\n".join(f"({e.letter}) {e.text}" for e in fresh) + "\n"
    return PROMPT.format(name=name, filed=filed, new=new)


# ---------------------------------------------------------------- reading the answer


def _squash(text: object) -> str:
    """A quote or a description compared on its words alone: case, runs of space, edge quotes and punctuation aside."""
    return re.sub(r"\s+", " ", str(text or "")).strip().strip("\"'`“”‘’«».,;:!? ").lower()


def _located(quote: object, texts: list[str]) -> bool:
    """The quote occurs word for word in one of the texts (never fuzzy, as the evidence spans are not), and says
    something: a few letters occur anywhere. An ellipsis joins pieces, each of which must occur."""
    pieces = [_squash(p) for p in re.split(r"\.{3}|…", str(quote or ""))]
    pieces = [p for p in pieces if p]
    if not pieces or sum(len(p) for p in pieces) < MIN_QUOTE_CHARS:
        return False
    haystack = [_squash(t) for t in texts]
    return all(any(p in h for h in haystack) for p in pieces)


def _says(quote: object, name: str) -> bool:
    """The quote says something beyond the name itself: "Marc is" names a person and states nothing about them."""
    rest = _squash(quote)
    for word in _squash(name).split():
        rest = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", " ", rest)
    return len(re.sub(r"[\W_]+", "", rest)) >= MIN_QUOTE_CHARS


def quotes_located(here: object, there: object, ours: list[str], theirs: list[str], name: str = "") -> bool:
    """Two quoted facts that set two groups of descriptions against each other: each occurs word for word in its own
    group's descriptions and in none of the other's (a fact both groups state sets nothing against anything, and a page
    read conversation by conversation lists a belief two conversations share under both), the two are not the same
    words, and each says something beyond the name. Either way round."""
    if _squash(here) == _squash(there) or not (_says(here, name) and _says(there, name)):
        return False

    def one_way(a: object, b: object) -> bool:
        return (_located(a, ours) and _located(b, theirs)
                and not _located(a, theirs) and not _located(b, ours))

    return one_way(here, there) or one_way(there, here)


@dataclass
class Reading:
    """The judge's answer as located people. ``cluster_of``: letter → person (0…). ``relation``: ``(a, b)`` with
    ``a < b`` → ``("apart" | "doubt", here, there)``, the located quotes; a pair with no relation is one person (the
    answer made them one, or its quotes were not there). ``single``: everything is one person."""

    cluster_of: dict[str, int]
    relation: dict[tuple[int, int], tuple[str, str, str]] = field(default_factory=dict)

    @property
    def single(self) -> bool:
        return len(set(self.cluster_of.values())) <= 1

    def members(self, cluster: int) -> list[str]:
        return [letter for letter, c in self.cluster_of.items() if c == cluster]


_VERDICTS = {"different": "apart", "cannot_tell": "doubt", "cannot tell": "doubt", "unsure": "doubt"}


def read(parsed: object, entries: list[Entry], name: str = "") -> Reading | None:
    """The judge's groups and verdicts → a :class:`Reading`; ``None`` for an answer that does not line up (never a guess:
    the caller keeps the old behaviour). A letter the answer leaves out, or lists twice, is the first group's or none. A
    verdict whose quotes are not located (`quotes_located`: here in one group's descriptions and not the other's, there
    in the other's and not the first's, either way round, two different facts, each more than the name) is no verdict:
    the two groups are one person. A group pair given one verdict and another is read as the milder."""
    groups = parsed.get("people") if isinstance(parsed, dict) else None
    if not isinstance(groups, list) or not groups:
        return None
    by_letter = {e.letter: e for e in entries}
    group_of: dict[str, int] = {}
    members: list[list[str]] = []
    for g, group in enumerate(groups):
        if not isinstance(group, dict):
            return None
        letters = [str(x).strip().strip("()").upper() for x in group.get("conversations") or []]
        own = [x for x in letters if x in by_letter and x not in group_of]
        for x in own:
            group_of[x] = g
        members.append(own)
    if not group_of:
        return None
    pairs = parsed.get("pairs")
    texts = {g: [by_letter[x].text for x in letters] for g, letters in enumerate(members)}
    verdicts: dict[tuple[int, int], tuple[str, str, str]] = {}
    for row in pairs if isinstance(pairs, list) else []:
        if not isinstance(row, dict):
            continue
        ends = row.get("people")
        if not (isinstance(ends, list) and len(ends) == 2):
            continue
        try:
            a, b = int(ends[0]) - 1, int(ends[1]) - 1
        except (TypeError, ValueError):
            continue
        verdict = _VERDICTS.get(str(row.get("verdict") or "").strip().lower())
        if verdict is None or a == b or not (0 <= a < len(members) and 0 <= b < len(members)):
            continue
        if not members[a] or not members[b]:
            continue
        here, there = row.get("here"), row.get("there")
        if not quotes_located(here, there, texts[a], texts[b], name):
            continue
        key = (min(a, b), max(a, b))
        if key in verdicts and verdicts[key][0] == "doubt":
            continue   # the milder reading stands
        verdicts[key] = (verdict, str(here or ""), str(there or ""))
    live = [g for g, letters in enumerate(members) if letters]
    parent = {g: g for g in live}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(live):
        for b in live[i + 1:]:
            if (a, b) not in verdicts:
                parent[find(a)] = find(b)   # no verdict, or an unlocated one: one person
    if any(find(a) == find(b) for (a, b) in verdicts):
        # The answer calls two groups different and joins them through a third: incoherent, so nothing is split.
        return Reading({x: 0 for x in group_of})
    roots = sorted({find(g) for g in live}, key=lambda r: min(live.index(g) for g in live if find(g) == r))
    number = {r: i for i, r in enumerate(roots)}
    relation: dict[tuple[int, int], tuple[str, str, str]] = {}
    for (a, b), found in verdicts.items():
        key = tuple(sorted((number[find(a)], number[find(b)])))
        if key not in relation or (found[0] == "apart" and relation[key][0] == "doubt"):
            relation[key] = found
    return Reading({x: number[find(g)] for x, g in group_of.items()}, relation)


# ---------------------------------------------------------------- placing the batch


def decide(reading: Reading, entries: list[Entry], identities: list[Identity],
           first_seen: dict[str, int]) -> tuple[dict[str, Destination], Plan]:
    """The reading → where each new conversation goes, and what the re-read says about the people already on record.

    A new conversation in a group that holds a person's filed conversations goes to that person (the plain one if the
    group holds it, else the one with the most there). A new group no one on record is in is a person not on record
    yet: held apart on a contrast, in doubt otherwise. With no plain person on record, the new group with the most
    conversations is the plain person; the others are people of their own. A known person's conversations in two groups
    that are different people is a page that holds two people; two people in doubt in one group are one person who was
    doubted: neither is touched here, the name is flagged for `same_name_tend`."""
    flags = Plan()
    moves: dict[str, Destination] = {}
    clusters = sorted(set(reading.cluster_of.values()))
    filed_of: dict[int, dict[int, int]] = {c: {} for c in clusters}   # cluster -> {identity: its filed entries there}
    for e in entries:
        if e.identity is not None and e.letter in reading.cluster_of:
            counts = filed_of[reading.cluster_of[e.letter]]
            counts[e.identity] = counts.get(e.identity, 0) + 1
    # What the re-read says about people already on record.
    for k, identity in enumerate(identities):
        there = sorted(c for c in clusters if k in filed_of[c])
        for i, a in enumerate(there):
            for b in there[i + 1:]:
                relation = reading.relation.get((a, b))
                if relation is not None:   # a contrast, or only a doubt: the stronger reading of the second look decides
                    flags.review = True
                    flags.review_reasons.append("page-holds-two-people")
                    if identity.kind == "page":
                        flags.review_pages.add(identity.ref)
    for a in clusters:
        for b in clusters:
            if a < b:
                for ka in filed_of[a]:
                    for kb in filed_of[b]:
                        relation = reading.relation.get((a, b))
                        if ka != kb and relation is not None and relation[0] == "doubt":
                            flags.review = True
                            flags.review_reasons.append("doubt-held")
                            flags.review_pairs.add(tuple(sorted((identities[ka].ref, identities[kb].ref))))
    for c in clusters:
        held = filed_of[c]
        for kx in held:
            for ky in held:
                if kx < ky and identities[ky].ref in identities[kx].doubt_with:
                    flags.review = True
                    flags.review_reasons.append("doubt-may-be-one")
                    flags.review_pairs.add(tuple(sorted((identities[kx].ref, identities[ky].ref))))
    plain = any(identity.plain for identity in identities)
    fresh_clusters: dict[int, list[str]] = {}
    for e in entries:
        if e.identity is not None or e.letter not in reading.cluster_of:
            continue
        episode = e.episodes[0]
        c = reading.cluster_of[e.letter]
        held = filed_of[c]
        if held:
            home = max(held, key=lambda k: (identities[k].plain, held[k], -k))
            identity = identities[home]
            if not identity.plain:
                moves[episode] = Destination(identity.kind, identity.ref)
        else:
            fresh_clusters.setdefault(c, []).append(episode)
    if fresh_clusters:
        ranked = sorted(fresh_clusters.items(), key=lambda item: (-len(item[1]), min(first_seen.get(e, 0) for e in item[1])))
        for position, (c, episodes) in enumerate(ranked):
            if position == 0 and not plain:
                continue   # the plain person, with nothing on record to say otherwise
            kinds = {reading.relation[key][0] for key in reading.relation if c in key}
            doubt = "apart" not in kinds
            for episode in episodes:
                moves[episode] = Destination("new", f"g{c}", doubt)
            if doubt:
                flags.review = True
                flags.review_reasons.append("doubt-held")
    return moves, flags


#: A person on record with this many filed conversations or more has a history a small judge can regroup wrongly (a conversation
#: of the page that belongs with the new mention left behind with the rest): a split decided against it is read again.
CONFIRM_ITEMS = 3


async def plan(name: str, mentions: list[Mention], identities: list[Identity],
               judge: Callable[[str, str], Awaitable[object]],
               strong: Callable[[str, str], Awaitable[object]] | None = None) -> Plan:
    """Decide one name. ``judge(system, prompt)`` answers the parsed JSON (an injected, engine-free seam); a failure or
    an answer that does not line up is the old behaviour: one person.

    ``strong`` is the engine's main model: when the small judge calls two or more of this batch's conversations one person, or
    divides them against a person on record with :data:`CONFIRM_ITEMS` or more filed conversations, the same prompt is put to it once and its
    grouping replaces the small judge's when it divides them. Its answer being unreadable, failing, or calling it one
    person leaves the small judge's reading."""
    result = Plan()
    shown = list(identities[:MAX_IDENTITIES])
    judged = [m for m in mentions[:MAX_MENTIONS]]
    if not judged or (len(judged) < 2 and not shown):
        return result
    result.called = True
    entries = entries_for(judged, shown)
    prompt = build_prompt(name, entries, shown)
    try:
        parsed = await judge(SYSTEM, prompt)
    except asyncio.CancelledError:
        raise
    except engine_errors.EngineError:
        raise   # G74(a): an engine failure is never a model's answer
    except Exception as e:  # noqa: BLE001 - anything else is "one person"
        logger.debug(f"Same-name judge failed: {type(e).__name__}")
        return result
    reading = read(parsed, entries, name)
    if reading is None:
        return result
    # The small judge says several of this batch's conversations are one person (the common answer, and where a silent join hides: it reads "both are connected to the
    # speaker" or "a later move" as a link), or divides the conversations against a person with a long history on record:
    # the main model reads the same prompt once and its grouping replaces the small judge's when it divides them. Its answer
    # failing, unreadable, or calling it one person leaves the small judge's reading: a located split is never lost to it.
    if strong is not None and ((reading.single and len(judged) >= 2)
                               or any(len(i.shown()) >= CONFIRM_ITEMS for i in shown) and not reading.single):
        try:
            second = read(await strong(SYSTEM, prompt), entries, name)
        except asyncio.CancelledError:
            raise
        except engine_errors.EngineError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Same-name second reading failed: {type(e).__name__}")
            second = None
        result.second = True
        if second is not None and not second.single:
            reading = second
    if reading.single:
        return result
    moves, flags = decide(reading, entries, shown, {m.episode: i for i, m in enumerate(judged)})
    result.review, result.review_reasons = flags.review, flags.review_reasons
    result.review_pages, result.review_pairs = flags.review_pages, flags.review_pairs
    # A split is a claim that two descriptions give one person facts the other cannot share, and a description that
    # says one thing (a person who "put in a word", a "colleague") has nothing to contradict: the model reads a thin
    # description as a different person when a later, richer one says more. Each person the grouping would make new
    # needs a description of at least MIN_WORDS words on both sides (the plain person's, and their own); one that has
    # less goes back to the plain name.
    text_of = {e.episodes[0]: e.text for e in entries if e.identity is None}
    plain_text = " ".join(i.text for i in shown if i.plain) or " ".join(
        text_of[e] for e in text_of if e not in moves)
    news: dict[str, list[str]] = {}
    for episode, destination in moves.items():
        if destination.kind == "new":
            news.setdefault(destination.ref, []).append(episode)
    for episodes in news.values():
        if words(plain_text) < MIN_WORDS or words(" ".join(text_of[e] for e in episodes)) < MIN_WORDS:
            result.thin += 1
            for episode in episodes:
                del moves[episode]
    if not moves and result.thin:
        # The only new person this would have made was thin: no doubt is held for it. What the re-read said about people
        # already on record stands.
        result.review_reasons = [r for r in result.review_reasons if r != "doubt-held" or result.review_pairs]
        result.review = bool(result.review_pages or result.review_pairs)
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
