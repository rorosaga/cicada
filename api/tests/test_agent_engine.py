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
    for flag in ("-p", "--output-format", "stream-json", "--verbose", "--setting-sources",
                 "--safe-mode", "--strict-mcp-config", "--tools", "--no-session-persistence"):
        assert flag in argv
    # `--tools ""` is the empty-string value right after the flag.
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--model") + 1] == "sonnet"
    # `--system-prompt` is a single `--flag=value` token (fix round 1, M1) —
    # see test_argv_joins_the_system_prompt_into_one_token below for why.
    assert "--system-prompt=SYS" in argv


# --------------------------------------------------------------------------- #
# argv hardening (review fix round 1, M1)
# --------------------------------------------------------------------------- #

def test_argv_rejects_a_model_id_that_could_be_read_as_a_flag():
    """A `--model` value beginning with `-` would otherwise be appended as a
    bare argv token right after `--model` with no validation. Reject it here,
    before any subprocess spawns."""
    with pytest.raises(engine_errors.EngineModelNotFound):
        agent_engine.build_argv(model="-oops", system_prompt="S")


def test_argv_rejects_a_model_id_with_shell_metacharacters():
    with pytest.raises(engine_errors.EngineModelNotFound):
        agent_engine.build_argv(model="sonnet; rm -rf /", system_prompt="S")


def test_argv_accepts_the_conservative_model_id_charset():
    """Aliases and canonical ids alike: alphanumerics, dash, dot, slash, colon."""
    argv = agent_engine.build_argv(model="claude-sonnet-5", system_prompt="S")
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5"


def test_argv_joins_the_system_prompt_into_one_token():
    """Verified live against `claude` 2.1.252: `--flag=value` is accepted as a
    single token, and a leading `-` in `value` is never read as a new option —
    confirmed with `--model=-oops --output-format bogus`, which failed on the
    *forced* `--output-format` error, never on `-oops`. Joining
    `--system-prompt` this way makes a leading `-` structurally safe with no
    content rejected (the system prompt is free-form template text, not a
    value from a small known set like `model`)."""
    argv = agent_engine.build_argv(model="sonnet", system_prompt="-alsobad")
    assert "--system-prompt=-alsobad" in argv
    # and the value never appears as its own bare argv token that a parser
    # could mistake for a flag.
    assert "-alsobad" not in argv


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


def test_model_from_envelope_alias_heuristic_can_misattribute_a_verbose_side_call():
    """Review nit 3, pinned as a known/accepted limitation (see the WHY
    comment on model_from_envelope): called by alias, there is nothing in
    `modelUsage` that identifies which key answered the alias, so the
    heuristic is "whichever model produced the most output tokens" — correct
    for the real V1d shape (sonnet 57 out, haiku 8 out), but a verbose
    internal side-call can in principle out-output a terse main-model turn
    and get mis-attributed, as constructed here."""
    envelope = {
        "modelUsage": {
            "claude-sonnet-5": {"canonicalModel": "claude-sonnet-5", "outputTokens": 5},
            "claude-haiku-4-5": {"canonicalModel": "claude-haiku-4-5", "outputTokens": 500},
        }
    }
    assert agent_engine.model_from_envelope(envelope, "sonnet") == "claude-haiku-4-5"


def test_schema_constrained_tool_use_success_is_not_treated_as_a_failure(agent_envelopes):
    """Review nit 2 — the specific fixture trap: `stop_reason: "tool_use"`
    with `is_error: False`, `subtype: "success"`, `terminal_reason:
    "completed"` (spec §9 V1b ground truth). Neither `parse_envelope` nor
    `_classify_error` may ever branch on `stop_reason` for success/failure —
    this fixture is the regression guard for that."""
    env = agent_engine.parse_envelope(
        CliResult(0, json.dumps(agent_envelopes["schema_constrained_success"]), "")
    )
    assert env["is_error"] is False
    resp = agent_engine.response_shim(env, "haiku")
    assert json.loads(resp.choices[0].message.content) == {"decision": "same"}
    assert resp.choices[0].finish_reason == "tool_use"


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
    assert "--system-prompt=S" in call["argv"]


def test_complete_appends_a_json_only_instruction_when_no_schema_is_registered(agent_runner, agent_envelopes):
    runner = agent_runner(agent_envelopes["success"])
    agent_engine.complete(messages=[{"role": "system", "content": "S"},
                                    {"role": "user", "content": "B"}],
                          model="sonnet", stage="skills", want_json=True, runner=runner)
    argv = runner.calls[0]["argv"]
    assert "--json-schema" not in argv
    sp_token = next(a for a in argv if a.startswith("--system-prompt="))
    assert agent_engine.JSON_ONLY_SUFFIX in sp_token


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


