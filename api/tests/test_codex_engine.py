"""R-E2/R-E15–R-E17 — the `codex exec` engine over recorded JSONL
(conftest `codex_events`). ZERO real spawns: every test injects a runner."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from api.config import Settings
from api.services import agent_engine, codex_engine, engine_errors, engine_schemas, providers
from api.services.codex_app_server import CodexSnapshot
from api.services.connections.base import CliResult
from api.services.telemetry import UsageEvent

MSGS = [{"role": "user", "content": "hi"}]


def _argv(tmp_path, **kw):
    base_kw = dict(model="gpt-5.6-luna", effort="low", instructions_path=tmp_path / "i.md",
                   schema_path=tmp_path / "s.json", cwd=tmp_path / "cwd")
    base_kw.update(kw)
    return codex_engine.build_argv(**base_kw)


def test_argv_is_exactly_the_verified_isolation_set(tmp_path):
    argv = _argv(tmp_path)
    assert argv[:1 + len(codex_engine.CODEX_PINNED)] == ["codex", *codex_engine.CODEX_PINNED]
    for flag in ("--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", "--json"):
        assert flag in argv
    disabled = {argv[i + 1] for i, a in enumerate(argv) if a == "--disable"}
    assert disabled == {"memories", "hooks", "plugins", "apps", "multi_agent", "shell_tool",
                        "unified_exec", "image_generation", "view_image"}
    assert argv[argv.index("-s") + 1] == "read-only" and 'web_search="disabled"' in argv
    # Final review M4: Codex's bundled skills listing is kept off every call.
    assert "skills.include_instructions=false" in argv
    assert "include_permissions_instructions=false" in argv
    assert "include_collaboration_mode_instructions=false" in argv
    assert argv[argv.index("-C") + 1] == str(tmp_path / "cwd")
    assert argv[argv.index("-m") + 1] == "gpt-5.6-luna" and 'model_reasoning_effort="low"' in argv
    assert f"model_instructions_file={json.dumps(str(tmp_path / 'i.md'))}" in argv
    assert argv[argv.index("--output-schema") + 1] == str(tmp_path / "s.json")
    assert argv[-1] == "-"
    assert not any("dangerously" in a or a == "--yolo" or "full-access" in a for a in argv)


def test_argv_rejects_a_flag_shaped_model_or_effort_and_omits_an_empty_model(tmp_path):
    with pytest.raises(engine_errors.EngineModelNotFound):
        _argv(tmp_path, model="-oops")
    with pytest.raises(engine_errors.EngineModelNotFound):
        _argv(tmp_path, effort="low; rm")
    argv = _argv(tmp_path, model="", schema_path=None)
    assert "-m" not in argv and "--output-schema" not in argv


def test_warning_items_on_a_completed_turn_are_a_success(codex_events):
    parsed = codex_engine.parse_events(codex_events["ok"])
    codex_engine.check(CliResult(0, codex_events["ok"], ""), parsed)
    assert parsed.text == '{"ok":true}' and parsed.usage["input_tokens"] == 11589
    assert parsed.completed and parsed.failure is None and len(parsed.warnings) == 1


def test_a_retry_notice_before_a_completed_turn_is_not_a_failure(codex_events):
    parsed = codex_engine.parse_events(codex_events["reconnected_then_ok"])
    codex_engine.check(CliResult(0, codex_events["reconnected_then_ok"], ""), parsed)
    assert parsed.failure is None and parsed.text == '{"ok":true}'


def test_signed_out_is_unavailable_with_the_sign_in_fix(codex_events):
    parsed = codex_engine.parse_events(codex_events["signed_out"])
    assert parsed.failure.startswith("unexpected status 401")
    with pytest.raises(engine_errors.EngineUnavailable) as info:
        codex_engine.check(CliResult(1, codex_events["signed_out"], ""), parsed)
    assert str(info.value) == codex_engine.SIGNED_OUT


def test_a_usage_limit_is_a_throttle(codex_events):
    with pytest.raises(engine_errors.EngineThrottled):
        codex_engine.check(CliResult(1, codex_events["usage_limit"], ""),
                           codex_engine.parse_events(codex_events["usage_limit"]))


def test_a_turn_with_no_answer_is_a_protocol_error(codex_events):
    with pytest.raises(engine_errors.EngineProtocolError):
        codex_engine.check(CliResult(0, codex_events["no_answer"], ""),
                           codex_engine.parse_events(codex_events["no_answer"]))


def test_no_events_rc_127_and_rc_124():
    with pytest.raises(engine_errors.EngineUnavailable):
        codex_engine.check(CliResult(1, "", "boom"), codex_engine.parse_events(""))
    with pytest.raises(engine_errors.EngineUnavailable) as info:
        codex_engine.check(CliResult(127, "", "codex: not found"), codex_engine.parse_events(""))
    assert "npm i -g @openai/codex" in str(info.value)
    with pytest.raises(engine_errors.EngineTimeout):
        codex_engine.check(CliResult(124, "", "timed out"), codex_engine.parse_events(""))


def test_complete_writes_private_per_call_files_and_deletes_them(codex_events):
    seen = {}

    def runner(argv, *, stdin=None, timeout=None, cwd=None, **_kw):
        instr = Path(json.loads(next(a for a in argv if a.startswith("model_instructions_file="))
                                .split("=", 1)[1]))
        schema = Path(argv[argv.index("--output-schema") + 1])
        seen.update(instructions=instr.read_text(), mode=oct(instr.stat().st_mode)[-3:], paths=(instr, schema),
                    schema=json.loads(schema.read_text()), stdin=stdin, cwd=cwd)
        return CliResult(0, codex_events["extraction"], "")

    parsed = codex_engine.complete(
        messages=[{"role": "system", "content": "EXTRACT"}, {"role": "user", "content": "transcript"}],
        model="gpt-5.6-luna", stage="extraction", want_json=True, runner=runner)
    assert seen["instructions"] == "EXTRACT" and seen["mode"] == "600" and seen["stdin"] == "transcript"
    assert seen["schema"] == engine_schemas.extraction_schema(strict=True)
    assert all(not p.exists() for p in seen["paths"])
    assert Path(seen["cwd"]).name == "cwd"
    assert json.loads(parsed.text)["entities"][0]["name"] == "alpha-project"


def test_codexs_own_prompt_is_always_replaced(codex_events):
    seen = {}

    def runner(argv, **_kw):
        instr = Path(json.loads(next(a for a in argv if a.startswith("model_instructions_file="))
                                .split("=", 1)[1]))
        seen["text"] = instr.read_text()
        seen["schema"] = "--output-schema" in argv
        return CliResult(0, codex_events["ok"], "")

    codex_engine.complete(messages=MSGS, model="", stage="skills", want_json=True, runner=runner)
    assert seen["text"] == agent_engine.JSON_ONLY_SUFFIX and seen["schema"] is False
    codex_engine.complete(messages=MSGS, model="", stage="ask", want_json=False, runner=runner)
    assert seen["text"] == codex_engine.DEFAULT_INSTRUCTIONS


def test_the_shared_breaker_fails_fast_without_spawning(agent_runner, codex_events):
    runner = agent_runner(CliResult(0, codex_events["ok"], ""))
    agent_engine.trip_breaker("ChatGPT plan limit reached")
    with pytest.raises(engine_errors.EngineThrottled) as info:
        codex_engine.complete(messages=MSGS, model="gpt-5.6-luna", runner=runner)
    assert info.value.spawned is False and runner.calls == []


def test_the_shim_follows_the_ledgers_gross_rule(codex_events):
    resp = codex_engine.response_shim(codex_engine.parse_events(codex_events["ok"]), "gpt-5.6-luna")
    assert resp.choices[0].message.content == '{"ok":true}'
    assert resp["usage"]["prompt_tokens"] == 11589 and resp.usage.completion_tokens == 15
    assert resp.model == "gpt-5.6-luna"


def test_model_and_effort_come_from_their_own_settings():
    s = Settings(codex_model="gpt-5.6-luna", codex_disambiguation_model="gpt-5.5")
    assert codex_engine.model_for_stage(s, "extraction") == "gpt-5.6-luna"
    assert codex_engine.model_for_stage(s, "disambiguation") == "gpt-5.5"
    assert codex_engine.model_for_stage(Settings(), None) == ""
    assert codex_engine.effort_for(Settings()) == "low"


# --- the seam ---------------------------------------------------------------

def test_the_codex_rung_is_subscription_shaped_on_the_ledger(agent_runner, codex_events):
    events: list[UsageEvent] = []
    fn = providers.resolve_llm_fn(Settings(llm_mode="codex", codex_model="gpt-5.6-luna"),
                                  stage="extraction", sink=events.append, is_async=False,
                                  runner=agent_runner(CliResult(0, codex_events["ok"], "")))
    resp = fn(messages=MSGS)
    assert resp.choices[0].message.content == '{"ok":true}'
    [ev] = events
    assert (ev.engine, ev.connection, ev.billing, ev.model) == ("codex-cli", "chatgpt-plan", "subscription", "gpt-5.6-luna")
    assert ev.cost_usd is None and ev.equiv_cost_usd is None and ev.input_tokens == 11589
    assert ev.refs == {"warnings": 1}
    assert "gpt-5.6-luna" in agent_engine.models_used()


def test_a_codex_throttle_trips_the_same_scoped_breaker(agent_runner, codex_events):
    events: list[UsageEvent] = []
    runner = agent_runner(CliResult(1, codex_events["usage_limit"], ""))
    fn = providers.resolve_llm_fn(Settings(llm_mode="codex"), sink=events.append, runner=runner, is_async=False)
    with pytest.raises(engine_errors.EngineThrottled):
        fn(messages=MSGS)
    with pytest.raises(engine_errors.EngineThrottled):
        fn(messages=MSGS)
    assert len(runner.calls) == 1 and [e.kind for e in events] == ["llm_call", "throttle"]
    assert events[1].connection == "chatgpt-plan"


def test_an_async_call_site_gets_an_awaitable(agent_runner, codex_events):
    async def acompletion(**_kw):  # pragma: no cover — never called on a CLI rung
        raise AssertionError

    fn = providers.resolve_llm_fn(Settings(llm_mode="codex"), completion=acompletion,
                                  runner=agent_runner(CliResult(0, codex_events["ok"], "")))
    resp = asyncio.run(fn(messages=MSGS))
    assert resp.choices[0].message.content == '{"ok":true}'


# --- probe + pre-flight -------------------------------------------------------

def _snap(**kw):
    base_kw = dict(signed_in=True, account_type="chatgpt", plan="plus", email="bob@example.com",
                   limit_reached=None, ordinary_usage_allowed=True, used_percent=20, resets_at=None,
                   models=("gpt-6-astra", "gpt-5.6-luna"), default_model="gpt-6-astra")
    base_kw.update(kw)
    return CodexSnapshot(**base_kw)


def _preflight(snap, probe=None):
    async def snapshot_fn(*, fresh):
        assert fresh is True           # R-E18: always fresh on a cycle
        return snap
    return asyncio.run(codex_engine.preflight(snapshot_fn=snapshot_fn, probe_fn=probe))


def test_preflight_passes_a_signed_in_plan_and_names_its_default_model():
    assert _preflight(_snap()) == (True, "Signed in to ChatGPT Plus.", "gpt-6-astra")


def test_preflight_refuses_signed_out_an_api_key_and_a_reached_limit():
    assert _preflight(_snap(signed_in=False, account_type=None))[:2] == (False, codex_engine.SIGNED_OUT)
    assert _preflight(_snap(account_type="apiKey"))[:2] == (False, codex_engine.API_KEY_ACCOUNT)
    ok, detail, _ = _preflight(_snap(limit_reached="rate_limit_reached"))
    assert not ok and detail.startswith("Your ChatGPT plan's Codex limit is used up")


def test_preflight_trusts_a_signed_in_reply_with_no_account_type():
    """Final review M3: the card (``codex_cli.status``) reads a type-less
    signed-in reply as Connected; the cycle must agree, not call it a key."""
    ok, detail, _ = _preflight(_snap(account_type=None))
    assert ok and detail != codex_engine.API_KEY_ACCOUNT


def test_preflight_degrades_to_login_status_when_the_app_server_is_unavailable():
    assert _preflight(None, probe=lambda **kw: (True, "Signed in to ChatGPT.")) == (
        True, "Signed in to ChatGPT (plan details unavailable right now).", None)
    assert _preflight(None, probe=lambda **kw: (False, codex_engine.SIGNED_OUT)) == (
        False, codex_engine.SIGNED_OUT, None)


def test_probe_maps_login_status():
    assert codex_engine.probe(runner=lambda argv, **kw: CliResult(0, "Logged in using ChatGPT", ""))[0] is True
    assert codex_engine.probe(runner=lambda argv, **kw: CliResult(1, "", "Not logged in")) == (False, codex_engine.SIGNED_OUT)
    assert codex_engine.probe(runner=lambda argv, **kw: CliResult(127, "", ""))[1] == codex_engine.INSTALL_HINT
