"""The closed set of 10 entity types holds at every writer that takes a type from a model, and a bank whose pages
slipped out of it is repaired by the person's own command (2026-10-17). Synthetic pages only."""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from api.models.schemas import InboxResolveRequest
from api.scripts import repair_entity_types
from api.services import conflict_resolver, entity_extractor, entity_type_repair, entity_types, inbox_service
from api.services import markdown_parser


def _fm(memory: Path, eid: str) -> dict:
    return markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter


# --- the mapping ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw, want", [
    ("person", "person"), ("Company", "company"), (" tool ", "tool"), ("directory", "directory"),
    ("organization", "company"), ("Organisation", "company"), ("non-profit", "company"), ("university", "company"),
    ("product", "tool"), ("software_library", "concept"), ("web-app", "tool"), ("platform", "tool"),
    ("program", "project"), ("Programme", "project"), ("initiative", "project"),
    ("city", "location"), ("folder", "directory"), ("people", "person"),
    ("deadline", "concept"), ("media", "concept"),   # real types, but never Stage 1's to produce
    ("", "concept"), (None, "concept"), ("something-else", "concept"), (42, "concept"),
])
def test_every_type_a_model_writes_becomes_one_stage1_may_produce(raw, want):
    assert entity_types.producible(raw) == want
    assert entity_types.producible(raw) in entity_types.PRODUCIBLE


def test_every_synonym_lands_inside_the_producible_set():
    assert set(entity_types.SYNONYMS.values()) <= entity_types.PRODUCIBLE
    assert not set(entity_types.SYNONYMS) & entity_types.ALL_TYPES


def test_the_writers_backstop_keeps_any_of_the_ten_and_maps_the_rest():
    assert entity_types.in_set("media") == "media" and entity_types.in_set("Deadline") == "deadline"
    assert entity_types.in_set("organization") == "company" and entity_types.in_set(None) == "concept"


def test_known_accepts_exactly_the_ten():
    assert {entity_types.known(t) for t in entity_types.ALL_TYPES} == entity_types.ALL_TYPES
    assert len(entity_types.ALL_TYPES) == 10
    assert entity_types.known("organization") is None and entity_types.known("") is None


# --- the writers ------------------------------------------------------------------------------------------------


def test_stage1_sanitizer_maps_an_out_of_set_type():
    entity = {"name": "Acme Example", "type": "organization"}
    entity_extractor.sanitize_entity_type(entity)
    assert entity["type"] == "company"
    bare = {"name": "Untyped Example"}
    entity_extractor.sanitize_entity_type(bare)
    assert bare["type"] == "concept"


def test_the_create_branch_holds_the_set_even_when_a_payload_slipped_through(tmp_path):
    """A pending line or a payload read before the extraction rail existed still carries the model's word."""
    (tmp_path / "entities").mkdir(parents=True)
    conflict_resolver.apply_changes(
        [{"id": "acme-example", "action": "create", "entity": {"name": "Acme Example", "type": "organization"}},
         {"id": "widget-example", "action": "create", "entity": {"name": "Widget Example", "type": "product"}},
         {"id": "study-example", "action": "create", "entity": {"name": "Study Example", "type": "program"}}],
        tmp_path,
    )
    assert [_fm(tmp_path, e)["type"] for e in ("acme-example", "widget-example", "study-example")] == [
        "company", "tool", "project"]


def test_an_inbox_answer_that_creates_a_page_holds_the_set(tmp_path):
    (tmp_path / "entities").mkdir(parents=True)
    (tmp_path / "inbox").mkdir(parents=True)
    item = tmp_path / "inbox" / "inbox-001.md"
    markdown_parser.write(item, {
        "kind": "clarification", "required_input": "text", "status": "pending", "priority": 0.5,
        "entity_id": "acme-example", "entity_name": "Acme Example", "entity_mention": "Acme Example",
        "uncertainty_type": "who_is_this", "title": "What is Acme Example?", "created_date": "2026-01-01",
        "suggested_classification": "organization — a synthetic fixture", "suggested_confidence": 0.5,
    }, "Unresolved mention.")

    class _Settings:
        memory_path = tmp_path

    asyncio.run(inbox_service._resolve_clarification(
        item, markdown_parser.parse(item), InboxResolveRequest(action="answer", answer="A synthetic lab."), _Settings()))
    assert _fm(tmp_path, "acme-example")["type"] == "company"


# --- the repair -------------------------------------------------------------------------------------------------


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], capture_output=True, text=True, check=True).stdout


