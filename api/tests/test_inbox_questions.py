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
    # Legacy conflicts (no allow_* keys) must still offer the free-text and
    # defer escapes — the resolve path accepts them for every conflict.
    assert item.allow_other is True and item.allow_defer is True


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


# ---------- G115 Phase 1: decay is a question object, synthesised at read ----------


def test_decay_question_shape_and_age_first_descriptions():
    q = inbox_questions.decay_question("Alpha Project", "2026-02-18", "2026-08-30")
    assert q["question"] == "Still tracking Alpha Project?"
    assert [o["key"] for o in q["options"]] == ["archive", "keep"]
    assert all(o["description"].startswith("Last mentioned 6 months ago") for o in q["options"])
    assert q["allow_defer"] is True and q["allow_other"] is False
    assert inbox_questions.validate_question(q["question"], q["options"], recommended_key="archive") == []


def test_validate_question_catches_the_copy_rules():
    v = inbox_questions.validate_question
    assert "question must end with '?'" in v("Still tracking X", [{"key": "a", "label": "x"}])
    assert any("recommended" in m for m in v("Q?", [{"key": "neither", "label": "Neither"}], recommended_key="neither"))
    assert any("marker" in m for m in v("Q?", [{"key": "a", "label": "x (Recommended)"}]))
    assert any("duplicate" in m for m in v("Q?", [{"key": "a", "label": "x"}, {"key": "a", "label": "y"}]))
    assert any("Last mentioned" in m for m in v("Q?", [{"key": "a", "label": "x", "observed_at": "2026-01-01",
                                                          "description": "stale"}]))
    assert v("Q?", [{"key": "a", "label": "x", "observed_at": "2026-01-01",
                     "description": "Last mentioned 2026-01-01 · 7 months ago"}]) == []


def test_decay_item_is_served_as_a_question_with_archive_recommended(tmp_path):
    from api.services import bank_index
    bank_index.invalidate()
    (tmp_path / "entities").mkdir()
    markdown_parser.write(tmp_path / "entities" / "alpha-project.md",
                          {"name": "Alpha Project", "type": "project", "status": "active",
                           "confidence": 0.3, "last_referenced": "2026-02-18", "source_episodes": []}, "# A\n")
    _write_item(tmp_path, "inbox-010", {"kind": "decay", "required_input": "choice", "status": "pending",
                                        "priority": 0.3, "entity_id": "alpha-project",
                                        "entity_name": "Alpha Project", "title": "No recent mentions of Alpha Project",
                                        "created_date": "2026-08-01"})
    [item] = inbox_service.load_inbox(tmp_path)
    assert item.question == "Still tracking Alpha Project?"
    assert [o.key for o in item.options] == ["archive", "keep"]
    assert item.recommended_key == "archive" and item.options[0].recommended is True
    assert item.options[0].verdict == "agreed" and item.options[1].verdict == "overruled"
    assert item.allow_defer is True and item.extractor_confidence == 0.3
    # synthesised at read, never written back (R5)
    assert markdown_parser.parse(tmp_path / "inbox" / "inbox-010.md").frontmatter.get("options") in (None, [])


def _conflict_fm(**over):
    fm = {"kind": "conflict", "required_input": "choice", "status": "pending", "entity_id": "bob-example",
          "entity_name": "Bob Example", "title": "q", "question": "Where does Bob Example work now?",
          "predicate": "works-at", "created_date": "2026-08-01", "claim_id": "clm_new",
          "options": [{"key": "a", "label": "alpha-corp", "claim_id": "clm_old"},
                      {"key": "b", "label": "beta-corp", "claim_id": "clm_new"},
                      {"key": "both", "label": "Both are true (different contexts)"}]}
    fm.update(over)
    return fm


def test_recommended_is_sleeps_proposal_and_is_served_first():
    fm = _conflict_fm()
    opts = inbox_questions.normalize_options(fm["options"])
    assert inbox_service.recommended_key("conflict", fm, opts) == "b"
    # wire == ledger (G115 §4): every kind × key grades the same at read and at resolve
    for kind, key in (("conflict", "a"), ("conflict", "b"), ("conflict", "both"), ("decay", "archive"), ("decay", "keep")):
        opts_k = opts if kind == "conflict" else inbox_questions.normalize_options(
            inbox_questions.decay_question("X", None, "2026-08-30")["options"])
        fm_k = fm if kind == "conflict" else {"kind": "decay"}
        expected = inbox_service._verdict(
            kind,
            inbox_service._action_label(kind, inbox_service._normalize_decay_request(
                kind, InboxResolveRequest(action="resolve", option_key=key)), opts_k),
            key, fm_k.get("claim_id"), opts_k)
        assert inbox_service._option_verdict(kind, key, fm_k, opts_k) == expected, (kind, key)


def test_recommended_never_on_neither_entity_path_merge_or_clarification():
    stale = _conflict_fm(options=[{"key": "neither", "label": "Neither anymore"}] + _conflict_fm()["options"])
    assert inbox_service.recommended_key("conflict", stale, inbox_questions.normalize_options(stale["options"])) == "b"
    entity_path = _conflict_fm(claim_id=None, options=[{"key": "a", "label": "x"}, {"key": "b", "label": "y"}])
    assert inbox_service.recommended_key("conflict", entity_path, inbox_questions.normalize_options(entity_path["options"])) is None
    assert inbox_service.recommended_key("merge_suggestion", {"kind": "merge_suggestion"}, [{"key": "0", "label": "m"}]) is None
    assert inbox_service.recommended_key("clarification", {"kind": "clarification"}, [{"key": "0", "label": "c"}]) is None


def test_options_are_served_recommended_first(tmp_path):
    from api.services import bank_index
    bank_index.invalidate()
    (tmp_path / "entities").mkdir()
    markdown_parser.write(tmp_path / "entities" / "bob-example.md",
                          {"name": "Bob Example", "type": "person", "status": "active", "source_episodes": []}, "# B\n")
    _write_item(tmp_path, "inbox-011", _conflict_fm())
    [item] = inbox_service.load_inbox(tmp_path)
    assert [o.key for o in item.options] == ["b", "a", "both"]
    assert item.options[0].recommended is True and item.recommended_key == "b"
