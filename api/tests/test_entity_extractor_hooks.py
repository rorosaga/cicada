"""Stage 1's per-conversation hooks (Sleep page v5): started, read, failed (with the exception the drain
classifies), skipped (the reserve line, a soft stop) — all optional, so every existing caller is unchanged."""
from __future__ import annotations

import asyncio

from api.config import Settings
from api.services import engine_errors, entity_extractor


def _eps(n):
    return [{"id": f"ep_2026-09-01_{i:03d}", "content": f"body {i}", "timestamp": "2026-09-01T10:00:00",
             "origin": "claude-code"} for i in range(n)]


def _ok(**_kw):
    return {"entities": [{"name": "Alpha", "type": "concept", "confidence": 0.9}], "relationships": []}


def test_every_outcome_is_reported_with_the_exception_for_a_failure(monkeypatch):
    boom = {"ep_2026-09-01_001": engine_errors.EngineProtocolError("finished without an answer"),
            "ep_2026-09-01_002": engine_errors.EngineUnavailable("signed out")}

    async def chunk(ep_id, chunk_text, ci, total, settings, **kw):
        if ep_id in boom:
            raise boom[ep_id]
        return _ok()

    monkeypatch.setattr(entity_extractor, "_extract_chunk", chunk)
    started, read, failed, skipped = [], [], [], []
    out = asyncio.run(entity_extractor.extract(
        _eps(4), Settings(),
        on_episode_started=lambda ep: started.append(ep["id"]),
        on_episode_read=lambda ep: read.append(ep["id"]),
        on_episode_failed=lambda ep, exc: failed.append((ep["id"], type(exc).__name__)),
        on_episode_skipped=lambda ep: skipped.append(ep["id"])))
    assert sorted(started) == [e["id"] for e in _eps(4)]
    assert sorted(read) == ["ep_2026-09-01_000", "ep_2026-09-01_003"] and len(out) == 2
    assert sorted(failed) == [("ep_2026-09-01_001", "EngineProtocolError"), ("ep_2026-09-01_002", "EngineUnavailable")]
    assert skipped == []


def test_the_stop_check_starts_no_new_read_and_marks_the_rest_skipped_not_failed(monkeypatch):
    calls = []

    async def chunk(ep_id, *a, **kw):
        calls.append(ep_id)
        return _ok()

    monkeypatch.setattr(entity_extractor, "_extract_chunk", chunk)
    started, failed, skipped = [], [], []
    out = asyncio.run(entity_extractor.extract(
        _eps(3), Settings(), stop_check=lambda: True,
        on_episode_started=lambda ep: started.append(ep["id"]),
        on_episode_failed=lambda ep, exc: failed.append(ep["id"]),
        on_episode_skipped=lambda ep: skipped.append(ep["id"])))
    assert out == [] and calls == [] and started == [] and failed == [], "no paid call, and not a failure"
    assert sorted(skipped) == [e["id"] for e in _eps(3)]


def test_a_hook_that_raises_never_fails_the_read(monkeypatch):
    async def chunk(*a, **kw):
        raise engine_errors.EngineTimeout("slow")

    monkeypatch.setattr(entity_extractor, "_extract_chunk", chunk)

    def bad(ep, exc):
        raise RuntimeError("a progress hook broke")

    out = asyncio.run(entity_extractor.extract(_eps(2), Settings(), on_episode_failed=bad))
    assert out == []


def test_without_any_hook_it_is_exactly_what_it_was(monkeypatch):
    async def chunk(*a, **kw):
        return _ok()

    monkeypatch.setattr(entity_extractor, "_extract_chunk", chunk)
    assert len(asyncio.run(entity_extractor.extract(_eps(3), Settings()))) == 3
