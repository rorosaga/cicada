"""G74(a) Task 7 — which engine a Sleep cycle resolves to, and why."""
from __future__ import annotations

import asyncio
import json

import pytest

from api.config import Settings
from api.models.schemas import ConnectionKind, ConnectionStatus
from api.services import engine_select
from api.services.connections.base import CliResult


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


def test_the_default_install_never_probes_even_when_the_plan_would_connect():
    """Fix round 1, L4: the test above uses a registry where claude-plan IS
    connected, so it can't tell "we chose byok because unconnected" apart
    from "we chose byok WITHOUT EVER PROBING". Prove the latter directly."""
    class _Boom(_FakeRegistry):
        async def status(self, connection_id, fresh=False):
            raise AssertionError("probed despite byok + no toggle")

    mode, why = _resolve(Settings(), _Boom())
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


def test_an_unrecognized_llm_mode_degrades_to_byok_without_probing():
    """Fix round 1, L3: `llm_mode` is a bare `str` — a typo (or a future
    value this module doesn't know yet) must never silently escalate into
    the agent rung just because it isn't literally "byok"."""
    class _Boom:
        def prefs(self):
            raise AssertionError("probed despite an unrecognized llm_mode")

    mode, why = _resolve(Settings(llm_mode="atuo"), _Boom())
    assert mode == "byok" and "unrecognized" in why


# --------------------------------------------------------------------------- #
# Fix round 1, H1/H2 — trigger scope: the toggle/auto rungs are
# user-triggered only. A scheduled cycle must never spend plan quota
# unattended, matching `Copy.sleepEngineExplainer`'s literal promise.
# --------------------------------------------------------------------------- #

def test_a_scheduled_cycle_never_selects_the_agent_rung_even_with_the_toggle_on():
    class _Boom(_FakeRegistry):
        async def status(self, connection_id, fresh=False):
            raise AssertionError("a scheduled cycle probed the registry")

    reg = _Boom(prefs={"claude-plan": {"use_for_sleep": True}}, connected={"claude-plan"})
    mode, why = asyncio.run(
        engine_select.resolve_llm_mode(Settings(), reg, user_triggered=False)
    )
    assert mode == "byok"
    assert "user-triggered" in why


def test_a_scheduled_cycle_with_auto_mode_also_stays_on_byok():
    class _Boom(_FakeRegistry):
        async def status(self, connection_id, fresh=False):
            raise AssertionError("a scheduled cycle probed the registry")

    reg = _Boom(connected={"claude-plan", "ollama-local"})
    mode, _why = asyncio.run(
        engine_select.resolve_llm_mode(Settings(llm_mode="auto"), reg, user_triggered=False)
    )
    assert mode == "byok"


def test_an_explicit_agent_mode_still_wins_on_a_scheduled_cycle():
    """The trigger gate only scopes the NEW toggle/auto resolution paths —
    deliberate `CICADA_LLM_MODE=agent` config predates this task and is
    "the existing engine selection" spec §7 says the scheduler keeps."""
    class _Boom:
        def prefs(self):
            raise AssertionError("probed despite an explicit mode")

    mode, _why = asyncio.run(
        engine_select.resolve_llm_mode(Settings(llm_mode="agent"), _Boom(), user_triggered=False)
    )
    assert mode == "agent"


def test_resolve_settings_forces_byok_on_a_scheduled_cycle_with_the_toggle_on():
    reg = _FakeRegistry(prefs={"claude-plan": {"use_for_sleep": True}},
                        connected={"claude-plan"})
    resolved, why = asyncio.run(
        engine_select.resolve_settings(Settings(), reg, user_triggered=False)
    )
    assert resolved.llm_mode == "byok"
    assert "user-triggered" in why


# --------------------------------------------------------------------------- #
# Fix round 1, M2 — a duck-typed Settings stand-in must never reach the
# registry at all, regardless of what a real ~/.cicada/connections.json on
# the machine running the test happens to hold.
# --------------------------------------------------------------------------- #

def test_a_duck_typed_settings_stand_in_never_probes():
    from types import SimpleNamespace

    class _Boom:
        def prefs(self):
            raise AssertionError("probed a duck-typed Settings stand-in")

    stand_in = SimpleNamespace(litellm_model="gpt-5.4-mini")  # no llm_mode, no model_copy
    mode, why = _resolve(stand_in, _Boom())
    assert mode == "byok" and "no Sleep engine chosen" in why


