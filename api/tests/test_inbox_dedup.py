"""G60 — dedup key, find_open, merge-on-collision, and question generation."""

from __future__ import annotations

from pathlib import Path

from api.services import inbox_generator, markdown_parser, predicates
from api.services.claim_reconciler import _conflict_nudge
from api.services.claims import Claim


def test_predicate_question_uses_the_table_then_falls_back():
    assert predicates.predicate_question("works-at", "Rodrigo") == "Where does Rodrigo work now?"
    assert predicates.predicate_question("located-in", "Cicada") == "Where is Cicada located now?"
    assert predicates.predicate_question("uses", "Cicada") == "What does Cicada use now?"
    assert (
        predicates.predicate_question("wears-hat-of", "Rodrigo")
        == "Which is true about Rodrigo (wears-hat-of)?"
    )


def test_predicate_phrase_uses_the_table_then_falls_back():
    assert (
        predicates.predicate_phrase("works-at", "Rodrigo Sagastegui", "MongoDB")
        == "Rodrigo Sagastegui works at MongoDB"
    )
    assert (
        predicates.predicate_phrase("wears-hat-of", "Rodrigo", "the crown")
        == "Rodrigo — wears hat of: the crown"
    )


def _claim(cid: str, obj: str, valid_from: str, episode: str = "") -> Claim:
    return Claim(
        id=cid,
        text=f"Rodrigo works at {obj}",
        subject="rodrigo-sagastegui",
        predicate="works-at",
        object=obj,
        valid_from=valid_from,
        recorded_at=valid_from,
        source_episodes=[episode] if episode else [],
    )


def test_conflict_nudge_emits_a_question_object_with_age_descriptions():
    old = _claim("clm_a", "mongodb", "2026-02-18", "ep_2026-02-18_004")
    new = _claim("clm_b", "supahost", "2026-02-18")

    nudge = _conflict_nudge(old, new, today="2026-08-30")

    assert nudge["action"] == "conflict_nudge"
    assert nudge["predicate"] == "works-at"
    assert nudge["question"] == "Where does Rodrigo Sagastegui work now?"
    assert nudge["allow_other"] is True
    assert nudge["allow_defer"] is True

    opts = nudge["options"]
    assert [o["key"] for o in opts] == ["a", "b", "both"]
    assert opts[0]["label"] == "mongodb"
    assert opts[0]["claim_id"] == "clm_a"
    assert opts[0]["observed_at"] == "2026-02-18"
    assert opts[0]["last_referenced"] == "2026-02-18"
    # Description leads with the age phrase so staleness is visible first.
    assert "6 months ago" in opts[0]["description"]
    assert "ep_2026-02-18_004" in opts[0]["description"]
    assert opts[2]["claim_id"] is None


def _write_conflict(memory: Path, item_id: str, entity_id: str, predicate: str,
                    options: list[dict], status: str = "pending",
                    created: str = "2026-06-18") -> Path:
    inbox = memory / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{item_id}.md"
    markdown_parser.write(
        path,
        {
            "kind": "conflict",
            "required_input": "choice",
            "status": status,
            "priority": 0.8,
            "entity_id": entity_id,
            "entity_name": entity_id.replace("-", " ").title(),
            "title": "Conflicting beliefs",
            "created_date": created,
            "predicate": predicate,
            "question": "Where does Rodrigo work now?",
            "allow_other": True,
            "allow_defer": True,
            "options": options,
        },
        "context",
    )
    return path


def test_dedup_key_per_kind():
    assert inbox_generator.dedup_key(
        "conflict", {"entity_id": "rodrigo", "predicate": "works-at"}
    ) == ("rodrigo", "works-at")
    # entity-path conflicts have no predicate -> "description"
    assert inbox_generator.dedup_key("conflict", {"entity_id": "rodrigo"}) == (
        "rodrigo",
        "description",
    )
    assert inbox_generator.dedup_key(
        "clarification", {"entity_id": "franco", "uncertainty_type": "who is this"}
    ) == ("franco", "who is this")
    # merge_suggestion: the sorted pair, so direction never matters
    assert inbox_generator.dedup_key(
        "merge_suggestion", {"entity_id": "zeta", "merge_target_hint": "alpha"}
    ) == ("alpha", "zeta")


