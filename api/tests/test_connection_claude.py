from __future__ import annotations

import asyncio
import json

from api.services.connections import claude_cli
from api.services.connections.base import CliResult


def _runner(rc=0, stdout="", stderr=""):
    calls: list[list[str]] = []

    async def run(argv):
        calls.append(argv)
        return CliResult(rc, stdout, stderr)

    run.calls = calls  # type: ignore[attr-defined]
    return run


LOGGED_IN = json.dumps({
    "loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty",
    "email": "r@example.com", "orgName": "Personal", "subscriptionType": "max",
})


def test_status_connected_max_without_tier(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/usr/local/bin/claude")
    run = _runner(stdout=LOGGED_IN)
    adapter = claude_cli.ClaudePlanAdapter(runner=run)
    s = asyncio.run(adapter.status())
    assert run.calls == [["claude", "auth", "status", "--json"]]
    assert s.available and s.connected
    assert s.plan == "max" and s.plan_label == "Claude Max"
    assert s.account == "r@example.com"
    assert s.price_usd_month is None and "pick your tier" in s.price_note
    assert s.billing == "subscription" and s.engine_role == "subscription-cli"


def test_status_connected_max_with_tier(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/usr/local/bin/claude")
    adapter = claude_cli.ClaudePlanAdapter(runner=_runner(stdout=LOGGED_IN), tier="20x")
    s = asyncio.run(adapter.status())
    assert s.price_usd_month == 200.0 and s.plan_label == "Claude Max 20x" and s.tier == "20x"


def test_status_connected_with_unknown_plan(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/usr/local/bin/claude")
    out = json.dumps({
        "loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty",
        "email": "r@example.com", "orgName": "Personal", "subscriptionType": "",
    })
    adapter = claude_cli.ClaudePlanAdapter(runner=_runner(stdout=out))
    s = asyncio.run(adapter.status())
    assert s.connected and s.plan is None
    assert s.price_usd_month is None
    assert s.price_note == "plan not detected — run the CLI once to refresh"


def test_status_logged_out(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/usr/local/bin/claude")
    adapter = claude_cli.ClaudePlanAdapter(runner=_runner(stdout='{"loggedIn": false}'))
    s = asyncio.run(adapter.status())
    assert s.available and not s.connected and s.plan is None
    assert s.login.mode == "terminal" and s.login.command == "claude auth login"


def test_status_not_installed(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: None)
    adapter = claude_cli.ClaudePlanAdapter(runner=_runner(rc=127))
    s = asyncio.run(adapter.status())
    assert not s.available and not s.connected and "install" in s.detail.lower()


def test_status_binary_vanishes_between_which_and_exec(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/usr/local/bin/claude")
    adapter = claude_cli.ClaudePlanAdapter(runner=_runner(rc=127, stderr="claude: not found"))
    s = asyncio.run(adapter.status())
    assert not s.available and not s.connected
    assert "install" in s.detail.lower()


def test_status_garbage_output_degrades(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/usr/local/bin/claude")
    adapter = claude_cli.ClaudePlanAdapter(runner=_runner(stdout="not json"))
    s = asyncio.run(adapter.status())
    assert s.available and not s.connected and "could not parse" in s.detail


def test_api_key_auth_is_not_a_plan_connection(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/usr/local/bin/claude")
    out = json.dumps({"loggedIn": True, "authMethod": "apiKey", "apiProvider": "firstParty"})
    s = asyncio.run(claude_cli.ClaudePlanAdapter(runner=_runner(stdout=out)).status())
    assert not s.connected and "API key" in s.detail


def test_logout_runs_cli():
    run = _runner()
    asyncio.run(claude_cli.ClaudePlanAdapter(runner=run).logout())
    assert run.calls == [["claude", "auth", "logout"]]


def test_begin_login_is_terminal_handoff():
    sess = asyncio.run(claude_cli.ClaudePlanAdapter(runner=_runner()).begin_login())
    assert sess.mode == "terminal" and sess.command == "claude auth login" and sess.state == "pending"
