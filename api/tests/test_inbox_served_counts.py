"""The menu bar's inbox count is what the inbox serves, not what is on disk.

2026-10-06: the menu bar said 49 items while the inbox listed 35 — `/status`
counted every `inbox-*.md`, while `load_inbox` skips items whose subject is
archived, dropped or gone (G98) and items deferred to a later day. Both now ask
one predicate, so the two numbers cannot drift apart again.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from api import config, main
from api.services import hub_builder, inbox_service, markdown_parser


def _write_item(memory: Path, item_id: str, *, entity_id: str, kind: str, **extra) -> None:
    inbox = memory / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    fm = {
        "kind": kind,
        "required_input": "choice",
        "status": "pending",
        "priority": 0.5,
        "entity_id": entity_id,
        "entity_name": entity_id.title(),
        "title": f"About {entity_id.title()}?",
        "created_date": "2026-06-01",
        **extra,
    }
    markdown_parser.write(inbox / f"{item_id}.md", fm, "Body.")


def _write_entity(memory: Path, entity_id: str, *, status: str = "active") -> None:
    entities = memory / "entities"
    entities.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(
        entities / f"{entity_id}.md",
        {"name": entity_id.title(), "type": "concept", "status": status, "confidence": 0.5},
        "Body.",
    )


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    _write_entity(memory, "alpha")
    _write_entity(memory, "beta", status="archived")
    _write_entity(memory, "gamma", status="dropped")
    tomorrow = str(date.today() + timedelta(days=1))
    _write_item(memory, "inbox-001", entity_id="alpha", kind="conflict")           # served
    _write_item(memory, "inbox-002", entity_id="alpha", kind="merge_suggestion")   # served
    _write_item(memory, "inbox-003", entity_id="no-page-yet", kind="clarification")  # served: answering creates it
    _write_item(memory, "inbox-004", entity_id="beta", kind="conflict")            # archived subject
    _write_item(memory, "inbox-005", entity_id="gamma", kind="merge_suggestion")   # dropped subject
    _write_item(memory, "inbox-006", entity_id="ghost", kind="conflict")           # page gone
    _write_item(memory, "inbox-007", entity_id="alpha", kind="decay", remind_after=tomorrow)  # deferred
    (memory / "inbox" / "inbox-008.md").write_text("---\ntitle: a: b: c\n---\nBody.\n")  # unparseable
    return memory


def test_served_counts_equal_what_load_inbox_serves(tmp_path):
    memory = _bank(tmp_path)
    served = inbox_service.load_inbox(memory)

    total, by_kind = inbox_service.served_counts(memory)

    assert total == len(served) == 3
    assert by_kind == dict(Counter(i.kind.value for i in served)) == {
        "conflict": 1, "merge_suggestion": 1, "clarification": 1,
    }
    assert len(list((memory / "inbox").glob("inbox-*.md"))) == 8, "filtered at read, never deleted"


def test_status_and_hub_report_the_served_count(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        inbox = TestClient(main.app).get("/status").json()["inbox"]
    finally:
        config.get_settings.cache_clear()

    assert inbox["total"] == 3
    assert inbox["byKind"] == {"conflict": 1, "merge_suggestion": 1, "clarification": 1}
    assert hub_builder._count_pending_inbox(memory) == 3
