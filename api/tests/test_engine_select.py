"""G74(a) Task 7 — which engine a Sleep cycle resolves to, and why."""
from __future__ import annotations

import asyncio
import json

import pytest

from api.config import Settings
from api.models.schemas import ConnectionKind, ConnectionStatus
from api.services import engine_select
from api.services.connections.base import CliResult


#: The shipped engine default (auto since 2026-10-19), not the suite's chosen key (conftest).
pytestmark = pytest.mark.shipped_engine_default


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


#: The person's explicit off for "Scheduled runs may use my plan" (ruling 4b; on by default since 2026-10-19).
PLAN_OFF = {"sleep-run": {"scheduled_use_plan": False}}


class _Probes(_FakeRegistry):
    """Records every connection it is asked about."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.asked: list[str] = []

    async def status(self, connection_id, fresh=False):
        self.asked.append(connection_id)
        return await super().status(connection_id, fresh)


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


def test_the_default_install_reads_with_the_plan_first(monkeypatch):
    """Owner 2026-10-19: "the defaults now are either the Claude plan or the Codex/ChatGPT plan" — nobody chose,
    so Auto: the Claude plan first, even with an API key in the environment."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-example")
    assert Settings().llm_mode == "auto"
    assert _resolve(Settings(), _FakeRegistry(connected={"claude-plan", "byok-openrouter"}))[0] == "agent"
    assert _resolve(Settings(), _FakeRegistry(connected={"chatgpt-plan", "byok-openrouter"}))[0] == "codex"


def test_the_default_install_never_falls_to_a_metered_key(monkeypatch):
    """No plan, no local model: no engine — never the configured API model by itself, key or no key."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-example")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-example")
    reg = _FakeRegistry(connected={"byok-openrouter", "byok-openai"})
    mode, why = _resolve(Settings(litellm_model="openrouter/z-ai/example"), reg)
    assert (mode, why) == ("auto", engine_select.NO_ENGINE)
    resolved, _why = asyncio.run(engine_select.resolve_settings(Settings(litellm_model="openrouter/z-ai/example"), reg))
    assert engine_select.no_engine(resolved) and resolved.llm_mode == "auto"
    assert engine_select.engine_label(resolved) == "none" and engine_select.shown_model(resolved) == ""
    assert "API key is used only when you choose it" in resolved.no_engine_reason


def test_a_resolved_no_engine_copy_refuses_every_call_before_it_is_made():
    from api.services import providers
    from api.services.engine_errors import EngineUnavailable

    sent = []
    resolved, _why = asyncio.run(engine_select.resolve_settings(Settings(), _FakeRegistry()))
    fn = providers.resolve_llm_fn(resolved, completion=lambda **kw: sent.append(kw), sink=lambda _e: None)
    with pytest.raises(EngineUnavailable, match="No engine"):
        fn(messages=[{"role": "user", "content": "hi"}])

    async def acompletion(**kw):
        sent.append(kw)

    afn = providers.resolve_llm_fn(resolved, completion=acompletion, sink=lambda _e: None)
    with pytest.raises(EngineUnavailable):
        asyncio.run(afn(messages=[{"role": "user", "content": "hi"}]))
    assert sent == []


def test_an_unresolved_auto_refuses_every_call_instead_of_billing_the_key(monkeypatch):
    """Review of #360: a caller that never resolved (the dedup sweep did not) must not fall to the API model."""
    from api.services import providers
    from api.services.engine_errors import EngineUnavailable

    monkeypatch.setenv("OPENAI_API_KEY", "sk-example")
    sent = []
    fn = providers.resolve_llm_fn(Settings(), completion=lambda **kw: sent.append(kw), sink=lambda _e: None)
    with pytest.raises(EngineUnavailable, match="never falls to an API key"):
        fn(messages=[{"role": "user", "content": "hi"}])
    assert sent == []
    chosen = providers.resolve_llm_fn(Settings(llm_mode="byok"), completion=lambda **kw: sent.append(kw) or {},
                                      sink=lambda _e: None)
    chosen(messages=[{"role": "user", "content": "hi"}])
    assert len(sent) == 1, "a key the person chose still reads"