def _page(memory: Path, eid: str, kind: str, **extra) -> None:
    fm = {"name": eid.replace("-", " ").title(), "type": kind, "status": "active", "confidence": 0.6,
          "created": "2026-01-01", "last_referenced": "2026-09-01", "decay_class": "active", "decay_rate": 0.05,
          "source_episodes": [], "tags": [], "related": [], "version": 1, **extra}
    markdown_parser.write(memory / "entities" / f"{eid}.md", fm, f"## Summary\n{eid} is a synthetic fixture.\n")


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "bank"
    (memory / "entities").mkdir(parents=True)
    _page(memory, "acme-example", "organization")
    _page(memory, "widget-example", "product")
    _page(memory, "study-example", "program")
    _page(memory, "alice-example", "person")
    _page(memory, "odd-example", "flavour")
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@example.com")
    _git(memory, "config", "user.name", "Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "fixtures")
    return memory


def _idle():
    return False


def test_the_dry_run_counts_and_writes_nothing(bank):
    before = {p.name: p.read_bytes() for p in (bank / "entities").iterdir()}
    result = entity_type_repair.survey(bank)
    counts = result.counts()
    assert counts["pages"] == 5 and counts["out_of_set"] == 4 and counts["fallback"] == 1
    assert counts["mapped"] == {"flavour -> concept": 1, "organization -> company": 1, "product -> tool": 1,
                                "program -> project": 1}
    assert "acme-example" not in json.dumps(counts)                       # counts and type words only
    assert {p.name: p.read_bytes() for p in (bank / "entities").iterdir()} == before
    assert [row["id"] for row in result.listing()] == ["acme-example", "odd-example", "study-example",
                                                         "widget-example"]


def test_apply_retypes_only_the_type_in_one_cicada_commit_and_a_second_run_is_a_no_op(bank):
    before = _fm(bank, "acme-example")
    result = entity_type_repair.apply(bank, sleep_running=_idle, overrides={"widget-example": "project"})
    assert result.repaired == 4 and result.committed and result.overridden == 1
    assert [_fm(bank, e)["type"] for e in ("acme-example", "widget-example", "study-example", "odd-example",
                                            "alice-example")] == ["company", "project", "project", "concept", "person"]
    after = _fm(bank, "acme-example")
    assert {k: v for k, v in after.items() if k != "type"} == {k: v for k, v in before.items() if k != "type"}
    log = _git(bank, "log", "-1", "--format=%s%n%b")
    assert log.startswith("Page types brought into the closed set: 4 page(s)")
    assert "maintenance/entity-types" in log and "Cicada-Author: cicada" in log
    assert not _git(bank, "status", "--porcelain")
    head = _git(bank, "rev-parse", "HEAD")
    again = entity_type_repair.apply(bank, sleep_running=_idle)
    assert again.repaired == 0 and not again.committed and _git(bank, "rev-parse", "HEAD") == head


def test_a_page_dirty_in_git_is_skipped(bank):
    path = bank / "entities" / "acme-example.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nAn uncommitted edit.\n", encoding="utf-8")
    result = entity_type_repair.apply(bank, sleep_running=_idle)
    assert result.dirty == 1 and result.repaired == 3
    assert _fm(bank, "acme-example")["type"] == "organization"


def test_apply_refuses_while_sleep_runs(bank):
    with pytest.raises(entity_type_repair.SleepRunning):
        entity_type_repair.apply(bank, sleep_running=lambda: True)
    assert _fm(bank, "acme-example")["type"] == "organization"


def test_an_override_must_name_a_page_needing_repair_and_a_producible_type(bank):
    with pytest.raises(entity_type_repair.BadOverride):
        entity_type_repair.survey(bank, overrides={"acme-example": "media"})
    with pytest.raises(entity_type_repair.BadOverride):
        entity_type_repair.survey(bank, overrides={"alice-example": "company"})


def test_the_command(bank, capsys, monkeypatch):
    monkeypatch.setattr(repair_entity_types, "backend_running", _idle)
    assert repair_entity_types.main(["--bank", str(bank)]) == 0
    assert json.loads(capsys.readouterr().out)["out_of_set"] == 4
    assert repair_entity_types.main(["--bank", str(bank), "--list"]) == 0
    assert len(json.loads(capsys.readouterr().out)["pages_to_retype"]) == 4
    assert repair_entity_types.main(["--bank", str(bank), "--apply", "--as", "nope"]) == 2
    capsys.readouterr()
    assert repair_entity_types.main(["--bank", str(bank.parent / "missing")]) == 2
    capsys.readouterr()
    assert repair_entity_types.main(["--bank", str(bank), "--apply", "--as", "odd-example=tool"]) == 0
    assert json.loads(capsys.readouterr().out)["repaired"] == 4
    assert _fm(bank, "odd-example")["type"] == "tool"
