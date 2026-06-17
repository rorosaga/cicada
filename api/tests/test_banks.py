"""Hermetic tests for memory banks (M6) + chat-history import (M7).

Every test points ``CICADA_MEMORY_PATH`` at its own ``tmp_path`` root and clears
the ``get_settings`` lru-cache, so the live ``memory/`` is never touched and no
real export is ever loaded. Fixtures are tiny inline snippets.

Coverage:
- bank_registry resolution: legacy fallback (no banks.yaml), unknown active
  pointer degrades gracefully, create / activate-switches-memory_path / duplicate;
- Settings.memory_path is a live property that follows a bank switch with no
  restart (the load-bearing M6 guarantee);
- import staging: Claude conversations.json backdates episode timestamps to the
  conversation's created_at, Gemini MyActivity.html parses + backdates, dedup
  works against the target bank.
"""

from __future__ import annotations

import json

import pytest

from api import config
from api.services import bank_registry, markdown_parser


# --- bank_registry: resolution + legacy fallback ---------------------------


def test_legacy_fallback_no_registry(tmp_path):
    """No banks.yaml -> resolve returns the root unchanged (pre-banks behavior)."""
    assert bank_registry.resolve_active_bank_path(tmp_path) == tmp_path


def test_unknown_active_pointer_degrades_to_root(tmp_path):
    """A dangling ``active`` pointer must not break resolution."""
    bank_registry.save_registry(
        tmp_path,
        {"active": "ghost", "banks": {"default": {"legacy": True}}},
    )
    assert bank_registry.resolve_active_bank_path(tmp_path) == tmp_path


def test_corrupt_registry_degrades_to_root(tmp_path):
    bank_registry.registry_path(tmp_path).write_text("{[ not yaml", encoding="utf-8")
    assert bank_registry.resolve_active_bank_path(tmp_path) == tmp_path


def test_create_scaffolds_and_resolves(tmp_path):
    slug = bank_registry.create_bank(tmp_path, "Claude Import", "from export")
    assert slug == "claude-import"
    bank_path = tmp_path / "banks" / "claude-import"
    assert (bank_path / "episodes").is_dir()
    assert (bank_path / "entities").is_dir()
    # Created but NOT activated.
    assert bank_registry.resolve_active_bank_path(tmp_path) == tmp_path


def test_create_duplicate_name_rejected(tmp_path):
    bank_registry.create_bank(tmp_path, "Research")
    with pytest.raises(ValueError):
        bank_registry.create_bank(tmp_path, "research")


def test_activate_switches_resolution(tmp_path):
    bank_registry.create_bank(tmp_path, "Research")
    bank_registry.activate_bank(tmp_path, "research")
    assert (
        bank_registry.resolve_active_bank_path(tmp_path)
        == tmp_path / "banks" / "research"
    )
    # Switching back to legacy default resolves to root again.
    bank_registry.activate_bank(tmp_path, "default")
    assert bank_registry.resolve_active_bank_path(tmp_path) == tmp_path


def test_activate_unknown_rejected(tmp_path):
    with pytest.raises(ValueError):
        bank_registry.activate_bank(tmp_path, "nope")


def test_duplicate_copies_content_not_git(tmp_path):
    # Seed the legacy default (root) with one entity + a .git dir.
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    (tmp_path / "entities" / "x.md").write_text("---\nid: x\n---\nbody\n", encoding="utf-8")
    (tmp_path / ".git").mkdir(exist_ok=True)
    (tmp_path / ".git" / "marker").write_text("source-history", encoding="utf-8")

    new_slug = bank_registry.duplicate_bank(tmp_path, "default", "Snapshot")
    assert new_slug == "snapshot"
    copy = tmp_path / "banks" / "snapshot"
    # Content copied.
    assert (copy / "entities" / "x.md").read_text(encoding="utf-8").endswith("body\n")
    # Source git history NOT forked into the copy.
    assert not (copy / ".git" / "marker").exists()
    # The banks/ container + registry were not recursively copied.
    assert not (copy / "banks").exists()
    assert not (copy / "banks.yaml").exists()


def test_list_banks_counts(tmp_path):
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    (tmp_path / "entities" / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "episodes" / "ep_2026-01-01_001.md").write_text("e", encoding="utf-8")
    bank_registry.create_bank(tmp_path, "Other")

    data = bank_registry.list_banks(tmp_path)
    assert data["active"] == "default"
    by_name = {b["name"]: b for b in data["banks"]}
    assert by_name["default"]["entity_count"] == 1
    assert by_name["default"]["episode_count"] == 1
    assert by_name["default"]["active"] is True
    assert by_name["other"]["episode_count"] == 0


# --- Settings.memory_path is a live property -------------------------------


def test_settings_memory_path_follows_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    config.get_settings.cache_clear()
    settings = config.get_settings()

    # No banks yet -> resolves to root.
    assert settings.memory_path == tmp_path
    assert settings.memory_root == tmp_path

    bank_registry.create_bank(tmp_path, "Lab")
    bank_registry.activate_bank(tmp_path, "lab")

    # SAME cached Settings instance now resolves to the new bank — no restart.
    assert settings.memory_path == tmp_path / "banks" / "lab"
    config.get_settings.cache_clear()


# --- HTTP endpoints --------------------------------------------------------


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    config.get_settings.cache_clear()
    # Scaffold the legacy default so counts/imports have a real dir.
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    return TestClient(main.app)