def test_the_no_engine_sentence_names_the_server_fix_too():
    assert "`cicada engine connect claude-plan`" in engine_select.no_engine_sentence(engine_select.NO_ENGINE)
    assert "--use-plan on" in engine_select.no_engine_sentence(engine_select.SCHEDULE_DEGRADED)


def test_the_use_for_sleep_toggle_selects_the_agent_rung_on_a_chosen_key():
    reg = _FakeRegistry(prefs={"claude-plan": {"use_for_sleep": True}},
                        connected={"claude-plan"})
    mode, why = _resolve(Settings(llm_mode="byok"), reg)
    assert mode == "agent" and "Sleep engine" in why


def test_the_toggle_degrades_to_the_chosen_key_when_the_plan_is_disconnected():
    reg = _FakeRegistry(prefs={"claude-plan": {"use_for_sleep": True}}, connected=set())
    mode, why = _resolve(Settings(llm_mode="byok"), reg)
    assert mode == "byok" and "not connected" in why


def test_a_chosen_key_reads_with_the_key_without_probing():
    class _Boom(_FakeRegistry):
        async def status(self, connection_id, fresh=False):
            raise AssertionError("probed despite a chosen key and no toggle")

    assert _resolve(Settings(llm_mode="byok"), _Boom(connected={"claude-plan"}))[0] == "byok"
    picked = _Boom(prefs={"sleep-engine": {"mode": "byok", "model": "openrouter/z-ai/example"}})
    resolved, _why = asyncio.run(engine_select.resolve_settings(Settings(), picked))
    assert (resolved.llm_mode, resolved.litellm_model) == ("byok", "openrouter/z-ai/example")
    assert not engine_select.no_engine(resolved)


def test_auto_prefers_the_plan_then_no_engine_never_a_local_model():
    assert _resolve(Settings(llm_mode="auto"),
                    _FakeRegistry(connected={"claude-plan", "ollama-local"}))[0] == "agent"
    assert _resolve(Settings(llm_mode="auto"),
                    _FakeRegistry(connected={"ollama-local"})) == ("auto", engine_select.NO_ENGINE)
    assert _resolve(Settings(llm_mode="auto"), _FakeRegistry()) == ("auto", engine_select.NO_ENGINE)


def test_a_probe_failure_falls_through_instead_of_raising():
    class _Broken(_FakeRegistry):
        async def status(self, connection_id, fresh=False):
            raise RuntimeError("CLI exploded")

    assert _resolve(Settings(llm_mode="auto"), _Broken()) == ("auto", engine_select.NO_ENGINE)

    class _ClaudeBroken(_FakeRegistry):
        async def status(self, connection_id, fresh=False):
            if connection_id == "claude-plan":
                raise RuntimeError("CLI exploded")
            return await super().status(connection_id, fresh)

    assert _resolve(Settings(), _ClaudeBroken(connected={"chatgpt-plan"}))[0] == "codex"


def test_an_unrecognized_llm_mode_has_no_engine_without_probing():
    """Fix round 1, L3: `llm_mode` is a bare `str` — a typo (or a future
    value this module doesn't know yet) must never silently escalate into
    the agent rung — nor (2026-10-19) into a metered key."""
    class _Boom:
        def prefs(self):
            raise AssertionError("probed despite an unrecognized llm_mode")

    mode, why = _resolve(Settings(llm_mode="atuo"), _Boom())
    assert mode == "auto" and "unrecognized" in why


# --------------------------------------------------------------------------- #
# Fix round 1, H1/H2 — trigger scope: the toggle/auto rungs are
# user-triggered only. A scheduled cycle must never spend plan quota
# unattended, matching `Copy.sleepEngineExplainer`'s literal promise.
# --------------------------------------------------------------------------- #

