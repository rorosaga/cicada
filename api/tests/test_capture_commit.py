"""G132 phase 1 — the capture commit (ruling 51e1): while the home publishes, only the episodes the capture writers
wrote are committed, once settled, only while their hash still matches, as `cicada` with trigger `sync/capture`,
under write admission, never while Sleep writes, never another path; someone else's edit stays theirs. Synthetic
banks and placeholder words only."""
from __future__ import annotations

import pytest

from _sync_home import git
from _synthetic_bank import _bank
from api.services import capture_commit, sleep_cycle, sync_publish
from api.services import transcript_capture as tc

SID = "11111111-2222-4333-8444-555555555555"
SID2 = "22222222-3333-4444-8555-666666666666"


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_SYNC_PUBLISH", "on")
    monkeypatch.setattr(capture_commit, "AUTOSTART", False)
    monkeypatch.setattr(capture_commit, "_BANKS", {})
    monkeypatch.setattr(tc, "_episode_cache", {}, raising=False)
    return _bank(tmp_path)


def _conv(*turns):
    return {"kept": [{"role": r, "text": t} for r, t in turns], "gap": None, "summary": {}}


def _capture(bank, sid, *turns, size=None):
    n = size or sum(len(t) for _, t in turns) * 10
    return tc.capture_posted(bank, harness="claude-code", session_id=sid, conversation=_conv(*turns),
                             transcript_bytes=n, transcript_size=n, cwd="/home/example/alpha", keep_assistant=True)


def _later(bank, extra=0.0):
    return max(r.at for r in capture_commit._bank(bank).records.values()) + capture_commit.SETTLE_S + 0.1 + extra


def _last(bank, fmt="%s"):
    return git(bank, "log", "-1", f"--format={fmt}").strip()


def test_only_the_written_episode_is_committed_as_cicada_once_settled(bank):
    other_episode = bank / "episodes" / "ep_2026-09-03_001.md"
    other_episode.write_text("---\nid: ep_2026-09-03_001\n---\nthe person's own note\n", encoding="utf-8")
    (bank / "entities" / "alpha-project.md").write_text("hand edit\n", encoding="utf-8")
    (bank / "_state.md").write_text("cursor\n", encoding="utf-8")
    result = _capture(bank, SID, ("user", "plan alpha"), ("assistant", "done"))
    rel = f"episodes/{result.episode_id}.md"
    assert list(capture_commit.pending(bank)) == [rel]
    head = _last(bank, "%H")
    assert capture_commit.sweep(bank, now=_later(bank, -1.0)) == 0      # not settled yet
    assert capture_commit.sweep(bank, now=_later(bank)) == 1
    assert _last(bank, "%H") != head
    assert _last(bank, "%(trailers:key=Cicada-Author,valueonly)") == "cicada"
    assert "trigger: sync/capture" in _last(bank, "%B")
    assert git(bank, "show", "--name-only", "--format=", "HEAD").split() == [rel]
    dirty = git(bank, "status", "--porcelain")
    assert "ep_2026-09-03_001.md" in dirty and "alpha-project.md" in dirty and "_state.md" in dirty
    assert rel not in dirty and capture_commit.pending(bank) == {}


def test_an_edit_after_the_writer_stays_uncommitted(bank):
    result = _capture(bank, SID, ("user", "plan alpha"))
    path = bank / "episodes" / f"{result.episode_id}.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nthe person's hand edit\n", encoding="utf-8")
    head = _last(bank, "%H")
    assert capture_commit.sweep(bank, now=_later(bank)) == 0
    assert _last(bank, "%H") == head and capture_commit.pending(bank) == {}
    assert path.name in git(bank, "status", "--porcelain")


def test_never_while_sleep_writes_and_then_once_it_is_done(bank, monkeypatch):
    _capture(bank, SID, ("user", "plan alpha"))
    when = _later(bank)
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)
    assert capture_commit.sweep(bank, now=when) == 0 and capture_commit.pending(bank)
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: False)
    assert capture_commit.sweep(bank, now=when) == 1


