"""Projects v2 (TODO ruling 45, 2026-10-27): the list is the person's, detected projects are suggested; the person's
description and name; every conversation tied, with why; influences. Synthetic projects only."""
import subprocess
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from _demo_scenario import demo
from api import config, main
from api.routers import projects
from api.services import (bank_index, entity_merge, handshake, markdown_parser, page_edits, project_conversations,
                          project_ownership, project_timeline, search_index)
from api.services.claims import parse_claims


@pytest.fixture
def client(tmp_path, monkeypatch):
    bank = demo(tmp_path, person=False, followups=False)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    monkeypatch.setattr(projects, "_now", lambda: datetime(2026, 9, 23, 18, tzinfo=UTC))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), bank
    config.get_settings.cache_clear()


def _fm(bank, stem):
    return markdown_parser.parse(bank / "entities" / f"{stem}.md").frontmatter


def _git(bank, *args):
    return subprocess.run(["git", *args], cwd=bank, capture_output=True, text=True, check=True).stdout


def _write(bank, stem, fm, body="## Summary\nA synthetic page."):
    markdown_parser.write(bank / "entities" / f"{stem}.md", fm, body)
    bank_index.invalidate()


def _episode(bank, ep, body, **fm):
    base = {"id": ep, "timestamp": f"{ep[3:13]}T10:00:00Z", "source": "test", "title": fm.pop("title", ep),
            "processed": True}
    markdown_parser.write(bank / "episodes" / f"{ep}.md", {**base, **fm}, body)
    bank_index.invalidate()
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)


# --- the visibility table ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("fm,mine,via", [
    ({"mine": {"via": "app", "day": "2026-10-27", "by": "user"}}, True, "app"),
    ({"mine": {"via": "agent", "day": "2026-10-27", "by": "claude-code"}}, True, "agent"),
    ({"born": {"origin": "words", "via": "folder", "day": "2026-10-01"}}, True, "folder"),
    ({"born": {"origin": "repo", "day": "2026-10-01"}}, False, None),
    ({"born": {"origin": "words", "day": "2026-10-01"}}, False, None),          # Q4: a words birth is suggested
    ({"born": {"origin": "created", "via": "agent", "by": "remote-app"}}, False, None),
    ({"born": {"origin": "words", "via": "folder"}, "not_mine": {"day": "2026-10-27"}}, False, None),
    ({}, False, None),
])
def test_who_lists_a_project(fm, mine, via):
    assert project_ownership.is_mine(fm) is mine
    assert project_ownership.mine_via(fm) == via


def test_progress_logged_in_the_app_counts_as_the_persons_on_day_one():
    class C:
        origin = "companion_app"

    assert project_ownership.mine_via({}, logged_progress=project_ownership.logged_progress([C()])) == "progress"
    assert project_ownership.mine_via({"not_mine": {"day": "x"}}, logged_progress=True) is None


def test_the_list_splits_mine_from_suggested_and_keeps_every_row(client):
    c, bank = client
    before = c.get("/projects").json()
    assert before["projects"], "the demo has projects"
    ids = {r["id"] for r in before["projects"]}
    suggested = {s["id"] for s in before["suggested"]}
    assert {r["id"] for r in before["projects"] if not r["mine"]} <= suggested
    r = c.post("/projects", json={"name": "Cedar Canoe Example", "description": "A strip-built canoe."})
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    after = c.get("/projects").json()
    row = next(x for x in after["projects"] if x["id"] == eid)
    assert row["mine"] and row["mineVia"] == "app" and row["description"] == "A strip-built canoe."
    assert row["oneLiner"] == "A strip-built canoe."
    assert ids <= {x["id"] for x in after["projects"]}          # nothing left the list
    assert eid not in {s["id"] for s in after["suggested"]}
    log = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: user" in log and f"entities/{eid}.md: created" in log


def test_a_create_refuses_a_name_already_a_page(client):
    c, _ = client
    r = c.post("/projects", json={"name": "Rover Arm Project"})
    assert r.status_code == 409 and "rover-arm-project" in r.json()["detail"]


def test_accept_and_dismiss_never_archive_or_retype(client):
    c, bank = client
    target = next(s for s in c.get("/projects").json()["suggested"] if s["kind"] == "page")["id"]
    status = _fm(bank, target).get("status")
    assert c.post(f"/projects/{target}/dismiss").status_code == 200
    fm = _fm(bank, target)
    assert fm["not_mine"] and fm.get("status") == status and fm["type"] == "project"
    listed = c.get("/projects").json()
    assert listed["dismissed"] >= 1
    assert next(s for s in listed["suggested"] if s["id"] == target)["dismissed"] is True
    assert c.post(f"/projects/{target}/accept").status_code == 200
    fm = _fm(bank, target)
    assert "not_mine" not in fm and fm["mine"]["via"] == "accepted"
    assert next(r for r in c.get("/projects").json()["projects"] if r["id"] == target)["mine"]


