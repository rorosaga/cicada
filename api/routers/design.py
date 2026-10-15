"""Design taste (owner, 2026-10-14) over HTTP — the board of looks the person likes.

Reads: ``GET /design`` (the board, newest first, with whether search by picture can run here), ``GET /design/{id}``
(one reference in full: the note, the snippets, the tokens) and ``GET /design/{id}/image`` (the screenshot, from the
bank). None is a Store domain: the app's ``LooksCache`` revalidates them with the ETag below (the ``design``
component, plus the image model's state) — no ``VersionVector`` mapping, so nothing has to ship beside it.

Writes: ``POST /design`` (a screenshot the app captured, or one dropped or pasted, with the page's link, their note
and any snippets they selected) and ``DELETE /design/{id}``. Each is committed alone, trigger ``user/companion_app``,
answers 409 while Sleep holds the pages (the write admission, G183) and 409 in a demo bank (a screenshot is capture:
``demo_guard``). The palette is read from the pixels **before** the admission is taken, so Sleep never waits on a
decode. **Looks v2:** an agent that saves through this door names itself (``author``, a harness id such as
``claude-code``; ``via=agent`` with no author is the generic ``agent``) — the commit is its, and its note shows as
"Noted by <agent>", never as the person's words. ``tokens`` carries the page's computed type and colour roles
(``design_tokens``), validated with bounds; a token out of bounds is dropped, never a failed save.

``POST /design/search`` takes words, an example picture, or both, and answers with the board re-ranked
(``design_index``): it writes only the derived index outside the bank. A POST so the words never reach an access log;
nothing here logs them.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from loguru import logger
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import CamelModel
from api.services import (demo_guard, design_index, design_refs, design_tokens, embedding_models, entity_picture,
                          git_service, sleep_cycle, sync_service, write_admission)
from api.services.sleep_refusal import SleepWriting

router = APIRouter()

TRIGGER = "user/companion_app"
BUSY = "Sleep is writing memory right now — try again in a moment."
_write_lock = write_admission.TransactionLock()


class DesignColour(CamelModel):
    hex: str
    share: float = 0.0
    role: str | None = None
    declared: bool = False


class DesignImage(CamelModel):
    url: str
    width: int = 0
    height: int = 0
    bytes: int = 0


class DesignSnippet(CamelModel):
    lang: str = "text"
    code: str


class DesignTypeRole(CamelModel):
    role: str
    family: str = ""
    generic: str | None = None
    size: float | None = None
    weight: int | None = None
    line_height: float | None = None
    letter_spacing: float | None = None
    color: str | None = None


class DesignColourRole(CamelModel):
    role: str
    hex: str
    #: ``page`` — the agent read it from the page's computed styles; ``pixels`` — Cicada read it from the screenshot.
    source: str = "pixels"


class DesignRefSummary(CamelModel):
    id: str
    title: str = ""
    url: str | None = None
    site: str | None = None
    captured: str = ""
    day: str = ""
    added_by: str = "user"
    added_by_kind: str = "user"
    via: str = "drop"
    image: DesignImage | None = None
    palette: list[DesignColour] = []
    look: list[str] = []
    fonts: list[str] = []
    tags: list[str] = []
    note_preview: str = ""
    entity: str | None = None
    note_by: str = "user"
    note_by_kind: str = "user"


class DesignRefModel(DesignRefSummary):
    note: str = ""
    snippets: list[DesignSnippet] = []
    tokens: dict = {}
    computed: dict = {}
    type_roles: list[DesignTypeRole] = []
    colour_roles: list[DesignColourRole] = []
    path: str = ""


class DesignVision(CamelModel):
    supported: bool = False
    installed: bool = False
    download_bytes: int = 0
    includes_text: bool = False   # the size covers the text encoder too (the Looks click fetches both)
    installing: bool = False
    step: str = ""
    error: str = ""


class DesignBoard(CamelModel):
    refs: list[DesignRefSummary]
    vision: DesignVision
    indexed_images: int = 0


class DesignHit(CamelModel):
    id: str
    score: float = 0.0
    legs: list[str] = []


class DesignSearchResult(CamelModel):
    results: list[DesignHit]
    mode: str
    missing: list[str] = []


def _colour_roles(ref: design_refs.Reference) -> list[DesignColourRole]:
    """Ground, ink, accent, wash: what the page's computed styles said, else what the pixels show."""
    given = (ref.computed or {}).get("colors") or {}
    out = []
    for role in design_tokens.COLOR_ROLES:
        if given.get(role):
            out.append(DesignColourRole(role=role, hex=given[role], source="page"))
            continue
        hit = next((c for c in ref.palette if c.get("role") == role), None)
        if hit is not None:
            out.append(DesignColourRole(role=role, hex=str(hit["hex"]), source="pixels"))
    return out


