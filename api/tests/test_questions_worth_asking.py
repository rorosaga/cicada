"""G239: Sleep asks only what the person alone can answer and what changes something; the rest waits in the index.

Measured 2026-11-05 on a real run (counts only): 25 questions from 53 conversations, 14 "who or what is" about a name a
note merely mentions, 9 "same as" between two different things, and 2 of 13 new pages a phrase typed `skill`. Three
causes, each the model's judgement replaced by a proxy: a low extraction confidence asked, an unsure judge asked on
names that look alike with nothing to read, and a skill got a page on one note. Everything here is invented.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from api.services import (clarification_manager, engine_identity, engine_schemas, entity_extractor, entity_resolver,
                          inbox_tend, inbox_wording, markdown_parser, skill_extractor, web_settle)


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    return memory


def _settings(memory: Path) -> SimpleNamespace:
    return SimpleNamespace(memory_path=memory, litellm_model="gpt-5.4-mini", litellm_disambiguation_model="gpt-5.4-nano",
                           sleep_promotion_threshold=2)


def _extracted(*entities: dict, relationships: tuple = ()) -> list[dict]:
    return [{"episode_id": "ep_2026-01-01_001", "entities": list(entities), "relationships": list(relationships)}]


def _questions(memory: Path) -> list[dict]:
    return [markdown_parser.parse(p).frontmatter for p in sorted((memory / "inbox").glob("inbox-*.md"))]


def _name(name: str, **extra) -> dict:
    return {"name": name, "type": "person", "confidence": 0.3, "source_episode": "ep_2026-01-01_001",
            "summary": f"{name} came up.", **extra}


def _page(page_id: str, name: str, page_type: str = "company") -> dict:
    return {"id": page_id, "frontmatter": {"name": name, "type": page_type, "confidence": 0.9}, "body": f"{name}."}


def test_a_low_confidence_alone_asks_nothing_and_the_name_waits(tmp_path):
    memory = _bank(tmp_path)
    asyncio.run(entity_resolver.resolve(_extracted(_name("Bob")), [], _settings(memory)))
    assert _questions(memory) == []
    assert "Bob" in (memory / "pending_entities.jsonl").read_text(), "never lost: the mention stays in the index"


def test_the_models_word_asks_and_says_why_on_the_card(tmp_path):
    memory = _bank(tmp_path)
    asyncio.run(entity_resolver.resolve(
        _extracted(_name("Bob", ask_person="the lease depends on him", confidence=0.8)), [], _settings(memory)))
    (fm,) = _questions(memory)
    assert fm["title"] == "Who or what is Bob?"
    assert fm["why_asked"] == "the lease depends on him"
    assert "Bob" in (memory / "pending_entities.jsonl").read_text()
    assert inbox_wording.spoken(fm, "2026-01-02").reason == "The lease depends on him."


def test_a_sibling_that_asks_is_enough_and_its_own_conversation_is_cited(tmp_path):
    memory = _bank(tmp_path)
    second = _name("Bob", ask_person="the deposit is his", source_episode="ep_2026-01-02_001")
    extracted = [*_extracted(_name("Bob")),
                 {"episode_id": "ep_2026-01-02_001", "entities": [second], "relationships": []}]
    settings = SimpleNamespace(**{**vars(_settings(memory)), "sleep_promotion_threshold": 3})
    asyncio.run(entity_resolver.resolve(extracted, [], settings))
    (fm,) = _questions(memory)
    assert fm["source_episode"] == "ep_2026-01-02_001"


def test_a_new_page_the_model_asks_about_keeps_its_question(tmp_path):
    """A name over the bar still gets its page, and the question stands: the confident extraction that created the page
    must not resolve it "organically" in the same breath."""
    memory = _bank(tmp_path)
    extracted = [*_extracted(_name("Bob", ask_person="the deposit is his", confidence=0.8)),
                 {"episode_id": "ep_2026-01-02_001", "relationships": [],
                  "entities": [_name("Bob", source_episode="ep_2026-01-02_001", confidence=0.8)]}]
    out = asyncio.run(entity_resolver.resolve(extracted, [], _settings(memory)))
    assert "bob" in {c["id"] for c in out["changes"] if c.get("action") == "create"}
    (fm,) = _questions(memory)
    assert fm["why_asked"] == "the deposit is his"


def _stake_card(memory: Path) -> None:
    """Run 1: a name with something resting on it, no page yet."""
    asyncio.run(entity_resolver.resolve(
        _extracted(_name("Bob", ask_person="the lease depends on him", confidence=0.8)), [], _settings(memory)))
    (fm,) = _questions(memory)
    assert fm["why_asked"] == "the lease depends on him"


def _second_mention(episode: str = "ep_2026-01-02_001") -> list[dict]:
    return [{"episode_id": episode, "relationships": [], "entities": [_name("Bob", source_episode=episode, confidence=0.8)]}]


def test_a_later_conversation_that_creates_the_page_leaves_the_stake_question_open(tmp_path):
    """Run 2 names Bob confidently with no `ask_person`: the page is born (entity_resolver's create branch) and the
    person's question stands."""
    memory = _bank(tmp_path)
    _stake_card(memory)
    out = asyncio.run(entity_resolver.resolve(_second_mention(), [], _settings(memory)))
    assert "bob" in {c["id"] for c in out["changes"] if c.get("action") == "create"}
    (fm,) = _questions(memory)
    assert fm["why_asked"] == "the lease depends on him"


def test_a_mention_matching_the_page_leaves_the_stake_question_open(tmp_path):
    """Bob's page is already there: run 2 matches it (the "same" branch) and the question still stands."""
    memory = _bank(tmp_path)
    _stake_card(memory)
    page = _page("bob", "Bob", "person")
    out = asyncio.run(entity_resolver.resolve(_second_mention(), [page], _settings(memory)))
    assert "bob" in {c["id"] for c in out["changes"] if c.get("action") == "update"}
    (fm,) = _questions(memory)
    assert fm["why_asked"] == "the lease depends on him"


def test_a_question_with_no_stake_still_closes_on_a_confident_mention(tmp_path):
    memory = _bank(tmp_path)
    clarifier = clarification_manager.ClarificationManager(memory)
    clarifier.create("Bob", "ep_2026-01-01_001", "Insufficient context to classify", "person — came up", 0.4, "Came up.")
    assert clarifier.check_organic_resolution("Bob", 0.4) is False
    assert clarifier.check_organic_resolution("Bob", 0.8) is True
    assert _questions(memory) == []


def test_a_stake_said_on_a_question_already_open_keeps_it_open_too(tmp_path):
    """A card raised before G239 has no stake; the model's word on the same question gives it one, or the next confident
    mention would delete what was just asked on purpose."""
    memory = _bank(tmp_path)
    clarifier = clarification_manager.ClarificationManager(memory)
    args = ("Bob", "ep_2026-01-01_001", "Insufficient context to classify", "person — came up", 0.4, "Came up.")
    assert clarifier.create(*args) is not None
    assert clarifier.create(*args, why_asked="the lease depends on him") is None
    assert clarifier.check_organic_resolution("Bob", 0.8) is False
    (fm,) = _questions(memory)
    assert fm["why_asked"] == "the lease depends on him"


def test_a_question_asked_on_purpose_is_never_closed_as_said_in_passing_nor_looked_up(tmp_path):
    memory = _bank(tmp_path)
    clarifier = clarification_manager.ClarificationManager(memory)
    item = clarifier.create("Kestrel", "ep_2026-01-01_001", "Insufficient context to classify", "concept — a transfer",
                            0.4, "A transfer.", why_asked="the transfer is due the 15th")
    fm = markdown_parser.parse(memory / "inbox" / f"{item}.md").frontmatter
    assert inbox_tend.passing_rule(memory, item, fm) == (None, "needs_person")
    assert web_settle.classify(memory, fm, "A transfer.", web_settle.bank_facts(memory)) == (None, "person_context")


def test_a_duplicate_question_never_carries_a_reason(tmp_path):
    memory = _bank(tmp_path)
    clarifier = clarification_manager.ClarificationManager(memory)
    item = clarifier.create("Alpha Tool", "", "Possible duplicate of Alpha Suite", "tool — a thing", 0.5, "A thing.",
                            why_asked="ignored")
    assert "why_asked" not in markdown_parser.parse(memory / "inbox" / f"{item}.md").frontmatter


def _linked(name: str, kind: str) -> tuple[dict, dict]:
    entity = {"name": name, "type": kind, "confidence": 0.8, "source_episode": "ep_2026-01-01_001", "summary": "A phrase."}
    rel = {"source": name, "target": "Alpha Labs", "label": "used at",
           "evidence": [{"kind": "user", "start": 0, "end": 5, "episode": "ep_2026-01-01_001"}]}
    return entity, rel


def test_one_note_linked_to_a_page_gives_a_thing_a_page_but_never_a_skill(tmp_path):
    memory = _bank(tmp_path)
    skill, rel_a = _linked("Maintains checklists for onboarding", "skill")
    tool, rel_b = _linked("Beta Tool", "tool")
    out = asyncio.run(entity_resolver.resolve(_extracted(skill, tool, relationships=(rel_a, rel_b)),
                                              [_page("alpha-labs", "Alpha Labs")], _settings(memory)))
    created = {c["id"] for c in out["changes"] if c.get("action") == "create"}
    assert "beta-tool" in created
    assert "maintains-checklists-for-onboarding" not in created
    assert "Maintains checklists" in (memory / "pending_entities.jsonl").read_text()


def test_a_skill_named_in_two_conversations_gets_its_page(tmp_path):
    memory = _bank(tmp_path)
    one, _ = _linked("Knot Tying", "skill")
    two = {**one, "source_episode": "ep_2026-01-02_001"}
    extracted = [*_extracted(one), {"episode_id": "ep_2026-01-02_001", "entities": [two], "relationships": []}]
    out = asyncio.run(entity_resolver.resolve(extracted, [], _settings(memory)))
    assert "knot-tying" in {c["id"] for c in out["changes"] if c.get("action") == "create"}


def _episode(memory: Path, episode_id: str, body: str) -> None:
    (memory / "episodes" / f"{episode_id}.md").write_text(
        f"---\nid: {episode_id}\nsource: apple-notes\ntimestamp: '2026-01-01T09:00:00+00:00'\n---\n\n{body}\n")


def test_the_judge_reads_the_lines_that_name_both(tmp_path):
    memory = _bank(tmp_path)
    _episode(memory, "ep_2026-01-01_001", "Groceries\nAna has the spare keys, not Anna.\nCall the plumber")
    candidate = {"source": "existing", "id": "anna", "data": _page("anna", "Anna", "person")}
    out = entity_resolver._with_said_together(candidate, _name("Ana"), _settings(memory))
    assert 'name both: "Ana has the spare keys, not Anna."' in out["note"]
    assert "plumber" not in out["note"], "only the lines naming both"
    assert "note" not in candidate, "the candidate itself is left as it was"


def test_the_judge_reads_every_conversation_of_the_batch_that_named_the_mention(tmp_path):
    memory = _bank(tmp_path)
    _episode(memory, "ep_2026-01-01_001", "Ana has the spare keys.")
    _episode(memory, "ep_2026-01-02_001", "Ana might be Anna, I can't tell.")
    candidate = {"source": "existing", "id": "anna", "data": _page("anna", "Anna", "person")}
    mention = _name("Ana", **{entity_resolver.BATCH_EPISODES: ["ep_2026-01-01_001", "ep_2026-01-02_001"]})
    assert "Ana might be Anna" in entity_resolver._with_said_together(candidate, mention, _settings(memory))["note"]


def test_no_line_naming_both_leaves_the_judge_as_it_was(tmp_path):
    memory = _bank(tmp_path)
    _episode(memory, "ep_2026-01-01_001", "Ana has the spare keys.")
    candidate = {"source": "existing", "id": "anna", "data": _page("anna", "Anna", "person"), "note": "A lead.\n"}
    assert entity_resolver._with_said_together(candidate, _name("Ana"), _settings(memory)) == candidate
    assert entity_resolver._with_said_together(candidate, {"name": "Ana"}, _settings(memory)) == candidate


def test_both_judges_are_told_what_an_unsure_costs():
    for prompt in (entity_resolver._DISAMBIG_PROMPT, entity_resolver._DISAMBIG_BATCH_PROMPT):
        assert entity_resolver._UNSURE_GUIDELINE in prompt
        assert "hesitating" not in prompt


def test_stage_one_is_given_the_goal_and_the_schema_carries_the_field():
    prompt = entity_extractor.EXTRACTION_SYSTEM_PROMPT
    assert "ASK PERSON" in prompt and '"ask_person"' in prompt
    for strict in (True, False):
        props = engine_schemas.extraction_schema(strict=strict)["properties"]["entities"]["items"]["properties"]
        assert "ask_person" in props


def test_stage_four_asks_for_how_the_person_works_not_what_comes_up_together():
    assert "RELATIONSHIP PATTERNS" not in skill_extractor.SKILL_DETECTION_RULES
    assert "how this person works" in skill_extractor.SKILL_DETECTION_RULES


def test_a_reason_carrying_the_plan_account_is_dropped_and_the_question_with_it():
    entities = [{"name": "Bob", "type": "person", "ask_person": "acct-alpha owes him"}]
    engine_identity.scrub_extraction(entities, [], [], "Bob owes money.", frozenset({"acct-alpha"}))
    assert not entities[0]["ask_person"]
