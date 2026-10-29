"""A computer keeps a replica of its home's bank (G132 phase 1, ruling 51a/d/e2).

**The mode.** ``runtime_layout.mode() == "replica"`` (``CICADA_REPLICA_OF`` or ``$CICADA_HOME/replica_of``, the same
device token as a client). This machine's own backend runs on loopback and answers reads from its copy; it never
runs Sleep, a schedule, a poll or a migration, and never commits on its own (``replica_guard``). Its writes go to the
home as transactions (``tx_outbox``): the tool door, the hand-written route table (``replica_routes``), the hooks.

**Bootstrap.** No copy yet: ask the home's ``/sync/status`` (its bank id and name — a demo is never published, so it
is never copied), fetch the whole pack (``/sync/pack``) and make a new git repository from it under
``<root>/banks/<name>`` (``git_service.bootstrap_from_bundle_sync``; the name gets ``-copy`` when this machine
already has one), register it in ``banks.yaml`` under **the home's bank id** with ``replica: true``, and make it the
active bank. Every other bank on this machine is left as it was, and inactive. The marker
``$CICADA_HOME/sync/<bank key>/replica.json`` (``{home, bankId, seq, sha, appliedAt}``) is this machine's alone —
never in a bank, never sent.

**Follow.** A reader thread holds the home's ``/sync/events`` open and notes each ``version`` whose ``git_head`` is not
the copy's (and each ``sleep`` event, the home's frame for §3a); the follower wakes on it, or every
:data:`POLL_S` seconds by itself (``/sync/log``), and on the person's write (:func:`wait_for_seq`). It asks
``/sync/pack?have=<copy's sha>``, and ``git_service.fast_forward_sync`` applies the bundle: ancestry checked here,
never a seq trusted alone; every file written atomically; then the page cache, ``bank_index`` and the words index
catch up at once, and the meaning index catches up in the background from the changed episode stems only.
Offline, it backs off (1 s doubling to :data:`BACKOFF_MAX_S`). A revoked token (401/403) stops it at once: nothing more
is fetched or sent until the token works again. A rewritten home (409 ``history_rewritten``) or a head that does not
descend from the copy stops it too and says so; only the person's "copy again" (:func:`recopy`) writes the home's
tree over the copy.

Nothing from the bundle reaches a log: only seqs, counts and timings.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from loguru import logger

POLL_S = 10.0
BACKOFF_MAX_S = 60.0
READ_YOUR_WRITES_S = 2.0
MARKER = "replica.json"
TIMEOUT_S = 30.0
PACK_TIMEOUT_S = 600.0

#: What the follower is doing, for the Devices page and ``/sync/replica``.
STATES = ("starting", "copying", "following", "offline", "revoked", "home_rewritten", "diverged", "error")
TEXTS = {
    "starting": "Starting to follow the computer that holds your memory.",
    "copying": "Making this computer's copy of your memory.",
    "following": "This computer keeps a copy of your memory and follows its home.",
    "offline": "The computer that holds your memory is not reachable. Reading works from this copy; changes wait.",
    "revoked": "The computer that holds your memory no longer accepts this computer. Reading works from this copy; "
               "nothing more is fetched or sent.",
    "home_rewritten": "The history of your memory was rewritten on the computer that holds it. This copy stopped "
                      "following; choose \"Copy again\" once that computer publishes again.",
    "diverged": "This copy no longer matches the history of the computer that holds your memory. Choose \"Copy "
                "again\" to replace it.",
    "error": "This copy could not be updated just now; it tries again.",
}


class HomeError(Exception):
    def __init__(self, status: int | None, body: dict | None = None):
        super().__init__(f"home answered {status}")
        self.status = status
        self.body = body or {}


@dataclass
class _State:
    status: str = "starting"
    seq: int = 0
    sha: str = ""
    home_seq: int | None = None
    bank_id: str | None = None
    applied_at: float | None = None
    last_contact: float | None = None
    last_apply: dict = field(default_factory=dict)
    home_sleep: dict | None = None
    home_frame: dict | None = None


_STATE = _State()
_COND = threading.Condition()
_WAKE = threading.Event()
_STOP = threading.Event()
_THREADS: list[threading.Thread] = []
_VECTORS_LOCK = threading.Lock()


# --- talking to the home ----------------------------------------------------------------------------------------------

def home_base(environ=os.environ) -> str:
    from api.services import runtime_layout

    return runtime_layout.replica_of(environ)


def _token(environ=os.environ) -> str:
    from api.services import runtime_layout

    return runtime_layout.client_token(environ)


def request(method: str, path: str, *, body: bytes | None = None, headers: dict | None = None,
            timeout: float = TIMEOUT_S, to_file: Path | None = None, environ=os.environ):
    """One request to the home with this device's token. ``(status, headers, body)``: body is decoded JSON (or the file
    path for ``to_file``). ``status`` None when the home was not reached. Never follows a redirect."""
    import urllib.error
    import urllib.request

    from api.services import runtime_layout

    try:
        base = home_base(environ)
    except ValueError:
        return None, {}, None
    token = _token(environ)
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json", **(headers or {})}
    req = urllib.request.Request(f"{base}{path}", data=body, method=method, headers=h)
    try:
        with runtime_layout.opener().open(req, timeout=timeout) as resp:
            status, rheaders = resp.status, dict(resp.headers.items())
            if to_file is not None:
                with open(to_file, "wb") as fh:
                    shutil.copyfileobj(resp, fh, 1024 * 1024)
                return status, rheaders, to_file
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        try:
            parsed = json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            parsed = None
        return exc.code, dict(exc.headers.items()) if exc.headers else {}, parsed
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
        return None, {}, None
    if not raw:
        return status, rheaders, None
    try:
        return status, rheaders, json.loads(raw.decode("utf-8"))
    except ValueError:
        return status, rheaders, raw


def _json_or_raise(status, body):
    if status is None:
        raise HomeError(None)
    if not 200 <= status < 300:
        raise HomeError(status, body if isinstance(body, dict) else None)
    return body


# --- where the copy lives ---------------------------------------------------------------------------------------------

def marker_path(memory_path: Path, *, create: bool = True) -> Path:
    from api.services import sync_publish

    return sync_publish.bank_dir(memory_path, create=create) / MARKER


def read_marker(memory_path: Path) -> dict | None:
    try:
        data = json.loads(marker_path(memory_path, create=False).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_marker(memory_path: Path, data: dict) -> None:
    path = marker_path(memory_path)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def _settings():
    from api.config import get_settings

    return get_settings()


def copy_path() -> Path | None:
    """The active bank when it is this machine's copy (its marker names the home's bank), else None."""
    from api.services import bank_registry

    root = Path(_settings().memory_root)
    try:
        name, path = bank_registry.current_active(root)
    except Exception:  # noqa: BLE001
        return None
    record = (bank_registry.load_registry(root).get("banks") or {}).get(name) or {}
    if not (isinstance(record, dict) and record.get("replica")):
        return None
    return path if read_marker(path) is not None else None


def _free_name(root: Path, wanted: str) -> str:
    from api.services import bank_registry

    banks = bank_registry.load_registry(root).get("banks") or {}
    slug = bank_registry.sanitize_id(wanted) if hasattr(bank_registry, "sanitize_id") else wanted
    for candidate in (slug, f"{slug}-copy", *(f"{slug}-copy-{i}" for i in range(2, 100))):
        if candidate not in banks and not (root / bank_registry.BANKS_SUBDIR / candidate).exists():
            return candidate
    raise RuntimeError("no free name for the copy")


def _fetch_pack(have: str | None, folder: Path) -> tuple[Path | None, dict, dict]:
    """``(bundle path or None when nothing is new, headers, timings)``."""
    target = folder / "pack.bundle"
    query = f"?have={have}" if have else ""
    t0 = time.perf_counter()
    status, headers, body = request("GET", f"/sync/pack{query}", to_file=target, timeout=PACK_TIMEOUT_S)
    total = (time.perf_counter() - t0) * 1000
    timings = {"packMs": round(total, 1)}
    build = headers.get("X-Cicada-Build-Ms") or headers.get("x-cicada-build-ms")
    if build:
        timings["bundleMs"] = float(build)
        timings["transferMs"] = round(max(0.0, total - float(build)), 1)
    if status == 204:
        return None, headers, timings
    if status != 200:
        raise HomeError(status, body if isinstance(body, dict) else None)
    timings["bytes"] = target.stat().st_size
    return target, headers, timings


def bootstrap() -> Path:
    """The first copy (see the module docstring). Returns the copy's path."""
    from api.services import bank_registry, git_service, replica_guard

    _set(status="copying")
    status, _h, frame = request("GET", "/sync/status")
    frame = _json_or_raise(status, frame)
    bank_id = frame.get("bankId")
    name = frame.get("bank") or "memory"
    if not bank_id:
        raise HomeError(status, {"code": "no_bank_id"})
    root = Path(_settings().memory_root)
    root.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="cicada-copy-"))
    os.chmod(folder, 0o700)
    t0 = time.perf_counter()
    try:
        bundle, headers, timings = _fetch_pack(None, folder)
        if bundle is None:
            raise HomeError(204, {"code": "empty_history"})
        slug = _free_name(root, str(name))
        target = root / bank_registry.BANKS_SUBDIR / slug
        with replica_guard.applying():
            head = git_service.bootstrap_from_bundle_sync(target, bundle)
            bank_registry.ensure_derived_excluded(target)
            registry = bank_registry.load_registry(root)
            registry.setdefault("banks", {})[slug] = {
                "legacy": False, "created": date.today().isoformat(),
                "description": "A copy of the memory another of your computers holds", "id": bank_id,
                "replica": True,
            }
            bank_registry.save_registry(root, registry)
            bank_registry.activate_bank(root, slug)
        seq = int(headers.get("X-Cicada-Seq") or headers.get("x-cicada-seq") or 0)
        _write_marker(target, {"home": _host(), "bankId": bank_id, "seq": seq, "sha": head,
                               "appliedAt": time.time()})
        _index_after(target, changed=None)
        timings["bootstrapMs"] = round((time.perf_counter() - t0) * 1000, 1)
        _set(status="following", seq=seq, sha=head, bank_id=bank_id, applied_at=time.time(), last_apply=timings,
             home_frame=frame)
        logger.info(f"replica: first copy at seq {seq} ({timings.get('bytes', 0)} bytes, "
                    f"{timings['bootstrapMs']:.0f} ms)")
        return target
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _host() -> str:
    from api.services import tool_client

    try:
        return tool_client.host_of(home_base())
    except ValueError:
        return ""


