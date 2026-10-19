"""Cicada as a Claude Code plugin (owner 2026-10-19: the plugin is the canonical Claude Code door; install.sh the
canonical machine install).

The marketplace (``.claude-plugin/marketplace.json``) and the plugin (``plugins/cicada``) are checked as files: every
path resolves inside the plugin, every hook command runs one of the plugin's own scripts, and those scripts reach the
same capture/recall scripts and MCP server install.sh registers — through the app's launchers or a named checkout.
Then the coexistence: with the plugin enabled, install.sh registers no Claude Code hook or MCP entry (and removes its
older ones), ``make doctor`` and ``GET /agents/wiring`` say which door is active. Everything runs in a scratch HOME;
nothing here reads the real ``~/.claude``.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from api.hooks import registry as hook_registry
from api.services import agent_wiring
from api.services.connections import base

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "cicada"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"
HOOKS = PLUGIN / "hooks" / "hooks.json"
MCP = PLUGIN / ".mcp.json"
HOOK_SHIM = PLUGIN / "scripts" / "cicada-hook"
MCP_SHIM = PLUGIN / "scripts" / "cicada-mcp"

CAPTURE_EVENTS = {"Stop", "PreCompact", "SessionEnd"}
RECALL_EVENTS = {"SessionStart", "UserPromptSubmit"}
USER_CONFIG_FIELDS = {"type", "title", "description", "required", "default", "options", "multiple", "sensitive",
                      "min", "max"}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _exe(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


# --------------------------------------------------------------------------- the manifests


def test_the_marketplace_lists_the_plugin_by_a_relative_path_inside_the_repo():
    market = _json(MARKETPLACE)
    assert market["name"] == "cicada" and market["owner"]["name"]
    [entry] = market["plugins"]
    assert entry["name"] == "cicada" and entry["source"] == "./plugins/cicada"
    assert (ROOT / entry["source"]).resolve() == PLUGIN.resolve()
    assert f"{entry['name']}@{market['name']}" == hook_registry.PLUGIN_ID, \
        "install.sh, doctor and the wiring detect the plugin by this id"


def test_the_manifest_is_valid_and_carries_the_release_version():
    manifest = _json(MANIFEST)
    assert manifest["name"] == "cicada"
    assert manifest["version"] == (ROOT / "VERSION").read_text().strip(), \
        "release.sh bumps it with VERSION and check_version.py agree holds it there"
    for key, option in manifest["userConfig"].items():
        assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
        assert {"type", "title", "description"} <= set(option) <= USER_CONFIG_FIELDS, key
        assert option.get("sensitive") is not True, "nothing secret is asked: the token stays in ~/.cicada"
    assert set(manifest["userConfig"]) == {"cicada_repo", "memory_path", "recall"}


def test_the_plugin_has_no_bin_folder_and_nothing_outside_the_standard_layout():
    """A top-level ``bin/`` makes claude.ai and Cowork refuse the plugin; a CLAUDE.md at the root is never loaded."""
    assert not (PLUGIN / "bin").exists()
    assert not (PLUGIN / "CLAUDE.md").exists()
    assert {p.name for p in PLUGIN.iterdir()} <= {".claude-plugin", "skills", "hooks", "scripts", ".mcp.json",
                                                   "README.md"}


def test_the_plugin_skill_is_the_repo_skill_byte_for_byte():
    copy = PLUGIN / "skills" / "cicada" / "SKILL.md"
    assert copy.read_bytes() == (ROOT / "SKILL.md").read_bytes(), (
        "the plugin's skill drifted from SKILL.md: run `cp SKILL.md plugins/cicada/skills/cicada/SKILL.md`")


def test_claude_plugin_validate_passes(tmp_path):
    claude = shutil.which("claude")
    if claude is None:
        pytest.skip("the claude CLI is not installed here")
    env = {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    for target in (PLUGIN, ROOT):
        done = subprocess.run([claude, "plugin", "validate", str(target)], env=env, capture_output=True, text=True,
                              timeout=60)
        out = done.stdout + done.stderr
        assert done.returncode == 0 and "Validation passed" in out, out
        assert "warning" not in out.lower(), out


# --------------------------------------------------------------------------- hook and MCP commands resolve


def _commands() -> dict[str, list[str]]:
    hooks = _json(HOOKS)["hooks"]
    return {event: [h["command"] for entry in entries for h in entry["hooks"]] for event, entries in hooks.items()}


def test_every_capture_and_recall_event_runs_the_plugin_s_own_hook_script():
    commands = _commands()
    assert set(commands) == CAPTURE_EVENTS | RECALL_EVENTS, "the same five events install.sh registers"
    for event, cmds in commands.items():
        assert len(cmds) == 1, f"{event}: one entry per event, never a second firing"
        kind = "capture" if event in CAPTURE_EVENTS else "recall"
        assert cmds[0] == f'"${{CLAUDE_PLUGIN_ROOT}}"/scripts/cicada-hook {kind} --harness claude-code'
    for entries in _json(HOOKS)["hooks"].values():
        for entry in entries:
            assert "matcher" not in entry and all(h["timeout"] == hook_registry.DEFAULT_TIMEOUT_S
                                                  for h in entry["hooks"])


def test_the_hook_and_mcp_scripts_exist_are_executable_and_reach_cicada_s_own_scripts():
    for shim in (HOOK_SHIM, MCP_SHIM):
        assert shim.is_file() and os.access(shim, os.X_OK), shim
        assert subprocess.run(["sh", "-n", str(shim)]).returncode == 0
    for name in ("capture", "recall"):
        assert (ROOT / "api" / "hooks" / f"{name}.py").is_file()
    launchers = (ROOT / "scripts" / "release" / "write-launchers.sh").read_text()
    assert "capture|recall|registry|cursor|cursor_registry)" in launchers, "the app's cicada-hook takes these names"
    server = _json(MCP)["mcpServers"]
    assert list(server) == ["cicada"]
    assert server["cicada"]["command"] == "${CLAUDE_PLUGIN_ROOT}/scripts/cicada-mcp"
    declared = set(_json(MANIFEST)["userConfig"])
    for value in server["cicada"]["env"].values():
        for key in re.findall(r"\$\{user_config\.([A-Za-z0-9_]+)\}", value):
            assert key in declared, key


# --------------------------------------------------------------------------- the scripts' behaviour


def _env(home: Path, **extra: str) -> dict[str, str]:
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "CLAUDE_PLUGIN_ROOT": str(PLUGIN)}
    env.update(extra)
    return env


def _echo_exe(path: Path) -> Path:
    """A fake interpreter/launcher that reports its argv, its stdin and the capture switch it was given."""
    return _exe(path, 'printf "argv:%s\\n" "$*"; printf "stdin:%s\\n" "$(cat)"; '
                      'printf "capture:%s\\n" "${CICADA_CAPTURE:-}"; printf "memory:%s\\n" "${CICADA_MEMORY_PATH:-}"\n')


def _run(shim: Path, args: list[str], env: dict[str, str], stdin: str = '{"session_id":"s"}'):
    return subprocess.run([str(shim), *args], env=env, input=stdin, capture_output=True, text=True, timeout=20)


def test_a_release_runs_the_app_s_launcher_with_the_hook_s_stdin(tmp_path):
    home = tmp_path / "home"
    _echo_exe(home / ".cicada" / "bin" / "cicada-hook")
    done = _run(HOOK_SHIM, ["capture", "--harness", "claude-code"], _env(home, CICADA_CAPTURE="off"))
    assert done.returncode == 0, done.stderr
    assert "argv:capture --harness claude-code" in done.stdout
    assert 'stdin:{"session_id":"s"}' in done.stdout, "the hook payload reaches the script unchanged"
    assert "capture:off" in done.stdout, "CICADA_CAPTURE=off (Cicada's own spawns) still reaches capture.py"


def test_cicada_home_moves_the_launcher(tmp_path):
    home, cicada_home = tmp_path / "home", tmp_path / "ch"
    _echo_exe(cicada_home / "bin" / "cicada-hook")
    done = _run(HOOK_SHIM, ["recall", "--harness", "claude-code"], _env(home, CICADA_HOME=str(cicada_home)))
    assert "argv:recall --harness claude-code" in done.stdout


def test_a_named_checkout_runs_its_venv_and_wins_over_the_launcher(tmp_path):
    home, repo = tmp_path / "home", tmp_path / "checkout"
    _exe(home / ".cicada" / "bin" / "cicada-hook", "echo launcher\n")
    _echo_exe(repo / "api" / ".venv" / "bin" / "python")
    (repo / "api" / "hooks").mkdir(parents=True)
    (repo / "api" / "hooks" / "capture.py").write_text("")
    done = _run(HOOK_SHIM, ["capture", "--harness", "claude-code"],
                _env(home, CLAUDE_PLUGIN_OPTION_CICADA_REPO=str(repo)))
    assert f"argv:{repo}/api/hooks/capture.py --harness claude-code" in done.stdout
    assert "launcher" not in done.stdout


def test_a_checkout_path_written_with_a_tilde_is_expanded(tmp_path):
    home = tmp_path / "home"
    repo = home / "code" / "cicada"
    _echo_exe(repo / "api" / ".venv" / "bin" / "python")
    (repo / "api" / "hooks").mkdir(parents=True)
    (repo / "api" / "hooks" / "recall.py").write_text("")
    done = _run(HOOK_SHIM, ["recall", "--harness", "claude-code"],
                _env(home, CLAUDE_PLUGIN_OPTION_CICADA_REPO="~/code/cicada"))
    assert f"argv:{repo}/api/hooks/recall.py" in done.stdout


@pytest.mark.parametrize("option", [None, "/no/such/checkout", "${user_config.cicada_repo}"])
def test_with_no_cicada_a_hook_says_so_on_stderr_and_never_blocks(tmp_path, option):
    extra = {} if option is None else {"CLAUDE_PLUGIN_OPTION_CICADA_REPO": option}
    done = _run(HOOK_SHIM, ["recall", "--harness", "claude-code"], _env(tmp_path / "home", **extra))
    assert done.returncode == 0
    assert done.stdout == "", "a SessionStart/UserPromptSubmit hook's stdout becomes the agent's context"
    assert "cicada plugin:" in done.stderr


@pytest.mark.parametrize("value", ["false", "False", "0", "off"])
def test_remember_automatically_off_silences_recall_but_not_capture(tmp_path, value):
    home = tmp_path / "home"
    _echo_exe(home / ".cicada" / "bin" / "cicada-hook")
    off = _run(HOOK_SHIM, ["recall", "--harness", "claude-code"], _env(home, CLAUDE_PLUGIN_OPTION_RECALL=value))
    assert (off.returncode, off.stdout) == (0, "")
    on = _run(HOOK_SHIM, ["capture", "--harness", "claude-code"], _env(home, CLAUDE_PLUGIN_OPTION_RECALL=value))
    assert "argv:capture" in on.stdout


def test_cicada_recall_off_silences_the_plugin_s_recall_too(tmp_path):
    home = tmp_path / "home"
    _echo_exe(home / ".cicada" / "bin" / "cicada-hook")
    off = _run(HOOK_SHIM, ["recall", "--harness", "claude-code"], _env(home, CICADA_RECALL="off"))
    assert (off.returncode, off.stdout) == (0, "")
    assert "argv:capture" in _run(HOOK_SHIM, ["capture"], _env(home, CICADA_RECALL="off")).stdout


def test_an_unknown_hook_name_runs_nothing(tmp_path):
    home = tmp_path / "home"
    _echo_exe(home / ".cicada" / "bin" / "cicada-hook")
    done = _run(HOOK_SHIM, ["registry", "uninstall"], _env(home))
    assert (done.returncode, done.stdout) == (0, ""), "the plugin runs capture and recall, nothing else"


def test_the_mcp_server_runs_the_launcher_and_passes_the_memory_root(tmp_path):
    home = tmp_path / "home"
    _echo_exe(home / ".cicada" / "bin" / "cicada-mcp")
    done = _run(MCP_SHIM, [], _env(home, CICADA_PLUGIN_REPO="", CICADA_PLUGIN_MEMORY_PATH="/M/root"), stdin="")
    assert done.returncode == 0 and "argv:\n" in done.stdout and "memory:/M/root" in done.stdout
    unset = _run(MCP_SHIM, [], _env(home, CICADA_PLUGIN_MEMORY_PATH="${user_config.memory_path}"), stdin="")
    assert "memory:\n" in unset.stdout, "an unset option is never passed on as a path"


def test_the_mcp_server_runs_a_named_checkout(tmp_path):
    home, repo = tmp_path / "home", tmp_path / "checkout"
    _echo_exe(repo / "api" / ".venv" / "bin" / "python")
    (repo / "mcp").mkdir(parents=True)
    (repo / "mcp" / "server.py").write_text("")
    done = _run(MCP_SHIM, [], _env(home, CICADA_PLUGIN_REPO=str(repo)), stdin="")
    assert f"argv:{repo}/mcp/server.py" in done.stdout


def test_with_no_cicada_the_mcp_server_fails_with_a_sentence(tmp_path):
    done = _run(MCP_SHIM, [], _env(tmp_path / "home"), stdin="")
    assert done.returncode == 1 and done.stdout == "" and "cicada plugin:" in done.stderr


# --------------------------------------------------------------------------- detection (registry.py plugin)


@pytest.mark.parametrize("settings,expected", [
    ({"enabledPlugins": {"cicada@cicada": True}}, True),
    ({"enabledPlugins": {"cicada@cicada": False}}, False),
    ({"enabledPlugins": {"cicada@someone-else": True}}, False),
    ({}, False),
])
def test_the_registry_reads_whether_the_plugin_is_enabled(tmp_path, settings, expected):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings))
    assert hook_registry.plugin_enabled(path) is expected


def _installed(claude_dir: Path, shape: str = "nested") -> None:
    (claude_dir / "plugins").mkdir(parents=True, exist_ok=True)
    table = {"cicada@cicada": [{"scope": "user"}]}
    (claude_dir / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": table} if shape == "nested" else table))


def _state_cli(settings: Path, cicada_home: Path) -> tuple[int, str]:
    done = subprocess.run([sys.executable, str(ROOT / "api/hooks/registry.py"), "plugin", "--settings", str(settings),
                           "--cicada-home", str(cicada_home)], capture_output=True, text=True)
    return done.returncode, done.stdout.strip()


def test_the_plugin_is_a_door_only_when_enabled_installed_and_runnable(tmp_path):
    """The coordinator's blocker: an enabled plugin that would run nothing must never take Claude Code over."""
    settings, cicada_home = tmp_path / "settings.json", tmp_path / "ch"
    settings.write_text(json.dumps({"enabledPlugins": {"cicada@cicada": True}}))
    # Enabled, not installed (a settings file synced from another machine).
    _exe(cicada_home / "bin" / "cicada-hook", "exit 0\n")
    state, why = hook_registry.plugin_state(settings, cicada_home)
    assert state == "broken" and "not installed" in why
    assert _state_cli(settings, cicada_home)[0] == 4
    # Installed, but nothing to run.
    _installed(tmp_path)
    (cicada_home / "bin" / "cicada-hook").unlink()
    state, why = hook_registry.plugin_state(settings, cicada_home)
    assert state == "broken" and "no Cicada to run" in why
    # Installed and the app's launcher is there: on.
    _exe(cicada_home / "bin" / "cicada-hook", "exit 0\n")
    assert hook_registry.plugin_state(settings, cicada_home) == ("on", str(cicada_home / "bin" / "cicada-hook"))
    rc, out = _state_cli(settings, cicada_home)
    assert rc == 0 and out.startswith("on: ")
    # Not enabled: off, whatever is installed.
    settings.write_text(json.dumps({"enabledPlugins": {"cicada@cicada": False}}))
    assert hook_registry.plugin_state(settings, cicada_home) == ("off", "")
    assert _state_cli(settings, cicada_home)[0] == 1


