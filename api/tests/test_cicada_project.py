"""G141 PJ-2 — agents read a project (R-PJ23, R12 for tool output)."""
from datetime import datetime, timezone

import pytest

from _demo_scenario import T, d, day_one
from api.remote import catalog
from api.services import handshake, mcp_tools, telemetry


@pytest.fixture
def bank(tmp_path, monkeypatch):
    b = day_one(tmp_path)
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    monkeypatch.setattr(mcp_tools, "_today_in", lambda tz: T)   # the tool's one clock seam
    return b


def _ctx(bank, *, remote_scopes=None):
    kw = {}
    if remote_scopes is not None:
        kw = {"connector_id": "abcd1234", "available": catalog.tool_names_for(remote_scopes),
              "raw_excerpts": "sources" in remote_scopes, "read_surface": "remote"}
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_test", harness="claude-code", **kw)


def test_the_local_reply_prints_both_date_forms_and_the_quote(bank):
    out = mcp_tools.project(_ctx(bank), "Rover Arm Project")
    assert out.startswith("Rover Arm Project — planned · 0 of 4 milestones done · last activity today (2026-09-23)")
    assert f"Next: Pick And Place Demo — {d(12)}, in 12 days" in out
    assert "Passed, no word on how it went: Arm assembled" in out
    assert "Waiting for Sleep: 1 conversation from today" in out
    assert '"Yesterday Hana Example sent me' in out           # the washed quote, locally
    # T5: a stdio caller holds every tool, cicada_note_progress included (R12 for tool output).
    assert out.rstrip().endswith("Open a page with cicada_recall_detail(entity_id); record progress with "
                                 "cicada_note_progress (settles=<claim id> to finish a thread above).")


def test_a_remote_connection_without_sources_sees_no_quote(bank):
    out = mcp_tools.project(_ctx(bank, remote_scopes={"search", "read"}), "rover-arm-project")
    assert "Yesterday Hana" not in out and "Hana Example provides Lab Cluster Onboarding Guide" in out
    with_sources = mcp_tools.project(_ctx(bank, remote_scopes={"search", "read", "sources"}), "rover-arm-project")
    assert "Yesterday Hana" in with_sources


def test_a_non_project_and_an_unknown_name_are_one_line_answers(bank):
    assert "is a tool, not a project" in mcp_tools.project(_ctx(bank), "lab-cluster-example")
    assert mcp_tools.project(_ctx(bank), "nothing-like-it").startswith("No project")


def test_the_read_is_recorded_ids_only(bank, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    mcp_tools.project(_ctx(bank), "rover-arm-project")
    reads = [e for e in telemetry.read_events() if e.kind == "read"]
    assert reads[-1].refs == {"entity_id": "rover-arm-project", "surface": "mcp-project"}
    ledger = "".join(p.read_text() for p in telemetry.telemetry_dir().glob("*.jsonl"))
    assert "Yesterday" not in ledger and "Hana" not in ledger
