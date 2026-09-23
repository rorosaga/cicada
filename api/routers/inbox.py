import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response

from api.config import Settings, get_settings
from api.models.schemas import CheckCensus, InboxItem, InboxResolveRequest
from api.services import inbox_service, source_check, sync_service

router = APIRouter()


@router.get("/inbox", response_model=list[InboxItem])
async def list_inbox(
    request: Request,
    response: Response,
    kind: Optional[str] = Query(None),
    settings: Settings = Depends(get_settings),
):
    # G97 ship-together trap (G115 R3): the response now embeds entity- and
    # episode-derived context (cause excerpt, entity type), so an entity edit
    # or a new episode must move this ETag too. The CLIENT half — `.inbox`
    # on `VersionVector`'s `entities`/`episodes` mappings — lands in the same
    # commit; without it SnapshotCache serves stale context until the inbox
    # itself changes.
    etag = sync_service.etag_for(settings.memory_path, "inbox", "entities", "episodes", extra=kind or "")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    items = inbox_service.load_inbox(settings.memory_path)
    if kind:
        wanted = {k.strip() for k in kind.split(",") if k.strip()}
        items = [i for i in items if i.kind.value in wanted]
    return items


@router.get("/inbox/check-census", response_model=CheckCensus)
async def check_census(settings: Settings = Depends(get_settings)):
    """G61 phase 2 S2 — how much of the pending inbox a source could answer.

    Counts per state, reason, kind, locus, rung and target access — enum keys
    only, never an item id, page id, link or host, so the census can be pasted
    into a PR or a backlog row. Read-only and engine-free; it parses the bank,
    so it runs off the event loop. No ETag: not a Store domain, and no screen
    polls it. The same numbers: ``scripts/check-census.sh <bank>``.
    """
    return CheckCensus(**await asyncio.to_thread(source_check.census, settings.memory_path))


@router.post("/inbox/{item_id}/resolve")
async def resolve_inbox(
    item_id: str,
    request: InboxResolveRequest,
    settings: Settings = Depends(get_settings),
):
    return await inbox_service.resolve(item_id, request, settings)
