"""Continue after a plan reset — the opt-in switch (TODO ruling 15, owner 2026-09-30).

**A narrow amendment to ruling 4.** A run the person started may continue itself once
its own plan window has reset, if they switched that on in Reading options for the runs
they start. It never crosses a weekly reset, never arms from a scheduled run, and never
changes engine. Off by default; the switch is snapshotted into the run when it starts,
so flipping it later never arms an old run.

The bounds (Sleep page v5 plan, Q-B — the owner confirms or changes them):

* at most ``MAX_CONTINUES`` (2) automatic continues per run;
* only within ``MAX_PAUSE_S`` (36 hours) of the pause, and only when the vendor gave a
  reset time (an absent reset is never guessed);
* only for a 5-hour window, the reserve line on a 5-hour window, or extra usage that
  then resets — ``seven_day`` and ``unknown`` limits never arm;
* only while the engine the run started on is still the engine the person's own choice
  resolves to (a changed engine cancels the automatic continue).

The job is a one-shot APScheduler ``DateTrigger`` at ``resets_at + GRACE_S``, one per bank
(``job_id``: the promise is stored per bank, so a trigger or End in one bank never drops
another bank's job), recorded in the run's sidecar so a backend restart — or the bank's
activation (``bank_migrations.run_bank_migrations``) — re-arms it. If the Mac was asleep at the reset it
fires on wake while still inside the 36 hours (``misfire_grace_time``). "Keep the Mac
awake" is not built. **This is the only module besides the Continue route that may call
``run(continue_from=...)``** (``test_only_two_modules_pass_continue_from``).
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

JOB_ID = "sleep-auto-continue"
MAX_CONTINUES = 2
MAX_PAUSE_S = 36 * 3600
GRACE_S = 60
ARMING_REASONS = ("plan_window", "overage", "reserve")
ARMING_LIMITS = ("five_hour", "overage")

_scheduler = None


def bind(scheduler) -> None:
    """The lifespan hands over the app's scheduler (tests bind a stand-in)."""
    global _scheduler
    _scheduler = scheduler


def job_id(memory_path) -> str:
    """The bank's own job id — one armed continue per bank, never one per process."""
    try:
        key = str(Path(memory_path).resolve())
    except OSError:
        key = str(memory_path)
    return f"{JOB_ID}:{hashlib.sha256(key.encode()).hexdigest()[:12]}"


def _now() -> float:
    return time.time()


def blocked_reason(rec: dict, *, started_by: str, switch_on: bool, used: int, now: float | None = None) -> str | None:
    """Why this pause may NOT continue itself, or ``None`` when every arming guard holds."""
    now = _now() if now is None else now
    if started_by != "user":
        return "scheduled"          # a scheduled run never arms
    if not switch_on:
        return "off"
    if rec.get("reason") == "plan_weekly":
        return "weekly"             # never across a weekly reset
    if rec.get("reason") not in ARMING_REASONS:
        return "reason"             # a person's pause, an engine failure, a restart: never
    if rec.get("limit") not in ARMING_LIMITS:
        return "weekly" if rec.get("limit") == "seven_day" else "unknown_limit"
    resets = rec.get("resets_at")
    if not isinstance(resets, int) or isinstance(resets, bool):
        return "no_reset_time"
    if used >= MAX_CONTINUES:
        return "used_twice"
    paused_at = float(rec.get("paused_at_ts") or now)
    if resets + GRACE_S - paused_at > MAX_PAUSE_S:
        return "too_far"
    return None


def arm(settings, memory_path: Path, rec: dict, ds) -> dict | None:
    """Called when a run pauses. ``None`` = nothing to say (a scheduled run, or the switch
    was off); otherwise the ``auto_continue`` block the record carries."""
    if getattr(ds, "started_by", "user") != "user" or not getattr(ds, "continue_after_reset", False):
        return None
    used = int(getattr(ds, "auto_used", 0) or 0)
    why = blocked_reason(rec, started_by="user", switch_on=True, used=used)
    if why is not None:
        return {"armed": False, "at": None, "left": max(0, MAX_CONTINUES - used), "used": used, "blocked": why}
    sched = _scheduler
    if sched is None:
        return {"armed": False, "at": None, "left": MAX_CONTINUES - used, "used": used, "blocked": "no_scheduler"}
    at = int(rec["resets_at"]) + GRACE_S
    try:
        _add_job(sched, str(memory_path), at, rec)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"auto-continue not armed: {type(e).__name__}: {e}")
        return {"armed": False, "at": None, "left": MAX_CONTINUES - used, "used": used, "blocked": "no_scheduler"}
    return {"armed": True, "at": at, "left": MAX_CONTINUES - used, "used": used, "blocked": None}


def _add_job(sched, memory_path: str, at: int, rec: dict) -> None:
    from apscheduler.triggers.date import DateTrigger

    remaining = max(60, int(float(rec.get("paused_at_ts") or _now()) + MAX_PAUSE_S - _now()))
    sched.add_job(
        _fire, DateTrigger(run_date=datetime.fromtimestamp(at, tz=timezone.utc)),
        id=job_id(memory_path), args=[memory_path, str(rec.get("run_id"))], replace_existing=True,
        misfire_grace_time=remaining,
    )