def test_get_banks_lists_default(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/banks")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["active"] == "default"
    assert any(b["name"] == "default" and b["active"] for b in body["banks"])
    # camelCase wire keys.
    assert "entityCount" in body["banks"][0]
    config.get_settings.cache_clear()


def test_create_then_activate_then_duplicate(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    r = client.post("/banks", json={"name": "Claude Export", "description": "d"})
    assert r.status_code == 200, r.text
    names = {b["name"] for b in r.json()["banks"]}
    assert "claude-export" in names

    r = client.post("/banks/claude-export/activate")
    assert r.status_code == 200
    assert r.json()["active"] == "claude-export"

    r = client.post("/banks/claude-export/duplicate", json={"newName": "Backup"})
    assert r.status_code == 200
    names = {b["name"] for b in r.json()["banks"]}
    assert "backup" in names
    config.get_settings.cache_clear()


def test_activate_unknown_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.post("/banks/ghost/activate").status_code == 404
    config.get_settings.cache_clear()


def test_create_conflict_409(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/banks", json={"name": "Dup"})
    r = client.post("/banks", json={"name": "dup"})
    assert r.status_code == 409
    config.get_settings.cache_clear()


# --- Import: Claude conversations.json backdating + dedup ------------------


_CLAUDE_EXPORT = [
    {
        "uuid": "c1",
        "name": "Thesis planning",
        "created_at": "2026-02-24T12:39:02.701295Z",
        "chat_messages": [
            {
                "uuid": "m1",
                "sender": "human",
                "text": "What is the capstone deadline?",
                "content": [],
                "created_at": "2026-02-24T12:39:02.701295Z",
            },
            {
                "uuid": "m2",
                "sender": "assistant",
                "text": "It is in June.",
                "content": [],
                "created_at": "2026-02-24T12:39:10.000000Z",
            },
        ],
    },
    {
        "uuid": "c2",
        "name": "Older chat",
        "created_at": "2025-11-03T08:00:00.000000Z",
        "chat_messages": [
            {
                "uuid": "m3",
                "sender": "human",
                "text": "Hello there from last year.",
                "content": [],
                "created_at": "2025-11-03T08:00:00.000000Z",
            },
        ],
    },
]


def _upload(client, name, payload, filename="conversations.json"):
    return client.post(
        f"/banks/{name}/import",
        files={"file": (filename, json.dumps(payload).encode(), "application/json")},
    )


def test_import_claude_backdates_episodes(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/banks", json={"name": "Imports"})

    r = _upload(client, "imports", _CLAUDE_EXPORT)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["format"] == "claude"
    assert body["episodesStaged"] == 2
    assert body["duplicatesSkipped"] == 0
    assert body["dateRange"]["from"] == "2025-11-03"
    assert body["dateRange"]["to"] == "2026-02-24"

    # Episodes land in the TARGET bank, backdated to the conversation date.
    ep_dir = tmp_path / "banks" / "imports" / "episodes"
    files = sorted(ep_dir.glob("*.md"))
    assert len(files) == 2
    stems = {f.stem for f in files}
    assert "ep_2026-02-24_001" in stems
    assert "ep_2025-11-03_001" in stems

    parsed = markdown_parser.parse(ep_dir / "ep_2026-02-24_001.md")
    assert parsed.frontmatter["timestamp"] == "2026-02-24T12:39:02.701295Z"
    assert parsed.frontmatter["origin"] == "claude-export"
    assert parsed.frontmatter["processed"] is False

    # Nothing leaked into the legacy default bank.
    assert not list((tmp_path / "episodes").glob("*.md"))
    config.get_settings.cache_clear()


def test_import_dedup_against_target_bank(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/banks", json={"name": "Imports"})

    _upload(client, "imports", _CLAUDE_EXPORT)
    r2 = _upload(client, "imports", _CLAUDE_EXPORT)
    assert r2.status_code == 200
    assert r2.json()["episodesStaged"] == 0
    assert r2.json()["duplicatesSkipped"] == 2
    config.get_settings.cache_clear()


def test_import_unknown_bank_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = _upload(client, "ghost", _CLAUDE_EXPORT)
    assert r.status_code == 404
    config.get_settings.cache_clear()


# --- Import: Gemini MyActivity.html backdating -----------------------------


_GEMINI_HTML = """<!DOCTYPE html>
<html><body>
<div class="outer-cell mdl-cell">
  <div class="content-cell mdl-typography--body-1">
    Prompted Gemini with: Summarize my robotics notes
    <br>Feb 24, 2026, 12:39:02 PM PST
  </div>
</div>
<div class="outer-cell mdl-cell">
  <div class="content-cell mdl-typography--body-1">
    Asked about the capstone deadline
    <br>Nov 3, 2025, 8:00:00 AM PST
  </div>
</div>
</body></html>
"""


def test_import_gemini_backdates(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/banks", json={"name": "Gem"})

    r = client.post(
        "/banks/gem/import",
        files={"file": ("MyActivity.html", _GEMINI_HTML.encode(), "text/html")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["format"] == "gemini"
    assert body["episodesStaged"] == 2
    assert body["dateRange"]["from"] == "2025-11-03"
    assert body["dateRange"]["to"] == "2026-02-24"

    ep_dir = tmp_path / "banks" / "gem" / "episodes"
    stems = {f.stem for f in ep_dir.glob("*.md")}
    assert "ep_2026-02-24_001" in stems
    assert "ep_2025-11-03_001" in stems

    parsed = markdown_parser.parse(ep_dir / "ep_2026-02-24_001.md")
    assert parsed.frontmatter["origin"] == "gemini-export"
    config.get_settings.cache_clear()
