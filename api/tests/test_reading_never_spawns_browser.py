"""G166 R-RW9 — Cicada never spawns a browser, and `--chrome` appears in no engine
argv. Measured for the spec (§8.2): adding `--chrome` to the pinned Claude argv
exposes 22 browser tools although `--safe-mode`, `--strict-mcp-config` and
`--tools ""` are all present — it overrides the locks. Reading with an agent is a
QUEUE the person's own agent works in its own harness (Route A); a spawned browse
call is a later, spike-gated slice with its own constant. Nothing in this slice
spawns anything, so this is a cheap lock: a future spawn cannot slip in through an
existing argv, and no module can start driving a browser unseen."""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from api.services import agent_engine, codex_engine

REPO = Path(__file__).resolve().parents[2]
DRIVERS = re.compile(
    r"\b(?:import|from)\s+(?:selenium|playwright|pyppeteer|splinter|mechanize|browser_use|browser_harness|"
    r"undetected_chromedriver|webbrowser)\b")
SPAWNED_BROWSERS = re.compile(r"""["'](?:google-chrome|chromium|chromium-browser|chromedriver|geckodriver|msedge)["']""")


def test_no_engine_argv_carries_chrome():
    assert not any("chrome" in flag.lower() for flag in agent_engine.PINNED_FLAGS)
    assert not any("chrome" in flag.lower() for flag in codex_engine.CODEX_PINNED)
    for kwargs in ({"model": "", "system_prompt": ""}, {"model": "sonnet", "system_prompt": "read"},
                   {"model": "opus", "system_prompt": "read", "effort": "high"},
                   {"model": "sonnet", "system_prompt": "--chrome", "json_schema": {"type": "object"}}):
        argv = agent_engine.build_argv(**kwargs)
        assert "--chrome" not in argv and not any(a.startswith("--chrome") for a in argv)
    argv = codex_engine.build_argv(model="gpt-5", effort="low", instructions_path=Path("/tmp/x"), cwd=Path("/tmp"))
    assert not any("chrome" in a.lower() for a in argv)


def _python_files():
    for root in (REPO / "api", REPO / "mcp"):
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in {".venv", "tests", "__pycache__"}]
            for name in filenames:
                if name.endswith(".py"):
                    yield Path(dirpath) / name


def test_no_module_imports_a_browser_driver_or_names_a_browser_binary():
    offenders = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        if DRIVERS.search(text) or SPAWNED_BROWSERS.search(text):
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], f"a module drives or spawns a browser: {offenders}"


def test_no_source_names_the_chrome_flag_outside_this_rule():
    offenders = []
    for path in _python_files():
        if "--chrome" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], f"--chrome appears in: {offenders}"


def test_the_reading_modules_import_no_process_spawner():
    """The reading modules are file and JSON work; only an agent's own tools read
    a page. None of them may spawn a process at all."""
    reading = ["reading_hosts", "reading_settings", "reading_asks", "reading_service", "reading_prompt", "page_read"]
    for name in reading:
        text = (REPO / "api" / "services" / f"{name}.py").read_text(encoding="utf-8")
        assert not re.search(r"\b(?:subprocess|os\.system|os\.exec|os\.spawn|asyncio\.create_subprocess)", text), name
    text = (REPO / "api" / "routers" / "reading.py").read_text(encoding="utf-8")
    assert "subprocess" not in text
