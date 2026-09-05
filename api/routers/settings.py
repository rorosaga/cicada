"""G117 — the owner's identity: one name, resolved into the observer every
user-stated claim carries (see `owner_identity.resolve_observer`) and into
the one entity page `GET /graph` marks `isOwner: true`.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from api.config import Settings, get_settings
from api.models.schemas import OwnerSettingsResponse, OwnerUpdateRequest
from api.services import git_service, owner_identity

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
    entity_id, created = owner_identity.ensure_owner_entity(settings.memory_path, name)
    owner_identity.save_owner(
        {"name": name, "handle": req.handle, "email": req.email, "entity_id": entity_id}
    )

    # Commit the entity-page write, scoped to this one file — mirrors
    # entities.py::update_entity_decay exactly: parse/write happened inside
    # ensure_owner_entity, this router (already async) does the commit right
    # after, never ``git add -A``. Without this the page is left
    # untracked/dirty with no ``Cicada-Author`` trailer, and the next writer
    # to run ``git add -A`` sweeps it into ITS commit under the wrong
    # author — the exact G85-class smear CLAUDE.md documents by name, here
    # landing on the owner's own identity write instead of a decay batch.
    verb = "created" if created else "updated"
    message = git_service.build_commit_message(
        f"Set owner identity {date.today().isoformat()}",
        [f"entities/{entity_id}.md: {verb} (trigger: user/companion_app)"],
        authors=["user"],
    )
    await git_service.commit_paths(settings.memory_path, message, [f"entities/{entity_id}.md"])

    return OwnerSettingsResponse(
        name=name, handle=req.handle, email=req.email, observer=entity_id, entity_id=entity_id,
    )
