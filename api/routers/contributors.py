"""Repo-wide model/user attribution (backlog A2).

Surfaces, for each authoring agent (a model id, "user", or "unknown"), how much
of memory it wrote — parsed from ``Cicada-Author:`` commit trailers. This is the
distinctive "honest about which model authored each belief" view.
"""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from api.config import Settings, get_settings
from api.models.schemas import (
    CalendarDay,
    ContributorCalendar,
    ContributorCommitsResponse,
    ContributorsResponse,
    TopEntities,
    TopEntityRead,
    TopEntityWrite,
)
from api.services import consumption_stats, git_service, sync_service

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


def _utc_today() -> date:
    # The ledger's own clock — see api/routers/consumption.py::_utc_today.
    return datetime.now(timezone.utc).date()


@router.get("/contributors/calendar", response_model=ContributorCalendar)
async def get_contributor_calendar(
    request: Request,
    response: Response,
    author: str = Query(..., min_length=1, description="Model id, 'user', 'cicada', or 'unknown'"),
    weeks: int = Query(53, ge=1, le=106),
    settings: Settings = Depends(get_settings),
):
    """When this contributor wrote memory (G124 R14) — the GitHub-style
    calendar per model. Git only; the UTC date is part of the ETag because a
    rolling window moves at midnight with no commit to move ``git_head``."""
    today = _utc_today()
    etag = sync_service.etag_for(settings.memory_path, "git_head", extra=f"{author}:{weeks}:{today}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    days = await consumption_stats.contributor_calendar(
        settings.memory_path, author=author.strip(), weeks=weeks, today=today)
    return ContributorCalendar(author=author.strip(), days=[CalendarDay(**d) for d in days], weeks=weeks)


@router.get("/contributors/top-entities", response_model=TopEntities)
async def get_top_entities(
    request: Request,
    response: Response,
    limit: int = Query(10, ge=1, le=50),
    range_: str = Query("all", alias="range", pattern=r"^(all|month|\d{1,4}d)$"),
    settings: Settings = Depends(get_settings),
):
    """Most-written (git) and most-read (ledger) entity pages (G124).

    Two sources, one ETag: ``git_head`` for the writes, ``telemetry`` for the
    reads, the UTC date for the rolling range. Counts only — no cost, no
    tokens — by the 2026-09-03 ruling on the G124 row.
    """
    today = _utc_today()
    etag = sync_service.etag_for(
        settings.memory_path, "git_head", "telemetry", extra=f"{limit}:{range_}:{today}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    written, scanned = await git_service.top_written_entities(settings.memory_path, limit=limit)
    read = consumption_stats.top_read_entities(range_=range_, today=today, limit=limit)
    return TopEntities(
        written=[TopEntityWrite(**r) for r in written],
        read=[TopEntityRead(**r) for r in read],
        commits_scanned=scanned, range=range_,
    )
