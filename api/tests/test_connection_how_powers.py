"""Every adapter must explain itself (G63).

"Connected" on the Claude card means `claude auth status --json` reported a
claude.ai login for the Claude Code CLI on this Mac — the page never said so.
`how` is that sentence, authored next to the probe that decided it; `powers`
says what the connection is actually doing right now.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from api.config import Settings
from api.services.connections import byok, claude_cli, codex_cli, ollama, registry
from api.services.connections.base import CliResult


def run(coro):
    return asyncio.run(coro)


def _claude_runner(payload: dict):
    async def fake(argv):
        if argv[:3] == ["claude", "auth", "status"]:
            return CliResult(0, json.dumps(payload), "")
        return CliResult(0, "", "")
    return fake


def test_claude_how_names_the_cli_the_mac_and_the_account(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda name: "/usr/local/bin/claude")
    adapter = claude_cli.ClaudePlanAdapter(runner=_claude_runner(
        {"loggedIn": True, "authMethod": "claude.ai", "email": "r@example.com",
         "subscriptionType": "max"}))
    status = run(adapter.status())
    assert status.connected
    assert status.how == (
        "Signed in to Claude Code on this Mac as `r@example.com`. Cicada runs its "
        "memory work through the `claude` CLI on your plan — it never sees your token."
    )


def test_claude_how_is_absent_when_not_connected(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda name: "/usr/local/bin/claude")
    adapter = claude_cli.ClaudePlanAdapter(runner=_claude_runner({"loggedIn": False}))
    status = run(adapter.status())
    assert status.connected is False
    assert status.how is None


def test_codex_how_names_codex_exec(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda name: "/usr/local/bin/codex")

    async def fake(argv):
        return CliResult(0, "Logged in", "")

    (tmp_path / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {}}))
    adapter = codex_cli.CodexPlanAdapter(runner=fake, codex_home=tmp_path)
    status = run(adapter.status())
    assert status.connected
    assert status.how == (
        "Signed in to Codex CLI on this Mac. Cicada runs through `codex exec` "
        "on your ChatGPT plan."
    )


def test_byok_how_names_the_secrets_file_and_the_provider(monkeypatch):
    monkeypatch.setattr(byok.secrets, "has_secret", lambda _var: True)
    adapter = byok.ByokAdapter("openai")
    status = run(adapter.status())
    assert status.connected
    assert status.how == (
        f"Key stored in {byok.secrets.secrets_path()} (0600); billed per token by OpenAI."
    )


def test_ollama_how_names_the_local_endpoint():
    settings = Settings()

    async def tags(_url):
        return [settings.ollama_model]

    adapter = ollama.OllamaAdapter(settings, fetch_tags=tags)
    status = run(adapter.status())
    assert status.connected
    assert status.how == f"Local models at `{settings.ollama_base_url}` — free."


def test_every_adapter_defines_how_when_connected(monkeypatch, tmp_path):
    """Regression net: a new adapter that forgets `how` is caught here."""
    monkeypatch.setattr(claude_cli.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(byok.secrets, "has_secret", lambda _var: True)
    settings = Settings()

    async def tags(_url):
        return [settings.ollama_model]

    adapters = [
        claude_cli.ClaudePlanAdapter(runner=_claude_runner(
            {"loggedIn": True, "authMethod": "claude.ai", "email": "r@example.com",
             "subscriptionType": "max"})),
        *[byok.ByokAdapter(p) for p in byok.BYOK_PROVIDERS],
        ollama.OllamaAdapter(settings, fetch_tags=tags),
    ]
    for adapter in adapters:
        status = run(adapter.status())
        assert status.connected, adapter.id
        assert status.how, f"{adapter.id} is connected but has no `how` line"


def test_powers_go_to_the_selected_engine_and_standby_to_the_rest():
    from api.models.schemas import ConnectionKind, ConnectionStatus

    def make(cid, connected, role=None):
        return ConnectionStatus(id=cid, label=cid, kind=ConnectionKind.subscription,
                                available=True, connected=connected, engine_role=role)

    statuses = [
        make("claude-plan", True, "subscription-cli"),
        make("chatgpt-plan", True, "subscription-cli"),
        make("byok-openai", False),
    ]
    registry.Registry.assign_powers(statuses)
    assert statuses[0].powers == registry.ENGINE_POWERS
    assert statuses[1].powers == registry.STANDBY_POWERS
    assert statuses[2].powers == []


def test_powers_are_empty_when_nothing_is_connected():
    from api.models.schemas import ConnectionKind, ConnectionStatus

    statuses = [ConnectionStatus(id="ollama-local", label="Ollama", kind=ConnectionKind.local)]
    registry.Registry.assign_powers(statuses)
    assert statuses[0].powers == []


def test_single_connection_status_carries_the_same_powers_as_the_full_set():
    """MED-4: `GET /connections/{id}` (and the login poll, and every mutation)
    used to return `powers: []` because only `statuses()` assigned them — the
    app writes that row straight into its store, so a card visibly lost its
    "Powers" line for the whole 5 minutes of login polling."""
    from api.models.schemas import ConnectionKind, ConnectionStatus

    class FakeAdapter:
        def __init__(self, cid, connected):
            self.id, self._connected = cid, connected

        async def status(self):
            return ConnectionStatus(id=self.id, label=self.id, kind=ConnectionKind.subscription,
                                    available=True, connected=self._connected)

    reg = registry.Registry(Settings(memory_path="/tmp/does-not-exist"))
    reg.adapters = lambda: [FakeAdapter("claude-plan", True),
                            FakeAdapter("chatgpt-plan", True),
                            FakeAdapter("byok-openai", False)]

    assert run(reg.status_with_powers("claude-plan")).powers == registry.ENGINE_POWERS
    assert run(reg.status_with_powers("chatgpt-plan")).powers == registry.STANDBY_POWERS
    assert run(reg.status_with_powers("byok-openai")).powers == []