def test_someone_elses_edit_under_the_write_is_kept_apart_without_an_author(bank):
    first = _capture(bank, SID, ("user", "plan alpha"))
    assert capture_commit.sweep(bank, now=_later(bank)) == 1
    path = bank / "episodes" / f"{first.episode_id}.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nthe person's hand edit\n", encoding="utf-8")
    hand = path.read_bytes()
    _capture(bank, SID, ("user", "plan alpha"), ("assistant", "done"), ("user", "and beta"))
    when = _later(bank, capture_commit.MIN_INTERVAL_S)
    assert capture_commit.sweep(bank, now=when) == 2
    subjects = git(bank, "log", "-2", "--format=%s").splitlines()
    assert subjects[0].startswith("Capture ") and subjects[1].startswith("Uncommitted edit kept apart")
    assert git(bank, "log", "-1", "--format=%(trailers:key=Cicada-Author,valueonly)", "HEAD").strip() == "cicada"
    assert git(bank, "log", "-1", "--format=%(trailers:key=Cicada-Author,valueonly)", "HEAD~1").strip() == ""
    rel = f"episodes/{first.episode_id}.md"
    assert git(bank, "show", f"HEAD~1:{rel}").encode() == hand
    assert path.name not in git(bank, "status", "--porcelain")


def test_bursts_coalesce_under_the_minimum_interval(bank):
    _capture(bank, SID, ("user", "plan alpha"))
    first_due = _later(bank)
    assert capture_commit.sweep(bank, now=first_due) == 1
    _capture(bank, SID2, ("user", "plan beta"))
    _capture(bank, SID, ("user", "plan alpha"), ("assistant", "done"))
    assert capture_commit.sweep(bank, now=first_due + 15) == 0    # inside the minimum interval
    assert capture_commit.sweep(bank, now=first_due + capture_commit.MIN_INTERVAL_S + 1) == 1
    assert len(git(bank, "show", "--name-only", "--format=", "HEAD").split()) == 2   # both in one commit


def test_sleeps_later_commit_is_unchanged(bank):
    from api.services import git_service, markdown_parser

    result = _capture(bank, SID, ("user", "plan alpha"))
    capture_commit.sweep(bank, now=_later(bank))
    path = bank / "episodes" / f"{result.episode_id}.md"
    stored = markdown_parser.parse(path)
    markdown_parser.write(path, {**stored.frontmatter, "processed": True, "processed_by": "sleep"}, stored.body)
    assert git_service.commit_changes_sync(bank, "Sleep cycle 2026-09-04\n\nCicada-Author: claude") is not None
    assert path.name in git(bank, "show", "--name-only", "--format=", "HEAD")
    assert capture_commit.pending(bank) == {}


def test_off_records_nothing_and_writes_nothing_under_sync(bank, monkeypatch, tmp_path):
    monkeypatch.setenv("CICADA_SYNC_PUBLISH", "off")
    _capture(bank, SID, ("user", "plan alpha"))
    assert capture_commit.pending.__module__   # the module is loaded, and still:
    assert not (tmp_path / "home" / "sync").exists()
    assert capture_commit.sweep(bank, now=1e12) == 0
    assert not sync_publish.publishable(bank)


def test_a_demo_bank_is_never_recorded(bank, monkeypatch):
    from api.services import demo_guard

    (bank / demo_guard.MANIFEST).write_text(f"kind: {demo_guard.DEMO_KIND}\n")
    assert not capture_commit.recording(bank)


def test_the_background_step_commits_then_stops(bank, monkeypatch):
    import time

    monkeypatch.setattr(capture_commit, "AUTOSTART", True)
    monkeypatch.setattr(capture_commit, "SETTLE_S", 0.2)
    monkeypatch.setattr(capture_commit, "MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(capture_commit, "_TICK_MIN_S", 0.05)
    head = _last(bank, "%H")
    _capture(bank, SID, ("user", "plan alpha"))
    deadline = time.time() + 10
    while time.time() < deadline and (_last(bank, "%H") == head or capture_commit._THREAD is not None):
        time.sleep(0.05)
    assert _last(bank, "%H") != head and capture_commit.pending(bank) == {}
    assert capture_commit._THREAD is None   # nothing is left running once no record waits
