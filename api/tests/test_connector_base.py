"""Hermetic tests for the shared ``base.run_sync``/``base.forget`` skeleton
(Task 15 §2, §4) that every connector's ``sync()``/``forget()`` now wraps.

These exercise the shared driver directly with a synthetic ``fetch``, rather
than through a real connector — the per-platform contract tests
(test_connector_{pinterest,reddit,x}.py) still cover each adapter's actual
``fetch`` logic end to end.
"""

from __future__ import annotations

import asyncio

import pytest

from api.services import media_ingestor, sync_state
from api.services.connections import secrets
from api.services.connectors import base
from api.services.media_ingestor import RawItem


def run(coro):
    return asyncio.run(coro)


def _memory(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)

    async def offline(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(
            title=media_ingestor._fallback_title(url), description="",
            site=media_ingestor._site_of(url), media_type="url")

    async def no_commit(memory_path, count):
        return None

    monkeypatch.setattr(media_ingestor, "enrich", offline)
    monkeypatch.setattr(media_ingestor, "_commit_media", no_commit)
    return memory


def test_run_sync_skips_when_not_connected(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    called = []

    async def fetch(fn):
        called.append(1)
        return [], None

    result = run(base.run_sync(
        "acme", memory, fetch, is_connected=lambda: False))
    assert result == {"status": "skipped", "reason": "not connected",
                       "new": 0, "seen": 0, "error": None}
    assert called == [], "fetch must never run when not connected"


def test_run_sync_skips_when_the_network_gate_is_closed(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    called = []

    async def fetch(fn):
        called.append(1)
        return [], None

    result = run(base.run_sync(
        "acme", memory, fetch, is_connected=lambda: True, allow_fetch=False))
    assert result == {"status": "skipped", "reason": "network disabled",
                       "new": 0, "seen": 0, "error": None}
    assert called == [], "fetch must never run with the gate closed"


def test_run_sync_never_raises_and_records_the_error(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)

    async def fetch(fn):
        raise RuntimeError("boom")

    result = run(base.run_sync(
        "acme", memory, fetch, is_connected=lambda: True,
        http_fn=lambda *a, **k: None))
    assert result["status"] == "error"
    assert result["reason"] is None
    assert result["new"] == 0 and result["seen"] == 0
    assert result["error"] == "RuntimeError: boom"
    assert "boom" in sync_state.read_sync_state(memory)["acme"]["last_error"]


def test_run_sync_ingests_and_records_a_success_with_extra_cursor_state(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    items = [RawItem(url="https://example.com/a", origin="acme"),
              RawItem(url="https://example.com/b", origin="acme")]

    async def fetch(fn):
        return items, {"cursor": "abc123"}

    result = run(base.run_sync(
        "acme", memory, fetch, is_connected=lambda: True,
        http_fn=lambda *a, **k: None))
    assert result == {"status": "ok", "reason": None, "new": 2, "seen": 2, "error": None}
    entry = sync_state.read_sync_state(memory)["acme"]
    assert entry["count"] == 2
    assert entry["cursor"] == "abc123"


def test_run_sync_is_idempotent_via_the_url_index(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    items = [RawItem(url="https://example.com/a", origin="acme")]

    async def fetch(fn):
        return items, None

    run(base.run_sync("acme", memory, fetch, is_connected=lambda: True,
                       http_fn=lambda *a, **k: None))
    second = run(base.run_sync("acme", memory, fetch, is_connected=lambda: True,
                                http_fn=lambda *a, **k: None))
    assert second["new"] == 0
    assert second["seen"] == 1


def test_run_sync_drops_no_platform_specific_counters(tmp_path, monkeypatch):
    """Task 15 §2: the canonical dict carries no ``boards``/``pages`` (or any
    other per-platform) counter — a caller that wants one adds it itself
    after calling in, the way ``x.sync()`` adds ``resources_read``."""
    memory = _memory(tmp_path, monkeypatch)

    async def fetch(fn):
        return [], None

    result = run(base.run_sync("acme", memory, fetch, is_connected=lambda: True,
                                http_fn=lambda *a, **k: None))
    assert set(result) == {"status", "reason", "new", "seen", "error"}


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    names = ("BASE_TEST_A", "BASE_TEST_B")
    for name in names:
        monkeypatch.delenv(name, raising=False)
    yield
    for name in names:
        os.environ.pop(name, None)


def test_forget_removes_every_named_secret():
    secrets.set_secret("BASE_TEST_A", "value-a")
    secrets.set_secret("BASE_TEST_B", "value-b")
    base.forget(("BASE_TEST_A", "BASE_TEST_B"))
    assert not secrets.has_secret("BASE_TEST_A")
    assert not secrets.has_secret("BASE_TEST_B")


def test_forget_tolerates_a_name_that_was_never_set():
    base.forget(("BASE_TEST_A", "BASE_TEST_B"))  # neither was ever stored
    assert not secrets.has_secret("BASE_TEST_A")
