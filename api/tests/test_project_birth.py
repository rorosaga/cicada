"""A project page is born from a repository or the person's own words, never from consolidation alone (G141, TODO
ruling 36 D4; `project_birth`, `project_sections`)."""
from __future__ import annotations

import asyncio
import json

import pytest

from api.scripts import project_origins_dry_run
from api.services import (conflict_resolver, entity_resolver, evidence, folder_source, markdown_parser, pending_store,
                          project_birth, project_timeline, workspace_identity)
from api.tests.test_sleep_cycle_hold import _bank, _entity, _settings

EP_A, TS_A = "ep_2026-10-20_001", "2026-10-20T10:00:00+00:00"
EP_B, TS_B = "ep_2026-10-21_001", "2026-10-21T10:00:00+00:00"
REPO_DIR = "/home/someone/code/alpha-project"


def _observed(cwd: str) -> dict:
    """What the hook's D2 observation leaves in an episode: hashes and a time, bound to the stored cwd."""
    return {"cwd_hash": workspace_identity.digest(cwd), "family_hash": "a" * 16, "checkout_hash": "b" * 16,
            "observed_at": "2026-10-20T10:00:00+00:00"}


def _repo_episode_fm(cwd: str = REPO_DIR) -> dict:
    return {"id": EP_A, "source": "claude-code", "harness": "claude-code", "timestamp": TS_A, "project_dir": cwd,
            "workspace_identity": _observed(cwd)}


# --- the rule, on its own ------------------------------------------------------------------------------------------


def test_a_repository_is_named_by_its_folder_or_the_folder_above_a_worktree():
    assert project_birth.repo_names("/home/someone/code/alpha-project") == ["alpha-project"]
    assert project_birth.repo_names("/home/someone/code/alpha-project/.worktrees/fix-x") == ["fix-x", "alpha-project"]
    assert project_birth.repo_names("relative/path") == [] and project_birth.repo_names(None) == []


def test_a_harness_session_in_a_checkout_of_that_name_is_a_repository_origin():
    entity = {"name": "Alpha Project", "type": "project"}
    assert project_birth.repo_match(entity, _repo_episode_fm()) == {"name": "alpha-project", "family": "a" * 16}
    worktree = REPO_DIR + "/.worktrees/fix-x"
    assert project_birth.repo_match(entity, _repo_episode_fm(worktree))["name"] == "alpha-project"


@pytest.mark.parametrize("fm", [
    {"project_dir": REPO_DIR},                                                          # no observation
    {"project_dir": REPO_DIR, "workspace_identity": {**_observed(REPO_DIR), "family_hash": None,
                                                     "checkout_hash": None}},           # a failed observation
    {"project_dir": REPO_DIR, "workspace_identity": _observed("/elsewhere")},           # bound to another cwd
    {"project_dir": "/home/someone/code/beta", "workspace_identity": _observed("/home/someone/code/beta")},  # other name
])
def test_no_observed_checkout_of_that_name_is_no_repository(fm):
    assert project_birth.repo_match({"name": "Alpha Project", "type": "project"}, fm) is None


def test_the_persons_sentence_calling_it_a_project_is_located_as_a_span():
    text = ("user: I keep coming back to the garden.\n"
            "assistant: The garden-plan project could track the beds.\n"
            "user: Yes, let's make garden-plan my project for the spring.\n")
    span = project_birth.said_project({"name": "Garden-plan"}, text)
    assert span is not None and span.kind == "user"
    assert text[span.start:span.end] == "Yes, let's make garden-plan my project for the spring."
    assert span.hash == evidence.body_hash(text)


@pytest.mark.parametrize("text", [
    "assistant: Your garden-plan project is a nice idea.\n",              # only the model said it
    "user: garden-plan came up again today.\n",                          # named, never called a project
    "user: garden-plan is fine, and separately the project at work moved to a new building next month.\n",  # far apart
    "user: I tried gardenplanner, a project tool.\n",                    # a longer word, not the name
])
def test_anything_else_is_not_the_persons_words_calling_it_a_project(text):
    assert project_birth.said_project({"name": "garden-plan"}, text) is None


def test_other_languages_count():
    assert project_birth.said_project({"name": "Huerta"}, "user: El proyecto Huerta empieza en marzo.\n") is not None


# --- Stage 2's gate ------------------------------------------------------------------------------------------------


def _project(name: str, ep: str, ts: str, **extra) -> dict:
    entity = _entity(name, "project", ep, ts)
    # Over every bar of the ordinary rule: substantive in one conversation.
    entity.update(confidence=0.99, description="Discussed at length. " * 12, mention_exchanges=5, named_by_person=True,
                  **extra)
    return entity


