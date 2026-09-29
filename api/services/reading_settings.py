"""The person's reading settings (G166, spec §7.2): a machine-wide file, never in a bank.

``$CICADA_HOME/reading.json`` (0600, atomic write) — the same home as
``owner.json`` and ``connections.json`` — holds:

* ``agent`` — the master switch, "Let an agent read pages for you". Off by
  default; while it is off ``cicada_reading_queue`` returns nothing, the tools
  refuse, and contract item 9 is not in the primer.
* ``agent_hosts`` — which login-walled sites the person allowed an agent to be
  asked about (``reading_hosts.AGENT_HOST_KEYS``). Empty by default.
* ``agent_ack`` — ``{date, v}``: the person's "I understand" on the first-use
  sheet. Turning the switch on needs a current one; a change of the sheet's
  wording bumps ``ACK_VERSION`` and asks again.

Read on EVERY call and never cached: the stdio MCP server and the backend are
two processes that both read this file (the split-brain rule — a value one
process cached would outlive the person's own change in the other).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

from api.services import reading_hosts
from api.services.auth import cicada_home

FILENAME = "reading.json"
#: Bump when the first-use sheet's wording changes: every earlier "I understand"
#: stops counting and the person is asked again.
ACK_VERSION = 1


def path() -> Path:
    return cicada_home() / FILENAME


def _load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    target = path()
    fd, tmp = tempfile.mkstemp(prefix=".reading-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def mtime() -> float:
    """The file's mtime, 0.0 when absent — the sync component reads it."""
    try:
        return path().stat().st_mtime
    except OSError:
        return 0.0


def agent_enabled() -> bool:
    return _load().get("agent") is True and ack_current()


def allowed_hosts() -> tuple[str, ...]:
    """The walled sites the person allowed, in the sheet's order; an unknown key
    in a hand-edited file is dropped, never granted."""
    raw = _load().get("agent_hosts")
    held = {str(k) for k in raw} if isinstance(raw, list) else set()
    return tuple(k for k in reading_hosts.AGENT_HOST_KEYS if k in held)


def ack() -> dict | None:
    raw = _load().get("agent_ack")
    if not isinstance(raw, dict):
        return None
    try:
        version = int(raw.get("v"))
    except (TypeError, ValueError):
        return None
    day = str(raw.get("date") or "")[:10]
    return {"date": day, "v": version} if day else None


def ack_current() -> bool:
    held = ack()
    return held is not None and held["v"] >= ACK_VERSION


def snapshot() -> dict:
    held = ack()
    return {
        "agentEnabled": agent_enabled(),
        "agentHosts": list(allowed_hosts()),
        "ackedAt": held["date"] if held else None,
        "ackCurrent": ack_current(),
    }


class SettingsError(ValueError):
    """A change the person's settings refuse, with a sentence they can read."""


def update(*, agent_enabled_: bool | None = None, agent_hosts=None, acknowledge: bool = False,
           today: date | None = None) -> dict:
    """Apply one change and return the new snapshot.

    Turning the switch on needs a current acknowledgement — either already
    stored, or given in this same call (``acknowledge``). An unknown host key is
    refused whole, nothing written. Turning it off keeps the acknowledgement and
    the per-site choices, so turning it back on does not re-ask."""
    data = _load()
    original = json.loads(json.dumps(data))
    if agent_hosts is not None:
        keys = [str(k) for k in agent_hosts] if isinstance(agent_hosts, (list, tuple, set, frozenset)) else None
        if keys is None:
            raise SettingsError("agentHosts must be a list of site keys.")
        unknown = sorted(k for k in keys if k not in reading_hosts.AGENT_HOST_KEYS)
        if unknown:
            raise SettingsError(
                f"Unknown site: {', '.join(unknown)}. The sites are {', '.join(reading_hosts.AGENT_HOST_KEYS)}.")
        data["agent_hosts"] = [k for k in reading_hosts.AGENT_HOST_KEYS if k in set(keys)]
    if acknowledge:
        data["agent_ack"] = {"date": (today or date.today()).isoformat(), "v": ACK_VERSION}
    if agent_enabled_ is not None:
        if agent_enabled_:
            held = data.get("agent_ack")
            try:
                current = isinstance(held, dict) and int(held.get("v")) >= ACK_VERSION
            except (TypeError, ValueError):
                current = False
            if not current:
                raise SettingsError(
                    "Read the sheet and tick I understand before turning this on. Nothing was changed.")
        data["agent"] = bool(agent_enabled_)
    if data != original:
        # A no-op call writes nothing, so the sync component's mtime never
        # moves for a change that changed nothing.
        _save(data)
    return snapshot()
