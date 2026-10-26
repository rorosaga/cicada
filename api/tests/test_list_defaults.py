"""Saved lists on by default for an existing install (owner 2026-10-26; ``list_defaults``): only accounts the memory
shows, only once agent reading counts, never over an off — applied when the Sources page reads its settings."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, list_defaults, reading_settings, saved_lists, youtube_lists


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()


def _bank(tmp_path, origins):
    bank = tmp_path / "bank"
    (bank / "episodes").mkdir(parents=True)
    for i, origin in enumerate(origins):
        (bank / "episodes" / f"2026-01-0{i + 1}-001.md").write_text(
            f"---\nid: 2026-01-0{i + 1}-001\norigin: {origin}\nprocessed: true\n---\nplaceholder\n", encoding="utf-8")
    bank_index.invalidate(bank)
    return bank


def test_detected_reads_the_accounts_from_episode_origins(tmp_path):
    bank = _bank(tmp_path, ["youtube-history", "x-likes", "claude-code"])
    assert list_defaults.detected(bank) == {"youtube", "x"}


def test_apply_turns_on_detected_accounts_once_acknowledged(tmp_path):
    bank = _bank(tmp_path, ["instagram-saved"])
    assert list_defaults.apply(bank) == [], "no acknowledgement, no default"
    reading_settings.update(acknowledge=True, today=date(2026, 10, 26))
    assert list_defaults.apply(bank) == ["saved:instagram"]
    assert saved_lists.allowed("instagram") and not saved_lists.allowed("x")
    assert saved_lists.due(bank) == ["instagram"], "the standing ask reaches the agent's queue"


def test_apply_records_a_list_read_before_as_off(tmp_path):
    bank = _bank(tmp_path, ["youtube-playlist"])
    reading_settings.update(acknowledge=True)
    youtube_lists.note(bank, "watch_later", "read", videos=3)
    assert list_defaults.apply(bank) == ["youtube:watch_later", "youtube:history"]
    assert not youtube_lists.allowed("watch_later") and youtube_lists.allowed("history")


def test_the_settings_route_applies_the_defaults(tmp_path, monkeypatch):
    from _synthetic_bank import _bank as synthetic

    memory = synthetic(tmp_path / "synthetic")
    (memory / "episodes" / "2026-01-01-901.md").write_text(
        "---\nid: 2026-01-01-901\norigin: linkedin-saved\nprocessed: true\n---\nplaceholder\n", encoding="utf-8")
    bank_index.invalidate(memory)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    reading_settings.update(acknowledge=True)
    try:
        body = TestClient(main.app).get("/reading/settings").json()
    finally:
        config.get_settings.cache_clear()
    assert body["savedLists"] == {"x": False, "instagram": False, "linkedin": True}
    assert body["savedListsOff"] == {"x": False, "instagram": False, "linkedin": False}
