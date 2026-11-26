"""What was said about a thing nobody named lands on the page it was said about (2026-11-25, G148, G98, ruling 41a).

Stage 1 sometimes writes a label for a thing the conversation only described ("<Feature> redesign", "<Project> extraction
worker"; `coined_names`). Stage 2 gives such a label no page from one conversation, so what was said about it waits in a
held line (`pending_store`) that nothing will ever name again. Measured on a real bank (real values redacted), 1,351 of
5,912 held lines were such labels.

**The first version of this rule was code alone, and it landed nothing on a real memory.** It asked that the claim's own
sentence name exactly one page and stand the label's words beside the page's name ("the <part> of <Page>"). Dry-run on the
owner's bank: 953 claims looked at, 0 would land. Of the 341 claims that cleared the turn, span and located-words gates only 22
sat in a sentence naming exactly one eligible page, and the last gate turned every one of those away, as it must: a label is
words nobody said that way, so the words of the label never stand beside the page. What tells which page a described fact is
about is the conversation AROUND it ("I have been on <Page> all week ... the importer keeps timing out"), and reading that is a
reader's job (the owner, three times in a week, about questions: "a Claude Code session with the same context would figure it
out easy"; and he ruled accuracy over model price). So the rule is now **code before, a read by the engine's main model, code
after**; a fact that fails any of them stays held (leaving a fact held is always allowed).

**Before the read (code).** A claim goes to the reader only when: the line is a label (a concept or project whose name and
aliases no text of any conversation it cites says, `coined_names.said_in` ``nowhere`` in every one; one that cannot be read is
not a label); the label was the claim's SUBJECT, the claim is open and no event; its evidence is a located span, current as the
source is now (`source_spans.Source.status`), inside a turn the person's own (`promotion.person_kinds`: in a meeting a named
speaker's, in a group chat only the person's), never an assistant's, an agent note's or a saved page's; and the SAME
CONVERSATION names at least one candidate page, in a turn of the person's (or a named speaker's), by its title or an alias,
located by `evidence.locate` (exact, whitespace, case: never fuzzy), a name only one page bears. A candidate is a live
project: never the owner's, never a tool, a concept, a person, a company or a place, never one the person said the mention is
not (`apart`). No candidate: the claim stays held. The old gates (the sentence names exactly one page, is short, holds the label's
words beside the name) are no longer gates; what they measured is the reader's context.

**The read.** The reader is shown the claim, the turn it was said in, the turns just before and after it (bounded) and each
candidate with its name and a one-line summary, and answers which ONE candidate the fact is about (a fact about that thing or a
part of it), or none, and copies the sentence from a turn of the person's that shows it. It reads TWICE: the second time in
the reverse candidate order, told to look for the reason the fact is about something else or about nothing on the list. Both
reads must name the same candidate, and each copied sentence must be located (never fuzzy) in a person's turn inside the shown
window. A disagreement, "none", an unusable reply or a sentence that does not locate leaves the claim held; a "no" is
remembered (a hash under a hashed key, outside every bank) so the pair is not read again until the line, the conversation or a
candidate changes, while an unusable reply or an unlocated sentence says nothing and is read again.
A line's claims said in one conversation are read in one call (at most :data:`MAX_CLAIMS_PER_CALL`).

**Only a project is a page a fact lands on (2026-11-25, after the dry run on the owner's bank, real values redacted).** The
first reader accepted a project, a tool or a concept page. Of the 33 claims it would have landed on 17 pages, I judged each
against its sentence: on a **project** page (4 pages, 17 claims) 17 were right (a description of the project in other words, a
deliverable of it, its repository, a component); on a **tool** page (4 pages, 6 claims) 2 were right and 4 doubtful (a thing the
person built WITH the tool, or an account or instance of theirs IN it, landed as "a part of" the tool); on a **concept** page
(9 pages, 10 claims) 3 were right and 7 wrong (a specific thing of the person's landed on the page of a general notion that
shares a word with it). The reader is right when the page is something of the person's that has parts, and wrong when the page
is a general notion or a product that the thing merely uses or runs in: a property the code can hold. So a tool or a concept is
never a candidate; a conversation that names only tools and concepts leaves the claim held, counted as
``named_pages_not_projects``, before any read (310 claims reached the reader on that bank, 0.59 calls a claim).

**After the read (code).** The landed claim records the sentence copied as a second evidence span; the settle's record keeps
every one. A relation ("the landlord of <Page>", "<Page>'s accountant"), the person's own life and a tool used with the page
are the reader's to refuse; the battery carries them.

**What landing means.** The claim is written on the page as a claim OF the page: subject the page, predicate and object as
held, id kept, its evidence span, source conversation, observer, trust and dates unchanged, its text kept with the label's own
words with what the two reads said it is marked: ``(a part of <Page>)`` when both said a part, ``(about <Page> itself)`` when both
said the label is the page in other words, nothing when they did not say the same (the weaker wording, never a refusal) —
never re-worded by a model, so a located span still backs every word. The line keeps whatever did not land (`pending_store.drop_released`) and is closed only when nothing is left. The
page's `source_episodes` and `last_referenced` are NOT moved: the conversation is no new mention for decay or promotion unless
it already counted. A page gets one settle per run: one commit of its own paths, one record `inbox/settled/land-NNN.md` under
"Settled by Sleep" with the sentences shown, undoable as one (`undo`: each claim leaves the page only while it is as the landing wrote it, whatever Sleep's decay pass has done
to its bookkeeping since; it goes back to its line, checked before anything is written, and the person's undo is
remembered as `apart`, so the page is never offered the mention again).

Rails held here: no model at capture time (this is a Sleep tail step); located spans only, never fuzzy; no name or sentence
is logged or kept outside the bank (what was read is a hash outside every bank, `_seen`); a plan limit is a pause; a
scheduled run reaches a plan only through the person's switch (`same_name_tend.main_engine`)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import (authorship, coined_names, engine_errors, evidence, markdown_parser, pending_store, promotion,
                          source_spans, text_fold)
from api.services.claims import Claim, Evidence, MalformedClaimsBlockError, is_event, parse_claims, write_claims
from api.services.id_utils import sanitize_id

RULE = "land_described"
RECORD_PREFIX = "land-"
SETTLED_DIR = "settled"
REASON = "What you said about this page, in a conversation that names it, was held under a label nobody said."

#: The only pages a fact can land on: something of the person's that has parts (see the module's docstring for the measurement).
#: A tool or a concept is a general notion or a product the thing merely uses or runs in; a person, the owner, a company, a place,
#: an event, a media record or a skill is never the thing a label's fact is about either.
TARGET_TYPES = frozenset({"project"})
#: Live pages a conversation may name that are turned away by type, counted (`named_pages_not_projects`): never a candidate.
TURNED_AWAY_TYPES = frozenset({"tool", "concept"})
ACTIVE = frozenset({"active", "decaying", ""})
#: A single-word page name this short is a common word more often than a name.
MIN_SINGLE_NAME = 4
#: Groups (a line's claims from one conversation) read per run, per bucket (old, and fresh: said in the last days).
GROUPS_PER_RUN = 25
FRESH_DAYS = 3
#: What the reader is shown: candidates, claims a call, turns around a claim, characters.
MAX_CANDIDATES = 6
MAX_CLAIMS_PER_CALL = 6
TURNS_BEFORE, TURNS_AFTER = 3, 2
WINDOW_CHARS = 9000
MIN_SENTENCE = 8
SUMMARY_CHARS = 240
LETTERS = "ABCDEF"
#: What a read says the fact is about: a part of the page, or the page itself (the label being its description in other words).
#: Anything else (no word, another word) is "" and the claim carries no marker.
SCOPES = ("part", "whole")

_WORD = re.compile(r"[^\W_]+", re.U)

SYSTEM = ("You read part of a conversation a person had and decide which one of the things they work on a fact they stated is "
          "about, from the words you are given only, and answer in JSON.")

PROMPT = """A person's knowledge graph holds the things they work on. While reading the conversation below, Sleep wrote each fact listed under a label of its own ("{label}") that nobody said in those words, so the fact is not yet written on any page. The conversation names the things in the list of candidates. Decide, for each fact, which ONE candidate it is about: a fact about that thing itself, or about a part, feature, stage, task, bug or aspect of it. If you agree, the fact is written on that candidate's page; a wrong yes puts a belief about one thing on another thing's page for good, and a no costs little (the fact stays where it is). Only what the person (or a named speaker) said counts; an assistant's words are context, never proof.

