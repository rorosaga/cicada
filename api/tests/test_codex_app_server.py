"""R-E18 — the read-only app-server probe. Reply shapes from codex-cli
0.154.0 (2026-09-23): signed in (R2 §2.4, email redacted) and signed out
(an empty isolated home: account null, rateLimits -32600, model/list still
answers)."""
from __future__ import annotations

import asyncio
import json
import sys

from loguru import logger

from api.services import codex_app_server
from api.services.connections import base

ROSTER = {"id": 4, "result": {"data": [
    {"id": "gpt-6-astra", "model": "gpt-6-astra", "hidden": False, "isDefault": True},
    {"id": "gpt-5.6-luna", "model": "gpt-5.6-luna", "hidden": False, "isDefault": False},
    {"id": "internal", "model": "internal", "hidden": True, "isDefault": False}], "nextCursor": None}}
SIGNED_IN = {
    "initialize": {"id": 1, "result": {"userAgent": "cicada/0.154.0"}},
    "account/read": {"id": 2, "result": {"account": {"type": "chatgpt", "email": "bob@example.com",
                                                     "planType": "prolite"}, "requiresOpenaiAuth": True}},
    "account/rateLimits/read": {"id": 3, "result": {"rateLimits": {
        "limitId": "codex", "planType": "prolite",
        "primary": {"windowDurationMins": 10080, "usedPercent": 27, "resetsAt": 1790600000},
        "secondary": None, "rateLimitReachedType": None}, "ordinaryUsageAllowed": True}},
    "model/list": ROSTER,
}
SIGNED_OUT = {
    "initialize": SIGNED_IN["initialize"],
    "account/read": {"id": 2, "result": {"account": None, "requiresOpenaiAuth": True}},
    "account/rateLimits/read": {"id": 3, "error": {"code": -32600, "message":
        "codex account authentication required to read rate limits"}},
    "model/list": ROSTER,
}


def test_a_signed_in_snapshot_reads_plan_limits_and_the_roster_default_first():
    snap = codex_app_server.parse_snapshot(SIGNED_IN)
    assert (snap.signed_in, snap.account_type, snap.plan, snap.email) == (True, "chatgpt", "prolite", "bob@example.com")
    assert (snap.used_percent, snap.resets_at, snap.limit_reached, snap.ordinary_usage_allowed) == (27, 1790600000, None, True)
    assert snap.models == ("gpt-6-astra", "gpt-5.6-luna") and snap.default_model == "gpt-6-astra"


def test_a_signed_out_snapshot_still_lists_models():
    snap = codex_app_server.parse_snapshot(SIGNED_OUT)
    assert snap.signed_in is False and snap.plan is None and snap.used_percent is None
    assert snap.models == ("gpt-6-astra", "gpt-5.6-luna")


def test_a_reached_limit_is_read_off_the_snapshot():
    replies = json.loads(json.dumps(SIGNED_IN))
    replies["account/rateLimits/read"]["result"]["rateLimits"]["rateLimitReachedType"] = "rate_limit_reached"
    assert codex_app_server.parse_snapshot(replies).limit_reached == "rate_limit_reached"


def test_the_snapshot_is_cached_until_fresh_or_invalidated():
    calls = []

    async def transport(*, timeout):
        calls.append(timeout)
        return SIGNED_IN

    assert asyncio.run(codex_app_server.snapshot(transport=transport)).plan == "prolite"
    asyncio.run(codex_app_server.snapshot(transport=transport))
    assert len(calls) == 1
    asyncio.run(codex_app_server.snapshot(fresh=True, transport=transport))
    codex_app_server.invalidate()
    asyncio.run(codex_app_server.snapshot(transport=transport))
    assert len(calls) == 3


def test_a_failing_probe_degrades_to_none_and_never_logs_a_reply():
    """A loguru sink, not `caplog`: loguru does not propagate to the stdlib
    logging `caplog` reads, so a `caplog` assertion here would pass
    vacuously whatever the module logged."""
    async def transport(*, timeout):
        raise OSError("boom bob@example.com")

    lines: list[str] = []
    sink_id = logger.add(lambda message: lines.append(str(message)), level="DEBUG")
    try:
        assert asyncio.run(codex_app_server.snapshot(transport=transport)) is None
    finally:
        logger.remove(sink_id)
    assert lines, "the degrade path logs one line — the sink must have captured it"
    assert not any("bob@example.com" in line for line in lines)


_FAKE_APP_SERVER = r'''#!@PYTHON@
import json, os, sys
replies = json.load(open(os.environ["CICADA_FAKE_REPLIES"]))
seen = open(os.environ["CICADA_FAKE_SEEN"], "a")
seen.write(json.dumps({"argv": sys.argv[1:], "codex_home": os.environ.get("CODEX_HOME")}) + "\n"); seen.flush()
for line in sys.stdin:
    msg = json.loads(line)
    seen.write(line); seen.flush()
    if "id" not in msg:
        continue
    if msg["method"] == "initialize":
        print(json.dumps({"method": "remoteControl/status/changed", "params": {"status": "disabled"}}), flush=True)
    body = dict(replies[msg["method"]]); body["id"] = msg["id"]
    print(json.dumps(body), flush=True)
'''


def test_the_stdio_transport_speaks_the_verified_protocol(tmp_path, monkeypatch, real_app_server_transport):
    script = tmp_path / "codex"
    script.write_text(_FAKE_APP_SERVER.replace("@PYTHON@", sys.executable), encoding="utf-8")
    script.chmod(0o755)
    replies = tmp_path / "replies.json"
    replies.write_text(json.dumps(SIGNED_IN), encoding="utf-8")
    seen = tmp_path / "seen.jsonl"
    monkeypatch.setenv("CICADA_CODEX_CLI", str(script))
    monkeypatch.setenv("CICADA_FAKE_REPLIES", str(replies))
    monkeypatch.setenv("CICADA_FAKE_SEEN", str(seen))
    got = asyncio.run(real_app_server_transport(timeout=5.0))
    snap = codex_app_server.parse_snapshot(got)
    assert snap.plan == "prolite" and snap.models[0] == "gpt-6-astra"
    first, *sent = [json.loads(line) for line in seen.read_text().splitlines()]
    assert first == {"argv": ["app-server", "--listen", "stdio://"], "codex_home": str(base.codex_home())}
    assert [m["method"] for m in sent] == ["initialize", "initialized", "account/read",
                                           "account/rateLimits/read", "model/list"]
    assert sent[2]["params"] == {"refreshToken": False}
