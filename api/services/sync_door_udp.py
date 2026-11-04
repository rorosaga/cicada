"""The door over UDP (G132, ruling 51f; owner 2026-11-03: "If we can work on tcp and udp directly probably best to do
udp, no?") — the door's sockets, its sessions and the blocking client, on ``sync_door_channel``'s sealed packets.

**Silence.** A datagram is answered only when it is a hello that proves a paired key (``sync_door.server_open``), and
then with exactly one reply datagram, smaller than the hello, to the address and port it came from. Nothing else ever
gets a byte back: not junk, not an old or replayed hello, not a valid-looking hello under an unknown key, not a packet
for a session that does not exist or does not open. Nothing more is sent to a peer until a packet of its own opens
under the session's key (the "confirm"), so a hello replayed from a forged address never turns the door into an
amplifier. A WireGuard-like port: a scanner cannot tell it from a closed one that answers nothing.

**Sessions follow the device** (WireGuard's roaming). A session is its id, never an address: the door answers at the
address and on the socket its last *authenticated* packet arrived from, so a device that switched Wi-Fi, took a new
port behind a NAT or reached the home at another of its addresses goes on in the same session — nothing re-paired, no
second handshake. A packet that does not open, or one already seen, never moves it. The client tries the target's
other addresses after two probe timeouts and pings at once when this computer's network changes
(:func:`network_changed`), and every :data:`KEEPALIVE_S` while it holds a session open (a watch), so a NAT keeps the
mapping.

Counts and enums only in logs; never an address.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import select
import socket
import time
import weakref
from collections import OrderedDict

from loguru import logger

from api.services import sync_door
from api.services import sync_door_channel as channel

#: A session's unsent and unacknowledged bytes above which a writer waits (``drain``).
SEND_HIGH = 4 * 1024 * 1024
#: A peer that leaves this long without a word while something of ours waits for its ack is gone: eight of its first
#: probe timeouts, never under :data:`SILENT_MIN_S` (a LAN; room for the event loop to be busy a moment) nor over :data:`SILENT_S` (a relayed
#: tailnet path on a slow link).
SILENT_MIN_S = 2.0
SILENT_S = 5.0


def silent_after(ch: channel.Channel) -> float:
    base = (ch.srtt or channel.INITIAL_RTT) + max(4 * ch.rttvar, channel.GRANULARITY) + channel.ACK_DELAY_S
    return min(SILENT_S, max(SILENT_MIN_S, 8 * base))
#: WireGuard's persistent-keepalive interval: under every common NAT's UDP timeout.
KEEPALIVE_S = 25.0
ROTATE_AFTER_PTO = 2
SOCKET_BUFFER = 4 * 1024 * 1024
#: A graceful close waits this long for the peer to acknowledge what it was sent.
LINGER_S = 10.0
#: How long, and for how many, the door remembers a hello's outcome (a resend is answered or dropped from memory).
HELLO_MEMORY_S = 10.0
HELLO_MEMORY = 1024

_EPOCH = [0]
_LIVE: "weakref.WeakSet[UdpConn]" = weakref.WeakSet()


def offer_path(device_id: str, host: str, port: int) -> int:
    """The app found ``device_id``'s door at ``host:port`` (and the handshake proved it): every open session with that
    device moves there now, in the same session — a request in flight, a watch — instead of waiting to notice its old
    path is gone. Returns how many were told."""
    told = 0
    for conn in list(_LIVE):
        if conn.target_id == device_id and not conn.broken:
            conn.new_path = (host, int(port))
            told += 1
    return told


def network_changed() -> None:
    """This computer's network changed (``sync_routes``' fingerprint or the app's word): every open client session
    pings now, so one whose path is gone notices in about a second instead of at its next keepalive."""
    _EPOCH[0] += 1


def tune(sock: socket.socket) -> None:
    """Room for a window of datagrams, and don't-fragment so an oversized probe is lost rather than split."""
    for opt in (socket.SO_RCVBUF, socket.SO_SNDBUF):
        for size in (SOCKET_BUFFER, SOCKET_BUFFER // 4, 256 * 1024):
            try:
                sock.setsockopt(socket.SOL_SOCKET, opt, size)
                break
            except OSError:
                continue
    import sys

    v6 = sock.family == socket.AF_INET6
    with contextlib.suppress(OSError, AttributeError):
        if sys.platform == "darwin":
            sock.setsockopt(socket.IPPROTO_IPV6, 62, 1) if v6 else sock.setsockopt(socket.IPPROTO_IP, 28, 1)
        elif sys.platform.startswith("linux"):     # IP(V6)_MTU_DISCOVER = IP_PMTUDISC_PROBE
            sock.setsockopt(socket.IPPROTO_IPV6, 23, 3) if v6 else sock.setsockopt(socket.IPPROTO_IP, 10, 3)


# --- the door's side ------------------------------------------------------------------------------------------------------

class Endpoint(asyncio.DatagramProtocol):
    """One bound address of the door."""

    def __init__(self, door: "Door", host: str):
        self.door = door
        self.host = host
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:
        self.transport = transport
        sock = transport.get_extra_info("socket")
        if sock is not None:
            tune(sock)

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            self.door.on_datagram(self, data, addr)
        except Exception as exc:  # noqa: BLE001 — one datagram never stops the door
            logger.info(f"door: a datagram was not handled ({type(exc).__name__})")

    def error_received(self, exc) -> None:   # an ICMP error for something we sent: the channel's timers decide
        pass

    def sockets(self) -> list:
        sock = self.transport.get_extra_info("socket") if self.transport is not None else None
        return [sock] if sock is not None else []

    def close(self) -> None:
        if self.transport is not None:
            self.transport.close()


class Door:
    """The UDP half of a ``sync_door.Server``: what each datagram is, and the sessions by id.

    **A hello sent again** (the client resends the same bytes when no reply came) costs nothing twice: the door keeps
    each hello's outcome for :data:`HELLO_MEMORY_S` by its hash. One that failed is dropped again with no crypto and no
    second charge; one that opened a session still waiting for its confirm gets the same reply again — only to the
    address and port the first came from, so the copy of a captured hello sent from anywhere else gets nothing."""

    def __init__(self, server):
        self.server = server
        self.sessions: dict[bytes, UdpLink] = {}
        self.pending = 0
        self.seen: OrderedDict[bytes, tuple] = OrderedDict()

    def _remember(self, digest: bytes, outcome: tuple) -> None:
        now = time.monotonic()
        self.seen[digest] = (now, *outcome)
        while self.seen and (len(self.seen) > HELLO_MEMORY or now - next(iter(self.seen.values()))[0] > HELLO_MEMORY_S):
            self.seen.popitem(last=False)

    async def bind(self, host: str, port: int) -> Endpoint:
        loop = asyncio.get_running_loop()
        _transport, ep = await loop.create_datagram_endpoint(lambda: Endpoint(self, host), local_addr=(host, port))
        return ep

    def on_datagram(self, ep: Endpoint, data: bytes, addr) -> None:
        srv = self.server
        kind = channel.shape(data)
        peer = addr[0]
        if kind == "data":
            link = self.sessions.get(bytes(data[1:1 + channel.SID_LEN]))
            if link is None or not sync_door.allowed_peer(ep.host, peer):
                srv.counts["dropped"] += 1
                return
            link.on_datagram(ep, data, addr)
            return
        if kind != "hello":
            srv.counts["dropped"] += 1          # junk, a reply shape, a truncated packet: nothing back
            return
        if not sync_door.allowed_peer(ep.host, peer):
            srv.counts["refusedPeer"] += 1
            return
        hello = bytes(data[1:])
        digest = hashlib.sha256(hello).digest()
        before = self.seen.get(digest)
        if before is not None and time.monotonic() - before[0] <= HELLO_MEMORY_S:
            _at, link, where = before
            if link is not None and not link.ended and not link.confirmed and where == (ep, addr):
                with contextlib.suppress(OSError):
                    ep.transport.sendto(channel.reply_datagram(link.sid, link.reply), addr)
            else:
                srv.counts["dropped"] += 1
            return
        who = sync_door.bucket_key(peer)
        if (self.pending >= sync_door.MAX_PENDING or srv.sessions >= sync_door.MAX_SESSIONS
                or not srv.buckets.take(who)):
            srv.counts["limited"] += 1
            return
        opened = srv.open_hello(hello)
        if opened is None:
            srv.counts["dropped"] += 1
            srv.buckets.charge(who, sync_door.FAILED_COST - 1)
            self._remember(digest, (None, None))
            return
        device, keys, reply = opened
        sid = channel.session_id(hello)
        link = UdpLink(self, sid, keys, ep, addr, device)
        link.reply = reply
        self.sessions[sid] = link
        self.pending += 1
        self._remember(digest, (link, (ep, addr)))
        with contextlib.suppress(OSError):
            ep.transport.sendto(channel.reply_datagram(sid, reply), addr)

    def close_all(self) -> None:
        for link in list(self.sessions.values()):
            link.abort()


class UdpLink:
    """One session at the door: the framed interface ``sync_door.Server`` runs its protocol on (``read``, ``send``,
    ``drain``, ``close``, ``abort``)."""

    carrier = "udp"

    def __init__(self, door: Door, sid: bytes, keys, ep: Endpoint, addr, device):
        self.door = door
        self.loop = asyncio.get_running_loop()
        self.sid = sid
        self.born = time.monotonic()
        self.ch = channel.Channel(sid, keys.send, keys.recv, now=self.born)
        self.ep, self.addr = ep, addr
        self.device = device
        self.peer_class = sync_door.address_class(addr[0]) or "lan"
        self.confirmed = False
        self.ended = False
        self.reply = b""
        self.closing_at: float | None = None
        self.readable = asyncio.Event()
        self.writable = asyncio.Event()
        self.timer: asyncio.TimerHandle | None = None
        self.timer_at: float | None = None
        self.expire = self.loop.call_later(sync_door.HELLO_TIMEOUT_S, self._unconfirmed)

    # -- datagrams in ----------------------------------------------------------------------------------------------
    def on_datagram(self, ep: Endpoint, data: bytes, addr) -> None:
        if self.ended:
            return
        now = time.monotonic()
        if not self.ch.receive(data, now):
            self.door.server.counts["dropped"] += 1
            return
        if (ep, addr) != (self.ep, self.addr):
            # The device moved (another network, a new NAT port, another of the home's addresses): follow its proven
            # packets, never an unproven one.
            self.ep, self.addr = ep, addr
            self.peer_class = sync_door.address_class(addr[0]) or self.peer_class
            self.door.server.counts["roamed"] += 1
            self.ch.path_changed()
        if not self.confirmed:
            self.confirmed = True
            self.expire.cancel()
            self.door.pending -= 1
            self.ch._rtt_sample(max(now - self.born, 1e-6))     # noqa: SLF001 — the handshake's round trip
            self.door.server.spawn(self)
        self.readable.set()
        if self.ch.backlog() <= SEND_HIGH:
            self.writable.set()
        if self.ch.peer_closed:
            self._end()
            return
        if self.closing_at is not None and self.ch.backlog() == 0:
            self.abort()
            return
        self.flush()

    def _unconfirmed(self) -> None:
        if not self.confirmed:
            self._end()

    # -- datagrams out ---------------------------------------------------------------------------------------------
    def flush(self) -> None:
        if self.ended:
            return
        now = time.monotonic()
        transport = self.ep.transport
        for pkt in self.ch.poll(now):
            with contextlib.suppress(OSError):
                transport.sendto(pkt, self.addr)
        self._arm(now)

    def _arm(self, now: float) -> None:
        due = self.ch.timeout(now)
        idle = self.ch.last_recv + sync_door.IDLE_S
        due = idle if due is None else min(due, idle)
        if self.timer is not None and self.timer_at is not None and self.timer_at <= due:
            return
        if self.timer is not None:
            self.timer.cancel()
        self.timer_at = due
        self.timer = self.loop.call_later(max(0.0, due - now), self._fire)

    def _fire(self) -> None:
        self.timer = self.timer_at = None
        if self.ended:
            return
        now = time.monotonic()
        if now - self.ch.last_recv >= sync_door.IDLE_S or (
                self.closing_at is not None and now - self.closing_at >= LINGER_S):
            self.abort()
            return
        self.ch.on_timeout(now)
        self.flush()

    # -- the framed interface --------------------------------------------------------------------------------------
    async def read(self, timeout: float) -> tuple[bytes, bytes]:
        deadline = self.loop.time() + timeout
        while True:
            if self.ended:
                raise ConnectionError("closed")
            got = self.ch.next_frame()
            if got is not None:
                if self.ch.ack_now:
                    self.flush()
                return got
            if self.ch.peer_closed:
                raise ConnectionError("closed")
            self.readable.clear()
            left = deadline - self.loop.time()
            if left <= 0:
                raise asyncio.TimeoutError()
            await asyncio.wait_for(self.readable.wait(), left)

    def send(self, kind: bytes, data: bytes = b"") -> None:
        if self.ended or self.closing_at is not None:
            raise ConnectionError("closed")
        self.ch.write(channel.frame(kind, data))
        self.flush()

    async def drain(self) -> None:
        while self.ch.backlog() > SEND_HIGH:
            if self.ended:
                raise ConnectionError("closed")
            self.writable.clear()
            await asyncio.wait_for(self.writable.wait(), sync_door.IDLE_S)

    def close(self) -> None:
        """Gracefully: what was sent is acknowledged first (or :data:`LINGER_S` passes), then a close."""
        if self.ended or self.closing_at is not None:
            return
        if self.ch.backlog() == 0:
            self.abort()
            return
        self.closing_at = time.monotonic()
        self.flush()

    def abort(self) -> None:
        """At once, with a close the device hears (its session's own key): a revoke, the door stopping."""
        if self.ended:
            return
        self.ch.close()
        if self.confirmed:
            self.flush()
        self._end()

    def _end(self) -> None:
        if self.ended:
            return
        self.ended = True
        if self.timer is not None:
            self.timer.cancel()
        self.expire.cancel()
        if self.door.sessions.get(self.sid) is self:
            del self.door.sessions[self.sid]
        if not self.confirmed:
            self.door.pending -= 1
        self.readable.set()
        self.writable.set()


# --- the client (blocking) --------------------------------------------------------------------------------------------------

def _resolve(host: str, port: int):
    try:
        info = socket.getaddrinfo(host, int(port), type=socket.SOCK_DGRAM, flags=socket.AI_NUMERICHOST)[0]
    except (OSError, ValueError) as exc:
        raise sync_door.Unreachable("connect") from exc
    return info[0], info[4]


class UdpConn:
    """A client session; the same interface as ``sync_door.Conn`` (``send``, ``recv``, ``settimeout``, ``close``),
    driven in the caller's thread — no thread of its own."""

    carrier = "door"

    def __init__(self, sock: socket.socket, ch: channel.Channel, addr, paths: list):
        self.sock = sock
        self.ch = ch
        self.addr = addr
        self.paths = paths
        self.path_i = 0
        self.rotated_at_pto = 0
        self.routes: dict | None = None
        self.at = time.monotonic()
        self.broken = False
        self.timeout = 30.0
        self.stop = None
        self.epoch = _EPOCH[0]
        self.keepalive = False
        self.send_failed = False
        self.target_id = ""
        self.new_path: tuple | None = None
        self.path_since = time.monotonic()

    def settimeout(self, t: float) -> None:
        self.timeout = float(t)

    def send(self, kind: bytes, data: bytes = b"") -> None:
        if self.broken:
            raise ConnectionError("closed")
        self.ch.write(channel.frame(kind, data))
        deadline = time.monotonic() + self.timeout
        self._flush()
        while self.ch.backlog() > SEND_HIGH:
            self._step(deadline)

    def recv(self) -> tuple[bytes, bytes]:
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                got = self.ch.next_frame()
            except ValueError as exc:
                self.close()
                raise ConnectionError("frame") from exc
            if got is not None:
                if self.ch.ack_now:
                    self._flush()
                return got
            if self.ch.peer_closed:
                self.broken = True
                raise ConnectionError("closed")
            self._step(deadline)

    def _step(self, deadline: float) -> None:
        now = time.monotonic()
        if self.broken:
            raise ConnectionError("closed")
        if now >= deadline:
            raise socket.timeout("timed out")
        if self.stop is not None and self.stop.is_set():
            raise ConnectionError("stopped")
        if _EPOCH[0] != self.epoch or self.send_failed:
            self.epoch, self.send_failed = _EPOCH[0], False
            self._reconnect(self.addr)           # a new network: this computer's new source address
            self.ch.ping()                       # and is the path still there?
        if self.new_path is not None:
            self._move(self.new_path)
        if self.keepalive and now - self.ch.last_send >= KEEPALIVE_S:
            self.ch.ping()
        if (self.ch.eliciting_out > 0 and self.ch.silent_for(now) > silent_after(self.ch)
                and now - self.path_since > silent_after(self.ch)):
            self.broken = True
            raise ConnectionError("silent")
        self._flush()
        due = self.ch.timeout(now)
        # A request waiting on its answer looks up often, so a new path offered from another thread is taken at once;
        # an idle watch, once a second.
        fast = self.ch.eliciting_out > 0 or not self.keepalive
        until = min(deadline, now + (0.25 if fast else 1.0), due if due is not None else deadline)
        if self.keepalive:
            until = min(until, self.ch.last_send + KEEPALIVE_S)
        try:
            ready = select.select([self.sock], [], [], max(0.0, until - now))[0]
        except (OSError, ValueError) as exc:          # closed from another thread
            self.broken = True
            raise ConnectionError("closed") from exc
        if ready:
            self._take()
        now = time.monotonic()
        due = self.ch.timeout(now)
        if due is not None and now >= due:
            self.ch.on_timeout(now)
        if (len(self.paths) > 1 and self.ch.pto_count >= ROTATE_AFTER_PTO
                and self.ch.pto_count != self.rotated_at_pto):
            self._rotate()
        self._flush()

    def _move(self, path: tuple) -> None:
        """Go on at ``path`` in this same session: the door follows the next packet that opens."""
        self.new_path = None
        if path not in self.paths:
            self.paths.append(path)
        self.path_i = self.paths.index(path)
        try:
            _family, addr = _resolve(*path)
        except sync_door.Unreachable:
            return
        self._reconnect(addr)
        self.path_since = time.monotonic()
        self.rotated_at_pto = 0
        self.ch.path_changed()                 # what waits goes again now, at the first timeout's pace
        self.ch.ping()

    def _rotate(self) -> None:
        """Try the target's next address in the same session (the door follows a proven packet)."""
        self.rotated_at_pto = self.ch.pto_count
        self.path_i = (self.path_i + 1) % len(self.paths)
        host, port = self.paths[self.path_i]
        try:
            _family, addr = _resolve(host, port)
        except sync_door.Unreachable:
            return
        self._reconnect(addr)
        self.ch.ping()

    def _reconnect(self, addr) -> None:
        """Point the socket at ``addr`` again, which also picks this computer's current source address (a network
        change); a new socket when the old one cannot (another family). The door follows either."""
        family = socket.AF_INET6 if len(addr) == 4 else socket.AF_INET
        if family == self.sock.family:
            try:
                self.sock.connect(addr)
                self.addr = addr
                return
            except OSError:
                pass
        try:
            sock = socket.socket(family, socket.SOCK_DGRAM)
            sock.setblocking(False)
            tune(sock)
            sock.connect(addr)
        except OSError:
            return
        with contextlib.suppress(OSError):
            self.sock.close()
        self.sock, self.addr = sock, addr

    def _take(self) -> None:
        while True:
            try:
                data = self.sock.recv(channel.MAX_DGRAM + 1)
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                return                 # an ICMP error mid-session: the timers decide, never a forged packet
            self.ch.receive(data, time.monotonic())

    def _flush(self) -> None:
        for pkt in self.ch.poll(time.monotonic()):
            try:
                self.sock.send(pkt)
            except (BlockingIOError, InterruptedError):
                pass                    # the buffer is full: the channel sends it again
            except OSError:
                self.send_failed = True     # the source address went away, or an oversized probe: see next step

    def close(self) -> None:
        if not self.broken:
            with contextlib.suppress(Exception):
                self.ch.close()
                self._flush()
        self.broken = True
        with contextlib.suppress(OSError):
            self.sock.close()


def connect(host: str, port: int, target, identity, *, timeout: float = 2.0, on_routes=None,
            pair_secret: bytes | None = None, paths: list | None = None) -> UdpConn:
    """A session with ``target``'s door at ``host:port`` over UDP: ``Unreachable`` when nothing answered as that
    device within ``timeout``. A lost hello (or its lost reply) is sent again — the same bytes while the door may still
    hold that session (it answers a resend from memory, never as a second session), a fresh hello after that."""
    import json

    family, addr = _resolve(host, port)
    sock = socket.socket(family, socket.SOCK_DGRAM)
    try:
        sock.setblocking(False)
        tune(sock)
        sock.connect(addr)              # only the door's address is heard, and a closed port says so at once
    except OSError as exc:
        sock.close()
        raise sync_door.Unreachable("connect") from exc
    started = time.monotonic()
    deadline = started + timeout
    resend_at, gap = started, min(0.25, max(0.05, timeout / 4))
    # The same hello is resent while the door may still hold its unconfirmed session; past that, a fresh one (the
    # door's replay check would drop the old bytes, and its memory of them has lapsed).
    fresh_after = 0.6 * sync_door.HELLO_TIMEOUT_S
    keys = None
    states: dict[bytes, tuple] = {}
    hello = made_at = None
    try:
        while keys is None:
            now = time.monotonic()
            if now >= deadline:
                raise sync_door.Unreachable("timeout")
            if now >= resend_at:
                if hello is None or now - made_at > fresh_after:
                    hello, state = sync_door.client_hello(identity, target.door_pub, pair_secret=pair_secret)
                    made_at = now
                    states[channel.session_id(hello)] = [state, now]
                states[channel.session_id(hello)][1] = now
                try:
                    sock.send(channel.hello_datagram(hello))
                except (BlockingIOError, InterruptedError):
                    pass
                except OSError as exc:
                    raise sync_door.Unreachable("connect") from exc
                resend_at, gap = now + gap, gap * 2
            if not select.select([sock], [], [], max(0.0, min(deadline, resend_at) - now))[0]:
                continue
            try:
                data = sock.recv(4096)
            except (BlockingIOError, InterruptedError):
                continue
            except ConnectionRefusedError as exc:
                raise sync_door.Unreachable("refused") from exc
            except OSError:
                continue
            if channel.shape(data) != "reply":
                continue
            sid = bytes(data[1:1 + channel.SID_LEN])
            got = states.get(sid)
            if got is None:
                continue
            state, sent_at = got
            try:
                keys = sync_door.client_finish(state, bytes(data[1 + channel.SID_LEN:]), target.jwk)
            except sync_door.Unreachable as exc:
                if str(exc) == "not_the_device":
                    raise
                continue                   # a reply that does not open: not the door's; keep listening
        now = time.monotonic()
        ch = channel.Channel(sid, keys.send, keys.recv, now=now, rtt=max(now - sent_at, 1e-6))
        ch.ping()                          # the confirm: the door sends nothing more until a packet of ours opens
        conn = UdpConn(sock, ch, addr, [(host, int(port))] + [p for p in (paths or []) if p != (host, int(port))])
        conn.target_id = target.device_id
        _LIVE.add(conn)
        conn.settimeout(max(0.2, deadline - now) + 2.0)
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
    except sync_door.Unreachable:
        sock.close()
        raise
    except Exception as exc:  # noqa: BLE001 — a handshake that did not finish
        sock.close()
        raise sync_door.Unreachable("handshake") from exc
