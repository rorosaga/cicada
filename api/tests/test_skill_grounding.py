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
    changes = skill_grounding.ground([SKILL], [], _extracted(), bank, name_to_id={"alpha tool": "alpha-tool"}).changes
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
    [change] = skill_grounding.ground([skill], [], _extracted(), bank).changes
    assert change["source_episodes"] == [EP1, EP2, EP3]
    assert change["evidence_ids"] == ["alpha-tool"]


def test_a_skill_with_no_evidence_in_the_batch_is_not_written(tmp_path):
    bank = _bank(tmp_path)
    for skill in ({**SKILL, "evidence_entities": ["Gamma Thing"]}, {**SKILL, "evidence_entities": []},
                  {**SKILL, "evidence_entities": None}):
        plan = skill_grounding.ground([skill], [], _extracted(), bank)
        assert plan.changes == [] and plan.held == []
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
    changes = skill_grounding.ground([SKILL], [], _extracted(), bank).changes
    assert [c["action"] for c in changes] == ["update"]
    _write(bank, changes)
    fm = _fm(bank, "checks-the-tracker-first").frontmatter
    assert fm["source_episodes"] == [EP1, EP2] and fm["version"] == 2
    assert fm["status"] == "active" and fm["confidence"] >= 0.3
    assert set(fm["related"]) == {"alpha-tool", "beta-project"}
    # A re-detection is evidence, not new text: a paraphrase never piles an undated History bullet onto the page.
    paraphrase = {**SKILL, "description": "Reads the tracker before any planning."}
    _write(bank, skill_grounding.ground([paraphrase], [], _extracted(), bank).changes)
    body = _fm(bank, "checks-the-tracker-first").body
    assert "History" not in body and "Reads the tracker before any planning." not in body
    assert "Before planning, reads the tracker." in body


def test_a_name_held_by_another_kind_of_page_is_left_alone(tmp_path):
    bank = _bank(tmp_path)
    for fm in ({"name": "Checks the tracker first", "type": "concept"},
               {"name": "Checks the tracker first", "type": "skill", "tags": ["agent-skill"]},
               {"name": "Checks the tracker first", "type": "skill", "status": "dropped"}):
        markdown_parser.write(bank / "entities" / "checks-the-tracker-first.md", fm, "Mine.\n")
        assert skill_grounding.ground([SKILL], [], _extracted(), bank) == skill_grounding.SkillPlan()


def test_a_page_another_change_of_the_batch_writes_is_not_written_twice(tmp_path):
    bank = _bank(tmp_path)
    stage1 = [{"id": "checks-the-tracker-first", "action": "create", "source_episodes": [EP1],
               "entity": {"name": "Checks the tracker first", "type": "skill"}}]
    assert skill_grounding.ground([SKILL], stage1, _extracted(), bank) == skill_grounding.SkillPlan()


def test_two_answers_on_one_page_are_one_change(tmp_path):
    bank = _bank(tmp_path)
    other = {**SKILL, "name": "checks the tracker first", "evidence_entities": ["Alpha Tool"]}
    [change] = skill_grounding.ground([SKILL, other], [], _extracted(), bank).changes
    assert change["source_episodes"] == [EP1, EP2, EP3]


def test_a_memory_export_entry_gives_no_date(tmp_path):
    bank = _bank(tmp_path)
    extracted = [{"episode_id": ep, "entities": [
        {"name": n, "source_episode": ep, "source_episode_timestamp": None, "untimed": True}
        for n in ("Alpha Tool", "Beta Project")]} for ep in (EP1, EP2)]
    [change] = skill_grounding.ground([SKILL], [], extracted, bank).changes
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
    _write(bank, skill_grounding.ground([SKILL], [], _extracted(), bank).changes)
    assert seen == ["checks-the-tracker-first"]


