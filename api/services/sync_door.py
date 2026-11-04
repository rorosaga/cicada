"""The home-network door: a sealed-frame endpoint for the person's own devices (G132, ruling 51f D3, owner 2026-11-03:
"encryption and security above all").

**What it is.** One UDP port a computer opens only while it shares a memory (a publishing home, or a copy) and never
for a demo (owner 2026-11-03: "If we can work on tcp and udp directly probably best to do udp, no?"). It speaks one
protocol, below, and nothing else: never the HTTP API, never a token, never a bank path. A device proves who it is in
its very first datagram; anything else gets no answer at all, so a scanner cannot tell the port from a closed one that
answers nothing (``sync_door_udp``; the sealed packets and their reliability are ``sync_door_channel``). A TCP fallback
on the same port number carries the same handshake and frames, held only with ``CICADA_SYNC_DOOR_TCP=on`` (a TCP port
shows open to a scanner; :func:`tcp_enabled`). Requests it carries run in process through the same routes a
device token reaches (``sync_inprocess``), held to that device's rules (a capture-only phone reaches only
``auth.CAPTURE_ROUTES``), keyed by the same ``Idempotency-Key`` — a write carried twice, by two routes, applies once.

**Where it listens: never a wildcard, never a public or global address** (:func:`bind_hosts`). Loopback, and each of
this computer's own private (RFC 1918, IPv6 unique-local) and tailnet addresses, one socket each, re-read every
:data:`REBIND_S` so a new network binds its address and a gone one is closed; on a Mac, loopback only until the app's
permissions step. A server with a public address never listens on it, so nothing on a device listens on a public port.

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
  group is dropped silently. The hello's last 32 bytes are zero — except for **pairing**: a device not yet in the
  group (a phone scanning the QR in the same room) proves it holds the QR's one-time 256-bit secret with an HMAC over
  ``domain ‖ e_c ‖ ts ‖ P``. Such a session may make exactly one request, ``POST /pair`` with the code, which redeems
  it bound to ``P`` and answers the new device's id — never its token (the door never carries one, and the phone
  needs none: its key is its identity);
* the door answers ``e_s ‖ AEAD(k_r, ver ‖ sig_home)`` (:data:`REPLY_LEN` bytes), where ``sig_home`` is the door
  computer's own device-key signature over ``domain ‖ sha256(hello) ‖ e_s`` — the client checks it against the key the
  registry holds for the device it meant to reach, so a stolen door key alone cannot pose as the home;
* both sides derive one key per direction from ``DH(e_c, S) ‖ DH(e_c, e_s)`` and the transcript: forward secret.

**Frames.** Over UDP, ``u32 length ‖ type ‖ data`` records in the channel's sealed, acknowledged stream
(``sync_door_channel``: a packet number per datagram, a replay window, the AEAD per packet). Over the TCP fallback,
``u32 length ‖ ChaCha20-Poly1305(key, nonce = counter)``, one counter per direction from 0 — a frame replayed, dropped
or reordered fails to open and the connection closes. Each frame's plaintext is one type byte and its data: the
door's current routes (``R``, sent first, so a client learns where the door is now), a request head (``Q``) and its
body (``B`` … ``E``), the answer's head (``S``) and body, a watch (``W``: the door then sends ``N`` with each new
commit, and ``P`` to keep the connection), so a copy is told of a commit at once instead of polling.

**Limits.** A session confirmed within :data:`HELLO_TIMEOUT_S`; per source address a bucket of :data:`BUCKET`
handshakes refilled one per :data:`REFILL_S` (a failed one costs three); at most :data:`MAX_PENDING` sessions waiting to
be confirmed and :data:`MAX_SESSIONS` open; a frame at most :data:`MAX_FRAME` bytes, a request body at most 32 MiB; an idle
session closes after :data:`IDLE_S`.

Nothing here logs an address, a key, a path or a body: counts and enums only.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import ctypes
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
PAIR_DOMAIN = b"cicada-door-pair-v1\x00"
PAIR_TTL_S = 600
FRAME_AAD = b"CD1F"
TAG = 16
HELLO_PLAIN = 1 + 8 + 64 + 64 + 32
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
#: One proven device's own open UDP sessions; a new one past this ends that device's least recently heard one, so a
#: device's memory at the door is bounded (each session holds at most a receive window and a send backlog) and a device
#: that left sessions behind is never locked out (security review of #590).
MAX_SESSIONS_PER_DEVICE = 16
REPLAY_KEEP = 4096
WATCH_POLL_S = 0.5
DOOR_FILE = "door.json"
DOOR_ENV = "CICADA_SYNC_DOOR"
TCP_ENV = "CICADA_SYNC_DOOR_TCP"
PORT_ENV = "CICADA_SYNC_DOOR_PORT"
#: The addresses the door binds, comma-separated, instead of its own choice (:func:`bind_hosts`); ``127.0.0.1`` keeps it
#: on this computer (the suite). An address that is not loopback, private or tailnet is never bound, named or not.
HOST_ENV = "CICADA_SYNC_DOOR_HOST"
LOOPBACK_HOSTS = ("127.0.0.1", "::1")
#: How often the door compares the addresses it should bind with those it holds (a new network, a VPN up or down).
REBIND_S = 5.0
BINDABLE = ("loopback", "lan", "tailnet")
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
    anything unusable (wildcard, link-local, multicast). **By range only**: ``tailnet`` here says an address is in
    Tailscale's ranges, not that it is a tailnet — 100.64.0.0/10 is also carrier-grade NAT's shared space. Whether this
    computer really is on a tailnet is :func:`own_tailnet`; every bind and every admission asks it."""
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


