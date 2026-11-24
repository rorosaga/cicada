"""Who asked a question (`question_origin`, owner 2026-11-24): the one quiet line on the card, "Asked 13 days ago by
Sleep's duplicate check". Derived from the question's own file, never stored, never from git; unknown is nothing.
Synthetic bank only (alpha-project, bob-example); no real bank, no model, no network."""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from api.services import (alias_collisions, bank_index, clarification_manager, inbox_service, markdown_parser,
                          mcp_tools, meeting_speakers, page_edits, person_duplicates, question_origin, role_people,
                          same_name_tend, source_proposals, source_refresh, typo_join, wrong_aliases)

TODAY = "2026-11-24"


def _asked(fm: dict, kind: str | None = None):
    return question_origin.of({"created_date": "2026-11-11", **fm}, kind or fm.get("kind"))


# --- who: one case per writer, built from the stamps the writers really write ---------------------------------------

@pytest.mark.parametrize("fm, step, how", [
    ({"kind": "merge_suggestion", "detected": "person_duplicate"}, "duplicate_check", "rule"),
    ({"kind": "merge_suggestion", "detected": "spelling"}, "duplicate_check", "rule"),
    ({"kind": "merge_suggestion", "detected": "alias_collision"}, "shared_name_check", "rule"),
    ({"kind": "merge_suggestion", "detected": "same_name_doubt"}, "same_name_review", "model"),
    ({"kind": "decay"}, "decay_check", "rule"),
    ({"kind": "decay", "trigger": "sleep/conflict_resolution"}, "decay_check", "rule"),
    ({"kind": "conflict", "trigger": "sleep/conflict_resolution"}, "conflict_check", "rule"),
    ({"kind": "conflict"}, "conflict_check", "rule"),
    ({"kind": "conflict", "trigger": "sleep/phone_number"}, "number_check", "rule"),
    ({"kind": "normalization", "trigger": "sleep/conflict_resolution"}, "wording_check", "rule"),
    ({"kind": "divergence", "trigger": "sleep/source-refresh"}, "source_recheck", "check"),
    ({"kind": "followup"}, "followup_check", "rule"),
    ({"kind": "sensitive"}, "sensitive_check", "rule"),
    ({"kind": "removal", "trigger": "sync/folder_removal"}, "source_sync", "rule"),
    ({"kind": "clarification", "asks": "name", "owner_role": "partner"}, "unnamed_check", "rule"),
    ({"kind": "clarification", "asks": "speaker", "speaker_marker": "S1"}, "meeting_read", "model"),
    ({"kind": "clarification", "asks": "sources"}, "link_suggestions", "rule"),
    ({"kind": "clarification", "source_episode": "ep_2026-11-11_001", "uncertainty_type": "Who or what?"},
     "conversation_read", "model"),
    ({"kind": "merge_suggestion", "source_episode": "ep_2026-11-11_001",
      "uncertainty_type": "Possible duplicate of Bob Example"}, "conversation_read", "model"),
    ({"kind": "page_edit", "origin": "wrong_alias", "proposed_by": "cicada", "trigger": "sleep/wrong_alias"},
     "shared_name_check", "rule"),
])
def test_each_step_is_named_by_what_it_stamped(fm, step, how):
    asked = _asked(fm)
    assert (asked.step, asked.how) == (step, how)
    assert asked.by == question_origin.STEPS[step][1] and asked.agent is None


def test_an_agents_proposal_names_its_harness_and_never_a_step():
    for fm in ({"kind": "page_edit", "proposed_by": "claude-code", "trigger": "mcp/claude-code"},
               {"kind": "page_edit", "trigger": "mcp/claude-code"}):
        asked = _asked(fm)
        assert (asked.how, asked.agent, asked.step, asked.by) == ("agent", "claude-code", None, "an agent")
    generic = _asked({"kind": "page_edit", "proposed_by": "agent"})
    assert (generic.how, generic.agent) == ("agent", None), "the record says only 'an agent': the card says so too"


