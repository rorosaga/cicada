"""One sync transport, direct first and the relay as fallback (G132 phase 3b; owner 2026-10-30: "cant we just connect
between devices").

Everything a device says to another device of the group goes through :func:`request` (to the home: the follower's
pack and log, the status frame, the outbox's transactions, the registry and keys) or :func:`ask_peer` (to one device:
the home-move peer calls). There are two paths:

* **direct** — HTTP(S) to the address the person already configured or a verified discovered one (``replica_of``, a
  device's registry address, ``CICADA_DEVICE_URL``), exactly phases 1–2's requests;
* **relay** — the same request sealed end to end (``sync_relay_crypto``) and carried by the relay the person set
  (``sync_relay_link``): it waits in the relay's mailbox while the peer is asleep and is answered when it wakes.

**Choosing.** With no relay set, :func:`request` *is* the direct request — the same code, the same timeouts, nothing
else imported or started (``test_sync_transport.py`` holds it byte for byte). With a relay running, a request first
checks the direct address answers a TCP connect within :data:`FALLBACK_AFTER_S` (cached :data:`PROBE_OK_S`); a peer
that does not answer — or a direct request that dies mid-way with no answer — is sent over the relay instead, and
direct is tried again after :data:`DIRECT_RETRY_S`. A request sent both ways is applied once: a write carries its
``Idempotency-Key`` either way and the home applies it through ``idempotency.run_once``; a delta is applied only when
its base is the copy's head (ancestry checked before any file is written); a relay frame the receiver already
accepted is refused by its counter.

**The relay-only address.** A device paired over the relay with no direct address follows ``RELAY_ONLY_BASE`` — a
name under ``.invalid`` (RFC 2606: never resolves), so a direct attempt costs nothing and every request goes over the
relay.

Nothing here reads or logs a body; counters and the last path chosen are kept for ``GET /sync/transport``.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

NO_ANSWER = "x-cicada-no-answer"
#: With a relay running: how long a direct peer has to accept a TCP connection before the relay is used.
FALLBACK_AFTER_S = 2.0
#: A direct connect that succeeded is trusted this long before it is probed again.
PROBE_OK_S = 5.0
#: After direct failed, it is tried again this long later (the relay carries everything meanwhile).
DIRECT_RETRY_S = 30.0
#: Followed by a device that knows its home only through the relay.
RELAY_ONLY_BASE = "https://home.relay.invalid"
RELAY_ONLY_HOST = "home.relay.invalid"

_LOCK = threading.Lock()
_STATS: dict = {"direct": 0, "relay": 0, "fallbacks": 0, "last": None, "lastFallbackMs": None, "directDownUntil": 0.0}
_PROBED: dict[tuple[str, int], float] = {}
_DOWN: dict[tuple[str, int], float] = {}


# --- the relay setting ---------------------------------------------------------------------------------------------------

RELAY_ENV = "CICADA_SYNC_RELAY"
RELAY_FILE = "relay.json"


def _setting_path() -> Path:
    from api.services import runtime_layout

    return runtime_layout.cicada_home() / "sync" / RELAY_FILE


def relay_url(environ=os.environ) -> str | None:
    """The relay the person set, or None (the default: off). ``CICADA_SYNC_RELAY`` (the suite, a headless server) or
    ``$CICADA_HOME/sync/relay.json`` (Settings → Devices). Only ``wss://`` — or ``ws://`` on loopback — is accepted
    (``sync_relay_client.check_url`` refuses anything else when the link starts)."""
    raw = (environ.get(RELAY_ENV) or "").strip()
    if raw:
        return None if raw.lower() in ("off", "0", "false") else raw
    try:
        data = json.loads(_setting_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    url = data.get("url") if isinstance(data, dict) else None
    return url.strip() if isinstance(url, str) and url.strip() else None


def check_relay_url(url: str) -> str:
    """The setting's own check, stdlib only (the same rule ``sync_relay_client.check_url`` enforces)."""
    parts = urlsplit(url.strip())
    loop = (parts.hostname or "") in ("127.0.0.1", "localhost", "::1")
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("A relay address is a wss:// address with no name, password, query or fragment.")
    if parts.scheme == "wss" or (parts.scheme == "ws" and loop):
        return url.strip().rstrip("/")
    raise ValueError("A relay address must start with wss:// (plain ws:// only for one on this computer).")


def set_relay_url(url: str | None) -> str | None:
    """Settings → Devices: set or clear the relay (0600, outside every bank). Returns what is set now."""
    path = _setting_path()
    if not url:
        path.unlink(missing_ok=True)
        return None
    checked = check_relay_url(url)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"url": checked}, fh)
    os.replace(tmp, path)
    return checked


def _link():
    """The running relay link, or None. Read from ``sys.modules`` only: with no relay set the link module was never
    imported, and asking never imports it (nor the crypto under it)."""
    mod = sys.modules.get("api.services.sync_relay_link")
    if mod is None:
        return None
    link = getattr(mod, "LINK", None)
    return link if link is not None and link.running() else None


# --- direct ---------------------------------------------------------------------------------------------------------------