def bindable(host: str, tailnet=None) -> bool:
    """May the door bind ``host``? Loopback and private addresses; a tailnet-range address only when it is one of this
    computer's own Tailscale addresses (``tailnet``, default :func:`own_tailnet`) — a carrier-grade NAT uplink in
    100.64.0.0/10 never. Never a wildcard, a public or a global address."""
    cls = address_class(host)
    if cls in ("loopback", "lan"):
        return True
    if cls == "tailnet":
        mine = own_tailnet() if tailnet is None else tailnet
        return str(_ip(host)) in {str(_ip(h)) for h in mine}
    return False


def allowed_peer(local: str, peer: str, *, tailnet=None) -> bool:
    """T3 Code's listener rule, made exact: a loopback connection from loopback; a private one from a private address;
    a tailnet-range peer **only** on one of this computer's own Tailscale addresses (``tailnet``, default
    :func:`own_tailnet`) — so a carrier's other subscribers in 100.64.0.0/10 are never let in."""
    lc, pc = address_class(local), address_class(peer)
    if lc == "loopback":
        return pc == "loopback"
    if lc == "lan":
        return pc == "lan"
    if lc == "tailnet" and pc == "tailnet":
        la, pa = _ip(local), _ip(peer)
        return la.version == pa.version and bindable(local, tailnet)
    return False


def _probe_local(family: int, target: str) -> str | None:
    """The local address the routing table would use toward ``target``. A UDP ``connect`` sends nothing."""
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as s:
            s.connect((target, 9))
            return s.getsockname()[0]
    except OSError:
        return None


class _Sockaddr(ctypes.Structure):
    _fields_ = [("sa_head", ctypes.c_ubyte * 2)]


class _Ifaddrs(ctypes.Structure):
    pass


_Ifaddrs._fields_ = [("ifa_next", ctypes.POINTER(_Ifaddrs)), ("ifa_name", ctypes.c_char_p),
                     ("ifa_flags", ctypes.c_uint), ("ifa_addr", ctypes.POINTER(_Sockaddr)),
                     ("ifa_netmask", ctypes.POINTER(_Sockaddr)), ("ifa_dstaddr", ctypes.POINTER(_Sockaddr)),
                     ("ifa_data", ctypes.c_void_p)]


_LIBC: list = []


def _libc():
    """The C library, loaded once: ``CDLL(None)`` is this process's own symbols (libc among them on macOS and Linux) —
    never ``ctypes.util.find_library``, which runs ``ldconfig`` in a subprocess on Linux."""
    if not _LIBC:
        _LIBC.append(ctypes.CDLL(None, use_errno=True))
    return _LIBC[0]


def interface_addresses() -> dict[str, list[str]]:
    """``{interface name: [its IPv4 and IPv6 addresses]}`` from the C library's ``getifaddrs`` (no process, no new
    dependency). Empty when it cannot be read — then no tailnet is recognised (the safe way to be wrong)."""
    import sys

    if sys.platform not in ("darwin", "linux"):
        return {}
    try:
        libc = _libc()
        head = ctypes.POINTER(_Ifaddrs)()
        if libc.getifaddrs(ctypes.byref(head)) != 0:
            return {}
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, list[str]] = {}
    try:
        node = head
        while node:
            ifa = node.contents
            if ifa.ifa_addr and ifa.ifa_name:
                ptr = ctypes.cast(ifa.ifa_addr, ctypes.c_void_p).value
                head2 = ctypes.string_at(ptr, 2)           # read only as far as the family says the address goes
                family = head2[1] if sys.platform == "darwin" else int.from_bytes(head2, sys.byteorder)
                addr = None
                if family == socket.AF_INET:
                    addr = socket.inet_ntop(socket.AF_INET, ctypes.string_at(ptr, 8)[4:8])
                elif family == socket.AF_INET6:
                    addr = socket.inet_ntop(socket.AF_INET6, ctypes.string_at(ptr, 24)[8:24])
                if addr:
                    out.setdefault(ifa.ifa_name.decode("utf-8", "replace"), []).append(addr)
            node = ifa.ifa_next
    finally:
        libc.freeifaddrs(head)
    return out


def _tailscale_interface(name: str, platform: str | None = None) -> bool:
    """Tailscale's own interface: ``utun*`` on a Mac (its network extension), ``tailscale*`` on Linux."""
    import sys

    platform = platform or sys.platform
    if platform == "darwin":
        return name.startswith("utun")
    if platform == "linux":
        return name.startswith("tailscale")
    return False


