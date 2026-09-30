"""G162 V2 — the video queue store: idempotent writes, leases that lapse, the satisfaction table,
the file's safety ceiling, orphans, and the sync stamp that makes a lapse visible. The clock is
injected; no test sleeps. Synthetic banks; the queue file lives under the conftest-isolated
CICADA_HOME."""
from __future__ import annotations

import json
import re
import subprocess
import threading
from datetime import datetime, timedelta, timezone

import pytest

from _video_fixtures import add_video, add_watch_episode, bank_with_videos, url_of
from api.services import bank_index, media_ingestor, sync_service, video_queue, video_state

T0 = datetime(2026, 9, 29, 14, 0, 0, tzinfo=timezone.utc)


def _at(minutes: float = 0) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest.fixture
def bank(tmp_path):
    memory, keys = bank_with_videos(tmp_path, 4)
    return memory, keys


def _rows(memory, now=None):
    return {r["key"]: r for r in video_queue.view(memory, now or _at())[0]}


def _persist(memory, now):
    """Any write settles the file and persists what lapsed (a no-op remove of a key nobody queued)."""
    video_queue.remove(memory, "0" * 12, now=now)


def _git_status(memory) -> str:
    return subprocess.run(["git", "-C", str(memory), "status", "--porcelain"], capture_output=True,
                          text=True).stdout


# --- B1: add, replace, remove ---------------------------------------------------------------------------


def test_put_is_idempotent_and_watch_replaces_transcript(bank):
    memory, keys = bank
    a = video_queue.put(memory, keys[0], "transcript", now=_at())
    b = video_queue.put(memory, keys[0], "transcript", now=_at(1))
    assert a == b and len(_rows(memory)) == 1
    assert video_queue.put(memory, keys[0], "watch", now=_at(2))["want"] == "watch"
    assert video_queue.put(memory, keys[0], "transcript", now=_at(3))["want"] == "watch", "a watch is never downgraded"
    assert video_queue.remove(memory, keys[0]) is True
    assert video_queue.remove(memory, keys[0]) is False and _rows(memory) == {}


def test_a_key_that_is_not_a_saved_video_is_refused(bank):
    memory, keys = bank
    with pytest.raises(video_queue.NotAVideo):
        video_queue.put(memory, "0" * 12, "transcript")
    with pytest.raises(video_queue.QueueError):
        video_queue.put(memory, keys[0], "everything")


def test_ceiling_sentence(bank, monkeypatch):
    memory, keys = bank
    monkeypatch.setattr(video_queue, "MAX_ROWS", 2)
    video_queue.put(memory, keys[0], "transcript")
    video_queue.put(memory, keys[1], "transcript")
    with pytest.raises(video_queue.QueueFull) as err:
        video_queue.put(memory, keys[2], "transcript")
    assert "holds at most 2" in str(err.value)
    video_queue.put(memory, keys[0], "watch")  # an existing row is never refused


def test_no_batch_cap_a_handoff_of_every_video_is_accepted(tmp_path):
    """P1: no cap — 60 videos in one hand-off, no 422 for size."""
    memory, keys = bank_with_videos(tmp_path, 60)
    batch, queued = video_queue.handoff(memory, [{"key": k, "want": "watch"} for k in keys], "auto")
    assert batch["total"] == 60 and queued == 60


# --- B2: two writers ------------------------------------------------------------------------------------


def test_two_threads_never_lose_an_entry(tmp_path):
    memory, keys = bank_with_videos(tmp_path, 12)
    errors = []

    def work(chunk):
        try:
            for k in chunk:
                video_queue.put(memory, k, "transcript")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(keys[i::3],)) for i in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and set(_rows(memory)) == set(keys)


# --- B3: the bank stays clean ---------------------------------------------------------------------------


