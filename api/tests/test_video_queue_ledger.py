"""G162 N-9 (M4) — the `video_queue` ledger kind: ids and enums only, filed beside `read` so it never ticks the
consumption domain, and absent from every Usage view. Mirrors the reading ledger's test."""
from __future__ import annotations

import json
from datetime import date

import pytest

from _video_fixtures import bank_with_videos, url_of
from api.services import consumption_stats, mcp_tools, sync_service, telemetry, video_queue


@pytest.fixture(autouse=True)
def _telemetry_on(monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")


def _rows():
    path = telemetry.ledger_file(f"{date.today():%Y-%m}", kind="video_queue")
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.fixture
def rig(tmp_path, monkeypatch):
    memory, keys = bank_with_videos(tmp_path, 2)
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_ledger_01", harness="acme-agent")
    return ctx, memory, keys


def test_telemetry_video_queue_ids_only(rig):
    ctx, memory, keys = rig
    video_queue.put(memory, keys[0], "watch")
    video_queue.put(memory, keys[1], "watch")
    mcp_tools.video_claim(ctx)
    mcp_tools.video_claim(ctx, release=[{"url": url_of("00"), "code": "needs_login",
                                         "reason": "a reason the ledger must not keep"}])
    mcp_tools.record_watch(ctx, url_of("01"), "A summary the ledger must not keep.", None, None, "frames")
    rows = [r for r in _rows() if r["kind"] == "video_queue"]
    assert [r["refs"]["action"] for r in rows] == ["claim", "release", "complete"]
    for row in rows:
        assert set(row["refs"]) <= {"action", "count", "code", "harness", "connector_id"}
        assert row["refs"]["harness"] == "acme-agent" and row["invocations"] == 0 and row["billing"] == "free"
    assert rows[0]["refs"]["count"] == 2 and rows[1]["refs"]["code"] == "needs_login"
    text = json.dumps(rows)
    for leak in ("youtube", "http", "must not keep", "Video 0"):
        assert leak not in text


def test_the_kind_is_filed_beside_read_and_never_moves_the_consumption_component(rig):
    ctx, memory, keys = rig
    video_queue.put(memory, keys[0], "watch")
    before = sync_service.components(memory)["telemetry"]
    mcp_tools.video_claim(ctx)
    assert sync_service.components(memory)["telemetry"] == before
    assert telemetry.ledger_file("2026-09", kind="video_queue").name.startswith("reads-")
    assert "video_queue" in telemetry.KINDS and "video_queue" in telemetry.NON_SPEND_KINDS
    assert "video_queue" in telemetry.SIBLING_KINDS


def test_the_kind_is_absent_from_every_usage_view():
    row = telemetry.UsageEvent(kind="video_queue", stage="driver", billing="free", invocations=0,
                               refs={"action": "claim", "count": 1, "harness": "h"})
    assert consumption_stats._activity([row]) == []
    assert telemetry.VIDEO_QUEUE_KIND in consumption_stats.PER_TURN_KINDS


def test_a_scrubbed_reason_leaves_a_capture_row_naming_the_writer_not_other(rig):
    ctx, memory, keys = rig
    video_queue.put(memory, keys[0], "watch")
    mcp_tools.video_claim(ctx)
    secret = "sk-" + "a1b2c3d4e5f6a7b8c9d0e1f2"
    mcp_tools.video_claim(ctx, release=[{"url": url_of("00"), "reason": f"token {secret}"}])
    path = telemetry.ledger_file(f"{date.today():%Y-%m}")
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    capture = [r for r in rows if r["kind"] == "capture"]
    assert capture and capture[-1]["refs"]["writer"] == "video_queue"
    assert secret not in json.dumps(rows)
