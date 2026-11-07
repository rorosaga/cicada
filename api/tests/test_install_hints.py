"""2026-11-06 — a stranger's Mac has no Node: the missing-tool words give the vendor's own installer, from one place."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from api.config import Settings
from api.services import agent_engine, sleep_engine_prefs
from api.services.connections import claude_cli, codex_cli, install_hints
from api.services.connections.base import CliResult
from api.services.connections.registry import get_registry

ROOT = Path(__file__).resolve().parents[2]


def _gone(monkeypatch):
    monkeypatch.setattr(claude_cli, "resolve_binary", lambda _n: None)
    monkeypatch.setattr(codex_cli, "resolve_binary", lambda _n: None)


def test_the_lines_need_no_node():
    for line in (install_hints.CLAUDE_INSTALL_COMMAND, install_hints.CODEX_INSTALL_COMMAND):
        assert line.startswith("curl -fsSL https://") and "npm" not in line


def test_each_missing_plan_row_carries_the_command_apart_from_its_words(monkeypatch):
    _gone(monkeypatch)
    claude = asyncio.run(claude_cli.ClaudePlanAdapter().status())
    codex = asyncio.run(codex_cli.CodexPlanAdapter().status())
    assert not claude.available and claude.next_command == install_hints.CLAUDE_INSTALL_COMMAND
    assert not codex.available and codex.next_command == install_hints.CODEX_INSTALL_COMMAND
    assert claude.detail == install_hints.CLAUDE_MISSING and codex.detail == install_hints.CODEX_MISSING
    assert claude.model_dump(by_alias=True)["nextCommand"] == install_hints.CLAUDE_INSTALL_COMMAND


def test_a_tool_that_is_here_carries_no_command(monkeypatch):
    monkeypatch.setattr(claude_cli, "resolve_binary", lambda _n: "/usr/local/bin/claude")

    async def run(_argv):
        return CliResult(0, '{"loggedIn": false}', "")

    status = asyncio.run(claude_cli.ClaudePlanAdapter(runner=run).status())
    assert status.available and status.next_command is None


def test_the_engine_cards_carry_the_same_command(monkeypatch):
    _gone(monkeypatch)
    cfg = Settings()
    cards = asyncio.run(sleep_engine_prefs._candidates(cfg, get_registry(cfg), mode="auto", model=None))
    by_id = {c.id: c for c in cards}
    assert by_id["agent"].next_command == install_hints.CLAUDE_INSTALL_COMMAND
    assert by_id["codex"].next_command == install_hints.CODEX_INSTALL_COMMAND


def test_a_sleep_preflight_names_the_same_line():
    ok, sentence = agent_engine.probe(runner=lambda *_a, **_k: CliResult(127, "", ""))
    assert not ok and install_hints.CLAUDE_INSTALL_COMMAND in sentence


def test_no_surface_spells_its_own_install_line():
    """The app and the engines never disagree: the command lives in `install_hints` and nowhere else."""
    needles = (install_hints.CLAUDE_INSTALL_COMMAND, install_hints.CODEX_INSTALL_COMMAND, "npm i -g @anthropic-ai",
               "npm i -g @openai", "npm install -g @openai", "npm install -g @anthropic")
    own = Path(install_hints.__file__).resolve()
    roots = [ROOT / "api", ROOT / "app" / "CicadaApp" / "Sources", ROOT / "mcp", ROOT / "scripts", ROOT / "install.md"]
    found = []
    for root in roots:
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.suffix in {".py", ".swift", ".sh"}]
        for path in files:
            if path.resolve() == own or "tests" in path.parts or ".venv" in path.parts or ".build" in path.parts:
                continue
            text = path.read_text(errors="ignore")
            found += [f"{path.relative_to(ROOT)}: {n}" for n in needles if n in text]
    assert not found, found
