"""Projects v3 (decisions 9 and 10, owner 2026-10-28): the pulse, counted and read at today with no model; pages tied
to a project by hand, the person's "Not part of it" final, a trusted agent tying at once and any other proposing.
Synthetic banks and placeholder names only."""
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank, _entity
from api import config, main
from api.remote import catalog
from api.routers import projects
from api.services import (bank_index, cli_map, handshake, markdown_parser, mcp_tools, project_ownership,
                          project_pulse, project_timeline, tool_door)
from api.services.claims import Claim, write_claims

CASES = json.loads((Path(__file__).parent / "fixtures" / "project_pulse.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_pulse_matches_the_shared_fixture(case):
    assert project_pulse.pulse(case["input"], case["today"]) == case["expected"]


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))    # the trust list's defaults: claude-code, codex
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    _entity(memory, "carol-example", type="person")
    _entity(memory, "delta-tool", type="tool")
    _entity(memory, "owner-example", type="person", owner=True)
    bank_index.invalidate()
    return memory


def _ctx(bank, harness="claude-code", remote=False):
    if remote:
        return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="rc_abcd1234_x", harness="claude-web",
                                     connector_id="abcd1234", available=catalog.tool_names_for({"record", "read"}),
                                     raw_excerpts=False, read_surface="remote")
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_test", harness=harness)


def _fm(bank, stem):
    return markdown_parser.parse(bank / "entities" / f"{stem}.md").frontmatter


def _pages(bank, stem="alpha-project"):
    bank_index.invalidate()
    return {p.id: p for p in project_timeline.build(bank, stem, tz_name="UTC").pages}


def _git(bank, *args):
    return subprocess.run(["git", *args], cwd=bank, capture_output=True, text=True, check=True).stdout


# --- tie by hand: the store ----------------------------------------------------------------------------------------

def test_the_person_ties_a_page_and_its_not_part_of_it_wins_over_a_claim(bank):
    # A claim on the project names the person: the automatic layer lists it.
    _entity(bank, "alpha-project", type="project", body=write_claims("## Summary\nAlpha.\n", [Claim(
        id="clm_a1", text="alpha project works with carol", subject="alpha-project", predicate="works-with",
        object="carol-example", valid_from="2026-09-01")]))
    bank_index.invalidate()
    assert _pages(bank)["carol-example"].tie == "said"
    project_ownership.tie_page(bank, "alpha-project", "delta-tool")
    assert _fm(bank, "alpha-project")["entities_added"] == ["delta-tool"]
    assert _pages(bank)["delta-tool"].tie == "user"
    project_ownership.tie_page(bank, "alpha-project", "carol-example", remove=True)
    assert "carol-example" not in _pages(bank)
    assert _fm(bank, "alpha-project")["entities_removed"] == ["carol-example"]
    # Adding it again lifts the "Not part of it".
    project_ownership.tie_page(bank, "alpha-project", "carol-example")
    fm = _fm(bank, "alpha-project")
    assert "entities_removed" not in fm and fm["entities_added"] == ["delta-tool", "carol-example"]


def test_a_tie_refuses_what_is_not_a_page_the_project_itself_and_the_owner(bank):
    for entity, words in (("no-such-page", "No page"), ("alpha-project", "not a page of itself"),
                          ("owner-example", "part of every project")):
        with pytest.raises(project_ownership.OwnershipError, match=words):
            project_ownership.tie_page(bank, "alpha-project", entity)
    assert "entities_added" not in _fm(bank, "alpha-project")


def test_a_sub_project_is_refused_in_words_never_tied_unseen(bank):
    """Review of #511: a sub-project lists under its parent, never in Pages in this project — a tie would be written
    and never shown, so it is refused with a sentence, for the person and for an agent alike."""
    _entity(bank, "beta-project", type="project", body=write_claims("## Summary\nBeta.\n", [Claim(
        id="clm_b1", text="beta project part of alpha project", subject="beta-project", predicate="part-of",
        object="alpha-project", valid_from="2026-09-01")]))
    bank_index.invalidate()
    with pytest.raises(project_ownership.OwnershipError, match="already a sub-project of Alpha Project"):
        project_ownership.tie_page(bank, "alpha-project", "beta-project")
    reply = mcp_tools.link_entity(_ctx(bank), "alpha-project", "beta-project", reason="It is part of alpha.")
    assert getattr(reply, "code", None) == "refused" and "already a sub-project" in str(reply)
    assert "entities_added" not in _fm(bank, "alpha-project")


