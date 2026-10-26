"""``GET /agents/live`` (round 4 C8): is each agent connected, and when did
Cicada last see it? The Agents page (and phase B's onboarding) polls this every
3 s while it is visible to turn a pill's ✓ on by itself (R-AG15).

Four signals, one rule (R-AG5), and no subprocess — unlike ``/agents/wiring``,
whose ``claude mcp get`` probe costs over a second and cannot run every 3 s:

* ``mcp`` — the ``handshake`` ledger row the stdio server writes on every
  ``initialize`` (``mcp/server.py``'s ``_handshake_text``), mapped to an agent by
  its G48 harness or its self-reported ``clientInfo.name`` (R-AG6). Read
  incrementally: only bytes appended since the last poll, newest two months.
* ``remote`` — an active connector for the agent's app whose ``last_used_at`` is
  set. The connector store is touched on every authenticated request
  (``api/remote/app.py``), so this lights on the app's first ``initialize`` and
  still answers under ``CICADA_TELEMETRY=off``; the ``remote_call`` rows the same
  requests write are not read a second time.
* ``seen`` (G217) — the last-seen registry (``agent_seen``, names, devices and times only, outside every bank) that
  the stdio server and the tool door stamp on every call, so a local agent still reads seen with telemetry off. It
  reports as ``mcp``.
* ``config`` — the agent's own MCP config names Cicada (``agent_wiring.config_state``,
  R-AG4); Claude Code's is its G105 Stop hook.

Ids and enums only (D7): an agent id, an ISO time and a ``via`` enum. Nothing
is persisted; every answer is computed per request. Never a path only the app
may read (R-AG4) and never Claude Code's state file — its signal is the hook.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from api.services import agent_catalog, agent_seen, agent_wiring, telemetry
from api.services.auth import cicada_home

# G217: every list here derives from the one table (`agent_catalog`). `LIVE_AGENTS` stays the app's eleven pills in
# its order (pinned by `api/tests/fixtures/agent_catalog.json`); `TRACKED` adds every other way the table names, so a
# tier-2 agent (Zed, GitHub Copilot, Devin…) is reported by its own id and still lights the "another agent" pill.
LIVE_AGENTS = agent_catalog.LIVE_PILLS
FEATURED = agent_catalog.FEATURED   # R-AG1: the owner's nine; Gemini CLI and "another agent" are Settings-only
TRACKED = agent_catalog.TRACKED
#: The "another agent" row (2026-10-14): a local ``initialize`` whose client names
#: itself but matches no rule below is some other agent the person connected.
OTHER_AGENT = agent_catalog.OTHER
#: Cicada's own MCP clients, never "another agent" (the release smoke test).
_OWN_CLIENTS = agent_catalog.OWN_CLIENTS
# A connector's app (G135 `catalog.APPS`) → the way it lights; an `other` connector is named by its client.
REMOTE_APP_AGENT = {w.remote_app: w.id for w in agent_catalog.WAYS if w.remote_app and w.remote_app != "other"}
_LOCAL_DELIVERIES = frozenset({"initialize", "tool"})
_NEEDLE = b'"kind":"handshake"'


def agent_for(harness: str | None, client_name: str | None) -> str | None:
    """The catalog way a sighting names: the G48 harness when it is one, else the client's own name by the table's
    words (``agent_catalog.way_for_client``, R-AG6); an unmatched name is ``other``, no name is nobody."""
    h = (harness or "").strip().lower()
    if h in TRACKED:
        return h
    return agent_catalog.way_for_client(client_name)


def _iso(value) -> str | None:
    """One spelling for every timestamp here — ``YYYY-MM-DDTHH:MM:SSZ`` in UTC —
    so sightings from the ledger and the store compare as strings."""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _HandshakeTail:
    """Per ledger file: (inode, bytes consumed, latest sighting per agent). A
    poll reads only what was appended; a replaced or truncated file starts over;
    a line with no newline yet waits for the next poll."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[Path, tuple[int, int, dict[str, str]]] = {}

    def reset(self) -> None:
        with self._lock:
            self._files.clear()

    def seen(self, ledger_dir: Path) -> dict[str, str]:
        paths = sorted(ledger_dir.glob("events-*.jsonl"))[-2:]
        merged: dict[str, str] = {}
        with self._lock:
            self._files = {p: v for p, v in self._files.items() if p in paths}
            for path in paths:
                for agent, ts in self._advance(path).items():
                    if ts > merged.get(agent, ""):
                        merged[agent] = ts
        return merged

    def _advance(self, path: Path) -> dict[str, str]:
        inode, offset, seen = self._files.get(path, (0, 0, {}))
        try:
            stat = path.stat()
        except OSError:
            return seen
        if stat.st_ino != inode or stat.st_size < offset:
            offset, seen = 0, {}
        if stat.st_size > offset:
            with path.open("rb") as fh:
                fh.seek(offset)
                chunk = fh.read(stat.st_size - offset)
            end = chunk.rfind(b"\n") + 1
            seen = dict(seen)
            for line in chunk[:end].splitlines():
                if _NEEDLE not in line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                refs = event.get("refs") or {}
                if refs.get("delivery") not in _LOCAL_DELIVERIES:
                    continue
                agent, ts = agent_for(refs.get("harness"), refs.get("client_name")), _iso(event.get("ts"))
                if agent and ts and ts > seen.get(agent, ""):
                    seen[agent] = ts
            offset += end
        self._files[path] = (stat.st_ino, offset, seen)
        return seen


