"""G49/G50 — Cursor, OpenCode and Grok as Sleep engines on the person's own sign-in (`cli_engines`).

None of the three tools is installed here, and none may be: each test puts a stub executable on a scratch PATH that
replays the tool's documented output (cursor.com/docs/cli, opencode.ai/docs/cli, xai-org/grok-build's headless guide)
and records the argv, working directory and environment it was spawned with. The real runner
(`connections.base.run_cli_sync`) spawns it, so the scrubbed environment is the one a real call gets.
"""
from __future__ import annotations

import io
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.services import cli_engines, engine_errors, engine_select
from api.services.cli_engines import CURSOR, GROK, OPENCODE
from api.services.connections import base
from api.services.connections.base import run_cli_sync as REAL_RUN   # bound before conftest's guard patches it

STUB = r'''#!{python}
import json, os, sys
mode = os.environ.get("STUB_MODE", "ok")
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
record = {{"argv": args, "cwd": os.getcwd(), "env": dict(os.environ), "files": sorted(
    os.path.relpath(os.path.join(d, f), os.getcwd()) for d, _, fs in os.walk(os.getcwd()) for f in fs)}}
for i, a in enumerate(args):
    if a in ("--prompt-file", "--file"):
        record["prompt"] = open(args[i + 1]).read()
    if a == "--workspace":
        deny = os.path.join(args[i + 1], ".cursor", "cli.json")
        record["cursor_deny"] = json.load(open(deny)) if os.path.exists(deny) else None
with open(os.environ["STUB_RECORD"], "a") as fh:
    fh.write(json.dumps(record) + "\n")

def out(obj):
    sys.stdout.write(json.dumps(obj) + "\n")

if args[:1] == ["--help"]:
    print(os.environ.get("STUB_HELP", "Cursor Agent - the Cursor CLI")); sys.exit(0)
if os.environ.get("STUB_HANG") == name and args[:1] in (["status"], ["models"]):
    import time; time.sleep(30)
if args[:1] == ["status"]:
    if mode == "signed_out":
        print("Not logged in. Run `agent login`."); sys.exit(1)
    print("Logged in as <person-a>"); sys.exit(0)
if args[:1] == ["models"]:
    if mode == "signed_out":
        sys.stderr.write("Error: not authenticated. Run `grok login` or set XAI_API_KEY\n"); sys.exit(1)
    if name == "opencode":
        lines = ["openai/gpt-5.5", "anthropic/claude-sonnet-5"]
        if mode != "no_plan":
            lines += ["github-copilot/gpt-5.5", "opencode-go/kimi-k3"]
        print("\n".join(lines)); sys.exit(0)
    if name == "grok":
        print("my-bedrock-proxy\ngrok-4.6\ngrok-4.6-mini"); sys.exit(0)
    print("Available models:\n  auto - Auto\n  sonnet-5 - Sonnet 5\n  grok-4.6"); sys.exit(0)

if mode == "signed_out":
    if name == "grok":
        out({{"type": "error", "message": "Couldn't start session: not authenticated, run grok login"}}); sys.exit(1)
    sys.stderr.write("Error: Not authenticated. Please run agent login.\n"); sys.exit(1)
if mode == "limit":
    if name == "opencode":
        out({{"type": "error", "timestamp": 1, "sessionID": "s", "error": {{"name": "APIError",
             "data": {{"message": "429 Too Many Requests: rate limit exceeded"}}}}}}); sys.exit(1)
    if name == "grok":
        out({{"type": "error", "message": "Weekly usage pool used up — usage limit reached"}}); sys.exit(1)
    sys.stderr.write("You've hit your usage limit\n"); sys.exit(1)
if mode == "unknown_model":
    if name == "grok":
        out({{"type": "error", "message": "Couldn't start session: unknown model 'grok-0'"}}); sys.exit(1)
    sys.stderr.write("Error: model not found: nope-1\n"); sys.exit(1)

answer = '{{"entities": []}}'
if name in ("agent", "cursor-agent"):
    out({{"type": "result", "subtype": "success", "is_error": False, "duration_ms": 9, "duration_api_ms": 9,
         "result": answer, "session_id": "sess-1"}})
elif name == "opencode":
    out({{"type": "step_start", "timestamp": 1, "sessionID": "s", "part": {{}}}})
    out({{"type": "text", "timestamp": 2, "sessionID": "s", "part": {{"type": "text", "text": answer}}}})
    out({{"type": "step_finish", "timestamp": 3, "sessionID": "s", "part": {{"providerID": "github-copilot",
         "modelID": "gpt-5.5", "tokens": {{"input": 40, "output": 7, "cache": {{"read": 5, "write": 0}}}}, "cost": 0}}}})
else:
    body = {{"text": answer, "stopReason": "end_turn", "sessionId": "s", "requestId": "r", "num_turns": 1,
            "usage": {{"input_tokens": 30, "output_tokens": 6, "cache_read_input_tokens": 0}},
            "modelUsage": {{"grok-4.6": {{"inputTokens": 30, "outputTokens": 6, "modelCalls": 1}}}}}}
    if mode == "metered":
        body["total_cost_usd"] = 0.0021
        body["total_cost_usd_ticks"] = 21000000
    out(body)
'''


