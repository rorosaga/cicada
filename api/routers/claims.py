"""Claim read endpoints + transclusion (M5b Part 2).

Per ``docs/goals/d2-companion-showcase.md`` (the authoritative API contract):

- ``GET /entities/{id}/claims`` → ``ClaimListResponse`` — a subject's claims
  (currently-valid by default; ``?include_superseded=true`` adds closed ones).
- ``GET /entities/{id}/timeline?predicate=&context=`` → ``ClaimTimeline`` — one
  ``(subject, predicate, context)`` key's ``superseded_by`` chain + validity
  windows, newest first (the flagship belief-timeline surface).
- ``GET /transclude?ref=<urlencoded>`` → ``TransclusionPayload`` — one resolved
  ``![[…]]`` embed, with depth-cap + cycle-guard + soft "not found" stub.

All three are read-only projections over the markdown pages (the source of
truth); they add no write path. They reuse the same in-page ``parse_claims``
the index derives from, so a page edit is reflected immediately.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from api.config import Settings, get_settings
from api.models.schemas import (
    ClaimListResponse,
    ClaimModel,
    ClaimTimeline,
    TransclusionPayload,
)
from api.services import markdown_parser, transclusion_resolver
from api.services.claims import Claim, parse_claims
from api.services.id_utils import resolve_entity_file

router = APIRouter()


def _claim_to_model(c: Claim) -> ClaimModel:
    return ClaimModel(
        id=c.id,
        text=c.text,
        subject=c.subject,
        predicate=c.predicate,
        object=c.object,
        object_kind=c.object_kind,
        observer=c.observer,
        context=c.context,
        epistemic=c.epistemic,
        source_trust=c.source_trust,
        confidence=c.confidence,
        valid_from=c.valid_from or "",
        valid_to=c.valid_to,
        superseded_by=c.superseded_by,
        supersedes=c.supersedes,
        source_episodes=c.source_episodes,
        premises=c.premises,
        authored_by=c.authored_by or "unknown",
        origin=c.origin,
    )


def _is_currently_valid(c: Claim) -> bool:
    return c.valid_to is None and not c.superseded_by


def _load_subject_claims(memory_path: Path, entity_id: str) -> list[Claim]:
    """Parse a subject's in-page claims, or raise 404 if the page is missing."""
    page = resolve_entity_file(memory_path, entity_id)
    if page is None or not page.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    try:
        parsed = markdown_parser.parse(page)
    except Exception:
        return []
    return parse_claims(parsed.body)


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
