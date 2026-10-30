"""G132 phase 3b — one transport: with no relay set it is phases 1–2's direct request exactly (nothing relay-side is
imported or started); with a relay running, a direct peer that does not answer falls back to the relay, a request
that died mid-way is resent there with the same key, and the relay-only address is never dialed. Plus the pieces that
ride with it: the relay setting, LAN discovery's signed hello, the direct listener's bind rule, and the phase-2 review
follow-ups (the journal's ``headAfter``, keyed own writes, ``/sync/keys`` paging, the set-aside count, the take-over
words, ``_another_home`` asking all at once)."""
from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from _synthetic_bank import _bank
from api import config
from api.services import (admitted_log, bank_registry, git_service, home_move, idempotency, replica_guard,
                          sync_direct_listen, sync_discovery, sync_publish, sync_transport)

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "cicada"))
    for var in ("CICADA_REPLICA_OF", "CICADA_API_BASE", "CICADA_SYNC_PUBLISH", "CICADA_DEVICE_URL",
                "CICADA_SYNC_RELAY", "CICADA_APP_BUNDLE_ID"):
        monkeypatch.delenv(var, raising=False)
    replica_guard.thaw()
    bank = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_registry.ensure_bank_ids(bank)
    home_move._CACHE.clear()     # noqa: SLF001
    sync_transport.reset_for_tests()
    yield bank
    config.get_settings.cache_clear()
    home_move._clear_handoff()   # noqa: SLF001


class _Answer(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def do_GET(self):  # noqa: N802
        type(self).seen.append((self.path, self.headers.get("Authorization")))
        body = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Answer)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Answer.seen = []
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


class _FakeLink:
    def __init__(self):
        self.asked = []

    def running(self):
        return True

    def public_state(self):
        return {"connected": True}

    def request(self, method, path, **kw):
        self.asked.append((method, path, kw.get("headers"), kw.get("to")))
        return 200, {}, {"via": "relay"}


@pytest.fixture
def link(monkeypatch):
    fake = _FakeLink()
    mod = type(sys)("api.services.sync_relay_link")
    mod.LINK = fake
    monkeypatch.setitem(sys.modules, "api.services.sync_relay_link", mod)
    yield fake


# --- unset: exactly phases 1–2 ----------------------------------------------------------------------------------------------

def test_with_no_relay_the_transport_is_the_direct_request_and_imports_nothing(home, server):
    assert sync_transport.relay_url() is None and sync_transport._link() is None   # noqa: SLF001
    status, _h, body = sync_transport.request(server, "GET", "/x", headers={"Authorization": "Bearer t"})
    assert (status, body) == (200, {"ok": True}) and _Answer.seen == [("/x", "Bearer t")]
    code = ("import sys, api.services.replica as r, api.services.sync_transport as t; t.request('http://127.0.0.1:9', "
            "'GET', '/'); bad=[m for m in sys.modules if 'sync_relay' in m or m.startswith('nacl')]; "
            "print(bad); sys.exit(1 if bad else 0)")
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(REPO), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_unreachable_with_no_relay_says_so_and_never_raises(home):
    status, headers, _b = sync_transport.request("http://127.0.0.1:9", "GET", "/x")
    assert status is None and headers[sync_transport.NO_ANSWER] == "unreachable"


# --- a relay running: direct first, the relay as fallback ----------------------------------------------------------------

def test_direct_answers_so_the_relay_carries_nothing(home, server, link):
    status, _h, body = sync_transport.request(server, "GET", "/x")
    assert body == {"ok": True} and link.asked == []
    assert sync_transport.stats()["last"] == "direct"