What Sleep read about the label (its own summary): {summary}

The conversation (turns are numbered; "..." marks turns left out):
{window}

Candidates (things of the person's the conversation names):
{candidates}

Facts:
{facts}
{second}
For each fact give the ONE candidate it is about, or "none". Answer "none" when any of these holds:
- the fact is about the person themself, their life, health, habits, taste, opinion or plans, and no candidate;
- the fact is about a person, a place, a company or another thing, even one named beside a candidate or nearby;
- the fact states a relation TO a candidate ("the landlord of X", "X's accountant", a competitor, client, owner, maintainer, a fork of X): it is about that other person or thing;
- a candidate is only where or when something happened, where something runs or lives, or what something is used with or for ("I use X for the newsletter", "the export runs in X"): a thing that runs in or uses a candidate is not a part of it;
- the person says the thing is separate from the candidate, or has moved away from it;
- two candidates would fit equally, or you are not sure. A wrong guess is worse than "none".
Also copy, exactly as written and without changing a character, the one sentence or clause (at most {max_chars} characters) from a turn of the PERSON (or named speaker), not the assistant, that shows the fact is about that candidate: usually the sentence that states the fact, or an earlier sentence of theirs that names the thing it is about. Never copy a sentence from an assistant turn, and never write words of your own in "sentence".

Respond with JSON only:
{{"claims": [{{"n": 1, "page": "A" | "B" | ... | "none", "scope": "part" | "whole", "sentence": "copied words"}}]}}
("scope": "part" when the fact is about a part, feature, deliverable or aspect of the candidate; "whole" when the label is just another way of describing the candidate itself and the fact is about the candidate as a whole.)
"""

SKEPTIC = """
Be a skeptic. A first reading proposed an answer for each fact; do not assume it was right. Before you answer, look for the reason each fact is about something else than any candidate, or about nothing on the list (the person themself, a person named, another thing, a relation, a tool used with a candidate, a different job or place); answer a candidate only when you cannot find one. The candidates are listed in a different order from before: read each name.
"""


# ---------------------------------------------------------------------------------------------------- the pages' names


def _fold_words(text: str) -> list[str]:
    return [text_fold.fold(w) for w in _WORD.findall(str(text or ""))]


@dataclass(frozen=True)
class Mention:
    """A page name found in a text: its words' positions and the pages that bear that name (more than one: ambiguous)."""
    start: int
    end: int
    pages: frozenset[str]


@dataclass
class Page:
    id: str
    name: str
    type: str
    owner: bool
    status: str
    names: tuple[str, ...]    # the name and the aliases as written

    @property
    def eligible(self) -> bool:
        return not self.owner and self.type in TARGET_TYPES and self.status in ACTIVE

    @property
    def turned_away(self) -> bool:
        """A live tool or concept: named, counted, never offered."""
        return not self.owner and self.type in TURNED_AWAY_TYPES and self.status in ACTIVE


class PageNames:
    """Every name and alias of every page of the bank, to find which pages a conversation names. Persons, the owner, archived
    pages included: a name two pages bear is ambiguous and offered to nobody."""

    def __init__(self, pages: list[dict]) -> None:
        owners: dict[tuple, set[str]] = defaultdict(set)
        self.pages: dict[str, Page] = {}
        for p in pages:
            names = [p["name"], *p["aliases"]]
            for n in names:
                key = tuple(_fold_words(n))
                if not key or (len(key) == 1 and len(key[0]) < MIN_SINGLE_NAME):
                    continue
                owners[key].add(p["id"])
            self.pages[p["id"]] = Page(p["id"], p["name"], p["type"], p["owner"], p["status"], tuple(dict.fromkeys(names)))
        self.by_first: dict[str, list[tuple[tuple, frozenset[str]]]] = defaultdict(list)
        for key, ids in owners.items():
            self.by_first[key[0]].append((key, frozenset(ids)))

    @classmethod
    def of_bank(cls, memory_path: Path) -> "PageNames":
        pages = []
        for path in sorted((Path(memory_path) / "entities").glob("*.md")):
            try:
                fm = markdown_parser.parse(path).frontmatter or {}
            except Exception:  # noqa: BLE001 - a page that does not parse is skipped, as every reader does
                continue
            pages.append({"id": path.stem, "name": str(fm.get("name") or path.stem), "type": str(fm.get("type") or "").lower(),
                          "owner": bool(fm.get("owner")), "status": str(fm.get("status") or "").lower(),
                          "aliases": [str(a) for a in fm.get("aliases") or [] if isinstance(a, str)]})
        return cls(pages)

    def mentions(self, words: list[str]) -> list[Mention]:
        """Every name in ``words`` (folded), longest first, no two overlapping: "Importer API" is not also "Importer"."""
        found: list[Mention] = []
        for i, w in enumerate(words):
            for key, ids in self.by_first.get(w, ()):
                if tuple(words[i:i + len(key)]) == key:
                    found.append(Mention(i, i + len(key), ids))
        found.sort(key=lambda m: (-(m.end - m.start), m.start))
        taken: list[Mention] = []
        for m in found:
            if all(m.end <= t.start or m.start >= t.end for t in taken):
                taken.append(m)
        return sorted(taken, key=lambda m: m.start)


# ---------------------------------------------------------------------------------------------------- a conversation


class Conv:
    """One conversation: its text, its turns, and which eligible pages its person's turns name."""

    def __init__(self, episode: str, doc: tuple[dict, str]) -> None:
        fm, body = doc
        self.episode, self.fm, self.text = episode, fm, body
        self.persons = promotion.person_kinds(fm)
        masked = evidence.mask_labels(body)
        self.turns = evidence.turns(masked, override=authorship.of(fm), gaps=evidence.gap_ranges(fm, body))
        self.title = str(fm.get("title") or "")
        self._named: dict[str, list[int]] | None = None
        self.not_projects: set[str] = set()    # live tools and concepts the person's turns name (never candidates)
        self.ambiguous = 0

    def is_person(self, i: int) -> bool:
        return 0 <= i < len(self.turns) and self.turns[i].role in self.persons

    def turn_at(self, pos: int) -> int | None:
        for i, t in enumerate(self.turns):
            if t.start <= pos < t.end:
                return i
        return None

    def content(self, i: int) -> tuple[int, int]:
        t = self.turns[i]
        return t.content_start, t.end

    def named(self, names: PageNames) -> dict[str, list[int]]:
        """``{page id: [indexes of the person's turns that name it]}`` for the eligible pages (projects; the tools and concepts
        named go to ``not_projects``) whose name or alias the
        conversation says (a name found by words, then located by `evidence.locate`: whole word, never fuzzy). A name two
        pages bear names none of them."""
        if self._named is not None:
            return self._named
        out: dict[str, list[int]] = defaultdict(list)
        for i, t in enumerate(self.turns):
            if t.role not in self.persons:
                continue
            a, b = self.content(i)
            chunk = self.text[a:b]
            for m in names.mentions(_fold_words(chunk)):
                if len(m.pages) != 1:
                    self.ambiguous += 1
                    continue
                page = names.pages.get(next(iter(m.pages)))
                if page is None or not (page.eligible or page.turned_away) or i in out.get(page.id, ()):
                    continue
                if any(evidence.locate(chunk, n, whole_word=True) for n in page.names):
                    if page.eligible:
                        out[page.id].append(i)
                    else:
                        self.not_projects.add(page.id)
        self._named = dict(out)
        return self._named


class Docs:
    """Episode documents read once each: ``(frontmatter, text)``, or ``None`` for one that cannot be read; and `Conv`s."""

    def __init__(self, memory_path: Path) -> None:
        self.memory_path, self._seen, self._conv = Path(memory_path), {}, {}

    def get(self, episode: str):
        if episode not in self._seen:
            doc = evidence.source_document(self.memory_path, episode) if str(episode).startswith("ep_") else None
            self._seen[episode] = doc
        return self._seen[episode]

    def conv(self, episode: str) -> Conv | None:
        if episode not in self._conv:
            doc = self.get(episode)
            self._conv[episode] = Conv(episode, doc) if doc is not None else None
        return self._conv[episode]


def is_label(line: pending_store.PendingEntity, docs: Docs) -> bool:
    """A concept or project whose name and aliases no text of any conversation it cites says (`coined_names`)."""
    if line.correspondent or str(line.type or "concept").lower() not in coined_names.COINABLE_TYPES:
        return False
    episodes = line.episodes()
    if not episodes:
        return False
    names = [line.name, *line.aliases]
    for ep in episodes:
        doc = docs.get(ep)
        if doc is None:
            return False
        fm, body = doc
        got = coined_names.said_in(names, body, override=authorship.of(fm), gaps=evidence.gap_ranges(fm, body),
                                   persons=promotion.person_kinds(fm), extra=str(fm.get("title") or ""))
        if got != coined_names.NOWHERE:
            return False
    return True


# ---------------------------------------------------------------------------------------------------- the candidates


@dataclass
class Item:
    """One claim that passed every code gate before the read: the reader says which candidate it is about, if any."""
    line: str                 # the held line's name (its key)
    claim: Claim
    episode: str
    start: int                # the claim's own located words
    end: int
    hash: str
    turn: str                 # whose turn: user | speaker
    turn_index: int
    rule: str = RULE

    @property
    def line_slug(self) -> str:
        return sanitize_id(self.line)


@dataclass
class Group:
    """A line's claims said in ONE conversation, with the pages that conversation names: one reader call (two reads)."""
    line: str
    episode: str
    items: list[Item]
    candidates: list[str]     # page ids, nearest the claims first, at most MAX_CANDIDATES
    summary: str = ""         # what Stage 1 read about the label (its own summary)

    def sub(self, items: list[Item]) -> "Group":
        return Group(self.line, self.episode, items, self.candidates, self.summary)


@dataclass
class Plan:
    """What the code gates decided for a bank (or a part of it): the groups, and counts of what each gate turned away."""
    groups: list[Group] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)
    lines: int = 0
    labels: int = 0
    claims: int = 0

    @property
    def items(self) -> list[Item]:
        return [i for g in self.groups for i in g.items]


