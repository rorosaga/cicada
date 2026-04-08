from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from api.config import Settings, get_settings
from api.models.schemas import NudgeResolveRequest, NudgeResponse
from api.services import git_service, markdown_parser

router = APIRouter()


def _load_nudges(memory_path: Path) -> list[NudgeResponse]:
    nudges_dir = memory_path / "nudges"
    results: list[NudgeResponse] = []
    for filepath in sorted(nudges_dir.glob("*.md")):
        parsed = markdown_parser.parse(filepath)
        fm = parsed.frontmatter
        results.append(
            NudgeResponse(
                id=filepath.stem,
                entity_name=fm.get("entity_name", ""),
                entity_id=fm.get("entity_id", ""),
                type=fm.get("type", "decay"),
                short_description=fm.get("short_description", ""),
                full_context=parsed.body,
                options=fm.get("options"),
                created_date=str(fm.get("created_date", "")),
            )
        )
    return results


@router.get("/nudges", response_model=list[NudgeResponse])
async def list_nudges(settings: Settings = Depends(get_settings)):
    return _load_nudges(settings.memory_path)


@router.post("/nudges/{nudge_id}/resolve")
async def resolve_nudge(
    nudge_id: str,
    request: NudgeResolveRequest,
    settings: Settings = Depends(get_settings),
):
    nudge_path = settings.memory_path / "nudges" / f"{nudge_id}.md"
    if not nudge_path.exists():
        raise HTTPException(404, f"Nudge {nudge_id} not found")

    parsed = markdown_parser.parse(nudge_path)
    entity_id = parsed.frontmatter.get("entity_id", "")
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"

    if request.action == "keep_active" and entity_path.exists():
        entity = markdown_parser.parse(entity_path)
        entity.frontmatter["status"] = "active"
        entity.frontmatter["confidence"] = max(entity.frontmatter.get("confidence", 0.5), 0.6)
        entity.frontmatter["last_referenced"] = str(date.today())
        markdown_parser.write(entity_path, entity.frontmatter, entity.body)
        nudge_path.unlink()

    elif request.action == "archive" and entity_path.exists():
        entity = markdown_parser.parse(entity_path)
        entity.frontmatter["status"] = "archived"
        markdown_parser.write(entity_path, entity.frontmatter, entity.body)
        nudge_path.unlink()

    elif request.action == "remind_later":
        new_date = date.today() + timedelta(days=7)
        parsed.frontmatter["created_date"] = str(new_date)
        markdown_parser.write(nudge_path, parsed.frontmatter, parsed.body)

    else:
        # Conflict resolution: apply selected option or free-text answer
        if entity_path.exists() and request.answer:
            entity = markdown_parser.parse(entity_path)
            entity.frontmatter["last_referenced"] = str(date.today())
            body = entity.body + f"\n\n{request.answer}"
            markdown_parser.write(entity_path, entity.frontmatter, body)
        nudge_path.unlink()

    await git_service.commit_resolution(settings.memory_path, entity_id, "nudge/resolved")
    return {"status": "resolved", "nudge_id": nudge_id}
