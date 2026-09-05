"""Daily cron for ``sleep_cycle.run``, persisted to ``memory/sleep_schedule.yaml``.

The backend runs as a child process of the SwiftUI app, so in-process
``AsyncIOScheduler`` is the right granularity: it survives app restarts via
the yaml, doesn't leak launchd plists on uninstall, and can be re-registered
whenever the user updates the schedule from the Sleep dashboard.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from api.config import Settings
from api.models.schemas import ScheduleConfig
from api.services import sleep_cycle

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


def _schedule_path(memory_path: Path) -> Path:
    return memory_path / SCHEDULE_FILE


def load_schedule(memory_path: Path) -> ScheduleConfig:
    path = _schedule_path(memory_path)
    if not path.exists():
        return _DEFAULT.model_copy()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning(f"Failed to parse {path}: {e} — using defaults")
        return _DEFAULT.model_copy()
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
        return _DEFAULT.model_copy()


def save_schedule(memory_path: Path, cfg: ScheduleConfig) -> None:
    path = _schedule_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": cfg.mode, "enabled": cfg.enabled, "hour": cfg.hour, "minute": cfg.minute,
        "interval_hours": cfg.interval_hours,
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")


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
    needs — or none, for ``manual`` (G125 (4))."""
    try:
        scheduler.remove_job(JOB_ID)
    except Exception:
        pass
    if cfg.mode == "manual":
        logger.info("Sleep schedule: manual — no job registered")
        return
    if cfg.mode == "daily":
        scheduler.add_job(
            _run_if_idle,
            CronTrigger(hour=cfg.hour, minute=cfg.minute),
            id=JOB_ID,
            args=[settings],
            replace_existing=True,
        )
        logger.info(f"Sleep schedule registered: daily at {cfg.hour:02d}:{cfg.minute:02d}")
        return
    if cfg.mode == "interval":
        scheduler.add_job(
            _run_if_idle,
            IntervalTrigger(hours=cfg.interval_hours),
            id=JOB_ID,
            args=[settings],
            replace_existing=True,
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
        replace_existing=True,
    )
    logger.info(f"Sleep schedule registered: after imports (probing every {AFTER_IMPORT_PROBE_MINUTES}m)")


async def _run_after_intake_if_settled(settings) -> None:
    """The ``after_import`` probe (G125 (4) R7): every few minutes, start a
    cycle only when the queue has SETTLED — idle, something waiting, and the
    newest unprocessed episode at least ``AFTER_IMPORT_SETTLE_MINUTES`` old —
    so a multi-file import lands as one consolidation, not one per file.
    Scheduled → ``user_triggered=False`` (TODO.md ruling 4: a scheduled cycle
    never spends plan quota)."""
    from api.services import sleep_debt

    if sleep_cycle.get_sleep_state().status == "running":
        return
    debt = await sleep_debt.compute(settings.memory_path, settings)
    newest = getattr(debt, "newest_unprocessed_at", None)
    if not debt.unprocessed_count or newest is None:
        return
    if datetime.now() - newest < timedelta(minutes=AFTER_IMPORT_SETTLE_MINUTES):
        return
    cycle_id = f"sleep_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    await sleep_cycle.run(settings, cycle_id, user_triggered=False)


async def _run_if_idle(settings: Settings) -> None:
    """Cron callback. Skips if a cycle is already running so we never stack."""
    state = sleep_cycle.get_sleep_state()
    if state.status == "running":
        logger.info("Skipping scheduled sleep cycle: another cycle is running")
        return
    cycle_id = f"sleep_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    # Fix round 1, H1: this is the unattended nightly cron, never a human
    # pressing Run — `user_triggered=False` keeps the agent rung (the
    # Claude card's "Use for Sleep" toggle, and "auto") out of reach here
    # even when it's switched on, per spec §7's trigger scope and what
    # `Copy.sleepEngineExplainer` promises ("never on the nightly
    # schedule"). An explicit `CICADA_LLM_MODE=agent`/`local` in api/.env
    # still applies — that's deliberate dotfile config, unaffected by who
    # triggered the cycle.
    await sleep_cycle.run(settings, cycle_id, user_triggered=False)