def test_resolve_settings_returns_a_duck_typed_stand_in_unchanged():
    from types import SimpleNamespace

    stand_in = SimpleNamespace(litellm_model="gpt-5.4-mini")
    resolved, _why = asyncio.run(engine_select.resolve_settings(stand_in, _FakeRegistry()))
    assert resolved is stand_in


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


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    """Fix round 1, M3: `PUT .../prefs?fresh=true` re-probes the WHOLE
    registry (every connection's `status()`, for `powers`) — an unpatched
    `TestClient` reached the real `claude`/`codex` CLIs and an Ollama HTTP
    probe. Mirrors `test_connections_api.py`'s `client` fixture so this
    round trip is exactly as hermetic as every other connections test."""
    from fastapi.testclient import TestClient

    from api import config, main
    from api.services.connections import base, registry as reg_mod

    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "memory"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    config.get_settings.cache_clear()
    reg_mod.reset_registry()

    async def fake_run(argv):
        if argv[:3] == ["claude", "auth", "status"]:
            return CliResult(0, json.dumps({"loggedIn": True, "authMethod": "claude.ai",
                                            "email": "r@example.com", "subscriptionType": "max"}), "")
        if argv[:3] == ["codex", "login", "status"]:
            return CliResult(1, "", "Not logged in")
        return CliResult(0, "", "")

    monkeypatch.setattr(base, "run_cli", fake_run)
    monkeypatch.setattr(reg_mod.shutil, "which", lambda name: f"/usr/local/bin/{name}")

    async def no_tags(_url):
        raise ConnectionError("no ollama in tests")

    monkeypatch.setattr(reg_mod, "_ollama_fetch_tags", no_tags)
    client = TestClient(main.app)
    yield client
    reg_mod.reset_registry()
    config.get_settings.cache_clear()


def test_the_prefs_round_trip_through_the_api(api_client):
    body = api_client.put("/connections/claude-plan/prefs", json={"useForSleep": True}).json()
    assert body["useForSleep"] is True

    rejected = api_client.put("/connections/byok-openai/prefs", json={"useForSleep": True})
    assert rejected.status_code == 400


# --------------------------------------------------------------------------- #
# G122 — the prefs rung. Precedence table (highest wins):
#
#   1. `CICADA_LLM_MODE` explicitly set (`env_explicit`)        -> that mode, zero registry touch for the mode itself
#   2. a real Settings, env NOT explicit, `sleep-engine` pref set -> the pref's mode (R2's shape gate)
#   3. a duck-typed Settings stand-in (no `model_fields_set`)   -> byok, zero registry touch (unchanged, R2)
#   4. real Settings, no pref, nothing configured                -> byok/auto probe path (unchanged)
#
# Ruling 4/R3 still applies ON TOP of rung 2: a prefs-chosen "agent" degrades
# to byok on a scheduled cycle exactly like an "auto"-resolved "agent" would.
# --------------------------------------------------------------------------- #

def test_prefs_mode_applies_when_env_is_not_explicit():
    reg = _FakeRegistry(prefs={engine_select.SLEEP_ENGINE_PREF_KEY: {"mode": "local"}})
    mode, why = _resolve(Settings(), reg)
    assert mode == "local"
    assert "Settings" in why


def test_prefs_agent_still_degrades_to_byok_on_a_scheduled_cycle():
    reg = _FakeRegistry(prefs={engine_select.SLEEP_ENGINE_PREF_KEY: {"mode": "agent"}})
    mode, why = asyncio.run(
        engine_select.resolve_llm_mode(Settings(), reg, user_triggered=False)
    )
    assert mode == "byok"


def test_prefs_agent_wins_on_a_user_triggered_cycle_when_claude_is_connected():
    reg = _FakeRegistry(
        prefs={engine_select.SLEEP_ENGINE_PREF_KEY: {"mode": "agent"}},
        connected={engine_select.CLAUDE_CONNECTION_ID},
    )
    mode, why = asyncio.run(
        engine_select.resolve_llm_mode(Settings(), reg, user_triggered=True)
    )
    assert mode == "agent"


def test_explicit_env_ignores_prefs_entirely():
    reg = _FakeRegistry(prefs={engine_select.SLEEP_ENGINE_PREF_KEY: {"mode": "agent"}})
    mode, _why = _resolve(Settings(llm_mode="byok"), reg)
    # An explicit env pin runs the normal byok/auto probe path — no prefs
    # short-circuit to "agent" from the pref, no probe of claude-plan either
    # (byok with no `use_for_sleep` toggle degrades straight to byok).
    assert mode == "byok"


def test_duck_typed_settings_never_touches_the_registry_for_prefs():
    from types import SimpleNamespace

    class _Boom:
        def prefs(self):
            raise AssertionError("probed a duck-typed Settings stand-in for prefs")

    stand_in = SimpleNamespace(llm_mode=None)  # no model_fields_set
    mode, why = _resolve(stand_in, _Boom())
    assert mode == "byok"
