"""G132 phase 3a — the relay's end-to-end layer (ruling 51c, gate g3): frames are encrypted to the device group,
signed by their sender, refused when replayed, reordered, tampered with or forged, and a revoke rotates the epoch so
the revoked device opens nothing sent afterwards. Synthetic keys only."""
from __future__ import annotations

import filecmp
from pathlib import Path

import pytest
from nacl.public import PublicKey, SealedBox

from _relay import Config
from api.services.sync_relay_crypto import (BUCKETS, MAX_PART_PLAIN, MAX_STREAM_BYTES, Endpoint, Home, Keys, MiB,
                                            Refused, b64d, b64e, bucket, build_frame, canonical, framed_size, pad,
                                            parse_frame, unpad)


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def group(n=2, clock=None):
    """A home and ``n`` devices that accepted every epoch frame the home posted."""
    clock = clock or Clock()
    home = Home.create(clock=clock)
    devices = []
    for _ in range(n):
        keys = Keys.generate()
        frame = home.add_device(keys.public())
        dev = Endpoint(keys=keys, mailbox=home.mailbox, home=home.me, clock=clock)
        for d in devices + [dev]:
            assert d.open(frame).kind == "epoch"
        devices.append(dev)
    return home, devices, clock


def test_padding_hides_the_length_to_a_bucket():
    assert pad(b"") == b"\x80" + b"\x00" * 4095
    for n in (0, 1, 4095, 4096, 5000, 70_000, 600_000, MAX_PART_PLAIN - 1):
        p = pad(b"a" * n)
        assert len(p) in BUCKETS and len(p) == bucket(n) and unpad(p) == b"a" * n
    with pytest.raises(Refused):
        unpad(b"\x00" * 16)


def test_a_delta_round_trips_and_every_byte_the_relay_sees_is_ciphertext():
    home, (laptop, phone), _ = group()
    marker = b"PLAINTEXT-MARKER-delta-0001"
    frames = home.seal("delta", marker * 10, meta={"seq": 41, "base_seq": 40})
    assert len(frames) == 1 and marker not in frames[0]
    for dev in (laptop, phone):
        msg = dev.open(frames[0])
        assert (msg.kind, msg.payload, msg.meta, msg.sender) == ("delta", marker * 10, {"base_seq": 40, "seq": 41},
                                                                 home.me)


def test_a_transaction_carries_its_idempotency_key_and_reaches_only_the_home():
    home, (laptop, phone), _ = group()
    frames = laptop.seal("tx", b'{"tool":"cicada_save_episode"}', meta={"idem": "k-0001-abcdef", "base_seq": 7},
                         to="home")
    msg = home.open(frames[0])
    assert msg.meta["idem"] == "k-0001-abcdef" and msg.meta["base_seq"] == 7
    with pytest.raises(Refused) as exc:
        phone.open(frames[0])
    assert exc.value.code == "not_for_me"
    with pytest.raises(Refused) as exc:
        laptop.seal("tx", b"{}", meta={}, to="home")
    assert exc.value.code == "bad_meta"


def test_replayed_and_reordered_frames_are_refused():
    home, (laptop,), _ = group(1)
    a = home.seal("delta", b"one", meta={"seq": 1})[0]
    b = home.seal("delta", b"two", meta={"seq": 2})[0]
    assert laptop.open(a).payload == b"one"
    with pytest.raises(Refused) as exc:
        laptop.open(a)
    assert exc.value.code == "replay"
    c = home.seal("delta", b"three", meta={"seq": 3})[0]
    assert laptop.open(c).payload == b"three"
    with pytest.raises(Refused) as exc:
        laptop.open(b)          # delivered after a later frame: reordered
    assert exc.value.code == "replay"


def test_a_tampered_frame_is_refused_wherever_the_byte_is():
    home, (laptop,), _ = group(1)
    frame = home.seal("delta", b"payload " * 50, meta={"seq": 9})[0]
    p = parse_frame(frame)
    for where in (len(p.aad) + 30, len(frame) - 10, 3 + 2 + 5):
        bad = bytearray(frame)
        bad[where] ^= 0x01
        with pytest.raises(Refused) as exc:
            laptop.open(bytes(bad))
        assert exc.value.code in ("bad_signature", "bad_header", "bad_frame")
    assert laptop.open(frame).payload == b"payload " * 50


