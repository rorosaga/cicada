"""The video queue's model-checking findings, reproduced against the real code (`.claude/skills/verify-video-queue`).

Each finding's test drives the real entry points in the order the TLC counterexample gives and fails today on its
assertion. They are `xfail(strict=True, raises=AssertionError)`, so a fix flips them to an unexpected pass (the marker
comes off with it), and a hang or a crash in the test's own threads fails the run instead of passing as the finding.
Synthetic banks only; the queue file lives under the conftest-isolated CICADA_HOME."""
from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta, timezone

import pytest

from _video_fixtures import add_video, bank_with_videos, url_of
from api.services import episode_ids, mcp_tools, video_queue, video_state

T0 = datetime(2026, 9, 29, 14, 0, 0, tzinfo=timezone.utc)
THREAD_LIMIT_S = 10


def _at(minutes: float = 0) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _row(memory, key, now=None):
    now = now or datetime.now(timezone.utc)
    return {r["key"]: r for r in video_queue.view(memory, now, holding=lambda: False)[0]}.get(key)


def _ctx(memory, session_id):
    return mcp_tools.ToolContext(memory_path=lambda: memory, session_id=session_id, harness="claude-code")


@pytest.fixture
def two_sessions(tmp_path, monkeypatch):
    memory, keys = bank_with_videos(tmp_path, 2)
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    return memory, keys, _ctx(memory, "ses_a"), _ctx(memory, "ses_b")


def _run_threads(*targets):
    """Run each target in its own thread; a thread still running after THREAD_LIMIT_S, or one that raised, is a
    RuntimeError (never the AssertionError a finding's xfail expects)."""
    errors: list[BaseException] = []

    def guarded(fn):
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=guarded, args=(fn,), daemon=True) for fn in targets]
    [t.start() for t in threads]
    [t.join(THREAD_LIMIT_S) for t in threads]
    if any(t.is_alive() for t in threads):
        raise RuntimeError(f"a thread was still running after {THREAD_LIMIT_S} s: a deadlock")
    if errors:
        raise RuntimeError(f"a thread raised: {errors[0]!r}") from errors[0]


def _record_with_a_gap(monkeypatch, ctx, url, basis, *, episode_at, between):
    """cicada_record_watch, with `between` run after its episode is written and before its queue credit."""
    real_credit = mcp_tools._credit_video_queue

    def credit_after_the_gap(*args, **kwargs):
        between()
        return real_credit(*args, **kwargs)

    monkeypatch.setattr(mcp_tools, "_credit_video_queue", credit_after_the_gap)
    monkeypatch.setattr(episode_ids, "utc_now_iso", lambda: episode_at.isoformat())
    reply = mcp_tools.record_watch(ctx, url, "A summary.", None, None, basis, "captions")
    assert reply.startswith("Recorded the watch"), reply
    return reply


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="F1: video_queue.release:661 fails any claimed row, whoever asks")
def test_f1_a_session_cannot_hand_back_another_sessions_lease(two_sessions):
    memory, keys, a, b = two_sessions
    video_queue.put(memory, keys[0], "watch")
    assert "Leased 1 video" in mcp_tools.video_claim(a, limit=1)
    reply = mcp_tools.video_claim(b, release=[{"url": url_of("00"), "code": "failed", "reason": "not mine"}])
    row = _row(memory, keys[0])
    assert row["state"] == "claimed" and row["session"] == "ses_a", (
        f"session b ended session a's lease; b was told: {reply!r}")


