"""Hermetic tests for the Telegram capture connector.

Covers the parse (Stage 1) and route+emit (Stage 2) layers of
``api/services/telegram_capture.py`` with injected ``save_url_fn`` /
``save_episode_fn`` doubles — no network, no live bot, no live filesystem
(everything lands in ``tmp_path``) — plus the ``POST /capture/telegram``
token gate.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from api.services import telegram_capture
from api.services.telegram_capture import ingest_telegram_update, parse_telegram_update


def run(coro):
    return asyncio.run(coro)


# --- fixtures ---------------------------------------------------------------


def _text_update(text: str, **overrides) -> dict:
    message = {
        "message_id": 1,
        "from": {"id": 111, "is_bot": False, "first_name": "Rodrigo"},
        "chat": {"id": 111, "type": "private"},
        "date": 1_750_000_000,
        "text": text,
    }
    message.update(overrides)
    return {"update_id": 1, "message": message}


# --- parse_telegram_update ---------------------------------------------------


def test_parse_extracts_text_and_url():
    update = _text_update("check this out https://example.com/article")
    parsed = parse_telegram_update(update)
    assert parsed is not None
    assert parsed["text"] == "check this out https://example.com/article"
    assert parsed["urls"] == ["https://example.com/article"]
    assert parsed["from_self"] is True
    assert parsed["date"] is not None


def test_parse_text_only_has_no_urls():
    update = _text_update("remember to buy milk")
    parsed = parse_telegram_update(update)
    assert parsed is not None
    assert parsed["text"] == "remember to buy milk"
    assert parsed["urls"] == []


def test_parse_text_link_entity_extracts_hidden_url():
    update = _text_update(
        "cool read",
        entities=[{"type": "text_link", "offset": 0, "length": 4, "url": "https://hidden.example.com"}],
    )
    parsed = parse_telegram_update(update)
    assert parsed["urls"] == ["https://hidden.example.com"]


def test_parse_forwarded_message_marks_not_from_self():
    update = _text_update("interesting", forward_date=1_750_000_001)
    parsed = parse_telegram_update(update)
    assert parsed is not None
    assert parsed["from_self"] is False


def test_parse_non_message_update_returns_none():
    assert parse_telegram_update({"update_id": 2, "edited_message": {"text": "x"}}) is None
    assert parse_telegram_update({"update_id": 3, "callback_query": {"id": "abc"}}) is None
    assert parse_telegram_update({}) is None
    assert parse_telegram_update("not a dict") is None  # type: ignore[arg-type]


def test_parse_message_with_no_text_and_no_url_returns_none():
    update = {"update_id": 4, "message": {"message_id": 1, "date": 1, "sticker": {"file_id": "abc"}}}
    assert parse_telegram_update(update) is None


# --- ingest_telegram_update (injected save fns, no filesystem/network) ------


def test_ingest_url_message_calls_save_url_fn(tmp_path):
    memory = tmp_path / "memory"
    calls = []

    def fake_save_url(memory_path, url, *, note=None):
        calls.append((memory_path, url, note))
        return {"status": "created", "media_entity_id": "media-example", "episode_id": "ep_x"}

    update = _text_update("look at this https://example.com/thing")
    result = run(
        ingest_telegram_update(memory, update, save_url_fn=fake_save_url, save_episode_fn=None)
    )

    assert result["kind"] == "url"
    assert result["url"] == "https://example.com/thing"
    assert result["result"]["media_entity_id"] == "media-example"
    assert len(calls) == 1
    assert calls[0][0] == memory
    assert calls[0][1] == "https://example.com/thing"


def test_ingest_url_message_save_url_fn_may_be_async(tmp_path):
    memory = tmp_path / "memory"

    async def fake_save_url(memory_path, url, *, note=None):
        return {"status": "created", "media_entity_id": "media-async", "episode_id": "ep_a"}

    update = _text_update("https://async.example.com")
    result = run(ingest_telegram_update(memory, update, save_url_fn=fake_save_url))
    assert result["kind"] == "url"
    assert result["result"]["media_entity_id"] == "media-async"


def test_ingest_text_only_message_stages_episode(tmp_path):
    memory = tmp_path / "memory"
    calls = []

    def fake_save_episode(memory_path, text, *, title=None):
        calls.append((memory_path, text, title))
        return {"status": "created", "episode_id": "ep_2026-07-02_001"}

    update = _text_update("remember to call the dentist")
    result = run(
        ingest_telegram_update(
            memory, update, save_url_fn=None, save_episode_fn=fake_save_episode
        )
    )

    assert result["kind"] == "note"
    assert result["result"]["episode_id"] == "ep_2026-07-02_001"
    assert len(calls) == 1
    assert calls[0][1] == "remember to call the dentist"
    # save_url_fn must NOT have been invoked for a text-only message.


def test_ingest_prefers_url_path_when_both_text_and_url_present(tmp_path):
    memory = tmp_path / "memory"
    url_calls = []
    episode_calls = []

    def fake_save_url(memory_path, url, *, note=None):
        url_calls.append(url)
        return {"status": "created"}

    def fake_save_episode(memory_path, text, *, title=None):
        episode_calls.append(text)
        return {"status": "created"}

    update = _text_update("note with a link https://example.com/x")
    result = run(
        ingest_telegram_update(
            memory, update, save_url_fn=fake_save_url, save_episode_fn=fake_save_episode
        )
    )
    assert result["kind"] == "url"
    assert url_calls == ["https://example.com/x"]
    assert episode_calls == []


def test_ingest_non_message_update_is_skipped(tmp_path):
    memory = tmp_path / "memory"
    result = run(ingest_telegram_update(memory, {"update_id": 9, "poll_answer": {}}))
    assert result["kind"] == "skipped"


def test_ingest_never_raises_when_save_fn_errors(tmp_path):
    memory = tmp_path / "memory"

    def boom(memory_path, text, *, title=None):
        raise RuntimeError("disk full")

    update = _text_update("a note that will fail to save")
    result = run(ingest_telegram_update(memory, update, save_episode_fn=boom))
    assert result["kind"] == "skipped"
    assert "reason" in result


def test_default_save_episode_writes_staged_episode(tmp_path):
    """The real (non-injected) writer, exercised directly — hermetic, tmp_path only."""
    memory = tmp_path / "memory"
    result = telegram_capture._default_save_episode(memory, "hello from telegram")
    assert result["status"] == "created"

    episode_files = list((memory / "episodes").glob("*.md"))
    assert len(episode_files) == 1
    content = episode_files[0].read_text(encoding="utf-8")
    assert "origin: telegram" in content
    assert "source: telegram" in content
    assert "processed: false" in content


def test_default_save_episode_dedups_by_content_hash(tmp_path):
    memory = tmp_path / "memory"
    first = telegram_capture._default_save_episode(memory, "same text twice")
    second = telegram_capture._default_save_episode(memory, "same text twice")
    assert first["status"] == "created"
    assert second["status"] == "duplicate"
    assert len(list((memory / "episodes").glob("*.md"))) == 1


# --- POST /capture/telegram endpoint ----------------------------------------


def _client(tmp_path, monkeypatch, token: str = ""):
    from api import config, main

    memory = tmp_path / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    if token:
        monkeypatch.setenv("CICADA_TELEGRAM_BOT_TOKEN", token)
    else:
        monkeypatch.delenv("CICADA_TELEGRAM_BOT_TOKEN", raising=False)
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_capture_telegram_503_when_not_configured(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, token="")
    resp = client.post("/capture/telegram", json=_text_update("hello"))
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


def test_capture_telegram_dispatches_when_token_set(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch, token="fake-token-123")

    async def fake_ingest(memory_path, update, **kwargs):
        return {"kind": "note", "result": {"status": "created", "episode_id": "ep_test_001"}}

    monkeypatch.setattr(
        "api.routers.capture.ingest_telegram_update", fake_ingest
    )

    resp = client.post("/capture/telegram", json=_text_update("hello from the endpoint"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "note"
    assert body["result"]["episode_id"] == "ep_test_001"


def test_settings_telegram_enabled_reflects_token(monkeypatch):
    from api.config import Settings

    assert Settings(telegram_bot_token="").telegram_enabled is False
    assert Settings(telegram_bot_token="abc123").telegram_enabled is True
