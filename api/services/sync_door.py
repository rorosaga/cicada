"""The home-network door: a sealed-frame endpoint for the person's own devices (G132, ruling 51f D3, owner 2026-11-03:
"encryption and security above all").

**What it is.** One TCP listener a computer opens only while it shares a memory (a publishing home, or a copy) and
never for a demo. It speaks one protocol, below, and nothing else: never the HTTP API, never a token, never a bank
path. A device proves who it is in its very first packet; anything else is closed without a byte sent back, so a
scanner learns only that a port accepted a connection. Requests it carries run in process through the same routes a
device token reaches (``sync_inprocess``), held to that device's rules (a capture-only phone reaches only
``auth.CAPTURE_ROUTES``), keyed by the same ``Idempotency-Key`` — a write carried twice, by two routes, applies once.

**Who may connect (T3 Code's rule).** Both ends of the connection must be loopback, private (RFC 1918, IPv6
unique-local) or tailnet (100.64.0.0/10, Tailscale's IPv6 range); a connection from any other address is closed
before it is read. Slice 2's "Reach my memory away from home" switch is the only thing that will ever widen this.

**The handshake** (everything fixed-length, so the parser is two reads and a length check):

* the door has a static X25519 key ``S`` (``$CICADA_HOME/sync/door.json``, 0600, outside every bank); its public half
  travels with the door's routes in the device registry and at pairing, never anywhere else;
* the client sends ``e_c ‖ AEAD(k_h, ver ‖ ts ‖ P ‖ sig)`` (:data:`HELLO_LEN` bytes): a fresh X25519 key, then —
  sealed under ``k_h = HKDF(DH(e_c, S))`` so an observer on the network sees neither — its P-256 public key ``P`` and
  its ES256 signature over ``domain ‖ S ‖ e_c ‖ ts``. ``P`` must be a device of the group: the key it registered
  (``sign_jwk``) or the key its token is bound to (a phone's Secure-Enclave key, ``key_thumbprint``). A hello that does
  not open, is older or newer than :data:`CLOCK_SKEW_S`, repeats an ``e_c`` already seen, or names no device of the
  group is dropped silently;
* the door answers ``e_s ‖ AEAD(k_r, ver ‖ sig_home)`` (:data:`REPLY_LEN` bytes), where ``sig_home`` is the door
  computer's own device-key signature over ``domain ‖ sha256(hello) ‖ e_s`` — the client checks it against the key the
  registry holds for the device it meant to reach, so a stolen door key alone cannot pose as the home;
* both sides derive one key per direction from ``DH(e_c, S) ‖ DH(e_c, e_s)`` and the transcript: forward secret.

**Frames.** ``u32 length ‖ ChaCha20-Poly1305(key, nonce = counter)``, one counter per direction from 0 — a frame
replayed, dropped or reordered fails to open and the connection closes. Plaintext is one type byte and its data: the
door's current routes (``R``, sent first, so a client learns where the door is now), a request head (``Q``) and its
body (``B`` … ``E``), the answer's head (``S``) and body, a watch (``W``: the door then sends ``N`` with each new
commit, and ``P`` to keep the connection), so a copy is told of a commit at once instead of polling.

**Limits.** A hello within :data:`HELLO_TIMEOUT_S`; per source address a bucket of :data:`BUCKET` handshakes refilled
one per :data:`REFILL_S` (a failed one costs three); at most :data:`MAX_PENDING` connections waiting for their hello
and :data:`MAX_SESSIONS` open; a frame at most :data:`MAX_FRAME` bytes, a request body at most 32 MiB; an idle
session closes after :data:`IDLE_S`.

Nothing here logs an address, a key, a path or a body: counts and enums only.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import ipaddress
import json
import os
import secrets
import socket
import struct
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

VERSION = 1
HELLO_DOMAIN = b"cicada-door-hello-v1\x00"
REPLY_DOMAIN = b"cicada-door-reply-v1\x00"
FRAME_AAD = b"CD1F"
TAG = 16
HELLO_PLAIN = 1 + 8 + 64 + 64
HELLO_LEN = 32 + HELLO_PLAIN + TAG
REPLY_PLAIN = 1 + 64
REPLY_LEN = 32 + REPLY_PLAIN + TAG
CLOCK_SKEW_S = 300
HELLO_TIMEOUT_S = 3.0
IDLE_S = 120.0
PING_S = 25.0
CHUNK = 512 * 1024
MAX_FRAME = CHUNK + 1024
MAX_HEAD = 64 * 1024
MAX_REQUEST_BODY = 32 * 1024 * 1024 + 4096
MAX_MEMORY_ANSWER = 64 * 1024 * 1024
BUCKET = 10
REFILL_S = 2.0
FAILED_COST = 3
MAX_PENDING = 32
MAX_SESSIONS = 128
REPLAY_KEEP = 4096
WATCH_POLL_S = 0.5
DOOR_FILE = "door.json"
DOOR_ENV = "CICADA_SYNC_DOOR"
PORT_ENV = "CICADA_SYNC_DOOR_PORT"
PORT_RANGE = (49152, 65000)

TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
PRIVATE_NETS = (ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
                ipaddress.ip_network("192.168.0.0/16"), TAILNET_V4, ipaddress.ip_network("fc00::/7"))


class Unreachable(Exception):
    """Nothing answered as the device we meant (never connected, refused, or the handshake did not prove it)."""


class Dropped(Exception):
    """The connection ended after the request was sent: it may have landed."""


# --- addresses ----------------------------------------------------------------------------------------------------------

def _ip(host: str):
    try:
        addr = ipaddress.ip_address(str(host).split("%", 1)[0])
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def address_class(host: str) -> str | None:
    """``loopback``, ``lan``, ``tailnet``, ``ipv6`` (a global IPv6 address) or ``public`` — or None for a name or
    anything unusable (wildcard, link-local, multicast)."""
    addr = _ip(host)
    if addr is None or addr.is_unspecified or addr.is_multicast or addr.is_link_local:
        return None
    if addr.is_loopback:
        return "loopback"
    if addr in TAILNET_V4 or (addr.version == 6 and addr in TAILNET_V6):
        return "tailnet"
    if any(addr in net for net in PRIVATE_NETS if net.version == addr.version):
        return "lan"
    return "ipv6" if addr.version == 6 else "public"


def allowed_peer(local: str, peer: str) -> bool:
    """T3 Code's listener rule: both addresses of the connection loopback, private or tailnet."""
    return all(address_class(h) in ("loopback", "lan", "tailnet") for h in (local, peer))