@pytest.fixture
def stubs(tmp_path, monkeypatch):
    """A scratch PATH holding only the stubs, a scratch CICADA_HOME, and a record of every spawn."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = STUB.format(python=sys.executable)
    for name in ("agent", "opencode", "grok"):
        path = bindir / name
        path.write_text(script, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    record = tmp_path / "record.jsonl"
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("STUB_RECORD", str(record))
    monkeypatch.setenv("STUB_MODE", "ok")
    # Keys a person might have exported: a child must never see them (rail 1).
    monkeypatch.setenv("CURSOR_API_KEY", "placeholder-cursor-key")
    monkeypatch.setenv("XAI_API_KEY", "placeholder-xai-key")
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"permission": {"*": "allow"}}')
    for d in ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin"):
        for name in ("cursor-agent", "agent", "opencode", "grok"):
            assert not (Path(os.path.expanduser(d)) / name).exists(), "a real tool is installed; never spawn it"
    # The suite's guard forbids the real runner; these tests need it, pointed only at the stubs above.
    monkeypatch.setattr(base, "run_cli_sync", REAL_RUN)
    cli_engines.invalidate()

    def spawns() -> list[dict]:
        if not record.exists():
            return []
        return [json.loads(line) for line in record.read_text().splitlines() if line.strip()]

    return SimpleNamespace(bindir=bindir, spawns=spawns)


MESSAGES = [{"role": "system", "content": "Extract the entities."}, {"role": "user", "content": "A conversation."}]


def _call(spec, **kw):
    return cli_engines.complete(spec, messages=MESSAGES, model=kw.pop("model", ""), want_json=True,
                                scope="sleep:test", **kw)


# --------------------------------------------------------------------------- #
# Success, and every call's no-tools / no-capture / no-key environment
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("spec", [CURSOR, OPENCODE, GROK], ids=lambda s: s.mode)
def test_success_reads_the_answer_without_tools_capture_or_keys(stubs, spec):
    model = {"cursor": "auto", "opencode": "github-copilot/gpt-5.5", "grok": "grok-4.6"}[spec.mode]
    parsed = _call(spec, model=model)
    assert json.loads(parsed.text) == {"entities": []}
    spawn = [s for s in stubs.spawns() if s["argv"][:1] not in (["--help"], ["models"], ["status"])][-1]
    env, argv = spawn["env"], spawn["argv"]
    # Rail 4: the child's own hooks are silent on both switches.
    assert env["CICADA_CAPTURE"] == "off" and env["CICADA_RECALL"] == "off"
    # Rail 1: no key that would move the tool off the person's sign-in reaches the child.
    for key in ("CURSOR_API_KEY", "XAI_API_KEY"):
        assert key not in env
    # The person's own inline OpenCode config never reaches a child; OpenCode gets Cicada's (MCP off, tools denied).
    assert "allow" not in env.get("OPENCODE_CONFIG_CONTENT", "")
    assert ("OPENCODE_CONFIG_CONTENT" in env) is (spec is OPENCODE)
    # Rail 3: an empty scratch cwd under CICADA_HOME, deleted after the call; no approve-everything flag.
    assert spawn["cwd"].startswith(str(Path(os.environ["CICADA_HOME"]).resolve())) or \
        spawn["cwd"].startswith(os.environ["CICADA_HOME"])
    assert not Path(spawn["cwd"]).exists()
    for flag in ("--force", "--yolo", "--always-approve", "--auto", "--dangerously-skip-permissions",
                 "bypassPermissions", "--approve-mcps"):
        assert flag not in argv
    assert "Do not run commands" in (spawn.get("prompt") or argv[-1])


def _call_spawn(stubs):
    return [s for s in stubs.spawns() if s["argv"][:1] not in (["--help"], ["models"], ["status"])][-1]


def test_cursor_runs_in_ask_mode_with_a_deny_all_project_file(stubs):
    _call(CURSOR, model="auto")
    spawn = _call_spawn(stubs)
    argv = spawn["argv"]
    assert argv[:3] == ["-p", "--output-format", "json"]
    assert argv[argv.index("--mode") + 1] == "ask" and "--trust" in argv
    assert argv[argv.index("--model") + 1] == "auto"
    deny = spawn["cursor_deny"]["permissions"]["deny"]
    assert {"Shell(*)", "Read(**)", "Write(**)", "WebFetch(*)", "Mcp(*:*)"} <= set(deny)
    assert spawn["files"] == [".cursor/cli.json"]


def test_opencode_denies_every_tool_and_loads_no_outside_config(stubs):
    _call(OPENCODE, model="github-copilot/gpt-5.5")
    spawn = _call_spawn(stubs)
    env, argv = spawn["env"], spawn["argv"]
    assert json.loads(env["OPENCODE_PERMISSION"]) == {"*": "deny"}
    assert env["OPENCODE_DISABLE_CLAUDE_CODE"] == "1" and env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert argv[:3] == ["run", "--format", "json"] and "--pure" in argv
    assert argv[argv.index("-m") + 1] == "github-copilot/gpt-5.5"
    assert "Extract the entities." in spawn["prompt"]


def test_grok_denies_every_tool_kind_and_no_web_agents_or_plan(stubs):
    _call(GROK)
    spawn = _call_spawn(stubs)
    argv = spawn["argv"]
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    denied = {argv[i + 1] for i, a in enumerate(argv) if a == "--deny"}
    assert denied == {"Bash", "Edit", "Write", "Read", "Grep", "WebFetch", "MCPTool"}
    for flag in ("--disable-web-search", "--no-subagents", "--no-plan", "--no-auto-update"):
        assert flag in argv
    assert argv[argv.index("--disallowed-tools") + 1] == "Agent"
    # No model chosen: never Grok's own config default (it could be key-backed) — the first built-in grok-… id it
    # lists, skipping the custom provider model listed first.
    assert argv[argv.index("-m") + 1] == "grok-4.6"


def test_the_model_a_tool_reports_is_the_one_recorded(stubs):
    shim = cli_engines.response_shim(_call(GROK, model="grok-4.6-mini"), "grok-4.6-mini")
    assert shim["model"] == "grok-4.6"          # from modelUsage: what served, not what was asked
    shim = cli_engines.response_shim(_call(OPENCODE, model="github-copilot/gpt-5.5"), "github-copilot/gpt-5.5")
    assert shim["model"] == "github-copilot/gpt-5.5"
    assert shim["usage"]["prompt_tokens"] == 45 and shim["usage"]["completion_tokens"] == 7
    shim = cli_engines.response_shim(_call(CURSOR), "")
    assert shim["model"] == ""                   # Cursor's json names no model and none was asked for: omitted


# --------------------------------------------------------------------------- #
# Signed out, plan limit, metered, unknown model
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("spec", [CURSOR, OPENCODE, GROK], ids=lambda s: s.mode)
def test_signed_out_names_the_exact_sign_in_command(stubs, monkeypatch, spec):
    monkeypatch.setenv("STUB_MODE", "signed_out")
    model = {"opencode": "github-copilot/gpt-5.5", "grok": "grok-4.6"}.get(spec.mode, "")
    with pytest.raises(engine_errors.EngineUnavailable) as err:
        _call(spec, model=model)
    assert spec.sign_in in str(err.value)


@pytest.mark.parametrize("spec", [CURSOR, OPENCODE, GROK], ids=lambda s: s.mode)
def test_a_plan_limit_is_a_throttle_so_sleep_pauses(stubs, monkeypatch, spec):
    monkeypatch.setenv("STUB_MODE", "limit")
    model = {"opencode": "github-copilot/gpt-5.5", "grok": "grok-4.6"}.get(spec.mode, "")
    with pytest.raises(engine_errors.EngineThrottled) as err:
        _call(spec, model=model)
    assert "Sleep paused" in str(err.value) and spec.plan_name in str(err.value)


@pytest.mark.parametrize("spec", [CURSOR, OPENCODE, GROK], ids=lambda s: s.mode)
def test_an_unknown_model_is_a_configuration_error(stubs, monkeypatch, spec):
    monkeypatch.setenv("STUB_MODE", "unknown_model")
    model = {"opencode": "github-copilot/nope-1", "grok": "grok-0"}.get(spec.mode, "nope-1")
    with pytest.raises(engine_errors.EngineModelNotFound):
        _call(spec, model=model)


def test_grok_on_an_api_key_stops_the_run(stubs, monkeypatch):
    monkeypatch.setenv("STUB_MODE", "metered")
    with pytest.raises(engine_errors.EngineOverage) as err:
        _call(GROK, model="grok-4.6")
    assert "API key" in str(err.value)


def test_opencode_never_calls_a_key_backed_model(stubs):
    with pytest.raises(engine_errors.EngineUnavailable) as err:
        _call(OPENCODE, model="anthropic/claude-sonnet-5")
    assert "Nothing was read" in str(err.value)
    assert stubs.spawns() == []                  # refused before any spawn
    assert getattr(err.value, "spawned", True) is False


def test_a_tripped_breaker_never_spawns(stubs):
    from api.services import agent_engine

    agent_engine.trip_breaker("Your Grok plan hit its usage limit", scope="sleep:test")
    try:
        with pytest.raises(engine_errors.EngineThrottled):
            _call(GROK, model="grok-4.6")
    finally:
        agent_engine.reset_breaker(scope="sleep:test")
    assert stubs.spawns() == []


def test_a_missing_tool_says_how_to_install_it(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    cli_engines.invalidate()
    st = cli_engines.probe_now(GROK)
    assert not st.available and "grok login" in st.detail
    with pytest.raises(engine_errors.EngineUnavailable) as err:
        _call(GROK, model="grok-4.6")
    assert "isn't installed" in str(err.value)


# --------------------------------------------------------------------------- #
# Status and models
# --------------------------------------------------------------------------- #


def test_status_lists_live_models_and_opencode_only_plan_ones(stubs):
    cursor = cli_engines.probe_now(CURSOR)
    assert cursor.connected and cursor.models == ["auto", "sonnet-5", "grok-4.6"]
    oc = cli_engines.probe_now(OPENCODE)
    assert oc.connected and oc.models == ["github-copilot/gpt-5.5", "opencode-go/kimi-k3"]
    grok = cli_engines.probe_now(GROK)
    assert grok.connected and grok.models == ["grok-4.6", "grok-4.6-mini"], "only xAI's built-in ids"


def test_opencode_with_only_api_keys_is_not_a_plan(stubs, monkeypatch):
    monkeypatch.setenv("STUB_MODE", "no_plan")
    st = cli_engines.probe_now(OPENCODE)
    assert st.available and not st.connected and "opencode auth login" in st.detail


@pytest.mark.parametrize("spec", [CURSOR, GROK], ids=lambda s: s.mode)
def test_status_signed_out(stubs, monkeypatch, spec):
    monkeypatch.setenv("STUB_MODE", "signed_out")
    st = cli_engines.probe_now(spec)
    assert st.available and not st.connected and spec.sign_in in st.detail


def test_a_saved_model_never_disappears_and_a_stale_one_says_so():
    st = cli_engines.Status(True, True, "Signed in.", ["auto", "sonnet-5"], 1.0)
    assert cli_engines.model_choices(CURSOR, st, "gpt-old") == ["auto", "sonnet-5", "gpt-old"]
    assert "no longer lists gpt-old" in cli_engines.stale_model_sentence(CURSOR, st, "gpt-old")
    assert cli_engines.stale_model_sentence(CURSOR, st, "auto") is None
    # No live list (signed out, or the listing failed): the documented defaults, and nothing is called stale.
    assert cli_engines.model_choices(CURSOR, None, None) == ["auto"]
    assert cli_engines.stale_model_sentence(CURSOR, None, "gpt-old") is None


def test_preflight_refuses_a_stale_model_and_fills_opencodes_first_plan_model(stubs):
    import asyncio

    stale = SimpleNamespace(cli_engine_model="gone-1", cli_engine_disambiguation_model="")
    ok, sentence, _ = asyncio.run(cli_engines.preflight(CURSOR, stale))
    assert not ok and "gone-1" in sentence
    blank = SimpleNamespace(cli_engine_model="", cli_engine_disambiguation_model="")
    ok, sentence, fill = asyncio.run(cli_engines.preflight(OPENCODE, blank))
    assert ok and fill == "github-copilot/gpt-5.5" and fill in sentence
    keyed = SimpleNamespace(cli_engine_model="anthropic/claude-sonnet-5", cli_engine_disambiguation_model="")
    ok, sentence, _ = asyncio.run(cli_engines.preflight(OPENCODE, keyed))
    assert not ok and "API key" in sentence


# --------------------------------------------------------------------------- #
# Rail 4 — Cicada's own hooks in a spawned child's environment
# --------------------------------------------------------------------------- #


def test_cicadas_hooks_stay_silent_in_a_spawned_childs_environment(stubs, tmp_path):
    """Cursor runs Cicada's Cursor hook, Gemini CLI its capture hook, and Grok also runs Claude Code's hooks: each,
    handed the exact environment a Sleep spawn got, captures nothing and recalls nothing."""
    from api.hooks import capture, cursor, recall

    _call(CURSOR, model="auto")
    env = dict(_call_spawn(stubs)["env"])
    env["CICADA_HOME"] = str(tmp_path / "hookhome")

    def never(*_a, **_kw):
        raise AssertionError("a hook in a Sleep spawn must never reach the backend")

    turn = json.dumps({"hook_event_name": "stop", "conversation_id": "c1", "status": "completed"})
    assert cursor.main(stdin=io.StringIO(turn), stdout=io.StringIO(), environ=env, post=never) == 0
    start = json.dumps({"hook_event_name": "sessionStart", "conversation_id": "c1", "workspace_roots": ["/tmp"]})
    out = io.StringIO()
    assert cursor.main(stdin=io.StringIO(start), stdout=out, environ=env, post=never) == 0
    assert json.loads(out.getvalue()) == {"continue": True}
    gemini = json.dumps({"hook_event_name": "AfterAgent", "session_id": "g1", "prompt": "hi",
                         "prompt_response": "hello"})
    assert capture.main(["--harness", "gemini-cli"], stdin=io.StringIO(gemini), stdout=io.StringIO(),
                        environ=env, post=never, log_path=tmp_path / "capture.log") == 0
    assert "skipped: CICADA_CAPTURE=off" in (tmp_path / "capture.log").read_text()
    assert recall.main(["--harness", "claude-code"], stdin=io.StringIO("{}"), stdout=io.StringIO(),
                       environ=env, post=never, log_path=tmp_path / "recall.log") == 0
    assert "skipped: CICADA_RECALL=off" in (tmp_path / "recall.log").read_text()


# --------------------------------------------------------------------------- #
# Engine selection: plans under ruling 4; Cursor and OpenCode Auto's last rungs (ruling 46), Grok never
# --------------------------------------------------------------------------- #


def test_the_new_engines_are_plans_and_cursor_then_opencode_close_autos_ladder():
    for mode, label in (("cursor", "cursor-cli"), ("opencode", "opencode-cli"), ("grok", "grok-cli")):
        assert engine_select.ENGINE_LABELS[mode] == label
        assert mode in engine_select.SUBSCRIPTION_MODES
        assert (mode in engine_select.SCHEDULE_PLAN_MODES) is (mode != "grok"), "Grok reads only when you start one"
        assert mode in engine_select._VALID_PREF_MODES
        assert engine_select.PLAN_ENGINES[label][1] == "subscription"
        assert label not in engine_select.RESERVE_ENGINES
    assert engine_select._AUTO_LADDER == (engine_select.CLAUDE_CONNECTION_ID, engine_select.CODEX_CONNECTION_ID,
                                          CURSOR.connection, OPENCODE.connection)
    assert GROK.connection not in engine_select._AUTO_LADDER


class _Registry:
    def __init__(self, prefs=None, connected=()):
        self._prefs, self._connected = prefs or {}, set(connected)

    def prefs(self):
        return self._prefs

    async def status(self, connection_id, fresh=False):
        from api.models.schemas import ConnectionKind, ConnectionStatus

        return ConnectionStatus(id=connection_id, label=connection_id, kind=ConnectionKind.subscription,
                                available=True, connected=connection_id in self._connected)


def _resolve(prefs, *, user_triggered=True, connected=(), cli_wait=None):
    import asyncio

    from api.config import Settings

    return asyncio.run(engine_select.resolve_settings(Settings(), _Registry(prefs, connected),
                                                      user_triggered=user_triggered, cli_wait=cli_wait))


@pytest.mark.shipped_engine_default
def test_a_chosen_cli_engine_resolves_with_its_models_and_ruling_4_on_schedules():
    prefs = {"sleep-engine": {"mode": "grok", "model": "grok-4.6", "disambiguation_model": "grok-4.6-mini"}}
    resolved, why = _resolve(prefs)
    assert resolved.llm_mode == "grok" and engine_select.engine_label(resolved) == "grok-cli"
    assert cli_engines.model_for_stage(resolved, "extraction") == "grok-4.6"
    assert cli_engines.model_for_stage(resolved, "disambiguation") == "grok-4.6-mini"
    assert engine_select.shown_model(resolved) == "grok-4.6" and engine_select.author_model(resolved) == "grok-4.6"
    assert why == "Sleep engine set to Grok plan in Settings"
    # Scheduled: Grok never (review of #494: user-started only until a live sign-in), said in words.
    resolved, why = _resolve(prefs, user_triggered=False)
    assert engine_select.no_engine(resolved) and why == engine_select.SCHEDULE_USER_ONLY
    assert "only when you start a read" in resolved.no_engine_reason
    # Cursor and OpenCode: through the person's switch (ruling 4b); off means no engine, never a key.
    cursor = {"sleep-engine": {"mode": "cursor", "model": "auto"}}
    resolved, _ = _resolve(cursor, user_triggered=False)
    assert resolved.llm_mode == "cursor"
    resolved, why = _resolve({**cursor, "sleep-run": {"scheduled_use_plan": False}}, user_triggered=False)
    assert engine_select.no_engine(resolved) and why == engine_select.SCHEDULE_DEGRADED


@pytest.fixture
def ladder(stubs, monkeypatch):
    """Auto's tool rungs put back (the suite empties them, conftest) over the stubs. ``only(*names)`` leaves just
    those stub tools installed."""
    monkeypatch.setattr(cli_engines, "AUTO_SPECS", (CURSOR, OPENCODE))

    def only(*names):
        for path in stubs.bindir.iterdir():
            if path.name not in names:
                path.unlink()
        cli_engines.invalidate()

    stubs.only = only
    return stubs


def _status_spawns(stubs):
    return [s["argv"][:1] for s in stubs.spawns() if s["argv"][:1] in (["status"], ["models"])]


@pytest.mark.shipped_engine_default
def test_auto_lands_on_cursor_when_it_is_the_only_one_signed_in_and_says_how_it_bills(ladder):
    ladder.only("agent")
    resolved, why = _resolve({})
    assert resolved.llm_mode == "cursor" and engine_select.engine_label(resolved) == "cursor-cli"
    assert not engine_select.no_engine(resolved)
    assert "Cursor plan" in why and cli_engines.CURSOR_USAGE_NOTE in why
    # The run detail keeps that sentence beside the pre-flight's own line.
    detail = engine_select.run_detail(why, "Signed in to Cursor.")
    assert detail.startswith("Cursor signed in") and "usage-based pricing" in detail and detail.endswith("Cursor.")


@pytest.mark.shipped_engine_default
def test_the_plans_outrank_cursor_and_no_tool_is_read(ladder):
    ladder.only("agent")
    resolved, _ = _resolve({}, connected={engine_select.CLAUDE_CONNECTION_ID})
    assert resolved.llm_mode == "agent"
    resolved, _ = _resolve({}, connected={engine_select.CODEX_CONNECTION_ID})
    assert resolved.llm_mode == "codex"
    assert _status_spawns(ladder) == [], "a plan above the tools answers before any tool is asked"


@pytest.mark.shipped_engine_default
def test_cursor_outranks_opencode(ladder):
    resolved, _ = _resolve({})
    assert resolved.llm_mode == "cursor"


@pytest.mark.shipped_engine_default
def test_auto_lands_on_opencode_with_a_subscription_model(ladder):
    ladder.only("opencode")
    resolved, why = _resolve({})
    assert resolved.llm_mode == "opencode" and "OpenCode plan" in why
    assert not engine_select.no_engine(resolved)


@pytest.mark.shipped_engine_default
def test_opencode_with_only_key_backed_models_is_no_engine_said_in_words(ladder, monkeypatch):
    ladder.only("opencode")
    monkeypatch.setenv("STUB_MODE", "no_plan")
    resolved, why = _resolve({})
    assert engine_select.no_engine(resolved) and why.startswith(engine_select.NO_ENGINE)
    assert resolved.llm_mode == "auto", "never a key"
    assert "OpenCode has no subscription signed in" in resolved.no_engine_reason
    assert "opencode auth login" in resolved.no_engine_reason


@pytest.mark.shipped_engine_default
def test_grok_alone_is_never_autos_engine_and_is_never_asked(ladder):
    ladder.only("grok")
    resolved, why = _resolve({})
    assert engine_select.no_engine(resolved) and why == engine_select.NO_ENGINE
    assert ladder.spawns() == []
    # The named-engine cache read never counts it either.
    cli_engines._CACHE["grok"] = cli_engines.Status(True, True, "Signed in to Grok.", ["grok-4.6"], 9e12)
    assert cli_engines.cached_connected() == set()


@pytest.mark.shipped_engine_default
def test_a_scheduled_run_reaches_cursor_only_through_the_switch(ladder):
    ladder.only("agent")
    resolved, why = _resolve({}, user_triggered=False)
    assert resolved.llm_mode == "cursor" and "Cursor plan" in why
    cli_engines.invalidate()
    before = len(ladder.spawns())
    resolved, why = _resolve({"sleep-run": {"scheduled_use_plan": False}}, user_triggered=False)
    assert engine_select.no_engine(resolved) and why == engine_select.SCHEDULE_DEGRADED
    assert len(ladder.spawns()) == before, "a closed switch never asks the tool"
    # Grok stays out of scheduled runs whatever the switch says (unchanged from #494).
    assert "grok" not in engine_select.SCHEDULE_PLAN_MODES


@pytest.mark.shipped_engine_default
def test_a_hung_tool_is_skipped_in_words_and_the_next_rung_reads(ladder, monkeypatch):
    import time as _time

    monkeypatch.setattr(cli_engines, "PROBE_TIMEOUT_S", 0.5)
    monkeypatch.setattr(cli_engines, "LADDER_WAIT_S", 5.0)
    monkeypatch.setenv("STUB_HANG", "agent")
    started = _time.monotonic()
    resolved, _ = _resolve({})
    assert _time.monotonic() - started < 4.0
    assert resolved.llm_mode == "opencode"
    # Alone, the hung tool leaves no engine, with the reason.
    ladder.only("agent")
    resolved, _ = _resolve({})
    assert engine_select.no_engine(resolved)
    assert "Cursor didn't answer within 0.5 s. Auto skipped it for this run." in resolved.no_engine_reason


@pytest.mark.shipped_engine_default
def test_the_page_never_waits_and_an_unknown_tool_is_skipped(ladder, monkeypatch):
    import time as _time

    ladder.only("agent")
    monkeypatch.setattr(cli_engines, "PROBE_TIMEOUT_S", 3.0)
    monkeypatch.setenv("STUB_HANG", "agent")
    started = _time.monotonic()
    resolved, _ = _resolve({}, cli_wait=0)   # the Sleep page: never waits
    assert _time.monotonic() - started < 1.0
    assert engine_select.no_engine(resolved)
    assert "Cursor's status isn't known yet, so Auto skipped it for this run." in resolved.no_engine_reason


@pytest.mark.shipped_engine_default
def test_the_named_engine_reads_the_tools_cache_and_never_probes(ladder):
    from api.config import Settings

    ladder.only("agent")
    _, expected = engine_select.expected_settings(Settings(), _Registry(), [])
    assert expected.llm_mode == "auto" and ladder.spawns() == []
    cli_engines._CACHE["cursor"] = cli_engines.Status(True, True, "Signed in to Cursor.", ["auto"], 9e12)
    _, expected = engine_select.expected_settings(Settings(), _Registry(), [])
    assert expected.llm_mode == "cursor"
    _, expected = engine_select.expected_settings(Settings(), _Registry(), [engine_select.CODEX_CONNECTION_ID])
    assert expected.llm_mode == "codex"
    assert engine_select.powered_connection_id(Settings(), _Registry(), []) == CURSOR.connection
    assert ladder.spawns() == []


@pytest.mark.shipped_engine_default
def test_an_unpicked_cli_model_is_shown_as_the_tools_default_and_never_guessed():
    resolved, _ = _resolve({"sleep-engine": {"mode": "cursor"}})
    assert engine_select.shown_model(resolved) == "default model"
    assert engine_select.author_model(resolved) == "unknown"


def test_the_seam_records_the_real_engine_model_and_plan(monkeypatch):
    """`providers.resolve_llm_fn` routes a CLI mode through `cli_engines`, and its ledger row carries the engine
    label, the plan's connection, subscription billing and the model the tool reported."""
    from api.config import Settings
    from api.services import agent_engine, providers

    monkeypatch.setattr(cli_engines, "resolve_binary", lambda spec: spec.binaries[0])
    seen: list = []

    def runner(argv, *, stdin, timeout, cwd, env_overrides=None):
        seen.append(argv)
        return base.CliResult(0, json.dumps({"text": "{}", "stopReason": "end_turn",
                                             "modelUsage": {"grok-4.6": {"modelCalls": 1}},
                                             "usage": {"input_tokens": 3, "output_tokens": 1}}), "")

    events: list = []
    agent_engine.reset_models_used()
    fn = providers.resolve_llm_fn(Settings(llm_mode="grok", cli_engine_model="grok-4.6-mini"), stage="extraction",
                                  runner=runner,
                                  sink=events.append, is_async=False, scope="sleep:seam")
    resp = fn(messages=MESSAGES, response_format={"type": "json_object"})
    assert resp["choices"][0]["message"]["content"] == "{}"
    (event,) = [e for e in events if e.kind == "llm_call"]
    assert (event.engine, event.connection, event.billing, event.model) == (
        "grok-cli", "grok-plan", "subscription", "grok-4.6")
    assert event.cost_usd is None
    assert agent_engine.models_used() == ["grok-4.6"]
    assert seen and seen[0][0] == "grok" and seen[0][seen[0].index("-m") + 1] == "grok-4.6-mini"


