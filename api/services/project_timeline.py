"""G141 PJ-1 — where a project stands, derived from what every bank already holds ($0).

Pure, engine-free and thread-pool safe, like `provenance.entity_provenance`: it
reads markdown through `bank_index` and a per-request memo, writes nothing and
imports no engine. The caller passes the ACTIVE bank's path and the machine
zone (the split-brain rule; R-PJ7). Every date it serves is absolute — an ISO
day in that zone or a UTC instant — and nothing here reads today: "yesterday",
"overdue" and "quiet" are `project_state.timeline_state`'s, per viewer.

Layers (spec §6.1): the TREE (a project and its `part-of` sub-projects, depth
2, `project` pages only — R-PJB4); derived MOMENTS (claims sharing an anchor
episode and a local day, widened by span co-citation — R-PJB20); MILESTONES
(G17 `due` claims read as milestones — R-PJ4 read-compat, R-PJB21 — and stated
ends); legacy `## History` bullets; activity density; the Sleep queue's pending
conversations (R-PJB5); the CLUSTER around the project with the commons guard
(R-PJ20). PJ-3's event claims join as their own layer (T5) and suppress the
moment of any episode they cite, so a day never says the same thing twice.
"""
from __future__ import annotations

import os
import re
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from api.models.schemas import (
    ActivityDay, ClusterGroup, ClusterMember, MilestoneRow, PendingConversations, ProjectCluster,
    ProjectNow, ProjectProgress, ProjectRef, ProjectRow, ProjectsResponse, ProjectTimeline, TimelineConversation,
    TimelineFact, TimelineItem, TimelineParticipant, TimelineQuote, TimelineWindow,
)
from api.services import (
    bank_index, claim_expiry, entity_body, evidence, inbox_context, project_state,
    search_index, session_stats, when,
)
from api.services.claims import Claim, Evidence, is_record, parse_claims, strip_claims_block
from api.services.hub_builder import _one_line_summary
from api.services.id_utils import sanitize_id
from api.services.transclusion_resolver import claim_to_model

# Bumped when a payload gains a field a client must see (the graph.NODE_SHAPE rule); rides both ETags.
PROJECT_SHAPE = "g141-1"
TREE_DEPTH = 2
MAX_SCAN_PAGES = 200          # §6.6: raw scans are capped; hitting the cap sets `partial`
COMMONS_DEGREE = 12           # R-PJ20
FACTS_SHOWN = 3               # §6.1: 3 facts, then "+N facts"
GROUP_CAP = 8                 # §6.4
ACTIVITY_DAYS = 120           # §10.1: ending at the last activity day, never "the last 120 days"
MAX_CONVERSATIONS = 20
MILESTONES_IN_ROW = 5
THREADS_IN_ROW = 3
GROUPS = (("People", ("person",)), ("Tools & infrastructure", ("tool", "directory")), ("Documents", ("media",)),
          ("Ideas", ("concept", "skill")), ("Sub-projects", ("project",)), ("Places & organisations", ("location", "company")))
_DUE_WORD = re.compile(r"\bdue\b", re.I)
_ISO_DAY = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_HISTORY_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*[:—–-]?\s*")
_NODE = ("", "node")

# Parsed claims per entity page, across requests, keyed on the `bank_index`
# stamp (mtime_ns, size) — the frontmatter cache's own rule, one level down.
# R-PJB9's bench: the pure-Python YAML constructor was ~40% of a project read
# even with the libyaml scanner. Stored as tuples and served as fresh lists;
# nothing in this module mutates a Claim, so sharing them is safe. Bounded:
# a bank switch or a mass rewrite simply refills it.
_CLAIMS_CACHE: dict[str, tuple[int, int, tuple[Claim, ...]]] = {}
_CLAIMS_CACHE_MAX = 8192
_CLAIMS_LOCK = threading.Lock()


def _cached_claims(f: bank_index.IndexedFile, body: Callable[[], str]) -> list[Claim]:
    key = str(f.path)
    with _CLAIMS_LOCK:
        hit = _CLAIMS_CACHE.get(key)
    if hit is not None and hit[0] == f.mtime_ns and hit[1] == f.size:
        return list(hit[2])
    claims = parse_claims(body())
    try:
        st = os.stat(f.path)
        unchanged = (st.st_mtime_ns, st.st_size) == (f.mtime_ns, f.size)
    except OSError:
        unchanged = False
    if unchanged:                      # never file a parse under a stamp it does not match
        with _CLAIMS_LOCK:
            if len(_CLAIMS_CACHE) >= _CLAIMS_CACHE_MAX:
                _CLAIMS_CACHE.clear()
            _CLAIMS_CACHE[key] = (f.mtime_ns, f.size, tuple(claims))
    return claims


def _day(value) -> str | None:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError):
        return None


def _open(c: Claim) -> bool:
    return c.valid_to is None and not c.superseded_by


