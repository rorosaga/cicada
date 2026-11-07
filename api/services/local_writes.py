"""A count of the writes this backend process makes, for the ETag listings' gate (speed 2026-10-29, item (e)).

A request's ETag may answer from the SSE tick's last walk of the bank (``sync_ticker.reusable_listings``) only while
nothing changed since that walk. The bank's watcher (``bank_watch``) sees every change, but reports one after a
debounce (``DEBOUNCE_MS``), so the person's own answer — a ``POST`` this process wrote a moment ago — could be served a
304 from before it. This counter closes that window for this process's own writes: every page write and delete through
``markdown_parser``, and every request that is not a read (counted when it starts and again when it ends, so a writer
that never goes through ``markdown_parser`` is covered too). A change from another process (the MCP server, the CLI,
an editor) is the watcher's, and the fallback walk catches anything both miss.
"""
from __future__ import annotations

import itertools
import threading

_COUNTER = itertools.count(1)
_lock = threading.Lock()
_current = 0

#: Methods that never write.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def bump() -> None:
    global _current
    with _lock:
        _current = next(_COUNTER)


def current() -> int:
    with _lock:
        return _current


class CountWrites:
    """ASGI middleware: a request that may write bumps the count when it arrives and again when it is done."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or str(scope.get("method") or "GET").upper() in SAFE_METHODS:
            return await self.app(scope, receive, send)
        bump()
        try:
            return await self.app(scope, receive, send)
        finally:
            bump()