def test_neither_the_relay_nor_another_device_can_forge_a_frame():
    home, (laptop, phone), _ = group()
    # The relay holds no member's key: a frame signed by any other key is refused.
    outsider = Keys.generate()
    real = parse_frame(home.seal("delta", b"x", meta={"seq": 1})[0])
    forged = build_frame(outsider, real.header | {"ctr": 99, "msg": 99}, real.body)
    with pytest.raises(Refused) as exc:
        laptop.open(forged)
    assert exc.value.code == "bad_signature"
    # A member that names another member as the sender fails the signature.
    as_laptop = parse_frame(laptop.seal("control", b"hi", meta={})[0])
    spoof = build_frame(phone.keys, as_laptop.header | {"ctr": 50, "msg": 50}, as_laptop.body)
    with pytest.raises(Refused) as exc:
        home.open(spoof)
    assert exc.value.code == "bad_signature"
    # A member may not send what only the home sends, even signed as itself.
    with pytest.raises(Refused):
        phone.seal("delta", b"x", meta={"seq": 1})
    own = parse_frame(phone.seal("control", b"x", meta={})[0])
    fake_delta = build_frame(phone.keys, own.header | {"kind": "delta"}, own.body)
    with pytest.raises(Refused) as exc:
        laptop.open(fake_delta)
    assert exc.value.code == "home_only"
    # Nor a membership change.
    epoch = parse_frame(home.add_device(Keys.generate().public()))
    fake_epoch = build_frame(phone.keys, epoch.header | {"from": phone.me}, epoch.body)
    with pytest.raises(Refused) as exc:
        laptop.open(fake_epoch)
    assert exc.value.code == "bad_signature"


def test_revoke_rotates_the_epoch_and_the_revoked_device_opens_nothing_after():
    home, (laptop, phone), _ = group()
    before = home.seal("delta", b"before", meta={"seq": 1})[0]
    rotate = home.revoke(phone.me)
    assert laptop.open(rotate).kind == "epoch"
    with pytest.raises(Refused) as exc:
        phone.open(rotate)
    assert exc.value.code == "revoked" and phone.revoked
    after = home.seal("delta", b"after", meta={"seq": 2})[0]
    assert laptop.open(before).payload == b"before"      # in flight across the rotation: still the old key
    assert laptop.open(after).payload == b"after"
    stale = Endpoint.from_state(phone.to_state() | {"revoked": False}, clock=phone.clock)
    with pytest.raises(Refused) as exc:
        stale.open(after)
    assert exc.value.code in ("unknown_epoch", "replay")
    # What the revoked device sends is refused by everyone still in the group.
    late = stale.seal("tx", b"{}", meta={"idem": "k-late-0001"}, to="home")[0]
    with pytest.raises(Refused) as exc:
        home.open(late)
    assert exc.value.code == "not_member"


def test_a_new_device_holds_no_key_from_before_it_joined():
    home, (laptop,), clock = group(1)
    old = home.seal("delta", b"old", meta={"seq": 1})[0]
    keys = Keys.generate()
    join = home.add_device(keys.public())
    newbie = Endpoint(keys=keys, mailbox=home.mailbox, home=home.me, clock=clock)
    assert newbie.open(join).kind == "epoch"
    assert set(newbie.epoch_keys) == {home.epoch}
    with pytest.raises(Refused) as exc:
        newbie.open(old)
    assert exc.value.code == "unknown_epoch"


def test_a_transaction_older_than_the_idempotency_window_is_refused():
    home, (laptop,), clock = group(1)
    frame = laptop.seal("tx", b"{}", meta={"idem": "k-0002-abcdef"}, to="home")[0]
    clock.t += 7 * 86_400 + 1
    with pytest.raises(Refused) as exc:
        home.open(frame)
    assert exc.value.code == "expired"