class _Bank:
    """One request's view: frontmatter from `bank_index` (cached across
    requests), bodies and claims parsed at most once per request, and the raw-scan
    budget that sets `partial` (§6.6)."""

    def __init__(self, memory_path: Path, tz_name: str | None, transcript_exists=None):
        self.path = Path(memory_path)
        self.tz_name = tz_name or "UTC"
        self.tz = when.zone(tz_name)
        self.entities = {f.stem: f for f in bank_index.files(self.path, "entities")}
        self.episodes = {f.stem: f for f in bank_index.files(self.path, "episodes")}
        self._all: dict[str, list[Claim]] = {}
        self._bodies: dict[str, str] = {}
        self._texts: dict[str, str | None] = {}
        self._names: dict[str, str] | None = None
        self._sessions: dict[str, list[str]] | None = None
        self._parents: tuple[dict[str, str], dict[str, list[str]]] | None = None
        self._citing: dict[str, list[str]] = {}
        self._ep_keys: dict[str, tuple] = {}
        self.scanned = 0
        self.partial = False
        self.transcript_exists = transcript_exists or session_stats.default_transcript_exists

    def fm(self, eid: str) -> dict:
        f = self.entities.get(eid)
        return dict(f.frontmatter or {}) if f else {}

    def live(self, eid: str | None) -> bool:
        return bool(eid) and eid in self.entities and str(self.fm(eid).get("status") or "active") != "dropped"

    def type_of(self, eid: str | None) -> str | None:
        return str(self.fm(eid).get("type") or "") or None if eid else None

    def name(self, eid: str) -> str:
        return str(self.fm(eid).get("name") or eid.replace("-", " ").title())

    def body(self, eid: str) -> str:
        if eid not in self._bodies:
            try:
                self._bodies[eid] = self.entities[eid].body()
            except Exception:  # noqa: BLE001 — one unreadable page never fails the read
                self._bodies[eid] = ""
        return self._bodies[eid]

    def all_claims(self, eid: str) -> list[Claim]:
        """Every claim on the page, records included (successor lookups need them)."""
        if eid not in self._all:
            f = self.entities.get(eid)
            self._all[eid] = _cached_claims(f, lambda: self.body(eid)) if f is not None else []
        return self._all[eid]

    def claims(self, eid: str) -> list[Claim]:
        """Beliefs only: records dropped (`is_record`), withdrawn claims dropped —
        a claim someone said was wrong never becomes a fact chip."""
        page = self.all_claims(eid)
        records = {c.id for c in page if is_record(c)}
        return [c for c in page if c.id not in records and (c.superseded_by or "") not in records]

    def episode_text(self, ep: str) -> str | None:
        if ep not in self._texts:
            f = self.episodes.get(ep)
            try:
                self._texts[ep] = f.body() if f else None
            except Exception:  # noqa: BLE001
                self._texts[ep] = None
        return self._texts[ep]

    def names(self) -> dict[str, str]:
        if self._names is None:
            idx: dict[str, str] = {}
            for stem in sorted(self.entities):
                fm = self.entities[stem].frontmatter or {}
                keys = [stem, stem.replace("-", " ")]
                name = str(fm.get("name") or "").strip()
                if name:
                    keys += [name, sanitize_id(name)]
                keys += [str(a) for a in (fm.get("aliases") or []) if str(a).strip()]
                for k in keys:
                    idx.setdefault(k.strip().lower(), stem)
            self._names = idx
        return self._names

    def resolve(self, ref) -> str | None:
        raw = str(ref or "").strip()
        if not raw:
            return None
        if raw in self.entities:
            return raw
        idx = self.names()
        return idx.get(raw.lower()) or idx.get(sanitize_id(raw))

    def owner(self) -> str | None:
        for stem in sorted(self.entities):
            if (self.entities[stem].frontmatter or {}).get("owner") is True:
                return stem
        try:
            from api.services import owner_identity

            oid = owner_identity.resolve_observer(self.path, None)
        except Exception:  # noqa: BLE001
            return None
        return oid if oid in self.entities else None

    def session_episodes(self, sid: str) -> list[str]:
        if self._sessions is None:
            self._sessions = {}
            for ep, f in sorted(self.episodes.items()):
                s = str((f.frontmatter or {}).get("session_id") or "").strip()
                if s:
                    self._sessions.setdefault(s, []).append(ep)
        return self._sessions.get(sid, [])

    def ep_key(self, ep: str) -> tuple:
        """`(sort key, instant)` of an episode's `timestamp`, once per request:
        `_anchor` asks for the same episode for every claim citing it."""
        hit = self._ep_keys.get(ep)
        if hit is None:
            from api.services import episode_ids

            ts = (self.episodes[ep].frontmatter or {}).get("timestamp")
            hit = self._ep_keys[ep] = (episode_ids.timestamp_sort_key(ts), when.parse_instant(ts))
        return hit

    def charge(self) -> bool:
        self.scanned += 1
        if self.scanned > MAX_SCAN_PAGES:
            self.partial = True
            return False
        return True

    def claims_naming(self, tree: list[str]) -> dict[str, list[Claim]]:
        """Pages outside `tree` with a node claim whose object resolves into it
        (§6.4's reverse claims). The FTS claim table answers first; while it builds,
        a raw prefilter reads pages whose text names a tree id, under the budget."""
        targets = set(tree)
        names = [n for t in tree for n in (t, self.name(t))]
        hits = search_index.claims_about(self.path, names)
        if hits is not None:
            subjects = sorted({ref for ref, _ in hits})
        else:
            # The raw scan is what §6.6 caps: EVERY page read is charged (not only the ones that
            # match), so a 2,500-page bank with no index reads at most MAX_SCAN_PAGES and says
            # `partial`. Needles are ids AND names, lower-cased, like the FTS phrase — a claim whose
            # object is a display name ("Rover Arm Project") must be found on both paths.
            needles = {n.lower() for n in names if n}
            subjects = []
            for stem, f in sorted(self.entities.items()):
                if stem in targets:
                    continue
                if not self.charge():
                    break
                try:
                    raw = f.path.read_text(encoding="utf-8").lower()
                except OSError:
                    continue
                if any(n in raw for n in needles):
                    subjects.append(stem)
        out: dict[str, list[Claim]] = {}
        for s in subjects:
            if s in targets or not self.live(s):
                continue
            found = [c for c in self.claims(s) if c.object_kind in _NODE and self.resolve(c.object) in targets]
            if found:
                out[s] = found
        return out

    def prefetch_citing(self, episodes: list[str]) -> None:
        """One index read for every moment's episode instead of one reader per
        episode (R-PJB9's bench: ~75 reader opens were a third of a build).
        A miss leaves `co_cited` on its own per-episode path and fallback."""
        found = search_index.pages_citing_many(self.path, [e for e in episodes if e not in self._citing])
        if found is not None:
            self._citing.update(found)

    def co_cited(self, episode: str) -> list[tuple[str, Claim]]:
        """Every claim with a SPAN into `episode` (R-PJB20)."""
        pages = self._citing.get(episode)
        if pages is None:
            pages = search_index.pages_citing(self.path, episode)
        if pages is None:
            from api.services import provenance

            paths, partial = provenance._candidate_pages(self.path, episode)
            self.partial = self.partial or partial
            pages = [p.stem for p in paths]
        out = []
        for page in pages:
            if not self.live(page):
                continue
            for c in self.claims(page):
                if any(e.is_span() and e.episode == episode for e in c.evidence):
                    out.append((page, c))
        return out


