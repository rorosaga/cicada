"""G147 — Settings → Memory's pace controls.

``GET /memory/decay-suggestions`` derives, from the bank's own decay answers,
which kinds of page the person keeps (or lets go of) far more often than
Cicada expected; ``PUT /memory/decay-tuning`` stores the pace they approve.
Neither is a Store domain, so neither carries an ETag (plan R-FD7).
"""

import asyncio
from datetime import date
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from api.config import Settings, get_settings
from api.models.schemas import DecayTuningResponse
from api.services import decay_tuning, git_service

router = APIRouter()

# One read-merge-write at a time in this process: two quick clicks (Apply,
# then Reset) must not both read the old file and drop each other's change.
_write_lock = asyncio.Lock()
BUSY = "Sleep is running — try again when it finishes"


@router.get("/memory/decay-suggestions", response_model=DecayTuningResponse)
async def get_decay_suggestions(settings: Settings = Depends(get_settings)):
    return DecayTuningResponse(**await decay_tuning.overview(settings.memory_path))


@router.put("/memory/decay-tuning", response_model=DecayTuningResponse)
async def put_decay_tuning(
    changes: dict[str, Optional[float]] = Body(...),
    settings: Settings = Depends(get_settings),
):
    """Merge ``{type: multiplier | null}`` into ``_decay_tuning.yaml``.

    409 while Sleep runs: Stage 3 reads this file, and a file written but not
    yet committed would ride the next ``git add -A`` writer's commit under the
    model's author (the G85 smear; `routers/projects.py`'s guard). The commit is
    this one file, as the person.
    """
    from api.services import sleep_cycle

    if sleep_cycle.get_sleep_state().status == "running":
        raise HTTPException(409, BUSY)
    async with _write_lock:
        try:
            tuning = decay_tuning.merge(decay_tuning.load(settings.memory_path), changes)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if decay_tuning.save(settings.memory_path, tuning):
            message = git_service.build_commit_message(
                f"Decay tuning {date.today().isoformat()}",
                [f"{decay_tuning.FILE}: updated (trigger: user/companion_app)"],
                authors=["user"],
            )
            await git_service.commit_paths(settings.memory_path, message, [decay_tuning.FILE])
    return DecayTuningResponse(**await decay_tuning.overview(settings.memory_path))