def tailscale_addresses(interfaces: dict[str, list[str]], default_v4: str | None) -> list[str]:
    """This computer's Tailscale addresses, or none. Both must hold (security re-check of #586):

    1. **On Tailscale's own interface.** One interface named as Tailscale's holds both a 100.64.0.0/10 address and
       one in ``fd7a:115c:a1e0::/48`` (Tailscale assigns the pair). A router advertisement on the LAN can make this
       computer give itself an ``fd7a:`` address on its Wi-Fi interface, and a carrier can hand it a 100.x uplink; neither
       is on Tailscale's interface.
    2. **Not the default route's IPv4 source.** A carrier's 100.x uplink is where the default route leaves from;
       Tailscale's is not (no router advertisement changes IPv4 source selection). So Tailscale used as an exit node —
       its 100.x then the default route's source — is not recognised: the accepted fail-safe, as is a tailnet with
       IPv6 turned off."""
    found: list[str] = []
    default = _ip(default_v4) if default_v4 else None
    for name, addrs in sorted(interfaces.items()):
        if not _tailscale_interface(name):
            continue
        v4 = [a for a in addrs if (ip := _ip(a)) is not None and ip.version == 4 and ip in TAILNET_V4]
        v6 = [a for a in addrs if (ip := _ip(a)) is not None and ip.version == 6 and ip in TAILNET_V6]
        v4 = [a for a in v4 if _ip(a) != default]
        if v4 and v6:
            found += [a for a in v4 + v6 if a not in found]
    return found


def local_addresses(probe=None, interfaces=None) -> dict:
    """This computer's own addresses by class, read from the routing table without a packet (the default route's IPv4
    and IPv6 sources) and from its interfaces (:func:`tailscale_addresses`). **A tailnet is Tailscale's only when it
    is really there**: any address in Tailscale's ranges that :func:`tailscale_addresses` does not vouch for — a
    carrier-grade NAT uplink, an ``fd7a:`` address a stray router advertisement gave — is ``public``: never bound,
    never a route, never a door to the neighbours."""
    probe = probe or _probe_local
    interfaces = interface_addresses() if interfaces is None else interfaces
    default_v4 = probe(socket.AF_INET, "192.0.2.1")
    mine = tailscale_addresses(interfaces, default_v4)
    found: dict[str, list[str]] = {"lan": [], "tailnet": list(mine), "ipv6": [], "public": []}
    for got in (default_v4, probe(socket.AF_INET6, "2001:db8::1"), probe(socket.AF_INET, "100.100.100.100"),
                probe(socket.AF_INET6, "fd7a:115c:a1e0::53")):
        kind = address_class(got) if got else None
        if kind == "tailnet" and got not in mine:
            kind = "public"
        if kind in found and got not in found[kind]:
            found[kind].append(got)
    return found


_TAILNET: list = [frozenset(), -1e9]


def own_tailnet() -> frozenset:
    """This computer's own Tailscale addresses (empty with no tailnet), read at most every 5 s."""
    now = time.monotonic()
    if now - _TAILNET[1] > 5.0:
        _TAILNET[0] = frozenset(local_addresses()["tailnet"])
        _TAILNET[1] = now
    return _TAILNET[0]


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


def tcp_enabled(environ=os.environ) -> bool:
    """The TCP fallback, off unless ``CICADA_SYNC_DOOR_TCP=on``: on the LAN and a tailnet UDP always passes, and a
    TCP port is a port a scanner sees open — the owner's silence goal wins until slice 2 reaches networks that block
    UDP."""
    return (environ.get(TCP_ENV) or "off").strip().lower() in ("on", "1", "true")


def own_routes(port: int | None = None) -> dict | None:
    """What this computer's door tells its devices: the port, the door's public key, this computer's addresses by
    class (slice 1: the LAN and the tailnet) and the carriers it answers on (``t``: ``udp``, and ``tcp`` only while
    the fallback is held). None while no door is open here."""
    server = SERVER
    if server is None or not server.running():
        return None
    state = door_state(create=False) or {}
    bound = server.hosts()
    # Only the addresses the door is bound to are routes (none beyond loopback, when it is loopback only).
    return {"v": 1, "port": int(port or server.port), "key": state.get("pub"),
            "lan": [h for h in bound if address_class(h) == "lan"],
            "tailnet": [h for h in bound if address_class(h) == "tailnet"], "t": server.carriers()}


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


def _pair_tag(secret: bytes, e_c: bytes, ts: int, xy: bytes) -> bytes:
    import hmac

    return hmac.new(secret, PAIR_DOMAIN + e_c + struct.pack(">Q", ts) + xy, hashlib.sha256).digest()


