"""Where remote connectors live (G135 R-R3, R-R30, R-R31): machine-global,
outside every bank, private to this user.

`~/.cicada/remote/` (0700) holds `connectors.db` (sqlite WAL, 0600) and
`settings.json` (0600). A token is `cic_rc_<id>_<secret>`: the id gives an O(1)
lookup and makes the token greppable by secret scanners. The secret is 256
bits and only its sha256 is stored, compared with `hmac.compare_digest`, so the
token exists in exactly one HTTP response — the one that created or rotated
it. Every column is an id, an enum or a timestamp, except `label` (the one
owner-typed field: printable, at most 40 characters) and `last_client` (a
self-reported client name, display only: at most 64 safe characters). A
connector follows the active bank, the stdio server's own rule; pinning a
bank is a later slice.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import string
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from api.remote import catalog
from api.services.auth import cicada_home

_ID_ALPHABET = string.ascii_lowercase + string.digits
_CLIENT_UNSAFE = re.compile(r"[^A-Za-z0-9 ._()/-]")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS connectors (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    app TEXT NOT NULL,
    scopes TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    revoked_at TEXT,
    last_used_at TEXT,
    last_client TEXT,
    use_count INTEGER NOT NULL DEFAULT 0
)"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("ascii")).hexdigest()


def remote_dir() -> Path:
    path = cicada_home() / "remote"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _clean_label(raw: str | None, app: str) -> str:
    label = "".join(ch for ch in (raw or "") if ch.isprintable()).strip()[:40]
    return label or catalog.APPS[app].label


def _clean_client(raw: str | None) -> str | None:
    if not raw:
        return None
    return _CLIENT_UNSAFE.sub("", str(raw))[:64].strip() or None


def _row(row: sqlite3.Row) -> catalog.Connector:
    return catalog.Connector(
        id=row["id"], label=row["label"], app=row["app"],
        scopes=catalog.clean_scopes((row["scopes"] or "").split(",")),
        created_at=row["created_at"], expires_at=row["expires_at"], revoked_at=row["revoked_at"],
        last_used_at=row["last_used_at"], last_client=row["last_client"], use_count=int(row["use_count"] or 0),
    )


class ConnectorStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else remote_dir() / "connectors.db"
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        if not self.path.exists():
            # Created 0600 BEFORE sqlite opens it: SQLite gives the -wal and
            # -shm files the main file's mode, so a chmod after the first
            # connect leaves that connection's sidecars at the umask's 0644
            # (measured). An empty file is a valid empty db.
            os.close(os.open(self.path, os.O_WRONLY | os.O_CREAT, 0o600))
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(_SCHEMA)

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create(self, *, app: str, label: str | None, scopes, expires_in_days: int,
               now: datetime | None = None) -> tuple[catalog.Connector, str]:
        """Every connector expires (R-R3, spec Decision 4: 7/30/90 days). A
        "no expiry" choice shipped in Task 7 and was taken out at the final
        review: a leaked secret link would have worked until someone thought
        to revoke it, which is exactly what "expiring" in the spec rules out."""
        if app not in catalog.APPS:
            raise ValueError(f"unknown app {app!r}")
        wanted = [str(s) for s in (scopes or [])]
        clean = catalog.clean_scopes(wanted)
        if not clean or len(clean) != len(set(wanted)):
            raise ValueError("scopes must be a non-empty subset of " + ", ".join(catalog.SCOPES))
        if expires_in_days not in catalog.EXPIRY_CHOICES:
            raise ValueError("expiresInDays must be 7, 30 or 90")
        now = now or _now()
        secret = secrets.token_urlsafe(32)
        with self._db() as db:
            while True:
                connector_id = "".join(secrets.choice(_ID_ALPHABET) for _ in range(8))
                if db.execute("SELECT 1 FROM connectors WHERE id=?", (connector_id,)).fetchone() is None:
                    break
            db.execute(
                "INSERT INTO connectors (id, label, app, scopes, token_hash, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (connector_id, _clean_label(label, app), app, ",".join(sorted(clean)), _hash(secret), _iso(now),
                 _iso(now + timedelta(days=expires_in_days))),
            )
        return self.get(connector_id), f"cic_rc_{connector_id}_{secret}"

    def get(self, connector_id: str) -> catalog.Connector | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM connectors WHERE id=?", (connector_id,)).fetchone()
        return _row(row) if row else None

    def list(self) -> list[catalog.Connector]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM connectors ORDER BY created_at DESC, id").fetchall()
        return [_row(r) for r in rows]

    def verify(self, token: str | None, now: datetime | None = None) -> tuple[catalog.Connector | None, str]:
        """``(connector, "ok")``; ``(connector, "revoked"|"expired")`` for a real
        but dead token (the gate needs the id for the ledger); ``(None,
        "malformed"|"unknown")`` otherwise. A wrong secret for a real id is
        ``unknown`` — the gate says nothing more to a stranger."""
        match = catalog.TOKEN_RE.match(token or "")
        if not match:
            return None, "malformed"
        connector_id, secret = match.groups()
        with self._db() as db:
            row = db.execute("SELECT * FROM connectors WHERE id=?", (connector_id,)).fetchone()
        if row is None or not hmac.compare_digest(row["token_hash"], _hash(secret)):
            return None, "unknown"
        connector = _row(row)
        state = connector.state(now or _now())
        return connector, ("ok" if state == "active" else state)

    def touch(self, connector_id: str, *, client: str | None = None, now: datetime | None = None) -> None:
        with self._db() as db:
            db.execute(
                "UPDATE connectors SET last_used_at=?, use_count=use_count+1, "
                "last_client=COALESCE(?, last_client) WHERE id=?",
                (_iso(now or _now()), _clean_client(client), connector_id),
            )

    def rotate(self, connector_id: str, now: datetime | None = None) -> tuple[catalog.Connector, str]:
        connector = self.get(connector_id)
        if connector is None:
            raise KeyError(connector_id)
        state = connector.state(now or _now())
        if state != "active":
            raise ValueError(state)
        secret = secrets.token_urlsafe(32)
        with self._db() as db:
            db.execute("UPDATE connectors SET token_hash=? WHERE id=?", (_hash(secret), connector_id))
        return self.get(connector_id), f"cic_rc_{connector_id}_{secret}"

    def revoke(self, connector_id: str, now: datetime | None = None) -> catalog.Connector:
        if self.get(connector_id) is None:
            raise KeyError(connector_id)
        with self._db() as db:
            db.execute("UPDATE connectors SET revoked_at=COALESCE(revoked_at, ?) WHERE id=?",
                       (_iso(now or _now()), connector_id))
        return self.get(connector_id)


@dataclass(frozen=True)
class RemoteSettings:
    enabled: bool = False
    public_base_url: str | None = None


def settings_path() -> Path:
    return remote_dir() / "settings.json"


def load_settings() -> RemoteSettings:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return RemoteSettings(enabled=bool(data.get("enabled")), public_base_url=data.get("public_base_url") or None)
    except (OSError, ValueError, AttributeError):
        return RemoteSettings()


def save_settings(settings: RemoteSettings) -> None:
    path = settings_path()
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(asdict(settings), fh)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def normalize_public_url(raw: str | None) -> str | None:
    """The person's own https address for this Mac, reduced to scheme + host
    (+ a non-443 port). Anything else — plain http, a path, credentials, a
    query — is refused: the listener serves `/mcp` and `/c/…` at the root."""
    value = (raw or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ValueError("Use the https:// address your tunnel gave you, with nothing after the host.")
    port = f":{parsed.port}" if parsed.port and parsed.port != 443 else ""
    return f"https://{parsed.hostname}{port}"


def remote_port(env=None) -> int:
    raw = ((env if env is not None else os.environ).get("CICADA_REMOTE_PORT") or "").strip()
    try:
        port = int(raw) if raw else catalog.DEFAULT_PORT
    except ValueError:
        return catalog.DEFAULT_PORT
    return port if 0 <= port <= 65535 else catalog.DEFAULT_PORT
