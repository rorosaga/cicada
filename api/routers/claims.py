"""Claim read endpoints + transclusion (M5b Part 2).

Per ``docs/goals/d2-companion-showcase.md`` (the authoritative API contract):

- ``GET /entities/{id}/claims`` → ``ClaimListResponse`` — a subject's claims
  (currently-valid by default; ``?include_superseded=true`` adds closed ones).
- ``GET /entities/{id}/timeline?predicate=&context=`` → ``ClaimTimeline`` — one
  ``(subject, predicate, context)`` key's ``superseded_by`` chain + validity
  windows, newest first (the flagship belief-timeline surface).
- ``GET /transclude?ref=<urlencoded>`` → ``TransclusionPayload`` — one resolved
  ``![[…]]`` embed, with depth-cap + cycle-guard + soft "not found" stub.
- ``GET /entities/{id}/provenance`` → ``EntityProvenance`` (G118 slice 2) —
  contributors, the conversations that fed the page, the best quote from
  each, and honest coverage; built by ``provenance.entity_provenance``.

All four are read-only projections over the markdown pages (the source of
truth); they add no write path. They reuse the same in-page ``parse_claims``
the index derives from, so a page edit is reflected immediately.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import (
    ClaimListResponse,
    ClaimModel,
    ClaimTimeline,
    EntityProvenance,
    TransclusionPayload,
)
from api.services import (
    git_service,
    markdown_parser,
    provenance,
    sync_service,
    transclusion_resolver,
)
from api.services.claims import Claim, is_record, parse_claims
from api.services.id_utils import resolve_entity_file

router = APIRouter()


def _claim_to_model(c: Claim) -> ClaimModel:
    """Every claim on the wire goes through ``transclusion_resolver.claim_to_model``
    (G118 slice 2, R-PB13): one builder, so this router and ``/transclude``
    never disagree about a claim's author identity, sessions or evidence."""
    return transclusion_resolver.claim_to_model(c)


def _is_currently_valid(c: Claim) -> bool:
    return c.valid_to is None and not c.superseded_by


def _load_subject_claims(memory_path: Path, entity_id: str) -> list[Claim]:
    """Parse a subject's in-page BELIEFS, or raise 404 if the page is missing.

    A withdrawal record (``predicate: retracts``, G140 Q-R5) is bookkeeping
    about another claim, never a belief, so it is dropped here through the one
    ``claims.is_record`` test every claim-listing surface shares. Served, two withdrawals in one context grouped
    into a "Contested beliefs" row named ``retracts`` whose values were raw
    claim ids (final review) — jargon the app's plain voice never shows.
    """
    page = resolve_entity_file(memory_path, entity_id)
    if page is None or not page.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    try:
        parsed = markdown_parser.parse(page)
    except Exception:
        return []
    return [c for c in parse_claims(parsed.body) if not is_record(c)]


@router.get("/entities/{entity_id}/claims", response_model=ClaimListResponse)
async def get_entity_claims(
    entity_id: str,
    include_superseded: bool = False,
    settings: Settings = Depends(get_settings),
):
    """A subject's claims — currently-valid by default; superseded on request."""
    claims = _load_subject_claims(settings.memory_path, entity_id)
    if not include_superseded:
        claims = [c for c in claims if _is_currently_valid(c)]
    return ClaimListResponse(claims=[_claim_to_model(c) for c in claims])


@router.get("/entities/{entity_id}/timeline", response_model=ClaimTimeline)
async def get_entity_timeline(
    entity_id: str,
    predicate: str,
    context: str,
    settings: Settings = Depends(get_settings),
):
    """One ``(subject, predicate, context)`` key's bi-temporal claim chain.

    Includes superseded claims (historical view), sorted newest-first: the
    currently-valid claim leads, closed claims follow by descending
    ``valid_from`` (then ``valid_to``) — the order the timeline view draws.
    """
    claims = _load_subject_claims(settings.memory_path, entity_id)
    key_claims = [
        c for c in claims if c.predicate == predicate and c.context == context
    ]
    key_claims.sort(key=_timeline_sort_key, reverse=True)
    return ClaimTimeline(
        subject=entity_id,
        predicate=predicate,
        context=context,
        claims=[_claim_to_model(c) for c in key_claims],
    )


@router.get("/entities/{entity_id}/provenance", response_model=EntityProvenance)
async def get_entity_provenance(
    entity_id: str,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    """Where an entity's beliefs came from and who wrote them (G118 s2, §4.8.4).

    One call for the card's "Where this came from" instead of N+2 (claims,
    history, one ``/conversations/{id}`` per session). Engine-free: one page
    parse, cached episode frontmatter, at most one body read per shown
    conversation, and ONE trailer-only ``git log`` of the page. Fetched on
    demand — not a Store domain — so the ETag serves the client's in-memory
    cache only and there is no ``VersionVector`` mapping (R-PB11); ``git_head``
    is in the recipe because the commit counts come from git, and a commit that
    lands after the file write would otherwise 304 a stale count.
    """
    memory_path = settings.memory_path
    page = resolve_entity_file(memory_path, entity_id)
    if page is None or not page.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    etag = sync_service.etag_for(
        memory_path, "entities", "episodes", "git_head", extra=f"provenance|{page.stem}",
    )
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    commits, truncated = await git_service.entity_commit_authors(memory_path, page.stem)
    return await run_in_threadpool(
        provenance.entity_provenance, memory_path, page,
        commit_authors=commits, commits_truncated=truncated,
    )


def _timeline_sort_key(c: Claim) -> tuple:
    """Newest-first: currently-valid wins, then by valid_from then valid_to."""
    return (
        1 if _is_currently_valid(c) else 0,
        c.valid_from or "",
        c.valid_to or "",
    )


@router.get("/transclude", response_model=TransclusionPayload)
async def get_transclusion(
    ref: str = "",
    settings: Settings = Depends(get_settings),
):
    """Resolve one ``![[ref]]`` embed. Never raises — a missing/cyclic/too-deep
    ref returns ``resolved=False`` so the client renders a soft stub."""
    return transclusion_resolver.resolve_transclusion(settings.memory_path, ref)
