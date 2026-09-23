"""G140 Q-R5 (R3 P7) — an agent withdraws a claim IT wrote; the claim is kept
as history, a record keeps the reason, nothing is deleted. Synthetic bank."""
from __future__ import annotations

import re
import subprocess
from datetime import date

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api import config
from api.remote import catalog
from api.remote.runtime import RemoteRuntime
from api.services import agentic_write, change_timeline, markdown_parser, mcp_tools, search_index
from api.services.claims import Claim, parse_claims, write_claims

TODAY = date.today().isoformat()
REASON = "The person said the index moved to another engine."


def _claims(memory, eid="alpha-project") -> dict[str, Claim]:
    return {c.id: c for c in parse_claims(markdown_parser.parse(memory / "entities" / f"{eid}.md").body)}


def _add(memory, claim: Claim, eid="alpha-project"):
    page = memory / "entities" / f"{eid}.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter,
                          write_claims(parsed.body, [*parse_claims(parsed.body), claim]))


@pytest.fixture
def srv(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    monkeypatch.setattr(server, "SESSION", server.SessionIdentity("ses_retract_fixed", "claude-code", None))
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    return server, memory


def _write(server, obj="sqlite-vec") -> str:
    reply = server.handle_tool("cicada_write_claim", {"subject": "alpha-project", "predicate": "uses", "object": obj})
    return re.search(r"claim `([^`]+)`", reply).group(1)


def _retract(server, claim_id, reason=REASON, **extra):
    return server.handle_tool("cicada_retract_claim",
                              {"subject": "alpha-project", "claim_id": claim_id, "reason": reason, **extra})


def test_an_agent_withdraws_its_own_claim_and_the_reason_is_kept(srv):
    server, memory = srv
    claim_id = _write(server)
    out = _retract(server, claim_id)
    assert out.startswith(f"Withdrew claim `{claim_id}` on `alpha-project`"), out
    claims = _claims(memory)
    target = claims[claim_id]
    record = claims[target.superseded_by]
    assert target.valid_to == TODAY
    assert (record.predicate, record.object, record.object_kind) == ("retracts", claim_id, "literal")
    assert record.valid_from == record.valid_to == TODAY, "born closed: history, never a belief"
    assert record.text == REASON and record.supersedes == claim_id and record.authored_by == "claude-code"
    assert [e.kind for e in record.evidence] == ["reasoning"]
    assert "sqlite-vec" not in server.handle_tool("cicada_get_perspective", {"subject": "alpha-project"})


def test_the_withdrawal_is_committed_under_the_agent_and_counted_by_the_timeline(srv):
    server, memory = srv
    _retract(server, _write(server))
    log = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%s%n%b"],
                         capture_output=True, text=True, check=True).stdout
    assert "entities/alpha-project.md: retracted (source: n/a, trigger: mcp/claude-code)" in log
    assert "Cicada-Author: claude-code" in log and "Cicada-Session: ses_retract_fixed" in log
    (day,) = change_timeline.collect(memory, date.today(), date.today())
    assert day.retracted == 1


def test_twice_is_a_no_op(srv):
    server, memory = srv
    claim_id = _write(server)
    _retract(server, claim_id)
    before = (memory / "entities" / "alpha-project.md").read_text()
    assert "already stopped being current" in _retract(server, claim_id)
    assert (memory / "entities" / "alpha-project.md").read_text() == before


@pytest.mark.parametrize("claim", [
    Claim(id="clm_sleep", text="alpha uses duckdb", subject="alpha-project", predicate="uses", object="duckdb",
          authored_by="gpt-5.4-mini", origin="claude-code", valid_from="2026-09-01"),
    Claim(id="clm_person", text="alpha is mine", subject="alpha-project", predicate="owned-by", object="owner",
          observer="owner", source_trust="user_stated", origin="manual_edit", authored_by="claude-code",
          valid_from="2026-09-01"),
    Claim(id="clm_other_app", text="alpha uses redis", subject="alpha-project", predicate="uses", object="redis",
          authored_by="claude-code", origin="remote:zz99zz99", valid_from="2026-09-01"),
    # Telegram's `saved-because` arrives without an author and `_stamp_new`
    # gives it the pre-G135 placeholder: the placeholder alone never makes a
    # claim an agent's (final review, T3 r1 M1).
    Claim(id="clm_telegram", text="saved for the alpha launch", subject="alpha-project",
          predicate="saved-because", object="alpha launch", observer="owner", source_trust="user_stated",
          origin="telegram", authored_by="mcp-agentic-write", valid_from="2026-09-01"),
], ids=["sleep", "the-person", "a-remote-app", "telegram-with-the-legacy-author"])
def test_a_claim_this_agent_did_not_write_is_refused(srv, claim):
    server, memory = srv
    _add(memory, claim)
    before = (memory / "entities" / "alpha-project.md").read_text()
    assert "was not written by this agent" in _retract(server, claim.id)
    assert (memory / "entities" / "alpha-project.md").read_text() == before