def test_p13_a_claimer_with_no_session_id_can_hand_back_its_own_lease(two_sessions):
    """The CLI door calls with session_id "" (cli._tool_context, tool_door.context). A fix for F1 that compares
    session ids would leave such a claimer unable to hand back what it holds (model check F1s-session-compare-*)."""
    memory, keys, _, _ = two_sessions
    cli = _ctx(memory, "")
    video_queue.put(memory, keys[0], "watch")
    leased = mcp_tools.video_claim(cli, limit=1)
    assert "Leased 1 video" in leased
    item = {"url": url_of("00"), "code": "no_captions", "reason": "none"}
    if token := re.search(r"lease_token[\"'`]?\s*[:=]\s*[\"'`]?([0-9a-f]{16,})", leased):
        item["lease_token"] = token.group(1)
    assert "Handed back 1 video" in mcp_tools.video_claim(cli, release=[item])
    assert _row(memory, keys[0])["state"] == "failed"


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="F2: mcp_tools.video_claim:1204 reads the saved videos before video_queue.claim:624 locks")
def test_f2_a_stale_saved_snapshot_never_drops_a_queued_video(two_sessions, monkeypatch):
    memory, keys, a, _ = two_sessions
    video_queue.put(memory, keys[0], "watch")
    real = video_state.saved_videos
    snapshot_taken, person_done = threading.Event(), threading.Event()
    agent_thread: dict[str, int] = {}
    new_key: dict[str, str] = {}

    def saved_videos(memory_path):
        snapshot = real(memory_path)
        if threading.get_ident() == agent_thread.get("id") and not snapshot_taken.is_set():
            snapshot_taken.set()
            # With the saved set read under the lock, the person's put waits on that lock: go on without it.
            person_done.wait(2)
        return snapshot

    def agent():
        agent_thread["id"] = threading.get_ident()
        mcp_tools.video_claim(a, limit=1)

    def person():
        if not snapshot_taken.wait(THREAD_LIMIT_S):
            raise RuntimeError("the agent never read the saved videos")
        new_key["k"] = add_video(memory, "09")
        video_queue.put(memory, new_key["k"], "watch", saved=real(memory))
        person_done.set()

    monkeypatch.setattr(video_state, "saved_videos", saved_videos)
    _run_threads(agent, person)
    monkeypatch.setattr(video_state, "saved_videos", real)
    assert new_key["k"] in real(memory), "the new video is saved"
    assert _row(memory, new_key["k"]) is not None, "the person's freshly queued video vanished from the queue"


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="F3: video_queue.complete:694 closes a row on a stated basis whatever the record's age")
def test_f3_a_record_older_than_the_request_never_closes_it(two_sessions, monkeypatch):
    memory, keys, a, b = two_sessions
    soon = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=30)

    def person_queues_and_a_claims():
        video_queue.put(memory, keys[0], "transcript", now=soon + timedelta(seconds=2))
        assert video_queue.claim(memory, session="ses_a", harness="claude-code", now=soon + timedelta(seconds=3))

    _record_with_a_gap(monkeypatch, b, url_of("00"), "transcript", episode_at=soon, between=person_queues_and_a_claims)
    row = _row(memory, keys[0], soon + timedelta(seconds=4))
    assert row is not None and row["session"] == "ses_a", (
        "a record written two seconds before the request closed it and ended session a's lease")


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="F3: requested_at is cut to the second (video_queue._iso:132); a record from earlier in "
                          "the same second counts as newer (video_state.newer_than:239)")
def test_f3_a_record_from_earlier_in_the_requests_second_never_closes_it(two_sessions, monkeypatch):
    memory, keys, a, b = two_sessions
    second = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=30)

    def person_queues_and_a_claims():
        video_queue.put(memory, keys[0], "transcript", now=second + timedelta(milliseconds=700))
        assert video_queue.claim(memory, session="ses_a", harness="claude-code",
                                 now=second + timedelta(milliseconds=800))

    _record_with_a_gap(monkeypatch, b, url_of("00"), "transcript", episode_at=second + timedelta(milliseconds=300),
                       between=person_queues_and_a_claims)
    row = _row(memory, keys[0], second + timedelta(seconds=1))
    assert row is not None and row["session"] == "ses_a", (
        "a record written 0.4 s before the request, in the same second, closed it")


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="F5: video_queue.complete:696 trusts a session id that conversations can share")
def test_f5_a_shared_session_id_never_lets_one_conversation_close_anothers_lease(tmp_path, monkeypatch):
    memory, keys = bank_with_videos(tmp_path, 1)
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    bucket = "rc_ab12cd34_2026-10-22"
    a, b = _ctx(memory, bucket), _ctx(memory, bucket)
    video_queue.put(memory, keys[0], "watch")
    assert "Leased 1 video" in mcp_tools.video_claim(a, limit=1)
    mcp_tools.record_watch(b, url_of("00"), "Another conversation's summary.")
    row = _row(memory, keys[0])
    assert row is not None and row["state"] == "claimed", (
        "a record with no basis from a second conversation on the same id closed the first one's lease")


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
        return lambda: got.__setitem__(session, [r["key"] for r in video_queue.claim(
            memory, session=session, harness="h", limit=2, now=_at(1), holding=lambda: False)])

    _run_threads(claimer("ses_a"), claimer("ses_b"))
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
