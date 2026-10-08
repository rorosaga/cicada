"""G112 (1): a skill Stage 4 detects is written with the conversations it came from, or not at all.

Synthetic bank, placeholder names; no model is called (Stage 4's answer is given)."""
import asyncio

import yaml

from api.services import conflict_resolver, decay_policy, inbox_generator, markdown_parser, section_provenance
from api.services import skill_grounding

EP1, EP2, EP3 = "ep_2026-03-02_1", "ep_2026-03-09_1", "ep_2026-03-10_1"


def _bank(tmp_path):
    (tmp_path / "entities").mkdir()
    (tmp_path / "inbox").mkdir()
    (tmp_path / "episodes").mkdir()
    for ep in (EP1, EP2, EP3):
        markdown_parser.write(tmp_path / "episodes" / f"{ep}.md", {"id": ep}, f"A conversation {ep}.\n")
    for slug, name, typ in (("alpha-tool", "Alpha Tool", "tool"), ("beta-project", "Beta Project", "project")):
        markdown_parser.write(tmp_path / "entities" / f"{slug}.md",
                              {"name": name, "type": typ, "status": "active", "confidence": 0.8,
                               "source_episodes": [EP1]}, "## Summary\nA thing.\n")
    return tmp_path


def _extracted():
    def ent(name, ep, ts):
        return {"name": name, "type": "tool", "source_episode": ep, "source_episode_timestamp": ts}
    return [
        {"episode_id": EP1, "entities": [ent("Alpha Tool", EP1, "2026-03-02T10:00:00+00:00"),
                                         ent("Beta Project", EP1, "2026-03-02T10:00:00+00:00")]},
        {"episode_id": EP2, "entities": [ent("alpha tool", EP2, "2026-03-09T10:00:00+00:00"),
                                         ent("Beta Project", EP2, "2026-03-09T10:00:00+00:00")]},
        {"episode_id": EP3, "entities": [ent("Alpha Tool", EP3, "2026-03-10T10:00:00+00:00")]},
    ]


SKILL = {"name": "Checks the tracker first", "description": "Before planning, reads the tracker.",
         "evidence_entities": ["Alpha Tool", "Beta Project"], "confidence": 0.7}


def _fm(bank, slug):
    return markdown_parser.parse(bank / "entities" / f"{slug}.md")


def _write(bank, skill_changes, changes=()):
    asyncio.run(inbox_generator.generate(list(changes), skill_changes, bank))


def test_a_grounded_skill_page_names_its_conversations_dates_and_evidence(tmp_path):
    bank = _bank(tmp_path)
    changes = skill_grounding.ground([SKILL], [], _extracted(), bank, name_to_id={"alpha tool": "alpha-tool"})
    assert [c["source_episodes"] for c in changes] == [[EP1, EP2]]   # where both came up together; not EP3
    _write(bank, changes)

    page = _fm(bank, "checks-the-tracker-first")
    fm = page.frontmatter
    assert fm["type"] == "skill" and fm["source_episodes"] == [EP1, EP2]
    assert fm["created"] == "2026-03-02" and fm["last_referenced"] == "2026-03-09"
    assert fm["confidence"] == 0.7 and fm["decay_class"] == "durable" and fm["layout_version"] == 2
    assert set(fm["related"]) == {"alpha-tool", "beta-project"}
    assert "## Summary" in page.body
    # The summary cites both conversations as reasoning — an inference, never a quotation.
    records = section_provenance.decode(fm[section_provenance.FIELD])
    rows = [ev for _hash, evs in records["summary"].values() for ev in evs]
    assert {(ev.episode, ev.kind) for ev in rows} == {(EP1, "reasoning"), (EP2, "reasoning")}
    edges = yaml.safe_load((bank / "graph_edges.yaml").read_text())["edges"]
    assert {"source": "checks-the-tracker-first", "target": "alpha-tool", "label": "draws on"} in edges
    assert "checks-the-tracker-first" in _fm(bank, "alpha-tool").frontmatter["related"]
    # G147: the page now counts the weeks it came up in.
    assert decay_policy.effective(fm).mention_weeks == 2


