"""G98 / Wave-1 1.2 — load_inbox must not serve a question about a subject the
graph no longer has an active belief about, and must not silently swallow an
unparseable item.

Both filters are read-time only: the item file stays on disk (never deleted),
so a later fix to the subject (or a corrected file) makes it visible again on
the next read.
"""

from __future__ import annotations

import logging
from pathlib import Path

from api.services import inbox_service, markdown_parser


def _write_item(memory: Path, item_id: str, *, entity_id: str = "rodrigo",
                 kind: str = "decay") -> Path:
    inbox = memory / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    fm = {
        "kind": kind,
        "required_input": "choice",
        "status": "pending",
        "priority": 0.5,
        "entity_id": entity_id,
        "entity_name": entity_id.title(),
        "title": f"Still interested in {entity_id.title()}?",
        "created_date": "2026-06-01",
    }
    path = inbox / f"{item_id}.md"
    markdown_parser.write(path, fm, "Body.")
    return path


def _write_entity(memory: Path, entity_id: str, *, status: str = "active") -> Path:
    entities = memory / "entities"
    entities.mkdir(parents=True, exist_ok=True)
    path = entities / f"{entity_id}.md"
    markdown_parser.write(
        path,
        {"name": entity_id.title(), "type": "concept", "status": status, "confidence": 0.5},
        "Body.",
    )
    return path


def test_item_with_no_entity_page_is_skipped_but_stays_on_disk(tmp_path):
    memory = tmp_path / "memory"
    path = _write_item(memory, "inbox-001", entity_id="ghost-entity")

    assert inbox_service.load_inbox(memory) == []
    assert path.exists(), "filter at read only — never delete from disk"


def test_item_whose_subject_is_archived_is_skipped(tmp_path):
    memory = tmp_path / "memory"
    _write_item(memory, "inbox-001", entity_id="octo")
    _write_entity(memory, "octo", status="archived")

    assert inbox_service.load_inbox(memory) == []


def test_item_whose_subject_is_dropped_is_skipped(tmp_path):
    memory = tmp_path / "memory"
    _write_item(memory, "inbox-001", entity_id="banished")
    _write_entity(memory, "banished", status="dropped")

    assert inbox_service.load_inbox(memory) == []


def test_item_whose_subject_is_active_is_served(tmp_path):
    memory = tmp_path / "memory"
    _write_item(memory, "inbox-001", entity_id="rodrigo")
    _write_entity(memory, "rodrigo", status="active")

    visible = inbox_service.load_inbox(memory)
    assert [i.id for i in visible] == ["inbox-001"]


def test_item_whose_subject_is_decaying_is_still_served(tmp_path):
    """`decaying` is still a live belief — only archived/dropped are gone."""
    memory = tmp_path / "memory"
    _write_item(memory, "inbox-001", entity_id="fading")
    _write_entity(memory, "fading", status="decaying")

    visible = inbox_service.load_inbox(memory)
    assert [i.id for i in visible] == ["inbox-001"]


def test_item_with_no_entity_id_is_never_gated(tmp_path):
    """A blank entity_id can't resolve to "gone" — it was never tied to a subject."""
    memory = tmp_path / "memory"
    _write_item(memory, "inbox-001", entity_id="")

    visible = inbox_service.load_inbox(memory)
    assert [i.id for i in visible] == ["inbox-001"]


def test_unparseable_item_is_skipped_with_a_warning_naming_the_file(tmp_path, caplog):
    memory = tmp_path / "memory"
    inbox = memory / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    _write_item(memory, "inbox-001", entity_id="rodrigo")
    _write_entity(memory, "rodrigo")

    # Reproduces inbox-3747.md: an unquoted colon inside a scalar value breaks
    # the whole YAML frontmatter parse.
    broken = inbox / "inbox-3747.md"
    broken.write_text(
        "---\n"
        "kind: clarification\n"
        "entity_id: rodrigo\n"
        "uncertainty_type: identity: unclear\n"
        "---\n\nBody.\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        visible = inbox_service.load_inbox(memory)

    assert [i.id for i in visible] == ["inbox-001"]
    assert broken.exists(), "filter at read only — never delete from disk"
    assert any("inbox-3747.md" in rec.message for rec in caplog.records), (
        "a swallowed parse error must name the offending file"
    )