_TAIL = _HandshakeTail()


def _mcp_seen() -> dict[str, str]:
    return _TAIL.seen(telemetry.telemetry_dir()) if telemetry.enabled() else {}


def _remote_seen(now: datetime) -> dict[str, str]:
    path = cicada_home() / "remote" / "connectors.db"
    if not path.is_file():   # never create the remote store just to answer "no"
        return {}
    from api.remote import store as remote_store

    try:
        connectors = remote_store.ConnectorStore(path).list()
    except Exception:  # noqa: BLE001 — a locked or corrupt store is "no sighting", never a 500
        return {}
    seen: dict[str, str] = {}
    for connector in connectors:
        agent = REMOTE_APP_AGENT.get(connector.app) or agent_for(None, connector.last_client)
        ts = _iso(connector.last_used_at)
        if agent and ts and connector.state(now) == "active" and ts > seen.get(agent, ""):
            seen[agent] = ts
    return seen


def _config(home: Path, python: str, repo: Path) -> dict[str, str | None]:
    """Each agent's config signal for ``row``. ``config_state`` answers ``off``
    both for a file that no longer names Cicada and for no file at all; only the
    first is negative evidence (R-AG5). An agent with no config file on this Mac
    — Cursor or Codex registered some other way, an agent installed elsewhere
    that reaches this server — is ``None``, so its handshake still counts."""
    states: dict[str, str | None] = {}
    for agent, probe in agent_wiring.CONFIG_PROBES.items():
        present = any((home / rel).is_file() for rel in probe.files)
        states[agent] = agent_wiring.config_state(agent, home) if present else None
    stop = agent_wiring.stop_hook_state(home, python, repo)
    states["claude-code"] = "on" if stop in ("on", "stale") else None   # no negative evidence (R-AG4)
    return states


def row(agent_id: str, *, config: str | None, mcp_ts: str | None, remote_ts: str | None) -> dict:
    """R-AG5's rule, pure: a config that no longer names Cicada outranks an old
    handshake; a used connector always counts; the latest sighting names ``via``."""
    mcp_counts = bool(mcp_ts) and config != "off"
    sightings = [(ts, via) for ts, via in ((mcp_ts if mcp_counts else None, "mcp"), (remote_ts, "remote")) if ts]
    connected = config == "on" or bool(sightings)
    via = max(sightings)[1] if sightings else ("config" if config == "on" else None)
    last_seen = max((ts for ts in (mcp_ts, remote_ts) if ts), default=None)
    return {"id": agent_id, "connected": connected, "last_seen_at": last_seen, "via": via}


def _registry_seen() -> tuple[dict[str, str], dict[str, str]]:
    """G217: the last-seen registry (``agent_seen``), which telemetry off does not empty. ``tool`` (a call from another
    of the person's machines through the tool door) is an MCP sighting; ``remote`` a connector one."""
    mcp: dict[str, str] = {}
    remote: dict[str, str] = {}
    for r in agent_seen.agents():
        target = remote if r["via"] == "remote" else mcp
        ts = _iso(r["lastSeen"])
        if ts and ts > target.get(r["agent"], ""):
            target[r["agent"]] = ts
    return mcp, remote


def _registry_calls() -> dict[str, str]:
    """Onboarding v3: each agent's latest tool call (``agent_seen.CALL_VIAS``) — the person's agent asking Cicada
    something, never a connect. A harness's wiring check (``claude mcp get``) initializes and calls nothing, so it
    never moves this time."""
    calls: dict[str, str] = {}
    for r in agent_seen.agents():
        if r["via"] not in agent_seen.CALL_VIAS:
            continue
        ts = _iso(r["lastSeen"])
        if ts and ts > calls.get(r["agent"], ""):
            calls[r["agent"]] = ts
    return calls


def _merge(*maps: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in maps:
        for agent, ts in m.items():
            if ts > out.get(agent, ""):
                out[agent] = ts
    return out


def _fold_other(seen: dict[str, str]) -> dict[str, str]:
    """A way the app has no pill for lights the ``other`` pill too (as an unmatched name always did)."""
    pills = set(LIVE_AGENTS)
    latest = max((ts for agent, ts in seen.items() if agent not in pills), default=None)
    if latest and latest > seen.get(OTHER_AGENT, ""):
        return {**seen, OTHER_AGENT: latest}
    return seen


def snapshot(*, home: Path, now: datetime | None = None, python: str | None = None,
             repo: Path = agent_wiring.REPO_ROOT) -> dict:
    python = python or agent_wiring.venv_python(repo)
    config = _config(home, python, repo)
    reg_mcp, reg_remote = _registry_seen()
    mcp = _fold_other(_merge(_mcp_seen(), reg_mcp))
    remote = _fold_other(_merge(_remote_seen(now or datetime.now(timezone.utc)), reg_remote))
    calls = _fold_other(_registry_calls())
    return {"agents": [{**row(a, config=config.get(a), mcp_ts=mcp.get(a), remote_ts=remote.get(a)),
                        "last_called_at": calls.get(a)}
                       for a in TRACKED]}
