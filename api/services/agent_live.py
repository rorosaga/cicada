"""``GET /agents/live`` (round 4 C8): is each agent connected, and when did
Cicada last see it? The Agents page (and phase B's onboarding) polls this every
3 s while it is visible to turn a pill's ✓ on by itself (R-AG15).

Three signals, one rule (R-AG5), and no subprocess — unlike ``/agents/wiring``,
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

from api.services import agent_wiring, telemetry
from api.services.auth import cicada_home

LIVE_AGENTS = ("claude-code", "codex", "claude", "chatgpt", "cursor", "opencode", "hermes", "openclaw", "grok",
               "gemini-cli")
FEATURED = LIVE_AGENTS[:9]   # R-AG1: the owner's nine; Gemini CLI is Settings-only

# R-AG6: ordered — `claude-code` before `claude`; unmatched names are ignored.
_CLIENT_RULES = (("claude-code", "claude-code"), ("claude code", "claude-code"), ("codex", "codex"),
                 ("cursor", "cursor"), ("opencode", "opencode"), ("openclaw", "openclaw"), ("hermes", "hermes"),
                 ("gemini", "gemini-cli"), ("grok", "grok"), ("claude", "claude"))
# A connector's app (G135 `catalog.APPS`) → the pill it lights.
REMOTE_APP_AGENT = {"claude": "claude", "chatgpt": "chatgpt", "grok": "grok", "claude-code": "claude-code",
                    "codex": "codex", "cursor": "cursor", "gemini-cli": "gemini-cli"}
_LOCAL_DELIVERIES = frozenset({"initialize", "tool"})
_NEEDLE = b'"kind":"handshake"'


def agent_for(harness: str | None, client_name: str | None) -> str | None:
    h = (harness or "").strip().lower()
    if h in LIVE_AGENTS:
        return h
    name = (client_name or "").strip().lower()
    for needle, agent in _CLIENT_RULES:
        if needle in name:
            return agent
    return None


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
        agent, ts = REMOTE_APP_AGENT.get(connector.app), _iso(connector.last_used_at)
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


def snapshot(*, home: Path, now: datetime | None = None, python: str | None = None,
             repo: Path = agent_wiring.REPO_ROOT) -> dict:
    python = python or agent_wiring.venv_python(repo)
    config = _config(home, python, repo)
    mcp, remote = _mcp_seen(), _remote_seen(now or datetime.now(timezone.utc))
    return {"agents": [row(a, config=config.get(a), mcp_ts=mcp.get(a), remote_ts=remote.get(a))
                       for a in LIVE_AGENTS]}
