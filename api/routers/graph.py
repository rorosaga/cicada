from fastapi import APIRouter, Depends

from api.config import Settings, get_settings
from api.models.schemas import GraphResponse
from api.services.graph_builder import build_graph

router = APIRouter()


@router.get("/graph", response_model=GraphResponse)
async def get_graph(settings: Settings = Depends(get_settings)):
    return build_graph(settings.memory_path)
