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


def test_cached_tokens_are_not_counted_twice():
    """`input_tokens` is the GROSS prompt (litellm's `Usage.prompt_tokens`
    contract), so the cache buckets are a breakdown of it, not an addition."""
    ev = tm.UsageEvent(kind="llm_call", input_tokens=100, output_tokens=20,
                       cache_read_tokens=40, cache_write_tokens=10)
    assert ev.tokens == 120


def test_raw_anthropic_usage_is_grossed_up_so_the_total_still_holds():
    """A raw Anthropic SDK usage object (no `prompt_tokens`) reports
    `input_tokens` EXCLUDING the cache buckets — the one shape that has to be
    added up, so that `tokens` means the same thing for every provider."""
    class _Resp:
        usage = {"input_tokens": 60, "output_tokens": 20,
                 "cache_read_input_tokens": 30, "cache_creation_input_tokens": 10}

    got = tm.usage_from_response(_Resp())
    assert got["input_tokens"] == 100  # 60 fresh + 30 read + 10 written
    assert got["cache_read_tokens"] == 30 and got["cache_write_tokens"] == 10
    assert tm.UsageEvent(kind="llm_call", **{k: v for k, v in got.items() if k != "cost_usd"}).tokens == 120


def test_a_valid_json_non_object_line_is_skipped_not_raised(home):
    """A bare string/number/list line is corruption like any other: `read_events`
    counts and skips it. It used to hit `.items()` -> AttributeError, which
    nothing catches, taking every /consumption/* endpoint down with it."""
    tm.record(_ev("2026-08-15T00:00:00.000Z"))
    with open(home / "telemetry" / "events-2026-08.jsonl", "a") as fh:
        fh.write('"just a string"\n')
        fh.write("42\n")
        fh.write('[{"kind":"llm_call"}]\n')
        fh.write("null\n")
    events = tm.read_events()
    assert len(events) == 1 and events[0].ts.startswith("2026-08-15")

    with pytest.raises(ValueError):
        tm.UsageEvent.from_json("42")


def test_a_null_ts_is_skipped_not_raised(home):
    """D4: a JSON *object* whose `ts` is null/non-string survives dataclass
    construction with no error, then used to crash `ev.ts[:10]` OUTSIDE
    `read_events`'s try/except — one such line 500s every /consumption/*
    endpoint instead of being counted+skipped like any other corrupt line."""
    tm.record(_ev("2026-08-15T00:00:00.000Z"))
    with open(home / "telemetry" / "events-2026-08.jsonl", "a") as fh:
        fh.write(json.dumps({"kind": "llm_call", "ts": None}) + "\n")
        fh.write(json.dumps({"kind": "llm_call", "ts": 12345}) + "\n")
        fh.write(json.dumps({"kind": "llm_call", "ts": ""}) + "\n")

    events = tm.read_events()
    assert len(events) == 1 and events[0].ts.startswith("2026-08-15")

    with pytest.raises(ValueError):
        tm.UsageEvent.from_json(json.dumps({"kind": "llm_call", "ts": None}))


def test_malformed_numeric_counters_are_skipped_not_raised(home):
    """D4: a counter field (`input_tokens`, etc.) that arrives as a string,
    null, or nested structure instead of a number must be rejected at parse
    time — not silently held as garbage that breaks arithmetic downstream."""
    tm.record(_ev("2026-08-15T00:00:00.000Z"))
    bad_shapes = [
        {"kind": "llm_call", "ts": "2026-08-16T00:00:00.000Z", "input_tokens": "not-a-number"},
        {"kind": "llm_call", "ts": "2026-08-17T00:00:00.000Z", "output_tokens": None},
        {"kind": "llm_call", "ts": "2026-08-18T00:00:00.000Z", "invocations": [1, 2]},
        {"kind": "llm_call", "ts": "2026-08-19T00:00:00.000Z", "cache_read_tokens": {"n": 1}},
        {"kind": "llm_call", "ts": "2026-08-20T00:00:00.000Z", "duration_ms": "slow"},
    ]
    with open(home / "telemetry" / "events-2026-08.jsonl", "a") as fh:
        for shape in bad_shapes:
            fh.write(json.dumps(shape) + "\n")

    events = tm.read_events()
    assert len(events) == 1 and events[0].ts.startswith("2026-08-15")

    for shape in bad_shapes:
        with pytest.raises(ValueError):
            tm.UsageEvent.from_json(json.dumps(shape))
