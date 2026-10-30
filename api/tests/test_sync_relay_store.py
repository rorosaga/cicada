"""G132 phase 3a — the relay's mailbox bounds (gate g2): every bound refuses or evicts as network.md says, and every one
is configurable. Small bounds stand in for the defaults so each edge is reached in a few frames."""
from __future__ import annotations

import pytest

from _relay import Clock, Config, MiB, Store, StoreRefused

DAY = 86_400
H, A, B = "home-key", "laptop-key", "phone-key"


def make(tmp_path, **bounds):
    tmp_path.mkdir(parents=True, exist_ok=True)
    clock = Clock()
    cfg = Config(**({"max_frame_bytes": 1000, "max_bank_bytes": 10_000, "tx_reserve_bytes": 4_000,
                     "max_bank_frames": 100, "max_stream_bytes": 3_000} | bounds))
    store = Store(tmp_path / "relay.db", cfg, clock)
    store.create_bank("mb", {"home": H, "epoch": 1, "devices": [{"ed": H}, {"ed": A}, {"ed": B}]}, b"epoch-1", 0)
    return store, clock


def put(store, kind, size, sender=A, to=(H,), at=None, stream=None):
    return store.put("mb", sender=sender, kind=kind, raw=b"\x01" * size,
                     created_at=store.clock() if at is None else at, recipients=list(to), to_home=to == (H,),
                     stream=stream)[0]


def code(fn):
    with pytest.raises(StoreRefused) as exc:
        fn()
    return exc.value.code


def test_every_bound_is_read_from_the_environment():
    cfg = Config.from_env({"RELAY_MAX_FRAME_BYTES": "2048", "RELAY_TTL_TX_S": "60", "RELAY_PORT": "9000"})
    assert (cfg.max_frame_bytes, cfg.ttl_tx_s, cfg.port) == (2048, 60, 9000)
    d = Config()
    assert (d.max_frame_bytes, d.max_bank_bytes, d.tx_reserve_bytes, d.max_bank_frames) == (MiB, 128 * MiB,
                                                                                            16 * MiB, 20_000)
    assert (d.max_stream_bytes, d.ttl_stream_s, d.ttl_tx_s, d.idle_purge_s) == (256 * MiB, DAY, 7 * DAY, 30 * DAY)


def test_a_frame_over_the_per_frame_max_is_refused(tmp_path):
    store, _ = make(tmp_path)
    assert code(lambda: put(store, "tx", 1001)) == "too_large"
    assert put(store, "tx", 1000) > 0


def test_deltas_never_take_the_transactions_reserve_and_the_oldest_goes_first(tmp_path):
    store, _ = make(tmp_path)
    first = put(store, "delta", 1000, sender=H, to=(A,))
    for _ in range(5):
        put(store, "delta", 1000, sender=H, to=(A,))
    assert store.usage("mb")["delta_bytes"] == 6000          # 10 000 total - 4 000 reserve
    put(store, "delta", 1000, sender=H, to=(A,))
    rows = store.pending("mb", A)
    assert len(rows) == 6 and rows[0][0] == first + 1          # the oldest delta was evicted
    assert store.take_dropped("mb", A) == 1 and store.take_dropped("mb", A) == 0


def test_a_transaction_evicts_deltas_but_never_another_transaction(tmp_path):
    store, _ = make(tmp_path)
    for _ in range(4):
        put(store, "tx", 1000)
    for _ in range(6):
        put(store, "delta", 1000, sender=H, to=(A,))
    assert store.usage("mb")["bytes"] == 10_000
    put(store, "tx", 1000)                                      # room made by dropping a delta
    assert store.usage("mb")["delta_bytes"] == 5000
    for _ in range(5):
        put(store, "tx", 1000)
    assert store.usage("mb")["delta_bytes"] == 0
    assert code(lambda: put(store, "tx", 1000)) == "relay_full"   # only transactions left: refused, kept on device
    assert len(store.pending("mb", H)) == 10


def test_the_frame_count_is_bounded_the_same_way(tmp_path):
    store, _ = make(tmp_path, max_bank_frames=3)
    put(store, "delta", 10, sender=H, to=(A,))
    put(store, "tx", 10)
    put(store, "tx", 10)
    put(store, "tx", 10)
    assert store.usage("mb")["frames"] == 3 and store.usage("mb")["delta_bytes"] == 0
    assert code(lambda: put(store, "tx", 10)) == "relay_full"


