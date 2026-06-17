"""Repo-wide model/user attribution (backlog A2).

Surfaces, for each authoring agent (a model id, "user", or "unknown"), how much
of memory it wrote — parsed from ``Cicada-Author:`` commit trailers. This is the
distinctive "honest about which model authored each belief" view.
"""

from fastapi import APIRouter, Depends

from api.config import Settings, get_settings
from api.models.schemas import ContributorsResponse
from api.services import git_service

router = APIRouter()


@router.get("/contributors", response_model=ContributorsResponse)
async def get_contributors(
    settings: Settings = Depends(get_settings),
):
    contributors = await git_service.get_contributors(
        settings.memory_path, github_user=(getattr(settings, "github_user", "") or None)
    )
    return ContributorsResponse(contributors=contributors)
