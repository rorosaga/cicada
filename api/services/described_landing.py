"""What was said about a thing nobody named lands on the page it was said about (2026-11-25, G148, G98, ruling 41a).

Stage 1 sometimes writes a label for a thing the conversation only described ("<Feature> redesign", "<Project> extraction
worker"; `coined_names`). Stage 2 gives such a label no page from one conversation, so what was said about it waits in a
held line (`pending_store`) that nothing will ever name again. Measured on a real bank (real values redacted), 1,351 of
5,912 held lines were such labels, and in 200 of them a claim's located words sit in a sentence that names exactly one
existing page. A fact the person (or a named speaker) said in a sentence that names one of their pages, about a part of it,
is a fact about that page, and should be readable there with that sentence as its evidence.

**The rule is code first, the model second, and a fact that fails either stays held** (leaving a fact held is always
allowed; a wrong landing is the one failure that matters). A claim lands only when ALL of these hold:

1. the line is a label: a concept or project whose name and aliases no text of any conversation it cites says
   (`coined_names.said_in` is ``nowhere`` in every one; one that cannot be read is not a label);
2. the label was the claim's SUBJECT (a claim held as the label's object stays held), the claim is open, not an event;
3. the claim's evidence is a located span, current as the source is now (`source_spans.Source.status`), inside a turn the
   person's own (`promotion.person_kinds`: in a meeting a named speaker's, in a group chat only the person's) — never an
   assistant's, an agent note's or a saved page's words;
4. its sentence is short, names exactly ONE page — counted over every page of the bank, a person's and the owner's
   included, ambiguous names included, with the claim's own other endpoint taken out of the count — and that page is a
   project, tool or concept, active, not the owner's and not one the person said the mention is not (`apart`). A sentence
   that names a person and a project ("<person> told me the importer is slow") names two, and nothing lands;
5. the claim's own subject is said in that sentence: every distinctive word of the label that is not a word of the page's
   own name (the label's other words are what the sentence describes), whole and folded, as ONE run of words (in any order),
   and none of them names what something is to a thing ("competitor", "owner", "client": `RELATIONAL`);
6. and the sentence STATES the part: that run sits right beside the page's name joined by containment or possession only
   ("the <part> of <Page>", "<Page>'s <part>", "<Page> <part>"), never by "for", "with", "using" or a verb
   ("I use <Tool> for the <part>" names a tool that is not the whole).

Then the engine's MAIN model reads it twice, once as `part_landing.confirms` already does for a name the pair judge called
a part (it must agree the label is a part of the page: the two rules agree where they meet), and once on the sentences
(`SYSTEM`/`PROMPT` here, one call a page): "is this fact about that page or a part of it, said by the person?". Anything
but "part" or "whole" for a claim, an unreadable answer, a failed call, no engine: the claim is left held.

**What landing means.** The claim is written on the page as a claim OF the page: subject the page, predicate and object as
held, id kept, evidence span, source conversation, observer, trust and dates unchanged, its text kept with the label's own
words and marked ``(a part of <Page>)`` when it is a part — never re-worded by a model, so a located span still backs every
word. The line keeps whatever did not land (`pending_store.drop_released`) and is closed only when nothing is left. The page's
`source_episodes` and `last_referenced` are NOT moved: the conversation is no new mention for decay or promotion unless it
already counted. A page gets one settle per run: one commit of its own paths, one record `inbox/settled/land-NNN.md`
under "Settled by Sleep" with the sentences shown, undoable as one (`undo`: the claims go back to the line, and the person's
undo is remembered as `apart`, so the page is never offered the mention again).

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
from api.services.claims import Claim, MalformedClaimsBlockError, is_event, parse_claims, write_claims
from api.services.id_utils import sanitize_id

RULE = "land_described"
RECORD_PREFIX = "land-"
SETTLED_DIR = "settled"
REASON = "What you said about a part of this page, in a sentence that names it, was held under a label nobody said."

#: The pages a part can belong to. A person, the owner, a company, a place, an event, a media record or a skill is never the
#: thing a label's fact is about (a "part" of a person is a different claim, and a media page's parts are its own).
TARGET_TYPES = frozenset({"project", "tool", "concept"})
ACTIVE = frozenset({"active", "decaying", ""})
MAX_SENTENCE = 400
#: A single-word page name this short is a common word more often than a name.
MIN_SINGLE_NAME = 4
#: Pairs (a line and the page it would land on) read by the model per run, per bucket (old, and fresh: said in the last days).
PAIRS_PER_RUN = 25
FRESH_DAYS = 3
MAX_CLAIMS_PER_READ = 8
CONTEXT_CHARS = 700

_SENTENCE = re.compile(r"[^.!?\n]+")
_WORD = re.compile(r"[^\W_]+", re.U)
_MARKER = re.compile(r"(?:user|assistant|human|you|me|speaker:[^:\n]{1,60}):[ \t]*", re.I)
#: Words a label's distinctiveness is never counted on.
_STOP = frozenset("the and for with from into onto this that these those its our their his her are was were has have had "
                  "new old one two part page thing".split())
#: A label whose words name what something is TO a thing (its rival, its owner, its client) is about that other thing, not
#: a part of this one. A closed English list: another language, or a word not here, is the second reading's.
RELATIONAL = frozenset("""competitor competitors rival rivals alternative alternatives successor successors predecessor
predecessors replacement replacements client clients customer customers user users owner owners author authors creator
creators founder founders maintainer maintainers contributor contributors investor investors sponsor sponsors team teams
manager managers boss employee employees partner partners supplier suppliers vendor vendors friend friends mentor mentors
fork forks clone clones copy copies""".split())
_CONTAINS = frozenset({"of", "in", "within", "inside", "from", "on", "at"})
_DETS = frozenset({"the", "a", "an", "our", "my", "their", "its", "this", "that"})

SYSTEM = ("You decide whether a fact the person said is about a named thing of theirs, or a part of it, from the words you "
          "are given, and answer in JSON.")

PROMPT = """A person's knowledge graph holds the things they work on. Sleep read the conversation sentences below, said by the person themselves, and wrote each fact under a label of its own ("{label}") that nobody said in those words. Each sentence names exactly one thing the graph has a page for: A. If you agree a fact is about A or one of its parts (a feature, stage, component, task, bug, plan or aspect of A), it is written on A's page; a wrong yes puts a belief about one thing on another thing's page, and a no costs little (the fact stays held).

