"""R-E12 — when a plan engine must stop, as one sentence a person can read.

Pure: no subprocess, no clock of its own (``now`` is injectable), no
settings. Both plan engines feed it — the Claude rung its stream's
``rate_limit_event`` signals (``agent_stream``), the ChatGPT rung the
read-only ``codex app-server`` snapshot (``codex_app_server``). What comes
back is a *reason*, never a meter: the 2026-09-03 ruling keeps usage numbers
out of the app, so a percentage only ever appears inside the sentence that
says why Sleep stopped, and the reset time is the vendor's own (G107/G125:
measured, never estimated).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Iterable

_WINDOW = {
    "five_hour": "5-hour", "seven_day": "weekly", "seven_day_opus": "weekly Opus",
    "seven_day_sonnet": "weekly Sonnet", "overage": "extra-usage",
}


@dataclass(frozen=True)
class PlanStop:
    kind: str                   # "overage" | "rejected" | "near_limit"
    sentence: str
    limit_type: str | None = None
    resets_at: int | None = None


def reset_phrase(resets_at, *, now: datetime | None = None, tz: tzinfo | None = None) -> str:
    """``"after 14:00"`` today, ``"after Tue 14:00"`` another day, ``""`` when
    the vendor gave no time — an absent reset is never guessed."""
    if isinstance(resets_at, bool) or not isinstance(resets_at, int) or resets_at <= 0:
        return ""
    now = now or datetime.now().astimezone()
    tz = tz or now.tzinfo
    when = datetime.fromtimestamp(resets_at, tz=tz)
    if when.date() == now.astimezone(tz).date():
        return f"after {when:%H:%M}"
    return f"after {when:%a %H:%M}"


def _again(resets_at, now, tz) -> str:
    phrase = reset_phrase(resets_at, now=now, tz=tz)
    return f" It can run again {phrase}." if phrase else ""


def claude_stop(signals: Iterable, *, allow_overage: bool, stop_utilization: float,
                now: datetime | None = None, tz: tzinfo | None = None) -> PlanStop | None:
    """The first reason, in precedence order, the Claude rung must stop (R-E12).

    1. Extra usage in play and not opted in (G117 treats "Claude with extra
       usage" as an explicit choice). The call that saw it already ran, so
       the stop is for everything after it.
    2. Any window rejected.
    3. The 5-hour window at or past ``stop_utilization`` — pause while the
       person still has room to work. Weekly windows stop only on rejection:
       stopping at 90 % of a week would idle Sleep for days.
    """
    signals = list(signals or [])
    if not allow_overage:
        for s in signals:
            if s.using_overage:
                return PlanStop(
                    "overage",
                    "Your Claude plan's included usage ran out — Sleep stopped instead of "
                    "running on extra usage." + _again(s.resets_at, now, tz),
                    s.limit_type, s.resets_at)
    for s in signals:
        if s.status == "rejected":
            window = _WINDOW.get(s.limit_type or "", "usage")
            return PlanStop(
                "rejected",
                f"Your Claude plan hit its {window} limit — Sleep paused." + _again(s.resets_at, now, tz),
                s.limit_type, s.resets_at)
    for s in signals:
        if s.limit_type == "five_hour" and s.utilization is not None and s.utilization >= stop_utilization:
            pct = min(100, int(round(s.utilization * 100)))
            return PlanStop(
                "near_limit",
                f"Your Claude plan is {pct}% used for this 5-hour window — Sleep paused to "
                "leave you room." + _again(s.resets_at, now, tz),
                s.limit_type, s.resets_at)
    return None


def codex_stop(snapshot, *, now: datetime | None = None, tz: tzinfo | None = None) -> str | None:
    """The ChatGPT plan's limit is already reached (or ordinary use is off),
    per the app-server's ``account/rateLimits/read`` — stop BEFORE the first
    ``codex exec`` rather than discover it one failed call at a time."""
    if snapshot is None:
        return None
    if snapshot.ordinary_usage_allowed is False or snapshot.limit_reached:
        return ("Your ChatGPT plan's Codex limit is used up — Sleep didn't start."
                + _again(snapshot.resets_at, now, tz))
    return None
