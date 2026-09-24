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


def test_gemini_gets_its_own_add_command_and_no_hook():
    assert _setup("gemini-cli")["argv"] == [[
        "/opt/homebrew/bin/gemini", "mcp", "add", "-s", "user", "-e", f"CICADA_MEMORY_PATH={MEM}",
        "cicada", PY, f"{REPO}/mcp/server.py"]]


def test_a_cli_the_backend_cannot_find_is_named_bare():
    assert _setup("claude-code", resolve=lambda name: None)["argv"][0][0] == "claude"


def test_cursor_gets_its_install_link_with_the_server_inside():
    setup = _setup("cursor")
    assert (setup["kind"], setup.get("prompt"), setup.get("argv")) == ("deeplink", None, None)
    link = setup["deeplink"]
    assert link.startswith("cursor://anysphere.cursor-deeplink/mcp/install?name=cicada&config=")
    assert json.loads(base64.b64decode(unquote(link.split("config=", 1)[1]))) == SPEC


def test_the_claude_app_gets_a_merge_the_app_performs():
    setup = _setup("claude-desktop")
    assert setup["kind"] == "config-merge"
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
                        "opencode", "hermes", "openclaw", "claude", "chatgpt", "grok"):
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
