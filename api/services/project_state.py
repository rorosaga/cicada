"""G141 §6.2 — a project's derived state on one day: one pure function.

Python here (for `cicada_project` and the follow-up proposer) and Swift in
PJ-5 (`ProjectState.swift`) run ONE fixture, `api/tests/fixtures/timeline_state.json`
— the QuickMatch/text_fold precedent (R-PJB17): two languages, one table, so the
app and an agent never disagree about whether a thread is quiet. `today` is an
argument; nothing here reads a clock and nothing is stored (R-PJ7).
"""
from __future__ import annotations

import math
from datetime import date
from statistics import median

QUIET_FLOOR_DAYS = 14          # R-PJ13
QUIET_MULTIPLIER = 2           # R-PJ13: 2×, not derived-first's 3×
FOLLOWUP_FLOOR_DAYS = 21       # R-PJ13
OVERDUE_ASK_DAYS = 3           # §9: a milestone is asked about once 3 days overdue
GAP_WINDOW_DAYS = 180          # R-PJB6: ending at the last moment day
QUIET_SECTION_DAYS = 90        # §6.2: Quiet ≤ 90 days, Resting beyond
RESTING_STATUSES = frozenset({"decaying", "archived"})
COUNTED = frozenset({"planned", "done", "missed", "passed-no-word"})   # R-PJ11: dropped never counts


def _d(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def median_gap(days) -> float | None:
    """Median gap between distinct moment days in the 180 days ending at the
    LAST one — data-anchored, so a server can serve it without today (R-PJB6)."""
    ds = sorted({x for x in (_d(v) for v in days or []) if x})
    if len(ds) < 2:
        return None
    ds = [x for x in ds if (ds[-1] - x).days <= GAP_WINDOW_DAYS]
    gaps = [(b - a).days for a, b in zip(ds, ds[1:])]
    return float(median(gaps)) if gaps else None


def quiet_threshold(median_gap_days: float | None) -> int:
    """Q = max(14, 2 × median gap), rounded half-up — Swift's `.rounded()`."""
    if median_gap_days is None:
        return QUIET_FLOOR_DAYS
    return max(QUIET_FLOOR_DAYS, int(math.floor(QUIET_MULTIPLIER * median_gap_days + 0.5)))


def milestone_state(m: dict, today: date) -> dict:
    status, target, done_on = m.get("status"), _d(m.get("target")), _d(m.get("doneOn"))
    out: dict = {"slug": m.get("slug"), "moved": bool(m.get("moved")), "days": None, "followupEligible": False}
    if status == "planned":
        if target is None:
            out["state"] = "someday"
        else:
            out["days"] = (target - today).days
            out["state"] = "upcoming" if target >= today else "overdue"
            out["followupEligible"] = (today - target).days >= OVERDUE_ASK_DAYS
    elif status == "done":
        out["state"] = "done"
        if target and done_on:
            out["days"] = (done_on - target).days   # < 0 early, 0 on time, > 0 late
    elif status in ("missed", "dropped", "passed-no-word"):
        out["state"] = status
    else:
        out["state"] = "someday"
    return out


def progress(milestones: list[dict]) -> dict:
    goals = [m for m in milestones if m.get("source") != "expectedEnd" and m.get("status") in COUNTED]
    return {"done": sum(1 for m in goals if m.get("status") == "done"), "total": len(goals)}


def next_slug(milestones: list[dict]) -> str | None:
    """The open planned milestone with the earliest target, undated last — the
    upcoming OR overdue one, found without reading today (§6.3)."""
    open_ = [m for m in milestones if m.get("status") == "planned" and m.get("source") != "expectedEnd"]
    open_.sort(key=lambda m: (_d(m.get("target")) is None, str(m.get("target") or ""), str(m.get("slug"))))
    return open_[0]["slug"] if open_ else None


def timeline_state(state_in: dict, today) -> dict:
    """`state_in` is a wire payload's absolute fields (`input_from_timeline`
    builds it from a `ProjectTimeline`; the fixture writes it by hand)."""
    today = _d(today)
    gap = state_in.get("medianGapDays")
    if gap is None and state_in.get("momentDays"):
        gap = median_gap(state_in["momentDays"])
    q = quiet_threshold(gap)
    last = _d(state_in.get("lastMomentDay"))
    if last is None and state_in.get("momentDays"):
        last = max(_d(x) for x in state_in["momentDays"])
    idle = None if last is None else (today - last).days
    if str(state_in.get("status") or "active") in RESTING_STATUSES or idle is None or idle > QUIET_SECTION_DAYS:
        section = "resting"
    elif idle <= q:
        section = "inMotion"
    else:
        section = "quiet"
    threads = []
    for t in state_in.get("openThreads") or []:
        heard = _d(t.get("lastHeard")) or _d(t.get("since"))
        quiet_days = (today - heard).days if heard else None
        threads.append({"claimId": t.get("claimId"), "quietDays": quiet_days,
                        "followupEligible": quiet_days is not None and quiet_days >= max(FOLLOWUP_FLOOR_DAYS, q)})
    milestones = list(state_in.get("milestones") or [])
    return {
        "medianGapDays": gap, "quietThreshold": q, "section": section, "threads": threads,
        "milestones": [milestone_state(m, today) for m in milestones if m.get("source") != "expectedEnd"],
        "progress": progress(milestones), "next": next_slug(milestones), "planned": bool(milestones),
    }


def input_from_timeline(timeline) -> dict:
    """A `ProjectTimeline` (or `ProjectRow`) as `timeline_state`'s input."""
    wire = timeline.model_dump(by_alias=True)
    return {"status": (wire.get("project") or wire).get("status"), "lastMomentDay": wire.get("lastMomentDay"),
            "medianGapDays": wire.get("medianGapDays"), "momentDays": wire.get("momentDays") or [],
            "openThreads": wire.get("openThreads") or (wire.get("now") or {}).get("threads") or [],
            "milestones": wire.get("milestones") or []}
