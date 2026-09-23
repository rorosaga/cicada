"""``GET /agents/wiring`` (Track I T3). Request/response, not a sync domain: no
ETag, nothing cached. See ``api/services/agent_wiring.py`` for why it only reads."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from api.config import Settings, get_settings
from api.models.schemas import AgentWiringResponse
from api.services import agent_wiring

router = APIRouter()


@router.get("/agents/wiring", response_model=AgentWiringResponse)
async def wiring(settings: Settings = Depends(get_settings)) -> AgentWiringResponse:
    data = await agent_wiring.probe(home=Path.home(), memory_root=settings.memory_root)
    return AgentWiringResponse(**data)
