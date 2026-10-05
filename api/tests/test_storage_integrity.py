"""Audit 2026-10-02 batch 1: atomic markdown replacement (A02), revision-safe
episode retirement (A01), and cross-process episode-id allocation (K01).

Three separate guarantees, tested separately. Synthetic banks under pytest's
tmp only; no model, no network.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from api.services import bank_index, episode_ids, markdown_parser, mcp_tools, sleep_cycle
from api.services import episode_staging as st
from api.services import transcript_capture as tc

SID = "11111111-2222-4333-8444-555555555555"


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    yield memory
    bank_index.invalidate(memory)


def _stray_temps(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.name.endswith(".tmp"))


# --- A02: atomic replacement ------------------------------------------------


def test_a_failed_rewrite_leaves_the_original_bytes_intact(tmp_path):
    page = tmp_path / "alpha-project.md"
    markdown_parser.write(page, {"id": "alpha-project"}, "Original synthetic body.")
    original = page.read_bytes()
    # A lone surrogate cannot be encoded: the write fails after the file was opened.
    with pytest.raises(UnicodeEncodeError):
        markdown_parser.write(page, {"id": "alpha-project"}, "Replacement \ud800 body.")
    assert page.read_bytes() == original
    assert _stray_temps(tmp_path) == []


def test_a_rewrite_keeps_the_permission_bits(tmp_path):
    page = tmp_path / "alpha-project.md"
    markdown_parser.write(page, {"id": "alpha-project"}, "One.")
    os.chmod(page, 0o640)
    markdown_parser.write(page, {"id": "alpha-project"}, "Two.")
    assert stat.S_IMODE(page.stat().st_mode) == 0o640
    assert markdown_parser.parse(page).body == "Two."


def test_a_new_file_gets_the_umask_mode(tmp_path):
    old = os.umask(0o022)
    try:
        markdown_parser.write(tmp_path / "bob-example.md", {"id": "bob-example"}, "Body.")
        markdown_parser.write_new(tmp_path / "carol-example.md", {"id": "carol-example"}, "Body.")
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "bob-example.md").stat().st_mode) == 0o644
    assert stat.S_IMODE((tmp_path / "carol-example.md").stat().st_mode) == 0o644


def test_a_symlinked_page_stays_a_symlink(tmp_path):
    target = tmp_path / "real.md"
    markdown_parser.write(target, {"id": "real"}, "One.")
    link = tmp_path / "alias.md"
    link.symlink_to(target)
    markdown_parser.write(link, {"id": "real"}, "Two.")
    assert link.is_symlink()
    assert markdown_parser.parse(target).body == "Two."


def test_write_new_never_replaces_a_file(tmp_path):
    page = tmp_path / "ep_2026-10-05_001.md"
    markdown_parser.write_new(page, {"id": "first"}, "First.")
    with pytest.raises(FileExistsError):
        markdown_parser.write_new(page, {"id": "second"}, "Second.")
    assert markdown_parser.parse(page).body == "First."
    assert _stray_temps(tmp_path) == []


# --- K01: unique allocation across writers and processes ---------------------


def _stale_mint(monkeypatch, episode_id: str):
    """What a concurrent writer in another process causes: the id this writer
    minted was taken between its scan and its write."""
    real = episode_ids.next_episode_id
    calls = {"n": 0}

    def stale(episodes_dir, ep_date):
        calls["n"] += 1
        return episode_id if calls["n"] == 1 else real(episodes_dir, ep_date)

    monkeypatch.setattr(episode_ids, "next_episode_id", stale)


def _occupy(bank: Path, episode_id: str) -> bytes:
    path = bank / "episodes" / f"{episode_id}.md"
    markdown_parser.write(path, {"id": episode_id, "source": "other-writer", "processed": False}, "Other writer.")
    return path.read_bytes()


def test_mcp_save_never_overwrites_an_id_another_process_took(bank, monkeypatch):
    from datetime import datetime

    taken = f"ep_{datetime.now().strftime('%Y-%m-%d')}_001"
    before = _occupy(bank, taken)
    _stale_mint(monkeypatch, taken)
    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="s", harness="codex")
    mcp_tools.save_episode(ctx, "A synthetic agent note.", "alpha-project")
    assert (bank / "episodes" / f"{taken}.md").read_bytes() == before
    files = sorted((bank / "episodes").glob("ep_*.md"))
    assert len(files) == 2
    saved = markdown_parser.parse(files[1])
    assert saved.body == "A synthetic agent note." and saved.frontmatter["id"] == files[1].stem


def _transcript(turns) -> str:
    lines = []
    for role, text in turns:
        content = text if role == "user" else [{"type": "text", "text": text}]
        lines.append(json.dumps({"type": role, "uuid": "u", "timestamp": "2026-09-03T10:00:00.000Z",
                                 "sessionId": SID, "cwd": "/tmp/alpha-project",
                                 "message": {"role": role, "content": content}}))
    return "\n".join(lines) + "\n"


@pytest.fixture
def claude_root(tmp_path, monkeypatch):
    root = tmp_path / "claude-projects" / "-tmp-alpha-project"
    root.mkdir(parents=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: root.parent)
    monkeypatch.setattr(tc, "_episode_cache", {})
    return root


def test_transcript_capture_never_overwrites_an_id_another_process_took(bank, claude_root, monkeypatch):
    before = _occupy(bank, "ep_2026-09-03_001")
    _stale_mint(monkeypatch, "ep_2026-09-03_001")
    path = claude_root / f"{SID}.jsonl"
    path.write_text(_transcript([("user", "Q1")]), encoding="utf-8")
    r = tc.capture_transcript(bank, harness="claude-code", session_id=SID, transcript_path=str(path),
                              cwd=None, keep_assistant=True)
    assert r.status == "created" and r.episode_id == "ep_2026-09-03_002"
    assert (bank / "episodes" / "ep_2026-09-03_001.md").read_bytes() == before
    assert markdown_parser.parse(bank / "episodes" / "ep_2026-09-03_002.md").frontmatter["id"] == "ep_2026-09-03_002"


def _draft(sid: str, text: str, ts: str = "2026-09-01T10:00:00+00:00") -> st.EpisodeDraft:
    return st.EpisodeDraft(title="alpha-project › notes.md", source_id=sid, source_updated_at=ts, timestamp=ts,
                           original_date=ts[:10], source="folder", origin="folder", body=text, writer="folder")


def test_the_stager_never_overwrites_an_id_another_process_took(bank, monkeypatch):
    episodes = bank / "episodes"
    real = episode_ids.max_suffix_by_date
    # The stager's scan ran before another process wrote _001.
    monkeypatch.setattr(episode_ids, "max_suffix_by_date", lambda d: {})
    before = _occupy(bank, "ep_2026-09-01_001")
    result = st.stage([_draft("folder-a", "Synthetic note.")], episodes, bank="memory")
    monkeypatch.setattr(episode_ids, "max_suffix_by_date", real)
    assert result.created == 1
    assert (episodes / "ep_2026-09-01_001.md").read_bytes() == before
    assert markdown_parser.parse(episodes / "ep_2026-09-01_002.md").body == "Synthetic note."
    assert result.episode_ids["folder-a"] == "ep_2026-09-01_002"


def _create_in_child(args):
    episodes_dir, n = args
    from api.services import episode_ids as ids

    fm = {"id": ids.next_episode_id(Path(episodes_dir), "2026-10-05"), "processed": False}
    return ids.create_episode(Path(episodes_dir), fm, f"Synthetic capture {n}.")


def test_independent_processes_mint_distinct_ids(bank):
    episodes = bank / "episodes"
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(8) as pool:
        ids = pool.map(_create_in_child, [(str(episodes), n) for n in range(16)])
    assert len(set(ids)) == 16
    files = sorted(episodes.glob("ep_2026-10-05_*.md"))
    assert len(files) == 16
    assert sorted(markdown_parser.parse(f).body for f in files) == sorted(f"Synthetic capture {n}." for n in range(16))
    assert all(markdown_parser.parse(f).frontmatter["id"] == f.stem for f in files)


def test_the_episode_lock_excludes_another_process(bank):
    episodes = bank / "episodes"
    probe = (
        "import fcntl, os, sys\n"
        "fd = os.open(sys.argv[1], os.O_RDONLY)\n"
        "try:\n"
        "    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); print('acquired')\n"
        "except BlockingIOError:\n"
        "    print('blocked')\n"
    )
    with episode_ids.episode_lock(episodes):
        with episode_ids.episode_lock(episodes):  # re-entrant within a thread
            held = subprocess.run([sys.executable, "-c", probe, str(episodes)], capture_output=True, text=True)
    free = subprocess.run([sys.executable, "-c", probe, str(episodes)], capture_output=True, text=True)
    assert held.stdout.strip() == "blocked"
    assert free.stdout.strip() == "acquired"


# --- A01: retire only the revision Sleep read --------------------------------


def _queue_ids(bank: Path) -> list[str]:
    bank_index.invalidate(bank)
    return [e["id"] for e in sleep_cycle._get_unprocessed_episodes(bank)]


def test_a_resumed_session_captured_mid_cycle_stays_queued(bank, claude_root):
    path = claude_root / f"{SID}.jsonl"
    path.write_text(_transcript([("user", "Q1")]), encoding="utf-8")
    first = tc.capture_transcript(bank, harness="claude-code", session_id=SID, transcript_path=str(path),
                                  cwd=None, keep_assistant=True)
    selected = sleep_cycle._get_unprocessed_episodes(bank)
    assert [e["id"] for e in selected] == [first.episode_id]

    # The person keeps talking while Sleep extracts the first revision.
    path.write_text(_transcript([("user", "Q1"), ("assistant", "A1"), ("user", "Later synthetic correction")]),
                    encoding="utf-8")
    second = tc.capture_transcript(bank, harness="claude-code", session_id=SID, transcript_path=str(path),
                                   cwd=None, keep_assistant=True)
    assert second.status == "updated"

    retired = sleep_cycle._mark_episodes_processed(selected)
    ep = markdown_parser.parse(bank / "episodes" / f"{first.episode_id}.md")
    assert retired == 0
    assert ep.frontmatter["processed"] is False and "processed_by" not in ep.frontmatter
    assert "Later synthetic correction" in ep.body
    assert _queue_ids(bank) == [first.episode_id]


def test_a_source_keyed_edit_mid_cycle_stays_queued(bank):
    episodes = bank / "episodes"
    st.stage([_draft("folder-a", "First synthetic revision.")], episodes, bank="memory")
    selected = sleep_cycle._get_unprocessed_episodes(bank)
    st.stage([_draft("folder-a", "Second synthetic revision.", ts="2026-09-01T11:00:00+00:00")], episodes,
             bank="memory")
    assert sleep_cycle._mark_episodes_processed(selected) == 0
    (path,) = episodes.glob("ep_*.md")
    parsed = markdown_parser.parse(path)
    assert parsed.frontmatter["processed"] is False and parsed.body == "Second synthetic revision."


def test_an_unchanged_episode_retires_once(bank):
    episodes = bank / "episodes"
    st.stage([_draft("folder-a", "Only revision.")], episodes, bank="memory")
    selected = sleep_cycle._get_unprocessed_episodes(bank)
    assert sleep_cycle._mark_episodes_processed(selected) == 1
    (path,) = episodes.glob("ep_*.md")
    fm = markdown_parser.parse(path).frontmatter
    assert fm["processed"] is True and fm["processed_by"] == "sleep"
    assert _queue_ids(bank) == []


def test_retirement_waits_for_another_holder_of_the_episode_lock(bank):
    episodes = bank / "episodes"
    st.stage([_draft("folder-a", "Only revision.")], episodes, bank="memory")
    selected = sleep_cycle._get_unprocessed_episodes(bank)
    done = threading.Event()

    def retire():
        sleep_cycle._mark_episodes_processed(selected)
        done.set()

    with episode_ids.episode_lock(episodes):
        worker = threading.Thread(target=retire)
        worker.start()
        time.sleep(0.2)
        assert not done.is_set()
        # A capture edit inside the critical section: Sleep must see it.
        (path,) = episodes.glob("ep_*.md")
        parsed = markdown_parser.parse(path)
        markdown_parser.write(path, parsed.frontmatter, "Edited inside the lock.")
    worker.join(5)
    assert done.is_set()
    assert markdown_parser.parse(path).frontmatter["processed"] is False