def test_with_the_switch_off_a_scheduled_cycle_never_selects_the_agent_rung_even_with_the_toggle_on():
    class _Boom(_FakeRegistry):
        async def status(self, connection_id, fresh=False):
            raise AssertionError("a scheduled cycle probed the registry")

    reg = _Boom(prefs={"claude-plan": {"use_for_sleep": True}, **PLAN_OFF}, connected={"claude-plan"})
    mode, why = asyncio.run(
        engine_select.resolve_llm_mode(Settings(llm_mode="byok"), reg, user_triggered=False)
    )
    assert mode == "byok"
    assert "user-triggered" in why


def test_with_the_switch_off_a_scheduled_auto_cycle_probes_no_plan_and_has_no_engine():
    reg = _Probes(prefs=PLAN_OFF, connected={"claude-plan", "chatgpt-plan"})
    mode, why = asyncio.run(
        engine_select.resolve_llm_mode(Settings(llm_mode="auto"), reg, user_triggered=False)
    )
    assert (mode, why) == ("auto", engine_select.SCHEDULE_DEGRADED)
    assert reg.asked == [], "ruling 36 D1: Auto has no local rung, so a closed plan probes nothing"
    local = _Probes(prefs=PLAN_OFF, connected={"claude-plan", "ollama-local"})
    assert asyncio.run(engine_select.resolve_llm_mode(Settings(), local, user_triggered=False))[0] == "auto"


def test_auto_never_reaches_a_running_local_model():
    """Ruling 36 D1: "stop pushing Ollama" — Auto is the Claude plan, then the ChatGPT plan, and nothing else."""
    reg = _FakeRegistry(connected={"ollama-local"})
    mode, why = asyncio.run(engine_select.resolve_llm_mode(Settings(llm_mode="auto"), reg, user_triggered=True))
    assert (mode, why) == ("auto", engine_select.NO_ENGINE)
    assert "ollama-local" not in engine_select._AUTO_LADDER
    chosen = _FakeRegistry(prefs={"sleep-engine": {"mode": "local"}}, connected={"ollama-local"})
    assert asyncio.run(engine_select.resolve_llm_mode(Settings(), chosen, user_triggered=True))[0] == "local"