def _index_after(memory_path: Path, *, changed: list[str] | None) -> float:
    """The words index at once (``ensure_fresh`` inline), the meaning index in the background — the changed episode
    stems only (``changed`` None: the first copy, whose meaning index builds as it does on any start). The FTS ms."""
    from api.services import search_index

    t0 = time.perf_counter()
    try:
        search_index.ensure_fresh(memory_path, wait=True, max_age_s=0)   # never the cached "fresh a moment ago"
    except Exception:  # noqa: BLE001 — a derived index never fails an apply
        pass
    fts_ms = (time.perf_counter() - t0) * 1000
    if changed:
        stems = [Path(p).stem for p in changed if p.startswith("episodes/ep_") and p.endswith(".md")]
        pages = any(p.startswith("entities/") for p in changed)
        if stems or pages:
            threading.Thread(target=_vectors, args=(memory_path, stems, pages), name="cicada-replica-vectors",
                             daemon=True).start()
    return fts_ms


def _vectors(memory_path: Path, stems: list[str], pages: bool) -> None:
    if not _VECTORS_LOCK.acquire(blocking=False):
        return   # one at a time; the next apply catches what this one would have
    try:
        from api.services.vector_index import SqliteVecIndexer

        indexer = SqliteVecIndexer(memory_path, defer_model_switch=True)
        if stems:
            indexer.index_episode_stems(stems)
        if pages:
            from api.services import sleep_cycle

            sleep_cycle._sync_vector_indexes(memory_path)   # noqa: SLF001 — unchanged text is skipped by its hash
    except Exception as exc:  # noqa: BLE001 — the meaning index is derived; recall falls back to words
        logger.info(f"replica: meaning index catch-up skipped ({type(exc).__name__})")
    finally:
        _VECTORS_LOCK.release()