def test_a_peer_that_does_not_answer_goes_over_the_relay_without_its_credential(home, link):
    started = time.perf_counter()
    status, _h, body = sync_transport.request("http://127.0.0.1:9", "POST", "/tools/call",
                                              headers={"Authorization": "Bearer secret", "Idempotency-Key": "k" * 16})
    assert body == {"via": "relay"}
    method, path, headers, to = link.asked[0]
    assert "Authorization" not in headers and headers["Idempotency-Key"] == "k" * 16 and to == "home"
    assert time.perf_counter() - started < sync_transport.FALLBACK_AFTER_S + 1
    stats = sync_transport.stats()
    assert stats["fallbacks"] == 1 and stats["last"] == "relay" and stats["directDownUntil"]
    # Within the retry window, direct is not probed again.
    sync_transport.request("http://127.0.0.1:9", "GET", "/y")
    assert len(link.asked) == 2


def test_the_relay_only_address_is_never_dialed(home, link):
    status, _h, body = sync_transport.request(sync_transport.RELAY_ONLY_BASE, "GET", "/sync/status")
    assert body == {"via": "relay"} and sync_transport.stats()["fallbacks"] == 0
    from api.services import runtime_layout

    assert runtime_layout._checked_base(sync_transport.RELAY_ONLY_BASE, "x")   # noqa: SLF001 — a valid replica_of


def test_the_relay_setting_is_off_by_default_wss_only_and_0600(home):
    assert sync_transport.relay_url() is None
    with pytest.raises(ValueError):
        sync_transport.set_relay_url("ws://relay.example.net")
    with pytest.raises(ValueError):
        sync_transport.set_relay_url("https://relay.example.net")
    assert sync_transport.set_relay_url("wss://relay.example.net/") == "wss://relay.example.net"
    path = sync_transport._setting_path()   # noqa: SLF001
    assert path.stat().st_mode & 0o777 == 0o600 and sync_transport.relay_url() == "wss://relay.example.net"
    assert sync_transport.set_relay_url("ws://127.0.0.1:8443")
    sync_transport.set_relay_url(None)
    assert sync_transport.relay_url() is None and not path.exists()


# --- discovery: only a hash is advertised; an address is trusted only after a signed hello ------------------------------

def _share(bank):
    sync_publish.set_enabled(True)
    home_move.ensure_own_identity()


def test_nothing_is_discovered_or_answered_on_a_memory_that_is_not_shared(home):
    assert sync_discovery.plan(home) is None
    assert sync_discovery.hello(home, "n" * 16, "x" * 16) is None


def test_the_advertised_name_is_a_hash_never_the_bank_id(home):
    _share(home)
    bank_id = sync_discovery._bank_id()   # noqa: SLF001
    plan = sync_discovery.plan(home)
    assert plan["type"] == "_cicada._tcp" and plan["browse"].startswith("c-")
    assert bank_id not in json.dumps(plan) and plan["advertise"] is None        # nothing listens beyond loopback
    assert len(sync_discovery.bank_hash(bank_id)) == 16


