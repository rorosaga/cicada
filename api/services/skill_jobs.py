"""Skill installs that take a while (a uv tool, the onboarding step, Update all) run as one background job each in
the backend, and the Skills page polls them. In memory only: a restart forgets a finished job, and an unfinished one
simply did not finish (the page shows what is installed, which is the truth either way)."""
from __future__ import annotations

import asyncio
import uuid
from typing import Awaitable, Callable

from loguru import logger

from api.services import skill_store

MAX_KEPT = 20
_JOBS: dict[str, dict] = {}
_TASKS: set[asyncio.Task] = set()


def start(kind: str, label: str, work: Callable[[dict], Awaitable[dict | None]]) -> dict:
    """Run ``work(job)`` in the background. ``work`` may set ``job["step"]`` as it goes."""
    job = {"id": uuid.uuid4().hex[:12], "kind": kind, "label": label, "state": "running", "step": None,
           "message": None, "result": None, "startedAt": skill_store.now_iso(), "finishedAt": None}
    _JOBS[job["id"]] = job
    while len(_JOBS) > MAX_KEPT:
        oldest = next((k for k, v in _JOBS.items() if v["state"] != "running"), None)
        if oldest is None:
            break
        _JOBS.pop(oldest)

    async def run() -> None:
        try:
            job["result"] = await work(job)
            job["state"] = "done"
        except skill_store.StoreError as exc:
            job["state"], job["message"] = "failed", str(exc)
        except Exception as exc:  # noqa: BLE001 — a job never takes the backend down; it says it failed
            logger.warning(f"skill_jobs: {kind} failed ({type(exc).__name__}: {exc})")
            job["state"], job["message"] = "failed", "Something went wrong while installing. Nothing else changed."
        finally:
            job["finishedAt"] = skill_store.now_iso()

    task = asyncio.get_running_loop().create_task(run())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return job


def get(job_id: str) -> dict | None:
    return _JOBS.get(job_id)


def running() -> list[dict]:
    return [j for j in _JOBS.values() if j["state"] == "running"]


def recent() -> list[dict]:
    return list(_JOBS.values())[-5:]


async def wait_all() -> None:
    """For tests: let every running job finish."""
    while _TASKS:
        await asyncio.gather(*list(_TASKS), return_exceptions=True)