def test_git_status_is_clean_after_every_queue_call(bank):
    memory, keys = bank
    for args in (["add", "-A"], ["commit", "-q", "-m", "fixture"]):
        subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True)
    video_queue.put(memory, keys[0], "transcript", now=_at())
    video_queue.handoff(memory, [{"key": keys[1], "want": "watch"}], "auto", now=_at())
    claimed = video_queue.claim(memory, session="ses_a", harness="claude-code", now=_at(1))
    video_queue.release(memory, [{"url": url_of("01"), "code": "needs_login", "reason": "login wall"}],
                        session="ses_a", now=_at(2))
    video_queue.complete(memory, keys[0], "transcript", session="ses_a", now=_at(3))
    video_queue.remove(memory, keys[1])
    assert claimed and _git_status(memory) == ""


# --- B4: leases -----------------------------------------------------------------------------------------


def test_a_lease_is_never_given_twice(bank):
    memory, keys = bank
    for k in keys:
        video_queue.put(memory, k, "transcript", now=_at())
    first = video_queue.claim(memory, session="ses_a", harness="claude-code", limit=3, now=_at(1))
    second = video_queue.claim(memory, session="ses_b", harness="codex", limit=3, now=_at(1))
    assert len(first) == 3 and len(second) == 1
    assert not {r["key"] for r in first} & {r["key"] for r in second}
    assert video_queue.claim(memory, session="ses_c", harness="x", now=_at(1)) == []


def test_claims_are_oldest_first_and_capped_at_a_page(tmp_path):
    memory, keys = bank_with_videos(tmp_path, 14)
    for i, k in enumerate(keys):
        video_queue.put(memory, k, "transcript", now=_at(i))
    first = video_queue.claim(memory, session="s", harness="h", limit=99, now=_at(30))
    assert [r["key"] for r in first] == keys[:10]


def test_claim_pages_of_ten(tmp_path):
    """C3: a hand-off of 14 is accepted in one call and claimed in two calls of at most 10."""
    memory, keys = bank_with_videos(tmp_path, 14)
    video_queue.handoff(memory, [{"key": k, "want": "transcript"} for k in keys], "auto", now=_at())
    a = video_queue.claim(memory, session="s", harness="h", limit=10, now=_at(1))
    b = video_queue.claim(memory, session="s", harness="h", limit=10, now=_at(1))
    assert (len(a), len(b)) == (10, 4)


def test_a_lapse_returns_the_video_with_one_more_attempt_and_the_third_fails_it(bank):
    memory, keys = bank
    video_queue.put(memory, keys[0], "watch", now=_at())
    for lap in (1, 2):
        video_queue.claim(memory, session="ses_a", harness="claude-code", now=_at(60 * lap))
        row = _rows(memory, _at(60 * lap + 46))[keys[0]]
        assert (row["state"], row["attempts"]) == ("queued", lap), "the lease lapsed: back in the queue"
        _persist(memory, _at(60 * lap + 46))  # persists the settled row
    video_queue.claim(memory, session="ses_a", harness="claude-code", now=_at(200))
    row = _rows(memory, _at(250))[keys[0]]
    assert row["state"] == "failed" and row["failed"]["code"] == "failed"
    assert row["failed"]["reason"] == "no agent recorded it"


def test_the_third_lapse_reason_names_what_exists(bank):
    memory, keys = bank
    add_watch_episode(memory, url_of("00"), basis="transcript", timestamp="2026-09-29T14:10:00+00:00")
    video_queue.put(memory, keys[0], "watch", now=_at())
    for minute in (5, 100, 200):
        video_queue.claim(memory, session="ses_a", harness="h", now=_at(minute))
        _persist(memory, _at(minute + 46))
    row = _rows(memory, _at(300))[keys[0]]
    assert row["state"] == "failed" and "transcript only" in row["failed"]["reason"]


def test_a_lapse_with_a_newer_satisfying_record_closes_the_entry_as_done(bank):
    memory, keys = bank
    video_queue.handoff(memory, [{"key": keys[0], "want": "watch"}], "auto", now=_at())
    video_queue.claim(memory, session="ses_a", harness="h", now=_at(1))
    add_watch_episode(memory, url_of("00"), basis="frames", timestamp="2026-09-29T14:20:00+00:00")
    assert keys[0] not in _rows(memory, _at(50))
    batch = video_queue.batch_view(*video_queue.view(memory, _at(50)), video_state.saved_videos(memory))
    assert batch["done"] == 1 and batch["waiting"] == 0


