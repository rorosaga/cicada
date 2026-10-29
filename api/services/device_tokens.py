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
    use_count INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'full',
    key_thumbprint TEXT,
    key_bound_at TEXT
)"""
#: G212 (owner 2026-10-29): a **key-bound** device's token works only with a proof signed by the device's own key
#: (``device_proof``, RFC 9449's shape). ``key_thumbprint`` is that public key's RFC 7638 thumbprint — a hash of a
#: public key, never a secret — set at pairing (the redeem carried a proof) or once by the device itself
#: (:meth:`DeviceStore.bind_key`); NULL = not yet key-bound, the bearer token alone, as every device was before.
#: G212 (owner 2026-10-22): what a device token may do. ``full`` — every route but the master-only ones (ruling 28,
#: what `cicada device add` and a computer's pairing issue); ``capture`` — a phone's: send links and notes, read back
#: its own recent captures, nothing else (``auth.CAPTURE_ROUTES``). A row from before the column is ``full``.
KINDS = ("full", "capture")
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
    device_id TEXT,
    kind TEXT NOT NULL DEFAULT 'capture'
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
    kind: str = "full"
    key_thumbprint: str | None = None
    key_bound_at: str | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    @property
    def key_bound(self) -> bool:
        return bool(self.key_thumbprint)

    def wire(self) -> dict:
        # The thumbprint itself stays here: the wire says only whether the device is bound, and since when.
        return {"id": self.id, "name": self.name, "createdAt": self.created_at, "revokedAt": self.revoked_at,
                "lastUsedAt": self.last_used_at, "useCount": self.use_count, "active": self.active,
                "kind": self.kind, "keyBound": self.key_bound, "keyBoundAt": self.key_bound_at}


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
    keys = row.keys()
    return Device(id=row["id"], name=row["name"], created_at=row["created_at"], revoked_at=row["revoked_at"],
                  last_used_at=row["last_used_at"], use_count=int(row["use_count"] or 0),
                  kind=row["kind"] if "kind" in keys and row["kind"] in KINDS else "full",
                  key_thumbprint=row["key_thumbprint"] if "key_thumbprint" in keys else None,
                  key_bound_at=row["key_bound_at"] if "key_bound_at" in keys else None)


#: Stores whose schema this process already made or migrated, by path — so the auth gate, which opens the store on
#: every device request, runs its DDL once per process instead of once per request (measured: the store's verify
#: p95 0.98 → 0.57 ms, 2026-10-29). A store file that disappears (a test's tmp dir, a wiped home) is made again.
_READY: set[str] = set()
_ready_lock = threading.Lock()


_touched: dict[str, float] = {}
_touch_guard = threading.Lock()


class DeviceStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else store_dir() / "devices.db"
        key = str(self.path)
        if key in _READY and self.path.exists():
            return
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.path.exists():
            # 0600 before sqlite opens it, so the -wal/-shm sidecars inherit it (the connector store's lesson).
            os.close(os.open(self.path, os.O_WRONLY | os.O_CREAT, 0o600))
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(_SCHEMA)
            db.execute(_PAIRING_SCHEMA)
            # G212 (owner 2026-10-22): a store made before device kinds gains the column; every old device is full,
            # and an old waiting code mints a full device, as it would have when it was made.
            for table, default in (("devices", "full"), ("pairings", "full")):
                if "kind" not in {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN kind TEXT NOT NULL DEFAULT '{default}'")
            # G212 (2026-10-29): a store from before key binding gains the two columns; every old device is not yet
            # key-bound and keeps working with its bearer token exactly as before.
            have = {r["name"] for r in db.execute("PRAGMA table_info(devices)")}
            for column in ("key_thumbprint", "key_bound_at"):
                if column not in have:
                    db.execute(f"ALTER TABLE devices ADD COLUMN {column} TEXT")
        with _ready_lock:
            _READY.add(key)

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


    def bind_key(self, device_id: str, key_thumbprint: str, *, narrow_to: str | None = None) -> tuple[Device, bool]:
        """Bind a device that is not yet key-bound to its key, once (2026-10-29: an already-paired phone upgrades by
        itself). ``(device, changed)``. Binding the key it already has is a no-op; another key is ``ValueError`` — a
        bound device never moves to a new key, a new key is a new pairing. ``narrow_to="capture"`` also narrows a
        full device to capture-only (a device may lower its own rights, never raise them). ``KeyError`` for an
        unknown or revoked device."""
        if not key_thumbprint or narrow_to not in (None, "capture"):
            raise ValueError("bad binding")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
            if row is None or row["revoked_at"]:
                raise KeyError(device_id)
            if row["kind"] != "capture" and narrow_to != "capture":
                raise FullDeviceKey()
            current = row["key_thumbprint"]
            if current and not hmac.compare_digest(current, key_thumbprint):
                raise ValueError("This device is already bound to another key. Pair it again for a new key.")
            changed = False
            if not current:
                db.execute("UPDATE devices SET key_thumbprint=?, key_bound_at=? WHERE id=?",
                           (key_thumbprint, _now(), device_id))
                changed = True
            if narrow_to == "capture" and row["kind"] != "capture":
                db.execute("UPDATE devices SET kind='capture' WHERE id=?", (device_id,))
                changed = True
        return self.get(device_id), changed

    # ── G212: pairing ──────────────────────────────────────────────────────────

    def create_pairing(self, *, now: datetime | None = None, kind: str = "capture") -> tuple[Pairing, str]:
        """A one-time code for a new device, shown on the person's own screen (a QR or the letters). Returns the
        pairing and the code — the code is in this one answer only. At most five wait at a time. ``kind`` is what the
        device it mints may do (``KINDS``; a phone's default is ``capture``, owner 2026-10-22)."""
        if kind not in KINDS:
            raise ValueError("kind must be 'capture' or 'full'")
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
            db.execute("INSERT INTO pairings (id, code_hash, created_at, expires_at, kind) VALUES (?, ?, ?, ?, ?)",
                       (pairing_id, _hash(normalize_code(code)), stamp, expires, kind))
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

    def redeem(self, code: str, name: str, *, now: datetime | None = None, key_thumbprint: str | None = None,
               kind: str | None = None) -> tuple[Device, str]:
        """Spend a code: the device the new machine named is issued its own token. ``KeyError`` for a code that
        matches nothing waiting — unknown, used, cancelled and expired all look the same to the asker. The code is
        spent in the same statement that checks it, so two redeems of one code make one device.

        ``key_thumbprint`` (2026-10-29): the redeem carried a proof of the device's own key, so the token is born
        key-bound. ``kind``: what the device asks to be — it may only **narrow** the code (a phone asking for
        ``capture`` on a computer's code gets a capture token), never widen it."""
        clean = clean_name(name)
        if kind is not None and kind not in KINDS:
            raise ValueError("kind must be 'capture' or 'full'")
        requested = kind
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
            row = db.execute("SELECT id, kind FROM pairings WHERE code_hash=?", (_hash(normal),)).fetchone()
            kind = row["kind"] if row["kind"] in KINDS else "capture"
            if requested == "capture":
                kind = "capture"
            if key_thumbprint and kind == "full":
                raise FullDeviceKey()   # raised inside the transaction: the code is not spent
            secret = secrets.token_urlsafe(32)
            while True:
                device_id = "".join(secrets.choice(_ID_ALPHABET) for _ in range(8))
                if db.execute("SELECT 1 FROM devices WHERE id=?", (device_id,)).fetchone() is None:
                    break
            bound_at = _now() if key_thumbprint else None
            db.execute("INSERT INTO devices (id, name, token_hash, created_at, kind, key_thumbprint, key_bound_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (device_id, clean, _hash(secret), _now(), kind, key_thumbprint or None, bound_at))
            db.execute("UPDATE pairings SET device_id=? WHERE id=?", (device_id, row["id"]))
        return self.get(device_id), f"{PREFIX}{device_id}_{secret}"


class FullDeviceKey(ValueError):
    """A key binding asked for a ``full`` device (review 2026-10-29): refused until a computer's clients can all sign."""


@dataclass(frozen=True)
class Pairing:
    id: str
    created_at: str
    expires_at: str
    state: str   # waiting | paired | cancelled | expired
    device_id: str | None = None
    kind: str = "capture"

    def wire(self) -> dict:
        return {"id": self.id, "createdAt": self.created_at, "expiresAt": self.expires_at, "state": self.state,
                "deviceId": self.device_id, "kind": self.kind}


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
                   device_id=row["device_id"], kind=row["kind"] if row["kind"] in KINDS else "capture")


def store() -> DeviceStore:
    """The store under the current ``$CICADA_HOME`` — resolved per call, never cached across a home change."""
    return DeviceStore()


def looks_like(token: str | None) -> bool:
    return bool(token) and str(token).startswith(PREFIX)
