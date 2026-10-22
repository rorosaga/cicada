"""``GET /agents/wiring`` (Track I T3) and ``GET /agents/setup`` (round 4 C5).
Request/response, not sync domains: no ETag, nothing cached. See
``api/services/agent_wiring.py`` for why both only read."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from api.config import Settings, get_settings
from api.models.schemas import AgentLiveResponse, AgentSetupResponse, AgentWiringResponse
from api.services import agent_live, agent_wiring

router = APIRouter()


@router.get("/agents/wiring", response_model=AgentWiringResponse)
async def wiring(settings: Settings = Depends(get_settings)) -> AgentWiringResponse:
    data = await agent_wiring.probe(home=Path.home(), memory_root=settings.memory_root)
    return AgentWiringResponse(**data)


@router.get("/agents/setup", response_model=AgentSetupResponse)
async def setup(harness: str = Query(..., max_length=40),
                settings: Settings = Depends(get_settings)) -> AgentSetupResponse:
    """Round 4 C5 (G76's in-app half): what to hand an agent so it connects
    itself. Engine-free and static per machine — no probe, no subprocess, no
    harness file read — so no ETag (not a Store domain)."""
    data = agent_wiring.setup(harness, home=Path.home(), memory_root=settings.memory_root)
    if data is None:
        raise HTTPException(404, f"No setup for {harness!r}")
    return AgentSetupResponse(**data)


@router.get("/agents/live", response_model=AgentLiveResponse)
def live() -> AgentLiveResponse:
    """Round 4 C8: the live ✓. Engine-free, subprocess-free, never persisted —
    see api/services/agent_live.py for the three signals and the one rule."""
    return AgentLiveResponse(**agent_live.snapshot(home=Path.home()))


@router.get("/providers")
def providers() -> dict:
    """G217: the one table of who connects to Cicada — an umbrella per provider with its logo slug, the ways each of
    its products connects (stdio and hooks, the remote connector, the HTTP API, Messages, an export), their setup ids,
    the ``clientInfo`` words that recognise them, and the plans and keys that can run Sleep. Static per release (no
    probe, no file read), so no ETag: the app fetches it once per launch and caches it in memory."""
    from api.services import agent_catalog

    return agent_catalog.snapshot()