@dataclass(frozen=True)
class _Anchor:
    episode: str | None
    day: str
    at: str | None
    basis: str                    # turn | episode | day
    span: Evidence | None


def _anchor(bank: _Bank, claim: Claim) -> _Anchor | None:
    """§6.1: the earliest evidence episode, else `source_episodes[0]`, else
    `valid_from` alone. The turn's own time wins over the episode's (G118)."""
    spans = [e for e in claim.evidence if e.is_span() and e.episode in bank.episodes]
    candidates = [e.episode for e in spans] or [ep for ep in claim.source_episodes if ep in bank.episodes]
    if not candidates:
        day = _day(claim.valid_from)
        return _Anchor(None, day, None, "day", None) if day else None
    ep = min(candidates, key=lambda e: (bank.ep_key(e)[0], e))
    span = next((e for e in spans if e.episode == ep), None)
    fm = bank.episodes[ep].frontmatter or {}
    instant, basis = None, "episode"
    if span is not None:
        stamps = evidence.turn_stamps(fm)
        if stamps:
            turn = evidence.turn_at(bank.episode_text(ep) or "", span.start, stamps)
            instant = when.parse_instant((turn or {}).get("ts"))
            basis = "turn" if instant else "episode"
    if instant is None:
        instant = bank.ep_key(ep)[1]
    if instant is None:
        day = _day(claim.valid_from)
        return _Anchor(ep, day, None, "day", span) if day else None
    return _Anchor(ep, when.local_day(instant, bank.tz).isoformat(), when.utc_z(instant), basis, span)


def _parents(bank: _Bank) -> tuple[dict[str, str], dict[str, list[str]]]:
    """`(parent_of, children)` over every live project page, built once per
    request: `list_projects` asks for every project's tree, and rebuilding
    this per root made the list O(projects²) in page walks (R-PJB9's bench)."""
    if bank._parents is None:
        parent_of: dict[str, str] = {}
        for stem in sorted(bank.entities):
            if bank.type_of(stem) != "project" or not bank.live(stem):
                continue
            for c in bank.claims(stem):
                if c.predicate == "part-of":
                    p = bank.resolve(c.object)
                    if p and p != stem and bank.type_of(p) == "project":
                        parent_of[stem] = p
                        break
        children: dict[str, list[str]] = {}
        for child, p in parent_of.items():
            children.setdefault(p, []).append(child)
        bank._parents = (parent_of, children)
    return bank._parents


def _tree(bank: _Bank, root: str) -> tuple[list[str], str | None]:
    """`(tree, parent of root)`. R-PJB4: `project` pages only; a `part-of` claim,
    current or closed, links a child to a parent; depth 2."""
    parent_of, children = _parents(bank)
    out, frontier = [root], [root]
    for _ in range(TREE_DEPTH):
        frontier = [k for p in frontier for k in sorted(children.get(p, [])) if k not in out]
        out += frontier
    return out, parent_of.get(root)


def _neg(day: str) -> str:
    """Digits inverted so an ascending sort reads newest first (the
    `inbox_service._neg_date_key` trick, inlined so the read model never imports
    the inbox service)."""
    return "".join(str(9 - int(ch)) if ch.isdigit() else ch for ch in day)


def _one_liner(bank: _Bank, eid: str) -> str:
    return _one_line_summary(strip_claims_block(bank.body(eid)), limit=120)


def _words(predicate: str) -> str:
    return (predicate or "").replace("-", " ")


def _neighbours(bank: _Bank, tree: list[str], owner: str | None,
                reverse: dict[str, list[Claim]]) -> dict[str, dict]:
    """Current graph neighbours of the tree (§6.4): open node claims out of a
    tree page, and open claims into it from any page but the owner's — the
    owner is "You" on every moment, never a member of the cluster."""
    out: dict[str, dict] = {}
    targets = set(tree)

    def add(member: str, claim: Claim, phrase: str) -> None:
        row = out.setdefault(member, {"count": 0, "last": None, "phrases": Counter()})
        row["count"] += 1
        day = _day(claim.valid_from)
        if day and (row["last"] is None or day > row["last"]):
            row["last"] = day
        row["phrases"][phrase] += 1

    for page in tree:
        for c in bank.claims(page):
            if not _open(c) or c.object_kind not in _NODE:
                continue
            obj = bank.resolve(c.object)
            if obj and obj not in targets and obj != owner and bank.live(obj):
                add(obj, c, f"this project {_words(c.predicate)}")
    for subject, claims in sorted(reverse.items()):
        if subject == owner or subject in targets or not bank.live(subject):
            continue
        for c in claims:
            if _open(c):
                add(subject, c, f"{_words(c.predicate)} this project")
    return out