def apply_once(*, rewrite: bool = False) -> dict:
    """One catch-up: ask for what is new since the copy's head and apply it. Returns the timings (empty when nothing
    was new). Raises :class:`HomeError` on the home's refusal or absence."""
    from api.services import git_service, replica_guard

    mp = copy_path()
    if mp is None:
        bootstrap()
        return dict(_STATE.last_apply)
    marker = read_marker(mp) or {}
    have = None if rewrite else (marker.get("sha") or None)
    folder = Path(tempfile.mkdtemp(prefix="cicada-ff-"))
    os.chmod(folder, 0o700)
    try:
        bundle, headers, timings = _fetch_pack(have, folder)
        seq = int(headers.get("X-Cicada-Seq") or headers.get("x-cicada-seq") or marker.get("seq") or 0)
        if bundle is None:
            _set(status="following", home_seq=seq, last_contact=time.time())
            return {}
        t0 = time.perf_counter()
        with replica_guard.applying():
            out = git_service.fast_forward_sync(mp, bundle, expect=headers.get("X-Cicada-Head") or None,
                                                rewrite=rewrite)
        timings["applyMs"] = round((time.perf_counter() - t0) * 1000, 1)
        timings["files"] = len(out["changed"]) + len(out["removed"])
        timings["ftsMs"] = round(_index_after(mp, changed=out["changed"]), 1)
        _write_marker(mp, {**marker, "seq": seq, "sha": out["head"], "appliedAt": time.time()})
        _set(status="following", seq=seq, sha=out["head"], home_seq=seq, applied_at=time.time(),
             last_contact=time.time(), last_apply=timings)
        _refresh_frame()
        return timings
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def recopy() -> dict:
    """The person's "copy again" after the home's history changed: the home's whole tree over the copy."""
    timings = apply_once(rewrite=True)
    return timings


