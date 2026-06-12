from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.config import Settings, get_settings
from api.models.schemas import InboxItem, InboxResolveRequest
from api.services import inbox_service

router = APIRouter()


@router.get("/inbox", response_model=list[InboxItem])
async def list_inbox(
    kind: Optional[str] = Query(None),
    settings: Settings = Depends(get_settings),
):
    items = inbox_service.load_inbox(settings.memory_path)
    if kind:
        wanted = {k.strip() for k in kind.split(",") if k.strip()}
        items = [i for i in items if i.kind.value in wanted]
    return items


@router.post("/inbox/{item_id}/resolve")
async def resolve_inbox(
    item_id: str,
    request: InboxResolveRequest,
    settings: Settings = Depends(get_settings),
):
    return await inbox_service.resolve(item_id, request, settings)