def _project_links(bank: _Bank) -> dict[str, set[str]]:
    """`{page: {live project pages linked to it by an open node claim, either
    way}}` — one pass over every project page's open node claims."""
    links: dict[str, set[str]] = {}
    for stem in sorted(bank.entities):
        if bank.type_of(stem) != "project" or not bank.live(stem):
            continue
        for c in bank.claims(stem):
            if _open(c) and c.object_kind in _NODE:
                obj = bank.resolve(c.object)
                if obj and obj != stem:
                    links.setdefault(obj, set()).add(stem)
    return links


def _commons(bank: _Bank, neighbours: dict[str, dict]) -> set[str]:
    """R-PJ20: a member linked to more than `COMMONS_DEGREE` projects is the
    commons (a hub tool everyone uses) — shown under "also uses", and its
    claims never ride into a project's moments."""
    if not neighbours:
        return set()
    links = _project_links(bank)
    out: set[str] = set()
    for member in neighbours:
        projects = set(links.get(member, set()))
        for c in bank.claims(member):
            if _open(c) and c.object_kind in _NODE:
                obj = bank.resolve(c.object)
                if obj and obj != member and bank.type_of(obj) == "project" and bank.live(obj):
                    projects.add(obj)
        if len(projects) > COMMONS_DEGREE:
            out.add(member)
    return out


def _candidates(bank: _Bank, tree: list[str], owner: str | None, members: list[str],
                reverse: dict[str, list[Claim]]) -> tuple[list[tuple[Claim, str, _Anchor]], set[str]]:
    """§6.1's three layers of candidate claims: (a) every claim on a tree page;
    (b) reverse claims — the owner's at any validity (what the person did on
    the project stays their history), other pages' only while open; (c) member
    pages' claims anchored inside the live window (a)+(b) spans, so a busy
    tool's old life never floods a young project."""
    rows: list[tuple[Claim, str, _Anchor]] = []
    seen: set[str] = set()
    core: set[str] = set()

    def take(c: Claim, page: str) -> _Anchor | None:
        if c.id in seen:
            return None
        a = _anchor(bank, c)
        if a is None:
            return None
        seen.add(c.id)
        rows.append((c, page, a))
        return a

    for page in tree:
        for c in bank.claims(page):
            if take(c, page):
                core.add(c.id)
    targets = set(tree)
    if owner and bank.live(owner):
        for c in bank.claims(owner):
            if c.object_kind in _NODE and bank.resolve(c.object) in targets and take(c, owner):
                core.add(c.id)
    for subject, claims in sorted(reverse.items()):
        if subject == owner:
            continue
        for c in claims:
            if _open(c) and take(c, subject):
                core.add(c.id)
    days = [a.day for _, _, a in rows if a.day]
    if days and members:
        lo, hi = min(days), max(days)
        for m in members:
            if not bank.live(m):
                continue
            for c in bank.claims(m):
                if c.id in seen:
                    continue
                a = _anchor(bank, c)
                if a is not None and lo <= a.day <= hi:
                    seen.add(c.id)
                    rows.append((c, m, a))
    return rows, core


def _object_label(bank: _Bank, c: Claim) -> str:
    if c.object_kind in _NODE:
        obj = bank.resolve(c.object)
        if obj:
            return bank.name(obj)
    return str(c.object or "")


def _fact(bank: _Bank, page: str, c: Claim) -> TimelineFact:
    """R-PJ14: `said` while open; `ended` when closed at its own stated end
    with nothing after it; `changed` when an open successor replaced it."""
    subject = bank.resolve(c.subject) or page
    phrase = f"{bank.name(subject) if subject in bank.entities else c.subject} {_words(c.predicate)} " \
             f"{_object_label(bank, c)}".strip()
    state, was, now = "said", None, None
    if not _open(c):
        successor = None
        if c.superseded_by:
            successor = next((x for x in bank.all_claims(page) if x.id == c.superseded_by), None)
        if successor is not None and _open(successor) and not is_record(successor):
            state, was, now = "changed", _object_label(bank, c), _object_label(bank, successor)
        elif not c.superseded_by and c.valid_to and claim_expiry.closing_date(c) == _day(c.valid_to):
            state = "ended"
    return TimelineFact(claim_id=c.id, subject=subject, predicate=c.predicate, object=str(c.object or ""),
                        phrase=phrase, state=state, was=was, now=now)


def _quote(bank: _Bank, lead: Claim, page: str, anchor: _Anchor) -> TimelineQuote | None:
    """The moment's washed sentence: the lead's own span (offsets dropped when
    the text moved — the `provenance.episode_citations` rule), else a mention
    found by name at read, said `derived` and never written (G118)."""
    if not anchor.episode:
        return None
    text = bank.episode_text(anchor.episode)
    if text is None:
        return None
    span = anchor.span
    if span is not None:
        status = evidence.span_status(text, end=span.end, hash=span.hash, appendable=True)
        if status == evidence.SPAN_STALE or span.end > len(text):
            return TimelineQuote(episode=anchor.episode, kind=span.kind, status=evidence.SPAN_STALE)
        return TimelineQuote(episode=anchor.episode, start=span.start, end=span.end, kind=span.kind, status=status)
    subject = bank.resolve(lead.subject) or page
    hit = inbox_context.locate_mention(text, bank.name(subject), subject)
    if hit is None:
        return TimelineQuote(episode=anchor.episode, kind="derived", status="derived")
    return TimelineQuote(episode=anchor.episode, start=hit[0], end=hit[1], kind="derived", status="derived")


