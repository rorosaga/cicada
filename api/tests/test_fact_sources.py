"""G61 — `sources:` frontmatter (where to look a fact up), minimal slice."""

from __future__ import annotations

from pathlib import Path

from api.services import fact_sources, markdown_parser


def _entity(tmp_path: Path, fm_extra: dict | None = None) -> Path:
    ents = tmp_path / "entities"
    ents.mkdir(parents=True, exist_ok=True)
    fm = {"name": "Rodrigo", "type": "person", "status": "active", "confidence": 0.8,
          "created": "2026-01-01", "last_referenced": "2026-08-30", "decay_rate": 0.05,
          "source_episodes": [], "tags": [], "related": [], "version": 1}
    fm.update(fm_extra or {})
    markdown_parser.write(ents / "rodrigo.md", fm, "Body.")
    return tmp_path


def test_infer_kind():
    assert fact_sources.infer_kind("https://www.linkedin.com/in/rodrigo") == "url"
    assert fact_sources.infer_kind("http://example.com") == "url"
    assert fact_sources.infer_kind("/Users/rodrigo/cv.pdf") == "path"
    assert fact_sources.infer_kind("~/Documents/cv.pdf") == "path"
    assert fact_sources.infer_kind("Ask me — I always announce a job change") == "note"
    assert fact_sources.infer_kind("") == "note"


def test_add_list_and_delete_round_trip(tmp_path):
    memory = _entity(tmp_path)

    added = fact_sources.add_source(
        memory, "rodrigo", "https://www.linkedin.com/in/rodrigo",
        predicate="works-at", added_by="user", added_at="2026-08-30",
    )
    assert added == {
        "ref": "https://www.linkedin.com/in/rodrigo",
        "kind": "url",
        "predicate": "works-at",
        "added_by": "user",
        "added_at": "2026-08-30",
    }

    fact_sources.add_source(
        memory, "rodrigo", "Ask me — I announce job changes",
        added_by="gpt-5.4-mini", added_at="2026-08-30",
    )

    listed = fact_sources.list_sources(memory, "rodrigo")
    assert [s["kind"] for s in listed] == ["url", "note"]
    assert listed[1]["added_by"] == "gpt-5.4-mini"
    assert "predicate" not in listed[1]

    assert fact_sources.delete_source(memory, "rodrigo", 0) is True
    assert [s["kind"] for s in fact_sources.list_sources(memory, "rodrigo")] == ["note"]
    assert fact_sources.delete_source(memory, "rodrigo", 7) is False


def test_add_is_idempotent_on_an_identical_ref(tmp_path):
    memory = _entity(tmp_path)
    fact_sources.add_source(memory, "rodrigo", "https://example.com", added_at="2026-08-30")
    fact_sources.add_source(memory, "rodrigo", "https://example.com", added_at="2026-08-31")
    assert len(fact_sources.list_sources(memory, "rodrigo")) == 1


def test_empty_key_is_never_written(tmp_path):
    memory = _entity(tmp_path)
    fact_sources.add_source(memory, "rodrigo", "  ", added_at="2026-08-30")
    fm = markdown_parser.parse(memory / "entities" / "rodrigo.md").frontmatter
    assert "sources" not in fm


def test_hint_for_prefers_a_predicate_match_then_any_url(tmp_path):
    memory = _entity(tmp_path, {"sources": [
        {"ref": "https://generic.example", "kind": "url"},
        {"ref": "https://linkedin.example/rodrigo", "kind": "url", "predicate": "works-at"},
        {"ref": "just a note", "kind": "note"},
    ]})

    hint = fact_sources.hint_for(memory, "rodrigo", "works-at")
    assert hint == "You said https://linkedin.example/rodrigo is where to check this"

    # No predicate match -> the first url-kind source
    assert fact_sources.hint_for(memory, "rodrigo", "uses") == (
        "You said https://generic.example is where to check this"
    )


def test_hint_for_returns_none_without_sources(tmp_path):
    memory = _entity(tmp_path)
    assert fact_sources.hint_for(memory, "rodrigo", "works-at") is None
    assert fact_sources.hint_for(memory, "nobody", "works-at") is None


def test_hint_for_ignores_note_only_sources_when_no_predicate_matches(tmp_path):
    memory = _entity(tmp_path, {"sources": [{"ref": "ask me", "kind": "note"}]})
    assert fact_sources.hint_for(memory, "rodrigo", "works-at") is None


import asyncio
import subprocess

import pytest
from fastapi import HTTPException

from api.models.schemas import EntitySourceCreate
from api.routers import entities as entities_router
from api.services import inbox_generator


def run(coro):
    return asyncio.run(coro)


class _FakeSettings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path


def _git_memory(tmp_path: Path) -> Path:
    repo = tmp_path / "memory"
    _entity(repo)
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@c.local"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=str(repo), check=True)
    return repo