def test_one_bootstrap_at_a_time_bounded_and_short_lived(tmp_path):
    store, clock = make(tmp_path)
    put(store, "stream", 1000, sender=H, to=(A,), stream="s1")
    put(store, "stream", 1000, sender=H, to=(A,), stream="s1")
    assert code(lambda: put(store, "stream", 10, sender=H, to=(B,), stream="s2")) == "stream_busy"
    put(store, "stream", 1000, sender=H, to=(A,), stream="s1")
    assert code(lambda: put(store, "stream", 1, sender=H, to=(A,), stream="s1")) == "stream_too_large"
    assert store.usage("mb")["bytes"] == 0                      # outside the standing mailbox
    clock.t += DAY
    store.purge()
    assert store.usage("mb")["stream_bytes"] == 0
    put(store, "stream", 10, sender=H, to=(B,), stream="s2")    # the next bootstrap may start


def test_ttl_counts_from_the_frames_own_creation_time(tmp_path):
    store, clock = make(tmp_path)
    put(store, "tx", 10, at=clock.t - 6 * DAY)                   # sat six days in a device's outbox
    put(store, "tx", 10)
    assert code(lambda: put(store, "tx", 10, at=clock.t - 7 * DAY)) == "expired"
    assert code(lambda: put(store, "tx", 10, at=clock.t + 3600)) == "clock"
    clock.t += DAY
    assert store.purge()["frames"] == 1 and len(store.pending("mb", H)) == 1
    clock.t += 6 * DAY
    assert store.purge()["frames"] == 1 and store.pending("mb", H) == []


def test_status_is_latest_only_and_bounded(tmp_path):
    store, clock = make(tmp_path, max_status_bytes=100)
    store.put_status("mb", H, b"status-1", clock.t)
    store.put_status("mb", H, b"status-2", clock.t)
    store.put_status("mb", A, b"laptop", clock.t)
    assert store.statuses("mb", exclude=A) == [b"status-2"]
    assert store.usage("mb")["frames"] == 0
    assert code(lambda: store.put_status("mb", H, b"x" * 101, clock.t)) == "too_large"


def test_counts_per_sender_and_ack_frees_the_frame(tmp_path):
    store, _ = make(tmp_path)
    r1 = put(store, "tx", 10)
    put(store, "tx", 10)
    put(store, "tx", 10, sender=B)
    put(store, "delta", 10, sender=H, to=(A, B))
    assert store.counts("mb") == {A: 2, B: 1, H: 1}
    store.ack("mb", H, r1)
    assert store.counts("mb") == {A: 1, B: 1, H: 1}
    rows = store.pending("mb", A)
    store.ack("mb", A, rows[-1][0])
    assert store.counts("mb")[H] == 1                            # the phone has not read it yet
    store.ack("mb", B, rows[-1][0])
    assert H not in store.counts("mb")


def test_a_bank_idle_for_thirty_days_is_purged_whole(tmp_path):
    store, clock = make(tmp_path)
    put(store, "tx", 10)
    clock.t += 29 * DAY
    store.purge(online={"mb"})                                   # a device online keeps it
    clock.t += 29 * DAY
    assert store.purge()["banks"] == 0
    clock.t += 2 * DAY
    assert store.purge()["banks"] == 1 and store.bank("mb") is None and store.members("mb") == []


def test_revoke_drops_the_device_with_what_it_sent_and_what_waited_for_it(tmp_path):
    store, _ = make(tmp_path)
    put(store, "tx", 10, sender=B)
    put(store, "delta", 10, sender=H, to=(A, B))
    removed = store.apply_epoch("mb", {"home": H, "epoch": 2, "devices": [{"ed": H}, {"ed": A}]}, b"epoch-2")
    assert removed == [B] and not store.is_member("mb", B) and store.pending("mb", B) == []
    assert store.pending("mb", H) == [] and store.counts("mb") == {H: 1}
    assert code(lambda: store.apply_epoch("mb", {"home": H, "epoch": 2, "devices": [{"ed": H}]}, b"x")) == \
        "stale_epoch"


def test_a_hand_off_re_targets_queued_transactions_to_the_new_home(tmp_path):
    store, _ = make(tmp_path)
    put(store, "tx", 10, sender=B)
    put(store, "tx", 10, sender=A)
    put(store, "delta", 10, sender=H, to=(A, B))
    store.apply_epoch("mb", {"home": A, "epoch": 2, "devices": [{"ed": H}, {"ed": A}, {"ed": B}]}, b"epoch-2")
    assert store.bank("mb")["home"] == A and store.pending("mb", H) == []
    # B's transaction now waits for the new home; A's own is in A's outbox, never delivered back to it.
    assert [r[0] for r in store.pending("mb", A)] == [1, 3]


