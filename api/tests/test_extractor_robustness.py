"""Stage-1 extraction hardening for reasoning models (GLM 5.2 via OpenRouter).

A live consolidation run failed 94/208 episodes: GLM 5.2's reasoning made big
chunks blow litellm's 600s timeout and intermittently return non-JSON content.
The fixes proven here:
  * reasoning is DISABLED on the call (extra_body={"reasoning":{"enabled":False}})
    — empirically 4x faster / 3x cheaper, valid JSON;
  * an explicit timeout so a hung call fails fast;
  * lenient JSON parsing tolerant of fences / reasoning prefixes / trailing text;
  * retry-once on timeout / rate-limit / parse failure;
  * a still-failing episode is OMITTED from extract()'s result (so the resumable
    Sleep queue retries it) and never aborts the batch.

Hermetic: litellm.acompletion is monkeypatched — no network.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import litellm
import pytest

from api.services import entity_extractor as ex


async def _noop_sleep(*_a, **_k):
    return None


def _resp(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


# --------------------------- lenient JSON parser --------------------------- #


def test_parse_plain_json():
    assert ex._parse_json_lenient('{"entities": [], "relationships": []}') == {
        "entities": [],
        "relationships": [],
    }


def test_parse_fenced_json():
    raw = '```json\n{"entities": [{"name": "X"}], "relationships": []}\n```'
    assert ex._parse_json_lenient(raw)["entities"][0]["name"] == "X"


def test_parse_reasoning_prefixed_json():
    raw = (
        "Let me think about this conversation.\n"
        "The key entities are FastAPI and sqlite-vec.\n"
        '{"entities": [{"name": "Y"}], "relationships": []}'
    )
    assert ex._parse_json_lenient(raw)["entities"][0]["name"] == "Y"


def test_parse_trailing_text():
    raw = '{"entities": [], "relationships": []}\n\nThat completes the extraction.'
    assert ex._parse_json_lenient(raw) == {"entities": [], "relationships": []}


def test_parse_empty_raises():
    for bad in (None, "", "   \n  "):
        with pytest.raises(ValueError):
            ex._parse_json_lenient(bad)


def test_parse_garbage_raises():
    with pytest.raises(ValueError):
        ex._parse_json_lenient("there is no json object in this text at all")


# ---------------------- reasoning-off + timeout passed --------------------- #


def test_extract_chunk_passes_reasoning_off_and_timeout(monkeypatch):
    captured = {}

    async def fake_acompletion(**kw):
        captured.update(kw)
        return _resp('{"entities": [], "relationships": []}')

    monkeypatch.setattr(ex.litellm, "acompletion", fake_acompletion)
    s = SimpleNamespace(litellm_model="openrouter/z-ai/glm-5.2")
    asyncio.run(ex._extract_chunk("ep1", "hello", 0, 1, s))

    assert captured.get("extra_body") == {"reasoning": {"enabled": False}}
    assert captured.get("timeout") == ex.EXTRACTION_TIMEOUT_S
    assert captured.get("response_format") == {"type": "json_object"}


# ------------------------- retry on timeout / parse ------------------------ #


def test_extract_chunk_retries_on_timeout_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def fake_acompletion(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise litellm.exceptions.Timeout(
                message="timed out", model="m", llm_provider="openrouter"
            )
        return _resp('{"entities": [{"name": "Z"}], "relationships": []}')

    monkeypatch.setattr(ex.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(ex.asyncio, "sleep", _noop_sleep)
    s = SimpleNamespace(litellm_model="m")
    out = asyncio.run(ex._extract_chunk("ep1", "hello", 0, 1, s))
    assert out["entities"][0]["name"] == "Z"
    assert calls["n"] == 2


def test_extract_chunk_retries_on_bad_json_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def fake_acompletion(**kw):
        calls["n"] += 1
        return _resp("not json" if calls["n"] == 1 else '{"entities": [], "relationships": []}')

    monkeypatch.setattr(ex.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(ex.asyncio, "sleep", _noop_sleep)
    s = SimpleNamespace(litellm_model="m")
    out = asyncio.run(ex._extract_chunk("ep1", "hello", 0, 1, s))
    assert out == {"entities": [], "relationships": []}
    assert calls["n"] == 2


# ----------------- a failing episode is omitted, batch survives ------------ #


def test_extract_omits_failed_episode_and_keeps_good(monkeypatch):
    async def fake_acompletion(**kw):
        content = kw["messages"][-1]["content"]
        if "BADEP" in content:
            return _resp("totally not json, just reasoning forever")
        return _resp('{"entities": [{"name": "G", "type": "tool"}], "relationships": []}')

    monkeypatch.setattr(ex.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(ex.asyncio, "sleep", _noop_sleep)
    s = SimpleNamespace(litellm_model="m")
    eps = [
        {"id": "ep_good", "content": "good content here", "timestamp": "t", "origin": "x"},
        {"id": "ep_bad", "content": "BADEP content here", "timestamp": "t", "origin": "x"},
    ]
    out = asyncio.run(ex.extract(eps, s))
    ids = {r["episode_id"] for r in out}
    assert "ep_good" in ids
    assert "ep_bad" not in ids  # failed after retry -> omitted -> requeued by the cycle
