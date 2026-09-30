"""The reading queue — the one read model behind the tool, the hook, the Feed and the settings page (G166).

An agent's queue is two kinds of entry, computed at read and never fanned out
as rows:

* **asks** — links the person asked about with "Ask an agent" (rows in the
  machine-wide ask store, ``reading_asks``);
* **check entries** (G61 S3) — a source on a page that could answer a pending inbox question, to be looked at
  by an agent BEFORE the question reaches the person. Derived at read from the inbox and the pages' ``sources:``
  (:func:`check_entries`); the consent is the per-site permission below and nothing else (D5: no one-off ask), so a
  planted source can only steer a read to a site the person already allowed, read-only, in their own session. A check
  reports a finding (``cicada_record_check``); it settles, holds and reorders nothing (S4–S8 wait);
* **site entries** — saved pages Cicada's own reader could not read
  (``reading_walls``) that belong to a site the person allowed
  (``reading_settings.allowed_sites``). Turning a site on writes one line in
  ``reading.json`` and queues every waiting page of it; a page saved (or walled)
  later joins with no write; turning the site off, or the master switch off,
  dequeues at once. Nothing goes stale because nothing is stored.

A site is *paused* while a live ``needs_login`` row exists for any of its
pages: the agent was not signed in there, so the site's derived entries stop
until that row expires (a week), the person asks again on a page, or the person
switches the site on again (:func:`resume_site`). An agent that is not signed
in is therefore asked again at most weekly, never in a loop.

A site entry whose page was not saved through a channel that is the person's own
saved content (the allowlist below) is served to a caller without the
``sources`` scope only if ``include_words_origin`` is set: a link a person typed
in Telegram or that an agent saved because it came up in chat is the person's
own words, and the queue must not hand it to a ``read``-scope connection. An agent's
``saved-link`` save is told from the app's by its episode's ``session_id``.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

from api.services import bank_index, media_ingestor, reading_asks, reading_hosts, reading_settings, reading_walls

#: Origins that are saved content, not the person's words: a bookmark, a saved
#: post, a history entry, a feed, the app's own save route. Everything else
#: (Telegram, an agent's save, a clarification, a chat export) needs ``sources``.
_SAVED_SUFFIXES = ("-saved", "-bookmark", "-bookmarks", "-history")
_SAVED_ORIGINS = frozenset({"rss", "saved-link", "pinterest"})


def origin_is_saved_content(origin: str) -> bool:
    o = (origin or "").strip().lower()
    return o in _SAVED_ORIGINS or o.endswith(_SAVED_SUFFIXES)


def _saved_by_agent(memory_path: Path, p: reading_walls.WallPage) -> bool:
    """Was the page saved by an agent (an MCP save, or the app's save route given a session)?
    Its origin cannot tell: ``cicada_save_url`` stamps ``saved-link`` byte-identical to the app's own
    route on purpose, but the save's episode carries the conversation's ``session_id``."""
    from api.services import markdown_parser

    for ep in p.episodes:
        try:
            fm = markdown_parser.parse(Path(memory_path) / "episodes" / f"{ep}.md").frontmatter or {}
        except (OSError, ValueError):
            continue
        if str(fm.get("session_id") or "").strip():
            return True
    return False


@dataclass(frozen=True)
class Entry:
    url: str
    url_hash: str
    host: str
    site: str
    origin: str          # "ask" | "site" | "check"
    since: str           # ISO day: when asked, or when saved (a check: when the question was raised)
    title: str
    wall: str | None
    walled: bool         # a closed-set walled host (pacing: one per call)
    # G61 S3 — a check entry's own fields (empty for an ask or a site entry).
    item_id: str = ""        # the inbox question this source could answer
    entity_id: str = ""      # its subject page
    predicate: str = ""
    linked_entity: str = ""  # the source's own memory node (`entity:`), when it still resolves
    access: str = ""         # the source's effective access, in the enum's words

#: A source an agent looked at is not listed again for this long (the ask store's own expiry).
CHECK_RECHECK_DAYS = 7


def _live_rows(memory_path: Path, now: datetime | None) -> list[dict]:
    try:
        return reading_asks.all_rows(memory_path, now=now)
    except ValueError:
        return []


def paused_sites(rows: list[dict]) -> set[str]:
    return {reading_hosts.site_of(r.get("host") or "") for r in rows if r.get("state") == "needs_login"} - {""}


def ask_entries(memory_path: Path, rows: list[dict], idx: dict) -> list[Entry]:
    out: list[Entry] = []
    for row in rows:
        if row.get("state") != "waiting":
            continue
        entry = idx.get(row["url_hash"]) or {}
        url = str(entry.get("url") or "").strip()
        if not url:
            continue
        verdict = reading_hosts.agent_may_read(url, enabled=True)
        if not verdict.ok:
            continue
        out.append(Entry(url=url, url_hash=row["url_hash"], host=reading_hosts.display_host(verdict.host),
                         site=verdict.site, origin="ask", since=str(row.get("asked_at") or "")[:10],
                         title=str(entry.get("title") or ""), wall=None, walled=verdict.walled))
    return out


def site_entries(memory_path: Path, rows: list[dict], *, include_words_origin: bool = True,
                 pages: list[reading_walls.WallPage] | None = None,
                 deadline: float | None = None) -> list[Entry]:
    allowed = reading_settings.allowed_sites()
    if not allowed:
        return []
    live = {r["url_hash"] for r in rows}
    paused = paused_sites(rows)
    out: list[Entry] = []
    for p in pages if pages is not None else reading_walls.scan(memory_path, deadline=deadline):
        if not p.waiting or p.site not in allowed or p.site in paused or p.url_hash in live:
            continue
        if not include_words_origin and (not origin_is_saved_content(p.origin)
                                         or (p.origin.strip().lower() == "saved-link"
                                             and _saved_by_agent(memory_path, p))):
            continue
        verdict = reading_hosts.classify(p.url)
        if not verdict.ok:
            continue
        out.append(Entry(url=p.url, url_hash=p.url_hash, host=reading_hosts.display_host(verdict.host),
                         site=p.site, origin="site", since=p.saved_at, title=p.title, wall=p.wall,
                         walled=verdict.walled))
    return out


class _ColdCandidates(Exception):
    """The candidates are not memoised yet and the caller has no time to derive them."""


_candidate_memo: dict[str, tuple[str, list]] = {}
_candidate_lock = threading.Lock()
_candidate_warming: set[str] = set()


def _candidate_stamp(memory_path: Path) -> str:
    from api.services import sync_service

    return sync_service.etag_for(Path(memory_path), "inbox", "entities", "sources", extra="check-candidates-1")


def _has_question_items(memory_path: Path) -> bool:
    """A cheap pre-filter on cached frontmatter: is there any pending question a source could answer? Most banks' inbox
    is decay and follow-up items, which never are."""
    from api.services import source_check

    for f in bank_index.files(Path(memory_path), "inbox"):
        fm = f.frontmatter or {}
        if str(fm.get("kind") or "") in source_check._QUESTION_KINDS and str(fm.get("status") or "pending") == "pending":
            return True
    return False


def _check_candidates(memory_path: Path, *, cached_only: bool = False) -> list:
    """``[(item, target)]`` — every source that could answer a pending, checkable question, before any permission is
    asked about. An item is agent-checkable when its checkability is ``checkable``, or ``inform_only`` for a host only
    the person's own session may open (``refused_host_only``, D-AC2); a target is a ``url`` the agent rung reaches. The
    targets are the item's own, already ranked and capped by ``source_check.targets_for`` — the owner's page counts only
    what the person added or took (R-AC9, D2). Read-only.

    Memoised per bank on the inbox, entities and sources stamp (an inbox load parses every item and its subject). With
    ``cached_only`` (the recall hook's 300 ms budget) a cold memo is never derived on the caller's time: it raises
    :class:`_ColdCandidates` and starts the derivation in the background."""
    from api.services import fact_sources, inbox_service, source_check

    memory_path = Path(memory_path)
    key = str(memory_path)
    stamp = _candidate_stamp(memory_path)
    with _candidate_lock:
        held = _candidate_memo.get(key)
    if held is not None and held[0] == stamp:
        return held[1]
    if cached_only:
        _warm_candidates(memory_path)
        raise _ColdCandidates()
    out = []
    if _has_question_items(memory_path):
        for item in inbox_service.load_inbox(memory_path):
            check = item.check
            if item.status != "pending" or check is None:
                continue
            if not (check.state == source_check.CHECKABLE
                    or (check.state == source_check.INFORM_ONLY and check.reason == "refused_host_only")):
                continue
            for t in check.targets:
                if t.kind == fact_sources.KIND_URL and source_check.RUNG_AGENT in t.rungs:
                    out.append((item, t))
    with _candidate_lock:
        _candidate_memo[key] = (stamp, out)
    return out


def _warm_candidates(memory_path: Path) -> None:
    key = str(memory_path)
    with _candidate_lock:
        if key in _candidate_warming:
            return
        _candidate_warming.add(key)

    def _run() -> None:
        try:
            _check_candidates(memory_path)
        except Exception:  # noqa: BLE001
            pass
        finally:
            with _candidate_lock:
                _candidate_warming.discard(key)

    threading.Thread(target=_run, name="check-warm", daemon=True).start()


def check_entries(memory_path: Path, *, now: datetime | None = None, ignore_site: bool = False,
                  ignore_recent: bool = False, candidates: list | None = None, cached_only: bool = False,
                  deadline: float | None = None) -> list[Entry]:
    """The check entries of the queue. An entry exists only when ALL hold: the master switch is on; the source is a URL
    an agent may be handed at all (``reading_hosts.agent_may_read``: never a secret-bearing, local, vendor, video or
    paper link); the person allowed its SITE (``reading_settings.site_allowed`` — the one consent, D5) and that site is
    not paused by a ``needs_login``; no non-waiting ask row holds the link; and no agent looked at it in the last
    :data:`CHECK_RECHECK_DAYS`. ``ignore_site`` lists what WOULD be checkable if a site were allowed (the permissions
    page); ``ignore_recent`` is for the authorization at record time. Empty while the master switch is off."""
    from api.services import fact_sources, source_check

    if not reading_settings.agent_enabled():
        return []
    memory_path = Path(memory_path)
    rows = _live_rows(memory_path, now)
    held = {r["url_hash"] for r in rows if r.get("state") != "waiting"}
    paused = paused_sites(rows)
    # One clock: every `at` is stamped in UTC (`episode_ids.utc_now_iso`), so the week is counted in UTC days.
    today = (now or datetime.now(timezone.utc)).date()
    cutoff = (today - timedelta(days=CHECK_RECHECK_DAYS)).isoformat()
    out: list[Entry] = []
    for item, t in candidates if candidates is not None else _check_candidates(memory_path, cached_only=cached_only):
        if deadline is not None and time.monotonic() > deadline:
            raise reading_walls.DeadlineExceeded()
        verdict = reading_hosts.agent_may_read(t.ref, enabled=True)
        if not verdict.ok or not verdict.site:
            continue
        if not ignore_site and (not reading_settings.site_allowed(verdict.site) or verdict.site in paused):
            continue
        h = media_ingestor.url_hash(t.ref)
        if h in held:
            continue
        last = _checked_map(item).get(t.ref)
        if not ignore_recent and last and last >= cutoff:
            continue
        linked = fact_sources.linked_entity(memory_path, {"entity": t.entity}, self_id=item.entity_id) if t.entity else None
        out.append(Entry(url=t.ref, url_hash=h, host=reading_hosts.display_host(verdict.host), site=verdict.site,
                         origin="check", since=item.created_date or "", title=item.question or item.title, wall=None,
                         walled=verdict.walled, item_id=item.id, entity_id=item.entity_id,
                         predicate=item.predicate or "", linked_entity=linked or "", access=t.access))
    return out


def _checked_map(item) -> dict[str, str]:
    """``{ref: day}`` from the item's served ``checks`` — the days an agent last looked."""
    out: dict[str, str] = {}
    for f in item.checks:
        ref = getattr(f, "ref", None)
        if ref:
            out[ref] = max(out.get(ref, ""), f.at[:10])
    return out


def authorizes_check(memory_path: Path, item_id: str, ref: str, *, now: datetime | None = None) -> Entry | None:
    """May an agent record a check of ``ref`` for inbox item ``item_id``? Only a source that is one of that item's own
    targets, on a site the person allowed, not paused, with the item still pending and checkable — recomputed now, so
    resolving the item, removing the source or switching the site off revokes it at once. Nothing stored grants it. The
    anti-plant rule: a URL that is not one of the item's listed sources gets nothing."""
    ref = (ref or "").strip()
    for e in check_entries(memory_path, now=now, ignore_recent=True):
        if e.item_id == item_id and e.url == ref:
            return e
    return None


def entries(memory_path: Path, *, include_words_origin: bool = True, now: datetime | None = None) -> list[Entry]:
    """The queue: the person's asks first (oldest ask first), then pages of allowed
    sites (oldest saved first), then the sources an agent could check an inbox question against (oldest question
    first). Empty while the master switch is off."""
    if not reading_settings.agent_enabled():
        return []
    memory_path = Path(memory_path)
    rows = _live_rows(memory_path, now)
    idx = media_ingestor.load_url_index(memory_path)
    return ask_entries(memory_path, rows, idx) + site_entries(
        memory_path, rows, include_words_origin=include_words_origin) + _safe_checks(memory_path, now)


def _safe_checks(memory_path: Path, now: datetime | None, *, cached_only: bool = False,
                 deadline: float | None = None) -> list[Entry]:
    """A broken inbox must never take the reading queue down with it. The hook's bounds (``cached_only``, ``deadline``)
    are not swallowed: they raise, so the caller can answer "unknown"."""
    try:
        return sorted(check_entries(memory_path, now=now, cached_only=cached_only, deadline=deadline),
                      key=lambda e: (e.since, e.item_id, e.url))
    except (_ColdCandidates, reading_walls.DeadlineExceeded):
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"check entries skipped: {type(exc).__name__}")
        return []


def authorizes(memory_path: Path, url: str, *, now: datetime | None = None) -> tuple[str, dict | None] | None:
    """May an agent record an outcome for ``url``? ``("ask", row)`` for a link the
    person asked about (or a site row, see below); ``("site", None)`` for a saved wall page, still without
    words, of a site the person allowed; else ``None``. The anti-plant rule:
    a saved public page with no wall, or a site not allowed, gets nothing."""
    memory_path = Path(memory_path)
    h = media_ingestor.url_hash(url)
    try:
        row = reading_asks.get(memory_path, h, now=now)
    except ValueError:
        row = None
    if row is not None and row.get("origin") != reading_asks.ORIGIN_SITE:
        return "ask", row
    # A row this tool wrote itself (``origin: site``, for a needs_login or a failed read of a site
    # page) is no consent of its own: the site grant is. It authorizes only while the site is still
    # allowed and the page is still a wall page waiting for words — switching the site off revokes
    # recording at once, as it dequeues at once.
    if not reading_settings.agent_enabled():
        return None
    page = reading_walls.scan_one(memory_path, url)
    if page is not None and page.waiting and reading_settings.site_allowed(page.site):
        return ("ask", row) if row is not None else ("site", None)
    return None


_warm_lock = threading.Lock()
_warming: set[str] = set()


def _warm_in_background(memory_path: Path) -> None:
    key = str(memory_path)
    with _warm_lock:
        if key in _warming:
            return
        _warming.add(key)

    def _run() -> None:
        try:
            # Parse the pages, then judge the wall candidates' bodies (memoised), so the next
            # counted prompt answers from memory instead of parsing inside the hook's budget.
            bank_index.files(memory_path, "entities")
            if reading_settings.allowed_sites():
                reading_walls.scan(memory_path)
            if reading_settings.agent_enabled():
                _check_candidates(memory_path)
        except Exception:  # noqa: BLE001
            pass
        finally:
            with _warm_lock:
                _warming.discard(key)

    threading.Thread(target=_run, name="reading-warm", daemon=True).start()


def warm(memory_path: Path) -> None:
    """Parse the bank's pages and judge its wall candidates in a background thread (once at a time
    per bank), so a later read of the queue answers from memory."""
    _warm_in_background(Path(memory_path))


def counts(memory_path: Path, *, warm_only: bool = False, include_words_origin: bool = True,
           deadline: float | None = None) -> tuple[int, int | None]:
    """``(asks, site entries)`` waiting. ``warm_only`` (the recall hook's 300 ms
    budget): the derived part is counted only when the bank's page cache is
    already warm; a cold cache counts the asks, starts a background warm and
    answers ``None`` for the derived part (unknown, not zero), so the next prompt
    counts the rest and a caller never mistakes 'not counted yet' for 'drained'. ``deadline``
    (a ``time.monotonic()`` value, the hook's budget) bounds the derived part too: a warm
    cache can still hold page bodies not yet judged (after a Sleep rewrite), so past the
    deadline the count is unknown, and the rest is finished in the background."""
    if not reading_settings.agent_enabled():
        return 0, 0
    memory_path = Path(memory_path)
    rows = _live_rows(memory_path, None)
    asks = 0
    if any(r.get("state") == "waiting" for r in rows):
        asks = len(ask_entries(memory_path, rows, media_ingestor.load_url_index(memory_path)))
    if not reading_settings.allowed_sites():
        return asks, 0
    if warm_only and not bank_index.is_warm(memory_path, "entities"):
        _warm_in_background(memory_path)
        return asks, None
    try:
        derived = len(site_entries(memory_path, rows, include_words_origin=include_words_origin,
                                   deadline=deadline if warm_only else None))
        # G61 S3: the sources an agent could check a pending question against count too, so the recall hook's
        # "links are waiting" note covers them with no new surface (G105's lesson: the agent is nudged without
        # having to decide to call a tool). Past the hook's deadline they are unknown, never zero.
        if deadline is not None and time.monotonic() > deadline:
            raise reading_walls.DeadlineExceeded()
        bounded = warm_only or deadline is not None
        return asks, derived + len(_safe_checks(memory_path, None, cached_only=bounded, deadline=deadline))
    except (reading_walls.DeadlineExceeded, _ColdCandidates):
        _warm_in_background(memory_path)
        return asks, None


def count_waiting(memory_path: Path, *, warm_only: bool = False, include_words_origin: bool = True) -> int:
    a, s = counts(memory_path, warm_only=warm_only, include_words_origin=include_words_origin)
    return a + (s or 0)


def resume_site(memory_path: Path, site: str) -> int:
    """Lift a site's ``needs_login`` pause (the person switched it on again, so
    'try again'). Returns how many rows were removed."""
    def _hit(row: dict) -> bool:
        return row.get("state") == "needs_login" and reading_hosts.site_of(row.get("host") or "") == site
    try:
        return reading_asks.drop_where(Path(memory_path), _hit)
    except ValueError:
        return 0


# --- the permissions page ------------------------------------------------------------------------------------


def site_rows(memory_path: Path, *, pages: list[reading_walls.WallPage] | None = None,
              now: datetime | None = None) -> list[dict]:
    """The sites Cicada's reader could not read, plus any site already allowed or
    holding a live ``needs_login`` row, with measured counts only — no URL, title
    or note. ``waiting`` = wall pages with no words and no live row of their own
    (for an allowed site exactly the queued ones); ``read`` = pages an agent read;
    ``needsLogin`` = live rows in that state. ``allowed`` is whether the permission
    counts right now (:func:`reading_settings.site_allowed`: false while the master
    switch is off); ``granted`` is the stored grant, so a switch drawn while agent
    reading is off can still show — and remove — what the person granted."""
    memory_path = Path(memory_path)
    pages = reading_walls.scan(memory_path) if pages is None else pages
    rows = _live_rows(memory_path, now)
    # A page with a recorded outcome is not waiting; one with a live ask still is.
    live = {r["url_hash"] for r in rows if r.get("state") != "waiting"}
    allowed = reading_settings.allowed_sites()
    counts = reading_settings.agent_enabled()
    sites: dict[str, dict] = {}

    def _site(key: str) -> dict:
        return sites.setdefault(key, {"walls": {}, "waiting": 0, "read": 0, "needs_login": 0, "checks": 0})

    for p in pages:
        s = _site(p.site)
        if p.read_by_agent:
            s["read"] += 1
        if p.waiting and p.url_hash not in live:
            s["waiting"] += 1
            s["walls"][p.wall] = s["walls"].get(p.wall, 0) + 1
        elif p.waiting:
            s["walls"].setdefault(p.wall, 0)
    for r in rows:
        if r.get("state") == "needs_login":
            key = reading_hosts.site_of(r.get("host") or "")
            if key:
                _site(key)["needs_login"] += 1
    # G61 S3: a site only sources reach — a profile page that could answer a pending question — is listed too, with how
    # many questions it could answer, so the person can allow it (the one consent). Counts only.
    try:
        by_site: dict[str, set[str]] = {}
        for e in check_entries(memory_path, now=now, ignore_site=True):
            by_site.setdefault(e.site, set()).add(e.item_id)
        for key, ids in by_site.items():
            _site(key)["checks"] = len(ids)
    except Exception as exc:  # noqa: BLE001 — the permissions page never fails on the inbox
        logger.warning(f"check counts skipped: {type(exc).__name__}")
    for key in allowed:
        _site(key)
    out = []
    for key, s in sites.items():
        if not s["walls"] and key not in allowed and not s["needs_login"] and not s["read"] and not s["checks"]:
            continue
        wall = None
        if s["walls"]:
            wall = sorted(s["walls"].items(), key=lambda kv: (-kv[1], reading_walls.WALL_KINDS.index(kv[0])))[0][0]
        out.append({
            "site": key, "label": reading_hosts.site_label(key), "wall": wall,
            "allowed": counts and key in allowed, "granted": key in allowed,
            "since": allowed.get(key) or None, "waiting": s["waiting"], "read": s["read"],
            "needsLogin": s["needs_login"], "checks": s["checks"], "note": reading_hosts.SITE_NOTES.get(key),
            "iconHost": reading_hosts.icon_host(key),
        })
    out.sort(key=lambda r: (not (r["allowed"] and r["needsLogin"]), -r["waiting"], r["label"].lower()))
    return out


# --- the memoised snapshot the sites route and the icon route share ------------------------------------------

SITES_SHAPE = "reading-sites-4"
_snapshots: dict[str, tuple[str, list[dict]]] = {}
_snapshot_lock = threading.Lock()


def sites_stamp(memory_path: Path) -> str:
    """The ETag the sites list carries — over the ``reading``, ``entities`` and ``sources``
    components (and, since G61 S3, ``inbox``: a question raised or answered changes what a source could check), so it
    moves exactly when a permission, an outcome, a page or a question does."""
    from api.services import sync_service

    return sync_service.etag_for(Path(memory_path), "reading", "entities", "sources", "inbox", extra=SITES_SHAPE)


def sites_snapshot(memory_path: Path) -> list[dict]:
    """:func:`site_rows`, memoised per bank on :func:`sites_stamp`, so the list route and
    the icon route (one request per row) do one scan between changes, not one each.
    Blocking (a cold bank parse): call it off the event loop."""
    key = str(memory_path)
    stamp = sites_stamp(memory_path)
    with _snapshot_lock:
        held = _snapshots.get(key)
        if held is not None and held[0] == stamp:
            return held[1]
    rows = site_rows(Path(memory_path))
    with _snapshot_lock:
        _snapshots[key] = (stamp, rows)
    return rows
