"""Last seen, without telemetry (G217): which agent and which device reached Cicada, and when.

Before this, a stdio agent's only sighting was the ``handshake`` row in the telemetry ledger, so with
``CICADA_TELEMETRY=off`` every local agent read "not seen" (``agent_live``'s own docstring said so). This registry is
not telemetry: it holds what the Agents and Devices pages draw and nothing else.

**What a row holds — names, devices and times only.** An agent row is ``(agent id, device id, via, first seen, last
seen, calls)``: the agent id is the catalog way (``agent_catalog.way_for_client``), never the raw ``clientInfo``
string; the device is a ``device_tokens`` id (``""`` for this machine); ``via`` is an enum (``mcp`` | ``tool`` |
``remote`` | ``call``). ``call`` (onboarding v3, 2026-10-24) is a stdio ``tools/call`` — the agent asked Cicada
something — beside the ``mcp`` row its ``initialize`` writes, so a call can be told apart from a connect (a harness's
own wiring check, ``claude mcp get``, initializes and never calls a tool). A device row is ``(device id, how, last seen)`` with ``how`` one of :data:`HOW`. No query, no argument,
no path, no session id, no address.

**Where:** ``$CICADA_HOME/agents/seen.db`` (0700 dir, 0600 file, sqlite WAL) — machine-global, outside every bank,
like the device and connector stores. Several processes write it (the backend and each stdio MCP server), which is
what sqlite is for.

**How often:** a stamp is at most one write per (agent, device, via) per :data:`STAMP_EVERY_S` per process, so a
burst of tool calls is one write. A stamp never raises and never blocks a call for long: a locked or unreadable store
is "no sighting" (``timeout`` 0.5 s).
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from api.services.auth import cicada_home

STAMP_EVERY_S = 60.0
VIAS = ("mcp", "tool", "remote", "call")
#: The vias that are a tool call (an agent asking something), never a bare connect: a stdio ``tools/call`` and a
#: call through the tool door from another of the person's machines.
CALL_VIAS = ("call", "tool")
#: How a device reached this server. ``local`` = this machine; ``ssh`` = another device's token arriving on loopback
#: (a tunnel); ``tailscale`` = through a Tailscale Serve proxy or from a tailnet address; ``lan`` = another private
#: address. Derived from the request, never from what a client says about itself.
HOW = ("local", "ssh", "tailscale", "lan")
_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agents (
        agent TEXT NOT NULL, device TEXT NOT NULL DEFAULT '', via TEXT NOT NULL,
        first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (agent, device, via))""",
    """CREATE TABLE IF NOT EXISTS devices (
        device TEXT PRIMARY KEY, how TEXT NOT NULL, last_seen TEXT NOT NULL)""",
)

_lock = threading.Lock()
_last: dict[tuple, float] = {}


def path() -> Path:
    return cicada_home() / "agents" / "seen.db"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def _db(create: bool):
    target = path()
    if not create and not target.is_file():
        yield None
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass
    conn = sqlite3.connect(str(target), timeout=0.5)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        for statement in _SCHEMA:
            conn.execute(statement)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        yield conn
        conn.commit()
    finally:
        conn.close()


def _due(key: tuple, now: float) -> bool:
    with _lock:
        if now - _last.get(key, 0.0) < STAMP_EVERY_S:
            return False
        _last[key] = now
        return True


def reset() -> None:
    """Tests: forget the per-process throttle."""
    with _lock:
        _last.clear()


def stamp_agent(agent: str | None, *, via: str, device: str | None = None) -> bool:
    """Record that ``agent`` (a catalog way id) reached Cicada through ``via``. Throttled; never raises.
    Returns whether a write happened."""
    if not agent or via not in VIAS:
        return False
    device = device or ""
    if not _due(("a", agent, device, via), time.monotonic()):
        return False
    try:
        now = _now()
        with _db(create=True) as conn:
            conn.execute(
                "INSERT INTO agents (agent, device, via, first_seen, last_seen, calls) VALUES (?, ?, ?, ?, ?, 1) "
                "ON CONFLICT(agent, device, via) DO UPDATE SET last_seen = excluded.last_seen, calls = calls + 1",
                (agent[:64], device[:16], via, now, now))
        return True
    except Exception:  # noqa: BLE001 — a sighting never fails a call
        return False


def stamp_device(device: str | None, how: str) -> bool:
    """Record how a device (a ``device_tokens`` id, ``""`` never) last reached this server. Throttled; never raises."""
    if not device or how not in HOW:
        return False
    if not _due(("d", device, how), time.monotonic()):
        return False
    try:
        with _db(create=True) as conn:
            conn.execute("INSERT INTO devices (device, how, last_seen) VALUES (?, ?, ?) ON CONFLICT(device) DO UPDATE "
                         "SET how = excluded.how, last_seen = excluded.last_seen", (device[:16], how, _now()))
        return True
    except Exception:  # noqa: BLE001
        return False


def agents() -> list[dict]:
    """Every agent row: ``{agent, device, via, firstSeen, lastSeen, calls}``. ``[]`` when there is no store yet
    (never created just to answer "no")."""
    try:
        with _db(create=False) as conn:
            if conn is None:
                return []
            rows = conn.execute("SELECT agent, device, via, first_seen, last_seen, calls FROM agents").fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [{"agent": a, "device": d or None, "via": v, "firstSeen": f, "lastSeen": last, "calls": c}
            for a, d, v, f, last, c in rows]


def devices() -> dict[str, dict]:
    try:
        with _db(create=False) as conn:
            if conn is None:
                return {}
            rows = conn.execute("SELECT device, how, last_seen FROM devices").fetchall()
    except Exception:  # noqa: BLE001
        return {}
    return {d: {"how": h, "lastSeen": s} for d, h, s in rows}


def how_from_request(*, peer: str | None, headers, device: bool) -> str:
    """How a request reached this server, from evidence on the request only. A Tailscale Serve proxy marks what it
    forwards with ``Tailscale-User-Login``; a tailnet peer is in ``100.64.0.0/10`` or ``fd7a:115c:a1e0::/48``. A
    device's token on loopback came through a tunnel (the server binds 127.0.0.1 only, G181), which the person runs as
    SSH; the server's own token on loopback is this machine."""
    import ipaddress

    get = getattr(headers, "get", None)
    if get is not None and (get("tailscale-user-login") or get("Tailscale-User-Login")):
        return "tailscale"
    try:
        address = ipaddress.ip_address((peer or "").split("%", 1)[0])
    except ValueError:
        address = None
    if address is not None:
        if address in ipaddress.ip_network("100.64.0.0/10") or address in ipaddress.ip_network("fd7a:115c:a1e0::/48"):
            return "tailscale"
        if not address.is_loopback and address.is_private:
            return "lan"
    return "ssh" if device else "local"