A: {page}
A's page:
{body}

What was read about the label (Sleep's own summary): {summary}

{items}

For each numbered item answer:
- "part": the fact is about a part, feature, stage, task or aspect of A, and the sentence says it belongs to A;
- "whole": the fact is about A itself and the label only described it;
- "no": anything else. Answer "no" when the fact is about another thing the sentence names or only mentions (a tool A uses, a person, an event, a place); when A is only where or when something happened or what something is used with; when the sentence says the thing is separate from A, or it is the person's own life or opinion about something other than A's part; or when you are not sure.

Respond with JSON only:
{{"claims": [{{"n": 1, "verdict": "part" | "whole" | "no"}}]}}
"""


# ---------------------------------------------------------------------------------------------------- the pages' names


def _fold_words(text: str) -> list[str]:
    return [text_fold.fold(w) for w in _WORD.findall(str(text or ""))]


@dataclass(frozen=True)
class Mention:
    """A page name found in a sentence: its words' positions and the pages that bear that name (more than one: ambiguous)."""
    start: int
    end: int
    pages: frozenset[str]


@dataclass
class Page:
    id: str
    type: str
    owner: bool
    status: str
    words: frozenset[str]


class PageNames:
    """Every name and alias of every page of the bank, to find which pages a sentence names. Persons, the owner, archived pages
    included: a sentence that names them is not a sentence about one thing. A name two pages bear is kept as ambiguous."""

    def __init__(self, pages: list[dict]) -> None:
        owners: dict[tuple, set[str]] = defaultdict(set)
        self.pages: dict[str, Page] = {}
        for p in pages:
            names = [p["name"], *p["aliases"]]
            words: set[str] = set()
            for n in names:
                key = tuple(_fold_words(n))
                if not key or (len(key) == 1 and len(key[0]) < MIN_SINGLE_NAME):
                    continue
                owners[key].add(p["id"])
                words.update(key)
            self.pages[p["id"]] = Page(p["id"], p["type"], p["owner"], p["status"], frozenset(words))
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


# ---------------------------------------------------------------------------------------------------- the sentence


def sentence_around(text: str, start: int, end: int) -> tuple[int, int] | None:
    """The sentences ``[start, end)`` lies in, as one range of ``text``; ``None`` when they run past :data:`MAX_SENTENCE`."""
    first = last = None
    for m in _SENTENCE.finditer(text):
        if first is None and m.start() <= start < m.end():
            first = m.start()
        if m.start() < end <= m.end() or (m.start() <= max(end - 1, start) < m.end()):
            last = m.end()
        if first is not None and last is not None:
            break
    if first is None or last is None or last <= first:
        return None
    a, b = first, last
    while a < b and text[a].isspace():
        a += 1
    marker = _MARKER.match(text, a, b)
    if marker:   # a turn's own marker line ("user: ", "speaker:<label>: ") is nobody's words
        a = marker.end()
    return (a, b) if b - a <= MAX_SENTENCE else None


def windows(words: list[str], wanted: list[str]) -> list[tuple[int, int]]:
    """Where the label's distinctive words stand as ONE run of the sentence (any order: a label is often the same words
    in another order): ``[(first index, end index)]``. Words that are only somewhere in the sentence are no run."""
    k, want = len(wanted), set(wanted)
    return [(i, i + k) for i in range(len(words) - k + 1) if set(words[i:i + k]) == want]


def states_part(words: list[str], page_at: Mention, runs: list[tuple[int, int]]) -> bool:
    """Whether the sentence joins the label's run of words to the page's name by containment or possession only: the run sits
    just before the name behind one of "of / in / within / inside / from / on / at" (and articles), or just after it
    ("<Page>'s <part>", "<Page> <part>", behind articles only). A verb, "for", "with" or "using" between them is no part."""
    for a, b in runs:
        if b <= page_at.start:
            between = words[b:page_at.start]
            core = [w for w in between if w not in _DETS]
            if len(core) == 1 and core[0] in _CONTAINS and len(between) <= 3:
                return True
        elif a >= page_at.end:
            between = words[page_at.end:a]
            core = [w for w in between if w not in _DETS]
            if (not core or core == ["s"]) and len(between) <= 3:
                return True
    return False


def label_words(label: str, page_words: frozenset[str]) -> list[str]:
    """The distinctive words of a label that are not a word of the page's own name (what the sentence has to describe)."""
    out = []
    for w in _fold_words(label):
        if len(w) >= 3 and w not in _STOP and w not in page_words and w not in out:
            out.append(w)
    return out


# ---------------------------------------------------------------------------------------------------- the candidates


@dataclass
class Item:
    """One claim that passed every code gate: it may land on ``page`` if the second reading agrees."""
    line: str                 # the held line's name (its key)
    claim: Claim
    page: str
    episode: str
    start: int                # the located words of the claim
    end: int
    turn: str                 # whose turn: user | speaker
    sentence: tuple[int, int]
    rule: str = RULE

    @property
    def line_slug(self) -> str:
        return sanitize_id(self.line)


@dataclass
class Plan:
    """What the gates decided for a bank (or a part of it): the items, and counts of what each gate turned away."""
    items: list[Item] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)
    lines: int = 0
    labels: int = 0
    claims: int = 0


