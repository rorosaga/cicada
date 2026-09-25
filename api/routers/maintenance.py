"""Maintenance endpoints (G21): housekeeping operations over the graph that
sit outside the nightly Sleep cycle. The full-graph dedup sweep —
``api/services/dedup_sweep.py`` and ``entity_merge.py`` were fully built and
tested but had zero production call sites; this router is that call site —
plus ``enrich-links``, the on-demand twin of the Sleep-tail link backfill
(G102).
"""
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import (
    MaintenanceDedupSweepRequest,
    MaintenanceDedupSweepResponse,
    MaintenanceEnrichLinksResponse,
    MaintenanceMergePair,
    MaintenanceNudgePair,
    SearchIndexStatus,
)
from api.services import search_index
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
        skipped_rejected=report.get("skipped_rejected", 0),
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
    from api.services import agent_engine, engine_select, link_enrichment, sleep_cycle

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
        # Final review H1: its own self-purging breaker scope, never the
        # shared ``_unscoped`` bucket that nothing resets — a throttle stops
        # this run (backfill aborts on the first EngineError) and is forgotten
        # when it ends, so the next click spawns again once the plan resets.
        with agent_engine.use_scope(f"links:{uuid.uuid4().hex}"):
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


# --- Search index (G139, Settings → Memory) ----------------------------------

# One rebuild per process, for the reason `_enrich_lock` exists: two
# overlapping rebuilds would each drop and refill the same tables.
_index_lock = asyncio.Lock()


def _built_at(memory_path: Path) -> str | None:
    db = search_index.db_path(memory_path)
    if not db.exists():
        return None
    return datetime.fromtimestamp(db.stat().st_mtime, tz=timezone.utc).isoformat()


@router.get("/maintenance/search-index", response_model=SearchIndexStatus)
async def search_index_status(settings: Settings = Depends(get_settings)):
    """Settings → Memory (G139): how fresh the derived FTS5 index is. Deleting
    or rebuilding it costs CPU, never a fact (TODO ruling 3). The same
    `ensure_fresh` every read path calls, so asking may start the catch-up."""
    memory_path = settings.memory_path
    state = await run_in_threadpool(search_index.ensure_fresh, memory_path)
    return SearchIndexStatus(state=state, built_at=_built_at(memory_path))


@router.post("/maintenance/search-index/rebuild", response_model=SearchIndexStatus)
async def rebuild_search_index(settings: Settings = Depends(get_settings)):
    """Rebuild the derived index now. 409 while a Sleep cycle runs (it rebuilds
    the same file) or while another rebuild runs; a failure is a plain 503 —
    search keeps working from the frontmatter cache (G136)."""
    from api.services import sleep_cycle

    if _index_lock.locked():
        raise HTTPException(409, "A rebuild is already running.")
    if sleep_cycle.get_sleep_state().status == "running":
        raise HTTPException(409, "A Sleep cycle is running and rebuilds the index itself.")
    # Resolved once: a bank switch mid-rebuild must not make the status below
    # describe a different bank than the one just rebuilt (the split-brain rule).
    memory_path = settings.memory_path
    async with _index_lock:
        try:
            documents = await run_in_threadpool(search_index.rebuild, memory_path)
        except Exception as exc:  # noqa: BLE001 — the reason is logged by class, never sent
            logger.warning(f"search index rebuild failed ({type(exc).__name__})")
            raise HTTPException(503, "The search index couldn't be rebuilt. Search still works from your pages.")
    state = await run_in_threadpool(search_index.ensure_fresh, memory_path)
    return SearchIndexStatus(state=state, built_at=_built_at(memory_path), documents=documents)
