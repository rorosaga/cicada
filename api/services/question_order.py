"""The order of the inbox: the expected change in what actually gets read (TODO ruling 71, 2026-11-06).

Rodrigo (2026-11-06): "the questions should have in order the impact they might have on current accesses knowledge,
and things that might have big impact." One function, ``Tables.score``, orders all three places a person meets the
list - ``load_inbox`` (so ``GET /inbox`` and Home), ``inbox_catchup.select`` (the catch-up chat) and
``cicada_check_nudges(mode="ask")`` - and the order is **derived on read from the record, never stored** (the stored
``priority`` no longer moves it; it stays on disk and on the wire for older clients).

**One order everywhere** (Rodrigo, 2026-11-06: "The same score orders every queue ... A page's queue must not fall back
to raw priority"). Every other place that lists or picks questions goes through :func:`ranked` (``cicada_check_nudges``
``list`` mode, recall's open-question block, the recall hook's pointer) or the served order (``web_settle.candidates``,
the app's ``orderIndex``); ``search_service`` drops priority from its tie-break. ``test_question_order_gate.py`` fails on
a new sort keyed on a question's raw priority.

    score(q) = p(q) x stake(q) / effort(q) x (FLOOR + exposure) x sqrt(seen(q)) x freshness(q)

* ``p`` - how likely an answer changes anything against what happens if it is never asked (:data:`P`). A conflict is
  answered into a verdict (.9); a decay question mostly retires on its own when ignored (.3); an informational
  conflict is shown, never asked (.05).
* ``stake`` - 1.5 when the answer decides who someone is (``asks: name``, or a duplicate pair of two people), .5 for the
  grouped links review, else 1.
* ``effort`` - 1.5 for a question that needs words (``required_input: freetext``), else 1.
* ``exposure`` - how much of the page is being read now: ``1 - (1 - use)(1 - reads)`` of the busier page of the question.
  ``use`` is :mod:`page_use` (derived from conversations, works with no counter); ``reads`` is
  :func:`page_reads.reads_fraction` of the page's counted reads (an empty or absent counter is 0, so the order degrades
  to ``use`` alone). :data:`FLOOR` lets a large question on a page nobody opens still surface.
* ``seen`` - how many of the facts this answer changes are in front of a reader: ``min(SHOWN, reach x visibility)``.
  ``reach`` is what the resolver changes (claims a merge moves, the contested claims of a conflict, the claims a
  decay covers; a plain clarification adds one claim, so 1). ``visibility(N) = min(1, sqrt(SHOWN / N))`` for the ``N``
  claims on the page they live on: a read shows about :data:`SHOWN` claims, and is aimed by words, so dilution is the
  square root of the share, not the share. **The owner's own page does not dilute** (Rodrigo, 2026-11-06, judging the
  real top 10: facts about the person matter most, and a recent one fell to 298th under their page's size).
* ``freshness`` - a fact said long ago asks less (Rodrigo, 2026-11-06: "the questions in regards to the amounts of <a-payment> are extremely old and in this case shouldn't they be lower impact? The impact formulation should
  apply to the question queues in all entities."). ``freshness = relief + (1 - relief) x fade`` and
  ``fade = max(FADE_FLOOR, 0.5 ** (age / half_life))``. The **age** counts from when the thing was SAID. For a conflict,
  the freshest of its contested options: an option on a claim the page holds, :func:`source_refresh.said_on` of that
  claim (its latest dated conversation, the codebase's one "day last said"); a claim only the option holds (the new side
  of a conflict is stored nowhere else), the conversation the option names, ``observed_at`` (``valid_from``) only when
  it names none and no other option has a date; an option with no claim, the question's ``source_episode``, never
  ``observed_at``, which holds the day the question was RAISED. A memory export entry or a feed item says nothing about
  when (:func:`episode_time.counts_as_activity`): it counts only when no contested option has a real date, and then as "no later than" its id's day, so an undated fact is not fresh
  for ever. For a divergence, clarification or follow-up the ``source_episode`` id's date. **Never**
  ``last_referenced``, ``created_date`` or ``updated_date``: a later re-reference or a re-asked question bumps those for
  something said a year ago. No date, no fade; a future date is age 0. The **half-life** is ln2 / the page's
  weekly decay rate from :func:`decay_policy.resolve` (durable ~243 days, active ~97, volatile ~32 - no constant per
  class here); an evergreen page never fades, **except the owner's own**, whose class means "never archived", not
  "every fact stays true", and which fades at the ``active`` rate. **Relief** keeps an old fact that is still in daily
  use: ``max over the question's pages of reads_fraction(reads) x visibility(claims on that page)``, so a page opened
  daily is read, but opening a huge hub daily does not rescue every old fact on it, the owner's page included: there the
  size only stops diluting the facts an answer changes, or a daily look at that page would exempt everything on it. An
  empty or absent counter is relief 0.
  ``asks: still`` fades (Rodrigo, 2026-11-06), from its claim's last saying, at the holding page's rate, relieved by its
  topic page's reads. What does **not** fade: who someone is (``merge_suggestion``, ``asks: name``, a held-name release,
  Rodrigo, 2026-11-06), ``decay`` (age is what it asks about, and its ``p`` already accounts for it), and a removal,
  normalization, page edit, ``asks: sources`` review or ``sensitive`` hold (not a fact someone said).

**One type at a time** (Rodrigo, 2026-11-06: the top was a wall of "same as?", 9 of 10). The score stays what it is;
:func:`spaced` takes the list in score order and lets at most :data:`RUN_LIMIT` questions of one :func:`family` run in a
row, bringing the best question of another family forward when a run reaches it. The first place is always the top
score, a family's own order never changes, and a family runs on when nothing else is left. A question shown, never asked
(informational) is never brought forward and does not break a run. Every list passes through it, so one order holds
everywhere; a subset (a page's queue, what a topic's ask finds) is spaced among itself, or keeps the served order.

**Every constant here is judgment** on two recorded answers by the person (there is no outcome data to fit): see
``docs/architecture/features.md``, "The order is the person's use", for the four formulations compared on a synthetic
bank (``test_question_order.py``) and for how it can be wrong. Nothing is a setting.

A claim count is a raw count of ``{"id": "`` lines in the page and its ledger, memoised by file stamp - no parse, no
body read for a page no question names. A question this cannot score falls back to its stored priority, per item: one
bad item never costs the list.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from loguru import logger

from api.services import bank_index, decay_policy, entity_types, episode_ids, episode_time, page_reads, page_use

SHOWN = 30
FLOOR = 0.1
#: ``sensitive`` holds have no reach in pages; they sit on the formula's own scale (it runs ~0.01 to ~6), above a typical
#: question and below a very large merge. The app draws them as a top card whatever their place here.
SENSITIVE_SCORE = 3.0
#: A fact said long ago still asks a little: the fade never goes below this (judgment, like the rest).
FADE_FLOOR = 0.05
#: At most this many questions of one family in a row. Measured on a real memory, 659 open questions: two left "same as?"
#: at 7 of the top 10 and 33 of the top 50, still the wall, for 1 % of the top's score; one leaves 5 and 25, for 5 %, and
#: every question brought into the top 10 still scores in the high bucket (`features.md`).
RUN_LIMIT = 1

P = {
    "conflict": 0.9, "still": 0.5, "informational": 0.05,
    "merge_suggestion": 0.5, "clarification": 0.6, "decay": 0.3, "removal": 0.9, "page_edit": 0.8,
    "normalization": 0.9, "divergence": 0.6, "followup": 0.5, "sources": 0.8,
}
#: The ledger's enum for a score on resolution rows (G113): so a later human reading can check the constants.
BUCKETS = (("high", 1.0), ("mid", 0.3), ("low", 0.0))

#: The `GET /inbox` wire shape this order adds (`orderIndex`): in the ETag, so every client takes one 200 for it.
SHAPE = "qo2"

_LOCK = threading.Lock()
#: ``path -> (page stamp, ledger stamp, count)``
_COUNTS: dict[str, tuple[tuple, tuple, int]] = {}
_COUNT_LINE = re.compile(rb'^\{"id": "', re.MULTILINE)
_SYNTHETIC = {"both", "neither"}


def _stamp(path: Path) -> tuple[int, int]:
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return (0, -1)


def claim_count(memory_path: Path, page_id: str) -> int:
    """Every claim a page holds (live or closed): a raw count of claim lines in the page and its ledger. 0 for no page."""
    if not page_id:
        return 0
    page = Path(memory_path) / "entities" / f"{page_id}.md"
    ledger = page.with_name(f"{page_id}.claims.jsonl")
    ps, ls = _stamp(page), _stamp(ledger)
    if ps[1] < 0:
        return 0
    key = str(page)
    with _LOCK:
        hit = _COUNTS.get(key)
        if hit is not None and hit[0] == ps and hit[1] == ls:
            return hit[2]
    n = 0
    for f in (page, ledger):
        try:
            n += len(_COUNT_LINE.findall(f.read_bytes()))
        except OSError:
            continue
    with _LOCK:
        if len(_COUNTS) > 20000:
            _COUNTS.clear()
        _COUNTS[key] = (ps, ls, n)
    return n


#: A claim's line in the page's fence or its ledger: one JSON object on one line, ``id`` first (``claims._jsonl_line``).
_CLAIM_LINE = re.compile(rb'^\{"id": "([^"]+)".*$', re.MULTILINE)
#: The conversation a stored option names: its own ``source_episode``, else the id an older writer put in its description.
_OPTION_EPISODE = re.compile(r"\bep_\d{4}-\d{2}-\d{2}_\d+")
#: ``path -> (page stamp, ledger stamp, {claim id: (origin, valid_from, recorded_at, conversations)})``; built only for a
#: page that holds a conflict question.
_SAID: dict[str, tuple[tuple, tuple, dict[str, tuple]]] = {}


def said_records(memory_path: Path, page_id: str) -> dict[str, tuple]:
    """``{claim id: what dates it}`` for one page, from the claim lines of the page and its ledger, memoised by their
    stamps. An id the page does not hold is simply absent; an unreadable line counts as absent."""
    if not page_id:
        return {}
    page = Path(memory_path) / "entities" / f"{page_id}.md"
    ledger = page.with_name(f"{page_id}.claims.jsonl")
    ps, ls = _stamp(page), _stamp(ledger)
    if ps[1] < 0:
        return {}
    key = str(page)
    with _LOCK:
        hit = _SAID.get(key)
        if hit is not None and hit[0] == ps and hit[1] == ls:
            return hit[2]
    out: dict[str, tuple] = {}
    for f in (page, ledger):
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        for m in _CLAIM_LINE.finditer(raw):
            try:
                c = json.loads(m.group(0))
            except ValueError:
                continue
            refs = [str(r) for r in _list(c.get("source_episodes"))]
            refs += [str(e.get("episode")) for e in _list(c.get("evidence"))
                     if isinstance(e, dict) and str(e.get("episode") or "").startswith("ep_")]
            out[str(c.get("id"))] = (c.get("origin"), c.get("valid_from"), c.get("recorded_at"), tuple(refs))
    with _LOCK:
        if len(_SAID) > 2000:
            _SAID.clear()
        _SAID[key] = (ps, ls, out)
    return out


def _day(value) -> date | None:
    """The leading ``YYYY-MM-DD`` of a stored date or timestamp, or None."""
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text) if len(text) == 10 else None
    except ValueError:
        return None


def _episode_day(value) -> date | None:
    parsed = episode_ids.parse_episode_id(str(value or "").strip())
    return _day(parsed[0]) if parsed else None


@dataclass
class Parts:
    """What one question's score is made of (the comparison test reads these)."""

    p: float = 0.0
    stake: float = 1.0
    effort: float = 1.0
    reach: int = 1
    n: int = 0
    pages: list[str] = field(default_factory=list)
    fixed: float | None = None
    #: When the thing was SAID (None: no date, or a kind that does not fade) and the page's half-life in days (None:
    #: this page never fades). Both set only for a kind that fades.
    said: date | None = None
    half_life: float | None = None


