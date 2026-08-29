"""Cheap change detection for the companion app's sync engine (G58).

A version vector built from directory mtimes + git HEAD (read from
``.git/HEAD``, no subprocess) + sleep state. Sub-10 ms, so the app can poll
it or subscribe to ``/sync/events`` and refresh only what changed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from fastapi import Request, Response

from api.services import bank_index
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


def components(memory_path: Path, *, sleep_state=None) -> dict[str, str]:
    mp = Path(memory_path)
    ep_count, ep_max = bank_index.dir_stamp(mp, "episodes")
    src_count, src_max = bank_index.dir_stamp(mp, "sources")
    return {
        "entities": f"{dir_mtime(mp / 'entities'):.6f}",
        "edges": f"{file_mtime(mp / 'graph_edges.yaml'):.6f}",
        "hubs": f"{dir_mtime(mp / 'hubs'):.6f}",
        "inbox": f"{inbox_mtime(mp):.6f}",
        "episodes": f"{ep_count}:{ep_max}",
        "sources": f"{src_count}:{src_max}:{file_mtime(mp / 'sources' / 'url_index.json'):.6f}",
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