def test_a_senders_counter_only_grows_at_the_relay(tmp_path):
    store, _ = make(tmp_path)
    store.bump_ctr("mb", A, 5)
    assert code(lambda: store.bump_ctr("mb", A, 5)) == "replay"
    assert code(lambda: store.bump_ctr("mb", A, 4)) == "replay"
    assert code(lambda: store.bump_ctr("mb", "stranger", 9)) == "not_member"


def test_pairing_slots_are_bounded(tmp_path):
    store, clock = make(tmp_path, pair_slots_per_bank=1, pair_max_msgs=2, pair_max_bytes=100)
    store.open_slot("slot-a", "mb", b"offer", ttl=9999)
    assert store.slot("slot-a")["expires"] == clock.t + 600       # capped at the code's ten minutes
    assert code(lambda: store.open_slot("slot-b", "mb", b"offer", ttl=60)) == "too_many_slots"
    store.count_slot_msg("slot-a", b"1")
    store.count_slot_msg("slot-a", b"2")
    assert code(lambda: store.count_slot_msg("slot-a", b"3")) == "slot_exhausted"
    assert code(lambda: store.count_slot_msg("slot-a", b"x" * 101)) == "too_large"
    clock.t += 601
    assert store.slot("slot-a") is None


def test_the_home_supersedes_only_its_own_deltas_for_one_device(tmp_path):
    store, _ = make(tmp_path)
    d1 = put(store, "delta", 10, sender=H, to=(A, B))
    put(store, "tx", 10, sender=B)
    d2 = put(store, "delta", 10, sender=H, to=(A,))
    d3 = put(store, "delta", 10, sender=H, to=(A,))
    assert store.supersede("mb", H, A, d2) == 2
    assert [r[0] for r in store.pending("mb", A)] == [d3]
    assert [r[0] for r in store.pending("mb", B)] == [d1]          # the phone still needs the first
    assert len(store.pending("mb", H)) == 1                         # a transaction is never superseded


def test_a_relay_wide_byte_budget_refuses_any_bank_and_its_count_follows_every_delete(tmp_path):
    store, clock = make(tmp_path, max_total_bytes=3_000)
    store.create_bank("mb2", {"home": H, "epoch": 1, "devices": [{"ed": H}, {"ed": A}]}, b"epoch-1", 0)
    r1 = put(store, "tx", 1000)
    put(store, "delta", 1000, sender=H, to=(A,))
    store.put("mb2", sender=A, kind="tx", raw=b"x" * 1000, created_at=clock.t, recipients=[H], to_home=True)
    assert store.total_bytes() == 3000
    assert code(lambda: store.put("mb2", sender=A, kind="tx", raw=b"x", created_at=clock.t, recipients=[H],
                                  to_home=True)) == "relay_full"
    assert code(lambda: put(store, "delta", 10, sender=H, to=(A,))) == "relay_full"   # never evicts across banks
    store.ack("mb", H, r1)                                         # every delete path moves the running total
    assert store.total_bytes() == 2000
    clock.t += 8 * DAY
    store.purge()
    assert store.total_bytes() == 0


def test_the_database_file_has_a_cap_too(tmp_path):
    store, _ = make(tmp_path, max_db_bytes=1)
    assert code(lambda: put(store, "tx", 10)) == "relay_full"


def test_a_flush_batch_is_capped_in_bytes_and_carries_only_sizes(tmp_path):
    store, _ = make(tmp_path, flush_batch_bytes=2_500)
    for _ in range(10):
        put(store, "tx", 1000)
    rows = store.pending("mb", H)
    assert [size for _, size in rows] == [1000, 1000]
    assert store.frame(rows[0][0]) == b"\x01" * 1000
    big, _ = make(tmp_path / "big", flush_batch_bytes=10)
    put(big, "tx", 1000)
    assert len(big.pending("mb", H)) == 1                           # always at least one frame


def test_a_bank_its_home_never_came_back_to_is_purged_after_two_days(tmp_path):
    """G132 phase 3b (pre-go-live): a create costs nothing, so a bank nobody connected to again does not hold a row for
    a month. One later connection — the home's or any device's — makes it an ordinary bank again."""
    store, clock = make(tmp_path)
    store.create_bank("mb-kept", {"home": H, "epoch": 1, "devices": [{"ed": H}]}, b"epoch-1", 0)
    clock.t += DAY
    store.connected("mb-kept")
    clock.t += DAY + 1
    out = store.purge()
    assert out["banks"] == 1 and store.bank("mb") is None          # never reconnected: gone after two days
    assert store.bank("mb-kept") is not None                        # reconnected once: the 30-day rule holds
    assert Config().unconfirmed_purge_s == 2 * DAY
