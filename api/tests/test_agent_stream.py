"""R-E1/R-E9 — the stream-json reader. Shapes: `system/init` and
`rate_limit_event` from claude-agent-sdk 0.2.157's parser tests (R1 §2.7),
`system/api_retry` from code.claude.com/docs/en/headless, and the `result`
line is the json-mode envelope verbatim (conftest `agent_envelopes`)."""
from __future__ import annotations

import json
from pathlib import Path

from api.services import agent_engine, agent_stream
from api.services.connections.base import CliResult


def test_the_last_result_line_is_the_envelope(claude_stream, agent_envelopes):
    out = agent_stream.parse_stream(claude_stream("success"))
    assert out.envelope == agent_envelopes["success"]
    assert out.api_key_source == "none" and out.json_lines == 2


def test_rate_limit_events_and_retries_are_collected_in_order(claude_stream):
    out = agent_stream.parse_stream(claude_stream(
        "success",
        rate_limits=[{"status": "allowed", "rateLimitType": "five_hour", "utilization": 0.5},
                     {"status": "allowed_warning", "rateLimitType": "five_hour",
                      "utilization": 0.92, "resetsAt": 1790000000, "isUsingOverage": False}],
        retries=[{"error": "rate_limit", "error_status": 429}]))
    assert [s.status for s in out.rate_limits] == ["allowed", "allowed_warning"]
    assert out.rate_limits[1].utilization == 0.92 and out.rate_limits[1].resets_at == 1790000000
    assert out.retries == [agent_stream.RetrySignal(error="rate_limit", status=429)]


def test_a_percentage_is_never_read_as_92x_over(claude_stream):
    out = agent_stream.parse_stream(claude_stream(
        "success", rate_limits=[{"status": "allowed_warning", "rateLimitType": "five_hour",
                                 "utilization": 92}]))
    assert out.rate_limits[0].utilization == 0.92


def test_an_overage_window_counts_as_overage_even_without_the_flag(claude_stream):
    out = agent_stream.parse_stream(claude_stream(
        "success", rate_limits=[{"status": "allowed", "rateLimitType": "overage"}]))
    assert out.rate_limits[0].using_overage is True


def test_unknown_events_malformed_lines_and_partial_deltas_are_ignored(claude_stream):
    text = "not json\n" + json.dumps({"type": "stream_event", "event": {}}) + "\n[1, 2]\n" \
        + claude_stream("success")
    out = agent_stream.parse_stream(text)
    assert out.envelope is not None and out.rate_limits == [] and out.retries == []


def test_a_single_json_mode_object_is_still_the_envelope(agent_envelopes):
    out = agent_stream.parse_stream(json.dumps(agent_envelopes["success"]))
    assert out.envelope == agent_envelopes["success"]


def test_no_result_line_leaves_no_envelope(claude_stream):
    assert agent_stream.parse_stream(claude_stream(None)).envelope is None
    assert agent_stream.parse_stream("").json_lines == 0


def test_the_stream_envelope_shims_exactly_like_json_mode(claude_stream, agent_envelopes):
    streamed = agent_engine.parse_envelope(CliResult(0, claude_stream("success"), ""))
    classic = agent_engine.parse_envelope(CliResult(0, json.dumps(agent_envelopes["success"]), ""))
    assert agent_engine.response_shim(streamed, "sonnet") == agent_engine.response_shim(classic, "sonnet")


def test_the_live_recorded_stream_parses():
    """claude 2.1.280, 2026-09-23, sanitised (Task 2 Step 6 of the Track E plan)."""
    text = (Path(__file__).parent / "fixtures" / "claude_stream_live.jsonl").read_text(encoding="utf-8")
    out = agent_stream.parse_stream(text)
    assert out.envelope is not None and out.envelope.get("is_error") is False
    assert out.api_key_source is not None
    assert agent_engine.parse_envelope(CliResult(0, text, ""))["subtype"] == "success"


def test_the_live_utilization_is_read_from_unified_windows():
    """The live 2.1.280 `rate_limit_info` carries NO top-level `utilization` —
    each window's fraction sits under `unifiedWindows.<window>`. Reading only
    the top-level key would leave the 90 % rule blind on every real stream."""
    text = (Path(__file__).parent / "fixtures" / "claude_stream_live.jsonl").read_text(encoding="utf-8")
    [signal] = [s for s in agent_stream.parse_stream(text).rate_limits if s.limit_type == "five_hour"]
    assert signal.status == "allowed" and signal.utilization == 0.49
    assert signal.resets_at == 1790000000 and signal.using_overage is False


def test_a_five_hour_window_beside_a_weekly_event_still_reaches_the_stop_rule(claude_stream):
    out = agent_stream.parse_stream(claude_stream("success", rate_limits=[{
        "status": "allowed_warning", "rateLimitType": "seven_day", "resetsAt": 1790000000,
        "isUsingOverage": False,
        "unifiedWindows": {"five_hour": {"utilization": 0.93, "resetsAt": 1790000500},
                           "seven_day": {"utilization": 0.81, "resetsAt": 1790000000}}}]))
    by_type = {s.limit_type: s for s in out.rate_limits}
    assert by_type["seven_day"].status == "allowed_warning" and by_type["seven_day"].utilization == 0.81
    assert by_type["five_hour"].utilization == 0.93 and by_type["five_hour"].resets_at == 1790000500
    # The reported window stays LAST, so the throttle refs name it.
    assert out.rate_limits[-1].limit_type == "seven_day"
    # A window listed beside the reported one was not the one the CLI flagged:
    # it never carries a rejection, only its fraction.
    assert by_type["five_hour"].status == "allowed"