def test_a_cicada_repo_setting_decides_and_never_falls_back_to_the_launcher(tmp_path):
    settings, cicada_home, repo = tmp_path / "settings.json", tmp_path / "ch", tmp_path / "checkout"
    _installed(tmp_path, shape="flat")
    _exe(cicada_home / "bin" / "cicada-hook", "exit 0\n")
    settings.write_text(json.dumps({"enabledPlugins": {"cicada@cicada": True},
                                    "pluginConfigs": {"cicada@cicada": {"options": {"cicada_repo": str(repo)}}}}))
    state, why = hook_registry.plugin_state(settings, cicada_home)
    assert state == "broken" and "not a set-up Cicada checkout" in why, "the plugin's script exits there too"
    _exe(repo / "api" / ".venv" / "bin" / "python", "exit 0\n")
    (repo / "api" / "hooks").mkdir(parents=True)
    (repo / "api" / "hooks" / "capture.py").write_text("")
    assert hook_registry.plugin_state(settings, cicada_home) == ("on", str(repo))


def test_an_unreadable_settings_file_is_not_a_plugin_and_is_left_alone(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert hook_registry.plugin_enabled(path) is False
    assert hook_registry.plugin_enabled(tmp_path / "missing.json") is False
    assert path.read_text() == "{not json"


def test_the_registry_reads_a_saved_plugin_option(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"enabledPlugins": {"cicada@cicada": True},
                                "pluginConfigs": {"cicada@cicada": {"options": {"cicada_repo": "/R/cicada"}}}}))
    assert hook_registry.plugin_option(path, "cicada_repo") == "/R/cicada"
    assert hook_registry.plugin_option(path, "memory_path") == ""
    done = subprocess.run([sys.executable, str(ROOT / "api/hooks/registry.py"), "plugin", "--settings", str(path),
                           "--option", "cicada_repo"], capture_output=True, text=True)
    assert done.stdout.strip() == "/R/cicada"


