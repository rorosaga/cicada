"""Repo-wide model/user attribution (backlog A2).

Surfaces, for each authoring agent (a model id, "user", or "unknown"), how much
of memory it wrote — parsed from ``Cicada-Author:`` commit trailers. This is the
distinctive "honest about which model authored each belief" view.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from api.config import Settings, get_settings
from api.models.schemas import ContributorCommitsResponse, ContributorsResponse
from api.services import git_service, sync_service

router = APIRouter()


@router.get("/contributors", response_model=ContributorsResponse)
async def get_contributors(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    etag = sync_service.etag_for(settings.memory_path, "git_head")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    contributors = await git_service.get_contributors(
        settings.memory_path, github_user=(getattr(settings, "github_user", "") or None)
    )
    return ContributorsResponse(contributors=contributors)


@router.get("/contributors/commits", response_model=ContributorCommitsResponse)
async def get_contributor_commits(
    author: str = Query(..., description="Model id, 'user', 'cicada', or 'unknown'"),
    limit: int = Query(50, ge=1, le=git_service.MAX_CONTRIBUTOR_COMMITS),
    settings: Settings = Depends(get_settings),
):
    """Recent commits by one authoring agent (G67 §2.2).

    ``author`` is a QUERY parameter, not a path segment: model ids contain
    slashes (``anthropic/claude-opus-4``) that would split a path. On demand
    only — no ETag and no ``Store`` domain, because this is a drill-down the
    user opens deliberately, not a snapshot the app keeps live.
    """
    author = (author or "").strip()
    if not author:
        raise HTTPException(400, "author is required")
    commits = await git_service.get_contributor_commits(
        settings.memory_path, author, limit=limit
    )
    return ContributorCommitsResponse(author=author, commits=commits)
