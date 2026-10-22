"""Per-device tokens for a server's own clients (G181 phase 2, owner ruling 1, 2026-10-16).

A second device of the person's (their Mac talking to their home server over an overlay they run) never gets the
server's master token (``$CICADA_HOME/api_token``). Each device gets its own **named, hashed, revocable** token,
issued only by an act of the person: ``cicada device add <name>`` on the server, or ``POST /devices`` with the master
token. Never automatic, never by an installer, never by a device token.

The store is G135's connector store's shape (``api/remote/store.py``), kept apart because the two mean different
things: a connector is a remote app, never trusted to edit a page and never the person's words; a device is the
person's own machine, which counts as local for the G198 trust list (owner ruling 3). ``$CICADA_HOME/devices/`` (0700)
holds ``devices.db`` (sqlite WAL, 0600), outside every bank. A token is ``cic_dev_<id>_<secret>``: the id gives an
O(1) lookup and makes the token greppable by secret scanners; the secret is 256 bits and only its sha256 is stored,
compared with ``hmac.compare_digest``, so the token exists in exactly one answer — the one that issued it. Every
column is an id, a timestamp or a count, except ``name`` (the one person-typed field: printable, at most 40
characters). A device token does not expire — the person's own machine, like the master token — and revoking it ends
it at once: the next request it signs is a 401.

How the server knows a request came through a device token: the auth dependency (``auth.require_token``) looks the
bearer up here and records the device on ``request.state.device``. Nothing a client sends in a header or a body can
claim a device; the token is the only evidence.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import string
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.services.auth import cicada_home

PREFIX = "cic_dev_"
TOKEN_RE = re.compile(r"^cic_dev_([a-z0-9]{8})_([A-Za-z0-9_-]{43})$")
ID_RE = re.compile(r"^[a-z0-9]{8}$")
_ID_ALPHABET = string.ascii_lowercase + string.digits
NAME_MAX = 40
#: ``last_used_at`` is written at most this often per device, so a hook firing after every reply is not a write each.
TOUCH_EVERY_S = 60.0
_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT,
    last_used_at TEXT,
    use_count INTEGER NOT NULL DEFAULT 0
)"""
#: G212: one-time pairing codes. A code is the credential a new device (a phone, another machine) trades ONCE for its
#: own device token; only its sha256 is kept, it lives ten minutes, and it is spent by the first redeem that names it.
_PAIRING_SCHEMA = """
CREATE TABLE IF NOT EXISTS pairings (
    id TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    cancelled_at TEXT,
    device_id TEXT
)"""
#: Unambiguous when read off a screen or typed: no I, L, O, 0 or 1. 31 symbols, 8 of them: about 40 bits — with a
#: ten-minute life, single use and a wrong-code bucket at the door, out of reach of guessing.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
PAIRING_TTL_S = 600
MAX_OPEN_PAIRINGS = 5


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    created_at: str
    revoked_at: str | None = None
    last_used_at: str | None = None
    use_count: int = 0

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    def wire(self) -> dict:
        return {"id": self.id, "name": self.name, "createdAt": self.created_at, "revokedAt": self.revoked_at,
                "lastUsedAt": self.last_used_at, "useCount": self.use_count, "active": self.active}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("ascii")).hexdigest()


def clean_name(raw: str | None) -> str:
    """The person's name for the device: printable, trimmed, at most 40 characters; ``ValueError`` when empty."""
    name = "".join(ch for ch in (raw or "") if ch.isprintable()).strip()[:NAME_MAX].strip()
    if not name:
        raise ValueError("Give the device a name (for example, the laptop it is).")
    return name


def store_dir() -> Path:
    path = cicada_home() / "devices"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _row(row: sqlite3.Row) -> Device:
    return Device(id=row["id"], name=row["name"], created_at=row["created_at"], revoked_at=row["revoked_at"],
                  last_used_at=row["last_used_at"], use_count=int(row["use_count"] or 0))


