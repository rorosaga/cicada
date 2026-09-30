"""G162 — the `/videos/*` routes: ETag and 304 honoured, a queue write moves the tag, auth, the
prompt preview equals the hand-off's, the browser permission follows the switch, and nothing here
touches the bank or sits behind the demo gate. Synthetic banks."""
from __future__ import annotations

import re
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from _video_fixtures import add_video, add_watch_episode, bank_with_videos, url_of
from api import config, main
from api.routers import videos as videos_router
from api.services import bank_index, demo_guard, video_prompt, video_queue, video_state

NOW = datetime(2026, 9, 29, 14, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    memory, keys = bank_with_videos(tmp_path, 4)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    monkeypatch.setattr(videos_router, "_now", lambda: NOW)
    monkeypatch.setattr(videos_router, "_holding", lambda: False)
    try:
        yield TestClient(main.app), memory, keys
    finally:
        config.get_settings.cache_clear()


def _clean(memory) -> bool:
    return subprocess.run(["git", "-C", str(memory), "status", "--porcelain"], capture_output=True,
                          text=True).stdout.strip() == ""


def test_state_and_summary_honour_the_etag(rig):
    c, memory, keys = rig
    for path in ("/videos/state", "/videos/summary"):
        first = c.get(path)
        assert first.status_code == 200 and first.headers["ETag"]
        assert c.get(path, headers={"If-None-Match": first.headers["ETag"]}).status_code == 304


def test_a_queue_write_moves_both_etags_and_the_item_shows_it(rig):
    c, memory, keys = rig
    tags = [c.get(p).headers["ETag"] for p in ("/videos/state", "/videos/summary")]
    got = c.put(f"/videos/queue/{keys[0]}", json={"want": "watch"})
    assert got.status_code == 200 and got.json()["queueState"] == "queued" and got.json()["want"] == "watch"
    assert [c.get(p).headers["ETag"] for p in ("/videos/state", "/videos/summary")] != tags
    body = c.get("/videos/state").json()
    assert body["shape"] == "video-1"
    item = next(i for i in body["items"] if i["key"] == keys[0])
    assert item["queueState"] == "queued" and item["state"] == "none"
    assert body["queue"] == {"total": 4, "unread": 3, "queued": 1, "claimed": 0, "failed": 0, "read": 0}


def test_summary_matches_state_queue(rig):
    """N-6: one function feeds both blocks, so they cannot disagree — with a queued, a claimed, a failed and
    a read video, and a batch."""
    c, memory, keys = rig
    add_watch_episode(memory, url_of("03"), basis="transcript")
    c.post("/videos/run/handoff", json={"items": [{"key": k, "want": "watch"} for k in keys[:3]], "method": "auto"})
    video_queue.claim(memory, session="s", harness="claude-code", limit=2, now=NOW)
    video_queue.release(memory, [{"url": url_of("00"), "code": "needs_login", "reason": "login wall"}],
                        session="s", now=NOW)
    state, summary = c.get("/videos/state").json(), c.get("/videos/summary").json()
    block = {k: v for k, v in summary.items() if k not in ("shape", "nextChangeAt")}
    assert state["queue"] == block
    assert (block["queued"], block["claimed"], block["failed"], block["read"], block["unread"]) == (1, 1, 1, 1, 0)
    assert block["unread"] + block["read"] + block["queued"] + block["claimed"] + block["failed"] == block["total"]
    failed = next(i for i in state["items"] if i["key"] == keys[0])
    assert failed["failedCode"] == "needs_login" and failed["failedReason"] == "login wall"
    assert block["batch"]["total"] == 3 and block["batch"]["failed"] == 1 and block["batch"]["claimed"] == 1


def test_the_queue_routes_404_a_key_that_is_not_a_saved_video(rig):
    c, memory, keys = rig
    assert c.put("/videos/queue/000000000000", json={"want": "watch"}).status_code == 404
    assert c.put(f"/videos/queue/{keys[0]}", json={"want": "everything"}).status_code == 422
    assert c.post("/videos/queue/000000000000/retry").status_code == 404
    assert c.delete("/videos/queue/000000000000").json() == {"removed": False}


def test_remove_and_retry(rig):
    c, memory, keys = rig
    c.put(f"/videos/queue/{keys[0]}", json={"want": "transcript"})
    video_queue.claim(memory, session="s", harness="h", now=NOW)
    video_queue.release(memory, [{"url": url_of("00"), "code": "not_found", "reason": "gone"}], session="s", now=NOW)
    retried = c.post(f"/videos/queue/{keys[0]}/retry")
    assert retried.status_code == 200 and retried.json()["queueState"] == "queued"
    assert c.delete(f"/videos/queue/{keys[0]}").json() == {"removed": True}
    assert not any(i.get("queueState") for i in c.get("/videos/state").json()["items"])


def test_handoff_is_all_or_nothing_and_names_the_keys(rig):
    c, memory, keys = rig
    got = c.post("/videos/run/handoff", json={"items": [{"key": keys[0], "want": "watch"},
                                                        {"key": "f" * 12, "want": "watch"}], "method": "auto"})
    assert got.status_code == 422 and got.json()["detail"]["keys"] == ["f" * 12]
    assert c.get("/videos/summary").json().get("batch") is None and video_queue.view(memory, NOW)[0] == []
    assert c.post("/videos/run/handoff", json={"items": [], "method": "auto"}).status_code == 422
    assert c.post("/videos/run/handoff", json={"items": [{"key": keys[0], "want": "watch"}],
                                               "method": "telepathy"}).status_code == 422


def test_handoff_has_no_cap_and_returns_the_prompt(tmp_path, monkeypatch):
    memory, keys = bank_with_videos(tmp_path, 45)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    try:
        c = TestClient(main.app)
        got = c.post("/videos/run/handoff", json={"items": [{"key": k, "want": "transcript"} for k in keys],
                                                  "method": "captions"})
        assert got.status_code == 200
        body = got.json()
        assert body["batch"]["total"] == 45 and body["batch"]["method"] == "captions"
        assert "45 videos" in body["prompt"] and "Preferred method: captions" in body["prompt"]
        assert c.get("/videos/summary").json()["batch"]["total"] == 45
    finally:
        config.get_settings.cache_clear()


def test_prompt_preview_writes_nothing(rig):
    """N-10: the preview route leaves the queue file untouched and equals the hand-off's prompt for the
    same inputs; with no query it is the active batch's prompt (404 with none)."""
    c, memory, keys = rig
    assert c.get("/videos/run/prompt").status_code == 404
    preview = c.get("/videos/run/prompt", params={"count": 3, "method": "link"})
    assert preview.status_code == 200 and not video_queue.path_for(memory).exists()
    handoff = c.post("/videos/run/handoff", json={"items": [{"key": k, "want": "watch"} for k in keys[:3]],
                                                  "method": "link"}).json()
    assert handoff["prompt"] == preview.json()["prompt"]
    mtime = video_queue.path_for(memory).stat().st_mtime_ns
    again = c.get("/videos/run/prompt")
    assert again.status_code == 200 and again.json()["prompt"] == handoff["prompt"]
    assert video_queue.path_for(memory).stat().st_mtime_ns == mtime
    assert c.get("/videos/run/prompt", params={"method": "telepathy"}).status_code == 422


def test_prompt_preview_follows_permission(rig, monkeypatch):
    """H1: the browser clause rides the hand-off and the preview only when the single reading permission is on,
    read per request; both routes answer identically in both states and neither is wrong-footed by an
    install without the switch."""
    c, memory, keys = rig
    settings = types.SimpleNamespace(on=False)
    fake = types.ModuleType("api.services.reading_settings")
    fake.agent_enabled = lambda: settings.on
    monkeypatch.setitem(sys.modules, "api.services.reading_settings", fake)
    import api.services as pkg

    monkeypatch.setattr(pkg, "reading_settings", fake, raising=False)
    items = [{"key": k, "want": "watch"} for k in keys[:2]]
    for on in (False, True):
        settings.on = on
        preview = c.get("/videos/run/prompt", params={"count": 2, "method": "auto"}).json()["prompt"]
        handoff = c.post("/videos/run/handoff", json={"items": items, "method": "auto"}).json()["prompt"]
        assert preview == handoff
        assert (video_prompt.BROWSER_CLAUSE in preview) is on
    assert video_queue.view(memory, NOW)[0], "the hand-off wrote"


def test_without_a_reading_switch_the_clause_stays_off(rig, monkeypatch):
    c, memory, keys = rig
    monkeypatch.setitem(sys.modules, "api.services.reading_settings", None)  # import raises ImportError
    assert videos_router.browser_clause() is None
    assert video_prompt.BROWSER_CLAUSE not in c.get("/videos/run/prompt", params={"count": 1}).json()["prompt"]


def test_no_route_touches_the_bank_or_the_demo_gate(rig):
    """The queue is outside the bank: no route dirties it, none answers 409, and queueing works in a demo bank."""
    c, memory, keys = rig
    subprocess.run(["git", "-C", str(memory), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-q", "-m", "fixture"], check=True, capture_output=True)
    c.put(f"/videos/queue/{keys[0]}", json={"want": "watch"})
    c.post("/videos/run/handoff", json={"items": [{"key": keys[1], "want": "transcript"}], "method": "auto"})
    c.delete(f"/videos/queue/{keys[0]}")
    assert _clean(memory)
    demo_guard.write_manifest(memory)
    subprocess.run(["git", "-C", str(memory), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-q", "-m", "demo"], check=True, capture_output=True)
    assert c.put(f"/videos/queue/{keys[2]}", json={"want": "watch"}).status_code == 200
    assert c.post("/videos/run/handoff", json={"items": [{"key": keys[3], "want": "watch"}],
                                               "method": "auto"}).status_code == 200
    assert _clean(memory)


def test_no_video_route_is_under_a_gated_prefix():
    paths = {r.path for r in main.app.routes if getattr(r, "path", "").startswith("/videos")}
    assert paths >= {"/videos/state", "/videos/summary", "/videos/queue/{key}", "/videos/queue/{key}/retry",
                     "/videos/run/handoff", "/videos/run/prompt"}
    assert not any(p.startswith(("/capture/", "/sources/")) for p in paths)


def test_the_routes_need_the_bearer_when_auth_is_on(rig, monkeypatch):
    c, memory, keys = rig
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.setenv("CICADA_API_TOKEN", "test-token-123")
    assert c.get("/videos/state").status_code in (401, 403)
    ok = c.get("/videos/state", headers={"Authorization": "Bearer test-token-123"})
    assert ok.status_code == 200


def test_a_lapse_shows_over_the_wire_with_no_write(rig, monkeypatch):
    """H2 through the route: after the lease lapses the same request answers a new ETag and a settled body
    (waiting again), and `nextChangeAt` named the moment — with no write to the queue file."""
    c, memory, keys = rig
    clock = {"t": NOW}
    real_stamp = video_queue.stamp
    monkeypatch.setattr(videos_router, "_now", lambda: clock["t"])
    monkeypatch.setattr(video_queue, "stamp", lambda mp, now=None: real_stamp(mp, clock["t"]))
    c.put(f"/videos/queue/{keys[0]}", json={"want": "watch"})
    video_queue.claim(memory, session="s", harness="claude-code", now=NOW)
    first = c.get("/videos/state")
    item = next(i for i in first.json()["items"] if i["key"] == keys[0])
    assert item["queueState"] == "claimed" and item["claimedBy"] == "claude-code"
    assert first.json()["nextChangeAt"] == "2026-09-29T14:45:00Z"
    assert c.get("/videos/state", headers={"If-None-Match": first.headers["ETag"]}).status_code == 304
    before = video_queue.path_for(memory).stat().st_mtime_ns
    clock["t"] = NOW + timedelta(minutes=50)
    later = c.get("/videos/state", headers={"If-None-Match": first.headers["ETag"]})
    assert later.status_code == 200 and later.headers["ETag"] != first.headers["ETag"], "no 304 after the lapse"
    item = next(i for i in later.json()["items"] if i["key"] == keys[0])
    assert item["queueState"] == "queued" and item["attempts"] == 1
    assert "nextChangeAt" not in later.json() and video_queue.path_for(memory).stat().st_mtime_ns == before


def test_the_etag_follows_whether_sleep_holds_the_pages(rig, monkeypatch):
    """A lapsed lease is settled only when Sleep does not hold the pages, so the body depends on that bit
    and the tag must too: when the drain's write window closes with no file change, the app must not 304
    on a body that still says 'claimed'."""
    c, memory, keys = rig
    clock = {"t": NOW}
    real_stamp = video_queue.stamp
    monkeypatch.setattr(videos_router, "_now", lambda: clock["t"])
    monkeypatch.setattr(video_queue, "stamp", lambda mp, now=None: real_stamp(mp, clock["t"]))
    c.put(f"/videos/queue/{keys[0]}", json={"want": "watch"})
    video_queue.claim(memory, session="s", harness="claude-code", now=NOW)
    clock["t"] = NOW + timedelta(minutes=50)
    held = {"v": True}
    monkeypatch.setattr(videos_router, "_holding", lambda: held["v"])
    during = c.get("/videos/state")
    item = next(i for i in during.json()["items"] if i["key"] == keys[0])
    assert item["queueState"] == "claimed"
    held["v"] = False
    after = c.get("/videos/state", headers={"If-None-Match": during.headers["ETag"]})
    assert after.status_code == 200 and after.headers["ETag"] != during.headers["ETag"]
    item = next(i for i in after.json()["items"] if i["key"] == keys[0])
    assert item["queueState"] == "queued"
