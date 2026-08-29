"""Repo-wide capture-origin provenance (ORIGIN-PROVENANCE aggregation).

Surfaces, for each capture origin (mcp, telegram, chrome-bookmark,
safari-bookmark, claude-export, ...), how many episodes came from it and how
many distinct entities are attributable to it — "where did this memory come
from", mirroring ``api/routers/contributors.py``'s "who authored this belief".
"""

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import OriginsResponse
from api.services import origin_stats, sync_service

router = APIRouter()


@router.get("/origins", response_model=OriginsResponse)
async def get_origins(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    etag = sync_service.etag_for(settings.memory_path, "episodes", "entities")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    origins = await run_in_threadpool(origin_stats.aggregate_origins, settings.memory_path)
    return OriginsResponse(origins=origins)
