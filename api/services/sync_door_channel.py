"""The door's datagram channel: sealed UDP packets carrying one reliable, ordered byte stream (G132, ruling 51f;
owner 2026-11-03: "If we can work on tcp and udp directly probably best to do udp, no?").

Pure (sans-IO): it is fed datagrams and the time and hands back datagrams to send, so it is tested — losses, reorder,
duplication, a stalled reader — without a socket. ``sync_door_udp`` drives it from the door's asyncio loop and from
the blocking client.

**Datagrams.** Three shapes, each told apart by its first byte *and* its exact length or minimum, so anything else is
dropped before a byte of it is parsed:

* ``0x01 ‖ hello`` (:data:`HELLO_DGRAM` bytes) — ``sync_door``'s hello, unchanged;
* ``0x02 ‖ sid ‖ reply`` (:data:`REPLY_DGRAM`) — the door's answer; ``sid = sha256(domain ‖ hello)[:8]``, so the
  session's id is fixed by the hello and a reply cannot be pinned to another;
* ``0x03 ‖ sid ‖ pn ‖ ChaCha20-Poly1305(key, nonce = pn, aad = the 17-byte header)`` — everything after the handshake.
  ``pn`` is a 64-bit packet number, never reused under a key (one key per direction); a packet number already seen or
  more than :data:`REPLAY_WINDOW` behind the highest is dropped *before* the AEAD is tried (WireGuard's sliding
  window), and one that does not open is dropped after.

**Inside a packet** (authenticated, so a malformed one is a peer's bug, never a stranger's input): chunks — ``PING``,
``ACK`` (up to :data:`ACK_RANGES` ranges of packet numbers, the receive window, the ack delay), ``DATA`` (a stream
offset and bytes), ``CLOSE`` and ``PAD``. A retransmission carries the same stream bytes at the same offset in a new
packet with a new number (QUIC's way), so a packet number never means two things.

**Reliability and pacing** follow RFC 9002 in small: RTT from acks (seeded by the handshake), a packet lost when three
later ones are acked or after 9/8 RTT, a probe timeout (PTO) that backs off, Reno congestion control with a 0.7
decrease (CUBIC's β, so one Wi-Fi loss does not halve a transfer), sends paced at 1.25 × cwnd / RTT in bursts of about
:data:`PACE_TICK_S`, and a receive window (:data:`RECV_WINDOW`) the reader opens as it reads. Datagrams start at
:data:`BASE_DGRAM` bytes (QUIC's floor, under a tailnet's 1,280 MTU) and one padded probe tries :data:`PROBE_DGRAM`
(a 1,500-byte Ethernet or Wi-Fi path) with don't-fragment set, once a session has sent :data:`PROBE_AFTER_BYTES`;
acked, the channel uses it.
"""
from __future__ import annotations

import bisect
import hashlib
import struct
from collections import OrderedDict, deque

from api.services import sync_door

HELLO_T = 0x01
REPLY_T = 0x02
DATA_T = 0x03
SID_DOMAIN = b"cicada-door-sid-v1\x00"
SID_LEN = 8
HEADER = 1 + SID_LEN + 8
OVERHEAD = HEADER + sync_door.TAG
HELLO_DGRAM = 1 + sync_door.HELLO_LEN
REPLY_DGRAM = 1 + SID_LEN + sync_door.REPLY_LEN
MIN_DATA_DGRAM = OVERHEAD + 1
BASE_DGRAM = 1200
PROBE_DGRAM = 1452
MAX_DGRAM = 2048            # nothing larger is ever read as a packet

C_PAD, C_PING, C_ACK, C_DATA, C_CLOSE = 0, 1, 2, 3, 4
DATA_HEAD = 1 + 8 + 2
ACK_RANGES = 16
RECV_RANGES = 32

REPLAY_WINDOW = 8192
INITIAL_RTT = 0.1
GRANULARITY = 0.001
ACK_DELAY_S = 0.005
ACK_EVERY = 4
PACKET_THRESHOLD = 3
TIME_THRESHOLD = 9 / 8
BETA = 0.7
INIT_CWND_PACKETS = 10
MAX_CWND = 16 * 1024 * 1024
RECV_WINDOW = 8 * 1024 * 1024
PACE_TICK_S = 0.002
PROBE_TRIES = 3
#: Only a session that is moving bulk (a pack, a first copy) probes: a few control frames never pay for a padded probe.
PROBE_AFTER_BYTES = 64 * 1024
PROBE_RETRY_S = 1.0
#: Frames inside the stream: ``u32 length ‖ kind ‖ data`` — the length bounded like the TCP door's.
MAX_FRAME_PLAIN = sync_door.MAX_FRAME + 1


