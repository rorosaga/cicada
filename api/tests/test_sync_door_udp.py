"""G132 ruling 51f — the door over UDP, live on loopback (owner 2026-11-03: "If we can work on tcp and udp directly
probably best to do udp, no?"), through a lossy forwarder the test owns (``_udp_wire``).

Shown: requests and a 5 MB answer arrive exact through loss, reorder and duplication; a session follows its device to
another address of the home and to a new source port (a NAT rebinding, another network) with no second handshake; a
path whose answers are cut ends in seconds as "may have landed"; a session never confirmed holds nothing; a watch pings
for its NAT and notices a gone path within seconds of a network change; on a clean path the larger datagram is used."""
from __future__ import annotations

import hashlib
import os
import socket
import threading
import time

import pytest

from _udp_wire import UdpWire
from test_sync_door import _git_head, _udp_heard, keys, udp_door  # noqa: F401 — fixtures
from api.services import sync_door, sync_door_udp
from api.services import sync_door_channel as channel


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_a_request_and_a_large_answer_arrive_exact_through_a_lossy_path(udp_door, tmp_path, seed):
    server, target, ident = udp_door
    wire = UdpWire(server.port, loss=0.05, reorder=0.10, dup=0.02, seed=seed)
    try:
        body = os.urandom(1_300_000)
        status, _h, answer = sync_door.request("127.0.0.1", wire.port, target, ident, "POST", "/capture/note",
                                               body=body, pool=sync_door.Pool(), connect_timeout=5.0)
        assert status == 201 and answer["sha"] == hashlib.sha256(body).hexdigest()
        out = tmp_path / f"big-{seed}.bin"
        status, _h, got = sync_door.request("127.0.0.1", wire.port, target, ident, "GET", "/big", to_file=out,
                                            pool=sync_door.Pool(), connect_timeout=5.0)
        assert status == 201 and out.read_bytes() == b"x" * (5 * 1024 * 1024 + 7)
        assert wire.forwarded["lost"] > 0 and wire.forwarded["reordered"] > 0
    finally:
        wire.stop()


def test_a_session_follows_its_device_to_another_address_with_no_second_handshake(udp_door):
    server, target, ident = udp_door
    a, b = UdpWire(server.port), UdpWire(server.port)
    try:
        conn = sync_door.connect("127.0.0.1", a.port, target, ident, paths=[("127.0.0.1", b.port)])
        assert sync_door.call(conn, "GET", "/x")[0] == 201
        a.down()                                        # the first network went away
        started = time.monotonic()
        status, _h, answer = sync_door.call(conn, "GET", "/y")
        moved_s = time.monotonic() - started
        assert status == 201 and answer["path"] == "/y"
        assert server.counts["accepted"] == 1 and server.counts["roamed"] >= 1
        assert moved_s < 2.0, moved_s
        conn.close()
    finally:
        a.stop()
        b.stop()


def test_a_new_source_port_is_followed_too(udp_door):
    """A NAT rebinding or this computer's own new address: the next proven packet comes from elsewhere."""
    server, target, ident = udp_door
    conn = sync_door.connect("127.0.0.1", server.port, target, ident)
    assert sync_door.call(conn, "GET", "/x")[0] == 201
    fresh = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    fresh.setblocking(False)
    fresh.connect(conn.addr)
    old, conn.sock = conn.sock, fresh
    old.close()
    assert sync_door.call(conn, "GET", "/z")[0] == 201
    assert server.counts["accepted"] == 1 and server.counts["roamed"] >= 1
    conn.close()


def test_a_path_that_loses_every_answer_ends_as_may_have_landed_in_seconds(udp_door):
    server, target, ident = udp_door
    wire = UdpWire(server.port)
    try:
        conn = sync_door.connect("127.0.0.1", wire.port, target, ident)
        assert sync_door.call(conn, "GET", "/x")[0] == 201
        wire.mode = "cut_answers"
        started = time.monotonic()
        with pytest.raises(sync_door.Dropped):
            sync_door.call(conn, "POST", "/capture/note", body=b"{}", timeout=30)
        assert time.monotonic() - started < sync_door_udp.SILENT_MIN_S + 2     # a loopback path: the floor
    finally:
        wire.stop()


def test_a_session_never_confirmed_holds_nothing(udp_door, keys):  # noqa: F811
    server, _target, ident = udp_door
    hello, _ = sync_door.client_hello(ident, keys["pub"])
    assert len(_udp_heard(server.port, [channel.hello_datagram(hello)], wait=0.2)) == channel.REPLY_DGRAM
    assert server.udp.pending == 1
    deadline = time.monotonic() + 3
    while server.udp.sessions and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.udp.sessions == {} and server.udp.pending == 0 and server.sessions == 0


def test_a_clean_path_uses_the_larger_datagram(udp_door, tmp_path):
    server, target, ident = udp_door
    conn = sync_door.connect("127.0.0.1", server.port, target, ident)
    for _ in range(3):                    # a probe lost to a full buffer under load is tried again a second later
        sync_door.call(conn, "GET", "/big", to_file=tmp_path / "b.bin")
        link = next(iter(server.udp.sessions.values()))
        if link.ch.mss == channel.PROBE_DGRAM:
            break
        time.sleep(1.1)
    assert link.ch.mss == channel.PROBE_DGRAM                     # the side that sent bulk probed, and kept it
    assert conn.ch.mss == channel.BASE_DGRAM                      # a few control frames never pay for a probe
    conn.close()


def test_a_watch_keeps_its_nat_and_notices_a_gone_path_after_a_network_change(udp_door, tmp_path, monkeypatch):
    server, target, ident = udp_door
    monkeypatch.setattr(sync_door_udp, "KEEPALIVE_S", 0.3)
    _git_head(tmp_path, "a" * 40)
    wire = UdpWire(server.port)
    try:
        heads, stop = [], threading.Event()
        conn = sync_door.connect("127.0.0.1", wire.port, target, ident)
        t = threading.Thread(target=sync_door.watch, args=(conn, heads.append, stop), daemon=True)
        t.start()
        deadline = time.monotonic() + 5
        while not heads and time.monotonic() < deadline:
            time.sleep(0.05)
        link = next(iter(server.udp.sessions.values()))
        before = link.ch.counts["received"]
        time.sleep(1.2)
        assert link.ch.counts["received"] - before >= 3            # keepalives reach the door: the NAT stays open
        wire.down()
        sync_door_udp.network_changed()
        started = time.monotonic()
        t.join(sync_door_udp.SILENT_S + 3)
        assert not t.is_alive() and time.monotonic() - started < sync_door_udp.SILENT_MIN_S + 2
    finally:
        stop.set()
        wire.stop()
