"""Every bound the relay enforces, each configurable by an environment variable (``RELAY_<NAME>``, upper case).

The defaults are the G132 phase 3 research's bounds (gate g2), confirmed against measured bundle sizes in
``benchmarks/scale/relay_bundles.py`` (network.md, "The relay: built on localhost, not deployed").
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields

MiB = 1024 * 1024
DAY = 86_400


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    port: int = 8443
    db_path: str = "relay.db"
    tls_cert: str = ""
    tls_key: str = ""
    #: Largest frame (header + ciphertext + signature). Larger payloads are split into parts by the sender.
    max_frame_bytes: int = 1 * MiB
    #: Standing mailbox per bank: every stored frame but the bootstrap stream and the latest-only status frames.
    max_bank_bytes: int = 128 * MiB
    #: Of that, what deltas may never take: room only transactions and control frames may use.
    tx_reserve_bytes: int = 16 * MiB
    max_bank_frames: int = 20_000
    #: The bootstrap: one stream per bank at a time, this large at most, gone after its TTL. 256 MiB, not the
    #: research's 64: a synthetic owner-scale bank's full bundle measured 53 MB (its .git 89 MB), and the owner's real
    #: .git is 147 MB, so its bundle is estimated near 90 MB (network.md, "The mailbox").
    max_stream_bytes: int = 256 * MiB
    ttl_stream_s: int = 1 * DAY
    #: Counted from the frame's own signed creation time, so a transaction that sat in a device's outbox is never kept
    #: past the home's 8-day idempotency window.
    ttl_tx_s: int = 7 * DAY
    ttl_control_s: int = 7 * DAY
    ttl_delta_s: int = 7 * DAY
    ttl_status_s: int = 7 * DAY
    max_status_bytes: int = 16 * 1024
    #: A bank no device has connected to for this long is purged whole; its home re-creates it from its statement.
    idle_purge_s: int = 30 * DAY
    purge_interval_s: int = 60
    #: A frame dated later than this past the relay's clock is refused.
    max_clock_skew_s: int = 300
    #: Pairing: an open slot lives at most this long and carries at most this many messages, each this large.
    pair_ttl_s: int = 600
    pair_max_msgs: int = 8
    pair_max_bytes: int = 16 * 1024
    pair_slots_per_bank: int = 2
    max_connections_per_bank: int = 16
    max_unauthenticated: int = 256
    handshake_timeout_s: float = 10.0
    max_banks: int = 100_000
    #: Relay-wide: every stored frame of every bank (streams included), kept as a running total by SQLite triggers,
    #: and the database file itself. Either one full answers ``relay_full``; no bank evicts another's frames.
    max_total_bytes: int = 16 * 1024 * MiB
    max_db_bytes: int = 20 * 1024 * MiB
    #: A flush reads at most this many bytes of frames per batch, one frame's bytes at a time as it is sent.
    flush_batch_bytes: int = 4 * MiB
    #: Creating a bank needs no credential (the home's own key is the bank's root of trust), so creation is limited:
    #: one per connection by construction (one hello), and this many per remote address per hour. The address is
    #: held in memory only for that count, never logged or stored.
    creates_per_ip_per_hour: int = 5
    max_unauthenticated_per_ip: int = 16

    @classmethod
    def from_env(cls, env: dict | None = None, **overrides) -> "Config":
        env = os.environ if env is None else env
        values: dict = {}
        for f in fields(cls):
            raw = env.get("RELAY_" + f.name.upper())
            if raw is None or raw == "":
                continue
            values[f.name] = type(f.default)(raw) if not isinstance(f.default, bool) else raw.lower() in ("1", "on")
        values.update(overrides)
        return cls(**values)

    def ttl_for(self, kind: str) -> int:
        return {"tx": self.ttl_tx_s, "control": self.ttl_control_s, "delta": self.ttl_delta_s,
                "status": self.ttl_status_s, "stream": self.ttl_stream_s}[kind]
