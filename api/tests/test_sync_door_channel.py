"""G132 ruling 51f — the UDP door's sealed channel (``sync_door_channel``), pure: no socket, a simulated path.

One reliable, ordered stream over sealed datagrams: exact bytes through loss, reorder and duplication; a packet that
is replayed, altered, from the other direction or of another session is refused before anything of it is used; the
reader's window holds a sender back; random datagrams never raise."""
from __future__ import annotations

import hashlib
import heapq
import os
import random

import pytest

from api.services import sync_door
from api.services import sync_door_channel as ch


def _pair(rtt: float = 0.01):
    k1, k2, sid = os.urandom(32), os.urandom(32), os.urandom(ch.SID_LEN)
    return ch.Channel(sid, k1, k2, now=0.0, rtt=rtt), ch.Channel(sid, k2, k1, now=0.0, rtt=rtt)


def _transfer(size: int, *, loss=0.0, reorder=0.0, dup=0.0, rtt=0.01, seed=1, read=True, until=None):
    """``a`` sends ``size`` bytes as 512 KiB frames and an end frame to ``b`` over a simulated path; returns what ``b``
    read, the simulated seconds, and both channels."""
    rnd = random.Random(seed)
    a, b = _pair(rtt)
    data = random.Random(seed + 1).randbytes(size)
    for i in range(0, size, 512 * 1024):
        a.write(ch.frame(b"B", data[i:i + 512 * 1024]))
    a.write(ch.frame(b"E"))
    q, seq, now, got, done, steps = [], 0, 0.0, bytearray(), False, 0

    def put(dst, pkts):
        nonlocal seq
        for p in pkts:
            if rnd.random() < loss:
                continue
            for _ in range(2 if rnd.random() < dup else 1):
                late = rnd.random() * rtt * 2 if rnd.random() < reorder else 0.0
                seq += 1
                heapq.heappush(q, (now + rtt / 2 + late, seq, dst, p))

    while (not done or a.backlog()) and steps < 1_000_000 and (until is None or now < until):
        steps += 1
        put(b, a.poll(now))
        if read and not done:
            while (f := b.next_frame()) is not None:
                if f[0] == b"E":
                    done = True
                else:
                    got += f[1]
        put(a, b.poll(now))
        due = [t for t in (a.timeout(now), b.timeout(now)) if t is not None]
        nxt = min(due) if due else None
        if q and (nxt is None or q[0][0] <= nxt):
            t, _s, dst, p = heapq.heappop(q)
            now = max(now, t)
            dst.receive(p, now)
        elif nxt is not None:
            now = max(now, nxt)
            a.on_timeout(now)
            b.on_timeout(now)
        else:
            break
    return bytes(got), data, now, a, b


@pytest.mark.parametrize("loss,reorder,dup,seed", [
    (0.0, 0.0, 0.0, 1), (0.02, 0.0, 0.0, 2), (0.10, 0.0, 0.0, 3), (0.0, 0.25, 0.0, 4), (0.05, 0.10, 0.05, 5),
    (0.05, 0.10, 0.05, 6), (0.30, 0.10, 0.10, 7)])
def test_the_stream_arrives_exactly_through_loss_reorder_and_duplication(loss, reorder, dup, seed):
    size = 300_000 if loss >= 0.3 else 2_000_000
    got, data, _t, a, _b = _transfer(size, loss=loss, reorder=reorder, dup=dup, seed=seed)
    assert hashlib.sha256(got).digest() == hashlib.sha256(data).digest()
    if loss:
        assert a.counts["lost"] > 0 and a.counts["retransmitted"] > 0
    assert a.backlog() == 0                                      # every byte acknowledged


def test_a_clean_path_grows_the_window_and_probes_a_larger_datagram():
    got, data, t, a, _b = _transfer(3_000_000)
    assert got == data and a.counts["lost"] == 0
    assert a.mss == ch.PROBE_DGRAM and a.cwnd > 100 * ch.BASE_DGRAM
    assert t < 0.5                                               # 3 MB over a simulated 10 ms path, slow start included


def test_a_reader_that_does_not_read_holds_the_sender_at_its_window():
    _got, _data, _t, a, b = _transfer(3 * ch.RECV_WINDOW, read=False, until=5.0)
    assert a.pending_off <= ch.RECV_WINDOW and a.pending                         # held, not lost
    assert len(b.readable) <= ch.RECV_WINDOW


