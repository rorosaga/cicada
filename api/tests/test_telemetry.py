from __future__ import annotations

import json
import stat
from datetime import date

import pytest

from api.services import telemetry as tm


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    return tmp_path


def _ev(ts: str, **kw) -> tm.UsageEvent:
    base = dict(kind="llm_call", stage="extraction", model="gpt-5.4-mini", input_tokens=10, output_tokens=5)
    base.update(kw)
    return tm.UsageEvent(ts=ts, **base)


def test_record_appends_monthly_file_0600(home):
    tm.record(_ev("2026-08-28T03:00:00.000Z"))
    tm.record(_ev("2026-08-29T03:00:00.000Z", output_tokens=7))
    path = home / "telemetry" / "events-2026-08.jsonl"
    lines = path.read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["output_tokens"] == 7
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_read_events_by_range_and_skips_bad_lines(home):
    tm.record(_ev("2026-07-31T23:00:00.000Z"))
    tm.record(_ev("2026-08-01T00:00:00.000Z"))
    tm.record(_ev("2026-08-15T00:00:00.000Z"))
    with open(home / "telemetry" / "events-2026-08.jsonl", "a") as fh:
        fh.write("{not json\n")
    assert len(tm.read_events()) == 3
    aug = tm.read_events(start=date(2026, 8, 1), end=date(2026, 8, 31))
    assert [e.ts[:10] for e in aug] == ["2026-08-01", "2026-08-15"]


def test_disabled_writes_nothing(home, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    tm.record(_ev("2026-08-28T03:00:00.000Z"))
    assert not (home / "telemetry").exists() or not list((home / "telemetry").glob("*.jsonl"))


def test_usage_from_response_dict_and_object():
    class _Resp:
        class usage:  # noqa: N801 — mimics litellm's object attr style
            prompt_tokens = 100
            completion_tokens = 20

            class prompt_tokens_details:  # noqa: N801
                cached_tokens = 40

        _hidden_params = {"response_cost": 0.0021}

    got = tm.usage_from_response(_Resp())
    assert got == {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 40, "cache_write_tokens": 0, "cost_usd": 0.0021}

    class _DictResp:
        usage = {"prompt_tokens": 3, "completion_tokens": 4, "cost": 0.5}

    assert tm.usage_from_response(_DictResp()) == {"input_tokens": 3, "output_tokens": 4, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 0.5}
    assert tm.usage_from_response(object())["input_tokens"] == 0


@pytest.mark.parametrize("model,expected", [
    ("ollama/qwen3:8b", ("ollama-local", "free")),
    ("openrouter/z-ai/glm-5.2", ("byok-openrouter", "usage")),
    ("anthropic/claude-sonnet-5", ("byok-anthropic", "usage")),
    ("gemini/gemini-2.5-flash", ("byok-gemini", "usage")),
    ("gpt-5.4-mini", ("byok-openai", "usage")),
])
def test_connection_for_model(model, expected):
    assert tm.connection_for_model(model) == expected


def test_roundtrip_ignores_unknown_fields():
    ev = tm.UsageEvent.from_json('{"ts":"2026-08-28T00:00:00Z","kind":"ask","future_field":1}')
    assert ev.kind == "ask" and ev.invocations == 1
