from fastapi import APIRouter, Depends

from api.config import Settings, get_settings
from api.models.schemas import GraphResponse
from api.services.graph_builder import build_graph

router = APIRouter()


def _split(value: str | None) -> set[str] | None:
    if not value:
        return None
    parts = {p.strip() for p in value.split(",") if p.strip()}
    return parts or None


@router.get("/graph", response_model=GraphResponse)
async def get_graph(
    types: str | None = None,
    statuses: str | None = None,
    min_confidence: float = 0.0,
    tags: str | None = None,
    include_hubs: bool = True,
    hubs_only: bool = False,
    settings: Settings = Depends(get_settings),
):
    return build_graph(
        settings.memory_path,
        types=_split(types),
        statuses=_split(statuses),
        min_confidence=min_confidence,
        tags=_split(tags),
        include_hubs=include_hubs,
        hubs_only=hubs_only,
    )