def _probe_local(family: int, target: str) -> str | None:
    """The local address the routing table would use toward ``target``. A UDP ``connect`` sends nothing."""
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as s:
            s.connect((target, 9))
            return s.getsockname()[0]
    except OSError:
        return None


def local_addresses() -> dict:
    """This computer's own addresses by class, read from the routing table without a packet: the default route's
    (IPv4, IPv6) and Tailscale's when it runs (its interface answers for 100.100.100.100 / its IPv6 range)."""
    found: dict[str, list[str]] = {"lan": [], "tailnet": [], "ipv6": [], "public": []}
    for family, target in ((socket.AF_INET, "192.0.2.1"), (socket.AF_INET6, "2001:db8::1"),
                           (socket.AF_INET, "100.100.100.100"), (socket.AF_INET6, "fd7a:115c:a1e0::53")):
        got = _probe_local(family, target)
        kind = address_class(got) if got else None
        if kind in found and got not in found[kind]:
            found[kind].append(got)
    return found


def network_fingerprint() -> str:
    """What changes when this computer joins another network (Wi-Fi switched, a cable, a VPN up): a hash of its
    default-route and tailnet addresses. Never stored or sent."""
    found = local_addresses()
    flat = "|".join(f"{k}:{','.join(sorted(v))}" for k, v in sorted(found.items()))
    return hashlib.sha256(flat.encode()).hexdigest()[:16]


# --- keys and the door's own state --------------------------------------------------------------------------------------

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(str(text) + "=" * (-len(str(text)) % 4))


