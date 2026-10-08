"""Cheap change detection for the companion app's sync engine (G58).

A version vector built from directory mtimes + git HEAD (read from
``.git/HEAD``, no subprocess) + sleep state. Sub-10 ms, so the app can poll
it or subscribe to ``/sync/events`` and refresh only what changed.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import Request, Response

from api.services import (backlog, bank_index, logo_service, markdown_parser, reading_asks, reading_settings,
                              telemetry, video_queue)
from api.services.calendar_registry import CALENDARS_FILENAME
from api.services.feed_registry import FEEDS_FILENAME
from api.services.folder_source import FOLDERS_FILENAME
from api.services.graph_builder import file_mtime, inbox_stamp
from api.services.sync_state import SYNC_STATE_FILENAME
from api.services.wispr_flow import SETTINGS_FILENAME as WISPR_SETTINGS_FILENAME


@dataclass
class VersionInfo:
    version: str
    components: dict


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def git_head(memory_path: Path) -> str:
    git_dir = Path(memory_path) / ".git"
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not head.startswith("ref:"):
        return head
    ref = head.split(":", 1)[1].strip()
    ref_file = git_dir / ref
    try:
        return ref_file.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    try:
        for line in (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0]
    except OSError:
        pass
    return ""


# One-entry-per-bank cache for :func:`_inbox_has_pending_defer`, keyed on the
# inbox mtime stamp that ``components()`` already computes. ``components()`` is
# on the ``/sync/version`` hot path (the SSE loop polls it once a second, and
# every ETag check for graph/inbox/sources/origins/banks calls it), so the
# YAML parse below must not run per call -- only when the inbox actually moves.
_DEFER_CACHE: dict[str, tuple[str, bool]] = {}


def _scan_inbox_for_pending_defer(mp: Path) -> bool:
    inbox_dir = mp / "inbox"
    if not inbox_dir.exists():
        return False
    for filepath in inbox_dir.glob("inbox-*.md"):
        try:
            fm = markdown_parser.parse(filepath).frontmatter
        except Exception:
            continue
        if str(fm.get("status", "pending") or "pending") != "pending":
            continue
        if fm.get("remind_after"):
            return True
    return False


def _inbox_has_pending_defer(mp: Path, mtime) -> bool:
    """True when any *pending* inbox item carries a ``remind_after`` date.

    ``load_inbox``'s ``is_deferred`` filter (api/services/inbox_service.py)
    hides an item purely by comparing ``remind_after`` to ``date.today()`` --
    no file changes the day the date passes, so file-mtime-only components
    never notice. Folding today's date into the "inbox" component below
    whenever such an item exists makes the ETag re-validate daily instead of
    serving a stale 304 forever once a deferred item's due date arrives.

    Cached on the inbox's stamp (``graph_builder.inbox_stamp``, a fingerprint
    of every ``*.md`` in it), so a defer, an undelete, a resolve or any other
    inbox write invalidates it while a quiet inbox costs one dict lookup.
    """
    key = str(mp)
    cached = _DEFER_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    result = _scan_inbox_for_pending_defer(mp)
    _DEFER_CACHE[key] = (mtime, result)
    return result


# Per-bank memo for :func:`_logos_component`: (meta mtime, expired count, epoch
# of the next expiry). Rescanned when `meta.json` is rewritten OR when the next
# TTL deadline passes — so the ~1/s `/sync/version` poll costs one dict lookup,
# not a JSON parse, while still noticing an expiry the same second it happens.
_LOGO_TTL_CACHE: dict[str, tuple[float, int, float | None]] = {}


def _logos_component(mp: Path) -> str:
    """The logo cache's version stamp: ``<meta.json mtime>:<expired entries>``.

    The mtime alone is blind to a purely time-based TTL expiry — nothing is
    written when an entry simply ages out — yet ``/graph``'s ``has_logo`` is
    computed from ``logo_service.is_fresh`` at read time, so the node silently
    stops claiming a logo behind an ETag that never moved. The expired count
    moves on exactly those transitions (see ``logo_service.expiry_state``).
    """
    bank = logo_service.bank_name(mp)
    mtime = file_mtime(logo_service.meta_path(bank))
    cached = _LOGO_TTL_CACHE.get(bank)
    if (
        cached is None
        or cached[0] != mtime
        or (cached[2] is not None and time.time() >= cached[2])
    ):
        expired, next_expiry = logo_service.expiry_state(bank)
        _LOGO_TTL_CACHE[bank] = (mtime, expired, next_expiry)
    else:
        expired = cached[1]
    return f"{mtime:.6f}:{expired}"


# Per-bank memo for :func:`_reading_component`, the same shape as the logos one:
# (asks mtime, expired count, epoch of the next expiry).
_READING_TTL_CACHE: dict[str, tuple[float, int, float | None]] = {}


def _reading_component(mp: Path) -> str:
    """``<asks mtime>:<expired asks>:<settings mtime>``. An ask row expires in memory
    at read time and nothing is written, so without the expired count a site's
    ``needs_login`` pause that aged out would keep serving from every ETag built
    on this component (``/reading/sites``, ``/reading/asks``, ``/sources``)."""
    mtime = reading_asks.mtime(mp)
    key = str(mp)
    cached = _READING_TTL_CACHE.get(key)
    if (
        cached is None
        or cached[0] != mtime
        or (cached[2] is not None and time.time() >= cached[2])
    ):
        expired, next_expiry = reading_asks.expiry_state(mp)
        _READING_TTL_CACHE[key] = (mtime, expired, next_expiry)
    else:
        expired = cached[1]
    return f"{mtime:.6f}:{expired}:{reading_settings.mtime():.6f}"


def components(memory_path: Path, *, sleep_state=None) -> dict[str, str]:
    mp = Path(memory_path)
    # Audit 2026-10-05 P2-9: every directory component is a fingerprint of its
    # files' names, sizes and nanosecond mtimes (`bank_index.dir_fingerprint`,
    # one shared scan) — "the newest mtime" stood still for an edit beside a
    # future-dated file, and the app's ETags answered 304 over a changed page.
    stamp = inbox_stamp(mp)
    inbox_component = stamp
    if _inbox_has_pending_defer(mp, stamp):
        # Cheap: today's date is enough to force a re-validate once a day: the
        # exact remind_after value doesn't matter, only that "today" advanced.
        inbox_component += f":{date.today().isoformat()}"
    return {
        "entities": bank_index.dir_fingerprint(mp / "entities"),
        "edges": f"{file_mtime(mp / 'graph_edges.yaml'):.6f}",
        "hubs": bank_index.dir_fingerprint(mp / "hubs"),
        "inbox": inbox_component,
        "episodes": bank_index.dir_fingerprint(mp / "episodes"),
        # G150 R-B16: every backlog item's stamp (a stat walk, no parse) — the
        # Projects page's backlog reads and `_state.md`'s `backlog_open` move
        # on it; nothing in `entities`/`episodes` notices a backlog write.
        "backlog": backlog.stamp(mp),
        # `feeds.yaml` / `calendars.yaml` (the RSS + ICS subscription registries)
        # ride the `sources` component: subscribing or unsubscribing changes
        # neither the sources dir nor the url index, so without them the app's
        # feed/calendar lists never learned they were stale. `sync_state.json`
        # (G62) rides it for the same reason: a bookmark/Notes sync flips a
        # channel to "connected" without touching any other component.
        # `sources/folders.json` (G133) rides it too: registering or renaming a
        # folder adds or relabels a channel row without touching any other
        # component. So does `sources/wispr_flow.json` (G134): turning the
        # source on adds a channel row the same way (R-LS29).
        "sources": (
            f"{bank_index.dir_fingerprint(mp / 'sources')}"
            f":{file_mtime(mp / 'sources' / 'url_index.json'):.6f}"
            f":{file_mtime(mp / 'sources' / FOLDERS_FILENAME):.6f}"
            f":{file_mtime(mp / 'sources' / WISPR_SETTINGS_FILENAME):.6f}"
            f":{file_mtime(mp / FEEDS_FILENAME):.6f}"
            f":{file_mtime(mp / CALENDARS_FILENAME):.6f}"
            f":{file_mtime(mp / SYNC_STATE_FILENAME):.6f}"
        ),
        # The logo cache lives at `$CICADA_HOME/logos/<bank>/`, *outside* the
        # memory bank, so no other component notices when a warm-up or an
        # on-demand fetch flips an entity to "has a logo" — and `/graph` bakes
        # `has_logo` into every node's `content_hash`. Without this the app's
        # conditional GET 304s and the node keeps painting a monogram forever.
        # (The other direction — an entry aging out of its TTL, which writes
        # nothing — rides the expired count; see `_logos_component`.)
        "logos": _logos_component(mp),
        # G162: the person's video queue lives at `$CICADA_HOME/video_queue/<bank>.json`,
        # OUTSIDE the bank, so a queued video, an agent's lease or a hand-back moves nothing
        # above. `stamp` is the file's mtime plus how many leases, failed rows and finished
        # batches have come DUE with nothing written (a lease lapsing writes nothing, yet it
        # changes what /videos/state says). The app revalidates its VideoStateCache on this
        # component (VideoRefresh); it is NOT a Store domain and NOT in `_state.md`'s digest.
        "videoQueue": video_queue.stamp(mp),
        # G166: the reading asks live at `$CICADA_HOME/reading_asks/<bank>.json`
        # and the person's reading settings at `$CICADA_HOME/reading.json` —
        # both OUTSIDE the bank, so nothing above notices a "needs you to sign
        # in" outcome, an ask, or a per-site switch. The app maps this
        # component onto `.sources` (the Feed's read state rides `/sources`),
        # so the outcome shows over SSE within a second, with no bank write. A row
        # aging out writes nothing and rides the expired count (`_reading_component`).
        "reading": _reading_component(mp),
        # The consumption ledger lives at `$CICADA_HOME/telemetry/events-YYYY-MM.jsonl`,
        # *outside* the memory bank (it's machine-global, not per-bank), so no other
        # component notices a new usage event landing. Modelled on "logos" above for
        # the same reason. Only the current month's file is watched: a new LLM call,
        # sleep run, or agentic write always appends to it. The month is UTC's,
        # because that is the clock `telemetry.record` stamps events with — the
        # machine's local month names the wrong file either side of a boundary.
        # The sibling `reads-YYYY-MM.jsonl` (the `read` kind, G124) is
        # deliberately NOT stat'd: the app maps this component onto its
        # `.consumption` domain, and a tick refetches every `/consumption/*`
        # endpoint — five GETs per entity-card open, `/harness` walking
        # `~/.codex/sessions` among them (G124 final review M2). The one
        # endpoint that reports reads folds that file's mtime into its own
        # ETag (`/contributors/top-entities`).
        "telemetry": (
            f"{file_mtime(telemetry.ledger_file(f'{_utc_now():%Y-%m}')):.6f}"
        ),
        "git_head": git_head(mp),
        "bank": mp.name,
        # A paused run (Sleep page v5) is not a status: it lives in a machine-local sidecar, so
        # Pause, Continue, End, a restart and an armed auto-continue move this on their own.
        # G177 — the write window too: the app's write controls follow `writing`, which flips between a drain's
        # batches with no status change, and `/status` has no ETag of its own to move.
        "sleep": (f"{getattr(sleep_state, 'status', 'idle')}:{getattr(sleep_state, 'cycle_id', '') or ''}"
                  f"{_writing_token(sleep_state)}{_paused_token(mp)}"),
        # The Sleep engine choice lives in `$CICADA_HOME/connections.json`, outside every bank, so a
        # `PUT /sleep/engine` from anywhere but the app's own menu (curl, an agent, the CLI) moved nothing
        # and the Sleep page kept naming the old engine until it was reopened. The app reloads its engine
        # response (not a Store domain) when this moves. While a run of this bank reads, the engine it
        # pinned at its start rides along, so the page learns when a run starts or ends on another engine.
        "engine": _engine_token(mp, sleep_state),
    }


def _engine_token(mp: Path, sleep_state) -> str:
    from api.services.auth import cicada_home
    from api.services.connections.registry import PREFS_FILE_NAME

    try:
        st = (cicada_home() / PREFS_FILE_NAME).stat()
        token = f"{st.st_mtime_ns}.{st.st_size}"
    except OSError:
        token = "0"
    ds = getattr(sleep_state, "drain", None) if getattr(sleep_state, "status", None) == "running" else None
    if ds is not None and getattr(ds, "memory_path", None) in (None, mp) and getattr(ds, "engine_label", None):
        token += f":{ds.engine_label}/{getattr(ds, 'engine_shown', None) or ''}"
    return token


def _writing_token(sleep_state) -> str:
    if sleep_state is None:
        return ""
    from api.services import sleep_cycle

    return ":writing" if sleep_cycle.writing_of(sleep_state) else ""


def _paused_token(mp: Path) -> str:
    try:
        from api.services import sleep_paused

        token = sleep_paused.sync_token(mp)
    except Exception:  # noqa: BLE001 - a version read must never fail
        token = ""
    return f":{token}" if token else ""


def _digest(parts: dict) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


def version(memory_path: Path, sleep_state=None) -> VersionInfo:
    comps = components(memory_path, sleep_state=sleep_state)
    return VersionInfo(version=_digest(comps), components=comps)


def etag_for(memory_path: Path, *keys: str, extra: str = "") -> str:
    """ETag over the named components, plus an optional ``extra`` string folded
    into the digest — for varying request state (query params, filters) that
    changes the response body but isn't reflected in any filesystem component.
    """
    comps = components(memory_path)
    parts: dict = {k: comps[k] for k in keys}
    if extra:
        parts["_extra"] = extra
    return '"' + _digest(parts) + '"'


def conditional(request: Request, response: Response, etag: str) -> Response | None:
    """Set ``ETag``; return a 304 response when the client already has it."""
    response.headers["ETag"] = etag
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return None
