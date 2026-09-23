"""R-E1 end to end on a real subprocess: the fake `claude` (conftest
`fake_cli`) prints a recorded stream and reports its argv and environment."""
from __future__ import annotations

import json

import pytest

from api.config import Settings
from api.services import agent_engine, engine_errors, providers
from api.services.telemetry import UsageEvent


def test_a_92_percent_window_keeps_the_answer_stops_the_rest_and_never_leaks_an_override(
        fake_cli, claude_stream, monkeypatch):
    read_seen = fake_cli("claude", claude_stream("success", rate_limits=[
        {"status": "allowed_warning", "rateLimitType": "five_hour", "utilization": 0.92,
         "resetsAt": 1790000000, "isUsingOverage": False}]),
        watch=("CLAUDE_CODE_MAX_RETRIES", "CICADA_CAPTURE", "ANTHROPIC_AUTH_TOKEN"))
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "leak")
    events: list[UsageEvent] = []
    fn = providers.resolve_llm_fn(Settings(llm_mode="agent", agent_max_concurrency=1),
                                  stage="extraction", sink=events.append, is_async=False,
                                  scope="sleep:fake-cli")
    resp = fn(messages=[{"role": "system", "content": "SYS"}, {"role": "user", "content": "hello"}],
              response_format={"type": "json_object"}, extra_body={"reasoning": {"enabled": False}})
    assert json.loads(resp.choices[0].message.content) == {"entities": [], "relationships": []}
    [seen] = read_seen()
    argv = seen["argv"]
    assert argv[argv.index("--output-format") + 1] == "stream-json" and "--verbose" in argv
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--effort") + 1] == "low"
    assert seen["stdin"] == "hello"
    assert seen["env"] == {"CLAUDE_CODE_MAX_RETRIES": "2", "CICADA_CAPTURE": "off",
                           "ANTHROPIC_AUTH_TOKEN": None}
    assert "92% used" in agent_engine.breaker_reason(scope="sleep:fake-cli")
    with pytest.raises(engine_errors.EngineThrottled):
        fn(messages=[{"role": "user", "content": "again"}])
    assert len(read_seen()) == 1
    assert [e.kind for e in events].count("throttle") == 1
