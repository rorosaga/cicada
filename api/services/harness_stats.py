"""Read-only, tolerant readers for the harnesses' OWN usage data (advanced view).

Claude Code keeps a pre-aggregated ``stats-cache.json`` (the store behind its
``/stats`` panel); Codex logs a ``rate_limits`` snapshot on every turn into
its session rollouts. Both are local files, involve no network and no
credential, and are labelled in the UI as the harness's data, not Cicada's.
Everything here returns ``None`` on any problem — never raises, and never
writes either file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _claude_config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def claude_code_stats(path: Path | None = None) -> dict | None:
    path = path or _claude_config_dir() / "stats-cache.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    hours = [0] * 24
    for k, v in (data.get("hourCounts") or {}).items():
        try:
            hours[int(k)] = int(v)
        except (ValueError, IndexError, TypeError):
            continue
    model_usage = {}
    for model, u in (data.get("modelUsage") or {}).items():
        u = u or {}
        model_usage[model] = {
            "input_tokens": int(u.get("inputTokens", 0) or 0),
            "output_tokens": int(u.get("outputTokens", 0) or 0),
            "cache_read_tokens": int(u.get("cacheReadInputTokens", 0) or 0),
            "cache_write_tokens": int(u.get("cacheCreationInputTokens", 0) or 0),
        }
    return {
        "daily_activity": [
            {"date": d.get("date"), "message_count": int(d.get("messageCount", 0) or 0),
             "session_count": int(d.get("sessionCount", 0) or 0), "tool_call_count": int(d.get("toolCallCount", 0) or 0)}
            for d in (data.get("dailyActivity") or []) if isinstance(d, dict)
        ],
        "model_usage": model_usage,
        "hour_counts": hours,
        "total_sessions": int(data.get("totalSessions", 0) or 0),
        "total_messages": int(data.get("totalMessages", 0) or 0),
        "longest_session": data.get("longestSession"),
        "first_session_date": data.get("firstSessionDate"),
        "source": str(path),
    }


def _codex_sessions_dir() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser() / "sessions"


def codex_rate_limits(sessions_dir: Path | None = None) -> dict | None:
    sessions_dir = sessions_dir or _codex_sessions_dir()
    if not sessions_dir.exists():
        return None
    files = sorted(sessions_dir.rglob("rollout-*.jsonl"), key=lambda p: p.name, reverse=True)
    for path in files[:20]:  # newest files first; stop at the first usable snapshot
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            payload = obj.get("payload") or {}
            if obj.get("type") == "event_msg" and payload.get("type") == "token_count" and payload.get("rate_limits"):
                rl = payload["rate_limits"]
                return {
                    "plan_type": rl.get("plan_type"),
                    "primary": rl.get("primary"),
                    "secondary": rl.get("secondary"),
                    "observed_at": obj.get("timestamp"),
                    "source": str(path),
                }
    return None
