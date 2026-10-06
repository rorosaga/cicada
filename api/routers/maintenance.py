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
from api.services.sleep_refusal import SleepWriting

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
    ``dry_run: false`` to actually perform the high-confidence merges — each
    one its own ``cicada`` commit of exactly the paths it wrote or removed
    (``Dedup sweep <date>``, trigger ``maintenance/dedup-sweep``; G183(e)).

    409 while Sleep holds the pages (G177's ``is_writing``), a dry run too —
    it reads the pages a batch is rewriting. A window that opens mid-sweep
    stops the merging (``stoppedForSleep``). Off the event loop: the judge is
    a model call per pair.
    """
    from api.services import sleep_cycle

    if sleep_cycle.is_writing():
        raise HTTPException(409, "a Sleep cycle is running and writes the same pages — retry when it finishes")
    memory_path = settings.memory_path   # resolved once (the split-brain rule)
    report = await run_in_threadpool(
        dedup_sweep,
        memory_path,
        settings,
        dry_run=request.dry_run,
        limit=request.limit,
        may_write=lambda: not sleep_cycle.is_writing(),
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
        stopped_for_sleep=report.get("stopped_for_sleep", False),
        skipped_dirty=[MaintenanceMergePair(loser=l, winner=w) for l, w in report.get("skipped_dirty", [])],
        skipped_unsafe=[MaintenanceMergePair(loser=l, winner=w) for l, w in report.get("skipped_unsafe", [])],
        failed=[MaintenanceMergePair(loser=l, winner=w) for l, w in report.get("failed", [])],
        recovery_failed=report.get("recovery_failed", False),
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
    if sleep_cycle.is_writing():
        raise SleepWriting(
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


# --- Sources linked to their own page (G61 S3-a, D8) ---------------------------------------------------------

_links_lock = asyncio.Lock()


@router.post("/maintenance/link-sources")
async def link_sources(settings: Settings = Depends(get_settings)):
    """Link every source that is EXACTLY a saved page (its URL) or a directory page (its path) to that page —
    engine-free, exact matches only, an empty ``entity:`` only, never a page created. The on-demand twin of the
    Sleep tail's step; one `cicada` commit (``Source links <date>``, trigger ``maintenance/source-links``). 409
    while Sleep runs or another call runs. Counts only in the body."""
    from datetime import date

    from api.services import git_service, sleep_cycle, source_links

    if _links_lock.locked():
        raise HTTPException(409, "a source-link pass is already running — retry when it finishes")
    if sleep_cycle.is_writing():
        raise SleepWriting("a Sleep cycle is running and writes the same pages — retry when it finishes")
    async with _links_lock:
        memory_path = settings.memory_path
        skip: frozenset[str] = frozenset()
        if (memory_path / ".git").exists():
            skip = await sleep_cycle._dirty_paths(memory_path)
        report = await asyncio.to_thread(source_links.backfill, memory_path, skip)
        if report.paths and (memory_path / ".git").exists():
            try:
                await git_service.commit_paths(
                    memory_path,
                    source_links.commit_message(report, date.today(), "maintenance/source-links"), report.paths)
            except Exception:
                await asyncio.to_thread(source_links.restore, memory_path, report)
                raise HTTPException(500, "the links could not be committed; nothing was changed")
    return {"linked": report.linked, "pages": len(report.paths)}


# --- Official sites, confirmed on Cicada's own rail (G61 S3-b) ---------------------------------------------------

_sites_lock = asyncio.Lock()
# One request holds a connection open for every fetch it makes (each ≤ 4 s, sequential), so the route's work is capped;
# `deferred` in the answer says how many were left for the next click or night.
ROUTE_BUDGET_DEFAULT = 40


@router.post("/maintenance/verify-sites")
async def verify_sites(
    budget: int = Query(ROUTE_BUDGET_DEFAULT, ge=1, le=ROUTE_BUDGET_DEFAULT),
    settings: Settings = Depends(get_settings),
):
    """Propose and confirm official sites now — the person's click, so (like `enrich-links`) it is ungated:
    `CICADA_ALLOW_CONNECTOR_FETCH` gates only the unattended nightly step. Same rail as the tail: at most `budget`
    fetches (40, the cap — `deferred` counts what waits for the next click), one per site, never a walled or platform
    host, Cicada's own read (4 s, ≤ 512 KB, no cookies). 409 while Sleep runs, another call runs, or the bank is the demo
    (a made-up bank's sites are not Cicada's to read). One `cicada` commit (`Site check <date>`, trigger `user/companion_app`). Counts
    only in the body: never a host, a page or a reason."""
    from datetime import date

    from api.services import demo_guard, git_service, sleep_cycle, site_sources

    if demo_guard.is_demo(settings.memory_path):
        raise HTTPException(409, "this is the demo memory, made up for the tour — there are no real sites to check")
    if _sites_lock.locked():
        raise HTTPException(409, "a site check is already running — retry when it finishes")
    if sleep_cycle.is_writing():
        raise SleepWriting("a Sleep cycle is running and writes the same pages — retry when it finishes")
    async with _sites_lock:
        memory_path = settings.memory_path
        skip: frozenset[str] = frozenset()
        if (memory_path / ".git").exists():
            skip = await sleep_cycle._dirty_paths(memory_path)
        report = site_sources.Report()
        try:
            await asyncio.to_thread(site_sources.propose, memory_path, skip, report)
            await site_sources.verify(memory_path, budget=budget, skip=skip, settings=settings, report=report)
        except Exception:
            # A page written before the failure must not ride the next `git add -A` writer's commit (the G85 smear).
            await asyncio.to_thread(site_sources.restore, memory_path, report)
            raise HTTPException(500, "the site check stopped part-way; nothing was changed")
        if report.paths and (memory_path / ".git").exists():
            try:
                await git_service.commit_paths(
                    memory_path,
                    site_sources.commit_message(report, date.today(), site_sources.ROUTE_TRIGGER), report.paths)
            except Exception:
                await asyncio.to_thread(site_sources.restore, memory_path, report)
                raise HTTPException(500, "the site check could not be committed; nothing was changed")
    return {"pages": len(report.paths), **{k: report.counts.get(k, 0) for k in (
        "proposed", "fetched", "verified", "unconfirmed", "mismatch", "platform", "unreachable", "deferred")},
            "budget": budget}


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
    if sleep_cycle.is_writing():
        raise SleepWriting("A Sleep cycle is running and rebuilds the index itself.")
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
