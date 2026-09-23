"""G135 R-R11..R-R13 — an agent write says who wrote it, commits only its own
page, and never escapes its bank or fails because git did."""
from __future__ import annotations

import asyncio
import subprocess

import pytest
from fastapi.testclient import TestClient

from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api import config, main
from api.services import agent_commits, agentic_write, bank_index, markdown_parser, media_ingestor, owner_identity
from api.services.claims import parse_claims


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def server(tmp_path, monkeypatch):
    srv = stdio_server()
    memory = _bank(tmp_path)
    monkeypatch.setattr(srv, "get_memory_path", lambda: memory)
    monkeypatch.setattr(srv, "SESSION", srv.SessionIdentity("ses_2026-09-23_c0ffee00", "claude-code", None))
    return srv, memory


def test_a_stdio_claim_commits_only_its_page_under_the_harness(server):
    srv, memory = server
    (memory / "notes.md").write_text("an unrelated dirty file\n")
    out = srv.handle_write_claim("alpha-project", "uses", "sqlite-vec", None, None, None, None)
    assert out.startswith("Recorded")
    body = _git(memory, "log", "-1", "--format=%B")
    assert body.startswith("Agent write ")
    assert "entities/alpha-project.md: updated (source: n/a, trigger: mcp/claude-code)" in body
    assert "Cicada-Author: claude-code" in body and "Cicada-Session: ses_2026-09-23_c0ffee00" in body
    assert "Cicada-Engine" not in body
    assert _git(memory, "show", "--name-only", "--format=", "HEAD").split() == ["entities/alpha-project.md"]
    assert "notes.md" in _git(memory, "status", "--porcelain"), "never git add -A"
    claim = [c for c in parse_claims(markdown_parser.parse(memory / "entities" / "alpha-project.md").body)
             if c.predicate == "uses"][0]
    assert claim.authored_by == "claude-code" and claim.origin == "mcp"


def test_an_unknown_harness_is_credited_to_agent(server, monkeypatch):
    srv, memory = server
    monkeypatch.setattr(srv, "SESSION", srv.SessionIdentity("ses_2026-09-23_0000beef", "unknown", None))
    srv.handle_write_claim("bob-example", "knows", "alpha-project", None, None, None, None)
    assert "Cicada-Author: agent" in _git(memory, "log", "-1", "--format=%B")


def test_a_bank_that_is_not_its_own_repo_is_written_but_never_committed(tmp_path):
    memory = _bank(tmp_path, git=False)
    result = agentic_write.write_claim(memory, "alpha-project", "uses", "sqlite-vec", observer="agent",
                                       authored_by="claude-code")
    assert result["action"] == "written" and result["path"] == "entities/alpha-project.md"
    assert agent_commits.commit_write(memory, subject="Agent write", lines=["x"], paths=[result["path"]],
                                      author="claude-code", session=None) is False


def test_commit_write_refuses_from_inside_a_running_loop(tmp_path):
    memory = _bank(tmp_path)

    async def inside():
        return agent_commits.commit_write(memory, subject="Agent write", lines=["x"],
                                          paths=["entities/alpha-project.md"], author="agent", session=None)

    assert asyncio.run(inside()) is False


@pytest.mark.parametrize("observer", ["owner", owner_identity.LEGACY_OBSERVER])
def test_forbid_owner_observer_writes_nothing(tmp_path, observer):
    memory = _bank(tmp_path)
    page = memory / "entities" / "alpha-project.md"
    before = page.read_text()
    result = agentic_write.write_claim(memory, "alpha-project", "lives-in", "Lisbon", observer=observer,
                                       forbid_owner_observer=True)
    assert result["action"] == "error" and "own words" in result["error"]
    assert page.read_text() == before


def test_forbid_owner_observer_catches_the_resolved_slug_too(tmp_path):
    # The third spelling: a caller that already knows the owner's slug. It never
    # enters the keyword-normalising `if`, so the check must sit outside it.
    memory = _bank(tmp_path)
    owner_identity.save_owner({"entity_id": "bob-example"})
    page = memory / "entities" / "alpha-project.md"
    before = page.read_text()
    result = agentic_write.write_claim(memory, "alpha-project", "knows", "bob-example", observer="bob-example",
                                       forbid_owner_observer=True)
    assert result["action"] == "error" and "own words" in result["error"]
    assert page.read_text() == before


def test_page_created_is_reported(tmp_path):
    memory = _bank(tmp_path)
    fresh = agentic_write.write_claim(memory, "gamma-new-thing", "uses", "x", observer="agent", force_new_entity=True)
    again = agentic_write.write_claim(memory, "gamma-new-thing", "uses", "y", observer="agent")
    assert fresh["page_created"] is True and again["page_created"] is False


def _client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()

    async def offline(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(title="Example Post", description="", site="example.com", media_type="url")

    monkeypatch.setattr(media_ingestor, "enrich", offline)
    return TestClient(main.app), memory


def test_a_pasted_link_now_commits_as_the_person(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    resp = client.post("/sources/save", json={"url": "https://example.com/pasted"})
    assert resp.status_code == 200
    body = _git(memory, "log", "-1", "--format=%B")
    assert body.startswith("Sources ingest ") and "Cicada-Author: user" in body
    assert "trigger: user/media_save" in body
    files = set(_git(memory, "show", "--name-only", "--format=", "HEAD").split())
    assert "sources/url_index.json" in files and len(files) == 3


def test_an_mcp_save_is_credited_to_its_harness(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    resp = client.post("/sources/save", json={"url": "https://example.com/agent", "sessionId": "ses_x_1",
                                              "harness": "claude-code"})
    assert resp.status_code == 200
    body = _git(memory, "log", "-1", "--format=%B")
    assert "Cicada-Author: claude-code" in body and "Cicada-Session: ses_x_1" in body
    assert "trigger: mcp/claude-code" in body