class Docs:
    """Episode documents read once each: ``(frontmatter, text)``, or ``None`` for one that cannot be read."""

    def __init__(self, memory_path: Path) -> None:
        self.memory_path, self._seen = Path(memory_path), {}

    def get(self, episode: str):
        if episode not in self._seen:
            doc = evidence.source_document(self.memory_path, episode) if str(episode).startswith("ep_") else None
            self._seen[episode] = doc
        return self._seen[episode]


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


def _turn_of(doc, start: int) -> str:
    """The role of the turn ``start`` lies in (``user``, ``speaker``, ``assistant`` …) — recomputed from the document."""
    fm, body = doc
    text = evidence.mask_labels(body)
    for t in evidence.turns(text, override=authorship.of(fm), gaps=evidence.gap_ranges(fm, body)):
        if t.start <= start < t.end:
            return t.role
    return ""


def gate_line(line: pending_store.PendingEntity, docs: Docs, names: Callable[[], PageNames], plan: Plan) -> list[Item]:
    """The claims of one held line that pass every code gate, with a count of what turned each other one away."""
    out: list[Item] = []
    slug = sanitize_id(line.name)
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
        item = _gate_claim(line, claim, docs, names(), plan)
        if item is not None:
            out.append(item)
    return out


def _gate_claim(line, claim: Claim, docs: Docs, names: PageNames, plan: Plan) -> Item | None:
    spans = [e for e in claim.evidence if e.is_span()]
    if not spans:
        plan.skipped["no_located_words"] += 1
        return None
    why = "no_located_words"
    for ev in spans:
        doc = docs.get(ev.episode)
        if doc is None:
            why = "source_unreadable"
            continue
        src = source_spans.Source.of(ev.episode, doc[0], doc[1])
        if src.status(ev.start, ev.end, ev.hash) not in (source_spans.CURRENT, source_spans.GROWN):
            why = "span_stale_or_held"
            continue
        turn = _turn_of(doc, ev.start)
        if turn not in promotion.person_kinds(doc[0]):
            why = "not_the_persons_turn"
            continue
        text = doc[1]
        sent = sentence_around(text, ev.start, ev.end)
        if sent is None:
            why = "sentence_too_long"
            continue
        page, reason = _page_for(line, claim, text[sent[0]:sent[1]], names)
        if page is None:
            why = reason
            continue
        return Item(line=line.name, claim=claim, page=page, episode=ev.episode, start=ev.start, end=ev.end, turn=turn,
                    sentence=sent)
    plan.skipped[why] += 1
    return None


