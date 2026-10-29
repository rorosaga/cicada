"""G132 phase 3a — the relay end to end on loopback: a home and two devices pair through it, exchange encrypted frames,
wait in its mailbox while offline, expire, hit its bounds, are revoked, and refuse whatever a misbehaving relay
replays, reorders or tampers with. Nothing here leaves 127.0.0.1; every key and payload is synthetic."""
from __future__ import annotations

import asyncio
import logging
import struct
from pathlib import Path

import pytest
from nacl import pwhash

from _relay import Clock, Config, Relay, wire
from api.services.sync_relay_client import PairingSocket, RelayClient, check_url
from api.services.sync_relay_crypto import Endpoint, Home, Keys, Refused, parse_frame
from api.services.sync_relay_pairing import DevicePairing, HomePairing, qr_payload, random_slot, slot_for_code

MARKER = b"PLAINTEXT-MARKER-7f3a9c"
TOKEN = "cic_dev_" + "T" * 40
CODE = "ABCD-EFGH"
FAST = {"ops": pwhash.argon2id.OPSLIMIT_MIN, "mem": pwhash.argon2id.MEMLIMIT_MIN}
DAY = 86_400


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 60))


async def start(tmp_path: Path, clock=None, relay_cls=Relay, **bounds) -> Relay:
    cfg = Config(host="127.0.0.1", port=0, db_path=str(tmp_path / "relay.db"), purge_interval_s=3600, **bounds)
    return await relay_cls(cfg, clock=clock or Clock()).start()


def url(relay: Relay) -> str:
    return f"ws://127.0.0.1:{relay.port}"


async def pair_qr(relay, hc: RelayClient, home: Home, name: str) -> Endpoint:
    slot = random_slot()
    hp = HomePairing(home=home, code=CODE, slot=slot, typed=False)
    await hc.pair_open(slot, hp.offer())
    dp = DevicePairing.from_qr(qr_payload(CODE, url(relay), slot, home.keys), name=name)
    ps = PairingSocket(url(relay), slot)
    dp.read_offer(await ps.connect())
    await ps.send(dp.request())
    got_slot, body = await hc.pair_request()
    assert got_slot == slot
    hp.receive(body)
    sealed, frame = hp.welcome(TOKEN, confirmed=True)
    assert (await hc.send([frame]))[0]["t"] == "ok"
    await hc.pair_reply(slot, sealed)
    token, endpoint = dp.accept_welcome(await ps.recv(), confirmed=False)
    assert token == TOKEN
    await ps.close()
    await hc.pair_close(slot)
    endpoint.clock = home.clock
    return endpoint


async def pair_typed(relay, hc: RelayClient, home: Home, name: str) -> Endpoint:
    slot = slot_for_code(CODE, **FAST)
    hp = HomePairing(home=home, code=CODE, slot=slot, typed=True)
    await hc.pair_open(slot, hp.offer())
    dp = DevicePairing.from_code(CODE, name=name, **FAST)
    ps = PairingSocket(url(relay), dp.slot)
    dp.read_offer(await ps.connect())
    await ps.send(dp.request())
    _, body = await hc.pair_request()
    candidate, reveal = hp.receive(body)
    await hc.pair_reply(slot, reveal)
    assert dp.read_reveal(await ps.recv()) == candidate.sas          # the person compares the two screens
    sealed, frame = hp.welcome(TOKEN, confirmed=True)
    assert (await hc.send([frame]))[0]["t"] == "ok"
    await hc.pair_reply(slot, sealed)
    _, endpoint = dp.accept_welcome(await ps.recv(), confirmed=True)
    await ps.close()
    await hc.pair_close(slot)
    endpoint.clock = home.clock
    return endpoint


async def drain(client: RelayClient, endpoint: Endpoint, timeout=0.5):
    """Every message waiting for ``client``; acks what it read."""
    out, last = [], 0
    while True:
        try:
            rseq, raw = await client.recv(timeout)
        except asyncio.TimeoutError:
            break
        msg = endpoint.open(raw)
        if msg is not None:
            out.append(msg)
        last = max(last, rseq)
    if last:
        await client.ack(last)
    return out


