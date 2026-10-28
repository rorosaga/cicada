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
        {"entity": "delta-tool", "by": "claude-code", "session": "ses_test"}]
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
