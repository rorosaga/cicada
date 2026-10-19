"""The owner's decisions after headless QA and the hunts (2026-10-16): plans on a server (ruling 4b), a schedule with no
engine says so, `/healthz` says no path without a token, and the backend hunt's fixes. Synthetic banks, fake engines,
a fake `claude` binary — never a real login, never a real bank, never port 8000."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import stat
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.config import Settings
from api.models.schemas import ConnectionKind, ConnectionStatus
from api.services import engine_readiness, engine_select, sleep_paused, sleep_run_prefs
from test_cli_app import TOKEN, _backend, _template, env  # noqa: F401 — the CLI's fake backend and its fixture


#: The shipped engine default (auto since 2026-10-19), not the suite's chosen key (conftest).
pytestmark = pytest.mark.shipped_engine_default


class _Registry:
    """Prefs in memory and a connected set; ``status`` answers like a probe that already ran."""

    def __init__(self, *, prefs=None, connected=()):
        self._prefs = prefs or {}
        self._connected = set(connected)

    def prefs(self):
        return self._prefs

    def set_pref(self, connection_id, key, value):
        entry = self._prefs.setdefault(connection_id, {})
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value

    async def status(self, connection_id, fresh=False):
        return ConnectionStatus(id=connection_id, label=connection_id, kind=ConnectionKind.subscription,
                                available=True, connected=connection_id in self._connected)


def _scheduled(settings, registry):
    return asyncio.run(engine_select.resolve_llm_mode(settings, registry, user_triggered=False))


def _switch(on: bool) -> dict:
    """The person's explicit choice; unset is ON since 2026-10-19 (ruling 4b amended)."""
    return {sleep_run_prefs.PREF_KEY: {"scheduled_use_plan": bool(on)}}


@pytest.fixture(autouse=True)
def _plan_probe(monkeypatch):
    """The Claude plan's cheap probe answers from the fake registry's connected set, never a CLI spawn."""
    async def probe(registry, *, timeout=5.0):
        status = await registry.status(engine_select.CLAUDE_CONNECTION_ID)
        return bool(status.connected), ""

    monkeypatch.setattr(engine_select, "probe_claude_cheaply", probe)


# --- ruling 4b: the switch is the guard's one door -----------------------------------------------------------------

def test_with_the_switch_off_a_scheduled_run_never_uses_a_plan_chosen_in_settings():
    reg = _Registry(prefs={"sleep-engine": {"mode": "agent"}, **_switch(False)}, connected={"claude-plan"})
    mode, why = _scheduled(Settings(), reg)
    # 2026-10-19: and never the metered key by itself — no engine.
    assert mode == "auto" and "user-triggered only" in why


def test_the_switch_is_on_by_default_and_an_explicit_off_stays_off():
    """Owner 2026-10-19: "Make scheduled runs run on the plan by default." An explicit off stays off."""
    never_set = _Registry(prefs={"sleep-engine": {"mode": "agent"}}, connected={"claude-plan"})
    assert engine_select.scheduled_plan_allowed(never_set)
    assert _scheduled(Settings(), never_set)[0] == "agent"
    assert _scheduled(Settings(), _Registry(connected={"claude-plan"}))[0] == "agent", "the default install too"
    turned_off = _Registry(prefs={"sleep-engine": {"mode": "agent"}, **_switch(False)}, connected={"claude-plan"})
    assert not engine_select.scheduled_plan_allowed(turned_off)
    reg = _Registry()
    sleep_run_prefs.write(reg, scheduled_use_plan=False)
    assert reg.prefs()["sleep-run"]["scheduled_use_plan"] is False, "an off is stored, so it outlives the default"
    assert not sleep_run_prefs.load(reg).scheduled_use_plan


def test_with_the_switch_a_scheduled_run_uses_the_claude_plan_chosen_in_settings():
    reg = _Registry(prefs={"sleep-engine": {"mode": "agent"}, **_switch(True)}, connected={"claude-plan"})
    mode, why = _scheduled(Settings(), reg)
    assert mode == "agent" and "scheduled runs may use your plan" in why.lower()


