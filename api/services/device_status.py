"""Devices, each by its own name, with a connected dot, how it connects and what waits for it (G212, owner D6:
"refer to the mac not as my mac but as its name").

``GET /devices/status`` is one list the Sleep page's strip and Settings → Devices both draw: this server first,
then every active device token the person issued. Ids, names, enums, times and counts only.

* **name** — this server's own name: macOS's Computer Name (``scutil --get ComputerName``, what Finder and AirDrop
  show), else the host name without ``.local``. A device's name is the one the person gave its token.
* **connected** — this server always (it is answering); a device by :func:`is_connected`, the ONE rule
  ``GET /sync/home`` uses for a device's ``online`` too: its latest sign of life (token used, request seen, copy
  reported) within :data:`COPY_ONLINE_WITHIN_S` when it keeps a copy (it polls the home every few seconds), within
  :data:`CONNECTED_WITHIN_S` when it does not (a capture-only device speaks only when it has something to send).
* **how** — ``local`` for this server; for a device, how its last request arrived (``agent_seen.HOW``: ``ssh``,
  ``tailscale``, ``lan``), read from the request, never from what the device says; ``None`` before any request.
* **kind**, **keyBound**, **keyBoundAt** — a device only (2026-10-29): ``capture`` or ``full`` (``device_tokens.KINDS``), whether
  its token works only with a proof of its own key (``device_proof``), and since when.
* **queue** — conversations from that machine waiting for Sleep (an episode's ``device`` frontmatter, G181 phase 3;
  none = this server), counted from ``bank_index``'s cached headers, never a body. It is counted exactly as the Sleep
  page's Waiting tab and headline count (``history_index.waits_for_model``; parked ones included), so the rows always
  add up to that total; ``parked`` is how many of them are parked (the headline's ``readable`` = total - parked). A
  revoked or removed device whose conversations still wait keeps a row (``revoked: true``) so no machine filter loses them.
* **home**, **keepsCopy**, **behind** (2026-11-24) — which row is the bank's home (the one that runs Sleep and writes;
  with nothing shared, the server), whether the machine keeps a copy of this memory, and how many changes its copy is
  behind (``None`` when unknown or not a copy): ``home_move.group`` / ``home_move.copy_facts``, the facts
  ``GET /sync/home`` is drawn from, never computed a second way.
* **unsent** — B3: how many captures and transactions that machine says it holds and has not delivered (waiting plus
  held, ``device_unsent``), said by the machine itself the next time it reached this server; ``null`` when it never
  reported (and always for this server, which holds none).
* **catchUp** — G229: what that machine's app is catching up on after it was closed (``reader_catch_up``): its readers
  in words, what came in while it was away and since it opened; ``None`` when it is not catching up. The same one scan
  of the headers answers it.
"""
from __future__ import annotations

import socket
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

#: A machine that keeps a copy polls its home every few seconds, so two minutes of silence is already "not connected".
COPY_ONLINE_WITHIN_S = 120.0
#: A machine that keeps no copy (a capture-only phone, a device that only sends) has no poll: it is heard when it has
#: something to say, so it stays connected longer.
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


def last_seen(*moments) -> datetime | None:
    """A machine's latest sign of life: the newest of the times given (ISO strings or datetimes, ``None`` skipped)."""
    parsed = [m if isinstance(m, datetime) else _parse(m) for m in moments if m]
    return max((m for m in parsed if m), default=None)


def is_connected(seen: datetime | None, keeps_copy: bool, now: datetime) -> bool:
    """THE liveness rule — ``GET /devices/status``'s ``connected`` and ``GET /sync/home``'s ``online`` both ask it, so
    the same machine at the same instant reads the same on both."""
    if seen is None:
        return False
    return (now - seen).total_seconds() <= (COPY_ONLINE_WITHIN_S if keeps_copy else CONNECTED_WITHIN_S)


def waiting(memory_path: Path, files=None) -> tuple[Counter, Counter]:
    """Waiting conversations per device id (``None`` = this server), and how many of them are parked. The Sleep page's
    Waiting tab, its headline (``sleep_debt``) and these counts all go through ``history_index.waits_for_model``."""
    from api.services import bank_index, history_index, sleep_parked

    parked_ids = sleep_parked.ids(memory_path)
    counts: Counter = Counter()
    parked: Counter = Counter()
    for f in (bank_index.files(memory_path, "episodes") if files is None else files):
        fm = f.frontmatter
        if not history_index.waits_for_model(fm):
            continue
        who = fm.get("device") or None
        counts[who] += 1
        if str(fm.get("id", f.stem)) in parked_ids:
            parked[who] += 1
    return counts, parked


def queues(memory_path: Path, files=None) -> Counter:
    """Waiting conversations per device id (``None`` = this server)."""
    return waiting(memory_path, files)[0]


