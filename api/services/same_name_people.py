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
behaviour: the name stays one person, and nothing is asked. Two exceptions, both about one conversation that names the name
twice (2026-11-24): its two people are never one person, and when nothing can say which of them a person on record is,
neither is it (each waits in doubt); and a person written with a qualifier is never left under the name it was written with
(a thin description of one the judge called different is a doubt, not the plain name's).

Bound: one judge call per bare name that has something to compare, at most :data:`MAX_NAMES` names a batch, and
:data:`MAX_ENTRIES` descriptions in a call; what is over is left as it was.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field, replace
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

#: Said when the bank's owner has a name (2026-11-24). The descriptions name the owner ("<owner>'s brother-in-law", "a
#: meeting with <owner>"), and a judge that does not know that name is the speaker's reads it as a third person both
#: descriptions share: two colleagues were joined "through <owner>" in 2 of 17 benchmark runs, by both models. Told only
#: who the speaker is, the judge then discounted the one true link a thin description had (someone who "moved with
#: <owner>" against <owner>'s partner: cut in two in 8 of 30), so the line also says what a tie to the speaker is.
SPEAKER = (' The speaker, the person whose conversations these are, appears in the descriptions as "{speaker}". What '
           'someone is to the speaker (their partner, a relative, the one they live, travel or move with) is a fact '
           'about that someone like any other.')


def speaker_line(speaker: str | None) -> str:
    speaker = " ".join(str(speaker or "").replace('"', "").split())
    return SPEAKER.format(speaker=speaker) if speaker else ""


PROMPT = """In one person's private conversations, someone is called "{name}" with no surname.{speaker} Several conversations name a "{name}": every description below is about someone called "{name}", whether or not it repeats the name. Decide which of them are the same real person, which are different people, and where you cannot tell.
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
    """One conversation's own account of the person it calls by the name. ``episode`` is the mention's key: the
    conversation's id, or, for a person the conversation wrote with a qualifier ("Nico (finance lead)", 2026-11-24),
    ``<id>`` + a separator + the name as written (lower case). ``conversation`` is the real id (``""``: ``episode`` is it) and
    ``qualified`` says the name carried a qualifier; two mentions of one conversation are two people, as the conversation
    itself said. ``no_rename``: a qualified mention whose conversation also names the bare name, which may never take the
    bare name (the two would be told apart by nothing)."""

    episode: str
    text: str
    conversation: str = ""
    qualified: bool = False
    no_rename: bool = False


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
    aliases: frozenset[str] = frozenset()   # lower case: a re-read matches a mention by the name it was written with

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
    #: The other people the same conversation named with this name, as ``(kind, ref, apart)``: ``apart`` says the
    #: conversation told the two apart for good (both written with a qualifier), else the pair is only a doubt. Only
    #: a ``new`` person carries it; the resolver records the pair by it (2026-11-24, not part of equality).
    siblings: tuple[tuple[str, str, bool], ...] = field(default=(), compare=False)


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
    conversation: str = ""
    qualified: bool = False
    no_rename: bool = False


def is_bare(name: str) -> bool:
    """A name with one word and nothing else in it: the only kind two people can share without anyone noticing. A
    full name two people share is rare and its surname is evidence; a bare name carries none."""
    words = str(name or "").split()
    return len(words) == 1 and len(words[0]) >= 2 and not re.search(r"[\d@/:()]", words[0])


def stem_of(name: str) -> tuple[str, str] | None:
    """``("Nico", "finance lead")`` for a person written ``Nico (finance lead)``: a bare name and what tells it apart from
    another person of that name. ``None`` for anything else: a real two-word name, a bare name, a parenthesis that does
    not close at the end or holds another. Structure only, never a word list: Stage 1 writes the qualifier in the
    conversation's own words, in any language (2026-11-24)."""
    m = re.fullmatch(r"\s*(\S+)\s*\(([^()]+)\)\s*", str(name or ""))
    if m is None or not is_bare(m.group(1)):
        return None
    qualifier = " ".join(m.group(2).split())
    return (m.group(1), qualifier) if qualifier else None


def mention_key(episode: str, name: str) -> str:
    """The key of a mention of ``name`` in a conversation: the conversation's id for the bare name, the id and the name
    as written for a qualified one."""
    return episode if is_bare(name) else f"{episode}\x1f{str(name).strip().lower()}"


def split_key(key: str) -> tuple[str, str]:
    """``(conversation id, name as written lower case or "")`` of a mention key."""
    episode, _, name = str(key).partition("\x1f")
    return episode, name


def describe(entity: dict) -> str:
    """What one extraction says about its person: its summary and its first facts, cut, dated when the conversation is.
    A person written with a qualifier (``Nico (finance lead)``) leads with it in brackets: it is what the conversation says
    tells the person from the other of the name, so the judge reads it and the thin-description count includes it
    (2026-11-24)."""
    summary = str(entity.get("summary") or entity.get("description") or "").strip()
    facts = [str(f).strip() for f in (entity.get("key_facts") or [])[:4] if str(f).strip()]
    text = " ".join(summary.split())
    if facts:
        text = (text + " Facts: " + "; ".join(" ".join(f.split()) for f in facts)).strip()
    stem = stem_of(str(entity.get("name") or ""))
    if stem is not None:
        text = f"[{stem[1]}] {text}".strip()
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
        out.append(Entry(_LETTERS[len(out)], m.text, None, (m.episode,), m.conversation or m.episode, m.qualified, m.no_rename))
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


def build_prompt(name: str, entries: list[Entry], identities: list[Identity], speaker: str | None = None) -> str:
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
    together = _same_conversation(fresh)
    if together:
        new += ("\nDescriptions that come from ONE conversation: " + "; ".join(" and ".join(f"({x})" for x in group) for group in together)
                + ". That conversation names two different people \"" + name + "\" together, so the descriptions of one conversation "
                "are always different people: put each in a group of its own, never with another one of its conversation. They need no "
                "quotes against each other; fit each to the other conversations and the people on record as usual.\n")
    return PROMPT.format(name=name, filed=filed, new=new, speaker=speaker_line(speaker))


def _same_conversation(entries: list[Entry]) -> list[list[str]]:
    """The letters of the new descriptions that come from one conversation (two or more of them), conversation by conversation."""
    by: dict[str, list[str]] = {}
    for e in entries:
        if e.identity is None and e.conversation:
            by.setdefault(e.conversation, []).append(e.letter)
    return [letters for letters in by.values() if len(letters) > 1]


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
    # Two descriptions of one conversation are two people (the conversation itself names both). The answer cannot say which
    # of them a group it put both of them in belongs to: neither is known to be it. Every sibling the answer put with another
    # of its conversation, or left out, is a person of its own that waits in doubt against whatever else was in its group
    # (2026-11-24: the first of them used to keep the group by mention order, and so the person on record).
    together = _same_conversation(entries)
    forced: dict[tuple[int, int], str] = {}
    unplaced: list[int] = []
    for letters in together:
        sharing: dict[int, list[str]] = {}
        for x in letters:
            if x in group_of:
                sharing.setdefault(group_of[x], []).append(x)
        for g, xs in sharing.items():
            if len(xs) > 1:
                for x in xs:
                    members[g].remove(x)
                    members.append([x])
                    group_of[x] = len(members) - 1
                    unplaced.append(group_of[x])
        for x in letters:
            if x not in group_of:   # a sibling the answer left out
                members.append([x])
                group_of[x] = len(members) - 1
                unplaced.append(group_of[x])
        for i, a in enumerate(letters):
            for b in letters[i + 1:]:
                forced[(min(group_of[a], group_of[b]), max(group_of[a], group_of[b]))] = \
                    sibling_relation(by_letter[a].qualified, by_letter[b].qualified)
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
        key = (min(a, b), max(a, b))
        if forced.get(key) == "apart":
            continue   # one conversation wrote both with a qualifier: apart, below
        if not quotes_located(here, there, texts[a], texts[b], name):
            continue
        if key in verdicts and verdicts[key][0] == "doubt":
            continue   # the milder reading stands
        verdicts[key] = (verdict, str(here or ""), str(there or ""))
    for key, kind in forced.items():
        if kind == "apart" or verdicts.get(key, ("",))[0] != "apart":   # a located contrast outranks a structural doubt
            verdicts[key] = (kind, "", "")
    live = [g for g, letters in enumerate(members) if letters]
    for u in unplaced:   # nothing says who an unplaced sibling is: in doubt with every other group, never one person with it
        for h in live:
            if h != u and (min(u, h), max(u, h)) not in verdicts:
                verdicts[(min(u, h), max(u, h))] = ("doubt", "", "")
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


def sibling_relation(first_qualified: bool, second_qualified: bool) -> str:
    """How two descriptions of ONE conversation stand: ``"apart"`` when both were written with a qualifier, ``"doubt"``
    otherwise (2026-11-24). Stage 1 writes a qualifier for each of the two people a conversation names (all of 66 replayed
    two-person conversations), and writes one person it describes twice as one entity (12 of 12): two spellings, a bare name
    beside a qualified one, is a shape it did not produce in either, so nothing says it is two people. A doubt is held, and
    a later conversation settles it (`same_name_tend`)."""
    return "apart" if first_qualified and second_qualified else "doubt"


def _sibling_clusters(entries: list[Entry], base: bool) -> Reading:
    """Every description of a conversation that holds two or more is a person of its own, the sibling relation between
    them, in doubt against everything else (cluster 0, when ``base``); one of a conversation of its own is in cluster 0."""
    fresh = [e for e in entries if e.identity is None]
    siblings = {x for letters in _same_conversation(fresh) for x in letters}
    cluster_of: dict[str, int] = {e.letter: 0 for e in entries if e.letter not in siblings}
    start = 1 if (base and cluster_of) else 0
    by_letter = {e.letter: e for e in entries}
    order = [e.letter for e in entries if e.letter in siblings]
    for i, letter in enumerate(order):
        cluster_of[letter] = start + i
    relation: dict[tuple[int, int], tuple[str, str, str]] = {}
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            kind = sibling_relation(by_letter[a].qualified, by_letter[b].qualified) \
                if by_letter[a].conversation == by_letter[b].conversation else "doubt"
            relation[(cluster_of[a], cluster_of[b])] = (kind, "", "")
        if start:
            relation[(0, cluster_of[a])] = ("doubt", "", "")
    return Reading(cluster_of, relation)


def sibling_reading(entries: list[Entry]) -> Reading | None:
    """What stands with no judge, or an answer that cannot be used (2026-11-24): the descriptions of one conversation are
    different people, the conversation itself said so, and nothing says which of them a person on record is: none is.
    Everything else is one person as it always was (cluster 0); each sibling is a person of its own, in doubt against it
    and against the siblings of other conversations, and apart from the siblings of its own conversation that were
    written with a qualifier. ``None`` when no conversation holds two descriptions."""
    if not _same_conversation([e for e in entries if e.identity is None]):
        return None
    return _sibling_clusters(entries, base=True)


def apart_reading(entries: list[Entry]) -> Reading:
    """Every description is a person of its own: the descriptions all come from one conversation and nothing else is on
    record (2026-11-24); apart when the conversation wrote both with a qualifier, else in doubt."""
    return _sibling_clusters(entries, base=False)


def known_for(keys: dict[str, str], conversation: str, identities: list[Identity]) -> dict[str, Identity]:
    """Which person on record each mention of a conversation already read is, with no judge (2026-11-24). ``keys`` maps a
    mention's key to the name it was written with, lower case, ``""`` for the bare name. One mention and one person who lists
    the conversation: that person. Several: a mention written with a qualifier is the person whose aliases carry that name
    (the first read wrote it there), and a bare name is the one person left when every other mention was matched. A person
    two mentions would both take, or a name that matches no one, is left to the judge."""
    holders = [i for i in identities if conversation in i.episodes]
    if len(keys) == 1 and len(holders) == 1:
        return {next(iter(keys)): holders[0]}
    found: dict[str, Identity] = {}
    for key, written in keys.items():
        hit = [h for h in holders if written and written in h.aliases]
        if len(hit) == 1:
            found[key] = hit[0]
    claimed = [i.ref for i in found.values()]
    found = {k: i for k, i in found.items() if claimed.count(i.ref) == 1}
    left = [h for h in holders if h.ref not in {i.ref for i in found.values()}]
    bare = [k for k, written in keys.items() if not written]
    if len(bare) == 1 and bare[0] not in found and len(left) == 1 and len(found) == len(keys) - 1:
        found[bare[0]] = left[0]
    return found


def fallback(mention: Mention) -> Destination:
    """Where a person written with a qualifier goes when nothing placed it (a judge that failed, a batch over the cap, a
    cancelled run): never left under the name it was written with. The bare name's person, as a bare mention nothing
    placed always was, unless its own conversation also names the bare name, which it is then another person than: held
    in doubt, a person of its own."""
    return Destination("new", f"u:{mention.episode}", True) if mention.no_rename else Destination("plain", "")


# ---------------------------------------------------------------- placing the batch


def doubted_together(reading: Reading, entries: list[Entry], identities: list[Identity]) -> set[tuple[str, str]]:
    """The pairs of people on record, held in doubt against each other, whose filed conversations the reading puts in
    one group: one person who was doubted. The reading is not a join (ruling 74a: `same_name_tend` reads the two pages
    again, twice, for a located link); it is the reason to look. This holds when the whole name reads as one person
    too, which is the usual way a doubt ends: a later conversation says both things of one person."""
    held: dict[int, set[int]] = {}
    for e in entries:
        if e.identity is not None and e.letter in reading.cluster_of:
            held.setdefault(reading.cluster_of[e.letter], set()).add(e.identity)
    found: set[tuple[str, str]] = set()
    for members in held.values():
        for kx in members:
            for ky in members:
                if kx < ky and identities[ky].ref in identities[kx].doubt_with:
                    found.add(tuple(sorted((identities[kx].ref, identities[ky].ref))))   # type: ignore[arg-type]
    return found


def _structural(relation: tuple[str, str, str] | None) -> bool:
    """A relation the conversation itself set (its two people, or one that could not be placed): no quotes, no judge."""
    return relation is not None and relation[1] == "" and relation[2] == ""


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
    together = doubted_together(reading, entries, identities)
    if together:
        flags.review = True
        flags.review_reasons.extend("doubt-may-be-one" for _ in together)
        flags.review_pairs |= together
    plain = any(identity.plain for identity in identities)
    # Two groups the conversation itself told apart (one conversation names both, so they are two people) that both hold a
    # known person's filed conversations: the page holds both (flagged above). The group with fewer of its conversations
    # there keeps the page no longer; its new mentions are a person of their own, apart (2026-11-24).
    home_of = {c: max(held, key=lambda k: (identities[k].plain, held[k], -k)) for c, held in filed_of.items() if held}
    demoted: set[int] = set()
    for a in clusters:
        for b in clusters:
            if a < b and a in home_of and b in home_of and home_of[a] == home_of[b] \
                    and _structural(reading.relation.get((a, b))):
                demoted.add(b if filed_of[a][home_of[a]] >= filed_of[b][home_of[b]] else a)
    fresh_clusters: dict[int, list[str]] = {}
    for e in entries:
        if e.identity is not None or e.letter not in reading.cluster_of:
            continue
        episode = e.episodes[0]
        c = reading.cluster_of[e.letter]
        held = filed_of[c] if c not in demoted else {}
        if held:
            home = max(held, key=lambda k: (identities[k].plain, held[k], -k))
            identity = identities[home]
            if not identity.plain or e.qualified:
                # A person written with a qualifier ("Nico (finance lead)") is never left to the bare name's default: it
                # is named where it goes, the plain person's page or line included.
                moves[episode] = Destination(identity.kind, identity.ref)
        else:
            fresh_clusters.setdefault(c, []).append(episode)
    if fresh_clusters:
        bare = {e.episodes[0] for e in entries if e.identity is None and not e.qualified}
        no_rename = {e.episodes[0] for e in entries if e.identity is None and e.no_rename}
        # The plain person is the biggest new group; one that holds a mention of the bare name goes first (a name written
        # with a qualifier is not the plain name's own).
        ranked = sorted(fresh_clusters.items(), key=lambda item: (not any(e in bare for e in item[1]), -len(item[1]),
                                                                  min(first_seen.get(e, 0) for e in item[1])))
        for position, (c, episodes) in enumerate(ranked):
            if position == 0 and not plain:
                # The plain person, with nothing on record to say otherwise: the bare name's default. A mention written with
                # a qualifier takes the bare name (`Destination("plain")`) unless its own conversation also names the bare name.
                for episode in episodes:
                    if episode not in bare and episode not in no_rename:
                        moves[episode] = Destination("plain", "")
                    elif episode not in bare:
                        # its own conversation names the bare name too: a doubt against it (`sibling_relation`), a person of its own
                        moves[episode] = Destination("new", f"g{c}", True)
                        flags.review = True
                        flags.review_reasons.append("doubt-held")
                continue
            # What decides it is what the judge said or the record says, not what the conversation said of its own two:
            # a sibling told apart from this one for good (``("apart", "", "")``) says nothing against the people on record.
            kinds = {reading.relation[key][0] for key in reading.relation if c in key and reading.relation[key] != ("apart", "", "")}
            doubt = bool(kinds) and "apart" not in kinds
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
               strong: Callable[[str, str], Awaitable[object]] | None = None, *, speaker: str | None = None) -> Plan:
    """Decide one name (`_plan`), then close what no path of it left unplaced (2026-11-24): a person written with a qualifier
    is never left under the name it was written with, whichever way the decision ended (`fallback`), and the people one
    conversation named together know of each other (`Destination.siblings`)."""
    result = await _plan(name, mentions, identities, judge, strong, speaker)
    for m in mentions:
        if m.qualified and m.episode not in result.moves:
            result.moves[m.episode] = placed = fallback(m)
            if placed.kind == "new":
                result.review = True
                result.review_reasons.append("doubt-held")
    by_conversation: dict[str, list[Mention]] = {}
    for m in mentions[:MAX_MENTIONS]:
        by_conversation.setdefault(m.conversation or m.episode, []).append(m)
    for group in by_conversation.values():
        for m in group:
            destination = result.moves.get(m.episode)
            if len(group) > 1 and destination is not None and destination.kind == "new":
                siblings = []
                for other in group:
                    if other is m:
                        continue
                    there = result.moves.get(other.episode)
                    siblings.append((there.kind, there.ref, sibling_relation(m.qualified, other.qualified) == "apart")
                                    if there is not None else ("plain", "", sibling_relation(m.qualified, other.qualified) == "apart"))
                result.moves[m.episode] = replace(destination, siblings=tuple(siblings))
    return result


