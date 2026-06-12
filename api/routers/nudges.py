# DEPRECATED: use /inbox. Thin projection over the unified inbox/ dir kept so
# the SwiftUI app and any external caller keep working mid-migration.
from fastapi import APIRouter, Depends, Response

from api.config import Settings, get_settings
from api.models.schemas import InboxResolveRequest, NudgeResolveRequest, NudgeResponse
from api.services import inbox_service

router = APIRouter()

_NUDGE_KINDS = {"decay", "conflict"}


@router.get("/nudges", response_model=list[NudgeResponse])
async def list_nudges(response: Response, settings: Settings = Depends(get_settings)):
    response.headers["Deprecation"] = "true"
    items = inbox_service.load_inbox(settings.memory_path)
    return [
        NudgeResponse(
            id=item.id,
            entity_name=item.entity_name,
            entity_id=item.entity_id,
            type=item.kind.value,
            short_description=item.title,
            full_context=item.body,
            options=item.options,
            created_date=item.created_date,
        )
        for item in items
        if item.kind.value in _NUDGE_KINDS
    ]


@router.post("/nudges/{nudge_id}/resolve")
async def resolve_nudge(
    nudge_id: str,
    request: NudgeResolveRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    response.headers["Deprecation"] = "true"
    result = await inbox_service.resolve(
        nudge_id,
        InboxResolveRequest(action=request.action, answer=request.answer),
        settings,
    )
    return {"status": result.get("status", "resolved"), "nudge_id": nudge_id}