def test_a_found_address_is_kept_only_with_a_fresh_nonce_and_the_registry_key(home, monkeypatch):
    _share(home)
    bank_id = sync_discovery._bank_id()   # noqa: SLF001
    h = sync_discovery.bank_hash(bank_id)
    nonce = sync_discovery.issue_nonce()
    answer = sync_discovery.hello(home, nonce, h)          # this computer answering for itself, as a peer would
    me = home_move.my_device_id()
    assert answer["device"] == me and answer["sig"]
    # Plain http to a LAN address is never kept: a token would cross the network in the clear.
    assert sync_discovery.accept(home, [{"url": "http://192.168.1.20:8443", "nonce": nonce, "answer": answer}],
                                 lan_allowed=True) == []
    nonce = sync_discovery.issue_nonce()
    answer = sync_discovery.hello(home, nonce, h)
    got = sync_discovery.accept(home, [{"url": "https://192.168.1.20:8443", "nonce": nonce, "answer": answer}],
                                lan_allowed=True)
    assert got == [{"device": me, "url": "https://192.168.1.20:8443"}]
    # Not dialed: the backend's plist does not name the app (TN3179), so the app's permission does not cover it.
    assert sync_discovery.address_for(home, me) is None
    # The nonce was spent; a forged signature and a stranger's device are refused.
    assert sync_discovery.accept(home, [{"url": "https://192.168.1.21:8443", "nonce": nonce, "answer": answer}],
                                 lan_allowed=True) == []
    n2 = sync_discovery.issue_nonce()
    assert sync_discovery.accept(home, [{"url": "https://192.168.1.22:8443", "nonce": n2,
                                         "answer": {**answer, "sig": answer["sig"][:-4] + "AAAA"}}],
                                 lan_allowed=True) == []
    n3 = sync_discovery.issue_nonce()
    assert sync_discovery.accept(home, [{"url": "https://192.168.1.23:8443", "nonce": n3,
                                         "answer": {"device": "zzzzzzzz", "sig": answer["sig"]}}],
                                 lan_allowed=True) == []
    # With the plist naming the app, the verified address may be dialed.
    monkeypatch.setenv("CICADA_APP_BUNDLE_ID", "com.example.cicada")
    n4 = sync_discovery.issue_nonce()
    sync_discovery.accept(home, [{"url": "https://192.168.1.24:8443", "nonce": n4,
                                  "answer": sync_discovery.hello(home, n4, h)}], lan_allowed=True)
    assert sync_discovery.address_for(home, me) == "https://192.168.1.24:8443"


def test_the_install_script_names_the_app_only_when_given_it(tmp_path):
    script = (REPO / "scripts" / "install-backend-agent.sh").read_text()
    assert "AssociatedBundleIdentifiers" in script and 'if [ -n "${CICADA_APP_BUNDLE_ID:-}" ]' in script


# --- the bind: loopback only; discovery advertises only a private https address the person set ------------------------

@pytest.mark.parametrize("url,ok", [
    ("https://192.168.1.20:8443", True), ("https://10.0.0.5:9000", True), ("https://100.101.102.103:8443", True),
    ("https://[fd7a:115c:a1e0::5]:8443", True), ("http://192.168.1.20:8443", False),
    ("https://0.0.0.0:8443", False), ("https://127.0.0.1:8443", False), ("https://203.0.113.7:8443", False),
    ("https://8.8.8.8:8443", False), ("https://169.254.1.1:8443", False), ("https://[::]:8443", False),
    ("https://laptop.tailnet.example:443", False), ("https://my-laptop.local:8443", False),
    ("https://192.168.1.20:8000", False)])
def test_only_a_private_https_address_the_person_set_is_advertised(url, ok):
    got = sync_direct_listen.plan({"CICADA_DEVICE_URL": url}, backend_port=8000)
    assert (got is not None) is ok, (url, got)
    assert sync_direct_listen.plan({}, backend_port=8000) is None


def test_the_bind_is_shown_and_stays_loopback(home):
    got = sync_direct_listen.wire()
    assert got["listening"].startswith("127.0.0.1:") and got["loopbackOnly"] is True


# --- phase 2's review follow-ups ------------------------------------------------------------------------------------------

def test_the_journal_records_the_commit_the_call_itself_made(home):
    _share(home)
    (home / "a.md").write_text("a\n")
    with admitted_log.tracking(home) as track:
        git_service.commit_paths_sync(home, "own", ["a.md"])
        own = git_service._git_sync(home, "rev-parse", "HEAD").strip()   # noqa: SLF001
        # Another writer commits before the journal line: the call's headAfter is still its own commit.
        with git_service.recording_commits():
            (home / "b.md").write_text("b\n")
            git_service.commit_paths_sync(home, "other", ["b.md"])
    admitted_log.record_tool(home, tool="cicada_add_backlog_item", arguments={}, track=track, key="key-of-mine-1")
    entry = admitted_log.entries(home)[-1]
    assert entry["headAfter"] == own and entry["key"] == "key-of-mine-1"
    assert git_service._COMMITS_MADE.get() is None                      # noqa: SLF001 — nothing noted outside