def test_complete_rejects_an_unsafe_model_before_spawning(agent_runner, agent_envelopes):
    """The model-id validation in build_argv (M1) fires from inside complete()
    too, and fires BEFORE the runner is ever invoked."""
    runner = agent_runner(agent_envelopes["success"])
    with pytest.raises(engine_errors.EngineModelNotFound):
        agent_engine.complete(messages=[{"role": "user", "content": "B"}],
                              model="-oops", runner=runner)
    assert runner.calls == []


def test_breaker_fails_fast_without_spawning(agent_runner, agent_envelopes):
    runner = agent_runner(agent_envelopes["success"])
    assert agent_engine.trip_breaker("throttled at call 4") is True
    assert agent_engine.trip_breaker("again") is False  # only the first call trips it
    with pytest.raises(engine_errors.EngineThrottled):
        agent_engine.complete(messages=[{"role": "user", "content": "B"}],
                              model="sonnet", runner=runner)
    assert runner.calls == []  # nothing spawned


# --------------------------------------------------------------------------- #
# Breaker scoping (Devin PR #25 round 1, finding 1)
# --------------------------------------------------------------------------- #


def test_a_throttle_raised_in_scope_a_leaves_scope_b_running(agent_runner, agent_envelopes):
    """The concrete regression: a concurrent Ask/MCP call hitting a throttle
    must never abort an unrelated, in-flight Sleep cycle. Scope A tripping
    must be invisible to scope B's breaker check and to a `complete()` call
    made in scope B."""
    runner = agent_runner(agent_envelopes["success"])

    assert agent_engine.trip_breaker("throttled", scope="A") is True
    assert agent_engine.breaker_reason(scope="A") == "throttled"
    assert agent_engine.breaker_reason(scope="B") is None

    # Scope B's complete() proceeds and spawns normally.
    resp = agent_engine.complete(
        messages=[{"role": "user", "content": "hi"}], model="sonnet",
        runner=runner, scope="B",
    )
    assert resp["result"] == '{"entities": [], "relationships": []}'
    assert len(runner.calls) == 1

    # Scope A is still tripped and still fails fast without spawning.
    with pytest.raises(engine_errors.EngineThrottled):
        agent_engine.complete(
            messages=[{"role": "user", "content": "hi"}], model="sonnet",
            runner=runner, scope="A",
        )
    assert len(runner.calls) == 1  # the scope-A call never spawned


def test_trip_breaker_only_the_first_call_wins_within_one_scope():
    assert agent_engine.trip_breaker("first", scope="cycle-1") is True
    assert agent_engine.trip_breaker("second", scope="cycle-1") is False
    assert agent_engine.breaker_reason(scope="cycle-1") == "first"


def test_reset_breaker_only_clears_its_own_scope():
    agent_engine.trip_breaker("a", scope="A")
    agent_engine.trip_breaker("b", scope="B")
    agent_engine.reset_breaker(scope="A")
    assert agent_engine.breaker_reason(scope="A") is None
    assert agent_engine.breaker_reason(scope="B") == "b"


def test_use_scope_makes_nested_calls_default_to_that_scope(agent_runner, agent_envelopes):
    """A Sleep cycle wraps its whole run in `use_scope` and every nested
    `agent_engine.complete()`/`trip_breaker()` call inside it — with no
    explicit `scope=` argument — resolves against that same scope."""
    runner = agent_runner(agent_envelopes["rate_limited"])

    with agent_engine.use_scope("sleep:cycle-42"):
        assert agent_engine.current_scope() == "sleep:cycle-42"
        with pytest.raises(engine_errors.EngineThrottled):
            agent_engine.complete(
                messages=[{"role": "user", "content": "hi"}], model="sonnet", runner=runner,
            )
        # `complete()` only raises on discovering the throttle in-band — same
        # as providers.py's `_agent_invoke`, the CALLER trips the breaker.
        # With no explicit `scope=` it lands in the ambient "sleep:cycle-42"
        # bucket the `with` block established.
        assert agent_engine.trip_breaker("throttled") is True
        assert agent_engine.breaker_reason() == agent_engine.breaker_reason(scope="sleep:cycle-42")

        # A second call in the SAME (ambient) scope now fails fast — no
        # second spawn.
        with pytest.raises(engine_errors.EngineThrottled):
            agent_engine.complete(
                messages=[{"role": "user", "content": "hi"}], model="sonnet", runner=runner,
            )
        assert len(runner.calls) == 1

    # Outside the `with`, the ambient scope reverts and the trip does not leak.
    assert agent_engine.current_scope() != "sleep:cycle-42"
    assert agent_engine.breaker_reason() is None