def test_session_activity_refreshes_leases(bank):
    """N-5: any call by the leaseholder extends its other leases, so a sub-agent on a long video is not
    judged lapsed."""
    memory, keys = bank
    video_queue.put(memory, keys[0], "watch", now=_at())
    video_queue.put(memory, keys[1], "watch", now=_at())
    video_queue.claim(memory, session="ses_a", harness="h", limit=1, now=_at(1))   # lease until 46
    video_queue.claim(memory, session="ses_a", harness="h", limit=1, now=_at(40))  # refreshes: until 85
    rows = _rows(memory, _at(60))
    assert {r["state"] for r in rows.values()} == {"claimed"}, "the first lease outlived its 45 minutes"


# --- B5: the satisfaction table -------------------------------------------------------------------------


@pytest.mark.parametrize("want, basis, session, outcome", [
    ("transcript", "transcript", "ses_a", "done"),
    ("transcript", "frames", "ses_a", "done"),
    ("transcript", "both", "ses_a", "done"),
    ("watch", "transcript", "ses_a", "stays"),
    ("watch", "frames", "ses_a", "done"),
    ("watch", "both", "ses_a", "done"),
    ("watch", None, "ses_a", "done"),        # omitted basis: the leaseholder closes it
    ("watch", None, "ses_other", "left"),    # ... and nobody else does
    ("transcript", None, "ses_other", "left"),
    ("watch", "telepathy", "ses_a", "done"),  # unknown = omitted, for the leaseholder
])
def test_the_satisfaction_table(bank, want, basis, session, outcome):
    memory, keys = bank
    video_queue.put(memory, keys[0], want, now=_at())
    video_queue.claim(memory, session="ses_a", harness="h", now=_at(1))
    assert video_queue.complete(memory, keys[0], basis, session=session, now=_at(2)) == outcome
    assert (keys[0] in _rows(memory, _at(2))) == (outcome != "done")


def test_a_record_for_a_video_nobody_queued_is_none(bank):
    memory, keys = bank
    assert video_queue.complete(memory, keys[0], "frames", session="s") == "none"
    video_queue.put(memory, keys[1], "watch")
    assert video_queue.complete(memory, keys[0], "frames", session="s") == "none"


def test_complete_credits_the_batch_once(bank):
    memory, keys = bank
    video_queue.handoff(memory, [{"key": k, "want": "transcript"} for k in keys[:2]], "auto", now=_at())
    video_queue.claim(memory, session="ses_a", harness="h", limit=1, now=_at(1))
    video_queue.complete(memory, keys[0], "transcript", session="ses_a", now=_at(2))
    rows, batches = video_queue.view(memory, _at(3))
    batch = video_queue.batch_view(rows, batches, video_state.saved_videos(memory))
    assert (batch["total"], batch["done"], batch["waiting"]) == (2, 1, 1)


def test_removing_a_member_shrinks_the_batch(bank):
    memory, keys = bank
    video_queue.handoff(memory, [{"key": k, "want": "transcript"} for k in keys[:3]], "auto", now=_at())
    video_queue.remove(memory, keys[2], now=_at(1))
    rows, batches = video_queue.view(memory, _at(2))
    assert video_queue.batch_view(rows, batches, video_state.saved_videos(memory))["total"] == 2


def test_a_new_handoff_replaces_the_active_batch(bank):
    memory, keys = bank
    a, _ = video_queue.handoff(memory, [{"key": keys[0], "want": "transcript"}], "auto", now=_at())
    b, _ = video_queue.handoff(memory, [{"key": keys[1], "want": "watch"}], "captions", now=_at(5))
    rows, batches = video_queue.view(memory, _at(6))
    assert list(batches) == [b["id"]] and a["id"] != b["id"]
    assert batches[b["id"]]["method"] == "captions"


