"""A project page is born from a repository or the person's own words, never from consolidation alone (G141, TODO
ruling 36 D4; `project_birth`, `project_sections`)."""
from __future__ import annotations

import asyncio
import json

import pytest

from api.scripts import project_origins_dry_run
from api.services import (conflict_resolver, entity_resolver, evidence, folder_source, markdown_parser, project_birth,
                          project_timeline, workspace_identity)
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
    memory = _bank(tmp_path)
    extracted = [{"episode_id": EP_A, "entities": [_project("Delta Plan", EP_A, TS_A)], "relationships": []},
                 {"episode_id": EP_B, "entities": [_project("Delta Plan", EP_B, TS_B)], "relationships": []}]
    out = _resolve(memory, extracted, monkeypatch)
    assert [c for c in out["changes"] if c["action"] == "create"] == []


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
    markdown_parser.write(memory / "episodes" / f"{ep}.md", {"id": ep, "processed": True, "source": "mcp",
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


def test_w2_a_project_mention_whose_alias_names_a_project_page_updates_it(tmp_path, monkeypatch):
    """A later conversation named the canoe "Hull build" (alias "Cedar canoe"): with no birth of its own it was held,
    and its news never reached the page the person already had."""
    memory = _bank(tmp_path)
    mention = _project("Hull build", EP_B, TS_B, aliases=["Cedar canoe"])
    out = _resolve_with(memory, [{"episode_id": EP_B, "entities": [mention], "relationships": []}],
                        [_project_page("cedar-canoe", "Cedar canoe")], monkeypatch)
    assert [(c["action"], c["id"]) for c in out["changes"]] == [("update", "cedar-canoe")]
    assert out["name_to_id"]["hull build"] == "cedar-canoe"


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
    assert out["changes"] == []


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