def session_id(hello: bytes) -> bytes:
    return hashlib.sha256(SID_DOMAIN + bytes(hello)).digest()[:SID_LEN]


def hello_datagram(hello: bytes) -> bytes:
    return bytes([HELLO_T]) + bytes(hello)


def reply_datagram(sid: bytes, reply: bytes) -> bytes:
    return bytes([REPLY_T]) + sid + bytes(reply)


def shape(data: bytes) -> str | None:
    """``hello``, ``reply``, ``data`` — or None for anything else (dropped unread)."""
    if not data:
        return None
    t, n = data[0], len(data)
    if t == HELLO_T and n == HELLO_DGRAM:
        return "hello"
    if t == REPLY_T and n == REPLY_DGRAM:
        return "reply"
    if t == DATA_T and MIN_DATA_DGRAM <= n <= MAX_DGRAM:
        return "data"
    return None


def frame(kind: bytes, data: bytes = b"") -> bytes:
    return struct.pack(">I", 1 + len(data)) + kind + data


class ReplayWindow:
    """The highest packet number seen and a bitmap of the :data:`REPLAY_WINDOW` below it (RFC 6479's idea)."""

    def __init__(self, size: int = REPLAY_WINDOW):
        self.size = size
        self.top = -1
        self.bits = 0

    def fresh(self, pn: int) -> bool:
        if pn > self.top:
            return True
        if self.top - pn >= self.size:
            return False
        return not (self.bits >> (self.top - pn)) & 1

    def mark(self, pn: int) -> None:
        if pn > self.top:
            shift = pn - self.top
            self.bits = ((self.bits << shift) | 1) & ((1 << self.size) - 1) if shift < self.size else 1
            self.top = pn
        else:
            self.bits |= 1 << (self.top - pn)


class _Sent:
    __slots__ = ("time", "size", "offs", "eliciting", "probe")

    def __init__(self, time, size, offs, eliciting, probe):
        self.time, self.size, self.offs, self.eliciting, self.probe = time, size, offs, eliciting, probe