def test_the_legacy_author_is_only_an_agents_on_an_mcp_origin():
    telegram = Claim(id="clm_t", text="t", subject="alpha-project", predicate="saved-because", object="x",
                     observer="owner", source_trust="user_stated", origin="telegram",
                     authored_by="mcp-agentic-write")
    for author in ("claude-code", "codex"):
        assert not agentic_write.owns(telegram, author=author, origin=None)
    stdio = Claim(id="clm_s", text="s", subject="alpha-project", predicate="uses", object="x",
                  origin="mcp", authored_by="mcp-agentic-write")
    assert agentic_write.owns(stdio, author="codex", origin=None)


def test_withdraw_restate_withdraw_closes_the_restatement(srv):
    """The id is minted from the fact, so a restatement after a withdrawal
    reuses it: the second withdrawal must close the OPEN copy, under a record
    id of its own (final review)."""
    server, memory = srv
    claim_id = _write(server)
    assert _retract(server, claim_id).startswith("Withdrew")
    assert _write(server) == claim_id
    assert "sqlite-vec" in server.handle_tool("cicada_get_perspective", {"subject": "alpha-project"})
    out = _retract(server, claim_id, reason="Said wrong a second time.")
    assert out.startswith(f"Withdrew claim `{claim_id}`"), out
    page = parse_claims(markdown_parser.parse(memory / "entities" / "alpha-project.md").body)
    copies = [c for c in page if c.id == claim_id]
    records = [c for c in page if c.predicate == "retracts"]
    assert len(copies) == 2 and all(c.valid_to == TODAY for c in copies)
    assert len({r.id for r in records}) == 2, "each withdrawal has its own record id"
    assert {c.superseded_by for c in copies} == {r.id for r in records}
    assert "sqlite-vec" not in server.handle_tool("cicada_get_perspective", {"subject": "alpha-project"})
    assert "already stopped being current" in _retract(server, claim_id)


def test_a_pre_g135_local_claim_can_be_withdrawn_by_a_local_agent(srv):
    server, memory = srv
    _add(memory, Claim(id="clm_legacy", text="alpha uses faiss", subject="alpha-project", predicate="uses",
                       object="faiss", authored_by="mcp-agentic-write", origin="mcp", valid_from="2026-08-01"))
    assert _retract(server, "clm_legacy").startswith("Withdrew")


def test_a_reason_is_required(srv):
    server, memory = srv
    claim_id = _write(server)
    assert "a reason is required" in _retract(server, claim_id, reason="   ")
    assert _claims(memory)[claim_id].valid_to is None


def test_the_persons_words_become_the_records_evidence(srv):
    server, memory = srv
    claim_id = _write(server)
    _retract(server, claim_id, evidence=[{"episode": "ep_2026-09-02_001", "quote": "ship alpha"}])
    record = _claims(memory)[_claims(memory)[claim_id].superseded_by]
    assert [e.kind for e in record.evidence] == ["user"]


def test_history_says_withdrawn(srv, monkeypatch):
    server, memory = srv
    monkeypatch.setattr(server.mcp_tools, "_relevant_inbox", lambda memory_path, query, **_: [])
    claim_id = _write(server)
    _retract(server, claim_id)
    full = server.handle_tool("cicada_get_perspective", {"subject": "alpha-project", "history": True})
    assert f"withdrawn by claude-code: {REASON}" in full
    # The count is what pins the filter: a listed record would render as its
    # reason text with "closed", and never print the word `retracts`.
    assert "Earlier, newest first (1):" in full, "a record is bookkeeping, never listed as a belief"
    lines = mcp_tools._recent_changes(memory / "entities", [{"entity_id": "alpha-project"}], date.today())
    assert lines == [f'- `alpha-project` uses: "sqlite-vec" withdrawn {TODAY} by claude-code — {REASON}']


