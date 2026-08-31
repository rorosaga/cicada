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
