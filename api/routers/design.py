"""Design taste (owner, 2026-10-14) over HTTP — the board of looks the person likes.

Reads: ``GET /design`` (the board, newest first, with whether search by picture can run here), ``GET /design/{id}``
(one reference in full: the note, the snippets, the tokens, the type specimens), ``GET /design/{id}/image`` (the
screenshot, from the bank) and ``GET /design/{id}/type/{n}`` (type specimen ``n``, a transparent PNG from the bank). None is a Store domain: the app's ``LooksCache`` revalidates them with the ETag below (the ``design``
component, plus the image model's state) — no ``VersionVector`` mapping, so nothing has to ship beside it.

Writes: ``POST /design`` (a screenshot the app captured, or one dropped or pasted, with the page's link, their note
and any snippets they selected; ``entity`` the page it was dropped on), ``PUT /design/{id}/entity`` (put a look on the
page of the thing it shows, or take it off — owner 2026-10-20), ``PATCH /design/{id}`` (the person's own words on it) and ``DELETE /design/{id}``. A look on a page writes that
page's ``## Looks`` section in the same page-lock section as the record, and the two commit together. Each is committed alone, trigger ``user/companion_app``,
answers 409 while Sleep holds the pages (the write admission, G183) and 409 in a demo bank (a screenshot is capture:
``demo_guard``). The palette is read from the pixels **before** the admission is taken, so Sleep never waits on a
decode. **Looks v2:** an agent that saves through this door names itself (``author``, a harness id such as
``claude-code``; ``via=agent`` with no author is the generic ``agent``) — the commit is its, and its note shows as
"Noted by <agent>", never as the person's words. ``tokens`` carries the page's computed type and colour roles
(``design_tokens``), validated with bounds; a token out of bounds is dropped, never a failed save.

``GET /design/{id}/similar`` answers the looks most like one (its stored picture vector, else its look words).
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


class DesignSpecimenRole(CamelModel):
    role: str
    size: float | None = None
    weight: int | None = None


class DesignSpecimen(CamelModel):
    """One family the page renders (looks polish): its name, the roles and sizes it is used for, and — when the
    capture drew one — "Aa" in that family, as a transparent PNG the app tints (``image``). Without one the app sets
    "Aa" in the family's generic kind and says so."""
    family: str
    generic: str | None = None
    roles: list[DesignSpecimenRole] = []
    image: DesignImage | None = None


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
    specimens: list[DesignSpecimen] = []
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


def _specimens(ref: design_refs.Reference) -> list[DesignSpecimen]:
    """The specimen model (``design_tokens.specimens``) with each family's drawn "Aa", when the look keeps one."""
    drawn = {str(s.get("family") or "").lower(): (n, s) for s in ref.specimens
             if (n := design_refs.specimen_number(ref.id, s)) is not None}
    out = []
    for spec in design_tokens.specimens(ref.computed):
        image = None
        if (hit := drawn.get(spec["family"].lower())) is not None:
            n, stored = hit
            image = DesignImage(url=f"/design/{ref.id}/type/{n}?v={str(stored.get('sha256') or '')[:12]}",
                                width=int(stored.get("width") or 0), height=int(stored.get("height") or 0))
        out.append(DesignSpecimen(family=spec["family"], generic=spec.get("generic"), image=image,
                                  roles=[DesignSpecimenRole(**r) for r in spec["roles"]]))
    return out


def _summary(ref: design_refs.Reference, memory_path=None) -> DesignRefSummary:
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
        note_preview=note[:160] + ("…" if len(note) > 160 else ""),
        # The page the look shows (owner 2026-10-20) — only one that is there: a look whose page went is unattached.
        entity=ref.entity if memory_path is None or design_refs.page_exists(memory_path, ref.entity) else None,
        note_by=ref.note_by, note_by_kind="user" if ref.note_by == design_refs.USER else
        (note_kind if note_kind != "user" else "harness"))


