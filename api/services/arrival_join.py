"""A first name joined to the person who newly appeared the same week — Sleep decides and reports (owner 2026-11-24, G245).

The owner met people at an event, connected with some of them that week, and wrote a few first names in a note. He wants
Cicada to tie the note's "<given-a>" to the "<given-a> <family-a>" who appeared in his LinkedIn connections (or his address
book) the same week, by itself, and let him say no ("yes ofc join. and this should happen accross sources").

**Two independent kinds of evidence, and nothing less.** The NAME (the first name is the given name of the full name) and the
TIME (both newly appeared within a week of each other). Name alone never joins ("I remember you mentioned some pairs that I'm
pretty sure have nothing to do with each other", ruling 74); time alone never does. Because a name and a date are thin for
people met at one event, more stands in front of the write: exactly one holder, exactly one arrival (counting namesakes wider
than a dormant row would suggest), no doubt and no history, a fresh directory, a conflict screen, and a two-read veto. A wrong
join tells the person things about someone who is someone else, so a miss is silent and costs nothing.

**This module decides; it writes through `arrival_join_write` and only when :data:`LIVE` is true.** It ships ``LIVE = False``:
the nightly step runs every rule and leaves a per-item report outside every bank (:func:`report_path`; the command
``python -m api.scripts.arrival_join_report``), and writes NOTHING to the bank. The coordinator reads that report on the real
bank, item by item, before a one-line change flips the constant — a synthetic battery measures the rule against its author's
picture of the world, only a real bank measures it against the world's.

**The rules** (:func:`decide`, pure; the first failure is the counted reason, never a name). Section numbers are the plan's 3.4:

1. (the step's) not a demo bank, not a replica, tree readable, the page not dirty.
2. The holder is a person page titled by ONE word of at least :data:`MIN_WORD` letters — not archived, not the owner's, not
   titled by a relation, not a second person of one name.
3. The given name matches by token equality — never a nickname, a sound, a spelling or an alias.
4. Exactly one holder: no other page or held line carries the word, as its name, an alias or the start of one.
5. Exactly one arrival, counting namesakes: rows of the two directories collapse by folded full name (a card and a connection
   of one name are ONE lead); exactly one lead has a day within :data:`WINDOW_DAYS` of the holder's. Then no other lead may
   carry a day within :data:`BLOCK_DAYS`, a fuzzy day whose range reaches that band, or no day at all with a profile link or a
   same-name ambiguity. A dormant old namesake does not block; any plausible same-season one does.
6. The arrival is waiting: no page holds its full name.
7. No doubt (`same_name_doubts`) and no history (a split or "different" answer, an alias or source the person removed, the
   person's own "Not them" on this pair).
8. Nothing already points elsewhere: the holder has no full-name alias, no profile naming someone else, and is in no candidate
   pair of `person_duplicates`.
9. The directory is fresh: looked at on or after the holder's day plus a week, or the join waits.
10. The conflict screen (no model): the page's own employer against the row's company; no word in common refuses.
11. The two-read veto (a model, the 74a / 74b pattern): two differently phrased reads each find nothing that fails to fit one
    person; one doubt, one unsure, one unreadable answer is no join.

**What "newly appeared" means, per directory.** A LinkedIn connection: its ``connected_on`` day, at ``day`` precision only (a
``week`` or ``month`` row is never THE arrival, and blocks when its range reaches the band). A Contacts card: the day the app
first saw it WAITING (`contacts_local.first_seen`, with its two guards against a bulk arrival); an unstamped card is dormant,
never an arrival and never a blocker. A note: its CREATED day (`created_at`) and only when it was not kept alive past a week
(a note's ``timestamp`` is its last edit, so a line added today to an old note must not look new); every other conversation:
its own ``timestamp`` day, never the day it was received or read, and never a source that is no time signal
(`episode_time`) or no words of the person's (a save, a feed, a tab group, a calendar entry).

**Privacy.** Nothing here names a directory row anywhere it persists: the report, a commit message, a record, a log line or a
ledger carries page ids (the bank's own slugs), days and hashes (a row's id is the directory's own hash), never a name, a
company, a headline, a link or an e-mail. The only things that read a row's company, position and headline are the conflict
screen (local) and the veto (the person's own engine, through `providers.resolve_llm_fn`, so the sensitive hold applies).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from api.services import bank_index, people_directory

#: **The switch.** False: the nightly step runs every rule, writes NOTHING to the bank and leaves a report outside every bank
#: for the coordinator to read per item. A one-line change flips it, only on that reading (plan 3.8).
LIVE = False

#: "The same week": the two first-seen days are at most this many days apart, either way, inclusive (an event spans a weekend).
WINDOW_DAYS = 7
#: A namesake whose day, or whose fuzzy day's range, reaches within this many days of the holder's blocks the join.
BLOCK_DAYS = 30
#: The shortest word a first-name page may be titled by (`person_duplicates.short_in_full`'s floor).
MIN_WORD = 3
#: How far a fuzzy precision's day may be off: a "3 weeks ago" is known to the week, a "2 months ago" to the month.
FUZZ_DAYS = {"week": 7, "month": 30}
#: A note kept alive longer than this between its creation and its last edit is a living note: it has no day.
LIVING_NOTE_DAYS = 7
#: The most candidates one night's veto reads (each is a pair of small reads); the rest wait for the next night.
MAX_VETOES = 6
#: A veto whose reply could not be read is tried again this many times, then left.
MAX_UNREAD_TRIES = 2

TRIGGER = "sleep/arrival-join"
CONNECTION = "connection"
CARD = "card"
#: Where the person's own notes keep their creation day (`notes_sync.CREATED_KEY`), and which origins are notes.
NOTE_ORIGINS = frozenset({"apple-notes", "notion-export"})
CREATED_KEY = "created_at"
#: A filing label is never anyone's words (`entity_resolver.CARD_REFUSED_SOURCES`).
NOT_WORDS = frozenset({"tab-group", "calendar", "calendar-local"})

REPORT_FILE = "arrival-join-report.json"
VETO_FILE = "arrival-join-veto.json"

#: Tokens of a company name that say nothing about which company it is.
_COMPANY_STOP = frozenset({"inc", "llc", "ltd", "co", "corp", "corporation", "gmbh", "sa", "ag", "bv", "plc", "the", "of", "and",
                           "group", "company", "limited", "holdings", "labs", "lab", "at", "for", "de"})

# --------------------------------------------------------------------------- the facts a decision stands on (no I/O)


@dataclass(frozen=True)
class Row:
    """One row of a directory outside the bank, as the rules see it. ``ref`` is a hash (a connection's own id, a card's id
    hashed): the only handle a report keeps."""
    ref: str
    kind: str                      # CONNECTION | CARD
    given: str                     # the folded given name, as one string ("mary ann" is a compound: no match)
    full: str                      # the folded full name ("given family"); '' when the row has no family name
    day: str | None = None         # ISO day; a connection's ``connected_on``, a card's first-seen day
    precision: str | None = None   # day | week | month (a card's is day, or none when unstamped)
    linked: bool = False           # a connection with a profile link
    dup: int = 0                   # a connection's same-name ambiguity (`Connection.dup`)
    waiting: bool = True           # no page holds it, nothing refuses it
    page_held: bool = False        # a page already holds this full name (name, alias or profile link)
    doubt: bool = False            # the bank holds a same-name doubt for the full name
    company: str = ""              # a connection's company, position, headline: read by the conflict screen and the veto only
    position: str = ""
    headline: str = ""
    slug: str = ""                 # a connection's profile slug, to compare with what the person removed
    history: str | None = None     # split | removed | refused: something the person said about this very pair


@dataclass(frozen=True)
class Holder:
    """The first-name page, with everything the rules ask of it. Built by :func:`gather`; plain data here."""
    page: str
    word: str                      # the page's title, folded, one token
    day: str | None = None         # the earliest day its own words give (3.3)
    day_from: str = ""             # conversation | meeting | note
    block: str | None = None       # a rule-2 refusal: owner, role, archived, not one word, second of its name ...
    others: int = 0                # rule 4: other pages and held lines carrying the word
    doubt: bool = False            # rule 7: the bank holds a same-name doubt for the word
    elsewhere: str | None = None   # rule 8: full_name_alias | profile_elsewhere | candidate_pair
    companies: tuple[str, ...] = ()   # the page's current employers (folded), for the conflict screen
    facts: tuple[str, ...] = ()       # the page's own claim texts, for the veto
    summary: str = ""
    excerpts: tuple[str, ...] = ()    # the person's own lines naming the word, for the veto


@dataclass(frozen=True)
class Case:
    holder: Holder
    rows: tuple[Row, ...]
    #: ``{kind: the day the directory was last looked at}`` for every directory the bank keeps; ``None`` = kept, stamp unknown.
    fresh: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Lead:
    """Rows collapsed by folded full name: a card and a connection of one name are one lead (#841)."""
    key: str
    rows: tuple[Row, ...]

    @property
    def day(self) -> str | None:
        days = sorted(r.day for r in self.rows if r.day and r.precision == "day")
        return days[0] if days else None

    def fuzzy(self) -> list[tuple[str, int]]:
        return [(r.day, FUZZ_DAYS[r.precision]) for r in self.rows if r.day and r.precision in FUZZ_DAYS]

    @property
    def refs(self) -> tuple[str, ...]:
        return tuple(r.ref for r in self.rows)

    @property
    def count(self) -> int:
        """How many people this lead may be: a card and a connection are one; two connections or two cards of one name are two."""
        return max(sum(1 for r in self.rows if r.kind == CONNECTION), sum(1 for r in self.rows if r.kind == CARD), 1)


@dataclass(frozen=True)
class Veto:
    """The two reads' answers: ``fits`` | ``conflict`` | ``unsure`` | ``unread`` each. Both ``fits`` to join."""
    answers: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return len(self.answers) == 2 and all(a == "fits" for a in self.answers)


@dataclass(frozen=True)
class Decision:
    page: str
    #: ``skip`` (a rule refused), ``candidate`` (every rule but the veto holds: the veto is next), ``join``.
    outcome: str
    reason: str
    refs: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    alias_key: str = ""            # a hash of the arrival's folded full name, never the name
    arrival_day: str | None = None
    holder_day: str | None = None
    delta: int | None = None
    conflict: str | None = None    # fact_conflict | None
    veto: tuple[str, ...] = ()
    counts: dict = field(default_factory=dict)

    @property
    def joins(self) -> bool:
        return self.outcome == "join"


# --------------------------------------------------------------------------- days


def parse_day(text) -> date | None:
    try:
        return date.fromisoformat(str(text or "")[:10]) if text else None
    except ValueError:
        return None


def gap(a, b) -> int | None:
    """Whole days between two ISO days (absolute); None when either is unreadable."""
    da, db = parse_day(a), parse_day(b)
    return abs((da - db).days) if da and db else None


def key_hash(folded_full: str) -> str:
    """A hash of a folded full name: how a refusal and a record name the arrival without keeping the name."""
    return hashlib.sha256(f"arrival\x00{folded_full}".encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- the rules (pure)


def leads_of(rows) -> list[Lead]:
    """Collapse rows by folded full name; a row with no family name is a lead of its own (it can never be an arrival)."""
    groups: dict[str, list[Row]] = {}
    for row in rows:
        groups.setdefault(row.full or f"~{row.ref}", []).append(row)
    return [Lead(key, tuple(g)) for key, g in groups.items()]


def _near(day: str | None, holder_day: str, days: int) -> bool:
    g = gap(day, holder_day)
    return g is not None and g <= days


def _blocks(lead: Lead, holder_day: str) -> str | None:
    """Why this OTHER lead blocks the join, or None. A dormant one — an old day, or no day and no link — does not."""
    if _near(lead.day, holder_day, BLOCK_DAYS):
        return "day_within_30"
    for day, fuzz in lead.fuzzy():
        if _near(day, holder_day, BLOCK_DAYS + fuzz):
            return "fuzzy_overlap"
    if any(r.kind == CONNECTION and not r.day and (r.linked or r.dup) for r in lead.rows):
        return "undated_linked"
    return None


def _significant(text: str) -> set[str]:
    return {t for t in people_directory.fold(text).split() if len(t) > 1 and t not in _COMPANY_STOP}


def conflict_screen(holder: Holder, rows) -> str | None:
    """The page's own employer against the row's company (no model). ``fact_conflict`` only when the page names a company, the
    row names one, and they share no significant word — the row's headline and position count as the row's words too, so a
    company the headline mentions is not a conflict. Nothing to compare is not a conflict. (A role that contradicts needs a
    reader of words; that is the veto's, never a word list's.)"""
    if not holder.companies:
        return None
    for row in rows:
        if not row.company.strip():
            continue
        theirs = _significant(f"{row.company} {row.headline} {row.position}")
        if not theirs:
            continue
        if not any(_significant(c) & theirs for c in holder.companies):
            return "fact_conflict"
    return None


def decide(case: Case, veto: Veto | None = None) -> Decision:
    """The one decision: rules 2 to 10 in order, the first failure its counted reason, then the veto. Pure."""
    h = case.holder
    counts: dict = {}

    def skip(reason: str, **kw) -> Decision:
        return Decision(h.page, "skip", reason, holder_day=h.day, counts=counts, **kw)

    # 2: the holder
    if h.block:
        return skip(h.block)
    # 3: the given name, by token equality
    rows = [r for r in case.rows if r.given == h.word]
    counts["namesakes"] = len(rows)
    if not rows:
        return skip("no_namesake")
    # 4: exactly one holder
    if h.others:
        return skip("other_holder")
    if not h.day:
        return skip("no_day")
    # 5: exactly one arrival, counting namesakes
    leads = leads_of(rows)
    window = [lead for lead in leads if _near(lead.day, h.day, WINDOW_DAYS)]
    counts["leads"] = len(leads)
    counts["in_window"] = sum(lead.count for lead in window)
    if not window:
        return skip("no_arrival")
    if sum(lead.count for lead in window) > 1:
        return skip("two_arrivals")
    lead = window[0]
    others = {lead2.key: why for lead2 in leads if lead2 is not lead and (why := _blocks(lead2, h.day))}
    counts["blockers"] = len(others)
    if others:
        return skip("namesake_block", refs=lead.refs)
    arrival_day = lead.day
    delta = gap(arrival_day, h.day)
    full = lead.rows[0].full
    common = dict(refs=lead.refs, kinds=tuple(sorted({r.kind for r in lead.rows})), arrival_day=arrival_day, delta=delta,
                  alias_key=key_hash(full) if full else "")
    if not full:
        return skip("arrival_no_family_name", **common)
    # 6: waiting
    if any(r.page_held for r in lead.rows):
        return skip("full_name_has_page", **common)
    if not all(r.waiting for r in lead.rows):
        return skip("arrival_not_waiting", **common)
    # 7: no doubt, no history
    if h.doubt or any(r.doubt for r in lead.rows):
        return skip("doubt", **common)
    if any(r.history for r in lead.rows):
        return skip("history", **common)
    # 8: nothing points elsewhere
    if h.elsewhere:
        return skip(h.elsewhere, **common)
    # 9: the directory is fresh
    need = parse_day(h.day) + timedelta(days=WINDOW_DAYS)
    for kind, stamp in sorted(case.fresh.items(), key=lambda kv: kv[0]):
        seen = parse_day(stamp)
        if seen is None or seen < need:
            counts["stale"] = kind
            return skip("directory_not_fresh", **common)
    # 10: the conflict screen
    conflict = conflict_screen(h, lead.rows)
    if conflict:
        return skip(conflict, conflict=conflict, **common)
    # 11: the veto
    if veto is None:
        return Decision(h.page, "candidate", "veto_pending", holder_day=h.day, counts=counts, **common)
    if not veto.passed:
        return skip("veto", veto=veto.answers, **common)
    return Decision(h.page, "join", "ok", holder_day=h.day, veto=veto.answers, counts=counts, **common)


# --------------------------------------------------------------------------- the report (outside every bank)


def report_path(bank: str) -> Path:
    """``$CICADA_HOME/people/<bank>/arrival-join-report.json`` — beside the directories the rules read, outside every bank
    and git, wiped with the bank (`people_directory.forget`). Page ids, days, hashes and counts only."""
    return people_directory.path(bank, REPORT_FILE)


def load_report(bank: str) -> dict:
    return people_directory.load_json(bank, REPORT_FILE)


def _item(case: Case, decision: Decision, *, live: bool) -> dict:
    h = case.holder
    rows = [r for r in case.rows if r.given == h.word]
    chosen = set(decision.refs)
    namesakes = []
    for r in rows:
        if r.ref in chosen:
            role = "arrival"
        elif h.day and _blocks(Lead(r.full or r.ref, (r,)), h.day):
            role = "blocker"
        else:
            role = "other"
        namesakes.append({"ref": r.ref, "kind": r.kind, "day": r.day, "precision": r.precision, "waiting": r.waiting,
                          "page": r.page_held, "linked": r.linked, "dup": r.dup, "role": role,
                          "gap": gap(r.day, h.day) if r.day and h.day else None})
    outcome = decision.outcome
    if outcome == "join":
        outcome = "join" if live else "would_join"
    return {"page": h.page, "holder_day": h.day, "day_from": h.day_from, "arrival_day": decision.arrival_day,
            "gap": decision.delta, "fresh": dict(case.fresh), "namesakes": namesakes,
            "alias_key": decision.alias_key or None, "conflict": decision.conflict or "none",
            "veto": list(decision.veto) if decision.veto else None, "decision": outcome, "reason": decision.reason,
            "counts": decision.counts}


def write_report(bank: str, items: list[dict], *, today: str, live: bool, tried: int, holders: int) -> dict:
    """Leave the night's reading outside every bank: one item per first-name page that has a namesake in a directory, and a
    count of every refusal across them. Overwritten each night."""
    reasons: dict[str, int] = {}
    for item in items:
        why = "would_join" if item["decision"] == "would_join" else item["reason"]
        reasons[why] = reasons.get(why, 0) + 1
    payload = {"v": 1, "live": bool(live), "ran_on": today, "holders_with_namesake": len(items), "first_name_pages": holders,
               "veto_reads": tried, "reasons": dict(sorted(reasons.items())), "items": items}
    people_directory.save_json(bank, REPORT_FILE, payload)
    return payload


# --------------------------------------------------------------------------- reading the bank and the directories (I/O)

_NOT_A_HOLDER = ("archived", "dropped")


def _fold(text) -> str:
    return people_directory.fold(text)


def _owner_ids(memory_path: Path) -> set[str]:
    from api.services import owner_identity

    try:
        return {owner_identity.resolve_observer(memory_path)}
    except Exception:  # noqa: BLE001 - an unreadable owner.json names no page; the flag still applies
        return set()


def _labels(fm: dict, stem: str) -> list[str]:
    return [x for x in people_directory.labels(fm, stem) if isinstance(x, str)]


def holder_block(fm: dict, stem: str, owners: set[str]) -> str | None:
    """Rule 2: why this page is not a first-name holder, or None. Pure over the page's frontmatter."""
    from api.services import role_people
    from api.services.id_utils import sanitize_id

    if str(fm.get("status") or "") in _NOT_A_HOLDER:
        return "holder_inactive"
    if fm.get("owner") is True or stem in owners:
        return "holder_owner"
    if fm.get(role_people.UNNAMED_KEY) or role_people.roles_of(fm):
        return "holder_role"
    name = str(fm.get("name") or stem.replace("-", " "))
    words = _fold(name).split()
    if len(words) != 1:
        return "holder_not_one_word"
    if len(words[0]) < MIN_WORD:
        return "holder_short_word"
    if stem != sanitize_id(name):
        return "holder_second_of_name"      # `sam-2`: a second person of one name is never a holder
    try:
        if role_people.parse(name, bare=True):
            return "holder_role"
    except Exception:  # noqa: BLE001
        pass
    return None


def episode_day(fm: dict | None) -> tuple[str | None, str]:
    """The day this episode's own words give a name — ``(day, kind)`` — or ``(None, "")``. 3.3: a conversation's own
    ``timestamp`` day (never the day it was received or read); never a source that is no time signal or no words of the
    person's; a note's day is its CREATED day and only when it was not kept alive past a week (its ``timestamp`` is its last
    edit)."""
    from api.services import authorship, episode_ids, episode_time, quiet_pages

    fm = fm or {}
    if not episode_time.counts_as_activity(fm) or quiet_pages.episode_kind(fm) != quiet_pages.CONVERSATION:
        return None, ""
    if str(fm.get("source") or "") in NOT_WORDS or str(fm.get("origin") or "") in NOT_WORDS:
        return None, ""
    if fm.get("locked_note") or authorship.is_saved(fm) or authorship.agent_saved(fm):
        return None, ""
    from api.services import meeting_transcripts

    folder = "folder" in (str(fm.get("source") or ""), str(fm.get("origin") or ""))
    if folder and not meeting_transcripts.is_meeting(fm):
        # A watched folder's file: its ``timestamp`` is the file's last-modified time when it was first read and no
        # later revision moves it, so it is neither a created day nor a mention's day. Only a meeting is dated.
        return None, ""
    modified = episode_ids.local_day(fm.get("timestamp"))
    if modified is None:
        return None, ""
    if str(fm.get("origin") or fm.get("source") or "") in NOTE_ORIGINS:
        created = episode_ids.local_day(fm.get(CREATED_KEY)) if fm.get(CREATED_KEY) else None
        if created is None or (modified - created).days > LIVING_NOTE_DAYS or created > modified:
            return None, ""
        return created.isoformat(), "note"
    return modified.isoformat(), "meeting" if folder else "conversation"


def _holder_day(memory_path: Path, fm: dict) -> tuple[str | None, str, list[str]]:
    best: tuple[str, str] | None = None
    used: list[str] = []
    for ep in fm.get("source_episodes") or []:
        ep = str(ep or "").split("#", 1)[0]
        if not ep.startswith("ep_"):
            continue
        entry = bank_index.file(memory_path, "episodes", f"{ep}.md")
        if entry is None:
            continue
        day, kind = episode_day(entry.frontmatter)
        if day and (best is None or day < best[0]):
            best = (day, kind)
            used = [ep]
        elif day and best and day == best[0]:
            used.append(ep)
    return (best[0], best[1], used) if best else (None, "", [])


def _doubted(memory_path: Path) -> tuple[set[str], set[str]]:
    """``(refs, folded names)`` the bank holds a same-name doubt for: every page id in a flagged page, a flagged pair or a
    pair held apart, and the names those pages carry."""
    from api.services import same_name_doubts

    try:
        pages, pairs = same_name_doubts.flagged(memory_path)
        refs = set(pages) | {r for p in pairs for r in p} | {r for p in same_name_doubts.pairs(memory_path) for r in p} \
            | {r for p in same_name_doubts.kept(memory_path) for r in p}
    except Exception:  # noqa: BLE001 - an unreadable doubt file refuses nothing it cannot name
        return set(), set()
    names = {_fold(r) for r in refs}
    for ref in refs:
        entry = bank_index.file(memory_path, "entities", f"{ref}.md")
        if entry is not None:
            names |= {_fold(x) for x in _labels(entry.frontmatter or {}, ref)}
    return refs, {n for n in names if n}


def _claims_of(memory_path: Path, page: str) -> list:
    from api.services import entity_relations

    return entity_relations._page_claims(memory_path, page)


def _companies_and_facts(memory_path: Path, page: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    companies, facts = [], []
    for c in _claims_of(memory_path, page):
        if c.valid_to is not None:
            continue
        text = " ".join(str(c.text or "").split())
        if text:
            facts.append(text[:220])
        if str(c.predicate or "").lower() == "works-at":
            obj = str(c.object or "").replace("-", " ") if c.object_kind == "node" else str(c.object or "")
            if _fold(obj):
                companies.append(_fold(obj))
    return tuple(dict.fromkeys(companies)), tuple(facts[:12])


def _excerpts(memory_path: Path, episodes: list[str], word: str) -> tuple[str, ...]:
    """Up to three lines of the person's own words that name ``word``, from the conversations that dated it."""
    out: list[str] = []
    for ep in episodes[:3]:
        entry = bank_index.file(memory_path, "episodes", f"{ep}.md")
        if entry is None:
            continue
        try:
            text = entry.body()
        except Exception:  # noqa: BLE001
            continue
        for line in text.splitlines():
            if f" {word} " in f" {_fold(line)} " and len(out) < 3:
                out.append(" ".join(line.split())[:240])
    return tuple(out)


def _summary(memory_path: Path, page: str) -> str:
    from api.services import markdown_parser

    try:
        body = markdown_parser.parse(Path(memory_path) / "entities" / f"{page}.md").body
    except Exception:  # noqa: BLE001
        return ""
    prose = body.split("```", 1)[0]
    return " ".join(prose.split())[:600]


def refusals(memory_path: Path) -> list[dict]:
    """The person's own "Not them" on a pair whose arrival had no page: ``[{holder, key, on}]`` from
    ``_merge_rejected.yaml`` (`merge_rejections.arrival_refusals`)."""
    from api.services import merge_rejections

    return merge_rejections.arrival_refusals(memory_path)


def _profile_slugs(fm: dict) -> tuple[set[str], bool]:
    """``(the LinkedIn profile slugs this page lists, whether it lists any other account)`` — a page that already names a
    profile names a person; the arrival's must be that one or the page points elsewhere (rule 8)."""
    from api.services import fact_sources, linkedin_people, person_photo

    slugs: set[str] = set()
    other = False
    for source in fact_sources.as_sources(fm.get("sources")):
        url = linkedin_people.profile_url(source.get("ref"))
        if url:
            slugs.add(url.rsplit("/", 1)[1].lower())
        elif person_photo.is_own_account(source):
            other = True
    return slugs, other


def _removed_for(fm: dict) -> tuple[set[str], set[str]]:
    """``(folded aliases the person removed, profile slugs the person removed)`` from the page's own frontmatter."""
    from api.services import fact_sources, linkedin_people, page_edits

    aliases = {_fold(a) for a in page_edits.removed_aliases(fm)}
    slugs: set[str] = set()
    for tomb in fm.get(fact_sources.REMOVED_KEY) or []:
        url = linkedin_people.profile_url(tomb.get("ref") if isinstance(tomb, dict) else None)
        if url:
            slugs.add(url.rsplit("/", 1)[1].lower())
    return aliases, slugs


@dataclass
class Gathered:
    cases: list[Case]
    holders: int = 0           # one-word person pages looked at
    directories: dict = field(default_factory=dict)   # {kind: rows} counts, for the log (counts only)


def directory_rows(memory_path: Path, bank: str, page_keys: set[str], doubt_names: set[str]) -> tuple[list[Row], dict]:
    """Every row of both directories as :class:`Row`, and ``{kind: the day it was last looked at}``. Public readers only:
    `linkedin_people.arrivals` (the connections with where each stands in this bank) and `contacts_local` (the waiting cards
    and when each first showed). Empty on a demo bank."""
    from api.services import contacts_local, demo_guard, linkedin_people, saved_lists

    rows: list[Row] = []
    fresh: dict = {}
    if demo_guard.is_demo(memory_path):
        return rows, fresh
    connections = linkedin_people.arrivals(memory_path, bank)
    if connections:
        held = linkedin_people.load_directory(bank)
        stamps = [str(held.get("exported_on") or "")[:10]]
        try:
            entry = saved_lists.last(memory_path, "linkedin-connections")
            if entry.get("outcome") == "read" and entry.get("read_at"):
                stamps.append(str(entry["read_at"])[:10])
        except Exception:  # noqa: BLE001 - an unreadable list file only makes the stamp older
            pass
        fresh[CONNECTION] = max((s for s in stamps if parse_day(s)), default=None)
        for a in connections:
            if a.owner:
                continue
            c = a.connection
            full = _fold(f"{c.first} {c.last}") if c.first and c.last else ""
            rows.append(Row(
                ref=c.id, kind=CONNECTION, given=_fold(c.first), full=full, day=a.day, precision=a.precision,
                linked=bool(c.url), dup=c.dup, waiting=a.waiting, page_held=bool(a.pages),
                doubt=a.doubted or a.refused or (full in doubt_names), company=c.company, position=c.position,
                headline=c.headline, slug=(linkedin_people.profile_url(c.url) or "").rsplit("/", 1)[-1].lower()))
    cards = contacts_local.load_waiting(bank)
    seen, synced = contacts_local.first_seen(bank)
    if cards or synced:
        fresh[CARD] = synced
    for card in cards:
        if not contacts_local.card_live(card):
            continue
        given, family = _fold(card.get("given_name")), _fold(card.get("family_name"))
        full = f"{given} {family}" if given and family else ""
        day = seen.get(contacts_local.card_hash(card["id"]))
        keys = contacts_local.name_keys(card.get("given_name"), card.get("family_name"))
        held = bool(keys & page_keys)
        rows.append(Row(ref=contacts_local.card_hash(card["id"]), kind=CARD, given=given, full=full, day=day,
                        precision="day" if day else None, waiting=not held, page_held=held,
                        doubt=bool(full and full in doubt_names)))
    return rows, fresh


def gather(memory_path: Path, *, bank: str | None = None) -> Gathered:
    """Every first-name page with at least one namesake in a directory, as a :class:`Case`. Reads the bank and the two
    directories once; writes nothing. Public readers of the directories only."""
    from api.services import pending_store

    memory_path = Path(memory_path)
    bank = bank or memory_path.name
    owners = _owner_ids(memory_path)
    pages: dict[str, dict] = {}
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("type") or "") == "person" and str(fm.get("status") or "") != "dropped":
            pages[f.stem] = fm
    page_keys = {k for stem, fm in pages.items() for label in _labels(fm, stem) if (k := _fold(label))}
    _doubt_refs, doubt_names = _doubted(memory_path)
    rows, fresh = directory_rows(memory_path, bank, page_keys, doubt_names)
    out = Gathered([], directories={k: sum(1 for r in rows if r.kind == k) for k in (CONNECTION, CARD)})
    if not rows:
        return out
    by_given: dict[str, list[Row]] = {}
    for r in rows:
        by_given.setdefault(r.given, []).append(r)
    try:
        held_lines = [(_fold(line.name), [_fold(a) for a in line.aliases]) for line in pending_store.load(memory_path)
                      if str(line.type or "") == "person"]
    except Exception:  # noqa: BLE001 - an unreadable store holds nothing it can name
        held_lines = []
    refused = {(r["holder"], r["key"]) for r in refusals(memory_path)}
    for stem, fm in sorted(pages.items()):
        words = _fold(str(fm.get("name") or stem.replace("-", " "))).split()
        if len(words) != 1 or words[0] not in by_given:
            continue
        word = words[0]
        out.holders += 1
        block = holder_block(fm, stem, owners)
        namesakes = [r for r in by_given[word]]
        day, day_from, used = (None, "", []) if block else _holder_day(memory_path, fm)
        carriers = 0
        for other, ofm in pages.items():
            if other == stem:
                continue
            for label in _labels(ofm, other):
                folded = _fold(label)
                if folded == word or folded.startswith(word + " "):
                    carriers += 1
                    break
        for name, aliases in held_lines:
            if any(x == word or x.startswith(word + " ") for x in [name, *aliases]):
                carriers += 1
        removed_aliases, removed_slugs = _removed_for(fm)
        slugs, other_account = _profile_slugs(fm)
        marked: list[Row] = []
        for r in namesakes:
            history = None
            if r.full and (r.full in removed_aliases):
                history = "removed"
            elif r.slug and r.slug in removed_slugs:
                history = "removed"
            elif r.full and (stem, key_hash(r.full)) in refused:
                history = "refused"
            marked.append(replace(r, history=history) if history else r)
        elsewhere = None
        if any(len(_fold(a).split()) > 1 for a in _labels(fm, stem)[1:]):
            elsewhere = "full_name_alias"
        elif other_account or (slugs and not any(r.slug in slugs for r in marked if r.slug)):
            elsewhere = "profile_elsewhere"
        companies, facts = ((), ()) if block else _companies_and_facts(memory_path, stem)
        holder = Holder(page=stem, word=word, day=day, day_from=day_from, block=block, others=carriers,
                        doubt=bool(stem in _doubt_refs or word in doubt_names), elsewhere=elsewhere,
                        companies=companies, facts=facts,
                        summary="" if block else _summary(memory_path, stem),
                        excerpts=() if block else _excerpts(memory_path, used, word))
        out.cases.append(Case(holder, tuple(marked), dict(fresh)))
    return out


def with_pairs(memory_path: Path, cases: list[Case], decisions: list[Decision]) -> list[Case]:
    """Rule 8's last check, made only for a case that has passed everything else (it reads every pair of people pages, so it
    is never paid for a page a cheaper rule already refused): a holder in any candidate pair of `person_duplicates` points
    elsewhere, and so reaches no veto. Returns the cases with ``elsewhere`` set where it does."""
    from api.services import person_duplicates

    reach = {d.page for d in decisions if d.outcome == "candidate"}
    if not reach:
        return cases
    try:
        in_pair = {p for pair in person_duplicates.candidates(Path(memory_path)) for p in (pair.a, pair.b)}
    except Exception as exc:  # noqa: BLE001 - never a night's failure; the veto and the report still stand
        logger.warning(f"Arrival join: candidate pairs unreadable ({type(exc).__name__})")
        return cases
    return [replace(c, holder=replace(c.holder, elsewhere=c.holder.elsewhere or "candidate_pair"))
            if c.holder.page in reach and c.holder.page in in_pair else c for c in cases]


# --------------------------------------------------------------------------- the two-read veto (a model)

SYSTEM = ("You check, from what a person's own memory holds about a first name and from one directory entry, whether anything "
          "fails to fit them being ONE person, and you answer in JSON.")

PROMPT = """A person met several people at an event and wrote a first name ("{word}") in their own notes. Later the same week someone with that first name appeared in their contacts. Only the first name and the week link them. Decide whether ANYTHING here fails to fit the two being one person.

WHAT THE PERSON'S MEMORY HOLDS ABOUT "{word}":
{facts}

THE PERSON'S OWN WORDS NAMING "{word}":
{excerpts}

THE DIRECTORY ENTRY (what the contact's own profile says):
- company: {company}
- position: {position}
- headline: {headline}

Answer with one of:
- "fits": nothing here stops them being one person (a missing detail is not a reason).
- "conflict": something here cannot be true of one person (a different employer, a different line of work, a place, an age, a relation). Copy the words that show it as "quote".
- "unsure": anything else.
A wrong join tells the person things about someone who is someone else; when in doubt say "unsure". Decide only from what is written above.

Answer in JSON only: {{"verdict": "fits" | "conflict" | "unsure", "quote": "words copied from above", "reason": "one short sentence"}}
"""

SKEPTIC = """You are the sceptical reader. Look for any reason the two are DIFFERENT people before you answer, and say "fits" only if you find none.

THE DIRECTORY ENTRY (what the contact's own profile says):
- company: {company}
- position: {position}
- headline: {headline}

WHAT THE PERSON'S MEMORY HOLDS ABOUT THE FIRST NAME "{word}", and nothing else links them but that name and the week:
{facts}

THE PERSON'S OWN WORDS NAMING "{word}":
{excerpts}

Answer with one of: "fits" (no reason found), "conflict" (copy the words that show it as "quote"), "unsure" (anything else). A wrong join tells the person things about someone who is someone else.

Answer in JSON only: {{"verdict": "fits" | "conflict" | "unsure", "quote": "words copied from above", "reason": "one short sentence"}}
"""


def _bullets(items) -> str:
    items = [str(i) for i in items if i]
    return "\n".join(f"- {i}" for i in items) if items else "- (nothing recorded yet)"


def veto_prompts(case: Case, decision: Decision) -> tuple[str, str]:
    """The two differently phrased prompts for one candidate. They carry the page's facts and the person's own words and the
    entry's company, position and headline — never the entry's name, link or e-mail."""
    h = case.holder
    row = next((r for r in case.rows if r.ref in decision.refs and r.kind == CONNECTION), None)
    facts = list(h.facts) + ([h.summary] if h.summary and not h.facts else [])
    fields = dict(word=h.word, facts=_bullets(facts), excerpts=_bullets(h.excerpts),
                  company=(row.company if row else "") or "(not given)", position=(row.position if row else "") or "(not given)",
                  headline=(row.headline if row else "") or "(not given)")
    return PROMPT.format(**fields), SKEPTIC.format(**fields)


def veto_digest(case: Case, decision: Decision) -> str:
    a, b = veto_prompts(case, decision)
    h = hashlib.sha256()
    for part in (case.holder.page, decision.alias_key, a, b):
        h.update(str(part).encode("utf-8", "replace"))
        h.update(b"\0")
    return h.hexdigest()[:20]


def _verdict(parsed) -> str:
    if not isinstance(parsed, dict):
        return "unread"
    word = str(parsed.get("verdict") or "").strip().lower()
    return word if word in ("fits", "conflict", "unsure") else "unread"


Judge = Callable[[str, str], Awaitable[object]]


async def read_veto(case: Case, decision: Decision, judge: Judge) -> Veto:
    """Two separate reads of the same material, differently phrased and ordered. A read that fails counts as unread, which is no
    join; an engine failure (a plan limit) stops the step, the answers it had stay cached."""
    from api.services import engine_errors

    answers: list[str] = []
    for prompt in veto_prompts(case, decision):
        try:
            parsed = await judge(SYSTEM, prompt)
        except asyncio.CancelledError:
            raise
        except engine_errors.EngineError:
            raise
        except Exception as exc:  # noqa: BLE001 - a read that failed has read nothing
            logger.debug(f"Arrival join read failed: {type(exc).__name__}")
            parsed = None
        answers.append(_verdict(parsed))
    return Veto(tuple(answers))


def _veto_cache(bank: str) -> dict:
    return people_directory.load_json(bank, VETO_FILE)


def _remember_veto(bank: str, digest: str, answers: tuple[str, ...], today: str) -> None:
    held = _veto_cache(bank)
    rows = held.get("reads") if isinstance(held.get("reads"), dict) else {}
    prior = rows.get(digest) if isinstance(rows.get(digest), dict) else {}
    tries = int(prior.get("tries") or 0) + (1 if "unread" in answers else 0)
    rows[digest] = {"answers": list(answers), "on": today, "tries": tries}
    if len(rows) > 400:
        rows = dict(list(rows.items())[-400:])
    people_directory.save_json(bank, VETO_FILE, {"v": 1, "reads": rows})


def _cached_veto(bank: str, digest: str) -> Veto | None:
    """An answer already read for exactly this material (a stand never read again until something it read changes), or None
    to read. An unread one is tried again until :data:`MAX_UNREAD_TRIES`."""
    row = (_veto_cache(bank).get("reads") or {}).get(digest)
    if not isinstance(row, dict):
        return None
    answers = tuple(str(a) for a in row.get("answers") or ())
    if "unread" in answers and int(row.get("tries") or 0) < MAX_UNREAD_TRIES:
        return None
    return Veto(answers) if len(answers) == 2 else None


# --------------------------------------------------------------------------- the nightly step


@dataclass
class Report:
    looked: int = 0                 # first-name pages with a namesake
    candidates: int = 0             # every rule but the veto held
    reads: int = 0                  # veto reads (pairs of model calls) paid tonight
    would_join: int = 0
    joined: int = 0
    reasons: dict = field(default_factory=dict)
    joins: list = field(default_factory=list)       # LIVE only: [(Decision, Case)] the caller writes
    skipped: str = ""

    def skip(self, why: str) -> None:
        self.skipped = self.skipped or why


async def _engine_judge(settings, *, user_triggered: bool) -> tuple[Judge | None, str]:
    """``(judge, "")`` — the engine's main model as the veto's call — or ``(None, why)``: no engine, or a scheduled run the
    person's plan switch does not allow (ruling 4b). The same door 74a and 74b read through (`same_name_tend.main_engine`,
    `full_name_join.ask_main`); a key's spend limit is that door's. Nothing is sent here."""
    from api.services import full_name_join, same_name_tend

    strong, why = await same_name_tend.main_engine(settings, user_triggered=user_triggered)
    if strong is None:
        return None, why

    async def judge(system: str, prompt: str) -> object:
        return await full_name_join.ask_main(strong, system, prompt)

    return judge, ""


async def run_tail(memory_path: Path, settings, *, user_triggered: bool, no_model: bool = False, today: date | None = None,
                   judge: Judge | None = None, live: bool | None = None) -> Report:
    """Sleep's tail step: decide, report, and — only when :data:`LIVE` — hand back the joins to write. Engine-free through
    rule 10; the veto's engine is resolved only when a candidate reaches it (a scheduled run reaches a plan only through the
    person's switch, ruling 4b; a plan limit is a pause; no engine means no veto and so no join). Never raises."""
    from api.services import engine_errors

    memory_path = Path(memory_path)
    bank = memory_path.name
    day = (today or date.today()).isoformat()
    live = LIVE if live is None else live
    report = Report()
    try:
        gathered = await asyncio.to_thread(gather, memory_path, bank=bank)
        cases = gathered.cases
        decisions = [decide(c) for c in cases]
        cases = await asyncio.to_thread(with_pairs, memory_path, cases, decisions)
        decisions = [decide(c) for c in cases]
        report.looked = len(cases)
        pending = [i for i, d in enumerate(decisions) if d.outcome == "candidate"]
        report.candidates = len(pending)
        vetoes: dict[int, Veto] = {}
        tried = 0
        use: Judge | None = judge
        for i in pending:
            digest = veto_digest(cases[i], decisions[i])
            cached = _cached_veto(bank, digest)
            if cached is not None:
                vetoes[i] = cached
                continue
            if no_model:
                report.skip("no_model")
                continue
            if tried >= MAX_VETOES:
                report.skip("max_vetoes")
                break
            if use is None:
                use, why = await _engine_judge(settings, user_triggered=user_triggered)
                if use is None:
                    report.skip(why)
                    break
            try:
                veto = await read_veto(cases[i], decisions[i], use)
            except (engine_errors.EngineThrottled, engine_errors.EngineExhausted, engine_errors.EngineOverage):
                report.skip("plan_limit")
                break
            tried += 1
            report.reads += 1
            await asyncio.to_thread(_remember_veto, bank, digest, veto.answers, day)
            vetoes[i] = veto
        items: list[dict] = []
        final: list[Decision] = []
        for i, (case, d) in enumerate(zip(cases, decisions)):
            if d.outcome == "candidate" and i in vetoes:
                d = decide(case, vetoes[i])
            elif d.outcome == "candidate":
                d = replace(d, reason="veto_unavailable" if report.skipped else "veto_pending")
            final.append(d)
            items.append(_item(case, d, live=live))
            reason = "would_join" if d.joins and not live else d.reason
            report.reasons[reason] = report.reasons.get(reason, 0) + 1
            if d.joins:
                report.would_join += 0 if live else 1
                if live:
                    report.joins.append((d, case))
        if items or load_report(bank):   # a bank with nothing to say leaves no folder behind
            await asyncio.to_thread(write_report, bank, items, today=day, live=live, tried=tried, holders=gathered.holders)
    except (engine_errors.EngineThrottled, engine_errors.EngineExhausted, engine_errors.EngineOverage):
        report.skip("plan_limit")
    except Exception as exc:  # noqa: BLE001 - the join never fails a Sleep
        logger.warning(f"Arrival join stopped: {type(exc).__name__}")
        report.skip("error")
    return report


def printable(bank: str) -> dict:
    """The last report as the command prints it (:mod:`api.scripts.arrival_join_report`): exactly what was written."""
    return load_report(bank)


def dumps(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False)