def gate_line(line: pending_store.PendingEntity, docs: Docs, names: Callable[[], PageNames], plan: Plan) -> list[Group]:
    """The groups of one held line's claims that pass every code gate, with a count of what turned each other one away."""
    slug = sanitize_id(line.name)
    by_episode: dict[str, list[Item]] = defaultdict(list)
    for data in line.held_claims:
        plan.claims += 1
        try:
            claim = Claim.from_dict(data)
        except (TypeError, ValueError):
            plan.skipped["unreadable_claim"] += 1
            continue
        if claim.subject != slug:
            plan.skipped["label_not_subject"] += 1
            continue
        if claim.valid_to is not None or is_event(claim):
            plan.skipped["closed_or_event"] += 1
            continue
        item = _gate_claim(line, claim, docs, plan)
        if item is not None:
            by_episode[item.episode].append(item)
    out: list[Group] = []
    for episode, items in by_episode.items():
        conv = docs.conv(episode)
        named = conv.named(names()) if conv is not None else {}
        # Ruling 83: what the person said about THIS conversation (it is not that page: "someone else"), and the page it was filed to.
        from api.services import which_one_file

        apart = line.apart_pages() | which_one_file.said_not(line).get(episode, set())
        if episode in which_one_file.filed(line):
            apart |= {p for p in named if p != which_one_file.filed(line)[episode]}
        for chunk in _chunks(sorted(items, key=lambda i: (i.start, i.claim.id))):
            ranked = _candidates(named, chunk, apart)
            kept = []
            for it in chunk:
                own = str(it.claim.object or "") if it.claim.object_kind != "literal" else ""
                if any(p != own for p in ranked):    # a page the claim's own other end names is no page it is about
                    kept.append(it)
                elif not ranked and conv is not None and conv.not_projects:
                    plan.skipped["named_pages_not_projects"] += 1   # it names tools or concepts only: held, never read
                else:
                    plan.skipped["no_candidate_page"] += 1
            if kept:
                out.append(Group(line.name, episode, kept, _candidates(named, kept, apart),
                                 summary=str(line.summary or line.description or "")))
    return out


def _chunks(items: list[Item]) -> list[list[Item]]:
    return [items[i:i + MAX_CLAIMS_PER_CALL] for i in range(0, len(items), MAX_CLAIMS_PER_CALL)]


def _candidates(named: dict[str, list[int]], items: list[Item], apart: set[str]) -> list[str]:
    """The pages the conversation names, nearest the claims' turns first (then by id), at most MAX_CANDIDATES."""
    def near(page: str) -> int:
        return min(abs(t - it.turn_index) for t in named[page] for it in items)

    pages = [p for p in named if p not in apart]
    return sorted(pages, key=lambda p: (near(p), p))[:MAX_CANDIDATES]


