"""G141 PJ-1 — a project's timeline over HTTP (spec §10.1).

Both reads are fetched on demand, like the provenance reads (R-PJ7): neither is
a Store domain, so there is no `VersionVector` mapping and the ship-together
rule has nothing to pair. Both ETags fold `entities`, `episodes` and `inbox`
plus the machine zone's NAME and `PROJECT_SHAPE` — never today, never a viewer
zone — so a 304 holds across midnight and moves only when the bank or the Mac's
zone does. (The `inbox` component itself re-validates once a day while a
deferred item is pending — that item's return IS a content change.) The build
runs in the threadpool: it parses pages.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import ProjectsResponse, ProjectTimeline
from api.services import bank_index, handshake, project_timeline, sync_service, telemetry
from api.services.id_utils import resolve_entity_file

router = APIRouter()


def _tz() -> str:
    return handshake.local_timezone() or "UTC"


def _project_stem(memory_path, project_id: str) -> str:
    page = resolve_entity_file(memory_path, project_id)
    if page is None:
        raise HTTPException(404, f"No project {project_id!r}")
    fm = next((f.frontmatter for f in bank_index.files(memory_path, "entities") if f.stem == page.stem), {}) or {}
    if str(fm.get("type") or "") != "project" or str(fm.get("status") or "active") == "dropped":
        raise HTTPException(404, f"{page.stem!r} is not a project")
    return page.stem


@router.get("/projects", response_model=ProjectsResponse)
async def list_projects(request: Request, response: Response, settings: Settings = Depends(get_settings)):
    mp, tz = settings.memory_path, _tz()
    etag = sync_service.etag_for(mp, "entities", "episodes", "inbox",
                                 extra=f"projects|{project_timeline.PROJECT_SHAPE}|{tz}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    return await run_in_threadpool(project_timeline.list_projects, mp, tz_name=tz)


@router.get("/projects/{project_id}/timeline", response_model=ProjectTimeline)
async def get_project_timeline(project_id: str, request: Request, response: Response,
                               since: Optional[str] = None, settings: Settings = Depends(get_settings)):
    mp, tz = settings.memory_path, _tz()
    since_day = None
    if since:
        try:
            since_day = date.fromisoformat(since[:10]).isoformat()
        except ValueError:
            raise HTTPException(400, "since must be a date (YYYY-MM-DD)")
    stem = _project_stem(mp, project_id)
    etag = sync_service.etag_for(mp, "entities", "episodes", "inbox",
                                 extra=f"project|{stem}|{since_day or ''}|{project_timeline.PROJECT_SHAPE}|{tz}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    result = await run_in_threadpool(project_timeline.build, mp, stem, tz_name=tz, since=since_day)
    if result is None:
        raise HTTPException(404, f"{stem!r} is not a project")
    # A 200 is an open (a 304 revalidation is not): ids and an enum only (G124 R11).
    telemetry.record_read(stem, surface="project", bank=telemetry.bank_name(settings))
    return result