def client_hello(identity: Identity, door_pub: bytes, *, now: float | None = None,
                 pair_secret: bytes | None = None) -> tuple[bytes, object]:
    eph = _x25519_new()
    e_c = _x_pub(eph)
    ts = int(now if now is not None else time.time())
    signed = HELLO_DOMAIN + door_pub + e_c + struct.pack(">Q", ts)
    sig = _b64d(identity.sign(signed))
    if len(sig) != 64:
        raise ValueError("signature")
    xy = _jwk_xy(identity.jwk)
    tag = _pair_tag(pair_secret, e_c, ts, xy) if pair_secret else b"\0" * 32
    plain = bytes([VERSION]) + struct.pack(">Q", ts) + xy + sig + tag
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
                now: float | None = None, pairing=None):
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
    xy, sig, tag = plain[9:73], plain[73:137], plain[137:169]
    jwk = _xy_jwk(xy)
    signed = HELLO_DOMAIN + door_pub + e_c + struct.pack(">Q", ts)
    if not device_key.verify(jwk, signed, _b64e(sig)):
        return None
    device = lookup(jwk)
    if device is None and pairing is not None and tag != b"\0" * 32:
        import hmac

        device = pairing(lambda secret: hmac.compare_digest(_pair_tag(secret, e_c, ts, xy), tag), jwk)
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

def bucket_key(peer: str) -> str:
    """Whose bucket a connection spends: its IPv4 address, or its IPv6 /64 — one network, however many addresses it
    rotates through."""
    addr = _ip(peer)
    if addr is None:
        return str(peer)
    if addr.version == 6:
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


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
    kind: str        # full | capture — or ``pairing``: a device the QR's secret let in, for its one redeem
    local: bool      # a row of this computer's own store: its routes are admitted as that device
    jwk: dict | None = None
    pairing_id: str | None = None


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


class TcpLink:
    """A TCP fallback session (``CICADA_SYNC_DOOR_TCP=on``): the same framed interface as ``sync_door_udp.UdpLink``,
    on ``u32 length ‖ sealed`` frames over the stream."""

    carrier = "tcp"

    def __init__(self, reader, writer, keys: Keys, device: "Peer", peer_class: str):
        self.reader, self.writer = reader, writer
        self.out, self.inn = Sealer(keys.send), Sealer(keys.recv)
        self.device = device
        self.peer_class = peer_class

    async def read(self, timeout: float) -> tuple[bytes, bytes]:
        head = await asyncio.wait_for(self.reader.readexactly(4), timeout)
        n = frame_length(head)
        if n is None:
            raise ValueError("frame")
        return self.inn.open_(await asyncio.wait_for(self.reader.readexactly(n), 30.0))

    def send(self, kind: bytes, data: bytes = b"") -> None:
        self.writer.write(self.out.seal(kind, data))

    async def drain(self) -> None:
        await self.writer.drain()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.writer.close()

    def abort(self) -> None:
        with contextlib.suppress(Exception):
            self.writer.transport.abort()


