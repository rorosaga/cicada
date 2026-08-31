# G74(a) — Claude Code CLI as a Sleep Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the reserved `llm_mode="agent"` rung as `claude -p` subprocess calls so the Sleep cycle runs on the user's already-connected Max plan with zero API credits, and make every failure it can produce visible instead of silent.

**Architecture:** One new module (`api/services/agent_engine.py`) owns everything about the subprocess — the pinned argv, stdin marshalling, envelope parsing, the throttle circuit breaker, and a dual-access response shim that satisfies both `resp.choices[0].message.content` and `resp["choices"][0]["message"]["content"]`. A second new module (`api/services/engine_errors.py`) is the failure taxonomy every layer above branches on. `providers.resolve_llm_fn` gains one branch: when the resolved mode is `agent` it returns a callable with the same signature that spawns the CLI instead of calling litellm, and emits telemetry with honest subscription-shaped fields. Everything else in the plan is repair work the spec exposed and that ships regardless of which engine runs: a shared lenient JSON parser, an abort ordering fix in `sleep_cycle`, an engine-failure-vs-uncertainty fix in `entity_resolver`, and provenance/ledger truth in `_finalize`.

**Tech Stack:** Python 3 / FastAPI / Pydantic v2 (`api/`, venv at `api/.venv`, tests `api/.venv/bin/python -m pytest api/tests -q`); SwiftUI macOS 14 / SwiftPM (`app/CicadaApp`, tests `cd app/CicadaApp && swift test`); the unmodified `claude` CLI (2.1.252) as a subprocess; git as the versioning + provenance layer.

**Spec:** `docs/superpowers/specs/2026-09-01-agent-engine-design.md` — the authority. Read it alongside this plan. The plan argues **from** the spec; do not re-litigate its decisions.

## Global Constraints

- **Python is `api/.venv/bin/python`.** Backend suite: `api/.venv/bin/python -m pytest api/tests -q`. It must stay green **except the 8 pre-existing `api/tests/test_calendar_registry.py` failures**, which are the documented baseline — never "fix" them here, and never count them as a regression.
- **App commands:** `cd app/CicadaApp && swift test` and `cd app/CicadaApp && swift build`.
- **ZERO real `claude` subprocess spawns in the test suite.** Every test injects a runner. `api/tests/conftest.py` gains an autouse guard (Task 1) that turns any attempt to reach the real default runner into a loud `AssertionError`. If a test needs a spawn, the test is wrong.
- **`scrubbed_env()` is mandatory for every subprocess this plan adds** (`api/services/connections/base.py:33`). It strips `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, so `claude -p` reads OAuth rather than silently diverting billing to an API key.
- **Never `--bare`.** It forces `ANTHROPIC_API_KEY`/`apiKeyHelper` and never reads OAuth — exactly the wrong mode for a subscription. A test asserts `"--bare" not in build_argv(...)`.
- **Never write secrets, tokens, or PII into `sync_state.json`, episodes, entity pages, or commit messages.** The engine's failure logging prints the *envelope*, which contains no credential; it must never print `scrubbed_env()`, argv containing a prompt, or stdin.
- **Prompts are prefix-ordered (spec §4): stable content first, varying content last.** Prompt-cache affinity across separate `-p` processes is worth 5.4× on a 58 KB prompt. `marshal_prompt` **preserves message order and never reorders**; the system text goes to `--system-prompt` (argv, constant across a cycle) so the cache prefix begins with it. Do not "tidy" a prompt builder by moving the per-call question to the front.
- **The engine is user-triggered only in this slice** (`POST /sleep/trigger`). The nightly scheduler keeps the existing engine selection; do not wire `auto`/`agent` into `sleep_scheduler`.
- **Out of scope:** Stage-2 batching, G74(b) (the in-session agent that writes through MCP), G75. Do not start them.
- **Never touch `.claude/settings.json`** — it is already modified in the working tree. Never stage it.
- **Never `git add -A`.** Stage explicit paths in every commit.
- **Every commit message ends with these two trailer lines** (after a blank line):
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
  ```
- **Additive on the wire.** Every new field on `ConnectionStatus`, `SleepStatusResponse`, and their Swift twins must decode from an *old* payload that omits it (`decodeIfPresent ?? default` in Swift, a defaulted Pydantic field in Python). Old `SnapshotCache` files on disk must still decode.
- **Python tests are hermetic and `tmp_path`-only.** No test reads the live `memory/` bank, makes an LLM call, or touches the network. `conftest.py` already forces `CICADA_API_AUTH=off`, `CICADA_ALLOW_LOGO_FETCH=off`, `CICADA_TELEMETRY=off`, `CICADA_ALLOW_CONNECTOR_FETCH=off`.

---

## File Structure

**Created**

| File | Responsibility |
|---|---|
| `api/services/engine_errors.py` | The failure taxonomy: seven exception types plus the retryable tuple. No logic, no imports beyond stdlib — every other layer branches on these. |
| `api/services/agent_engine.py` | Everything about the `claude -p` subprocess: pinned argv, stdin marshalling, envelope parse + classification, the dual-access response shim, per-stage model + schema selection, the throttle circuit breaker, the models-used ledger, and the pre-flight probe. |
| `api/services/json_parse.py` | The one lenient JSON-object parser, promoted out of `entity_extractor`. |
| `api/services/engine_select.py` | Resolves `llm_mode` (`auto`, and the `use_for_sleep` pref) to a concrete mode by consulting the connections registry, once per Sleep cycle. |
| `api/tests/test_agent_engine.py` | T1 — argv, marshalling, envelope parse/classification, shim, breaker. Recorded fixtures only. |
| `api/tests/test_json_parse.py` | T2 — the shared parser and the six re-routed call sites. |
| `api/tests/test_agent_seam.py` | T3 — the `providers` agent branch: sync/async duality, kwarg handling, semaphore, telemetry fields. |
| `api/tests/test_engine_error_taxonomy.py` | T4 — retry widening, extractor classification, breaker behaviour, the resolver's failure-vs-uncertainty split. |
| `api/tests/test_sleep_engine_state.py` | T5 — pre-flight probe, honest abort copy, the engine-independent tail running on every exit path. |
| `api/tests/test_agent_provenance.py` | T6 — `_finalize` engine/connection/author truth and the five `stage=` labels. |
| `api/tests/test_engine_select.py` | T7 — mode resolution precedence and the `use_for_sleep` pref. |
| `app/CicadaApp/Tests/CicadaAppTests/EngineSelectionTests.swift` | T7 — `ConnectionStatus.useForSleep` decoding, the card's engine copy, `SleepStatusResponse.lastEngine` decoding. |

**Modified**

| File | Change |
|---|---|
| `api/services/connections/base.py:37-62` | `run_cli` gains `stdin=` / `cwd=`; a new blocking twin `run_cli_sync` with the identical rc contract. |
| `api/services/providers.py:135-239` | The agent branch, `is_async` inference + override, branch-dependent `_emit`, the rung semaphore. |
| `api/services/entity_extractor.py:152-156, 159-207, 277-289, 371-379` | Widened retry tuple, parser moved out (alias kept), engine-error classification branches. |
| `api/services/entity_resolver.py:706, 711-713` | Lenient parse; `EngineError` re-raised instead of being flattened to `"unsure"`. |
| `api/services/conflict_resolver.py:618-620, 721-729` | `stage=` labels; lenient parse. |
| `api/services/skill_extractor.py:81-90` | `stage=` label; lenient parse. |
| `api/services/dedup_sweep.py:106-123` | `stage=` label; lenient parse. |
| `api/services/source_rewrite.py:50-66` | `stage=` label; lenient parse. |
| `api/services/ask_service.py:443` | Lenient parse (replaces `_strip_fences` + `json.loads`). |
| `api/services/sleep_cycle.py:13-56, 184-528, 699-834` | `last_engine`/`engine_detail` state, the `_run_stages` / engine-independent-tail split (the abort ordering fix), engine resolution + pre-flight, honest Stage-1 failure copy, `_finalize(engine=…, connection=…, authors=…)`. |
| `api/services/connections/registry.py:60-69, 101-108` | `use_for_sleep` pref stamped onto the `claude-plan` status. |
| `api/routers/connections.py:18-21, 94-104` | `PrefsBody.use_for_sleep`, restricted to `claude-plan`. |
| `api/routers/sleep.py:41-62` | `last_engine` / `engine_detail` on `GET /sleep/status`. |
| `api/models/schemas.py:895-920, 1258-1282` | `SleepStatusResponse.last_engine` / `.engine_detail`; `ConnectionStatus.use_for_sleep`. |
| `api/config.py:94-110` | `llm_mode` doc for `agent`/`auto`; `agent_model`, `agent_disambiguation_model`, `agent_max_concurrency`. |
| `api/tests/conftest.py` | The no-real-spawn guard + the recorded envelope fixtures. |
| `app/CicadaApp/Sources/CicadaApp/Models/Connection.swift:5-70` | `useForSleep`. |
| `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift:495-533, 1041-1043` | `SleepStatusResponse.lastEngine`/`.engineDetail`; `setUseForSleep`. |
| `app/CicadaApp/Sources/CicadaApp/Views/Connections/ConnectionsView.swift:92-175` | The "Use for Sleep" toggle + honest copy on the Claude card. |
| `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift:57-62` | The engine line above the error banner. |
| `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift:26-40` | The engine copy constants. |
| `app/CicadaApp/Sources/CicadaApp/ViewModels/ConnectionsViewModel.swift:157-160` | `setUseForSleep`. |
| `app/CicadaApp/Sources/CicadaApp/Services/Mutations.swift` (or wherever `SetConnectionTier` lives) | `SetUseForSleep` mutation. |
| `scripts/doctor.sh:105-119` | Three engine checks. |

---

## Task 1: The agent engine — argv, marshalling, envelope, shim, breaker

**Files:**
- Create: `api/services/engine_errors.py`
- Create: `api/services/agent_engine.py`
- Modify: `api/services/connections/base.py:37-62`
- Modify: `api/config.py:105-110`
- Modify: `api/tests/conftest.py`
- Test: `api/tests/test_agent_engine.py`

**Interfaces:**
- Consumes: `api.services.connections.base.CliResult`, `scrubbed_env()`, `api.services.auth.cicada_home()`.
- Produces, relied on by Tasks 3–7:
  - `engine_errors.EngineError` and subclasses `EngineUnavailable`, `EngineTimeout`, `EngineThrottled`, `EngineExhausted`, `EngineModelNotFound`, `EngineProtocolError`, `EngineFailed`; `engine_errors.RETRYABLE: tuple[type[Exception], ...]`.
  - `base.run_cli_sync(argv: list[str], *, timeout: float = 15.0, stdin: str | None = None, cwd: str | None = None) -> CliResult`
  - `base.run_cli(argv, *, timeout=15.0, stdin=None, cwd=None) -> Awaitable[CliResult]`
  - `agent_engine.build_argv(*, model: str, system_prompt: str, json_schema: dict | None = None, binary: str = "claude") -> list[str]`
  - `agent_engine.marshal_prompt(messages: list[dict]) -> tuple[str, str]`
  - `agent_engine.parse_envelope(result: CliResult) -> dict`
  - `agent_engine.response_shim(envelope: dict, requested_model: str) -> _D`
  - `agent_engine.model_from_envelope(envelope: dict, requested_model: str) -> str`
  - `agent_engine.equiv_cost_from_envelope(envelope: dict) -> float | None`
  - `agent_engine.complete(*, messages, model, stage=None, want_json=False, timeout=DEFAULT_TIMEOUT_S, runner=None, binary="claude") -> dict`
  - `agent_engine.model_for_stage(settings, stage: str | None) -> str`
  - `agent_engine.probe(*, runner=None, binary="claude", timeout=20.0) -> tuple[bool, str]`
  - `agent_engine.trip_breaker(reason: str) -> bool` / `breaker_reason() -> str | None` / `reset_breaker() -> None`
  - `agent_engine.record_model_used(model: str) -> None` / `models_used() -> list[str]` / `reset_models_used() -> None`
  - `Settings.agent_model` (`"sonnet"`), `Settings.agent_disambiguation_model` (`"haiku"`), `Settings.agent_max_concurrency` (`3`).
  - pytest fixtures `agent_envelopes` (dict of recorded envelopes) and `agent_runner` (factory).

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_agent_engine.py`:

```python
"""G74(a) Task 1 — the `claude -p` engine, exercised over recorded envelopes.

ZERO subprocess spawns: every test injects a runner. The autouse guard in
conftest.py turns any attempt to reach the real default runner into a failure.
"""
from __future__ import annotations

import json

import pytest

from api.config import Settings
from api.services import agent_engine, engine_errors
from api.services.connections.base import CliResult


# --------------------------------------------------------------------------- #
# argv
# --------------------------------------------------------------------------- #

def test_argv_pins_the_verified_flag_set():
    argv = agent_engine.build_argv(model="sonnet", system_prompt="SYS")
    assert argv[0] == "claude"
    for flag in ("-p", "--output-format", "json", "--safe-mode",
                 "--strict-mcp-config", "--tools", "--no-session-persistence"):
        assert flag in argv
    # `--tools ""` is the empty-string value right after the flag.
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--system-prompt") + 1] == "SYS"


def test_argv_never_uses_bare_mode():
    """`--bare` forces ANTHROPIC_API_KEY and never reads OAuth — the exact
    wrong mode for a subscription (spec §3)."""
    argv = agent_engine.build_argv(model="sonnet", system_prompt="SYS")
    assert "--bare" not in argv


def test_argv_carries_a_json_schema_when_one_is_given():
    argv = agent_engine.build_argv(model="sonnet", system_prompt="S",
                                   json_schema={"type": "object"})
    assert json.loads(argv[argv.index("--json-schema") + 1]) == {"type": "object"}


def test_argv_omits_json_schema_when_none():
    assert "--json-schema" not in agent_engine.build_argv(model="sonnet", system_prompt="S")


# --------------------------------------------------------------------------- #
# prompt marshalling
# --------------------------------------------------------------------------- #

def test_marshal_splits_system_from_stdin_and_preserves_order():
    system, body = agent_engine.marshal_prompt([
        {"role": "system", "content": "STABLE SYSTEM"},
        {"role": "user", "content": "corpus then question"},
    ])
    assert system == "STABLE SYSTEM"
    assert body == "corpus then question"


def test_marshal_joins_multiple_turns_with_role_prefixes_in_order():
    _, body = agent_engine.marshal_prompt([
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "third"},
    ])
    assert body == "USER: first\n\nASSISTANT: second\n\nUSER: third"


def test_marshal_drops_empty_messages_and_stringifies_non_str_content():
    system, body = agent_engine.marshal_prompt([
        {"role": "system", "content": "   "},
        {"role": "user", "content": {"a": 1}},
    ])
    assert system == ""
    assert json.loads(body) == {"a": 1}


# --------------------------------------------------------------------------- #
# envelope parsing + classification
# --------------------------------------------------------------------------- #

def test_parse_success_envelope(agent_envelopes):
    env = agent_engine.parse_envelope(CliResult(0, json.dumps(agent_envelopes["success"]), ""))
    assert env["is_error"] is False


@pytest.mark.parametrize("key,exc", [
    ("budget_exhausted", engine_errors.EngineExhausted),
    ("model_not_found", engine_errors.EngineModelNotFound),
    ("rate_limited", engine_errors.EngineThrottled),
    ("not_logged_in", engine_errors.EngineUnavailable),
    ("unclassified_error", engine_errors.EngineFailed),
])
def test_parse_classifies_error_envelopes(agent_envelopes, key, exc):
    with pytest.raises(exc):
        agent_engine.parse_envelope(CliResult(0, json.dumps(agent_envelopes[key]), ""))


def test_rc_127_is_unavailable_with_an_install_hint():
    with pytest.raises(engine_errors.EngineUnavailable) as err:
        agent_engine.parse_envelope(CliResult(127, "", "claude: not found"))
    assert "not installed" in str(err.value)


def test_rc_124_is_a_timeout():
    with pytest.raises(engine_errors.EngineTimeout):
        agent_engine.parse_envelope(CliResult(124, "", "claude timed out after 300s"))


def test_non_json_stdout_is_unavailable():
    with pytest.raises(engine_errors.EngineUnavailable):
        agent_engine.parse_envelope(CliResult(0, "Welcome to Claude Code!", ""))


def test_envelope_with_no_result_is_a_protocol_error():
    with pytest.raises(engine_errors.EngineProtocolError):
        agent_engine.parse_envelope(CliResult(0, json.dumps({"type": "result"}), ""))


# --------------------------------------------------------------------------- #
# the dual-access response shim (spec §3.1 non-negotiable 1)
# --------------------------------------------------------------------------- #

def test_shim_supports_attribute_and_subscript_access(agent_envelopes):
    resp = agent_engine.response_shim(agent_envelopes["success"], "sonnet")
    assert resp.choices[0].message.content == '{"entities": [], "relationships": []}'
    assert resp["choices"][0]["message"]["content"] == '{"entities": [], "relationships": []}'
    assert resp.choices[0].finish_reason == "end_turn"


def test_shim_folds_cache_counters_into_a_gross_prompt(agent_envelopes):
    """V2b: input_tokens 2 + cache_creation 19631. Reading `input_tokens`
    alone under-counts ~10,000x, so `prompt_tokens` must be the GROSS prompt
    with the cache buckets as a breakdown of it (telemetry.py:174-208)."""
    from api.services import telemetry

    resp = agent_engine.response_shim(agent_envelopes["success"], "sonnet")
    usage = telemetry.usage_from_response(resp)
    assert usage["input_tokens"] == 2 + 19631 + 0
    assert usage["cache_write_tokens"] == 19631
    assert usage["cache_read_tokens"] == 0
    assert usage["output_tokens"] == 57
    assert usage["cost_usd"] is None  # a plan call is never real money


def test_shim_prefers_structured_output_when_result_is_absent(agent_envelopes):
    env = dict(agent_envelopes["structured"])
    env["result"] = None
    resp = agent_engine.response_shim(env, "sonnet")
    assert json.loads(resp.choices[0].message.content) == {"ok": True}


def test_model_from_envelope_picks_the_requested_model_not_the_side_call(agent_envelopes):
    """V1d: modelUsage held claude-haiku-4-5 AND claude-sonnet-5."""
    assert agent_engine.model_from_envelope(agent_envelopes["success"], "claude-sonnet-5") == "claude-sonnet-5"


def test_model_from_envelope_falls_back_to_the_heaviest_model_for_an_alias(agent_envelopes):
    assert agent_engine.model_from_envelope(agent_envelopes["success"], "sonnet") == "claude-sonnet-5"


def test_equiv_cost_reads_the_envelope_total(agent_envelopes):
    assert agent_engine.equiv_cost_from_envelope(agent_envelopes["success"]) == 0.092


# --------------------------------------------------------------------------- #
# complete(): runner wiring, schema selection, breaker
# --------------------------------------------------------------------------- #

def test_complete_sends_the_prompt_on_stdin_and_runs_in_the_scratch_dir(agent_runner, agent_envelopes):
    runner = agent_runner(agent_envelopes["success"])
    agent_engine.complete(messages=[{"role": "system", "content": "S"},
                                    {"role": "user", "content": "BODY"}],
                          model="sonnet", stage="extraction", runner=runner)
    call = runner.calls[0]
    assert call["stdin"] == "BODY"
    assert call["cwd"] == str(agent_engine.scratch_dir())
    assert "--system-prompt" in call["argv"]


def test_complete_appends_a_json_only_instruction_when_no_schema_is_registered(agent_runner, agent_envelopes):
    runner = agent_runner(agent_envelopes["success"])
    agent_engine.complete(messages=[{"role": "system", "content": "S"},
                                    {"role": "user", "content": "B"}],
                          model="sonnet", stage="skills", want_json=True, runner=runner)
    argv = runner.calls[0]["argv"]
    assert "--json-schema" not in argv
    assert agent_engine.JSON_ONLY_SUFFIX in argv[argv.index("--system-prompt") + 1]


