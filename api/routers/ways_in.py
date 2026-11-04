"""``GET /sources/ways-in`` — each consumption source's ways in, for the standard source page's connect area (G232).

Read-only: ``ways_in`` reads the connectors' status and the saved-list switches and writes nothing. Every action the
page offers is an existing route (``ways_in``'s module doc lists them).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.config import Settings, get_settings
from api.services import ways_in

router = APIRouter(prefix="/sources/ways-in")


@router.get("")
async def list_ways_in(settings: Settings = Depends(get_settings)):
    return {"sources": ways_in.describe_all(settings.memory_path)}


@router.get("/{source_id}")
async def get_ways_in(source_id: str, settings: Settings = Depends(get_settings)):
    found = ways_in.describe(source_id, settings.memory_path)
    if found is None:
        raise HTTPException(status_code=404, detail=f"unknown source '{source_id}'")
    return found