def _refresh_frame() -> None:
    status, _h, frame = request("GET", "/sync/status", timeout=10)
    if status == 200 and isinstance(frame, dict):
        _set(home_frame=frame, home_seq=frame.get("seq"))


# --- state, waking and waiting ----------------------------------------------------------------------------------------

def _set(**changes) -> None:
    with _COND:
        for k, v in changes.items():
            setattr(_STATE, k, v)
        _COND.notify_all()


def state() -> dict:
    """What the Devices page and ``GET /sync/replica`` show: words, seqs, counts — never a body."""
    with _COND:
        s = _STATE
        behind = (s.home_seq - s.seq) if isinstance(s.home_seq, int) and s.home_seq >= s.seq else None
        return {"status": s.status, "text": TEXTS.get(s.status, ""), "seq": s.seq, "homeSeq": s.home_seq,
                "behind": behind, "bankId": s.bank_id, "appliedAt": _iso(s.applied_at),
                "lastContact": _iso(s.last_contact), "lastApply": dict(s.last_apply)}


def _iso(t: float | None) -> str | None:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def seq() -> int:
    with _COND:
        return _STATE.seq


def wake() -> None:
    _WAKE.set()


def wait_for_seq(target: int | None, timeout: float = READ_YOUR_WRITES_S) -> bool:
    """Read-your-writes: nudge the follower and wait until the copy reaches ``target`` (at most ``timeout``)."""
    if not isinstance(target, int):
        return False
    wake()
    deadline = time.monotonic() + timeout
    with _COND:
        while _STATE.seq < target:
            left = deadline - time.monotonic()
            if left <= 0:
                return False
            _COND.wait(left)
    return True


