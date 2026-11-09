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
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
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
    claims,
    git_service,
    markdown_parser,
    provenance,
    sync_service,
    transclusion_resolver,
    turn_authorship,
)
from api.services.claims import Claim, is_event, is_mark, is_record, parse_claims
from api.services.id_utils import resolve_entity_file

router = APIRouter()

#: (bank, page, flags) -> (validity stamp, the response). A big page's claim list is seconds of work and
#: megabytes of JSON (the owner's: ~1.1 s warm, 7.6 MB, 2026-11-09), rebuilt by every read; this keeps the last one per
#: page until the entities or episodes it is built from move (or the day turns: validity is read against today). Not an
#: ETag on the wire: this answers the same body, only sooner. Process-local and disposable.
_MEMO: dict[tuple, tuple[str, ClaimListResponse]] = {}
_MEMO_KEPT = 16
_PROVENANCE_MEMO: dict[tuple, tuple[str, object]] = {}


def _remember(table: dict, key: tuple, value: tuple, kept: int) -> None:
    if key not in table and len(table) >= kept:
        table.pop(next(iter(table)))   # the oldest; plain insertion order
    table[key] = value


def _claim_to_model(c: Claim, turns: turn_authorship.TurnAuthorship | None) -> ClaimModel:
    """Every claim on the wire goes through ``transclusion_resolver.claim_to_model``
    (G118 slice 2, R-PB13): one builder, so this router and ``/transclude``
    never disagree about a claim's author identity, sessions or evidence.
    ``turns`` is the request's one model join (round 4 C3, R4B-8)."""
    return transclusion_resolver.claim_to_model(c, turns=turns)


def _is_currently_valid(c: Claim) -> bool:
    return claims.is_current(c)


def _load_subject_claims(memory_path: Path, entity_id: str) -> list[Claim]:
    """Parse a subject's in-page BELIEFS, or raise 404 if the page is missing.

    A withdrawal record (``predicate: retracts``, G140 Q-R5) is bookkeeping
    about another claim, never a belief, so it is dropped here through the one
    ``claims.is_record`` test every claim-listing surface shares. Served, two withdrawals in one context grouped
    into a "Contested beliefs" row named ``retracts`` whose values were raw
    claim ids (final review) — jargon the app's plain voice never shows. What the person marked in a book is no belief
    either (ruling 64): the page's own block draws it.
    """
    page = resolve_entity_file(memory_path, entity_id)
    if page is None or not page.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    try:
        parsed = markdown_parser.parse(page)
    except Exception:
        return []
    return [c for c in parse_claims(parsed.body) if not is_record(c) and not is_mark(c)]


@router.get("/entities/{entity_id}/claims", response_model=ClaimListResponse)
async def get_entity_claims(
    entity_id: str,
    include_superseded: bool = False,
    include_events: bool = False,
    predicate: Annotated[list[str] | None, Query()] = None,
    settings: Settings = Depends(get_settings),
):
    """A subject's claims — currently-valid by default; superseded on request.

    ``predicate`` (repeatable) keeps only claims with one of those predicates: a person card asks for its "Works at"
    and "Role" beliefs when it opens, a few rows instead of every belief on an owner-sized page (megabytes).

    Event claims (G141 `happened`/`milestone`) only with ``include_events``
    (R-PJB10): the shipped card groups claims by ``(predicate, context)`` and
    calls any key with two or more "contested" (``EntityDetailCard.swift``),
    so every project with two happenings would grow a bogus contested row.
    Events have their own reader, ``/projects/{id}/timeline``.

    Built in the threadpool (round 4 final review #2): the C3 model join scans
    the episode index and reads each cited capture body — seconds cold on a big
    bank — and on the event loop that would stall SSE and every other request,
    the hazard ``/origins`` and ``/sources/channels`` were moved off it for.
    """
    return await run_in_threadpool(
        _claims_response, settings.memory_path, entity_id, include_superseded, include_events, predicate,
    )


def _claims_response(memory_path: Path, entity_id: str, include_superseded: bool, include_events: bool,
                     predicates: list[str] | None) -> ClaimListResponse:
    page = resolve_entity_file(memory_path, entity_id)
    if page is None or not page.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    flags = f"{int(include_superseded)}{int(include_events)}|{','.join(sorted(predicates or []))}"
    key = (str(memory_path), page.stem, flags)
    stamp = sync_service.etag_for(
        memory_path, "entities", "episodes", extra=f"claims|{page.stem}|{flags}|{claims.current_day()}")
    hit = _MEMO.get(key)
    if hit is None or hit[0] != stamp:
        built = _build_entity_claims(memory_path, entity_id, include_superseded, include_events, predicates)
        hit = (stamp, built)
        _remember(_MEMO, key, hit, _MEMO_KEPT)
    return hit[1]


def _build_entity_claims(memory_path: Path, entity_id: str, include_superseded: bool,
                         include_events: bool, predicates: list[str] | None = None) -> ClaimListResponse:
    claims = _load_subject_claims(memory_path, entity_id)
    if predicates:
        wanted = set(predicates)
        claims = [c for c in claims if c.predicate in wanted]
    if not include_events:
        claims = [c for c in claims if not is_event(c)]
    if not include_superseded:
        claims = [c for c in claims if _is_currently_valid(c)]
    turns = turn_authorship.TurnAuthorship(memory_path)
    return ClaimListResponse(claims=[_claim_to_model(c, turns) for c in claims])


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
    In the threadpool for the same reason as ``/claims`` (final review #2).
    """
    return await run_in_threadpool(
        _build_entity_timeline, settings.memory_path, entity_id, predicate, context,
    )


def _build_entity_timeline(memory_path: Path, entity_id: str, predicate: str, context: str) -> ClaimTimeline:
    claims = _load_subject_claims(memory_path, entity_id)
    key_claims = [
        c for c in claims if c.predicate == predicate and c.context == context
    ]
    key_claims.sort(key=_timeline_sort_key, reverse=True)
    turns = turn_authorship.TurnAuthorship(memory_path)
    return ClaimTimeline(
        subject=entity_id,
        predicate=predicate,
        context=context,
        claims=[_claim_to_model(c, turns) for c in key_claims],
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
        memory_path, "entities", "episodes", "git_head",
        extra=f"provenance|{page.stem}|{git_service.AUTHOR_SHAPE}|src1|sections3|validity2|said2|served1|device1|{claims.current_day()}",
    )
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    # The same stamp is the cache key: the page's account is rebuilt only when what it is made of moved (the owner's
    # page took ~3.8 s every open, 2026-11-09), and the commit walk is skipped with it.
    key = (str(memory_path), page.stem)
    hit = _PROVENANCE_MEMO.get(key)
    if hit is not None and hit[0] == etag:
        return hit[1]
    commits, truncated = await git_service.entity_commit_authors(memory_path, page.stem)
    built = await run_in_threadpool(
        provenance.entity_provenance, memory_path, page,
        commit_authors=commits, commits_truncated=truncated,
    )
    _remember(_PROVENANCE_MEMO, key, (etag, built), _MEMO_KEPT)
    return built


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
    ref returns ``resolved=False`` so the client renders a soft stub. In the
    threadpool: its claims carry the C3 model join too (final review #2)."""
    return await run_in_threadpool(transclusion_resolver.resolve_transclusion, settings.memory_path, ref)