def test_sources_endpoints_round_trip_and_commit(tmp_path):
    repo = _git_memory(tmp_path)
    settings = _FakeSettings(repo)

    empty = run(entities_router.get_entity_sources("rodrigo", settings=settings))
    assert empty.entity_id == "rodrigo" and empty.sources == []

    created = run(entities_router.add_entity_source(
        "rodrigo",
        EntitySourceCreate(ref="https://linkedin.example/rodrigo", predicate="works-at"),
        settings=settings,
    ))
    assert [s.kind for s in created.sources] == ["url"]
    assert created.sources[0].predicate == "works-at"
    assert created.sources[0].added_by == "user"

    log = subprocess.run(
        ["git", "log", "--format=%s%n%b"], cwd=str(repo),
        check=True, capture_output=True, text=True,
    ).stdout
    assert "user/companion_app" in log
    assert "Cicada-Author: user" in log

    after = run(entities_router.delete_entity_source("rodrigo", 0, settings=settings))
    assert after.sources == []


def test_sources_endpoints_404_on_a_missing_entity(tmp_path):
    repo = _git_memory(tmp_path)
    with pytest.raises(HTTPException) as exc:
        run(entities_router.get_entity_sources("nobody", settings=_FakeSettings(repo)))
    assert exc.value.status_code == 404


def test_delete_out_of_range_is_404(tmp_path):
    repo = _git_memory(tmp_path)
    with pytest.raises(HTTPException) as exc:
        run(entities_router.delete_entity_source("rodrigo", 3, settings=_FakeSettings(repo)))
    assert exc.value.status_code == 404


def test_generated_conflict_carries_the_source_hint(tmp_path):
    memory = tmp_path / "memory"
    _entity(memory, {"sources": [
        {"ref": "https://linkedin.example/rodrigo", "kind": "url", "predicate": "works-at"},
    ]})
    (memory / "inbox").mkdir(parents=True)

    inbox_generator.write_claim_nudges([{
        "id": "rodrigo",
        "action": "conflict_nudge",
        "entity": {"name": "Rodrigo"},
        "predicate": "works-at",
        "question": "Where does Rodrigo work now?",
        "allow_other": True,
        "allow_defer": True,
        "conflict_context": "conflict",
        "options": [{"key": "a", "label": "mongodb", "claim_id": "clm_a"}],
        "claim_id": "clm_a",
    }], memory)

    fm = markdown_parser.parse(memory / "inbox" / "inbox-001.md").frontmatter
    assert fm["hint"] == "You said https://linkedin.example/rodrigo is where to check this"


def test_entity_path_conflict_carries_the_source_hint(tmp_path):
    """The legacy entity-path conflict written by ``generate()`` also gets a
    hint (controller ruling): its predicate is always the literal
    ``"description"``, so any url-kind source matches (§ruling 2)."""
    memory = tmp_path / "memory"
    _entity(memory, {"sources": [
        {"ref": "https://example.com/rodrigo-cv", "kind": "url"},
    ]})
    (memory / "inbox").mkdir(parents=True)

    run(inbox_generator.generate(
        [{
            "id": "rodrigo",
            "action": "conflict_nudge",
            "entity": {"name": "Rodrigo"},
            "question": "Where does Rodrigo work now?",
            "options": [{"key": "a", "label": "mongodb"}],
        }],
        [],
        memory,
    ))

    fm = markdown_parser.parse(memory / "inbox" / "inbox-001.md").frontmatter
    assert fm["hint"] == "You said https://example.com/rodrigo-cv is where to check this"


def test_merge_on_collision_refreshes_the_hint_on_the_open_item(tmp_path):
    """A source added AFTER the first conflict was written must still surface
    on the already-open item once a second nudge merges into it (controller
    ruling 2)."""
    memory = tmp_path / "memory"
    _entity(memory)
    (memory / "inbox").mkdir(parents=True)

    first_nudge = {
        "id": "rodrigo",
        "action": "conflict_nudge",
        "entity": {"name": "Rodrigo"},
        "predicate": "works-at",
        "question": "Where does Rodrigo work now?",
        "allow_other": True,
        "allow_defer": True,
        "conflict_context": "conflict",
        "options": [{"key": "a", "label": "mongodb", "claim_id": "clm_a"}],
        "claim_id": "clm_a",
    }
    inbox_generator.write_claim_nudges([first_nudge], memory)

    fm_before = markdown_parser.parse(memory / "inbox" / "inbox-001.md").frontmatter
    assert fm_before.get("hint") is None

    fact_sources.add_source(
        memory, "rodrigo", "https://linkedin.example/rodrigo",
        predicate="works-at", added_at="2026-08-30",
    )

    second_nudge = dict(first_nudge, options=[{"key": "b", "label": "stripe", "claim_id": "clm_b"}],
                         claim_id="clm_b")
    result = inbox_generator.write_claim_nudges([second_nudge], memory)
    assert result["merged"] == 1

    fm_after = markdown_parser.parse(memory / "inbox" / "inbox-001.md").frontmatter
    assert fm_after["hint"] == "You said https://linkedin.example/rodrigo is where to check this"
