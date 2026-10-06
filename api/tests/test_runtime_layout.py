"""G182 — a release app's commands go through the stable launchers in $CICADA_HOME/bin.

The app holds the same shapes (`CicadaRuntime.swift`, `AgentConnectPolicy`); a checkout's
commands stay byte for byte what install.sh registers.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.hooks import registry
from api.services import agent_wiring, runtime_layout

REPO = Path("/opt/example/cicada")
PY = "/opt/example/cicada/api/.venv/bin/python"


@pytest.fixture
def release(monkeypatch, tmp_path):
    home = tmp_path / "cicada home"
    monkeypatch.setenv("CICADA_DISTRIBUTION", "release")
    monkeypatch.setenv("CICADA_HOME", str(home))
    return home / "bin"


@pytest.fixture
def checkout(monkeypatch):
    monkeypatch.delenv("CICADA_DISTRIBUTION", raising=False)


def test_a_checkout_keeps_install_sh_commands(checkout):
    assert not runtime_layout.is_release()
    assert runtime_layout.mcp_argv(PY, REPO) == [PY, f"{REPO}/mcp/server.py"]
    assert runtime_layout.registry_argv(PY, REPO) == [PY, f"{REPO}/api/hooks/registry.py"]
    assert agent_wiring.hook_command(PY, REPO, "claude-code") == \
        f'"{PY}" "{REPO}/api/hooks/capture.py" --harness claude-code'
    assert agent_wiring.recall_hook_command(PY, REPO, "codex") == \
        f'"{PY}" "{REPO}/api/hooks/recall.py" --harness codex'


def test_a_release_runs_every_command_through_the_launchers(release):
    hook = f"{release}/cicada-hook"
    assert runtime_layout.is_release()
    assert runtime_layout.mcp_argv(PY, REPO) == [f"{release}/cicada-mcp"]
    assert runtime_layout.registry_argv(PY, REPO) == [hook, "registry"]
    assert agent_wiring.hook_command(PY, REPO, "claude-code") == f'"{hook}" capture --harness claude-code'
    assert agent_wiring.recall_hook_command(PY, REPO, "codex") == f'"{hook}" recall --harness codex'
    assert agent_wiring.venv_python(REPO) == f"{release}/cicada-python"


def test_release_steps_have_the_shapes_the_app_allows(release, tmp_path):
    h = agent_wiring.HARNESSES[0]
    mcp = agent_wiring.mcp_step(h, "/usr/local/bin/claude", memory_root=tmp_path / "m", repo=REPO, python=PY)
    assert mcp["argv"][-2:] == ["--", f"{release}/cicada-mcp"]
    hook = agent_wiring.hook_step(h, home=tmp_path, repo=REPO, python=PY)
    assert hook["argv"][:3] == [f"{release}/cicada-hook", "registry", "install"]
    assert len(hook["argv"]) == 9 and hook["argv"][8] == f'"{release}/cicada-hook" capture --harness claude-code'
    recall = agent_wiring.autorecall_argv(h, home=tmp_path, repo=REPO, python=PY)
    assert [s["argv"][6] for s in recall["on"]] == ["SessionStart", "UserPromptSubmit"]
    assert recall["off"][0]["argv"] == [f"{release}/cicada-hook", "registry", "uninstall", "--settings",
                                        str(tmp_path / h.settings), "--hook", "recall"]
    spec = agent_wiring.server_spec(memory_root=tmp_path / "m", repo=REPO, python=PY)
    assert spec["command"] == f"{release}/cicada-mcp" and spec["args"] == []


def test_a_release_hook_replaces_a_checkout_hook_and_back(tmp_path):
    """Installing the app over a source install (or the reverse) updates Cicada's one
    entry per script instead of registering a second hook that would capture twice."""
    settings = tmp_path / "settings.json"
    dev_capture = f'"{PY}" "{REPO}/api/hooks/capture.py" --harness claude-code'
    rel_capture = '"/Users/x/.cicada/bin/cicada-hook" capture --harness claude-code'
    rel_recall = '"/Users/x/.cicada/bin/cicada-hook" recall --harness claude-code'
    assert registry.install(settings, event="Stop", command=dev_capture) == "added"
    assert registry.status(settings, event="Stop", command=rel_capture) == "stale"
    assert registry.install(settings, event="Stop", command=rel_capture) == "updated"
    assert registry.install(settings, event="SessionStart", command=rel_recall) == "added"
    data = json.loads(settings.read_text())
    assert [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]] == [rel_capture]
    assert registry.uninstall(settings, hook="recall") == 1, "recall off never touches the Stop hook"
    assert registry.install(settings, event="Stop", command=dev_capture) == "updated"
    data = json.loads(settings.read_text())
    assert [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]] == [dev_capture]


@pytest.mark.parametrize("raw,expected", [("", 8000), ("18000", 18000), ("0", 8000), ("70000", 8000), ("x", 8000)])
def test_the_port_is_cicada_port_or_8000(monkeypatch, raw, expected):
    monkeypatch.setenv("CICADA_PORT", raw)
    assert runtime_layout.port() == expected
    assert runtime_layout.backend_url() == f"http://127.0.0.1:{expected}"


def test_only_known_launchers_and_hooks():
    with pytest.raises(ValueError):
        runtime_layout.launcher("rm")
    with pytest.raises(ValueError):
        runtime_layout.hook_command("evil", PY, REPO, "claude-code")


def test_the_mcp_server_and_hooks_honour_cicada_port():
    root = Path(__file__).resolve().parents[2]
    server = (root / "mcp" / "server.py").read_text(encoding="utf-8")
    assert "http://127.0.0.1:8000" not in server
    assert "runtime_layout.backend_url()" in server
    for hook in ("capture.py", "recall.py"):
        assert 'environ.get("CICADA_PORT")' in (root / "api" / "hooks" / hook).read_text(encoding="utf-8")
