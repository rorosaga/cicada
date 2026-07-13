"""Repo-wide capture-origin provenance (ORIGIN-PROVENANCE aggregation).

Surfaces, for each capture origin (mcp, telegram, chrome-bookmark,
safari-bookmark, claude-export, ...), how many episodes came from it and how
many distinct entities are attributable to it — "where did this memory come
from", mirroring ``api/routers/contributors.py``'s "who authored this belief".
"""

from fastapi import APIRouter, Depends

from api.config import Settings, get_settings
from api.models.schemas import OriginsResponse
from api.services import origin_stats

router = APIRouter()


@router.get("/origins", response_model=OriginsResponse)
async def get_origins(
    settings: Settings = Depends(get_settings),
):
    origins = origin_stats.aggregate_origins(settings.memory_path)
    return OriginsResponse(origins=origins)
