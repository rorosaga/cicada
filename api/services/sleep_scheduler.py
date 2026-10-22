"""Daily cron for ``sleep_cycle.run``, persisted to ``memory/sleep_schedule.yaml``.

The backend runs as a child process of the SwiftUI app, so in-process
``AsyncIOScheduler`` is the right granularity: it survives app restarts via
the yaml, doesn't leak launchd plists on uninstall, and can be re-registered
whenever the user updates the schedule from the Sleep dashboard.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from api.config import Settings
from api.models.schemas import ScheduleConfig
from api.services import bank_registry, sleep_catch_up, sleep_cycle, sleep_paused

JOB_ID = "sleep_daily"
SCHEDULE_FILE = "sleep_schedule.yaml"

# G125 (4) R7 — "after imports" is a settle probe, not a writer hook: no
# ingest path calls into the scheduler directly (that would couple every
# capture writer to Sleep's own concerns). Instead a short interval job polls
# whether the queue has gone quiet. AFTER_IMPORT_PROBE_MINUTES is how often
# it looks; AFTER_IMPORT_SETTLE_MINUTES is how long the newest unprocessed
# episode must have sat untouched before a multi-file import is treated as
# "done arriving" and consolidated once, not once per file.
AFTER_IMPORT_SETTLE_MINUTES = 10
AFTER_IMPORT_PROBE_MINUTES = 5

_DEFAULT = ScheduleConfig(mode="manual", hour=3, minute=0)


#: Owner 2026-10-22: a NEW bank consolidates nightly. Written once into a bank that was just created (the first-boot
#: default bank or `create_bank`), never into one that exists — so an existing bank with no schedule file keeps reading
#: as `_DEFAULT` (`manual`), exactly as before. A scheduled run uses the person's plan per ruling 4c.
NEW_BANK_SCHEDULE = ScheduleConfig(mode="daily", enabled=True, hour=3, minute=0)


def seed_new_bank_schedule(memory_path: Path) -> bool:
    """Write the nightly default into a brand-new bank. Never overwrites a schedule file that is already there; returns
    whether it wrote one."""
    if _schedule_path(Path(memory_path)).exists():
        return False
    save_schedule(Path(memory_path), NEW_BANK_SCHEDULE)
    return True


def _schedule_path(memory_path: Path) -> Path:
    return memory_path / SCHEDULE_FILE


def load_schedule(memory_path: Path) -> ScheduleConfig:
    cfg = read_schedule(memory_path)
    return cfg if cfg is not None else _DEFAULT.model_copy()


def read_schedule(memory_path: Path) -> ScheduleConfig | None:
    """The bank's schedule, the default (``manual``) when it has none — or ``None`` when the file is there but cannot
    be read or parsed. :func:`load_schedule` maps ``None`` onto the default (the API keeps starting); the fire-time
    check (``_stale_trigger``) keeps the schedule it was registered with instead, so an unreadable file never
    unregisters every job."""
    path = _schedule_path(memory_path)
    if not path.exists():
        return _DEFAULT.model_copy()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("not a mapping")
    except Exception as e:
        logger.warning(f"Failed to parse {path}: {e} — using defaults")
        return None
    try:
        return ScheduleConfig(
            mode=data.get("mode"),
            enabled=bool(data.get("enabled", False)),
            hour=int(data.get("hour", 3)),
            minute=int(data.get("minute", 0)),
            interval_hours=int(data.get("interval_hours", 6)),
        )
    except Exception as e:
        # Corrupt or out-of-range values on disk (e.g. hour=99 from an older
        # build that lacked validation) — fall back to the safe default so the
        # API keeps starting cleanly. The next PUT will overwrite the bad yaml.
        logger.warning(
            f"Invalid schedule in {path}: {e} — falling back to default"
        )
        return None


def save_schedule(memory_path: Path, cfg: ScheduleConfig) -> None:
    path = _schedule_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": cfg.mode, "enabled": cfg.enabled, "hour": cfg.hour, "minute": cfg.minute,
        "interval_hours": cfg.interval_hours,
    }
    # Atomic (the page rule): a temp file beside it, fsynced, then replaced over it — a fire that reads the schedule
    # mid-save (`_stale_trigger`) sees the old file or the new one, never a torn one.
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(yaml.safe_dump(payload, sort_keys=True))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def next_run_at(
    memory_path: Path, now: datetime | None = None, *,
    last_cycle_at: datetime | None = None,
    newest_unprocessed_at: datetime | None = None,
) -> str | None:
    """Next run as a naive local ISO string, per mode (G125 (4) R6/R7):
    ``manual`` → ``None``; ``daily`` → the next HH:MM; ``interval`` → the last
    cycle plus N hours (``now`` + N hours if Sleep never ran in this bank —
    there's no other anchor); ``after_import`` → the newest unprocessed
    episode plus the settle window, or ``None`` with an empty queue (nothing
    to settle).

    Lived in ``api/routers/status.py`` until G53: the state dictionary (a
    service) needs the same answer and a service must not import a router.
    ``now`` is injectable so the state builder's determinism tests are
    date-stable; ``last_cycle_at``/``newest_unprocessed_at`` are injected
    rather than recomputed here so callers reuse the same
    ``sleep_debt.compute`` call they already made for other fields, instead
    of this function running its own redundant scan.
    """
    cfg = load_schedule(memory_path)
    current = now or datetime.now()
    if cfg.mode == "manual":
        return None
    if cfg.mode == "daily":
        candidate = current.replace(hour=cfg.hour, minute=cfg.minute, second=0, microsecond=0)
        if candidate <= current:
            candidate += timedelta(days=1)
        return candidate.isoformat()
    if cfg.mode == "interval":
        base = last_cycle_at or current
        candidate = base + timedelta(hours=cfg.interval_hours)
        return max(candidate, current).isoformat(timespec="seconds")
    # after_import
    if newest_unprocessed_at is None:
        return None
    return (newest_unprocessed_at + timedelta(minutes=AFTER_IMPORT_SETTLE_MINUTES)).isoformat(timespec="seconds")


def register_job(
    scheduler: AsyncIOScheduler, settings: Settings, cfg: ScheduleConfig
) -> None:
    """Remove any existing sleep job and register the trigger this mode
    needs — or none, for ``manual`` (G125 (4)).

    G183(d): registered in an unpinned copy of the context. ``PUT /sleep/schedule`` calls this inside a request pinned
    to its bank, and APScheduler's wakeup/timer callbacks capture the context they are created in — the scheduled run
    must resolve the bank active when it fires, never the one the schedule was saved in."""
    bank_registry.run_unpinned(_register_job, scheduler, settings, cfg)


def trigger_key(cfg: ScheduleConfig) -> str:
    """What a registered job's trigger depends on: the mode, plus the time (``daily``) or the step (``interval``).
    Two banks with the same key share one trigger; any other difference is a different job."""
    if cfg.mode == "daily":
        return f"daily@{int(cfg.hour):02d}:{int(cfg.minute):02d}"
    if cfg.mode == "interval":
        return f"interval@{int(cfg.interval_hours)}h"
    return str(cfg.mode)


def follow_active_bank(scheduler, settings: Settings) -> ScheduleConfig | None:
    """Re-register the jobs from the ACTIVE bank's own schedule — called when the active bank changes (the switch
    routes). The trigger is the schedule's: a bank switched to on ``manual`` must not keep the last bank's 03:00, and
    one on 05:00 must fire at 05:00. Resolved unpinned (the switching request may carry a pin to the bank it left).
    Never raises: a switch never fails on the scheduler. ``None`` when there is no scheduler (tests, a bare app)."""
    if scheduler is None:
        return None
    try:
        def follow() -> ScheduleConfig:
            cfg = load_schedule(settings.memory_path)
            _register_job(scheduler, settings, cfg)
            return cfg

        return bank_registry.run_unpinned(follow)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Sleep schedule not re-registered after a bank switch: {type(e).__name__}")
        return None


_unreadable_warned: set[str] = set()


def _warn_unreadable(memory_path) -> None:
    """Once per bank until it reads again: a fire every few minutes must not repeat it."""
    key = str(memory_path)
    if key in _unreadable_warned:
        return
    _unreadable_warned.add(key)
    logger.warning("Scheduled sleep: the bank's schedule file cannot be read — keeping the registered schedule")


def _stale_trigger(scheduler, settings: Settings, registered: ScheduleConfig | None) -> bool:
    """The fire-time half of following the active bank: a job registered for one schedule fires, but the active bank's
    own schedule is now another (the active bank changed by a path that did not re-register — a registry edited by
    another process, a restore). Then nothing runs on the old trigger: the jobs are re-registered from the active
    bank's schedule (``manual`` registers none) and this firing is dropped. ``registered`` is ``None`` for a direct
    call (tests, older jobs): no check."""
    if registered is None:
        return False
    active = read_schedule(settings.memory_path)
    if active is None:
        # Unreadable (corrupt, or a write by hand cut short): keep the schedule this job was registered with and run
        # as it says — never treat it as `manual` and unregister every job until the next save, switch or restart.
        _warn_unreadable(settings.memory_path)
        return False
    _unreadable_warned.discard(str(settings.memory_path))
    if trigger_key(active) == trigger_key(registered):
        return False
    logger.info(f"Scheduled sleep: the active bank's schedule is {trigger_key(active)}, not "
                f"{trigger_key(registered)} — re-registered, nothing run on the old time")
    if scheduler is not None:
        try:
            _register_job(scheduler, settings, active)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Sleep schedule not re-registered: {type(e).__name__}")
    return True


def _register_job(scheduler: AsyncIOScheduler, settings: Settings, cfg: ScheduleConfig) -> None:
    for job_id in (JOB_ID, sleep_catch_up.JOB_ID):
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
    if cfg.mode in ("daily", "interval"):
        # Owner 2026-10-19: a time the Mac slept or was off through runs once when it is back (`sleep_catch_up`).
        # The schedule's own timer keeps a minute's grace for a wake just after the time; later is the catch-up's.
        try:
            sleep_catch_up.note_schedule(settings.memory_path, cfg)
        except Exception:  # noqa: BLE001 - a stand-in settings object, or an unreadable bank: the probe notes it later
            pass
        scheduler.add_job(
            sleep_catch_up.probe,
            IntervalTrigger(minutes=sleep_catch_up.PROBE_MINUTES),
            id=sleep_catch_up.JOB_ID,
            args=[settings],   # the probe reads the active bank's own schedule each time, never this `cfg`
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=sleep_catch_up.PROBE_MINUTES * 60,
            next_run_time=datetime.now().astimezone() + timedelta(minutes=1),
        )
    if cfg.mode == "manual":
        logger.info("Sleep schedule: manual — no job registered")
        return
    if cfg.mode == "daily":
        scheduler.add_job(
            _run_if_idle,
            CronTrigger(hour=cfg.hour, minute=cfg.minute),
            id=JOB_ID,
            args=[settings],
            kwargs=_fire_kwargs(scheduler, cfg),
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=sleep_catch_up.ON_TIME_GRACE_S,
        )
        logger.info(f"Sleep schedule registered: daily at {cfg.hour:02d}:{cfg.minute:02d}")
        return
    if cfg.mode == "interval":
        scheduler.add_job(
            _run_if_idle,
            IntervalTrigger(hours=cfg.interval_hours),
            id=JOB_ID,
            args=[settings],
            kwargs=_fire_kwargs(scheduler, cfg),
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=sleep_catch_up.ON_TIME_GRACE_S,
        )
        logger.info(f"Sleep schedule registered: every {cfg.interval_hours}h")
        return
    # after_import: a settle probe (R7), not a hook — see
    # `_run_after_intake_if_settled`'s own docstring for why nothing calls in.
    scheduler.add_job(
        _run_after_intake_if_settled,
        IntervalTrigger(minutes=AFTER_IMPORT_PROBE_MINUTES),
        id=JOB_ID,
        args=[settings],
        kwargs=_fire_kwargs(scheduler, cfg),
        replace_existing=True,
    )
    logger.info(f"Sleep schedule registered: after imports (probing every {AFTER_IMPORT_PROBE_MINUTES}m)")


def _fire_kwargs(scheduler, cfg: ScheduleConfig) -> dict:
    """What a fire needs to tell a stale trigger (``_stale_trigger``): the schedule it was registered for, and the
    scheduler to re-register on (in-memory job store: nothing is pickled)."""
    return {"registered": cfg.model_copy(), "scheduler": scheduler}


#: While a run is paused, the after-import probe runs the engine-free upkeep this often.
PAUSED_UPKEEP_HOURS = 24
_paused_upkeep_at: dict[str, datetime] = {}


def _paused_for_the_person(memory_path: Path) -> bool:
    """A paused run the schedule must not read over. A scheduled run's pause that no person
    chose (a restart, or the scheduled engine away for a while — ``sleep_paused.
    schedule_may_replace``) is dropped here and ended in Past nights, so the schedule reads
    afresh instead of stopping until someone presses Continue (TODO ruling 16)."""
    rec = sleep_paused.get_paused(memory_path)
    if rec is None:
        return False
    if sleep_paused.schedule_may_replace(rec):
        logger.info(f"Scheduled sleep: replacing a scheduled run paused by {rec.get('reason')} with a fresh one")
        sleep_cycle._drop_paused_record(memory_path)
        return False
    return True


def _scheduled_drain(settings) -> bool:
    """Every scheduled run reads everything waiting (TODO ruling 16) — except when an explicit
    ``CICADA_LLM_MODE=agent|codex`` dotfile pin makes the scheduled engine a plan: then it
    reads one batch, as before ruling 16, so no unattended run drains a plan's quota."""
    from api.services import engine_select

    return not engine_select.scheduled_plan_pin(settings)


