"""G66 — every entity writer stamps a decay_class from the resolver, and
Stage-1 may never propose `evergreen`."""

from __future__ import annotations

import asyncio
from pathlib import Path

from api.models.schemas import DecayClass
from api.services import (
    agentic_write,
    conflict_resolver,
    entity_extractor,
    inbox_generator,
    inbox_service,
    markdown_parser,
    media_ingestor,
)


def _fm(memory: Path, entity_id: str) -> dict:
    return markdown_parser.parse(memory / "entities" / f"{entity_id}.md").frontmatter


def _run(coro):
    return asyncio.run(coro)


# --- Stage-1 rail -----------------------------------------------------------


def test_stage1_sanitizer_drops_an_evergreen_proposal(tmp_path):
    entity = {"name": "Some Bookmark", "decay_class": "evergreen"}
    entity_extractor.sanitize_decay_class(entity)
    assert "decay_class" not in entity


def test_stage1_sanitizer_keeps_the_three_producible_classes():
    for value in ["volatile", "durable", "active"]:
        entity = {"name": "X", "decay_class": value}
        entity_extractor.sanitize_decay_class(entity)
        assert entity["decay_class"] == value


def test_stage1_sanitizer_drops_volatile_on_a_person_a_company_and_a_project_only():
    """A sister who is moving flats, an employer the person just joined: a fact in motion, not a short-lived thing."""
    for kind in ("person", "company", "project"):
        entity = {"name": "X", "type": kind, "decay_class": "volatile"}
        entity_extractor.sanitize_decay_class(entity)
        assert "decay_class" not in entity
    for kind in ("concept", "tool", "location"):
        entity = {"name": "X", "type": kind, "decay_class": "volatile"}
        entity_extractor.sanitize_decay_class(entity)
        assert entity["decay_class"] == "volatile"


def test_stage1_sanitizer_drops_junk_and_leaves_a_missing_key_missing():
    entity = {"name": "X", "decay_class": "forever"}
    entity_extractor.sanitize_decay_class(entity)
    assert "decay_class" not in entity

    bare = {"name": "X"}
    entity_extractor.sanitize_decay_class(bare)
    assert bare == {"name": "X"}


def test_extraction_prompt_offers_the_three_and_forbids_evergreen():
    prompt = entity_extractor.EXTRACTION_SYSTEM_PROMPT
    assert "durable|active|volatile" in prompt
    assert "never evergreen" in prompt.lower()


# --- media ingest -----------------------------------------------------------


def test_media_entity_is_written_evergreen(tmp_path):
    entities_dir = tmp_path / "entities"
    item = media_ingestor.RawItem(url="https://example.com/post", title="A Post")
    meta = media_ingestor.MediaMeta(title="A Post", media_type="bookmark")

    media_ingestor.write_media_entity(entities_dir, "media-a-post", item, meta, "ep_1")

    fm = markdown_parser.parse(entities_dir / "media-a-post.md").frontmatter
    assert fm["decay_class"] == "evergreen"
    assert fm["decay_rate"] == 0.0


# --- skills -----------------------------------------------------------------


def test_skill_entity_is_written_durable(tmp_path):
    (tmp_path / "entities").mkdir(parents=True)
    (tmp_path / "inbox").mkdir(parents=True)

    # Stage 4's answers reach `generate` grounded (`skill_grounding.ground`, G112).
    _run(inbox_generator.generate(
        [], [{"id": "prefers-concise-summaries", "action": "create", "trigger": "sleep/skills",
              "source_episodes": ["ep_2026-01-02_1"], "source_episode": "ep_2026-01-02_1",
              "entity": {"name": "Prefers concise summaries", "type": "skill",
                         "description": "Keep it short.", "confidence": 0.6}}],
        tmp_path,
    ))

    fm = _fm(tmp_path, "prefers-concise-summaries")
    assert fm["decay_class"] == "durable"
    assert fm["decay_rate"] == 0.02


# --- Sleep create branch ----------------------------------------------------


def test_created_entity_defaults_to_active(tmp_path):
    (tmp_path / "entities").mkdir(parents=True)
    conflict_resolver.apply_changes(
        [{"id": "acme", "action": "create",
          "entity": {"name": "Acme", "type": "company", "confidence": 0.6}}],
        tmp_path,
    )
    fm = _fm(tmp_path, "acme")
    assert fm["decay_class"] == "active"
    assert fm["decay_rate"] == 0.05


def test_created_entity_honors_a_stage1_volatile_estimate(tmp_path):
    (tmp_path / "entities").mkdir(parents=True)
    conflict_resolver.apply_changes(
        [{"id": "current-role", "action": "create",
          "entity": {"name": "Current Role", "type": "concept",
                     "decay_class": "volatile"}}],
        tmp_path,
    )
    fm = _fm(tmp_path, "current-role")
    assert fm["decay_class"] == "volatile"
    assert fm["decay_rate"] == 0.15