def test_use_scope_purges_its_trip_on_exit_so_the_breaker_dict_stays_bounded():
    with agent_engine.use_scope("sleep:cycle-99"):
        agent_engine.trip_breaker("throttled")
        assert agent_engine.breaker_reason() is not None
    # `use_scope` purges the scope's entry on exit — a workload's throttle
    # can never outlive the workload that discovered it, and a later cycle
    # reusing a similar-looking (but distinct) cycle id starts clean.
    assert agent_engine.breaker_reason(scope="sleep:cycle-99") is None


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


def test_probe_rejects_non_plan_auth_with_the_login_fix():
    """Fix round 1, M2: verified empirically that `authMethod` cannot reflect
    a stray ANTHROPIC_API_KEY (every Cicada spawn runs under scrubbed_env(),
    which strips it first) — so the old "unset ANTHROPIC_API_KEY" remedy was
    a no-op. The real cause is a non-plan auth method persisted in the CLI's
    own config (API key helper, setup token, Bedrock, Vertex); the real fix
    is re-authing the CLI onto the plan."""
    def runner(argv, **kw):
        return CliResult(0, json.dumps({"loggedIn": True, "authMethod": "apiKeyHelper"}), "")
    ok, detail = agent_engine.probe(runner=runner)
    assert not ok
    assert "claude auth login" in detail
    assert "ANTHROPIC_API_KEY" not in detail


def test_probe_reports_a_missing_binary():
    ok, detail = agent_engine.probe(runner=lambda argv, **kw: CliResult(127, "", "not found"))
    assert not ok and "not installed" in detail


def test_is_valid_model_id_matches_build_argvs_charset():
    """G122 — `sleep_engine_prefs` validates a PUT body's model id through
    this public wrapper rather than reaching into the private `_MODEL_ID_RE`
    `build_argv` itself enforces (see that function's own docstring)."""
    for ok in ("sonnet", "claude-sonnet-5", "ollama/llama3.1:8b"):
        assert agent_engine.is_valid_model_id(ok), ok
    for bad in ("", "-oops", "rm -rf"):
        assert not agent_engine.is_valid_model_id(bad), bad


# --------------------------------------------------------------------------- #
# R-E1 — stream-json, the stop rules, capped retries, effort, the Stage-1 schema
# --------------------------------------------------------------------------- #

def test_argv_v2_pins_stream_json_verbose_and_no_setting_sources():
    argv = agent_engine.build_argv(model="sonnet", system_prompt="SYS")
    assert argv[argv.index("--output-format") + 1] == "stream-json" and "--verbose" in argv
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "--effort" not in argv


def test_argv_carries_a_valid_effort_and_rejects_a_flag_shaped_one():
    argv = agent_engine.build_argv(model="sonnet", system_prompt="S", effort="low")
    assert argv[argv.index("--effort") + 1] == "low"
    with pytest.raises(engine_errors.EngineModelNotFound):
        agent_engine.build_argv(model="sonnet", system_prompt="S", effort="--bare")


def test_complete_caps_the_clis_own_retries(agent_runner, agent_envelopes):
    runner = agent_runner(agent_envelopes["success"])
    agent_engine.complete(messages=[{"role": "user", "content": "x"}], model="sonnet", runner=runner)
    assert runner.calls[0]["env_overrides"] == {"CLAUDE_CODE_MAX_RETRIES": "2"}


def test_the_stage1_schema_ships_only_behind_its_flag(agent_runner, agent_envelopes):
    runner = agent_runner(agent_envelopes["success"])
    msgs = [{"role": "user", "content": "x"}]
    agent_engine.complete(messages=msgs, model="sonnet", stage="extraction", want_json=True, runner=runner)
    assert "--json-schema" not in runner.calls[0]["argv"]
    agent_engine.complete(messages=msgs, model="sonnet", stage="extraction", want_json=True,
                          runner=runner, policy=agent_engine.CallPolicy(extraction_schema=True))
    argv = runner.calls[1]["argv"]
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert "evidence_quote" in schema["properties"]["relationships"]["items"]["properties"]


def test_a_stop_on_a_failed_call_raises_the_right_error(agent_runner, claude_stream):
    msgs = [{"role": "user", "content": "x"}]
    overage = CliResult(1, claude_stream("rate_limited", rate_limits=[
        {"status": "rejected", "rateLimitType": "overage", "isUsingOverage": True}]), "")
    with pytest.raises(engine_errors.EngineOverage):
        agent_engine.complete(messages=msgs, model="sonnet", runner=agent_runner(overage))
    weekly = CliResult(1, claude_stream("rate_limited", rate_limits=[
        {"status": "rejected", "rateLimitType": "seven_day", "resetsAt": 1790000000}]), "")
    with pytest.raises(engine_errors.EngineExhausted) as info:
        agent_engine.complete(messages=msgs, model="sonnet", runner=agent_runner(weekly))
    assert info.value.resets_at == 1790000000
    five = CliResult(1, claude_stream("rate_limited", rate_limits=[
        {"status": "rejected", "rateLimitType": "five_hour"}]), "")
    with pytest.raises(engine_errors.EngineThrottled):
        agent_engine.complete(messages=msgs, model="sonnet", runner=agent_runner(five))