def test_a_question_the_record_says_nothing_about_has_no_who():
    """Never a guess: a clarification with no conversation, a bare merge question, an empty file."""
    for fm in ({"kind": "clarification"}, {"kind": "merge_suggestion"}, {"kind": "clarification",
               "source_episode": "ep_x"}, {"kind": "removal"}, {}):
        assert question_origin.of(fm) is None
    assert question_origin.wire({"kind": "clarification"}) is None


def test_the_step_words_never_name_a_provider_or_a_model():
    """CLAUDE.md, "Copy is provider-neutral": the line describes the step; a model's name is shown where provenance
    already shows it (a claim's author, the card's own "<model>'s guess")."""
    banned = ("claude", "anthropic", "openai", "gpt", "gemini", "haiku", "sonnet", "opus", "codex", "ollama", "model")
    for step, (how, words) in question_origin.STEPS.items():
        assert how in question_origin.HOWS
        assert not any(b in words.lower() for b in banned), (step, words)
        assert words[0].isupper() or words.startswith("the "), words


# --- the table follows the writers: a writer that renames its stamp fails here, not on the owner's card -------------

def test_the_stamps_the_table_reads_are_the_ones_the_writers_write():
    assert alias_collisions.DETECTED == "alias_collision"
    assert '"detected": "person_duplicate"' in inspect.getsource(person_duplicates)
    assert '"detected": "person_duplicate"' in inspect.getsource(typo_join)
    assert '"detected": "same_name_doubt"' in inspect.getsource(same_name_tend)
    assert wrong_aliases.ORIGIN == "wrong_alias" and wrong_aliases.AUTHOR in question_origin._OWN
    assert source_refresh.TRIGGER == "sleep/source-refresh" and source_proposals.TRIGGER == "sleep/where-to-check"
    assert role_people.TRIGGER == "maintenance/placeholder-people" and role_people.ASKS == "name"
    assert meeting_speakers.ASKS == "speaker" and source_proposals.ASKS == "sources"
    from api.services import papers
    assert '"sync/folder_removal"' in inspect.getsource(papers)
    assert 'f"mcp/{author}"' in inspect.getsource(page_edits)


def test_a_clarification_the_manager_writes_is_a_read_of_a_conversation(tmp_path):
    (tmp_path / "inbox").mkdir()
    made = clarification_manager.ClarificationManager(tmp_path).create(
        entity_name="Bob", source_episode="ep_2026-11-11_001", uncertainty_type="unknown_entity",
        suggested_classification="person", suggested_confidence=0.6, source_context="Bob joined the call.")
    fm = markdown_parser.parse(tmp_path / "inbox" / f"{made}.md").frontmatter
    asked = question_origin.of(fm)
    assert asked is not None and (asked.step, asked.how) == ("conversation_read", "model")


def test_a_page_edit_an_agent_proposes_names_the_agent(tmp_path):
    (tmp_path / "inbox").mkdir()
    rel = page_edits.write_proposal(
        tmp_path, entity_id="alpha-project", name="Alpha Project", request=page_edits.Request(remove_aliases=["Alpha"]),
        reason="Alpha is another thing.", author="claude-code", session="s1", day="2026-11-11")
    asked = question_origin.of(markdown_parser.parse(tmp_path / rel).frontmatter)
    assert (asked.how, asked.agent) == ("agent", "claude-code")
    own = page_edits.write_proposal(
        tmp_path, entity_id="alpha-project", name="Alpha Project", request=page_edits.Request(remove_aliases=["Al"]),
        reason="Al is another thing.", author=wrong_aliases.AUTHOR, session=None, day="2026-11-11",
        origin=wrong_aliases.ORIGIN)
    asked = question_origin.of(markdown_parser.parse(tmp_path / own).frontmatter)
    assert (asked.step, asked.how) == ("shared_name_check", "rule")


# --- the wire and the agent's line ---------------------------------------------------------------------------------

