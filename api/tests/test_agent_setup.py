"""Round 4 D5 / C5 (G76's in-app half): `GET /agents/setup` hands the person
what to give an agent — a prompt naming exactly the commands `/agents/wiring`
would run, a Cursor install link, or a config merge the app performs. Nothing
here probes, runs a CLI or reads a harness root. Synthetic paths only."""
from __future__ import annotations

import asyncio
import base64
import json
import re
import shlex
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import agent_wiring
from api.services.connections import base

REPO = Path("/opt/example-person/Documents/code/cicada")   # a 41-character checkout (R4B-11)
PY = f"{REPO}/api/.venv/bin/python"
MEM = REPO / "memory"
HOME = Path("/opt/example-person")
BINARIES = {"claude": "/opt/homebrew/bin/claude", "codex": "/opt/homebrew/bin/codex",
            "gemini": "/opt/homebrew/bin/gemini"}
SPEC = {"command": PY, "args": [f"{REPO}/mcp/server.py"], "env": {"CICADA_MEMORY_PATH": str(MEM)}}


def _setup(harness, *, home=HOME, resolve=BINARIES.get):
    return agent_wiring.setup(harness, home=home, memory_root=MEM, repo=REPO, python=PY, resolve=resolve)


def _runner(rc):
    async def run(argv, *, timeout):
        return base.CliResult(rc, "", "")
    return run


@pytest.mark.parametrize("harness", ["claude-code", "codex"])
def test_the_prompt_runs_exactly_what_the_wiring_would(tmp_path, harness):
    setup = _setup(harness, home=tmp_path)
    wiring = asyncio.run(agent_wiring.probe(home=tmp_path, memory_root=MEM, repo=REPO, python=PY,
                                            runner=_runner(1), resolve=BINARIES.get))
    row = next(a for a in wiring["agents"] if a["id"] == harness)
    assert setup["kind"] == "prompt"
    assert setup["argv"] == [s["argv"] for s in row["connect"]]      # C5: the same argv
    assert setup["display"] == [shlex.join(a) for a in setup["argv"]]
    numbered = [line.split(". ", 1)[1] for line in setup["prompt"].splitlines() if re.match(r"^\d+\. ", line)]
    assert numbered == setup["display"]                              # every command, verbatim, nothing else


@pytest.mark.parametrize("harness", ["claude-code", "codex", "gemini-cli"])
def test_the_prompt_is_short_plain_and_says_what_it_touches(harness):
    prompt = _setup(harness)["prompt"]
    assert len(prompt) <= agent_wiring.PROMPT_MAX_CHARS, len(prompt)
    assert "change nothing else" in prompt and "uploads nothing" in prompt


def test_gemini_gets_its_own_add_command_and_its_after_agent_hook():
    setup = _setup("gemini-cli")
    assert setup["argv"] == [[
        "/opt/homebrew/bin/gemini", "mcp", "add", "-s", "user", "-e", f"CICADA_MEMORY_PATH={MEM}",
        "cicada", PY, f"{REPO}/mcp/server.py"],
        [PY, f"{REPO}/api/hooks/registry.py", "install", "--settings", str(HOME / ".gemini/settings.json"),
         "--event", "AfterAgent", "--command", f'"{PY}" "{REPO}/api/hooks/capture.py" --harness gemini-cli']]
    assert len(setup["prompt"]) <= agent_wiring.PROMPT_MAX_CHARS
    assert "saves our conversations" in setup["prompt"]


def test_a_cli_the_backend_cannot_find_is_named_bare():
    assert _setup("claude-code", resolve=lambda name: None)["argv"][0][0] == "claude"


def test_cursor_gets_its_install_link_with_the_server_inside():
    setup = _setup("cursor")
    assert setup["kind"] == "deeplink"
    assert len(setup["argv"]) == 2 and all(a[1].endswith("/api/hooks/cursor_registry.py") for a in setup["argv"])
    assert setup["argv"][1][-2:] == ["--hook", "capture"]
    link = setup["deeplink"]
    assert link.startswith("cursor://anysphere.cursor-deeplink/mcp/install?name=cicada&config=")
    assert json.loads(base64.b64decode(unquote(link.split("config=", 1)[1]))) == SPEC