def _resolve(memory, extracted, monkeypatch):
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    return asyncio.run(entity_resolver.resolve(extracted, [], _settings(memory)))


def test_consolidation_alone_never_mints_a_project_even_over_two_conversations(tmp_path, monkeypatch):
    """Owner 2026-10-23: no project page without a birth — over the bar it is a fallback concept page instead."""
    memory = _bank(tmp_path)
    extracted = [{"episode_id": EP_A, "entities": [_project("Delta Plan", EP_A, TS_A)], "relationships": []},
                 {"episode_id": EP_B, "entities": [_project("Delta Plan", EP_B, TS_B)], "relationships": []}]
    out = _resolve(memory, extracted, monkeypatch)
    creates = [c for c in out["changes"] if c["action"] == "create"]
    assert [(c["id"], c["entity"]["type"], c.get(project_birth.PROPOSED_KEY), c.get("project_birth"))
            for c in creates] == [("delta-plan", "concept", "project", None)]


def test_a_concept_on_the_same_evidence_still_gets_its_page(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    concept = _project("Delta Plan", EP_A, TS_A)
    concept["type"] = "concept"
    out = _resolve(memory, [{"episode_id": EP_A, "entities": [concept], "relationships": []}], monkeypatch)
    assert [(c["action"], c["id"]) for c in out["changes"]] == [("create", "delta-plan")]


@pytest.mark.parametrize("born", [
    {"origin": "repo", "day": "2026-10-20", "episode": EP_A, "repo": {"name": "delta-plan", "family": "a" * 16}},
    {"origin": "words", "day": "2026-10-20", "episode": EP_A, "span": {"start": 6, "end": 40, "hash": "x", "kind": "user"}},
])
def test_a_birth_record_mints_the_page_and_stage_5_writes_it_once(tmp_path, monkeypatch, born):
    memory = _bank(tmp_path)
    entity = _entity("Delta Plan", "project", EP_A, TS_A)   # one plain mention: the origin alone is enough
    entity["project_birth"] = born
    out = _resolve(memory, [{"episode_id": EP_A, "entities": [entity], "relationships": []}], monkeypatch)
    (change,) = out["changes"]
    assert (change["action"], change["id"], change["project_birth"]) == ("create", "delta-plan", born)
    conflict_resolver.apply_changes([change], memory)
    fm = markdown_parser.parse(memory / "entities" / "delta-plan.md").frontmatter
    assert fm["born"] == born


def test_a_folder_the_person_named_is_born_from_their_words(tmp_path):
    memory = _bank(tmp_path)
    eid, created = folder_source.ensure_project(memory, "Notes Garden", path="/x/notes", device="box")
    fm = markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter
    assert created and fm["born"]["origin"] == "words" and fm["born"]["via"] == "folder"


# --- extraction reads both origins from the conversation ------------------------------------------------------------


def test_at_extraction_prefers_the_repository_and_falls_back_to_the_words():
    text = "user: alpha-project is my project now.\n"
    repo = project_birth.at_extraction({"name": "alpha-project"}, episode_id=EP_A, frontmatter=_repo_episode_fm(),
                                       text=text, day="2026-10-20")
    assert repo["origin"] == "repo" and repo["repo"]["name"] == "alpha-project" and repo["day"] == "2026-10-20"
    words = project_birth.at_extraction({"name": "alpha-project"}, episode_id=EP_A, frontmatter={}, text=text,
                                        day="2026-10-20")
    assert words["origin"] == "words" and text[words["span"]["start"]:words["span"]["end"]] == \
        "alpha-project is my project now."
    assert project_birth.at_extraction({"name": "alpha-project"}, episode_id=EP_A, frontmatter={},
                                       text="user: alpha-project again.\n", day=None) is None


# --- reading it back: classify, the wire, the dry run --------------------------------------------------------------


def _write_episode(memory, ep, ts, body, **fm):
    markdown_parser.write(memory / "episodes" / f"{ep}.md", {"id": ep, "processed": True, "source": "claude-code",
                                                              "timestamp": ts, **fm}, body)


def _write_project(memory, eid, name, episodes, **fm):
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"name": name, "type": "project", "status": "active", "confidence": 0.8,
                           "created": "2026-10-20", "source_episodes": episodes, **fm},
                          f"## Summary\n{name} is a project.\n\n## Design\nWarm colours, one column.\n")


