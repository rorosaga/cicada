"""``GET /episodes/{id}/span`` — slice a stored document back out (G118 s1).

The read half of evidence spans: a claim points at ``(episode, start, end,
hash)``; this endpoint returns those characters with context so a viewer
(slice 2) can highlight them inside the raw source. Engine-free by
construction — one ``markdown_parser.parse`` and string slicing (G80) —
and honest about drift: ``stale`` is set when the caller's ``hash`` no
longer matches the current evidence text (R2), and the slice is still
returned so the viewer can show *something* while saying it may have moved.

``{id}`` is a source-document id (R3): ``ep_*`` resolves under ``episodes/``,
anything else under ``entities/`` — the same resolver the writers use, so a
``page`` span on a media entity opens exactly what recon cited. Bearer-gated
like every route; no ETag (R9) — the response validates itself.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.config import Settings, get_settings
from api.models.schemas import EpisodeSpan
from api.services import evidence

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
    current = evidence.body_hash(text)
    return EpisodeSpan(
        episode=episode_id,
        text=text[start:end],
        before=text[max(0, start - context):start],
        after=text[end:end + context],
        start=start,
        end=end,
        length=len(text),
        stale=bool(hash) and hash != current,
        kind=evidence.speaker_kind(text, start) if evidence.is_episode_id(episode_id) else "page",
    )
