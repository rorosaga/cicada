"""A replica's writes on their way to the home (G132 phase 1, ruling 51a): the transaction outbox.

Every write made on a replica — an agent's mutating tool call, an app write the route table forwards, a capture — is a
**transaction** the home applies through the same body it runs today: ``{id, bankId, baseSeq, kind, …}`` where
``id`` is the ``Idempotency-Key`` the home keys it by (8 days there, ``idempotency.TOOLS_TTL_S``), ``kind`` is
``tool`` (``POST /tools/call``) or ``rest`` (the same route at the home). A transaction is never a file diff.

``$CICADA_HOME/spool/tx/`` (0700), one JSON file per transaction (0600, written atomically), named so a listing is
oldest first. :func:`submit` writes the entry, then flushes oldest first; the caller gets the home's answer when its
own entry landed in that flush, else ``queued``. The keep / drop / hold rules are ``hook_spool``'s:

* **wait** (kept, the flush stops so order holds): no answer, 401/403 (a revoked device — nothing more is sent until
  the token works again), 409 ``sleep_writing`` (also a tool's ``sleep_writing`` refusal code), 5xx;
* **drop**, its reason counted: 400, 404, 405, 413, 422, and **expired** — an entry older than :data:`EXPIRE_S`
  (7 days, before the home's 8-day key) is dropped rather than risk a second apply;
* **hold**: 409 ``bank_mismatch`` — the home's memory is another one now; held, never in front of the others, tried
  again at most every :data:`HOLD_RETRY_S`;
* **rejected**: any other refusal the home answered (an inbox item already answered elsewhere) — the transaction no
  longer applies; it leaves the outbox and its id, tool or route and code (never its arguments) are kept in
  ``rejected.json`` for the Devices page (the G132 g1 gate: shown, never silently lost).

What the outbox shows beside the queue is counts (:func:`counts`): waiting, held, dropped and rejected — never a body.
"""
from __future__ import annotations

import base64
import fcntl
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

EXPIRE_S = 7 * 24 * 3600
HOLD_RETRY_S = 600.0
MAX_ENTRIES = 5000
MAX_BODY_BYTES = 32 * 1024 * 1024
REJECTED_KEEP = 200
DROP_STATUSES = frozenset({400, 404, 405, 413, 422})
#: A tool reply's refusal code that means "try again later", not "no longer applies".
WAIT_CODES = frozenset({"sleep_writing", "backend_down", "backend_timeout"})
QUEUED_TEXT = ("Queued for the home: the computer that holds your memory is not reachable now. This is sent as soon "
               "as it is, in order, and applied once.")

_LOCK = threading.RLock()


def folder(home: Path | None = None) -> Path:
    from api.services import runtime_layout

    path = Path(home or runtime_layout.cicada_home()) / "spool" / "tx"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    os.chmod(path.parent, 0o700)
    return path


@contextmanager
def _locked(home: Path | None = None):
    with _LOCK:
        fd = os.open(folder(home) / ".lock", os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)


def _write(path: Path, data: dict) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def entries(home: Path | None = None) -> list[Path]:
    return sorted(p for p in folder(home).glob("tx-*.json"))


def tool_entry(tool: str, arguments: dict, *, bank_id: str | None, base_seq: int | None, caller: dict,
               surface: str, options: dict, state: dict | None = None, key: str | None = None) -> dict:
    return {"v": 1, "id": key or uuid.uuid4().hex, "kind": "tool", "bankId": bank_id, "baseSeq": base_seq,
            "tool": tool, "arguments": arguments or {}, "caller": caller or {}, "surface": surface,
            "options": options or {}, "state": state or {}, "queuedAt": time.time(), "attempts": 0}


def rest_entry(method: str, path: str, query: str, body: bytes, content_type: str | None, *, bank_id: str | None,
               base_seq: int | None, key: str | None = None) -> dict:
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("too large to queue")
    return {"v": 1, "id": key or uuid.uuid4().hex, "kind": "rest", "bankId": bank_id, "baseSeq": base_seq,
            "method": method, "path": path, "query": query or "", "contentType": content_type or "",
            "body": base64.b64encode(body).decode("ascii"), "queuedAt": time.time(), "attempts": 0}


def describe(entry: dict) -> str:
    """What the entry is, for counts and the rejected list: the tool or the route, never its arguments or body."""
    return entry.get("tool") or f"{entry.get('method')} {entry.get('path')}"


def _counters(home: Path | None = None) -> dict:
    return _read(folder(home) / "counters.json") or {}


def _count(reason: str, home: Path | None = None) -> None:
    data = _counters(home)
    data[reason] = int(data.get(reason) or 0) + 1
    _write(folder(home) / "counters.json", data)


def _reject(entry: dict, status: int | None, code: str | None, home: Path | None = None) -> None:
    path = folder(home) / "rejected.json"
    rows = (_read(path) or {}).get("rows") or []
    rows.append({"id": entry.get("id"), "what": describe(entry), "status": status, "code": code, "at": time.time()})
    _write(path, {"rows": rows[-REJECTED_KEEP:]})
    _count("rejected", home)


