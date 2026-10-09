"""Page quality (owner 2026-10-09: "the markdowns of each page are too short and some saved facts are useless").

Pins the measured promotion bar (`promotion`), restatement folding (`fact_policy`), displaced orientations kept as
Key Facts instead of "Undated background", the legacy synthesis path that no longer drops the extraction's facts,
the re-read gate, the opt-in synthesis's restated/covered lists and the dry-run-first prose repair. Synthetic
names and conversations only; no model is called.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from types import SimpleNamespace

import pytest

from api.config import Settings
from api.services import (conflict_resolver as cr, entity_body as body, entity_extractor as ex,
                          entity_orientation as orientation, entity_resolver as er, fact_policy, markdown_parser as md,
                          page_quality_repair as repair, pending_store, promotion, section_provenance as sp,
                          summary_policy)

EP_A, EP_B = "ep_2026-03-02_001", "ep_2026-04-10_001"


# --------------------------------------------------------------------------- fact_policy

def test_only_a_word_for_word_restatement_folds():
    assert fact_policy.restates("Bob Example lives in Lisbon.", "Bob Example lives in Lisbon, Portugal.")
    assert fact_policy.restates("Alice reports to Bob.", "Since May 2026, Alice reports to Bob.")
    assert fact_policy.restates("Forge CI runs alpha-project's tests.", "Forge CI runs alpha-project's tests on every push.")
    # A paraphrase is kept: a duplicate is cheaper than a lost fact.
    assert not fact_policy.restates("Forge CI is a CI platform.", "Forge CI is a CI/CD automation platform.")
    assert not fact_policy.restates("Lisbon.", "Bob lives in Lisbon.")  # one content word is never swallowed


# Review of e33f1f93 (blocker 1): each incoming fact says something its page item does not.
CHANGED = [
    ("alpha-project launched in May 2026.", "alpha-project will launch in May 2026."),
    ("Bob Example works at Acme.", "Bob Example previously worked at Acme."),
    ("Bob Example prefers tea over coffee.", "Bob Example prefers coffee over tea."),
    ("alpha-project does not use Docker.", "alpha-project does not use Kubernetes; it uses Docker instead."),
    ("alpha-project has 1,200 GitHub stars.", "alpha-project has 1 maintainer and 200 GitHub stars."),
    ("Lives in Berlin.", "Formerly lived in Berlin."),
    ("Uses Docker for deployment.", "Stopped using Docker for deployment."),
    ("Is CTO of Acme.", "Was CTO of Acme."),
    ("Moved to Berlin in 2026.", "Moving to Berlin in 2026."),
    ("Budget is 5,000 euros.", "Budget is 5,000,000 euros."),
    ("Alice reports to Bob.", "Bob reports to Alice."),
    ("alice reports to bob.", "bob reports to alice."),
    ("Depends on beta-lib.", "beta-lib depends on it."),
    ("Price is 50 dollars.", "Price rose from 50 dollars to 80 dollars."),
    ("Approved the budget.", "Not yet approved the budget; Bob approved the budget."),
    ("Bob uses Docker.", "Bob does not use Docker."),
    ("beta-app had 12 testers in May 2026.", "beta-app had 12 testers in June 2026."),
]


@pytest.mark.parametrize("incoming, existing", CHANGED)
def test_a_fact_that_says_something_different_is_never_folded(incoming, existing):
    assert not fact_policy.restates(incoming, existing)
    assert fact_policy.union([existing], [incoming])[0] == [existing, incoming]


@pytest.mark.parametrize("incoming, existing", CHANGED)
def test_every_changed_fact_reaches_the_page_through_the_writer(tmp_path, incoming, existing):
    (tmp_path / "entities").mkdir()
    path = tmp_path / "entities" / "alpha-project.md"
    md.write(path, {"name": "alpha-project", "type": "project", "source_episodes": [EP_A]},
             f"## Summary\nalpha-project is a project.\n\n## Key Facts\n- {existing}")
    cr.apply_changes([{"id": "alpha-project", "action": "update", "source_episodes": [EP_B],
                       "entity": {"name": "alpha-project", "type": "project", "summary": "", "key_facts": [incoming]}}],
                     tmp_path)
    assert body._bullet_lines(body.parse_sections(md.parse(path).body)["Key Facts"]) == [existing, incoming]


def test_the_fold_keeps_the_extractions_current_fact_beside_an_older_one():
    merged = er._merge_entity_payload(
        {"name": "alpha-project", "summary": "alpha-project is a project.",
         "key_facts": ["alpha-project launched in May 2026.", "Bob Example works at Acme."]},
        {"name": "alpha-project", "summary": "",
         "key_facts": ["alpha-project will launch in May 2026.", "Bob Example previously worked at Acme."]})
    assert merged["key_facts"] == ["alpha-project launched in May 2026.", "Bob Example works at Acme.",
                                   "alpha-project will launch in May 2026.", "Bob Example previously worked at Acme."]


def test_a_reread_that_changes_a_status_is_something_new():
    page = "## Summary\nalpha-project will launch in May 2026."
    assert body.adds_orientation(page, "alpha-project launched in May 2026.", names=["alpha-project"])
    assert not body.adds_orientation(page, "alpha-project will launch in May 2026.", names=["alpha-project"])


def test_union_keeps_every_existing_item_and_the_more_specific_incoming_one():
    existing = ["Bob lives in Lisbon.", "bob lives in lisbon"]  # never touched, even an exact repeat
    items, folded = fact_policy.union(existing, ["Bob lives in Lisbon.", "Bob studied with Alex.",
                                                 "Bob studied with Alex at university."])
    assert items == existing + ["Bob studied with Alex at university."]
    assert folded == 2


def test_sentences_keep_abbreviations_versions_and_lowercase_names():
    assert fact_policy.sentences("beta-app is a tracker. It stores e.g. notes in v2.1 files. alpha-project uses it.") == [
        "beta-app is a tracker.", "It stores e.g. notes in v2.1 files.", "alpha-project uses it."]


@pytest.mark.parametrize("fact, narration", [
    ("Forge CI was mentioned in a conversation.", True),
    ("Forge CI was discussed in the conversation.", True),
    ("It was brought up in a conversation.", True),
    ("Forge CI was discussed in a conversation about pricing.", False),
    ("Forge CI runs alpha-project's tests.", False),
    # Review of e33f1f93 (blocker 2): a clause with content is never narration.
    ("Moving to Berlin in March 2027 was discussed in a conversation.", False),
    ("A 20% budget cut for alpha-project was raised during a discussion.", False),
    ("The decision to sell the company for $2M was discussed in the session.", False),
])
def test_only_a_fact_whose_subject_is_the_thing_and_that_just_says_it_came_up_is_narration(fact, narration):
    assert fact_policy.about_the_conversation(fact, ["Forge CI", "forge"]) is narration


# --------------------------------------------------------------------------- entity_body

def test_a_restated_incoming_fact_is_folded_and_an_existing_one_is_never_removed():
    merged = body._merge_facts("- Forge CI runs alpha-project's tests on every push.\n- Forge CI is a CI platform.",
                               ["Forge CI runs alpha-project's tests.", "Free tier: 2,000 minutes."])
    assert merged.splitlines() == ["- Forge CI runs alpha-project's tests on every push.",
                                   "- Forge CI is a CI platform.", "- Free tier: 2,000 minutes."]


def test_an_incoming_orientation_beside_a_usable_summary_becomes_a_fact_not_background():
    sections = body.merge_sections_fallback(
        {"Summary": "Forge CI is a CI platform.", "Key Facts": "- Forge CI runs alpha-project's tests."},
        {"name": "Forge CI", "summary": "Forge CI runs alpha-project's tests. "
                                        "Its free tier covers 2,000 minutes a month."})
    assert sections["Summary"] == "Forge CI is a CI platform."
    assert "History" not in sections
    # The first sentence is already a Key Fact word for word; the second adds something.
    assert sections["Key Facts"].splitlines() == ["- Forge CI runs alpha-project's tests.",
                                                  "- Its free tier covers 2,000 minutes a month."]


def test_a_summary_that_fits_and_introduces_once_keeps_its_exact_text():
    text = "beta-app is an iOS habit tracker Alex Example builds. It was on TestFlight in May 2026."
    assert body.bound_summary({"Summary": text}, name="beta-app")["Summary"] == text


def test_the_fallback_names_only_what_the_page_knows():
    assert summary_policy.fallback(name="beta-app", entity_type="project") == "beta-app is a project."


# --------------------------------------------------------------------------- promotion

CHAT = ("user: My Forge CI build for alpha-project fails.\n\nassistant: Try parse_manifest in Forge CI.\n\n"
        "user: Still failing.\n\nassistant: Then parse_manifest is not the cause.\n\n"
        "user: Forge CI runs every push.\n\nassistant: Cache it.\n\n"
        "user: And Forge CI caching costs?\n\nassistant: Nothing.\n\n"
        "user: Forge CI it is.\n")


def test_exchanges_are_counted_on_the_conversation_and_only_a_person_names_a_thing():
    units = promotion.exchanges(CHAT)
    assert len(units) == 5
    assert promotion.measure({"name": "Forge CI"}, units) == (4, True)
    assert promotion.measure({"name": "parse_manifest"}, units) == (2, False)
    assert promotion.substantive({"mention_exchanges": 4, "named_by_person": True})
    assert not promotion.substantive({"mention_exchanges": 9, "named_by_person": False})
    assert not promotion.substantive({"mention_exchanges": 3, "named_by_person": True})


def test_a_note_without_turns_is_the_persons_own_writing_one_paragraph_per_exchange():
    note = "Forge CI notes.\n\nForge CI costs.\n\nOther things.\n\nForge CI again.\n\nForge CI done."
    assert promotion.measure({"name": "Forge CI"}, promotion.exchanges(note)) == (4, True)


def test_a_person_first_name_counts_for_a_person_page():
    units = promotion.exchanges("user: Bob is coming.\n\nassistant: Nice.")
    assert promotion.measure({"name": "Bob Example", "type": "person"}, units) == (1, True)


# --------------------------------------------------------------------------- Stage 2

class _Index:
    """The pending store without a vector index."""

    def __init__(self, path):
        self.path = path

    def pending_by_name(self, name):
        return next((e for e in pending_store.load(self.path) if e.name.lower() == name.lower()), None)

    def index_pending_entity(self, entity):
        pending_store.upsert(self.path, entity)

    def promote_from_pending(self, name):
        return pending_store.take(self.path, name)[0]

    def rebuild_pending_index(self):
        return 0


@pytest.fixture
def bank(tmp_path, monkeypatch):
    for name in ("entities", "episodes", "inbox"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    monkeypatch.setattr(er, "SqliteVecIndexer", _Index)

    async def no_judge(*args, **kwargs):
        return "different"
    monkeypatch.setattr(er, "_llm_judge_same_entity", no_judge)
    return tmp_path


def _settings(bank):
    return SimpleNamespace(memory_path=bank, litellm_model="synthetic", litellm_disambiguation_model="",
                           sleep_promotion_threshold=2, sleep_resolve_concurrency=1)


def _git_page():
    return {"id": "git", "frontmatter": {"name": "Git", "type": "tool", "confidence": 0.8}, "body": "## Summary\nGit."}


def _helper(ep=EP_A, **extra):
    entity = {"name": "git-credential-vault", "type": "tool", "confidence": 0.9,
              "summary": "git-credential-vault is a credential helper.",
              "description": "A credential helper the assistant suggested for storing tokens in CI runs. " * 3,
              "key_facts": ["git-credential-vault stores tokens for Git."],
              "history_entries": [{"date": "2026-03-02", "event": "a"}, {"date": "2026-03-02", "event": "b"}],
              "source_episode": ep, "source_episode_timestamp": f"{ep[3:13]}T10:00:00Z",
              "source_episode_day": ep[3:13], "mention_exchanges": 1, "named_by_person": False, **extra}
    sp.attach(entity, ep, "assistant: synthetic")
    return entity


def _link(kind, ep=EP_A):
    return {"source": "git-credential-vault", "target": "Git", "label": "integrates with", "source_episode": ep,
            "evidence": [{"episode": ep, "start": 3, "end": 30, "kind": kind, "hash": "0" * 12}]}


def _resolve(bank, entities, rels, ep=EP_A, existing=None):
    extracted = [{"episode_id": ep, "entities": entities, "relationships": rels}]
    return asyncio.run(er.resolve(extracted, existing if existing is not None else [_git_page()], _settings(bank)))


def test_an_assistant_detail_is_held_with_what_was_said_never_a_page(bank):
    out = _resolve(bank, [_helper()], [_link("assistant")])
    assert not [c for c in out["changes"] if c["action"] == "create"]
    (line,) = pending_store.load(bank)
    assert line.summary == "git-credential-vault is a credential helper."
    assert line.key_facts == ["git-credential-vault stores tokens for Git."]
    assert line.episodes() == [EP_A]
    assert line.item_inputs, "the G118 item records ride along"


def test_a_link_in_the_persons_own_words_promotes_on_one_conversation(bank):
    out = _resolve(bank, [_helper()], [_link("user")])
    assert [c["id"] for c in out["changes"] if c["action"] == "create"] == ["git-credential-vault"]


def test_more_than_three_exchanges_in_the_persons_words_promote(bank):
    out = _resolve(bank, [_helper(mention_exchanges=4, named_by_person=True)], [])
    assert [c["id"] for c in out["changes"] if c["action"] == "create"] == ["git-credential-vault"]


def test_the_same_conversation_read_again_is_not_a_second_one(bank):
    _resolve(bank, [_helper()], [])
    out = _resolve(bank, [_helper(key_facts=["git-credential-vault caches for an hour."])], [])
    assert not [c for c in out["changes"] if c["action"] == "create"]
    (line,) = pending_store.load(bank)
    assert line.key_facts == ["git-credential-vault stores tokens for Git.", "git-credential-vault caches for an hour."]


def test_a_second_conversation_promotes_crediting_both_with_what_each_said(bank):
    _resolve(bank, [_helper()], [])
    out = _resolve(bank, [_helper(ep=EP_B, summary="", description="",
                                  key_facts=["git-credential-vault caches for an hour."])], [], ep=EP_B)
    (create,) = [c for c in out["changes"] if c["action"] == "create"]
    assert sorted(create["source_episodes"]) == [EP_A, EP_B]
    assert "2026-03-02" in create["source_episode_days"]
    facts = create["entity"]["key_facts"]
    assert "git-credential-vault stores tokens for Git." in facts and "git-credential-vault caches for an hour." in facts
    assert create["entity"]["summary"] == "git-credential-vault is a credential helper."


def test_a_folded_summary_that_restates_the_chosen_one_is_not_a_fact():
    merged = er._merge_entity_payload(
        {"name": "Bob Example", "summary": "Bob Example lives in Lisbon with Ana, a friend from university.",
         "key_facts": []},
        {"name": "Bob Example", "summary": "Bob Example lives in Lisbon.", "key_facts": ["Bob Example gets seasick."]})
    assert merged["summary"] == "Bob Example lives in Lisbon with Ana, a friend from university."
    assert merged["key_facts"] == ["Bob Example gets seasick."]


# --------------------------------------------------------------------------- Stage 1

def test_stage_1_measures_each_entity_and_drops_only_narration(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    (tmp_path / "entities").mkdir()
    payload = {"entities": [{"name": "Forge CI", "type": "tool", "summary": "Forge CI is a CI service.",
                             "key_facts": ["Forge CI was mentioned in a conversation.", "Forge CI runs every push."]},
                            {"name": "parse_manifest", "type": "concept", "summary": "A helper.", "key_facts": []}],
               "relationships": []}

    async def fake(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
    monkeypatch.setattr(ex.litellm, "acompletion", fake)
    (out,) = asyncio.run(ex.extract([{"id": EP_A, "content": CHAT, "timestamp": "2026-03-02T10:00:00Z",
                                      "origin": "synthetic"}], Settings(_env_file=None, litellm_model="synthetic")))
    forge, helper = out["entities"]
    assert (forge["mention_exchanges"], forge["named_by_person"]) == (4, True)
    assert forge["key_facts"] == ["Forge CI runs every push."]
    assert (helper["mention_exchanges"], helper["named_by_person"]) == (2, False)


# --------------------------------------------------------------------------- Stage 3 / 5

def _page(tmp_path, facts=("Forge CI runs alpha-project's tests.",), sources=(EP_A,)):
    (tmp_path / "entities").mkdir(exist_ok=True)
    path = tmp_path / "entities" / "forge-ci.md"
    md.write(path, {"name": "Forge CI", "type": "tool", "source_episodes": list(sources), "last_referenced": "2026-03-02"},
             "## Summary\nForge CI is a CI platform.\n\n## Key Facts\n" + "\n".join(f"- {f}" for f in facts))
    page = md.parse(path)
    return path, {"id": "forge-ci", "frontmatter": page.frontmatter, "body": page.body}


def test_legacy_synthesis_never_drops_the_extractions_facts(tmp_path, monkeypatch):
    path, existing = _page(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    incoming = {"name": "Forge CI", "type": "tool", "description": "Forge CI also runs the release job.",
                "key_facts": ["Forge CI's free tier covers 2,000 minutes a month."]}
    prompts = []

    async def fake(**kwargs):
        prompts.append(kwargs["messages"][-1]["content"])
        text = ("## Summary\nForge CI is a CI platform. Forge CI is a CI platform that also runs the release job."
                if "EXISTING PAGE BODY" in prompts[-1] else json.dumps({"has_unresolvable_contradiction": False}))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
    monkeypatch.setattr(cr.litellm, "acompletion", fake)
    change = {"id": "forge-ci", "action": "update", "entity": incoming, "source_episodes": [EP_B]}
    changes = asyncio.run(cr.resolve_and_prune([change], [existing], Settings(_env_file=None), decay=False))
    cr.apply_changes(changes, tmp_path)
    sections = body.parse_sections(md.parse(path).body)
    assert sections["Summary"] == "Forge CI is a CI platform."  # the glued re-introduction left the Summary
    assert sections["Key Facts"].splitlines() == [
        "- Forge CI runs alpha-project's tests.", "- Forge CI's free tier covers 2,000 minutes a month.",
        "- Forge CI is a CI platform that also runs the release job."]


def test_a_reread_that_says_nothing_new_about_it_makes_no_call(tmp_path, monkeypatch):
    _path, existing = _page(tmp_path)
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps({"has_unresolvable_contradiction": False, "summary": "Forge CI is a CI platform."})))])
    monkeypatch.setattr(cr.litellm, "acompletion", fake)
    reread = {"id": "forge-ci", "action": "update", "source_episodes": [EP_A],
              "entity": {"name": "Forge CI", "description": "Forge CI is a CI platform.",
                         "key_facts": ["Forge CI caches dependencies."]}}
    for enabled in (False, True):
        settings = Settings(_env_file=None, summary_synthesis_enabled=enabled)
        out = asyncio.run(cr.resolve_and_prune([dict(reread)], [existing], settings, decay=False))
        assert not calls and not any(c.get("synthesized_body") for c in out)
    # A re-read that says something new about it still gets the merge and the contradiction check.
    news = dict(reread, entity={"name": "Forge CI", "description": "Forge CI moved to self-hosted runners."})
    asyncio.run(cr.resolve_and_prune([news], [existing], Settings(_env_file=None), decay=False))
    assert len(calls) == 2


def test_synthesis_leaves_out_only_what_it_says_the_page_restates_and_shares_a_word_with(tmp_path):
    _path, existing = _page(tmp_path)
    fields = {"name": "Forge CI", "summary": "Forge CI is a hosted CI service.",
              "key_facts": ["Forge CI is a continuous integration platform.", "Forge CI bills per minute."]}
    summary = "Forge CI is the hosted CI service that runs alpha-project's tests."
    # Index 1 shares no word with the page beyond the name: the model's claim is not enough to drop it.
    assert orientation.restated_facts(fields, [0, 1, 7, True], summary, existing["body"]) == {0}
    assert orientation.covered_sentences(existing["body"], fields, [0, 1], summary) == {
        "forge ci is a ci platform.", "forge ci is a hosted ci service."}
    composed = body.parse_sections(orientation.compose(
        existing["body"], fields, summary, restated={0},
        covered={"forge ci is a ci platform.", "forge ci is a hosted ci service."}))
    assert composed["Summary"] == summary
    assert composed["Key Facts"].splitlines() == ["- Forge CI runs alpha-project's tests.", "- Forge CI bills per minute."]


# --------------------------------------------------------------------------- the repair

def _git(path, *args):
    return subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True).stdout


def test_the_repair_counts_first_and_repairs_only_machine_prose_in_one_commit(tmp_path):
    tmp_path = tmp_path / "bank"
    tmp_path.mkdir()
    (tmp_path / "entities").mkdir()
    (tmp_path / "episodes").mkdir()
    md.write(tmp_path / "episodes" / f"{EP_A}.md", {"id": EP_A}, "assistant: parse_manifest reads a file.")
    machine = tmp_path / "entities" / "beta-app.md"
    md.write(machine, {"name": "beta-app", "type": "project", "source_episodes": [EP_A, EP_B]},
             "## Summary\nbeta-app is a project. Its present role for the owner is not established.\n\n"
             "## Key Facts\n- beta-app is built in Swift.\n- beta-app was mentioned in a conversation.\n\n"
             "## History\n- 2026-03-02: Started.\n- Undated background: beta-app is built in Swift. "
             "It was on TestFlight in May 2026.")
    legacy = tmp_path / "entities" / "legacy.md"
    legacy_text = ("## Summary\nlegacy is a tool. Its present role for the owner is not established.\n\n"
                   "## Key Facts\nFree prose a legacy writer left here.\n- legacy was mentioned in a conversation.")
    md.write(legacy, {"name": "legacy", "type": "tool", "source_episodes": [EP_A, EP_B]}, legacy_text)
    human = tmp_path / "entities" / "notes.md"
    human_text = "## Summary\nMine. Its present role for the owner is not established.\n\n## My Notes\nKeep."
    md.write(human, {"name": "notes", "type": "concept", "source_episodes": [EP_A, EP_B]}, human_text)
    one = tmp_path / "entities" / "parse_manifest.md"
    md.write(one, {"name": "parse_manifest", "type": "concept", "source_episodes": [EP_A], "confidence": 0.9},
             "## Summary\n" + "parse_manifest is a helper in the assistant's code example. " * 4)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Synthetic")
    _git(tmp_path, "config", "user.email", "synthetic@example.com")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "seed")
    before, human_before = machine.read_text(), human.read_text()

    counts = repair.survey(tmp_path).counts()
    assert machine.read_text() == before, "the dry run writes nothing"
    assert counts["one_conversation"] == 1 and counts["one_conversation_below_bar"] == 1
    assert counts["old_rung_confident_long"] == 1, "the old proxy let it through; the measured bar does not"
    assert counts["summary_fallback_clause"] == 1 and counts["background_bullets"] == 1
    assert counts["background_to_facts"] == 1 and counts["facts_about_the_conversation"] == 1
    assert counts["human_pages"] == 1 and counts["pages_to_repair"] == 2  # the helper's Summary repeats itself
    assert counts["skipped_free_prose"] == 1
    assert "beta-app" not in json.dumps(counts)

    result = repair.apply(tmp_path, sleep_running=lambda: False)
    assert result.repaired == 2 and result.committed
    sections = body.parse_sections(md.parse(machine).body)
    assert sections["Summary"] == "beta-app is a project."
    assert sections["Key Facts"].splitlines() == ["- beta-app is built in Swift.", "- It was on TestFlight in May 2026."]
    assert sections["History"] == "- 2026-03-02: Started."
    assert human.read_text() == human_before, "a page with human prose is never repaired"
    assert "Free prose a legacy writer left here." in legacy.read_text(), "free prose in a list is never rebuilt away"
    assert _git(tmp_path, "status", "--porcelain") == ""
    assert len(_git(tmp_path, "log", "--format=%H").split()) == 2


def test_the_repair_is_refused_while_sleep_runs(tmp_path):
    (tmp_path / "entities").mkdir()
    with pytest.raises(repair.SleepRunning):
        repair.apply(tmp_path, sleep_running=lambda: True)


# --------------------------------------------------------------------------- a promoted line leaves only with its page

def test_a_promoted_pending_line_survives_a_cancel_and_leaves_once_its_page_is_written(tmp_path, monkeypatch):
    from api.services import sleep_cycle
    from api.tests.test_sleep_cycle_hold import _bank, _entity, _episode, _patch, _settings

    memory = _bank(tmp_path)
    ts_a, ts_b = "2026-03-02T10:00:00+00:00", "2026-04-10T10:00:00+00:00"
    first = dict(_entity("Gamma Board", "tool", EP_A, ts_a), key_facts=["Gamma Board has 3 sensors."])
    second = _entity("Gamma Board", "tool", EP_B, ts_b)
    batch = lambda ep, ts, e: [{"episode_id": ep, "episode_timestamp": ts, "origin": "synthetic",
                                "entities": [dict(e)], "relationships": []}]
    _episode(memory, EP_A, ts_a, "user: Gamma Board arrived.\nassistant: Noted.")
    _patch(monkeypatch, [batch(EP_A, ts_a, first), batch(EP_B, ts_b, second), batch(EP_B, ts_b, second)])
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="pq_1"))
    (line,) = pending_store.load(memory)
    assert line.key_facts == ["Gamma Board has 3 sensors."]

    # The second conversation promotes it, but the run is cancelled before Stage 5: the line stays.
    _episode(memory, EP_B, ts_b, "user: Gamma Board again.\nassistant: Good.")
    real_resolve = er.resolve

    async def resolve_then_cancel(*args, **kwargs):
        out = await real_resolve(*args, **kwargs)
        assert out["promoted_pending"] == ["Gamma Board"]
        sleep_cycle.request_cancel()
        return out
    monkeypatch.setattr(er, "resolve", resolve_then_cancel)
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="pq_2"))
    assert [e.key_facts for e in pending_store.load(memory)] == [["Gamma Board has 3 sensors."]]
    assert not (memory / "entities" / "gamma-board.md").exists()

    # Read again: the page carries the first conversation's fact and both credits; then the line leaves.
    monkeypatch.setattr(er, "resolve", real_resolve)
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="pq_3"))
    page = md.parse(memory / "entities" / "gamma-board.md")
    assert "Gamma Board has 3 sensors." in page.body
    assert sorted(page.frontmatter["source_episodes"]) == [EP_A, EP_B]
    assert pending_store.load(memory) == []


def test_the_repair_never_removes_a_bullet_with_content(tmp_path):
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    page = bank / "entities" / "bob-example.md"
    kept = ["Moving to Berlin in March 2027 was discussed in a conversation.",
            "A 20% budget cut for alpha-project was raised during a discussion.",
            "The decision to sell the company for $2M was discussed in the session."]
    md.write(page, {"name": "Bob Example", "type": "person", "source_episodes": [EP_A, EP_B]},
             "## Summary\nBob Example is a friend.\n\n## Key Facts\n" + "\n".join(f"- {f}" for f in kept)
             + "\n- Bob Example was mentioned in a conversation.")
    result = repair.apply(bank, sleep_running=lambda: False)
    assert result.repaired == 1 and result.facts_about_the_conversation == 1
    assert body._bullet_lines(body.parse_sections(md.parse(page).body)["Key Facts"]) == kept
