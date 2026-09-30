"""G162 C10 — the app's Videos fixtures ARE the server's wire (the `projects-demo.json` precedent).

`app/CicadaApp/Tests/fixtures/videos-state-demo.json` is `GET /videos/state` and `GET /videos/summary` on the
demo bank with `today` pinned (three saved videos: the NASA video read from its captions, a fictional bench recording
read from frames and captions, and a walkthrough nobody has read). It fails on any byte of drift.

`videos-state-boards.json` is the approved boards' one 23-video fixture, at both moments (2:13 PM before the
hand-off, 2:44 PM thirty minutes after), hand-authored to the wire and built here from one table so the large-run
and empty boards can be laid out and tested. The same invariants hold for it: the picker's three tabs are disjoint
and sum to the total, the queue block is the one function's answer, every enum is one the server sends. Synthetic
only: placeholder people and hosts.

After a deliberate wire change, rewrite both: `CICADA_WRITE_APP_FIXTURE=1 python -m pytest <this file>`.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _demo_scenario import demo
from api import config, main
from api.services import bank_index, demo_showcase, handshake, media_ingestor, video_queue, video_state

FIXTURES = Path(__file__).resolve().parents[2] / "app" / "CicadaApp" / "Tests" / "fixtures"
DEMO = FIXTURES / "videos-state-demo.json"
BOARDS = FIXTURES / "videos-state-boards.json"
WRITE = os.environ.get("CICADA_WRITE_APP_FIXTURE") == "1"
QUEUE_STATES = {"queued", "claimed", "failed"}
FAIL_CODES = set(video_queue.FAIL_CODES)
ITEM_KEYS = {"key", "mediaEntityId", "url", "state", "want", "queueState", "claimedBy", "attempts", "failedCode",
             "failedReason", "batch", "basis", "engine", "fidelity", "episodeId", "recordedAt", "recordedBy",
             "readBySleep"}


def _dump(data) -> str:
    return json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def _check_item(item: dict) -> None:
    assert set(item) <= ITEM_KEYS, set(item) - ITEM_KEYS
    assert re.fullmatch(r"[0-9a-f]{12}", item["key"]) and item["state"] in video_state.STATES
    if "queueState" in item:
        assert item["queueState"] in QUEUE_STATES and item["want"] in video_queue.WANTS
    if item.get("queueState") == "failed":
        assert item["failedCode"] in FAIL_CODES
    if "engine" in item:
        assert item["engine"] in video_state.ENGINES
    if "fidelity" in item:
        assert item["fidelity"] in ("verbatim", "approximate")


def _check_wire(state: dict, summary: dict) -> None:
    for item in state["items"]:
        _check_item(item)
    assert len({i["key"] for i in state["items"]}) == len(state["items"])
    block = {k: v for k, v in summary.items() if k not in ("shape", "nextChangeAt")}
    assert state["queue"] == block == video_state.summary_from(state["items"], block.get("batch"))
    assert block["unread"] + block["read"] + block["queued"] + block["claimed"] + block["failed"] == block["total"]
    assert state["shape"] == summary["shape"] == video_state.VIDEO_SHAPE


# --- the demo bank's wire ------------------------------------------------------------------------------------


def _demo_wire(tmp_path, monkeypatch) -> dict:
    bank = demo(tmp_path, showcase=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    try:
        c = TestClient(main.app)
        return {"state": c.get("/videos/state").json(), "summary": c.get("/videos/summary").json()}
    finally:
        config.get_settings.cache_clear()


def test_the_app_fixture_is_the_demo_wire(tmp_path, monkeypatch):
    wire = _demo_wire(tmp_path, monkeypatch)
    text = _dump(wire)
    if WRITE:
        DEMO.parent.mkdir(parents=True, exist_ok=True)
        DEMO.write_text(text, encoding="utf-8")
    assert DEMO.read_text(encoding="utf-8") == text, (
        "the app's fixture drifted from the demo wire — rerun with CICADA_WRITE_APP_FIXTURE=1 after a deliberate "
        "change")


def test_the_demo_holds_three_videos_in_three_states_and_no_queue(tmp_path, monkeypatch):
    """C10: the generator writes no queue file; the media count and the three states are pinned."""
    wire = _demo_wire(tmp_path, monkeypatch)
    items = {i["mediaEntityId"]: i for i in wire["state"]["items"]}
    assert set(items) == {demo_showcase.VIDEO_ID, demo_showcase.GRIPPER_VIDEO_ID, demo_showcase.LAB_VIDEO_ID}
    assert items[demo_showcase.VIDEO_ID]["state"] == "transcript"
    assert items[demo_showcase.VIDEO_ID]["fidelity"] == "verbatim" and items[demo_showcase.VIDEO_ID]["readBySleep"] is True
    assert items[demo_showcase.GRIPPER_VIDEO_ID]["state"] == "watched_and_transcript"
    assert items[demo_showcase.GRIPPER_VIDEO_ID]["readBySleep"] is False
    assert items[demo_showcase.LAB_VIDEO_ID]["state"] == "none"
    assert wire["summary"] == {"total": 3, "unread": 1, "queued": 0, "claimed": 0, "failed": 0, "read": 2,
                               "shape": "video-1"}
    assert all(i["recordedBy"] == "claude-code" for i in items.values() if "recordedBy" in i)
    assert not (Path(os.environ["CICADA_HOME"]) / "video_queue").exists() or not list(
        (Path(os.environ["CICADA_HOME"]) / "video_queue").glob("demo.json"))
    _check_wire(wire["state"], wire["summary"])


def test_the_demo_record_joins_a_model_through_the_leo_session(tmp_path, monkeypatch):
    bank = demo(tmp_path, showcase=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    try:
        c = TestClient(main.app)
        item = next(i for i in c.get("/videos/state").json()["items"]
                    if i["mediaEntityId"] == demo_showcase.VIDEO_ID)
        watch = c.get(f"/episodes/{item['episodeId']}/text").json()["watch"]
    finally:
        config.get_settings.cache_clear()
    assert (watch["authorModel"], watch["authorEffort"]) == (demo_showcase.MODEL, demo_showcase.EFFORT)
    assert watch["basis"] == "transcript" and watch["engine"] == "captions"


def test_the_demo_fixture_is_synthetic():
    """Privacy: demo fiction only; every URL on example.com or a demo_showcase public URL; no machine path."""
    raw = DEMO.read_text(encoding="utf-8")
    assert "/Users/" not in raw and "/private/" not in raw and "/home/" not in raw
    for url in re.findall(r"https?://[^\s\"']+", raw):
        assert url.split("/")[2].endswith("example.com") or url in demo_showcase.PUBLIC_URLS, url


# --- the boards' 23-video fixture ---------------------------------------------------------------------------------

# (slug, title, channel, provider, length at A, length at B, saved, state A, state B, queue A, queue B, want, in batch,
#  recorder, record day, record time, read by Sleep, approximate, failed reason, claimed by). Placeholders only.
_V = (
    ("calm", "Designing calm software", "alpha-project", "youtube", None, "12:48", "2026-09-29", "none", "transcript",
     None, None, "transcript", True, "claude-code", "2026-09-29", "14:31", False, False, None, None),
    ("lantern", "Lantern on a Pi: sqlite-vec in five minutes", "Helios Labs", "youtube", "8:14", "8:14", "2026-09-28",
     "transcript", "transcript", None, None, "transcript", False, "claude-code", "2026-09-28", "10:12", False, True,
     None, None),
    ("rover", "Northwind rover demo", "Northwind Robotics", "youtube", None, None, "2026-09-27", "none", "none",
     "queued", "queued", "watch", False, None, None, None, None, None, None, None),
    ("meter", "Meter Sim overview", "Leo Example", "vimeo", "22:10", "22:10", "2026-09-26", "none", "none",
     "queued", "queued", "watch", False, None, None, None, None, None, None, None),
    ("bench", "Bench notes, part 2", "Leo Example", "loom", "14:02", "14:02", "2026-09-25", "recorded", "recorded",
     None, None, "transcript", False, "claude-code", "2026-09-25", "16:40", True, True, None, None),
    ("keynote", "Helios Labs keynote 2026", "Helios Labs", "youtube", None, None, "2026-09-24", "none", "none",
     None, "failed", "transcript", True, None, None, None, None, None, "no captions on this video", None),
    ("graph", "Graph layouts that don't jitter", "bob-example", "youtube", "31:45", "31:45", "2026-09-22",
     "watched_and_transcript", "watched_and_transcript", None, None, "watch", False, "claude-code", "2026-09-22",
     "09:05", True, True, None, None),
    ("embed", "Embeddings, explained slowly", "Kite School", "youtube", "18:20", "18:20", "2026-09-20", "watched",
     "watched", None, None, "watch", False, "claude-web", "2026-09-21", "18:30", False, True, None, None),
    ("wheel", "Rover wheel design, part 1", "Northwind Robotics", "youtube", None, None, "2026-09-18", "none", "none",
     None, "claimed", "watch", True, None, None, None, None, None, None, "claude-code"),
    ("spaced", "Why spaced repetition works", "Quiet Minds", "youtube", None, None, "2026-09-15", "none", "recorded",
     None, None, "transcript", True, "codex", "2026-09-29", "14:40", False, True, None, None),
    ("pixel", "Pixel art for tiny sprites", "sprite-lab", "youtube", None, None, "2026-09-12", "none", "none",
     None, None, "transcript", False, None, None, None, None, None, None, None),
    ("standup", "Standup recording, Sep 12", "alpha-project", "loom", "11:37", "11:37", "2026-09-12", "transcript",
     "transcript", None, None, "transcript", False, "claude-code", "2026-09-13", "08:20", True, False, None, None),
    ("solder", "Soldering a Pi hat without tears", "bob-example", "youtube", None, None, "2026-09-10", "none", "none",
     "queued", "queued", "transcript", False, None, None, None, None, None, None, None),
    ("server", "Sharing a local server safely", "bob-example", "youtube", None, None, "2026-09-08", "none", "none",
     None, None, "transcript", False, None, None, None, None, None, None, None),
    ("deeper", "sqlite-vec, a deeper look", "Helios Labs", "youtube", None, None, "2026-09-06", "none", "none",
     None, None, "transcript", False, None, None, None, None, None, None, None),
    ("eink", "Weekend build: an e-ink dashboard", "Leo Example", "vimeo", "9:48", "9:48", "2026-09-03", "none", "none",
     None, "queued", "watch", True, None, None, None, None, None, None, None),
    ("dry", "Lantern demo, dry run", "alpha-project", "loom", "6:05", "6:05", "2026-09-02", "transcript",
     "transcript", None, None, "transcript", False, "claude-code", "2026-09-02", "11:00", True, False, None, None),
    ("forces", "How force layouts cool", "Kite School", "youtube", None, None, "2026-08-30", "none", "none",
     None, None, "transcript", False, None, None, None, None, None, None, None),
    ("field", "Northwind field day, highlights", "Northwind Robotics", "youtube", None, None, "2026-08-28", "none",
     "none", None, None, "transcript", False, None, None, None, None, None, None, None),
    ("oneperson", "Designing for one person", "Quiet Minds", "youtube", None, None, "2026-08-24", "none", "none",
     None, None, "transcript", False, None, None, None, None, None, None, None),
    ("tour", "Helios Labs: product tour", "Helios Labs", "vimeo", "4:30", "4:30", "2026-08-20", "recorded",
     "recorded", None, None, "transcript", False, "claude-code", "2026-08-21", "13:00", True, True, None, None),
    ("codebase", "A tour of the Meter Sim codebase", "Leo Example", "loom", "27:15", "27:15", "2026-08-16", "none",
     "none", None, None, "transcript", False, None, None, None, None, None, None, None),
    ("keyboards", "Quiet keyboards, compared", "sprite-lab", "youtube", None, None, "2026-08-10", "none", "none",
     None, None, "transcript", False, None, None, None, None, None, None, None),
)
_HOSTS = {"youtube": ("youtube.com", "https://www.youtube.com/watch?v={}", "youtube"),
          "vimeo": ("vimeo.com", "https://vimeo.com/{}", "url"),
          "loom": ("loom.com", "https://www.loom.com/share/{}", "url")}
_BATCH_ID = "b_7f3"
_BATCH_AT = "2026-09-29T14:14:00Z"


def _placeholder_id(provider: str, n: int) -> str:
    return {"youtube": f"Board{n:06d}", "vimeo": f"{100000000 + n}", "loom": f"{n:032x}"}[provider]


def _seconds(text):
    if not text:
        return None
    parts = [int(p) for p in text.split(":")]
    return parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0] * 3600 + parts[1] * 60 + parts[2]


def _boards(moment: str) -> dict:
    at_b = moment == "B"
    feed, items = [], []
    for n, row in enumerate(_V, 1):
        (slug, title, channel, provider, dur_a, dur_b, saved, st_a, st_b, q_a, q_b, want, in_batch, by, rec_day, rec_time,
         sleep, approx, reason, claimed_by) = row
        site, template, media_type = _HOSTS[provider]
        url = template.format(_placeholder_id(provider, n))
        key = media_ingestor.url_hash(url)
        state, queue = (st_b, q_b) if at_b else (st_a, q_a)
        # A record that lands between the moments only exists at B.
        recorded = bool(by) and (at_b or rec_day != "2026-09-29")
        length = _seconds(dur_b if at_b else dur_a)
        feed.append({"mediaEntityId": f"media-{slug}", "url": url, "title": title, "mediaType": media_type,
                     "site": site, "channel": channel, "thumbnail": None, "savedAt": f"{saved}T09:00:00Z",
                     **({"durationS": length} if length else {}), "provider": provider if provider == "youtube" else None})
        item = {"key": key, "mediaEntityId": f"media-{slug}", "url": url, "state": state}
        if state != "none" and recorded:
            item["episodeId"] = f"ep_{rec_day}_{n:03d}"
            item["recordedAt"] = f"{rec_day}T{rec_time}:00Z"
            item["recordedBy"] = by
            item["readBySleep"] = bool(sleep)
            item["fidelity"] = "approximate" if approx else "verbatim"
            if state != "recorded":
                item["basis"] = {"transcript": "transcript", "watched": "frames",
                                 "watched_and_transcript": "both"}[state]
                item["engine"] = "video_link" if approx else "captions"
        if queue:
            item.update(want=want, queueState=queue)
            if at_b and in_batch:
                item["batch"] = _BATCH_ID
            if queue == "claimed":
                item.update(claimedBy=claimed_by, attempts=1)
            if queue == "failed":
                item.update(failedCode="no_captions", failedReason=reason, attempts=3)
        items.append(item)
    batch = None
    if at_b:
        keys = [i["key"] for v, i in zip(_V, items) if v[12]]  # the five in the hand-off, in list order
        by_key = {i["key"]: i for i in items}
        batch = {"id": _BATCH_ID, "createdAt": _BATCH_AT, "method": "auto", "total": 5, "done": 2,
                 "claimed": sum(by_key[k].get("queueState") == "claimed" for k in keys),
                 "waiting": sum(by_key[k].get("queueState") == "queued" for k in keys),
                 "failed": sum(by_key[k].get("queueState") == "failed" for k in keys), "keys": keys}
    queue_block = video_state.summary_from(items, batch)
    summary = {**queue_block, "shape": video_state.VIDEO_SHAPE}
    return {"moment": moment, "asOf": "2026-09-29T14:44:00Z" if at_b else "2026-09-29T14:13:00Z",
            "state": {"items": items, "queue": queue_block, "shape": video_state.VIDEO_SHAPE},
            "summary": summary, "feed": feed}


def test_the_boards_fixture_is_the_boards_wire():
    wire = {"note": ("The approved Video boards' one 23-video fixture in the server's wire shape. Moment A is 2:13 PM "
                     "(the picker, before the hand-off); moment B is 2:44 PM (thirty minutes after it). `feed` is the "
                     "MediaFeedItem rows the app joins by mediaEntityId|url; titles, channels and people are "
                     "placeholders."),
            "moments": {"A": _boards("A"), "B": _boards("B")}}
    text = _dump(wire)
    if WRITE:
        BOARDS.parent.mkdir(parents=True, exist_ok=True)
        BOARDS.write_text(text, encoding="utf-8")
    assert BOARDS.read_text(encoding="utf-8") == text, "rerun with CICADA_WRITE_APP_FIXTURE=1 after a deliberate change"


def test_the_picker_tabs_are_disjoint_and_sum_to_the_total_at_both_moments():
    a, b = (json.loads(BOARDS.read_text(encoding="utf-8"))["moments"][m] for m in "AB")
    ca, cb = a["summary"], b["summary"]
    assert (ca["unread"], ca["queued"] + ca["claimed"] + ca["failed"], ca["read"]) == (13, 3, 7)
    assert (cb["unread"], cb["queued"] + cb["claimed"] + cb["failed"], cb["read"]) == (8, 6, 9)
    assert (cb["queued"], cb["claimed"], cb["failed"]) == (4, 1, 1) and ca["total"] == cb["total"] == 23
    assert "batch" not in ca and cb["batch"]["total"] == 5 and cb["batch"]["done"] == 2
    assert (cb["batch"]["claimed"], cb["batch"]["waiting"], cb["batch"]["failed"]) == (1, 1, 1)
    for moment in (a, b):
        _check_wire(moment["state"], moment["summary"])
        joined = {f"{f['mediaEntityId']}|{f['url']}" for f in moment["feed"]}
        assert joined == {f"{i['mediaEntityId']}|{i['url']}" for i in moment["state"]["items"]}


def test_the_boards_fixture_is_synthetic():
    raw = BOARDS.read_text(encoding="utf-8")
    assert "/Users/" not in raw and "/private/" not in raw and "/home/" not in raw
    for url in re.findall(r"https?://[^\s\"']+", raw):
        assert url.split("/")[2] in ("www.youtube.com", "vimeo.com", "www.loom.com"), url
    assert not re.search(r"@[a-z0-9-]+\.", raw), "no address"