def test_one_named_entity_grounds_on_each_conversation_it_came_up_in(tmp_path):
    bank = _bank(tmp_path)
    skill = {**SKILL, "evidence_entities": ["Alpha Tool", "Nobody Here"]}
    [change] = skill_grounding.ground([skill], [], _extracted(), bank)
    assert change["source_episodes"] == [EP1, EP2, EP3]
    assert change["evidence_ids"] == ["alpha-tool"]


def test_a_skill_with_no_evidence_in_the_batch_is_not_written(tmp_path):
    bank = _bank(tmp_path)
    for skill in ({**SKILL, "evidence_entities": ["Gamma Thing"]}, {**SKILL, "evidence_entities": []},
                  {**SKILL, "evidence_entities": None}):
        assert skill_grounding.ground([skill], [], _extracted(), bank) == []
    _write(bank, [])
    assert not (bank / "entities" / "checks-the-tracker-first.md").exists()


def test_a_pattern_found_again_updates_its_page_instead_of_a_silent_no_op(tmp_path):
    bank = _bank(tmp_path)
    # A page the old Stage-4 writer left: no sources, one paragraph, decaying.
    markdown_parser.write(bank / "entities" / "checks-the-tracker-first.md",
                          {"name": "Checks the tracker first", "type": "skill", "status": "decaying",
                           "confidence": 0.3, "created": "2026-10-01", "last_referenced": "2026-10-01",
                           "source_episodes": [], "tags": [], "related": [], "version": 1},
                          "Before planning, reads the tracker.\n")
    changes = skill_grounding.ground([SKILL], [], _extracted(), bank)
    assert [c["action"] for c in changes] == ["update"]
    _write(bank, changes)
    fm = _fm(bank, "checks-the-tracker-first").frontmatter
    assert fm["source_episodes"] == [EP1, EP2] and fm["version"] == 2
    assert fm["status"] == "active" and fm["confidence"] >= 0.3
    assert set(fm["related"]) == {"alpha-tool", "beta-project"}


def test_a_name_held_by_another_kind_of_page_is_left_alone(tmp_path):
    bank = _bank(tmp_path)
    for fm in ({"name": "Checks the tracker first", "type": "concept"},
               {"name": "Checks the tracker first", "type": "skill", "tags": ["agent-skill"]},
               {"name": "Checks the tracker first", "type": "skill", "status": "dropped"}):
        markdown_parser.write(bank / "entities" / "checks-the-tracker-first.md", fm, "Mine.\n")
        assert skill_grounding.ground([SKILL], [], _extracted(), bank) == []


def test_a_page_another_change_of_the_batch_writes_is_not_written_twice(tmp_path):
    bank = _bank(tmp_path)
    stage1 = [{"id": "checks-the-tracker-first", "action": "create", "source_episodes": [EP1],
               "entity": {"name": "Checks the tracker first", "type": "skill"}}]
    assert skill_grounding.ground([SKILL], stage1, _extracted(), bank) == []


def test_two_answers_on_one_page_are_one_change(tmp_path):
    bank = _bank(tmp_path)
    other = {**SKILL, "name": "checks the tracker first", "evidence_entities": ["Alpha Tool"]}
    [change] = skill_grounding.ground([SKILL, other], [], _extracted(), bank)
    assert change["source_episodes"] == [EP1, EP2, EP3]


def test_a_memory_export_entry_gives_no_date(tmp_path):
    bank = _bank(tmp_path)
    extracted = [{"episode_id": ep, "entities": [
        {"name": n, "source_episode": ep, "source_episode_timestamp": None, "untimed": True}
        for n in ("Alpha Tool", "Beta Project")]} for ep in (EP1, EP2)]
    [change] = skill_grounding.ground([SKILL], [], extracted, bank)
    assert change["untimed"] is True and change["source_episode_timestamps"] == []
    _write(bank, [change])
    fm = _fm(bank, "checks-the-tracker-first").frontmatter
    assert "last_referenced" not in fm and fm["source_episodes"] == [EP1, EP2]


