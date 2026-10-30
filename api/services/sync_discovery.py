"""Finding the person's other devices on the LAN, and trusting an address only after the device proved who it is
(G132 phase 3b).

**What is advertised.** Bonjour (mDNS-SD) service ``_cicada._tcp``, instance name ``c-<hash>`` and the direct
listener's port — nothing else: no TXT record, no machine name, no hostname in the instance name, never the bank id.
``<hash>`` is the first 80 bits of ``sha256("cicada-lan-v1\\0" + bank id)`` in base32: devices of the same memory
recognise each other; anyone else on the network learns that some Cicada memory is shared there, not which one.

**Who advertises and browses on a Mac: the app, never the backend.** Apple's TN3179 ("Understanding local network
privacy", updated 2026-10-06): *"All Bonjour operations require local network access"* — registering, browsing and
resolving — and *"Making an outgoing TCP connection"* to a local-network address does too (listening and accepting
do not). macOS allows it automatically only for *"Any daemon started by launchd"*, root, and command-line tools run
from Terminal or SSH; *"The exception for launchd daemons doesn't apply to launchd agents"*. The backend is a launchd
**agent** (``com.cicada.backend``, ``scripts/install-backend-agent.sh``), so a Bonjour call from it would raise the
Local Network alert on its own, under no app's name. So the app — which may ask, with its usage text, and whose
answer System Settings shows under Cicada — advertises and browses with ``NWListener``/``NWBrowser``, resolves, and
hands the backend what it found (``POST /sync/discovered``) together with whether the person allowed local network
access. Dialing that address is an outgoing TCP connection to the LAN, so it is the backend's own local-network
operation too: TN3179 says a launch agent not installed with SMAppService names its responsible app with
``AssociatedBundleIdentifiers`` in its launchd plist, so the person's answer to the app covers it. The backend dials a
discovered LAN address only when both hold — the app says the person allowed local network access, and this
backend's plist names the app (``install-backend-agent.sh`` writes ``AssociatedBundleIdentifiers`` and
``CICADA_APP_BUNDLE_ID`` together when the app passes its bundle id). Otherwise the address is kept, verified, and
never dialed; the configured address and the relay carry everything. On Linux there is no such rule; the backend never
advertises in this build (a headless server is reached on the address the person configured).

**Trust.** A found address is only a candidate. The app (on the backend's behalf) asks the peer's open
``GET /sync/hello?nonce=…&for=<hash>``; the peer signs ``domain ‖ hash ‖ nonce`` with its device key (P-256, the key
the registry holds for it, ``device_key``). The backend checks the nonce is one it issued in the last two minutes,
used once, and the signature against the registry's key for that device id — and only then records the address as
that device's. No Cicada token is ever sent to an address before that.

Off on a single-machine install: nothing is advertised, ``/sync/hello`` answers 404, and nothing is kept.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

SERVICE_TYPE = "_cicada._tcp"
HELLO_DOMAIN = b"cicada-lan-hello-v1\x00"
NONCE_TTL_S = 120.0
FOUND_FILE = "discovered.json"
FOUND_TTL_S = 24 * 3600

_NONCES: dict[str, float] = {}
_LOCK = threading.Lock()


def bank_hash(bank_id: str) -> str:
    digest = hashlib.sha256(b"cicada-lan-v1\x00" + bank_id.encode("utf-8")).digest()[:10]
    return base64.b32encode(digest).decode("ascii").lower().rstrip("=")


def instance_name(bank_id: str) -> str:
    return f"c-{bank_hash(bank_id)}"


def _bank_id() -> str | None:
    """The shared memory's id: the bank this request is pinned to, else the active one (a background task)."""
    from api.services import bank_registry

    pin = bank_registry.pinned_bank()
    if pin is not None and pin.id:
        return pin.id
    try:
        from api.config import get_settings

        return bank_registry._active_record(Path(get_settings().memory_root))[2] or None   # noqa: SLF001
    except Exception:  # noqa: BLE001
        return None


def shared(memory_path) -> bool:
    """Discovery exists only for a memory shared between devices (a publishing home, or a copy)."""
    from api.services import demo_guard, runtime_layout, sync_publish

    try:
        if demo_guard.is_demo(Path(memory_path)):
            return False
        return runtime_layout.is_replica() or sync_publish.publishable(memory_path)
    except Exception:  # noqa: BLE001
        return False


def issue_nonce() -> str:
    nonce = base64.urlsafe_b64encode(secrets.token_bytes(24)).decode("ascii").rstrip("=")
    now = time.monotonic()
    with _LOCK:
        for k in [k for k, t in _NONCES.items() if now - t > NONCE_TTL_S]:
            _NONCES.pop(k, None)
        if len(_NONCES) < 256:
            _NONCES[nonce] = now
    return nonce


def _spend(nonce: str) -> bool:
    with _LOCK:
        at = _NONCES.pop(nonce, None)
    return at is not None and time.monotonic() - at <= NONCE_TTL_S


