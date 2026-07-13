"""Maintenance endpoints (G21): housekeeping operations over the graph that
sit outside the nightly Sleep cycle. Currently just the full-graph dedup
sweep — ``api/services/dedup_sweep.py`` and ``entity_merge.py`` were fully
built and tested but had zero production call sites; this router is that
call site.
"""
from fastapi import APIRouter, Depends

from api.config import Settings, get_settings
from api.models.schemas import (
    MaintenanceDedupSweepRequest,
    MaintenanceDedupSweepResponse,
    MaintenanceMergePair,
    MaintenanceNudgePair,
)
from api.services.dedup_sweep import dedup_sweep

router = APIRouter()


@router.post("/maintenance/dedup-sweep", response_model=MaintenanceDedupSweepResponse)
async def run_dedup_sweep(
    request: MaintenanceDedupSweepRequest,
    settings: Settings = Depends(get_settings),
):
    """Run the embedding-gate + LLM-judge dedup sweep over the active bank.

    ``dry_run`` (default true) never writes: candidate pairs the judge would
    merge come back under ``proposed`` instead of being merged. Set
    ``dry_run: false`` to actually perform the high-confidence merges.
    """
    report = dedup_sweep(
        settings.memory_path,
        settings,
        dry_run=request.dry_run,
        limit=request.limit,
    )
    return MaintenanceDedupSweepResponse(
        dry_run=request.dry_run,
        candidate_pairs=report.get("candidate_pairs", 0),
        merged=[
            MaintenanceMergePair(loser=loser, winner=winner)
            for loser, winner in report.get("merged", [])
        ],
        proposed=[
            MaintenanceMergePair(loser=loser, winner=winner)
            for loser, winner in report.get("proposed", [])
        ],
        nudged=[
            MaintenanceNudgePair(a=a, b=b) for a, b in report.get("nudged", [])
        ],
    )