def test_complete_uses_the_registered_schema_for_disambiguation(agent_runner, agent_envelopes):
    runner = agent_runner(agent_envelopes["structured"])
    agent_engine.complete(messages=[{"role": "user", "content": "B"}],
                          model="haiku", stage="disambiguation", want_json=True, runner=runner)
    argv = runner.calls[0]["argv"]
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert schema["properties"]["decision"]["enum"] == ["same", "different", "unsure"]


def test_complete_honours_the_timeout_it_is_given(agent_runner, agent_envelopes):
    runner = agent_runner(agent_envelopes["success"])
    agent_engine.complete(messages=[{"role": "user", "content": "B"}], model="sonnet",
                          timeout=17.0, runner=runner)
    assert runner.calls[0]["timeout"] == 17.0


def test_breaker_fails_fast_without_spawning(agent_runner, agent_envelopes):
    runner = agent_runner(agent_envelopes["success"])
    assert agent_engine.trip_breaker("throttled at call 4") is True
    assert agent_engine.trip_breaker("again") is False  # only the first call trips it
    with pytest.raises(engine_errors.EngineThrottled):
        agent_engine.complete(messages=[{"role": "user", "content": "B"}],
                              model="sonnet", runner=runner)
    assert runner.calls == []  # nothing spawned


def test_models_used_ledger_is_a_sorted_deduped_set():
    agent_engine.record_model_used("claude-sonnet-5")
    agent_engine.record_model_used("claude-haiku-4-5")
    agent_engine.record_model_used("claude-sonnet-5")
    assert agent_engine.models_used() == ["claude-haiku-4-5", "claude-sonnet-5"]


def test_model_for_stage_routes_the_judge_to_the_cheaper_model():
    s = Settings(agent_model="sonnet", agent_disambiguation_model="haiku")
    assert agent_engine.model_for_stage(s, "extraction") == "sonnet"
    assert agent_engine.model_for_stage(s, "disambiguation") == "haiku"
    assert agent_engine.model_for_stage(s, None) == "sonnet"


# --------------------------------------------------------------------------- #
# probe
# --------------------------------------------------------------------------- #

def test_probe_reports_signed_in():
    def runner(argv, **kw):
        return CliResult(0, json.dumps({"loggedIn": True, "authMethod": "claude.ai",
                                        "email": "r@example.com"}), "")
    ok, detail = agent_engine.probe(runner=runner)
    assert ok and "r@example.com" in detail


def test_probe_reports_signed_out_with_the_fix():
    def runner(argv, **kw):
        return CliResult(0, json.dumps({"loggedIn": False}), "")
    ok, detail = agent_engine.probe(runner=runner)
    assert not ok and "claude auth login" in detail


def test_probe_rejects_api_key_auth():
    def runner(argv, **kw):
        return CliResult(0, json.dumps({"loggedIn": True, "authMethod": "apiKey"}), "")
    ok, detail = agent_engine.probe(runner=runner)
    assert not ok and "ANTHROPIC_API_KEY" in detail


def test_probe_reports_a_missing_binary():
    ok, detail = agent_engine.probe(runner=lambda argv, **kw: CliResult(127, "", "not found"))
    assert not ok and "not installed" in detail
```

- [ ] **Step 2: Add the shared fixtures and the no-real-spawn guard**

Append to `api/tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _no_real_agent_spawn(monkeypatch):
    """G74(a): no test may spawn the real `claude` CLI.

    Every agent-engine test injects a runner; this makes a missed injection
    fail loudly at the seam instead of quietly shelling out (and spending the
    developer's plan quota) on whatever machine runs the suite.
    """
    from api.services.connections import base

    def _boom(*args, **kwargs):  # pragma: no cover - the guard itself
        raise AssertionError(
            "a test reached the real `claude` runner — inject a runner instead"
        )

    monkeypatch.setattr(base, "run_cli_sync", _boom)


@pytest.fixture
def agent_envelopes():
    """Envelopes recorded from `claude` 2.1.252 (spec §9) plus the three
    failure shapes the spec could not produce on demand.

    `success` is the V2b/V1d call: input_tokens 2 with 19,631 cache-creation
    tokens, and a haiku side-call alongside the requested sonnet.
    """
    return {
        "success": {
            "type": "result", "subtype": "success", "is_error": False,
            "result": '{"entities": [], "relationships": []}',
            "stop_reason": "end_turn", "terminal_reason": None,
            "session_id": "ses-fixture", "num_turns": 1,
            "usage": {"input_tokens": 2, "cache_creation_input_tokens": 19631,
                      "cache_read_input_tokens": 0, "output_tokens": 57},
            "modelUsage": {
                "claude-sonnet-5": {"canonicalModel": "claude-sonnet-5", "inputTokens": 2,
                                    "outputTokens": 57, "cacheReadInputTokens": 0,
                                    "cacheCreationInputTokens": 19631,
                                    "costUSD": 0.0917, "costBasis": "list"},
                "claude-haiku-4-5": {"canonicalModel": "claude-haiku-4-5", "inputTokens": 120,
                                     "outputTokens": 8, "costUSD": 0.0003, "costBasis": "list"},
            },
            "total_cost_usd": 0.092, "duration_ms": 1600,
            "api_error_status": None, "permission_denials": [], "uuid": "u-1",
        },
        "structured": {
            "type": "result", "subtype": "success", "is_error": False,
            "result": '{"ok": true}', "structured_output": {"ok": True},
            "stop_reason": "end_turn", "terminal_reason": None,
            "usage": {"input_tokens": 781, "output_tokens": 6},
            "modelUsage": {"claude-haiku-4-5": {"canonicalModel": "claude-haiku-4-5",
                                                "inputTokens": 781, "outputTokens": 6,
                                                "costUSD": 0.0003, "costBasis": "list"}},
            "total_cost_usd": 0.0003, "duration_ms": 900,
        },
        "budget_exhausted": {
            "type": "result", "subtype": "error", "is_error": True,
            "terminal_reason": "budget_exhausted",
            "result": "Budget exhausted for this window.", "stop_reason": None,
        },
        "model_not_found": {
            "type": "result", "subtype": "error", "is_error": True,
            "terminal_reason": "api_error", "api_error_status": 404,
            "result": "model not found: claude-nope", "stop_reason": None,
        },
        "rate_limited": {
            "type": "result", "subtype": "error", "is_error": True,
            "terminal_reason": "api_error", "api_error_status": 429,
            "result": "rate limit exceeded, please retry later", "stop_reason": None,
        },
        "not_logged_in": {
            "type": "result", "subtype": "error", "is_error": True,
            "terminal_reason": "api_error", "api_error_status": None,
            "result": "Not logged in. Run `claude auth login`.", "stop_reason": None,
        },
        "unclassified_error": {
            "type": "result", "subtype": "error", "is_error": True,
            "terminal_reason": "something_new", "result": "unknown failure", "stop_reason": None,
        },
    }


@pytest.fixture
def agent_runner():
    """Factory: `agent_runner(envelope_or_result, ...)` -> a recording runner.

    Each positional argument is either a dict (returned as a rc-0 JSON
    envelope) or a ready-made ``CliResult``. The last one repeats once the
    list is exhausted, so a fan-out of N calls needs only one fixture.
    """
    import json as _json

    from api.services.connections.base import CliResult

    def _make(*responses):
        queue = list(responses) or [CliResult(0, "{}", "")]

        class _Runner:
            def __init__(self):
                self.calls: list[dict] = []

            def __call__(self, argv, *, stdin=None, timeout=None, cwd=None):
                self.calls.append({"argv": list(argv), "stdin": stdin,
                                   "timeout": timeout, "cwd": cwd})
                item = queue[min(len(self.calls) - 1, len(queue) - 1)]
                if isinstance(item, CliResult):
                    return item
                if isinstance(item, BaseException):
                    raise item
                return CliResult(0, _json.dumps(item), "")

        return _Runner()

    return _make


@pytest.fixture(autouse=True)
def _reset_agent_engine_state():
    """The breaker and the models-used ledger are process-global; a tripped
    breaker leaking into the next test would make it fail-fast for free."""
    from api.services import agent_engine

    agent_engine.reset_breaker()
    agent_engine.reset_models_used()
    yield
    agent_engine.reset_breaker()
    agent_engine.reset_models_used()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_agent_engine.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'api.services.agent_engine'`.

- [ ] **Step 4: Write `api/services/engine_errors.py`**

```python
"""G74(a) — the failure taxonomy for the `claude -p` Sleep engine.

The rung's failures are subprocess-shaped, so nothing above it can branch on
litellm exception types (``entity_extractor._EXTRACT_RETRYABLE`` matched
*nothing* and gave a CLI failure zero retries). These seven types are the
contract every layer above branches on: the extractor's retry tuple, its
per-episode classifier, the resolver's failure-vs-uncertainty split, and the
Sleep page's honest engine copy.

No logic and no imports beyond stdlib on purpose — this module is safe to
import from anywhere, including ``providers`` at seam-resolution time.
"""
from __future__ import annotations


class EngineError(Exception):
    """Base: the Sleep engine could not answer. Never a model's opinion."""


class EngineUnavailable(EngineError):
    """The engine cannot be reached at all: binary missing, signed out, or
    stdout that isn't the JSON envelope. Not retryable — retrying a signed-out
    CLI 200 times is just 200 spawns."""


class EngineTimeout(EngineError):
    """The subprocess exceeded its wall-clock budget (rc 124)."""


class EngineThrottled(EngineError):
    """The plan is rate-limited right now. Trips the circuit breaker: after
    the first one the cycle stops cleanly rather than re-hitting it once per
    remaining episode."""


class EngineExhausted(EngineError):
    """``terminal_reason: budget_exhausted`` — the plan window is spent."""


class EngineModelNotFound(EngineError):
    """The CLI rejected the model id. A configuration bug, not a transient."""


class EngineProtocolError(EngineError):
    """A well-formed JSON envelope of an unexpected shape (no ``result`` and
    no ``structured_output``). Worth one retry — a truncated stream produces
    this."""


class EngineFailed(EngineError):
    """``is_error: true`` with a ``terminal_reason`` we cannot yet classify.

    The spec (§9, "still unverified") could not produce a real 429/quota
    envelope on demand, so an unrecognised failure is logged in full and given
    one retry rather than being silently mapped onto a class it may not be.
    """


#: Engine failures worth exactly one retry inside a single call. Deliberately
#: excludes ``EngineThrottled`` (the breaker handles it — a retry would spawn
#: again), ``EngineUnavailable``, ``EngineExhausted`` and
#: ``EngineModelNotFound`` (all of which need a human, not a second attempt).
RETRYABLE: tuple[type[Exception], ...] = (EngineTimeout, EngineProtocolError, EngineFailed)
```

- [ ] **Step 5: Extend `base.run_cli` and add `run_cli_sync`**

In `api/services/connections/base.py`, add `import subprocess` at the top of the stdlib block, then replace the body of `run_cli` (`:37-62`) and append the sync twin:

```python
async def run_cli(
    argv: list[str],
    *,
    timeout: float = 15.0,
    stdin: str | None = None,
    cwd: str | None = None,
) -> CliResult:
    """Run ``argv`` with a scrubbed env. Never raises: missing binary -> rc 127,
    timeout -> rc 124, so adapters can degrade to ``available=False``.

    ``stdin`` (G74(a)): text piped to the child. ``None`` (the default, and
    what every connection adapter passes) keeps the historical
    ``stdin=DEVNULL``. ``cwd``: the child's working directory — the agent
    engine runs in a scratch dir under ``$CICADA_HOME``, never a bank and
    never the repo.
    """
    if not argv:
        return CliResult(127, "", "empty argv")
    if shutil.which(argv[0]) is None and not os.path.exists(argv[0]):
        return CliResult(127, "", f"{argv[0]}: not found")
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            env=scrubbed_env(),
            cwd=cwd,
        )
    except OSError as exc:
        return CliResult(127, "", str(exc))
    payload = stdin.encode("utf-8") if stdin is not None else None
    try:
        out, err = await asyncio.wait_for(proc.communicate(payload), timeout=timeout)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=5)
        return CliResult(124, "", f"{argv[0]} timed out after {timeout}s")
    return CliResult(proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))


def run_cli_sync(
    argv: list[str],
    *,
    timeout: float = 15.0,
    stdin: str | None = None,
    cwd: str | None = None,
) -> CliResult:
    """Blocking twin of :func:`run_cli`, with the identical rc contract.

    The Sleep engine needs ONE implementation callable from both a sync call
    site (``dedup_sweep``, ``source_rewrite``, ``ask_service``) and an async
    one (``entity_extractor``, ``entity_resolver``). ``asyncio.run`` cannot be
    used from inside a running loop, so the core is synchronous and the async
    seam wraps it in ``asyncio.to_thread`` instead.
    """
    if not argv:
        return CliResult(127, "", "empty argv")
    if shutil.which(argv[0]) is None and not os.path.exists(argv[0]):
        return CliResult(127, "", f"{argv[0]}: not found")
    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": scrubbed_env(),
        "cwd": cwd,
        "timeout": timeout,
    }
    if stdin is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = stdin.encode("utf-8")
    try:
        proc = subprocess.run(argv, **kwargs)  # noqa: S603 - argv is built, never shell
    except subprocess.TimeoutExpired:
        return CliResult(124, "", f"{argv[0]} timed out after {timeout}s")
    except OSError as exc:
        return CliResult(127, "", str(exc))
    return CliResult(
        proc.returncode or 0,
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
    )
```

- [ ] **Step 6: Add the three engine settings**

In `api/config.py`, replace the `llm_mode` block (`:94-110`) comment tail and add three fields after `ollama_base_url`:

```python
    llm_mode: str = "byok"                    # CICADA_LLM_MODE (agent|auto|byok|local)
    # Model name passed to Ollama when llm_mode="local" (litellm bind:
    # "ollama/<ollama_model>"). Does NOT include the "ollama/" prefix itself.
    ollama_model: str = "llama3.1"             # CICADA_OLLAMA_MODEL
    # Base URL of the local Ollama server, forwarded to litellm as api_base.
    ollama_base_url: str = "http://localhost:11434"  # CICADA_OLLAMA_BASE_URL

    # G74(a) — the agent rung (llm_mode="agent"): Sleep runs through the
    # user's own `claude` CLI on their plan. `litellm_model` ids
    # ("gpt-5.4-mini", "openrouter/z-ai/glm-5.2") are meaningless to
    # `claude --model`, so the rung has its own two-model pair mirroring the
    # main/disambiguation split: an alias or a full Claude model id.
    agent_model: str = "sonnet"                     # CICADA_AGENT_MODEL
    agent_disambiguation_model: str = "haiku"       # CICADA_AGENT_DISAMBIGUATION_MODEL
    # Concurrent `claude -p` subprocesses. Stage 1 fans out at MAX_CONCURRENCY
    # (10) and each fan-out slot would otherwise be one more process; 3 keeps
    # the machine usable and the plan's own rate limit further away.
    agent_max_concurrency: int = 3                  # CICADA_AGENT_MAX_CONCURRENCY
```

Update the `llm_mode` docstring comment immediately above it so the last two sentences read:

```python
    # ``"agent"`` runs every call through the user's own ``claude`` CLI on
    # their subscription (G74(a)); ``"auto"`` resolves to the agent rung when
    # the Claude plan probes connected, else the local rung when Ollama is
    # running, else ``"byok"``. Resolution happens once per Sleep cycle in
    # ``engine_select``; ``resolve_llm_fn`` treats an unresolved ``"auto"`` as
    # ``"byok"`` and never shells out synchronously.
