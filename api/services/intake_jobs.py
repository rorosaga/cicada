"""Process-local background staging for large imports (Track I T2b — design §9.2).

An export of a few hundred conversations used to stage inside the request, so
the app's panel sat on "Uploading…" with nothing to say. Above
``intake.BACKGROUND_THRESHOLD`` episodes to write, ``POST /intake/import``
answers 202 with a job, stages here through ``episode_staging.stage`` — the
same stager every other writer uses, under its own process-wide lock (G114
ids) — and ``GET /intake/jobs/{id}`` reports ``{staged, total}``: a count the
app shows only once reported, never interpolated (design §5.2).

ONE ``stage`` call per job, counted per draft through its ``progress`` hook.
The first cut staged in 50-episode batches, and every batch re-scanned the
whole bank: 1,000 new threads into a 2,000-episode bank took 177 s that way
against 9.9 s as one call, with the lock held throughout so every other import
queued behind it (Track I final review, finding 2).

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

from loguru import logger

from api.services import episode_staging

KEEP_SECONDS = 3600


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


def run(job_id: str, episodes: list[dict], episodes_dir: Path) -> None:
    """Stage ``episodes`` in one ``episode_staging.stage`` call. ``staged``
    advances per draft only after that draft's verdict is on disk, so the
    panel's count is never ahead of the bank. Always ends ``done``; a failure
    is recorded as ``error`` for the panel, never raised into the server."""
    job = get(job_id)
    if job is None:
        return

    def progress(verb: str) -> None:
        with _lock:
            job.staged += 1
            if verb == "skipped":
                job.skipped += 1
            elif verb == "created":
                job.created += 1
            else:  # updated, or renamed — a rename is an update to the panel
                job.updated += 1

    try:
        drafts = [episode_staging.draft_from_export(e) for e in episodes]
        episode_staging.stage(drafts, episodes_dir, bank=episodes_dir.parent.name, progress=progress)
    except Exception as exc:  # recorded for the panel, never raised into the server
        logger.error(f"Intake job {job_id} failed: {type(exc).__name__}")
        with _lock:
            job.error = f"{type(exc).__name__}: {exc}"
    finally:
        with _lock:
            job.done = True
            job.finished_at = time.time()