def test_the_switch_opens_the_chatgpt_plan_too_and_only_through_itself(monkeypatch):
    """Owner, 2026-10-16: "Yeah chat too"."""
    async def codex_probe(registry, *, timeout=5.0):
        status = await registry.status(engine_select.CODEX_CONNECTION_ID)
        return bool(status.connected), ""

    monkeypatch.setattr(engine_select, "probe_codex_cheaply", codex_probe)
    off = _Registry(prefs={"sleep-engine": {"mode": "codex"}, **_switch(False)}, connected={"chatgpt-plan"})
    assert _scheduled(Settings(), off)[0] == "auto"
    on = _Registry(prefs={"sleep-engine": {"mode": "codex"}, **_switch(True)}, connected={"chatgpt-plan"})
    assert _scheduled(Settings(), on)[0] == "codex"
    auto = _Registry(prefs={"sleep-engine": {"mode": "auto"}, **_switch(True)}, connected={"chatgpt-plan"})
    assert _scheduled(Settings(), auto)[0] == "codex", "auto on a schedule reaches the ChatGPT rung through the switch"
    auto_off = _Registry(prefs={"sleep-engine": {"mode": "auto"}, **_switch(False)}, connected={"chatgpt-plan"})
    assert _scheduled(Settings(), auto_off)[0] == "auto"


def test_with_the_switch_the_use_for_sleep_toggle_and_auto_reach_the_plan_on_a_schedule():
    toggle = _Registry(prefs={"claude-plan": {"use_for_sleep": True}, **_switch(True)}, connected={"claude-plan"})
    assert _scheduled(Settings(llm_mode="byok"), toggle)[0] == "agent"
    auto = _Registry(prefs={"sleep-engine": {"mode": "auto"}, **_switch(True)}, connected={"claude-plan"})
    assert _scheduled(Settings(), auto)[0] == "agent"
    signed_out = _Registry(prefs={"sleep-engine": {"mode": "auto"}, **_switch(True)})
    assert _scheduled(Settings(), signed_out)[0] == "auto", "no plan signed in: no engine, never the key by itself"


def test_the_switch_is_stored_beside_the_reading_options_and_reads_off_when_corrupt():
    reg = _Registry()
    assert engine_select.scheduled_plan_allowed(reg), "on by default (2026-10-19)"
    sleep_run_prefs.write(reg, scheduled_use_plan=True)
    assert engine_select.scheduled_plan_allowed(reg) and sleep_run_prefs.load(reg).scheduled_use_plan
    sleep_run_prefs.write(reg, scheduled_use_plan=False)
    assert not engine_select.scheduled_plan_allowed(reg)
    assert not engine_select.scheduled_plan_allowed(_Registry(prefs={"sleep-run": {"scheduled_use_plan": "yes"}}))
    assert engine_select.scheduled_plan_allowed(None), "no prefs to read: the default"


def test_a_scheduled_plan_run_drains_and_the_dotfile_pin_still_reads_one_batch():
    from api.services import sleep_scheduler

    assert sleep_scheduler._scheduled_drain(Settings()) is True
    assert sleep_scheduler._scheduled_drain(Settings(llm_mode="agent")) is False


@pytest.mark.parametrize("reason,resets_in,age_h,replaced", [
    ("plan_window", -60, 0, True),     # the window has reset: the next scheduled run reads afresh
    ("plan_window", 3600, 0, False),   # not yet: a fresh run would only stop on its first call
    ("plan_weekly", 3600 * 24, 48, False),
    ("plan_weekly", -1, 0, True),
    ("plan_window", None, 7, True),    # no reset time given: after ENGINE_RETRY_S
    ("overage", -60, 48, False),       # extra usage stays the person's
])
def test_a_scheduled_plan_pause_is_replaced_only_after_its_limit_resets(reason, resets_in, age_h, replaced):
    now = time.time()
    rec = {"phase": "paused", "started_by": "schedule", "reason": reason,
           "resets_at": int(now + resets_in) if resets_in is not None else None,
           "paused_at_ts": int(now - age_h * 3600)}
    assert sleep_paused.schedule_may_replace(rec, now=now) is replaced
    assert sleep_paused.schedule_may_replace({**rec, "started_by": "user"}, now=now) is False


def test_the_web_lookup_follows_the_switch_on_a_schedule(monkeypatch):
    from api.services import web_lookup

    resolved = Settings(llm_mode="agent")

    async def resolve(settings, registry=None, *, user_triggered=True):
        return resolved, "pinned"

    monkeypatch.setattr(engine_select, "resolve_settings", resolve)
    monkeypatch.setattr(web_lookup, "_registry", lambda settings: _Registry(prefs=_switch(False)))
    assert asyncio.run(web_lookup.engine_for(Settings(), user_triggered=False))[2] == "scheduled_plan"
    monkeypatch.setattr(web_lookup, "_registry", lambda settings: _Registry())
    assert asyncio.run(web_lookup.engine_for(Settings(), user_triggered=False))[2] == "plan", "on by default"
    monkeypatch.setattr(web_lookup, "_registry", lambda settings: _Registry(prefs=_switch(True)))
    assert asyncio.run(web_lookup.engine_for(Settings(), user_triggered=False))[2] == "plan"


