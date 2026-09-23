"""R-LS6 — every module that mints an episode id scrubs what it writes."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from _stdio_server import stdio_server

from api.services import calendar_registry, markdown_parser, media_ingestor, telegram_capture

REPO = Path(__file__).resolve().parents[2]
MINTERS = ("next_episode_id(", "max_suffix_by_date(")
# transcript_capture mints the id but its text is scrubbed inside the extractor
# (transcript_extract._Builder._add), so the lint reads the extractor for it.
DELEGATES = {"transcript_capture.py": "transcript_extract.py"}
SECRET = "sk-" + "Z" * 24


def _python_files():
    for root in (REPO / "api", REPO / "mcp"):
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in {".venv", "tests", "__pycache__"}]
            for name in filenames:
                if name.endswith(".py") and name != "episode_ids.py":
                    yield Path(dirpath) / name


def test_every_module_that_mints_an_episode_id_references_episode_scrub():
    offenders = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        if not any(m in text for m in MINTERS):
            continue
        target = DELEGATES.get(path.name)
        source = (path.parent / target).read_text(encoding="utf-8") if target else text
        if "episode_scrub" not in source:
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], f"episode writers that never scrub: {offenders}"


def test_the_lint_found_the_writers_it_exists_for():
    minted = {p.name for p in _python_files() if any(m in p.read_text(encoding="utf-8") for m in MINTERS)}
    # G135 moved the MCP tool bodies out of `mcp/server.py`: `save_episode` now
    # mints in `api/services/mcp_tools.py`, one implementation for stdio and remote.
    assert {"episode_staging.py", "telegram_capture.py", "media_ingestor.py", "notes_sync.py",
            "calendar_registry.py", "demo_bank.py", "mcp_tools.py", "transcript_capture.py"} <= minted


def test_telegram_writer_scrubs_before_hashing(tmp_path):
    memory = tmp_path / "memory"
    telegram_capture._default_save_episode(memory, f"note {SECRET} code: 123456")
    (path,) = (memory / "episodes").glob("*.md")
    body = markdown_parser.parse(path).body
    assert SECRET not in body and "123456" not in body


def test_calendar_writer_scrubs_a_meeting_passcode(tmp_path):
    event = calendar_registry.ICSEvent(
        uid="evt-1", summary="alpha-project sync", dtstart_iso="2026-07-14T10:00:00+00:00",
        dtend_iso=None, all_day=False, location=None,
        description="Join https://example.com/j/1 Passcode: 998877", sequence=0, recurring=False)
    ep_id = calendar_registry._write_calendar_episode(tmp_path / "episodes", event, "https://example.com/c.ics")
    body = markdown_parser.parse(tmp_path / "episodes" / f"{ep_id}.md").body
    assert "998877" not in body and "Passcode: [redacted]" in body


def test_media_writer_scrubs_a_saved_reason(tmp_path):
    item = media_ingestor.RawItem(url="https://example.com/a", reason=f"it has {SECRET}")
    meta = media_ingestor.MediaMeta(title="A")
    ep_id = media_ingestor.write_media_episode(tmp_path / "episodes", item, meta, "media-a")
    assert SECRET not in markdown_parser.parse(tmp_path / "episodes" / f"{ep_id}.md").body


def test_mcp_save_episode_scrubs(tmp_path, monkeypatch):
    # By FILE PATH (G135 R-R8): `mcp.server` now names the official SDK.
    server = stdio_server()
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    assert "Episode saved" in server.handle_save_episode(f"deploy key {SECRET}", "T")
    (path,) = (memory / "episodes").glob("*.md")
    assert SECRET not in markdown_parser.parse(path).body