def plan(memory_path) -> dict | None:
    """What the app advertises and browses for (``GET /sync/discovery``), or None when nothing is shared."""
    if not shared(memory_path):
        return None
    bank_id = _bank_id()
    if not bank_id:
        return None
    from api.services import sync_direct_listen

    bind = sync_direct_listen.bound()
    return {"type": SERVICE_TYPE, "browse": instance_name(bank_id),
            "advertise": {"name": instance_name(bank_id), "port": bind[1]} if bind else None,
            "nonce": issue_nonce()}


def hello(memory_path, nonce: str, for_hash: str) -> dict | None:
    """``GET /sync/hello``: this device's signature over the asker's nonce, when the hash is this memory's."""
    from api.services import device_key, home_move

    bank_id = _bank_id()
    if not shared(memory_path) or not bank_id or for_hash != bank_hash(bank_id) or not (8 <= len(nonce) <= 128):
        return None
    me = home_move.my_device_id()
    if not me:
        return None
    sig = device_key.sign(HELLO_DOMAIN + for_hash.encode("ascii") + b"\x00" + nonce.encode("ascii"))
    return {"device": me, "sig": sig}


def accept(memory_path, candidates: list[dict], *, lan_allowed: bool) -> list[dict]:
    """``POST /sync/discovered``: each candidate ``{url, nonce, answer: {device, sig}}`` the app resolved and asked.
    Kept only when the nonce is ours (once, fresh) and the signature is the registry's key for that device."""
    from api.services import device_key, home_move, runtime_layout

    bank_id = _bank_id()
    if not shared(memory_path) or not bank_id:
        return []
    rows = home_move.registry(memory_path)
    h = bank_hash(bank_id)
    kept = []
    for c in candidates[:16]:
        answer = c.get("answer") or {}
        nonce, device = str(c.get("nonce") or ""), str(answer.get("device") or "")
        try:
            url = runtime_layout._checked_base(str(c.get("url") or ""), "url")   # noqa: SLF001
        except ValueError:
            continue
        if not _spend(nonce):
            continue
        r = home_move.row(rows, device)
        if r is None or r.get("revoked_at") or not r.get("sign_jwk"):
            continue
        try:
            jwk = json.loads(r["sign_jwk"])
        except (TypeError, ValueError):
            continue
        signed = HELLO_DOMAIN + h.encode("ascii") + b"\x00" + nonce.encode("ascii")
        if not device_key.verify(jwk, signed, str(answer.get("sig") or "")):
            continue
        kept.append({"device": device, "url": url, "at": time.time(), "lan": True})
    if kept:
        dial = bool(lan_allowed) and associated()
        found = _load(memory_path)
        for k in kept:
            found[k["device"]] = {**k, "dial": dial}
        _save(memory_path, found)
        _HOME_BASE[1] = 0.0
    return [{"device": k["device"], "url": k["url"]} for k in kept]


def associated() -> bool:
    """This backend's launchd plist names the app as its responsible code (TN3179), so the app's local-network answer
    covers this backend's own connections. Set by the install script beside ``AssociatedBundleIdentifiers``."""
    return bool((os.environ.get("CICADA_APP_BUNDLE_ID") or "").strip())


_HOME_BASE: list = [None, 0.0]


def preferred_home_base(default: str, memory_path=None) -> str:
    """A copy's way to its home: a verified LAN address this backend may dial, when the app found one for the home
    device; else ``default`` (the configured address). Read at most every 5 s; no file, no cost but one stat."""
    now = time.monotonic()
    if now - _HOME_BASE[1] < 5.0:
        return _HOME_BASE[0] or default
    _HOME_BASE[1] = now
    _HOME_BASE[0] = None
    try:
        from api.config import get_settings
        from api.services import home_move

        mp = memory_path or get_settings().memory_path
        if not _path(mp).exists():
            return default
        rec = home_move.record(mp)
        home_id = rec.to if rec is not None else next(
            (r.get("id") for r in home_move.load_mirror(mp) if r.get("is_self")), None)
        _HOME_BASE[0] = address_for(mp, home_id)
    except Exception:  # noqa: BLE001 — the configured address, as before
        return default
    return _HOME_BASE[0] or default


def _path(memory_path, create: bool = False) -> Path:
    from api.services import sync_publish

    return sync_publish.bank_dir(memory_path, create=create) / FOUND_FILE


def _load(memory_path) -> dict:
    try:
        data = json.loads(_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(memory_path, data: dict) -> None:
    path = _path(memory_path, create=True)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def address_for(memory_path, device_id: str | None) -> str | None:
    """A verified, fresh LAN address for ``device_id`` that the backend may dial (the person allowed local network
    access in the app), else None."""
    if not device_id:
        return None
    got = _load(memory_path).get(device_id)
    if not isinstance(got, dict) or not got.get("dial") or time.time() - float(got.get("at") or 0) > FOUND_TTL_S:
        return None
    url = got.get("url")
    return url if isinstance(url, str) and urlsplit(url).hostname else None