async def group(relay, clock):
    """A home online, a laptop paired by QR and a phone paired by a typed code, both offline."""
    home = Home.create(clock=clock)
    hc = RelayClient(url(relay), home, create=home.epoch_frame())
    await hc.connect()
    laptop = await pair_qr(relay, hc, home, "laptop")
    phone = await pair_typed(relay, hc, home, "phone")
    return home, hc, laptop, phone


def test_urls_must_be_tls_unless_loopback():
    assert check_url("wss://relay.example") == "wss://relay.example/v1"
    assert check_url("ws://127.0.0.1:9") == "ws://127.0.0.1:9/v1"
    with pytest.raises(Refused):
        check_url("ws://relay.example")


def test_offline_delivery_both_ways_and_the_relay_stores_no_plaintext(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="cicada_relay")

    async def scenario():
        clock = Clock()
        relay = await start(tmp_path, clock)
        try:
            home, hc, laptop, phone = await group(relay, clock)
            lc = RelayClient(url(relay), laptop)
            await lc.connect()
            # The phone joined after the laptop: the laptop learns the newer membership on connect.
            assert [m.kind for m in await drain(lc, laptop)] == ["epoch"] and laptop.epoch == home.epoch
            for seq in (1, 2, 3):
                replies = await hc.send(home.seal("delta", MARKER + b" delta %d" % seq, meta={"seq": seq}))
                assert replies[0]["t"] == "ok"
            got = await drain(lc, laptop)
            assert [m.meta["seq"] for m in got] == [1, 2, 3]
            # The phone is off: the home coalesces what waits for it into one cursor..HEAD delta.
            for seq in (4, 5):
                last = (await hc.send(home.seal("delta", b"superseded %d" % seq, meta={"seq": seq})))[-1]["rseq"]
            assert await hc.supersede(phone.me, last) == 5      # seq 1-5, all still waiting for it
            await hc.send(home.seal("delta", MARKER + b" coalesced", meta={"seq": 5, "base_seq": 3}))
            assert [m.meta["seq"] for m in await drain(lc, laptop)] == [4, 5, 5]
            # The home goes to sleep; the laptop's write waits at the relay.
            await hc.close()
            tx = laptop.seal("tx", MARKER + b' {"tool":"cicada_save_episode"}',
                             meta={"idem": "idem-0001-synthetic", "base_seq": 3}, to="home")
            assert (await lc.send(tx))[0]["t"] == "ok"
            assert await lc.counts() == {home.me: 1, laptop.me: 1}      # on its way, per sender (ruling 51d)
            # The phone was off through all of it.
            pc = RelayClient(url(relay), phone)
            await pc.connect()
            assert [m.payload for m in await drain(pc, phone)] == [MARKER + b" coalesced"]
            assert await pc.counts() == {laptop.me: 1}
            # The home wakes and applies the transaction once.
            hc2 = RelayClient(url(relay), home)
            await hc2.connect()
            msgs = await drain(hc2, home)
            assert [(m.kind, m.meta["idem"], m.sender) for m in msgs] == [("tx", "idem-0001-synthetic", laptop.me)]
            assert await hc2.counts() == {}
            # Status frames are latest-only and never queued.
            await hc2.send(home.seal("status", b'{"sleep":"idle"}', meta={"seq": 3}))
            await hc2.send(home.seal("status", MARKER + b'{"sleep":"running"}', meta={"seq": 3}))
            await pc.close()
            pc2 = RelayClient(url(relay), phone)
            await pc2.connect()
            statuses = [m for m in await drain(pc2, phone) if m.kind == "status"]
            assert [s.payload for s in statuses] == [MARKER + b'{"sleep":"running"}']
            for c in (lc, hc2, pc2):
                await c.close()
        finally:
            await relay.stop()

    run(scenario())
    stored = b"".join(p.read_bytes() for p in tmp_path.glob("relay.db*"))
    assert len(stored) > 10_000 and MARKER not in stored and TOKEN.encode() not in stored
    assert CODE.encode() not in stored and CODE.replace("-", "").encode() not in stored
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "frame mb=" in logged and MARKER.decode() not in logged and TOKEN not in logged


