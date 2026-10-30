"""G132 phase 3a — the relay's credential-free doors (bank creation, unauthenticated sockets) are limited per network:
an IPv6 /64 is one key, the create table is hard-capped and O(1) at the cap, only a created bank counts, and a proxy's
forwarded address is believed only from a configured proxy."""
from __future__ import annotations

import time

from _relay import Clock, Config, Relay  # noqa: F401 — puts the relay package on the path
from cicada_relay import limits


def test_an_ipv6_64_is_one_key_and_ipv4_its_own_address():
    assert limits.net_key("2001:db8:1:1::1") == limits.net_key("2001:db8:1:1:ffff:ffff:ffff:ffff") == \
        "2001:db8:1:1::/64"
    assert limits.net_key("2001:db8:1:2::1") != limits.net_key("2001:db8:1:1::1")
    assert limits.net_key("203.0.113.7") == "203.0.113.7" != limits.net_key("203.0.113.8")
    assert limits.net_key("::ffff:203.0.113.7") == "203.0.113.7"
    assert limits.net_key("fe80::1%en0") == "fe80::/64"
    assert limits.net_key("not an address") == "?"


def test_many_addresses_from_one_64_share_the_hourly_cap(tmp_path):
    clock = Clock()
    relay = Relay(Config(db_path=str(tmp_path / "relay.db"), creates_per_ip_per_hour=5), clock=clock)
    allowed = 0
    for i in range(100_000 // 50):                      # a fresh source address per attempt, as in the review's repro
        key = limits.net_key(f"2001:db8:1:1::{i:x}")
        if relay._creates.allow(key):
            relay._creates.record(key)
            allowed += 1
    assert allowed == 5 and len(relay._creates.table) == 1
    clock.t += 3600
    assert relay._creates.allow(limits.net_key("2001:db8:1:1::abcd"))
    relay.store.close()


def test_only_a_created_bank_counts():
    lim = limits.CreateLimiter(per_window=2, max_keys=10, clock=Clock())
    for _ in range(50):                                  # failed attempts: allow() is asked, nothing is recorded
        assert lim.allow("203.0.113.7")
    assert lim.table == {}
    lim.record("203.0.113.7")
    lim.record("203.0.113.7")
    assert not lim.allow("203.0.113.7")


def test_the_table_is_hard_capped_and_a_call_at_the_cap_is_constant_time():
    clock = Clock()
    lim = limits.CreateLimiter(per_window=5, max_keys=50_000, clock=clock)
    for i in range(50_000):
        lim.record(f"10.{i >> 16 & 255}.{i >> 8 & 255}.{i & 255}")
    assert len(lim.table) == 50_000
    # Full and nothing expired: a new network is refused, without a scan and without forgetting anyone's count.
    started = time.perf_counter()
    for i in range(2_000):
        assert not lim.allow(f"198.51.100.{i % 250}")
    per_call = (time.perf_counter() - started) / 2_000
    assert per_call < 50e-6, per_call                  # a scan of 50,000 entries costs milliseconds
    assert len(lim.table) == 50_000 and lim.allow("10.0.0.0")
    # An hour on, the oldest windows pop off the front one at a time and room is made.
    clock.t += 3600
    assert lim.allow("198.51.100.1")
    lim.record("198.51.100.1")
    assert len(lim.table) <= 50_000


def test_a_forwarded_address_is_believed_only_from_a_trusted_proxy():
    trusted = limits.parse_networks("127.0.0.1/32, ::1")
    headers = {"X-Forwarded-For": "198.51.100.9, 203.0.113.7"}
    assert limits.client_ip("127.0.0.1", headers, trusted) == "203.0.113.7"    # the hop the proxy appended
    assert limits.client_ip("192.0.2.1", headers, trusted) == "192.0.2.1"      # anyone else's header is ignored
    assert limits.client_ip("127.0.0.1", headers, []) == "127.0.0.1"           # off by default
    assert limits.client_ip("127.0.0.1", {"X-Forwarded-For": "junk"}, trusted) == "127.0.0.1"
    assert Config().trusted_proxies == ""