def test_the_live_cycle_holds_a_one_conversation_skill_and_writes_it_on_the_second(tmp_path, monkeypatch):
    """owner ruling 2026-10-09: a new skill page needs two conversations. Cycle one holds the skill on the pending store;
    cycle two, on another conversation, writes the page citing both and the line leaves the store."""
    from api.services import git_service, pending_store, skill_hold, sleep_cycle
    from api.tests import test_sleep_cycle_claims_wired as wired

    memory = wired._seed_bank(tmp_path)
    ep1, ep2 = "ep_2026-06-17_001", "ep_2026-06-24_001"

    def batch(ep, ts, action):
        extracted = [{"episode_id": ep, "episode_timestamp": ts, "origin": "claude-code",
                      "entities": [{"name": "Cicada", "type": "project", "source_episode": ep,
                                    "source_episode_timestamp": ts}],
                      "relationships": []}]
        changes = [{"id": "cicada", "action": action, "source_episode": ep, "source_episodes": [ep],
                    "source_episode_timestamps": [ts], "trigger": "sleep/extraction",
                    "entity": {"name": "Cicada", "type": "project", "confidence": 0.8}}]
        wired._patch_boundaries(monkeypatch, memory, extracted=extracted, resolved_changes=changes,
                                resolved_edges=[])

    async def fake_detect(changes, existing, settings, **kw):
        return [{"name": "Reads the plan first", "description": "Reads the plan before coding.",
                 "evidence_entities": ["Cicada"], "confidence": 0.6},
                {"name": "Unseen habit", "description": "Something.", "evidence_entities": ["Nowhere"]}]

    messages = []

    async def fake_commit(memory_path, message):
        messages.append(message)
        return None

    def run(cycle_id):
        monkeypatch.setattr("api.services.skill_extractor.detect_patterns", fake_detect)
        monkeypatch.setattr(git_service, "commit_changes", fake_commit)
        asyncio.run(sleep_cycle.run(wired._settings(memory), cycle_id=cycle_id))

    page = memory / "entities" / "reads-the-plan-first.md"
    batch(ep1, "2026-06-17T10:00:00", "create")
    run("2026-06-17_skill")
    assert not page.exists() and not (memory / "entities" / "unseen-habit.md").exists()
    assert sleep_cycle._state.skills_detected == 0
    [line] = skill_hold.load(memory)
    assert (line.name, line.source_episode, line.description, line.evidence_ids) == \
        ("Reads the plan first", ep1, "Reads the plan before coding.", ["cicada"])
    assert pending_store.load(memory) == []        # Stage 2's store is not where a skill waits

    markdown_parser.write(memory / "episodes" / f"{ep2}.md",
                          {"id": ep2, "processed": False, "source": "mcp", "timestamp": "2026-06-24T10:00:00"},
                          "Cicada again.")
    batch(ep2, "2026-06-24T10:00:00", "update")
    run("2026-06-24_skill")
    fm = markdown_parser.parse(page).frontmatter
    assert fm["source_episodes"] == [ep1, ep2] and fm["related"] == ["cicada"]
    assert fm["created"] == "2026-06-17" and fm["last_referenced"] == "2026-06-24"
    assert sleep_cycle._state.skills_detected == 1
    assert skill_hold.load(memory) == []
    assert any(f"entities/reads-the-plan-first.md: create (source: {ep2}, trigger: sleep/skills" in m
               for m in messages)


def test_a_malformed_answer_is_skipped_not_fatal(tmp_path):
    bank = _bank(tmp_path)
    answers = ["not a dict", {"name": "No words"}, {**SKILL, "evidence_entities": "Alpha Tool"}]
    [change] = skill_grounding.ground(answers, [], _extracted(), bank).changes
    assert change["source_episodes"] == [EP1, EP2, EP3]


# --- owner ruling 2026-10-09: a new skill page needs two or more conversations ---------------------------------------


def _one_conversation(ep):
    return [{"episode_id": ep, "entities": [
        {"name": n, "type": "tool", "source_episode": ep, "source_episode_timestamp": f"{ep[3:13]}T10:00:00+00:00"}
        for n in ("Alpha Tool", "Beta Project")]}]


def _dated_bank(tmp_path):
    bank = _bank(tmp_path)
    for ep in (EP1, EP2, EP3):
        markdown_parser.write(bank / "episodes" / f"{ep}.md", {"id": ep, "timestamp": f"{ep[3:13]}T10:00:00+00:00"},
                              f"A conversation {ep}.\n")
    return bank


def _settle(bank, plan):
    _write(bank, plan.changes)
    return skill_grounding.settle(bank, plan)


def test_a_skill_seen_in_one_conversation_is_held_not_written(tmp_path):
    from api.services import skill_hold

    bank = _dated_bank(tmp_path)
    plan = skill_grounding.ground([SKILL], [], _one_conversation(EP1), bank)
    assert plan.changes == [] and [h.source_episode for h in plan.held] == [EP1]
    assert _settle(bank, plan) == (1, 0)
    assert not (bank / "entities" / "checks-the-tracker-first.md").exists()
    [line] = skill_hold.load(bank)
    assert (line.slug, line.name, line.source_episode, line.description, line.confidence, line.evidence_ids) == \
        ("checks-the-tracker-first", "Checks the tracker first", EP1, "Before planning, reads the tracker.", 0.7,
         ["alpha-tool", "beta-project"])
    # The same conversation read again (a re-staged episode) is still one conversation: nothing new is written.
    again = skill_grounding.ground([SKILL], [], _one_conversation(EP1), bank)
    assert again == skill_grounding.SkillPlan()