def home_sleep() -> dict | None:
    with _COND:
        return dict(_STATE.home_sleep) if _STATE.home_sleep else (
            dict((_STATE.home_frame or {}).get("sleep") or {}) or None)


def home_frame() -> dict | None:
    with _COND:
        return dict(_STATE.home_frame) if _STATE.home_frame else None


# --- the threads ------------------------------------------------------------------------------------------------------

def _events_reader() -> None:
    """Hold the home's ``/sync/events`` open: a ``version`` whose ``git_head`` is not the copy's wakes the follower;
    a ``sleep`` event is the home's frame (§3a). Reconnects with backoff; a 401/403 waits long."""
    import urllib.error
    import urllib.request

    from api.services import runtime_layout

    delay = 1.0
    while not _STOP.is_set():
        try:
            base = home_base()
        except ValueError:
            _STOP.wait(BACKOFF_MAX_S)
            continue
        req = urllib.request.Request(f"{base}/sync/events", headers={
            "Authorization": f"Bearer {_token()}", "Accept": "text/event-stream"})
        try:
            with runtime_layout.opener().open(req, timeout=45) as resp:
                delay = 1.0
                event = None
                for raw in resp:
                    if _STOP.is_set():
                        return
                    line = raw.decode("utf-8", "replace").rstrip("\n")
                    if line.startswith("event: "):
                        event = line[7:].strip()
                    elif line.startswith("data: ") and event:
                        _on_event(event, line[6:])
                    elif not line:
                        event = None
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                _set(status="revoked")
                _STOP.wait(BACKOFF_MAX_S)
                continue
        except Exception:  # noqa: BLE001 — offline, a reset, a timeout: try again
            pass
        _STOP.wait(delay)
        delay = min(delay * 2, BACKOFF_MAX_S)


def _on_event(event: str, data: str) -> None:
    try:
        payload = json.loads(data)
    except ValueError:
        return
    if event == "version":
        head = ((payload or {}).get("components") or {}).get("git_head")
        with _COND:
            _STATE.last_contact = time.time()
            known = _STATE.sha
        if head and head != known:
            _NOTIFIED[0] = time.perf_counter()
            wake()
    elif event == "sleep" and isinstance(payload, dict):
        _set(home_sleep=payload, last_contact=time.time())


#: When the last ``git_head`` notice arrived (the notify leg of a fast-forward's timing).
_NOTIFIED: list[float | None] = [None]


def _follower() -> None:
    delay = 1.0
    while not _STOP.is_set():
        try:
            notified = _NOTIFIED[0]
            timings = apply_once()
            _flush_outbox()
            if timings and notified is not None:
                timings["sinceNoticeMs"] = round((time.perf_counter() - notified) * 1000, 1)
                _NOTIFIED[0] = None
            delay = 1.0
            wait = POLL_S
        except HomeError as exc:
            code = (exc.body or {}).get("code")
            if exc.status in (401, 403):
                _set(status="revoked")
                wait = BACKOFF_MAX_S
            elif exc.status == 409 and code == "history_rewritten":
                _set(status="home_rewritten")
                wait = BACKOFF_MAX_S
            elif exc.status == 404 and code == "unknown_base":
                _set(status="diverged")
                wait = BACKOFF_MAX_S
            elif exc.status is None:
                _set(status="offline")
                wait, delay = delay, min(delay * 2, BACKOFF_MAX_S)
            else:
                _set(status="error")
                wait, delay = delay, min(delay * 2, BACKOFF_MAX_S)
        except Exception as exc:  # noqa: BLE001 — never a crash: say so and try again
            from api.services import git_service

            status = "diverged" if isinstance(exc, (git_service.NotFastForward, git_service.DirtyCopy)) else "error"
            logger.warning(f"replica: catch-up failed ({type(exc).__name__})")
            _set(status=status)
            wait, delay = (BACKOFF_MAX_S, delay) if status == "diverged" else (delay, min(delay * 2, BACKOFF_MAX_S))
        if _STATE.status in ("revoked", "home_rewritten", "diverged"):
            _STOP.wait(wait)          # stopped: only time (or the person) brings it back
            continue
        _WAKE.wait(wait)
        _WAKE.clear()