# --------------------------------------------------------------------------- #
# Review of #494 — MCP stays off, Grok only on built-in models, Cursor's own `agent`, status tokens, a fast picker
# --------------------------------------------------------------------------- #


def test_grok_never_loads_claude_or_cursor_mcp_servers_or_their_config(stubs):
    _call(GROK, model="grok-4.6")
    env = _call_spawn(stubs)["env"]
    for vendor in ("CLAUDE", "CURSOR"):
        for cell in ("MCPS", "HOOKS", "RULES", "SKILLS", "AGENTS"):
            assert env[f"GROK_{vendor}_{cell}_ENABLED"] == "false"
    assert env["GROK_MANAGED_MCPS_ENABLED"] == "false"
    assert env["CICADA_ENGINE_SPAWN"] == "1"


def test_opencode_turns_off_every_mcp_server_the_persons_config_names(stubs, tmp_path, monkeypatch):
    cfg = tmp_path / "xdg" / "opencode"
    cfg.mkdir(parents=True)
    (cfg / "opencode.jsonc").write_text('{\n // mine\n "mcp": {"notes": {"type": "local", "command": ["x"]},\n'
                                        ' "cicada": {"type": "local", "command": ["y"]},},\n}', encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _call(OPENCODE, model="github-copilot/gpt-5.5")
    env = _call_spawn(stubs)["env"]
    content = json.loads(env["OPENCODE_CONFIG_CONTENT"])          # Cicada's own, set after the scrub
    assert content["mcp"] == {"cicada": {"enabled": False}, "notes": {"enabled": False}}
    assert content["permission"] == {"*": "deny"}
    assert env["CICADA_ENGINE_SPAWN"] == "1"


def test_cursor_never_approves_an_mcp_server_and_denies_every_mcp_call(stubs):
    _call(CURSOR, model="auto")
    spawn = _call_spawn(stubs)
    assert "--approve-mcps" not in spawn["argv"]
    assert "Mcp(*:*)" in spawn["cursor_deny"]["permissions"]["deny"]
    assert spawn["env"]["CICADA_ENGINE_SPAWN"] == "1"


def test_cicadas_own_mcp_server_offers_nothing_inside_an_engine_call(monkeypatch):
    """Belt for every tool (Cursor has no run-wide MCP switch, Grok always loads its own config.toml's servers):
    a Cicada server started under the spawn marker answers with no instructions, no tools and no seen row."""
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("cicada_mcp_server_engine_spawn", root / "mcp" / "server.py")
    server = importlib.util.module_from_spec(spec)
    sys.modules["cicada_mcp_server_engine_spawn"] = server
    spec.loader.exec_module(server)
    stamped: list = []
    monkeypatch.setattr(server, "_stamp_seen", lambda *a, **k: stamped.append(a))
    monkeypatch.setenv("CICADA_ENGINE_SPAWN", "1")
    result = server.initialize_result({"clientInfo": {"name": "grok-build"}})
    assert "instructions" not in result and stamped == []
    monkeypatch.delenv("CICADA_ENGINE_SPAWN")
    assert server.in_engine_spawn() is False


def test_a_grok_model_that_is_not_xais_own_is_never_offered_or_called(stubs):
    with pytest.raises(engine_errors.EngineUnavailable) as err:
        _call(GROK, model="my-bedrock-proxy")
    assert "Nothing was read" in str(err.value)
    assert [s for s in stubs.spawns() if s["argv"][:1] not in (["models"],)] == []
    assert cli_engines.model_choices(GROK, cli_engines.probe_now(GROK), None) == ["grok-4.6", "grok-4.6-mini"]


def test_an_agent_binary_that_is_not_cursors_is_never_called(stubs, monkeypatch):
    monkeypatch.setenv("STUB_HELP", "agent — some other tool")
    cli_engines._CURSOR_CHECKED.clear()
    try:
        assert cli_engines.resolve_binary(CURSOR) is None
        with pytest.raises(engine_errors.EngineUnavailable):
            _call(CURSOR, model="auto")
        assert all(s["argv"] == ["--help"] for s in stubs.spawns())
    finally:
        cli_engines._CURSOR_CHECKED.clear()


@pytest.mark.parametrize("stderr,expected", [
    ("connection reset (request id req_4291f, trace 401af)", engine_errors.EngineConnectionLost),
    ("HTTP 429: slow down", engine_errors.EngineThrottled),
    ("status=401", engine_errors.EngineUnavailable),
])
def test_a_status_code_counts_only_as_its_own_token(stderr, expected):
    result = base.CliResult(1, "", stderr)
    with pytest.raises(expected):
        cli_engines.check(CURSOR, result, cli_engines.ExecResult())


def test_the_picker_serves_the_last_known_state_while_a_refresh_runs(monkeypatch):
    import threading
    import time as _time

    calls: list = []
    release = threading.Event()

    def slow_probe(spec, runner=None, timeout=0):
        calls.append(spec.mode)
        release.wait(5)
        return cli_engines.Status(True, True, "fresh", ["auto"], _time.time())

    cli_engines.invalidate()
    monkeypatch.setattr(cli_engines, "probe_now", slow_probe)
    old = cli_engines.Status(True, False, "old", [], _time.time() - 999)
    with cli_engines._CACHE_LOCK:
        cli_engines._CACHE["cursor"] = old
    started = _time.monotonic()
    assert cli_engines.status(CURSOR, stale_ok=True) is old          # served at once
    assert cli_engines.status(CURSOR, stale_ok=True) is old          # one refresh, not two
    assert _time.monotonic() - started < 1.0
    release.set()
    for _ in range(50):
        if cli_engines._CACHE["cursor"].detail == "fresh":
            break
        _time.sleep(0.05)
    assert cli_engines._CACHE["cursor"].detail == "fresh" and calls == ["cursor"]
    cli_engines.invalidate()


# --------------------------------------------------------------------------- #
# Ruling 46a (owner 2026-10-28): Auto and schedules use Cursor only with Cursor's own models
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model, own", [
    ("auto", True), ("composer-2", True), ("grok-4.7", True), ("grok-4.6-fast", True), ("cursor-small", True),
    ("sonnet-5", False), ("claude-opus-5-5", False), ("gpt-6", False), ("gemini-3-pro", False), ("", False),
])
def test_cursors_own_models(model, own):
    assert cli_engines.cursor_own_model(model) is own