def _page_for(line, claim: Claim, sentence: str, names: PageNames) -> tuple[str | None, str]:
    """``(the one page the sentence is about, "")`` — or ``(None, why not)``."""
    words = _fold_words(sentence)
    other = {str(claim.object or "")} if claim.object_kind != "literal" else set()
    found = [m for m in names.mentions(words) if not (m.pages <= other)]
    if not found:
        return None, "names_no_page"
    ids = {p for m in found for p in m.pages}
    if len(ids) > 1:
        return None, "names_more_than_one_page"
    if any(len(m.pages) > 1 for m in found):
        return None, "name_is_ambiguous"
    page = names.pages.get(next(iter(ids)))
    if page is None or page.owner or page.type not in TARGET_TYPES or page.status not in ACTIVE:
        return None, "page_may_not_hold_a_part"
    if page.id in line.apart_pages():
        return None, "person_said_not_that_page"
    wanted = label_words(line.name, page.words)
    if not wanted:
        return None, "label_adds_nothing"
    if not set(wanted) <= set(words):
        return None, "label_not_said_here"
    if set(wanted) & RELATIONAL:
        return None, "label_names_a_relation"
    runs = windows(words, wanted)
    if not runs:
        return None, "label_words_not_one_phrase"
    if not any(states_part(words, m, runs) for m in found):
        return None, "no_part_relation"
    return page.id, ""


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
        if not is_label(line, docs):
            plan.skipped["line_is_not_a_label"] += 1
            continue
        plan.labels += 1
        plan.items.extend(gate_line(line, docs, names, plan))
    return plan


