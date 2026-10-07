"""G110 gate A (ruling 2026-10-07): PreCompact and SessionEnd also run the
capture hook as a best-effort, idempotent flush. Stop stays the trigger; a
flush is the same request through the same writer, so after a Stop with no new
turn it changes nothing, and it is the only capture of a turn the person
interrupted (no Stop) before clearing or quitting. The event rides into the
ledger as an enum. Synthetic fixtures only."""
from __future__ import annotations

import pytest

from api.services import telemetry
from api.tests.test_continuity_acceptance import A, B, A_TURNS, _start, _transcript, _ts, env  # noqa: F401

URL = "/capture/transcript"


def _post(env, session, turns, event):
    path = env["claude"] / f"{session}.jsonl"
    path.write_text(_transcript(session, turns), encoding="utf-8")
    r = env["client"].post(URL, json={"harness": "claude-code", "session_id": session, "transcript_path": str(path),
                                      "cwd": "/home/example/alpha-project", "hook_event": event})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("event", ["PreCompact", "SessionEnd"])
def test_a_flush_after_a_stop_with_no_new_turn_changes_nothing(env, event):
    first = _post(env, A, A_TURNS, "Stop")
    fp = env["memory"] / "episodes" / f"{first['episodeId']}.md"
    before = fp.read_bytes()
    again = _post(env, A, A_TURNS, event)
    assert first["status"] == "created" and again["status"] == "unchanged" and again["episodeId"] == first["episodeId"]
    assert fp.read_bytes() == before


def test_an_interrupted_turn_captured_at_session_end_is_disclosed_next_time(env):
    """The person asked, interrupted the reply (no Stop fires) and cleared: only
    the SessionEnd flush captures the request, and the next session hears that
    it has no captured reply."""
    _post(env, A, A_TURNS[:2], "Stop")
    interrupted = A_TURNS[:2] + [("user", "Now also handle leap days in parse_alpha.", _ts(20))]
    assert _post(env, A, interrupted, "SessionEnd")["status"] == "updated"
    note = _start(env, B)
    assert "Now also handle leap days in parse_alpha." in note
    assert "its last request has no captured reply" in note


def test_the_ledger_names_the_event_as_an_enum(env, monkeypatch, tmp_path):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    for event, expected in (("Stop", "Stop"), ("PreCompact", "PreCompact"), ("SessionEnd", "SessionEnd"),
                            ("something new", "other"), (None, "other")):
        _post(env, A, A_TURNS, event)
        ev = [e for e in telemetry.read_events() if e.kind == "capture"][-1]
        assert ev.refs["event"] == expected