def test_frames_expire_in_the_mailbox(tmp_path):
    async def scenario():
        clock = Clock()
        relay = await start(tmp_path, clock)
        try:
            home, hc, laptop, _ = await group(relay, clock)
            await hc.send(home.seal("delta", b"old", meta={"seq": 1}))
            clock.t += 7 * DAY
            assert relay.purge()["frames"] >= 1
            await hc.send(home.seal("delta", b"new", meta={"seq": 2}))
            lc = RelayClient(url(relay), laptop)
            await lc.connect()
            assert [m.payload for m in await drain(lc, laptop) if m.kind == "delta"] == [b"new"]
            # A transaction already past its TTL by its own signed time is refused at the door.
            await hc.close()
            stale = Endpoint.from_state(laptop.to_state(), clock=Clock(clock.t - 8 * DAY))
            frame = stale.seal("tx", b"{}", meta={"idem": "idem-stale-0001"}, to="home")
            assert (await lc.send(frame))[0] == {"t": "refused", "ctr": laptop.ctr + 1, "code": "expired"}
            await lc.close()
        finally:
            await relay.stop()

    run(scenario())


def test_bounds_are_refused_over_the_wire(tmp_path):
    async def scenario():
        clock = Clock()
        relay = await start(tmp_path, clock, max_frame_bytes=9000, max_bank_bytes=20_000, tx_reserve_bytes=5_000)
        try:
            home, hc, laptop, _ = await group(relay, clock)
            too_big = home.seal("delta", b"x" * 9000, meta={"seq": 2})       # pads to 16 KiB: over the 9 000 max
            assert (await hc.send(too_big))[0]["code"] == "too_large"
            await hc.close()
            lc = RelayClient(url(relay), laptop)
            await lc.connect()
            answers = []
            for i in range(5):
                f = laptop.seal("tx", b"{}", meta={"idem": f"idem-bound-{i:04d}"}, to="home")
                answers.append((await lc.send(f))[0])
            assert [a["t"] for a in answers[:4]] == ["ok"] * 4 and answers[4]["code"] == "relay_full"
            await lc.close()
        finally:
            await relay.stop()

    run(scenario())


def test_revoke_rotates_and_the_relay_drops_the_device(tmp_path):
    async def scenario():
        clock = Clock()
        relay = await start(tmp_path, clock)
        try:
            home, hc, laptop, phone = await group(relay, clock)
            lc, pc = RelayClient(url(relay), laptop), RelayClient(url(relay), phone)
            await lc.connect()
            await pc.connect()
            await drain(lc, laptop)
            await drain(pc, phone)
            phone_ws = pc.ws
            assert (await hc.send([home.revoke(phone.me)]))[0]["t"] == "ok"
            await asyncio.wait_for(phone_ws.wait_closed(), 5)
            assert phone_ws.close_code == 4403
            with pytest.raises(Refused) as exc:
                await RelayClient(url(relay), phone).connect()
            assert exc.value.code == "not_member"
            assert [m.kind for m in await drain(lc, laptop)] == ["epoch"]
            frames = home.seal("delta", b"after the revoke", meta={"seq": 9})
            await hc.send(frames)
            assert [m.payload for m in await drain(lc, laptop)] == [b"after the revoke"]
            with pytest.raises(Refused) as exc:
                phone.open(frames[0])                                       # even holding the bytes
            assert exc.value.code in ("unknown_epoch", "not_member")
            await lc.close()
        finally:
            await relay.stop()

    run(scenario())