def _conversation(bank: _Bank, ep: str) -> TimelineConversation | None:
    f = bank.episodes.get(ep)
    if f is None:
        return None
    fm = f.frontmatter or {}
    sid = str(fm.get("session_id") or "").strip()
    cid = sid or str(fm.get("source_id") or "").strip() or None
    try:
        resumable = bool(sid) and bool(bank.transcript_exists(fm.get("project_dir"), sid))
    except Exception:  # noqa: BLE001 — a resumability probe never fails the read
        resumable = False
    return TimelineConversation(id=cid, episode_id=ep, title=str(fm.get("title") or ""),
                                origin=fm.get("origin"), harness=fm.get("harness"), resumable=resumable)


def _participants(bank: _Bank, root: str, owner: str | None,
                  rows: list[tuple[Claim, str, _Anchor]]) -> list[TimelineParticipant]:
    out: list[TimelineParticipant] = []
    seen: set[str] = set()
    for c, page, _ in rows:
        ids = [bank.resolve(c.subject) or page]
        if c.object_kind in _NODE:
            ids.append(bank.resolve(c.object))
        for eid in ids:
            if not eid or eid == root or eid in seen or not bank.live(eid):
                continue
            seen.add(eid)
            fm = bank.fm(eid)
            media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
            out.append(TimelineParticipant(id=eid, name=bank.name(eid), type=bank.type_of(eid),
                                           is_owner=eid == owner, url=(media or {}).get("url")))
    return out


def _lead_key(tree: list[str], owner: str | None):
    def key(row):
        c, page, a = row
        span = a.span
        subject = c.subject if c.subject else page
        return (0 if span is not None and span.kind == "user" else 1,
                0 if subject in tree or subject == owner or page in tree or page == owner else 1,
                -((span.end - span.start) if span is not None else 0), c.id)
    return key


def _moments(bank: _Bank, root: str, tree: list[str], owner: str | None,
             rows: list[tuple[Claim, str, _Anchor]], suppressed: set[str], commons: set[str]) -> list[TimelineItem]:
    """Claims grouped by (anchor episode, local day) — one moment per
    conversation per day — widened by span co-citation (R-PJB20) so the
    moment carries what the conversation said around the project too."""
    groups: dict[tuple[str, str], list[tuple[Claim, str, _Anchor]]] = {}
    for c, page, a in rows:
        if a.episode and a.episode in suppressed:
            continue
        groups.setdefault((a.episode or "", a.day), []).append((c, page, a))
    items: list[TimelineItem] = []
    bank.prefetch_citing(sorted({ep for ep, _ in groups if ep}))
    for (ep, day), group in sorted(groups.items()):
        if ep:
            have = {c.id for c, _, _ in group}
            for page, c in bank.co_cited(ep):
                if c.id in have or page in commons:
                    continue
                a = _anchor(bank, c)
                if a is not None and a.episode == ep and a.day == day:
                    have.add(c.id)
                    group.append((c, page, a))
        group.sort(key=_lead_key(tree, owner))
        lead, lead_page, lead_anchor = group[0]
        facts = [_fact(bank, page, c) for c, page, _ in group]
        pages = {page for _, page, _ in group}
        if root in pages:
            via = None
        else:
            via = next((t for t in tree if t in pages), lead_page)
        items.append(TimelineItem(
            kind="moment", id=f"m:{ep}:{day}" if ep else f"m:{day}:{lead.id}", day=day, at=lead_anchor.at,
            date_basis=lead_anchor.basis, state=facts[0].state, via=via,
            project=next((t for t in tree if t in pages), None), text=facts[0].phrase,
            facts=facts[:FACTS_SHOWN], more_facts=max(0, len(facts) - FACTS_SHOWN),
            participants=_participants(bank, root, owner, group),
            quote=_quote(bank, lead, lead_page, lead_anchor),
            conversation=_conversation(bank, ep) if ep else None))
    return items


def _due_name(claim: Claim, page_name: str) -> str:
    text = _ISO_DAY.sub(" ", _DUE_WORD.sub(" ", claim.text or ""))
    text = re.sub(r"\s+", " ", text).strip(" ,;:-—–\t")
    return text or page_name


def _milestones(bank: _Bank, tree: list[str]) -> list[MilestoneRow]:
    """R-PJB21 read-compat: a G17 `due` with a date is a milestone — open →
    planned; closed at its own stated end with nothing after it → passed with
    no word (never "missed": nobody said so); closed any other way → dropped;
    superseded → not listed. An open claim's `expected_end` is a tick
    (`source: expectedEnd`), never a goal."""
    root = tree[0]
    rows: list[MilestoneRow] = []
    slugs: set[str] = set()

    def slug_for(base: str) -> str:
        slug, n = base, 2
        while slug in slugs:
            slug, n = f"{base}-{n}", n + 1
        slugs.add(slug)
        return slug

    for page in tree:
        for c in bank.claims(page):
            if c.predicate == "due":
                target = claim_expiry.stated_end(c)
                if target is None or c.superseded_by:
                    continue
                if _open(c):
                    status = "planned"
                elif claim_expiry.closing_date(c) == _day(c.valid_to):
                    status = "passed-no-word"
                else:
                    status = "dropped"
                rows.append(MilestoneRow(slug=slug_for(f"due-{target}"), name=_due_name(c, bank.name(page)),
                                         status=status, target=target, source="due",
                                         on=page if page != root else None, claim_id=c.id,
                                         chain=[claim_to_model(c)]))
            elif c.expected_end and _open(c):
                end = _day(c.expected_end)
                if end is None:
                    continue
                rows.append(MilestoneRow(slug=slug_for(f"end-{end}"), name=c.text or bank.name(page),
                                         status="planned", target=end, source="expectedEnd",
                                         on=page if page != root else None, claim_id=c.id,
                                         chain=[claim_to_model(c)]))
    planned = sorted((m for m in rows if m.status == "planned"),
                     key=lambda m: (m.target is None, m.target or "", m.slug))
    rest = sorted((m for m in rows if m.status != "planned"), key=lambda m: (m.target or "", m.slug), reverse=True)
    return planned + rest