def direct(base: str, method: str, path: str, *, body: bytes | None = None, headers: dict | None = None,
           timeout: float = 30.0, to_file: Path | None = None):
    """One HTTP request to ``base`` — phases 1–2's request, unchanged. ``(status, headers, body)``: body is decoded
    JSON (or the file path for ``to_file``); ``status`` None when nobody answered, with :data:`NO_ANSWER` saying
    ``timeout`` (sent, may have landed) or ``unreachable`` (never connected, nothing landed). Never follows a
    redirect. ``headers`` carry the credential the caller chose."""
    import urllib.error
    import urllib.request

    from api.services import runtime_layout

    req = urllib.request.Request(f"{base}{path}", data=body, method=method, headers=headers or {})
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
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        timed_out = isinstance(exc, (socket.timeout, TimeoutError)) or isinstance(reason, (socket.timeout,
                                                                                            TimeoutError))
        return None, {NO_ANSWER: "timeout" if timed_out else "unreachable"}, None
    if not raw:
        return status, rheaders, None
    try:
        return status, rheaders, json.loads(raw.decode("utf-8"))
    except ValueError:
        return status, rheaders, raw


def _endpoint(base: str | None) -> tuple[str, int] | None:
    if not base:
        return None
    try:
        parts = urlsplit(base)
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None
    if not host or host == RELAY_ONLY_HOST or host.endswith(".invalid"):
        return None
    return host, port


def _direct_usable(base: str | None) -> bool:
    """With a relay running: whether direct is worth trying now (it answered a TCP connect lately, or does now)."""
    target = _endpoint(base)
    if target is None:
        return False
    now = time.monotonic()
    with _LOCK:
        if _DOWN.get(target, 0.0) > now:
            return False
        if _PROBED.get(target, 0.0) > now:
            return True
    try:
        socket.create_connection(target, timeout=FALLBACK_AFTER_S).close()
    except OSError:
        _mark_down(target)
        return False
    with _LOCK:
        _PROBED[target] = now + PROBE_OK_S
    return True


def _mark_down(target: tuple[str, int] | None) -> None:
    if target is None:
        return
    with _LOCK:
        until = time.monotonic() + DIRECT_RETRY_S
        _DOWN[target] = until
        _PROBED.pop(target, None)
        _STATS["directDownUntil"] = time.time() + DIRECT_RETRY_S


def _count(path: str, fallback_ms: float | None = None) -> None:
    with _LOCK:
        _STATS[path] = int(_STATS.get(path) or 0) + 1
        _STATS["last"] = path
        if fallback_ms is not None:
            _STATS["fallbacks"] = int(_STATS.get("fallbacks") or 0) + 1
            _STATS["lastFallbackMs"] = round(fallback_ms, 1)


# --- the one entry point ------------------------------------------------------------------------------------------------

def request(base: str | None, method: str, path: str, *, body: bytes | None = None, headers: dict | None = None,
            timeout: float = 30.0, to_file: Path | None = None, to: str = "home"):
    """``(status, headers, body)`` from the home (``to="home"``) or one device (``to`` its relay key). ``base`` is
    the direct address (None or :data:`RELAY_ONLY_BASE`: none). ``headers`` carry the caller's credential for the
    direct path only — the relay path never carries one: the receiver knows the sender by its signed frame."""
    link = _link()
    if link is None:
        if not base:
            return None, {NO_ANSWER: "unreachable"}, None
        return direct(base, method, path, body=body, headers=headers, timeout=timeout, to_file=to_file)
    started = time.perf_counter()
    if _direct_usable(base):
        got = direct(base, method, path, body=body, headers=headers, timeout=timeout, to_file=to_file)
        if got[0] is not None:
            _count("direct")
            return got
        _mark_down(_endpoint(base))          # died mid-way: the same request (same key) goes over the relay
    relay_headers = {k: v for k, v in (headers or {}).items() if k.lower() != "authorization"}
    got = link.request(method, path, body=body, headers=relay_headers, timeout=timeout, to_file=to_file, to=to)
    _count("relay", fallback_ms=(time.perf_counter() - started) * 1000 if base and _endpoint(base) else None)
    return got


def ask_peer(address: str | None, relay_ed: str | None, method: str, path: str, *, token: str,
             body: bytes | None = None, timeout: float = 3.0):
    """One device of the group, by its address and/or its relay key: ``(status | None, headers, body)``."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"}
    if _link() is None or not relay_ed:
        if not address:
            return None, {NO_ANSWER: "unreachable"}, None
        return direct(address.rstrip("/"), method, path, body=body, headers=headers, timeout=timeout)
    return request(address.rstrip("/") if address else None, method, path, body=body, headers=headers,
                   timeout=timeout, to=relay_ed)


def stats() -> dict:
    """What ``GET /sync/transport`` shows: which path the last request took, counts, the last fallback's time."""
    with _LOCK:
        out = {"requests": {"direct": int(_STATS["direct"]), "relay": int(_STATS["relay"])},
               "fallbacks": int(_STATS["fallbacks"]), "last": _STATS["last"],
               "lastFallbackMs": _STATS["lastFallbackMs"], "directDownUntil": _STATS["directDownUntil"] or None}
    link = _link()
    out["relay"] = {"set": relay_url() is not None, "running": link is not None,
                    **(link.public_state() if link is not None else {})}
    return out


def reset_for_tests() -> None:
    with _LOCK:
        _PROBED.clear()
        _DOWN.clear()
        _STATS.update({"direct": 0, "relay": 0, "fallbacks": 0, "last": None, "lastFallbackMs": None,
                       "directDownUntil": 0.0})