def test_find_open_matches_only_pending_same_key(tmp_path):
    memory = tmp_path / "memory"
    _write_conflict(memory, "inbox-001", "rodrigo", "works-at", [{"key": "a", "label": "mongodb"}])
    _write_conflict(memory, "inbox-002", "rodrigo", "uses", [{"key": "a", "label": "vim"}])
    _write_conflict(
        memory, "inbox-003", "rodrigo", "lives-in", [{"key": "a", "label": "madrid"}],
        status="resolved",
    )

    assert inbox_generator.find_open(memory, "conflict", "rodrigo", "works-at").stem == "inbox-001"
    assert inbox_generator.find_open(memory, "conflict", "rodrigo", "uses").stem == "inbox-002"
    # resolved items are invisible to dedup
    assert inbox_generator.find_open(memory, "conflict", "rodrigo", "lives-in") is None
    assert inbox_generator.find_open(memory, "conflict", "someone-else", "works-at") is None


def test_merge_options_into_appends_new_value_and_bumps_existing(tmp_path):
    memory = tmp_path / "memory"
    path = _write_conflict(
        memory, "inbox-001", "rodrigo", "works-at",
        [
            {"key": "a", "label": "mongodb", "claim_id": "clm_a",
             "observed_at": "2026-02-18", "last_referenced": "2026-02-18"},
            {"key": "both", "label": "Both are true (different contexts)"},
        ],
    )

    changed = inbox_generator.merge_options_into(
        path,
        [
            # already present -> bumps last_referenced only
            {"key": "a", "label": "mongodb", "claim_id": "clm_a",
             "observed_at": "2026-08-01", "last_referenced": "2026-08-01"},
            # new value -> appended with a fresh key, before the synthetic rows
            {"key": "b", "label": "supahost", "claim_id": "clm_b",
             "observed_at": "2026-08-01", "last_referenced": "2026-08-01",
             "description": "Last mentioned 2026-08-01 · 4 weeks ago"},
        ],
        today="2026-08-30",
    )

    assert changed is True
    fm = markdown_parser.parse(path).frontmatter
    labels = [o["label"] for o in fm["options"]]
    assert labels == ["mongodb", "supahost", "Both are true (different contexts)"]
    assert fm["options"][0]["last_referenced"] == "2026-08-01"
    assert fm["options"][1]["claim_id"] == "clm_b"
    # keys stay unique
    assert len({o["key"] for o in fm["options"]}) == 3
    # created_date is preserved; updated_date is new
    assert fm["created_date"] == "2026-06-18"
    assert fm["updated_date"] == "2026-08-30"


def test_write_claim_nudges_merges_instead_of_duplicating(tmp_path):
    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    def nudge(obj: str, claim_id: str, observed: str) -> dict:
        return {
            "id": "rodrigo",
            "action": "conflict_nudge",
            "entity": {"name": "Rodrigo"},
            "predicate": "works-at",
            "question": "Where does Rodrigo work now?",
            "allow_other": True,
            "allow_defer": True,
            "conflict_context": "conflict",
            "options": [
                {"key": "a", "label": "mongodb", "claim_id": "clm_a",
                 "observed_at": "2026-02-18", "last_referenced": "2026-02-18"},
                {"key": "b", "label": obj, "claim_id": claim_id,
                 "observed_at": observed, "last_referenced": observed},
                {"key": "both", "label": "Both are true (different contexts)"},
            ],
            "claim_id": claim_id,
            "existing_claim_id": "clm_a",
        }

    inbox_generator.write_claim_nudges([nudge("supahost", "clm_b", "2026-02-18")], memory)
    inbox_generator.write_claim_nudges([nudge("acme", "clm_c", "2026-08-20")], memory)

    files = sorted((memory / "inbox").glob("inbox-*.md"))
    assert len(files) == 1, "a second conflict on the same key must MERGE, not duplicate"
    fm = markdown_parser.parse(files[0]).frontmatter
    assert [o["label"] for o in fm["options"]] == [
        "mongodb", "supahost", "acme", "Both are true (different contexts)",
    ]


def test_write_claim_nudges_returns_written_and_merged_counts(tmp_path):
    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    def nudge(obj: str, claim_id: str, observed: str) -> dict:
        return {
            "id": "rodrigo",
            "action": "conflict_nudge",
            "entity": {"name": "Rodrigo"},
            "predicate": "works-at",
            "question": "Where does Rodrigo work now?",
            "allow_other": True,
            "allow_defer": True,
            "conflict_context": "conflict",
            "options": [
                {"key": "a", "label": "mongodb", "claim_id": "clm_a",
                 "observed_at": "2026-02-18", "last_referenced": "2026-02-18"},
                {"key": "b", "label": obj, "claim_id": claim_id,
                 "observed_at": observed, "last_referenced": observed},
                {"key": "both", "label": "Both are true (different contexts)"},
            ],
            "claim_id": claim_id,
            "existing_claim_id": "clm_a",
        }

    first = inbox_generator.write_claim_nudges([nudge("supahost", "clm_b", "2026-02-18")], memory)
    assert first["written"] == 1
    assert first["merged"] == 0

    second = inbox_generator.write_claim_nudges([nudge("acme", "clm_c", "2026-08-20")], memory)
    assert second["written"] == 0
    assert second["merged"] == 1