@pytest.mark.shipped_engine_default
def test_auto_on_cursor_runs_its_own_auto_never_the_tools_config_default(ladder):
    ladder.only("agent")
    resolved, why = _resolve({})
    assert resolved.llm_mode == "cursor"
    assert cli_engines.model_for_stage(resolved, None) == "auto", "never the tool's own config default"
    assert cli_engines.model_for_stage(resolved, "disambiguation") == "auto"
    assert "Cursor's own models" in why


@pytest.mark.shipped_engine_default
def test_auto_never_carries_a_third_party_model_onto_cursor(ladder, monkeypatch):
    ladder.only("agent")
    from api.config import Settings

    monkeypatch.setattr(Settings, "model_copy", Settings.model_copy)
    import asyncio

    base = Settings().model_copy(update={"cli_engine_model": "sonnet-5"})
    resolved, _ = asyncio.run(engine_select.resolve_settings(base, _Registry({}, ())))
    assert resolved.llm_mode == "cursor" and cli_engines.model_for_stage(resolved, None) == "auto"


def test_a_person_who_chose_cursor_keeps_any_model_they_start_a_read_with():
    prefs = {"sleep-engine": {"mode": "cursor", "model": "sonnet-5"}}
    resolved, _ = _resolve(prefs)
    assert resolved.llm_mode == "cursor" and cli_engines.model_for_stage(resolved, None) == "sonnet-5"