def _three_projects(memory):
    _write_episode(memory, EP_A, TS_A, "user: let's fix the parser.\nassistant: Done.\n",
                   project_dir=REPO_DIR, workspace_identity=_observed(REPO_DIR))
    _write_episode(memory, EP_B, TS_B, "user: The garden-plan project starts in spring.\n"
                                       "user: Also delta plan came up.\n")
    _write_project(memory, "alpha-project", "Alpha Project", [EP_A])
    _write_project(memory, "garden-plan", "Garden-plan", [EP_B])
    _write_project(memory, "delta-plan", "Delta Plan", [EP_A, EP_B])


def test_classify_derives_each_origin_and_says_why(tmp_path):
    memory = _bank(tmp_path)
    _three_projects(memory)
    by = {r["id"]: r for r in project_origins_dry_run.survey(memory, quotes=True)}
    assert (by["alpha-project"]["origin"], by["alpha-project"]["repo"]) == ("repo", "alpha-project")
    assert by["garden-plan"]["origin"] == "words" and by["garden-plan"]["quote"] == \
        "The garden-plan project starts in spring."
    assert by["delta-plan"]["origin"] == "neither" and "consolidation alone" in by["delta-plan"]["why"]
    assert not any(r["stored"] for r in by.values())


def test_the_dry_run_writes_nothing(tmp_path, capsys):
    memory = _bank(tmp_path)
    _three_projects(memory)
    before = {p: p.read_bytes() for p in memory.rglob("*") if p.is_file()}
    assert project_origins_dry_run.main(["--bank", str(memory), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"] == {"repo": 1, "words": 1, "neither": 1}
    assert {p: p.read_bytes() for p in memory.rglob("*") if p.is_file()} == before


def test_a_declared_repository_and_a_stored_birth_answer_without_reading_a_conversation(tmp_path):
    memory = _bank(tmp_path)
    _write_project(memory, "omega", "Omega", ["ep_2099-01-01_001"], repos=[{"path": "/x/omega"}])
    _write_project(memory, "sigma", "Sigma", [], born={"origin": "words", "day": "2026-10-01", "episode": EP_B})
    never = lambda ep: pytest.fail("no conversation is read")  # noqa: E731
    omega = project_birth.classify(memory, "omega", markdown_parser.parse(memory / "entities/omega.md").frontmatter,
                                   documents=never)
    sigma = project_birth.classify(memory, "sigma", markdown_parser.parse(memory / "entities/sigma.md").frontmatter,
                                   documents=never)
    assert (omega.kind, omega.via, sigma.kind, sigma.stored, sigma.day) == ("repo", "declared", "words", True,
                                                                             "2026-10-01")


def test_the_timeline_wire_carries_origin_sections_and_people(tmp_path):
    memory = _bank(tmp_path)
    _three_projects(memory)
    tl = project_timeline.build(memory, "garden-plan", tz_name="UTC")
    wire = tl.model_dump(by_alias=True)
    assert wire["origin"]["kind"] == "words" and wire["origin"]["quote"] == "The garden-plan project starts in spring."
    assert [s["key"] for s in wire["sections"]] == ["overview", "timeline", "done", "expected", "design", "people"]
    design = next(s for s in wire["sections"] if s["key"] == "design")
    assert design["markdown"] == "Warm colours, one column." and "design_refs" in design["writtenBy"]
    assert wire["people"] == []
    rows = {r.id: r.origin for r in project_timeline.list_projects(memory, tz_name="UTC").projects}
    assert rows == {"alpha-project": None, "garden-plan": None, "delta-plan": None}   # nothing stored yet


# --- benchmarks/newuser follow-up (2026-10-22): W2, W3, W4 ---------------------------------------------------------

_BORN = {"origin": "words", "day": "2026-10-20", "episode": EP_A, "span": {"start": 0, "end": 1, "hash": "x",
                                                                          "kind": "user"}}


def _project_page(eid: str, name: str, aliases=()) -> dict:
    return {"id": eid, "frontmatter": {"name": name, "type": "project", "status": "active", "confidence": 0.8,
                                       "born": _BORN, **({"aliases": list(aliases)} if aliases else {})},
            "body": f"## Summary\n{name} is a synthetic project."}


def _resolve_with(memory, extracted, pages, monkeypatch, verdict="different"):
    async def judge(*_a, **_k):
        return verdict

    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        return [verdict for _ in entries]
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    monkeypatch.setattr(entity_resolver, "_llm_judge_same_entity", judge)
    monkeypatch.setattr(entity_resolver, "_llm_judge_batch", batch)
    return asyncio.run(entity_resolver.resolve(extracted, pages, _settings(memory)))


def test_w2_an_alias_brings_the_project_page_to_the_judge_who_decides(tmp_path, monkeypatch):
    """A later conversation named the canoe "Hull build" (alias "Cedar canoe"): it shares no word with the page, so
    the judge never saw it, and the mention was held. The alias now brings the page to the judge (owner 2026-10-08:
    "an alias brings its page to the judge, never a decision")."""
    memory = _bank(tmp_path)
    mention = _project("Hull build", EP_B, TS_B, aliases=["Cedar canoe"])
    out = _resolve_with(memory, [{"episode_id": EP_B, "entities": [mention], "relationships": []}],
                        [_project_page("cedar-canoe", "Cedar canoe")], monkeypatch, verdict="same")
    assert [(c["action"], c["id"]) for c in out["changes"]] == [("update", "cedar-canoe")]
    assert out["name_to_id"]["hull build"] == "cedar-canoe"


def test_w2_an_alias_never_overrides_the_judges_different(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    mention = _project("Hull build", EP_B, TS_B, aliases=["Cedar canoe"])
    out = _resolve_with(memory, [{"episode_id": EP_B, "entities": [mention], "relationships": []}],
                        [_project_page("cedar-canoe", "Cedar canoe")], monkeypatch, verdict="different")
    assert not any(c["id"] == "cedar-canoe" for c in out["changes"])
    assert out["name_to_id"].get("hull build") != "cedar-canoe"


def test_w2_an_unsure_judge_asks_the_person(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    mention = _project("Hull build", EP_B, TS_B, aliases=["Cedar canoe"])
    out = _resolve_with(memory, [{"episode_id": EP_B, "entities": [mention], "relationships": []}],
                        [_project_page("cedar-canoe", "Cedar canoe")], monkeypatch, verdict="unsure")
    assert out["changes"] == []
    asked = [markdown_parser.parse(p).frontmatter for p in (memory / "inbox").glob("inbox-*.md")]
    assert [(fm["kind"], fm["merge_target_hint"]) for fm in asked] == [("merge_suggestion", "cedar-canoe")]


def test_w2_a_pair_the_person_said_were_different_is_not_brought(tmp_path, monkeypatch):
    from api.services import merge_rejections

    memory = _bank(tmp_path)
    merge_rejections.add_rejected(memory, "hull-build", "cedar-canoe")
    judged = []

    async def judge(*_a, **k):
        judged.append(k.get("existing_name"))
        return "same"
    monkeypatch.setattr(entity_resolver, "_llm_judge_same_entity", judge)
    mention = _project("Hull build", EP_B, TS_B, aliases=["Cedar canoe"])
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    out = asyncio.run(entity_resolver.resolve([{"episode_id": EP_B, "entities": [mention], "relationships": []}],
                                              [_project_page("cedar-canoe", "Cedar canoe")], _settings(memory)))
    assert judged == [] and not any(c["id"] == "cedar-canoe" for c in out["changes"])


def test_w2_a_project_mention_judged_the_same_as_a_project_page_updates_it(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    mention = _project("Canoe", EP_B, TS_B)
    out = _resolve_with(memory, [{"episode_id": EP_B, "entities": [mention], "relationships": []}],
                        [_project_page("cedar-canoe", "Cedar canoe")], monkeypatch, verdict="same")
    assert [(c["action"], c["id"]) for c in out["changes"]] == [("update", "cedar-canoe")]


def test_w2_an_alias_naming_two_project_pages_updates_neither(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    mention = _project("Hull build", EP_B, TS_B, aliases=["Cedar canoe", "Oak canoe"])
    out = _resolve_with(memory, [{"episode_id": EP_B, "entities": [mention], "relationships": []}],
                        [_project_page("cedar-canoe", "Cedar canoe"), _project_page("oak-canoe", "Oak canoe")],
                        monkeypatch)
    assert not any(c["id"] in ("cedar-canoe", "oak-canoe") for c in out["changes"])
    # Substantive on its own, it is a page of its own — a fallback concept, never a project with no birth.
    assert [(c["action"], c["entity"]["type"]) for c in out["changes"]] == [("create", "concept")]


@pytest.mark.parametrize("text", [
    "user: New project with Teo: fernpost, a tiny web app for the street.\n",
    "user: My next project: fernpost.\n",
])
def test_w3_a_colon_after_the_project_word_introduces_its_name(text):
    span = project_birth.said_project({"name": "fernpost"}, text)
    assert span is not None and span.kind == "user"


def test_w3_a_colon_that_starts_a_new_thought_still_does_not(tmp_path):
    text = "user: fernpost: the project at work moved to a new building.\n"
    assert project_birth.said_project({"name": "fernpost"}, text) is None


def test_w4_a_page_written_as_a_project_needs_a_birth_whatever_type_the_chosen_mention_had(tmp_path, monkeypatch):
    """A concept-typed mention and a project-typed one of the same name: the page was written as a project with no
    `born` — the gate read only the mention it chose."""
    memory = _bank(tmp_path)
    concept = _project("Delta Plan", EP_A, TS_A)
    concept["type"] = "concept"
    project = _project("Delta Plan", EP_B, TS_B)
    project["confidence"] = 0.6
    out = _resolve_with(memory, [{"episode_id": EP_A, "entities": [concept], "relationships": []},
                                 {"episode_id": EP_B, "entities": [project], "relationships": []}], [], monkeypatch)
    for change in out["changes"]:
        if change["action"] == "create" and (change["entity"].get("type") or "") == "project":
            assert change.get("project_birth"), "a project page is never written without its birth"


def test_w4_a_birth_on_the_project_sibling_reaches_the_page_the_concept_mention_starts(tmp_path, monkeypatch):
    """The chosen mention is a concept, its project-typed sibling carries the birth: the page is written as a
    project and must carry that `born` (review of #436: the birth was attached only when the chosen mention was)."""
    memory = _bank(tmp_path)
    concept = _project("Delta Plan", EP_A, TS_A)
    concept["type"] = "concept"
    project = _project("Delta Plan", EP_B, TS_B)
    project["confidence"] = 0.6
    project["project_birth"] = {**_BORN, "episode": EP_B, "day": "2026-10-21"}
    out = _resolve_with(memory, [{"episode_id": EP_A, "entities": [concept], "relationships": []},
                                 {"episode_id": EP_B, "entities": [project], "relationships": []}], [], monkeypatch)
    [change] = [c for c in out["changes"] if c["action"] == "create"]
    assert change["entity"]["type"] == "project"
    assert change["project_birth"]["episode"] == EP_B


# --- the fallback page (owner 2026-10-23, amends D4) -----------------------------------------------------------------

EP_C, TS_C = "ep_2026-10-22_001", "2026-10-22T10:00:00+00:00"
EP_D, TS_D = "ep_2026-10-23_001", "2026-10-23T10:00:00+00:00"
CANOE_NAMES = {"cedar-strip canoe", "canoe", "boat hull build", "hull build project", "boat hull"}


def _mention(name: str, ep: str, ts: str, summary: str, **extra) -> dict:
    """One plain project-typed mention, under every bar of the ordinary rule on its own (`_entity`: confidence 0.6,
    not substantive)."""
    entity = _entity(name, "project", ep, ts)
    entity.update(summary=summary, **extra)
    return entity


def _canoe_judge(monkeypatch, judged: list | None = None):
    """The judge: two canoe spellings are the same thing, anything else is different. Records every pair it saw."""
    def same(a: str, b: str) -> str:
        return "same" if a.lower() in CANOE_NAMES and b.lower() in CANOE_NAMES else "different"

    async def judge(*_a, **k):
        if judged is not None:
            judged.append((k["new_name"], k["existing_name"]))
        return same(k["new_name"], k["existing_name"])

    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        if judged is not None:
            judged.extend((new_name, e["name"]) for e in entries)
        return [same(new_name, e["name"]) for e in entries]
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    monkeypatch.setattr(entity_resolver, "_llm_judge_same_entity", judge)
    monkeypatch.setattr(entity_resolver, "_llm_judge_batch", batch)


def _canoe_batch() -> list[dict]:
    """The newuser canoe, shrunk: three conversations, five spellings, never called a project."""
    return [
        {"episode_id": EP_A, "relationships": [], "entities": [
            _mention("Cedar-strip canoe", EP_A, TS_A, "A 15-foot cedar-strip canoe built in the garage."),
            _mention("Canoe", EP_A, TS_A, "The canoe being built this autumn.")]},
        {"episode_id": EP_B, "relationships": [], "entities": [
            _mention("Boat hull build", EP_B, TS_B, "Stripping the hull, 60 percent done."),
            _mention("Hull build project", EP_B, TS_B, "The hull is being stripped a few strips an evening.")]},
        {"episode_id": EP_C, "relationships": [], "entities": [
            _mention("Boat hull", EP_C, TS_C, "The hull is fully stripped and faired."),
            _mention("Garden shed", EP_C, TS_C, "Thinking about a shed some day.")]},
    ]


def _resolve_canoe(memory, extracted, pages, monkeypatch, judged=None):
    _canoe_judge(monkeypatch, judged)
    return asyncio.run(entity_resolver.resolve(extracted, pages, _settings(memory)))


def test_a_thing_never_called_a_project_over_three_conversations_gets_one_concept_page(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    judged: list = []
    out = _resolve_canoe(memory, _canoe_batch(), [], monkeypatch, judged)
    creates = [c for c in out["changes"] if c["action"] == "create"]
    assert len(creates) == 1, [c["id"] for c in creates]
    (page,) = creates
    assert page["entity"]["type"] == "concept" and page[project_birth.PROPOSED_KEY] == "project"
    assert "project_birth" not in page
    # Every spelling lands on the one page, and the page is credited with all three conversations.
    assert {out["name_to_id"][n] for n in CANOE_NAMES} == {page["id"]}
    assert set(page["source_episodes"]) == {EP_A, EP_B, EP_C}
    assert {a.lower() for a in page["entity"]["aliases"]} >= CANOE_NAMES - {page["entity"]["name"].lower()}
    # The judge joined them, never an alias or a shared word: a hull spelling shares no word with a canoe one.
    assert any(("hull" in a.lower()) != ("hull" in b.lower()) for a, b in judged)
    # The one-off beside it stays held.
    assert "garden shed" not in out["name_to_id"]
    held = {line.name for line in pending_store.load(memory)}
    assert "Garden shed" in held and not (held & {"Cedar-strip canoe", "Canoe", "Boat hull build", "Boat hull"})

    conflict_resolver.apply_changes(creates, memory)
    fm = markdown_parser.parse(memory / "entities" / f"{page['id']}.md").frontmatter
    assert (fm["type"], fm[project_birth.PROPOSED_KEY], "born" in fm) == ("concept", "project", False)


def test_a_one_off_never_called_a_project_stays_held(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    out = _resolve_canoe(memory, [{"episode_id": EP_A, "relationships": [], "entities": [
        _mention("Cedar-strip canoe", EP_A, TS_A, "A canoe, said once.")]}], [], monkeypatch)
    assert out["changes"] == []
    assert [line.name for line in pending_store.load(memory)] == ["Cedar-strip canoe"]


def test_two_different_things_are_not_counted_together(tmp_path, monkeypatch):
    """The bar is read over what the judge joins, never over the batch: two one-off things stay two held lines."""
    memory = _bank(tmp_path)
    out = _resolve_canoe(memory, [
        {"episode_id": EP_A, "relationships": [], "entities": [_mention("Garden shed", EP_A, TS_A, "A shed.")]},
        {"episode_id": EP_B, "relationships": [], "entities": [_mention("Canoe", EP_B, TS_B, "A canoe.")]}],
        [], monkeypatch)
    assert out["changes"] == []
    assert {line.name for line in pending_store.load(memory)} == {"Garden shed", "Canoe"}


def test_a_line_an_earlier_batch_parked_joins_the_page(tmp_path, monkeypatch):
    """Batch one held "Boat hull"; batch two says "Canoe" once: judged the same thing, two conversations — one page,
    and the earlier line leaves through Stage 5 (`promoted_pending`)."""
    memory = _bank(tmp_path)
    _resolve_canoe(memory, [{"episode_id": EP_A, "relationships": [], "entities": [
        _mention("Boat hull", EP_A, TS_A, "Stripping the canoe's hull.")]}], [], monkeypatch)
    out = _resolve_canoe(memory, [{"episode_id": EP_B, "relationships": [], "entities": [
        _mention("Canoe", EP_B, TS_B, "The canoe in the garage.")]}], [], monkeypatch)
    (page,) = [c for c in out["changes"] if c["action"] == "create"]
    assert page["entity"]["type"] == "concept" and set(page["source_episodes"]) == {EP_A, EP_B}
    assert out["name_to_id"]["boat hull"] == out["name_to_id"]["canoe"] == page["id"]
    assert "Boat hull" in out["promoted_pending"]


def _write_fallback(memory, monkeypatch) -> dict:
    """The canoe's fallback page on disk, as Stage 5 wrote it from the first test's batch."""
    out = _resolve_canoe(memory, _canoe_batch(), [], monkeypatch)
    creates = [c for c in out["changes"] if c["action"] == "create"]
    conflict_resolver.apply_changes(creates, memory)
    (page,) = creates
    parsed = markdown_parser.parse(memory / "entities" / f"{page['id']}.md")
    return {"id": page["id"], "frontmatter": parsed.frontmatter, "body": parsed.body}


@pytest.fixture
def canoe_page(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    return memory, _write_fallback(memory, monkeypatch)


def test_a_later_mention_lands_on_the_fallback_page_never_a_second_one(canoe_page, monkeypatch):
    memory, page = canoe_page
    out = _resolve_canoe(memory, [{"episode_id": EP_D, "relationships": [], "entities": [
        _mention("Boat hull", EP_D, TS_D, "Glassed the outside of the hull.")]}], [page], monkeypatch)
    assert [(c["action"], c["id"]) for c in out["changes"]] == [("update", page["id"])]
    assert out["changes"][0]["entity"]["type"] == "concept"   # the page keeps its type: no birth yet


def test_my_canoe_project_turns_the_fallback_page_into_the_project_with_born(canoe_page, monkeypatch):
    memory, page = canoe_page
    born = {**_BORN, "episode": EP_D, "day": "2026-10-23"}
    mention = _mention("Canoe", EP_D, TS_D, "My canoe project: glassing the inside next.", project_birth=born)
    out = _resolve_canoe(memory, [{"episode_id": EP_D, "relationships": [], "entities": [mention]}], [page],
                         monkeypatch)
    assert [(c["action"], c["id"]) for c in out["changes"]] == [("update", page["id"])]   # never duplicated
    (change,) = out["changes"]
    assert change["project_birth"] == born and change["entity"]["type"] == "project"
    conflict_resolver.apply_changes([change], memory)
    fm = markdown_parser.parse(memory / "entities" / f"{page['id']}.md").frontmatter
    assert fm["type"] == "project" and fm["born"] == born and project_birth.PROPOSED_KEY not in fm
    assert sorted(p.stem for p in (memory / "entities").glob("*.md")) == [page["id"]]


def test_the_exact_name_with_a_birth_retypes_the_page_too(canoe_page, monkeypatch):
    memory, page = canoe_page
    born = {**_BORN, "episode": EP_D, "day": "2026-10-23"}
    name = page["frontmatter"]["name"]
    mention = _mention(name, EP_D, TS_D, f"The {name} is my project now.", project_birth=born)
    out = _resolve_canoe(memory, [{"episode_id": EP_D, "relationships": [], "entities": [mention]}], [page],
                         monkeypatch)
    (change,) = out["changes"]
    assert (change["action"], change["id"], change["project_birth"]) == ("update", page["id"], born)


def test_a_birth_in_the_same_batch_makes_the_page_a_project_from_the_start(tmp_path, monkeypatch):
    """One canoe spelling carries the person's words: its page is the project with `born` — one page, no fallback."""
    memory = _bank(tmp_path)
    batch = _canoe_batch()
    born = {**_BORN, "episode": EP_C, "day": "2026-10-22"}
    batch[2]["entities"][0]["project_birth"] = born
    out = _resolve_canoe(memory, batch, [], monkeypatch)
    projects = [c for c in out["changes"] if c["action"] == "create" and c["entity"]["type"] == "project"]
    assert [c["project_birth"] for c in projects] == [born]
    assert not any(c.get(project_birth.PROPOSED_KEY) for c in out["changes"])
    assert {out["name_to_id"][n] for n in CANOE_NAMES} == {projects[0]["id"]}   # one page, every spelling on it


def test_retype_on_birth_touches_only_a_fallback_page():
    born = {**_BORN}
    project = {"type": "project", "born": {"origin": "repo"}, project_birth.PROPOSED_KEY: "project"}
    concept = {"type": "concept"}
    tool = {"type": "tool", project_birth.PROPOSED_KEY: "project"}
    for fm in (project, concept, tool):
        before = dict(fm)
        assert project_birth.retype_on_birth(fm, born) is False and fm == before
    fallback = {"type": "concept", project_birth.PROPOSED_KEY: "project"}
    assert project_birth.retype_on_birth(fallback, None) is False
    assert project_birth.retype_on_birth(fallback, born) is True
    assert fallback == {"type": "project", "born": born}


def test_an_existing_project_page_is_never_retyped_or_archived_by_the_fallback(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    page = _project_page("cedar-canoe", "Cedar canoe")
    markdown_parser.write(memory / "entities" / "cedar-canoe.md", page["frontmatter"], page["body"])
    out = _resolve_canoe(memory, _canoe_batch(), [page], monkeypatch)
    conflict_resolver.apply_changes(out["changes"], memory)
    fm = markdown_parser.parse(memory / "entities" / "cedar-canoe.md").frontmatter
    assert (fm["type"], fm["status"], fm["born"]) == ("project", "active", _BORN)


def test_a_held_birth_still_mints_the_project_as_today(tmp_path, monkeypatch):
    """A name parked with no birth, then said in the person's words: the project page, folded with the line."""
    memory = _bank(tmp_path)
    _resolve_canoe(memory, [{"episode_id": EP_A, "relationships": [], "entities": [
        _mention("Delta Plan", EP_A, TS_A, "A plan.")]}], [], monkeypatch)
    born = {**_BORN, "episode": EP_B, "day": "2026-10-21"}
    out = _resolve_canoe(memory, [{"episode_id": EP_B, "relationships": [], "entities": [
        _mention("Delta Plan", EP_B, TS_B, "My Delta Plan project.", project_birth=born)]}], [], monkeypatch)
    (change,) = out["changes"]
    assert (change["action"], change["entity"]["type"], change["project_birth"]) == ("create", "project", born)
    assert set(change["source_episodes"]) == {EP_A, EP_B} and out["promoted_pending"] == ["Delta Plan"]


def _inbox_titles(memory) -> list[str]:
    return sorted(str(markdown_parser.parse(p).frontmatter.get("title", "")) for p in (memory / "inbox").glob("*.md"))


def _resolve_unsure(memory, mention, page, monkeypatch):
    async def unsure(*_a, **_k):
        return "unsure"

    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        return ["unsure" for _ in entries]
    monkeypatch.setattr(entity_resolver, "_llm_judge_same_entity", unsure)
    monkeypatch.setattr(entity_resolver, "_llm_judge_batch", batch)
    return asyncio.run(entity_resolver.resolve([{"episode_id": EP_D, "relationships": [], "entities": [mention]}],
                                               [page], _settings(memory)))


def test_unsure_against_a_page_with_no_shared_word_holds_without_asking(canoe_page, monkeypatch):
    """benchmarks/newuser: "Epoxy & fiberglass workshop" against the canoe's page, unsure. No word or conversation in
    common is no question for the person: the name is held, never a second page, and nothing reaches the inbox."""
    memory, page = canoe_page
    before = _inbox_titles(memory)
    out = _resolve_unsure(memory, _project("Epoxy workshop", EP_D, TS_D), page, monkeypatch)   # over the bar alone
    assert out["changes"] == []
    assert _inbox_titles(memory) == before
    assert "Epoxy workshop" in {line.name for line in pending_store.load(memory)}


def test_unsure_against_a_page_that_shares_a_word_asks(canoe_page, monkeypatch):
    memory, page = canoe_page
    out = _resolve_unsure(memory, _project("Strip canoe trailer", EP_D, TS_D), page, monkeypatch)
    assert out["changes"] == []
    assert any("Strip canoe trailer" in t for t in _inbox_titles(memory))


def _birth_mention(name: str) -> dict:
    return _mention(name, EP_D, TS_D, f"My {name.lower()} project.",
                    project_birth={**_BORN, "episode": EP_D, "day": "2026-10-23"})


@pytest.fixture
def restoration_is_the_canoe():
    CANOE_NAMES.add("canoe restoration")
    yield
    CANOE_NAMES.discard("canoe restoration")


def test_a_birth_spelling_sharing_a_word_only_with_an_alias_retypes_the_page(canoe_page, monkeypatch,
                                                                             restoration_is_the_canoe):
    """Review of #441: the page is named "Hull build project" with "Canoe" among its aliases; "Canoe restoration"
    carries the person's words. It shares no word with the page's name, so the loop's judge never saw the page and a
    second, project page was minted beside it. It is weighed against the fallback pages too: the same page, retyped."""
    memory, page = canoe_page
    assert "canoe" not in page["frontmatter"]["name"].lower()
    assert any("canoe" in a.lower() for a in page["frontmatter"]["aliases"])
    out = _resolve_canoe(memory, [{"episode_id": EP_D, "relationships": [],
                                   "entities": [_birth_mention("Canoe restoration")]}], [page], monkeypatch)
    assert [(c["action"], c["id"]) for c in out["changes"]] == [("update", page["id"])]
    conflict_resolver.apply_changes(out["changes"], memory)
    fm = markdown_parser.parse(memory / "entities" / f"{page['id']}.md").frontmatter
    assert fm["type"] == "project" and fm["born"]["episode"] == EP_D
    assert sorted(p.stem for p in (memory / "entities").glob("*.md")) == [page["id"]]


def test_a_birth_spelling_the_judge_calls_different_is_its_own_project(canoe_page, monkeypatch):
    memory, page = canoe_page
    out = _resolve_canoe(memory, [{"episode_id": EP_D, "relationships": [],
                                   "entities": [_birth_mention("Garden shed")]}], [page], monkeypatch)
    assert [(c["action"], c["entity"]["type"]) for c in out["changes"]] == [("create", "project")]


def test_a_birth_spelling_the_person_said_is_different_is_not_brought(canoe_page, monkeypatch,
                                                                     restoration_is_the_canoe):
    from api.services import merge_rejections

    memory, page = canoe_page
    merge_rejections.add_rejected(memory, "canoe-restoration", page["id"])
    judged: list = []
    out = _resolve_canoe(memory, [{"episode_id": EP_D, "relationships": [],
                                   "entities": [_birth_mention("Canoe restoration")]}], [page], monkeypatch, judged)
    assert not any(b == page["frontmatter"]["name"] for _a, b in judged)
    assert not any(c["id"] == page["id"] for c in out["changes"])