def test_handoff_all_or_nothing(bank):
    memory, keys = bank
    with pytest.raises(video_queue.NotAVideo) as err:
        video_queue.handoff(memory, [{"key": keys[0], "want": "watch"}, {"key": "f" * 12, "want": "watch"},
                                     {"key": "e" * 12, "want": "watch"}], "auto")
    assert set(err.value.keys) == {"f" * 12, "e" * 12}
    assert _rows(memory) == {} and not video_queue.path_for(memory).exists() or video_queue.view(memory)[1] == {}
    with pytest.raises(video_queue.QueueError):
        video_queue.handoff(memory, [{"key": keys[0], "want": "watch"}], "telepathy")
    with pytest.raises(video_queue.QueueError):
        video_queue.handoff(memory, [], "auto")


# --- release: codes, reasons, scrubbing (B10, N-2) -----------------------------------------------------------


def test_release_code_and_reason(bank):
    """Secret-shaped strings and newlines are stored scrubbed, one line, at most 200 characters;
    `needs_login` surfaces as its own code; an unknown code becomes `failed`."""
    memory, keys = bank
    for k in keys[:3]:
        video_queue.put(memory, k, "watch", now=_at())
    video_queue.claim(memory, session="ses_a", harness="h", limit=3, now=_at(1))
    secret = "sk-" + "a1b2c3d4e5f6a7b8c9d0e1f2"
    results = video_queue.release(memory, [
        {"url": url_of("00"), "code": "needs_login", "reason": f"line one\nline two {secret} " + "x" * 400},
        {"url": url_of("01"), "code": "telepathy", "reason": "odd"},
        {"url": url_of("02")},
        {"url": "https://example.com/never-queued"},
    ], session="ses_a", now=_at(2))
    assert [o for _, o in results] == ["needs_login", "released", "released", "unknown"]
    rows = _rows(memory, _at(3))
    login = rows[keys[0]]["failed"]
    assert login["code"] == "needs_login" and "\n" not in login["reason"] and secret not in login["reason"]
    assert len(login["reason"]) <= video_queue.MAX_REASON_CHARS and "[redacted]" in login["reason"]
    assert rows[keys[1]]["failed"]["code"] == "failed"
    assert rows[keys[2]]["failed"]["reason"] == ""


def test_only_a_claimed_video_can_be_released(bank):
    memory, keys = bank
    video_queue.put(memory, keys[0], "watch")
    assert video_queue.release(memory, [{"url": url_of("00")}], session="s")[0][1] == "not_claimed"


def test_retry_puts_a_failed_row_back(bank):
    memory, keys = bank
    video_queue.put(memory, keys[0], "watch", now=_at())
    video_queue.claim(memory, session="s", harness="h", now=_at(1))
    video_queue.release(memory, [{"url": url_of("00"), "code": "blocked"}], session="s", now=_at(2))
    row = video_queue.retry(memory, keys[0], now=_at(3))
    assert row["state"] == "queued" and row["attempts"] == 0 and "failed" not in row
    assert video_queue.retry(memory, keys[0], now=_at(4)) is None


# --- expiry, orphans, per-bank files --------------------------------------------------------------------------


def test_failed_rows_and_finished_batches_expire_in_memory_and_persist_only_on_a_write(bank):
    memory, keys = bank
    video_queue.handoff(memory, [{"key": keys[0], "want": "watch"}], "auto", now=_at())
    video_queue.claim(memory, session="s", harness="h", now=_at(1))
    video_queue.release(memory, [{"url": url_of("00"), "code": "not_found"}], session="s", now=_at(2))
    path = video_queue.path_for(memory)
    before = path.stat().st_mtime_ns
    later = _at(60 * 24 * 8)
    rows, batches = video_queue.view(memory, later)
    assert rows == [] and batches == {}, "expired in memory"
    assert path.stat().st_mtime_ns == before, "a read never wrote"
    video_queue.put(memory, keys[1], "transcript", now=later)
    assert [r["key"] for r in json.loads(path.read_text())["items"]] == [keys[1]]


