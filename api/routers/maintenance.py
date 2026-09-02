"""Maintenance endpoints (G21): housekeeping operations over the graph that
sit outside the nightly Sleep cycle. The full-graph dedup sweep —
``api/services/dedup_sweep.py`` and ``entity_merge.py`` were fully built and
tested but had zero production call sites; this router is that call site —
plus ``enrich-links``, the on-demand twin of the Sleep-tail link backfill
(G102).
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from api.config import Settings, get_settings
from api.models.schemas import (
    MaintenanceDedupSweepRequest,
    MaintenanceDedupSweepResponse,
    MaintenanceEnrichLinksResponse,
    MaintenanceMergePair,
    MaintenanceNudgePair,
)
from api.services.dedup_sweep import dedup_sweep

router = APIRouter()

# One backfill per process (final review M4 / Task 3 review M1): two
# overlapping ``enrich-links`` calls would each read-modify-write the same
# media pages' frontmatter and claims, and each ``commit_paths`` would stage
# the other's half-written pages under its own author/engine trailers. The
# second caller gets a 409 rather than queueing — the first run's ``remaining``
# already tells them whether another click is worth it. Process-local on
# purpose: the backend is one uvicorn process, and the Sleep-cycle overlap is
# guarded separately by ``get_sleep_state`` (R11).
_enrich_lock = asyncio.Lock()


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


@router.post("/maintenance/enrich-links", response_model=MaintenanceEnrichLinksResponse)
async def run_enrich_links(
    limit: int | None = Query(None, ge=1, le=500),
    recon_limit: int | None = Query(None, ge=0, le=500),
    settings: Settings = Depends(get_settings),
):
    """Describe + relate saved links now (G102 cheap slice) — the on-demand
    twin of the Sleep-tail backfill.

    User-initiated, so (R10) the live fetch + summarize seams are passed
    ungated — ``CICADA_ALLOW_CONNECTOR_FETCH`` gates only the unattended
    nightly poll, exactly the connector contract (G71 final review H2) — and
    the engine is resolved as a user-triggered cycle would resolve it, so a
    connected Claude plan is used when the owner asked for it. ``409`` while
    a Sleep cycle is running: the tail writes the same media pages (R11) —
    and ``409`` while another ``enrich-links`` call is still running, for the
    same reason (``_enrich_lock``).
    The kill switch (``link_enrich_enabled``) returns an empty report before
    the engine is even resolved — "off" must never probe a plan.
    Warm a bulk-imported bank with ``?limit=50`` a few times; each run
    reports ``remaining`` so the drain is visible.
    """
    from api.services import engine_select, link_enrichment, sleep_cycle

    if _enrich_lock.locked():
        raise HTTPException(409, "a link backfill is already running — retry when it finishes")
    if sleep_cycle.get_sleep_state().status == "running":
        raise HTTPException(
            409,
            "a Sleep cycle is running and writes the same media pages — retry when it finishes",
        )
    if not settings.link_enrich_enabled:
        return MaintenanceEnrichLinksResponse()
    async with _enrich_lock:
        resolved, why = await engine_select.resolve_settings(settings, user_triggered=True)
        engine = engine_select.engine_label(resolved)
        report = await link_enrichment.backfill(
            resolved.memory_path,
            resolved,
            limit=limit if limit is not None else resolved.link_enrich_backfill_per_cycle,
            recon_limit=recon_limit,
            summarize_fn=link_enrichment._summarize_excerpt,
            fetch_fn=link_enrichment.default_fetch,
            engine=engine,
        )
    return MaintenanceEnrichLinksResponse(**report.as_dict(), engine=engine, engine_detail=why)