def _full(ref: design_refs.Reference, memory_path=None) -> DesignRefModel:
    return DesignRefModel(**_summary(ref, memory_path).model_dump(by_alias=False), note=ref.note,
                          snippets=[DesignSnippet(**s) for s in ref.snippets], tokens=ref.tokens or {},
                          computed=ref.computed or {}, type_roles=_type_roles(ref), colour_roles=_colour_roles(ref),
                          specimens=_specimens(ref), path=ref.path)


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
        return DesignBoard(refs=[_summary(r, mp) for r in refs], vision=_vision(),
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
    return _full(ref, mp)


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


@router.get("/design/{ref_id}/type/{n}")
async def design_specimen(ref_id: str, n: int, request: Request, settings: Settings = Depends(get_settings)):
    ref = await run_in_threadpool(design_refs.get_ref, settings.memory_path, ref_id)
    path = design_refs.specimen_file(settings.memory_path, ref, n) if ref is not None else None
    if path is None:
        raise HTTPException(404, "no type specimen here")
    data = await asyncio.to_thread(path.read_bytes)
    etag = '"' + entity_picture.sha12(data) + '"'
    headers = {"ETag": etag, "Cache-Control": "private, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type="image/png", headers=headers)


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


def _commit_sync(memory_path, paths: list[str], action: str, author: str = design_refs.USER) -> None:
    """The write's own commit — called inside the same page-lock section as the write (a look on a page writes the
    page's ``## Looks`` section too), so no other writer's commit can carry it."""
    if not paths:
        return
    trigger = TRIGGER if author == design_refs.USER else "agent/rest_api"
    message = design_refs.commit_message(paths, action=action, subject="Design reference", trigger=trigger,
                                         day=datetime.now(timezone.utc).date().isoformat(), author=author)
    try:
        git_service.commit_paths_sync(memory_path, message, sorted(set(paths)))
    except Exception as exc:  # noqa: BLE001 — the write stands; a later writer's commit picks it up
        logger.warning(f"design commit skipped: {type(exc).__name__}")


def _tracked_sync(memory_path, paths: list[str]) -> list[str]:
    """The removed paths git knows (``git add`` refuses a pathspec that matches nothing) plus every file still there."""
    import subprocess

    out = []
    for rel in paths:
        if (memory_path / rel).exists():
            out.append(rel)
            continue
        try:
            done = subprocess.run(["git", "-C", str(memory_path), "ls-files", "--", rel], capture_output=True,
                                  text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.stdout.strip():
            out.append(rel)
    return out


@router.post("/design", response_model=DesignRefModel)
async def add_design_ref(image: UploadFile = File(...), url: str | None = Form(None), title: str | None = Form(None),
                         note: str | None = Form(None), snippets: str | None = Form(None),
                         tags: str | None = Form(None), via: str | None = Form(None),
                         author: str | None = Form(None), tokens: str | None = Form(None),
                         entity: str | None = Form(None), settings: Settings = Depends(get_settings)):
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
    subject = str(entity or "").strip() or None
    if subject is not None and not design_refs.page_exists(mp, subject):
        raise HTTPException(404, "That page isn't in memory, so the look can't go on it.")

    def write() -> dict:
        from api.services import page_lock

        with page_lock.page_lock(mp):
            result = design_refs.add_ref(
                mp, image=data, url=url, title=title, note=note, snippets=snippet_list, tags=tag_list,
                via=via or "drop", author=writer, look=look, computed=computed, entity=subject)
            if result["action"] == "added":
                _commit_sync(mp, [p for p in result["paths"] if p], "created", author=result["ref"].added_by)
            return result

    async def store() -> DesignRefModel:
        async with _write_lock:
            result = await asyncio.to_thread(write)
            if result["action"] == "duplicate":
                raise HTTPException(409, result["error"])
            if result["action"] != "added":
                raise HTTPException(400, result.get("error") or "That couldn't be saved.")
            return _full(result["ref"], mp)

    out = await write_admission.run_admitted(mp, store, refuse=lambda: SleepWriting(BUSY))
    design_index.refresh_in_background(mp)
    return out


@router.delete("/design/{ref_id}")
@write_admission.route(refuse=lambda: SleepWriting(BUSY))
async def remove_design_ref(ref_id: str, settings: Settings = Depends(get_settings)):
    mp = settings.memory_path
    if demo_guard.is_demo(mp):
        raise HTTPException(409, demo_guard.REFUSAL)
    def remove() -> dict:
        from api.services import page_lock

        with page_lock.page_lock(mp):
            result = design_refs.remove_ref(mp, ref_id, author=design_refs.USER)
            if result["action"] == "removed":
                _commit_sync(mp, _tracked_sync(mp, result["paths"]), "deleted")
            return result

    async with _write_lock:
        result = await asyncio.to_thread(remove)
        if result["action"] == "not_found":
            raise HTTPException(404, result["error"])
        if result["action"] != "removed":
            raise HTTPException(400, result.get("error") or "That couldn't be removed.")
    return {"removed": ref_id}


class EditBody(CamelModel):
    """The person's own words on a look: any of the three; a field left out is left as it is."""
    title: str | None = None
    url: str | None = None
    note: str | None = None


@router.patch("/design/{ref_id}", response_model=DesignRefModel)
@write_admission.route(refuse=lambda: SleepWriting(BUSY))
async def edit_design_ref(ref_id: str, body: EditBody, settings: Settings = Depends(get_settings)):
    """What the person liked, the look's name and its link (owner 2026-10-20) — committed alone, as the person, with
    the page the look is on when its ``## Looks`` line changes."""
    from api.services import page_lock

    mp = settings.memory_path
    if demo_guard.is_demo(mp):
        raise HTTPException(409, demo_guard.REFUSAL)
    given = body.model_dump(exclude_unset=True, by_alias=False)

    def run() -> dict:
        with page_lock.page_lock(mp):
            result = design_refs.update_ref(mp, ref_id, **given)
            if result.get("paths"):
                _commit_sync(mp, result["paths"], "updated")
            return result

    async with _write_lock:
        result = await asyncio.to_thread(run)
    if result["action"] == "not_found":
        raise HTTPException(404, result["error"])
    if result["action"] == "error":
        raise HTTPException(422, result["error"])
    if result["action"] == "updated":
        design_index.refresh_in_background(mp)
    return _full(result["ref"], mp)


class AttachBody(CamelModel):
    entity: str | None = None


@router.put("/design/{ref_id}/entity", response_model=DesignRefModel)
@write_admission.route(refuse=lambda: SleepWriting(BUSY))
async def attach_design_ref(ref_id: str, body: AttachBody, settings: Settings = Depends(get_settings)):
    """Put a look on the page of the thing it shows, or take it off (``entity`` null) — the person's move, committed
    alone with the record and both pages' ``## Looks`` sections (owner 2026-10-20)."""
    from api.services import page_lock

    mp = settings.memory_path
    if demo_guard.is_demo(mp):
        raise HTTPException(409, demo_guard.REFUSAL)
    def run() -> dict:
        with page_lock.page_lock(mp):
            result = design_refs.attach(mp, ref_id, body.entity, author=design_refs.USER)
            if result.get("paths"):
                _commit_sync(mp, result["paths"], "updated")
            return result

    async with _write_lock:
        result = await asyncio.to_thread(run)
        if result["action"] == "not_found":
            raise HTTPException(404, result["error"])
        if result["action"] == "error":
            raise HTTPException(422, result["error"])
    return _full(result["ref"], mp)


@router.get("/design/{ref_id}/similar", response_model=DesignSearchResult)
async def similar_design(ref_id: str, settings: Settings = Depends(get_settings)):
    """Looks like this one (its stored picture vector, else its look words), itself left out."""
    if design_refs.get_ref(settings.memory_path, ref_id) is None:
        raise HTTPException(404, "No such reference on your board.")
    embed = sleep_cycle.get_sleep_state().status != "running"
    out = await asyncio.to_thread(design_index.similar, settings.memory_path, ref_id, embed=embed)
    return DesignSearchResult(results=[DesignHit(**r) for r in out["results"]], mode=out["mode"],
                              missing=out["missing"])


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
