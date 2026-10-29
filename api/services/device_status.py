"""Devices, each by its own name, with a connected dot, how it connects and what waits for it (G212, owner D6:
"refer to the mac not as my mac but as its name").

``GET /devices/status`` is one list the Sleep page's strip and Settings → Devices both draw: this server first,
then every active device token the person issued. Ids, names, enums, times and counts only.

* **name** — this server's own name: macOS's Computer Name (``scutil --get ComputerName``, what Finder and AirDrop
  show), else the host name without ``.local``. A device's name is the one the person gave its token.
* **connected** — this server always (it is answering); a device when its token reached this server within
  :data:`CONNECTED_WITHIN_S`.
* **how** — ``local`` for this server; for a device, how its last request arrived (``agent_seen.HOW``: ``ssh``,
  ``tailscale``, ``lan``), read from the request, never from what the device says; ``None`` before any request.
* **kind**, **keyBound**, **keyBoundAt** — a device only (2026-10-29): ``capture`` or ``full`` (``device_tokens.KINDS``), whether
  its token works only with a proof of its own key (``device_proof``), and since when.
* **queue** — conversations from that machine waiting for Sleep (an episode's ``device`` frontmatter, G181 phase 3;
  none = this server), counted from ``bank_index``'s cached headers, never a body.
"""
from __future__ import annotations

import socket
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

CONNECTED_WITHIN_S = 600

_NAME: str | None = None


def machine_name() -> str:
    """This machine's own name, read once per process."""
    global _NAME
    if _NAME is None:
        name = ""
        if sys.platform == "darwin":
            try:
                name = subprocess.run(["/usr/sbin/scutil", "--get", "ComputerName"], capture_output=True,
                                      text=True, timeout=2).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                name = ""
        if not name:
            name = socket.gethostname().removesuffix(".local")
        _NAME = name[:64] or "This computer"
    return _NAME


def _parse(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None


def queues(memory_path: Path) -> Counter:
    """Waiting conversations per device id (``None`` = this server)."""
    from api.services import bank_index, history_index

    counts: Counter = Counter()
    for f in bank_index.files(memory_path, "episodes"):
        if history_index.waits_for_model(f.frontmatter):
            counts[f.frontmatter.get("device") or None] += 1
    return counts


def snapshot(memory_path: Path, *, asking_device: str | None = None, now: datetime | None = None) -> dict:
    from api.services import agent_seen, device_tokens

    now = now or datetime.now(timezone.utc)
    waiting = queues(memory_path)
    seen = agent_seen.devices()
    rows = [{"id": None, "name": machine_name(), "role": "server", "current": asking_device is None,
             "connected": True, "how": "local", "lastSeenAt": _iso(now), "queue": waiting.get(None, 0)}]
    for device in device_tokens.store().list():
        if not device.active:
            continue
        sighting = seen.get(device.id) or {}
        last = max((m for m in (_parse(device.last_used_at), _parse(sighting.get("lastSeen"))) if m), default=None)
        rows.append({"id": device.id, "name": device.name, "role": "device", "current": device.id == asking_device,
                     "connected": bool(last and (now - last).total_seconds() <= CONNECTED_WITHIN_S),
                     "how": sighting.get("how"), "lastSeenAt": _iso(last), "queue": waiting.get(device.id, 0),
                     # 2026-10-29: what it may do (`capture` = send captures only) and whether its token needs its key.
                     "kind": device.kind, "keyBound": device.key_bound, "keyBoundAt": device.key_bound_at})
    return {"devices": rows, "connectedWithinSeconds": CONNECTED_WITHIN_S}
