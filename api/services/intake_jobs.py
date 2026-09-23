"""Process-local background staging for large imports (Track I T2b — design §9.2).

An export of a few hundred conversations used to stage inside the request, so
the app's panel sat on "Uploading…" with nothing to say. Above
``intake.BACKGROUND_THRESHOLD`` episodes to write, ``POST /intake/import``
answers 202 with a job, stages here in batches through the unchanged
``conversations._stage_episodes`` (each batch re-scans the bank, so G114 ids and
G20 identity stay exact across batches), and ``GET /intake/jobs/{id}`` reports
``{staged, total}`` — a count the app shows only once reported, never
interpolated (design §5.2).

Process-local on purpose (R-IA12): a job is a convenience for the panel that
started it, not state; a backend restart loses the counter, never the episodes
already written. Finished jobs are kept an hour.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from loguru import logger

#: One stage at a time in this process: two overlapping stages into one bank
#: would each seed ids from the same max suffix (G114 R1 is per call), and
#: ``markdown_parser.write`` overwrites on a collision. The sync path takes it too.
STAGING_LOCK = threading.Lock()
BATCH = 50
KEEP_SECONDS = 3600

StageFn = Callable[[list[dict], Path], "tuple[int, int, int]"]


@dataclass
class Job:
    id: str
    total: int
    staged: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    done: bool = False
    error: str | None = None
    finished_at: float | None = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _prune(now: float) -> None:
    for job_id in [j.id for j in _jobs.values() if j.finished_at and now - j.finished_at > KEEP_SECONDS]:
        _jobs.pop(job_id, None)


def start(total: int, *, already_skipped: int = 0) -> Job:
    """Register a job before its 202 goes out, so the first poll never 404s.
    ``already_skipped`` is ``plan()``'s unchanged count: the job only ever
    carries what will be written, and its final ``skipped`` must still equal
    the synchronous path's."""
    with _lock:
        _prune(time.time())
        job = Job(id=uuid.uuid4().hex[:12], total=total, skipped=already_skipped)
        _jobs[job.id] = job
        return job


def get(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def reset() -> None:
    """Tests only."""
    with _lock:
        _jobs.clear()


def run(job_id: str, episodes: list[dict], episodes_dir: Path, stage: StageFn, *, batch: int = BATCH) -> None:
    """Stage ``episodes`` in ``batch``-sized chunks under ``STAGING_LOCK``.
    ``staged`` advances only after a chunk is on disk, so the panel's count is
    never ahead of the bank. Always ends ``done``; a failure is recorded as
    ``error`` for the panel, never raised into the server."""
    job = get(job_id)
    if job is None:
        return
    try:
        with STAGING_LOCK:
            for i in range(0, len(episodes), batch):
                chunk = episodes[i:i + batch]
                created, updated, skipped = stage(chunk, episodes_dir)
                with _lock:
                    job.created += created
                    job.updated += updated
                    job.skipped += skipped
                    job.staged += len(chunk)
    except Exception as exc:  # recorded for the panel, never raised into the server
        logger.error(f"Intake job {job_id} failed: {type(exc).__name__}")
        with _lock:
            job.error = f"{type(exc).__name__}: {exc}"
    finally:
        with _lock:
            job.done = True
            job.finished_at = time.time()