class Channel:
    """One session's two directions. ``write`` stream bytes, ``receive`` datagrams, ``poll`` for datagrams to send,
    ``timeout``/``on_timeout`` for the timers, ``next_frame`` for what arrived."""

    def __init__(self, sid: bytes, send_key: bytes, recv_key: bytes, *, now: float, rtt: float | None = None):
        self.sid = bytes(sid)
        self.tx = sync_door._aead(send_key)      # noqa: SLF001
        self.rx = sync_door._aead(recv_key)      # noqa: SLF001
        self.pn = 0
        self.window = ReplayWindow()
        # sending
        self.mss = BASE_DGRAM
        self.pending = bytearray()
        self.pending_off = 0
        self.unacked: dict[int, bytes] = {}
        self.unacked_bytes = 0
        self.retx: deque[int] = deque()
        self.peer_max = RECV_WINDOW
        self.sent: OrderedDict[int, _Sent] = OrderedDict()
        self.inflight = 0
        self.eliciting_out = 0
        self.last_eliciting: float | None = None
        self.largest_acked = -1
        self.loss_time: float | None = None
        self.pto_count = 0
        self.probes_owed = 0
        self.ping_owed = False
        self.cwnd = INIT_CWND_PACKETS * BASE_DGRAM
        self.ssthresh = float("inf")
        self.recovery_pn = -1
        self.tokens = float(self.cwnd)
        self.pace_at = now
        self.srtt: float | None = None
        self.rttvar = 0.0
        self.latest_rtt = 0.0
        if rtt is not None and rtt > 0:
            self._rtt_sample(rtt)
        self.probe_state = "idle"          # idle | out | done
        self.probe_tries = 0
        self.probe_after = now
        self.closing = False
        self.close_sent = False
        # receiving
        self.recv_off = 0
        self.segments: dict[int, bytes] = {}
        self.starts: list[int] = []                # the held pieces' offsets, sorted (none overlap)
        self.segment_bytes = 0
        self.readable = bytearray()
        self.consumed = 0
        self.advertised = RECV_WINDOW
        self.ranges: list[list[int]] = []          # [hi, lo], highest first
        self.largest_recv_at: float | None = None
        self.ack_dirty = False
        self.ack_now = False
        self.ack_deadline: float | None = None
        self.eliciting_unacked = 0
        self.last_recv = now
        self.last_send = now
        self.peer_closed = False
        self.counts = {"sent": 0, "received": 0, "lost": 0, "retransmitted": 0, "dropped": 0}

    # -- the stream ------------------------------------------------------------------------------------------------
    def write(self, data: bytes) -> None:
        if self.closing:
            raise ConnectionError("closed")
        self.pending += data

    def backlog(self) -> int:
        """Bytes written and not yet acknowledged."""
        return len(self.pending) + self.unacked_bytes

    def idle(self) -> bool:
        return not self.pending and not self.unacked and not self.retx

    def next_frame(self) -> tuple[bytes, bytes] | None:
        buf = self.readable
        if len(buf) < 4:
            return None
        n = struct.unpack(">I", buf[:4])[0]
        if not 1 <= n <= MAX_FRAME_PLAIN:
            raise ValueError("frame")
        if len(buf) < 4 + n:
            return None
        kind, data = bytes(buf[4:5]), bytes(buf[5:4 + n])
        del buf[:4 + n]
        self.consumed += 4 + n
        if self.consumed + RECV_WINDOW - self.advertised >= RECV_WINDOW // 4:
            self.ack_now = True          # the reader made room: say so
        return kind, data

    def ping(self) -> None:
        self.ping_owed = True

    def close(self) -> None:
        self.closing = True

    # -- receiving -------------------------------------------------------------------------------------------------
    def receive(self, data: bytes, now: float) -> bool:
        """True when ``data`` is a fresh, authentic packet of this session (then it was acted on)."""
        if shape(data) != "data" or data[1:1 + SID_LEN] != self.sid:
            return False
        header = bytes(data[:HEADER])
        pn = struct.unpack(">Q", header[1 + SID_LEN:])[0]
        if not self.window.fresh(pn):
            self.counts["dropped"] += 1
            return False
        try:
            plain = self.rx.decrypt(b"\0\0\0\0" + header[1 + SID_LEN:], bytes(data[HEADER:]), header)
        except Exception:  # noqa: BLE001 — not this session's, or altered
            self.counts["dropped"] += 1
            return False
        self.window.mark(pn)
        self.last_recv = now
        self.counts["received"] += 1
        try:
            eliciting = self._chunks(plain, now)
        except (struct.error, ValueError, IndexError):
            return True             # authentic but malformed: the peer's bug; nothing of it is used
        in_order = not self.ranges or pn == self.ranges[0][0] + 1
        if not self.ranges or pn > self.ranges[0][0]:
            self.largest_recv_at = now
        self._note_pn(pn)
        if eliciting:
            self.ack_dirty = True
            self.eliciting_unacked += 1
            if not in_order or self.eliciting_unacked >= ACK_EVERY:
                self.ack_now = True
            elif self.ack_deadline is None:
                self.ack_deadline = now + ACK_DELAY_S
        return True

    def _note_pn(self, pn: int) -> None:
        r = self.ranges
        for i, (hi, lo) in enumerate(r):
            if lo <= pn <= hi:
                return
            if pn == hi + 1:
                r[i][0] = pn
                return
            if pn == lo - 1:
                r[i][1] = pn
                if i + 1 < len(r) and r[i + 1][0] == pn - 1:
                    r[i][1] = r[i + 1][1]
                    del r[i + 1]
                return
            if pn > hi:
                r.insert(i, [pn, pn])
                break
        else:
            r.append([pn, pn])
        del r[RECV_RANGES:]

    def _chunks(self, plain: bytes, now: float) -> bool:
        i, n, eliciting = 0, len(plain), False
        acks = None
        while i < n:
            c = plain[i]
            i += 1
            if c == C_PAD:
                break
            if c == C_PING:
                eliciting = True
                self.ack_now = True
            elif c == C_ACK:
                count = plain[i]
                i += 1
                if not 1 <= count <= ACK_RANGES:
                    raise ValueError("ack")
                ranges = [struct.unpack(">QQ", plain[i + 16 * k:i + 16 * k + 16]) for k in range(count)]
                i += 16 * count
                max_data, delay_us = struct.unpack(">QI", plain[i:i + 12])
                i += 12
                acks = (ranges, max_data, delay_us)
            elif c == C_DATA:
                off, ln = struct.unpack(">QH", plain[i:i + 10])
                i += 10
                piece = plain[i:i + ln]
                if len(piece) != ln:
                    raise ValueError("data")
                i += ln
                eliciting = True
                self._data(off, piece)
            elif c == C_CLOSE:
                self.peer_closed = True
            else:
                raise ValueError("chunk")
        if acks is not None:
            self._on_ack(*acks, now)
        return eliciting

    def _data(self, off: int, piece: bytes) -> None:
        """One stream piece. **Held memory is bounded by the window** (security review of #590): a piece ahead of
        what was read is kept only if it overlaps no piece already held and the held bytes stay within
        :data:`RECV_WINDOW`; anything else is dropped (its sender's retransmission brings it again). Our own sender
        never overlaps — a retransmission carries the same bytes at the same offset — so only a misbehaving peer is
        refused. Disjoint pieces inside ``[recv_off, advertised)`` cannot exceed the window anyway; the byte check is
        the second wall."""
        end = off + len(piece)
        if end <= self.recv_off:
            return                                          # already had it
        if end > self.advertised:
            return                                          # beyond the window we offered: never kept
        if off < self.recv_off:
            piece, off = piece[self.recv_off - off:], self.recv_off
        if off > self.recv_off:
            if self.segment_bytes + len(piece) > RECV_WINDOW or self._overlaps(off, off + len(piece)):
                self.counts["dropped"] += 1
                return
            bisect.insort(self.starts, off)
            self.segments[off] = piece
            self.segment_bytes += len(piece)
            return
        self.readable += piece
        self.recv_off += len(piece)
        self._drain()

    def _overlaps(self, start: int, end: int) -> bool:
        i = bisect.bisect_left(self.starts, start)
        if i < len(self.starts) and self.starts[i] < end:
            return True                                     # a held piece begins inside this one
        if i > 0:
            prev = self.starts[i - 1]
            return prev + len(self.segments[prev]) > start  # the one before reaches into it
        return False

    def _drain(self) -> None:
        """Move every held piece the stream has reached into ``readable``: one starting at or behind ``recv_off`` is
        taken off the list either way — its part already read is cut, its rest appended — so nothing is left behind
        the read point."""
        while self.starts and self.starts[0] <= self.recv_off:
            start = self.starts.pop(0)
            seg = self.segments.pop(start)
            self.segment_bytes -= len(seg)
            if start + len(seg) > self.recv_off:
                tail = seg[self.recv_off - start:]
                self.readable += tail
                self.recv_off += len(tail)

    def _rtt_sample(self, rtt: float) -> None:
        self.latest_rtt = rtt
        if self.srtt is None:
            self.srtt, self.rttvar = rtt, rtt / 2
        else:
            self.rttvar = 0.75 * self.rttvar + 0.25 * abs(self.srtt - rtt)
            self.srtt = 0.875 * self.srtt + 0.125 * rtt

    def _on_ack(self, ranges, max_data: int, delay_us: int, now: float) -> None:
        self.peer_max = max(self.peer_max, max_data)
        largest = ranges[0][0]
        if largest >= self.pn:
            return                       # acks a packet never sent: ignored
        newly = []
        for hi, lo in ranges:
            if not self.sent:
                break
            hi = min(hi, self.pn - 1)          # a malformed range never walks past what was sent
            first = next(iter(self.sent))
            if hi < first or lo > hi:
                continue
            for p in range(max(lo, first), hi + 1):
                s = self.sent.pop(p, None)
                if s is not None:
                    newly.append((p, s))
        if not newly:
            return
        top_pn, top = max(newly, key=lambda x: x[0])
        if top_pn == largest and top.eliciting:
            sample = now - top.time
            delay = min(delay_us / 1e6, ACK_DELAY_S)
            if self.srtt is not None and sample - delay >= GRANULARITY:
                sample -= delay
            self._rtt_sample(max(sample, 1e-6))
        self.largest_acked = max(self.largest_acked, largest)
        for p, s in newly:
            self.inflight -= s.size
            if s.eliciting:
                self.eliciting_out -= 1
            for off in s.offs:
                chunk = self.unacked.pop(off, None)
                if chunk is not None:
                    self.unacked_bytes -= len(chunk)
            if s.probe:
                self.mss = max(self.mss, s.size)
                self.probe_state = "done"
            elif p > self.recovery_pn:
                if self.cwnd < self.ssthresh:
                    self.cwnd += s.size
                else:
                    self.cwnd += self.mss * s.size / self.cwnd
                self.cwnd = min(self.cwnd, MAX_CWND)
        self.pto_count = 0
        self._detect_loss(now)

    def _loss_delay(self) -> float:
        base = max(self.srtt or INITIAL_RTT, self.latest_rtt)
        return max(TIME_THRESHOLD * base, GRANULARITY)

    def _detect_loss(self, now: float) -> None:
        self.loss_time = None
        if self.largest_acked < 0:
            return
        delay = self._loss_delay()
        lost = []
        for p, s in self.sent.items():
            if p > self.largest_acked:
                break
            if self.largest_acked - p >= PACKET_THRESHOLD or s.time + delay <= now:   # the timer's own sum
                lost.append(p)
            else:
                self.loss_time = s.time + delay
                break
        congested = False
        for p in lost:
            s = self.sent.pop(p)
            self.inflight -= s.size
            if s.eliciting:
                self.eliciting_out -= 1
            if s.probe:
                self.probe_state = "idle"
                self.probe_after = now + PROBE_RETRY_S
                continue
            self.counts["lost"] += 1
            for off in s.offs:
                if off in self.unacked:
                    self.retx.append(off)
            if p > self.recovery_pn:
                congested = True
        if congested:
            self.recovery_pn = self.pn - 1
            self.cwnd = max(self.cwnd * BETA, 2 * self.mss)
            self.ssthresh = self.cwnd

    # -- timers ----------------------------------------------------------------------------------------------------
    def pto_s(self) -> float:
        srtt = self.srtt if self.srtt is not None else INITIAL_RTT
        rttvar = self.rttvar if self.srtt is not None else INITIAL_RTT / 2
        return (srtt + max(4 * rttvar, GRANULARITY) + ACK_DELAY_S) * (2 ** min(self.pto_count, 8))

    def _pto_deadline(self) -> float | None:
        if self.eliciting_out <= 0 or self.last_eliciting is None:
            return None
        return self.last_eliciting + self.pto_s()

    def _pace_wait(self, now: float, size: int) -> float:
        self._refill(now)
        if self.tokens + 1.0 >= size:          # a byte's tolerance: float dust never stalls a send
            return 0.0
        return (size - self.tokens) / self._rate()

    def _rate(self) -> float:
        return 1.25 * self.cwnd / max(self.srtt or INITIAL_RTT, 1e-5)

    def _refill(self, now: float) -> None:
        if self.srtt is None:
            self.tokens = float(self.cwnd)
            self.pace_at = now
            return
        rate = self._rate()
        burst = max(INIT_CWND_PACKETS * self.mss, min(self.cwnd, rate * PACE_TICK_S))
        self.tokens = min(burst, self.tokens + (now - self.pace_at) * rate)
        self.pace_at = now

    def _wants_data(self) -> bool:
        while self.retx and self.retx[0] not in self.unacked:
            self.retx.popleft()                 # acked since it was queued again
        if self.retx:
            return True
        return bool(self.pending) and self.pending_off < self.peer_max

    def timeout(self, now: float) -> float | None:
        """When :meth:`on_timeout` must next run (absolute, the same clock as ``now``), or None."""
        if self.ack_now or self.ping_owed or self.probes_owed or (self.closing and not self.close_sent):
            return now
        due = [t for t in (self.loss_time, self._pto_deadline(), self.ack_deadline) if t is not None]
        if self._wants_data() and self.inflight + self.mss <= self.cwnd:
            due.append(now + self._pace_wait(now, self.mss))
        return min(due) if due else None

    def on_timeout(self, now: float) -> None:
        if self.loss_time is not None and now >= self.loss_time:
            self._detect_loss(now)
            return
        pto = self._pto_deadline()
        if pto is not None and now >= pto:
            self.pto_count += 1
            self.probes_owed = 2
            oldest = next(iter(self.unacked), None)
            if oldest is not None:
                self.retx.appendleft(oldest)
        if self.ack_deadline is not None and now >= self.ack_deadline:
            self.ack_now = True

    def path_changed(self) -> None:
        """The peer is somewhere else now (its proven packet came from another address): what waits for an ack is
        sent again at once, and the timers start over instead of at a backed-off pace (QUIC's migration, in small)."""
        self.pto_count = 0
        oldest = next(iter(self.unacked), None)
        if oldest is not None:
            self.retx.appendleft(oldest)
            self.probes_owed = max(self.probes_owed, 1)

    def silent_for(self, now: float) -> float:
        return now - self.last_recv

    # -- sending ---------------------------------------------------------------------------------------------------
    def poll(self, now: float) -> list[bytes]:
        """Every datagram this session may send now."""
        out: list[bytes] = []
        while self.probes_owed > 0:
            self.probes_owed -= 1
            out.append(self._packet(now, ping=not self._wants_data(), data=True))
        while self._wants_data() and self.inflight + self.mss <= self.cwnd and self._pace_wait(now, self.mss) == 0:
            pkt = self._packet(now, data=True)
            if pkt is None:
                break
            out.append(pkt)
        if (self.probe_state == "idle" and self.mss < PROBE_DGRAM and self.srtt is not None
                and self.pending_off >= PROBE_AFTER_BYTES
                and self.probe_tries < PROBE_TRIES and now >= self.probe_after
                and self.inflight + PROBE_DGRAM <= self.cwnd):
            self.probe_tries += 1
            self.probe_state = "out"
            out.append(self._packet(now, ping=True, size=PROBE_DGRAM))
        if self.ping_owed:
            out.append(self._packet(now, ping=True))
        if self.closing and not self.close_sent:
            self.close_sent = True
            out.append(self._packet(now, close=True))
        if self.ranges and (self.ack_now or (self.ack_dirty and self.ack_deadline is not None
                                             and now >= self.ack_deadline)):
            out.append(self._packet(now))
        self.last_send = now if out else self.last_send
        return out

    def _ack_chunk(self, now: float) -> bytes:
        ranges = self.ranges[:ACK_RANGES]
        self.advertised = self.consumed + RECV_WINDOW
        body = bytes([C_ACK, len(ranges)]) + b"".join(struct.pack(">QQ", hi, lo) for hi, lo in ranges)
        self.ack_dirty = self.ack_now = False
        self.ack_deadline = None
        self.eliciting_unacked = 0
        delay = max(0.0, now - self.largest_recv_at) if self.largest_recv_at is not None else 0.0
        return body + struct.pack(">QI", self.advertised, min(int(delay * 1e6), 0xFFFFFFFF))

    def _packet(self, now: float, *, data: bool = False, ping: bool = False, close: bool = False,
                size: int | None = None) -> bytes | None:
        limit = (size or self.mss) - OVERHEAD
        parts: list[bytes] = []
        used = 0
        if self.ranges and (self.ack_dirty or self.ack_now):
            a = self._ack_chunk(now)
            parts.append(a)
            used += len(a)
        if ping:
            parts.append(bytes([C_PING]))
            used += 1
            self.ping_owed = False
        if close:
            parts.append(bytes([C_CLOSE]))
            used += 1
        offs: list[int] = []
        if data:
            while self.retx and used + DATA_HEAD + 1 <= limit:
                off = self.retx[0]
                chunk = self.unacked.get(off)
                if chunk is None:
                    self.retx.popleft()
                    continue
                if used + DATA_HEAD + len(chunk) > limit:
                    break
                self.retx.popleft()
                parts.append(bytes([C_DATA]) + struct.pack(">QH", off, len(chunk)) + chunk)
                used += DATA_HEAD + len(chunk)
                offs.append(off)
                self.counts["retransmitted"] += 1
            while self.pending and used + DATA_HEAD + 1 <= limit:
                room = min(limit - used - DATA_HEAD, len(self.pending), self.peer_max - self.pending_off)
                if room <= 0:
                    break
                chunk = bytes(self.pending[:room])
                del self.pending[:room]
                off = self.pending_off
                self.pending_off += room
                self.unacked[off] = chunk
                self.unacked_bytes += room
                parts.append(bytes([C_DATA]) + struct.pack(">QH", off, room) + chunk)
                used += DATA_HEAD + room
                offs.append(off)
        if not parts:
            return None
        if size:
            parts.append(bytes([C_PAD]) + b"\0" * max(0, limit - used - 1))
        payload = b"".join(parts)
        eliciting = bool(offs) or ping
        pn = self.pn
        self.pn += 1
        header = bytes([DATA_T]) + self.sid + struct.pack(">Q", pn)
        packet = header + self.tx.encrypt(b"\0\0\0\0" + header[1 + SID_LEN:], payload, header)
        if eliciting:
            self.sent[pn] = _Sent(now, len(packet), tuple(offs), True, bool(size))
            self.inflight += len(packet)
            self.eliciting_out += 1
            self.last_eliciting = now
            self._refill(now)
            self.tokens -= len(packet)
        self.counts["sent"] += 1
        return packet