def test_a_connection_can_only_withdraw_what_it_wrote(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        runtime = RemoteRuntime(post=lambda path, payload: {}, sleep_running=lambda: False)
        mine = catalog.Connector(id="aaaaaaaa", label="Phone", app="claude", scopes=catalog.DEFAULT_SCOPES,
                                 created_at="2026-09-01T00:00:00+00:00")
        theirs = catalog.Connector(id="bbbbbbbb", label="Laptop", app="chatgpt", scopes=catalog.DEFAULT_SCOPES,
                                   created_at="2026-09-01T00:00:00+00:00")
        text, _ = runtime.call(mine, "cicada_write_claim",
                               {"subject": "alpha-project", "predicate": "uses", "object": "sqlite-vec"})
        claim_id = re.search(r"claim `([^`]+)`", text).group(1)
        args = {"subject": "alpha-project", "claim_id": claim_id, "reason": REASON}
        assert "was not written by this agent" in runtime.call(theirs, "cicada_retract_claim", args)[0]
        assert runtime.call(mine, "cicada_retract_claim", args)[0].startswith("Withdrew")
    finally:
        config.get_settings.cache_clear()
    assert catalog.TOOL_SCOPE["cicada_retract_claim"] == "record"
    assert "cicada_retract_claim" in catalog.WRITE_TOOLS


def test_the_apps_claim_endpoints_never_serve_a_withdrawal_record(srv):
    """Two withdrawals in one context used to surface as a contested
    `retracts` belief listing raw claim ids (final review)."""
    import asyncio

    from api.routers import claims as claims_router

    server, memory = srv
    _retract(server, _write(server, "sqlite-vec"))
    _retract(server, _write(server, "duckdb"))
    assert sum(c.predicate == "retracts" for c in _claims(memory).values()) == 2

    class _Settings:
        memory_path = memory

    listed = asyncio.run(claims_router.get_entity_claims(
        "alpha-project", include_superseded=True, settings=_Settings()))
    assert listed.claims and all(c.predicate != "retracts" for c in listed.claims)
    timeline = asyncio.run(claims_router.get_entity_timeline(
        "alpha-project", predicate="retracts", context="general", settings=_Settings()))
    assert timeline.claims == []


@pytest.fixture
def app_client(srv, monkeypatch):
    """The app's own routes over the same synthetic bank the MCP server wrote."""
    from fastapi.testclient import TestClient

    from api import config, main
    from api.services import bank_index

    _server, memory = srv
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    search_index.reset()
    yield TestClient(main.app)
    search_index.reset()
    bank_index.invalidate()
    config.get_settings.cache_clear()


def _withdraw_with_the_persons_words(server) -> str:
    claim_id = server.handle_tool("cicada_write_claim", {
        "subject": "alpha-project", "predicate": "uses", "object": "sqlite-vec",
        "evidence": [{"episode": "ep_2026-09-02_001", "quote": "ship alpha"}]})
    claim_id = re.search(r"claim `([^`]+)`", claim_id).group(1)
    _retract(server, claim_id, evidence=[{"episode": "ep_2026-09-02_001", "quote": "ship alpha"}])
    return claim_id


def test_search_never_serves_a_withdrawal_record_as_a_belief(srv, app_client):
    """A record indexed as a claim came back from `/search` named with the
    agent's reason, and the find palette listed it under "Beliefs" (final
    review). The withdrawn claim itself stays searchable: that is history."""
    server, memory = srv
    claim_id = _withdraw_with_the_persons_words(server)
    record_id = _claims(memory)[claim_id].superseded_by
    search_index.ensure_fresh(memory, wait=True)  # else "building" and every leg is vacuously empty
    reason = app_client.get("/search", params={"q": "engine", "kinds": "claim", "mode": "prefix"})
    assert reason.status_code == 200, reason.text
    assert reason.json()["indexState"] == "ready"
    assert [h for h in reason.json()["results"] if h["kind"] == "claim"] == []
    history = app_client.get("/search", params={"q": "sqlite", "kinds": "claim", "mode": "prefix"}).json()
    ids = {h.get("claimId") or h.get("id") for h in history["results"] if h["kind"] == "claim"}
    assert claim_id in ids and record_id not in ids


def test_episode_citations_never_list_a_withdrawal_record(srv, app_client):
    """Listed, the reader showed the agent's reason struck through under
    "Noted from this conversation" as a "No longer current" belief (final
    review). The withdrawn claim is still cited — closed, not hidden."""
    server, memory = srv
    claim_id = _withdraw_with_the_persons_words(server)
    record_id = _claims(memory)[claim_id].superseded_by
    got = app_client.get("/episodes/ep_2026-09-02_001/citations")
    assert got.status_code == 200, got.text
    rows = {c["claimId"]: c for c in got.json()["citations"]}
    assert record_id not in rows
    assert rows[claim_id]["current"] is False
