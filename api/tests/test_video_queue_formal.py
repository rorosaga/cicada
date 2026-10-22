"""The video queue's model-checking findings, reproduced against the real code (`.claude/skills/verify-video-queue`).

Each test drives the real functions in the order the TLC counterexample gives and fails today. They are
`xfail(strict=True)`, so a fix flips them to an unexpected pass and the marker must come off with it. Synthetic
banks only; the queue file lives under the conftest-isolated CICADA_HOME; the clock is injected."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from _video_fixtures import add_video, add_watch_episode, bank_with_videos, url_of
from api.services import mcp_tools, video_queue, video_state

T0 = datetime(2026, 9, 29, 14, 0, 0, tzinfo=timezone.utc)


def _at(minutes: float = 0) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _row(memory, key, now=None):
    return {r["key"]: r for r in video_queue.view(memory, now or _at(), holding=lambda: False)[0]}.get(key)


@pytest.fixture
def two_sessions(tmp_path, monkeypatch):
    memory, keys = bank_with_videos(tmp_path, 2)
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    a = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_a", harness="claude-code")
    b = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_b", harness="claude-code")
    return memory, keys, a, b


@pytest.mark.xfail(strict=True, reason="F1: video_queue.release (video_queue.py:661) never compares the session")
def test_f1_a_session_cannot_hand_back_another_sessions_lease(two_sessions):
    memory, keys, a, b = two_sessions
    video_queue.put(memory, keys[0], "watch")
    assert "Leased 1 video" in mcp_tools.video_claim(a, limit=1)
    reply = mcp_tools.video_claim(b, release=[{"url": url_of("00"), "code": "failed", "reason": "not mine"}])
    row = _row(memory, keys[0], datetime.now(timezone.utc))
    assert row["state"] == "claimed" and row["session"] == "ses_a", (
        f"session b ended session a's lease; b was told: {reply!r}")


@pytest.mark.xfail(strict=True, reason="F2: a writer's saved snapshot is read before the lock (mcp_tools.py:1204)")
def test_f2_a_stale_saved_snapshot_never_drops_a_queued_video(two_sessions, monkeypatch):
    memory, keys, a, _ = two_sessions
    video_queue.put(memory, keys[0], "watch")
    real = video_state.saved_videos
    newly_saved = []

    def snapshot_then_the_person_saves_and_queues(memory_path):
        snapshot = real(memory_path)
        if not newly_saved:
            newly_saved.append(add_video(memory, "09"))
            video_queue.put(memory, newly_saved[0], "watch", saved=real(memory))
        return snapshot

    monkeypatch.setattr(video_state, "saved_videos", snapshot_then_the_person_saves_and_queues)
    mcp_tools.video_claim(a, limit=1)
    monkeypatch.setattr(video_state, "saved_videos", real)
    assert newly_saved[0] in real(memory), "the new video is saved"
    assert _row(memory, newly_saved[0], datetime.now(timezone.utc)) is not None, (
        "the person's freshly queued video vanished from the queue")


@pytest.mark.xfail(strict=True, reason="F3: complete (video_queue.py:692) closes a row on a record older than its request")
def test_f3_a_record_older_than_the_request_never_closes_it(two_sessions):
    memory, keys, _, _ = two_sessions
    add_watch_episode(memory, url_of("00"), basis="transcript", timestamp=_at(0).isoformat())
    video_queue.put(memory, keys[0], "transcript", now=_at(1))
    video_queue.claim(memory, session="ses_a", harness="claude-code", now=_at(2))
    outcome = video_queue.complete(memory, keys[0], "transcript", session="ses_b", now=_at(3))
    row = _row(memory, keys[0], _at(3))
    assert outcome != "done" and row is not None and row["session"] == "ses_a", (
        f"an episode written before the request closed it as {outcome!r} and ended session a's lease")


def test_p1_two_claimers_that_read_at_once_never_share_a_video(tmp_path, monkeypatch):
    """Both claimers are held at the read until the other arrives or a second passes; under the lock the
    second never arrives, so the reads are serialised and the leases stay disjoint."""
    memory, keys = bank_with_videos(tmp_path, 2)
    for k in keys:
        video_queue.put(memory, k, "watch", now=_at())
    real_read = video_queue._read_file
    gate = threading.Barrier(2, timeout=1)

    def read_when_both_arrive(memory_path):
        try:
            gate.wait()
        except threading.BrokenBarrierError:
            pass
        return real_read(memory_path)

    monkeypatch.setattr(video_queue, "_read_file", read_when_both_arrive)
    got: dict[str, list[str]] = {}

    def claimer(session):
        got[session] = [r["key"] for r in video_queue.claim(memory, session=session, harness="h", limit=2,
                                                            now=_at(1), holding=lambda: False)]

    threads = [threading.Thread(target=claimer, args=(s,)) for s in ("ses_a", "ses_b")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not set(got["ses_a"]) & set(got["ses_b"]), f"one video leased to two sessions: {got}"
    assert sorted(got["ses_a"] + got["ses_b"]) == sorted(keys)


def test_p6_releasing_or_recording_twice_leaves_the_queue_as_once(tmp_path):
    memory, keys = bank_with_videos(tmp_path, 2)
    for k in keys:
        video_queue.put(memory, k, "watch", now=_at())
    video_queue.claim(memory, session="ses_a", harness="h", limit=2, now=_at(1))
    path = video_queue.path_for(memory)
    release = [{"url": url_of("00"), "code": "no_captions", "reason": "none"}]
    video_queue.release(memory, release, session="ses_a", now=_at(2))
    once = path.read_text()
    assert video_queue.release(memory, release, session="ses_a", now=_at(2)) == [(url_of("00"), "not_claimed")]
    assert path.read_text() == once, "a second release changed the queue"
    assert video_queue.complete(memory, keys[1], "transcript", session="ses_a", now=_at(3)) == "stays"
    once = path.read_text()
    assert video_queue.complete(memory, keys[1], "transcript", session="ses_a", now=_at(3)) == "stays"
    assert path.read_text() == once, "a second record of the same basis changed the queue"


def test_p11_a_failed_video_waits_for_the_person(tmp_path):
    memory, keys = bank_with_videos(tmp_path, 1)
    video_queue.put(memory, keys[0], "watch", now=_at())
    video_queue.claim(memory, session="ses_a", harness="h", now=_at(1))
    video_queue.release(memory, [{"url": url_of("00"), "code": "needs_login", "reason": "sign-in"}],
                        session="ses_a", now=_at(2))
    assert video_queue.claim(memory, session="ses_b", harness="h", now=_at(3)) == [], "a failed video was leased"
    video_queue.retry(memory, keys[0], now=_at(4))
    assert [r["key"] for r in video_queue.claim(memory, session="ses_b", harness="h", now=_at(5))] == keys
