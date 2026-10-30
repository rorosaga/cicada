"""The mailbox: one SQLite file, one log per bank, every bound enforced here (G132 phase 3a, gate g2).

What is stored is exactly what the relay was sent: whole frames (header, ciphertext, signature), the latest status
frame per sender, the latest membership frame per bank, and the pairing slots' sealed messages. There is no plaintext
column because there is no plaintext.

Bounds, all from ``Config``:

- a frame over ``max_frame_bytes`` is refused (``too_large``); one already past its TTL, counted from its own signed
  creation time, is refused (``expired``);
- deltas may fill the standing mailbox only up to ``max_bank_bytes - tx_reserve_bytes``; past that the oldest delta
  is evicted to make room (a device told it missed some asks the home for ``cursor..HEAD``);
- a transaction or control frame may use the whole ``max_bank_bytes``, evicting deltas, never another transaction;
  when only transactions are left it is refused ``relay_full`` and stays in its device's outbox;
- ``max_bank_frames`` the same way;
- the bootstrap stream: one per bank at a time (``stream_busy``), ``max_stream_bytes`` at most
  (``stream_too_large``), its own ``ttl_stream_s``, outside the standing budget;
- status frames are latest-only per sender, never queued; ``max_status_bytes`` each;
- a bank no device connected to for ``idle_purge_s`` is purged whole.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .config import Config

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS banks (
    mb TEXT PRIMARY KEY, home TEXT NOT NULL, epoch INTEGER NOT NULL, epoch_frame BLOB NOT NULL,
    created REAL NOT NULL, last_seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS members (
    mb TEXT NOT NULL, dev TEXT NOT NULL, hw INTEGER NOT NULL DEFAULT -1, dropped INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (mb, dev));
CREATE TABLE IF NOT EXISTS frames (
    rseq INTEGER PRIMARY KEY AUTOINCREMENT, mb TEXT NOT NULL, sender TEXT NOT NULL, kind TEXT NOT NULL,
    size INTEGER NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, stream TEXT, to_home INTEGER NOT NULL,
    raw BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS frames_mb ON frames (mb, kind, rseq);
CREATE INDEX IF NOT EXISTS frames_expires ON frames (expires);
CREATE TABLE IF NOT EXISTS recips (
    rseq INTEGER NOT NULL, mb TEXT NOT NULL, dev TEXT NOT NULL, PRIMARY KEY (mb, dev, rseq));
CREATE INDEX IF NOT EXISTS recips_rseq ON recips (rseq);
CREATE TABLE IF NOT EXISTS status (
    mb TEXT NOT NULL, sender TEXT NOT NULL, raw BLOB NOT NULL, expires REAL NOT NULL, PRIMARY KEY (mb, sender));
CREATE TABLE IF NOT EXISTS slots (
    slot TEXT PRIMARY KEY, mb TEXT NOT NULL, offer BLOB NOT NULL, expires REAL NOT NULL,
    msgs INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS slot_msgs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, slot TEXT NOT NULL, dir TEXT NOT NULL, body BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS totals (k TEXT PRIMARY KEY, bytes INTEGER NOT NULL);
INSERT OR IGNORE INTO totals VALUES ('frames', 0);
CREATE TRIGGER IF NOT EXISTS frames_in AFTER INSERT ON frames
    BEGIN UPDATE totals SET bytes = bytes + NEW.size WHERE k = 'frames'; END;
CREATE TRIGGER IF NOT EXISTS frames_out AFTER DELETE ON frames
    BEGIN UPDATE totals SET bytes = bytes - OLD.size WHERE k = 'frames'; END;
"""