def _history(bank: _Bank, tree: list[str]) -> list[TimelineItem]:
    """Legacy `## History` bullets as grey rows. A leading date outside the
    page's plausible life (R-PJB6: created − 1 y … max(created, last seen) + 2 y,
    never "today") is a typo, kept in the text and left undated."""
    items: list[TimelineItem] = []
    for page in tree:
        section = entity_body.parse_sections(strip_claims_block(bank.body(page))).get("History") or ""
        fm = bank.fm(page)
        created = _day(fm.get("created"))
        last = _day(fm.get("last_referenced"))
        lo = hi = None
        if created:
            lo = (date.fromisoformat(created) - timedelta(days=365)).isoformat()
            top = max(created, last or created)
            hi = (date.fromisoformat(top) + timedelta(days=730)).isoformat()
        n = 0
        for line in section.splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue
            n += 1
            text = line[2:].strip()
            day = None
            m = _HISTORY_DATE.match(text)
            if m and lo and hi and lo <= m.group(1) <= hi and _day(m.group(1)):
                day = m.group(1)
                text = text[m.end():].strip()
            items.append(TimelineItem(kind="history", id=f"h:{page}:{n:03d}", day=day, project=page, text=text))
    return items


def _claim_episodes(c: Claim) -> list[str]:
    eps = list(c.source_episodes or [])
    eps += [e.episode for e in c.evidence if e.is_span() and evidence.is_episode_id(e.episode)]
    return eps


def _conv_key(bank: _Bank, ep: str) -> str:
    fm = bank.episodes[ep].frontmatter or {}
    return str(fm.get("session_id") or "").strip() or str(fm.get("source_id") or "").strip() or ep


def _ep_day(bank: _Bank, ep: str) -> str | None:
    instant = when.parse_instant((bank.episodes[ep].frontmatter or {}).get("timestamp"))
    return when.local_day(instant, bank.tz).isoformat() if instant else None


def _activity(bank: _Bank, claims: list[Claim]) -> list[ActivityDay]:
    """Distinct conversations per local day, over the `ACTIVITY_DAYS` ending
    at the last active day (§10.1: anchored to data, never to today)."""
    per_day: dict[str, set[str]] = {}
    seen: set[str] = set()
    for c in claims:
        eps = _claim_episodes(c)
        for sid in c.all_session_ids():
            eps += bank.session_episodes(sid)
        for ep in eps:
            if ep in seen or ep not in bank.episodes:
                continue
            seen.add(ep)
            day = _ep_day(bank, ep)
            if day:
                per_day.setdefault(day, set()).add(_conv_key(bank, ep))
    if not per_day:
        return []
    last = date.fromisoformat(max(per_day))
    floor = (last - timedelta(days=ACTIVITY_DAYS - 1)).isoformat()
    return [ActivityDay(day=d, n=len(k)) for d, k in sorted(per_day.items()) if d >= floor]


def _tree_names(bank: _Bank, tree: list[str]) -> list[str]:
    names: set[str] = set()
    for page in tree:
        fm = bank.fm(page)
        for n in (page, page.replace("-", " "), str(fm.get("name") or ""),
                  *[str(a) for a in (fm.get("aliases") or [])]):
            n = n.strip()
            if len(n) >= 3:
                names.add(n)
    return sorted(names, key=lambda n: (-len(n), n))


def _pending(bank: _Bank, tree: list[str]) -> PendingConversations:
    """R-PJB5: the Sleep queue, read directly — unprocessed episodes naming a
    tree page. Not FTS, so the count never moves with the index's build state."""
    names = _tree_names(bank, tree)
    if not names:
        return PendingConversations()
    rx = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b", re.I)
    n, newest = 0, None
    for ep, f in sorted(bank.episodes.items()):
        fm = f.frontmatter or {}
        if fm.get("processed"):
            continue
        text = bank.episode_text(ep) or ""
        if not rx.search(text):
            continue
        n += 1
        instant = when.parse_instant(fm.get("timestamp"))
        if instant and (newest is None or instant > newest):
            newest = instant
    return PendingConversations(unconsolidated=n,
                                newest_day=when.local_day(newest, bank.tz).isoformat() if newest else None)


def _conversations(bank: _Bank, claims: list[Claim]) -> list[TimelineConversation]:
    """Grouped like `/entities/{id}/provenance`: session, then source id, else
    the lone episode; newest first, at most `MAX_CONVERSATIONS`."""
    groups: dict[str, str] = {}
    for c in claims:
        for ep in _claim_episodes(c):
            if ep not in bank.episodes:
                continue
            key = _conv_key(bank, ep)
            cur = groups.get(key)
            if cur is None or _sort_ts(bank, ep) > _sort_ts(bank, cur):
                groups[key] = ep
    ordered = sorted(groups.values(), key=lambda ep: (_sort_ts(bank, ep), ep), reverse=True)
    return [conv for ep in ordered[:MAX_CONVERSATIONS] if (conv := _conversation(bank, ep))]


def _sort_ts(bank: _Bank, ep: str) -> str:
    from api.services import episode_ids

    return episode_ids.timestamp_sort_key((bank.episodes[ep].frontmatter or {}).get("timestamp"))