def test_the_inbox_serves_asked_by_beside_the_day(tmp_path):
    bank_index.invalidate()
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (tmp_path / "entities").mkdir()
    for page, name in (("bob-example", "Bob Example"), ("bobby-example", "Bobby Example")):
        markdown_parser.write(tmp_path / "entities" / f"{page}.md",
                              {"name": name, "type": "person", "status": "active"}, "## Summary\nA fixture.\n")
    markdown_parser.write(inbox / "inbox-001.md", {
        "kind": "merge_suggestion", "required_input": "merge", "status": "pending", "entity_id": "bob-example",
        "entity_name": "Bob Example", "title": "Is Bob Example the same as Bobby Example?",
        "created_date": "2026-11-11", "detected": "person_duplicate", "merge_target_hint": "bobby-example"}, "Why.")
    markdown_parser.write(inbox / "inbox-002.md", {
        "kind": "clarification", "required_input": "freetext", "status": "pending", "entity_id": "bob-example",
        "entity_name": "Bob Example", "title": "Who is Bob?", "created_date": "2026-11-12"}, "Unknown.")
    items = {i.id: i for i in inbox_service.load_inbox(tmp_path)}
    one = items["inbox-001"]
    assert one.created_date == "2026-11-11"
    assert one.asked_by == {"step": "duplicate_check", "how": "rule", "by": "Sleep's duplicate check", "agent": None}
    assert items["inbox-002"].asked_by is None, "unknown is nothing"
    dumped = one.model_dump(by_alias=True)
    assert dumped["askedBy"]["how"] == "rule" and items["inbox-002"].model_dump(by_alias=True)["askedBy"] is None


def test_the_agents_line_says_when_and_by_what(tmp_path):
    fm = {"kind": "merge_suggestion", "detected": "person_duplicate", "created_date": "2026-11-11"}
    assert question_origin.line(fm, TODAY) == (
        "Asked 13 days ago by Sleep's duplicate check (a rule found it; no model read anything for it).")
    assert question_origin.line({**fm, "detected": "same_name_doubt"}, TODAY).endswith(
        "(a model read a conversation to raise it).")
    agent = {"kind": "page_edit", "proposed_by": "claude-code", "created_date": "2026-11-23"}
    assert question_origin.line(agent, TODAY) == (
        "Asked yesterday by an agent (claude-code) (an agent proposed it through Cicada's tools).")
    assert question_origin.line({"kind": "clarification", "created_date": "2026-11-11"}, TODAY) == "Asked 13 days ago."
    assert question_origin.line({"kind": "decay"}, TODAY) is None, "no day, nothing said"
    assert question_origin.line({"kind": "decay", "created_date": "not a day"}, TODAY) is None


def test_check_nudges_carries_the_line_in_list_and_ask_mode(tmp_path):
    bank_index.invalidate()
    for sub in ("entities", "episodes", "inbox"):
        (tmp_path / sub).mkdir()
    markdown_parser.write(tmp_path / "entities" / "bob-example.md",
                          {"name": "Bob Example", "type": "person", "status": "active"}, "## Summary\nA fixture.\n")
    markdown_parser.write(tmp_path / "inbox" / "inbox-001.md", {
        "kind": "clarification", "status": "pending", "entity_id": "bob-example", "entity_name": "Bob Example",
        "entity_mention": "Bob", "question": "Who is Bob?", "created_date": "2026-11-11",
        "source_episode": "ep_2026-11-11_001", "uncertainty_type": "unknown_entity",
        "options": [{"key": "a", "label": "A designer"}]}, "ctx")
    ctx = mcp_tools.ToolContext(memory_path=lambda: tmp_path, session_id="s", harness="unknown")
    listed = mcp_tools.check_nudges(ctx, None)
    assert "Asked " in listed and "by Sleep's read of a conversation (a model read a conversation to raise it)." in listed
    asked = mcp_tools.check_nudges(ctx, "Can Bob review the designs?", ["bob-example"], "ask")
    assert "by Sleep's read of a conversation" in asked
    bank_index.invalidate()