def test_accepting_a_fallback_concept_retypes_it_in_place(client):
    c, bank = client
    _write(bank, "cedar-canoe", {"name": "Cedar canoe", "type": "concept", "status": "active",
                                 "proposed_type": "project", "source_episodes": ["ep_2026-09-01_001"]})
    s = next(x for x in c.get("/projects").json()["suggested"] if x["id"] == "cedar-canoe")
    assert s["whyKind"] == "fallback" and "never called it a project" in s["why"]
    assert c.post("/projects/cedar-canoe/accept").status_code == 200
    fm = _fm(bank, "cedar-canoe")
    assert fm["type"] == "project" and "proposed_type" not in fm
    assert fm["born"]["origin"] == "created" and fm["born"]["via"] == "accepted" and fm["mine"]["via"] == "accepted"


def test_the_header_is_the_persons_and_a_rename_keeps_the_old_name(client):
    c, bank = client
    r = c.patch("/projects/rover-arm-project", json={"name": "Rover Arm", "description": "An arm for the rover."})
    assert r.status_code == 200, r.text
    fm = _fm(bank, "rover-arm-project")
    assert fm["name"] == "Rover Arm" and "Rover Arm Project" in fm["aliases"]
    assert fm["description"] == "An arm for the rover." and fm["description_by"]["by"] == "user"
    t = c.get("/projects/rover-arm-project/timeline").json()
    assert t["project"]["description"] == "An arm for the rover." and t["project"]["descriptionBy"]["by"] == "user"


def test_an_agent_edit_sets_the_description_through_page_edits():
    fm = {"name": "Alpha Project", "type": "project"}
    out = page_edits.plan(fm, "## Summary\nx", page_edits.parse_request(description="Alpha, in a line."),
                          author="claude-code", day="2026-10-27")
    assert out.frontmatter["description"] == "Alpha, in a line."
    assert out.frontmatter["description_by"] == {"by": "claude-code", "day": "2026-10-27"}
    with pytest.raises(page_edits.EditError):
        page_edits.plan({"name": "Bob Example", "type": "person"}, "## Summary\nx",
                        page_edits.parse_request(description="no"), author="claude-code")


# --- conversations -------------------------------------------------------------------------------------------------

def test_conversations_tie_by_the_persons_words_never_the_agents(client):
    c, bank = client
    _episode(bank, "ep_2026-09-20_901", "user: I worked on the Rover Arm Project today.\nassistant: Good.")
    _episode(bank, "ep_2026-09-20_902", "user: hello\nassistant: Rover Arm Project is great.")
    reasons, _ = project_conversations.tie_reasons(bank, "rover-arm-project", tz_name="UTC")
    assert "named" in reasons.get("ep_2026-09-20_901", set())
    assert "named" not in reasons.get("ep_2026-09-20_902", set())


def test_an_untie_overrides_every_signal_and_a_tie_brings_it_back(client):
    c, bank = client
    _episode(bank, "ep_2026-09-20_903", "user: The Rover Arm Project needs a gripper.")
    page = c.get("/projects/rover-arm-project/conversations").json()
    assert any(r["episodeId"] == "ep_2026-09-20_903" and "named" in r["why"] for r in page["conversations"])
    assert c.post("/projects/rover-arm-project/conversations",
                  json={"episode": "ep_2026-09-20_903", "remove": True}).status_code == 200
    page = c.get("/projects/rover-arm-project/conversations").json()
    assert all(r["episodeId"] != "ep_2026-09-20_903" for r in page["conversations"])
    assert c.post("/projects/rover-arm-project/conversations", json={"episode": "ep_2026-09-20_903"}).status_code == 200
    row = next(r for r in c.get("/projects/rover-arm-project/conversations").json()["conversations"]
               if r["episodeId"] == "ep_2026-09-20_903")
    assert "added" in row["why"] and row["manual"]