def _type_roles(ref: design_refs.Reference) -> list[DesignTypeRole]:
    types = (ref.computed or {}).get("type") or {}
    return [DesignTypeRole(role=role, family=str(t.get("family") or ""), generic=t.get("generic"),
                           size=t.get("size"), weight=t.get("weight"), line_height=t.get("line_height"),
                           letter_spacing=t.get("letter_spacing"), color=t.get("color"))
            for role in design_tokens.TYPE_ROLES if isinstance(t := types.get(role), dict)]


def _summary(ref: design_refs.Reference) -> DesignRefSummary:
    kind, _ = git_service.author_identity(ref.added_by)
    note_kind, _ = git_service.author_identity(ref.note_by)
    image = None
    if ref.image.get("sha256"):
        image = DesignImage(url=f"/design/{ref.id}/image?v={str(ref.image['sha256'])[:12]}",
                            width=int(ref.image.get("width") or 0), height=int(ref.image.get("height") or 0),
                            bytes=int(ref.image.get("bytes") or 0))
    note = " ".join(ref.note.split())
    return DesignRefSummary(
        id=ref.id, title=ref.title, url=ref.url, site=ref.site, captured=ref.captured, day=ref.day,
        added_by=ref.added_by, added_by_kind=kind, via=ref.via, image=image,
        palette=[DesignColour(hex=str(c["hex"]), share=float(c.get("share") or 0),
                              role=c.get("role") if c.get("role") in design_tokens.COLOR_ROLES else None,
                              declared=bool(c.get("declared"))) for c in ref.palette],
        look=ref.look, fonts=design_refs.fonts(ref), tags=ref.tags,
        note_preview=note[:160] + ("…" if len(note) > 160 else ""), entity=ref.entity,
        note_by=ref.note_by, note_by_kind="user" if ref.note_by == design_refs.USER else
        (note_kind if note_kind != "user" else "harness"))


def _full(ref: design_refs.Reference) -> DesignRefModel:
    return DesignRefModel(**_summary(ref).model_dump(by_alias=False), note=ref.note,
                          snippets=[DesignSnippet(**s) for s in ref.snippets], tokens=ref.tokens or {},
                          computed=ref.computed or {}, type_roles=_type_roles(ref), colour_roles=_colour_roles(ref),
                          path=ref.path)


def _vision() -> DesignVision:
    state = embedding_models.vision_status()
    job = embedding_models.JOB.snapshot()
    return DesignVision(**state, installing=job["state"] == "installing", step=job["step"],
                        error=job["error"] if job["state"] == "failed" else "")


def _etag(memory_path, *parts: str) -> str:
    vision = _vision()
    extra = "|".join(["design", design_refs.SHAPE, *parts, str(vision.installed), str(vision.installing),
                      vision.step, vision.error])
    return sync_service.etag_for(memory_path, "design", extra=extra)


@router.get("/design", response_model=DesignBoard)
async def design_board(request: Request, response: Response, settings: Settings = Depends(get_settings)):
    mp = settings.memory_path
    etag = await run_in_threadpool(_etag, mp, "board")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early

    def build() -> DesignBoard:
        refs = design_refs.list_refs(mp)
        return DesignBoard(refs=[_summary(r) for r in refs], vision=_vision(),
                           indexed_images=design_index.status(mp)["images"])

    return await run_in_threadpool(build)


@router.get("/design/{ref_id}", response_model=DesignRefModel)
async def design_ref(ref_id: str, request: Request, response: Response, settings: Settings = Depends(get_settings)):
    mp = settings.memory_path
    etag = await run_in_threadpool(_etag, mp, "ref", ref_id)
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    ref = await run_in_threadpool(design_refs.get_ref, mp, ref_id)
    if ref is None:
        raise HTTPException(404, "No such reference on your board.")
    return _full(ref)