def test_the_claude_app_gets_a_merge_the_app_performs_and_no_prompt():
    setup = _setup("claude-desktop")
    assert setup["kind"] == "config-merge" and setup.get("prompt") is None
    assert setup["config"] == {"path": "~/Library/Application Support/Claude/claude_desktop_config.json",
                               "key": "mcpServers.cicada", "value": SPEC}
    assert "Quit and reopen" in setup["note"]


def test_an_unknown_harness_has_no_setup():
    assert _setup("nope") is None


def test_the_route_serves_every_harness_and_never_runs_a_cli(tmp_path, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("/agents/setup must never run a CLI")

    (tmp_path / "memory").mkdir()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "memory"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(base, "run_cli", boom)
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        for harness in ("claude-code", "codex", "gemini-cli", "cursor", "claude-desktop",
                        "opencode", "hermes", "openclaw", "claude", "chatgpt", "grok", "other"):
            r = client.get(f"/agents/setup?harness={harness}")
            assert r.status_code == 200, (harness, r.text)
            assert r.json()["harness"] == harness and r.json()["title"]
        assert client.get("/agents/setup?harness=nope").status_code == 404
        assert client.get("/agents/setup").status_code == 422
    finally:
        config.get_settings.cache_clear()


# --- Round 4 C8 (R-AG3, R-AG19): config prompts and remote outlines ---


@pytest.mark.parametrize("harness,where", [
    ("opencode", "~/.config/opencode/opencode.json"),
    ("hermes", "~/.hermes/config.yaml"),
    ("openclaw", "~/.openclaw/openclaw.json"),
])
def test_config_agents_get_a_prompt_that_names_the_server_and_runs_nothing(harness, where):
    setup = _setup(harness)
    assert setup["kind"] == "prompt" and setup["argv"] == [] and setup["display"] == []
    prompt = setup["prompt"]
    assert len(prompt) <= agent_wiring.PROMPT_MAX_CHARS, len(prompt)
    assert PY in prompt and f"{REPO}/mcp/server.py" in prompt and f"CICADA_MEMORY_PATH={MEM}" in prompt
    assert where in prompt and "change nothing else" in prompt and "uploads nothing" in prompt
    assert setup["config"]["path"] == where and setup["note"]


def test_opencode_s_value_is_its_own_local_shape():
    value = _setup("opencode")["config"]["value"]
    assert value == {"type": "local", "command": [PY, f"{REPO}/mcp/server.py"],
                     "environment": {"CICADA_MEMORY_PATH": str(MEM)}, "enabled": True}
    assert _setup("hermes")["config"]["value"] == SPEC and _setup("openclaw")["config"]["value"] == SPEC


@pytest.mark.parametrize("harness", ["claude", "chatgpt", "grok"])
def test_cloud_agents_get_the_two_remote_steps_and_nothing_to_run(harness):
    setup = _setup(harness)
    assert setup["kind"] == "remote" and setup["title"]
    assert len(setup["display"]) == 2 and setup["display"][0] == agent_wiring.REACH_STEP
    assert "Create a link" in setup["display"][1]
    assert (setup.get("prompt"), setup.get("argv"), setup.get("deeplink"), setup.get("config")) == (None, None, None, None)
    assert "no automatic save" in setup["note"]


# --- 2026-10-14: a paste-able prompt on every local row, and one for any other agent ---


def _numbered(prompt):
    return [line for line in prompt.splitlines() if re.match(r"^\d+\. ", line)]


def test_cursor_s_prompt_adds_only_the_mcp_server_to_its_own_config():
    prompt = _setup("cursor")["prompt"]
    assert len(prompt) <= agent_wiring.PROMPT_MAX_CHARS, len(prompt)
    assert "to Cursor" in prompt and "~/.cursor/mcp.json, at mcpServers.cicada" in prompt
    assert f"command: {PY}\nargument: {REPO}/mcp/server.py\nenvironment: CICADA_MEMORY_PATH={MEM}" in prompt
    assert "change nothing else" in prompt and "uploads nothing" in prompt and "one sentence" in prompt
    # The startup hook stays its own click (R-H11): the prompt names no hook and no command to run.
    assert "hooks.json" not in prompt and "cursor_registry" not in prompt and _numbered(prompt) == []


def test_another_agent_gets_the_server_and_its_own_settings_and_no_name():
    setup = _setup("other")
    assert (setup["kind"], setup["argv"], setup["display"], setup.get("config")) == ("prompt", [], [], None)
    assert setup["title"] == "Connect another agent" and setup["note"]
    prompt = setup["prompt"]
    assert len(prompt) <= agent_wiring.PROMPT_MAX_CHARS, len(prompt)
    assert prompt.startswith("Please connect Cicada, the memory app on this Mac, to yourself.")
    assert "MCP server named cicada" in prompt and "your own MCP settings" in prompt
    assert f"command: {PY}\nargument: {REPO}/mcp/server.py\nenvironment: CICADA_MEMORY_PATH={MEM}" in prompt
    assert "change nothing else" in prompt and "uploads nothing" in prompt and "one sentence" in prompt
    assert "don't guess" in prompt
    for product in ("Claude", "Codex", "Cursor", "Gemini", "OpenCode", "Hermes", "OpenClaw", "Windsurf"):
        assert product not in prompt, product                           # provider-neutral: the person's choice


def test_every_prompt_names_a_long_checkout_whole():
    """Commands and paths are never shortened (R4B-11): a 60-character checkout still fits."""
    repo = Path("/opt/example-person-with-a-long-name/Documents/code/cicada-x")
    py = f"{repo}/api/.venv/bin/python"
    for harness in ("claude-code", "codex", "gemini-cli", "cursor", "opencode", "hermes", "openclaw", "other"):
        setup = agent_wiring.setup(harness, home=HOME, memory_root=repo / "memory", repo=repo, python=py,
                                   resolve=BINARIES.get)
        assert len(setup["prompt"]) <= agent_wiring.PROMPT_MAX_CHARS, (harness, len(setup["prompt"]))
        assert py in setup["prompt"] and f"{repo}/memory" in setup["prompt"], harness


@pytest.mark.parametrize("harness", ["claude-code", "codex", "gemini-cli", "cursor", "opencode", "hermes",
                                     "openclaw", "other"])
def test_a_release_app_s_prompt_names_its_launcher_and_no_checkout(monkeypatch, harness):
    """G182: a release app has no venv and no `mcp/server.py`; the MCP command is the
    argument-less `~/.cicada/bin/cicada-mcp` launcher. The config prompts used to
    index the first argument and failed for OpenCode, Hermes and OpenClaw."""
    home = Path("/Users/example-person")
    monkeypatch.setenv("CICADA_DISTRIBUTION", "release")
    monkeypatch.setenv("CICADA_HOME", str(home / ".cicada"))
    launcher = f"{home}/.cicada/bin/cicada-mcp"
    setup = agent_wiring.setup(harness, home=home, memory_root=home / "cicada" / "memory",
                               repo=Path("/Applications/Cicada.app/Contents/Resources/backend/app"),
                               python=None, resolve=BINARIES.get)
    prompt = setup["prompt"]
    assert len(prompt) <= agent_wiring.PROMPT_MAX_CHARS, len(prompt)
    assert launcher in prompt and f"CICADA_MEMORY_PATH={home}/cicada/memory" in prompt
    assert ".venv" not in prompt and "server.py" not in prompt and "Cicada.app" not in prompt
    if harness in ("claude-code", "codex", "gemini-cli"):
        assert _numbered(prompt)[0].endswith(f"-- {launcher}" if harness != "gemini-cli" else f"cicada {launcher}")
    else:
        assert f"command: {launcher}\nenvironment: CICADA_MEMORY_PATH=" in prompt   # no `argument:` line


def test_release_config_values_carry_no_arguments(monkeypatch):
    monkeypatch.setenv("CICADA_DISTRIBUTION", "release")
    monkeypatch.setenv("CICADA_HOME", "/Users/example-person/.cicada")
    setup = agent_wiring.setup("opencode", home=HOME, memory_root=MEM, repo=REPO, python=PY)
    assert setup["config"]["value"]["command"] == ["/Users/example-person/.cicada/bin/cicada-mcp"]