def _member_fact(bank: _Bank, eid: str) -> str:
    t = bank.type_of(eid)
    fm = bank.fm(eid)
    if t in ("tool", "directory"):
        lits = [str(c.object) for c in bank.claims(eid) if _open(c) and c.object_kind == "literal" and c.object]
        return " · ".join(lits[:3])
    if t == "person":
        c = next((c for c in bank.claims(eid) if _open(c) and c.predicate == "works-at"), None)
        return _object_label(bank, c) if c else ""
    if t == "media":
        media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
        paper = fm.get("paper") if isinstance(fm.get("paper"), dict) else None
        if (media or {}).get("kind") == "paper" or paper is not None:
            p = paper or {}
            return " ".join(x for x in (str(p.get("venue") or ""), str(p.get("published") or "")[:4]) if x)
        return str((media or {}).get("site") or "")
    return ""


def _cluster(bank: _Bank, tree: list[str], neighbours: dict[str, dict], commons: set[str]) -> ProjectCluster:
    """§6.4: the pages around the project, grouped by kind, each with one
    fact worth knowing; sub-projects are the tree's own (R-PJB4)."""
    def member(eid: str) -> ClusterMember:
        row = neighbours.get(eid) or {"count": 0, "last": None, "phrases": Counter()}
        phrase = row["phrases"].most_common(1)[0][0] if row["phrases"] else ""
        return ClusterMember(id=eid, type=bank.type_of(eid), name=bank.name(eid), role_phrase=phrase,
                             fact=_member_fact(bank, eid), last_seen=row["last"], count=row["count"])

    def order(m: ClusterMember):
        return (-m.count, _neg(m.last_seen) if m.last_seen else "~", m.name)

    buckets: dict[str, list[ClusterMember]] = {label: [] for label, _ in GROUPS}
    by_type = {t: label for label, types in GROUPS for t in types}
    buckets["Sub-projects"] = [member(eid) for eid in tree[1:]]
    also: list[ClusterMember] = []
    for eid in sorted(neighbours):
        if eid in commons:
            also.append(member(eid))
            continue
        label = by_type.get(bank.type_of(eid) or "", "Ideas")
        if label == "Sub-projects":
            label = "Ideas"      # a linked project outside the tree is a neighbour, not a child (R-PJB4)
        buckets[label].append(member(eid))
    groups = []
    for label, _ in GROUPS:
        members = sorted(buckets[label], key=order) if label != "Sub-projects" else buckets[label]
        if members:
            groups.append(ClusterGroup(label=label, members=members[:GROUP_CAP], more=max(0, len(members) - GROUP_CAP)))
    return ProjectCluster(groups=groups, also_uses=sorted(also, key=order))


def build(memory_path: Path, project_id: str, *, tz_name: str | None, since: str | None = None,
          transcript_exists: Callable | None = None) -> ProjectTimeline | None:
    bank = _Bank(memory_path, tz_name, transcript_exists)
    root = bank.resolve(project_id)
    if root is None or bank.type_of(root) != "project" or not bank.live(root):
        return None
    tree, parent = _tree(bank, root)
    owner = bank.owner()
    reverse = bank.claims_naming(tree)
    neighbours = _neighbours(bank, tree, owner, reverse)
    commons = _commons(bank, neighbours)
    members = [m for m in neighbours if m not in commons]
    rows, core_ids = _candidates(bank, tree, owner, members, reverse)
    suppressed: set[str] = set()                     # T5: episodes an event claim cites
    moments = _moments(bank, root, tree, owner, rows, suppressed, commons)
    milestones = _milestones(bank, tree)
    fm = bank.fm(root)
    created = _day(fm.get("created"))
    items = moments + _history(bank, tree)
    if created:
        items.append(TimelineItem(kind="created", id=f"c:{root}", day=created, project=root,
                                  text="Cicada started tracking this"))
    since_day = _day(since)
    if since_day:
        items = [i for i in items if i.day is None or i.day >= since_day]
    order = {"happening": 0, "moment": 1, "history": 2, "created": 3}
    items.sort(key=lambda i: (i.day is None, "" if i.day is None else _neg(i.day), order[i.kind], i.id))
    moment_days = sorted({m.day for m in moments if m.day})
    core = [c for c, _, _ in rows if c.id in core_ids]
    activity = _activity(bank, core)
    next_slug = project_state.next_slug([m.model_dump(by_alias=True) for m in milestones])
    targets = [m.target for m in milestones if m.target]
    days = [i.day for i in items if i.day]
    ref = ProjectRef(id=root, name=bank.name(root), one_liner=_one_liner(bank, root), parent=parent,
                     children=tree[1:], status=str(fm.get("status") or "active"), created=created)
    return ProjectTimeline(
        project=ref, tz_name=bank.tz_name,
        window=TimelineWindow(start=min([x for x in (created, *days) if x], default=None),
                              end=max([x for x in (*(a.day for a in activity), *targets) if x], default=None)),
        # `now` ignores `since`: "me today" is never cut by a history filter.
        now=ProjectNow(threads=[], next=next((m for m in milestones if m.slug == next_slug), None),
                       last=max(moments, key=lambda m: (m.day or "", m.at or "", m.id), default=None)),
        pending=_pending(bank, tree), milestones=milestones, items=items, activity=activity,
        moment_days=moment_days, last_moment_day=moment_days[-1] if moment_days else None,
        median_gap_days=project_state.median_gap(moment_days),
        cluster=_cluster(bank, tree, neighbours, commons), conversations=_conversations(bank, core),
        partial=bank.partial)


