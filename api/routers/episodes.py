"""``GET /episodes/{id}/span`` — slice a stored document back out (G118 s1).

The read half of evidence spans: a claim points at ``(episode, start, end,
hash)``; this endpoint returns those characters with context so a viewer
(slice 2) can highlight them inside the raw source. Engine-free by
construction — one ``markdown_parser.parse`` and string slicing (G80) —
and honest about drift: ``stale`` is set when the caller's ``hash`` matches
neither the current evidence text (R2) nor, for an episode, any
turn-boundary prefix of it — that case is ``grown`` (slice 2 / A7: the
conversation continued and the offsets are still exact). The slice is
returned either way so the viewer can show *something* while saying it may
have moved.

``{id}`` is a source-document id (R3): ``ep_*`` resolves under ``episodes/``,
anything else under ``entities/`` — the same resolver the writers use, so a
``page`` span on a media entity opens exactly what recon cited. Bearer-gated
like every route; no ETag (R9) — the response validates itself.

``GET /episodes/{id}/text`` (G118 slice 2) returns the WHOLE document with its
turns for the Reader — see ``provenance.episode_document``. It carries an
ETag for the client's in-memory cache only: it is fetched on demand and is
not a Store domain, so there is no ``VersionVector`` mapping (R-PB11).
``GET /episodes/{id}/citations`` lists every belief the document contributed
— see ``provenance.episode_citations`` (same ETag rule).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import EpisodeCitations, EpisodeSpan, EpisodeText
from api.services import evidence, provenance, sync_service

router = APIRouter()

# A viewer never needs more than a screen of context; 2,000 chars on each
# side keeps the response bounded regardless of the episode's size.
MAX_CONTEXT = 2000
DEFAULT_CONTEXT = 240


@router.get("/episodes/{episode_id}/span", response_model=EpisodeSpan)
async def get_episode_span(
    episode_id: str,
    start: int = Query(..., ge=0),
    end: int = Query(..., ge=1),
    context: int = Query(DEFAULT_CONTEXT, ge=0, le=MAX_CONTEXT),
    hash: str | None = Query(None, max_length=64),  # noqa: A002 - the field's own name
    settings: Settings = Depends(get_settings),
):
    """The evidence text at ``[start, end)`` with ``context`` chars either side."""
    text = evidence.source_text(settings.memory_path, episode_id)
    if text is None:
        raise HTTPException(404, f"No stored document {episode_id!r}")
    if end <= start or end > len(text):
        raise HTTPException(422, f"span [{start}, {end}) is outside the document (length {len(text)})")
    # A7: one freshness rule for every reader (R-PB1) — a Stop-hook episode
    # that took another turn is `grown`, not `stale`; a page never grows.
    status = evidence.span_status(
        text, end=end, hash=hash, appendable=evidence.is_episode_id(episode_id),
    )
    return EpisodeSpan(
        episode=episode_id,
        text=text[start:end],
        before=text[max(0, start - context):start],
        after=text[end:end + context],
        start=start,
        end=end,
        length=len(text),
        stale=status == evidence.SPAN_STALE,
        grown=status == evidence.SPAN_GROWN,
        kind=evidence.speaker_kind(text, start) if evidence.is_episode_id(episode_id) else "page",
        t=evidence.media_time(text, start) if evidence.is_episode_id(episode_id) else None,
    )


@router.get("/episodes/{episode_id}/text", response_model=EpisodeText)
async def get_episode_text(
    episode_id: str,
    request: Request,
    response: Response,
    start: int | None = Query(None, ge=0),
    end: int | None = Query(None, ge=1),
    hash: str | None = Query(None, max_length=64),  # noqa: A002 - the field's own name
    focus: str | None = Query(None, max_length=200),
    settings: Settings = Depends(get_settings),
):
    """The whole evidence text of one document, with its turns (G118 s2).

    ``start``/``end`` (+ ``hash``) ask for an asserted focus; ``focus=<entity>``
    for a derived one. 404 for an unknown or non-bare id (the ``source_path``
    rail), 422 for a half or out-of-range pair. Engine-free: one parse.
    """
    memory_path = settings.memory_path
    etag = sync_service.etag_for(
        memory_path, "episodes", "entities",
        extra=f"text|{episode_id}|{start}|{end}|{hash or ''}|{focus or ''}",
    )
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    try:
        doc = await run_in_threadpool(
            provenance.episode_document, memory_path, episode_id,
            start=start, end=end, hash=hash, focus=focus,
        )
    except provenance.SpanOutOfRange as exc:
        raise HTTPException(422, str(exc))
    if doc is None:
        raise HTTPException(404, f"No stored document {episode_id!r}")
    return doc


@router.get("/episodes/{episode_id}/citations", response_model=EpisodeCitations)
async def get_episode_citations(
    episode_id: str,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    """What this conversation taught Cicada (G118 s2, §4.8.3; G106 (ii)).

    Spans in document order, then rows without offsets; ``partial`` when more
    pages named the document than one call parses. Engine-free, nothing
    written. 404 for an unknown or non-bare id.
    """
    memory_path = settings.memory_path
    etag = sync_service.etag_for(memory_path, "episodes", "entities", extra=f"citations|{episode_id}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    result = await run_in_threadpool(provenance.episode_citations, memory_path, episode_id)
    if result is None:
        raise HTTPException(404, f"No stored document {episode_id!r}")
    return result