def _hkdf(ikm: bytes, salt: bytes, info: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(ikm)


def _aead(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    return ChaCha20Poly1305(key)


def _x25519_new():
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    return X25519PrivateKey.generate()


def _x_pub(priv) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _x_dh(priv, pub: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey

    return priv.exchange(X25519PublicKey.from_public_bytes(pub))


def _x_load(raw: bytes):
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    return X25519PrivateKey.from_private_bytes(raw)


def _jwk_xy(jwk: dict) -> bytes:
    return _b64d(jwk["x"]).rjust(32, b"\0") + _b64d(jwk["y"]).rjust(32, b"\0")


def _xy_jwk(xy: bytes) -> dict:
    return {"kty": "EC", "crv": "P-256", "x": _b64e(xy[:32]), "y": _b64e(xy[32:])}


def _door_path() -> Path:
    from api.services import runtime_layout

    return runtime_layout.cicada_home() / "sync" / DOOR_FILE


_STATE_LOCK = threading.Lock()


def door_state(create: bool = True) -> dict | None:
    """``{key (private, b64), pub (b64), port}`` — made once, kept across restarts so a learned route stays right."""
    path = _door_path()
    with _STATE_LOCK:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("key") and data.get("port"):
                return data
        except (OSError, ValueError):
            pass
        if not create:
            return None
        priv = _x25519_new()
        from cryptography.hazmat.primitives import serialization

        raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                 serialization.NoEncryption())
        data = {"v": 1, "key": _b64e(raw), "pub": _b64e(_x_pub(priv)),
                "port": secrets.randbelow(PORT_RANGE[1] - PORT_RANGE[0]) + PORT_RANGE[0]}
        _write_private(path, data)
        return data


def _write_private(path: Path, data: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def enabled(environ=os.environ) -> bool:
    return (environ.get(DOOR_ENV) or "on").strip().lower() not in ("off", "0", "false")


def own_routes(port: int | None = None) -> dict | None:
    """What this computer's door tells its devices: the port, the door's public key, and this computer's addresses
    by class (slice 1: the LAN and the tailnet). None while no door is open here."""
    server = SERVER
    if server is None or not server.running():
        return None
    state = door_state(create=False) or {}
    found = local_addresses()
    return {"v": 1, "port": int(port or server.port), "key": state.get("pub"),
            "lan": found["lan"], "tailnet": found["tailnet"]}


# --- the handshake (pure: tested and fuzzed without a socket) -----------------------------------------------------------

@dataclass
class Identity:
    """Who a client is: its device id, its P-256 public key and a signer (``device_key.sign`` on a computer; a
    phone signs with its Secure-Enclave key)."""
    device_id: str
    jwk: dict
    sign: callable


def own_identity() -> Identity | None:
    from api.services import device_key, home_move

    me = home_move.my_device_id()
    jwk = device_key.public_jwk(create=True)
    return Identity(me, jwk, device_key.sign) if me and jwk else None


@dataclass
class Target:
    """The device a client means to reach: its id, its door's public key and its registered signing key."""
    device_id: str
    door_pub: bytes
    jwk: dict


@dataclass
class Keys:
    send: bytes
    recv: bytes


def client_hello(identity: Identity, door_pub: bytes, *, now: float | None = None) -> tuple[bytes, object]:
    eph = _x25519_new()
    e_c = _x_pub(eph)
    ts = int(now if now is not None else time.time())
    signed = HELLO_DOMAIN + door_pub + e_c + struct.pack(">Q", ts)
    sig = _b64d(identity.sign(signed))
    if len(sig) != 64:
        raise ValueError("signature")
    plain = bytes([VERSION]) + struct.pack(">Q", ts) + _jwk_xy(identity.jwk) + sig
    dh1 = _x_dh(eph, door_pub)
    k_h = _hkdf(dh1, door_pub, b"cicada-door-v1 hello")
    hello = e_c + _aead(k_h).encrypt(b"\0" * 12, plain, e_c + door_pub)
    return hello, (eph, dh1, hello)


class Replays:
    def __init__(self, keep: int = REPLAY_KEEP):
        self.keep = keep
        self.seen: OrderedDict[bytes, float] = OrderedDict()

    def spend(self, e_c: bytes, now: float) -> bool:
        while self.seen and now - next(iter(self.seen.values())) > 2 * CLOCK_SKEW_S:
            self.seen.popitem(last=False)
        if e_c in self.seen:
            return False
        self.seen[e_c] = now
        while len(self.seen) > self.keep:
            self.seen.popitem(last=False)
        return True


def server_open(hello: bytes, door_priv, door_pub: bytes, lookup, sign, replays: Replays, *,
                now: float | None = None):
    """``(device, keys, reply)`` for a hello that proves a device of the group, else None (drop it silently).
    ``lookup(jwk) -> device | None``; ``sign(bytes) -> b64`` is this computer's device key."""
    from api.services import device_key

    if not isinstance(hello, (bytes, bytearray)) or len(hello) != HELLO_LEN:
        return None
    hello = bytes(hello)
    e_c, sealed = hello[:32], hello[32:]
    try:
        dh1 = _x_dh(door_priv, e_c)
        k_h = _hkdf(dh1, door_pub, b"cicada-door-v1 hello")
        plain = _aead(k_h).decrypt(b"\0" * 12, sealed, e_c + door_pub)
    except Exception:  # noqa: BLE001 — not sealed to this door (a scanner, another door, noise)
        return None
    if len(plain) != HELLO_PLAIN or plain[0] != VERSION:
        return None
    ts = struct.unpack(">Q", plain[1:9])[0]
    t = now if now is not None else time.time()
    if abs(t - ts) > CLOCK_SKEW_S:
        return None
    xy, sig = plain[9:73], plain[73:137]
    jwk = _xy_jwk(xy)
    signed = HELLO_DOMAIN + door_pub + e_c + struct.pack(">Q", ts)
    if not device_key.verify(jwk, signed, _b64e(sig)):
        return None
    device = lookup(jwk)
    if device is None:
        return None
    if not replays.spend(e_c, t):
        return None
    eph = _x25519_new()
    e_s = _x_pub(eph)
    dh2 = _x_dh(eph, e_c)
    h_hash = hashlib.sha256(hello).digest()
    home_sig = _b64d(sign(REPLY_DOMAIN + h_hash + e_s))
    k_r = _hkdf(dh1 + dh2, h_hash, b"cicada-door-v1 reply")
    reply = e_s + _aead(k_r).encrypt(b"\0" * 12, bytes([VERSION]) + home_sig, e_s)
    th = hashlib.sha256(hello + reply).digest()
    keys = Keys(send=_hkdf(dh1 + dh2, th, b"cicada-door-v1 s2c"), recv=_hkdf(dh1 + dh2, th, b"cicada-door-v1 c2s"))
    return device, keys, reply


def client_finish(state, reply: bytes, target_jwk: dict) -> Keys:
    """Check the door's answer is the device we meant; ``Unreachable`` otherwise."""
    from api.services import device_key

    eph, dh1, hello = state
    if len(reply) != REPLY_LEN:
        raise Unreachable("reply")
    e_s = reply[:32]
    try:
        dh2 = _x_dh(eph, e_s)
        h_hash = hashlib.sha256(hello).digest()
        k_r = _hkdf(dh1 + dh2, h_hash, b"cicada-door-v1 reply")
        plain = _aead(k_r).decrypt(b"\0" * 12, reply[32:], e_s)
    except Exception as exc:  # noqa: BLE001
        raise Unreachable("reply") from exc
    if len(plain) != REPLY_PLAIN or plain[0] != VERSION:
        raise Unreachable("reply")
    if not device_key.verify(target_jwk, REPLY_DOMAIN + h_hash + e_s, _b64e(plain[1:65])):
        raise Unreachable("not_the_device")
    th = hashlib.sha256(hello + reply).digest()
    return Keys(send=_hkdf(dh1 + dh2, th, b"cicada-door-v1 c2s"), recv=_hkdf(dh1 + dh2, th, b"cicada-door-v1 s2c"))


class Sealer:
    """One direction of a session: ``seal`` / ``open_`` with a counter nonce."""

    def __init__(self, key: bytes):
        self.aead = _aead(key)
        self.ctr = 0

    def _nonce(self) -> bytes:
        n = b"\0\0\0\0" + struct.pack(">Q", self.ctr)
        self.ctr += 1
        return n

    def seal(self, kind: bytes, data: bytes) -> bytes:
        ct = self.aead.encrypt(self._nonce(), kind + data, FRAME_AAD)
        return struct.pack(">I", len(ct)) + ct

    def open_(self, ct: bytes) -> tuple[bytes, bytes]:
        plain = self.aead.decrypt(self._nonce(), ct, FRAME_AAD)
        if not plain:
            raise ValueError("empty")
        return plain[:1], plain[1:]


def frame_length(header: bytes) -> int | None:
    """The ciphertext length a frame header announces, or None when it is out of bounds."""
    if len(header) != 4:
        return None
    n = struct.unpack(">I", header)[0]
    return n if TAG + 1 <= n <= MAX_FRAME + TAG else None


# --- the server --------------------------------------------------------------------------------------------------------

class Buckets:
    def __init__(self):
        self.b: dict[str, tuple[float, float]] = {}

    def take(self, who: str, cost: float = 1.0, now: float | None = None) -> bool:
        t = now if now is not None else time.monotonic()
        tokens, at = self.b.get(who, (float(BUCKET), t))
        tokens = min(float(BUCKET), tokens + (t - at) / REFILL_S)
        ok = tokens >= cost
        self.b[who] = (tokens - cost if ok else tokens, t)
        if len(self.b) > 4096:
            for k in list(self.b)[:1024]:
                self.b.pop(k, None)
        return ok

    def charge(self, who: str, cost: float) -> None:
        tokens, at = self.b.get(who, (float(BUCKET), time.monotonic()))
        self.b[who] = (max(0.0, tokens - cost), at)


@dataclass
class Peer:
    device_id: str
    kind: str
    local: bool      # a row of this computer's own store: its routes are admitted as that device


def registry_lookup(memory_path):
    """``lookup(jwk)`` over the group's registry: a device's registered signing key, or the key its token is bound to
    (a phone's). Revoked rows never match. Read at most every 5 s."""
    from api.services import device_key, device_tokens, home_move, runtime_layout

    cache: dict = {"at": -1e9, "rows": [], "own": set()}

    def rows():
        now = time.monotonic()
        if now - cache["at"] > 5.0:
            own = device_tokens.store().export()
            merged = {r.get("id"): r for r in own}
            if runtime_layout.is_replica():
                merged.update({r.get("id"): r for r in home_move.load_mirror(memory_path) if isinstance(r, dict)})
            cache.update(at=now, rows=list(merged.values()), own={r.get("id") for r in own})
        return cache["rows"], cache["own"]

    def lookup(jwk: dict):
        thumb = device_key.thumbprint(jwk)
        all_rows, own = rows()
        for r in all_rows:
            if r.get("revoked_at") or not r.get("id"):
                continue
            match = bool(thumb) and r.get("key_thumbprint") == thumb
            if not match and r.get("sign_jwk"):
                try:
                    reg = json.loads(r["sign_jwk"])
                    match = reg.get("x") == jwk.get("x") and reg.get("y") == jwk.get("y")
                except (TypeError, ValueError, AttributeError):
                    match = False
            if match:
                return Peer(str(r["id"]), str(r.get("kind") or "full"), r.get("id") in own)
        return None

    lookup.forget = lambda: cache.update(at=-1e9)   # type: ignore[attr-defined]
    return lookup


class Server:
    def __init__(self, app, memory_path: Path, *, port: int):
        self.app = app
        self.memory_path = Path(memory_path)
        self.port = port
        self.servers: list[asyncio.base_events.Server] = []
        self.buckets = Buckets()
        self.replays = Replays()
        self.pending = 0
        self.sessions = 0
        self.watchers: set[asyncio.Queue] = set()
        self.watch_task: asyncio.Task | None = None
        self.counts = {"accepted": 0, "dropped": 0, "refusedPeer": 0, "limited": 0, "requests": 0}
        self.by_route: dict[str, float] = {}
        st = door_state() or {}
        self.priv = _x_load(_b64d(st["key"]))
        self.pub = _x_pub(self.priv)
        self.lookup = registry_lookup(memory_path)

    def running(self) -> bool:
        return bool(self.servers)

    async def start(self) -> None:
        last: Exception | None = None
        for _attempt in range(4):
            try:
                v4 = await asyncio.start_server(self._on_conn, host="0.0.0.0", port=self.port, reuse_address=True,
                                                limit=MAX_FRAME + 8)
            except OSError as exc:
                last = exc
                if self.port == 0 or os.environ.get(PORT_ENV):
                    raise
                self.port = secrets.randbelow(PORT_RANGE[1] - PORT_RANGE[0]) + PORT_RANGE[0]
                st = door_state() or {}
                _write_private(_door_path(), {**st, "port": self.port})
                continue
            self.servers.append(v4)
            self.port = v4.sockets[0].getsockname()[1]
            try:
                self.servers.append(await asyncio.start_server(self._on_conn, host="::", port=self.port,
                                                               reuse_address=True, limit=MAX_FRAME + 8))
            except OSError:
                pass          # no IPv6 here: the IPv4 door alone
            return
        raise last or OSError("no port")

    async def stop(self) -> None:
        for s in self.servers:
            s.close()
            with contextlib.suppress(Exception):
                await s.wait_closed()
        self.servers.clear()
        if self.watch_task is not None:
            self.watch_task.cancel()

    def wire(self) -> dict:
        return {"open": self.running(), "port": self.port, **self.counts, "sessions": self.sessions}

    # -- one connection ----------------------------------------------------------------------------------------------
    async def _on_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = (writer.get_extra_info("peername") or ("", 0))[0]
        local = (writer.get_extra_info("sockname") or ("", 0))[0]
        if not allowed_peer(local, peer):
            self.counts["refusedPeer"] += 1
            return self._close(writer)
        if self.pending >= MAX_PENDING or self.sessions >= MAX_SESSIONS or not self.buckets.take(peer):
            self.counts["limited"] += 1
            return self._close(writer)
        self.pending += 1
        opened = None
        try:
            try:
                hello = await asyncio.wait_for(reader.readexactly(HELLO_LEN), HELLO_TIMEOUT_S)
            except (asyncio.TimeoutError, asyncio.IncompleteReadError, OSError):
                hello = None
            if hello is not None:
                from api.services import device_key

                opened = server_open(hello, self.priv, self.pub, self.lookup, device_key.sign, self.replays)
        finally:
            self.pending -= 1
        if opened is None:
            self.counts["dropped"] += 1
            self.buckets.charge(peer, FAILED_COST - 1)
            return self._close(writer)          # silently: not one byte was sent
        device, keys, reply = opened
        self.counts["accepted"] += 1
        self.sessions += 1
        self._note_route(device.device_id, address_class(peer) or "lan")
        try:
            writer.write(reply)
            out, inn = Sealer(keys.send), Sealer(keys.recv)
            routes = own_routes(self.port) or {}
            writer.write(out.seal(b"R", json.dumps(routes).encode()))
            await writer.drain()
            await self._session(reader, writer, out, inn, device)
        except (asyncio.IncompleteReadError, ConnectionError, OSError, asyncio.TimeoutError, ValueError):
            pass
        except Exception as exc:  # noqa: BLE001 — one session never stops the door
            from cryptography.exceptions import InvalidTag

            if not isinstance(exc, InvalidTag):
                logger.info(f"door: a session ended ({type(exc).__name__})")
        finally:
            self.sessions -= 1
            self._close(writer)

    @staticmethod
    def _close(writer) -> None:
        with contextlib.suppress(Exception):
            writer.close()

    def _note_route(self, device_id: str, kind: str) -> None:
        """Which route a device reached this door by, as an enum in the telemetry ledger (once an hour per device
        and route; never an address)."""
        key = f"{device_id}|{kind}"
        now = time.monotonic()
        if now - self.by_route.get(key, -1e9) < 3600:
            return
        self.by_route[key] = now
        from api.services import sync_routes

        sync_routes.record("door", route="lan" if kind == "loopback" else kind, event="served")

    async def _read(self, reader, inn: Sealer, timeout: float = IDLE_S) -> tuple[bytes, bytes]:
        head = await asyncio.wait_for(reader.readexactly(4), timeout)
        n = frame_length(head)
        if n is None:
            raise ValueError("frame")
        return inn.open_(await asyncio.wait_for(reader.readexactly(n), 30.0))

    async def _session(self, reader, writer, out: Sealer, inn: Sealer, device: Peer) -> None:
        while True:
            kind, data = await self._read(reader, inn)
            if kind == b"P":
                continue
            if kind == b"W":
                await self._watch(reader, writer, out, inn)
                return
            if kind != b"Q" or len(data) > MAX_HEAD:
                raise ValueError("unexpected")
            req = json.loads(data)
            body = bytearray()
            while True:
                k, d = await self._read(reader, inn, 30.0)
                if k == b"E":
                    break
                if k != b"B" or len(body) + len(d) > MAX_REQUEST_BODY:
                    raise ValueError("body")
                body += d
            await self._serve(writer, out, device, req, bytes(body))

    async def _serve(self, writer, out: Sealer, device: Peer, req: dict, body: bytes) -> None:
        from api.services import sync_inprocess

        self.counts["requests"] += 1
        spill = _spool_dir()
        try:
            status, headers, answer, file = await sync_inprocess.run_in_process(
                self.app, sender=None, device_id=device.device_id if device.local else None,
                door_device=device.device_id, method=str(req.get("m") or "GET"), path=str(req.get("p") or "/"),
                query=str(req.get("q") or ""), headers=dict(req.get("h") or {}), body=body, spill_to=spill)
        except Exception as exc:  # noqa: BLE001
            logger.info(f"door: a request was not served ({type(exc).__name__})")
            status, headers, answer, file = 500, {}, b"", None
        writer.write(out.seal(b"S", json.dumps({"s": status, "h": headers}).encode()))
        try:
            if file is not None:
                with open(file, "rb") as fh:
                    while chunk := fh.read(CHUNK):
                        writer.write(out.seal(b"B", chunk))
                        await writer.drain()
            else:
                for i in range(0, len(answer), CHUNK):
                    writer.write(out.seal(b"B", answer[i:i + CHUNK]))
                    await writer.drain()
            writer.write(out.seal(b"E", b""))
            await writer.drain()
        finally:
            if file is not None:
                with contextlib.suppress(OSError):
                    os.unlink(file)

    async def _watch(self, reader, writer, out: Sealer, inn: Sealer) -> None:
        """Tell this device of every new commit until it hangs up; a ping keeps the connection."""
        from api.services import sync_service

        q: asyncio.Queue = asyncio.Queue(maxsize=4)
        self.watchers.add(q)
        if self.watch_task is None or self.watch_task.done():
            self.watch_task = asyncio.create_task(self._poll_head())
        head = await asyncio.to_thread(sync_service.git_head, self.memory_path)
        writer.write(out.seal(b"N", json.dumps({"head": head}).encode()))
        await writer.drain()
        hangup = asyncio.create_task(self._read(reader, inn, 10 * IDLE_S))
        try:
            while True:
                got = asyncio.create_task(q.get())
                done, _ = await asyncio.wait({got, hangup}, timeout=PING_S, return_when=asyncio.FIRST_COMPLETED)
                if hangup in done:
                    got.cancel()
                    return
                if got in done:
                    writer.write(out.seal(b"N", json.dumps({"head": got.result()}).encode()))
                else:
                    got.cancel()
                    writer.write(out.seal(b"P", b""))
                await writer.drain()
        finally:
            hangup.cancel()
            self.watchers.discard(q)

    async def _poll_head(self) -> None:
        """One file read every :data:`WATCH_POLL_S`, only while a device watches."""
        from api.services import sync_service

        last = await asyncio.to_thread(sync_service.git_head, self.memory_path)
        while self.watchers:
            await asyncio.sleep(WATCH_POLL_S)
            head = sync_service.git_head(self.memory_path)
            if head and head != last:
                last = head
                for q in list(self.watchers):
                    with contextlib.suppress(asyncio.QueueFull):
                        q.put_nowait(head)


def _spool_dir() -> Path:
    from api.services import runtime_layout

    path = runtime_layout.cicada_home() / "sync" / "door-spool"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


SERVER: Server | None = None


async def start(app, memory_path) -> Server | None:
    global SERVER
    if not enabled():
        return None
    if SERVER is not None and SERVER.running():
        return SERVER
    st = await asyncio.to_thread(door_state)
    raw_port = (os.environ.get(PORT_ENV) or "").strip()
    port = int(raw_port) if raw_port.isdigit() else int(st["port"])
    server = Server(app, memory_path, port=port)
    try:
        await server.start()
    except OSError as exc:
        logger.warning(f"door: not opened ({type(exc).__name__})")
        return None
    SERVER = server
    logger.info("door: open for this memory's devices (home network and tailnet only)")
    return server


async def stop() -> None:
    global SERVER
    server, SERVER = SERVER, None
    if server is not None:
        await server.stop()


# --- the client (blocking: called from the follower's, the outbox's and a phone-like client's threads) -----------------

class Conn:
    def __init__(self, sock: socket.socket, keys: Keys, routes: dict | None):
        self.sock = sock
        self.out = Sealer(keys.send)
        self.inn = Sealer(keys.recv)
        self.routes = routes
        self.at = time.monotonic()
        self.broken = False

    def send(self, kind: bytes, data: bytes = b"") -> None:
        self.sock.sendall(self.out.seal(kind, data))

    def _exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return bytes(buf)

    def recv(self) -> tuple[bytes, bytes]:
        n = frame_length(self._exact(4))
        if n is None:
            raise ConnectionError("frame")
        return self.inn.open_(self._exact(n))

    def close(self) -> None:
        self.broken = True
        with contextlib.suppress(OSError):
            self.sock.close()


def connect(host: str, port: int, target: Target, identity: Identity, *, timeout: float = 2.0,
            on_routes=None) -> Conn:
    """A session with ``target``'s door at ``host:port``: ``Unreachable`` when nothing answered as that device."""
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
    except OSError as exc:
        raise Unreachable("connect") from exc
    try:
        sock.settimeout(timeout + 2.0)
        hello, state = client_hello(identity, target.door_pub)
        sock.sendall(hello)
        reply = bytearray()
        while len(reply) < REPLY_LEN:
            chunk = sock.recv(REPLY_LEN - len(reply))
            if not chunk:
                raise Unreachable("closed")
            reply += chunk
        keys = client_finish(state, bytes(reply), target.jwk)
        conn = Conn(sock, keys, None)
        kind, data = conn.recv()
        if kind == b"R":
            try:
                conn.routes = json.loads(data)
            except ValueError:
                conn.routes = None
            if on_routes is not None and isinstance(conn.routes, dict):
                with contextlib.suppress(Exception):
                    on_routes(target.device_id, conn.routes)
        return conn
    except Unreachable:
        sock.close()
        raise
    except Exception as exc:  # noqa: BLE001 — a handshake that did not finish
        sock.close()
        raise Unreachable("handshake") from exc


def call(conn: Conn, method: str, path_q: str, *, body: bytes | None = None, headers: dict | None = None,
         timeout: float = 30.0, to_file: Path | None = None):
    """One request over an open session: ``(status, headers, body)`` — ``Dropped`` when the session ended before the
    whole answer came (the request may have landed)."""
    from urllib.parse import urlsplit

    from api.services import sync_inprocess

    parts = urlsplit(path_q)
    keep = {k.lower(): v for k, v in (headers or {}).items() if k.lower() in sync_inprocess.REQUEST_HEADERS}
    conn.sock.settimeout(timeout)
    try:
        conn.send(b"Q", json.dumps({"m": method, "p": parts.path, "q": parts.query, "h": keep}).encode())
        data = body or b""
        for i in range(0, len(data), CHUNK):
            conn.send(b"B", data[i:i + CHUNK])
        conn.send(b"E")
    except OSError as exc:
        conn.close()
        raise Unreachable("send") from exc
    try:
        kind, head = conn.recv()
        while kind == b"P":
            kind, head = conn.recv()
        if kind != b"S":
            raise ConnectionError("answer")
        meta = json.loads(head)
        status = int(meta.get("s") or 500)
        rheaders = {str(k).title(): v for k, v in (meta.get("h") or {}).items()}
        fh = open(to_file, "wb") if to_file is not None and 200 <= status < 300 else None
        buf = bytearray()
        try:
            while True:
                kind, chunk = conn.recv()
                if kind == b"E":
                    break
                if kind != b"B":
                    raise ConnectionError("answer")
                if fh is not None:
                    fh.write(chunk)
                else:
                    buf += chunk
                    if len(buf) > MAX_MEMORY_ANSWER:
                        raise ConnectionError("too large")
        finally:
            if fh is not None:
                fh.close()
    except Exception as exc:  # noqa: BLE001 — a timeout, a reset, a frame that did not open
        conn.close()
        raise Dropped("answer") from exc
    conn.at = time.monotonic()
    if fh is not None:
        return status, rheaders, to_file
    if not buf:
        return status, rheaders, None
    try:
        return status, rheaders, json.loads(bytes(buf).decode("utf-8"))
    except ValueError:
        return status, rheaders, bytes(buf)


def watch(conn: Conn, on_head, stop: threading.Event) -> None:
    """Hold ``conn`` as a watch: ``on_head(sha)`` for each commit the door announces, until ``stop`` or a hang-up."""
    conn.sock.settimeout(PING_S * 2 + 5)
    try:
        conn.send(b"W")
        while not stop.is_set():
            kind, data = conn.recv()
            if kind == b"N":
                with contextlib.suppress(Exception):
                    on_head((json.loads(data) or {}).get("head"))
    except Exception:  # noqa: BLE001 — the door went away: the caller tries again
        pass
    finally:
        conn.close()


class Pool:
    """Idle sessions kept per (address, device) for reuse; a session idle longer than :data:`REUSE_S` is closed."""

    REUSE_S = 60.0

    def __init__(self):
        self.lock = threading.Lock()
        self.idle: dict[tuple, list[Conn]] = {}

    def take(self, key: tuple) -> Conn | None:
        with self.lock:
            conns = self.idle.get(key) or []
            while conns:
                c = conns.pop()
                if not c.broken and time.monotonic() - c.at < self.REUSE_S:
                    return c
                c.close()
        return None

    def give(self, key: tuple, conn: Conn) -> None:
        if conn.broken:
            return
        with self.lock:
            conns = self.idle.setdefault(key, [])
            conns.append(conn)
            while len(conns) > 4:
                conns.pop(0).close()

    def drop(self, prefix: tuple | None = None) -> None:
        with self.lock:
            for key in list(self.idle):
                if prefix is None or key[:len(prefix)] == prefix:
                    for c in self.idle.pop(key):
                        c.close()


POOL = Pool()


def request(host: str, port: int, target: Target, identity: Identity, method: str, path_q: str, *,
            body: bytes | None = None, headers: dict | None = None, timeout: float = 30.0,
            to_file: Path | None = None, connect_timeout: float = 2.0, on_routes=None, pool: Pool | None = None):
    """One request through ``target``'s door, reusing an idle session when one is open. ``Unreachable`` (nothing was
    sent) or ``Dropped`` (sent, no whole answer)."""
    pool = pool or POOL
    key = (host, int(port), target.device_id)
    conn = pool.take(key)
    if conn is not None:
        try:
            got = call(conn, method, path_q, body=body, headers=headers, timeout=timeout, to_file=to_file)
            pool.give(key, conn)
            return got
        except (Unreachable, Dropped):
            pass              # the idle session had gone stale: a new one, once (a write carries its key: once)
    conn = connect(host, port, target, identity, timeout=connect_timeout, on_routes=on_routes)
    got = call(conn, method, path_q, body=body, headers=headers, timeout=timeout, to_file=to_file)
    pool.give(key, conn)
    return got
