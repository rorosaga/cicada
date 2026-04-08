from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from api.config import Settings, get_settings
from api.models.schemas import ClarificationResolveRequest, ClarificationResponse
from api.services import git_service, markdown_parser

router = APIRouter()


def _load_clarifications(memory_path: Path) -> list[ClarificationResponse]:
    clar_dir = memory_path / "clarifications"
    results: list[ClarificationResponse] = []
    for filepath in sorted(clar_dir.glob("*.md")):
        parsed = markdown_parser.parse(filepath)
        fm = parsed.frontmatter
        results.append(
            ClarificationResponse(
                id=filepath.stem,
                entity_mention=fm.get("entity_mention", ""),
                uncertainty_type=fm.get("uncertainty_type", ""),
                source_context=parsed.body,
                suggested_classification=fm.get("suggested_classification"),
                suggested_confidence=fm.get("suggested_confidence"),
                created_date=str(fm.get("created_date", "")),
            )
        )
    return results


@router.get("/clarifications", response_model=list[ClarificationResponse])
async def list_clarifications(settings: Settings = Depends(get_settings)):
    return _load_clarifications(settings.memory_path)


@router.post("/clarifications/{clarification_id}")
async def resolve_clarification(
    clarification_id: str,
    request: ClarificationResolveRequest,
    settings: Settings = Depends(get_settings),
):
    clar_path = settings.memory_path / "clarifications" / f"{clarification_id}.md"
    if not clar_path.exists():
        raise HTTPException(404, f"Clarification {clarification_id} not found")

    parsed = markdown_parser.parse(clar_path)
    entity_mention = parsed.frontmatter.get("entity_mention", "")
    entity_id = entity_mention.lower().replace(" ", "-")

    if request.action == "answer":
        # Create or update entity from the answer
        entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
        if entity_path.exists():
            entity = markdown_parser.parse(entity_path)
            entity.frontmatter["last_referenced"] = str(date.today())
            body = entity.body + f"\n\n{request.answer}"
            markdown_parser.write(entity_path, entity.frontmatter, body)
        else:
            frontmatter = {
                "name": entity_mention,
                "type": parsed.frontmatter.get("suggested_classification", "concept").split(" ")[0].lower(),
                "status": "active",
                "confidence": parsed.frontmatter.get("suggested_confidence", 0.5),
                "created": str(date.today()),
                "last_referenced": str(date.today()),
                "decay_rate": 0.05,
                "source_episodes": [],
                "tags": [],
                "related": [],
                "version": 1,
            }
            markdown_parser.write(entity_path, frontmatter, request.answer or "")
        clar_path.unlink()

    elif request.action == "dismiss":
        clar_path.unlink()

    elif request.action == "merge" and request.merge_target:
        # Add relation to merge target
        target_path = settings.memory_path / "entities" / f"{request.merge_target}.md"
        if target_path.exists():
            target = markdown_parser.parse(target_path)
            related = target.frontmatter.get("related", [])
            if entity_id not in related:
                related.append(entity_id)
                target.frontmatter["related"] = related
                markdown_parser.write(target_path, target.frontmatter, target.body)
        clar_path.unlink()

    elif request.action == "skip":
        return {"status": "skipped", "clarification_id": clarification_id}

    else:
        raise HTTPException(400, f"Unknown action: {request.action}")

    await git_service.commit_resolution(
        settings.memory_path, entity_id, "clarification/resolved"
    )
    return {"status": "resolved", "clarification_id": clarification_id}