def test_a_near_limit_stop_on_a_failed_call_keeps_the_failures_real_class(agent_runner, claude_stream):
    """Final review H1: past 90% of the 5-hour window, an unrelated failure (a
    bad model id) must not be re-raised as EngineThrottled — that would trip
    the breaker for a throttle the plan never enforced. The stop still
    reaches ``on_signals``."""
    seen = {}
    bad_model = CliResult(1, claude_stream("model_not_found", rate_limits=[
        {"status": "allowed_warning", "rateLimitType": "five_hour", "utilization": 0.95}]), "")
    with pytest.raises(engine_errors.EngineError) as info:
        agent_engine.complete(messages=[{"role": "user", "content": "x"}], model="sonnet",
                              runner=agent_runner(bad_model),
                              on_signals=lambda stream, stop: seen.update(stop=stop))
    assert not isinstance(info.value, engine_errors.EngineThrottled)
    assert seen["stop"].kind == "near_limit"


def test_a_stop_on_a_successful_call_keeps_the_answer_and_reports_the_stop(agent_runner, claude_stream):
    seen = {}
    runner = agent_runner(CliResult(0, claude_stream("success", rate_limits=[
        {"status": "allowed_warning", "rateLimitType": "five_hour", "utilization": 0.93}]), ""))
    envelope = agent_engine.complete(
        messages=[{"role": "user", "content": "x"}], model="sonnet", runner=runner,
        on_signals=lambda stream, stop: seen.update(stream=stream, stop=stop))
    assert envelope["subtype"] == "success"
    assert seen["stop"].kind == "near_limit" and "93% used" in seen["stop"].sentence


def test_an_opted_in_overage_does_not_stop(agent_runner, claude_stream):
    seen = {}
    runner = agent_runner(CliResult(0, claude_stream("success", rate_limits=[
        {"status": "allowed", "rateLimitType": "overage", "isUsingOverage": True}]), ""))
    agent_engine.complete(messages=[{"role": "user", "content": "x"}], model="sonnet", runner=runner,
                          policy=agent_engine.CallPolicy(allow_overage=True),
                          on_signals=lambda stream, stop: seen.update(stop=stop))
    assert seen["stop"] is None


def test_a_rate_limit_retry_that_runs_out_the_clock_is_a_throttle_not_a_timeout():
    stdout = json.dumps({"type": "system", "subtype": "api_retry", "error": "rate_limit",
                         "error_status": 429}) + "\n"
    with pytest.raises(engine_errors.EngineThrottled):
        agent_engine.parse_envelope(CliResult(124, stdout, "claude timed out after 300s"))
    with pytest.raises(engine_errors.EngineTimeout):
        agent_engine.parse_envelope(CliResult(124, "", "claude timed out after 300s"))


def test_a_billing_retry_is_exhaustion(claude_stream):
    stdout = claude_stream("unclassified_error", retries=[{"error": "billing_error"}])
    with pytest.raises(engine_errors.EngineExhausted):
        agent_engine.parse_envelope(CliResult(1, stdout, ""))


def test_a_truncated_stream_is_a_retryable_protocol_error(claude_stream):
    with pytest.raises(engine_errors.EngineProtocolError):
        agent_engine.parse_envelope(CliResult(0, claude_stream(None), ""))


def test_shim_prefers_the_validated_structured_output():
    env = {"type": "result", "subtype": "success", "is_error": False, "result": "prose",
           "structured_output": {"ok": True}, "usage": {}}
    assert agent_engine.response_shim(env, "sonnet").choices[0].message.content == '{"ok": true}'


def test_a_live_shaped_event_with_no_top_level_utilization_still_stops(agent_runner, claude_stream):
    """claude 2.1.280 reports the fraction only under `unifiedWindows`
    (fixtures/claude_stream_live.jsonl) — the 90 % rule must still fire."""
    seen = {}
    runner = agent_runner(CliResult(0, claude_stream("success", rate_limits=[{
        "status": "allowed", "rateLimitType": "five_hour", "resetsAt": 1790000000,
        "overageStatus": "rejected", "isUsingOverage": False,
        "unifiedWindows": {"five_hour": {"utilization": 0.92, "resetsAt": 1790000000},
                           "seven_day": {"utilization": 0.4, "resetsAt": 1790100000}}}]), ""))
    agent_engine.complete(messages=[{"role": "user", "content": "x"}], model="sonnet", runner=runner,
                          on_signals=lambda stream, stop: seen.update(stop=stop))
    assert seen["stop"].kind == "near_limit" and "92% used" in seen["stop"].sentence
