"""The reading queue — the one read model behind the tool, the hook, the Feed and the settings page (G166).

An agent's queue is two kinds of entry, computed at read and never fanned out
as rows:

* **asks** — links the person asked about with "Ask an agent" (rows in the
  machine-wide ask store, ``reading_asks``);
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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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
    origin: str          # "ask" | "site"
    since: str           # ISO day: when asked, or when saved
    title: str
    wall: str | None
    walled: bool         # a closed-set walled host (pacing: one per call)


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


def entries(memory_path: Path, *, include_words_origin: bool = True, now: datetime | None = None) -> list[Entry]:
    """The queue: the person's asks first (oldest ask first), then pages of allowed
    sites (oldest saved first). Empty while the master switch is off."""
    if not reading_settings.agent_enabled():
        return []
    memory_path = Path(memory_path)
    rows = _live_rows(memory_path, now)
    idx = media_ingestor.load_url_index(memory_path)
    return ask_entries(memory_path, rows, idx) + site_entries(
        memory_path, rows, include_words_origin=include_words_origin)


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
        return asks, len(site_entries(memory_path, rows, include_words_origin=include_words_origin,
                                      deadline=deadline if warm_only else None))
    except reading_walls.DeadlineExceeded:
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
    ``needsLogin`` = live rows in that state."""
    memory_path = Path(memory_path)
    pages = reading_walls.scan(memory_path) if pages is None else pages
    rows = _live_rows(memory_path, now)
    # A page with a recorded outcome is not waiting; one with a live ask still is.
    live = {r["url_hash"] for r in rows if r.get("state") != "waiting"}
    allowed = reading_settings.allowed_sites()
    sites: dict[str, dict] = {}

    def _site(key: str) -> dict:
        return sites.setdefault(key, {"walls": {}, "waiting": 0, "read": 0, "needs_login": 0})

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
    for key in allowed:
        _site(key)
    out = []
    for key, s in sites.items():
        if not s["walls"] and key not in allowed and not s["needs_login"] and not s["read"]:
            continue
        wall = None
        if s["walls"]:
            wall = sorted(s["walls"].items(), key=lambda kv: (-kv[1], reading_walls.WALL_KINDS.index(kv[0])))[0][0]
        out.append({
            "site": key, "label": reading_hosts.site_label(key), "wall": wall, "allowed": key in allowed,
            "since": allowed.get(key) or None, "waiting": s["waiting"], "read": s["read"],
            "needsLogin": s["needs_login"], "note": reading_hosts.SITE_NOTES.get(key),
            "iconHost": reading_hosts.icon_host(key),
        })
    out.sort(key=lambda r: (not (r["allowed"] and r["needsLogin"]), -r["waiting"], r["label"].lower()))
    return out


# --- the memoised snapshot the sites route and the icon route share ------------------------------------------

SITES_SHAPE = "reading-sites-2"
_snapshots: dict[str, tuple[str, list[dict]]] = {}
_snapshot_lock = threading.Lock()


def sites_stamp(memory_path: Path) -> str:
    """The ETag the sites list carries — over the ``reading``, ``entities`` and ``sources``
    components, so it moves exactly when a permission, an outcome or a page does."""
    from api.services import sync_service

    return sync_service.etag_for(Path(memory_path), "reading", "entities", "sources", extra=SITES_SHAPE)


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