def test_the_recall_setting_is_read_and_a_recall_off_choice_is_written_by_merge(tmp_path):
    path = tmp_path / "settings.json"
    other = {"hooks": [{"type": "command", "command": "other"}]}
    path.write_text(json.dumps({"enabledPlugins": {"cicada@cicada": True}, "hooks": {"Stop": [other]}}))
    assert hook_registry.plugin_recall_on(path) is True, "on unless the person set it off"
    done = subprocess.run([sys.executable, str(ROOT / "api/hooks/registry.py"), "plugin-recall-off", "--settings",
                           str(path)], capture_output=True, text=True)
    assert done.returncode == 0 and done.stdout.startswith("updated")
    assert hook_registry.plugin_recall_on(path) is False
    assert _json(path) == {"enabledPlugins": {"cicada@cicada": True}, "hooks": {"Stop": [other]},
                           "pluginConfigs": {"cicada@cicada": {"options": {"recall": False}}}}
    assert hook_registry.plugin_recall_off(path) == "present"
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    with pytest.raises(hook_registry.RegistryError):
        hook_registry.plugin_recall_off(bad)
    assert bad.read_text() == "{nope"


# --------------------------------------------------------------------------- install.sh: no double registration


def _install(tmp_path: Path, *, plugin: bool, args=("--dry-run",), codex: bool = False, installed: bool = True,
             launcher: bool = True, env_extra: dict | None = None, settings_data: dict | None = None) -> tuple[str, Path]:
    home, bin_dir = tmp_path / "home", tmp_path / "bin"
    (home / ".claude").mkdir(parents=True)
    bin_dir.mkdir()
    settings = home / ".claude" / "settings.json"
    data: dict = {"enabledPlugins": {"cicada@cicada": True}} if plugin else {}
    data.update(settings_data or {})
    settings.write_text(json.dumps(data))
    if plugin and installed:
        _installed(home / ".claude")
    if plugin and launcher:
        _exe(home / ".cicada" / "bin" / "cicada-hook", "exit 0\n")
    _exe(bin_dir / "uname", 'if [ "$1" = "-m" ]; then echo arm64; else echo Darwin; fi\n')
    _exe(bin_dir / "uv", "exit 0\n")
    _exe(bin_dir / "curl", "exit 7\n")
    # A claude CLI whose user scope still holds install.sh's older entry.
    _exe(bin_dir / "claude", 'if [ "$1 $2" = "mcp list" ]; then echo "cicada: /x/python /x/mcp/server.py - ok"; fi\n')
    if codex:
        _exe(bin_dir / "codex", "exit 0\n")
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "CICADA_MEMORY_PATH": str(tmp_path / "memory"),
           "CICADA_PORT": "1", "CICADA_HOME": str(home / ".cicada"), **(env_extra or {})}
    done = subprocess.run(["/bin/bash", str(ROOT / "install.sh"), *args], env=env, capture_output=True, text=True,
                          timeout=120)
    out = re.sub(r"\x1b\[[0-9;]*m", "", done.stdout)
    assert done.returncode == 0, done.stderr + out[-3000:]
    return out, settings


