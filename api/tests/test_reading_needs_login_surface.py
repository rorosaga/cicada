"""G166 — a login wall surfaces at once: stored outside the bank (no bank write, no
commit, no Sleep gate), the `reading` sync component moves, and `GET /sources`
returns the state under a new ETag. The agent's own reply tells it to stop."""
from __future__ import annotations

import hashlib
import os
import subprocess

from fastapi.testclient import TestClient

from _reading_fixtures import PUBLIC, WALLED, ask, git_log, reading, record  # noqa: F401
from api import config, main
from api.remote import catalog
from api.remote.runtime import BUSY_TEXT, RemoteRuntime
from api.services import media_ingestor, mcp_tools, reading_asks, sync_service


def _tree(memory) -> str:
    """Every file under the bank, `.git` included, hashed: any bank write shows."""
    digest = hashlib.sha256()
    for root, dirs, files in os.walk(memory):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(root, name)
            digest.update(path.encode())
            with open(path, "rb") as handle:
                digest.update(handle.read())
    return digest.hexdigest()


def _client(memory, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app)


def test_needs_login_changes_no_bank_file_and_makes_no_commit(reading):
    server, memory = reading
    ask(memory, WALLED)
    before, head = _tree(memory), git_log(memory)
    out = record(server, url=WALLED, outcome="needs_login", via="Claude in Chrome")
    assert _tree(memory) == before and git_log(memory) == head
    assert out == ("Recorded: the person needs to sign in to x.com. Stop on this page. Do not sign in, type "
                   "credentials or try another route. Move to the next link. It shows on the link in Cicada's Feed.")
    row = reading_asks.get(memory, media_ingestor.url_hash(WALLED))
    assert row["state"] == "needs_login" and row["via"] == "Claude in Chrome"


def test_every_non_read_outcome_is_ask_store_only(reading):
    server, memory = reading
    ask(memory, PUBLIC)
    before = _tree(memory)
    for outcome in ("blocked", "not_found", "failed", "needs_login"):
        assert record(server, outcome=outcome).startswith("Recorded:")
        assert _tree(memory) == before
        assert reading_asks.get(memory, media_ingestor.url_hash(PUBLIC))["state"] == outcome


def test_it_succeeds_while_sleep_runs_on_stdio(reading, monkeypatch):
    server, memory = reading
    ask(memory, WALLED)
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: True)
    assert record(server, url=WALLED, outcome="needs_login").startswith("Recorded: the person needs to sign in")


def test_it_succeeds_while_sleep_runs_remotely_but_a_read_waits(reading):
    _, memory = reading
    ask(memory, WALLED)
    runtime = RemoteRuntime(memory_path=lambda: memory, post=lambda p, d: {}, sleep_running=lambda: True)
    phone = catalog.Connector(id="aaaaaaaa", label="Phone", app="claude", scopes=catalog.DEFAULT_SCOPES,
                              created_at="2026-09-01T00:00:00+00:00")
    text, status = runtime.call(phone, "cicada_record_read", {"url": WALLED, "outcome": "needs_login"})
    assert status == "ok" and text.startswith("Recorded: the person needs to sign in"), text
    text, status = runtime.call(phone, "cicada_record_read",
                                {"url": WALLED, "outcome": "read", "summary": "A summary of the page."})
    assert (text, status) == (BUSY_TEXT, "busy")
    text, status = runtime.call(phone, "cicada_save_url", {"url": "https://blog.bob-example.org/x"})
    assert status == "busy", "every other write still waits"


def test_the_sync_component_moves_and_sources_serves_the_state_under_a_new_etag(reading, monkeypatch):
    server, memory = reading
    ask(memory, WALLED)
    client = _client(memory, monkeypatch)
    try:
        first = client.get("/sources")
        (item,) = first.json()["items"]
        assert item["read"]["status"] == "waiting" and item["read"]["siteKey"] == "x" and item["read"]["askable"]
        assert item["read"]["wall"] == "walled" and item["read"]["siteAllowed"] is False and "hostKey" not in item["read"]
        etag = first.headers["ETag"]
        assert client.get("/sources", headers={"If-None-Match": etag}).status_code == 304
        component = sync_service.components(memory)["reading"]
        record(server, url=WALLED, outcome="needs_login")
        # a same-tick rewrite can share an mtime on a coarse clock: the store's file moved regardless
        os.utime(reading_asks.path_for(memory), ns=(0, reading_asks.path_for(memory).stat().st_mtime_ns + 7_000_000))
        assert sync_service.components(memory)["reading"] != component
        second = client.get("/sources", headers={"If-None-Match": etag})
        assert second.status_code == 200 and second.headers["ETag"] != etag
        (item,) = second.json()["items"]
        assert item["read"]["status"] == "needs_login" and item["read"]["by"] == "agent"
        assert item["read"]["host"] == "x.com" and item["read"]["at"]
    finally:
        config.get_settings.cache_clear()


def test_a_newer_ask_after_a_wall_reads_as_waiting_again(reading, monkeypatch):
    server, memory = reading
    ask(memory, WALLED)
    record(server, url=WALLED, outcome="needs_login")
    client = _client(memory, monkeypatch)
    try:
        (item,) = client.get("/sources").json()["items"]
        assert item["read"]["status"] == "needs_login"
        ask(memory, WALLED)
        (item,) = client.get("/sources").json()["items"]
        assert item["read"]["status"] == "waiting" and "outcome" not in item["read"]
    finally:
        config.get_settings.cache_clear()
