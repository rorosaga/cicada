"""G117 — the owner's identity: one name, resolved into the observer every
user-stated claim carries (see `owner_identity.resolve_observer`) and into
the one entity page `GET /graph` marks `isOwner: true`.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from api.config import Settings, get_settings
from api.models.schemas import OwnerSettingsResponse, OwnerUpdateRequest, PageEditorsResponse, PageEditorsUpdate
from api.services import git_service, owner_identity, page_editors, write_admission
from api.services.sleep_refusal import SleepWriting

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
# The owner's page is one Stage 5 rewrites: admitted like every page writer (G183 round 1), held through its commit.
@write_admission.route(refuse=lambda: SleepWriting("Sleep is updating your memory — try again in a moment."))
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


# --- G198: the agents the person lets edit a page directly ------------------------------------------------------------


@router.get("/editors", response_model=PageEditorsResponse)
async def get_editors() -> PageEditorsResponse:
    """Which harnesses may edit a page directly (``page_editors``); every other agent's edit waits in the inbox."""
    return PageEditorsResponse(**page_editors.snapshot())


@router.put("/editors", response_model=PageEditorsResponse)
async def put_editors(update: PageEditorsUpdate) -> PageEditorsResponse:
    """A patch ``{trusted: {harness: bool}}``. Writes ``$CICADA_HOME/editors.json`` only — nothing in the bank. Only
    the app's Settings calls this; no MCP tool or agent-shell command can."""
    try:
        return PageEditorsResponse(**page_editors.update(update.trusted))
    except page_editors.EditorsError as exc:
        raise HTTPException(400, str(exc)) from exc