_touched: dict[str, float] = {}
_touch_guard = threading.Lock()


class DeviceStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else store_dir() / "devices.db"
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.path.exists():
            # 0600 before sqlite opens it, so the -wal/-shm sidecars inherit it (the connector store's lesson).
            os.close(os.open(self.path, os.O_WRONLY | os.O_CREAT, 0o600))
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(_SCHEMA)
            db.execute(_PAIRING_SCHEMA)

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create(self, name: str) -> tuple[Device, str]:
        """Issue a token for a device the person named. The token is returned once and never stored."""
        clean = clean_name(name)
        secret = secrets.token_urlsafe(32)
        with self._db() as db:
            while True:
                device_id = "".join(secrets.choice(_ID_ALPHABET) for _ in range(8))
                if db.execute("SELECT 1 FROM devices WHERE id=?", (device_id,)).fetchone() is None:
                    break
            db.execute("INSERT INTO devices (id, name, token_hash, created_at) VALUES (?, ?, ?, ?)",
                       (device_id, clean, _hash(secret), _now()))
        return self.get(device_id), f"{PREFIX}{device_id}_{secret}"

    def get(self, device_id: str) -> Device | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
        return _row(row) if row else None

    def list(self) -> list[Device]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM devices ORDER BY created_at DESC, id").fetchall()
        return [_row(r) for r in rows]

    def verify(self, token: str | None) -> Device | None:
        """The active device a token belongs to, else None — malformed, unknown, a wrong secret for a real id and a
        revoked device all answer None (the gate says nothing more to a stranger)."""
        match = TOKEN_RE.match(token or "")
        if not match:
            return None
        device_id, secret = match.groups()
        with self._db() as db:
            row = db.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
        if row is None or not hmac.compare_digest(row["token_hash"], _hash(secret)):
            return None
        device = _row(row)
        return device if device.active else None

    def touch(self, device_id: str) -> None:
        """Record a use, at most once a minute per device (never on the request's critical path for long)."""
        now = time.monotonic()
        with _touch_guard:
            if now - _touched.get(device_id, -TOUCH_EVERY_S) < TOUCH_EVERY_S:
                return
            _touched[device_id] = now
        try:
            with self._db() as db:
                db.execute("UPDATE devices SET last_used_at=?, use_count=use_count+1 WHERE id=?", (_now(), device_id))
        except sqlite3.Error:
            pass

    def revoke(self, device_id: str) -> Device:
        if not ID_RE.match(device_id or "") or self.get(device_id) is None:
            raise KeyError(device_id)
        with self._db() as db:
            db.execute("UPDATE devices SET revoked_at=COALESCE(revoked_at, ?) WHERE id=?", (_now(), device_id))
        return self.get(device_id)


    # ── G212: pairing ──────────────────────────────────────────────────────────

    def create_pairing(self, *, now: datetime | None = None) -> tuple[Pairing, str]:
        """A one-time code for a new device, shown on the person's own screen (a QR or the letters). Returns the
        pairing and the code — the code is in this one answer only. At most five wait at a time."""
        now = now or datetime.now(timezone.utc)
        stamp = now.replace(microsecond=0).isoformat()
        with self._db() as db:
            open_count = db.execute(
                "SELECT COUNT(*) FROM pairings WHERE used_at IS NULL AND cancelled_at IS NULL AND expires_at > ?",
                (stamp,)).fetchone()[0]
            if open_count >= MAX_OPEN_PAIRINGS:
                raise ValueError("Five pairing codes already wait; cancel one or let it expire.")
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            while True:
                pairing_id = "".join(secrets.choice(_ID_ALPHABET) for _ in range(8))
                if db.execute("SELECT 1 FROM pairings WHERE id=?", (pairing_id,)).fetchone() is None:
                    break
            expires = (now + timedelta(seconds=PAIRING_TTL_S)).replace(microsecond=0).isoformat()
            db.execute("INSERT INTO pairings (id, code_hash, created_at, expires_at) VALUES (?, ?, ?, ?)",
                       (pairing_id, _hash(normalize_code(code)), stamp, expires))
        return self.pairing(pairing_id, now=now), f"{code[:4]}-{code[4:]}"

    def pairing(self, pairing_id: str, *, now: datetime | None = None) -> Pairing | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM pairings WHERE id=?", (pairing_id,)).fetchone()
        return _pairing(row, now or datetime.now(timezone.utc)) if row else None

    def cancel_pairing(self, pairing_id: str) -> Pairing:
        if not ID_RE.match(pairing_id or "") or self.pairing(pairing_id) is None:
            raise KeyError(pairing_id)
        with self._db() as db:
            db.execute("UPDATE pairings SET cancelled_at=COALESCE(cancelled_at, ?) WHERE id=? AND used_at IS NULL",
                       (_now(), pairing_id))
        return self.pairing(pairing_id)

    def redeem(self, code: str, name: str, *, now: datetime | None = None) -> tuple[Device, str]:
        """Spend a code: the device the new machine named is issued its own token. ``KeyError`` for a code that
        matches nothing waiting — unknown, used, cancelled and expired all look the same to the asker. The code is
        spent in the same statement that checks it, so two redeems of one code make one device."""
        clean = clean_name(name)
        normal = normalize_code(code)
        if len(normal) != CODE_LENGTH or any(ch not in CODE_ALPHABET for ch in normal):
            raise KeyError("code")
        stamp = (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            spent = db.execute(
                "UPDATE pairings SET used_at=? WHERE code_hash=? AND used_at IS NULL AND cancelled_at IS NULL "
                "AND expires_at > ?", (stamp, _hash(normal), stamp)).rowcount
            if spent != 1:
                raise KeyError("code")
            row = db.execute("SELECT id FROM pairings WHERE code_hash=?", (_hash(normal),)).fetchone()
            secret = secrets.token_urlsafe(32)
            while True:
                device_id = "".join(secrets.choice(_ID_ALPHABET) for _ in range(8))
                if db.execute("SELECT 1 FROM devices WHERE id=?", (device_id,)).fetchone() is None:
                    break
            db.execute("INSERT INTO devices (id, name, token_hash, created_at) VALUES (?, ?, ?, ?)",
                       (device_id, clean, _hash(secret), _now()))
            db.execute("UPDATE pairings SET device_id=? WHERE id=?", (device_id, row["id"]))
        return self.get(device_id), f"{PREFIX}{device_id}_{secret}"


@dataclass(frozen=True)
class Pairing:
    id: str
    created_at: str
    expires_at: str
    state: str   # waiting | paired | cancelled | expired
    device_id: str | None = None

    def wire(self) -> dict:
        return {"id": self.id, "createdAt": self.created_at, "expiresAt": self.expires_at, "state": self.state,
                "deviceId": self.device_id}


def normalize_code(raw: str | None) -> str:
    """What a person may type or a QR may carry — any case, with a dash or spaces — reduced to the code itself."""
    return "".join(ch for ch in str(raw or "").upper() if ch.isalnum())


def _pairing(row: sqlite3.Row, now: datetime) -> Pairing:
    if row["used_at"]:
        state = "paired"
    elif row["cancelled_at"]:
        state = "cancelled"
    elif datetime.fromisoformat(row["expires_at"]) <= now:
        state = "expired"
    else:
        state = "waiting"
    return Pairing(id=row["id"], created_at=row["created_at"], expires_at=row["expires_at"], state=state,
                   device_id=row["device_id"])


def store() -> DeviceStore:
    """The store under the current ``$CICADA_HOME`` — resolved per call, never cached across a home change."""
    return DeviceStore()


def looks_like(token: str | None) -> bool:
    return bool(token) and str(token).startswith(PREFIX)
