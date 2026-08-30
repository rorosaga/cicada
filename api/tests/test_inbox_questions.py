"""G60 — question-object helpers: age phrasing + legacy flat-options upgrade."""

from __future__ import annotations

from api.services import inbox_questions


def test_humanize_age_phrases():
    today = "2026-08-30"
    assert inbox_questions.humanize_age("2026-08-30", today) == "today"
    assert inbox_questions.humanize_age("2026-08-29", today) == "yesterday"
    assert inbox_questions.humanize_age("2026-08-27", today) == "3 days ago"
    assert inbox_questions.humanize_age("2026-08-09", today) == "3 weeks ago"
    assert inbox_questions.humanize_age("2026-02-18", today) == "6 months ago"
    assert inbox_questions.humanize_age("2025-07-01", today) == "a year ago"
    assert inbox_questions.humanize_age("2023-07-01", today) == "3 years ago"
    assert inbox_questions.humanize_age(None, today) == "unknown"


def test_age_days_handles_missing_and_iso_timestamps():
    assert inbox_questions.age_days("2026-08-27", "2026-08-30") == 3
    assert inbox_questions.age_days("2026-08-27T09:00:00Z", "2026-08-30") == 3
    assert inbox_questions.age_days(None, "2026-08-30") is None
    assert inbox_questions.age_days("not-a-date", "2026-08-30") is None


def test_normalize_options_upgrades_legacy_flat_list():
    upgraded = inbox_questions.normalize_options(["MongoDB", "Supahost"])
    assert upgraded == [
        {"key": "0", "label": "MongoDB"},
        {"key": "1", "label": "Supahost"},
    ]


def test_normalize_options_passes_object_form_through_and_fills_keys():
    raw = [{"label": "MongoDB", "claim_id": "clm_1"}, {"key": "b", "label": "Supahost"}]
    out = inbox_questions.normalize_options(raw)
    assert out[0]["key"] == "0"
    assert out[0]["claim_id"] == "clm_1"
    assert out[1]["key"] == "b"


def test_normalize_options_empty_inputs():
    assert inbox_questions.normalize_options(None) == []
    assert inbox_questions.normalize_options([]) == []


from pathlib import Path

from api.models.schemas import InboxResolveRequest
from api.services import inbox_service, markdown_parser


def _write_item(memory: Path, item_id: str, fm: dict, body: str = "context") -> Path:
    inbox = memory / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{item_id}.md"
    markdown_parser.write(path, fm, body)
    return path


def test_item_from_file_upgrades_legacy_flat_options(tmp_path):
    path = _write_item(
        tmp_path,
        "inbox-001",
        {
            "kind": "conflict",
            "required_input": "choice",
            "status": "pending",
            "entity_id": "rodrigo",
            "entity_name": "Rodrigo",
            "title": "Conflicting beliefs about Rodrigo",
            "created_date": "2026-06-18",
            "options": ["mongodb", "supahost", "Both are true (different contexts)"],
        },
    )
    item = inbox_service._item_from_file(path)
    assert [o.key for o in item.options] == ["0", "1", "2"]
    assert item.options[0].label == "mongodb"
    assert item.question is None
    assert item.allow_other is False


def test_item_from_file_reads_question_object_and_derives_age(tmp_path):
    path = _write_item(
        tmp_path,
        "inbox-002",
        {
            "kind": "conflict",
            "required_input": "choice",
            "status": "pending",
            "entity_id": "rodrigo",
            "entity_name": "Rodrigo",
            "title": "Where does Rodrigo work now?",
            "created_date": "2026-06-18",
            "predicate": "works-at",
            "question": "Where does Rodrigo work now?",
            "allow_other": True,
            "allow_defer": True,
            "hint": "You said https://example.com/me is where to check this",
            "options": [
                {
                    "key": "a",
                    "label": "MongoDB",
                    "description": "Last mentioned 2026-02-18 · 6 months ago",
                    "claim_id": "clm_a",
                    "observed_at": "2026-02-18",
                    "last_referenced": "2026-02-18",
                }
            ],
        },
    )
    item = inbox_service._item_from_file(path, today="2026-08-30")
    assert item.question == "Where does Rodrigo work now?"
    assert item.predicate == "works-at"
    assert item.allow_other is True and item.allow_defer is True
    assert item.hint.startswith("You said")
    assert item.options[0].claim_id == "clm_a"
    assert item.options[0].age_days == 193


def test_resolve_request_accepts_option_key_and_remind_days():
    req = InboxResolveRequest(action="resolve", optionKey="b", remindDays=14)
    assert req.option_key == "b"
    assert req.remind_days == 14
    assert InboxResolveRequest(action="skip").option_key is None