def _gate_claim(line, claim: Claim, docs: Docs, plan: Plan) -> Item | None:
    spans = [e for e in claim.evidence if e.is_span()]
    if not spans:
        plan.skipped["no_located_words"] += 1
        return None
    why = "no_located_words"
    for ev in spans:
        doc = docs.get(ev.episode)
        conv = docs.conv(ev.episode)
        if doc is None or conv is None:
            why = "source_unreadable"
            continue
        src = source_spans.Source.of(ev.episode, doc[0], doc[1])
        if src.status(ev.start, ev.end, ev.hash) not in (source_spans.CURRENT, source_spans.GROWN):
            why = "span_stale_or_held"
            continue
        at = conv.turn_at(ev.start)
        if at is None or not conv.is_person(at):
            why = "not_the_persons_turn"
            continue
        return Item(line=line.name, claim=claim, episode=ev.episode, start=ev.start, end=ev.end, hash=ev.hash,
                    turn=conv.turns[at].role, turn_index=at)
    plan.skipped[why] += 1
    return None


def plan_bank(memory_path: Path, *, lines: list[pending_store.PendingEntity] | None = None,
              only: Callable[[pending_store.PendingEntity], bool] | None = None) -> Plan:
    """Run every code gate over the bank's held lines. Reads files, writes nothing, calls no model."""
    memory_path = Path(memory_path)
    plan = Plan()
    docs = Docs(memory_path)
    lazy: list[PageNames] = []

    def names() -> PageNames:
        if not lazy:
            lazy.append(PageNames.of_bank(memory_path))
        return lazy[0]

    for line in lines if lines is not None else pending_store.load(memory_path):
        plan.lines += 1
        if not line.held_claims or (only is not None and not only(line)):
            continue
        slug = sanitize_id(line.name)
        if not any(d.get("subject") == slug and not d.get("valid_to") and d.get("evidence") for d in line.held_claims):
            plan.skipped["nothing_the_label_said_with_words"] += 1   # cheap, before any conversation is read
            continue
        if not is_label(line, docs):
            plan.skipped["line_is_not_a_label"] += 1
            continue
        plan.labels += 1
        plan.groups.extend(gate_line(line, docs, names, plan))
    return plan


# ---------------------------------------------------------------------------------------------------- the reader


def _page_text(memory_path: Path, page_id: str) -> tuple[str, str, str] | None:
    """``(name, one-line summary, body)`` of a page, or ``None``."""
    from api.services.claims import strip_claims_block

    path = Path(memory_path) / "entities" / f"{page_id}.md"
    try:
        parsed = markdown_parser.parse(path)
    except Exception:  # noqa: BLE001
        return None
    fm = parsed.frontmatter or {}
    body = strip_claims_block(parsed.body or "").strip()
    one = str(fm.get("summary") or fm.get("description") or "").strip()
    if not one:
        one = next((ln.strip() for ln in body.splitlines() if ln.strip() and not ln.lstrip().startswith("#")), "")
    return str(fm.get("name") or page_id), " ".join(one.split())[:SUMMARY_CHARS] or "(no description)", body


@dataclass
class Shown:
    """The part of a turn the reader is shown: ``[a, b)`` of the conversation text."""
    index: int
    a: int
    b: int