def test_a_provider_grouping_ties_and_an_unnamed_one_is_suggested(client):
    c, bank = client
    for n in (1, 2):
        _episode(bank, f"ep_2026-09-21_90{n}", "user: notes\nassistant: ok",
                 provider_project={"provider": "chatgpt", "id": "g-p-synthetic01"})
    s = next(x for x in c.get("/projects").json()["suggested"] if x["id"] == "g-p-synthetic01")
    assert s["kind"] == "group" and s["why"] == "A ChatGPT project, 2 conversations."
    assert c.post("/projects/g-p-synthetic01/accept", json={}).status_code == 400   # named on accept
    r = c.post("/projects/g-p-synthetic01/accept", json={"name": "Garden Plan Example"})
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    rows = c.get(f"/projects/{eid}/conversations").json()["conversations"]
    assert {r["episodeId"] for r in rows} == {"ep_2026-09-21_901", "ep_2026-09-21_902"}
    assert all("provider" in r["why"] and r["providerLabel"] == "ChatGPT" for r in rows)
    assert "g-p-synthetic01" not in {x["id"] for x in c.get("/projects").json()["suggested"]}


def test_a_relayed_project_word_ties_as_the_apps(client):
    c, bank = client
    _episode(bank, "ep_2026-09-22_901", "assistant: hi\nuser: a question", evidence_kind="assistant",
             relay={"app": "claude", "project": "Rover Arm Project"})
    reasons, _ = project_conversations.tie_reasons(bank, "rover-arm-project", tz_name="UTC")
    assert "relay" in reasons["ep_2026-09-22_901"]


# --- influences ----------------------------------------------------------------------------------------------------

def test_something_new_is_plain_text_and_never_mints_a_page(client):
    c, bank = client
    pages = {p.name for p in (bank / "entities").glob("*.md")}
    r = c.post("/projects/rover-arm-project/influences",
               json={"what": "A Synthetic Film About Rovers", "how": "inspired", "note": "It made me want arms."})
    assert r.status_code == 200, r.text
    assert {p.name for p in (bank / "entities").glob("*.md")} == pages
    claim = next(x for x in parse_claims(markdown_parser.parse(bank / "entities" / "rover-arm-project.md").body)
                 if x.id == r.json()["claimId"])
    assert claim.predicate == "inspired-by" and claim.object_kind == "literal"
    assert claim.source_trust == "user_stated" and any(e.kind == "user" for e in claim.evidence)
    t = c.get("/projects/rover-arm-project/timeline").json()
    row = next(i for i in t["influences"] if i["claimId"] == claim.id)
    assert row["by"] == "user" and row["how"] == "inspired" and row["label"] == "A Synthetic Film About Rovers"
    w = c.post("/projects/rover-arm-project/influences/withdraw", json={"claimId": claim.id})
    assert w.status_code == 200, w.text
    t = c.get("/projects/rover-arm-project/timeline").json()
    assert all(i.get("claimId") != claim.id for i in t["influences"])


def test_a_link_influence_is_a_source_and_undo_remembers_the_removal(client):
    c, bank = client
    r = c.post("/projects/rover-arm-project/influences", json={"url": "https://example.com/rover-paper.pdf"})
    assert r.status_code == 200, r.text
    t = c.get("/projects/rover-arm-project/timeline").json()
    row = next(i for i in t["influences"] if i.get("url") == "https://example.com/rover-paper.pdf")
    assert row["tag"] == "Paper"
    w = c.post("/projects/rover-arm-project/influences/withdraw",
               json={"ref": row["ref"], "predicate": row["predicate"]})
    assert w.status_code == 200, w.text
    assert _fm(bank, "rover-arm-project")["sources_removed"]


# --- carried by Sleep's merges -------------------------------------------------------------------------------------

def test_a_merge_carries_the_persons_keys(tmp_path):
    bank = tmp_path
    (bank / "entities").mkdir()
    markdown_parser.write(bank / "entities" / "alpha.md", {"name": "Alpha", "type": "project"}, "## Summary\nA")
    markdown_parser.write(bank / "entities" / "alpha-2.md", {
        "name": "Alpha two", "type": "project", "mine": {"via": "app", "day": "2026-10-27", "by": "user"},
        "description": "Mine.", "description_by": {"by": "user", "day": "2026-10-27"},
        "conversations_added": ["ep_2026-10-01_001"], "conversations_removed": ["ep_2026-10-02_001"],
        "provider_projects": [{"provider": "claude", "id": "uuid-1"}]}, "## Summary\nB")
    entity_merge.merge_entities(bank, "alpha-2", "alpha")
    fm = markdown_parser.parse(bank / "entities" / "alpha.md").frontmatter
    assert fm["mine"]["via"] == "app" and fm["description"] == "Mine."
    assert fm["conversations_added"] == ["ep_2026-10-01_001"]
    assert fm["conversations_removed"] == ["ep_2026-10-02_001"]
    assert fm["provider_projects"] == [{"provider": "claude", "id": "uuid-1"}]


def test_the_shape_moves_so_caches_refetch_once():
    assert project_timeline.PROJECT_SHAPE == "g141-7"