```

- [ ] **Step 7: Write `api/services/agent_engine.py`**

```python
"""G74(a) — the Claude Code CLI as a Sleep engine.

One `claude -p` process per LLM call, on the user's own subscription, with
zero API credits. This module owns everything subprocess-shaped: the pinned
argv, stdin marshalling from OpenAI-shaped messages, the envelope parse and
its failure classification, the dual-access response shim, per-stage model and
schema selection, the throttle circuit breaker, and the pre-flight probe.

Three invariants, all load-bearing:

1. **The spawned engine can never write back into memory.** ``--safe-mode``
   disables CLAUDE.md, skills, plugins, hooks and MCP servers;
   ``--strict-mcp-config`` with no ``--mcp-config`` is the independent second
   lock. Together they guarantee the engine cannot call Cicada's own MCP tools
   and consolidate its own consolidation turns.
2. **Never ``--bare``.** It forces ``ANTHROPIC_API_KEY``/``apiKeyHelper`` and
   never reads OAuth — the exact wrong mode for a subscription. The env is
   scrubbed of provider keys (``base.scrubbed_env``) for the same reason.
3. **Prefix-ordered prompts.** Prompt caching persists across separate ``-p``
   processes (spec §4, verified 5.4x on a 58 KB prompt, 1-hour TTL), so the
   stable system text goes to ``--system-prompt`` (argv, constant for a whole
   cycle) and ``marshal_prompt`` NEVER reorders the caller's messages.

The core is synchronous. The async seam wraps it in ``asyncio.to_thread``
rather than the other way around, because sync call sites (``dedup_sweep``,
``source_rewrite``, ``ask_service``) may already be inside a running loop,
where ``asyncio.run`` raises.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from api.services import engine_errors
from api.services.auth import cicada_home
from api.services.connections.base import CliResult

#: ``runner(argv, *, stdin=None, timeout=None, cwd=None) -> CliResult``.
Runner = Callable[..., CliResult]

#: Every flag verified present and accepted together against `claude` 2.1.252
#: (spec §3/§9 V1). ``--tools ""`` is a flag/value pair, hence the empty string.
PINNED_FLAGS: tuple[str, ...] = (
    "-p", "--output-format", "json", "--safe-mode",
    "--strict-mcp-config", "--tools", "", "--no-session-persistence",
)

DEFAULT_AGENT_MODEL = "sonnet"
#: Matches ``entity_extractor.EXTRACTION_TIMEOUT_S`` — the only wall-clock
#: guard Stage 1 has. Call sites that pass ``timeout=`` always win.
DEFAULT_TIMEOUT_S = 300.0

JSON_ONLY_SUFFIX = (
    "Respond with a single JSON object and nothing else — no prose, "
    "no explanation, no markdown fences."
)

#: Per-stage ``--json-schema`` payloads. ONLY stages whose output shape is
#: fully specifiable ship one: a structured-output mode that drops unlisted
#: keys would silently gut entity extraction, and V1b verified the flag only
#: against a trivial schema. Every other stage gets ``JSON_ONLY_SUFFIX`` plus
#: the shared lenient parser (``json_parse``), which is belt-and-braces the
#: spec asks for regardless. Widen this map once a live cycle proves no
#: field-stripping.
SCHEMA_BY_STAGE: dict[str, dict] = {
    "disambiguation": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["same", "different", "unsure"]},
            "reason": {"type": "string"},
        },
        "required": ["decision"],
    },
}

_RATE_LIMIT_MARKERS = ("rate limit", "rate_limit", "too many requests", "overloaded", "429")
_LOGGED_OUT_MARKERS = (
    "not logged in", "not authenticated", "claude auth login",
    "invalid api key", "oauth token has expired", "session expired",
)
_NOT_FOUND_MARKERS = ("model not found", "unknown model", "no such model")

_STATE_LOCK = threading.Lock()
_BREAKER: dict[str, str | None] = {"reason": None}
_MODELS_USED: set[str] = set()


# --------------------------------------------------------------------------- #
# Dual-access response shim (spec §3.1 non-negotiable 1)
# --------------------------------------------------------------------------- #


class _D(dict):
    """A dict whose values are reachable by attribute AND by key.

    Seven Sleep call sites read ``resp.choices[0].message.content``; two
    (``dedup_sweep.py:120``, ``source_rewrite.py:57``) read
    ``resp["choices"][0]["message"]["content"]``. A ``SimpleNamespace`` breaks
    the second; a bare dict breaks the first.
    """

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # so getattr(resp, "_hidden_params", None) works
            raise AttributeError(name) from exc


def _wrap(value: Any) -> Any:
    if isinstance(value, dict):
        return _D({k: _wrap(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_wrap(v) for v in value]
    return value


def _bare_model(model: str) -> str:
    return (model or "").strip().split("/")[-1].lower()


def model_from_envelope(envelope: dict, requested_model: str) -> str:
    """The model that actually did the work.

    ``modelUsage`` is multi-model (V1d: one call reported ``claude-haiku-4-5``
    for an internal side-call *and* the requested ``claude-sonnet-5``), so
    never assume one key. Prefer the entry whose ``canonicalModel`` matches
    what we asked for; when we asked by alias ("sonnet"), fall back to the
    entry that emitted the most output tokens.
    """
    per_model = envelope.get("modelUsage")
    if not isinstance(per_model, dict) or not per_model:
        return requested_model
    want = _bare_model(requested_model)
    for key, info in per_model.items():
        canonical = (info or {}).get("canonicalModel") or key
        if want and (_bare_model(canonical) == want or _bare_model(key) == want):
            return key
    return max(
        per_model.items(),
        key=lambda kv: int((kv[1] or {}).get("outputTokens") or 0),
    )[0]


def equiv_cost_from_envelope(envelope: dict) -> float | None:
    """List-price metering for this call, summed across every model it used.

    ``costBasis: "list"`` says this is metering, not money charged — which is
    exactly why it lands in ``equiv_cost_usd`` and never in ``cost_usd``.
    """
    total = envelope.get("total_cost_usd")
    if isinstance(total, (int, float)) and not isinstance(total, bool):
        return float(total)
    per_model = envelope.get("modelUsage")
    if not isinstance(per_model, dict):
        return None
    costs = [
        float(v["costUSD"]) for v in per_model.values()
        if isinstance(v, dict) and isinstance(v.get("costUSD"), (int, float))
        and not isinstance(v.get("costUSD"), bool)
    ]
    return round(sum(costs), 6) if costs else None


def response_shim(envelope: dict, requested_model: str) -> _D:
    """The envelope, wearing an OpenAI response's clothes.

    ``prompt_tokens`` is the GROSS prompt with the cache counters carried
    alongside as a breakdown of it — the contract
    ``telemetry.usage_from_response`` documents and ``pricing.estimate_cost``
    depends on. Verified necessary: a 58 KB prompt reported ``input_tokens: 2``
    with ``cache_creation_input_tokens: 19631``, so reading ``input_tokens``
    alone would record a 20k-token prompt as 2 (V2b).
    """
    usage = envelope.get("usage") or {}
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    cache_write = int(usage.get("cache_creation_input_tokens") or 0)
    raw_input = int(usage.get("input_tokens") or 0)
    output = int(usage.get("output_tokens") or 0)

    content = envelope.get("result")
    if content is None and envelope.get("structured_output") is not None:
        content = json.dumps(envelope["structured_output"], ensure_ascii=False)

    return _wrap({
        "choices": [{
            "message": {"role": "assistant", "content": content or ""},
            "finish_reason": envelope.get("stop_reason"),
        }],
        "model": model_from_envelope(envelope, requested_model),
        "usage": {
            "prompt_tokens": raw_input + cache_read + cache_write,
            "completion_tokens": output,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write,
            "prompt_tokens_details": {"cached_tokens": cache_read},
        },
    })


# --------------------------------------------------------------------------- #
# argv + prompt
# --------------------------------------------------------------------------- #


def build_argv(
    *,
    model: str,
    system_prompt: str,
    json_schema: dict | None = None,
    binary: str = "claude",
) -> list[str]:
    """The pinned invocation. Never grows a ``--bare``, never a ``--mcp-config``."""
    argv = [binary, *PINNED_FLAGS]
    if model:
        argv += ["--model", model]
    if system_prompt:
        argv += ["--system-prompt", system_prompt]
    if json_schema is not None:
        argv += ["--json-schema", json.dumps(json_schema, separators=(",", ":"))]
    return argv


def marshal_prompt(messages: list[dict] | None) -> tuple[str, str]:
    """Split OpenAI-shaped messages into ``(--system-prompt text, stdin body)``.

    Order is PRESERVED and never rewritten. Prompt-cache affinity (spec §4)
    depends on the caller putting stable content first; reordering here would
    break that contract *and* change meaning.
    """
    system_parts: list[str] = []
    turns: list[tuple[str, str]] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip().lower()
        content = message.get("content")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        if not content.strip():
            continue
        if role == "system":
            system_parts.append(content)
        else:
            turns.append((role, content))
    if len(turns) <= 1:
        body = turns[0][1] if turns else ""
    else:
        body = "\n\n".join(f"{role.upper()}: {text}" for role, text in turns)
    return "\n\n".join(system_parts), body


def scratch_dir() -> Path:
    """The engine's cwd: a scratch dir under ``$CICADA_HOME``.

    Never a memory bank (a stray write must not land in versioned memory) and
    never the repo (``--safe-mode`` already disables CLAUDE.md, but running
    somewhere with nothing to read is the belt).
    """
    path = cicada_home() / "engine-scratch"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def model_for_stage(settings, stage: str | None) -> str:
    """The Claude model id/alias for a stage — mirrors the litellm main/judge split."""
    if (stage or "") == "disambiguation":
        return (getattr(settings, "agent_disambiguation_model", "") or "").strip() or DEFAULT_AGENT_MODEL
    return (getattr(settings, "agent_model", "") or "").strip() or DEFAULT_AGENT_MODEL


# --------------------------------------------------------------------------- #
# Envelope parsing + classification (spec §5 detection order)
# --------------------------------------------------------------------------- #


def _classify_error(envelope: dict, result: CliResult) -> engine_errors.EngineError:
    reason = str(envelope.get("terminal_reason") or envelope.get("subtype") or "").strip().lower()
    detail = " ".join(
        str(envelope.get(key) or "") for key in ("result", "error", "message")
    ).strip()
    blob = f"{detail} {result.stderr or ''}".lower()
    status = envelope.get("api_error_status")
    # The exact shape of a real 429/quota envelope could not be produced on
    # demand (spec §9). Log the whole envelope on every failure so the first
    # real one captured in the wild can tighten the markers below. The
    # envelope carries no credential — argv, stdin and env are never logged.
    logger.warning(f"claude engine error envelope: {json.dumps(envelope, default=str)[:2000]}")

    if reason == "budget_exhausted":
        return engine_errors.EngineExhausted(
            "Claude plan budget is exhausted for this window — Sleep stopped with the queue intact."
        )
    if any(marker in blob for marker in _LOGGED_OUT_MARKERS):
        return engine_errors.EngineUnavailable(
            "Claude Code is signed out — run `claude auth login`, then trigger Sleep again."
        )
    if status == 404 or any(marker in blob for marker in _NOT_FOUND_MARKERS):
        return engine_errors.EngineModelNotFound(
            f"the Claude CLI rejected the model id: {detail[:200]}"
        )
    if status == 429 or any(marker in blob for marker in _RATE_LIMIT_MARKERS):
        return engine_errors.EngineThrottled(f"Claude plan throttled: {detail[:200]}")
    return engine_errors.EngineFailed(
        f"`claude -p` failed ({reason or 'unknown reason'}): {detail[:200]}"
    )


def parse_envelope(result: CliResult) -> dict:
    """``CliResult`` -> the parsed envelope, or the right ``EngineError``.

    Detection order (spec §5): rc 127 -> binary missing; rc 124 -> timeout;
    non-JSON stdout -> unavailable; ``is_error`` -> classify.
    """
    if result.rc == 127:
        return _raise(engine_errors.EngineUnavailable(
            "Claude Code is not installed — install it (npm i -g @anthropic-ai/claude-code) "
            "and run `claude` once to sign in."
        ))
    if result.rc == 124:
        return _raise(engine_errors.EngineTimeout(
            f"`claude -p` timed out: {(result.stderr or '').strip()[:200]}"
        ))
    text = (result.stdout or "").strip()
    if not text:
        return _raise(engine_errors.EngineUnavailable(
            f"`claude -p` produced no output (rc {result.rc}): "
            f"{(result.stderr or '').strip()[:200] or 'no stderr'}"
        ))
    try:
        envelope = json.loads(text)
    except ValueError:
        return _raise(engine_errors.EngineUnavailable(
            f"`claude -p` did not return the JSON envelope (rc {result.rc}): {text[:200]}"
        ))
    if not isinstance(envelope, dict):
        return _raise(engine_errors.EngineProtocolError(
            f"envelope is not a JSON object: {text[:200]}"
        ))
    if envelope.get("is_error"):
        return _raise(_classify_error(envelope, result))
    if envelope.get("result") is None and envelope.get("structured_output") is None:
        return _raise(engine_errors.EngineProtocolError(
            f"envelope carries neither result nor structured_output: {text[:300]}"
        ))
    return envelope


def _raise(exc: engine_errors.EngineError):
    raise exc


# --------------------------------------------------------------------------- #
# Circuit breaker + models-used ledger (process-global, reset per Sleep cycle)
# --------------------------------------------------------------------------- #


def trip_breaker(reason: str) -> bool:
    """Trip the throttle breaker. Returns ``True`` only for the call that tripped it.

    Stage 1 fans out per-episode with no batch abort, so one throttle would be
    re-hit once per remaining episode. After the first, every subsequent call
    fails fast WITHOUT spawning and the cycle stops cleanly, leaving
    ``processed: false`` to do the rest.
    """
    with _STATE_LOCK:
        if _BREAKER["reason"]:
            return False
        _BREAKER["reason"] = reason or "Claude plan throttled"
        return True


def breaker_reason() -> str | None:
    with _STATE_LOCK:
        return _BREAKER["reason"]


def reset_breaker() -> None:
    with _STATE_LOCK:
        _BREAKER["reason"] = None


def record_model_used(model: str | None) -> None:
    """Remember a model the engine actually reported, for the commit trailers."""
    if not model:
        return
    with _STATE_LOCK:
        _MODELS_USED.add(str(model))


def models_used() -> list[str]:
    with _STATE_LOCK:
        return sorted(_MODELS_USED)


def reset_models_used() -> None:
    with _STATE_LOCK:
        _MODELS_USED.clear()


# --------------------------------------------------------------------------- #
# The call
# --------------------------------------------------------------------------- #


def _default_runner() -> Runner:
    from api.services.connections import base

    return base.run_cli_sync


def complete(
    *,
    messages: list[dict],
    model: str,
    stage: str | None = None,
    want_json: bool = False,
    timeout: float = DEFAULT_TIMEOUT_S,
    runner: Runner | None = None,
    binary: str = "claude",
) -> dict:
    """One `claude -p` call. Returns the parsed envelope; raises ``EngineError``.

    Synchronous by design — see the module docstring.
    """
    tripped = breaker_reason()
    if tripped:
        raise engine_errors.EngineThrottled(tripped)

    system_prompt, body = marshal_prompt(messages)
    schema = SCHEMA_BY_STAGE.get(stage or "") if want_json else None
    if want_json and schema is None:
        system_prompt = f"{system_prompt}\n\n{JSON_ONLY_SUFFIX}" if system_prompt else JSON_ONLY_SUFFIX

    argv = build_argv(model=model, system_prompt=system_prompt, json_schema=schema, binary=binary)
    run = runner or _default_runner()
    result = run(argv, stdin=body, timeout=timeout, cwd=str(scratch_dir()))
    return parse_envelope(result)


def probe(*, runner: Runner | None = None, binary: str = "claude", timeout: float = 20.0) -> tuple[bool, str]:
    """Pre-flight: is the agent rung usable right now? Returns ``(ok, sentence)``.

    The sentence is what the Sleep page shows, so it always names the fix.
    """
    run = runner or _default_runner()
    result = run([binary, "auth", "status", "--json"], stdin=None, timeout=timeout, cwd=None)
    if result.rc == 127:
        return False, (
            "Claude Code is not installed — install it (npm i -g @anthropic-ai/claude-code) "
            "and run `claude` once to sign in."
        )
    try:
        info = json.loads((result.stdout or "").strip() or "{}")
    except ValueError:
        return False, "Could not read `claude auth status` — run `claude` once in a terminal."
    if not isinstance(info, dict) or not info.get("loggedIn"):
        return False, "Claude Code is signed out — run `claude auth login`, then trigger Sleep again."
    if info.get("authMethod") not in (None, "claude.ai"):
        return False, (
            "Claude Code is signed in with an API key, not your plan — unset ANTHROPIC_API_KEY "
            "so Sleep runs on the subscription."
        )
    email = info.get("email")
    return True, f"Claude Code signed in as {email}." if email else "Claude Code signed in on this Mac."
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `api/.venv/bin/python -m pytest api/tests/test_agent_engine.py -q`
Expected: PASS (35 tests).

- [ ] **Step 9: Verify nothing else broke**

Run: `api/.venv/bin/python -m pytest api/tests/test_connections_base.py api/tests/test_connection_claude.py api/tests/test_connections_api.py -q`
Expected: PASS — `run_cli`'s new keyword-only params default to the old behaviour, so every adapter is byte-identical.

- [ ] **Step 10: Commit**

```bash
git add api/services/engine_errors.py api/services/agent_engine.py \
        api/services/connections/base.py api/config.py \
        api/tests/conftest.py api/tests/test_agent_engine.py
git commit -F - <<'MSG'
feat(engine): claude -p Sleep engine — argv, envelope, shim, breaker

New agent_engine + engine_errors: the pinned invocation (never --bare),
stdin marshalling that preserves prompt-cache prefix order, envelope parse
with the spec §5 classification order, a dual-access response shim that
folds cache counters into a gross prompt, the throttle circuit breaker and
the pre-flight probe. base.run_cli gains stdin/cwd and a blocking twin.
Zero subprocess spawns in tests: an injected runner replays recorded
envelopes, and a conftest guard fails loudly on any real spawn.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
MSG
```

---

## Task 2: One lenient JSON parser for all seven LLM call sites

Ships value independently of Task 1: three of these sites call bare `json.loads` today, and a single preambled answer makes Stage 4 return `[]`, Stage 3 skip, and Stage 2 answer `"unsure"` — which mints a clarification and splits an entity page.

**Files:**
- Create: `api/services/json_parse.py`
- Modify: `api/services/entity_extractor.py:159-207` (move out, keep the alias), `:276`
- Modify: `api/services/entity_resolver.py:706`
- Modify: `api/services/conflict_resolver.py:729`
- Modify: `api/services/skill_extractor.py:89`
- Modify: `api/services/dedup_sweep.py:120-122`
- Modify: `api/services/source_rewrite.py:57-66`
- Modify: `api/services/ask_service.py:443`
- Test: `api/tests/test_json_parse.py`

**Interfaces:**
- Consumes: nothing from Task 1 (independent).
- Produces: `json_parse.parse_json_object(raw: str | None) -> dict` (raises `ValueError`), `json_parse.parse_json_object_or(raw: str | None, default: dict) -> dict`. `entity_extractor._parse_json_lenient` stays as a re-export alias so `api/tests/test_extractor_robustness.py:43-76` keeps passing unchanged.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_json_parse.py`:

```python
"""G74(a) Task 2 — one lenient JSON parser, used by every LLM JSON call site.

Three sites called bare ``json.loads`` (skill_extractor:89,
conflict_resolver:729, entity_resolver:706) and three carved a substring by
hand (dedup_sweep, source_rewrite, ask_service). A single preambled answer
therefore made Stage 4 return [], Stage 3 skip, and Stage 2 answer "unsure" —
which *creates a clarification and splits the entity page*.
"""
from __future__ import annotations

import json

import pytest

from api.services import json_parse


PREAMBLED = 'Let me think about this.\n```json\n{"decision": "same"}\n```\nHope that helps!'


def test_parses_plain_json():
    assert json_parse.parse_json_object('{"a": 1}') == {"a": 1}


def test_parses_fenced_json():
    assert json_parse.parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_parses_reasoning_preamble_and_trailing_prose():
    assert json_parse.parse_json_object(PREAMBLED) == {"decision": "same"}


def test_parses_a_nested_object_without_stopping_at_the_first_brace():
    raw = 'thinking...\n{"outer": {"inner": {"deep": true}}, "n": 2}\ndone'
    assert json_parse.parse_json_object(raw)["outer"]["inner"]["deep"] is True


def test_braces_inside_strings_do_not_confuse_the_scanner():
    raw = 'x {"body": "a } brace \\" and more {", "ok": true} y'
    assert json_parse.parse_json_object(raw)["ok"] is True


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_empty_raises_value_error(bad):
    with pytest.raises(ValueError):
        json_parse.parse_json_object(bad)


def test_garbage_raises_value_error():
    with pytest.raises(ValueError):
        json_parse.parse_json_object("there is no json object in this text at all")


def test_or_variant_returns_the_default_instead_of_raising():
    assert json_parse.parse_json_object_or("nope", {"verdict": "unsure"}) == {"verdict": "unsure"}


def test_extractor_alias_still_exists_for_the_existing_suite():
    from api.services import entity_extractor

    assert entity_extractor._parse_json_lenient('{"entities": []}') == {"entities": []}


# --------------------------------------------------------------------------- #
# The six re-routed call sites now survive a preambled answer.
# --------------------------------------------------------------------------- #


def _resp(text):
    """A response object satisfying BOTH access styles the call sites use."""
    from api.services.agent_engine import _wrap

    return _wrap({"choices": [{"message": {"content": text}}]})


def test_entity_resolver_judge_survives_a_preambled_answer(monkeypatch):
    import asyncio

    from api.config import Settings
    from api.services import entity_resolver

    async def fake(**kw):
        return _resp(PREAMBLED)

    monkeypatch.setattr(entity_resolver.litellm, "acompletion", fake)
    out = asyncio.run(entity_resolver._llm_judge_same_entity(
        "A", "person", "d", "A.", "person", "b", Settings()))
    assert out == "same"


def test_skill_extractor_survives_a_preambled_answer(monkeypatch):
    import asyncio

    from api.config import Settings
    from api.services import skill_extractor

    async def fake(**kw):
        return _resp('Sure!\n{"skills": [{"name": "Prefers terse summaries"}]}')

    monkeypatch.setattr(skill_extractor.litellm, "acompletion", fake)
    skills = asyncio.run(skill_extractor.detect_patterns(
        [{"id": "x", "action": "create", "name": "X"}], [], Settings()))
    assert skills == [{"name": "Prefers terse summaries"}]


def test_dedup_judge_survives_a_preambled_answer(monkeypatch):
    from api.config import Settings
    from api.services import dedup_sweep, providers

    monkeypatch.setattr(
        providers, "resolve_llm_fn",
        lambda *a, **kw: (lambda **kwargs: _resp('ok:\n{"verdict":"same","confidence":0.9,"winner":"a"}')),
    )
    judge = dedup_sweep._default_judge_fn(Settings())
    assert judge("A body", "B body", "a", "b")["verdict"] == "same"


def test_ask_synthesis_survives_a_preambled_answer():
    from api.services import ask_service

    assert json_parse.parse_json_object(
        '```json\n{"answer": "yes", "confidence": 0.8}\n```'
    )["answer"] == "yes"
    assert ask_service.json_parse is json_parse  # the module is wired in, not re-implemented
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_json_parse.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'api.services.json_parse'`.

- [ ] **Step 3: Create `api/services/json_parse.py`**

Move the body verbatim out of `entity_extractor._parse_json_lenient` (`:159-207`):

```python
"""The one lenient JSON-object parser for every LLM response in Cicada.