def _flush_outbox() -> None:
    """The home answered: what waits in the outbox goes now, oldest first (``tx_outbox``'s rules)."""
    from api.services import tx_outbox

    try:
        if tx_outbox.entries():
            tx_outbox.flush(send, deadline_s=20.0)
    except Exception as exc:  # noqa: BLE001 — a flush is retried on the next contact
        logger.info(f"replica: outbox flush skipped ({type(exc).__name__})")


def start() -> None:
    """Start the follower and the events reader (the backend's lifespan, replica mode only)."""
    if any(t.is_alive() for t in _THREADS):
        return
    _STOP.clear()
    mp = copy_path()
    if mp is not None:
        marker = read_marker(mp) or {}
        _set(seq=int(marker.get("seq") or 0), sha=str(marker.get("sha") or ""), bank_id=marker.get("bankId"),
             applied_at=marker.get("appliedAt"))
    _THREADS[:] = [threading.Thread(target=_follower, name="cicada-replica-follow", daemon=True),
                   threading.Thread(target=_events_reader, name="cicada-replica-events", daemon=True)]
    for t in _THREADS:
        t.start()


def stop(timeout: float = 2.0) -> None:
    _STOP.set()
    _WAKE.set()
    for t in _THREADS:
        t.join(timeout)
    _THREADS.clear()


# --- writes go to the home ------------------------------------------------------------------------------------------

def send(entry: dict) -> tuple[int | None, dict | None]:
    """``tx_outbox``'s sender: one transaction to the home, keyed by its id, naming the home's bank id."""
    import base64

    headers = {"Idempotency-Key": entry["id"]}
    if entry.get("bankId"):
        headers["X-Cicada-Bank-Id"] = entry["bankId"]
    if entry.get("kind") == "tool":
        body = {k: entry.get(k) for k in ("tool", "arguments", "caller", "state", "surface", "options")}
        if entry.get("baseSeq") is not None:
            body["base_seq"] = entry["baseSeq"]
        from api.services import tool_client

        status, _h, answer = request("POST", "/tools/call", body=json.dumps(body).encode("utf-8"),
                                     headers={**headers, "Content-Type": "application/json"},
                                     timeout=tool_client.SLOW_TOOLS.get(entry.get("tool"), 60.0))
    else:
        path = entry["path"] + (f"?{entry['query']}" if entry.get("query") else "")
        if entry.get("contentType"):
            headers["Content-Type"] = entry["contentType"]
        status, rheaders, answer = request(entry["method"], path, body=base64.b64decode(entry.get("body") or ""),
                                           headers=headers, timeout=120)
        if isinstance(answer, dict):
            seq_header = {k.lower(): v for k, v in (rheaders or {}).items()}.get("x-cicada-seq")
            if seq_header and seq_header.isdigit():
                answer = {**answer, "_cicadaSeq": int(seq_header)}   # the home's head once this write committed
    if status in (401, 403):
        _set(status="revoked")       # stops at once: the follower and the outbox wait for a token that works
    elif status is not None:
        _set(last_contact=time.time())
    return status, answer if isinstance(answer, dict) else ({"raw": True} if answer else None)