def test_a_page_found_again_is_not_charged_for_silence_in_the_same_batch():
    skill_changes = [{"id": "s", "action": "update"}]
    changes = [{"id": "s", "action": "decay", "trigger": "sleep/decay"},
               {"id": "t", "action": "decay", "trigger": "sleep/decay"},
               {"id": "s", "action": "update", "trigger": "sleep/extraction"}]
    assert skill_grounding.without_decay_of(changes, skill_changes) == changes[1:]


def test_apply_changes_is_the_only_writer(tmp_path, monkeypatch):
    """No second skill writer: `generate` hands grounded changes to `apply_changes`."""
    bank = _bank(tmp_path)
    seen = []

    def spy(changes, memory_path):
        seen.extend(c["id"] for c in changes)
        return conflict_resolver.apply_changes(changes, memory_path)

    monkeypatch.setattr(inbox_generator, "apply_changes", spy)
    _write(bank, skill_grounding.ground([SKILL], [], _extracted(), bank))
    assert seen == ["checks-the-tracker-first"]


def test_the_live_cycle_writes_a_grounded_skill_and_its_commit_line_names_the_conversation(tmp_path, monkeypatch):
    from api.services import git_service, sleep_cycle
    from api.tests import test_sleep_cycle_claims_wired as wired

    memory = wired._seed_bank(tmp_path)
    ep = "ep_2026-06-17_001"
    extracted = [{"episode_id": ep, "episode_timestamp": "2026-06-17T10:00:00", "origin": "claude-code",
                  "entities": [{"name": "Cicada", "type": "project", "source_episode": ep,
                                "source_episode_timestamp": "2026-06-17T10:00:00"}],
                  "relationships": []}]
    changes = [{"id": "cicada", "action": "create", "source_episode": ep, "source_episodes": [ep],
                "source_episode_timestamps": ["2026-06-17T10:00:00"], "trigger": "sleep/extraction",
                "entity": {"name": "Cicada", "type": "project", "confidence": 0.8}}]
    wired._patch_boundaries(monkeypatch, memory, extracted=extracted, resolved_changes=changes, resolved_edges=[])

    async def fake_detect(changes, existing, settings, **kw):
        return [{"name": "Reads the plan first", "description": "Reads the plan before coding.",
                 "evidence_entities": ["Cicada"], "confidence": 0.6},
                {"name": "Unseen habit", "description": "Something.", "evidence_entities": ["Nowhere"]}]

    messages = []

    async def fake_commit(memory_path, message):
        messages.append(message)
        return None

    monkeypatch.setattr("api.services.skill_extractor.detect_patterns", fake_detect)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    asyncio.run(sleep_cycle.run(wired._settings(memory), cycle_id="2026-06-17_skill"))

    fm = markdown_parser.parse(memory / "entities" / "reads-the-plan-first.md").frontmatter
    assert fm["source_episodes"] == [ep] and fm["created"] == "2026-06-17" and fm["related"] == ["cicada"]
    assert not (memory / "entities" / "unseen-habit.md").exists()
    assert sleep_cycle._state.skills_detected == 1
    assert any(f"entities/reads-the-plan-first.md: create (source: {ep}, trigger: sleep/skills" in m
               for m in messages)


def test_a_malformed_answer_is_skipped_not_fatal(tmp_path):
    bank = _bank(tmp_path)
    answers = ["not a dict", {"name": "No words"}, {**SKILL, "evidence_entities": "Alpha Tool"}]
    [change] = skill_grounding.ground(answers, [], _extracted(), bank)
    assert change["source_episodes"] == [EP1, EP2, EP3]
