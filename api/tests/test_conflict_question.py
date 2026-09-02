"""G60 — the entity path (conflict_resolver) also emits a question object.

The LLM is asked for `question` + per-option `description`, so a parse failure or
a key-less response falls back to the deterministic template, so this path
never regresses to a bare option list.
"""

from __future__ import annotations

from api.services import conflict_resolver


def test_build_entity_question_uses_the_llm_payload_when_complete():
    raw = {
        "has_unresolvable_contradiction": True,
        "contradiction": "Two stacks are described.",
        "question": "Which database is Cicada on now?",
        "options": [
            {"label": "Postgres", "description": "Described in the older page body"},
            {"label": "SQLite", "description": "Described in the newer extraction"},
            {"label": "Both are true (different contexts)"},
        ],
    }
    out = conflict_resolver.build_entity_question("Cicada", raw, today="2026-08-30")
    assert out["question"] == "Which database is Cicada on now?"
    assert [o["key"] for o in out["options"]] == ["a", "b", "both"]
    assert out["options"][0]["label"] == "Postgres"
    assert out["options"][0]["description"] == "Described in the older page body"
    assert out["options"][2]["key"] == "both"
    assert out["options"][0]["claim_id"] is None


def test_build_entity_question_falls_back_to_the_template():
    raw = {
        "has_unresolvable_contradiction": True,
        "contradiction": "Two stacks.",
        "options": ["Postgres", "SQLite"],
    }
    out = conflict_resolver.build_entity_question("Cicada", raw, today="2026-08-30")
    assert out["question"] == "What is currently true about Cicada?"
    assert [o["label"] for o in out["options"]] == [
        "Postgres", "SQLite", "Both are true (different contexts)",
    ]
    # The template always adds a description so the card is never blank.
    assert out["options"][0]["description"]


def test_build_entity_question_survives_a_null_payload():
    out = conflict_resolver.build_entity_question("Cicada", None, today="2026-08-30")
    assert out["question"] == "What is currently true about Cicada?"
    assert [o["key"] for o in out["options"]] == ["both"]


def test_contradiction_prompt_asks_for_question_and_descriptions():
    assert '"question"' in conflict_resolver._CONTRADICTION_PROMPT
    assert '"description"' in conflict_resolver._CONTRADICTION_PROMPT