def test_a_plan_token_from_setup_token_reads_as_a_signed_in_plan():
    from api.services.connections import claude_cli
    from api.services.connections.base import CliResult

    async def runner(argv):
        return CliResult(0, json.dumps({"loggedIn": True, "authMethod": "oauth_token"}), "")

    adapter = claude_cli.ClaudePlanAdapter(runner=runner)
    monkey_available = adapter.available
    adapter.available = lambda: True
    try:
        status = asyncio.run(adapter.status())
    finally:
        adapter.available = monkey_available
    assert status.connected is True


# --- owner decision 2: a schedule with no engine it may use says so ------------------------------------------------

@pytest.fixture
def server(tmp_path, monkeypatch):
    """A backend on a scratch bank, auth off, no provider key in the environment."""
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "CICADA_LLM_MODE"):
        monkeypatch.delenv(key, raising=False)
    config.get_settings.cache_clear()
    from api.services.connections import registry as registry_module

    reg = _Registry()
    monkeypatch.setattr(registry_module, "get_registry", lambda settings=None: reg)
    import api.routers.sleep as sleep_router

    monkeypatch.setattr(sleep_router, "get_registry", lambda settings=None: reg)
    with TestClient(main.app) as client:
        yield client, reg, memory
    config.get_settings.cache_clear()


def test_turning_the_schedule_on_with_no_engine_warns_and_offers_the_plan_first(server, monkeypatch):
    client, reg, _ = server
    off = client.put("/sleep/schedule", json={"mode": "manual"}).json()
    assert off.get("warning") is None, "a schedule that never runs needs no engine"
    on = client.put("/sleep/schedule", json={"mode": "daily", "hour": 4, "minute": 0}).json()
    assert on["warningCode"] == engine_readiness.NO_ENGINE and "no engine" in on["warning"]
    fix = engine_readiness.Problem(on["warningCode"], on["warning"]).with_cli_fix()
    assert fix.index("claude-plan") < fix.index("--mode byok"), "connecting the Claude plan is offered first"
    assert client.get("/sleep/schedule").json()["warningCode"] == engine_readiness.NO_ENGINE
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    assert client.get("/sleep/schedule").json()["warningCode"] == engine_readiness.NO_ENGINE, \
        "a key alone is no engine: it reads only when the person chooses it (2026-10-19)"
    reg.set_pref("sleep-engine", "mode", "byok")
    assert client.get("/sleep/schedule").json().get("warning") is None


def test_the_switch_round_trips_through_the_reading_options_route(server):
    client, reg, _ = server
    assert client.get("/sleep/run-options").json()["scheduledUsePlan"] is True, "on by default (2026-10-19)"
    assert client.put("/sleep/run-options", json={"scheduledUsePlan": False}).json()["scheduledUsePlan"] is False
    assert reg.prefs()["sleep-run"]["scheduled_use_plan"] is False
    assert client.get("/sleep/run-options").json()["scheduledUsePlan"] is False, "an explicit off stays off"
    assert client.put("/sleep/run-options", json={"scheduledUsePlan": True}).json()["scheduledUsePlan"] is True
    assert reg.prefs()["sleep-run"]["scheduled_use_plan"] is True
    assert client.put("/sleep/run-options", json={"scheduledUsePlan": None}).status_code == 422


def test_a_signed_out_plan_or_an_unchosen_one_is_named(server):
    client, reg, _ = server
    reg.set_pref("sleep-run", "scheduled_use_plan", True)
    reg.set_pref("sleep-engine", "mode", "agent")
    body = client.put("/sleep/schedule", json={"mode": "daily", "hour": 4, "minute": 0}).json()
    assert body["warningCode"] == engine_readiness.PLAN_SIGNED_OUT
    reg._connected.add("claude-plan")
    assert client.get("/sleep/schedule").json().get("warning") is None
    reg.set_pref("sleep-engine", "mode", "byok")
    assert client.get("/sleep/schedule").json()["warningCode"] == engine_readiness.PLAN_NOT_CHOSEN
    reg.set_pref("sleep-engine", "mode", None)
    assert client.get("/sleep/schedule").json().get("warning") is None, "the default (Auto) reads with the plan"