def test_a_held_skill_seen_again_in_a_later_batch_gets_its_page_citing_both(tmp_path):
    from api.services import skill_hold

    bank = _dated_bank(tmp_path)
    _settle(bank, skill_grounding.ground([SKILL], [], _one_conversation(EP1), bank))   # "batch 3"
    # Batches in between that do not show the skill leave the line alone.
    assert skill_grounding.ground([], [], _one_conversation(EP3), bank) == skill_grounding.SkillPlan()
    plan = skill_grounding.ground([SKILL], [], _one_conversation(EP2), bank)            # "batch 9"
    [change] = plan.changes
    assert change["action"] == "create" and change["source_episodes"] == [EP1, EP2]
    assert plan.promoted == ["checks-the-tracker-first"]
    assert _settle(bank, plan) == (0, 1)
    page = _fm(bank, "checks-the-tracker-first")
    fm = page.frontmatter
    assert fm["source_episodes"] == [EP1, EP2]
    assert fm["created"] == "2026-03-02" and fm["last_referenced"] == "2026-03-09"
    assert set(fm["related"]) == {"alpha-tool", "beta-project"}
    records = section_provenance.decode(fm[section_provenance.FIELD])
    rows = [ev for _hash, evs in records["summary"].values() for ev in evs]
    assert {(ev.episode, ev.kind) for ev in rows} == {(EP1, "reasoning"), (EP2, "reasoning")}
    assert skill_hold.load(bank) == []


def test_the_held_batch_s_evidence_pages_are_kept(tmp_path):
    bank = _dated_bank(tmp_path)
    _settle(bank, skill_grounding.ground([SKILL], [], _one_conversation(EP1), bank))
    # The second batch names only one of the two pages; the first batch's other evidence page still gets its edge.
    only_alpha = [{"episode_id": EP2, "entities": [{"name": "Alpha Tool", "type": "tool", "source_episode": EP2,
                                                    "source_episode_timestamp": "2026-03-09T10:00:00+00:00"}]}]
    [change] = skill_grounding.ground([SKILL], [], only_alpha, bank).changes
    assert change["source_episodes"] == [EP1, EP2] and change["evidence_ids"] == ["alpha-tool", "beta-project"]


def _stage2_line(bank, kind="concept"):
    from api.services import pending_store

    line = pending_store.PendingEntity(
        name="Checks the tracker first", type=kind, description="Read about it once.", source_episode=EP3,
        confidence=0.4, tags=["reading"], history_entries=[{"date": "2026-03-10", "entry": "Read a guide."}])
    pending_store.upsert(bank, line)
    return pending_store.load(bank)


def test_a_stage_one_line_of_the_same_name_neither_counts_nor_is_consumed(tmp_path):
    """Review B2: a skill never takes a line Stage 2 parked — its history, description and tags stay where they
    are, for Stage 2's own promotion — and a name heard is not the pattern seen, so it does not count."""
    from api.services import pending_store

    bank = _dated_bank(tmp_path)
    for kind in ("concept", "skill"):
        before = _stage2_line(bank, kind)
        plan = skill_grounding.ground([SKILL], [], _one_conversation(EP1), bank)
        assert plan.changes == [] and [h.source_episode for h in plan.held] == [EP1]
        _settle(bank, plan)
        assert pending_store.load(bank) == before
        _settle(bank, skill_grounding.ground([SKILL], [], _one_conversation(EP2), bank))
        assert pending_store.load(bank) == before
        assert _fm(bank, "checks-the-tracker-first").frontmatter["source_episodes"] == [EP1, EP2]
        (bank / "entities" / "checks-the-tracker-first.md").unlink()
        pending_store.save(bank, [])