def test_orphan_row_skipped_and_dropped(bank):
    """M5: a page that stops resolving (archived, junk, index entry gone) drops out of a claim and is
    removed by the next write, shrinking its batch."""
    memory, keys = bank
    video_queue.handoff(memory, [{"key": k, "want": "transcript"} for k in keys[:2]], "auto", now=_at())
    idx = media_ingestor.load_url_index(memory)
    del idx[keys[0]]
    media_ingestor.save_url_index(memory, idx)
    bank_index.invalidate(memory)
    claimed = video_queue.claim(memory, session="s", harness="h", limit=5, now=_at(1))
    assert [r["key"] for r in claimed] == [keys[1]]
    raw = json.loads(video_queue.path_for(memory).read_text())
    assert [r["key"] for r in raw["items"]] == [keys[1]]
    (batch,) = raw["batches"].values()
    assert batch["keys"] == [keys[1]]


def test_hidden_page_leaves_summary_counts(bank):
    memory, keys = bank
    video_queue.put(memory, keys[0], "watch", now=_at())
    add_video(memory, "00", status="archived")
    body = video_state.build(memory, *[(video_queue.view(memory, _at())[0]), None])
    assert body["queue"]["total"] == 3 and body["queue"]["queued"] == 0


def test_per_bank_files(tmp_path):
    a, keys_a = bank_with_videos(tmp_path / "one", 1)
    b, keys_b = bank_with_videos(tmp_path / "two", 1)
    a = a.rename(tmp_path / "one" / "alpha")
    b = b.rename(tmp_path / "two" / "beta")
    video_queue.put(b, keys_b[0], "watch")
    assert video_queue.path_for(a) != video_queue.path_for(b)
    assert video_queue.path_for(b).exists() and not video_queue.path_for(a).exists()
    assert video_queue.view(a) == ([], {}) and len(video_queue.view(b)[0]) == 1


def test_a_bank_name_that_cannot_name_a_file_is_refused(tmp_path):
    with pytest.raises(ValueError):
        video_queue.path_for(tmp_path / ".." / "..")
    assert video_queue.mtime(tmp_path / "bad name!") == 0.0


def test_a_bank_name_outside_the_plain_slug_still_gets_its_own_queue(tmp_path):
    """A bank named with non-ASCII letters, an ampersand or an apostrophe is a real bank
    (id_utils.sanitize_id keeps them): its queue works, and no two names share a file."""
    seen = set()
    for name in ("diseño", "trabajo-&-vida", "rodrigo's-memory", "_underscore", "x" * 100, "日本語"):
        memory, keys = bank_with_videos(tmp_path / f"b{len(seen)}", 1)
        memory = memory.rename(memory.parent / name)
        path = video_queue.path_for(memory)
        assert path.parent == video_queue.path_for(tmp_path / "plain").parent and path.name.endswith(".json")
        assert re.fullmatch(r"[A-Za-z0-9._-]+", path.stem) and path not in seen
        seen.add(path)
        keys = list(video_state.saved_videos(memory))
        video_queue.put(memory, keys[0], "watch")
        assert path.exists() and len(video_queue.view(memory)[0]) == 1
        assert video_queue.stamp(memory) != "0.000000:0"
        assert video_queue.remove(memory, keys[0]) is True