def disarm(memory_path: Path) -> None:
    """Drop this bank's job (its run ended, continued or was replaced). Another bank's
    armed continue is left alone."""
    sched = _scheduler
    if sched is None:
        return
    try:
        sched.remove_job(job_id(memory_path))
    except Exception:  # noqa: BLE001 - no such job
        pass


def rearm_after_restart(memory_path: Path) -> bool:
    """At backend start and whenever the bank is activated: a paused record that was armed
    re-arms its job, if every guard still holds (nothing before the lifespan binds the
    scheduler — boot's own migrations run first, and the lifespan calls this again). Never raises."""
    from api.services import sleep_paused

    try:
        rec = sleep_paused.get_paused(memory_path)
        ac = (rec or {}).get("auto_continue") or {}
        if not rec or not ac.get("armed") or _scheduler is None:
            return False
        why = blocked_reason(rec, started_by=rec.get("started_by", "user"),
                             switch_on=bool((rec.get("options") or {}).get("continue_after_reset")),
                             used=sleep_paused.auto_used(rec))
        if why is not None:
            _record_block(memory_path, rec, why)
            return False
        _add_job(_scheduler, str(memory_path), int(ac.get("at") or int(rec["resets_at"]) + GRACE_S), rec)
        return True
    except Exception:  # noqa: BLE001
        return False


def _record_block(memory_path: Path, rec: dict, why: str) -> None:
    from api.services import sleep_paused

    rec = dict(rec)
    ac = dict(rec.get("auto_continue") or {})
    ac.update({"armed": False, "blocked": why})
    rec["auto_continue"] = ac
    sleep_paused.save(memory_path, rec)


async def _fire(memory_path: str, run_id: str) -> None:
    """The job. Every guard is checked again at fire time; any failure leaves the run
    paused, says why in ``autoContinue.blocked``, and starts nothing."""
    from api.config import get_settings
    from api.services import engine_select, sleep_cycle, sleep_paused

    mp = Path(memory_path)
    rec = sleep_paused.get_paused(mp)
    if not rec or str(rec.get("run_id")) != str(run_id):
        return                      # ended, continued by hand, or replaced
    used = sleep_paused.auto_used(rec)
    now = _now()
    why = blocked_reason(rec, started_by=rec.get("started_by", "user"),
                         switch_on=bool((rec.get("options") or {}).get("continue_after_reset")),
                         used=used, now=now)
    if why is None and now - float(rec.get("paused_at_ts") or now) > MAX_PAUSE_S:
        why = "too_far"
    settings = get_settings()
    if why is None:
        # Turning the switch off after the pause withdraws it: the snapshot arms, the person disarms.
        try:
            from api.services import sleep_run_prefs
            from api.services.connections.registry import get_registry

            if not sleep_run_prefs.load(get_registry(settings)).continue_after_reset:
                why = "off"
        except Exception:  # noqa: BLE001
            why = "off"
    if why is None and Path(settings.memory_path) != mp:
        why = "bank_changed"
    if why is None and sleep_cycle.get_sleep_state().status == "running":
        why = "busy"
    if why is None:
        try:
            resolved, _ = await engine_select.resolve_settings(settings, user_triggered=True)
            label = engine_select.engine_label(resolved)
            model = _model_of(engine_select, resolved)
            if label != rec.get("engine_label") or (
                    rec.get("engine_model") and model and model != rec.get("engine_model")):
                why = "engine_changed"
        except Exception:  # noqa: BLE001
            why = "engine_changed"
    if why is not None:
        logger.info(f"auto-continue not run: {why}")
        _record_block(mp, rec, why)
        return
    # The resolve above awaited (it may probe the app-server for seconds): a person may have
    # pressed Consolidate, Continue or End meanwhile. Check again with no await before the
    # reservation, so two runs never go at once.
    live = sleep_paused.get_paused(mp)
    if sleep_cycle.get_sleep_state().status == "running" or not live or str(live.get("run_id")) != str(run_id):
        logger.info("auto-continue not run: busy")
        if live and str(live.get("run_id")) == str(run_id):
            _record_block(mp, live, "busy")
        return
    rec = dict(live)
    rec["auto_used"] = used + 1
    from datetime import datetime as _dt

    cycle_id = f"sleep_{_dt.now().strftime('%Y-%m-%d_%H%M%S')}"
    sleep_cycle.reserve_cycle(cycle_id, drain=True)
    logger.info(f"auto-continue: resuming run {run_id} after its plan window reset")
    await sleep_cycle.run(settings, cycle_id, user_triggered=True, drain=True, continue_from=rec)


def _model_of(engine_select, resolved) -> str | None:
    try:
        return engine_select.author_model(resolved)
    except Exception:  # noqa: BLE001
        return None
