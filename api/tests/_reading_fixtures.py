"""Shared setup for the G166 reading tests — never collected (underscore prefix).

A synthetic git bank, the stdio server pointed at it, agent reading switched on
(acknowledged, `x` and `linkedin` allowed), and helpers that save a link the way
"Ask an agent" does — without a fetch. Placeholders only (bob-example.org,
alpha-project); nothing reads a real bank, `~/.cicada` or the network."""
from __future__ import annotations

import asyncio
import re
import subprocess
import urllib.request
from pathlib import Path

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api.services import markdown_parser, mcp_tools, reading_service, reading_settings
from api.services.claims import parse_claims

PUBLIC = "https://blog.bob-example.org/post/1"
WALLED = "https://x.com/alpha/status/1"
SUMMARY = "A post about how alpha indexes notes with sqlite-vec and why the index stays on the laptop."
EXCERPTS = [{"quote": "search is one lookup"}, {"quote": "we keep every vector on the laptop"}]


def _offline(*a, **k):
    raise OSError("no backend in this test")


def enable(*, hosts=("x", "linkedin")) -> None:
    reading_settings.update(agent_enabled_=True, acknowledge=True, agent_hosts=list(hosts))


def ask(memory: Path, url: str) -> dict:
    return asyncio.run(reading_service.ask(memory, url))


@pytest.fixture
def reading(tmp_path, monkeypatch):
    """(server, memory) with agent reading on and no link saved yet."""
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = _bank(tmp_path)
    (memory / "sources").mkdir(exist_ok=True)
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    monkeypatch.setattr(server, "SESSION", server.SessionIdentity("ses_read_fixed", "claude-code", None))
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    monkeypatch.setattr(urllib.request, "urlopen", _offline)
    enable()
    return server, memory


def record(server, url=PUBLIC, outcome="read", **kw):
    args = {"url": url, "outcome": outcome, **kw}
    if outcome == "read":
        args.setdefault("summary", SUMMARY)
        args.setdefault("excerpts", EXCERPTS)
    return server.handle_tool("cicada_record_read", args)


def ids(out: str) -> tuple[str, str, str]:
    return (re.search(r"entity `([^`]+)`", out).group(1), re.search(r"episode `(ep_[^`]+)`", out).group(1),
            re.search(r"claim `([^`]+)`", out).group(1))


def claims(memory: Path, eid: str):
    return parse_claims(markdown_parser.parse(memory / "entities" / f"{eid}.md").body)


def page(memory: Path, eid: str):
    return markdown_parser.parse(memory / "entities" / f"{eid}.md")


def git_log(memory: Path, n: int = 1) -> str:
    return subprocess.run(["git", "-C", str(memory), "log", f"-{n}", "--format=%s%n%b---"],
                          capture_output=True, text=True, check=True).stdout


def porcelain(memory: Path) -> str:
    return subprocess.run(["git", "-C", str(memory), "status", "--porcelain"], capture_output=True, text=True,
                          check=True).stdout