@router.get("/design/{ref_id}/image")
async def design_image(ref_id: str, request: Request, settings: Settings = Depends(get_settings)):
    ref = await run_in_threadpool(design_refs.get_ref, settings.memory_path, ref_id)
    found = design_refs.image_file(settings.memory_path, ref) if ref is not None else None
    if found is None:
        raise HTTPException(404, "no screenshot for this reference")
    path, media_type = found
    data = await asyncio.to_thread(path.read_bytes)
    etag = '"' + entity_picture.sha12(data) + '"'
    headers = {"ETag": etag, "Cache-Control": "private, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type=media_type, headers=headers)


def _json_list(raw: str | None, what: str) -> list:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(400, f"The {what} couldn't be read.") from exc
    if not isinstance(value, list):
        raise HTTPException(400, f"The {what} couldn't be read.")
    return value


def _author(raw: str | None, via: str | None) -> str:
    """The author an upload names: the person by default; an agent only as a harness id Cicada knows (or ``agent``),
    so a commit trailer never carries free text. ``via=agent`` never writes as the person."""
    from api.services.source_overview import HARNESS_LABELS

    name = str(raw or "").strip().lower()
    if name and name != design_refs.USER and name != design_refs.AGENT and \
            (name not in HARNESS_LABELS or name == "unknown"):
        raise HTTPException(400, "Name the agent by its harness id (for example claude-code), or leave the author out.")
    return design_refs.resolve_author(name or design_refs.USER, via)


async def _commit(memory_path, paths: list[str], action: str, author: str = design_refs.USER) -> None:
    trigger = TRIGGER if author == design_refs.USER else "agent/rest_api"
    message = design_refs.commit_message(paths, action=action, subject="Design reference", trigger=trigger,
                                         day=datetime.now(timezone.utc).date().isoformat(), author=author)
    try:
        await git_service.commit_paths(memory_path, message, sorted(set(paths)))
    except Exception as exc:  # noqa: BLE001 — the write stands; a later writer's commit picks it up
        logger.warning(f"design commit skipped: {type(exc).__name__}")


@router.post("/design", response_model=DesignRefModel)
async def add_design_ref(image: UploadFile = File(...), url: str | None = Form(None), title: str | None = Form(None),
                         note: str | None = Form(None), snippets: str | None = Form(None),
                         tags: str | None = Form(None), via: str | None = Form(None),
                         author: str | None = Form(None), tokens: str | None = Form(None),
                         settings: Settings = Depends(get_settings)):
    mp = settings.memory_path
    if demo_guard.is_demo(mp):
        raise HTTPException(409, demo_guard.REFUSAL)
    data = await image.read(design_refs.MAX_IMAGE_BYTES + 1)
    try:
        design_refs.validate_image(data)
    except ValueError as exc:
        raise HTTPException(413 if len(data) > design_refs.MAX_IMAGE_BYTES else 400, str(exc)) from exc
    snippet_list, tag_list = _json_list(snippets, "snippets"), _json_list(tags, "tags")
    writer = _author(author, via)
    # Off the event loop, like the decode below; the value caps in design_tokens keep it linear anyway.
    computed, _problems = await asyncio.to_thread(design_tokens.clean, tokens)
    if tokens and not computed and _problems and _problems[0] in ("tokens are not JSON", "tokens are an object",
                                                                  "tokens are too large"):
        raise HTTPException(400, f"The tokens couldn't be read: {_problems[0]}.")
    declared = design_refs.declared_colours(snippet_list, computed)
    look = await asyncio.to_thread(design_refs.read_look, data, declared)   # the decode, before the admission

    async def store() -> DesignRefModel:
        async with _write_lock:
            result = await asyncio.to_thread(
                design_refs.add_ref, mp, image=data, url=url, title=title, note=note, snippets=snippet_list,
                tags=tag_list, via=via or "drop", author=writer, look=look, computed=computed)
            if result["action"] == "duplicate":
                raise HTTPException(409, result["error"])
            if result["action"] != "added":
                raise HTTPException(400, result.get("error") or "That couldn't be saved.")
            await _commit(mp, result["paths"], "created", author=result["ref"].added_by)
            return _full(result["ref"])

    out = await write_admission.run_admitted(mp, store, refuse=lambda: SleepWriting(BUSY))
    design_index.refresh_in_background(mp)
    return out


@router.delete("/design/{ref_id}")
@write_admission.route(refuse=lambda: SleepWriting(BUSY))
async def remove_design_ref(ref_id: str, settings: Settings = Depends(get_settings)):
    mp = settings.memory_path
    if demo_guard.is_demo(mp):
        raise HTTPException(409, demo_guard.REFUSAL)
    async with _write_lock:
        result = await asyncio.to_thread(design_refs.remove_ref, mp, ref_id, author=design_refs.USER)
        if result["action"] == "not_found":
            raise HTTPException(404, result["error"])
        if result["action"] != "removed":
            raise HTTPException(400, result.get("error") or "That couldn't be removed.")
        tracked = [p for p in result["paths"] if await git_service.is_tracked(mp, p)]
        if tracked:
            await _commit(mp, tracked, "deleted")
    return {"removed": ref_id}


@router.post("/design/search", response_model=DesignSearchResult)
async def search_design(query: str | None = Form(None), image: UploadFile | None = File(None),
                        settings: Settings = Depends(get_settings)):
    data = None
    if image is not None:
        data = await image.read(design_refs.MAX_IMAGE_BYTES + 1)
        if len(data) > design_refs.MAX_IMAGE_BYTES:
            raise HTTPException(413, "That picture is too large to search with.")
        if not data:
            data = None
    if not (query or "").strip() and data is None:
        raise HTTPException(400, "Search with some words or a picture.")
    # Never embed the board while Sleep runs (the rail): the search answers from the vectors already there.
    embed = sleep_cycle.get_sleep_state().status != "running"
    out = await asyncio.to_thread(design_index.search, settings.memory_path, query=query, image=data, embed=embed)
    return DesignSearchResult(results=[DesignHit(**r) for r in out["results"]], mode=out["mode"],
                              missing=out["missing"])
