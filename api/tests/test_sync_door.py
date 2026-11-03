"""G132 ruling 51f D3 — the home-network door: a sealed-frame endpoint, never the HTTP API, never a token.

The handshake proves both ends by their pairing keys and hides who connects; anything else is dropped without a byte
sent back; both addresses must be loopback, private or tailnet (T3 Code's rule); a source is rate-limited; the parser
is two fixed reads and a bounded length, fuzzed here; requests run in process with the proved device and no
``Authorization`` ever arrives."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import socket
import threading
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from api.services import device_proof, sync_door


class Key:
    """A P-256 key that signs like ``device_key.sign`` (raw r||s, base64url)."""

    def __init__(self):
        self.k = ec.generate_private_key(ec.SECP256R1())
        self.jwk = device_proof.public_jwk(self.k)

    def sign(self, data: bytes) -> str:
        r, s = decode_dss_signature(self.k.sign(data, ec.ECDSA(hashes.SHA256())))
        return base64.urlsafe_b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).rstrip(b"=").decode()


@pytest.fixture
def keys(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "cicada"))
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    door = sync_door.door_state()
    priv = sync_door._x_load(sync_door._b64d(door["key"]))   # noqa: SLF001
    pub = sync_door._x_pub(priv)                              # noqa: SLF001
    home, dev = Key(), Key()
    return {"door": door, "priv": priv, "pub": pub, "home": home, "dev": dev}


def _lookup_for(dev: Key):
    def lookup(jwk):
        return sync_door.Peer("d1", "full", True) if (jwk["x"], jwk["y"]) == (dev.jwk["x"], dev.jwk["y"]) else None
    return lookup


def _open(keys, hello, **kw):
    return sync_door.server_open(hello, keys["priv"], keys["pub"], _lookup_for(keys["dev"]), keys["home"].sign,
                                 kw.pop("replays", sync_door.Replays()), **kw)


# --- the handshake -----------------------------------------------------------------------------------------------------

def test_the_handshake_proves_both_ends_and_gives_matching_keys(keys):
    ident = sync_door.Identity("d1", keys["dev"].jwk, keys["dev"].sign)
    hello, state = sync_door.client_hello(ident, keys["pub"])
    assert len(hello) == sync_door.HELLO_LEN
    device, server_keys, reply = _open(keys, hello)
    assert device.device_id == "d1" and len(reply) == sync_door.REPLY_LEN
    client_keys = sync_door.client_finish(state, reply, keys["home"].jwk)
    assert (client_keys.send, client_keys.recv) == (server_keys.recv, server_keys.send)
    # A frame each way opens on the other side; the same frame twice does not.
    a, b = sync_door.Sealer(client_keys.send), sync_door.Sealer(server_keys.recv)
    frame = a.seal(b"Q", b"{}")
    assert b.open_(frame[4:]) == (b"Q", b"{}")
    with pytest.raises(Exception):
        b.open_(frame[4:])


def test_who_connects_is_never_in_the_clear(keys):
    ident = sync_door.Identity("d1", keys["dev"].jwk, keys["dev"].sign)
    hello, _ = sync_door.client_hello(ident, keys["pub"])
    for field in (keys["dev"].jwk["x"], keys["dev"].jwk["y"]):
        assert sync_door._b64d(field) not in hello                # noqa: SLF001
    assert b"d1" not in hello


def test_a_hello_is_dropped_for_every_reason_it_could_be_wrong(keys):
    ident = sync_door.Identity("d1", keys["dev"].jwk, keys["dev"].sign)
    stranger = sync_door.Identity("d9", Key().jwk, Key().sign)       # a key that is not the device's
    other_door = sync_door._x_pub(sync_door._x25519_new())            # noqa: SLF001
    good, _ = sync_door.client_hello(ident, keys["pub"])
    assert _open(keys, sync_door.client_hello(ident, other_door)[0]) is None                    # another door
    assert _open(keys, sync_door.client_hello(ident, keys["pub"], now=time.time() - 400)[0]) is None   # too old
    assert _open(keys, sync_door.client_hello(ident, keys["pub"], now=time.time() + 400)[0]) is None   # too new
    stranger_sig = sync_door.Identity("d1", keys["dev"].jwk, Key().sign)                       # not its key
    assert _open(keys, sync_door.client_hello(stranger_sig, keys["pub"])[0]) is None
    unknown = sync_door.Identity("d9", stranger.jwk, lambda d: stranger.sign(d))
    assert _open(keys, sync_door.client_hello(unknown, keys["pub"])[0]) is None                # not in the group
    replays = sync_door.Replays()
    assert _open(keys, good, replays=replays) is not None
    assert _open(keys, good, replays=replays) is None                                          # replayed
    flipped = bytearray(good)
    flipped[-1] ^= 1
    assert _open(keys, bytes(flipped)) is None


def test_the_client_refuses_a_door_that_is_not_the_device_it_meant(keys):
    ident = sync_door.Identity("d1", keys["dev"].jwk, keys["dev"].sign)
    hello, state = sync_door.client_hello(ident, keys["pub"])
    _device, _k, reply = _open(keys, hello)
    with pytest.raises(sync_door.Unreachable):
        sync_door.client_finish(state, reply, Key().jwk)


def test_the_parser_is_fuzzed_and_never_raises(keys):
    """Random bytes, truncations and single-bit flips of a valid hello and reply: always a silent None (the door) or
    ``Unreachable`` (the client), never another exception."""
    rnd = random.Random(51)
    ident = sync_door.Identity("d1", keys["dev"].jwk, keys["dev"].sign)
    good, _ = sync_door.client_hello(ident, keys["pub"])
    cases = [os.urandom(rnd.randrange(0, 400)) for _ in range(1500)]
    cases += [good[:rnd.randrange(0, len(good))] for _ in range(300)]
    for _ in range(1500):
        b = bytearray(good)
        b[rnd.randrange(len(b))] ^= 1 << rnd.randrange(8)
        cases.append(bytes(b))
    for case in cases:
        assert _open(keys, case) is None
    hello, state = sync_door.client_hello(ident, keys["pub"])
    _d, _k, reply = _open(keys, hello)
    for _ in range(500):
        b = bytearray(reply)
        b[rnd.randrange(len(b))] ^= 1 << rnd.randrange(8)
        with pytest.raises(sync_door.Unreachable):
            sync_door.client_finish(state, bytes(b), keys["home"].jwk)
    assert sync_door.frame_length(b"\x00\x00\x00\x00") is None
    assert sync_door.frame_length(b"\xff\xff\xff\xff") is None
    assert sync_door.frame_length(b"\x00\x00") is None
    assert sync_door.frame_length((100).to_bytes(4, "big")) == 100


@pytest.mark.parametrize("local,peer,ok", [
    ("127.0.0.1", "127.0.0.1", True), ("192.168.1.4", "192.168.1.9", True), ("10.0.0.2", "10.9.9.9", True),
    ("172.16.0.1", "172.31.255.1", True), ("100.101.1.1", "100.64.0.9", True), ("::1", "::1", True),
    ("fd7a:115c:a1e0::1", "fd7a:115c:a1e0::2", True), ("fd00::1", "fd00::2", True),
    ("::ffff:192.168.1.4", "::ffff:192.168.1.9", True),
    ("192.168.1.4", "8.8.8.8", False), ("203.0.113.5", "192.168.1.9", False), ("192.168.1.4", "2001:db8::1", False),
    ("192.168.1.4", "fe80::1", False), ("0.0.0.0", "192.168.1.9", False), ("192.168.1.4", "224.0.0.1", False),
    ("192.168.1.4", "not-an-address", False),
])
def test_only_loopback_private_and_tailnet_peers_are_let_in(local, peer, ok):
    assert sync_door.allowed_peer(local, peer) is ok


def test_a_source_that_keeps_failing_runs_out_of_tries():
    b = sync_door.Buckets()
    t = 1000.0
    assert sum(b.take("x", now=t) for _ in range(30)) == sync_door.BUCKET
    assert b.take("x", now=t + sync_door.REFILL_S) is True       # refilled one
    assert b.take("y", now=t) is True                             # another source is its own


# --- a live door -------------------------------------------------------------------------------------------------------

async def _echo_app(scope, receive, send):
    msg = await receive()
    body = msg.get("body", b"")
    if scope["path"] == "/big":
        out = b"x" * (5 * 1024 * 1024 + 7)
        ctype = b"application/octet-stream"
    else:
        out = json.dumps({"path": scope["path"], "query": scope["query_string"].decode(),
                          "door": scope.get("cicada.door_device"), "device": scope.get("cicada.relay_device"),
                          "headers": sorted(k.decode() for k, _ in scope["headers"]), "len": len(body),
                          "sha": __import__("hashlib").sha256(body).hexdigest()}).encode()
        ctype = b"application/json"
    await send({"type": "http.response.start", "status": 201, "headers": [(b"content-type", ctype)]})
    await send({"type": "http.response.body", "body": out})


@pytest.fixture
def live(keys, tmp_path, monkeypatch):
    monkeypatch.setattr(sync_door, "HELLO_TIMEOUT_S", 0.5)
    monkeypatch.setattr(sync_door, "own_routes", lambda port=None: {"v": 1, "port": port, "lan": [], "tailnet": []})
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    server = sync_door.Server(_echo_app, tmp_path, port=0, host="127.0.0.1")
    server.lookup = _lookup_for(keys["dev"])
    from api.services import device_key

    monkeypatch.setattr(device_key, "sign", keys["home"].sign)
    asyncio.run_coroutine_threadsafe(server.start(), loop).result(5)
    target = sync_door.Target("home1", keys["pub"], keys["home"].jwk)
    ident = sync_door.Identity("d1", keys["dev"].jwk, keys["dev"].sign)
    yield server, target, ident
    asyncio.run_coroutine_threadsafe(server.stop(), loop).result(5)
    loop.call_soon_threadsafe(loop.stop)


def _silent(port: int, data: bytes, wait: float = 1.5) -> bytes:
    s = socket.create_connection(("127.0.0.1", port), timeout=wait)
    try:
        if data:
            s.sendall(data)
        got = b""
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                got += chunk
        except (socket.timeout, ConnectionResetError):
            pass
        return got
    finally:
        s.close()


def test_a_scanner_gets_not_one_byte(live):
    server, _t, _i = live
    assert _silent(server.port, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n" + b"\0" * 200) == b""
    assert _silent(server.port, os.urandom(sync_door.HELLO_LEN)) == b""
    assert _silent(server.port, b"") == b""                        # says nothing: closed after the hello timeout
    assert server.counts["dropped"] >= 3 and server.counts["accepted"] == 0


def test_requests_run_in_process_as_the_proved_device_with_no_token(live, tmp_path):
    server, target, ident = live
    body = os.urandom(1_300_000)                                   # three body frames
    status, headers, answer = sync_door.request(
        "127.0.0.1", server.port, target, ident, "POST", "/capture/note?x=1", body=body,
        headers={"Authorization": "Bearer secret", "Idempotency-Key": "k" * 16, "Content-Type": "application/json",
                 "X-Other": "nope"}, pool=sync_door.Pool())
    assert status == 201 and answer["door"] == "d1" and answer["device"] == "d1" and answer["query"] == "x=1"
    assert answer["len"] == len(body) and answer["sha"] == __import__("hashlib").sha256(body).hexdigest()
    assert "authorization" not in answer["headers"] and "x-other" not in answer["headers"]
    assert "idempotency-key" in answer["headers"]
    out = tmp_path / "big.bin"
    status, _h, got = sync_door.request("127.0.0.1", server.port, target, ident, "GET", "/big", to_file=out,
                                        pool=sync_door.Pool())
    assert status == 201 and got == out and out.stat().st_size == 5 * 1024 * 1024 + 7


def test_a_session_is_reused_and_the_routes_are_learned(live):
    server, target, ident = live
    learned = []
    pool = sync_door.Pool()
    for _ in range(3):
        sync_door.request("127.0.0.1", server.port, target, ident, "GET", "/x", pool=pool,
                          on_routes=lambda dev, r: learned.append((dev, r)))
    assert server.counts["accepted"] == 1 and server.counts["requests"] == 3
    assert learned == [("home1", {"v": 1, "port": server.port, "lan": [], "tailnet": []})]


def test_a_door_that_is_not_the_home_is_unreachable(live):
    server, target, ident = live
    wrong = sync_door.Target("home1", target.door_pub, Key().jwk)
    with pytest.raises(sync_door.Unreachable):
        sync_door.connect("127.0.0.1", server.port, wrong, ident)
    with pytest.raises(sync_door.Unreachable):
        sync_door.connect("127.0.0.1", 9, target, ident, timeout=0.5)


def test_a_flood_from_one_source_is_cut_off(live):
    server, target, ident = live
    for _ in range(sync_door.BUCKET + 5):
        _silent(server.port, os.urandom(sync_door.HELLO_LEN), wait=0.3)
    assert server.counts["limited"] >= 1
    with pytest.raises(sync_door.Unreachable):                     # the real device waits its turn too
        sync_door.connect("127.0.0.1", server.port, target, ident, timeout=0.5)


def test_a_watch_hears_each_new_commit(live, tmp_path):
    server, target, ident = live
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "refs" / "heads" / "main").write_text("a" * 40 + "\n")
    heads, stop = [], threading.Event()
    conn = sync_door.connect("127.0.0.1", server.port, target, ident)
    t = threading.Thread(target=sync_door.watch, args=(conn, heads.append, stop), daemon=True)
    t.start()
    deadline = time.monotonic() + 5
    while not heads and time.monotonic() < deadline:
        time.sleep(0.05)
    (git / "refs" / "heads" / "main").write_text("b" * 40 + "\n")
    while len(heads) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert heads[:2] == ["a" * 40, "b" * 40]
    stop.set()
    conn.close()


def test_a_device_not_yet_in_the_group_is_let_in_only_with_the_qrs_secret(keys):
    phone = Key()
    ident = sync_door.Identity("", phone.jwk, phone.sign)
    secret = os.urandom(32)

    def pairing(matches, jwk):
        return sync_door.Peer("", "pairing", False, jwk=jwk, pairing_id="p1") if matches(secret) else None

    def opened(hello):
        return sync_door.server_open(hello, keys["priv"], keys["pub"], lambda jwk: None, keys["home"].sign,
                                     sync_door.Replays(), pairing=pairing)

    assert opened(sync_door.client_hello(ident, keys["pub"])[0]) is None                    # no secret
    assert opened(sync_door.client_hello(ident, keys["pub"], pair_secret=os.urandom(32))[0]) is None   # wrong one
    got = opened(sync_door.client_hello(ident, keys["pub"], pair_secret=secret)[0])
    assert got is not None and got[0].kind == "pairing" and got[0].jwk == phone.jwk


def test_on_a_mac_the_door_stays_on_loopback_until_the_person_allowed_the_lan(keys, monkeypatch):
    """Binding every interface raises the application firewall's question: never before the app's permissions step."""
    from api.services import sync_routes

    monkeypatch.delenv(sync_door.HOST_ENV, raising=False)
    monkeypatch.setattr(__import__("sys"), "platform", "darwin")
    assert sync_door.wanted_host() == "127.0.0.1"
    sync_routes.set_lan_allowed(True)
    assert sync_door.wanted_host() is None
    assert sync_door.wanted_host({sync_door.HOST_ENV: "192.168.1.4"}) == "192.168.1.4"
    monkeypatch.setattr(__import__("sys"), "platform", "linux")
    sync_routes.set_lan_allowed(False)
    assert sync_door.wanted_host() is None
