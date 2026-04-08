from fastapi import APIRouter, Depends, HTTPException

from api.config import Settings, get_settings
from api.models.schemas import EntityHistoryEntry
from api.services import git_service

router = APIRouter()


@router.get("/entities/{entity_id}/history", response_model=list[EntityHistoryEntry])
async def get_entity_history(
    entity_id: str,
    settings: Settings = Depends(get_settings),
):
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")

    return await git_service.get_entity_history(entity_id, settings.memory_path)