class Server:
    def __init__(self, app, memory_path: Path, *, port: int, hosts=None, tcp: bool | None = None):
        """``hosts``: the addresses to bind (a list, or a callable giving them); by default :func:`bind_hosts`.
        ``tcp``: also hold the TCP fallback (default :func:`tcp_enabled`, off)."""
        from api.services import sync_door_udp

        self.plan = (lambda: list(hosts)) if isinstance(hosts, (list, tuple)) else (hosts or bind_hosts)
        self.bound: dict[str, object] = {}          # UDP: the door
        self.tcp_bound: dict[str, asyncio.base_events.Server] = {}
        self.with_tcp = tcp_enabled() if tcp is None else bool(tcp)
        self.udp = sync_door_udp.Door(self)
        self.rebind_task: asyncio.Task | None = None
        self.by_device: dict[str, set] = {}
        self.tasks: set[asyncio.Task] = set()
        self.app = app
        self.memory_path = Path(memory_path)
        self.port = port
        self.buckets = Buckets()
        self.replays = Replays()
        self.pending = 0
        self.sessions = 0
        self.watchers: set[asyncio.Queue] = set()
        self.watch_task: asyncio.Task | None = None
        self.counts = {"accepted": 0, "dropped": 0, "refusedPeer": 0, "limited": 0, "requests": 0, "roamed": 0,
                       "evicted": 0}
        self.by_route: dict[str, float] = {}
        #: How each device last reached this door (``agent_seen.HOW``), so a request it sends is stamped the same way.
        self.how_of: dict[str, str] = {}
        st = door_state() or {}
        self.priv = _x_load(_b64d(st["key"]))
        self.pub = _x_pub(self.priv)
        self.lookup = registry_lookup(memory_path)
        self.pairings: dict[str, tuple[bytes, float]] = {}

    # -- pairing over the door ---------------------------------------------------------------------------------------
    def open_pairing(self, pairing_id: str) -> str:
        """A one-time secret for the QR of pairing ``pairing_id`` (ten minutes, one use)."""
        now = time.monotonic()
        for k in [k for k, (_s, at) in self.pairings.items() if now - at > PAIR_TTL_S]:
            self.pairings.pop(k, None)
        secret = secrets.token_bytes(32)
        self.pairings[pairing_id] = (secret, now)
        return _b64e(secret)

    def _pairing_peer(self, matches, jwk):
        now = time.monotonic()
        for pid, (secret, at) in list(self.pairings.items()):
            if now - at <= PAIR_TTL_S and matches(secret):
                return Peer("", "pairing", False, jwk=jwk, pairing_id=pid)
        return None

    def open_hello(self, hello: bytes):
        """``(device, keys, reply)`` for a hello proving a device of the group (or a pairing), else None."""
        from api.services import device_key

        return server_open(hello, self.priv, self.pub, self.lookup, device_key.sign, self.replays,
                           pairing=self._pairing_peer if self.pairings else None)

    def running(self) -> bool:
        return bool(self.bound)

    def hosts(self) -> list[str]:
        return list(self.bound)

    def carriers(self) -> list[str]:
        return ["udp"] + (["tcp"] if self.tcp_bound else [])

    async def _bind(self, host: str):
        if not bindable(host):          # never a wildcard, a public or global address, nor a carrier's 100.64/10
            raise OSError("not a private address")
        return await self.udp.bind(host, self.port)

    async def _bind_tcp(self, host: str):
        if not bindable(host):
            raise OSError("not a private address")
        return await asyncio.start_server(self._on_conn, host=host, port=self.port, reuse_address=True,
                                          limit=MAX_FRAME + 8)

    async def start(self) -> None:
        """Bind loopback first (it fixes the port), then every other planned address on the same port; an address
        that cannot be bound now (gone, or no IPv6) is skipped and tried again at the next rebind."""
        self.loop = asyncio.get_running_loop()
        last: Exception | None = None
        for _attempt in range(4):
            try:
                first = await self._bind(LOOPBACK_HOSTS[0])
            except OSError as exc:
                last = exc
                if self.port == 0 or os.environ.get(PORT_ENV):
                    raise
                self.port = secrets.randbelow(PORT_RANGE[1] - PORT_RANGE[0]) + PORT_RANGE[0]
                st = door_state() or {}
                _write_private(_door_path(), {**st, "port": self.port})
                continue
            self.port = first.sockets()[0].getsockname()[1]
            self.bound[LOOPBACK_HOSTS[0]] = first
            await self.rebind()
            self.rebind_task = asyncio.create_task(self._rebind_loop())
            return
        raise last or OSError("no port")

    async def rebind(self) -> None:
        """Hold exactly the planned addresses: bind the new ones, close the ones this computer no longer has."""
        try:
            wanted = [h for h in await asyncio.to_thread(self.plan) if bindable(h)]
        except Exception:  # noqa: BLE001 — keep what is bound
            return
        if LOOPBACK_HOSTS[0] not in wanted:
            wanted.insert(0, LOOPBACK_HOSTS[0])
        for held, binder in ((self.bound, self._bind), (self.tcp_bound, self._bind_tcp)):
            if held is self.tcp_bound and not self.with_tcp:
                continue
            for host in [h for h in held if h not in wanted]:
                held.pop(host).close()
            for host in [h for h in wanted if h not in held]:
                try:
                    held[host] = await binder(host)
                except OSError:
                    pass

    async def _rebind_loop(self) -> None:
        while self.bound:
            await asyncio.sleep(REBIND_S)
            await self.rebind()

    async def stop(self) -> None:
        if self.rebind_task is not None:
            self.rebind_task.cancel()
        self.udp.close_all()
        for links in list(self.by_device.values()):
            for link in list(links):
                link.abort()                    # an open TCP session would hold wait_closed forever
        for ep in list(self.bound.values()):
            ep.close()
        self.bound.clear()
        for srv in list(self.tcp_bound.values()):
            srv.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(srv.wait_closed(), 2.0)
        self.tcp_bound.clear()
        running = [t for t in list(self.tasks) + [self.watch_task] if t is not None and not t.done()]
        for task in running:
            task.cancel()
        if running:
            with contextlib.suppress(Exception):
                await asyncio.wait(running, timeout=2.0)

    def close_device(self, device_id: str) -> int:
        """A revoked device's open sessions (its watch included) end at once. Returns how many."""
        links = self.by_device.pop(device_id, set())
        for link in links:
            link.abort()
        return len(links)

    def wire(self) -> dict:
        kinds = [address_class(h) for h in self.bound]
        tcp = [address_class(h) for h in self.tcp_bound]
        return {"open": self.running(), "port": self.port, **self.counts, "sessions": self.sessions,
                "bound": {k: kinds.count(k) for k in BINDABLE},
                "tcp": {k: tcp.count(k) for k in BINDABLE} if self.tcp_bound else None}

    # -- one session, whichever carrier --------------------------------------------------------------------------------
    def spawn(self, link) -> None:
        """A UDP session the device just confirmed: run it."""
        task = asyncio.create_task(self._run(link))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _on_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """The TCP fallback's connections."""
        peer = (writer.get_extra_info("peername") or ("", 0))[0]
        local = (writer.get_extra_info("sockname") or ("", 0))[0]
        if not allowed_peer(local, peer):
            self.counts["refusedPeer"] += 1
            return self._close(writer)
        who = bucket_key(peer)
        if self.pending >= MAX_PENDING or self.sessions >= MAX_SESSIONS or not self.buckets.take(who):
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
                opened = self.open_hello(hello)
        finally:
            self.pending -= 1
        if opened is None:
            self.counts["dropped"] += 1
            self.buckets.charge(who, FAILED_COST - 1)
            return self._close(writer)          # silently: not one byte was sent
        device, keys, reply = opened
        writer.write(reply)
        await self._run(TcpLink(reader, writer, keys, device, address_class(peer) or "lan"))

    @staticmethod
    def _close(writer) -> None:
        with contextlib.suppress(Exception):
            writer.close()

    async def _run(self, link) -> None:
        device = link.device
        self.counts["accepted"] += 1
        self.sessions += 1
        if device.device_id:
            self.by_device.setdefault(device.device_id, set()).add(link)
        try:
            if device.kind != "pairing":
                self._note_route(device.device_id, link.peer_class, link.carrier)
                self._seen(device.device_id, link.peer_class)
            link.send(b"R", json.dumps(own_routes(self.port) or {}).encode())
            await link.drain()
            await self._session(link, device)
        except (asyncio.IncompleteReadError, ConnectionError, OSError, asyncio.TimeoutError, ValueError):
            pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — one session never stops the door
            from cryptography.exceptions import InvalidTag

            if not isinstance(exc, InvalidTag):
                logger.info(f"door: a session ended ({type(exc).__name__})")
        finally:
            self.sessions -= 1
            if device.device_id:
                self.by_device.get(device.device_id, set()).discard(link)
            link.close()

    def _note_route(self, device_id: str, kind: str, carrier: str) -> None:
        """Which route and carrier a device reached this door by, as enums in the telemetry ledger (once an hour per
        device, route and carrier; never an address)."""
        key = f"{device_id}|{kind}|{carrier}"
        now = time.monotonic()
        if now - self.by_route.get(key, -1e9) < 3600:
            return
        self.by_route[key] = now
        from api.services import sync_routes

        sync_routes.record("door", route="lan" if kind == "loopback" else kind, event="served", carrier=carrier)

    def _seen(self, device_id: str | None, kind: str | None = None) -> None:
        """The Devices page's *how* and *last seen* for a device that reached this door (``agent_seen``, G212): a
        tailnet peer is ``tailscale``, any other ``lan`` — an enum and a time, never an address. Throttled there."""
        if not device_id:
            return
        if kind is not None:
            self.how_of[device_id] = "tailscale" if kind == "tailnet" else "lan"
        from api.services import agent_seen

        agent_seen.stamp_device(device_id, self.how_of.get(device_id, "lan"))

    async def _session(self, link, device: Peer) -> None:
        while True:
            kind, data = await link.read(IDLE_S)
            if kind == b"P":
                continue
            if kind == b"W":
                await self._watch(link)
                return
            if kind != b"Q" or len(data) > MAX_HEAD:
                raise ValueError("unexpected")
            req = json.loads(data)
            body = bytearray()
            while True:
                k, d = await link.read(30.0)
                if k == b"E":
                    break
                if k != b"B" or len(body) + len(d) > MAX_REQUEST_BODY:
                    raise ValueError("body")
                body += d
            if device.kind == "pairing":
                await self._pair(link, device, req, bytes(body))
                return
            await self._serve(link, device, req, bytes(body))

    async def _pair(self, link, device: Peer, req: dict, body: bytes) -> None:
        """The one request a pairing session may make: ``POST /pair`` with the code — redeemed bound to the key the
        hello proved. The answer is the new device's id and kind; never its token."""
        from api.services import device_key, device_tokens

        status, answer = 404, {"detail": "No pairing waits with that code."}
        if req.get("m") == "POST" and req.get("p") == "/pair" and self.pairings.pop(device.pairing_id, None):
            try:
                ask = json.loads(body or b"{}")
                made, _token = await asyncio.to_thread(
                    device_tokens.store().redeem, str(ask.get("code") or ""), str(ask.get("name") or "Phone"),
                    key_thumbprint=device_key.thumbprint(device.jwk), kind="capture", pairing_id=device.pairing_id)
                status, answer = 201, {"device": made.wire()}
                self.lookup.forget()
            except device_tokens.FullDeviceKey:
                status, answer = 409, {"detail": "Only a phone pairs over this path."}
            except (KeyError, ValueError, TypeError):
                pass
        link.send(b"S", json.dumps({"s": status, "h": {"content-type": "application/json"}}).encode())
        link.send(b"B", json.dumps(answer).encode())
        link.send(b"E", b"")
        await link.drain()

    async def _serve(self, link, device: Peer, req: dict, body: bytes) -> None:
        from api.services import sync_inprocess

        self.counts["requests"] += 1
        self._seen(device.device_id)
        spill = _spool_dir()
        try:
            status, headers, answer, file = await sync_inprocess.run_in_process(
                self.app, sender=None, device_id=device.device_id if device.local else None,
                door_device=device.device_id, method=str(req.get("m") or "GET"), path=str(req.get("p") or "/"),
                query=str(req.get("q") or ""), headers=dict(req.get("h") or {}), body=body, spill_to=spill)
        except Exception as exc:  # noqa: BLE001
            logger.info(f"door: a request was not served ({type(exc).__name__})")
            status, headers, answer, file = 500, {}, b"", None
        link.send(b"S", json.dumps({"s": status, "h": headers}).encode())
        try:
            if file is not None:
                with open(file, "rb") as fh:
                    while chunk := fh.read(CHUNK):
                        link.send(b"B", chunk)
                        await link.drain()
            else:
                for i in range(0, len(answer), CHUNK):
                    link.send(b"B", answer[i:i + CHUNK])
                    await link.drain()
            link.send(b"E", b"")
            await link.drain()
        finally:
            if file is not None:
                with contextlib.suppress(OSError):
                    os.unlink(file)

    async def _watch(self, link) -> None:
        """Tell this device of every new commit until it hangs up; a ping keeps the session (and any NAT) alive."""
        from api.services import sync_service

        q: asyncio.Queue = asyncio.Queue(maxsize=4)
        self.watchers.add(q)
        if self.watch_task is None or self.watch_task.done():
            self.watch_task = asyncio.create_task(self._poll_head())
        head = await asyncio.to_thread(sync_service.git_head, self.memory_path)
        link.send(b"N", json.dumps({"head": head}).encode())
        await link.drain()
        hangup = asyncio.create_task(link.read(10 * IDLE_S))
        got = None
        try:
            while True:
                got = asyncio.create_task(q.get())
                done, _ = await asyncio.wait({got, hangup}, timeout=PING_S, return_when=asyncio.FIRST_COMPLETED)
                if hangup in done:
                    got.cancel()
                    hangup.exception()          # retrieved: a hang-up is the normal end of a watch
                    return
                if got in done:
                    link.send(b"N", json.dumps({"head": got.result()}).encode())
                else:
                    got.cancel()
                    link.send(b"P", b"")
                await link.drain()
        finally:
            hangup.cancel()
            if got is not None:
                got.cancel()
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