def test_a_large_payload_is_split_into_consecutive_parts_and_a_gap_is_refused():
    home, (laptop, phone), _ = group()
    payload = bytes(range(256)) * (3 * MAX_PART_PLAIN // 256)
    frames = home.seal("delta", payload, meta={"seq": 5})
    assert len(frames) == 4 and all(len(f) <= 1024 * 1024 for f in frames)
    got = [laptop.open(f) for f in frames]
    assert got[:-1] == [None] * 3 and got[-1].payload == payload
    phone.open(frames[0])
    with pytest.raises(Refused) as exc:
        phone.open(frames[2])
    assert exc.value.code == "gap"
    assert framed_size(len(payload)) >= sum(len(f) for f in frames) - 4 * 400


def test_a_bootstrap_over_80_mib_is_spooled_to_a_private_file_never_held_in_memory(tmp_path):
    """The owner's bootstrap is estimated near 90 MB; the device's cap matches the relay's 256 MiB stream bound."""
    import tracemalloc

    home, (laptop, phone), _ = group()
    bundle = tmp_path / "bootstrap.bundle"
    with open(bundle, "wb") as fh:
        for i in range(81):
            fh.write(bytes([i]) * MiB)
    laptop.spool_dir = str(tmp_path / "spool")
    tracemalloc.start()
    got = None
    for frame in home.seal_stream(str(bundle), meta={"seq": 7}):
        got = laptop.open(frame)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert got is not None and got.meta == {"seq": 7} and got.payload == b""
    assert Path(got.path).stat().st_size == 81 * MiB and filecmp.cmp(got.path, bundle, shallow=False)
    assert Path(got.path).parent == tmp_path / "spool" and (Path(got.path).stat().st_mode & 0o777) == 0o600
    assert peak < 16 * MiB, peak                                 # a few parts in flight, never the whole bundle
    # Without a spool directory a stream is refused, never assembled in memory.
    with pytest.raises(Refused) as exc:
        phone.open(next(iter(home.seal_stream(str(bundle), meta={"seq": 8}))))
    assert exc.value.code == "no_spool"
    assert MAX_STREAM_BYTES == Config().max_stream_bytes


def test_a_bootstrap_with_a_gap_leaves_no_spool_file(tmp_path):
    home, (laptop,), _ = group(1)
    laptop.spool_dir = str(tmp_path / "spool")
    frames = home.seal("stream", b"z" * (2 * MAX_PART_PLAIN), meta={"seq": 1})
    laptop.open(frames[0])
    assert len(list((tmp_path / "spool").iterdir())) == 1
    with pytest.raises(Refused):
        laptop.open(frames[2])
    assert list((tmp_path / "spool").iterdir()) == []


def test_the_home_moves_by_a_hand_off_its_devices_verify():
    home, (laptop, phone), clock = group()
    frame, record = home.hand_off(laptop.me)
    for dev in (laptop, phone):
        assert dev.open(frame).kind == "epoch" and dev.home == laptop.me
    new_home = Home.take_over(laptop, record)
    rotate = new_home.revoke(home.me)
    assert phone.open(rotate).kind == "epoch"
    assert phone.open(new_home.seal("delta", b"from the new home", meta={"seq": 100})[0]).payload == \
        b"from the new home"
    # The old home can no longer change the membership.
    old_try = Home.from_state(home.to_state(), clock=clock)
    old_try.home = old_try.me
    with pytest.raises(Refused):
        phone.open(old_try.add_device(Keys.generate().public()))


def test_after_a_hand_off_no_device_holds_a_key_older_than_the_epoch_it_joined():
    clock = Clock()
    home = Home.create(clock=clock)
    ka, kb = Keys.generate(), Keys.generate()
    a = Endpoint(keys=ka, mailbox=home.mailbox, home=home.me, clock=clock)
    a.open(home.add_device(ka.public()))                                    # A joins epoch 2
    before_b = home.seal("control", b"before B joined", meta={})[0]
    b = Endpoint(keys=kb, mailbox=home.mailbox, home=home.me, clock=clock)
    join = home.add_device(kb.public())                                     # B joins epoch 3
    a.open(join)
    b.open(join)
    b_joined = b.epoch
    frame, record = home.hand_off(a.me)
    a.open(frame)
    b.open(frame)
    clock.t += 9 * 86_400                                                   # past the 8-day retention
    new_home = Home.take_over(a, record)
    assert new_home.joined[b.me] == b_joined and new_home.started[2] == home.started[2]
    b.open(new_home.add_device(Keys.generate().public()))
    assert min(b.epoch_keys) >= b_joined
    b.hw.clear()
    with pytest.raises(Refused) as exc:
        b.open(before_b)
    assert exc.value.code == "unknown_epoch"
    # Retention is not restarted by the move: an epoch older than 8 days is not wrapped again.
    c_keys = Keys.generate()
    c = Endpoint(keys=c_keys, mailbox=home.mailbox, home=new_home.me, clock=clock)
    c.open(new_home.add_device(c_keys.public()))
    assert set(c.epoch_keys) == {new_home.epoch}


def test_take_over_needs_the_old_homes_record():
    home, (laptop, phone), _ = group()
    frame, record = home.hand_off(laptop.me)
    laptop.open(frame)
    phone.open(frame)
    with pytest.raises(TypeError):
        Home.take_over(laptop)                                              # required, never defaulted
    forged = SealedBox(PublicKey(b64d(laptop.keys.x_b64))).encrypt(canonical({"body": b64e(b"{}"), "sig": b64e(
        b"\x00" * 64)}))
    with pytest.raises(Refused) as exc:
        Home.take_over(laptop, forged)
    assert exc.value.code == "bad_handoff"
    with pytest.raises(Refused) as exc:
        Home.take_over(phone, record)                                        # not the device it names
    assert exc.value.code == "not_home"


def test_state_round_trips():
    home, (laptop,), clock = group(1)
    laptop.open(home.seal("delta", b"a", meta={"seq": 1})[0])
    again = Endpoint.from_state(laptop.to_state(), clock=clock)
    assert again.open(home.seal("delta", b"b", meta={"seq": 2})[0]).payload == b"b"
    home2 = Home.from_state(home.to_state(), clock=clock)
    assert again.open(home2.seal("delta", b"c", meta={"seq": 3})[0]).payload == b"c"


def test_a_restored_endpoint_clears_unfinished_streams_from_its_spool(tmp_path):
    home, (laptop,), clock = group(1)
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "stream-0123456789abcdef.part").write_bytes(b"half a bootstrap")
    (spool / "keep.txt").write_text("not ours")
    again = Endpoint.from_state(laptop.to_state(), clock=clock, spool_dir=str(spool))
    assert sorted(p.name for p in spool.iterdir()) == ["keep.txt"] and again.spool_dir == str(spool)
