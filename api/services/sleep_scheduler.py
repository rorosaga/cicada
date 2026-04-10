"""Daily cron for ``sleep_cycle.run``, persisted to ``memory/sleep_schedule.yaml``.

The backend runs as a child process of the SwiftUI app, so in-process
``AsyncIOScheduler`` is the right granularity: it survives app restarts via
the yaml, doesn't leak launchd plists on uninstall, and can be re-registered
whenever the user updates the schedule from the Sleep dashboard.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from api.config import Settings
from api.models.schemas import ScheduleConfig
from api.services import sleep_cycle

JOB_ID = "sleep_daily"
SCHEDULE_FILE = "sleep_schedule.yaml"

_DEFAULT = ScheduleConfig(enabled=False, hour=3, minute=0)


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
            enabled=bool(data.get("enabled", False)),
            hour=int(data.get("hour", 3)),
            minute=int(data.get("minute", 0)),
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
    payload = {"enabled": cfg.enabled, "hour": cfg.hour, "minute": cfg.minute}
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")


def register_job(
    scheduler: AsyncIOScheduler, settings: Settings, cfg: ScheduleConfig
) -> None:
    """Remove any existing sleep job and add a new cron trigger if enabled."""
    try:
        scheduler.remove_job(JOB_ID)
    except Exception:
        pass
    if not cfg.enabled:
        logger.info("Sleep schedule disabled — no cron registered")
        return
    scheduler.add_job(
        _run_if_idle,
        CronTrigger(hour=cfg.hour, minute=cfg.minute),
        id=JOB_ID,
        args=[settings],
        replace_existing=True,
    )
    logger.info(
        f"Sleep schedule registered: daily at {cfg.hour:02d}:{cfg.minute:02d}"
    )


async def _run_if_idle(settings: Settings) -> None:
    """Cron callback. Skips if a cycle is already running so we never stack."""
    state = sleep_cycle.get_sleep_state()
    if state.status == "running":
        logger.info("Skipping scheduled sleep cycle: another cycle is running")
        return
    cycle_id = f"sleep_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    await sleep_cycle.run(settings, cycle_id)