def _claude_registrations(out: str, settings: Path) -> list[str]:
    return [line for line in out.splitlines()
            if "registry.py install" in line and f"--settings {settings}" in line]


def test_with_the_plugin_on_install_sh_registers_no_claude_code_hook_or_mcp_entry(tmp_path):
    out, settings = _install(tmp_path, plugin=True, codex=True)
    assert _claude_registrations(out, settings) == [], "every Claude Code hook comes from the plugin"
    assert "claude mcp add" not in out
    assert "Claude Code has Cicada through its plugin" in out
    assert f"registry.py uninstall --settings {settings}" in out, "install.sh's own older entries are removed"
    assert "claude mcp remove cicada -s user" in out, "and so is its older user-scope MCP entry"
    codex_hooks = str(tmp_path / "home" / ".codex" / "hooks.json")
    assert any("registry.py install" in line and codex_hooks in line for line in out.splitlines()), \
        "Codex stays install.sh's"
    assert "the Cicada plugin (cicada@cicada) carries the MCP server, the skill and the hooks" in out
    assert "capture hook:" not in out
    written = sorted(str(p.relative_to(tmp_path / "home")) for p in (tmp_path / "home").rglob("*") if p.is_file())
    assert written == [".cicada/bin/cicada-hook", ".claude/plugins/installed_plugins.json", ".claude/settings.json"], \
        "a dry run, plugin check included, writes nothing"
    assert _json(settings) == {"enabledPlugins": {"cicada@cicada": True}}
    assert "plugin-recall-off" not in out, "recall was not off: the plugin's own setting is left alone"