def now_next(memory_path: Path, project_id: str) -> tuple[dict | None, dict | None]:
    """`_state.md` v3's two cursor fields (G53, G141 §10.3) — pure functions of
    the claims; neither reads today (the file's `inputs_version` would not
    notice a day passing, so a today-dependent field would go stale silently).
    `now` is the newest open `ongoing` happening in the tree (PJ-3; absent
    before it); `next` the open planned milestone with the earliest target
    (`project_state.next_slug`, overdue or upcoming alike). A light path: one
    tree and its milestones — no moments, no cluster, no FTS."""
    bank = _Bank(memory_path, None)
    if bank.type_of(project_id) != "project" or not bank.live(project_id):
        return None, None
    tree, _ = _tree(bank, project_id)
    milestones = _milestones(bank, tree)
    slug = project_state.next_slug([m.model_dump(by_alias=True) for m in milestones])
    nxt = next(({"slug": m.slug, "name": m.name, "target": m.target} for m in milestones if m.slug == slug), None)
    return _now_thread(bank, tree), nxt


def _now_thread(bank: _Bank, tree: list[str]) -> dict | None:
    """T5 (PJ-3): the event layer fills this — no happening exists before it."""
    return None


def _payload_claim(payload: dict) -> Claim | None:
    """An FTS claim payload as a Claim thin enough for `_anchor` — the list
    never opens a member page (R-PJB19)."""
    cid = str(payload.get("id") or "")
    if not cid:
        return None
    ev = payload.get("evidence")
    return Claim(id=cid, text="", predicate=str(payload.get("predicate") or ""),
                 object=str(payload.get("object") or ""), valid_from=payload.get("valid_from"),
                 valid_to=payload.get("valid_to"), superseded_by=payload.get("superseded_by"),
                 evidence=[Evidence.from_dict(ev)] if isinstance(ev, dict) else [])


def _followup_counts(bank: _Bank) -> Counter:
    """Pending `followup` inbox items per entity (PJ-6; always empty before it)."""
    out: Counter = Counter()
    for f in bank_index.files(bank.path, "inbox"):
        fm = f.frontmatter or {}
        if fm.get("kind") == "followup" and str(fm.get("status") or "pending") == "pending":
            eid = str(fm.get("entity_id") or "")
            if eid:
                out[eid] += 1
    return out


def list_projects(memory_path: Path, *, tz_name: str | None, transcript_exists: Callable | None = None) -> ProjectsResponse:
    """Every live project, lighter than the detail and honest about it
    (R-PJB19): each project page, the owner page and the FTS claim payloads
    that name a tree page — never a member page. `partial` whenever the FTS
    index could not answer (the reverse layer is then the owner's alone)."""
    bank = _Bank(memory_path, tz_name, transcript_exists)
    projects = [s for s in sorted(bank.entities) if bank.type_of(s) == "project" and bank.live(s)]
    owner = bank.owner()
    owner_claims = bank.claims(owner) if owner and bank.live(owner) else []
    names = [n for p in projects for n in (p, bank.name(p))]
    payloads = search_index.claims_about(bank.path, names) if names else []
    partial = payloads is None
    payloads = payloads or []
    followups = _followup_counts(bank)
    # Each payload is converted and resolved ONCE and filed under the page its
    # object names; a project then reads only its own tree's buckets, in the
    # payloads' order. Scanning every payload per project was O(projects ×
    # payloads) — ~600k conversions on R-PJB9's 2,500-page bench.
    by_target: dict[str, list[int]] = {}
    converted: list[tuple[str, Claim]] = []
    for ref, payload in payloads:
        c = _payload_claim(payload)
        if c is None or not _open(c):
            continue
        target = bank.resolve(c.object)
        if target is None:
            continue
        by_target.setdefault(target, []).append(len(converted))
        converted.append((ref, c))
    rows: list[ProjectRow] = []
    for root in projects:
        tree, parent = _tree(bank, root)
        targets = set(tree)
        claims: list[Claim] = []
        seen: set[str] = set()
        for page in tree:
            for c in bank.claims(page):
                if c.id not in seen:
                    seen.add(c.id)
                    claims.append(c)
        for c in owner_claims:
            if c.id not in seen and c.object_kind in _NODE and bank.resolve(c.object) in targets:
                seen.add(c.id)
                claims.append(c)
        for i in sorted(i for t in tree for i in by_target.get(t, ())):
            ref, c = converted[i]
            if ref in targets or ref == owner or c.id in seen:
                continue
            seen.add(c.id)
            claims.append(c)
        days = sorted({a.day for c in claims if (a := _anchor(bank, c)) is not None and a.day})
        milestones = _milestones(bank, tree)
        progress = project_state.progress([m.model_dump(by_alias=True) for m in milestones])
        shown = [m.model_copy(update={"chain": []}) for m in
                 sorted(milestones, key=lambda m: m.status != "planned")[:MILESTONES_IN_ROW]]
        fm = bank.fm(root)
        rows.append(ProjectRow(
            id=root, name=bank.name(root), one_liner=_one_liner(bank, root), parent=parent, children=tree[1:],
            status=str(fm.get("status") or "active"), created=_day(fm.get("created")),
            planned=bool(milestones), last_moment_day=days[-1] if days else None,
            median_gap_days=project_state.median_gap(days), open_threads=[], milestones=shown,
            progress=ProjectProgress(**progress), activity=_activity(bank, claims),
            followups=sum(followups.get(t, 0) for t in tree)))
    rows.sort(key=lambda r: (r.last_moment_day is None, _neg(r.last_moment_day) if r.last_moment_day else "", r.id))
    return ProjectsResponse(projects=rows, tz_name=bank.tz_name, partial=partial or bank.partial)