def bind_hosts(environ=os.environ, *, found: dict | None = None) -> list[str]:
    """Every address the door binds now — **never a wildcard, never a public or global address**: loopback, then this
    computer's own private (RFC 1918, IPv6 unique-local) and tailnet addresses, read from the routing table. On a Mac,
    loopback only until the app says the person went through its permissions step (``sync_routes``' ``lanAllowed``)
    **and** this backend's agent names the app as its responsible code (``sync_routes.may_dial_lan``): binding a LAN
    address raises the application firewall's question, and the UDP door's answers are outgoing datagrams to the LAN,
    which need the Local Network privilege (TN3179: "Sending a UDP unicast" — yes; accepting TCP — no) — nothing may
    ask either unasked, and nothing may ask under no app's name.
    ``CICADA_SYNC_DOOR_HOST`` names the addresses instead (only the bindable ones are kept)."""
    import sys

    raw = (environ.get(HOST_ENV) or "").strip()
    if raw:
        named = [h.strip() for h in raw.split(",") if bindable(h.strip())]
        return named or [LOOPBACK_HOSTS[0]]
    hosts = list(LOOPBACK_HOSTS)
    if sys.platform == "darwin":
        from api.services import sync_routes

        if not sync_routes.may_dial_lan(environ):
            return hosts
    found = found if found is not None else local_addresses()
    mine = frozenset(found.get("tailnet") or [])
    for h in list(found.get("lan") or []) + list(found.get("tailnet") or []):
        if bindable(h, mine) and h not in hosts:
            hosts.append(h)
    return hosts