def test_clarification_collision_bumps_updated_date_instead_of_duplicating(tmp_path):
    from api.services.clarification_manager import ClarificationManager

    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    manager = ClarificationManager(memory)

    first = manager.create(
        entity_name="Franco", source_episode="ep_1",
        uncertainty_type="unclear who this is",
        suggested_classification="person", suggested_confidence=0.5,
        source_context="Franco came up.",
    )
    assert first == "inbox-001"

    again = manager.create(
        entity_name="Franco", source_episode="ep_2",
        uncertainty_type="unclear who this is",
        suggested_classification="person", suggested_confidence=0.5,
        source_context="Franco came up again.",
    )
    assert again is None
    assert len(list((memory / "inbox").glob("inbox-*.md"))) == 1
    fm = markdown_parser.parse(memory / "inbox" / "inbox-001.md").frontmatter
    assert fm["updated_date"] == str(__import__("datetime").date.today())


def test_a_different_uncertainty_about_the_same_mention_is_a_new_question(tmp_path):
    from api.services.clarification_manager import ClarificationManager

    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    manager = ClarificationManager(memory)

    manager.create(
        entity_name="Franco", source_episode="ep_1",
        uncertainty_type="unclear who this is",
        suggested_classification="person", suggested_confidence=0.5,
        source_context="ctx",
    )
    second = manager.create(
        entity_name="Franco", source_episode="ep_2",
        uncertainty_type="Possible duplicate of Franco Rossi",
        suggested_classification="person", suggested_confidence=0.5,
        source_context="ctx",
    )
    assert second == "inbox-002"
    assert len(list((memory / "inbox").glob("inbox-*.md"))) == 2


def test_merge_on_collision_adopts_the_new_date_keyed_claim_id(tmp_path):
    """H3 — Stage-1 claim ids are date-keyed, so the same value re-mentioned
    later arrives as a DIFFERENT open claim. The option must point at the live
    id, or it ages forever while being mentioned daily and a later resolution
    closes a claim that is already dead.
    """
    memory = tmp_path / "memory"
    path = _write_conflict(
        memory, "inbox-001", "rodrigo", "works-at",
        [
            {"key": "a", "label": "mongodb", "claim_id": "clm_2026-02-18_old",
             "observed_at": "2026-02-18", "last_referenced": "2026-02-18"},
        ],
    )

    changed = inbox_generator.merge_options_into(
        path,
        [{"key": "a", "label": "MongoDB", "claim_id": "clm_2026-08-30_new",
          "observed_at": "2026-08-30", "last_referenced": "2026-08-30"}],
        today="2026-08-30",
    )

    assert changed is True
    fm = markdown_parser.parse(path).frontmatter
    assert fm["options"][0]["claim_id"] == "clm_2026-08-30_new"
    assert fm["options"][0]["last_referenced"] == "2026-08-30"
    # The label the user already saw is preserved (match is case-insensitive).
    assert fm["options"][0]["label"] == "mongodb"


def test_write_claim_nudges_persists_source_episode_and_skips_multi_valued(tmp_path):
    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)
    base = {"id": "alpha-project", "action": "conflict_nudge", "entity": {"name": "Alpha Project"},
            "question": "q?", "allow_other": True, "allow_defer": True, "conflict_context": "c",
            "options": [{"key": "a", "label": "x"}, {"key": "b", "label": "y"}],
            "claim_id": "clm_b", "existing_claim_id": "clm_a", "source_episode": "ep_2026-08-20_001"}
    single = {**base, "predicate": "works-at"}
    multi = {**base, "predicate": "uses"}   # the seed says a tech stack is a set (G98)
    out = inbox_generator.write_claim_nudges([single, multi], memory)
    assert out == {"written": 1, "merged": 0, "skipped_multi_valued": 1}
    [path] = sorted((memory / "inbox").glob("inbox-*.md"))
    fm = markdown_parser.parse(path).frontmatter
    assert fm["predicate"] == "works-at" and fm["source_episode"] == "ep_2026-08-20_001"