async def _run_after_intake_if_settled(settings, *, registered: ScheduleConfig | None = None,
                                       scheduler=None) -> None:
    """The ``after_import`` probe (G125 (4) R7): every few minutes, start a
    cycle only when the queue has SETTLED — idle, something READABLE waiting, and the
    newest unprocessed episode at least ``AFTER_IMPORT_SETTLE_MINUTES`` old —
    so a multi-file import lands as one consolidation, not one per file.
    Scheduled → ``user_triggered=False`` (TODO.md ruling 4: a scheduled cycle
    never spends plan quota). It reads everything waiting (TODO ruling 16).

    A paused run is the person's to continue or end: the probe never reads over it (it would
    undo a Pause within minutes and clear the record), but runs the engine-free upkeep once a
    day meanwhile (``run(tail_only=True)``). A parked conversation is waiting but not
    readable, so a queue of only parked ones never fires an empty run every five minutes."""
    bank_registry.unpin()   # G183(d): the bank active now, whatever context scheduled this (`register_job`)
    if _stale_trigger(scheduler, settings, registered):
        return
    from api.services import sleep_debt

    if sleep_cycle.get_sleep_state().status == "running":
        return
    if _paused_for_the_person(settings.memory_path):
        # Nothing is read over a pause, but the engine-free upkeep still runs — at most once
        # every PAUSED_UPKEEP_HOURS, since the probe fires every five minutes.
        key = str(settings.memory_path)
        last = _paused_upkeep_at.get(key)
        if last is not None and datetime.now() - last < timedelta(hours=PAUSED_UPKEEP_HOURS):
            return
        _paused_upkeep_at[key] = datetime.now()
        logger.info("After-import probe: a paused run waits for the person — upkeep only")
        cycle_id = f"sleep_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
        await sleep_cycle.run(settings, cycle_id, user_triggered=False, tail_only=True)
        return
    debt = await sleep_debt.compute(settings.memory_path, settings)
    newest = getattr(debt, "newest_unprocessed_at", None)
    readable = getattr(debt, "readable_count", None)
    if readable is None:
        readable = debt.unprocessed_count
    if not readable or newest is None:
        return
    if datetime.now() - newest < timedelta(minutes=AFTER_IMPORT_SETTLE_MINUTES):
        return
    cycle_id = f"sleep_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    # A scheduled run reads everything waiting too (owner, 2026-09-30; TODO ruling 16 amends
    # ruling 13). Ruling 4 is untouched: `user_triggered=False` keeps every plan engine out, so
    # it reads on the scheduled engine — on an API key that spends without a ceiling, which the
    # engine menu and Details say in words. Only a person's Continue can resume it on a plan.
    await sleep_cycle.run(settings, cycle_id, user_triggered=False, drain=_scheduled_drain(settings))


