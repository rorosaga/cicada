"""\"Keep as a page\" on a saved post (G246, ruling 81; ``keep_as_page``): the person's one click that gives a post drawn
as a row a page of its own, and the way back. Its own module so the Sources router stays untouched while it is edited
elsewhere; the paths are the Sources family's (``/sources/keep-as-page``)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import CamelModel
from api.routers.capture import refuse_capture_into_demo
from api.services import keep_as_page, write_admission
from api.services.sleep_refusal import SleepWriting

router = APIRouter()

_DEMO_GATE = [Depends(refuse_capture_into_demo)]

#: A click that finds Sleep holding the pages.
KEEP_BUSY = "Sleep is updating your memory — that wasn't kept. Try again in a moment."


class KeepState(CamelModel):
    """What the app may draw for a saved link. ``state``: ``none`` (no control), ``row`` ("Keep as a page"), ``kept``
    ("Back to a row" when ``canUndo``), ``page`` (another reason holds its page: no control)."""

    state: str = "none"
    can_undo: bool = False
    #: Sign ids (``saved_posts.SIGNS``) other than the person's own click that hold the page; never a title.
    because_of: list[str] = []
    media_entity_id: str = ""


class KeepRequest(CamelModel):
    #: The saved link. A row of a list that holds no link names its own page as ``entity`` instead (one of the two).
    url: str = Field("", max_length=4000)
    entity: str = Field("", max_length=200)
    #: ``true`` keeps the post as a page; ``false`` sends it back to a row.
    kept: bool = True


class KeepResult(KeepState):
    #: ``kept``, ``undone`` or ``unchanged`` (already so, or a work that keeps its page anyway).
    status: str = "unchanged"
    episode_id: str = ""


@router.get("/sources/keep-as-page", response_model=KeepState)
async def keep_state(url: str = Query("", max_length=4000), entity: str = Query("", max_length=200),
                     settings: Settings = Depends(get_settings)) -> KeepState:
    """What a saved link's card may offer: ``none`` for everything but a post drawn as a row (or kept by the person's
    click), and for every link while the posts-as-rows switch is off (``saved_posts.HIDE_POSTS``). Read-only. The link
    is ``url``, or ``entity`` for a row of a list (its own page id); 422 when neither is given."""
    if not url.strip() and not entity.strip():
        raise HTTPException(status_code=422, detail="Give the saved link or the row's page.")
    found = await run_in_threadpool(keep_as_page.offer, settings.memory_path, url, entity)
    return KeepState.model_validate({k: v for k, v in found.items() if k != "episode_id"})


@router.post("/sources/keep-as-page", response_model=KeepResult, dependencies=_DEMO_GATE)
async def keep_as_page_route(request: KeepRequest, settings: Settings = Depends(get_settings)) -> KeepResult:
    """Give a saved post a page of its own for good (``kept: true``, the default), or send it back to a row
    (``kept: false``, only while nothing else has earned it a page: 409 otherwise; ``GET`` names what does in ``becauseOf``).
    One stamp on the post's own save, under the episode lock, committed alone as the person (``Cicada-Author: user``);
    the body and the queue are untouched, so it costs no model read. 404 for a link not saved or a save with no page,
    409 in a demo bank or while Sleep holds the pages (this one waits Sleep's window out, never writes through it). A
    page that is no post already has its page: ``status: unchanged``."""
    memory_path = settings.memory_path
    if not request.url.strip() and not request.entity.strip():
        raise HTTPException(status_code=422, detail="Give the saved link or the row's page.")

    async def write() -> dict:
        result = await run_in_threadpool(
            lambda: keep_as_page.keep(memory_path, url=request.url, kept=request.kept, entity=request.entity))
        if result["paths"]:
            from api.services import git_service

            try:
                await git_service.commit_paths(memory_path, keep_as_page.commit_message(result["paths"], request.kept),
                                               result["paths"])
            except Exception as e:  # noqa: BLE001 — a non-git bank (tests) keeps the stamp
                logger.warning(f"keep-as-page commit failed: {type(e).__name__}: {e}")
        return result

    try:
        result = await write_admission.run_admitted(memory_path, write, refuse=lambda: SleepWriting(KEEP_BUSY))
    except keep_as_page.KeepError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return KeepResult.model_validate({k: v for k, v in result.items() if k != "paths"})
