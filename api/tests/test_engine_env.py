"""R-E1/R-E3/R-E5–R-E7 — a plan child never inherits a plan override, and
every `codex` child runs in Cicada's own Codex home.

The last four tests drive the REAL `run_cli_sync` against a fake vendor
binary (conftest `fake_cli`) that reports the argv and environment it was
given — the scrub is proven on a real subprocess, never only on a dict.
"""
from __future__ import annotations

import asyncio
import json
import stat

from api.services import agent_engine
from api.services.connections import base, claude_cli, codex_cli
from api.services.connections.base import CliResult

_EVERY_STRIPPED = (*base.MANAGED_KEY_ENV, *base.CLAUDE_PLAN_OVERRIDE_ENV,
                   *base.CODEX_PLAN_OVERRIDE_ENV, "CLAUDE_CODE_RETRY_WATCHDOG", "CODEX_HOME")


def test_scrubbed_env_strips_every_plan_override_and_managed_key(monkeypatch):
    for key in _EVERY_STRIPPED:
        monkeypatch.setenv(key, "leak")
    env = base.scrubbed_env()
    for key in _EVERY_STRIPPED:
        assert key not in env, key
    assert env["CICADA_CAPTURE"] == "off"


def test_the_override_lists_name_every_credential_that_outranks_the_plan():
    # code.claude.com/docs/en/authentication (fetched 2026-09-23): the cloud
    # switches, then ANTHROPIC_AUTH_TOKEN, outrank /login; ANTHROPIC_BASE_URL
    # reroutes. Codex: an env key outranks the ChatGPT sign-in (R2 §1.4).
    for name in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
                 "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
        assert name in base.CLAUDE_PLAN_OVERRIDE_ENV
    for name in ("CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL"):
        assert name in base.CODEX_PLAN_OVERRIDE_ENV


def test_a_codex_child_gets_cicadas_own_home_and_nothing_else_does(monkeypatch, tmp_path):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "the-persons-own-codex"))
    home = base.codex_home()
    assert home == tmp_path / "home" / "codex"
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    assert base.scrubbed_env("codex")["CODEX_HOME"] == str(home)
    assert base.scrubbed_env("/opt/elsewhere/bin/codex")["CODEX_HOME"] == str(home)
    assert "CODEX_HOME" not in base.scrubbed_env("claude")
    assert codex_cli.codex_home_dir() == home


def test_the_override_note_names_variables_never_values(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.com/secret-path")
    note = base.override_note("claude")
    assert "ANTHROPIC_BASE_URL" in note
    assert "gateway.example.com" not in note and "secret-path" not in note
    assert base.override_note("codex") is None


def test_a_managed_key_is_stripped_silently(monkeypatch):
    """R-E6: Cicada's own BYOK keys are hot-loaded into os.environ on every
    BYOK install — warning about them would be noise, not information."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert base.override_note("claude") is None and base.override_note("codex") is None


def test_the_claude_card_says_why_the_plan_would_be_bypassed(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _n: "/usr/local/bin/claude")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")

    async def run(argv):
        return CliResult(0, json.dumps({"loggedIn": True, "authMethod": "claude.ai",
                                        "subscriptionType": "pro"}), "")

    status = asyncio.run(claude_cli.ClaudePlanAdapter(runner=run).status())
    assert status.connected and "CLAUDE_CODE_USE_BEDROCK" in status.how


def test_the_sleep_preflight_sentence_says_why_too(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "t")
    ok, detail = agent_engine.probe(runner=lambda argv, **kw: CliResult(
        0, json.dumps({"loggedIn": True, "authMethod": "claude.ai"}), ""))
    assert ok and "ANTHROPIC_AUTH_TOKEN" in detail


def test_a_real_claude_child_sees_the_scrubbed_env(fake_cli, monkeypatch):
    read_seen = fake_cli("claude", "{}\n", watch=(
        "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CICADA_CAPTURE",
        "CLAUDE_CODE_MAX_RETRIES", "CODEX_HOME"))
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "leak")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.com")
    result = base.run_cli_sync(["claude", "-p"], stdin="hi",
                               env_overrides={"CLAUDE_CODE_MAX_RETRIES": "2"})
    assert result.rc == 0
    [seen] = read_seen()
    assert seen["argv"] == ["-p"] and seen["stdin"] == "hi"
    assert seen["env"] == {"ANTHROPIC_AUTH_TOKEN": None, "ANTHROPIC_BASE_URL": None,
                           "CICADA_CAPTURE": "off", "CLAUDE_CODE_MAX_RETRIES": "2",
                           "CODEX_HOME": None}


def test_a_real_codex_child_runs_in_cicadas_home(fake_cli, monkeypatch):
    read_seen = fake_cli("codex", "", watch=("CODEX_HOME", "CODEX_API_KEY",
                                             "OPENAI_BASE_URL", "CICADA_CAPTURE"))
    monkeypatch.setenv("CODEX_API_KEY", "leak")
    monkeypatch.setenv("CODEX_HOME", "/nonexistent/not-cicadas")
    assert base.run_cli_sync(["codex", "login", "status"]).rc == 0
    [seen] = read_seen()
    assert seen["env"] == {"CODEX_HOME": str(base.codex_home()), "CODEX_API_KEY": None,
                           "OPENAI_BASE_URL": None, "CICADA_CAPTURE": "off"}


def test_the_async_runner_scrubs_the_same_way(fake_cli, monkeypatch):
    read_seen = fake_cli("codex", "", watch=("CODEX_HOME", "CODEX_API_KEY"))
    monkeypatch.setenv("CODEX_API_KEY", "leak")
    assert asyncio.run(base.run_cli(["codex", "login", "status"])).rc == 0
    [seen] = read_seen()
    assert seen["env"] == {"CODEX_HOME": str(base.codex_home()), "CODEX_API_KEY": None}


def test_a_timeout_keeps_what_the_child_already_printed(fake_cli):
    """R-E9: an api_retry printed before the wall clock ran out is the
    evidence that turns a "timeout" into a throttle (Task 2)."""
    fake_cli("claude", '{"type":"system","subtype":"api_retry","error":"rate_limit"}\n', sleep=5)
    result = base.run_cli_sync(["claude", "-p"], timeout=1.0)
    assert result.rc == 124 and "api_retry" in result.stdout