async def start(app, memory_path) -> Server | None:
    global SERVER
    if not enabled():
        return None
    if SERVER is not None and SERVER.running():
        await SERVER.rebind()         # the person allowed the LAN since, or this computer joined another network
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
    logger.info("door: open for this memory's devices (UDP; loopback, home network and tailnet addresses only)")
    return server


async def stop() -> None:
    global SERVER
    server, SERVER = SERVER, None
    if server is not None:
        await server.stop()


# --- the client (blocking: called from the follower's, the outbox's and a phone-like client's threads) -----------------
#
# Two carriers, one interface (``send``, ``recv``, ``settimeout``, ``close``): ``door`` — UDP, ``sync_door_udp.UdpConn``
# — and ``door-tcp``, the fallback below (:class:`Conn`), used only toward a door that says it holds one.

CARRIERS = ("door", "door-tcp")


class Conn:
    """A TCP fallback session."""

    carrier = "door-tcp"

    def __init__(self, sock: socket.socket, keys: Keys, routes: dict | None):
        self.sock = sock
        self.out = Sealer(keys.send)
        self.inn = Sealer(keys.recv)
        self.routes = routes
        self.at = time.monotonic()
        self.broken = False
        self.stop = None
        self.keepalive = False

    def settimeout(self, t: float) -> None:
        self.sock.settimeout(t)

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
            self.sock.shutdown(socket.SHUT_RDWR)      # wakes a read blocked in another thread (a watch)
        with contextlib.suppress(OSError):
            self.sock.close()


def _connect_tcp(host: str, port: int, target: Target, identity: Identity, *, timeout: float = 2.0,
                 on_routes=None, pair_secret: bytes | None = None) -> Conn:
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
    except OSError as exc:
        raise Unreachable("connect") from exc
    try:
        sock.settimeout(timeout + 2.0)
        hello, state = client_hello(identity, target.door_pub, pair_secret=pair_secret)
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


