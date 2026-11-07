"""ROR-126 — the person's yes per provider, and the agent's report through ``cicada_export_requests``."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_intake import _client  # noqa: E402

from api.services import export_requests as er  # noqa: E402


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    return tmp_path / "bank"


def test_a_yes_is_per_provider_and_the_agent_can_only_report_on_a_granted_one(bank):
    bank.mkdir()
    er.grant(bank, "claude")
    assert [r["vendor"] for r in er.rows(bank)] == ["claude"]
    with pytest.raises(er.RequestError):
        er.report(bank, "chatgpt", "requested")
    row = er.report(bank, "claude", "requested", harness="agent-x")
    assert row["state"] == "requested" and row["requested_at"] and row["harness"] == "agent-x"
    er.report(bank, "claude", "manual", reason="a captcha stopped it")
    assert er.rows(bank)[0]["state"] == "manual" and er.rows(bank)[0]["reason"] == "a captcha stopped it"
    assert er.clear(bank, "claude") is True and er.clear(bank, "claude") is False and er.rows(bank) == []


def test_a_request_older_than_the_waits_own_limit_is_gone(bank):
    bank.mkdir()
    long_ago = datetime.now(timezone.utc) - er.MAX_AGE - timedelta(hours=1)
    er.grant(bank, "gemini", now=long_ago)
    assert er.rows(bank) == []


def test_the_file_holds_ids_and_enums_outside_the_bank(bank):
    bank.mkdir()
    er.grant(bank, "chatgpt")
    target = er.path_for(bank)
    assert str(target).startswith(str(bank.parent / "home")) and not (bank / target.name).exists()
    assert oct(target.stat().st_mode & 0o777) == "0o600"


def test_the_routes_grant_list_and_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    client = _client(tmp_path, monkeypatch)
    assert client.post("/export-requests/nope").status_code == 422
    assert client.post("/export-requests/claude").json()["state"] == "asked"
    assert [r["vendor"] for r in client.get("/export-requests").json()["requests"]] == ["claude"]
    assert client.delete("/export-requests/claude").json() == {"cleared": True}
    assert client.get("/export-requests").json()["requests"] == []