def visibility(n: int) -> float:
    return 1.0 if n <= SHOWN else math.sqrt(SHOWN / n)


def bucket(score: float | None) -> str | None:
    if score is None:
        return None
    return next(name for name, floor in BUCKETS if score >= floor)


def _f(value, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _list(value) -> list:
    return value if isinstance(value, list) else []


class Tables:
    """The inputs of one ordering: page use, the day-cut read counts, and memoised claim counts."""

    def __init__(self, memory_path: Path, *, reads: bool = True, today: date | None = None, prune: bool = False):
        self.memory_path = Path(memory_path)
        self.today = today or date.today()
        self.use = page_use.scores(self.memory_path, today=today)
        self.reads_on = bool(reads)
        self.r = (page_reads.table(self.memory_path, today=self.today, live=set(self.use) if prune else None)
                  if reads else {})
        self._claims: dict[str, int] = {}
        self._held: dict[str, int] = {}
        self._types: dict[str, str] = {}
        self._fms: dict[str, dict] = {}
        self._multi: dict[str, bool] = {}
        self._owner: str | None = None
        self._owner_read = False
        self._untimed: dict[str, bool] = {}

    # ---- inputs

    def claims(self, pid: str) -> int:
        if pid not in self._claims:
            self._claims[pid] = claim_count(self.memory_path, pid)
        return self._claims[pid]

    def held(self, name: str) -> int:
        """Claims waiting under a name that has no page yet."""
        name = str(name or "").strip()
        if not name:
            return 0
        if name not in self._held:
            n = 0
            try:
                from api.services import pending_store

                line = pending_store.held_line(self.memory_path, name)
                n = len(line.held_claims or []) if line is not None else 0
            except Exception:  # noqa: BLE001 - a held name we cannot read counts nothing
                n = 0
            self._held[name] = n
        return self._held[name]

    def type_of(self, pid: str) -> str:
        if pid not in self._types:
            f = bank_index.file(self.memory_path, "entities", f"{pid}.md") if pid else None
            self._types[pid] = str((f.frontmatter or {}).get("type") or "") if f is not None else ""
        return self._types[pid]

    def page_fm(self, pid: str) -> dict:
        if pid not in self._fms:
            f = bank_index.file(self.memory_path, "entities", f"{pid}.md") if pid else None
            self._fms[pid] = dict(f.frontmatter or {}) if f is not None else {}
        return self._fms[pid]

    def untimed(self, episode: str) -> bool:
        """A memory export entry or a feed item, which says nothing about when. One header per id, not the bank-wide
        ``episode_time.untimed_ids``: that scans every episode, and a hook has 300 ms right after a capture."""
        if episode not in self._untimed:
            f = bank_index.file(self.memory_path, "episodes", f"{episode}.md") if episode else None
            self._untimed[episode] = f is not None and not episode_time.counts_as_activity(f.frontmatter)
        return self._untimed[episode]

    def owner(self) -> str | None:
        if not self._owner_read:
            from api.services import everyday_names

            self._owner = everyday_names.owner_id(self.memory_path)
            self._owner_read = True
        return self._owner

    def has_page(self, pid: str) -> bool:
        return bool(pid) and (self.memory_path / "entities" / f"{pid}.md").is_file()

    def exposure(self, pages) -> float:
        best = 0.0
        for pid in pages:
            if not pid:
                continue
            use = max(0.0, min(1.0, self.use.get(pid, 0.0)))
            reads = page_reads.reads_fraction(self.r.get(pid, 0.0))
            best = max(best, 1.0 - (1.0 - use) * (1.0 - reads))
        return best

    # ---- what each kind's resolver changes

    def parts(self, fm: dict, *, informational: bool = False) -> Parts:
        from api.services import inbox_generator

        kind = str(fm.get("kind") or fm.get("type") or "")
        asks = str(fm.get("asks") or "")
        eid = str(fm.get("entity_id") or "")
        parts = Parts(pages=[eid] if eid else [])
        parts.effort = 1.5 if _required_input(fm, kind) == "freetext" else 1.0
        if kind == "sensitive":
            parts.fixed = SENSITIVE_SCORE
            return parts
        if asks == "sources":
            rows = [r for r in _list(fm.get("rows")) if isinstance(r, dict)]
            parts.p, parts.stake, parts.reach, parts.n = P["sources"], 0.5, max(1, len(rows)), 0
            parts.pages = [str(r.get("page") or "") for r in rows] or parts.pages
            return parts
        if kind == "conflict":
            if asks == "still":
                # The fact is about the OBJECT's page (the owner's page holds the claim and is pinned at use 1.0: taking
                # the busier of the two would give every "still?" full exposure). An older item with no `object_id`
                # reaches no page, so it earns the floor only.
                parts.p, parts.reach, parts.n = P["still"], 1, 0
                obj = str(fm.get("object_id") or "")
                parts.pages = [obj] if obj else []
                # "Not anymore" is no saying: only what holds the claim dates it. `last_said` is what the generator read.
                held = [o for o in _list(fm.get("options")) if isinstance(o, dict) and o.get("claim_id")]
                self._age(parts, eid, self._conflict_said(fm, held, eid) or _day(fm.get("last_said")))
                return parts
            options = [o for o in _list(fm.get("options")) if isinstance(o, dict)]
            contested = {str(o.get("claim_id")) for o in options
                         if o.get("claim_id") and str(o.get("key")) not in _SYNTHETIC}
            parts.p = P["informational"] if informational else P["conflict"]
            parts.reach, parts.n = max(2, len(contested)), self.claims(eid)
            self._age(parts, eid, self._conflict_said(fm, options, eid))
            return parts
        if kind == "divergence":
            parts.p, parts.reach, parts.n = P["divergence"], 2, self.claims(eid)
            self._age(parts, eid, _episode_day(fm.get("source_episode")))
            return parts
        if kind == "merge_suggestion":
            return self._merge(fm, parts, eid)
        if kind == "decay":
            ids = inbox_generator.decay_claim_ids(fm)
            parts.p, parts.n = P["decay"], self.claims(eid)
            parts.reach = max(1, len(ids) if ids else parts.n)
            return parts
        if kind == "removal":
            parts.p, parts.n = P["removal"], self.claims(eid)
            parts.reach = max(1, parts.n)
            return parts
        if kind == "clarification":
            parts.p = P["clarification"]
            name = str(fm.get("entity_name") or eid)
            page_c = self.claims(eid)
            held = self.held(name)
            release = held > 0 and not self.has_page(eid)
            if asks == "name" or release:
                parts.reach = max(1, page_c + held)
                parts.n = page_c + held
                if asks == "name":
                    parts.stake = 1.5
            else:
                parts.reach, parts.n = 1, page_c
                self._age(parts, eid, _episode_day(fm.get("source_episode")))
            return parts
        if kind == "normalization":
            folds = inbox_generator.fold_claims(fm)
            parts.p, parts.reach, parts.n = P["normalization"], max(1, len(folds)), self.claims(eid)
            parts.pages = sorted({e for e, _c in folds} | set(parts.pages))
            return parts
        if kind == "page_edit":
            return self._page_edit(fm, parts, eid)
        if kind == "followup":
            parts.p, parts.reach, parts.n = P["followup"], 1, self.claims(eid)
            self._age(parts, eid, _episode_day(fm.get("source_episode")))
            return parts
        raise ValueError(f"no formula for kind {kind!r}")

    def _merge(self, fm: dict, parts: Parts, eid: str) -> Parts:
        target = str(fm.get("merge_target_hint") or "")
        a = self.claims(eid) if self.has_page(eid) else 0
        b = self.claims(target) if self.has_page(target) else 0
        held = 0 if self.has_page(eid) else self.held(str(fm.get("entity_name") or eid))
        conf = _f(fm.get("suggested_confidence"), 0.5) if fm.get("suggested_confidence") is not None else 0.5
        parts.p = max(0.1, min(1.0, conf))
        parts.reach, parts.n = min(a, b) + held + 1, a + b
        parts.pages = [x for x in (eid, target) if x]
        # Stored as "person - could refer to the same person as X" (`entity_resolver`): the type is the first word, as
        # `inbox_service` reads it when it makes the page.
        stored = entity_types.in_set(str(fm.get("suggested_classification") or "concept").split(" ")[0])
        kinds = {self.type_of(eid) or stored, self.type_of(target)}
        if kinds == {"person"}:
            parts.stake = 1.5
        return parts

    def _page_edit(self, fm: dict, parts: Parts, eid: str) -> Parts:
        parts.p = P["page_edit"]
        join = fm.get("join")
        if isinstance(join, dict):
            op = str(join.get("op") or "")
            if op == "merge":
                into = str(join.get("into") or "")
                a, b = self.claims(eid), self.claims(into)
                parts.reach, parts.n = min(a, b) + 1, a + b
                parts.pages = [x for x in (eid, into) if x]
            elif op == "split":
                parts.reach, parts.n = max(1, len(_list(join.get("claims")))), self.claims(eid)
            else:
                parts.n = self.claims(eid)
                parts.reach = max(1, parts.n)
            return parts
        edit = fm.get("edit") if isinstance(fm.get("edit"), dict) else {}
        changes = (len(_list(edit.get("edits"))) + len(_list(edit.get("add_aliases")))
                   + len(_list(edit.get("remove_aliases")))
                   + sum(1 for k in ("text", "name", "description") if edit.get(k)))
        parts.reach, parts.n = max(1, changes), 0   # prose has its own read budget: visibility 1
        return parts

    # ---- how long ago it was said

    def _conflict_said(self, fm: dict, options: list[dict], eid: str) -> date | None:
        """The freshest of the contested options: one side said again recently makes the conflict fresh. An option known
        only as "no later than" counts only when no contested option has a real date."""
        said: list[date] = []
        bound: list[date] = []
        for o in options:
            if str(o.get("key")) in _SYNTHETIC:
                continue
            day, exact = self._option_said(fm, o, eid)
            if day is not None:
                (said if exact else bound).append(day)
        return max(said or bound, default=None)

    def _option_said(self, fm: dict, option: dict, eid: str) -> tuple[date | None, bool]:
        """When one contested option was said, and whether that is a real date rather than "no later than"."""
        from api.services import source_refresh

        cid = str(option.get("claim_id") or "")
        record = said_records(self.memory_path, eid).get(cid) if cid and eid else None
        if record is not None:
            origin, valid_from, recorded_at, refs = record
            claim = SimpleNamespace(origin=origin, valid_from=valid_from, recorded_at=recorded_at,
                                    source_episodes=list(refs), evidence=[])
            day = _day(source_refresh.said_on(claim, frozenset(r for r in refs if self.untimed(r))))
            if day is not None:
                return day, True
            day = _day(decay_policy.latest_said(refs))
            if day is not None:
                return day, False
        named = _OPTION_EPISODE.search(f'{option.get("source_episode") or ""} {option.get("description") or ""}')
        episode = named.group(0) if named else ("" if cid else str(fm.get("source_episode") or ""))
        day = _episode_day(episode)
        if day is not None:
            return day, not self.untimed(episode)
        # With no conversation the option's date is the claim's `valid_from` (when it became true, not when it was said),
        # so it only counts when nothing better does. With no claim that date is the day the question was raised.
        return (_day(option.get("observed_at")), False) if cid else (None, False)

    def _age(self, parts: Parts, eid: str, said: date | None) -> None:
        """Record when it was said and the page's half-life, for a kind that fades; leave both None otherwise."""
        if said is None:
            return
        _cls, rate = decay_policy.resolve(self.page_fm(eid))
        if rate <= 0 and eid and eid == self.owner():
            # The owner's page is evergreen so it is never archived; that is not "every fact on it stays true".
            _cls, rate = decay_policy.resolve({"decay_class": "active"})
        if rate <= 0:
            return
        parts.said, parts.half_life = said, math.log(2) / rate * 7.0

    def freshness(self, parts: Parts) -> float:
        """``relief + (1 - relief) x fade``: 1.0 for a kind that does not fade, a fact with no date, or a page that never
        fades; never below :data:`FADE_FLOOR`."""
        if parts.said is None or not parts.half_life:
            return 1.0
        age = max(0, (self.today - parts.said).days)
        fade = max(FADE_FLOOR, 0.5 ** (age / parts.half_life))
        relief = 0.0
        for pid in parts.pages:
            if pid:
                relief = max(relief, page_reads.reads_fraction(self.r.get(pid, 0.0)) * visibility(self.claims(pid)))
        return relief + (1.0 - relief) * fade

    def informational(self, fm: dict) -> bool:
        """The G98 rule `load_inbox` applies: a conflict on a predicate the vocabulary calls a set (not a "still?" question)
        is shown, never asked. Memoised per predicate; for a caller that scores items it did not build as inbox cards."""
        if str(fm.get("kind") or fm.get("type") or "") != "conflict" or str(fm.get("asks") or "") == "still":
            return False
        predicate = str(fm.get("predicate") or "")
        if predicate not in self._multi:
            try:
                from api.services import predicates

                self._multi[predicate] = predicates.cardinality(self.memory_path, predicate) == "multi"
            except Exception:  # noqa: BLE001 - an unreadable vocabulary asks as usual
                self._multi[predicate] = False
        return self._multi[predicate]

    # ---- the score

    def seen(self, parts: Parts) -> float:
        if parts.reach and parts.pages and self.owner() in parts.pages:
            return min(float(SHOWN), float(parts.reach))   # the person's own facts are never diluted by their page's size
        return min(float(SHOWN), parts.reach * visibility(parts.n))

    def score(self, fm: dict, *, informational: bool = False) -> float:
        """The question's place on the formula's scale, higher asks first. Never raises: a question it cannot read
        keeps its stored priority."""
        try:
            parts = self.parts(fm, informational=informational)
            if parts.fixed is not None:
                return parts.fixed
            return (parts.p * parts.stake / parts.effort * (FLOOR + self.exposure(parts.pages))
                    * math.sqrt(max(0.0, self.seen(parts))) * self.freshness(parts))
        except Exception as exc:  # noqa: BLE001 - one bad item never costs the list
            logger.warning(f"question order: item scored by its priority ({type(exc).__name__})")
            return max(0.0, min(1.0, _f(fm.get("priority"), 0.0)))


def _required_input(fm: dict, kind: str) -> str:
    stored = str(fm.get("required_input") or "")
    if stored:
        return stored
    from api.services import inbox_service

    return inbox_service._required_input_for(kind)


def family(fm: dict, *, informational: bool = False) -> str | None:
    """What kind of question the person meets: what a run of one looks like. None for one shown, never asked."""
    if informational:
        return None
    kind = str(fm.get("kind") or fm.get("type") or "")
    join = fm.get("join")
    if kind == "merge_suggestion" or (kind == "page_edit" and isinstance(join, dict) and join.get("op") == "merge"):
        return "same"
    return str(fm.get("asks") or "") or kind


def spaced(rows: list, family_of) -> list:
    """``rows`` in score order, with at most :data:`RUN_LIMIT` of one family in a row (see the module docstring)."""
    queues: dict[str | None, deque] = {}
    for n, row in enumerate(rows):
        queues.setdefault(family_of(row), deque()).append((n, row))
    out: list = []
    running, run = None, 0
    while queues:
        chosen = min(queues, key=lambda k: queues[k][0][0])
        if chosen is not None and chosen == running and run >= RUN_LIMIT:
            others = [k for k in queues if k is not None and k != chosen]
            if others:
                chosen = min(others, key=lambda k: queues[k][0][0])
        out.append(queues[chosen].popleft()[1])
        if not queues[chosen]:
            del queues[chosen]
        if chosen is not None:
            run = run + 1 if chosen == running else 1
            running = chosen
    return out


def tables(memory_path: Path, *, reads: bool = True, today: date | None = None, prune: bool = False) -> Tables:
    """The inputs of one ordering. ``reads=False`` leaves the counter out (the remote door's order: nothing derived from
    it crosses that door). ``prune`` lets the backend's inbox read drop counter rows of pages that are gone."""
    return Tables(memory_path, reads=reads, today=today, prune=prune)


def ranked(memory_path: Path, rows, *, reads: bool = True, today: date | None = None) -> list[str]:
    """The ids of ``rows`` (``(id, frontmatter)`` pairs) in the order the inbox serves them: highest score first, newest on
    a tie, then id - the same key ``load_inbox`` sorts by. For every caller that picks or lists questions outside
    ``load_inbox`` (the recall hook, recall's block, ``cicada_check_nudges``): none of them may order by the stored
    priority. Spaced by family among themselves (:func:`spaced`). Builds the tables only when there is something to order; a failure leaves the ids in id order."""
    rows = [(str(ident), fm) for ident, fm in rows]
    if len(rows) < 2:
        return [ident for ident, _fm in rows]
    try:
        from api.services import inbox_service

        t = tables(memory_path, reads=reads, today=today)
        keyed = []
        for ident, fm in rows:
            informational = t.informational(fm)
            keyed.append((-t.score(fm, informational=informational),
                          inbox_service._neg_date_key(str(fm.get("created_date") or "")), ident,
                          family(fm, informational=informational)))
        return [row[2] for row in spaced(sorted(keyed), lambda row: row[3])]
    except Exception as exc:  # noqa: BLE001 - an order is never worth the answer it sits in
        logger.warning(f"question order: ranked by id ({type(exc).__name__})")
        return sorted(ident for ident, _fm in rows)


def stamp(memory_path: Path, *, today: date | None = None) -> str:
    """The counter's contribution to a built list's inputs and the ETag: the day-cut table's digest."""
    return page_reads.stamp(memory_path, today=today)


def warm(memory_path: Path) -> None:
    """Build the order's tables once, in the background at launch: a hook's first ask (a 300 ms budget) would otherwise
    read every page's header to find the pages' use. Never raises."""
    try:
        tables(memory_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"question order: warm-up skipped ({type(exc).__name__})")


def reset() -> None:
    with _LOCK:
        _COUNTS.clear()
        _SAID.clear()
