"""Bounds a request meets before any route parses it (backend hunt, 2026-10-16; G181).

Two holes the hunt measured, both behind the token but reachable from a device over an overlay now:

* **A name longer than any file's.** A 3,000-character id in a path (``/entities/{id}``, ``/projects/{id}``,
  ``/backlog/{id}/{item}``…) reached ``Path.exists()`` and surfaced as a 500 (``ENAMETOOLONG``). No id Cicada mints or
  stores is longer than a file name, so a path segment past ``NAME_MAX`` bytes names nothing: 404, before any route.
* **A body read whole before its bound.** ``PUT /sources/messages/photos`` decoded every photo's base64 before its
  256 KB check, and ``POST /capture/session`` parsed every turn before ``MAX_TURNS``. Each route here has a ceiling well
  above anything its own client sends; a declared ``Content-Length`` past it is refused at once (413), and a body that
  arrives without one is counted as it streams and refused the moment it passes.

A pure ASGI middleware, so the event stream (SSE) and every other response pass through untouched.
"""
from __future__ import annotations

from urllib.parse import unquote

from fastapi import HTTPException

#: A file name's limit in bytes on every filesystem Cicada runs on (APFS, ext4).
NAME_MAX = 255

#: Route → the most bytes its body may hold. The session post is capped server-side at 100k characters of kept text
#: (``transcript_extract.SESSION_CAP_CHARS``) — at worst six bytes a character escaped, plus each turn's fields; the
#: Messages photos are ≤ 128 px thumbnails, at most ``messages_photos.MAX_ITEMS`` of them.
BODY_LIMITS: dict[str, int] = {
    "/capture/session": 8 * 1024 * 1024,
    # Ruling 43: an agent's memory notes, every one under the harness root — the hook sends at most 8 MB of note text
    # (`api/hooks/memory_notes.MAX_POST_BYTES`), JSON-escaped.
    "/capture/agent-memory": 12 * 1024 * 1024,
    # G91 (ruling 38): a shared photo or file, ≤ 25 MB (`capture_files.MAX_BYTES`), plus its caption and the multipart
    # framing — refused before FastAPI spools a single byte of a bigger one.
    "/capture/file": 26 * 1024 * 1024,
    "/sources/messages/photos": 24 * 1024 * 1024,
    # G218: at most 2,000 spans of short fields; one ≤ 2 MB screenshot as base64 plus its recognized text.
    "/sources/traces/sync": 4 * 1024 * 1024,
    "/sources/traces/frames": 4 * 1024 * 1024,
}

NAME_TOO_LONG = b'{"detail":"Not found: a name in this address is longer than any file name can be."}'
TOO_LARGE = "This request's body is larger than this route ever accepts."


def _segment_too_long(path: str) -> bool:
    return any(len(unquote(part).encode("utf-8", "surrogatepass")) > NAME_MAX for part in path.split("/") if part)


class RequestLimits:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path") or ""
        if _segment_too_long(path):
            await send({"type": "http.response.start", "status": 404,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(NAME_TOO_LONG)).encode())]})
            await send({"type": "http.response.body", "body": NAME_TOO_LONG})
            return
        limit = BODY_LIMITS.get(path.rstrip("/") or "/")
        if limit is None:
            return await self.app(scope, receive, send)
        declared = None
        for name, value in scope.get("headers") or ():
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
        if declared is not None and declared > limit:
            body = ('{"detail":"%s"}' % TOO_LARGE).encode()
            await send({"type": "http.response.start", "status": 413,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        seen = 0

        async def counted():
            nonlocal seen
            message = await receive()
            if message.get("type") == "http.request":
                seen += len(message.get("body") or b"")
                if seen > limit:
                    # Raised inside the route's own body read, so FastAPI answers it like any HTTPException.
                    raise HTTPException(status_code=413, detail=TOO_LARGE)
            return message

        return await self.app(scope, counted, send)