def test_an_agent_cannot_retie_what_the_person_removed_or_untie_what_it_did_not_tie(bank):
    project_ownership.tie_page(bank, "alpha-project", "carol-example", remove=True)
    with pytest.raises(project_ownership.OwnershipError, match="not part of this project"):
        project_ownership.tie_page(bank, "alpha-project", "carol-example", by="claude-code")
    project_ownership.tie_page(bank, "alpha-project", "delta-tool")
    with pytest.raises(project_ownership.OwnershipError, match="only a page you tied"):
        project_ownership.tie_page(bank, "alpha-project", "delta-tool", remove=True, by="claude-code")
    assert _fm(bank, "alpha-project")["entities_added"] == ["delta-tool"]


def test_a_merge_keeps_both_pages_hand_ties_and_an_untie_wins():
    winner = {"entities_added": ["a-page"], "entities_removed": ["b-page"]}
    loser = {"entities_added": ["b-page", {"entity": "c-page", "by": "codex"}]}
    project_ownership.carry_on_merge(winner, loser)
    assert winner["entities_added"] == ["a-page", {"entity": "c-page", "by": "codex"}]
    assert winner["entities_removed"] == ["b-page"]


# --- the agent door ------------------------------------------------------------------------------------------------

def test_a_trusted_harness_ties_at_once_with_its_name_and_trailers(bank):
    reply = str(mcp_tools.link_entity(_ctx(bank), "alpha-project", "delta-tool", reason="Alpha runs on it."))
    assert "Tied delta-tool" in reply
    assert _fm(bank, "alpha-project")["entities_added"] == [
        {"entity": "delta-tool", "by": "claude-code", "session": "ses_test", "reason": "Alpha runs on it."}]
    row = _pages(bank)["delta-tool"]
    assert row.tie == "agent" and row.by == "claude-code"
    log = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: claude-code" in log and "Reason: Alpha runs on it." in log
    # It takes back its own tie; the person's untie is never written by an agent.
    assert "Took back" in str(mcp_tools.link_entity(_ctx(bank), "alpha-project", "delta-tool", remove=True,
                                                     reason="Wrong project."))
    fm = _fm(bank, "alpha-project")
    assert "entities_added" not in fm and "entities_removed" not in fm


def test_an_untrusted_or_remote_client_only_proposes_and_the_persons_add_takes_it(bank):
    assert "Proposed" in str(mcp_tools.link_entity(_ctx(bank, harness="cursor"), "alpha-project", "delta-tool",
                                                   reason="Alpha runs on it."))
    assert "Proposed" in str(mcp_tools.link_entity(_ctx(bank, remote=True), "alpha-project", "carol-example",
                                                   reason="Carol is on it."))
    pages = _pages(bank)
    assert pages["delta-tool"].tie == "proposed" and pages["delta-tool"].by == "cursor"
    assert pages["carol-example"].tie == "proposed"
    # Proposals come first on the panel, and the agent reply keeps them apart from the project's pages.
    text = str(mcp_tools.project(_ctx(bank), "alpha-project"))
    assert "Proposed by an agent, waiting for the person:" in text and "Pages in this project" not in text
    project_ownership.tie_page(bank, "alpha-project", "delta-tool")
    assert _pages(bank)["delta-tool"].tie == "user"
    assert "Pages in this project: Delta Tool (delta-tool)." in str(mcp_tools.project(_ctx(bank), "alpha-project"))


def test_a_reason_is_required_and_nothing_is_written_without_one(bank):
    reply = mcp_tools.link_entity(_ctx(bank), "alpha-project", "delta-tool")
    assert getattr(reply, "code", None) == "invalid_arguments"
    assert "entities_added" not in _fm(bank, "alpha-project")


def test_the_tool_is_on_every_door():
    from _stdio_server import stdio_server
    from api.remote import tools as remote_tools

    assert "cicada_link_entity" in tool_door.DISPATCH
    assert any(r.tool == "cicada_link_entity" for r in cli_map.ROWS)
    assert catalog.TOOL_SCOPE["cicada_link_entity"] == "record"
    assert "cicada_link_entity" in catalog.WRITE_TOOLS
    assert "cicada_link_entity" in remote_tools.REMOTE_TOOLS
    assert any(t["name"] == "cicada_link_entity" for t in stdio_server().TOOLS)


# --- the route -----------------------------------------------------------------------------------------------------

@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    monkeypatch.setattr(projects, "_now", lambda: datetime(2026, 9, 23, 18, tzinfo=UTC))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_the_route_adds_and_removes_and_commits_as_the_person(client, bank):
    r = client.post("/projects/alpha-project/pages", json={"entity": "delta-tool"})
    assert r.status_code == 200 and r.json()["action"] == "added"
    assert "Cicada-Author: user" in _git(bank, "log", "-1", "--format=%B")
    assert client.post("/projects/alpha-project/pages", json={"entity": "delta-tool"}).json()["action"] == "unchanged"
    r = client.post("/projects/alpha-project/pages", json={"entity": "delta-tool", "remove": True})
    assert r.json()["action"] == "removed"
    assert client.post("/projects/alpha-project/pages", json={"entity": "nope"}).status_code == 400
    body = client.get("/projects/alpha-project/timeline").json()
    assert "pages" in body and "pagesTotal" in body and "conversationDays" in body