@pytest.mark.parametrize("installed,launcher,why", [
    (True, False, "no Cicada to run"),
    (False, True, "not installed"),
])
def test_an_enabled_plugin_that_cannot_run_keeps_install_sh_s_entries(tmp_path, installed, launcher, why):
    """The blocker: removing install.sh's working entries for a plugin that runs nothing leaves Claude Code with no
    capture and no tools. They stay, and install.sh says how to finish the switch."""
    out, settings = _install(tmp_path, plugin=True, installed=installed, launcher=launcher)
    events = sorted(re.search(r"--event (\S+)", line).group(1) for line in _claude_registrations(out, settings))
    assert events == sorted(CAPTURE_EVENTS | RECALL_EVENTS), "install.sh registers Claude Code as before"
    assert f"registry.py uninstall --settings {settings}" not in out and "claude mcp remove" not in out
    assert "enabled but" in out and why in out and "keeping this script's Claude Code entries" in out
    assert "fix: /plugin install cicada@cicada" in out
    assert "through its plugin" not in out


def test_handing_over_keeps_a_recall_off_choice(tmp_path):
    """CICADA_RECALL=off, or the app's switch (a capture hook in the settings file and no recall hook), becomes the
    plugin's own recall setting before install.sh's entries go — handing over never turns recall back on."""
    out, settings = _install(tmp_path / "env", plugin=True, env_extra={"CICADA_RECALL": "off"})
    assert f"registry.py plugin-recall-off --settings {settings}" in out
    assert "plugin recall is off" in out
    venv_py = str(ROOT / "api" / ".venv" / "bin" / "python")
    capture = f'"{venv_py}" "{ROOT}/api/hooks/capture.py" --harness claude-code'
    hooks = {"Stop": [{"hooks": [{"type": "command", "command": capture, "timeout": 5}]}]}
    out, settings = _install(tmp_path / "app", plugin=True, settings_data={"hooks": hooks})
    assert f"registry.py plugin-recall-off --settings {settings}" in out, "the app's recall-off choice carries over"