def window_for(conv: Conv, items: list[Item]) -> list[Shown]:
    """The turns around every claim of the group (``TURNS_BEFORE`` before, ``TURNS_AFTER`` after), each cut to its share of
    ``WINDOW_CHARS``; the claim's own turn is cut around the claim's words."""
    wanted: set[int] = set()
    for it in items:
        wanted.update(range(max(0, it.turn_index - TURNS_BEFORE), min(len(conv.turns), it.turn_index + TURNS_AFTER + 1)))
    order = sorted(wanted)
    cap = max(300, min(1500, WINDOW_CHARS // max(1, len(order))))
    focus = {it.turn_index: (it.start, it.end) for it in items}
    shown: list[Shown] = []
    for i in order:
        a, b = conv.content(i)
        if b - a > cap:
            if i in focus:
                lo, hi = focus[i]
                mid = (lo + hi) // 2
                a2 = max(a, min(mid - cap // 2, b - cap))
                a, b = a2, min(b, a2 + cap)
            else:
                b = a + cap
        shown.append(Shown(i, a, b))
    return shown


def window_text(conv: Conv, shown: list[Shown]) -> str:
    out, last = [], None
    for s in shown:
        if last is not None and s.index != last + 1:
            out.append("...")
        role = conv.turns[s.index].marker or conv.turns[s.index].role
        out.append(f"[{s.index + 1}] {role}: {conv.text[s.a:s.b].strip()}")
        last = s.index
    return "\n".join(out)


def locate_sentence(conv: Conv, shown: list[Shown], sentence: object) -> tuple[int, int, int] | None:
    """``(start, end, turn index)`` of the copied sentence inside a PERSON's turn of the shown window — exact, whitespace or
    case, never fuzzy — or ``None``. A reply too short or too long to be one sentence is none."""
    quote = " ".join(str(sentence or "").split())
    if not (MIN_SENTENCE <= len(quote) <= evidence.MAX_QUOTE_CHARS):
        return None
    for s in shown:
        if not conv.is_person(s.index):
            continue
        hit = evidence.locate(conv.text[s.a:s.b], quote)
        if hit is not None:
            return s.a + hit[0], s.a + hit[1], s.index
    return None


@dataclass
class Pick:
    """What both reads agreed on for one claim."""
    page: str
    scope: str                       # part | whole | "" (the two reads did not say the same: the weaker wording, no marker)
    start: int                       # the copied sentence, offsets into the conversation text
    end: int
    turn: str
    hash: str = ""


@dataclass
class GroupRead:
    picks: dict[int, Pick] = field(default_factory=dict)        # item index -> the agreed pick
    left: dict[int, str] = field(default_factory=dict)          # item index -> why it stays held
    calls: int = 0
    failed: bool = False                                        # a call failed: nothing is remembered
    #: item index -> (page the first read named, the sentence it copied, the page the second read named): what a dry run shows
    #: about a claim that stayed held; never stored, never logged.
    seen: dict[int, tuple[str, str, str]] = field(default_factory=dict)


def prompt_for(label: str, summary: str, window: str, candidates: list[tuple[str, str]], facts: list[tuple[int, str, int]],
               *, second: bool = False) -> str:
    cands = "\n".join(f"{LETTERS[i]}. {name} — {one}" for i, (name, one) in enumerate(candidates))
    rows = "\n".join(f"{n}. {text} (said in turn [{turn + 1}])" for n, text, turn in facts)
    return PROMPT.format(label=label, summary=(summary or "").strip()[:500] or "(empty)", window=window, candidates=cands,
                         facts=rows, second=SKEPTIC if second else "", max_chars=evidence.MAX_QUOTE_CHARS)


def answers_of(parsed: object) -> dict[int, dict]:
    """``{fact number: {"page": letter | "none", "scope": ..., "sentence": ...}}``; every other shape is no answer."""
    out: dict[int, dict] = {}
    rows = parsed.get("claims") if isinstance(parsed, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            n = int(row.get("n"))
        except (TypeError, ValueError):
            continue
        out[n] = {"page": str(row.get("page") or "").strip().upper().rstrip("."), "sentence": row.get("sentence"),
                  "scope": str(row.get("scope") or "").strip().lower()}
    return out


async def _one_read(label: str, summary: str, conv: Conv, shown: list[Shown], cands: list[tuple[str, str, str]],
                    facts: list[tuple[int, Item]], ask: Callable, *, second: bool) -> dict[int, tuple[str | None, dict | None, str]]:
    """One call: ``{fact number: (page id or None, located sentence or None, scope | why-not)}``."""
    prompt = prompt_for(label, summary, window_text(conv, shown), [(n, o) for _i, n, o in cands],
                        [(k, it.claim.text, it.turn_index) for k, it in facts], second=second)
    parsed = await ask(SYSTEM, prompt)
    said = answers_of(parsed)
    out: dict[int, tuple[str | None, dict | None, str]] = {}
    ids = {LETTERS[i]: cands[i][0] for i in range(len(cands))}
    for k, it in facts:
        row = said.get(k)
        if row is None:
            out[k] = (None, None, "unusable_reply")
            continue
        if row["page"] in ("", "NONE"):
            out[k] = (None, None, "none")
            continue
        page = ids.get(row["page"])
        if page is None:
            out[k] = (None, None, "unusable_reply")
            continue
        hit = locate_sentence(conv, shown, row["sentence"])
        if hit is None:
            out[k] = (page, None, "sentence_not_located")
            continue
        out[k] = (page, {"start": hit[0], "end": hit[1], "turn": hit[2]}, row["scope"] if row["scope"] in SCOPES else "")
    return out


async def read_group(memory_path: Path, group: Group, docs: Docs, ask: Callable) -> GroupRead:
    """The two reads. ``ask(system, prompt)`` is the engine's main model, JSON back. An engine failure propagates (the caller
    pauses); any other failure is no claim landing and nothing remembered."""
    result = GroupRead()
    conv = docs.conv(group.episode)
    if conv is None:
        result.failed = True
        return result
    cands: list[tuple[str, str, str]] = []   # (page id, name, one-line summary)
    for pid in group.candidates:
        got = _page_text(memory_path, pid)
        if got is not None:
            cands.append((pid, got[0], got[1]))
    summary = group.summary
    if not cands:
        for i in range(len(group.items)):
            result.left[i] = "no_candidate_page"
        return result
    shown = window_for(conv, group.items)
    facts = [(i + 1, it) for i, it in enumerate(group.items)]
    try:
        first = await _one_read(group.line, summary, conv, shown, cands, facts, ask, second=False)
        result.calls += 1
    except engine_errors.EngineError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Described landing: reading failed: {type(e).__name__}")
        result.failed = True
        return result
    keep: list[tuple[int, Item]] = []
    for k, it in facts:
        page, hit, why = first[k]
        if page is not None:
            result.seen[k - 1] = (page, " ".join(conv.text[hit["start"]:hit["end"]].split()) if hit else "", "")
        obj = str(it.claim.object or "") if it.claim.object_kind != "literal" else ""
        if page is None:
            result.left[k - 1] = f"first_read_{why}"
        elif hit is None:
            result.left[k - 1] = f"first_read_{why}"
        elif page == obj:
            result.left[k - 1] = "first_read_names_the_claims_own_object"
        else:
            keep.append((k, it))
    if not keep:
        return result
    backwards = list(reversed(cands))
    try:
        again = await _one_read(group.line, summary, conv, shown, backwards, keep, ask, second=True)
        result.calls += 1
    except engine_errors.EngineError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Described landing: second reading failed: {type(e).__name__}")
        result.failed = True
        return result
    for k, it in keep:
        p1, h1, s1 = first[k]
        p2, h2, s2 = again[k]
        result.seen[k - 1] = (p1, result.seen[k - 1][1], p2 or "")
        if p2 is None or h2 is None:
            result.left[k - 1] = f"second_read_{s2}"
        elif p2 != p1:
            result.left[k - 1] = "reads_disagree"
        else:
            result.picks[k - 1] = Pick(page=p1, scope=s1 if s1 == s2 and s1 in SCOPES else "", start=h1["start"],
                                       end=h1["end"], turn=conv.turns[h1["turn"]].role, hash=it.hash)
    return result


# ---------------------------------------------------------------------------------------------------- landing


class NotLandable(ValueError):
    """The landing (or its undo) cannot be done as asked; the reason is said in words and nothing was written."""


@dataclass
class Landed:
    record_id: str
    page: str
    claim_ids: list[str]
    paths: list[str]
    lines: list[str]


def _next_record_id(memory_path: Path) -> str:
    settled = Path(memory_path) / "inbox" / SETTLED_DIR
    nums = [int(m.group(1)) for p in settled.glob(f"{RECORD_PREFIX}*.md")
            if (m := re.fullmatch(rf"{RECORD_PREFIX}(\d+)", p.stem))]
    return f"{RECORD_PREFIX}{(max(nums) + 1) if nums else 1:03d}"


def is_record_id(item_id: str) -> bool:
    return bool(re.fullmatch(rf"{RECORD_PREFIX}\d{{3,}}", item_id or ""))


def landed_claim(claim: Claim, page_id: str, page_name: str, pick: Pick, episode: str = "") -> Claim:
    """The held claim as a claim of the page: subject the page, everything else — id, predicate, object, source conversation,
    observer, trust, dates — as it was held, its own evidence spans first. The text keeps the label's own words, so a located
    span still backs every word; a part says so, and a label that is the page in other words says so too ("about <Page> itself"),
    while two reads that did not say the same leave the words as they were. The sentence the reader copied (the one that shows which page the fact
    is about) is recorded as one more evidence span, unless it is the claim's own."""
    data = claim.to_dict()
    data["subject"] = page_id
    if pick.scope == "part":
        data["text"] = f"{claim.text} (a part of {page_name})"
    elif pick.scope == "whole":
        data["text"] = f"{claim.text} (about {page_name} itself)"
    ev = list(data.get("evidence") or [])
    copied = {"episode": episode, "start": pick.start, "end": pick.end, "kind": pick.turn, "hash": pick.hash}
    if episode and pick.start >= 0 and not any(isinstance(e, dict) and (e.get("episode"), e.get("start"), e.get("end")) == (episode, pick.start, pick.end)
                           for e in ev):
        ev.append(copied)
    data["evidence"] = ev
    return Claim.from_dict(data)


def land_page(memory_path: Path, page_id: str, items: list[tuple[Item, Pick]], *, by: str, engine: str | None = None,
              cardinal: Callable[[str], bool] | None = None, today: str | None = None, rule: str = RULE,
              reason: str = REASON, extra: dict | None = None, close_empty: bool = True) -> Landed | None:
    """Write one page's claims, take them off their lines, write the settle's record. The caller holds the bank and commits
    ``paths``; ``None`` when nothing changes (everything is already there, or would clash with a single-valued belief).
    ``rule``, ``reason`` and ``extra`` (more keys for the record) are for a sibling that lands held facts by the same writer
    (`which_one_file`, ruling 83: a mention that could be two people, filed conversation by conversation); ``close_empty`` False
    leaves a line that holds nothing it knows how to keep for that caller to close (it keeps history entries too)."""
    from api.services import bank_index, episode_ids, predicates

    memory_path = Path(memory_path)
    path = memory_path / "entities" / f"{page_id}.md"
    if not path.is_file():
        return None
    parsed = markdown_parser.parse(path)
    try:
        claims = parse_claims(parsed.body, strict=True)
    except MalformedClaimsBlockError:
        return None
    cardinal = cardinal or predicates.build_cardinality_fn(memory_path)
    page_name = str((parsed.frontmatter or {}).get("name") or page_id)
    have = {c.id for c in claims}
    new: list[tuple[Item, Claim, Pick]] = []
    heal: dict[str, list[str]] = defaultdict(list)   # on the page already (an earlier write that did not finish): only taken off the line
    from api.services import which_one_file

    lines_now = {name.lower(): pending_store.held_line(memory_path, name) for name in {it.line for it, _p in items}}
    for it, pick in items:
        if it.claim.id in have:
            heal[it.line].append(it.claim.id)
            continue
        if which_one_file.withheld(lines_now.get(it.line.lower()), it.claim.to_dict(), page_id):
            continue   # ruling 83: a conversation it cites was ruled out for this page (or filed to another): it stays held
        # The page's own claims AND the ones accepted before this one in the same call: two held values of one
        # single-valued predicate never land together (this path does not go through the reconciler).
        same = [c for c in [*claims, *(n for _i, n, _p in new)] if c.valid_to is None and c.predicate == it.claim.predicate]
        if any(c.object == it.claim.object for c in same):
            continue   # the page already says it: nothing is lost by leaving it held, nothing is written twice
        if same and cardinal(it.claim.predicate):
            continue   # a single-valued belief the page already holds (or one landing just now): left for the person, never decided here
        new.append((it, landed_claim(it.claim, page_id, page_name, pick, it.episode), pick))
    if not new and not heal:
        return None
    paths: list[str] = []
    lines: list[str] = []
    ids: list[str] = []
    if new:
        markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, claims + [n for _i, n, _p in new]))
        ids = [n.id for _i, n, _p in new]
        paths.append(f"entities/{page_id}.md")
        ledger = memory_path / "entities" / f"{page_id}.claims.jsonl"
        if ledger.is_file():
            paths.append(f"entities/{page_id}.claims.jsonl")
    taken = defaultdict(list)
    for it, n, _p in new:
        taken[it.line].append(n.id)
    for line, cids in heal.items():
        taken[line].extend(cids)
    closed: list[dict] = []
    for line, cids in taken.items():
        pending_store.drop_released(memory_path, line, cids)
        left = pending_store.held_line(memory_path, line)
        if close_empty and left is not None and nothing_left(left):
            closed.append(left.to_dict())
            pending_store.release(memory_path, [line])
    paths.append(pending_store.PENDING_STORE_FILE)
    record_id = ""
    if new:
        spans = [{"episode": it.episode, "start": p.start, "end": p.end, "kind": p.turn, "claim_id": n.id}
                 for it, n, p in new]
        record_id = _next_record_id(memory_path)
        settled_dir = memory_path / "inbox" / SETTLED_DIR
        settled_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "group": "sleep", "rule": rule, "at": episode_ids.utc_now_iso(), "by": by, "by_kind": "sleep",
            "reason": reason, "answer": f"{len(new)} fact(s) said about {page_name}",
            "entity_id": page_id, "entity_name": page_name, "predicate": new[0][0].claim.predicate,
            "claim_id": new[0][1].id, "claim_ids": ids, "evidence": spans[0], "evidence_spans": spans,
            "lines": sorted({it.line for it, _n, _p in new}),
            "held": [it.claim.to_dict() for it, _n, _p in new], "closed_lines": closed, "landed": [n.to_dict() for _i, n, _p in new],
            "episodes": sorted({it.episode for it, _n, _p in new}),
            **({"engine": engine} if engine else {}),
            **(extra or {}),
        }
        markdown_parser.write(settled_dir / f"{record_id}.md",
                              {"kind": "landing", "question": f"What was said about {page_name}?",
                               "entity_id": page_id, "entity_name": page_name, "settled": record}, "")
        paths.append(f"inbox/{SETTLED_DIR}/{record_id}.md")
        source = new[0][0].episode
        lines.append(f"entities/{page_id}.md: updated (source: {source}, trigger: sleep/land-described)")
        lines.append(f"inbox/{SETTLED_DIR}/{record_id}.md: created (source: {source}, trigger: sleep/land-described)")
    lines.append(f"{pending_store.PENDING_STORE_FILE}: updated (source: {page_id}, trigger: sleep/land-described)")
    bank_index.invalidate(memory_path)
    markdown_parser.invalidate_pages(os.path.realpath(memory_path))
    return Landed(record_id, page_id, ids, paths, lines)


#: What a landing wrote and a later change would be the person's or a conversation's: the claim's identity and its words, and
#: whether it is still open. Everything else on a claim is bookkeeping Sleep keeps up every night (confidence, the decay
#: watermark and its day-placing `read_late`, `faded_by_age`, the sessions, episodes and reactions a restatement adds,
#: `recorded_at` / `recorded_ts`), and never makes the claim another claim.
LANDED_IDENTITY = ("id", "subject", "predicate", "object", "object_kind", "text", "valid_to", "superseded_by", "supersedes")


def as_written(now: Claim, wrote: dict) -> bool:
    """The claim on the page is still what the landing wrote: the same identity and words, still open (never closed,
    superseded or withdrawn), and every evidence span the landing recorded still cites its place. A restatement may add
    spans, and Sleep's nightly passes move the bookkeeping fields, neither of which is a change."""
    data = now.to_dict()
    if any(data.get(k) != wrote.get(k) for k in LANDED_IDENTITY):
        return False
    have = {(e.get("episode"), e.get("start"), e.get("end")) for e in data.get("evidence") or [] if isinstance(e, dict)}
    return all((e.get("episode"), e.get("start"), e.get("end")) in have
               for e in wrote.get("evidence") or [] if isinstance(e, dict))


def _gone(what: str = "A held line this settle took facts from") -> NotLandable:
    return NotLandable(f"{what} changed since; nothing was changed.")


def _places(memory_path: Path, names: list[str], held: list[Claim], closed: set[str]) -> None:
    """Every claim an undo is about to put back has a line to go to, with room — checked before anything is written.
    A line the record closed is recreated from the record; any other must still be held. :class:`NotLandable` otherwise."""
    for name in names:
        slug = sanitize_id(name)
        mine = [c for c in held if c.subject == slug]
        if not mine or name.lower() in closed:
            continue
        line = pending_store.held_line(memory_path, name)
        if line is None:
            raise _gone()   # released by promotion, taken, or gone: the facts would be written nowhere
        have = {d.get("id") for d in line.held_claims}
        if len(line.held_claims) + sum(1 for c in mine if c.id not in have) > pending_store.MAX_HELD_CLAIMS:
            raise _gone("A held line this settle took facts from is full and")


def undo(memory_path: Path, record_id: str) -> tuple[list[str], list[str], dict]:
    """Take back one landing: its claims leave the page (each only while it is still as the landing wrote it, whatever
    Sleep's bookkeeping did to it since), go back to their lines, the page is remembered as one the mention is not
    (`pending_store.mark_apart`), the record goes. Returns ``(paths, manifest lines, record)``; :class:`NotLandable` and
    nothing written when the page changed under a claim or a fact has no line to go back to; a held count that comes up short
    after the write puts every path back as it was."""
    from api.services import bank_index, claims_ledger

    memory_path = Path(memory_path)
    if not is_record_id(record_id):
        raise NotLandable("No such settled landing.")
    rec_path = memory_path / "inbox" / SETTLED_DIR / f"{record_id}.md"
    if not rec_path.is_file():
        raise NotLandable("No such settled landing.")
    rec = markdown_parser.parse(rec_path).frontmatter.get("settled")
    if not isinstance(rec, dict) or rec.get("rule") != RULE:
        raise NotLandable("No such settled landing.")
    page_id = str(rec.get("entity_id") or "")
    page_rel = f"entities/{page_id}.md"
    path = memory_path / page_rel
    landed = {str(d.get("id")): d for d in rec.get("landed") or [] if isinstance(d, dict)}
    names = [str(n) for n in rec.get("lines") or []]
    episodes = [str(e) for e in rec.get("episodes") or []]
    held = [Claim.from_dict(d) for d in rec.get("held") or [] if isinstance(d, dict)]
    closed_lines = [d for d in rec.get("closed_lines") or [] if isinstance(d, dict) and d.get("name")]
    # Everything is checked before anything is written.
    kept: list[Claim] | None = None
    parsed = None
    if path.is_file():
        parsed = markdown_parser.parse(path)
        try:
            claims = parse_claims(parsed.body, strict=True)
        except MalformedClaimsBlockError as exc:
            raise NotLandable("The page's claims could not be read; nothing was changed.") from exc
        for c in claims:
            if c.id in landed and not as_written(c, landed[c.id]):
                raise NotLandable("A fact this settle wrote was changed since; nothing was changed.")
        kept = [c for c in claims if c.id not in landed]
        if len(kept) == len(claims):
            kept = None
    _places(memory_path, names, held, {str(d["name"]).lower() for d in closed_lines})
    ledger_rel = claims_ledger.rel_for(page_rel) or ""
    snapshot = {rel: _bytes(memory_path / rel) for rel in (page_rel, ledger_rel, pending_store.PENDING_STORE_FILE) if rel}
    paths: list[str] = []
    lines: list[str] = []
    try:
        for d in closed_lines:
            pending_store.upsert(memory_path, pending_store.PendingEntity.from_dict(d))
        for name in names:
            slug = sanitize_id(name)
            mine = [c for c in held if c.subject == slug]
            if mine:
                pending_store.hold(memory_path, {slug: mine})
            pending_store.mark_apart(memory_path, name, [page_id], episodes)
        for name in names:   # the held count, as written: a claim that is not on its line was written nowhere
            slug = sanitize_id(name)
            mine = {c.id for c in held if c.subject == slug}
            line = pending_store.held_line(memory_path, name)
            if mine and (line is None or not mine <= {d.get("id") for d in line.held_claims}):
                raise _gone()
            if line is not None and page_id not in line.apart_pages():
                raise _gone()
        if kept is not None and parsed is not None:
            markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, kept))
            paths += [rel for rel in (page_rel, ledger_rel) if rel and ((memory_path / rel).exists() or snapshot.get(rel) is not None)]
            lines.append(f"{page_rel}: updated (source: {record_id}, trigger: sleep/land-described/undone)")
        rec_path.unlink()
    except BaseException:
        _restore(memory_path, snapshot)
        raise
    paths.append(pending_store.PENDING_STORE_FILE)
    lines.append(f"{pending_store.PENDING_STORE_FILE}: updated (source: {record_id}, trigger: sleep/land-described/undone)")
    bank_index.invalidate(memory_path)
    paths.append(f"inbox/{SETTLED_DIR}/{record_id}.md")
    lines.append(f"inbox/{SETTLED_DIR}/{record_id}.md: removed (source: {record_id}, trigger: sleep/land-described/undone)")
    return paths, lines, rec


