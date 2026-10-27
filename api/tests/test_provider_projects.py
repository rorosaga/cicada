"""Ruling 45 addendum (2026-10-27): projects the person already made in Claude and ChatGPT. Synthetic exports only."""
from __future__ import annotations

import json

import pytest

from api import config
from api.routers import conversations as conv
from api.routers import intake
from api.services import (bank_index, bank_registry, entity_extractor, markdown_parser, project_conversations,
                          project_ownership, project_timeline, provider_projects)

PROJECTS = [
    {"uuid": "11111111-aaaa-4bbb-8ccc-000000000001", "name": "Cedar Canoe Example", "description": "A strip canoe.",
     "prompt_template": "Answer as a boat builder.", "is_starter_project": False, "created_at": "2026-08-01T10:00:00Z",
     "updated_at": "2026-08-02T10:00:00Z", "docs": [{"filename": "plans.pdf", "content": "never read"}]},
    {"uuid": "11111111-aaaa-4bbb-8ccc-000000000002", "name": "Empty Example", "description": "", "prompt_template": "",
     "is_starter_project": False, "created_at": "2026-08-03T10:00:00Z", "docs": []},
    {"uuid": "11111111-aaaa-4bbb-8ccc-000000000003", "name": "How to use Claude", "description": "x",
     "prompt_template": "y", "is_starter_project": True, "created_at": "2026-08-01T10:00:00Z", "docs": []},
]


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    config.get_settings.cache_clear()
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    bank_index.invalidate()
    yield tmp_path
    config.get_settings.cache_clear()


def _import(bank, data):
    return intake.import_bytes(json.dumps(data).encode(), "projects.json", config.get_settings())


def _pages(bank):
    return {p.stem: markdown_parser.parse(p).frontmatter for p in (bank / "entities").glob("*.md")}


def test_every_non_starter_project_becomes_the_persons_page(bank):
    _import(bank, PROJECTS)
    pages = _pages(bank)
    assert set(pages) == {"cedar-canoe-example", "empty-example"}
    fm = pages["cedar-canoe-example"]
    assert fm["type"] == "project" and fm["born"]["origin"] == "created" and fm["born"]["via"] == "claude-export"
    assert fm["born"]["day"] == "2026-08-01"
    assert fm["mine"]["via"] == "import" and project_ownership.CLAUDE_EXPORT_MINE
    assert fm["description"] == "A strip canoe."
    entry = fm["provider_projects"][0]
    assert entry["provider"] == "claude" and entry["docs"] == ["plans.pdf"] and entry["episode"].startswith("ep_")
    t = project_timeline.build(bank, "cedar-canoe-example", tz_name="UTC")
    k = t.knowledge[0]
    assert k.instructions == "Answer as a boat builder." and k.docs == ["plans.pdf"]


def test_a_reimport_is_idempotent_and_never_brings_back_a_deleted_page(bank):
    _import(bank, PROJECTS)
    episodes = sorted(p.name for p in (bank / "episodes").glob("*.md"))
    _import(bank, PROJECTS)
    assert sorted(p.name for p in (bank / "episodes").glob("*.md")) == episodes
    assert set(_pages(bank)) == {"cedar-canoe-example", "empty-example"}
    (bank / "entities" / "empty-example.md").unlink()
    bank_index.invalidate()
    _import(bank, PROJECTS)
    assert "empty-example" not in _pages(bank)


def test_a_not_mine_page_stays_not_mine_and_a_persons_description_is_never_replaced(bank):
    _import(bank, PROJECTS)
    project_ownership.dismiss(bank, "cedar-canoe-example")
    project_ownership.set_header(bank, "cedar-canoe-example", desc="My own words.")
    bank_index.invalidate()
    _import(bank, [{**PROJECTS[0], "description": "Changed in Claude."}])
    fm = _pages(bank)["cedar-canoe-example"]
    assert "mine" not in fm and fm["not_mine"] and fm["description"] == "My own words."


def test_an_existing_project_page_of_that_name_takes_the_id(bank):
    markdown_parser.write(bank / "entities" / "cedar-canoe.md",
                          {"name": "Cedar Canoe Example", "type": "project", "status": "active"}, "## Summary\nA.")
    bank_index.invalidate()
    provider_projects.adopt_claude(bank, conv.claude_project_list(PROJECTS[:1]))
    pages = _pages(bank)
    assert "cedar-canoe-example" not in pages
    assert pages["cedar-canoe"]["provider_projects"][0]["id"] == PROJECTS[0]["uuid"]
    assert pages["cedar-canoe"]["description"] == "A strip canoe."


def test_a_bank_that_imported_projects_before_gets_no_second_episode(bank):
    old = [{k: v for k, v in e.items() if k not in ("source_id", "source_updated_at", "legacy_hashes")}
           for e in conv._stamp_origin(conv.parse_anthropic_projects(PROJECTS), "claude-export")]
    conv._stage_export(old, bank / "episodes")
    before = sorted(p.name for p in (bank / "episodes").glob("*.md"))
    _import(bank, PROJECTS)
    assert sorted(p.name for p in (bank / "episodes").glob("*.md")) == before


def test_a_chatgpt_project_id_rides_on_the_episode_and_a_custom_gpt_never_does():
    base = {"title": "t", "create_time": 1767225600, "mapping": {"a": {"message": {
        "author": {"role": "user"}, "content": {"parts": ["hello"]}, "create_time": 1767225600}}}}
    eps = conv.parse_chatgpt_json([{**base, "conversation_id": "c1", "conversation_template_id": "g-p-abcdef123456"},
                                   {**base, "conversation_id": "c2", "gizmo_id": "g-abcdef123456"}])
    by = {e["source_id"]: e for e in eps}
    assert by["c1"]["provider_project"] == {"provider": "chatgpt", "id": "g-p-abcdef123456"}
    assert "provider_project" not in by["c2"]


def test_an_unchanged_conversation_gains_its_grouping_in_frontmatter_only(bank):
    base = {"title": "t", "create_time": 1767225600, "conversation_id": "c1", "mapping": {"a": {"message": {
        "author": {"role": "user"}, "content": {"parts": ["hello"]}, "create_time": 1767225600}}}}
    conv._stage_export(conv.parse_chatgpt_json([base]), bank / "episodes")
    path = next((bank / "episodes").glob("*.md"))
    before = markdown_parser.parse(path)
    result = conv._stage_export(conv.parse_chatgpt_json([{**base, "conversation_template_id": "g-p-abcdef123456"}]),
                                bank / "episodes")
    after = markdown_parser.parse(path)
    assert result.skipped == 1 and result.created == 0 and result.updated == 0
    assert after.body == before.body and after.frontmatter["provider_project"]["id"] == "g-p-abcdef123456"
    assert after.frontmatter.get("processed") == before.frontmatter.get("processed")


def test_sleep_is_told_the_grouping_as_context():
    note = entity_extractor.project_note({"provider_project": {"provider": "chatgpt", "id": "g-p-x"}})
    assert note and "ChatGPT project" in note
    assert entity_extractor.project_note({"relay": {"app": "claude", "project": "Alpha"}}).count("Alpha") == 1
    assert entity_extractor.project_note({}) is None


def test_the_signal_reads_the_provider_id(bank):
    assert project_conversations.ep_provider({"provider_project": {"provider": "chatgpt", "id": "g-p-1"}}) == \
        ("chatgpt", "g-p-1")