def test_with_the_plugin_off_install_sh_registers_claude_code_as_before(tmp_path):
    out, settings = _install(tmp_path, plugin=False)
    events = sorted(re.search(r"--event (\S+)", line).group(1) for line in _claude_registrations(out, settings))
    assert events == sorted(CAPTURE_EVENTS | RECALL_EVENTS)
    assert "claude mcp remove" not in out and "through its plugin" not in out


def test_the_removal_install_sh_runs_keeps_the_plugin_switch_and_every_other_hook(tmp_path):
    """What install.sh runs with the plugin on (``registry.py uninstall --settings``), on a real file: Cicada's older
    entries go; the plugin switch and another tool's hook stay."""
    settings = tmp_path / "settings.json"
    other = {"hooks": [{"type": "command", "command": "some-other-tool --stop"}]}
    settings.write_text(json.dumps({"enabledPlugins": {"cicada@cicada": True}, "hooks": {"Stop": [other]}}))
    hook_registry.install(settings, event="Stop", command='"/x/api/.venv/bin/python" "/x/api/hooks/capture.py" '
                                                          "--harness claude-code")
    hook_registry.install(settings, event="SessionStart", command='"/x/api/.venv/bin/python" '
                                                                  '"/x/api/hooks/recall.py" --harness claude-code')
    done = subprocess.run([sys.executable, str(ROOT / "api/hooks/registry.py"), "uninstall", "--settings",
                           str(settings)], capture_output=True, text=True)
    assert done.returncode == 0 and "removed 2" in done.stdout
    assert _json(settings) == {"enabledPlugins": {"cicada@cicada": True}, "hooks": {"Stop": [other]}}