# ---------------------------------------------------------------------------------------------------- the tail step


@dataclass
class Report:
    looked: int = 0
    read: int = 0
    calls: int = 0
    landed: int = 0
    pages: int = 0
    skipped: Counter = field(default_factory=Counter)
    paths: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)

    def skip(self, why: str, n: int = 1) -> None:
        self.skipped[why] += n


def _seen_file(memory_path: Path) -> Path:
    from api.services import auth, continuity_sessions

    return auth.cicada_home() / "described_landing_reads" / f"{continuity_sessions.bank_file_id(Path(memory_path))}.json"


def _seen(memory_path: Path) -> dict[str, str]:
    try:
        data = json.loads(_seen_file(memory_path).read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _memo_key(line: str, claim_id: str) -> str:
    """The memo's key: a hash of the line's slug and the claim's id, so the file outside the bank holds no label."""
    return hashlib.sha256(f"{sanitize_id(line)}|{claim_id}".encode()).hexdigest()[:24]


#: A read that ended in one of these says nothing about the fact (the reply was no answer, or its sentence is not in the
#: conversation): it is read again, never remembered as a no.
UNSETTLED = ("unusable_reply", "sentence_not_located")


def _remember(memory_path: Path, key: str, digest: str) -> None:
    """Hashes only, never a name or a word. A file that cannot be written only means a pair is read again."""
    try:
        data = _seen(memory_path)
        data[key] = digest
        path = _seen_file(memory_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


def _digest(memory_path: Path, group: Group, docs: Docs) -> str:
    """What the reader was shown, as a hash: the claims, the window and each candidate's name and summary. A read that left
    its claims held is not made again until one of these changes (the line, the conversation or a page)."""
    h = hashlib.sha256()
    conv = docs.conv(group.episode)
    for it in sorted(group.items, key=lambda i: i.claim.id):
        h.update(f"{it.claim.id}|{it.claim.text}|{it.start}|{it.end}".encode())
    if conv is not None:
        h.update(window_text(conv, window_for(conv, group.items)).encode())
    for pid in group.candidates:
        got = _page_text(memory_path, pid)
        h.update(f"|{pid}|{got[0]}|{got[1]}".encode() if got else f"|{pid}".encode())
    return h.hexdigest()[:16]


def _fresh(line: pending_store.PendingEntity, today: date) -> bool:
    """A conversation of the line was had in the last days (an episode id carries its local day)."""
    for ep in line.episodes():
        m = re.match(r"ep_(\d{4})-(\d{2})-(\d{2})_", str(ep))
        if m:
            try:
                if (today - date(int(m.group(1)), int(m.group(2)), int(m.group(3)))).days <= FRESH_DAYS:
                    return True
            except ValueError:
                continue
    return False


def nothing_left(line: pending_store.PendingEntity | None) -> bool:
    """A line that holds no claim, fact, link, question, summary or description: it can be closed."""
    return line is None or not (line.held_claims or line.key_facts or line.links or line.open_questions or line.summary
                                or line.description)


def order(groups: list[Group], reads: dict[str, float]) -> list[Group]:
    """The groups whose candidate pages are read most come first (`page_reads`), then by line — never the order the bank
    happens to list them."""
    def heat(g: Group) -> float:
        return max((reads.get(p, 0.0) for p in g.candidates), default=0.0)

    return sorted(groups, key=lambda g: (-heat(g), sanitize_id(g.line), g.episode))


async def tend(memory_path: Path, settings, ask: Callable, *, today: date | None = None, per_run: int = GROUPS_PER_RUN,
               engine: str | None = None, commit: Callable | None = None, plan: Plan | None = None) -> Report:
    """Read and land. ``ask(system, prompt)`` is the main model's call. Each page is one write and one commit of its own
    paths; the reads run outside any write. An engine failure stops the step (the groups are read again next run)."""
    from api.services import page_reads, web_settle

    memory_path = Path(memory_path)
    today = today or date.today()
    report = Report()
    plan = plan if plan is not None else await asyncio.to_thread(plan_bank, memory_path)
    report.looked = plan.labels
    for why, n in plan.skipped.items():
        report.skip(why, n)
    if not plan.groups:
        return report
    lines = {l.name: l for l in pending_store.load(memory_path)}
    docs = Docs(memory_path)
    try:
        reads = await asyncio.to_thread(page_reads.table, memory_path, today=today)
    except Exception:  # noqa: BLE001 - the order is a courtesy
        reads = {}
    seen = _seen(memory_path)
    fresh = [g for g in plan.groups if lines.get(g.line) and _fresh(lines[g.line], today)]
    fresh_ids = {id(g) for g in fresh}
    old = [g for g in plan.groups if id(g) not in fresh_ids]
    todo = order(fresh, reads)[:per_run] + order(old, reads)[:per_run]
    landing: dict[str, list[tuple[Item, Pick]]] = defaultdict(list)
    stopped: Exception | None = None
    for whole in todo:
        marks = {it.claim.id: await asyncio.to_thread(_digest, memory_path, whole.sub([it]), docs) for it in whole.items}
        todo_items = [it for it in whole.items if seen.get(_memo_key(it.line, it.claim.id)) != marks[it.claim.id]]
        report.skip("read_already", len(whole.items) - len(todo_items))
        if not todo_items:
            continue
        group = whole.sub(todo_items)
        report.read += 1
        try:
            got = await read_group(memory_path, group, docs, ask)
        except engine_errors.EngineError as exc:
            stopped = exc   # a pause: what was read so far still lands below, the rest waits for the next run
            break
        report.calls += got.calls
        if got.failed:
            report.skip("read_failed")
            continue
        for why in got.left.values():
            report.skip(why)
        for i, it in enumerate(group.items):
            if i in got.picks or str(got.left.get(i, "")).endswith(UNSETTLED):
                continue   # landed, or a read that said nothing: read again
            # what was left stands until the claim, the conversation or a candidate changes
            await asyncio.to_thread(_remember, memory_path, _memo_key(it.line, it.claim.id), marks[it.claim.id])
        for i, pick in got.picks.items():
            landing[pick.page].append((group.items[i], pick))
    for page_id, rows in landing.items():
        by = engine or "agent"
        # Every path the write can create or change: the page, the ledger its claims may spill into (past 64k characters),
        # the held lines and the settle's record. A restore puts back what was there and removes what was not.
        before = {rel: _bytes(memory_path / rel) for rel in
                  (f"entities/{page_id}.md", f"entities/{page_id}.claims.jsonl", pending_store.PENDING_STORE_FILE)}
        next_record = _next_record_id(memory_path)
        try:
            done = await asyncio.to_thread(land_page, memory_path, page_id, rows, by=by, engine=engine)
        except Exception as exc:  # noqa: BLE001 - one page never stops the others
            logger.warning(f"Described landing: a page was not written ({type(exc).__name__})")
            await asyncio.to_thread(_restore, memory_path, before, next_record)
            report.skip("write_failed")
            continue
        if done is None:
            report.skip("nothing_to_write")
            continue
        # As the sibling tail steps: the author is Cicada, the engine that served the read is the trailer's.
        message = web_settle.commit_message("Facts about a page landed", done.lines, authors=["cicada"], engine=engine)
        try:
            await asyncio.to_thread(commit or web_settle.commit_sync, memory_path, message, done.paths)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Described landing: a commit failed, undone ({type(exc).__name__})")
            await asyncio.to_thread(_restore, memory_path, before, done.record_id)
            report.skip("commit_failed")
            continue
        report.pages += 1
        report.landed += len(done.claim_ids)
        report.paths += done.paths
    if stopped is not None:
        report.skip("plan_limit" if isinstance(stopped, (engine_errors.EngineThrottled, engine_errors.EngineExhausted))
                    else "engine_error")
    return report


def _bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def _restore(memory_path: Path, before: dict[str, bytes | None], record_id: str = "") -> None:
    from api.services import bank_index

    for rel, data in before.items():
        target = Path(memory_path) / rel
        try:
            if data is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(data)
        except OSError:
            pass
    if record_id:
        (Path(memory_path) / "inbox" / SETTLED_DIR / f"{record_id}.md").unlink(missing_ok=True)
    bank_index.invalidate(memory_path)
    markdown_parser.invalidate_pages(os.path.realpath(memory_path))


async def run_tail(memory_path: Path, settings, *, user_triggered: bool, ask: Callable | None = None,
                   today: date | None = None) -> Report:
    """Sleep's tail step, inside the run's window: no engine is resolved and nothing is sent unless a held line is a label
    with a claim that passes every code gate and a conversation that names a page. A scheduled run reaches a plan only through the person's switch (ruling 4b), a
    plan limit is a pause (nothing is lost), no engine means no read. Never raises."""
    from api.services import full_name_join, same_name_tend

    memory_path = Path(memory_path)
    report = Report()
    try:
        plan = await asyncio.to_thread(plan_bank, memory_path)
        if not plan.groups:
            report.looked, report.skipped = plan.labels, plan.skipped
            return report
        engine = None
        if ask is None:
            strong, why = await same_name_tend.main_engine(settings, user_triggered=user_triggered)
            if strong is None:
                report.skip(why)
                return report
            engine = str(getattr(strong, "llm_mode", "") or "") or None

            async def ask(system: str, prompt: str) -> object:
                return await full_name_join.ask_main(strong, system, prompt)

            settings = strong
        return await tend(memory_path, settings, ask, today=today, engine=engine, plan=plan)
    except (engine_errors.EngineThrottled, engine_errors.EngineExhausted, engine_errors.EngineOverage):
        report.skip("plan_limit")
    except Exception as exc:  # noqa: BLE001 - landing never fails a Sleep
        logger.warning(f"Described landing stopped: {type(exc).__name__}")
        report.skip("error")
    return report