# ---------------------------------------------------------------------------------------------------- the second reading


def _context(text: str, sentence: tuple[int, int]) -> str:
    a, b = sentence
    pad = max(0, (CONTEXT_CHARS - (b - a)) // 2)
    return " ".join(text[max(0, a - pad):b + pad].split())


def prompt_for(label: str, summary: str, page_name: str, page_body: str, rows: list[tuple[str, str, str]]) -> str:
    from api.services.claims import strip_claims_block

    items = "\n\n".join(f"Item {i}:\nThe person said: {ctx}\nThe fact written about the label: {fact}" for i, (ctx, fact, _s)
                        in enumerate(rows, 1))
    body = strip_claims_block(page_body or "").strip()[:1500] or "(empty)"
    return PROMPT.format(label=label, page=page_name, body=body, summary=(summary or "").strip()[:500] or "(empty)",
                         items=items)


def verdicts_of(parsed: object, n: int) -> dict[int, str]:
    """``{item number: "part" | "whole"}`` for the items the answer says yes to; every other shape is no."""
    out: dict[int, str] = {}
    rows = parsed.get("claims") if isinstance(parsed, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            k = int(row.get("n"))
        except (TypeError, ValueError):
            continue
        verdict = str(row.get("verdict") or "").strip().lower()
        if 1 <= k <= n and verdict in ("part", "whole"):
            out[k] = verdict
    return out


async def read(memory_path: Path, settings, line: pending_store.PendingEntity, page_id: str, items: list[Item], docs: Docs, *,
               ask: Callable | None = None, part_read: Callable | None = None) -> dict[int, str]:
    """``{index into items: "part" | "whole"}`` — the claims the engine's main model agrees are about the page. Two calls at
    most: `part_landing.confirms` (the label is a part of the page, as the pair judge's second reading asks it), then the
    sentences. An engine failure propagates (the caller pauses); any other failure is no claim landing."""
    from api.services import entity_resolver, part_landing, same_name_tend

    entity = _page_text(memory_path, page_id)
    if entity is None:
        return {}
    page_name, page_body = entity
    confirm = part_read or part_landing.confirms
    try:
        agreed = await confirm(line.name, line.summary or line.description, line.episodes(), page_name, page_body, settings,
                               memory_path=memory_path)
    except engine_errors.EngineError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Described landing: part reading failed: {type(e).__name__}")
        return {}
    if not agreed:
        return {}
    rows, picked = [], []
    for i, it in enumerate(items):
        doc = docs.get(it.episode)
        if doc is None or len(picked) >= MAX_CLAIMS_PER_READ:
            continue
        rows.append((_context(doc[1], it.sentence), it.claim.text, ""))
        picked.append(i)
    if not rows:
        return {}
    prompt = prompt_for(line.name, line.summary or line.description, page_name, page_body, rows)
    ask = ask or entity_resolver._same_name_ask
    try:
        parsed = await ask(same_name_tend.main_tier(settings), SYSTEM, prompt)
    except engine_errors.EngineError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Described landing: reading failed: {type(e).__name__}")
        return {}
    said = verdicts_of(parsed, len(rows))
    return {picked[k - 1]: v for k, v in said.items()}


def _page_text(memory_path: Path, page_id: str) -> tuple[str, str] | None:
    path = Path(memory_path) / "entities" / f"{page_id}.md"
    try:
        parsed = markdown_parser.parse(path)
    except Exception:  # noqa: BLE001
        return None
    return str((parsed.frontmatter or {}).get("name") or page_id), parsed.body


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


def landed_claim(claim: Claim, page_id: str, page_name: str, verdict: str) -> Claim:
    """The held claim as a claim of the page: subject the page, everything else — id, predicate, object, evidence, source
    conversation, observer, trust, dates — as it was held. The text keeps the label's own words, so a located span still
    backs every word, and a part says so."""
    data = claim.to_dict()
    data["subject"] = page_id
    if verdict == "part":
        data["text"] = f"{claim.text} (a part of {page_name})"
    return Claim.from_dict(data)


def land_page(memory_path: Path, page_id: str, items: list[tuple[Item, str]], *, by: str, engine: str | None = None,
              cardinal: Callable[[str], bool] | None = None, today: str | None = None) -> Landed | None:
    """Write one page's claims, take them off their lines, write the settle's record. The caller holds the bank and commits
    ``paths``; ``None`` when nothing changes (everything is already there, or would clash with a single-valued belief)."""
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
    new: list[tuple[Item, Claim, str]] = []
    heal: dict[str, list[str]] = defaultdict(list)   # on the page already (an earlier write that did not finish): only taken off the line
    for it, verdict in items:
        if it.claim.id in have:
            heal[it.line].append(it.claim.id)
            continue
        same = [c for c in claims if c.valid_to is None and c.predicate == it.claim.predicate]
        if any(c.object == it.claim.object for c in same):
            continue   # the page already says it: nothing is lost by leaving it held, nothing is written twice
        if same and cardinal(it.claim.predicate):
            continue   # a single-valued belief the page already holds: left for the person, never decided here
        new.append((it, landed_claim(it.claim, page_id, page_name, verdict), verdict))
    if not new and not heal:
        return None
    paths: list[str] = []
    lines: list[str] = []
    ids: list[str] = []
    if new:
        markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, claims + [n for _i, n, _v in new]))
        ids = [n.id for _i, n, _v in new]
        paths.append(f"entities/{page_id}.md")
        ledger = memory_path / "entities" / f"{page_id}.claims.jsonl"
        if ledger.is_file():
            paths.append(f"entities/{page_id}.claims.jsonl")
    taken = defaultdict(list)
    for it, n, _v in new:
        taken[it.line].append(n.id)
    for line, cids in heal.items():
        taken[line].extend(cids)
    closed: list[dict] = []
    for line, cids in taken.items():
        pending_store.drop_released(memory_path, line, cids)
        left = pending_store.held_line(memory_path, line)
        if left is not None and nothing_left(left):
            closed.append(left.to_dict())
            pending_store.release(memory_path, [line])
    paths.append(pending_store.PENDING_STORE_FILE)
    record_id = ""
    if new:
        spans = [{"episode": it.episode, "start": it.sentence[0], "end": it.sentence[1], "kind": it.turn} for it, _n, _v in new]
        record_id = _next_record_id(memory_path)
        settled_dir = memory_path / "inbox" / SETTLED_DIR
        settled_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "group": "sleep", "rule": RULE, "at": episode_ids.utc_now_iso(), "by": by, "by_kind": "sleep",
            "reason": REASON, "answer": f"{len(new)} fact(s) said about a part of {page_name}",
            "entity_id": page_id, "entity_name": page_name, "predicate": new[0][0].claim.predicate,
            "claim_id": new[0][1].id, "claim_ids": ids, "evidence": spans[0], "evidence_spans": spans,
            "lines": sorted({it.line for it, _n, _v in new}),
            "held": [it.claim.to_dict() for it, _n, _v in new], "closed_lines": closed, "landed": [n.to_dict() for _i, n, _v in new],
            "episodes": sorted({it.episode for it, _n, _v in new}),
            **({"engine": engine} if engine else {}),
        }
        markdown_parser.write(settled_dir / f"{record_id}.md",
                              {"kind": "landing", "question": f"What was said about parts of {page_name}?",
                               "entity_id": page_id, "entity_name": page_name, "settled": record}, "")
        paths.append(f"inbox/{SETTLED_DIR}/{record_id}.md")
        source = new[0][0].episode
        lines.append(f"entities/{page_id}.md: updated (source: {source}, trigger: sleep/land-described)")
        lines.append(f"inbox/{SETTLED_DIR}/{record_id}.md: created (source: {source}, trigger: sleep/land-described)")
    lines.append(f"{pending_store.PENDING_STORE_FILE}: updated (source: {page_id}, trigger: sleep/land-described)")
    bank_index.invalidate(memory_path)
    markdown_parser.invalidate_pages(os.path.realpath(memory_path))
    return Landed(record_id, page_id, ids, paths, lines)


