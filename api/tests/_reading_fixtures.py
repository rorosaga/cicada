"""Shared setup for the G166 reading tests — never collected (underscore prefix).

A synthetic git bank, the stdio server pointed at it, agent reading switched on
(acknowledged; no site allowed unless a test names one), and helpers that save a link the way
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


def enable(*, sites=()) -> None:
    """Master switch on, acknowledged, and EXACTLY the named sites allowed (the surfaced-site
    check is bypassed: these tests build the waiting pages themselves)."""
    patch = {s: True for s in sites} | {s: False for s in reading_settings.allowed_sites() if s not in sites}
    reading_settings.update(agent_enabled_=True, acknowledge=True, sites=patch, surfaced=set(sites))


def ask(memory: Path, url: str) -> dict:
    return asyncio.run(reading_service.ask(memory, url))


def save(memory: Path, url: str, *, origin: str = "linkedin-saved", **frontmatter) -> str:
    """Save a link the way a connector or a bookmark import does, WITHOUT a fetch and without an ask
    (``defer_enrich``), optionally stamping page frontmatter (``fetch_status="blocked"``, ...) or a
    body (``body="## Description\\n\\n..."``). Returns the media entity id."""
    from api.services import media_ingestor

    idx = media_ingestor.load_url_index(memory)
    item = media_ingestor.RawItem(url=url, origin=origin, defer_enrich=True)
    result = asyncio.run(media_ingestor.ingest_one(item, memory, None, idx))
    media_ingestor.save_url_index(memory, idx)
    path = memory / "entities" / f"{result.media_entity_id}.md"
    body_text = frontmatter.pop("body", None)
    if frontmatter or body_text is not None:
        parsed = markdown_parser.parse(path)
        parsed.frontmatter.update(frontmatter)
        markdown_parser.write(path, parsed.frontmatter,
                              parsed.body if body_text is None else (parsed.body.rstrip() + "\n\n" + body_text + "\n"))
    return result.media_entity_id


def put_page(memory: Path, slug: str, url: str, *, origin: str = "linkedin-saved", saved: str = "2026-09-01",
             body: str = "", title: str | None = None, **frontmatter) -> str:
    """A saved media page written straight to disk (fast; no ingest) and its url-index entry, for tests
    that need many pages or exact stamps. Returns the entity id."""
    from api.services import media_ingestor

    eid = f"media-{slug}"
    fm = {"name": title or slug, "type": "media", "status": "active", "confidence": 0.7, "created": saved,
          "last_referenced": saved, "saved_at": saved, "origin": origin, "source_episodes": [], "tags": [],
          "related": [], "version": 1,
          "media": {"url": url, "media_type": "url", "url_hash": media_ingestor.url_hash(url)}}
    fm.update(frontmatter)
    markdown_parser.write(memory / "entities" / f"{eid}.md", fm, body or "## Summary\nA saved link.\n")
    idx = media_ingestor.load_url_index(memory)
    idx[media_ingestor.url_hash(url)] = {"media_entity_id": eid, "url": url, "title": title or slug}
    media_ingestor.save_url_index(memory, idx)
    return eid


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
