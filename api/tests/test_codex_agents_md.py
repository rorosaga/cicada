"""Codex is told to use Cicada: one marked block in ``~/.codex/AGENTS.md`` (2026-10-23).

A live test found Codex with Cicada's server attached and no start-of-session note never calling a Cicada tool, while
the primer claimed "AGENTS.md points here" and nothing wrote that line. ``registry.py agents-md-install`` adds the
block; ``GET /agents/wiring`` puts that step in Codex's ``connect`` (what the Agents page's Connect and ``cicada
setup`` run); ``install.sh --uninstall`` removes it. Every test runs on a scratch HOME under ``tmp_path``: nothing
here opens the real ``~/.codex``.
"""
from __future__ import annotations

import asyncio
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from api import cli_setup
from api.hooks import registry
from api.services import agent_wiring
from api.services.connections import base

REPO = Path("/R/cicada")
PY = "/R/cicada/api/.venv/bin/python"
MEM = Path("/M/memory")
REGISTRY = Path(__file__).resolve().parents[1] / "hooks" / "registry.py"
OWN = "# My rules\n\nAlways run the tests.\r\nKeep this line exactly.\n"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return tmp_path


def _agents(home: Path) -> Path:
    return home / ".codex" / "AGENTS.md"


def _raw(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def test_install_adds_one_block_and_keeps_the_rest_byte_for_byte(home):
    path = _agents(home)
    path.parent.mkdir(parents=True)
    path.write_bytes(OWN.encode("utf-8"))
    assert registry.agents_md_install(path) == "added"
    text = _raw(path)
    assert text.startswith(OWN) and text.count(registry.AGENTS_MD_BEGIN) == 1
    assert "cicada_continue()" in text and "cicada_recall(query)" in text
    assert registry.agents_md_status(path) == "present"
    assert registry.agents_md_install(path) == "present" and _raw(path) == text, "a second run never duplicates"
    assert registry.agents_md_uninstall(path) == 1
    assert _raw(path) == OWN, "removing Cicada leaves the person's file as it was"


def test_a_missing_file_is_created_and_removed_whole(home):
    path = _agents(home)
    assert registry.agents_md_status(path) == "absent"
    assert registry.agents_md_install(path) == "added"
    assert _raw(path) == registry.AGENTS_MD_BLOCK
    assert registry.agents_md_uninstall(path) == 1 and not path.exists()
    assert registry.agents_md_uninstall(path) == 0


def test_older_words_are_replaced_in_place_and_duplicates_collapse(home):
    path = _agents(home)
    path.parent.mkdir(parents=True)
    old = f"{registry.AGENTS_MD_BEGIN}\nold words\n{registry.AGENTS_MD_END}\n"
    path.write_text(f"top\n{old}middle\n{old}bottom\n", encoding="utf-8")
    assert registry.agents_md_status(path) == "stale"
    assert registry.agents_md_install(path) == "updated"
    assert _raw(path) == f"top\n{registry.AGENTS_MD_BLOCK}middle\nbottom\n"


@pytest.mark.parametrize("broken", [f"{registry.AGENTS_MD_BEGIN}\nno end\n",
                                    f"stray\n{registry.AGENTS_MD_END}\n"])
def test_unpaired_markers_are_never_touched(home, broken):
    path = _agents(home)
    path.parent.mkdir(parents=True)
    path.write_text(broken, encoding="utf-8")
    for call in (registry.agents_md_install, registry.agents_md_uninstall, registry.agents_md_status):
        with pytest.raises(registry.RegistryError):
            call(path)
    assert _raw(path) == broken
    assert agent_wiring.agents_md_state(home) == "invalid"


def test_the_command_line_verbs(home):
    path = _agents(home)

    def run(action):
        return subprocess.run([sys.executable, str(REGISTRY), action, "--settings", str(path)],
                              capture_output=True, text=True, timeout=30)

    assert run("agents-md-status").returncode == 1
    assert run("agents-md-install").stdout.startswith("added")
    assert run("agents-md-install").stdout.startswith("present")
    assert run("agents-md-status").returncode == 0
    assert run("agents-md-uninstall").returncode == 0 and not path.exists()


def _probe(home: Path, rc: int = 1):
    async def runner(argv, *, timeout):
        return base.CliResult(rc, "", "")
    return asyncio.run(agent_wiring.probe(home=home, memory_root=MEM, repo=REPO, python=PY, runner=runner,
                                          resolve=lambda name: name if name in ("claude", "codex") else None))


def _codex(data) -> dict:
    return next(a for a in data["agents"] if a["id"] == "codex")


def test_codex_connect_carries_the_agents_md_step_until_the_block_is_there(home):
    row = _codex(_probe(home))
    assert row["agents_md"] == "off"
    step = row["connect"][-1]
    assert step["step"] == "agents-md" and step["display"] == shlex.join(step["argv"])
    assert step["argv"] == [PY, f"{REPO}/api/hooks/registry.py", "agents-md-install", "--settings",
                            str(_agents(home))]
    assert step["touches"] == ["~/.codex/AGENTS.md"]
    assert all(s["step"] != "agents-md" for s in next(a for a in _probe(home)["agents"]
                                                      if a["id"] == "claude-code")["connect"])
    registry.agents_md_install(_agents(home))
    row = _codex(_probe(home, rc=0))
    assert row["agents_md"] == "on" and all(s["step"] != "agents-md" for s in row["connect"])


def test_a_probe_that_timed_out_offers_no_block(home):
    row = _codex(_probe(home, rc=124))
    assert row["recall"] == "unknown" and all(s["step"] != "agents-md" for s in row["connect"])


def test_codexs_session_end_flush_asks_for_three_seconds(home):
    flush = _codex(_probe(home))["flush_on"]
    end = next(s for s in flush if "SessionEnd" in s["argv"])
    assert end["argv"][-2:] == ["--timeout", "3"] and end["display"] == shlex.join(end["argv"])
    assert "--timeout" not in next(s for s in flush if "PreCompact" in s["argv"])["argv"]
    settings = home / ".codex" / "hooks.json"
    command = agent_wiring.hook_command(PY, REPO, "codex")
    registry.install(settings, event="SessionEnd", command=command)          # an install from before: 5 s
    assert registry.install(settings, event="SessionEnd", command=command, timeout=3) == "updated"
    assert registry.install(settings, event="SessionEnd", command=command, timeout=3) == "present"
    assert registry.install(settings, event="SessionEnd", command=command) == "present", "the default never rewrites"


class _Ui(cli_setup.Ui):
    def __init__(self):
        super().__init__(interactive=True)
        self.said: list[str] = []

    def say(self, text: str = "") -> None:
        self.said.append(text)

    def confirm(self, question: str, default: bool = True) -> bool:
        return True


def test_cicada_setup_runs_the_block_for_a_codex_already_connected(home):
    """A Codex wired before the block reaches Cicada (`recall: on`); setup still runs what `connect` lists."""
    registry_argv = [PY, f"{REPO}/api/hooks/registry.py", "agents-md-install", "--settings", str(_agents(home))]
    found = cli_setup.Found(server={"version": "x"}, agents=[
        {"id": "codex", "installed": True, "recall": "on",
         "connect": [{"step": "agents-md", "display": shlex.join(registry_argv), "argv": registry_argv}]}])
    ran: list[list[str]] = []
    assert cli_setup.connect_agents(found, _Ui(), lambda argv: ran.append(argv) or 0) == ["codex"]
    assert ran == [registry_argv]
