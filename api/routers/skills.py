"""G138 — Settings → Skills reads this. No write endpoint: the app runs an
agent's own installer after consent, and writes only Cicada's own bundles
itself (R-O26). No ETag: not a Store domain, and a few isfile() calls."""
from __future__ import annotations

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from api.models.skill_schemas import RecommendedSkillsResponse
from api.services import skill_catalog

router = APIRouter()


@router.get("/skills/recommended", response_model=RecommendedSkillsResponse)
async def recommended_skills() -> RecommendedSkillsResponse:
    payload = await run_in_threadpool(skill_catalog.recommended)
    return RecommendedSkillsResponse.model_validate(payload)