def test_an_unreadable_url_index_never_wipes_the_queue(bank):
    """A bookmark sync rewriting sources/url_index.json can leave it empty or half-written for a
    moment: a claim, a release or a completion in that window must leave every row and batch alone."""
    memory, keys = bank
    for k in keys:
        video_queue.put(memory, k, "watch", now=_at())
    index = memory / "sources" / "url_index.json"
    good = index.read_text()
    for broken in (good[: len(good) // 2], "", "{}"):
        index.write_text(broken)
        video_queue.claim(memory, session="s", harness="claude-code", limit=2, now=_at(1))
        video_queue.remove(memory, "0" * 12, now=_at(1))
        rows = json.loads(video_queue.path_for(memory).read_text())["items"]
        assert {r["key"] for r in rows} == set(keys), broken[:10]
    index.write_text(good)
    assert len(video_queue.view(memory, _at(2))[0]) == len(keys)


def test_the_url_index_is_written_atomically(tmp_path):
    memory, keys = bank_with_videos(tmp_path, 1)
    idx = media_ingestor.load_url_index(memory)
    media_ingestor.save_url_index(memory, idx)
    assert media_ingestor.load_url_index(memory) == idx
    assert not list((memory / "sources").glob(".url_index.json.*.tmp"))


# --- the stamp: H2 --------------------------------------------------------------------------------------------


def test_a_write_moves_the_component_and_the_version(bank):
    memory, keys = bank
    before = sync_service.version(memory)
    video_queue.put(memory, keys[0], "watch")
    after = sync_service.version(memory)
    assert before.components["videoQueue"] != after.components["videoQueue"] and before.version != after.version
    assert sync_service.components(memory).keys() >= {"videoQueue"}


def test_lapse_moves_stamp_and_etag(bank):
    """H2: a lease lapsing writes nothing, yet it changes what /videos/state says — the stamp counts it,
    so a poller sees the change with no file write."""
    memory, keys = bank
    video_queue.put(memory, keys[0], "watch", now=_at())
    video_queue.claim(memory, session="s", harness="h", now=_at(1))
    path = video_queue.path_for(memory)
    mtime_before = path.stat().st_mtime_ns
    before, after = video_queue.stamp(memory, _at(30)), video_queue.stamp(memory, _at(50))
    assert before != after and before.split(":")[0] == after.split(":")[0], "same mtime, a different due count"
    assert path.stat().st_mtime_ns == mtime_before
    assert before.endswith(":0") and after.endswith(":1")


def test_next_change_at_names_the_earliest_future_instant(bank):
    memory, keys = bank
    assert video_queue.next_change_at(memory, _at()) is None
    video_queue.put(memory, keys[0], "watch", now=_at())
    assert video_queue.next_change_at(memory, _at(1)) is None, "a queued row changes nothing by itself"
    video_queue.claim(memory, session="s", harness="h", now=_at(1))
    assert video_queue.next_change_at(memory, _at(2)) == "2026-09-29T14:46:00Z"
    assert video_queue.next_change_at(memory, _at(50)) is None, "the lease has lapsed; nothing later"


def test_a_missing_file_is_a_zero_stamp_and_nothing_is_created_by_a_read(bank):
    memory, keys = bank
    assert video_queue.stamp(memory) == "0.000000:0" and video_queue.view(memory) == ([], {})
    assert not video_queue.path_for(memory).exists()


# --- lease judged only when Sleep is not holding the pages (P5, N-4) -------------------------------------------


def test_lease_not_judged_while_pages_held(bank):
    memory, keys = bank
    video_queue.put(memory, keys[0], "watch", now=_at())
    video_queue.claim(memory, session="s", harness="h", now=_at(1))
    rows, _ = video_queue.view(memory, _at(300), holding=lambda: True)
    assert rows[0]["state"] == "claimed" and rows[0]["attempts"] == 0
    rows, _ = video_queue.view(memory, _at(300), holding=lambda: False)
    assert rows[0]["state"] == "queued" and rows[0]["attempts"] == 1


def test_the_probe_is_asked_only_when_a_lease_lapsed(bank):
    memory, keys = bank
    video_queue.put(memory, keys[0], "watch", now=_at())
    calls = []
    video_queue.claim(memory, session="s", harness="h", now=_at(1), holding=lambda: calls.append(1) or False)
    assert calls == [], "a normal claim never pays the probe"
    video_queue.claim(memory, session="s", harness="h", now=_at(100), holding=lambda: calls.append(1) or True)
    assert calls == [1]