def test_ask_with_no_engine_says_so_and_spends_nothing(tmp_path, monkeypatch):
    from api.services import ask_service

    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CICADA_LLM_MODE"):
        monkeypatch.delenv(key, raising=False)
    config.get_settings.cache_clear()
    memory = _bank(tmp_path)

    def retrieve(query, k):
        return []      # the substring fallback finds the page by its name

    def boom(prompt):
        raise AssertionError("a keyless call was made")

    result = ask_service.answer_query(memory, "Alpha Project", retrieve_fn=retrieve, no_engine=True, llm_fn=boom)
    assert "no engine" in result["answer"] and "claude-plan" in result["answer"]
    assert "Alpha" in result["answer"] or "alpha" in result["answer"], "the pages it found are still named"
    keyless = ask_service.answer_query(memory, "Alpha Project", retrieve_fn=retrieve)
    assert "no engine" in keyless["answer"], "with no llm_fn and no key, the environment's engine is checked"


# --- owner decision 3: /healthz says no path without a token ------------------------------------------------------

def test_healthz_without_a_token_says_only_ok_ids_and_version(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.setenv("CICADA_API_TOKEN", TOKEN)
    config.get_settings.cache_clear()
    with TestClient(main.app) as client:
        open_body = client.get("/healthz").json()
        wrong = client.get("/healthz", headers={"Authorization": "Bearer nope"}).json()
        full = client.get("/healthz", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    config.get_settings.cache_clear()
    assert set(open_body) <= {"status", "version", "bankId", "bankIds"} and open_body["status"] == "ok"
    assert "version" in open_body and isinstance(open_body.get("bankIds"), list)
    assert str(memory) not in json.dumps(open_body) and str(tmp_path) not in json.dumps(open_body)
    assert set(wrong) == set(open_body)
    assert full["memoryRoot"] == str(memory) and full["memoryPath"] == str(memory) and "entityCount" in full


def test_the_cli_names_its_token_when_it_asks_healthz_for_the_root(env, monkeypatch, capsys):  # noqa: F811
    from api import cli_app

    with _backend(env, monkeypatch) as server:
        import urllib.request

        seen = {}
        real = urllib.request.OpenerDirector.open

        def spy(self, req, *a, **kw):
            if hasattr(req, "full_url") and req.full_url.endswith("/healthz"):
                seen["auth"] = req.headers.get("Authorization")
            return real(self, req, *a, **kw)

        monkeypatch.setattr(urllib.request.OpenerDirector, "open", spy)
        url = f"http://127.0.0.1:{server.server_address[1]}"
        probe = cli_app.probe_backend(url, os.path.realpath(env), 2.0)
    assert probe["state"] == "confirmed" and seen["auth"] == f"Bearer {TOKEN}"


# --- the CLI: the switch, readiness in words, the plan's own sign-in -----------------------------------------------

def _cli(argv, capsys):
    from api import cli

    code = cli.main([*argv, "--json"])
    out = capsys.readouterr()
    return code, json.loads(out.out), out.err


def test_use_plan_on_says_once_that_nightly_runs_count_against_the_plan(env, monkeypatch, capsys):  # noqa: F811
    routes = {("GET", "/sleep/schedule"): (200, {"mode": "daily", "hour": 3, "minute": 0}),
              ("PUT", "/sleep/run-options"): (200, {"scheduledUsePlan": True, "batchSize": 25})}
    with _backend(env, monkeypatch, routes) as server:
        code, out, _ = _cli(["sleep", "schedule", "--use-plan", "on"], capsys)
    assert code == 0, out
    assert "count against your plan's limits" in out["text"] and out["data"]["scheduledUsePlan"] is True
    sent = [r for r in server.seen if r["method"] == "PUT"]
    assert [r["path"] for r in sent] == ["/sleep/run-options"]
    assert json.loads(sent[0]["body"]) == {"scheduledUsePlan": True}


def test_turning_the_schedule_on_prints_the_servers_warning_with_the_cli_fix(env, monkeypatch, capsys):  # noqa: F811
    warned = {"mode": "daily", "hour": 4, "minute": 0, "warning": "Scheduled runs have no engine they may use here.",
              "warningCode": "no_engine"}
    routes = {("GET", "/sleep/schedule"): (200, {"mode": "manual", "hour": 3, "minute": 0}),
              ("PUT", "/sleep/schedule"): (200, warned)}
    with _backend(env, monkeypatch, routes):
        code, out, _ = _cli(["sleep", "schedule", "--at", "04:00"], capsys)
    assert code == 0 and "Warning: Scheduled runs have no engine" in out["text"]
    assert "cicada engine connect claude-plan" in out["text"]


def test_engine_list_says_no_key_and_whether_scheduled_runs_may_use_the_plan(env, monkeypatch, capsys):  # noqa: F811
    routes = {
        ("GET", "/connections"): (200, {"connections": [
            {"id": "byok-openai", "label": "OpenAI API key", "billing": "usage", "available": True},
            {"id": "claude-plan", "label": "Claude plan", "billing": "subscription", "available": True,
             "connected": True, "planLabel": "Max"},
            {"id": "chatgpt-plan", "label": "ChatGPT plan", "billing": "subscription", "available": False},
            {"id": "ollama-local", "label": "Ollama", "billing": "free", "available": True}]}),
        ("GET", "/sleep/engine"): (200, {"preview": {"manual": {"engine": "claude-cli", "model": "haiku"},
                                                     "scheduled": {"engine": "litellm", "model": "gpt-5.4-mini"}}}),
        ("GET", "/sleep/run-options"): (200, {"scheduledUsePlan": False}),
        ("GET", "/sleep/schedule"): (200, {"mode": "daily", "warning": "Scheduled runs have no engine they may "
                                                                      "use here.", "warningCode": "no_engine"}),
    }
    with _backend(env, monkeypatch, routes):
        code, out, _ = _cli(["engine", "list"], capsys)
    text = out["text"]
    assert code == 0
    assert "byok-openai  OpenAI API key  no key" in text and "available" not in text
    assert "claude-plan  Claude plan  signed in (Max)" in text and "chatgpt-plan  ChatGPT plan  not installed" in text
    assert "ollama-local  Ollama  not running" in text
    assert "Scheduled Sleep: litellm · gpt-5.4-mini" in text and "--use-plan on" in text
    assert "Warning: Scheduled runs have no engine" in text and out["data"]["scheduleWarning"] == "no_engine"


def _fake_claude(tmp_path: Path, *, signed_in: bool) -> Path:
    """A `claude` that answers only `auth status --json` and `auth login --claudeai` (Claude Code 2.1's own flags),
    from a state file — never a real login, never a network call."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    state = tmp_path / "claude-state"
    state.write_text("in" if signed_in else "out")
    log = tmp_path / "claude-calls"
    script = bindir / "claude"
    script.write_text(f"""#!/bin/sh
echo "$*" >> '{log}'
if [ "$1 $2 $3" = "auth status --json" ]; then
  if [ "$(cat '{state}')" = in ]; then echo '{{"loggedIn": true, "authMethod": "claude.ai"}}'; exit 0; fi
  echo '{{"loggedIn": false, "authMethod": "none"}}'; exit 1
fi
if [ "$1 $2 $3" = "auth login --claudeai" ]; then echo in > '{state}'; exit 0; fi
exit 2
""")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return bindir


def test_engine_connect_runs_claude_codes_own_sign_in_and_never_handles_the_token(env, monkeypatch, capsys,  # noqa: F811
                                                                                  tmp_path):
    from api import cli_app

    bindir = _fake_claude(tmp_path, signed_in=False)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-reach-the-child")
    monkeypatch.setattr(cli_app, "_interactive", lambda: True)
    routes = {("GET", "/connections/claude-plan"): (200, {"id": "claude-plan", "connected": True, "plan": "max"})}
    from api import cli

    with _backend(env, monkeypatch, routes):
        code = cli.main(["engine", "connect", "claude-plan"])      # a terminal, never --json: the prompts are seen
        captured = capsys.readouterr()
    assert code == 0, captured
    assert "signed in on this machine" in captured.out and "--use-plan on" in captured.out
    assert "--mode agent" in captured.out
    assert "Cicada never sees or stores the token" in captured.err
    calls = (tmp_path / "claude-calls").read_text().splitlines()
    assert "auth login --claudeai" in calls and calls[0] == "auth status --json"
    assert not (Path(os.environ["CICADA_HOME"]) / "secrets.env").exists() if os.environ.get("CICADA_HOME") else True


def test_engine_connect_refuses_without_a_terminal_and_on_a_client(env, monkeypatch, capsys, tmp_path):  # noqa: F811
    from api import cli_app

    bindir = _fake_claude(tmp_path, signed_in=False)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(cli_app, "_interactive", lambda: False)
    from api import cli

    with _backend(env, monkeypatch):
        code = cli.main(["engine", "connect", "claude-plan"])
        said = "".join(capsys.readouterr())
        json_code, out, _ = _cli(["engine", "connect", "claude-plan"], capsys)
    assert code != 0 and "your own terminal" in said and "setup-token" in said
    assert json_code != 0 and "--json would hide" in out["text"]
    assert "auth login" not in (tmp_path / "claude-calls").read_text()


def test_sleep_status_says_the_running_stage_once():
    from api import cli_app

    assert cli_app._stage_line({"stage": 4, "totalStages": 5, "progress": "Stage 5/5: Writing changes..."}) \
        == "stage 5 of 5: Writing changes..."
    assert cli_app._stage_line({"stage": 0, "totalStages": 5, "progress": "Reading batch 2"}) \
        == "stage 1 of 5: Reading batch 2"


def test_a_second_device_with_the_same_name_is_warned_about(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(_bank(tmp_path)))
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.setenv("CICADA_API_TOKEN", TOKEN)
    config.get_settings.cache_clear()
    with TestClient(main.app) as client:
        auth = {"Authorization": f"Bearer {TOKEN}"}
        first = client.post("/devices", json={"name": "laptop"}, headers=auth).json()
        second = client.post("/devices", json={"name": " Laptop "}, headers=auth).json()
    config.get_settings.cache_clear()
    assert first["sameName"] == [] and second["sameName"] == [first["device"]["id"]]


# --- the backend hunt: bounds before parsing ------------------------------------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    with TestClient(main.app) as client:
        yield client
    config.get_settings.cache_clear()


@pytest.mark.parametrize("path", ["/entities/{x}", "/entities/{x}/history", "/projects/{x}", "/backlog/{x}/item"])
def test_a_name_longer_than_any_file_is_a_404_never_a_500(api, path):
    answer = api.get(path.replace("{x}", "a" * 3000))
    assert answer.status_code == 404 and "longer than any file name" in answer.json()["detail"]


def test_a_session_body_past_its_ceiling_is_refused_before_it_is_parsed(api, monkeypatch):
    from api.services import request_limits

    monkeypatch.setitem(request_limits.BODY_LIMITS, "/capture/session", 1024)
    big = {"harness": "claude-code", "session_id": "s", "conversation": {"kept": ["x" * 4096]},
           "transcript_bytes": 1, "transcript_size": 1}
    assert api.post("/capture/session", json=big).status_code == 413

    def chunks():
        yield b'{"harness": "claude-code", "session_id": "s", "conversation": {"kept": ["'
        for _ in range(8):
            yield b"x" * 512
        yield b'"]}, "transcript_bytes": 1, "transcript_size": 1}'

    streamed = api.post("/capture/session", content=chunks(), headers={"Content-Type": "application/json"})
    assert streamed.status_code == 413


def test_a_photo_too_long_to_be_256_kb_is_refused_before_it_is_decoded(monkeypatch):
    from api.services import messages_photos

    def no_decode(*a, **kw):
        raise AssertionError("decoded before the bound")

    monkeypatch.setattr(messages_photos.base64, "b64decode", no_decode)
    with pytest.raises(messages_photos.PayloadError):
        messages_photos._decode("A" * (messages_photos.B64_MAX + 4))


# --- the backend hunt: the client side ------------------------------------------------------------------------------

def test_one_stuck_session_never_blocks_the_turns_behind_it(tmp_path):
    from api.hooks import hook_spool

    hook_spool.put(tmp_path, "/capture/session", {"session_id": "stuck"}, key="claude-code:stuck")
    time.sleep(0.01)
    hook_spool.put(tmp_path, "/capture/turn", {"turn": 1})
    time.sleep(0.01)
    hook_spool.put(tmp_path, "/capture/turn", {"turn": 2})
    sent = []

    def send(route, body):
        if route == "/capture/session":
            return 503
        sent.append(body["turn"])
        return 200

    result = hook_spool.flush(tmp_path, send, deadline=time.monotonic() + 30, keep=lambda s: s is None or s >= 500
                              or s in (401, 403, 409), size_of=lambda p, n: n)
    assert sent == [1, 2] and result == (2, 0, 1), "the session waits, kept; the turns go"


def test_a_stuck_turn_holds_the_turns_behind_it_and_an_away_server_stops_the_flush(tmp_path):
    from api.hooks import hook_spool

    for n in (1, 2):
        hook_spool.put(tmp_path, "/capture/turn", {"turn": n})
        time.sleep(0.01)
    tried = []

    def stuck(route, body):
        tried.append(body["turn"])
        return 503

    keep = lambda s: s is None or s >= 500 or s in (401, 403, 409)  # noqa: E731
    assert hook_spool.flush(tmp_path, stuck, deadline=time.monotonic() + 30, keep=keep,
                            size_of=lambda p, n: n)[2] == 2
    assert tried == [1], "turn order holds: turn 2 is never sent ahead of turn 1"
    tried.clear()
    hook_spool.flush(tmp_path, lambda r, b: tried.append(b) or None, deadline=time.monotonic() + 30, keep=keep,
                     size_of=lambda p, n: n)
    assert len(tried) == 1, "no answer at all: the server is away, the flush stops"


def test_a_timed_out_write_says_it_may_have_written(monkeypatch):
    from api.services import tool_client

    assert tool_client._no_answer_text("cicada_save_episode", socket.timeout()) == tool_client.TIMED_OUT_WRITE_TEXT
    assert tool_client._no_answer_text("cicada_recall", socket.timeout()) == tool_client.TIMED_OUT_READ_TEXT
    import urllib.error

    refused = urllib.error.URLError(ConnectionRefusedError())
    assert tool_client._no_answer_text("cicada_save_episode", refused) == tool_client.NOT_REACHED_TEXT


# --- the backend hunt: watch history, agent commits, Watch later ----------------------------------------------------

@pytest.fixture
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _watch(at):
    from api.services import watch_history

    return watch_history.make("https://www.youtube.com/watch?v=aaaaaaaaaaa", at=at, title="Bridge design",
                              channel="alice-example", door="chrome")


def _times(memory: Path) -> list[str]:
    from api.services import markdown_parser

    for path in (memory / "episodes").glob("*.md"):
        fm = markdown_parser.parse(path).frontmatter
        if str(fm.get("source_id", "")).startswith("watch-history:"):
            return fm["watched"][0]["times"]
    return []


def test_watch_times_are_the_same_whatever_order_the_doors_arrive_in(tmp_path, utc):
    from api.services import watch_history

    chrome = [_watch("2026-10-14T10:20Z"), _watch("2026-10-14T10:40Z")]
    takeout = [_watch("2026-10-14T10:00Z")]
    one = _bank(tmp_path / "a")
    watch_history.record(one, chrome)
    watch_history.record(one, takeout)
    resent = watch_history.record(one, chrome)
    assert resent.added == 0, "an idle re-read adds no phantom re-watch"
    two = _bank(tmp_path / "b")
    watch_history.record(two, chrome + takeout)
    three = _bank(tmp_path / "c")
    watch_history.record(three, takeout)
    watch_history.record(three, chrome)
    assert _times(one) == _times(two) == _times(three) == ["2026-10-14T10:00:00+00:00", "2026-10-14T10:40:00+00:00"]


def test_a_raw_instant_on_an_unchanged_day_is_kept_in_its_frontmatter(tmp_path, utc):
    from api.services import markdown_parser, watch_history

    memory = _bank(tmp_path)
    watch_history.record(memory, [_watch("2026-10-14T10:00Z")])
    quiet = watch_history.record(memory, [_watch("2026-10-14T10:25Z")])   # inside the 30 minutes: same watch
    assert quiet.days_unchanged == 1 and len(quiet.paths) == 1
    later = watch_history.record(memory, [_watch("2026-10-14T09:50Z")])
    assert later.added == 1 and _times(memory) == ["2026-10-14T09:50:00+00:00", "2026-10-14T10:25:00+00:00"]
    day = next(p for p in (memory / "episodes").glob("*.md")
               if str(markdown_parser.parse(p).frontmatter.get("source_id", "")).startswith("watch-history:"))
    assert len(markdown_parser.parse(day).frontmatter["watched"][0]["seen"]) == 3


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], capture_output=True, text=True, check=True).stdout


def test_an_agent_write_keeps_someone_elses_uncommitted_edit_apart(tmp_path):
    from api.services import agent_commits

    memory = _bank(tmp_path, git=True)
    page = memory / "entities" / "alpha-project.md"
    page.write_text(page.read_text() + "\nThe person's own uncommitted line.\n")
    with agent_commits.setting_apart(memory):
        page.write_text(page.read_text() + "\nThe agent's line.\n")
        assert agent_commits.commit_write(memory, subject="Agent write", lines=["entities/alpha-project.md: updated"],
                                          paths=["entities/alpha-project.md"], author="claude-code", session=None)
    log = _git(memory, "log", "-2", "--format=%s%n%b%n--")
    agent_commit, kept_commit = log.split("--\n")[0], log.split("--\n")[1]
    assert agent_commit.startswith("Agent write") and "Cicada-Author: claude-code" in agent_commit
    assert kept_commit.startswith("Uncommitted edit kept apart") and "Cicada-Author" not in kept_commit
    kept_diff = _git(memory, "show", "HEAD~1", "--", "entities/alpha-project.md")
    agent_diff = _git(memory, "show", "HEAD", "--", "entities/alpha-project.md")
    added = lambda diff: [line for line in diff.splitlines() if line.startswith("+")]  # noqa: E731
    assert any("own uncommitted line" in line for line in added(kept_diff))
    assert not any("agent's line" in line for line in added(kept_diff))
    assert any("agent's line" in line for line in added(agent_diff))
    assert not any("own uncommitted line" in line for line in added(agent_diff))
    assert _git(memory, "status", "--porcelain", "--", "entities/") == ""


def test_watch_later_duplicates_save_their_alias_rows(tmp_path, monkeypatch):
    """`write_prepared`'s contract: every caller saves the index — a duplicate adds alias rows too."""
    from api.services import mcp_tools, media_ingestor, reading_settings, youtube_lists
    from api.services.media_ingestor import IngestResult

    memory = _bank(tmp_path, git=True)
    monkeypatch.setattr(reading_settings, "agent_enabled", lambda: True)
    monkeypatch.setattr(youtube_lists, "allowed", lambda name: True)
    monkeypatch.setattr(youtube_lists, "note", lambda *a, **kw: None)

    def duplicate(prepared, memory_path, idx):
        idx[media_ingestor.url_hash(prepared.item.url) + "-alias"] = {"media_entity_id": "knots", "url": "alias",
                                                                       "alias_of": "primary"}
        return IngestResult(status="duplicate", media_entity_id="knots", episode_id="", title="Knots",
                            media_type="youtube")

    monkeypatch.setattr(media_ingestor, "write_prepared", duplicate)
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="", harness="claude-code")
    said = mcp_tools.record_youtube_list(ctx, "watch_later", "read",
                                         videos=[{"url": "https://www.youtube.com/watch?v=bbbbbbbbbbb",
                                                  "title": "Knots"}])
    assert "already in memory" in said
    saved = json.loads((memory / "sources" / "url_index.json").read_text())
    assert any(row.get("alias_of") == "primary" for row in saved.values()), "the duplicate's alias row was saved"
    assert "sources/url_index.json" in _git(memory, "show", "--name-only", "--format=", "HEAD")


def _fake_codex(tmp_path: Path) -> Path:
    """A `codex` that answers only `login status` and `login --device-auth` (the Codex CLI's own flags), from a state
    file, and records the CODEX_HOME it ran with — never a real login, never a network call."""
    bindir = tmp_path / "fakecodex"
    bindir.mkdir()
    state, log = tmp_path / "codex-state", tmp_path / "codex-calls"
    state.write_text("out")
    script = bindir / "codex"
    script.write_text(f"""#!/bin/sh
echo "$* | $CODEX_HOME" >> '{log}'
if [ "$1 $2" = "login status" ]; then
  if [ "$(cat '{state}')" = in ]; then echo "Logged in using ChatGPT"; exit 0; fi
  echo "Not logged in"; exit 1
fi
if [ "$1 $2" = "login --device-auth" ]; then echo in > '{state}'; exit 0; fi
exit 2
""")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return bindir


def test_engine_connect_signs_the_chatgpt_plan_in_with_the_device_code_in_cicadas_own_codex_home(
        env, monkeypatch, capsys, tmp_path):  # noqa: F811
    from api import cli, cli_app

    home = tmp_path / "cicada-home"
    monkeypatch.setenv("CICADA_HOME", str(home))
    bindir = _fake_codex(tmp_path)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "persons-own-codex"))
    monkeypatch.setattr(cli_app, "_interactive", lambda: True)
    routes = {("GET", "/connections/chatgpt-plan"): (200, {"id": "chatgpt-plan", "connected": True, "plan": "plus"})}
    with _backend(env, monkeypatch, routes):
        code = cli.main(["engine", "connect", "chatgpt-plan"])
        captured = capsys.readouterr()
    assert code == 0, captured
    assert "signed in on this machine" in captured.out and "--mode codex" in captured.out
    assert "one-time code" in captured.err and "never sees or stores the token" in captured.err
    calls = (tmp_path / "codex-calls").read_text().splitlines()
    assert any(c.startswith("login --device-auth |") for c in calls)
    assert all("persons-own-codex" not in c and c.endswith(str(home / "codex")) for c in calls), calls


def test_an_api_key_codex_login_is_not_a_plan(monkeypatch, tmp_path):
    from api import cli_app

    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "codex"
    script.write_text("#!/bin/sh\necho 'Logged in using an API key - sk-***'\nexit 0\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    assert cli_app._signed_in(cli_app.PLAN_SIGN_INS["chatgpt-plan"], str(script)) is False