def connect(host: str, port: int, target: Target, identity: Identity, *, timeout: float = 2.0,
            on_routes=None, pair_secret: bytes | None = None, carrier: str = "door", paths: list | None = None):
    """A session with ``target``'s door at ``host:port``: ``Unreachable`` when nothing answered as that device.
    ``carrier``: ``door`` (UDP) or ``door-tcp`` (the fallback). ``paths``: the target's other door addresses, which a
    UDP session moves to when this one goes quiet."""
    if carrier == "door-tcp":
        return _connect_tcp(host, port, target, identity, timeout=timeout, on_routes=on_routes,
                            pair_secret=pair_secret)
    from api.services import sync_door_udp

    return sync_door_udp.connect(host, port, target, identity, timeout=timeout, on_routes=on_routes,
                                 pair_secret=pair_secret, paths=paths)


def call(conn, method: str, path_q: str, *, body: bytes | None = None, headers: dict | None = None,
         timeout: float = 30.0, to_file: Path | None = None):
    """One request over an open session: ``(status, headers, body)`` — ``Dropped`` when the session ended before the
    whole answer came (the request may have landed)."""
    from urllib.parse import urlsplit

    from api.services import sync_inprocess

    parts = urlsplit(path_q)
    keep = {k.lower(): v for k, v in (headers or {}).items() if k.lower() in sync_inprocess.REQUEST_HEADERS}
    conn.settimeout(timeout)
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


def watch(conn, on_head, stop: threading.Event) -> None:
    """Hold ``conn`` as a watch: ``on_head(sha)`` for each commit the door announces, until ``stop`` or a hang-up.
    A UDP session pings every keepalive interval and at once on a network change, so a gone path ends the watch in
    seconds and a NAT keeps the mapping."""
    conn.settimeout(PING_S * 2 + 5)
    conn.stop = stop
    conn.keepalive = True
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
    """Idle sessions kept per (carrier, address, device) for reuse; a session idle longer than :data:`REUSE_S` is
    closed."""

    REUSE_S = 60.0

    def __init__(self):
        self.lock = threading.Lock()
        self.idle: dict[tuple, list] = {}
        self.gen = 0          # bumped by every drop: a session taken before a network change is not kept after it

    def take(self, key: tuple):
        with self.lock:
            conns = self.idle.get(key) or []
            while conns:
                c = conns.pop()
                if not c.broken and time.monotonic() - c.at < self.REUSE_S:
                    return c
                c.close()
        return None

    def give(self, key: tuple, conn, gen: int | None = None) -> None:
        if conn.broken or (gen is not None and gen != self.gen):
            if not conn.broken:
                conn.close()
            return
        with self.lock:
            conns = self.idle.setdefault(key, [])
            conns.append(conn)
            while len(conns) > 4:
                conns.pop(0).close()

    def drop(self, prefix: tuple | None = None) -> None:
        with self.lock:
            if prefix is None:
                self.gen += 1
            for key in list(self.idle):
                if prefix is None or key[:len(prefix)] == prefix:
                    for c in self.idle.pop(key):
                        c.close()


POOL = Pool()


def request(host: str, port: int, target: Target, identity: Identity, method: str, path_q: str, *,
            body: bytes | None = None, headers: dict | None = None, timeout: float = 30.0,
            to_file: Path | None = None, connect_timeout: float = 2.0, on_routes=None, pool: Pool | None = None,
            carrier: str = "door"):
    """One request through ``target``'s door, reusing an idle session when one is open. ``Unreachable`` (nothing was
    sent) or ``Dropped`` (sent, no whole answer)."""
    pool = pool or POOL
    key = (carrier, host, int(port), target.device_id)
    gen = pool.gen
    conn = pool.take(key)
    if conn is not None:
        try:
            got = call(conn, method, path_q, body=body, headers=headers, timeout=timeout, to_file=to_file)
            pool.give(key, conn, gen)
            return got
        except (Unreachable, Dropped):
            pass              # the idle session had gone stale: a new one, once (a write carries its key: once)
    conn = connect(host, port, target, identity, timeout=connect_timeout, on_routes=on_routes, carrier=carrier)
    got = call(conn, method, path_q, body=body, headers=headers, timeout=timeout, to_file=to_file)
    pool.give(key, conn, gen)
    return got


def pair(host: str, port: int, target: Target, identity: Identity, *, secret: bytes, code: str, name: str,
         timeout: float = 5.0, carrier: str = "door") -> dict:
    """A phone in the same room pairs through the door with what the QR carried (the home's ids and keys, the door's
    address, the one-time secret and the code). Returns the new device's wire (``id``, ``kind``); never a token."""
    conn = connect(host, port, target, identity, timeout=timeout, pair_secret=secret, carrier=carrier)
    try:
        status, _h, body = call(conn, "POST", "/pair", body=json.dumps({"code": code, "name": name}).encode(),
                                headers={"Content-Type": "application/json"}, timeout=timeout)
    finally:
        conn.close()
    if status != 201 or not isinstance(body, dict):
        raise Unreachable("pairing")
    return body["device"]