Promoted out of ``entity_extractor`` (where it was ``_parse_json_lenient``)
because six other call sites needed it and did not have it: three called bare
``json.loads`` and three carved a ``{...}`` substring by hand. A reasoning
model that emits a preamble, a ```json fence, or trailing commentary is the
normal case, not the exception — and each of those sites failed differently
and silently.

Raises ``ValueError`` (``json.JSONDecodeError`` is a subclass) on empty or
unparseable content so the caller can count the work failed and requeue.
"""
from __future__ import annotations

import json
import re


def parse_json_object(raw: str | None) -> dict:
    """Parse a JSON object from a possibly-noisy LLM response.

    Tolerates ```json fences, leading prose/thinking before the object, and
    trailing commentary after it.
    """
    if not raw or not raw.strip():
        raise ValueError("empty LLM response")
    text = raw.strip()

    # Strip a leading ```json / ``` fence and its closing ``` if present.
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z0-9]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    # Fast path: the whole thing is JSON.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Otherwise carve out the first balanced {...} object (skips reasoning
    # prose before it and any trailing text after it).
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in response")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])  # JSONDecodeError -> ValueError
    raise ValueError("unbalanced JSON object in response")


def parse_json_object_or(raw: str | None, default: dict) -> dict:
    """:func:`parse_json_object`, degrading to ``default`` instead of raising.

    For the two sweep call sites whose contract is "an unparseable answer is
    an *unsure* verdict", not "the sweep failed".
    """
    try:
        return parse_json_object(raw)
    except ValueError:
        return dict(default)
```

- [ ] **Step 4: Re-route all seven call sites**

`api/services/entity_extractor.py` — delete the function body at `:159-207` and replace with the alias, keeping `import re`/`import json` only if still used elsewhere in the file (`json` is used by `entities_to_claims`; `re` is used at `:419` via a local import, so the module-level `import re` at `:6` can go):

```python
from api.services.json_parse import parse_json_object

# Historical name: the parser now lives in ``json_parse`` (six other call
# sites needed it). Kept as an alias — ``api/tests/test_extractor_robustness.py``
# and every reader of this module still reach for it here.
_parse_json_lenient = parse_json_object
```

`api/services/entity_resolver.py:706` — replace `parsed = json.loads(raw)` with:

```python
        parsed = json_parse.parse_json_object(raw)
```

adding `from api.services import json_parse` to its imports.

`api/services/conflict_resolver.py:729` — replace `return json.loads(raw)` with:

```python
    return json_parse.parse_json_object(raw)
```

`api/services/skill_extractor.py:89` — replace `parsed = json.loads(content)` with:

```python
        parsed = json_parse.parse_json_object(content)
```

`api/services/dedup_sweep.py:120-122` — replace the hand-carved substring scan with:

```python
        txt = resp["choices"][0]["message"]["content"]
        return json_parse.parse_json_object_or(txt, {"verdict": "unsure", "confidence": 0.0})
```

(and drop the now-unused `import json` inside `_default_judge_fn`, adding `from api.services import json_parse` beside the `resolve_llm_fn` import).

`api/services/source_rewrite.py:57-66` — replace the `find`/`rfind` block plus its `try` with:

```python
    txt = resp["choices"][0]["message"]["content"]
    parsed = json_parse.parse_json_object_or(txt, {})
    new_body = str(parsed.get("body", "") or "").strip()
    if not new_body:
        return {"entity_id": entity_id, "changed": False,
                "before_words": before, "after_words": before}
```

`api/services/ask_service.py:443` — replace `parsed = json.loads(_strip_fences(raw))` with:

```python
        parsed = json_parse.parse_json_object(raw)
```

and add `from api.services import json_parse` to its imports. Leave `_strip_fences` in place (`:548-555`) — it has other callers to check; if `grep -n "_strip_fences" api` shows `:443` was its only use, delete it in the same commit.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `api/.venv/bin/python -m pytest api/tests/test_json_parse.py api/tests/test_extractor_robustness.py api/tests/test_ask_service.py api/tests/test_dedup_sweep.py api/tests/test_llm_seam_adoption.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS except the 8 documented `test_calendar_registry.py` failures.

- [ ] **Step 7: Commit**

```bash
git add api/services/json_parse.py api/services/entity_extractor.py \
        api/services/entity_resolver.py api/services/conflict_resolver.py \
        api/services/skill_extractor.py api/services/dedup_sweep.py \
        api/services/source_rewrite.py api/services/ask_service.py \
        api/tests/test_json_parse.py
git commit -F - <<'MSG'
fix(llm): one lenient JSON parser for all seven LLM call sites

skill_extractor, conflict_resolver and entity_resolver called bare
json.loads; dedup_sweep, source_rewrite and ask_service each carved a
substring by hand. A single preambled or fenced answer therefore made
Stage 4 return [], Stage 3 skip, and Stage 2 answer "unsure" — which mints
a clarification and splits an entity page. entity_extractor's parser is
promoted to api/services/json_parse and every site routes through it;
the historical _parse_json_lenient name stays as an alias.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
MSG
```

---

## Task 3: The `providers` agent branch — one seam, honest telemetry

**Files:**
- Modify: `api/services/providers.py:135-239`
- Test: `api/tests/test_agent_seam.py`

**Interfaces:**
- Consumes: `agent_engine.complete`, `.response_shim`, `.model_for_stage`, `.equiv_cost_from_envelope`, `.record_model_used`, `.trip_breaker` (Task 1); `engine_errors.EngineError`, `.EngineThrottled` (Task 1); `Settings.agent_max_concurrency` (Task 1).
- Produces: `resolve_llm_fn(..., is_async: bool | None = None, runner: Callable | None = None)` — two new keyword-only params. In agent mode the returned callable has the unchanged signature `fn(*, messages, response_format=None, **kw)` and returns an `agent_engine._D` (sync) or a coroutine resolving to one (async).

**Note on `equiv_cost_usd`:** the spec asks to "extend `telemetry.UsageEvent` with `equiv_cost_usd`". **It already exists** (`api/services/telemetry.py:43`) and `consumption_stats` already reads it in `summary` (`:100`), `calendar` (`:153`), `stats` (`:202`) and `per_connection` (`:246`). This task therefore *populates* it from the envelope rather than adding it — and adds the regression test proving the dashboard aggregations still work with a `cost_usd: None` / `equiv_cost_usd: 0.09` event.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_agent_seam.py`:

```python
"""G74(a) Task 3 — the `llm_mode="agent"` branch of resolve_llm_fn.

The seam contract (spec §2) is non-negotiable: dual access, sync/async
duality, accept-and-drop unknown kwargs except `timeout`, optional `usage`.
Zero spawns: every test injects a runner.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from api.config import Settings
from api.services import agent_engine, engine_errors, providers
from api.services.connections.base import CliResult
from api.services.telemetry import UsageEvent


def _agent_settings(**kw):
    return Settings(llm_mode="agent", agent_model="sonnet",
                    agent_disambiguation_model="haiku", **kw)


# --------------------------------------------------------------------------- #
# The seam contract
# --------------------------------------------------------------------------- #

def test_sync_call_site_gets_a_dual_access_response(agent_runner, agent_envelopes):
    fn = providers.resolve_llm_fn(_agent_settings(), stage="dedup", sink=lambda e: None,
                                  runner=agent_runner(agent_envelopes["success"]))
    resp = fn(messages=[{"role": "user", "content": "hi"}])
    assert resp.choices[0].message.content == '{"entities": [], "relationships": []}'
    assert resp["choices"][0]["message"]["content"] == '{"entities": [], "relationships": []}'


def test_async_call_site_gets_an_awaitable(agent_runner, agent_envelopes):
    import litellm

    fn = providers.resolve_llm_fn(_agent_settings(), completion=litellm.acompletion,
                                  stage="extraction", sink=lambda e: None,
                                  runner=agent_runner(agent_envelopes["success"]))
    result = fn(messages=[{"role": "user", "content": "hi"}])
    assert asyncio.iscoroutine(result) or hasattr(result, "__await__")
    resp = asyncio.run(result)
    assert resp.choices[0].message.content


def test_is_async_override_wins_over_inference(agent_runner, agent_envelopes):
    """V6: iscoroutinefunction(litellm.acompletion) is True and (completion) is
    False, so inference is sound — but the override exists for callers that
    pass neither."""
    fn = providers.resolve_llm_fn(_agent_settings(), is_async=True, sink=lambda e: None,
                                  runner=agent_runner(agent_envelopes["success"]))
    resp = asyncio.run(fn(messages=[{"role": "user", "content": "hi"}]))
    assert resp["model"] == "claude-sonnet-5"


def test_unknown_kwargs_are_dropped_but_timeout_is_honoured(agent_runner, agent_envelopes):
    runner = agent_runner(agent_envelopes["success"])
    fn = providers.resolve_llm_fn(_agent_settings(), sink=lambda e: None, runner=runner)
    fn(messages=[{"role": "user", "content": "hi"}],
       response_format={"type": "json_object"},
       extra_body={"reasoning": {"enabled": False}}, temperature=0, max_tokens=100,
       timeout=42)
    call = runner.calls[0]
    assert call["timeout"] == 42.0
    argv = " ".join(call["argv"])
    for leaked in ("reasoning", "temperature", "max_tokens", "extra_body"):
        assert leaked not in argv


def test_stage_selects_the_cheaper_judge_model(agent_runner, agent_envelopes):
    runner = agent_runner(agent_envelopes["structured"])
    fn = providers.resolve_llm_fn(_agent_settings(), stage="disambiguation",
                                  sink=lambda e: None, runner=runner)
    fn(messages=[{"role": "user", "content": "a vs b"}], response_format={"type": "json_object"})
    argv = runner.calls[0]["argv"]
    assert argv[argv.index("--model") + 1] == "haiku"


# --------------------------------------------------------------------------- #
# Telemetry: honest numbers for a subscription call (spec §6)
# --------------------------------------------------------------------------- #

def test_agent_event_is_subscription_shaped(agent_runner, agent_envelopes):
    events: list[UsageEvent] = []
    fn = providers.resolve_llm_fn(_agent_settings(), stage="extraction",
                                  sink=events.append, bank="lab",
                                  runner=agent_runner(agent_envelopes["success"]))
    fn(messages=[{"role": "user", "content": "hi"}])

    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "llm_call" and ev.stage == "extraction" and ev.bank == "lab"
    assert ev.engine == "claude-cli"
    # Must EQUAL the adapter id: consumption_stats.per_connection joins strictly on it.
    assert ev.connection == "claude-plan"
    assert ev.billing == "subscription"
    assert ev.model == "claude-sonnet-5"          # what the CLI actually used
    assert ev.cost_usd is None                    # a plan call is never money
    assert ev.equiv_cost_usd == 0.092             # list-price metering only
    assert (ev.input_tokens, ev.output_tokens) == (19633, 57)
    assert ev.cache_write_tokens == 19631
    assert ev.ok and ev.duration_ms is not None


def test_byok_events_are_byte_identical_to_before():
    """The non-agent path must not move. Same assertions as
    test_seam_telemetry.test_sync_call_records_event."""
    class _Resp:
        def __init__(self):
            self.choices = [type("C", (), {"message": type("M", (), {"content": "{}"})()})()]
            self.usage = {"prompt_tokens": 120, "completion_tokens": 30}
            self._hidden_params = {"response_cost": 0.002}

    events: list[UsageEvent] = []
    fn = providers.resolve_llm_fn(Settings(litellm_model="gpt-5.4-mini"),
                                  completion=lambda **kw: _Resp(),
                                  stage="ask", sink=events.append)
    fn(messages=[])
    ev = events[0]
    assert ev.engine == "litellm" and ev.connection == "byok-openai" and ev.billing == "usage"
    assert ev.cost_usd == 0.002


def test_a_failed_agent_call_records_not_ok_and_reraises(agent_runner, agent_envelopes):
    events: list[UsageEvent] = []
    fn = providers.resolve_llm_fn(_agent_settings(), sink=events.append,
                                  runner=agent_runner(agent_envelopes["budget_exhausted"]))
    with pytest.raises(engine_errors.EngineExhausted):
        fn(messages=[{"role": "user", "content": "hi"}])
    assert len(events) == 1 and events[0].ok is False and events[0].engine == "claude-cli"


def test_the_first_throttle_writes_the_first_ever_throttle_event(agent_runner, agent_envelopes):
    """telemetry.KINDS has listed "throttle" and consumption_stats:249 has
    counted throttle_events since G51 — nothing has ever written one."""
    events: list[UsageEvent] = []
    fn = providers.resolve_llm_fn(_agent_settings(), stage="extraction", sink=events.append,
                                  runner=agent_runner(agent_envelopes["rate_limited"]))
    with pytest.raises(engine_errors.EngineThrottled):
        fn(messages=[{"role": "user", "content": "hi"}])
    kinds = [e.kind for e in events]
    assert kinds.count("throttle") == 1
    throttle = next(e for e in events if e.kind == "throttle")
    assert throttle.throttled is True and throttle.connection == "claude-plan"
    assert throttle.invocations == 0 and throttle.ok is False


def test_only_one_throttle_event_per_cycle_even_across_many_calls(agent_runner, agent_envelopes):
    events: list[UsageEvent] = []
    runner = agent_runner(agent_envelopes["rate_limited"])
    fn = providers.resolve_llm_fn(_agent_settings(), sink=events.append, runner=runner)
    for _ in range(5):
        with pytest.raises(engine_errors.EngineThrottled):
            fn(messages=[{"role": "user", "content": "hi"}])
    assert sum(1 for e in events if e.kind == "throttle") == 1
    # Only the tripping call spawned; the other four failed fast.
    assert len(runner.calls) == 1


def test_the_dashboard_aggregations_survive_a_null_cost_event():
    """The Usage page must total a subscription event without crashing on the
    None cost, and attribute it to the claude-plan card."""
    from api.services import consumption_stats

    ev = UsageEvent(kind="llm_call", connection="claude-plan", engine="claude-cli",
                    billing="subscription", model="claude-sonnet-5",
                    input_tokens=19633, output_tokens=57,
                    cost_usd=None, equiv_cost_usd=0.092)
    rows = consumption_stats.per_connection(
        [ev], [{"id": "claude-plan", "label": "Claude plan",
                "billing": "subscription", "connected": True, "priceUsdMonth": 100.0}])
    assert rows[0]["cost_usd"] is None            # never presented as spend
    assert rows[0]["equiv_cost_usd"] == 0.092
    assert rows[0]["tokens"] == 19690