def test_a_schedule_never_reads_cursor_on_a_third_party_model_and_says_so():
    prefs = {"sleep-engine": {"mode": "cursor", "model": "sonnet-5"}}
    resolved, why = _resolve(prefs, user_triggered=False)
    assert engine_select.no_engine(resolved), "never swapped onto another model either"
    assert why == engine_select.SCHEDULE_CURSOR_THIRD_PARTY
    assert "billed separately at list price" in resolved.no_engine_reason


def test_a_schedule_on_cursors_own_model_reads():
    for model in ("grok-4.7", "composer-2", None):
        prefs = {"sleep-engine": {"mode": "cursor", "model": model}}
        resolved, _ = _resolve(prefs, user_triggered=False)
        assert resolved.llm_mode == "cursor"
        assert cli_engines.model_for_stage(resolved, None) == (model or "auto")


def _resolve_pinned(fields: dict, *, user_triggered: bool):
    """`CICADA_LLM_MODE` (and its model) set in the environment — a headless server's .env: explicit fields."""
    import asyncio

    from api.config import Settings

    return asyncio.run(engine_select.resolve_settings(Settings(**fields), _Registry({}, ()),
                                                      user_triggered=user_triggered))


@pytest.mark.shipped_engine_default
@pytest.mark.parametrize("user_triggered", [True, False])
@pytest.mark.parametrize("model", ["sonnet-5", ""])
def test_a_pinned_auto_landing_on_cursor_still_runs_its_own_models(ladder, user_triggered, model):
    """Review of #507: ruling 46a holds when the mode is pinned in the environment, not only when chosen in the app."""
    ladder.only("agent")
    resolved, _ = _resolve_pinned({"llm_mode": "auto", "cli_engine_model": model}, user_triggered=user_triggered)
    assert resolved.llm_mode == "cursor"
    assert cli_engines.model_for_stage(resolved, None) == "auto"
    assert cli_engines.model_for_stage(resolved, "disambiguation") == "auto"


