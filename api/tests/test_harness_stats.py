from __future__ import annotations

import json

from api.services import harness_stats as hs


def test_claude_code_stats_reads_cache(tmp_path):
    cache = tmp_path / "stats-cache.json"
    cache.write_text(json.dumps({
        "version": 5,
        "dailyActivity": [{"date": "2026-08-27", "messageCount": 40, "sessionCount": 3, "toolCallCount": 12}],
        "dailyModelTokens": [],
        "modelUsage": {"claude-sonnet-5": {"inputTokens": 100, "outputTokens": 20, "cacheReadInputTokens": 5, "cacheCreationInputTokens": 1}},
        "totalSessions": 10, "totalMessages": 400,
        "longestSession": {"sessionId": "s", "duration": 3600000, "messageCount": 90, "timestamp": "2026-08-01T00:00:00Z"},
        "firstSessionDate": "2026-05-01", "hourCounts": {"9": 4, "23": 1},
    }))
    got = hs.claude_code_stats(cache)
    assert got["daily_activity"][0] == {"date": "2026-08-27", "message_count": 40, "session_count": 3, "tool_call_count": 12}
    assert got["model_usage"]["claude-sonnet-5"] == {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 5, "cache_write_tokens": 1}
    assert got["hour_counts"][9] == 4 and got["hour_counts"][23] == 1 and len(got["hour_counts"]) == 24
    assert got["total_sessions"] == 10 and got["source"] == str(cache)


def test_claude_code_stats_missing_or_corrupt(tmp_path):
    assert hs.claude_code_stats(tmp_path / "nope.json") is None
    (tmp_path / "bad.json").write_text("{")
    assert hs.claude_code_stats(tmp_path / "bad.json") is None


def test_codex_rate_limits_newest_token_count(tmp_path):
    day = tmp_path / "2026" / "08" / "28"
    day.mkdir(parents=True)
    older = day / "rollout-2026-08-28T01-00-00-aaa.jsonl"
    newer = day / "rollout-2026-08-28T02-00-00-bbb.jsonl"
    older.write_text(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
        "plan_type": "plus", "primary": {"used_percent": 10, "window_minutes": 300, "resets_at": 1}}}}) + "\n")
    newer.write_text("\n".join([
        json.dumps({"type": "session_meta", "payload": {"id": "x"}}),
        json.dumps({"type": "event_msg", "timestamp": "2026-08-28T02:05:00Z", "payload": {"type": "token_count", "rate_limits": {
            "plan_type": "plus", "primary": {"used_percent": 42.5, "window_minutes": 300, "resets_at": 1756350000},
            "secondary": {"used_percent": 12, "window_minutes": 10080, "resets_at": 1756800000}}}}),
    ]) + "\n")
    got = hs.codex_rate_limits(tmp_path)
    assert got["plan_type"] == "plus" and got["primary"]["used_percent"] == 42.5
    assert got["secondary"]["window_minutes"] == 10080 and got["source"].endswith("bbb.jsonl")


def test_codex_rate_limits_none_when_absent(tmp_path):
    assert hs.codex_rate_limits(tmp_path) is None
