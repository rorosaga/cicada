"""Round 4 C2 (R4B-5): every claim an agent writes through the MCP seam — stdio
or remote — carries `recorded_ts`, the second it landed, so it can be joined to
the turn it was written in. Nothing else stamps one. Synthetic bank."""
from __future__ import annotations

import re

import pytest

from _synthetic_bank import _bank
from api.remote import catalog
from api.services import agentic_write, episode_ids, markdown_parser, mcp_tools
from api.services.claims import Claim, parse_claims

TS = "2026-09-24T10:31:02Z"


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_tools, "_now_ts", lambda: TS)
    return _bank(tmp_path)


def _ctx(bank, **kw):
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_test", harness="claude-code", **kw)


def _claims(bank, stem="alpha-project"):
    return parse_claims(markdown_parser.parse(bank / "entities" / f"{stem}.md").body)


def test_the_clock_is_seconds_in_utc():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", episode_ids.utc_now_seconds())


def test_a_stdio_write_is_stamped_to_the_second(bank):
    mcp_tools.write_claim(_ctx(bank), "alpha-project", "uses", "sqlite-vec", "agent", 0.8, None, None)
    [c] = [c for c in _claims(bank) if c.object == "sqlite-vec"]
    assert (c.recorded_ts, c.session_id) == (TS, "ses_test")


def test_a_remote_write_is_stamped_too(bank):
    ctx = _ctx(bank, connector_id="ab12cd34", available=catalog.tool_names_for(catalog.DEFAULT_SCOPES),
               read_surface="remote")
    mcp_tools.write_claim(ctx, "alpha-project", "uses", "duckdb", "agent", 0.8, None, None)
    [c] = [c for c in _claims(bank) if c.object == "duckdb"]
    assert (c.recorded_ts, c.origin) == (TS, "remote:ab12cd34")


def test_note_progress_is_stamped(bank):
    out = mcp_tools.note_progress(_ctx(bank), "alpha-project", "happened", "Shipped the alpha-project index", "done")
    assert "Not recorded" not in out, out
    [c] = [c for c in _claims(bank) if c.predicate == "happened"]
    assert c.recorded_ts == TS


def test_an_in_process_write_carries_none_and_writes_no_key(bank):
    agentic_write.write_claim(bank, "alpha-project", "uses", "postgres", observer="agent")
    [c] = [c for c in _claims(bank) if c.object == "postgres"]
    assert c.recorded_ts is None
    assert "recorded_ts" not in (bank / "entities" / "alpha-project.md").read_text(encoding="utf-8")


def test_a_reinforce_keeps_the_first_writers_second(bank, monkeypatch):
    mcp_tools.write_claim(_ctx(bank), "alpha-project", "uses", "sqlite-vec", "agent", 0.8, None, None)
    monkeypatch.setattr(mcp_tools, "_now_ts", lambda: "2026-09-25T08:00:00Z")
    mcp_tools.write_claim(_ctx(bank), "alpha-project", "uses", "sqlite-vec", "agent", 0.9, None, None)
    [c] = [c for c in _claims(bank) if c.object == "sqlite-vec"]
    assert c.recorded_ts == TS  # pairs with the first writer's session_id and authored_by


def test_the_field_round_trips_and_is_omitted_when_unset():
    assert Claim.from_dict(Claim(id="c1", text="t", recorded_ts=TS).to_dict()).recorded_ts == TS
    assert "recorded_ts" not in Claim(id="c2", text="t").to_dict()