class _Prefs(_FakeRegistry):
    """A registry whose prefs can be written (the one-time step records itself)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._store = {k: dict(v) for k, v in (kw.get("prefs") or {}).items()}

    def prefs(self):
        return self._store

    def set_pref(self, cid, key, value):
        entry = self._store.setdefault(cid, {})
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value


class _Cli:
    """A stand-in for the CLI runner: an answer per command (`claude` / `codex`), recorded."""

    def __init__(self, claude=(0, '{"loggedIn": false}'), codex=(1, "")):
        self.answers = {"claude": claude, "codex": codex}
        self.ran: list[str] = []

    def __call__(self, argv, *, stdin=None, timeout=None, cwd=None):
        from api.services.connections.base import CliResult

        self.ran.append(argv[0])
        rc, out = self.answers[argv[0]]
        return CliResult(rc, out, "")


def _retire(settings, reg, cli):
    return asyncio.run(engine_select.retire_auto_local_rung(settings, reg, runner=cli))


def test_a_person_reading_through_a_local_model_under_auto_keeps_it_as_a_recorded_choice():
    reg = _Prefs(connected={"ollama-local"})
    assert _retire(Settings(), reg, _Cli()) == "kept_local"
    entry = reg.prefs()["sleep-engine"]
    assert entry["mode"] == "local" and entry[engine_select.AUTO_LOCAL_RECORD_KEY]["outcome"] == "kept_local"
    assert asyncio.run(engine_select.resolve_llm_mode(Settings(), reg, user_triggered=True))[0] == "local"
    assert _retire(Settings(), reg, _Cli()) is None, "once"


def test_a_timed_out_plan_probe_never_pins_a_signed_in_person_to_local():
    """Re-review 2026-10-22: at boot the Claude cache is cold; a `claude auth status` that times out (rc 124) or prints
    nothing readable is not "signed out". The mode and the record stay untouched, so the next start asks again."""
    for claude in [(124, ""), (0, ""), (0, "not json")]:
        reg = _Prefs(connected={"ollama-local"})
        assert _retire(Settings(), reg, _Cli(claude=claude)) is None, claude
        assert reg.prefs().get("sleep-engine", {}) == {}, claude
    reg = _Prefs(connected={"ollama-local"})
    assert _retire(Settings(), reg, _Cli(codex=(124, ""))) is None
    assert reg.prefs().get("sleep-engine", {}) == {}


def test_the_one_time_step_never_adopts_a_local_model_beside_a_plan():
    with_plan = _Prefs(connected={"ollama-local"})
    assert _retire(Settings(), with_plan, _Cli(claude=(0, '{"loggedIn": true}'))) == "checked"
    assert "mode" not in with_plan.prefs()["sleep-engine"]
    codex = _Prefs(connected={"ollama-local"})
    assert _retire(Settings(), codex, _Cli(codex=(0, "Logged in"))) == "checked"
    # No local model running: nothing recorded and no plan CLI spawned (it may start after Cicada at login).
    cli = _Cli()
    without = _Prefs(connected=set())
    assert _retire(Settings(), without, cli) is None
    assert without.prefs().get("sleep-engine", {}) == {} and cli.ran == []
    pinned = _Prefs(connected={"ollama-local"})
    assert _retire(Settings(llm_mode="auto"), pinned, _Cli()) is None



def test_by_default_a_scheduled_cycle_reads_with_the_plan():
    """Ruling 4b amended 2026-10-19: "Make scheduled runs run on the plan by default"."""
    reg = _FakeRegistry(connected={"claude-plan"})
    mode, why = asyncio.run(engine_select.resolve_llm_mode(Settings(), reg, user_triggered=False))
    assert mode == "agent" and "Settings → Sleep" in why
    codex = _FakeRegistry(prefs={"sleep-engine": {"mode": "codex"}}, connected={"chatgpt-plan"})
    assert asyncio.run(engine_select.resolve_llm_mode(Settings(), codex, user_triggered=False))[0] == "codex"


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


def test_resolve_settings_keeps_the_chosen_key_on_a_scheduled_cycle_with_the_switch_off():
    reg = _FakeRegistry(prefs={"claude-plan": {"use_for_sleep": True}, **PLAN_OFF},
                        connected={"claude-plan"})
    resolved, why = asyncio.run(
        engine_select.resolve_settings(Settings(llm_mode="byok"), reg, user_triggered=False)
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
    # An unresolved "auto" is never reported as the metered engine (review of #360); a RESOLVED auto with no engine
    # reads "none".
    assert engine_select.engine_label(Settings(llm_mode="auto")) == "auto"
    assert engine_select.engine_label(Settings(llm_mode="auto", no_engine_reason="x")) == "none"


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
#   4. real Settings, no pref, nothing configured                -> the Auto ladder (the default since 2026-10-19)
#
# Ruling 4/R3 still applies ON TOP of rung 2: with the person's switch off, a prefs-chosen "agent" has no engine on a
# scheduled cycle (2026-10-19: never the metered key by itself), exactly like an "auto"-resolved "agent".
# --------------------------------------------------------------------------- #

def test_prefs_mode_applies_when_env_is_not_explicit():
    reg = _FakeRegistry(prefs={engine_select.SLEEP_ENGINE_PREF_KEY: {"mode": "local"}})
    mode, why = _resolve(Settings(), reg)
    assert mode == "local"
    assert "Settings" in why


def test_prefs_agent_has_no_engine_on_a_scheduled_cycle_with_the_switch_off():
    reg = _FakeRegistry(prefs={engine_select.SLEEP_ENGINE_PREF_KEY: {"mode": "agent"}, **PLAN_OFF})
    mode, why = asyncio.run(
        engine_select.resolve_llm_mode(Settings(), reg, user_triggered=False)
    )
    assert (mode, why) == ("auto", engine_select.SCHEDULE_DEGRADED)


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


# --- Track E Task 3: the codex label, the plan maps, authorship (R-E22) ------

def test_the_codex_label_and_the_plan_maps():
    assert engine_select.engine_label(Settings(llm_mode="codex")) == "codex-cli"
    assert engine_select.PLAN_ENGINES == {"claude-cli": ("claude-plan", "subscription"),
                                          "codex-cli": ("chatgpt-plan", "subscription"),
                                          # G49/G50: the person's own signed-in Cursor, OpenCode and Grok.
                                          "cursor-cli": ("cursor-plan", "subscription"),
                                          "opencode-cli": ("opencode-plan", "subscription"),
                                          "grok-cli": ("grok-plan", "subscription")}
    assert engine_select.PLAN_NAMES["codex-cli"] == "ChatGPT plan"


def test_plan_work_is_authored_by_the_plans_model_and_byok_is_unchanged():
    from types import SimpleNamespace
    assert engine_select.author_model(Settings(llm_mode="agent", agent_model="opus")) == "opus"
    assert engine_select.author_model(Settings(llm_mode="codex", codex_model="gpt-5.6-luna")) == "gpt-5.6-luna"
    assert engine_select.author_model(Settings(llm_mode="codex")) == "unknown"
    assert engine_select.author_model(SimpleNamespace(litellm_model="gpt-5.4-mini")) == "gpt-5.4-mini"


def test_a_plan_cycles_claim_is_authored_by_the_plans_model_and_byok_is_unchanged():
    from api.services import claim_reconciler
    from api.services.claims import Claim

    claim = Claim(id="c-fixture", text="alpha-project uses SQLite",
                  subject="alpha-project", predicate="uses", object="sqlite")
    claim_reconciler._stamp_new(claim, Settings(llm_mode="codex", codex_model="gpt-5.6-luna"),
                                today="2026-09-23")
    assert claim.authored_by == "gpt-5.6-luna"
    byok = Claim(id="c-fixture-2", text="t")
    claim_reconciler._stamp_new(byok, Settings(litellm_model="gpt-5.4-mini"), today="2026-09-23")
    assert byok.authored_by == "gpt-5.4-mini"


# --------------------------------------------------------------------------- #
# Track E — the ChatGPT plan on the ladder; ruling 4 for both plans (R-E20/R-E21)
# --------------------------------------------------------------------------- #

def test_ruling_4_names_every_plan_in_one_tuple():
    assert engine_select.SUBSCRIPTION_MODES == ("agent", "codex", "cursor", "opencode", "grok")


@pytest.mark.parametrize("mode", ["agent", "codex"])
def test_a_settings_chosen_plan_never_runs_on_a_schedule_with_the_switch_off(mode):
    class _NoStatus(_FakeRegistry):
        async def status(self, connection_id, fresh=False):
            raise AssertionError("a scheduled cycle probed a plan")

    reg = _NoStatus(prefs={"sleep-engine": {"mode": mode}, **PLAN_OFF}, connected={"claude-plan", "chatgpt-plan"})
    got, why = asyncio.run(engine_select.resolve_llm_mode(Settings(), reg, user_triggered=False))
    assert got == "auto" and "user-triggered" in why


def test_an_explicit_env_codex_is_deliberate_config_and_runs_on_a_schedule():
    class _Boom:
        def prefs(self):
            raise AssertionError("probed despite an explicit mode")

    got, why = asyncio.run(engine_select.resolve_llm_mode(Settings(llm_mode="codex"), _Boom(),
                                                          user_triggered=False))
    assert got == "codex" and "CICADA_LLM_MODE" in why


def test_a_settings_chosen_codex_runs_when_you_start_it():
    assert _resolve(Settings(), _FakeRegistry(prefs={"sleep-engine": {"mode": "codex"}}))[0] == "codex"


def test_auto_prefers_claude_then_chatgpt_then_never_a_key_or_a_local_model():
    auto = Settings(llm_mode="auto")
    assert _resolve(auto, _FakeRegistry(connected={"claude-plan", "chatgpt-plan", "ollama-local"}))[0] == "agent"
    assert _resolve(auto, _FakeRegistry(connected={"chatgpt-plan", "ollama-local"}))[0] == "codex"
    assert _resolve(auto, _FakeRegistry(connected={"ollama-local"}))[0] == "auto"
    assert _resolve(auto, _FakeRegistry(connected={"byok-openrouter", "byok-openai"}))[0] == "auto"


def test_a_failed_chatgpt_probe_falls_through_to_no_engine():
    class _CodexProbeFails(_FakeRegistry):
        async def status(self, connection_id, fresh=False):
            if connection_id == "chatgpt-plan":
                raise RuntimeError("codex probe blew up")
            return await super().status(connection_id, fresh)

    assert _resolve(Settings(llm_mode="auto"), _CodexProbeFails(connected={"ollama-local"}))[0] == "auto"


def test_the_use_for_sleep_toggle_never_reaches_for_chatgpt():
    reg = _FakeRegistry(prefs={"claude-plan": {"use_for_sleep": True}}, connected={"chatgpt-plan"})
    assert _resolve(Settings(llm_mode="byok"), reg)[0] == "byok"


def test_the_codex_model_pref_reaches_the_resolved_settings():
    reg = _FakeRegistry(prefs={"sleep-engine": {"mode": "codex", "model": "gpt-5.6-luna",
                                                "disambiguation_model": "gpt-5.5"}})
    resolved, _why = asyncio.run(engine_select.resolve_settings(Settings(), reg))
    assert (resolved.llm_mode, resolved.codex_model, resolved.codex_disambiguation_model) == (
        "codex", "gpt-5.6-luna", "gpt-5.5")


def test_a_model_pref_reaches_a_cycle_that_passed_no_registry(tmp_path, monkeypatch):
    """R-E21 — every Sleep cycle calls resolve_settings with no registry; the
    model picked in Settings → Intelligence used to reach only the preview."""
    from api.services.connections.registry import get_registry, reset_registry

    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    reset_registry()
    reg = get_registry(Settings())
    reg.set_pref("sleep-engine", "mode", "agent")
    reg.set_pref("sleep-engine", "model", "opus")
    resolved, _why = asyncio.run(engine_select.resolve_settings(Settings()))
    assert resolved.llm_mode == "agent" and resolved.agent_model == "opus"


def test_the_overage_opt_in_reaches_the_resolved_settings_only_when_not_env_pinned():
    reg = _FakeRegistry(prefs={"sleep-engine": {"mode": "agent", "allow_overage": True}})
    resolved, _why = asyncio.run(engine_select.resolve_settings(Settings(), reg))
    assert resolved.agent_allow_overage is True
    pinned, _why = asyncio.run(engine_select.resolve_settings(Settings(llm_mode="agent"), reg))
    assert pinned.agent_allow_overage is False


@pytest.mark.parametrize("mode,model,disambiguation", [
    ("agent", "opus", "sonnet"),
    ("codex", "gpt-5.6-luna", "gpt-5.5"),
])
def test_a_plans_model_never_rides_into_the_key_a_schedule_degrades_to(mode, model, disambiguation):
    """Task 4 review round 1: ruling 4 degrades a Settings-chosen plan to byok
    on a schedule, and the plan's stored model must stay with the plan — a
    CLI alias or a ChatGPT-plan model id in `litellm_model` either fails every
    night or bills the person's API key for a model they never chose for it."""
    reg = _FakeRegistry(prefs={"sleep-engine": {"mode": mode, "model": model,
                                                "disambiguation_model": disambiguation}, **PLAN_OFF})
    base_settings = Settings()
    resolved, _why = asyncio.run(
        engine_select.resolve_settings(base_settings, reg, user_triggered=False))
    assert resolved.llm_mode == "auto" and engine_select.no_engine(resolved)   # 2026-10-19: no key by itself
    assert resolved.litellm_model == base_settings.litellm_model
    assert resolved.litellm_disambiguation_model == base_settings.litellm_disambiguation_model