# --- the pulse's server facts --------------------------------------------------------------------------------------

def test_an_open_thread_says_who_it_waits_on_from_its_from_participant(bank):
    _entity(bank, "alpha-project", type="project", body=write_claims("## Summary\nAlpha.\n", [Claim(
        id="clm_t1", text="Ordered the cloth", subject="alpha-project", predicate="happened", status="ongoing",
        valid_from="2026-09-01", participants=[{"role": "from", "surface": "Carol Example", "entity": "carol-example"},
                                               {"role": "owner", "entity": "owner-example"}])]))
    bank_index.invalidate()
    t = project_timeline.build(bank, "alpha-project", tz_name="UTC")
    assert t.now.threads[0].waiting_on == "Carol Example"
    p = project_pulse.pulse(project_pulse.input_from_timeline(t), "2026-09-10")
    assert p["waiting"][0]["who"] == "Carol Example" and p["waitingTotal"] == 1


def test_conversation_days_count_each_conversation_once_on_its_newest_day(bank):
    project_ownership.tie(bank, "alpha-project", "ep_2026-09-01_001")
    project_ownership.tie(bank, "alpha-project", "ep_2026-09-02_001")
    bank_index.invalidate()
    t = project_timeline.build(bank, "alpha-project", tz_name="UTC")
    assert sum(d.n for d in t.conversation_days) == t.conversation_count


# --- New project as a page: the person's words and the pages they attach (owner 2026-11-04) ------------------------

def _repo_page(bank, eid="alpha-repo", full="bob-example/alpha-repo"):
    _entity(bank, eid, type="media", media={"kind": "repository"},
            github={"id": 41, "full_name": full, "owner": "bob-example"})
    bank_index.invalidate()


def test_new_project_attaches_pages_of_every_kind_in_one_person_commit(client, bank):
    _repo_page(bank)
    _entity(bank, "talk-video", type="media", media={"kind": "video"})
    before = _git(bank, "rev-list", "--count", "HEAD")
    r = client.post("/projects", json={"name": "Kite Lab", "description": "Why kites fly.\n\nAnd what to build next.",
                                       "pages": ["delta-tool", "talk-video", "alpha-repo", "Carol Example"]})
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    assert int(_git(bank, "rev-list", "--count", "HEAD")) == int(before) + 1      # one commit for all of it
    message = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: user" in message and "trigger: user/companion_app" in message
    assert f"entities/{eid}.md: created" in message and "entities/alpha-repo.md: updated" in message
    fm = _fm(bank, eid)
    assert set(project_ownership.pages(fm, project_ownership.PAGES_ADDED_KEY)) == {"delta-tool", "talk-video",
                                                                                   "carol-example"}
    assert [r["entity"] for r in fm["repositories"]] == ["alpha-repo"] and fm["repositories"][0]["by"] == "user"
    assert _fm(bank, "alpha-repo")["github"]["projects"] == [eid]                     # the repository names it back
    pages = _pages(bank, eid)
    assert set(pages) == {"delta-tool", "talk-video", "alpha-repo", "carol-example"}
    assert {p.tie for p in pages.values()} == {"user"}
    assert fm["description"] == "Why kites fly.\n\nAnd what to build next."            # paragraphs kept
    row = next(p for p in client.get("/projects").json()["projects"] if p["id"] == eid)
    assert row["oneLiner"] == "Why kites fly." and row["description"].endswith("what to build next.")
    # Made a moment ago in the app: in motion (heard the day it was made), never "Nothing heard yet" under Past.
    assert row["lastMomentDay"] == "2026-09-23"


def test_new_project_refuses_an_unknown_or_owner_page_before_writing_anything(client, bank):
    before = _git(bank, "rev-parse", "HEAD")
    for pages in (["delta-tool", "nope"], ["owner-example"]):
        r = client.post("/projects", json={"name": "Kite Lab", "pages": pages})
        assert r.status_code == 400
        assert not (bank / "entities" / "kite-lab.md").exists()
    assert _git(bank, "rev-parse", "HEAD") == before
    r = client.post("/projects", json={"name": "Kite Lab", "pages": ["delta-tool"] * 101})
    assert r.status_code == 400