async def _plan(name: str, mentions: list[Mention], identities: list[Identity],
                judge: Callable[[str, str], Awaitable[object]],
                strong: Callable[[str, str], Awaitable[object]] | None = None, speaker: str | None = None) -> Plan:
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
    fresh = [e for e in entries if e.identity is None]
    sibling_fallback = sibling_reading(entries)
    if not shown and len({e.conversation for e in fresh}) == 1:
        # One conversation names them all and nobody is on record: they are different people, and there is nothing to ask.
        result.called = False   # no judge was asked
        return _place(result, apart_reading(fresh), entries, shown, judged)
    prompt = build_prompt(name, entries, shown, speaker)
    try:
        parsed = await judge(SYSTEM, prompt)
    except asyncio.CancelledError:
        raise
    except engine_errors.EngineError:
        raise   # G74(a): an engine failure is never a model's answer
    except Exception as e:  # noqa: BLE001 - anything else is "one person"
        logger.debug(f"Same-name judge failed: {type(e).__name__}")
        parsed = None
    reading = read(parsed, entries, name) if parsed is not None else None
    if reading is None:
        if sibling_fallback is None:
            return result
        return _place(result, sibling_fallback, entries, shown, judged)
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
        if second is not None and not second.single and _covers(second, entries):
            reading = second
    if reading.single and sibling_fallback is not None:
        reading = sibling_fallback   # one conversation names two of them: they are not one person
    return _place(result, reading, entries, shown, judged)


