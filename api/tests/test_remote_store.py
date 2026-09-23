"""G135 R-R3 / R-R30 / R-R31 — the connector store: tokens shown once and
hashed at rest, scopes that fail closed, expiry, rotation, revocation."""
from __future__ import annotations

import hashlib
import sqlite3
import stat
from datetime import datetime, timedelta, timezone

import pytest

from api.remote import catalog, store

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    return store.ConnectorStore(tmp_path / "remote" / "connectors.db")


def test_a_token_is_shown_once_and_only_its_hash_is_stored(db):
    connector, token = db.create(app="claude", label="Phone", scopes=["search", "read", "record"],
                                 expires_in_days=30, now=NOW)
    match = catalog.TOKEN_RE.match(token)
    assert match and match.group(1) == connector.id
    secret = match.group(2)
    raw = db.path.read_bytes() + b"".join(p.read_bytes() for p in db.path.parent.glob("connectors.db-*"))
    assert secret.encode() not in raw and token.encode() not in raw
    with sqlite3.connect(db.path) as conn:
        (stored,) = conn.execute("SELECT token_hash FROM connectors").fetchone()
    assert stored == hashlib.sha256(secret.encode()).hexdigest()
    assert connector.expires_at == (NOW + timedelta(days=30)).isoformat()


def test_the_store_is_private_to_this_user(db):
    assert stat.S_IMODE(db.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(db.path.parent.stat().st_mode) == 0o700
    # SQLite deletes -wal/-shm on the last close, so hold a reader open while
    # writing: the sidecars then exist, and must be as private as the db (SQLite
    # copies the main file's mode, which is why the store creates it 0600 first).
    holder = sqlite3.connect(db.path)
    try:
        holder.execute("SELECT count(*) FROM connectors").fetchall()
        db.create(app="claude", label="", scopes=["search"], expires_in_days=30)
        sidecars = list(db.path.parent.glob("connectors.db-*"))
        assert sidecars, "WAL mode leaves -wal/-shm beside the db while a connection is open"
        for sidecar in sidecars:
            assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600, sidecar.name
    finally:
        holder.close()


def test_verify_names_every_way_a_token_can_fail(db):
    good, token = db.create(app="chatgpt", label="", scopes=["search"], expires_in_days=7, now=NOW)
    assert db.verify(token, now=NOW) == (good, "ok")
    assert db.verify("", now=NOW) == (None, "malformed")
    assert db.verify("cic_rc_nope", now=NOW) == (None, "malformed")
    wrong = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
    assert db.verify(wrong, now=NOW) == (None, "unknown")
    assert db.verify(token, now=NOW + timedelta(days=8))[1] == "expired"
    db.revoke(good.id, now=NOW)
    assert db.verify(token, now=NOW)[1] == "revoked"


@pytest.mark.parametrize("scopes", [[], ["delete"], ["search", "admin"], ["cicada_pending"]])
def test_scopes_fail_closed(db, scopes):
    with pytest.raises(ValueError):
        db.create(app="claude", label="", scopes=scopes, expires_in_days=30)


def test_an_unknown_scope_in_a_stored_row_is_dropped_never_granted(db):
    c, _ = db.create(app="claude", label="", scopes=["search"], expires_in_days=30)
    with sqlite3.connect(db.path) as conn:
        conn.execute("UPDATE connectors SET scopes='search,delete' WHERE id=?", (c.id,))
    assert db.get(c.id).scopes == {"search"}


def test_expiry_choices_and_apps_are_closed(db):
    with pytest.raises(ValueError):
        db.create(app="claude", label="", scopes=["search"], expires_in_days=365)
    with pytest.raises(ValueError):
        db.create(app="myspace", label="", scopes=["search"], expires_in_days=30)
    # Every connector expires (R-R3): "no expiry" is refused, not stored as forever.
    for never in (None, 0):
        with pytest.raises(ValueError):
            db.create(app="claude", label="", scopes=["search"], expires_in_days=never)


def test_rotation_keeps_everything_but_the_secret(db):
    c, old = db.create(app="cursor", label="Desk", scopes=["search", "record"], expires_in_days=90, now=NOW)
    rotated, new = db.rotate(c.id, now=NOW)
    assert (rotated.id, rotated.label, rotated.scopes, rotated.expires_at) == (c.id, c.label, c.scopes, c.expires_at)
    assert db.verify(old, now=NOW)[1] == "unknown" and db.verify(new, now=NOW)[1] == "ok"
    db.revoke(c.id, now=NOW)
    with pytest.raises(ValueError):
        db.rotate(c.id, now=NOW)
    with pytest.raises(KeyError):
        db.rotate("zzzzzzzz")


def test_revocation_keeps_the_row_and_is_idempotent(db):
    c, _ = db.create(app="claude", label="", scopes=["search"], expires_in_days=30)
    first = db.revoke(c.id, now=NOW)
    second = db.revoke(c.id, now=NOW + timedelta(days=1))
    assert first.revoked_at == second.revoked_at == NOW.isoformat()
    assert [x.id for x in db.list()] == [c.id] and db.list()[0].state() == "revoked"


def test_touch_records_last_use_and_a_clean_client_name(db):
    c, _ = db.create(app="claude", label="", scopes=["search"], expires_in_days=30)
    db.touch(c.id, client="claude-ai <script>" + "x" * 100, now=NOW)
    got = db.get(c.id)
    assert got.last_used_at == NOW.isoformat() and got.use_count == 1
    assert got.last_client.startswith("claude-ai script") and len(got.last_client) <= 64


def test_labels_are_short_printable_and_default_to_the_app(db):
    assert db.create(app="perplexity", label="", scopes=["search"], expires_in_days=7)[0].label == "Perplexity"
    long = db.create(app="claude", label="\x07" + "L" * 80, scopes=["search"], expires_in_days=7)[0]
    assert long.label == "L" * 40


def test_settings_round_trip_privately(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    assert store.load_settings() == store.RemoteSettings()
    store.save_settings(store.RemoteSettings(enabled=True, public_base_url="https://mac.example-tailnet.ts.net"))
    assert store.load_settings().enabled is True
    assert stat.S_IMODE(store.settings_path().stat().st_mode) == 0o600


@pytest.mark.parametrize("raw,want", [
    ("https://mac.example-tailnet.ts.net", "https://mac.example-tailnet.ts.net"),
    ("https://MAC.example-tailnet.ts.net/", "https://mac.example-tailnet.ts.net"),
    ("https://abc.ngrok-free.app:8443", "https://abc.ngrok-free.app:8443"),
    ("", None), (None, None),
])
def test_a_public_url_is_normalised(raw, want):
    assert store.normalize_public_url(raw) == want


@pytest.mark.parametrize("raw", ["http://mac.example-tailnet.ts.net", "https://x.example/mcp",
                                 "https://u:p@x.example", "https://x.example/?a=1", "mac.example"])
def test_a_bad_public_url_is_refused(raw):
    with pytest.raises(ValueError):
        store.normalize_public_url(raw)


def test_the_port_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("CICADA_REMOTE_PORT", raising=False)
    assert store.remote_port() == 8765
    monkeypatch.setenv("CICADA_REMOTE_PORT", "0")
    assert store.remote_port() == 0
    monkeypatch.setenv("CICADA_REMOTE_PORT", "not a port")
    assert store.remote_port() == 8765