def test_a_pinned_cursor_on_a_third_party_model_reads_when_started_and_never_on_a_schedule():
    """The operator's `CICADA_LLM_MODE=cursor` is an explicit choice: a run the person starts keeps the pinned model;
    a scheduled run on a third-party one has no engine and says why — never swapped."""
    pinned = {"llm_mode": "cursor", "cli_engine_model": "sonnet-5"}
    started, _ = _resolve_pinned(pinned, user_triggered=True)
    assert started.llm_mode == "cursor" and cli_engines.model_for_stage(started, None) == "sonnet-5"
    scheduled, why = _resolve_pinned(pinned, user_triggered=False)
    assert engine_select.no_engine(scheduled) and why == engine_select.SCHEDULE_CURSOR_THIRD_PARTY
    assert "billed separately at list price" in scheduled.no_engine_reason


def test_a_pinned_cursor_with_no_model_or_its_own_runs_on_a_schedule():
    for model, runs in (("", "auto"), ("grok-4.7", "grok-4.7")):
        resolved, _ = _resolve_pinned({"llm_mode": "cursor", "cli_engine_model": model}, user_triggered=False)
        assert resolved.llm_mode == "cursor" and cli_engines.model_for_stage(resolved, None) == runs


def test_grok_stays_off_auto():
    """Ruling 46a keeps ruling 46's exclusion: the shipped ladder (read from the source — the suite empties it) and
    the connection ladder name Cursor and OpenCode, never Grok."""
    import inspect

    source = inspect.getsource(cli_engines)
    assert "AUTO_SPECS: tuple[EngineSpec, ...] = (CURSOR, OPENCODE)" in source
    assert "grok-plan" not in engine_select._AUTO_LADDER