def test_a_repository_added_on_the_page_is_one_of_its_repositories_and_not_part_of_it_unlinks(client, bank):
    _repo_page(bank)
    r = client.post("/projects/alpha-project/pages", json={"entity": "alpha-repo"})
    assert r.status_code == 200 and r.json()["action"] == "added"
    fm = _fm(bank, "alpha-project")
    assert [x["entity"] for x in fm["repositories"]] == ["alpha-repo"]
    assert "alpha-repo" not in project_ownership.pages(fm, project_ownership.PAGES_ADDED_KEY)
    assert _pages(bank)["alpha-repo"].tie == "user"
    r = client.post("/projects/alpha-project/pages", json={"entity": "alpha-repo", "remove": True})
    assert r.json()["action"] == "removed"
    fm = _fm(bank, "alpha-project")
    assert "repositories" not in fm and fm["repositories_removed"] == ["https://github.com/bob-example/alpha-repo"]
    assert "alpha-repo" in project_ownership.pages(fm, project_ownership.PAGES_REMOVED_KEY)
    assert "alpha-repo" not in _pages(bank)
    # The person's add again lifts both.
    client.post("/projects/alpha-project/pages", json={"entity": "alpha-repo"})
    fm = _fm(bank, "alpha-project")
    assert [x["entity"] for x in fm["repositories"]] == ["alpha-repo"] and "repositories_removed" not in fm
    assert "alpha-repo" in _pages(bank)


def test_a_description_keeps_its_paragraphs_within_its_cap():
    text = "  First   line \r\n\r\n\r\n  second  para\nwith a break  "
    assert project_ownership.clean_description(text) == "First line\n\nsecond para\nwith a break"
    assert project_ownership.first_line("\n\nHello there\nmore") == "Hello there"
    words = "kite " * 2000          # prose, never a token-shaped run the scrub would redact
    assert len(project_ownership.clean_description(words[:project_ownership.MAX_DESCRIPTION])) <= 4000
    with pytest.raises(project_ownership.OwnershipError):
        project_ownership.clean_description(words[:project_ownership.MAX_DESCRIPTION + 2])


def test_a_create_whose_attach_is_refused_leaves_nothing_behind_and_a_retry_works(client, bank):
    """Review of #595, B1: a page whose `part-of` names the new project by name only becomes its sub-project once the
    page exists, so `tie_page` refuses it after `create` wrote — the create is all or nothing: no orphan page, the
    repository page's back-link restored, no commit, and the retry without that page is not told the name is taken."""
    _repo_page(bank)
    _entity(bank, "kite-wing", type="project", body=write_claims("## Summary\nA wing.\n", [Claim(
        id="clm_kw1", text="kite wing part of kite lab", subject="kite-wing", predicate="part-of",
        object="Kite Lab", valid_from="2026-09-01")]))
    bank_index.invalidate()
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "fixture pages")
    head = _git(bank, "rev-parse", "HEAD")
    repo_before = (bank / "entities" / "alpha-repo.md").read_bytes()
    r = client.post("/projects", json={"name": "Kite Lab", "pages": ["alpha-repo", "kite-wing"]})
    assert r.status_code == 400 and "sub-project" in r.json()["detail"]
    assert not (bank / "entities" / "kite-lab.md").exists()
    assert (bank / "entities" / "alpha-repo.md").read_bytes() == repo_before        # its back-link taken back
    assert _git(bank, "rev-parse", "HEAD") == head and _git(bank, "status", "--porcelain") == ""
    r = client.post("/projects", json={"name": "Kite Lab", "pages": ["alpha-repo"]})
    assert r.status_code == 200, r.text


def test_any_failure_while_attaching_takes_back_the_new_page(bank, monkeypatch):
    """B1: not only a refusal — any exception in the attach loop leaves nothing behind."""
    def boom(*_a, **_k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(project_ownership, "attach", boom)
    with pytest.raises(RuntimeError):
        project_ownership.create_with_pages(bank, "Kite Lab", "", ["delta-tool"], via="app")
    assert not (bank / "entities" / "kite-lab.md").exists()


def test_every_door_scrubs_the_description_and_ledgers_it_as_project(client, bank, monkeypatch):
    """Review of #595, B2: the description holds up to 4,000 characters of the person's paragraphs; every door (create,
    the header's PATCH, `page_edits`, a provider import) comes through `clean_description`, which scrubs and ledgers
    the count as `project` (R-B10's rule)."""
    from api.services import episode_scrub

    rows = []
    monkeypatch.setattr(episode_scrub, "record", lambda writer, n, bank=None: rows.append((writer, n, bank)))
    secret = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
    r = client.post("/projects", json={"name": "Kite Lab", "description": f"Why kites fly.\n\nKey {secret} here."})
    assert r.status_code == 200, r.text
    desc = _fm(bank, r.json()["id"])["description"]
    assert secret not in desc and desc.startswith("Why kites fly.\n\n")
    assert ("project", 1, bank.name) in rows
    r = client.patch(f"/projects/{r.json()['id']}", json={"description": f"Now {secret}."})
    assert r.status_code == 200 and secret not in _fm(bank, "kite-lab")["description"]
    assert "project" in episode_scrub.WRITERS
    assert secret not in project_ownership.clean_description(f"x {secret}")