def test_the_skill_is_not_copied_when_the_plugin_carries_it(tmp_path):
    out, _ = _install(tmp_path, plugin=True, args=("--dry-run", "--skill"))
    assert "plugin carries the cicada skill" in out and "cp " + str(ROOT / "SKILL.md") not in out


def test_uninstall_points_at_the_plugin_when_it_is_still_on(tmp_path):
    out, _ = _install(tmp_path, plugin=True, args=("--dry-run", "--uninstall"))
    assert "/plugin uninstall cicada@cicada" in out


# --------------------------------------------------------------------------- GET /agents/wiring and /agents/setup

REPO = Path("/R/cicada")
PY = "/R/cicada/api/.venv/bin/python"


def _runner(rc: int):
    async def run(argv, *, timeout):
        return base.CliResult(rc, "", "")
    return run


def _probe(home: Path, rc: int = 1) -> dict:
    return asyncio.run(agent_wiring.probe(home=home, memory_root=Path("/M"), repo=REPO, python=PY,
                                          runner=_runner(rc), resolve=lambda n: n if n in ("claude", "codex") else None,
                                          cicada_home=home / ".cicada"))


def _row(data: dict, agent_id: str) -> dict:
    return next(a for a in data["agents"] if a["id"] == agent_id)


def _enable(home: Path, *, runnable: bool = True, options: dict | None = None) -> Path:
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"enabledPlugins": {"cicada@cicada": True}}
    if options:
        data["pluginConfigs"] = {"cicada@cicada": {"options": options}}
    settings.write_text(json.dumps(data))
    _installed(home / ".claude")
    if runnable:
        _exe(home / ".cicada" / "bin" / "cicada-hook", "exit 0\n")
    return settings


def test_the_wiring_reads_the_plugin_as_on_and_offers_no_argv(tmp_path):
    _enable(tmp_path)
    row = _row(_probe(tmp_path, rc=1), "claude-code")  # `claude mcp get cicada` fails: the plugin's server is namespaced
    assert (row["recall"], row["autosave"], row["autosave_flush"], row["autorecall"]) == ("on", "on", "on", "on")
    assert row["connect"] == row["flush_on"] == row["autorecall_on"] == row["autorecall_off"] == []
    assert row["capabilities"] == {"via": "plugin"} and row["detail"] is None
    codex = _row(_probe(tmp_path, rc=1), "codex")
    assert codex["connect"] and "via" not in (codex.get("capabilities") or {}), "Codex stays install.sh's"


def test_the_wiring_reports_the_plugin_s_recall_off_setting_truthfully(tmp_path):
    _enable(tmp_path, options={"recall": False})
    row = _row(_probe(tmp_path), "claude-code")
    assert row["autorecall"] == "off" and row["autorecall_on"] == [] and row["capabilities"] == {"via": "plugin"}


def test_an_enabled_plugin_that_cannot_run_is_not_reported_as_on(tmp_path):
    _enable(tmp_path, runnable=False)
    row = _row(_probe(tmp_path, rc=1), "claude-code")
    assert "via" not in (row.get("capabilities") or {})
    assert (row["recall"], row["autosave"]) == ("off", "off") and row["connect"], "install.sh's commands are offered"
    assert "enabled but" in row["detail"] and "no Cicada to run" in row["detail"]
    setup = agent_wiring.setup("claude-code", home=tmp_path, memory_root=Path("/M"), repo=REPO, python=PY,
                               resolve=lambda n: n, cicada_home=tmp_path / ".cicada")
    assert setup["argv"], "a plugin that runs nothing is no reason to hand over nothing"


def test_the_wiring_names_older_settings_hooks_that_would_fire_twice(tmp_path):
    settings = _enable(tmp_path)
    hook_registry.install(settings, event="Stop", command=agent_wiring.hook_command(PY, REPO, "claude-code"))
    hook_registry.install(settings, event="SessionStart",
                          command=agent_wiring.recall_hook_command(PY, REPO, "claude-code"))
    row = _row(_probe(tmp_path), "claude-code")
    assert row["connect"] == [] and "Stop" in row["detail"] and "SessionStart" in row["detail"]
    assert "./install.sh" in row["detail"]