def test_created_person_company_or_project_ignores_a_volatile_estimate_that_slipped_through(tmp_path):
    """The rail is held where the page is born too: a pending line or a merged payload may still carry it."""
    (tmp_path / "entities").mkdir(parents=True)
    conflict_resolver.apply_changes(
        [{"id": "sister", "action": "create",
          "entity": {"name": "Sister", "type": "person", "decay_class": "volatile"}},
         {"id": "employer", "action": "create",
          "entity": {"name": "Employer", "type": "company", "decay_class": "volatile"}},
         {"id": "the-study", "action": "create",
          "entity": {"name": "The study", "type": "project", "decay_class": "volatile"}},
         {"id": "the-trip", "action": "create",
          "entity": {"name": "The trip", "type": "concept", "decay_class": "volatile"}}],
        tmp_path,
    )
    assert _fm(tmp_path, "sister")["decay_class"] == "active"
    assert _fm(tmp_path, "employer")["decay_class"] == "active"
    assert _fm(tmp_path, "the-study")["decay_class"] == "active"   # born as a concept (ruling 56), judged as a project
    assert _fm(tmp_path, "the-trip")["decay_class"] == "volatile"


def test_extraction_prompt_puts_the_class_on_the_thing_not_on_a_fact_about_it():
    prompt = entity_extractor.EXTRACTION_SYSTEM_PROMPT
    section = prompt[prompt.index("DECAY CLASS"):prompt.index("WEBSITE (optional")]
    # volatile is for a thing that is itself short-lived; a fact in motion about a lasting thing is a claim.
    assert "never because a fact about it is changing" in section
    assert "a new role" not in section.split("- volatile:")[1].split("- durable:")[0]


def test_created_entity_ignores_an_evergreen_estimate_that_slipped_through(tmp_path):
    """Defense in depth: even if a payload reaches the writer with `evergreen`,
    the create branch refuses it — the rail is enforced at BOTH ends."""
    (tmp_path / "entities").mkdir(parents=True)
    conflict_resolver.apply_changes(
        [{"id": "mongodb", "action": "create",
          "entity": {"name": "MongoDB", "type": "tool", "decay_class": "evergreen"}}],
        tmp_path,
    )
    fm = _fm(tmp_path, "mongodb")
    assert fm["decay_class"] == "active"


def test_created_skill_page_is_durable_even_from_the_sleep_create_branch(tmp_path):
    (tmp_path / "entities").mkdir(parents=True)
    conflict_resolver.apply_changes(
        [{"id": "concise", "action": "create",
          "entity": {"name": "Concise", "type": "skill"}}],
        tmp_path,
    )
    assert _fm(tmp_path, "concise")["decay_class"] == "durable"


# --- agentic write ----------------------------------------------------------


def test_agentic_created_page_is_active(tmp_path):
    filepath, _entity_id = agentic_write._ensure_subject_page(
        tmp_path, "Some New Thing", "works-at", "ep_1"
    )
    fm = markdown_parser.parse(filepath).frontmatter
    assert fm["decay_class"] == "active"
    assert fm["decay_rate"] == 0.05


# --- clarification-answer writer (inbox_service ~601) -----------------------


def test_clarification_answer_creates_entity_with_active_decay_class(tmp_path):
    """The clarification `answer` branch's create-page path (inbox_service
    ~601) must route through the resolver too — not just the Sleep/agentic/
    media writers. Calls the private ``_resolve_clarification`` directly
    (rather than the public ``resolve``) so the test doesn't need a real git
    repo — ``resolve`` commits via ``git_service`` after a successful write."""
    memory = tmp_path
    (memory / "entities").mkdir(parents=True)
    inbox_dir = memory / "inbox"
    inbox_dir.mkdir(parents=True)

    item_frontmatter = {
        "kind": "clarification",
        "required_input": "text",
        "status": "pending",
        "priority": 0.5,
        "entity_id": "francesco",
        "entity_name": "Francesco",
        "entity_mention": "Francesco",
        "uncertainty_type": "who_is_this",
        "title": "Who is Francesco?",
        "created_date": "2026-01-01",
        "suggested_classification": "person",
        "suggested_confidence": 0.5,
    }
    item_path = inbox_dir / "inbox-001.md"
    markdown_parser.write(item_path, item_frontmatter, "Unresolved mention of Francesco.")
    parsed = markdown_parser.parse(item_path)

    class _FakeSettings:
        def __init__(self, memory_path: Path):
            self.memory_path = memory_path

    from api.models.schemas import InboxResolveRequest

    request = InboxResolveRequest(action="answer", answer="A colleague from the lab.")
    _run(inbox_service._resolve_clarification(
        item_path, parsed, request, _FakeSettings(memory)
    ))

    fm = _fm(memory, "francesco")
    assert fm["decay_class"] == "active"
    assert fm["decay_rate"] == 0.05
