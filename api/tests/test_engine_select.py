"""G74(a) Task 7 — which engine a Sleep cycle resolves to, and why."""
from __future__ import annotations

import asyncio

from api.config import Settings
from api.models.schemas import ConnectionKind, ConnectionStatus
from api.services import engine_select


class _FakeRegistry:
    def __init__(self, *, prefs=None, connected=()):
        self._prefs = prefs or {}
        self._connected = set(connected)

    def prefs(self):
        return self._prefs

    async def status(self, connection_id, fresh=False):
        return ConnectionStatus(id=connection_id, label=connection_id,
                                kind=ConnectionKind.subscription, available=True,
                                connected=connection_id in self._connected)


def _resolve(settings, registry):
    return asyncio.run(engine_select.resolve_llm_mode(settings, registry))


def test_an_explicit_agent_mode_wins_without_probing():
    class _Boom:
        def prefs(self):
            raise AssertionError("probed despite an explicit mode")

    mode, why = _resolve(Settings(llm_mode="agent"), _Boom())
    assert mode == "agent" and "CICADA_LLM_MODE" in why


def test_an_explicit_local_mode_wins_without_probing():
    class _Boom:
        def prefs(self):
            raise AssertionError("probed despite an explicit mode")

    assert _resolve(Settings(llm_mode="local"), _Boom())[0] == "local"


def test_the_default_install_is_unchanged():
    """byok + no toggle = byok. Every existing install stays byte-identical."""
    mode, why = _resolve(Settings(), _FakeRegistry(connected={"claude-plan"}))
    assert mode == "byok" and "no Sleep engine chosen" in why


def test_the_use_for_sleep_toggle_selects_the_agent_rung_on_a_default_install():
    reg = _FakeRegistry(prefs={"claude-plan": {"use_for_sleep": True}},
                        connected={"claude-plan"})
    mode, why = _resolve(Settings(), reg)
    assert mode == "agent" and "Sleep engine" in why


def test_the_toggle_degrades_to_byok_when_the_plan_is_disconnected():
    reg = _FakeRegistry(prefs={"claude-plan": {"use_for_sleep": True}}, connected=set())
    mode, why = _resolve(Settings(), reg)
    assert mode == "byok" and "not connected" in why


def test_auto_prefers_the_plan_then_ollama_then_byok():
    assert _resolve(Settings(llm_mode="auto"),
                    _FakeRegistry(connected={"claude-plan", "ollama-local"}))[0] == "agent"
    assert _resolve(Settings(llm_mode="auto"),
                    _FakeRegistry(connected={"ollama-local"}))[0] == "local"
    assert _resolve(Settings(llm_mode="auto"), _FakeRegistry())[0] == "byok"


def test_a_probe_failure_degrades_instead_of_raising():
    class _Broken(_FakeRegistry):
        async def status(self, connection_id, fresh=False):
            raise RuntimeError("CLI exploded")

    mode, why = _resolve(Settings(llm_mode="auto"), _Broken())
    assert mode == "byok" and "could not probe" in why


def test_resolve_settings_returns_a_copy_with_a_concrete_mode():
    reg = _FakeRegistry(connected={"claude-plan"})
    original = Settings(llm_mode="auto")
    resolved, _why = asyncio.run(engine_select.resolve_settings(original, reg))
    assert resolved.llm_mode == "agent"
    assert original.llm_mode == "auto"        # never mutated in place


def test_engine_label_maps_every_concrete_mode():
    assert engine_select.engine_label(Settings(llm_mode="agent")) == "claude-cli"
    assert engine_select.engine_label(Settings(llm_mode="local")) == "ollama"
    assert engine_select.engine_label(Settings(llm_mode="byok")) == "litellm"
    # An unresolved "auto" reaching a label call is byok's behaviour (providers
    # degrades it the same way) — never a crash.
    assert engine_select.engine_label(Settings(llm_mode="auto")) == "litellm"


def test_the_prefs_round_trip_through_the_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import main
    from api.services.connections import registry as reg_mod

    monkeypatch.setenv("CICADA_HOME", str(tmp_path))
    reg_mod.reset_registry()
    client = TestClient(main.app)

    body = client.put("/connections/claude-plan/prefs", json={"useForSleep": True}).json()
    assert body["useForSleep"] is True

    rejected = client.put("/connections/byok-openai/prefs", json={"useForSleep": True})
    assert rejected.status_code == 400
