"""G117 — the owner's identity: one name, resolved into the observer every
user-stated claim carries (see `owner_identity.resolve_observer`) and into
the one entity page `GET /graph` marks `isOwner: true`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.config import Settings, get_settings
from api.models.schemas import OwnerSettingsResponse, OwnerUpdateRequest
from api.services import owner_identity

router = APIRouter(prefix="/settings")


@router.get("/owner", response_model=OwnerSettingsResponse)
async def get_owner(settings: Settings = Depends(get_settings)) -> OwnerSettingsResponse:
    data = owner_identity.load_owner()
    return OwnerSettingsResponse(
        name=data.get("name", ""),
        handle=data.get("handle"),
        email=data.get("email"),
        observer=owner_identity.resolve_observer(settings.memory_path, settings),
        entity_id=data.get("entity_id"),
    )


@router.put("/owner", response_model=OwnerSettingsResponse)
async def put_owner(
    req: OwnerUpdateRequest, settings: Settings = Depends(get_settings)
) -> OwnerSettingsResponse:
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "name is required")
    entity_id, _ = owner_identity.ensure_owner_entity(settings.memory_path, name)
    owner_identity.save_owner(
        {"name": name, "handle": req.handle, "email": req.email, "entity_id": entity_id}
    )
    return OwnerSettingsResponse(
        name=name, handle=req.handle, email=req.email, observer=entity_id, entity_id=entity_id,
    )