def test_the_rung_semaphore_caps_concurrent_spawns():
    """Stage 1 fans out at MAX_CONCURRENCY=10; the rung must not turn that into
    10 concurrent `claude` processes."""
    import threading

    live = 0
    peak = 0
    lock = threading.Lock()

    def runner(argv, *, stdin=None, timeout=None, cwd=None):
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        try:
            import time as _t
            _t.sleep(0.02)
            return CliResult(0, json.dumps({
                "is_error": False, "result": "{}", "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1}}), "")
        finally:
            with lock:
                live -= 1

    import litellm

    fn = providers.resolve_llm_fn(_agent_settings(agent_max_concurrency=2),
                                  completion=litellm.acompletion,
                                  sink=lambda e: None, runner=runner)

    async def _fan_out():
        await asyncio.gather(*(fn(messages=[{"role": "user", "content": "x"}]) for _ in range(8)))

    asyncio.run(_fan_out())
    assert peak <= 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_agent_seam.py -q`
Expected: FAIL — `TypeError: resolve_llm_fn() got an unexpected keyword argument 'runner'`.

- [ ] **Step 3: Implement the branch in `providers.py`**

Add `import asyncio` beside `import inspect` (`:22`), add `from api.services import engine_errors, pricing, telemetry` to `:32`, and add the module-level rung semaphore just above `resolve_llm_fn`:

```python
#: Wall-clock default for an agent call when the caller passes no ``timeout``.
#: Matches ``entity_extractor.EXTRACTION_TIMEOUT_S`` — the only guard Stage 1 has.
AGENT_DEFAULT_TIMEOUT_S = 300.0

# One process-wide cap on concurrent `claude -p` subprocesses. Stage 1 fans out
# at MAX_CONCURRENCY (10) and Stage 2 is sequential, so without this the rung
# would put 10 CLI processes on the machine at once and walk straight into the
# plan's own rate limit. A threading (not asyncio) semaphore because the agent
# core is synchronous and is shared by both the sync and async call paths.
_AGENT_SEM_LOCK = threading.Lock()
_AGENT_SEM: tuple[int, threading.BoundedSemaphore] | None = None


def _agent_semaphore(limit: int) -> threading.BoundedSemaphore:
    global _AGENT_SEM
    limit = max(1, int(limit or 1))
    with _AGENT_SEM_LOCK:
        if _AGENT_SEM is None or _AGENT_SEM[0] != limit:
            _AGENT_SEM = (limit, threading.BoundedSemaphore(limit))
        return _AGENT_SEM[1]
```

Extend the signature (`:135-143`) with two keyword-only params:

```python
def resolve_llm_fn(
    settings: Settings,
    *,
    model: str | None = None,
    completion: LlmFn | None = None,
    stage: str | None = None,
    sink: Callable[[telemetry.UsageEvent], None] | None = None,
    bank: str | None = None,
    is_async: bool | None = None,
    runner: Callable[..., Any] | None = None,
) -> LlmFn:
```

and document them in the docstring's Args block:

```
        is_async: force the returned callable to be awaitable (``True``) or
            blocking (``False``). Defaults to
            ``inspect.iscoroutinefunction(completion)``: verified sound
            (``litellm.acompletion`` is a coroutine function,
            ``litellm.completion`` is not), but in ``llm_mode="agent"`` the
            injected ``completion`` is never called, so the override exists
            for callers that pass neither.
        runner: injected subprocess runner for ``llm_mode="agent"``
            (``runner(argv, *, stdin, timeout, cwd) -> CliResult``). Tests
            always pass one; production leaves it ``None`` and gets
            ``connections.base.run_cli_sync``.
```

Replace the body from `:186` (the `is_local` line) through `:239` (`return _call`) with:

```python
    if is_async is None:
        is_async = inspect.iscoroutinefunction(completion)

    # "auto" is resolved ONCE per Sleep cycle by ``engine_select`` (it has to
    # probe the connections registry, which is async and shells out). An
    # unresolved "auto" reaching this synchronous seam degrades to byok rather
    # than blocking a request thread on a subprocess probe.
    mode = (settings.llm_mode or "byok").strip().lower()
    is_agent = mode == "agent"
    is_local = (not is_agent) and (mode == "local" or resolved_model.startswith("ollama/"))
    if is_local and not resolved_model.startswith("ollama/"):
        resolved_model = f"ollama/{settings.ollama_model}"

    is_openrouter = resolved_model.startswith("openrouter/")
    headers = _openrouter_headers(settings) if is_openrouter else None

    if is_agent:
        # A plan call is not money and does not belong to the disconnected
        # BYOK API-key card. `connection` must EQUAL the adapter id —
        # consumption_stats.per_connection joins strictly on it.
        engine_label, connection, billing = "claude-cli", "claude-plan", "subscription"
        # `litellm_model` ids mean nothing to `claude --model`; the rung has
        # its own model pair (settings.agent_model / agent_disambiguation_model).
        argv_model = agent_engine.model_for_stage(settings, stage)
    else:
        engine_label = "litellm"
        connection, billing = telemetry.connection_for_model(resolved_model)
        argv_model = resolved_model

    def _emit(resp, started: float, ok: bool, *, model_used: str | None = None,
              equiv_override: float | None = None) -> None:
        try:
            usage = telemetry.usage_from_response(resp) if ok else telemetry.usage_from_response(None)
            event_model = model_used or (argv_model if is_agent else resolved_model)
            if is_agent:
                # `costBasis: "list"` says the envelope's figure is metering,
                # not money charged — so it is an equivalent, never a spend.
                cost = None
                equiv = equiv_override
                if equiv is None:
                    equiv = pricing.estimate_cost(
                        event_model, usage["input_tokens"], usage["output_tokens"],
                        usage["cache_read_tokens"], usage["cache_write_tokens"])
            else:
                cost = None if billing == "free" else usage["cost_usd"]
                equiv = pricing.estimate_cost(
                    resolved_model, usage["input_tokens"], usage["output_tokens"],
                    usage["cache_read_tokens"], usage["cache_write_tokens"])
                if equiv is None:
                    equiv = cost
            sink(telemetry.UsageEvent(
                kind="llm_call", stage=stage or "unknown", connection=connection,
                engine=engine_label, model=event_model, bank=bank_label, billing=billing,
                input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
                cache_read_tokens=usage["cache_read_tokens"],
                cache_write_tokens=usage["cache_write_tokens"],
                cost_usd=cost, equiv_cost_usd=equiv,
                duration_ms=int((time.perf_counter() - started) * 1000), ok=ok,
            ))
        except Exception as exc:  # a sink must never break an LLM call
            logger.warning(f"telemetry sink failed: {exc}")

    def _emit_throttle(exc: Exception) -> None:
        """The first ``kind="throttle"`` event this codebase has ever written.

        ``telemetry.KINDS`` has listed it and ``consumption_stats:249`` has
        counted ``throttle_events`` since G51; nothing produced one.
        """
        try:
            sink(telemetry.UsageEvent(
                kind="throttle", stage=stage or "unknown", connection=connection,
                engine=engine_label, model=argv_model, bank=bank_label, billing=billing,
                invocations=0, throttled=True, ok=False, refs={"detail": str(exc)[:300]},
            ))
        except Exception as sink_exc:
            logger.warning(f"telemetry sink failed: {sink_exc}")

    def _agent_invoke(messages, response_format, timeout: float):
        started = time.perf_counter()
        with _agent_semaphore(getattr(settings, "agent_max_concurrency", 3)):
            try:
                envelope = agent_engine.complete(
                    messages=messages, model=argv_model, stage=stage,
                    want_json=response_format is not None, timeout=timeout, runner=runner,
                )
            except engine_errors.EngineThrottled as exc:
                # Trip BEFORE emitting so a concurrent caller cannot also trip.
                newly_tripped = agent_engine.trip_breaker(str(exc))
                _emit(None, started, ok=False)
                if newly_tripped:
                    _emit_throttle(exc)
                raise
            except engine_errors.EngineError:
                _emit(None, started, ok=False)
                raise
        resp = agent_engine.response_shim(envelope, argv_model)
        used = resp["model"]
        agent_engine.record_model_used(used)
        _emit(resp, started, ok=True, model_used=used,
              equiv_override=agent_engine.equiv_cost_from_envelope(envelope))
        return resp

    def _agent_call(*, messages, response_format=None, **kw):
        # Accept-and-drop every unknown kwarg (`extra_body`, `temperature`,
        # `max_tokens`, `api_base`, ...) — none of them have an argv form.
        # `timeout` is the exception: it is the only wall-clock guard Stage 1
        # has (entity_extractor.py:138).
        raw_timeout = kw.get("timeout")
        timeout = float(raw_timeout) if raw_timeout else AGENT_DEFAULT_TIMEOUT_S
        if is_async:
            return asyncio.to_thread(_agent_invoke, messages, response_format, timeout)
        return _agent_invoke(messages, response_format, timeout)

    if is_agent:
        return _agent_call

    def _call(*, messages, response_format=None, **kw):
        call_kw: dict[str, Any] = {"model": resolved_model, "messages": messages, **kw}
        if response_format is not None:
            call_kw["response_format"] = response_format
        if headers is not None and "extra_headers" not in call_kw:
            call_kw["extra_headers"] = headers
        if is_local and "api_base" not in call_kw:
            call_kw["api_base"] = settings.ollama_base_url
        started = time.perf_counter()
        try:
            result = completion(**call_kw)
        except Exception:
            _emit(None, started, ok=False)
            raise
        if inspect.isawaitable(result):
            async def _awaited():
                try:
                    resp = await result
                except Exception:
                    _emit(None, started, ok=False)
                    raise
                _emit(resp, started, ok=True)
                return resp

            return _awaited()
        _emit(result, started, ok=True)
        return result

    return _call
```

Add `from api.services import agent_engine` **inside** `resolve_llm_fn`, immediately before the `if is_agent:` block, to keep the module's import graph acyclic (`agent_engine` imports `connections.base`, which imports `api.models.schemas`):

```python
    from api.services import agent_engine
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `api/.venv/bin/python -m pytest api/tests/test_agent_seam.py -q`
Expected: PASS (12 tests).

- [ ] **Step 5: Verify the byok/local paths did not move**

Run: `api/.venv/bin/python -m pytest api/tests/test_providers.py api/tests/test_seam_telemetry.py api/tests/test_llm_seam_adoption.py api/tests/test_local_llm.py api/tests/test_consumption_stats.py api/tests/test_consumption_api.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/services/providers.py api/tests/test_agent_seam.py
git commit -F - <<'MSG'
feat(engine): resolve_llm_fn grows the llm_mode="agent" rung

One branch in the seam: agent mode spawns `claude -p` through agent_engine
instead of calling litellm, keeps the same callable signature, honours
`timeout` and drops every other unknown kwarg, and caps concurrent
subprocesses at agent_max_concurrency (default 3). Telemetry becomes
branch-dependent and honest: engine="claude-cli", connection="claude-plan"
(the adapter id per_connection joins on), billing="subscription",
cost_usd=None, and the envelope's list-price figure in equiv_cost_usd.
The first `kind="throttle"` event this codebase has ever written.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
MSG
```

---

## Task 4: Error taxonomy wired in — retries, classification, and the resolver's failure/uncertainty split

**Files:**
- Modify: `api/services/entity_extractor.py:152-156` (retry tuple), `:277-289` (backoff), `:371-379` (classifier)
- Modify: `api/services/entity_resolver.py:711-713`
- Test: `api/tests/test_engine_error_taxonomy.py`

**Interfaces:**
- Consumes: `engine_errors.RETRYABLE`, `EngineThrottled`, `EngineExhausted`, `EngineUnavailable`, `EngineModelNotFound`, `EngineError` (Task 1); `agent_engine.breaker_reason` (Task 1).
- Produces: no new public API. `entity_extractor._EXTRACT_RETRYABLE` widens; `_llm_judge_same_entity` may now raise `EngineError` instead of always returning a string.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_engine_error_taxonomy.py`:

```python
"""G74(a) Task 4 — engine failures are visible, retried correctly, and never
mistaken for a model's opinion.

Two pre-existing bugs are fixed here and both predate the rung:
  * `_EXTRACT_RETRYABLE` is litellm-exception-typed, so a CLI failure matched
    nothing and got ZERO retries.
  * `_llm_judge_same_entity`'s blanket `except -> "unsure"` turned an engine
    failure into a clarification and a split entity page, while the cycle
    reported success.
"""
from __future__ import annotations

import asyncio

import pytest

from api.config import Settings
from api.services import agent_engine, engine_errors, entity_extractor, entity_resolver, providers


def _agent_settings():
    return Settings(llm_mode="agent", agent_model="sonnet", agent_disambiguation_model="haiku")


def _extract_with(monkeypatch, runner):
    """Point entity_extractor's seam at an injected agent runner."""
    real = providers.resolve_llm_fn

    def patched(settings, **kw):
        kw.setdefault("runner", runner)
        kw.setdefault("sink", lambda e: None)
        return real(settings, **kw)

    monkeypatch.setattr(providers, "resolve_llm_fn", patched)


# --------------------------------------------------------------------------- #
# Retry widening
# --------------------------------------------------------------------------- #

def test_engine_errors_are_in_the_retry_tuple():
    for exc in (engine_errors.EngineTimeout, engine_errors.EngineProtocolError,
                engine_errors.EngineFailed):
        assert issubclass(exc, entity_extractor._EXTRACT_RETRYABLE)


def test_non_transient_engine_errors_are_not_retried():
    for exc in (engine_errors.EngineThrottled, engine_errors.EngineUnavailable,
                engine_errors.EngineExhausted, engine_errors.EngineModelNotFound):
        assert not issubclass(exc, entity_extractor._EXTRACT_RETRYABLE)


def test_a_timed_out_chunk_is_retried_once_then_succeeds(monkeypatch, agent_runner, agent_envelopes):
    from api.services.connections.base import CliResult

    runner = agent_runner(CliResult(124, "", "timed out"), agent_envelopes["success"])
    _extract_with(monkeypatch, runner)
    monkeypatch.setattr(asyncio, "sleep", lambda *_: asyncio.sleep(0))
    parsed = asyncio.run(entity_extractor._extract_chunk("ep1", "body", 0, 1, _agent_settings()))
    assert parsed == {"entities": [], "relationships": []}
    assert len(runner.calls) == 2


def test_a_signed_out_engine_is_not_retried(monkeypatch, agent_runner, agent_envelopes):
    runner = agent_runner(agent_envelopes["not_logged_in"])
    _extract_with(monkeypatch, runner)
    with pytest.raises(engine_errors.EngineUnavailable):
        asyncio.run(entity_extractor._extract_chunk("ep1", "body", 0, 1, _agent_settings()))
    assert len(runner.calls) == 1


# --------------------------------------------------------------------------- #
# The per-episode classifier
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("envelope_key,needle", [
    ("not_logged_in", "signed out"),
    ("budget_exhausted", "budget"),
    ("model_not_found", "model"),
    ("rate_limited", "throttled"),
])
def test_extract_logs_a_specific_reason_per_engine_failure(
        monkeypatch, agent_runner, agent_envelopes, caplog, envelope_key, needle):
    runner = agent_runner(agent_envelopes[envelope_key])
    _extract_with(monkeypatch, runner)
    episodes = [{"id": "ep_2026-09-01_001", "content": "hello", "timestamp": "2026-09-01T10:00:00"}]
    with caplog.at_level("ERROR"):
        out = asyncio.run(entity_extractor.extract(episodes, _agent_settings()))
    assert out == []                                   # the episode requeues
    assert needle in caplog.text.lower()


def test_a_throttle_stops_the_batch_instead_of_re_hitting_it_per_episode(
        monkeypatch, agent_runner, agent_envelopes):
    """Stage 1 fans out per-episode with no batch abort; without the breaker
    one throttle is re-hit once per remaining episode."""
    runner = agent_runner(agent_envelopes["rate_limited"])
    _extract_with(monkeypatch, runner)
    episodes = [{"id": f"ep_2026-09-01_{i:03d}", "content": "hello",
                 "timestamp": "2026-09-01T10:00:00"} for i in range(12)]
    out = asyncio.run(entity_extractor.extract(episodes, _agent_settings()))
    assert out == []                                   # every episode stays queued
    assert len(runner.calls) == 1                      # exactly one spawn, then fail-fast
    assert agent_engine.breaker_reason() is not None


def test_a_throttled_cycle_mints_no_clarifications(monkeypatch, agent_runner, agent_envelopes):
    """The whole point: a throttle must not become graph damage."""
    runner = agent_runner(agent_envelopes["rate_limited"])
    _extract_with(monkeypatch, runner)
    episodes = [{"id": "ep_2026-09-01_001", "content": "hello", "timestamp": "2026-09-01T10:00:00"}]
    assert asyncio.run(entity_extractor.extract(episodes, _agent_settings())) == []


# --------------------------------------------------------------------------- #
# entity_resolver: engine failure is NOT model uncertainty
# --------------------------------------------------------------------------- #

def test_judge_raises_on_engine_failure_instead_of_answering_unsure(
        monkeypatch, agent_runner, agent_envelopes):
    """An `except -> "unsure"` here creates a clarification and splits the
    entity page: the inbox floods and the graph fragments while the cycle
    reports success."""
    runner = agent_runner(agent_envelopes["budget_exhausted"])
    _extract_with(monkeypatch, runner)
    with pytest.raises(engine_errors.EngineExhausted):
        asyncio.run(entity_resolver._llm_judge_same_entity(
            "Francesco", "person", "d", "Francesco B.", "person", "b", _agent_settings()))


def test_judge_still_answers_unsure_on_a_genuinely_ambiguous_reply(monkeypatch):
    """Model uncertainty is unchanged — only ENGINE failure is escalated."""
    from api.services.agent_engine import _wrap

    async def fake(**kw):
        return _wrap({"choices": [{"message": {"content": '{"decision": "maybe?"}'}}]})

    monkeypatch.setattr(entity_resolver.litellm, "acompletion", fake)
    out = asyncio.run(entity_resolver._llm_judge_same_entity(
        "A", "person", "d", "A.", "person", "b", Settings()))
    assert out == "unsure"


def test_judge_still_swallows_a_malformed_reply_as_unsure(monkeypatch):
    from api.services.agent_engine import _wrap

    async def fake(**kw):
        return _wrap({"choices": [{"message": {"content": "not json at all"}}]})

    monkeypatch.setattr(entity_resolver.litellm, "acompletion", fake)
    out = asyncio.run(entity_resolver._llm_judge_same_entity(
        "A", "person", "d", "A.", "person", "b", Settings()))
    assert out == "unsure"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_engine_error_taxonomy.py -q`
Expected: FAIL — `test_engine_errors_are_in_the_retry_tuple` fails first (`_EXTRACT_RETRYABLE` is litellm-typed only).

- [ ] **Step 3: Widen the retry tuple and the backoff**

In `api/services/entity_extractor.py`, add `from api.services import engine_errors` beside the existing service imports and replace `:150-156`:

```python
# Errors worth one retry inside a single chunk call: transient rate limits,
# timeouts, and a malformed/empty response (``parse_json_object`` raises
# ValueError; ``json.JSONDecodeError`` is a ValueError subclass).
#
# G74(a): the tuple was litellm-exception-typed ONLY, so under
# ``llm_mode="agent"`` a CLI failure matched nothing and got zero retries.
# ``engine_errors.RETRYABLE`` adds the three subprocess failures worth one more
# attempt — deliberately NOT ``EngineThrottled`` (the breaker handles it; a
# retry would just spawn again), ``EngineUnavailable``, ``EngineExhausted`` or
# ``EngineModelNotFound``, all of which need a human rather than a retry.
_EXTRACT_RETRYABLE = (
    litellm.exceptions.RateLimitError,
    litellm.exceptions.Timeout,
    ValueError,
    *engine_errors.RETRYABLE,
)
```

and the backoff choice at `:280-282`:

```python
        # Rate limits need a real cooldown; timeouts/parse failures retry fast.
        backoff = 10 if isinstance(e, litellm.exceptions.RateLimitError) else 2
```

becomes:

```python
        # Rate limits need a real cooldown; timeouts/parse failures retry fast.
        slow = isinstance(e, (litellm.exceptions.RateLimitError, engine_errors.EngineTimeout))
        backoff = 10 if slow else 2
```

- [ ] **Step 4: Add the classification branches**

Replace `api/services/entity_extractor.py:371-379` (inside `_do_process`) with:

```python
            except litellm.exceptions.AuthenticationError as e:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — auth error (check API key): {e}")
            except litellm.exceptions.NotFoundError:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — model not found: {settings.litellm_model}")
            # G74(a): the agent rung's failures are subprocess-shaped. Each one
            # names its own fix so the Sleep page never says "check API credits"
            # for a plan that has no credits to check.
            except engine_errors.EngineThrottled as e:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — Claude plan throttled: {e}")
            except engine_errors.EngineExhausted as e:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — Claude plan budget exhausted: {e}")
            except engine_errors.EngineUnavailable as e:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — Claude Code is signed out or missing: {e}")
            except engine_errors.EngineModelNotFound as e:
                failed += 1
                logger.error(
                    f"  [{i+1}/{total}] {ep_id} — model not accepted by the Claude CLI "
                    f"({settings.agent_model}): {e}"
                )
            except engine_errors.EngineError as e:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — engine failure: {type(e).__name__}: {e}")
            except Exception as e:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — {type(e).__name__}: {e}")
```

- [ ] **Step 5: Fix the resolver's failure/uncertainty conflation**

Replace `api/services/entity_resolver.py:711-713`:

```python
    except engine_errors.EngineError:
        # G74(a): an ENGINE failure is not a model's uncertainty. Flattening it
        # to "unsure" here created a clarification and split the entity page —
        # the inbox floods and the graph fragments while the cycle reports
        # success. Propagate so the cycle stops with the episode queue intact.
        raise
    except Exception as e:
        logger.debug(f"Disambiguation judge failed for {new_name} vs {existing_name}: {e}")
        return "unsure"
```

adding `from api.services import engine_errors` to the module's imports.

Then check every caller between the judge and the stage boundary lets `EngineError` through. Run:

```bash
grep -n "_llm_judge_same_entity\|_find_llm_candidate_match" api/services/entity_resolver.py
```

For each `try:` wrapping one of those calls, add `except engine_errors.EngineError: raise` as the **first** handler, above the existing broad `except`. If there is none, nothing to do — the exception already reaches `sleep_cycle.run`, which is exactly where the requeue happens (`_mark_episodes_processed` is never reached, so every episode stays `processed: false`).

- [ ] **Step 6: Run the tests to verify they pass**

Run: `api/.venv/bin/python -m pytest api/tests/test_engine_error_taxonomy.py -q`
Expected: PASS (13 tests).

- [ ] **Step 7: Verify the entity path did not move**

Run: `api/.venv/bin/python -m pytest api/tests/test_extractor_robustness.py api/tests/test_entity_merge.py api/tests/test_sleep_resumable.py api/tests/test_llm_seam_adoption.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add api/services/entity_extractor.py api/services/entity_resolver.py \
        api/tests/test_engine_error_taxonomy.py
git commit -F - <<'MSG'
fix(sleep): engine failures are retried, classified, and never "unsure"

_EXTRACT_RETRYABLE was litellm-exception-typed, so a CLI failure matched
nothing and got zero retries; it now includes the three transient engine
errors and pointedly excludes throttle/exhausted/signed-out/model-not-found.
Stage 1 gains a branch per engine failure so each one names its own fix. And
_llm_judge_same_entity stops flattening engine failures into "unsure" — that
minted a clarification and split the entity page while the cycle reported
success. Uncertainty from the MODEL still answers "unsure", unchanged.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
MSG
```

---

## Task 5: Honest engine state — the abort ordering fix, the pre-flight probe, and `last_engine`

Spec §1: with a non-empty queue and no engine, `sleep_cycle.py:261` returns *before* `_warm_logos_safely` (`:474`) and `_poll_connectors_safely` (`:501`), and `_refresh_questions_safely` only runs in the zero-episode idle branch (`:231`). **Capturing more episodes makes Sleep do strictly less work.** This is independent of which engine ships and is fixed here regardless.

**Files:**
- Modify: `api/services/sleep_cycle.py:13-56` (state), `:184-528` (the split)
- Modify: `api/models/schemas.py:895-920`
- Modify: `api/routers/sleep.py:41-62`
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift:495-533`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift:57-62`
- Test: `api/tests/test_sleep_engine_state.py`

**Interfaces:**
- Consumes: `agent_engine.probe`, `.reset_breaker`, `.reset_models_used` (Task 1).
- Produces:
  - `sleep_cycle._StageOutcome(committed: bool = False, questions_refreshed: bool = False)`
  - `sleep_cycle._run_stages(settings, cycle_id, memory_path) -> _StageOutcome`
  - `sleep_cycle._run_engine_independent_tail(memory_path, settings, outcome) -> None`
  - `sleep_cycle._tree_is_clean(memory_path) -> bool`
  - `sleep_cycle._engine_label(settings) -> str` — `"claude-cli"` | `"ollama"` | `"litellm"`. **Task 7 replaces the body of this with a call into `engine_select`; keep the name.**
  - `sleep_cycle._stage1_failure_message(engine: str) -> str`
  - `SleepState.last_engine: str | None`, `SleepState.engine_detail: str | None`
  - `SleepStatusResponse.last_engine` / `.engine_detail`; Swift `SleepStatusResponse.lastEngine` / `.engineDetail`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_sleep_engine_state.py`:

```python
"""G74(a) Task 5 — the abort is no longer upside-down, and the engine is honest.

The old ordering meant a non-empty queue with no engine did LESS work than an
empty one: `return` at sleep_cycle.py:261 skipped the logo warm-up, the
connector poll and the question refresh — all three of which need no LLM.
"""
from __future__ import annotations

import asyncio

import pytest

from api.config import Settings
from api.services import agent_engine, git_service, markdown_parser, predicates, sleep_cycle


def _seed(tmp_path, *, unprocessed: int):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    (memory / "inbox").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    for i in range(unprocessed):
        markdown_parser.write(
            memory / "episodes" / f"ep_2026-09-01_{i:03d}.md",
            {"id": f"ep_2026-09-01_{i:03d}", "processed": False, "source": "mcp",
             "timestamp": f"2026-09-01T10:0{i}:00"},
            "Episode body about project X and tool Y.",
        )
    return memory


@pytest.fixture
def tail_spy(monkeypatch):
    """Record which engine-independent steps ran, in order."""
    ran: list[str] = []

    async def _logos(memory_path):
        ran.append("logos")

    async def _connectors(memory_path):
        ran.append("connectors")

    async def _questions(memory_path, settings):
        ran.append("questions")

    monkeypatch.setattr(sleep_cycle, "_warm_logos_safely", _logos)
    monkeypatch.setattr(sleep_cycle, "_poll_connectors_safely", _connectors)
    monkeypatch.setattr(sleep_cycle, "_refresh_questions_safely", _questions)
    return ran


def _no_engine(monkeypatch):
    """Stage 1 returns nothing for every episode — the total-failure case."""
    async def extract(episodes, settings):
        return []

    monkeypatch.setattr("api.services.entity_extractor.extract", extract)


# --------------------------------------------------------------------------- #
# The abort ordering fix (spec §1)
# --------------------------------------------------------------------------- #

def test_a_dead_engine_still_runs_logos_connectors_and_questions(tmp_path, monkeypatch, tail_spy):
    memory = _seed(tmp_path, unprocessed=3)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))
    _no_engine(monkeypatch)

    asyncio.run(sleep_cycle.run(Settings(), "sleep_test"))

    assert set(tail_spy) == {"logos", "connectors", "questions"}
    assert sleep_cycle.get_sleep_state().error


def test_an_idle_cycle_still_runs_all_three(tmp_path, monkeypatch, tail_spy):
    memory = _seed(tmp_path, unprocessed=0)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))

    asyncio.run(sleep_cycle.run(Settings(), "sleep_test"))

    assert set(tail_spy) == {"logos", "connectors", "questions"}


def test_a_raised_exception_mid_pipeline_still_runs_the_tail(tmp_path, monkeypatch, tail_spy):
    memory = _seed(tmp_path, unprocessed=2)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))

    async def boom(episodes, settings):
        raise RuntimeError("stage 1 exploded")

    monkeypatch.setattr("api.services.entity_extractor.extract", boom)

    asyncio.run(sleep_cycle.run(Settings(), "sleep_test"))

    assert set(tail_spy) == {"logos", "connectors", "questions"}
    assert "stage 1 exploded" in (sleep_cycle.get_sleep_state().error or "")


def test_the_queue_is_untouched_when_the_engine_is_dead(tmp_path, monkeypatch, tail_spy):
    memory = _seed(tmp_path, unprocessed=3)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))
    _no_engine(monkeypatch)

    asyncio.run(sleep_cycle.run(Settings(), "sleep_test"))

    assert len(sleep_cycle._get_unprocessed_episodes(memory)) == 3


def test_the_connector_poll_is_skipped_when_the_tree_is_dirty(tmp_path, monkeypatch, tail_spy):
    """H1 protection: the connectors' own `git add -A` must never absorb a
    failed cycle's uncommitted entity writes into a media commit."""
    memory = _seed(tmp_path, unprocessed=1)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))

    async def dirty(_path):
        return " M entities/x.md\n"

    monkeypatch.setattr(git_service, "porcelain_status", dirty)
    _no_engine(monkeypatch)

    asyncio.run(sleep_cycle.run(Settings(), "sleep_test"))

    assert "connectors" not in tail_spy
    assert {"logos", "questions"} <= set(tail_spy)


# --------------------------------------------------------------------------- #
# Honest engine copy + state
# --------------------------------------------------------------------------- #

def test_the_stage1_failure_message_no_longer_says_api_credits_on_a_plan():
    msg = sleep_cycle._stage1_failure_message("claude-cli")
    assert "API credits" not in msg
    assert "claude auth status" in msg


def test_the_byok_failure_message_still_names_credits():
    msg = sleep_cycle._stage1_failure_message("litellm")
    assert "credit" in msg.lower()


def test_engine_label_maps_the_mode(monkeypatch):
    assert sleep_cycle._engine_label(Settings(llm_mode="agent")) == "claude-cli"
    assert sleep_cycle._engine_label(Settings(llm_mode="local")) == "ollama"
    assert sleep_cycle._engine_label(Settings(llm_mode="byok")) == "litellm"


def test_the_preflight_probe_aborts_before_stage_1_with_the_fix(tmp_path, monkeypatch, tail_spy):
    memory = _seed(tmp_path, unprocessed=2)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))
    monkeypatch.setattr(agent_engine, "probe",
                        lambda **kw: (False, "Claude Code is signed out — run `claude auth login`."))

    called = {"extract": False}

    async def extract(episodes, settings):
        called["extract"] = True
        return []

    monkeypatch.setattr("api.services.entity_extractor.extract", extract)

    asyncio.run(sleep_cycle.run(Settings(llm_mode="agent"), "sleep_test"))

    state = sleep_cycle.get_sleep_state()
    assert called["extract"] is False               # never spent a spawn
    assert "claude auth login" in (state.error or "")
    assert state.last_engine == "claude-cli"
    assert set(tail_spy) == {"logos", "connectors", "questions"}


def test_the_probe_is_not_run_on_an_idle_cycle(tmp_path, monkeypatch, tail_spy):
    memory = _seed(tmp_path, unprocessed=0)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))

    def _boom(**kw):
        raise AssertionError("probed an idle cycle")

    monkeypatch.setattr(agent_engine, "probe", _boom)
    asyncio.run(sleep_cycle.run(Settings(llm_mode="agent"), "sleep_test"))


def test_the_breaker_is_reset_at_the_top_of_every_cycle(tmp_path, monkeypatch, tail_spy):
    memory = _seed(tmp_path, unprocessed=0)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))
    agent_engine.trip_breaker("left over from the last cycle")
    asyncio.run(sleep_cycle.run(Settings(), "sleep_test"))
    assert agent_engine.breaker_reason() is None


def test_sleep_status_exposes_the_engine():
    from fastapi.testclient import TestClient

    from api import main

    sleep_cycle.get_sleep_state().last_engine = "claude-cli"
    sleep_cycle.get_sleep_state().engine_detail = "Claude Code signed in on this Mac."
    body = TestClient(main.app).get("/sleep/status").json()
    assert body["lastEngine"] == "claude-cli"
    assert body["engineDetail"] == "Claude Code signed in on this Mac."
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_sleep_engine_state.py -q`
Expected: FAIL — `AttributeError: module 'api.services.sleep_cycle' has no attribute '_stage1_failure_message'`, and `test_a_dead_engine_still_runs_logos_connectors_and_questions` fails because the tail is empty.

- [ ] **Step 3: Add the new state fields**

In `api/services/sleep_cycle.py`, append to `SleepState` (after `organic_resolutions`, `:55`):

```python
    # G74(a) — which engine this cycle actually ran on ("claude-cli" |
    # "ollama" | "litellm"), and one sentence about its state. The Sleep page
    # showed "check model id / API credits" on a Max plan that has no credits
    # to check; these two make the real answer visible.
    last_engine: str | None = None
    engine_detail: str | None = None
```

and reset both in `run` beside the other resets (`:205-206`):

```python
    _state.last_engine = None
    _state.engine_detail = None
```

- [ ] **Step 4: Split `run` into `_run_stages` + the engine-independent tail**

Add the outcome type and the helpers above `run` (after `_refresh_questions_safely`):

```python
@dataclass
class _StageOutcome:
    """What the LLM-dependent pipeline achieved, for the tail to react to.

    ``committed``: ``_finalize`` ran, so the working tree is clean and the
    connector poll's own ``git add -A`` can safely sweep only its own files.
    ``questions_refreshed``: Stage 5.56 already re-scored the open questions,
    so the tail must not do it a second time.
    """
    committed: bool = False
    questions_refreshed: bool = False


_ENGINE_LABELS = {"agent": "claude-cli", "local": "ollama", "byok": "litellm"}


def _engine_label(settings: Settings) -> str:
    """Which engine a resolved mode means. (Task 7 routes "auto" here too.)"""
    return _ENGINE_LABELS.get((settings.llm_mode or "byok").strip().lower(), "litellm")


def _stage1_failure_message(engine: str) -> str:
    """The user-visible reason Stage 1 produced nothing — per engine.

    The old single string ("check model id / API credits") is a lie on a Max
    plan: a subscription has no credits to check, and the real fixes are
    completely different per rung.
    """
    if engine == "claude-cli":
        return (
            "Stage 1 extracted nothing — every episode failed on the Claude Code engine. "
            "Run `claude auth status` to check the plan is signed in. "
            "The queue is intact; trigger Sleep again once it is."
        )
    if engine == "ollama":
        return (
            "Stage 1 extracted nothing — every episode failed on the local Ollama engine. "
            "Check the Ollama server is running and the model is pulled. "
            "The queue is intact for retry."
        )
    return (
        "Stage 1 extracted nothing — every episode failed on the API engine "
        "(check the model id, and that the key still has credit). "
        "Queue left intact for retry."
    )


async def _tree_is_clean(memory_path: Path) -> bool:
    try:
        return not (await git_service.porcelain_status(memory_path)).strip()
    except Exception:  # not a git workspace: there is nothing to protect
        return True


async def _run_engine_independent_tail(
    memory_path: Path, settings: Settings, outcome: _StageOutcome
) -> None:
    """The work that never needed an LLM — on EVERY exit path.

    Spec §1: the abort was upside-down. With a non-empty queue and no engine,
    the Stage-1 abort ``return``ed before the logo warm-up and the connector
    poll, and the question refresh only ever ran in the zero-episode idle
    branch — so capturing more episodes made Sleep do strictly LESS work.
    """
    if outcome.committed or await _tree_is_clean(memory_path):
        # Final-review H1 is preserved: on the happy path this still runs
        # AFTER ``_finalize``'s commit, so the connectors' ``git add -A``
        # finds a clean tree. On a failed cycle we only poll when the tree is
        # already clean, so a partial Sleep write can never be swept into a
        # media commit with no session provenance.
        await _poll_connectors_safely(memory_path)
    else:
        logger.warning(
            "connector poll skipped: the cycle left uncommitted writes, and the "
            "connectors' own `git add -A` would absorb them into a media commit"
        )
    await _warm_logos_safely(memory_path)
    if not outcome.questions_refreshed:
        # Staleness is a function of TIME, not of episodes: a cycle that never
        # reached Stage 5.56 must still escalate questions everyone stopped
        # talking about (and clear ones answered organically).
        await _refresh_questions_safely(memory_path, settings)
```

Now rewrite `run` (`:184-527`) as the thin wrapper:

```python
async def run(settings: Settings, cycle_id: str) -> None:
    """Execute the 5-stage Sleep cycle pipeline."""
    global _state

    _state.status = "running"
    _state.cycle_id = cycle_id
    _state.started_at = datetime.now().isoformat()
    _state.started_monotonic = time.monotonic()
    _state.progress = "Starting..."
    _state.error = None
    _state.index_warning = None
    _state.stage = 0
    _state.episodes_total = 0
    _state.entities_created = 0
    _state.entities_updated = 0
    _state.relationships_created = 0
    _state.skills_detected = 0
    _state.episodes_processed = 0
    _state.episodes_requeued = 0
    _state.questions_refreshed = 0
    _state.organic_resolutions = 0
    _state.last_engine = None
    _state.engine_detail = None

    memory_path = settings.memory_path

    # G74(a): the throttle breaker and the models-used ledger are
    # process-global. A breaker left tripped by last night's cycle would make
    # this one fail fast for free.
    from api.services import agent_engine
    agent_engine.reset_breaker()
    agent_engine.reset_models_used()

    outcome = _StageOutcome()
    try:
        outcome = await _run_stages(settings, cycle_id, memory_path)
    except Exception as e:
        _state.progress = f"Failed: {e}"
        _state.error = f"{type(e).__name__}: {e}"
        logger.error(f"Sleep cycle failed: {e}")
        logger.exception("Full traceback:")
    finally:
        await _run_engine_independent_tail(memory_path, settings, outcome)
        _state.status = "idle"


async def _run_stages(settings: Settings, cycle_id: str, memory_path: Path) -> _StageOutcome:
    """The LLM-dependent pipeline. Returns what it achieved; never runs the tail."""
    from api.services import agent_engine

    _state.last_engine = _engine_label(settings)
    logger.info(
        f"Sleep cycle {cycle_id} started — engine: {_state.last_engine}, "
        f"model: {settings.litellm_model}"
    )

    # M5e: ensure the runtime predicate-normalization map exists (idempotent,
    # non-clobbering) so Stage 2 predicate folding + Stage 3 cardinality keying
    # have a controlled vocabulary to key on.
    try:
        from api.services import predicates
        predicates.install_predicate_map(memory_path)
    except Exception as e:
        logger.warning(f"predicate map install skipped: {type(e).__name__}: {e}")

    episodes = _get_unprocessed_episodes(memory_path)
    if not episodes:
        logger.info("No unprocessed episodes found — skipping")
        _state.progress = "No unprocessed episodes"
        return _StageOutcome()

    logger.info(f"Found {len(episodes)} unprocessed episodes")
    _state.episodes_total = len(episodes)

    # G74(a) pre-flight: ask the engine whether it can work BEFORE spending a
    # spawn per episode discovering it cannot. Only on a cycle with real work,
    # so an idle bank never shells out.
    if _state.last_engine == "claude-cli":
        ok, detail = await asyncio.to_thread(agent_engine.probe)
        _state.engine_detail = detail
        if not ok:
            logger.error(f"Sleep cycle {cycle_id} aborted before Stage 1 — {detail}")
            _state.error = detail
            _state.progress = f"Failed: {detail}"
            return _StageOutcome()

    # ... Stage 1 through Stage 5.7 unchanged, verbatim from the old body ...
```

Then apply exactly four edits inside the copied body:

1. Replace the Stage-1 abort (old `:253-261`) with:

```python
        if episodes and not extracted:
            msg = _stage1_failure_message(_state.last_engine or "litellm")
            if _state.engine_detail:
                msg = f"{msg} ({_state.engine_detail})"
            logger.error(msg)
            _state.error = msg
            _state.progress = f"Failed: {msg}"
            return _StageOutcome()
```

2. Inside the Stage 5.56 `try:` block, immediately after `organic_resolution_paths = set(...)` (old `:361`), add:

```python
            questions_refreshed = True
```

and initialise `questions_refreshed = False` beside `organic_resolution_paths: set[str] = set()` (old `:339`).

3. Delete the `await _warm_logos_safely(memory_path)` line (old `:474`) and the `await _poll_connectors_safely(memory_path)` line plus its H1 comment block (old `:488-501`) — both now live in the tail.

4. Replace the trailing `_state.stage = 5` (old `:519`) with:

```python
    _state.stage = 5
    return _StageOutcome(committed=True, questions_refreshed=questions_refreshed)
```

Finally delete the whole `try:` / `except Exception` / `finally:` scaffolding that used to wrap the body (old `:211`, `:521-527`) — `run` owns it now — and de-indent the body one level.

- [ ] **Step 5: Surface `last_engine` on the API**

`api/models/schemas.py`, after `organic_resolutions` (`:920`):

```python
    # G74(a) — which engine this cycle ran on, and one sentence about its
    # state ("Claude Code is signed out — run `claude auth login`").
    last_engine: Optional[str] = None
    engine_detail: Optional[str] = None
```

`api/routers/sleep.py`, inside `SleepStatusResponse(...)` (after `:61`):

```python
        last_engine=state.last_engine,
        engine_detail=state.engine_detail,
```

- [ ] **Step 6: Run the backend tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_sleep_engine_state.py api/tests/test_sleep_resumable.py api/tests/test_sleep_cycle_claims_wired.py api/tests/test_sleep_cycle_logo_warmup.py api/tests/test_sleep_connector_poll.py api/tests/test_sleep_cycle_malformed_files.py api/tests/test_inbox_refresh.py -q`
Expected: PASS. If `test_sleep_cycle_logo_warmup.py` or `test_sleep_connector_poll.py` assert an ordering that the tail changed, update the assertion to the new contract (both steps still run; logos now run after `_finalize` rather than before, which no assertion should care about because logos live in `$CICADA_HOME`, not the bank).

- [ ] **Step 7: Decode `lastEngine` in the app**

`app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift` — add to `SleepStatusResponse` (`:495-533`):

```swift
    /// G74(a) — which engine the last cycle ran on ("claude-cli" | "ollama" |
    /// "litellm"), and one sentence about its state. Both absent on an older
    /// backend, so both are optional.
    let lastEngine: String?
    let engineDetail: String?
```

add `case lastEngine, engineDetail` to `CodingKeys`, and in `init(from:)`:

```swift
        lastEngine = try c.decodeIfPresent(String.self, forKey: .lastEngine)
        engineDetail = try c.decodeIfPresent(String.self, forKey: .engineDetail)
```

- [ ] **Step 8: Render the engine line on the Sleep page**

`app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift` — inside the `VStack` at `:57`, immediately above the error banner:

```swift
                    if let engine = sleepVM.status?.lastEngine {
                        engineLine(engine, detail: sleepVM.status?.engineDetail)
                    }
                    if let error = sleepVM.lastError ?? sleepVM.errorMessage, !error.isEmpty {
                        errorBanner(error)
                    }
```

and add the view builder beside `errorBanner` (`:461`):

```swift
    /// Which engine the last cycle ran on. Named, not implied — a Sleep page
    /// that says "check API credits" while running on a subscription is the
    /// exact confusion this replaces.
    private func engineLine(_ engine: String, detail: String?) -> some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Text("ENGINE")
                .font(.system(size: 9, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.1)
            Text(Copy.engineLabel(engine))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            if let detail, !detail.isEmpty {
                Text("· \(detail)")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(2)
            }
            Spacer()
        }
    }
```

Add the label map to `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift` (after `addASource`, `:37`):

```swift
    // MARK: Sleep engine (G74(a))

    /// The engine id the backend reports, in the user's words.
    static func engineLabel(_ id: String) -> String {
        switch id {
        case "claude-cli": "Claude Code (your plan)"
        case "ollama": "Ollama (on this Mac)"
        case "litellm": "API key"
        default: id
        }
    }
```

- [ ] **Step 9: Build and test the app**

Run: `cd app/CicadaApp && swift build && swift test`
Expected: build succeeds; tests PASS.

- [ ] **Step 10: Commit**

```bash
git add api/services/sleep_cycle.py api/models/schemas.py api/routers/sleep.py \
        api/tests/test_sleep_engine_state.py \
        app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift \
        app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift
git commit -F - <<'MSG'
fix(sleep): the abort was upside-down; name the engine instead of guessing

With a non-empty queue and no engine, sleep_cycle returned before the logo
warm-up and the connector poll, and only refreshed open questions in the
zero-episode branch — so capturing MORE episodes made Sleep do strictly less
work. The pipeline is now `_run_stages` and the three engine-independent
steps run in a `finally` on every exit path (idle, aborted, failed,
completed), with the H1 clean-tree guard kept so a failed cycle's partial
writes can never be swept into a connector's `git add -A` commit.

Stage-1 total failure now says what actually failed per engine instead of
"check model id / API credits" — a lie on a subscription. The agent rung
pre-flights `claude auth status` before spending a spawn per episode, and
/sleep/status reports lastEngine + engineDetail, rendered on the Sleep page.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
MSG
```

---

## Task 6: Provenance + ledger truth — `_finalize` and the five missing `stage=` labels

**Files:**
- Modify: `api/services/sleep_cycle.py:477-486` (the call), `:699-834` (`_finalize`)
- Modify: `api/services/conflict_resolver.py:618-620`, `:721-723`
- Modify: `api/services/skill_extractor.py:81-83`
- Modify: `api/services/dedup_sweep.py:109`
- Modify: `api/services/source_rewrite.py:52`
- Test: `api/tests/test_agent_provenance.py`

**Interfaces:**
- Consumes: `agent_engine.models_used()` (Task 1), `sleep_cycle._engine_label` and `_StageOutcome` (Task 5).
- Produces: `_finalize(..., engine: str = "litellm", connection: str | None = None, billing: str | None = None, authors: list[str] | None = None)` — three new keyword-only params beside the existing `engine`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_agent_provenance.py`:

```python
"""G74(a) Task 6 — the commit and the ledger both name what really ran.

Two lies today: `_finalize`'s `engine=` default is never overridden by its one
call site, and `connection_for_model` maps any model containing "claude" to
("byok-anthropic", "usage") — so every plan call is attributed to the
DISCONNECTED BYOK API-key card and billed as real money.
"""
from __future__ import annotations

import asyncio

import pytest

from api.config import Settings
from api.services import agent_engine, git_service, sleep_cycle, telemetry


@pytest.fixture
def committed(tmp_path, monkeypatch):
    """Capture the commit message and the sleep_run event `_finalize` produces."""
    seen: dict = {}

    async def fake_status(_path):
        return ""

    async def fake_commit(_path, message):
        seen["message"] = message
        return "abc1234"

    monkeypatch.setattr(git_service, "porcelain_status", fake_status)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    seen["events"] = []
    monkeypatch.setattr(telemetry, "record", seen["events"].append)
    return seen


def test_a_plan_cycle_is_never_attributed_to_the_byok_card(tmp_path, committed):
    agent_engine.record_model_used("claude-sonnet-5")
    asyncio.run(sleep_cycle._finalize(
        tmp_path, "sleep_1", [], Settings(llm_mode="agent"),
        engine="claude-cli", connection="claude-plan", billing="subscription",
        authors=agent_engine.models_used(),
    ))
    ev = committed["events"][0]
    assert ev.kind == "sleep_run"
    assert ev.engine == "claude-cli"
    assert ev.connection == "claude-plan"     # NOT byok-anthropic
    assert ev.billing == "subscription"       # NOT usage
    assert ev.model == "claude-sonnet-5"


def test_the_commit_trailers_name_the_models_that_actually_ran(tmp_path, committed):
    asyncio.run(sleep_cycle._finalize(
        tmp_path, "sleep_1", [], Settings(llm_mode="agent"),
        engine="claude-cli", connection="claude-plan", billing="subscription",
        authors=["claude-haiku-4-5", "claude-sonnet-5"],
    ))
    trailers = git_service._parse_authors(committed["message"])
    assert set(trailers) == {"claude-haiku-4-5", "claude-sonnet-5"}


def test_the_byok_path_still_derives_authors_from_settings(tmp_path, committed):
    asyncio.run(sleep_cycle._finalize(
        tmp_path, "sleep_1", [], Settings(litellm_model="gpt-5.4-mini",
                                          litellm_disambiguation_model="gpt-5.4-nano"),
    ))
    ev = committed["events"][0]
    assert ev.engine == "litellm" and ev.connection == "byok-openai"
    assert set(git_service._parse_authors(committed["message"])) == {"gpt-5.4-mini", "gpt-5.4-nano"}


def test_the_five_unlabelled_call_sites_now_carry_a_stage(monkeypatch):
    """`by_stage` in the Usage dashboard groups on this field; five sites fell
    into the "unknown" bucket (providers.py:201 defaults it)."""
    from api.services import providers

    seen: list[str | None] = []
    real = providers.resolve_llm_fn

    def patched(settings, **kw):
        seen.append(kw.get("stage"))
        return real(settings, **kw)

    monkeypatch.setattr(providers, "resolve_llm_fn", patched)

    import inspect

    from api.services import conflict_resolver, dedup_sweep, skill_extractor, source_rewrite

    sources = "\n".join(
        inspect.getsource(mod) for mod in
        (conflict_resolver, dedup_sweep, skill_extractor, source_rewrite)
    )
    # Every resolve_llm_fn call in these four modules names its stage.
    for chunk in sources.split("resolve_llm_fn(")[1:]:
        head = chunk[: chunk.index(")")] if ")" in chunk else chunk
        assert "stage=" in head, f"unlabelled resolve_llm_fn call: {head[:120]}"


def test_no_sleep_stage_reports_unknown(monkeypatch):
    """The ledger's `by_stage` must contain no "unknown" row after a cycle."""
    from api.services import consumption_stats

    events = [
        telemetry.UsageEvent(kind="llm_call", stage=s, connection="claude-plan",
                             engine="claude-cli", model="claude-sonnet-5",
                             input_tokens=10, output_tokens=1)
        for s in ("extraction", "disambiguation", "conflict", "skills", "dedup",
                  "rewrite", "enrichment", "ask")
    ]
    rows = consumption_stats._group(events, "stage", "stage")
    assert "unknown" not in {r["stage"] for r in rows}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_agent_provenance.py -q`
Expected: FAIL — `_finalize() got an unexpected keyword argument 'connection'`.

- [ ] **Step 3: Widen `_finalize`**

In `api/services/sleep_cycle.py`, extend the signature (`:699-710`):

```python
async def _finalize(
    memory_path: Path,
    cycle_id: str,
    changes: list,
    settings: Settings | None = None,
    *,
    organic_resolution_paths: set[str] | None = None,
    started: float | None = None,
    engine: str = "litellm",
    connection: str | None = None,
    billing: str | None = None,
    authors: list[str] | None = None,
    sessions: list[str] | None = None,
    episode_sessions: dict[str, str] | None = None,
) -> None:
```

and add to the docstring:

```
    ``engine`` / ``connection`` / ``billing`` / ``authors`` (G74(a)): what
    actually ran. Left to their defaults these reproduce the old behaviour
    exactly — engine ``"litellm"``, connection derived from the model via
    ``telemetry.connection_for_model``, authors derived from ``settings``. The
    agent rung passes all four, because ``connection_for_model`` maps any
    model containing "claude" to ``("byok-anthropic", "usage")``: left alone,
    every plan cycle would be attributed to the *disconnected* BYOK API-key
    card and billed as real money.
```

Replace the author derivation (`:796-804`):

```python
    # Author trailers: the models that actually wrote this consolidation.
    # `authors` (G74(a)) is what the engine REPORTED using; without it we fall
    # back to what settings CONFIGURED (main + Stage-2 judge when distinct).
    resolved_authors: list[str] = [a for a in (authors or []) if a]
    if not resolved_authors and settings is not None:
        if settings.litellm_model:
            resolved_authors.append(settings.litellm_model)
        disambig = (settings.litellm_disambiguation_model or "").strip()
        if disambig and disambig not in resolved_authors:
            resolved_authors.append(disambig)
```

and use `resolved_authors` in `build_commit_message` (`:806-808`) and in the telemetry block (`:815-816`):

```python
    message = git_service.build_commit_message(
        f"Sleep cycle {date_str}", body_lines, authors=resolved_authors, sessions=sessions or []
    )
    ...
    model = resolved_authors[0] if resolved_authors else None
    if connection is not None:
        event_connection, event_billing = connection, (billing or "subscription")
    elif model:
        event_connection, event_billing = telemetry.connection_for_model(model)
    else:
        event_connection, event_billing = None, "free"
    telemetry.record(telemetry.UsageEvent(
        kind="sleep_run", stage="structural", engine=engine,
        connection=event_connection,
        model=model,
        bank=telemetry.bank_name(settings) if settings is not None else memory_path.name,
        billing=event_billing,
        ...
```

- [ ] **Step 4: Pass the truth from the call site**

In `_run_stages`, replace the `_finalize(...)` call (old `:477-486`) with:

```python
        from api.services import agent_engine

        engine = _state.last_engine or "litellm"
        engine_models = agent_engine.models_used()
        await _finalize(
            memory_path,
            cycle_id,
            changes,
            settings,
            organic_resolution_paths=organic_resolution_paths,
            started=_state.started_monotonic,
            engine=engine,
            # A plan cycle belongs to the claude-plan card and is billed
            # against the subscription, not as money.
            connection="claude-plan" if engine == "claude-cli" else None,
            billing="subscription" if engine == "claude-cli" else None,
            # The models the engine ACTUALLY used this cycle — the CLI may
            # route an internal side-call to a different model than the one we
            # asked for (V1d), and the trailer should say so.
            authors=engine_models or None,
            sessions=_collect_session_ids(processed_episodes),
            episode_sessions=_episode_session_map(processed_episodes),
        )
```

- [ ] **Step 5: Label the five unlabelled call sites**

`api/services/conflict_resolver.py:618-620`:

```python
    llm_fn = resolve_llm_fn(
        settings, model=settings.effective_consolidation_model,
        completion=litellm.acompletion, stage="merge",
    )
```

`api/services/conflict_resolver.py:721-723`:

```python
    llm_fn = resolve_llm_fn(
        settings, model=settings.effective_consolidation_model,
        completion=litellm.acompletion, stage="conflict",
    )
```

`api/services/skill_extractor.py:81-83`:

```python
        llm_fn = resolve_llm_fn(
            settings, model=settings.effective_consolidation_model,
            completion=litellm.acompletion, stage="skills",
        )
```

`api/services/dedup_sweep.py:109`:

```python
    llm = resolve_llm_fn(settings, model=settings.effective_consolidation_model, stage="dedup")
```

`api/services/source_rewrite.py:52`:

```python
        llm_fn = resolve_llm_fn(settings, model=settings.effective_consolidation_model,
                                stage="rewrite")
```

(`link_enrichment.py:268` already passes `stage="enrichment"`; `ask_service.py:259`, `entity_extractor.py:264` and `entity_resolver.py:693` already pass theirs. These five were the whole "unknown" bucket.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `api/.venv/bin/python -m pytest api/tests/test_agent_provenance.py -q`
Expected: PASS (5 tests).

- [ ] **Step 7: Run the full backend suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS except the 8 documented `test_calendar_registry.py` failures.

- [ ] **Step 8: Commit**

```bash
git add api/services/sleep_cycle.py api/services/conflict_resolver.py \
        api/services/skill_extractor.py api/services/dedup_sweep.py \
        api/services/source_rewrite.py api/tests/test_agent_provenance.py
git commit -F - <<'MSG'
fix(ledger): a plan cycle stops being billed to the BYOK card

_finalize's `engine=` default was never overridden by its one call site, and
connection_for_model maps anything containing "claude" to
("byok-anthropic", "usage") — so an agent-rung cycle was attributed to a
DISCONNECTED API-key card and recorded as real money. It now takes
engine/connection/billing/authors, and the Cicada-Author trailers name the
models the engine actually reported (the CLI can route an internal side-call
to a different model than the one requested). The five resolve_llm_fn call
sites that never named a stage — merge, conflict, skills, dedup, rewrite —
now do, emptying the ledger's "unknown" by_stage bucket.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
MSG
```

---

## Task 7: Configuration, UI, and doctor — choosing the engine and proving it works

**Files:**
- Create: `api/services/engine_select.py`
- Modify: `api/services/connections/registry.py:60-69`, `:101-108`
- Modify: `api/models/schemas.py:1258-1282`
- Modify: `api/routers/connections.py:18-21`, `:94-104`
- Modify: `api/services/sleep_cycle.py` (`_engine_label` + resolution in `_run_stages`)
- Modify: `scripts/doctor.sh:105-119`
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/Connection.swift:5-70`
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift:1041-1043`, `:1762-1764`
- Modify: `app/CicadaApp/Sources/CicadaApp/Sync/SyncAPI.swift:87`
- Modify: `app/CicadaApp/Sources/CicadaApp/Sync/Mutations.swift:170-205`
- Modify: `app/CicadaApp/Sources/CicadaApp/ViewModels/ConnectionsViewModel.swift:157-160`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Connections/ConnectionsView.swift:92-175`
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift`
- Modify: `app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift:129-131` (protocol conformance)
- Test: `api/tests/test_engine_select.py`, `app/CicadaApp/Tests/CicadaAppTests/EngineSelectionTests.swift`

**Interfaces:**
- Consumes: `sleep_cycle._engine_label` (Task 5), `Registry.prefs()` / `.set_pref()` / `.status()`.
- Produces:
  - `engine_select.USE_FOR_SLEEP_PREF = "use_for_sleep"`
  - `engine_select.resolve_llm_mode(settings, registry=None) -> tuple[str, str]` — `(mode, why)`
  - `engine_select.resolve_settings(settings, registry=None) -> tuple[Settings, str]` — a `model_copy` with a concrete `llm_mode`
  - `engine_select.engine_label(settings) -> str`
  - `ConnectionStatus.use_for_sleep: bool = False` / Swift `useForSleep: Bool`
  - `SyncAPI.setUseForSleep(_ id: String, on: Bool) async throws -> ConnectionStatus`; `SetUseForSleep` mutation.

**Precedence rule (the one thing to get right):** an explicit `llm_mode` of `agent` or `local` always wins — it is deliberate configuration in `api/.env`. `auto` probes the registry. `byok` (the shipped default, i.e. "nobody chose") defers to the card's **Use for Sleep** toggle, so a user who flips the switch gets the agent rung without editing a dotfile. This keeps every existing install byte-identical (default `byok` + no pref = `byok`).

- [ ] **Step 1: Write the failing backend test**

Create `api/tests/test_engine_select.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_engine_select.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'api.services.engine_select'`.

- [ ] **Step 3: Create `api/services/engine_select.py`**

```python
"""G74(a) §8 — which engine a Sleep cycle runs on, resolved once per cycle.

`resolve_llm_fn` is synchronous and called from deep inside every stage, so it
can never probe the connections registry (which shells out to vendor CLIs).
Resolution happens here, once, at the top of the cycle; the concrete mode
travels down as a ``Settings`` copy.

Precedence, and the reason for each rung:
  1. ``llm_mode`` of ``"agent"`` or ``"local"`` — deliberate configuration in
     ``api/.env``; it wins, and nothing is probed.
  2. ``"auto"`` — the Claude plan if it probes connected, else Ollama if it is
     running, else the configured API model.
  3. ``"byok"`` (the shipped default, i.e. nobody chose) — defers to the
     Claude card's **Use for Sleep** toggle, so flipping a switch in the app
     picks the engine without editing a dotfile. With no toggle set this is
     exactly today's behaviour, so every existing install is unchanged.
"""
from __future__ import annotations

from loguru import logger

from api.config import Settings

USE_FOR_SLEEP_PREF = "use_for_sleep"
CLAUDE_CONNECTION_ID = "claude-plan"
OLLAMA_CONNECTION_ID = "ollama-local"

ENGINE_LABELS = {"agent": "claude-cli", "local": "ollama", "byok": "litellm"}


def engine_label(settings: Settings) -> str:
    """The engine id for a resolved mode. An unresolved "auto" reads as byok,
    matching how ``providers.resolve_llm_fn`` degrades it."""
    return ENGINE_LABELS.get((settings.llm_mode or "byok").strip().lower(), "litellm")


def use_for_sleep(registry) -> bool:
    try:
        return bool((registry.prefs().get(CLAUDE_CONNECTION_ID) or {}).get(USE_FOR_SLEEP_PREF))
    except Exception:
        return False


async def _connected(registry, connection_id: str) -> bool | None:
    """``True``/``False``, or ``None`` when the probe itself failed."""
    try:
        status = await registry.status(connection_id)
    except Exception as exc:
        logger.warning(f"engine probe failed for {connection_id}: {type(exc).__name__}: {exc}")
        return None
    return bool(getattr(status, "connected", False))


async def resolve_llm_mode(settings: Settings, registry=None) -> tuple[str, str]:
    """Returns ``(concrete mode, one sentence saying why)``."""
    configured = (settings.llm_mode or "byok").strip().lower()
    if configured in ("agent", "local"):
        return configured, f"CICADA_LLM_MODE={configured}"

    if registry is None:
        from api.services.connections.registry import get_registry

        registry = get_registry(settings)

    prefer_claude = use_for_sleep(registry)
    if configured == "byok" and not prefer_claude:
        return "byok", "no Sleep engine chosen — using the configured API model"

    claude = await _connected(registry, CLAUDE_CONNECTION_ID)
    if claude is None:
        return "byok", "could not probe the Claude plan — using the configured API model"
    if claude:
        return "agent", (
            "Claude plan is set as the Sleep engine" if prefer_claude
            else "Claude plan connected — running Sleep on your plan"
        )

    if configured == "auto":
        ollama = await _connected(registry, OLLAMA_CONNECTION_ID)
        if ollama:
            return "local", "Ollama is running — using the local engine"

    return "byok", "Claude plan is not connected — using the configured API model"


async def resolve_settings(settings: Settings, registry=None) -> tuple[Settings, str]:
    """A ``Settings`` copy whose ``llm_mode`` is concrete, plus the reason.

    Never mutates the caller's object: ``get_settings()`` is ``@lru_cache``d
    and shared with every request handler.
    """
    mode, why = await resolve_llm_mode(settings, registry)
    if mode == (settings.llm_mode or "").strip().lower():
        return settings, why
    return settings.model_copy(update={"llm_mode": mode}), why
```

- [ ] **Step 4: Stamp the pref onto the Claude card's status**

`api/models/schemas.py`, in `ConnectionStatus` after `powers` (`:1281`):

```python
    # G74(a) — the user has picked this connection as the Sleep engine. Only
    # meaningful on `claude-plan`; a machine-global preference, never a probe.
    use_for_sleep: bool = False
```

`api/services/connections/registry.py`, in `status()` (`:101-108`):

```python
    async def status(self, connection_id: str, fresh: bool = False) -> ConnectionStatus:
        now = time.monotonic()
        hit = self._cache.get(connection_id)
        if hit and not fresh and now - hit[0] < STATUS_TTL_SECONDS:
            return hit[1]
        status = await self.get(connection_id).status()
        # G74(a): "is this the Sleep engine" is a stored user choice, not
        # something an adapter probing itself can know — same shape as
        # `assign_powers`. `set_pref` invalidates the cache, so this can never
        # go stale behind a toggle.
        if connection_id == engine_select.CLAUDE_CONNECTION_ID:
            status.use_for_sleep = engine_select.use_for_sleep(self)
        self._cache[connection_id] = (now, status)
        return status
```

adding `from api.services import engine_select` to the module imports.

`api/routers/connections.py` — extend `PrefsBody` (`:18-21`) and the handler (`:94-104`):

```python
class PrefsBody(BaseModel):
    tier: str | None = None
    enabled: bool | None = None
    use_for_sleep: bool | None = None
```

```python
@router.put("/{connection_id}/prefs", response_model=ConnectionStatus)
async def set_prefs(connection_id: str, body: PrefsBody, reg: Registry = Depends(_registry)):
    _adapter(reg, connection_id)
    if body.tier is not None and body.tier not in VALID_TIERS:
        raise HTTPException(status_code=422, detail=f"tier must be one of {VALID_TIERS}")
    if "tier" in body.model_fields_set:
        reg.set_pref(connection_id, "tier", body.tier)
    if body.enabled is not None:
        reg.set_pref(connection_id, "enabled", body.enabled)
    if body.use_for_sleep is not None:
        # Exactly one connection can be the Sleep engine, and only the Claude
        # plan implements the rung — accepting it elsewhere would store a
        # preference nothing reads.
        if connection_id != engine_select.CLAUDE_CONNECTION_ID:
            raise HTTPException(
                status_code=400,
                detail="only the Claude plan can be used as the Sleep engine",
            )
        reg.set_pref(connection_id, engine_select.USE_FOR_SLEEP_PREF,
                     True if body.use_for_sleep else None)
    return await reg.status_with_powers(connection_id, fresh=True)
```

adding `from api.services import engine_select` to its imports. (`set_pref` with `None` deletes the key — turning the toggle off leaves no residue.)

- [ ] **Step 5: Route `sleep_cycle` through the resolver**

In `api/services/sleep_cycle.py`, replace `_ENGINE_LABELS` / `_engine_label` (added in Task 5) with a delegation:

```python
def _engine_label(settings: Settings) -> str:
    from api.services import engine_select

    return engine_select.engine_label(settings)
```

and, in `_run_stages`, resolve before labelling — immediately after the `from api.services import agent_engine` line:

```python
    from api.services import engine_select

    # "auto" (and a default install with the Use-for-Sleep toggle on) probes
    # the connections registry, which shells out to vendor CLIs — so it is
    # resolved ONCE here and the concrete mode travels down as a copy. The
    # caller's Settings is never mutated: get_settings() is lru_cached.
    settings, engine_why = await engine_select.resolve_settings(settings)
    _state.last_engine = _engine_label(settings)
    _state.engine_detail = engine_why
```

(remove the plain `_state.last_engine = _engine_label(settings)` line Task 5 added; the pre-flight probe still overwrites `engine_detail` with the probe's own sentence when it runs.)

- [ ] **Step 6: Run the backend tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_engine_select.py api/tests/test_connections_api.py api/tests/test_connection_claude.py api/tests/test_connection_how_powers.py api/tests/test_sleep_engine_state.py -q`
Expected: PASS.

- [ ] **Step 7: Write the failing app test**

Create `app/CicadaApp/Tests/CicadaAppTests/EngineSelectionTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G74(a) — the Claude card can be made the Sleep engine, and the Sleep page
/// names whichever engine actually ran.
final class EngineSelectionTests: XCTestCase {

    func testConnectionDecodesUseForSleep() throws {
        let json = #"{"id":"claude-plan","label":"Claude plan","kind":"subscription","useForSleep":true}"#
        let c = try JSONDecoder().decode(ConnectionStatus.self, from: Data(json.utf8))
        XCTAssertTrue(c.useForSleep)
    }

    /// An older backend omits the field; the card must still decode and simply
    /// read as "not the engine".
    func testConnectionDecodesWithoutUseForSleep() throws {
        let json = #"{"id":"claude-plan","label":"Claude plan","kind":"subscription"}"#
        let c = try JSONDecoder().decode(ConnectionStatus.self, from: Data(json.utf8))
        XCTAssertFalse(c.useForSleep)
    }

    /// Only a connected Claude plan can be the Sleep engine — the rung does
    /// not exist for anything else.
    func testOnlyAConnectedClaudePlanOffersTheToggle() {
        func make(_ id: String, connected: Bool) -> ConnectionStatus {
            ConnectionStatus(id: id, label: id, kind: "subscription", available: true,
                             connected: connected, plan: "max", planLabel: nil, tier: nil,
                             account: nil, priceUsdMonth: nil, priceNote: nil,
                             billing: "subscription", engineRole: nil, detail: nil,
                             how: nil, powers: [], useForSleep: false, login: nil)
        }
        XCTAssertTrue(make("claude-plan", connected: true).showsSleepEngineToggle)
        XCTAssertFalse(make("claude-plan", connected: false).showsSleepEngineToggle)
        XCTAssertFalse(make("chatgpt-plan", connected: true).showsSleepEngineToggle)
        XCTAssertFalse(make("byok-openai", connected: true).showsSleepEngineToggle)
    }

    /// The copy has to say all three honest things: what it costs, who starts
    /// it, and what a throttle does.
    func testTheEngineExplainerIsHonestAboutCostTriggerAndThrottle() {
        let text = Copy.sleepEngineExplainer.lowercased()
        XCTAssertTrue(text.contains("plan"), "must say it spends plan quota")
        XCTAssertFalse(text.contains("free"), "plan quota is not 'free'")
        XCTAssertTrue(text.contains("you start") || text.contains("you run"),
                      "must say it is user-triggered")
        XCTAssertTrue(text.contains("throttl"), "must say what happens on a throttle")
    }

    func testEngineLabelsAreHumanReadable() {
        XCTAssertEqual(Copy.engineLabel("claude-cli"), "Claude Code (your plan)")
        XCTAssertEqual(Copy.engineLabel("ollama"), "Ollama (on this Mac)")
        XCTAssertEqual(Copy.engineLabel("litellm"), "API key")
        XCTAssertEqual(Copy.engineLabel("something-new"), "something-new")
    }

    func testSleepStatusDecodesTheEngine() throws {
        let json = #"{"status":"idle","lastEngine":"claude-cli","engineDetail":"Signed in."}"#
        let s = try JSONDecoder().decode(SleepStatusResponse.self, from: Data(json.utf8))
        XCTAssertEqual(s.lastEngine, "claude-cli")
        XCTAssertEqual(s.engineDetail, "Signed in.")
    }

    func testSleepStatusDecodesWithoutTheEngine() throws {
        let s = try JSONDecoder().decode(SleepStatusResponse.self,
                                         from: Data(#"{"status":"idle"}"#.utf8))
        XCTAssertNil(s.lastEngine)
    }

    func testTheMutationCallsTheRightEndpoint() async {
        let api = RecordingSyncAPI()
        let store = Store(api: api)
        _ = await store.perform(SetUseForSleep(id: "claude-plan", on: true))
        XCTAssertEqual(api.writes, ["setUseForSleep:claude-plan:true"])
    }
}
```

(`RecordingSyncAPI` is the existing fake in `Tests/CicadaAppTests/StoreTests.swift`; reuse it rather than defining a second one. If its name differs, use whatever `MutationTests.swift:113` uses.)

- [ ] **Step 8: Run it to verify it fails**

Run: `cd app/CicadaApp && swift test --filter EngineSelectionTests`
Expected: compile error — `value of type 'ConnectionStatus' has no member 'useForSleep'`.

- [ ] **Step 9: Implement the app side**

`Sources/CicadaApp/Models/Connection.swift` — add the property, the coding key, the memberwise-init parameter (defaulted, placed before `login:` so existing call sites compile untouched), the `patching` passthrough, the decoder line, and the affordance predicate:

```swift
    /// G74(a) — the user picked this connection as the Sleep engine.
    /// Meaningful only on `claude-plan`; absent on an older backend.
    let useForSleep: Bool
```

```swift
        case priceUsdMonth, priceNote, billing, engineRole, detail, how, powers, useForSleep, login
```

```swift
         engineRole: String?, detail: String?, how: String? = nil,
         powers: [String] = [], useForSleep: Bool = false, login: LoginHint?) {
```
```swift
        self.how = how; self.powers = powers; self.useForSleep = useForSleep; self.login = login
```

in `init(from:)`:
```swift
        useForSleep = (try? c.decode(Bool.self, forKey: .useForSleep)) ?? false
```

in `patching(...)` add `useForSleep: Bool? = nil` and pass `useForSleep: useForSleep ?? self.useForSleep`.

Then, beside `showsTierPicker`:

```swift
    /// Only a connected Claude plan can drive the Sleep engine — the `claude
    /// -p` rung does not exist for anything else.
    var showsSleepEngineToggle: Bool { id == "claude-plan" && connected }
```

`Sources/CicadaApp/Sync/SyncAPI.swift:87` — add:

```swift
    func setUseForSleep(_ id: String, on: Bool) async throws -> ConnectionStatus
```

`Sources/CicadaApp/Services/APIClient.swift` — beside `setTier` (`:1041`):

```swift
    func setUseForSleep(_ id: String, on: Bool) async throws -> ConnectionStatus {
        try await put("/connections/\(id)/prefs", body: ["useForSleep": on])
    }
```

and the `SyncAPI` conformance beside `setConnectionTier` (`:1762`):

```swift
    func setUseForSleep(_ id: String, on: Bool) async throws -> ConnectionStatus {
        try await setUseForSleep(id, on: on) as ConnectionStatus
    }
```
(if that reads as a recursive call in the actual file layout, name the client method `putUseForSleep` and have the conformance forward to it — match whatever pattern `setConnectionTier`/`setTier` already uses.)

`Sources/CicadaApp/Sync/Mutations.swift` — after `SetConnectionTier` (`:205`):

```swift
/// Make (or unmake) the Claude plan the Sleep engine. Optimistic: the toggle
/// moves at once and rolls back with a toast if the write fails.
struct SetUseForSleep: Mutation {
    let id: String
    let on: Bool
    private let memo = MutationMemo<ConnectionStatus>()

    func optimistic(_ store: Store) async {
        memo.value = patchConnection(store, id: id) { row in
            row.patching(useForSleep: on)
        }
    }

    func request(_ api: any SyncAPI) async throws {
        _ = try await api.setUseForSleep(id, on: on)
    }

    func rollback(_ store: Store) async {
        restoreConnection(store, memo.value)
    }

    var failureMessage: String { "Couldn't change the Sleep engine — reverted" }
    var refreshDomains: Set<SyncDomain> { [.connections] }
}
```

`Tests/CicadaAppTests/StoreTests.swift:129-131` — add the fake's conformance beside `setConnectionTier`:

```swift
    func setUseForSleep(_ id: String, on: Bool) async throws -> ConnectionStatus {
        try await record("setUseForSleep:\(id):\(on)")
    }
```

`Sources/CicadaApp/ViewModels/ConnectionsViewModel.swift:157` — after `setTier`:

```swift
    func setUseForSleep(_ id: String, on: Bool) async {
        await mutate(SetUseForSleep(id: id, on: on))
    }
```

`Sources/CicadaApp/Theme/Copy.swift` — beside `engineLabel` (added in Task 5):

```swift
    static let sleepEngineTitle = "Use for Sleep"

    /// The three honest things about running Sleep on a subscription: what it
    /// spends, who starts it, and what a throttle does. Not "free" — plan
    /// quota is a real budget, just not a dollar one.
    static let sleepEngineExplainer =
        "Sleep runs through the `claude` CLI on your plan: it spends plan quota, not money. "
        + "Only when you start a cycle yourself — never on the nightly schedule — and if the "
        + "plan throttles it stops cleanly with the queue intact."
```

`Sources/CicadaApp/Views/Connections/ConnectionsView.swift` — add the callback to `ConnectionCard`'s properties and to the call site at `:29-40`:

```swift
                                onUseForSleep: { on in Task { await viewModel.setUseForSleep(c.id, on: on) } }
```
```swift
    let onUseForSleep: (Bool) -> Void
```

and render it immediately above `actions` (`:169`):

```swift
            if connection.showsSleepEngineToggle {
                Divider().opacity(0.35)
                Toggle(Copy.sleepEngineTitle,
                       isOn: Binding(get: { connection.useForSleep },
                                     set: { onUseForSleep($0) }))
                    .toggleStyle(.switch)
                    .font(CicadaTheme.captionFont)
                Text(Copy.sleepEngineExplainer)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
```

- [ ] **Step 10: Build and test the app**

Run: `cd app/CicadaApp && swift build && swift test`
Expected: build succeeds; all tests PASS.

- [ ] **Step 11: Add the three doctor checks**

`scripts/doctor.sh` — insert before the summary block (`:113`):

```bash
# 9. A Sleep engine resolves to something real.
CONN_JSON=""
if [ -r "$TOKEN_FILE" ]; then
  CONN_JSON=$(curl -fsS -H "Authorization: Bearer $(cat "$TOKEN_FILE")" \
                   "http://127.0.0.1:$PORT/connections" 2>/dev/null || true)
fi
if printf '%s' "$CONN_JSON" | grep -q '"connected":true'; then
  pass "Sleep engine: at least one connection is live"
else
  fail "Sleep engine: no connection is live — Sleep has nothing to run on"
  note "open Settings → Plans & keys, or run: claude auth login"
fi

# 10. `claude -p` still authenticates with OAuth, not an API key.
#     The announced flip of `-p` to bare-by-default would silently break the
#     agent rung: --bare forces ANTHROPIC_API_KEY and never reads OAuth.
if command -v "$CLAUDE_CLI" >/dev/null 2>&1; then
  PROBE=$(env -u ANTHROPIC_API_KEY "$CLAUDE_CLI" -p --output-format json --safe-mode \
              --strict-mcp-config --tools "" --no-session-persistence \
              --system-prompt 'Reply with the single word ok.' <<< 'ok' 2>/dev/null || true)
  if printf '%s' "$PROBE" | grep -q '"is_error":false'; then
    pass "claude -p works on OAuth with no API key (agent rung is viable)"
  else
    fail "claude -p did not succeed without ANTHROPIC_API_KEY"
    note "check 'claude auth status --json' shows loggedIn + authMethod claude.ai"
    note "if -p has flipped to bare-by-default, the agent rung needs the OAuth flag"
  fi
else
  pass "claude CLI absent — skipping the agent-rung probe (not a failure)"
fi

# 11. No stray ANTHROPIC_API_KEY diverting a plan call to metered billing.
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  fail "ANTHROPIC_API_KEY is set in this environment"
  note "claude would bill the API key instead of your plan; unset it (Cicada's own"
  note "subprocesses scrub it, but a shell export still misleads anything you run by hand)"
else
  pass "No ANTHROPIC_API_KEY in the environment"
fi
```

- [ ] **Step 12: Run doctor**

Run: `bash scripts/doctor.sh; echo "exit=$?"`
Expected: the three new lines appear. Check 10 costs a fraction of a cent of plan quota by design — it is the only honest way to prove the rung works. Failures on checks 1/8 (backend/launchd) are environment-dependent and not this task's concern.

- [ ] **Step 13: Run the full backend suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS except the 8 documented `test_calendar_registry.py` failures.

- [ ] **Step 14: Commit**

```bash
git add api/services/engine_select.py api/services/connections/registry.py \
        api/services/sleep_cycle.py api/models/schemas.py api/routers/connections.py \
        api/tests/test_engine_select.py scripts/doctor.sh \
        app/CicadaApp/Sources/CicadaApp/Models/Connection.swift \
        app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift \
        app/CicadaApp/Sources/CicadaApp/Sync/SyncAPI.swift \
        app/CicadaApp/Sources/CicadaApp/Sync/Mutations.swift \
        app/CicadaApp/Sources/CicadaApp/ViewModels/ConnectionsViewModel.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Connections/ConnectionsView.swift \
        app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift \
        app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift \
        app/CicadaApp/Tests/CicadaAppTests/EngineSelectionTests.swift
git commit -F - <<'MSG'
feat(engine): choose the Sleep engine from the Claude card, and prove it

llm_mode gains "auto"; the Claude plan card gains a "Use for Sleep" toggle
that a default (byok) install honours, so picking the plan engine no longer
means editing api/.env. Explicit agent/local always win. Resolution runs once
per cycle in engine_select — resolve_llm_fn stays synchronous and never
shells out. The card's copy says the three honest things: plan quota not
money, user-triggered only, stops cleanly on a throttle. doctor.sh gains
three checks: something is connected, `claude -p` still works on OAuth with
no API key, and no stray ANTHROPIC_API_KEY is diverting billing.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
MSG
```

---

## Final verification (run before declaring the plan done)

- [ ] **Backend suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS except the 8 documented `api/tests/test_calendar_registry.py` failures. Any other failure is a regression from this branch.

- [ ] **No test spawned a real `claude`**

Run: `api/.venv/bin/python -m pytest api/tests -q -k "agent or engine" -p no:randomly 2>&1 | grep -c "reached the real"`
Expected: `0`.

- [ ] **App build + tests**

Run: `cd app/CicadaApp && swift build && swift test`
Expected: both succeed.

- [ ] **Nothing under `memory/` and nothing in `.claude/settings.json` is staged**

Run: `git status --porcelain | grep -E "^(A|M|\?\?).*(memory/|\.claude/settings\.json)" || echo clean`
Expected: `clean`.

- [ ] **The live pass — the controller's, not the suite's**

One real Sleep cycle on a **copy** of the bank with `CICADA_LLM_MODE=agent`, then check:
1. `GET /sleep/status` reports `lastEngine: "claude-cli"`.
2. `git log -1` in the copy shows `Cicada-Author:` trailers naming real Claude model ids.
3. `~/.cicada/telemetry/events-YYYY-MM.jsonl` gained `llm_call` lines with `engine: "claude-cli"`, `connection: "claude-plan"`, `billing: "subscription"`, `cost_usd: null`, a non-null `equiv_cost_usd`, and **no `stage: "unknown"`**.
4. `GET /consumption/connections` shows the Claude plan row with `equiv_cost_usd` populated and `cost_usd: null`.
5. Second and later calls show a non-zero `cache_read_tokens` — proof the prefix-ordered prompts are hitting the cross-process prompt cache (spec §4).

Record the wall-clock time and the call count. Spec §7 predicts ~200-350 calls at ~90% serialised for a 20-episode cycle; those numbers are the input to the Stage-2 batching follow-up, which is **out of scope here**.

---

## Self-review notes

**Spec coverage.** §1 abort ordering → T5. §2 seam contract (dual access, sync/async, kwargs, optional usage) → T1 shim + T3 branch. §3 invocation and flags → T1. §3.1 structured output + lenient parser → T1 (schema map) + T2. §3.2 response shim → T1. §4 prompt-cache prefix ordering → global constraint + `marshal_prompt`'s no-reorder rule + the live-pass check. §5 failure taxonomy, retry widening, circuit breaker, throttle event, resolver conflation → T1 + T3 + T4. §6 telemetry honesty → T3 + T6. §7 scope lines → global constraints. §8 config + UI + doctor → T7. §9 verifications → encoded as the recorded fixtures in `conftest.py`. §10 testing → the test files listed per task, plus the final live pass.

**Three calls made where the spec left room:**

1. **`--json-schema` is opt-in per stage.** V1b verified the flag only against a trivial `{"ok": true}` schema, and a structured-output mode that drops unlisted keys would silently gut entity extraction in a way no recorded fixture can catch. Only `disambiguation` — whose output shape is fully specifiable — ships a schema; every other JSON site gets `JSON_ONLY_SUFFIX` plus the shared lenient parser, which the spec asks for as belt-and-braces regardless. `SCHEMA_BY_STAGE` widens after the live pass proves no field-stripping.

2. **The shim carries `cache_creation_input_tokens`.** Spec §3.2's shim lists only `prompt_tokens_details.cached_tokens`; `telemetry.usage_from_response:199` reads cache *writes* from `cache_creation_input_tokens`, so the spec's literal shim would have recorded the V2b call's 19,631 cache-creation tokens as `cache_write_tokens: 0`. The key is added.

3. **`equiv_cost_usd` already exists.** Spec §6 and the task brief both say to extend `telemetry.UsageEvent` with it; it is already there (`telemetry.py:43`) and already aggregated by `consumption_stats` in four places. T3 populates it rather than adding it, and adds the regression test proving a `cost_usd: None` / `equiv_cost_usd: 0.09` event totals correctly on the Usage page.

**Two gaps the spec did not name, filled here:** the rung needs its own Claude model ids (`Settings.agent_model` / `agent_disambiguation_model`) because `litellm_model` values like `gpt-5.4-mini` mean nothing to `claude --model`; and the engine core is **synchronous** with an `asyncio.to_thread` wrapper rather than the reverse, because three sync call sites may already be inside a running loop where `asyncio.run` raises.
