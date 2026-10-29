"""`Idempotency-Key` on the capture routes (G212, 2026-10-22): a resend is the first answer, never a second write.

A phone's offline queue sends each capture with its own key. When the server saved it but the phone never heard back
(the app died, the network dropped), the resend carries the same key: the server answers what it answered the first
time and writes nothing — not a second episode, not a second "Note on …". Measured before this: a resent link with a
note wrote one extra note episode.

Keys live outside every bank, in ``$CICADA_HOME/idempotency/keys.db`` (0700/0600, sqlite), scoped to who sent them
(the device's id, or ``server`` for the server's own token), the bank (its id) and the route, and are forgotten after a day (8 days for the capture routes and the tool door, below) — long
enough for an offline queue's retries, short enough to keep nothing about what was saved: a row is the scope, the
route, the key's sha256, the status and the answer's JSON (ids and titles, no request body). A request with no key
runs as before. A key the client reuses for a different request gets the first answer — the key is the client's
promise that it is the same request.

**The tool door (G132 phase 1, ruling 51a).** ``POST /tools/call`` keys a mutating tool's call under the route
``/tools/call:<tool>``, kept 8 days (:data:`TOOLS_TTL_S`: an outbox entry waits at most 7); its kept answer is the
tool's reply (the confirmation the agent was shown), only when it was neither a refusal nor an error.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from api.services.auth import cicada_home

HEADER = "Idempotency-Key"
TTL_S = 24 * 3600
#: G132 phase 1 (coordinator decision 4, 2026-10-29): a write another device sends through the tool door may wait in
#: its outbox up to 7 days, so its key outlives that by a day. Every other route keeps :data:`TTL_S`.
TOOLS_ROUTE_PREFIX = "/tools/call:"
TOOLS_TTL_S = 8 * 24 * 3600


#: Review of #566: the capture routes a copy's outbox (or a phone's queue) may send again, days later, with the key
#: it sent first — kept as long as a tool door key, so an answer lost and resent after a day is still applied once.
LONG_ROUTES = frozenset({"/capture/note", "/capture/file", "/sources/save"})


def _long(route: str) -> bool:
    return route.startswith(TOOLS_ROUTE_PREFIX) or route in LONG_ROUTES


def ttl_for(route: str) -> float:
    return TOOLS_TTL_S if _long(route) else TTL_S
KEY_MAX = 200
_SCHEMA = """
CREATE TABLE IF NOT EXISTS keys (
    scope TEXT NOT NULL,
    route TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    created REAL NOT NULL,
    status INTEGER NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (scope, route, key_hash)
)"""
#: One in-flight request per (scope, route, key) in this process: a resend that arrives while the first is still
#: writing waits for it and gets its answer instead of racing it.
_LOCKS: dict[tuple[str, str, str], asyncio.Lock] = {}


def _path() -> Path:
    folder = cicada_home() / "idempotency"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    path = folder / "keys.db"
    if not path.exists():
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
    return path


@contextmanager
def _db():
    conn = sqlite3.connect(_path(), timeout=5)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def clean_key(raw: str | None) -> str | None:
    value = (raw or "").strip()
    if not value or len(value) > KEY_MAX or not value.isprintable():
        return None
    return value


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _lookup(scope: str, route: str, key_hash: str, now: float) -> tuple[int, dict] | None:
    with _db() as db:
        long_routes = sorted(LONG_ROUTES)
        marks = ",".join("?" for _ in long_routes)
        is_long = f"(substr(route, 1, ?) = ? OR route IN ({marks}))"
        prefix = (len(TOOLS_ROUTE_PREFIX), TOOLS_ROUTE_PREFIX)
        db.execute(f"DELETE FROM keys WHERE created < ? AND NOT {is_long}", (now - TTL_S, *prefix, *long_routes))
        db.execute(f"DELETE FROM keys WHERE created < ? AND {is_long}", (now - TOOLS_TTL_S, *prefix, *long_routes))
        row = db.execute("SELECT status, body FROM keys WHERE scope=? AND route=? AND key_hash=?",
                         (scope, route, key_hash)).fetchone()
    return (int(row[0]), json.loads(row[1])) if row is not None else None


def _remember(scope: str, route: str, key_hash: str, now: float, status: int, body: dict) -> None:
    with _db() as db:
        db.execute("INSERT OR REPLACE INTO keys VALUES (?, ?, ?, ?, ?, ?)",
                   (scope, route, key_hash, now, status, json.dumps(body)))


def export_since(since: float) -> list[dict]:
    """G132 phase 2 (review of #569): every key kept since ``since`` — scope, route, the key's sha256, when, and the
    answer it replays — for the person's other full devices, so a write sent again after the home moved is applied
    once there too. Never the key itself."""
    with _db() as db:
        rows = db.execute("SELECT scope, route, key_hash, created, status, body FROM keys WHERE created >= ? "
                          "ORDER BY created", (since,)).fetchall()
    return [{"scope": r[0], "route": r[1], "keyHash": r[2], "created": r[3], "status": r[4], "body": r[5]}
            for r in rows]


def import_rows(rows: list[dict]) -> int:
    """Take another home's keys (a copy following it; a new home at its promotion). A key kept here wins."""
    taken = 0
    with _db() as db:
        for r in rows or ():
            try:
                db.execute("INSERT OR IGNORE INTO keys VALUES (?, ?, ?, ?, ?, ?)",
                           (str(r["scope"]), str(r["route"]), str(r["keyHash"]), float(r["created"]),
                            int(r["status"]), str(r["body"])))
                taken += 1
            except (KeyError, TypeError, ValueError):
                continue
    return taken


def newest() -> float:
    with _db() as db:
        row = db.execute("SELECT MAX(created) FROM keys").fetchone()
    return float(row[0] or 0) if row else 0.0


async def run_once(scope: str, route: str, key: str | None, work, *, now=time.time,
                   keep=None) -> tuple[int, dict, bool]:
    """``(status, body, replayed)``. ``await work()`` returns ``(status, body)``; only a 2xx answer is kept, so a
    refused request (Sleep held the pages, a bad link) runs again when it is sent again. ``keep(status, body)`` narrows
    that further for a door whose refusals answer 200 (``/tools/call``: a reply with a refusal code or an error).
    Without a key, ``work`` runs as before."""
    key = clean_key(key)
    if key is None:
        status, body = await work()
        return status, body, False
    key_hash = _hash(key)
    lock = _LOCKS.setdefault((scope, route, key_hash), asyncio.Lock())
    async with lock:
        try:
            seen = await asyncio.to_thread(_lookup, scope, route, key_hash, now())
            if seen is not None:
                return seen[0], seen[1], True
            status, body = await work()
            if 200 <= status < 300 and (keep is None or keep(status, body)):
                await asyncio.to_thread(_remember, scope, route, key_hash, now(), status, body)
            return status, body, False
        finally:
            if not lock._waiters:   # noqa: SLF001 — drop an idle lock so the map never grows without bound
                _LOCKS.pop((scope, route, key_hash), None)


def scope_of(request) -> str:
    """Who a key belongs to and where it was written: the device whose token signed the request (else the server's
    own token) and the bank the request is pinned to (its id) — so a resend after a bank switch runs in the bank now
    open instead of answering with the other bank's episode id."""
    from api.services import bank_registry

    device = getattr(request.state, "device", None)
    who = f"device:{device.id}" if device is not None else "server"
    pin = bank_registry.pinned_bank()
    return f"{who}|bank:{pin.id if pin is not None and pin.id else '-'}"
