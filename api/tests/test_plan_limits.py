"""R-E12 — when a plan engine stops, and the one sentence it says."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from api.services import plan_limits
from api.services.agent_stream import RateLimitSignal

NOW = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
AT_14 = int(datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc).timestamp())
TUE_14 = int(datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc).timestamp())


def _stop(*signals, allow_overage=False, stop=0.9):
    return plan_limits.claude_stop(list(signals), allow_overage=allow_overage,
                                   stop_utilization=stop, now=NOW, tz=timezone.utc)


def test_reset_phrase_is_the_vendors_own_time_and_never_a_guess():
    assert plan_limits.reset_phrase(AT_14, now=NOW, tz=timezone.utc) == "after 14:00"
    assert plan_limits.reset_phrase(TUE_14, now=NOW, tz=timezone.utc) == "after Tue 14:00"
    assert plan_limits.reset_phrase(None, now=NOW) == ""
    assert plan_limits.reset_phrase(True, now=NOW) == ""


def test_extra_usage_stops_first_unless_opted_in():
    signal = RateLimitSignal("allowed", "five_hour", 0.95, AT_14, using_overage=True)
    stop = _stop(signal)
    assert stop.kind == "overage" and "extra usage" in stop.sentence
    assert "It can run again after 14:00." in stop.sentence
    near = _stop(signal, allow_overage=True)
    assert near.kind == "near_limit"          # opted in: the 5-hour rule still applies


def test_a_rejected_window_stops_with_its_name():
    assert "5-hour limit" in _stop(RateLimitSignal("rejected", "five_hour", resets_at=AT_14)).sentence
    weekly = _stop(RateLimitSignal("rejected", "seven_day", resets_at=TUE_14))
    assert weekly.kind == "rejected" and "weekly limit" in weekly.sentence and "Tue" in weekly.sentence


def test_ninety_percent_of_the_five_hour_window_pauses_with_the_percentage():
    stop = _stop(RateLimitSignal("allowed_warning", "five_hour", 0.92, AT_14))
    assert stop.kind == "near_limit"
    assert stop.sentence.startswith("Your Claude plan is 92% used for this 5-hour window")
    assert _stop(RateLimitSignal("allowed_warning", "five_hour", 0.89)) is None


def test_a_weekly_window_never_stops_before_it_is_rejected():
    assert _stop(RateLimitSignal("allowed_warning", "seven_day", 0.97)) is None


def test_no_signal_means_no_stop():
    assert _stop() is None


def test_the_chatgpt_plan_stops_before_the_first_spawn_when_its_limit_is_reached():
    reached = SimpleNamespace(ordinary_usage_allowed=True, limit_reached="rate_limit_reached",
                              resets_at=AT_14)
    assert plan_limits.codex_stop(reached, now=NOW, tz=timezone.utc) == (
        "Your ChatGPT plan's Codex limit is used up — Sleep didn't start. It can run again after 14:00.")
    off = SimpleNamespace(ordinary_usage_allowed=False, limit_reached=None, resets_at=None)
    assert plan_limits.codex_stop(off, now=NOW) == "Your ChatGPT plan's Codex limit is used up — Sleep didn't start."
    fine = SimpleNamespace(ordinary_usage_allowed=True, limit_reached=None, resets_at=None)
    assert plan_limits.codex_stop(fine, now=NOW) is None and plan_limits.codex_stop(None) is None