def test_a_model_pref_applies_only_to_the_mode_that_wrote_it():
    reg = _FakeRegistry(prefs={"sleep-engine": {"mode": "agent", "model": "opus"}})
    assert engine_select._model_overrides(reg, "agent") == {"agent_model": "opus"}
    assert engine_select._model_overrides(reg, "byok") == {}
    assert engine_select._model_overrides(reg, "local") == {}
    assert engine_select._model_overrides(reg, "codex") == {}


def test_powered_connection_follows_the_configured_mode_and_never_probes():
    class _NoStatus(_FakeRegistry):
        async def status(self, *a, **k):
            raise AssertionError("powers must never probe")

    both = {"claude-plan", "chatgpt-plan", "ollama-local", "byok-openai"}
    pick = engine_select.powered_connection_id
    assert pick(Settings(), _NoStatus(prefs={"sleep-engine": {"mode": "codex"}}), both) == "chatgpt-plan"
    assert pick(Settings(), _NoStatus(prefs={"sleep-engine": {"mode": "codex"}}), {"claude-plan"}) is None
    assert pick(Settings(llm_mode="auto"), _NoStatus(), both) == "claude-plan"
    assert pick(Settings(llm_mode="auto"), _NoStatus(), {"chatgpt-plan", "byok-openai"}) == "chatgpt-plan"
    assert pick(Settings(llm_mode="byok"), _NoStatus(prefs={"claude-plan": {"use_for_sleep": True}}),
                both) == "claude-plan"
    assert pick(Settings(llm_mode="byok"), _NoStatus(), both) == "byok-openai"
    assert pick(Settings(llm_mode="byok"), _NoStatus(), {"claude-plan"}) is None
    # The default is Auto (2026-10-19): a plan powers it, a key never does by itself.
    assert pick(Settings(), _NoStatus(), both) == "claude-plan"
    assert pick(Settings(), _NoStatus(), {"byok-openai"}) is None