class MisbehavingRelay(Relay):
    """Delivers every frame out of order, then again, then with one byte flipped."""

    async def _flush(self, conn):
        async with conn.lock:
            rows = self.store.pending(conn.mb, conn.dev, after=conn.sent_upto)
            if not rows:
                return
            for rseq, raw in reversed(rows):
                await conn.ws.send(struct.pack(">Q", rseq) + raw)
            for rseq, raw in rows:
                await conn.ws.send(struct.pack(">Q", rseq) + raw)
                bad = bytearray(raw)
                bad[len(bad) // 2] ^= 0x01
                await conn.ws.send(struct.pack(">Q", rseq) + bytes(bad))
            conn.sent_upto = rows[-1][0]


def test_a_misbehaving_relay_cannot_replay_reorder_or_tamper(tmp_path):
    async def scenario():
        clock = Clock()
        relay = await start(tmp_path, clock, relay_cls=MisbehavingRelay)
        try:
            home, hc, laptop, _ = await group(relay, clock)
            for seq in (1, 2, 3):
                await hc.send(home.seal("delta", b"delta %d" % seq, meta={"seq": seq}))
            lc = RelayClient(url(relay), laptop)
            await lc.connect()
            accepted, refused = [], []
            while True:
                try:
                    _, raw = await lc.recv(0.5)
                except asyncio.TimeoutError:
                    break
                try:
                    msg = laptop.open(raw)
                    if msg is not None and msg.kind == "delta":
                        accepted.append(msg.meta["seq"])
                except Refused as exc:
                    refused.append(exc.code)
            # Reversed, only the newest is accepted; every replay and every flipped byte is refused. The follower
            # notices seq 1 and 2 never arrived and asks the home for cursor..HEAD.
            assert accepted == [3]
            assert set(refused) <= {"replay", "bad_signature", "bad_header", "bad_frame"}
            assert refused.count("replay") >= 5 and len(refused) == 8
            # The relay itself refuses a frame a device sends twice.
            frame = laptop.seal("control", b"ping", meta={})
            assert (await lc.send(frame))[0]["t"] == "ok"
            await lc.send_raw(frame[0])
            assert (await lc.next_control("refused", 5))["code"] == "replay"
            await lc.close()
        finally:
            await relay.stop()

    run(scenario())


def test_the_relay_refuses_frames_it_cannot_attribute(tmp_path):
    async def scenario():
        clock = Clock()
        relay = await start(tmp_path, clock)
        try:
            home, hc, laptop, phone = await group(relay, clock)
            lc = RelayClient(url(relay), laptop)
            await lc.connect()
            # A frame signed by the phone, sent on the laptop's socket.
            assert (await lc.send(phone.seal("control", b"x", meta={})))[0]["code"] == "not_yours"
            # A member sending what only the home sends.
            own = parse_frame(laptop.seal("control", b"x", meta={})[0])
            from api.services.sync_relay_crypto import build_frame
            fake = build_frame(laptop.keys, own.header | {"kind": "delta", "ctr": 77, "msg": 77}, own.body)
            assert (await lc.send([fake]))[0]["code"] == "home_only"
            # An outsider cannot even connect.
            stranger = Endpoint(keys=Keys.generate(), mailbox=home.mailbox, home=home.me)
            with pytest.raises(Refused) as exc:
                await RelayClient(url(relay), stranger).connect()
            assert exc.value.code == "not_member"
            # The relay's parser and the backend's builder agree on the frame.
            parsed = wire.parse(home.seal("delta", b"y", meta={"seq": 1})[0])
            wire.verify(parsed)
            assert parsed.kind == "delta" and parsed.sender == home.me
            await lc.close()
        finally:
            await relay.stop()

    run(scenario())


def test_health_and_unknown_paths(tmp_path):
    import urllib.request

    async def scenario():
        relay = await start(tmp_path)
        try:
            base = f"http://127.0.0.1:{relay.port}"
            loop = asyncio.get_running_loop()
            body = await loop.run_in_executor(None, lambda: urllib.request.urlopen(base + "/healthz", timeout=5).read())
            assert body == b"ok\n"
            with pytest.raises(Exception):
                await loop.run_in_executor(None, lambda: urllib.request.urlopen(base + "/other", timeout=5))
        finally:
            await relay.stop()

    run(scenario())