def test_stage_two_never_sees_a_held_skill(tmp_path, monkeypatch):
    """Review B1: Stage 2 promotes any pending line a Stage-1 entity repeats, under that entity's type. A held skill
    is not on its store, so a concept of the same name in another conversation stays a first mention there, and the
    skill — still held — gets its own page when Stage 4 grounds it again."""
    from types import SimpleNamespace

    from api.services import entity_resolver, pending_store, skill_hold

    bank = _dated_bank(tmp_path)
    _settle(bank, skill_grounding.ground([SKILL], [], _one_conversation(EP1), bank))

    class _Indexer:   # the real pending store behind Stage 2, no embedding
        def __init__(self, *_a, **_k):
            pass

        def pending_by_name(self, name):
            return next((e for e in pending_store.load(bank) if e.name.lower() == name.lower()), None)

        def index_pending_entity(self, entity):
            pending_store.upsert(bank, entity)

        def promote_from_pending(self, name):
            return pending_store.take(bank, name)[0]

        def rebuild_pending_index(self):
            return 0

    async def no_judge(**_kw):
        return None

    monkeypatch.setattr(entity_resolver, "SqliteVecIndexer", _Indexer)
    monkeypatch.setattr(entity_resolver, "_find_llm_candidate_match", no_judge)
    settings = SimpleNamespace(memory_path=bank, litellm_model="m", litellm_disambiguation_model="m",
                               sleep_promotion_threshold=2)
    stage1 = [{"episode_id": EP2, "entities": [{"name": "Checks the tracker first", "type": "concept",
                                                 "confidence": 0.8, "source_episode": EP2,
                                                 "source_episode_timestamp": "2026-03-09T10:00:00+00:00",
                                                 "description": "a technique"}], "relationships": []}]
    resolved = asyncio.run(entity_resolver.resolve(stage1, [], settings))
    assert resolved["changes"] == []                                   # no concept page made of the skill
    assert [line.source_episode for line in skill_hold.load(bank)] == [EP1]
    plan = skill_grounding.ground([SKILL], resolved["changes"], _one_conversation(EP2), bank)
    assert [(c["action"], c["source_episodes"]) for c in plan.changes] == [("create", [EP1, EP2])]


def test_a_held_conversation_no_longer_in_the_bank_is_no_evidence(tmp_path):
    from api.services import skill_hold

    bank = _dated_bank(tmp_path)
    skill_hold.settle(bank, [skill_hold.HeldSkill("Checks the tracker first", "Old.", 0.4, "ep_2026-01-01_9")], [])
    plan = skill_grounding.ground([SKILL], [], _one_conversation(EP1), bank)
    assert plan.changes == [] and [h.source_episode for h in plan.held] == [EP1]
    _settle(bank, plan)
    assert [line.source_episode for line in skill_hold.load(bank)] == [EP1]


def test_an_existing_skill_page_found_in_one_conversation_is_still_updated(tmp_path):
    bank = _dated_bank(tmp_path)
    markdown_parser.write(bank / "entities" / "checks-the-tracker-first.md",
                          {"name": "Checks the tracker first", "type": "skill", "status": "active",
                           "confidence": 0.5, "source_episodes": [EP1], "version": 1},
                          "Before planning, reads the tracker.\n")
    plan = skill_grounding.ground([SKILL], [], _one_conversation(EP2), bank)
    assert [(c["action"], c["source_episodes"]) for c in plan.changes] == [("update", [EP2])]
    assert plan.held == [] and plan.promoted == []
    _settle(bank, plan)
    assert _fm(bank, "checks-the-tracker-first").frontmatter["source_episodes"] == [EP1, EP2]


def test_a_held_skill_whose_page_appeared_meanwhile_joins_it(tmp_path):
    """A skill page another writer made after the hold (Stage 1 with type skill): the held conversation is added to
    the update and the line leaves — nothing held is lost."""
    from api.services import skill_hold

    bank = _dated_bank(tmp_path)
    _settle(bank, skill_grounding.ground([SKILL], [], _one_conversation(EP1), bank))
    markdown_parser.write(bank / "entities" / "checks-the-tracker-first.md",
                          {"name": "Checks the tracker first", "type": "skill", "status": "active",
                           "confidence": 0.5, "source_episodes": [EP3], "version": 1}, "Mine.\n")
    plan = skill_grounding.ground([SKILL], [], _one_conversation(EP2), bank)
    assert [(c["action"], c["source_episodes"]) for c in plan.changes] == [("update", [EP1, EP2])]
    assert _settle(bank, plan) == (0, 1) and skill_hold.load(bank) == []


def test_the_hold_file_round_trips_and_skips_junk(tmp_path):
    from api.services import skill_hold

    (tmp_path / skill_hold.HOLD_FILE).write_text('not json\n{"name": ""}\n', encoding="utf-8")
    assert skill_hold.load(tmp_path) == []
    held = skill_hold.HeldSkill("Ünïcode habit", "Désc.", 0.6, EP1, ["alpha-tool"])
    assert skill_hold.settle(tmp_path, [held], []) == (1, 0)
    assert skill_hold.load(tmp_path) == [held]
    assert skill_hold.settle(tmp_path, [], ["nobody"]) == (0, 0)
    assert skill_hold.settle(tmp_path, [], [held.slug]) == (0, 1) and skill_hold.load(tmp_path) == []
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