def test_powered_connection_reads_the_byok_pref_model_before_the_env_model():
    """Round 4 final review: the OpenRouter card and the key-provider picker
    write the byok pref's model; POWERS and /status must name the card that
    model bills, not the env default's (or none)."""
    prefs = {"sleep-engine": {"mode": "byok", "model": "openrouter/openai/gpt-oss-120b"}}
    pick = engine_select.powered_connection_id
    assert pick(Settings(), _FakeRegistry(prefs=prefs), {"byok-openrouter"}) == "byok-openrouter"
    assert pick(Settings(), _FakeRegistry(prefs=prefs), {"byok-openai", "byok-openrouter"}) == "byok-openrouter"
    # A model slot written for another mode never leaks into the byok answer.
    stale = {"sleep-engine": {"mode": "local", "model": "openrouter/x"}}
    assert pick(Settings(llm_mode="byok"), _FakeRegistry(prefs=stale), {"byok-openai", "byok-openrouter"}) == "byok-openai"


def test_a_new_install_never_adopts_a_local_model_started_later():
    """Re-review 2026-10-22: a new install of this build never had a local rung. Its first start records `checked`, so
    on a later start with a local model running and both plans signed out, the mode stays Auto."""
    reg = _Prefs(connected=set())
    assert asyncio.run(engine_select.retire_auto_local_rung(Settings(), reg, runner=_Cli(), new_install=True)) == "checked"
    assert reg.prefs()["sleep-engine"][engine_select.AUTO_LOCAL_RECORD_KEY]["outcome"] == "checked"
    reg._connected = {"ollama-local"}
    assert _retire(Settings(), reg, _Cli()) is None
    assert "mode" not in reg.prefs()["sleep-engine"]
    assert engine_select.configured_mode(Settings(), reg) == "auto"
    assert asyncio.run(engine_select.resolve_llm_mode(Settings(), reg, user_triggered=True))[0] == "auto"