class Refused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class Store:
    def __init__(self, path: str | Path, config: Config, clock=time.time):
        self.config = config
        self.clock = clock
        self.db = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.execute("PRAGMA synchronous=NORMAL")

    def close(self) -> None:
        self.db.close()

    # -- transactions -------------------------------------------------------------------------------------------
    def _tx(self):
        store = self

        class _T:
            def __enter__(self):
                store.db.execute("BEGIN IMMEDIATE")

            def __exit__(self, exc_type, exc, tb):
                store.db.execute("ROLLBACK" if exc_type else "COMMIT")
                return False
        return _T()

    # -- banks and members --------------------------------------------------------------------------------------
    def bank(self, mb: str) -> dict | None:
        row = self.db.execute("SELECT home, epoch, epoch_frame, last_seen FROM banks WHERE mb=?", (mb,)).fetchone()
        if not row:
            return None
        return {"home": row[0], "epoch": row[1], "epoch_frame": row[2], "last_seen": row[3]}

    def members(self, mb: str) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT dev FROM members WHERE mb=? ORDER BY dev", (mb,))]

    def is_member(self, mb: str, dev: str) -> bool:
        return self.db.execute("SELECT 1 FROM members WHERE mb=? AND dev=?", (mb, dev)).fetchone() is not None

    def create_bank(self, mb: str, statement: dict, frame_raw: bytes, ctr: int) -> None:
        now = self.clock()
        with self._tx():
            if self.db.execute("SELECT 1 FROM banks WHERE mb=?", (mb,)).fetchone():
                raise Refused("mailbox_exists")
            if self.db.execute("SELECT COUNT(*) FROM banks").fetchone()[0] >= self.config.max_banks:
                raise Refused("relay_full")
            self.db.execute("INSERT INTO banks VALUES (?,?,?,?,?,?)",
                            (mb, statement["home"], statement["epoch"], frame_raw, now, now))
            for d in statement["devices"]:
                self.db.execute("INSERT INTO members (mb, dev) VALUES (?,?)", (mb, d["ed"]))
            self.db.execute("UPDATE members SET hw=? WHERE mb=? AND dev=?", (ctr, mb, statement["home"]))

    def apply_epoch(self, mb: str, statement: dict, frame_raw: bytes) -> list[str]:
        """A newer membership from the bank's home: admit the listed devices, drop the rest with every frame still
        waiting for them or sent by them, and re-target queued transactions when the home moved. Returns the devices
        removed."""
        with self._tx():
            row = self.db.execute("SELECT home, epoch FROM banks WHERE mb=?", (mb,)).fetchone()
            if not row:
                raise Refused("unknown_mailbox")
            old_home, epoch = row
            if statement["epoch"] <= epoch:
                raise Refused("stale_epoch")
            new = {d["ed"] for d in statement["devices"]}
            old = set(self.members(mb))
            removed = sorted(old - new)
            for dev in removed:
                self.db.execute("DELETE FROM members WHERE mb=? AND dev=?", (mb, dev))
                self.db.execute("DELETE FROM recips WHERE mb=? AND dev=?", (mb, dev))
                self.db.execute("DELETE FROM recips WHERE rseq IN (SELECT rseq FROM frames WHERE mb=? AND sender=?)",
                                (mb, dev))
                self.db.execute("DELETE FROM status WHERE mb=? AND sender=?", (mb, dev))
            for dev in sorted(new - old):
                self.db.execute("INSERT INTO members (mb, dev) VALUES (?,?)", (mb, dev))
            if statement["home"] != old_home:
                # The new home holds its own outbox: what it sent the old home is not delivered back to it.
                self.db.execute("DELETE FROM recips WHERE rseq IN (SELECT rseq FROM frames WHERE mb=? AND to_home=1 "
                                "AND sender=?)", (mb, statement["home"]))
                self.db.execute(
                    "UPDATE OR IGNORE recips SET dev=? WHERE mb=? AND dev=? AND rseq IN "
                    "(SELECT rseq FROM frames WHERE mb=? AND to_home=1)", (statement["home"], mb, old_home, mb))
            self._drop_orphans(mb)
            self.db.execute("UPDATE banks SET home=?, epoch=?, epoch_frame=? WHERE mb=?",
                            (statement["home"], statement["epoch"], frame_raw, mb))
        return removed

    def bump_ctr(self, mb: str, sender: str, ctr: int) -> None:
        """A sender's counter only grows at the relay too (the devices enforce it again; the relay is untrusted)."""
        row = self.db.execute("SELECT hw FROM members WHERE mb=? AND dev=?", (mb, sender)).fetchone()
        if row is None:
            raise Refused("not_member")
        if ctr <= row[0]:
            raise Refused("replay")
        self.db.execute("UPDATE members SET hw=? WHERE mb=? AND dev=?", (ctr, mb, sender))

    def touch(self, mb: str) -> None:
        self.db.execute("UPDATE banks SET last_seen=? WHERE mb=?", (self.clock(), mb))

    # -- frames -------------------------------------------------------------------------------------------------
    def usage(self, mb: str) -> dict:
        rows = self.db.execute("SELECT kind, COUNT(*), COALESCE(SUM(size),0) FROM frames WHERE mb=? GROUP BY kind",
                               (mb,)).fetchall()
        by = {k: (n, s) for k, n, s in rows}
        standing = sum(s for k, (n, s) in by.items() if k != "stream")
        return {"bytes": standing, "delta_bytes": by.get("delta", (0, 0))[1],
                "frames": sum(n for n, _ in by.values()), "stream_bytes": by.get("stream", (0, 0))[1]}

    def put(self, mb: str, *, sender: str, kind: str, raw: bytes, created_at: float, recipients: list[str],
            to_home: bool, stream: str | None = None) -> tuple[int, dict[str, int]]:
        """Store one frame for ``recipients``; returns its relay sequence and the devices that lost a delta to
        eviction (with how many). Raises ``Refused``."""
        cfg = self.config
        now = self.clock()
        size = len(raw)
        if size > cfg.max_frame_bytes:
            raise Refused("too_large")
        if kind not in ("tx", "control", "delta", "stream"):
            raise Refused("bad_kind")
        if not recipients:
            raise Refused("no_recipient")
        if created_at > now + cfg.max_clock_skew_s:
            raise Refused("clock")
        expires = min(created_at, now) + cfg.ttl_for(kind)
        if expires <= now:
            raise Refused("expired")
        evicted: dict[str, int] = {}
        with self._tx():
            # Relay-wide first: a full relay refuses, it never evicts another bank's frames.
            if self.total_bytes() + size > cfg.max_total_bytes or self.db_bytes() + size > cfg.max_db_bytes:
                raise Refused("relay_full")
            use = self.usage(mb)
            if kind == "stream":
                active = self.db.execute("SELECT DISTINCT stream FROM frames WHERE mb=? AND kind='stream'",
                                         (mb,)).fetchall()
                if active and any(a[0] != stream for a in active):
                    raise Refused("stream_busy")
                if use["stream_bytes"] + size > cfg.max_stream_bytes:
                    raise Refused("stream_too_large")
                if use["frames"] + 1 > cfg.max_bank_frames and not self._evict_delta(mb, evicted):
                    raise Refused("relay_full")
            else:
                while True:
                    use = self.usage(mb)
                    over_total = use["bytes"] + size > cfg.max_bank_bytes
                    over_count = use["frames"] + 1 > cfg.max_bank_frames
                    over_delta = kind == "delta" and use["delta_bytes"] + size > cfg.max_bank_bytes - cfg.tx_reserve_bytes
                    if not (over_total or over_count or over_delta):
                        break
                    if not self._evict_delta(mb, evicted):
                        raise Refused("relay_full")
            cur = self.db.execute(
                "INSERT INTO frames (mb, sender, kind, size, created, expires, stream, to_home, raw) "
                "VALUES (?,?,?,?,?,?,?,?,?)", (mb, sender, kind, size, now, expires, stream, int(to_home), raw))
            rseq = cur.lastrowid
            self.db.executemany("INSERT INTO recips (rseq, mb, dev) VALUES (?,?,?)",
                                [(rseq, mb, dev) for dev in recipients])
        return rseq, evicted

    def _evict_delta(self, mb: str, evicted: dict[str, int]) -> bool:
        row = self.db.execute("SELECT rseq FROM frames WHERE mb=? AND kind='delta' ORDER BY rseq LIMIT 1",
                              (mb,)).fetchone()
        if not row:
            return False
        for (dev,) in self.db.execute("SELECT dev FROM recips WHERE rseq=?", (row[0],)).fetchall():
            self.db.execute("UPDATE members SET dropped=dropped+1 WHERE mb=? AND dev=?", (mb, dev))
            evicted[dev] = evicted.get(dev, 0) + 1
        self.db.execute("DELETE FROM recips WHERE rseq=?", (row[0],))
        self.db.execute("DELETE FROM frames WHERE rseq=?", (row[0],))
        return True

    def total_bytes(self) -> int:
        return self.db.execute("SELECT bytes FROM totals WHERE k='frames'").fetchone()[0]

    def db_bytes(self) -> int:
        pages = self.db.execute("PRAGMA page_count").fetchone()[0]
        return pages * self.db.execute("PRAGMA page_size").fetchone()[0]

    def pending(self, mb: str, dev: str, after: int = 0, limit: int = 256,
                max_bytes: int | None = None) -> list[tuple[int, int]]:
        """``(relay seq, size)`` of what waits for ``dev``, oldest first, at most ``max_bytes`` of frames a batch
        (always at least one). The bytes themselves are read one frame at a time by ``frame``."""
        cap = self.config.flush_batch_bytes if max_bytes is None else max_bytes
        rows = self.db.execute(
            "SELECT f.rseq, f.size FROM recips r JOIN frames f ON f.rseq = r.rseq "
            "WHERE r.mb=? AND r.dev=? AND r.rseq>? AND f.expires>? ORDER BY r.rseq LIMIT ?",
            (mb, dev, after, self.clock(), limit)).fetchall()
        out, total = [], 0
        for rseq, size in rows:
            if out and total + size > cap:
                break
            out.append((rseq, size))
            total += size
        return out

    def frame(self, rseq: int) -> bytes | None:
        row = self.db.execute("SELECT raw FROM frames WHERE rseq=?", (rseq,)).fetchone()
        return None if row is None else row[0]

    def ack(self, mb: str, dev: str, upto: int) -> None:
        with self._tx():
            self.db.execute("DELETE FROM recips WHERE mb=? AND dev=? AND rseq<=?", (mb, dev, upto))
            self._drop_orphans(mb)

    def supersede(self, mb: str, home: str, dev: str, upto: int) -> int:
        """The home coalesces: deltas it sent that still wait for ``dev``, up to relay seq ``upto``, are replaced by
        one ``cursor..HEAD`` bundle it sends next. Only deltas, only the home's own. Returns how many were dropped."""
        with self._tx():
            n = self.db.execute(
                "DELETE FROM recips WHERE mb=? AND dev=? AND rseq<=? AND rseq IN "
                "(SELECT rseq FROM frames WHERE mb=? AND sender=? AND kind='delta')", (mb, dev, upto, mb, home)).rowcount
            self._drop_orphans(mb)
        return n

    def _drop_orphans(self, mb: str) -> None:
        self.db.execute("DELETE FROM frames WHERE mb=? AND rseq NOT IN (SELECT rseq FROM recips WHERE mb=?)",
                        (mb, mb))

    def counts(self, mb: str) -> dict[str, int]:
        """Frames still on their way, per sending device: metadata the relay holds anyway (ruling 51d)."""
        return {s: n for s, n in self.db.execute(
            "SELECT sender, COUNT(*) FROM frames WHERE mb=? AND expires>? GROUP BY sender", (mb, self.clock()))}

    def take_dropped(self, mb: str, dev: str) -> int:
        row = self.db.execute("SELECT dropped FROM members WHERE mb=? AND dev=?", (mb, dev)).fetchone()
        if not row or not row[0]:
            return 0
        self.db.execute("UPDATE members SET dropped=0 WHERE mb=? AND dev=?", (mb, dev))
        return row[0]

    # -- status (latest only) -----------------------------------------------------------------------------------
    def put_status(self, mb: str, sender: str, raw: bytes, created_at: float) -> None:
        now = self.clock()
        if len(raw) > self.config.max_status_bytes:
            raise Refused("too_large")
        if created_at > now + self.config.max_clock_skew_s:
            raise Refused("clock")
        self.db.execute("INSERT OR REPLACE INTO status VALUES (?,?,?,?)",
                        (mb, sender, raw, min(created_at, now) + self.config.ttl_status_s))

    def statuses(self, mb: str, exclude: str) -> list[bytes]:
        return [r[0] for r in self.db.execute(
            "SELECT raw FROM status WHERE mb=? AND sender<>? AND expires>? ORDER BY sender",
            (mb, exclude, self.clock()))]

    # -- pairing slots ------------------------------------------------------------------------------------------
    def open_slot(self, slot: str, mb: str, offer: bytes, ttl: float) -> None:
        cfg = self.config
        now = self.clock()
        if len(offer) > cfg.pair_max_bytes:
            raise Refused("too_large")
        with self._tx():
            self.db.execute("DELETE FROM slots WHERE expires<=?", (now,))
            if self.db.execute("SELECT 1 FROM slots WHERE slot=?", (slot,)).fetchone():
                raise Refused("slot_taken")
            if self.db.execute("SELECT COUNT(*) FROM slots WHERE mb=?", (mb,)).fetchone()[0] >= cfg.pair_slots_per_bank:
                raise Refused("too_many_slots")
            self.db.execute("INSERT INTO slots (slot, mb, offer, expires) VALUES (?,?,?,?)",
                            (slot, mb, offer, now + min(float(ttl), cfg.pair_ttl_s)))

    def slot(self, slot: str) -> dict | None:
        row = self.db.execute("SELECT mb, offer, expires, msgs FROM slots WHERE slot=? AND expires>?",
                              (slot, self.clock())).fetchone()
        return None if not row else {"mb": row[0], "offer": row[1], "expires": row[2], "msgs": row[3]}

    def count_slot_msg(self, slot: str, body: bytes) -> None:
        if len(body) > self.config.pair_max_bytes:
            raise Refused("too_large")
        row = self.slot(slot)
        if row is None:
            raise Refused("unknown_slot")
        if row["msgs"] >= self.config.pair_max_msgs:
            raise Refused("slot_exhausted")
        self.db.execute("UPDATE slots SET msgs=msgs+1 WHERE slot=?", (slot,))

    def queue_slot_msg(self, slot: str, direction: str, body: bytes) -> None:
        self.db.execute("INSERT INTO slot_msgs (slot, dir, body) VALUES (?,?,?)", (slot, direction, body))

    def take_slot_msgs(self, slot: str, direction: str) -> list[bytes]:
        with self._tx():
            rows = self.db.execute("SELECT id, body FROM slot_msgs WHERE slot=? AND dir=? ORDER BY id",
                                   (slot, direction)).fetchall()
            self.db.execute("DELETE FROM slot_msgs WHERE slot=? AND dir=?", (slot, direction))
        return [r[1] for r in rows]

    def slots_of(self, mb: str) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT slot FROM slots WHERE mb=? AND expires>?", (mb, self.clock()))]

    def close_slot(self, slot: str) -> None:
        with self._tx():
            self.db.execute("DELETE FROM slots WHERE slot=?", (slot,))
            self.db.execute("DELETE FROM slot_msgs WHERE slot=?", (slot,))

    # -- expiry -------------------------------------------------------------------------------------------------
    def purge(self, online: set[str] | frozenset = frozenset()) -> dict[str, int]:
        """Expired frames, statuses and slots; banks idle past ``idle_purge_s`` (a bank with a device online now is
        never idle)."""
        now = self.clock()
        out = {}
        with self._tx():
            for mb in online:
                self.db.execute("UPDATE banks SET last_seen=? WHERE mb=?", (now, mb))
            expired = self.db.execute("SELECT rseq FROM frames WHERE expires<=?", (now,)).fetchall()
            self.db.executemany("DELETE FROM recips WHERE rseq=?", expired)
            self.db.execute("DELETE FROM frames WHERE expires<=?", (now,))
            out["frames"] = len(expired)
            out["status"] = self.db.execute("DELETE FROM status WHERE expires<=?", (now,)).rowcount
            gone = [r[0] for r in self.db.execute("SELECT slot FROM slots WHERE expires<=?", (now,))]
            for slot in gone:
                self.db.execute("DELETE FROM slot_msgs WHERE slot=?", (slot,))
            self.db.execute("DELETE FROM slots WHERE expires<=?", (now,))
            out["slots"] = len(gone)
            idle = [r[0] for r in self.db.execute("SELECT mb FROM banks WHERE last_seen<=?",
                                                  (now - self.config.idle_purge_s,))]
            for mb in idle:
                for table in ("frames", "recips", "members", "status", "slots", "banks"):
                    self.db.execute(f"DELETE FROM {table} WHERE mb=?", (mb,))
            out["banks"] = len(idle)
        return out