def test_the_setup_prompt_runs_nothing_when_the_plugin_is_on(tmp_path):
    _enable(tmp_path)
    setup = agent_wiring.setup("claude-code", home=tmp_path, memory_root=Path("/M"), repo=REPO, python=PY,
                               resolve=lambda n: n, cicada_home=tmp_path / ".cicada")
    assert setup["argv"] == [] and setup["display"] == [] and "mcp add" not in setup["prompt"]
    plain = agent_wiring.setup("claude-code", home=tmp_path / "other", memory_root=Path("/M"), repo=REPO, python=PY,
                               resolve=lambda n: n, cicada_home=tmp_path / ".cicada")
    assert plain["argv"], "without the plugin the prompt is unchanged"


# --------------------------------------------------------------------------- make doctor says which door is active


def _doctor(tmp_path: Path, settings: dict, *, launcher: bool = True) -> str:
    home, bin_dir = tmp_path / "home", tmp_path / "bin"
    (home / ".claude").mkdir(parents=True)
    bin_dir.mkdir()
    (home / ".claude" / "settings.json").write_text(json.dumps(settings))
    _installed(home / ".claude")
    if launcher:
        _exe(home / ".cicada" / "bin" / "cicada-hook", "exit 0\n")
    _exe(bin_dir / "curl", "exit 7\n")
    _exe(bin_dir / "claude", 'if [ "$1 $2" = "mcp list" ]; then echo "cicada: /x - ok"; fi\nexit 0\n')
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "CICADA_MEMORY_PATH": str(tmp_path / "memory"),
           "CICADA_PORT": "1", "CICADA_HOME": str(home / ".cicada"), "CICADA_DOCTOR_PROBE": "0"}
    done = subprocess.run(["/bin/bash", str(ROOT / "scripts" / "doctor.sh")], env=env, capture_output=True,
                          text=True, timeout=120)
    return re.sub(r"\x1b\[[0-9;]*m", "", done.stdout)


def test_doctor_says_the_plugin_is_claude_code_s_door_and_flags_a_double_registration(tmp_path):
    settings = {"enabledPlugins": {"cicada@cicada": True}}
    hook_registry.install(tmp_path / "s.json", event="Stop",
                          command='"/x/api/.venv/bin/python" "/x/api/hooks/capture.py" --harness claude-code')
    settings["hooks"] = _json(tmp_path / "s.json")["hooks"]
    out = _doctor(tmp_path, settings)
    assert "claude: the Cicada plugin (cicada@cicada)" in out
    assert "MCP server 'cicada' is registered twice" in out
    assert "Cicada's hooks are in both the plugin and" in out and "Stop" in out
    assert "The plugin runs " + str(tmp_path / "home" / ".cicada" / "bin" / "cicada-hook") in out
    assert "Session-capture Stop hook not registered" not in out, "the settings-file checks are not asked"


def test_doctor_without_the_plugin_reads_install_sh_s_entries(tmp_path):
    out = _doctor(tmp_path, {})
    assert "claude: install.sh's hooks and MCP entry" in out
    assert "MCP server 'cicada' registered" in out and "Session-capture Stop hook" in out


def test_doctor_says_when_the_plugin_has_no_cicada_to_run(tmp_path):
    out = _doctor(tmp_path, {"enabledPlugins": {"cicada@cicada": True}}, launcher=False)
    assert "claude: install.sh's hooks and MCP entry (the Cicada plugin is enabled but can't run)" in out
    assert "The Cicada plugin is enabled but it has no Cicada to run" in out
    assert "Session-capture Stop hook" in out, "install.sh's entries are checked, as they are the door"


# --------------------------------------------------------------------------- the version stamp


def test_check_version_holds_the_plugin_manifest_to_version(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts" / "release"))
    try:
        import check_version
    finally:
        sys.path.pop(0)
    (tmp_path / "VERSION").write_text("1.2.3\n")
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "pyproject.toml").write_text('[project]\nname = "cicada-api"\nversion = "1.2.3"\n')
    (tmp_path / "api" / "uv.lock").write_text('[[package]]\nname = "cicada-api"\nversion = "1.2.3"\n')
    manifest = tmp_path / check_version.PLUGIN_MANIFEST
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": "cicada", "version": "1.2.3"}))
    assert check_version.agree(tmp_path) == "1.2.3"
    manifest.write_text(json.dumps({"name": "cicada", "version": "1.2.2"}))
    with pytest.raises(check_version.VersionError, match="plugin.json"):
        check_version.agree(tmp_path)