def undo(memory_path: Path, record_id: str) -> tuple[list[str], list[str], dict]:
    """Take back one landing: its claims leave the page (each only while it is still as it was written), go back to their
    lines, the page is remembered as one the mention is not (`pending_store.mark_apart`), the record goes. Returns
    ``(paths, manifest lines, record)``; :class:`NotLandable` and nothing written when the page changed under a claim."""
    from api.services import bank_index

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
    path = memory_path / "entities" / f"{page_id}.md"
    landed = {str(d.get("id")): d for d in rec.get("landed") or [] if isinstance(d, dict)}
    paths: list[str] = []
    lines: list[str] = []
    if path.is_file():
        parsed = markdown_parser.parse(path)
        try:
            claims = parse_claims(parsed.body, strict=True)
        except MalformedClaimsBlockError as exc:
            raise NotLandable("The page's claims could not be read; nothing was changed.") from exc
        for c in claims:
            if c.id in landed and json.dumps(c.to_dict(), sort_keys=True) != json.dumps(landed[c.id], sort_keys=True):
                raise NotLandable("A fact this settle wrote was changed since; nothing was changed.")
        kept = [c for c in claims if c.id not in landed]
        if len(kept) != len(claims):
            markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, kept))
            paths.append(f"entities/{page_id}.md")
            lines.append(f"entities/{page_id}.md: updated (source: {record_id}, trigger: sleep/land-described/undone)")
    for d in rec.get("closed_lines") or []:
        if isinstance(d, dict) and d.get("name"):
            pending_store.upsert(memory_path, pending_store.PendingEntity.from_dict(d))
    names = [str(n) for n in rec.get("lines") or []]
    episodes = [str(e) for e in rec.get("episodes") or []]
    held = [Claim.from_dict(d) for d in rec.get("held") or [] if isinstance(d, dict)]
    for name in names:
        slug = sanitize_id(name)
        mine = [c for c in held if c.subject == slug]
        if mine:
            pending_store.hold(memory_path, {slug: mine})
        pending_store.mark_apart(memory_path, name, [page_id], episodes)
    paths.append(pending_store.PENDING_STORE_FILE)
    lines.append(f"{pending_store.PENDING_STORE_FILE}: updated (source: {record_id}, trigger: sleep/land-described/undone)")
    rec_path.unlink()
    bank_index.invalidate(memory_path)
    paths.append(f"inbox/{SETTLED_DIR}/{record_id}.md")
    lines.append(f"inbox/{SETTLED_DIR}/{record_id}.md: removed (source: {record_id}, trigger: sleep/land-described/undone)")
    return paths, lines, rec