def test_a_remote_apps_saved_episode_is_counted_once(home, monkeypatch):
    entries = [{"kind": "unofferable", "tool": "cicada_save_episode"}, {"kind": "unofferable", "tool": "cicada_write_claim"}]
    monkeypatch.setattr(admitted_log, "not_in", lambda *a, **k: entries)
    monkeypatch.setattr(home_move, "_git_read", lambda *a, **k: "")
    rec = type("R", (), {"bank_id": "b" * 32, "seq": 0, "term": 2})()
    got = home_move._offers(home, rec, "f", "o", "h", was_home=True)   # noqa: SLF001
    assert got["unoffered"] == {"cicada_write_claim": 1}


def test_own_token_keys_read_as_this_devices_elsewhere_and_back(home):
    import asyncio

    async def work():
        return 200, {"ok": 1}

    asyncio.run(idempotency.run_once("server|bank:b", "/tools/call:x", "k-own-1234", work))
    asyncio.run(idempotency.run_once("device:dddddddd|bank:b", "/tools/call:x", "k-dev-1234", work))
    rows = idempotency.export_since(0, me="mmmmmmmm")
    scopes = {r["scope"] for r in rows}
    assert scopes == {"device:mmmmmmmm|bank:b", "device:dddddddd|bank:b"}
    # Imported at the device that was "mmmmmmmm" there, its own device's keys are its own token's here.
    with idempotency._db() as db:   # noqa: SLF001
        db.execute("DELETE FROM keys")
    idempotency.import_rows(rows, me="mmmmmmmm")
    with idempotency._db() as db:   # noqa: SLF001
        assert {r[0] for r in db.execute("SELECT scope FROM keys")} == {"server|bank:b", "device:dddddddd|bank:b"}


def test_sync_keys_is_paged(home):
    import asyncio

    for i in range(7):
        async def work():
            return 200, {"i": 1}
        asyncio.run(idempotency.run_once("server|bank:b", "/tools/call:x", f"key-number-{i:04d}", work))
    seen, since, after = [], 0.0, ""
    while True:
        page = idempotency.export_since(since, after=after, limit=3)
        if not page:
            break
        seen += page
        since, after = page[-1]["created"], page[-1]["keyHash"]
    assert len(seen) == 7 and len({r["keyHash"] for r in seen}) == 7


def test_the_take_over_words_carry_the_key_window(home, monkeypatch):
    from api.services import replica, runtime_layout

    monkeypatch.setattr(runtime_layout, "is_replica", lambda environ=None: True)
    monkeypatch.setattr(replica, "state", lambda: {"seq": 4, "homeSeq": 6, "lastContact": None})
    monkeypatch.setattr(replica, "request", lambda *a, **k: (None, {}, None))
    monkeypatch.setattr(home_move, "_another_home", lambda *a, **k: None)
    text = home_move.take_over_preview(home)["text"]
    assert "2 changes behind" in text and "about the last minute" in text


def test_another_home_asks_every_device_at_once(home, monkeypatch):
    rows = [{"id": f"{c * 8}", "name": f"d-{c}", "kind": "full", "address": f"https://{c}.example"} for c in "abcdef"]
    monkeypatch.setattr(home_move, "registry", lambda _p: rows)
    monkeypatch.setattr(home_move, "_own_token", lambda: "cic_dev_zzzzzzzz_" + "x" * 43)
    monkeypatch.setattr(home_move, "my_device_id", lambda: "zzzzzzzz")
    monkeypatch.setattr(home_move, "_pin", lambda: home_move._Pin("b" * 32))   # noqa: SLF001

    def slow(*a, **k):
        time.sleep(0.5)
        return None, None

    monkeypatch.setattr(home_move, "_ask", slow)
    started = time.perf_counter()
    assert home_move._another_home(home, 0) is None   # noqa: SLF001
    assert time.perf_counter() - started < 1.5          # six devices at 0.5 s each, asked together