def verdict(entry: dict, status: int | None, body: dict | None) -> str:
    """``landed``, ``wait``, ``drop``, ``hold`` or ``rejected`` for one send's answer."""
    code = body.get("code") if isinstance(body, dict) else None
    detail_code = (body.get("detail") or {}).get("code") if isinstance(body, dict) and isinstance(
        body.get("detail"), dict) else None
    code = code or detail_code
    if status is None or status in (401, 403) or (status is not None and status >= 500):
        return "wait"
    if 200 <= status < 300:
        if entry.get("kind") == "tool" and code in WAIT_CODES:
            return "wait"
        return "landed"
    if status == 409 and code == "bank_mismatch":
        return "hold"
    if status == 409 and code in WAIT_CODES:
        return "wait"
    if status in DROP_STATUSES:
        return "drop"
    return "rejected"


def keep(entry: dict, *, home: Path | None = None) -> bool:
    """Keep ``entry`` without sending it now (G132 phase 2: what an old home offers back to the new one goes out on
    the follower's next flush, in order). False when the outbox is full."""
    with _locked(home):
        waiting = entries(home)
        tag = f"-{entry['id'][:12]}.json"
        for path in waiting:
            if path.name.endswith(tag) and (_read(path) or {}).get("id") == entry["id"]:
                return True          # kept already (a reconcile done again after a cut): kept once
        if len(waiting) >= MAX_ENTRIES:
            return False
        _write(folder(home) / f"tx-{time.time_ns():020d}{tag}", entry)
    return True


def submit(entry: dict, send, *, home: Path | None = None, deadline_s: float = 30.0) -> tuple[str, int | None, dict]:
    """Keep ``entry``, then flush oldest first. ``(verdict, status, body)`` for ``entry`` itself — ``queued`` when it
    did not land in this flush (it waits, in order). ``send(entry) -> (status | None, body | None)``."""
    # One hold across the write and its flush (review of #566): a flush racing in between (the follower's) could send
    # this entry and leave this caller answering "queued" for a write that landed.
    with _locked(home):
        if len(entries(home)) >= MAX_ENTRIES:
            return "full", None, {}
        name = f"tx-{time.time_ns():020d}-{entry['id'][:12]}.json"
        _write(folder(home) / name, entry)
        outcome = _flush_locked(send, home=home, deadline_s=deadline_s, now=time.time)
    return outcome.get(entry["id"], ("queued", None, {}))


def flush(send, *, home: Path | None = None, deadline_s: float = 30.0, want: str | None = None,
          now=time.time) -> dict[str, tuple[str, int | None, dict]]:
    """Send what waits, oldest first, until one must wait (order holds) or the deadline. ``{id: (verdict, status,
    body)}`` of what this flush decided."""
    with _locked(home):
        return _flush_locked(send, home=home, deadline_s=deadline_s, now=now)


def _flush_locked(send, *, home: Path | None, deadline_s: float, now) -> dict[str, tuple[str, int | None, dict]]:
    decided: dict[str, tuple[str, int | None, dict]] = {}
    stop_at = time.monotonic() + deadline_s
    for path in entries(home):
        if time.monotonic() > stop_at:
            break
        entry = _read(path)
        if entry is None:
            path.unlink(missing_ok=True)
            continue
        if now() - float(entry.get("queuedAt") or 0) > EXPIRE_S:
            path.unlink(missing_ok=True)
            _count("expired", home)
            decided[entry.get("id", "")] = ("expired", None, {})
            continue
        if entry.get("heldAt") and now() - float(entry["heldAt"]) < HOLD_RETRY_S:
            continue
        try:
            status, body = send(entry)
        except Exception:  # noqa: BLE001 — a send that raised is no answer
            status, body = None, None
        v = verdict(entry, status, body)
        decided[entry["id"]] = (v, status, body or {})
        if v == "landed":
            path.unlink(missing_ok=True)
            continue
        if v == "drop":
            path.unlink(missing_ok=True)
            _count(f"dropped_{status}", home)
            continue
        if v == "rejected":
            path.unlink(missing_ok=True)
            _reject(entry, status, (body or {}).get("code") if isinstance(body, dict) else None, home)
            continue
        if v == "hold":
            entry["heldAt"] = now()
            _write(path, entry)
            continue
        entry["attempts"] = int(entry.get("attempts") or 0) + 1
        _write(path, entry)
        break   # wait: what follows waits behind it
    return decided


def counts(home: Path | None = None) -> dict:
    """``{waiting, held, dropped, expired, rejected, oldestAt}`` — numbers only."""
    waiting = held = 0
    oldest = None
    for path in entries(home):
        entry = _read(path) or {}
        if entry.get("heldAt"):
            held += 1
        else:
            waiting += 1
        at = entry.get("queuedAt")
        if isinstance(at, (int, float)) and (oldest is None or at < oldest):
            oldest = at
    c = _counters(home)
    return {"waiting": waiting, "held": held, "expired": int(c.get("expired") or 0),
            "dropped": sum(int(v) for k, v in c.items() if k.startswith("dropped_")),
            "rejected": int(c.get("rejected") or 0), "oldestAt": oldest}


def rejected(home: Path | None = None) -> list[dict]:
    return (_read(folder(home) / "rejected.json") or {}).get("rows") or []