# ---------------------------------------------------------------------------------------------------- the tail step


@dataclass
class Report:
    looked: int = 0
    read: int = 0
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


def _digest(items: list[Item], docs: Docs) -> str:
    h = hashlib.sha256()
    for it in sorted(items, key=lambda i: i.claim.id):
        doc = docs.get(it.episode)
        h.update(it.claim.id.encode())
        h.update((doc[1][it.sentence[0]:it.sentence[1]] if doc else "").encode())
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


def order(pairs: list[tuple[str, str]], reads: dict[str, float]) -> list[tuple[str, str]]:
    """The pages read most come first (`page_reads`), then by name — never the order the bank happens to list them."""
    return sorted(pairs, key=lambda p: (-reads.get(p[1], 0.0), p[1], p[0]))


async def tend(memory_path: Path, settings, ask: Callable, *, today: date | None = None, per_run: int = PAIRS_PER_RUN,
               part_read: Callable | None = None, engine: str | None = None, commit: Callable | None = None,
               plan: Plan | None = None) -> Report:
    """Read and land. ``ask(system, prompt)`` is the main model's call. Each page is one write and one commit of its own
    paths; the reads run outside any write. An engine failure stops the step (the pairs are read again next run)."""
    from api.services import page_reads, web_settle

    memory_path = Path(memory_path)
    today = today or date.today()
    report = Report()
    plan = plan if plan is not None else await asyncio.to_thread(plan_bank, memory_path)
    report.looked = plan.labels
    for why, n in plan.skipped.items():
        report.skip(why, n)
    if not plan.items:
        return report
    lines = {l.name: l for l in pending_store.load(memory_path)}
    docs = Docs(memory_path)
    by_pair: dict[tuple[str, str], list[Item]] = defaultdict(list)
    for it in plan.items:
        by_pair[(it.line, it.page)].append(it)
    try:
        reads = await asyncio.to_thread(page_reads.table, memory_path, today=today)
    except Exception:  # noqa: BLE001 - the order is a courtesy
        reads = {}
    seen = _seen(memory_path)
    fresh = [p for p in by_pair if lines.get(p[0]) and _fresh(lines[p[0]], today)]
    old = [p for p in by_pair if p not in set(fresh)]
    todo = order(fresh, reads)[:per_run] + order(old, reads)[:per_run]
    landing: dict[str, list[tuple[Item, str]]] = defaultdict(list)
    for pair in todo:
        items = by_pair[pair]
        key = f"{sanitize_id(pair[0])}|{pair[1]}"
        mark = _digest(items, docs)
        if seen.get(key) == mark:
            report.skip("read_already")
            continue
        report.read += 1

        async def _ask(_settings, system, prompt):
            return await ask(system, prompt)

        said = await read(memory_path, settings, lines[pair[0]], pair[1], items, docs, ask=_ask, part_read=part_read)
        await asyncio.to_thread(_remember, memory_path, key, mark)   # a no stands until a sentence or a claim changes
        for i, verdict in said.items():
            landing[pair[1]].append((items[i], verdict))
    for page_id, rows in landing.items():
        by = engine or "agent"
        before = {rel: _bytes(memory_path / rel) for rel in
                  (f"entities/{page_id}.md", pending_store.PENDING_STORE_FILE)}
        try:
            done = await asyncio.to_thread(land_page, memory_path, page_id, rows, by=by, engine=engine)
        except Exception as exc:  # noqa: BLE001 - one page never stops the others
            logger.warning(f"Described landing: a page was not written ({type(exc).__name__})")
            await asyncio.to_thread(_restore, memory_path, before)
            report.skip("write_failed")
            continue
        if done is None:
            report.skip("nothing_to_write")
            continue
        message = web_settle.commit_message("Facts about a part landed", done.lines, authors=[by], engine=engine)
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
                   part_read: Callable | None = None, today: date | None = None) -> Report:
    """Sleep's tail step, inside the run's window: no engine is resolved and nothing is sent unless a held line is a label
    with a claim that passes every code gate. A scheduled run reaches a plan only through the person's switch (ruling 4b), a
    plan limit is a pause (nothing is lost), no engine means no read. Never raises."""
    from api.services import full_name_join, same_name_tend

    memory_path = Path(memory_path)
    report = Report()
    try:
        plan = await asyncio.to_thread(plan_bank, memory_path)
        if not plan.items:
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
        return await tend(memory_path, settings, ask, today=today, part_read=part_read, engine=engine, plan=plan)
    except (engine_errors.EngineThrottled, engine_errors.EngineExhausted, engine_errors.EngineOverage):
        report.skip("plan_limit")
    except Exception as exc:  # noqa: BLE001 - landing never fails a Sleep
        logger.warning(f"Described landing stopped: {type(exc).__name__}")
        report.skip("error")
    return report