def _covers(reading: Reading, entries: list[Entry]) -> bool:
    """The reading accounts for every description of a person on record. An answer that leaves them all out (a second reading
    that grouped only this batch's conversations) puts the person on record nowhere, so each of the batch's people would be a
    new one, however sure its grouping: that does not line up with what was shown, and the first reading stands (2026-11-24; a
    real run made the cousin of a two-Nico conversation a third Nico this way)."""
    return all(e.letter in reading.cluster_of for e in entries if e.identity is not None)


def _place(result: Plan, reading: Reading, entries: list[Entry], shown: list[Identity], judged: list[Mention]) -> Plan:
    """The reading's people → where each new conversation goes (`decide`), less a person a description too thin to stand
    on would make new."""
    first_seen = {m.episode: i for i, m in enumerate(judged)}
    if reading.single:
        # One person throughout: the bare name's mentions stay as they always did. A mention written with a qualifier
        # still goes where that person is (the plain page or line, or the bare name), never on under its qualified name.
        moves, _flags = decide(reading, entries, shown, first_seen)
        asked = {e.episodes[0] for e in entries if e.identity is None and e.qualified}
        result.moves = {k: d for k, d in moves.items() if k in asked}
        # One person, and it may be two who were held in doubt: nothing is joined here, the pair is looked at again.
        result.review_pairs = doubted_together(reading, entries, shown)
        if result.review_pairs:
            result.review = True
            result.review_reasons = ["doubt-may-be-one"] * len(result.review_pairs)
        return result
    moves, flags = decide(reading, entries, shown, first_seen)
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
    forced = {c for key, relation in reading.relation.items() if relation == ("apart", "", "") for c in key}
    cluster_by_key = {e.episodes[0]: reading.cluster_of.get(e.letter) for e in entries if e.identity is None}
    written = {e.episodes[0] for e in entries if e.identity is None and e.qualified}
    for episodes in news.values():
        if any(cluster_by_key.get(e) in forced for e in episodes):
            continue   # one conversation said they are two people: nothing thin about that
        if words(plain_text) < MIN_WORDS or words(" ".join(text_of[e] for e in episodes)) < MIN_WORDS:
            if any(e in written for e in episodes):
                # A person written with a qualifier is never put back under the bare name by a thin description, and never
                # left under its written name: the judge and the qualifier say it is another person, the words say too
                # little to be sure. That is a doubt (2026-11-24): a person of its own, waiting, joined to none.
                for episode in episodes:
                    moves[episode] = replace(moves[episode], doubt=True)
                result.review = True
                result.review_reasons.append("doubt-held")
                continue
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
