"""Cheap change detection for the companion app's sync engine (G58).

A version vector built from directory mtimes + git HEAD (read from
``.git/HEAD``, no subprocess) + sleep state. Sub-10 ms, so the app can poll
it or subscribe to ``/sync/events`` and refresh only what changed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fastapi import Request, Response

from api.services import bank_index, markdown_parser
from api.services.calendar_registry import CALENDARS_FILENAME
from api.services.feed_registry import FEEDS_FILENAME
from api.services.graph_builder import dir_mtime, file_mtime, inbox_mtime


@dataclass
class VersionInfo:
    version: str
    components: dict


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
_DEFER_CACHE: dict[str, tuple[float, bool]] = {}


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


def _inbox_has_pending_defer(mp: Path, mtime: float) -> bool:
    """True when any *pending* inbox item carries a ``remind_after`` date.

    ``load_inbox``'s ``is_deferred`` filter (api/services/inbox_service.py)
    hides an item purely by comparing ``remind_after`` to ``date.today()`` --
    no file changes the day the date passes, so file-mtime-only components
    never notice. Folding today's date into the "inbox" component below
    whenever such an item exists makes the ETag re-validate daily instead of
    serving a stale 304 forever once a deferred item's due date arrives.

    Cached on ``mtime`` (``graph_builder.inbox_mtime``, which folds in the
    inbox dir's own mtime as well as every ``*.md`` inside it), so a defer, an
    undelete, a resolve or any other inbox write invalidates it while a quiet
    inbox costs one dict lookup.
    """
    key = str(mp)
    cached = _DEFER_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    result = _scan_inbox_for_pending_defer(mp)
    _DEFER_CACHE[key] = (mtime, result)
    return result


def components(memory_path: Path, *, sleep_state=None) -> dict[str, str]:
    mp = Path(memory_path)
    ep_count, ep_max = bank_index.dir_stamp(mp, "episodes")
    src_count, src_max = bank_index.dir_stamp(mp, "sources")
    inbox_stamp = inbox_mtime(mp)
    inbox_component = f"{inbox_stamp:.6f}"
    if _inbox_has_pending_defer(mp, inbox_stamp):
        # Cheap: today's date is enough to force a re-validate once a day: the
        # exact remind_after value doesn't matter, only that "today" advanced.
        inbox_component += f":{date.today().isoformat()}"
    return {
        "entities": f"{dir_mtime(mp / 'entities'):.6f}",
        "edges": f"{file_mtime(mp / 'graph_edges.yaml'):.6f}",
        "hubs": f"{dir_mtime(mp / 'hubs'):.6f}",
        "inbox": inbox_component,
        "episodes": f"{ep_count}:{ep_max}",
        # `feeds.yaml` / `calendars.yaml` (the RSS + ICS subscription registries)
        # ride the `sources` component: subscribing or unsubscribing changes
        # neither the sources dir nor the url index, so without them the app's
        # feed/calendar lists never learned they were stale.
        "sources": (
            f"{src_count}:{src_max}"
            f":{file_mtime(mp / 'sources' / 'url_index.json'):.6f}"
            f":{file_mtime(mp / FEEDS_FILENAME):.6f}"
            f":{file_mtime(mp / CALENDARS_FILENAME):.6f}"
        ),
        "git_head": git_head(mp),
        "bank": mp.name,
        "sleep": f"{getattr(sleep_state, 'status', 'idle')}:{getattr(sleep_state, 'cycle_id', '') or ''}",
    }


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