def snapshot(memory_path: Path, *, asking_device: str | None = None, now: datetime | None = None) -> dict:
    from api.services import agent_seen, bank_index, device_tokens, device_unsent, home_move, reader_catch_up, replica

    now = now or datetime.now(timezone.utc)
    files = bank_index.files(memory_path, "episodes")
    counts, parked = waiting(memory_path, files)
    catching = reader_catch_up.views(memory_path, files=files, now=now)
    seen = agent_seen.devices()
    unsent = device_unsent.unsent()   # B3: what each machine says it holds and has not sent
    try:
        group = home_move.group(memory_path, now)
    except Exception:  # noqa: BLE001 - a half-written share never fails the list; read as nothing shared
        group = {"shared": False}
    shared = bool(group.get("shared"))
    registry = {r.get("id"): r for r in group.get("rows") or [] if isinstance(r, dict)} if shared else {}
    pin, home_seq = group.get("pin"), group.get("home_seq")
    store = device_tokens.store()
    own = store.own()
    server_behind = None
    if shared and group.get("role") == "replica":
        server_behind = replica.state().get("behind")
    server_waiting = counts.get(None, 0) + (counts.get(own.id, 0) if own is not None else 0)
    server_parked = parked.get(None, 0) + (parked.get(own.id, 0) if own is not None else 0)
    rows = [{"id": None, "name": machine_name(), "role": "server", "current": asking_device is None,
             "connected": True, "how": "local", "lastSeenAt": _iso(now), "queue": server_waiting,
             "parked": server_parked, "catchUp": catching.get(None),
             # With nothing shared this server holds and runs the memory; shared, whoever the record names does.
             "home": (not shared) or group.get("home_id") == group.get("me"), "keepsCopy": True,
             "behind": server_behind, "revoked": False, "unsent": None}]
    known = {own.id} if own is not None else set()
    removed: list[dict] = []
    for device in store.list():
        known.add(device.id)
        if not device.active and not counts.get(device.id):
            continue
        sighting = seen.get(device.id) or {}
        reg = registry.get(device.id) or {"copy_bank_id": device.copy_bank_id, "copy_seq": device.copy_seq,
                                          "copy_at": device.copy_at, "last_used_at": device.last_used_at}
        keeps, behind = home_move.copy_facts(reg, pin, home_seq)
        last = last_seen(reg.get("copy_at"), reg.get("last_used_at"), device.last_used_at, sighting.get("lastSeen"))
        row = {"id": device.id, "name": device.name, "role": "device", "current": device.id == asking_device,
               "connected": device.active and is_connected(last, keeps, now),
               "how": sighting.get("how"), "lastSeenAt": _iso(last), "queue": counts.get(device.id, 0),
               "parked": parked.get(device.id, 0),
               # 2026-10-29: what it may do (`capture` = send captures only) and whether its token needs its key.
               "kind": device.kind, "keyBound": device.key_bound, "keyBoundAt": device.key_bound_at,
               "catchUp": catching.get(device.id),
               "home": shared and device.id == group.get("home_id"), "keepsCopy": keeps, "behind": behind,
               "revoked": not device.active,
               # B3: what that machine says it holds and has not sent (null: it never reported).
               "unsent": unsent.get(device.id)}
        (rows if device.active else removed).append(row)
    # A copy's own store does not hold the computers it follows: the home and its other devices live in the mirrored
    # registry (`home_move.registry`), so without them a copy would show one machine and never say which one runs Sleep.
    me_id = group.get("me")
    for r in sorted((r for r in registry.values() if isinstance(r, dict)), key=lambda r: str(r.get("id"))):
        rid = r.get("id")
        if (not rid or rid in known or rid == me_id or r.get("revoked_at")
                or r.get("kind") not in (None, "full")):
            continue
        known.add(rid)
        sighting = seen.get(rid) or {}
        keeps, behind = home_move.copy_facts(r, pin, home_seq)
        last = last_seen(r.get("copy_at"), r.get("last_used_at"), sighting.get("lastSeen"))
        is_home = rid == group.get("home_id")
        rows.append({"id": rid, "name": r.get("name") or "Another computer", "role": "device", "current": False,
                     "connected": bool(group.get("home_online")) if is_home else is_connected(last, keeps, now),
                     "how": sighting.get("how"), "lastSeenAt": _iso(last), "queue": counts.get(rid, 0),
                     "parked": parked.get(rid, 0), "kind": "full", "keyBound": False, "keyBoundAt": None,
                     "catchUp": catching.get(rid), "home": is_home, "keepsCopy": keeps, "behind": behind,
                     "revoked": False, "unsent": unsent.get(rid)})
    # Conversations stamped with a device the store no longer knows at all still wait: a row each, so they sum.
    for device_id in sorted(k for k in counts if k is not None and k not in known):
        removed.append({"id": device_id, "name": "Removed device", "role": "device", "current": False,
                        "connected": False, "how": None, "lastSeenAt": None, "queue": counts[device_id],
                        "parked": parked.get(device_id, 0), "catchUp": catching.get(device_id), "home": False,
                        "keepsCopy": False, "behind": None, "revoked": True, "unsent": None})
    return {"devices": rows + removed, "connectedWithinSeconds": CONNECTED_WITHIN_S,
            "copyConnectedWithinSeconds": int(COPY_ONLINE_WITHIN_S)}
