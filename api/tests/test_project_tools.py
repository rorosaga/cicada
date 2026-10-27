"""Ruling 45 (2026-10-27): an agent starts a project, ties a conversation, records an influence. Synthetic bank only."""
import subprocess

import pytest

from _synthetic_bank import _bank
from api.remote import catalog
from api.services import bank_index, handshake, markdown_parser, mcp_tools, project_ownership, project_timeline
from api.services.claims import parse_claims


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))    # the trust list's defaults (no editors.json)
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
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


def _git(bank, *args):
    return subprocess.run(["git", *args], cwd=bank, capture_output=True, text=True, check=True).stdout


def test_a_trusted_harness_lands_its_project_in_the_list(bank):
    reply = mcp_tools.create_project(_ctx(bank), "Delta Project Example", "A synthetic project.")
    assert "in the person's projects" in str(reply)
    fm = _fm(bank, "delta-project-example")
    assert fm["mine"] == {"via": "agent", "day": fm["mine"]["day"], "by": "claude-code", "session": "ses_test"}
    assert fm["born"]["origin"] == "created" and fm["born"]["via"] == "agent" and fm["born"]["by"] == "claude-code"
    assert fm["description"] == "A synthetic project." and fm["description_by"]["by"] == "claude-code"
    log = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: claude-code" in log and "Cicada-Session: ses_test" in log


def test_an_untrusted_or_remote_client_only_suggests(bank):
    mcp_tools.create_project(_ctx(bank, harness="cursor"), "Epsilon Example")
    mcp_tools.create_project(_ctx(bank, remote=True), "Zeta Example")
    for stem in ("epsilon-example", "zeta-example"):
        fm = _fm(bank, stem)
        assert "mine" not in fm and fm["born"]["via"] == "agent"
    listed = project_timeline.list_projects(bank, tz_name="UTC")
    s = {g.id: g for g in listed.suggested}
    assert s["epsilon-example"].why_kind == "agent" and s["epsilon-example"].by == "cursor"


def test_a_create_refuses_an_existing_page_and_names_it(bank):
    reply = mcp_tools.create_project(_ctx(bank), "Alpha Project")
    assert getattr(reply, "code", None) == "refused" and "alpha-project" in str(reply)


def test_an_agent_unties_only_what_it_tied_and_never_reties_a_persons_untie(bank):
    ctx = _ctx(bank)
    assert "Tied 1" in mcp_tools.link_conversation(ctx, "alpha-project", "ep_2026-09-01_001", reason="About alpha.")
    assert project_ownership.tied_by(_fm(bank, "alpha-project"), "ep_2026-09-01_001") == "claude-code"
    other = mcp_tools.link_conversation(_ctx(bank, harness="codex"), "alpha-project", "ep_2026-09-01_001",
                                        remove=True, reason="Not it.")
    assert getattr(other, "code", None) == "refused"
    assert "Untied" in mcp_tools.link_conversation(ctx, "alpha-project", "ep_2026-09-01_001", remove=True,
                                                   reason="Wrong one.")
    assert "conversations_removed" not in _fm(bank, "alpha-project")       # an agent's untie is no person's untie
    project_ownership.tie(bank, "alpha-project", "ep_2026-09-01_001", remove=True)   # the person
    again = mcp_tools.link_conversation(ctx, "alpha-project", "ep_2026-09-01_001", reason="Retry.")
    assert getattr(again, "code", None) == "refused"


def test_an_agents_influence_is_its_own_never_the_persons(bank):
    reply = mcp_tools.add_influence(_ctx(bank), "alpha-project", what="A Synthetic Book", how="reference")
    assert "with you as the observer" in str(reply)
    claims = parse_claims(markdown_parser.parse(bank / "entities" / "alpha-project.md").body)
    c = next(x for x in claims if x.predicate == "references")
    assert c.object == "A Synthetic Book" and c.object_kind == "literal" and c.authored_by == "claude-code"
    assert c.source_trust != "user_stated"
    assert not (bank / "entities" / "a-synthetic-book.md").exists()


def test_cicada_project_says_whose_it_is(bank):
    reply = mcp_tools.project(_ctx(bank), "alpha-project")
    assert "Not in the person's projects yet" in str(reply)
    project_ownership.accept(bank, "alpha-project")
    reply = mcp_tools.project(_ctx(bank), "alpha-project")
    assert "In the person's projects." in str(reply) and reply.data["mine"] is True


def test_an_edit_renames_a_project_and_keeps_the_old_name(bank):
    reply = mcp_tools.edit_page(_ctx(bank), "alpha-project", "The person renamed it.", name="Alpha Prime")
    assert "renamed" in str(reply)
    fm = _fm(bank, "alpha-project")
    assert fm["name"] == "Alpha Prime" and any(a.lower() == "alpha project" for a in fm["aliases"])