def _one_packet():
    a, b = _pair()
    a.write(ch.frame(b"Q", b"{}"))
    return a, b, a.poll(0.0)[0]


def test_a_packet_replayed_altered_reversed_or_of_another_session_is_refused():
    a, b, pkt = _one_packet()
    assert b.receive(pkt, 0.01) is True and b.next_frame() == (b"Q", b"{}")
    assert b.receive(pkt, 0.02) is False                                      # replayed
    a2, b2, pkt2 = _one_packet()
    flipped = bytearray(pkt2)
    flipped[-1] ^= 1
    assert b2.receive(bytes(flipped), 0.01) is False                           # altered
    header = bytearray(pkt2)
    header[ch.HEADER - 1] ^= 1
    assert b2.receive(bytes(header), 0.01) is False                            # its number changed
    assert a2.receive(pkt2, 0.01) is False                                     # its own direction's key
    other = bytearray(pkt2)
    other[1:1 + ch.SID_LEN] = os.urandom(ch.SID_LEN)
    assert b2.receive(bytes(other), 0.01) is False                             # another session
    assert b2.receive(pkt2, 0.01) is True                                      # the real one still opens


def test_the_replay_window_keeps_order_free_and_old_packets_out():
    w = ch.ReplayWindow(64)
    for pn in (5, 3, 9, 4):
        assert w.fresh(pn)
        w.mark(pn)
    assert not w.fresh(3) and not w.fresh(9) and w.fresh(6)
    w.mark(1000)
    assert not w.fresh(1000 - 64) and w.fresh(1000 - 63) and not w.fresh(9)
    w.mark(10 ** 9)                                              # a jump wider than the window
    assert w.fresh(10 ** 9 - 1) and not w.fresh(10 ** 9)


def test_datagrams_are_told_apart_by_type_and_exact_length():
    assert ch.shape(ch.hello_datagram(b"\0" * sync_door.HELLO_LEN)) == "hello"
    assert ch.shape(ch.hello_datagram(b"\0" * (sync_door.HELLO_LEN - 1))) is None
    assert ch.shape(ch.reply_datagram(b"\0" * ch.SID_LEN, b"\0" * sync_door.REPLY_LEN)) == "reply"
    assert ch.shape(bytes([ch.DATA_T]) + b"\0" * (ch.MIN_DATA_DGRAM - 2)) is None
    assert ch.shape(bytes([ch.DATA_T]) + b"\0" * (ch.MIN_DATA_DGRAM - 1)) == "data"
    assert ch.shape(bytes([ch.DATA_T]) + b"\0" * ch.MAX_DGRAM) is None
    assert ch.shape(b"") is None and ch.shape(b"\x09" + b"\0" * 300) is None
    assert ch.REPLY_DGRAM < ch.HELLO_DGRAM                      # the door's one answer never amplifies


def test_random_datagrams_never_raise_and_never_count_as_the_peers():
    rnd = random.Random(132)
    _a, b = _pair()
    sid = b.sid
    for _ in range(3000):
        n = rnd.randrange(0, 1600)
        raw = bytearray(rnd.randbytes(n))
        if n > ch.HEADER and rnd.random() < 0.5:
            raw[0] = ch.DATA_T
            raw[1:1 + ch.SID_LEN] = sid
        assert b.receive(bytes(raw), 0.1) is False
    assert b.readable == bytearray() and b.counts["received"] == 0


def test_an_ack_naming_packets_never_sent_costs_nothing():
    """From the peer (so authentic): ranges reaching far past what was sent never walk that far."""
    import struct
    import time

    a, b = _pair()
    a.write(ch.frame(b"B", b"x" * 3000))
    pkts = a.poll(0.0)
    assert len(pkts) == 3 and b.receive(pkts[0], 0.01)
    b.ranges = [[0, 0], [2 ** 63, 1]]                    # a malformed second range, far past what was sent
    started = time.monotonic()
    ack = b.poll(0.02)
    for p in ack:
        a.receive(p, 0.03)
    assert time.monotonic() - started < 0.5 and a.backlog() == 0
    assert struct.calcsize(">QQ") == 16