async def _run_if_idle(settings: Settings, *, registered: ScheduleConfig | None = None, scheduler=None) -> None:
    """Cron callback. Skips if a cycle is already running so we never stack. While a paused
    run waits for the person it reads nothing (that would replace the pause) but still runs
    the engine-free tail (``run(tail_only=True)``)."""
    bank_registry.unpin()   # G183(d): the bank active now, whatever context scheduled this (`register_job`)
    # The trigger that fired must be the ACTIVE bank's own: after a switch that did not re-register, a bank on
    # `manual` (or on another time) never runs on the last bank's time.
    if _stale_trigger(scheduler, settings, registered):
        return
    # This time took its turn, whatever follows (a running cycle, a pause, a failure): the catch-up never repeats it.
    sleep_catch_up.note_handled(settings.memory_path)
    state = sleep_cycle.get_sleep_state()
    if state.status == "running":
        logger.info("Skipping scheduled sleep cycle: another cycle is running")
        return
    cycle_id = f"sleep_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    if _paused_for_the_person(settings.memory_path):
        # The paused run is the person's to continue or end, so nothing is read — but the
        # engine-free upkeep (claim expiry, follow-ups, the state refresh, the polls, the link
        # backfill) never waits on a pause: it runs on schedule as on any idle night.
        logger.info("Scheduled sleep: a paused run waits for the person — upkeep only")
        await sleep_cycle.run(settings, cycle_id, user_triggered=False, tail_only=True)
        return
    # Fix round 1, H1: this is the unattended nightly cron, never a human
    # pressing Run — `user_triggered=False` keeps the agent rung (the
    # Claude card's "Use for Sleep" toggle, and "auto") out of reach here
    # even when it's switched on, per spec §7's trigger scope and what
    # `Copy.sleepEngineExplainer` promises ("never on the nightly
    # schedule"). An explicit `CICADA_LLM_MODE=agent`/`local` in api/.env
    # still applies — that's deliberate dotfile config, unaffected by who
    # triggered the cycle — so under that pin the run reads one batch (`_scheduled_drain`);
    # otherwise it reads everything waiting (TODO ruling 16).
    await sleep_cycle.run(settings, cycle_id, user_triggered=False, drain=_scheduled_drain(settings))
