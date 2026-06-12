# DEPRECATED: use /inbox. Thin projection over the unified inbox/ dir kept so
# the SwiftUI app and any external caller keep working mid-migration.
from fastapi import APIRouter, Depends, Response

from api.config import Settings, get_settings
from api.models.schemas import (
    ClarificationResolveRequest,
    ClarificationResponse,
    InboxResolveRequest,
)
from api.services import inbox_service

router = APIRouter()

_CLARIFICATION_KINDS = {"clarification", "merge_suggestion"}


@router.get("/clarifications", response_model=list[ClarificationResponse])
async def list_clarifications(
    response: Response, settings: Settings = Depends(get_settings)
):
    response.headers["Deprecation"] = "true"
    items = inbox_service.load_inbox(settings.memory_path)
    return [
        ClarificationResponse(
            id=item.id,
            entity_mention=item.entity_name,
            uncertainty_type=item.uncertainty_type or "",
            source_context=item.body,
            suggested_classification=item.suggested_classification,
            suggested_confidence=item.suggested_confidence,
            created_date=item.created_date,
        )
        for item in items
        if item.kind.value in _CLARIFICATION_KINDS
    ]


@router.post("/clarifications/{clarification_id}")
async def resolve_clarification(
    clarification_id: str,
    request: ClarificationResolveRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    response.headers["Deprecation"] = "true"
    result = await inbox_service.resolve(
        clarification_id,
        InboxResolveRequest(
            action=request.action,
            answer=request.answer,
            merge_target=request.merge_target,
        ),
        settings,
    )
    status = result.get("status", "resolved")
    return {"status": status, "clarification_id": clarification_id}
