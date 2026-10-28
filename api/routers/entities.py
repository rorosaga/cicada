import asyncio
import hashlib
import re
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import (
    EntityRelevance,
    PageBlameResponse,
    SourcesOverview,
    ContextEpisodeExcerpt,
    ContextNeighbor,
    EntityContextResponse,
    EntityBands,
    EntityDecay,
    EntityDecayUpdate,
    EntityDiff,
    EntityHistoryEntry,
    EntityMedia,
    EntityPictureResponse,
    EntityReadRequest,
    EntityRawResponse,
    EntityReadResponse,
    EntityResponse,
    EntitySource,
    EntitySourceChange,
    EntitySourceCreate,
    EntitySourceList,
    LocationListing,
    SourceRefreshRequest,
    PageEditRequest,
    PageEditResponse,
    PageBlocks,
    PageCitationDetail,
    PageLinksResponse,
    PaperDetailResponse,
    PictureInputsModel,
    RepoContext,
    RepoContextList,
    RepoDeclaration,
    RepoDeclarationList,
    RepoInput,
    RepoObservedRequest,
    RepoUpdateRequest,
    VideoChapter,
)
from api.services import (
    page_relevance,
    bank_index,
    claims_ledger,
    page_blocks,
    decay_policy,
    decay_tuning,
    entity_bands,
    entity_picture,
    episode_time,
    fact_sources,
    git_service,
    local_refs,
    logo_service,
    markdown_parser,
    media_preview,
    page_lock,
    person_photo,
    quiet_pages,
    repo_context,
    repo_observations,
    source_refresh,
    sync_service,
    telemetry,
    write_admission,
)
from api.services.claims import claims_block_start, served_prose, strip_claims_block
from api.services.hub_builder import _one_line_summary
from api.services.id_utils import build_name_index, resolve_entity_id
from api.services.wikilink_resolver import extract_wikilinks
from api.services.sleep_refusal import SleepWriting

router = APIRouter()

#: F4 — above this a page's ``raw_markdown`` stops at its first claims fence (``raw_omitted``); the Source view and
#: Copy ask ``GET /entities/{id}/raw`` for the whole file. Every page but an owner-sized one is far below it (the largest others measured
#: ~70 KB); the owner's is ~2.6 MB, 96% of it the claims fence the card already reads from ``/claims``.
RAW_INLINE_MAX_BYTES = 256 * 1024
#: Owner page, 2026-10-14: a page whose claims live partly in its ledger, or whose fence alone is over this, withholds
#: the fence too — the card reads claims from `/claims`, and the fence was the largest machine block left in the card.
RAW_INLINE_FENCE_MAX_CHARS = 16 * 1024

# G59: bound concurrent first-fetches so opening a graph full of new companies
# can't fan out into dozens of simultaneous outbound requests.
_LOGO_FETCH_SEMAPHORE = asyncio.Semaphore(4)

_LOGO_MEDIA_TYPES = {
    "png": "image/png", "jpg": "image/jpeg", "gif": "image/gif",
    "webp": "image/webp", "svg": "image/svg+xml", "ico": "image/x-icon",
}


@router.get("/entities/{entity_id}", response_model=EntityResponse)
async def get_entity(
    entity_id: str,
    settings: Settings = Depends(get_settings),
    request: Request = None,
    response: Response = None,
):
    """Get full entity data including markdown content and history.

    Vision item 5 (2026-10-28): with its ``blocks`` (``page_blocks``) and an ETag over every input the card reads
    (``page_blocks.card_etag``), checked before the page is parsed or its history read — a held card answers 304 at
    the cost of a few stats. On demand, not a Store domain: the app's ``EntityCardCache`` holds the answer by bank and
    id and revalidates it on every open."""
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    # `request`/`response` are None only for an in-process caller (tests, the CLI's twin): no revalidation then.
    card = await run_in_threadpool(_card_read, settings, entity_id, entity_path,
                                   request.headers.get("if-none-match") if request is not None else None)
    if response is not None:
        response.headers["ETag"] = card["etag"]
    if card.get("not_modified"):
        return Response(status_code=304, headers={"ETag": card["etag"]})
    history, history_truncated = await git_service.entity_history(entity_id, settings.memory_path)
    blocks = card.pop("blocks")
    blocks["history"] = page_blocks.history(history, history_truncated)
    if blocks["history"] is not None:
        blocks["order"].append("history")
    card.pop("etag")
    return EntityResponse(**card, history=history, history_truncated=history_truncated, blocks=PageBlocks(**blocks))


def _card_read(settings: Settings, entity_id: str, entity_path: Path, if_none_match: str | None) -> dict:
    """Everything the card reads but its history, in one worker thread under one shared directory scan (the ETag's
    fingerprints and the relevance line's name index list ``entities/`` and ``episodes/`` once between them)."""
    from api.services.claims import parse_claims

    memory_path = settings.memory_path
    alpha, floor = decay_policy.spacing_params(settings)
    with bank_index.shared_scans():
        etag = page_blocks.card_etag(memory_path, entity_id, extra=f"{alpha}|{floor}")
        if if_none_match == etag:
            return {"etag": etag, "not_modified": True}
        # The page file alone: the card shows prose and reads claims from `/claims`, so an owner-sized page's ledger
        # (`claims_ledger`) is never opened here.
        parsed = markdown_parser.parse(entity_path, ledger=False)
        fm = parsed.frontmatter
        decay_class, decay_rate = decay_policy.resolve(fm)
        # G147 — the pace the decay pass actually charges, from the SAME function
        # (`decay_policy.effective`, plan R-FD11), so the card can never describe a
        # pace Sleep does not charge. Read time only; nothing is stored.
        effective = decay_policy.effective(
            fm, alpha=alpha, floor=floor, tuning=decay_tuning.load(memory_path),
            # Only this page's conversations are read (a full episode scan was most of a cold open's time).
            untimed=episode_time.untimed_among(memory_path, decay_policy._as_list(fm.get("source_episodes"))),
        )
        # C11 (G146) — the page's picture, resolved at read like everything else on this card (plan R-PE5).
        page_stat = entity_path.stat()
        picture, picture_inputs = entity_picture.resolve_page(
            memory_path, entity_id, fm, parsed.body, page_mtime=page_stat.st_mtime)
        raw = entity_path.read_text(encoding="utf-8")
        raw_omitted = False
        fence = claims_block_start(raw)
        big_fence = page_stat.st_size > RAW_INLINE_MAX_BYTES or claims_ledger.STAMP in fm \
            or (fence is not None and len(raw) - fence > RAW_INLINE_FENCE_MAX_CHARS)
        if claims_ledger.STAMP in fm and (split := markdown_parser.split_frontmatter(raw)) is not None:
            # A hub page (its claims partly in its ledger): the frontmatter alone — every frontmatter reader (a
            # location's lat/lon, a media block) keeps its input, the prose is `markdown_content` already, and Source
            # and Copy read `/raw` for the file (owner page, 2026-10-14: the prose twice was a third of a 490 KB card).
            raw, raw_omitted = raw[:len(raw) - len(split[1])], True
        elif big_fence and fence is not None:
            # Review r1 #4: withhold only the fence. The frontmatter and prose stay verbatim, so every frontmatter
            # reader (a location's declared lat/lon, a media block) keeps its input; Source and Copy read `/raw`.
            raw, raw_omitted = raw[:fence], True
        try:
            claims = parse_claims(parsed.body or "")
        except Exception:  # noqa: BLE001 — an unreadable fence reads as a page with no claims
            claims = []
        relevance = page_relevance.for_page(memory_path, entity_id, fm=fm, body=parsed.body, claims=claims).to_dict()
        blocks = page_blocks.build(memory_path, entity_id, fm=fm, claims=claims, relevance=relevance,
                                   body=parsed.body or "")
        return {
            "etag": etag,
            "blocks": blocks,
            "id": entity_id,
            "name": fm.get("name", entity_id.replace("-", " ").title()),
            "type": fm.get("type", "concept"),
            "status": fm.get("status", "active"),
            "confidence": fm.get("confidence", 0.5),
            "created": str(fm.get("created", "")),
            "last_referenced": str(fm.get("last_referenced", "")),
            "decay_rate": decay_rate,
            "decay_class": decay_class,
            "source_episodes": fm.get("source_episodes", []),
            "tags": fm.get("tags", []),
            "related": fm.get("related", []),
            "version": fm.get("version", 1),
            # F4: prose only — the fence is machine data the card reads from `/claims`, and on the owner's page it was
            # 2.5 MB shipped twice per open.
            "markdown_content": served_prose(parsed.body)[0],
            "raw_markdown": raw,
            "raw_omitted": raw_omitted,
            "media": _build_media_block(fm, parsed.body, entity_id=entity_id),
            "is_owner": bool(fm.get("owner")),
            "decay": EntityDecay(
                decay_class=effective.decay_class,
                effective_rate_per_week=round(effective.rate, 6),
                mention_weeks=effective.mention_weeks,
            ),
            # G180 parity: the card's bands from the backend, the charged rate above being the pace's one input.
            "bands": EntityBands(**entity_bands.bands(confidence=fm.get("confidence", 0.5),
                                                      rate_per_week=round(effective.rate, 6),
                                                      last_referenced=str(fm.get("last_referenced", "")),
                                                      today=date.today())),
            "picture": picture.url,
            "picture_source": picture.source,
            "picture_inputs": PictureInputsModel(**picture_inputs.to_fields()),
            "quiet": quiet_pages.page_is_quiet(memory_path, entity_id),
            "relevance": EntityRelevance(**relevance),
        }


@router.post("/entities/{entity_id}/web-context")
async def look_up_context(entity_id: str, settings: Settings = Depends(get_settings)):
    """Owner ruling 44 (G121) — "go deeper" on this one page: a deep web lookup now, by the person's click (or their
    agent through the API). The same public test (a private person's name is never sent anywhere), pinned queries,
    citations, protection of the person's own words and undo ("Settled by a check") as Sleep's light context; plan
    only, never a metered key. Not behind the connector switch: a click never is. 404 for no such page, 409 while Sleep
    holds the pages."""
    from api.services import web_context

    if not (settings.memory_path / "entities" / f"{entity_id}.md").exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    return await web_context.deeper(settings.memory_path, settings, entity_id)


@router.get("/entities/{entity_id}/raw", response_model=EntityRawResponse)
async def get_entity_raw(entity_id: str, settings: Settings = Depends(get_settings)):
    """F4 — the page verbatim (frontmatter, prose and claims fence), for the Source view and Copy when
    ``GET /entities/{id}`` left ``raw_markdown`` out (``raw_omitted``). Read on demand only; not a Store domain."""
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    text = await run_in_threadpool(entity_path.read_text, encoding="utf-8")
    return EntityRawResponse(id=entity_id, raw_markdown=text)


@router.post("/entities/{entity_id}/read", response_model=EntityReadResponse)
async def record_entity_read(
    entity_id: str,
    body: EntityReadRequest,
    settings: Settings = Depends(get_settings),
):
    """The app opened this entity's card (G124 R11) — one ids-only ``read``
    ledger event. 404 for a page that does not exist so a stray id can never
    seed the most-read list. Nothing is written to the bank; nothing here can
    fail the card open (``telemetry.record`` never raises)."""
    if not (settings.memory_path / "entities" / f"{entity_id}.md").is_file():
        raise HTTPException(status_code=404, detail="Entity not found")
    telemetry.record_read(entity_id, surface=body.surface, bank=telemetry.bank_name(settings))
    return EntityReadResponse(recorded=telemetry.enabled())


@router.get("/entities/{entity_id}/logo")
async def get_entity_logo(
    entity_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """The entity's logo as an image (G59).

    404 means "no logo" — no resolvable domain, or the fetch ladder came up
    empty — and the app draws its monogram fallback. The fast path (no
    semaphore, no ``ensure_logo`` call at all) only applies when there's a
    fresh cache entry AND the page hasn't changed since it was fetched — an
    edited page must still go through ``ensure_logo`` to re-resolve, or this
    endpoint would keep painting a stale (or, per M2, a since-deleted) domain
    for up to 30 days after every edit, same as the router-less callers
    already did. The first request that actually needs to touch the network
    is bounded by a semaphore of 4; a re-resolve that lands on the same
    domain (M1) or a failed revalidation (kept, not deleted) never reaches the
    network at all. ``GET /graph`` never comes through here: it reads the
    cache index only.
    """
    memory_path = settings.memory_path
    entity_file = memory_path / "entities" / f"{entity_id}.md"
    if not entity_file.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")

    bank = logo_service.bank_name(memory_path)
    entry = logo_service.read_meta(bank).get(entity_id)
    path = logo_service.cached_path(bank, entity_id)
    if path is None or logo_service.page_edited_since_fetch(entity_file, entry):
        async with _LOGO_FETCH_SEMAPHORE:
            path = await logo_service.ensure_logo(memory_path, entity_id)
    if path is None or not path.exists():
        raise HTTPException(404, "no logo for this entity")

    stat = path.stat()
    etag = '"' + hashlib.sha1(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()[:16] + '"'
    headers = {"ETag": etag, "Cache-Control": "max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)

    media_type = _LOGO_MEDIA_TYPES.get(path.suffix.lstrip("."), "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers=headers)


_PREVIEW_SEMAPHORE = asyncio.Semaphore(4)


@router.get("/entities/{entity_id}/preview")
async def get_entity_preview(entity_id: str, request: Request, settings: Settings = Depends(get_settings)):
    """A media page's own picture — the saved page's image, a provider's thumbnail, a YouTube still or a saved PDF's
    first page (`media_preview`) — served from Cicada's store outside the bank. The first request fetches it once
    (under the picture-fetch gate, the ToS rail and `net_guard`); every later one is the stored copy, so a dead link
    keeps its card. 404 means "no preview" and the app draws its placeholder. The `v=` the wire adds is the source's
    key and is only for the app's caches. `GET /graph` never comes through here."""
    memory_path = settings.memory_path
    if not (memory_path / "entities" / f"{entity_id}.md").is_file():
        raise HTTPException(404, f"Entity {entity_id} not found")
    async with _PREVIEW_SEMAPHORE:
        path = await media_preview.ensure_preview(memory_path, entity_id)
    if path is None or not path.is_file():
        raise HTTPException(404, "no preview for this entity")
    data = await asyncio.to_thread(path.read_bytes)
    etag = '"' + entity_picture.sha12(data) + '"'
    headers = {"ETag": etag, "Cache-Control": "private, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    media_type = media_preview.MEDIA_TYPES.get(path.suffix.lstrip("."), "application/octet-stream")
    return Response(content=data, media_type=media_type, headers=headers)


PICTURE_BUSY = "Sleep is updating your memory — try the picture again in a moment."
#: One picture write at a time in this process (`projects._write_lock`'s reason): an upload and a quick "Use initials"
#: would otherwise both read the page, and the second rewrite — or its `_drop_uploads` — would land between the first's
#: write and its commit, leaving that commit to stage a file that is already gone.
_PICTURE_LOCK = write_admission.TransactionLock()   # taken inside admitted transactions (writer loop)


SOURCE_BUSY = "Sleep is updating your memory — try the source change again in a moment."


PAGE_BUSY = "Sleep is updating your memory — try again in a moment."


def _admits(busy: str):
    """The route's write admission (G183): 409 with ``busy`` when Sleep holds the pages, asked once the hold is taken
    and held through the route's write and its commit — so a window cannot open between them. The person's source,
    picture, decay-class and repo-link writes (G61 S3-a, G146 R-PE8, G177/G183(a)): a frontmatter rewrite between
    Sleep's read and its commit would be lost or swept into the cycle's commit under a model's name."""
    return write_admission.route(refuse=lambda: SleepWriting(busy))


def _rewrite_page_and_commit(memory_path: Path, entity_id: str, mutate, message: str) -> dict:
    """One page's frontmatter rewrite and its commit as ONE page-lock section, in a worker thread (G183(a)): read,
    ``mutate(frontmatter)``, write, then the scoped synchronous commit — so no other page writer (an agent's claim, a
    dedup merge) can take the person's change into its own commit between the write and the commit. Nothing here is
    awaited, so the thread-re-entrant lock never spans the event loop. An edit already on the page is committed apart
    first, unauthored (``commit_touched_sync``'s ``before`` — the inbox's P1-3 mechanism). Returns the frontmatter."""
    rel = f"entities/{entity_id}.md"
    page = memory_path / rel
    with page_lock.page_lock(memory_path):   # under the route's admission (`_admits`): no window opens here
        if not page.exists():
            raise HTTPException(404, f"Entity {entity_id} not found")
        tracked = (memory_path / ".git").exists()
        before = None
        if tracked:
            before = {rel: page.read_bytes()} if rel in git_service.dirty_paths_sync(memory_path, rel) else {}
        parsed = markdown_parser.parse(page)
        fm = parsed.frontmatter
        mutate(fm)
        markdown_parser.write(page, fm, parsed.body)
        if tracked:
            git_service.commit_touched_sync(memory_path, message, [rel], before=before)
    return fm


def _entity_page(settings: Settings, entity_id: str) -> Path:
    page = settings.memory_path / "entities" / f"{entity_id}.md"
    if not page.is_file():
        raise HTTPException(404, f"Entity {entity_id} not found")
    return page


def _picture_payload(memory_path: Path, entity_id: str) -> EntityPictureResponse:
    page = memory_path / "entities" / f"{entity_id}.md"
    parsed = markdown_parser.parse(page)
    resolved, inputs = entity_picture.resolve_page(memory_path, entity_id, parsed.frontmatter, parsed.body,
                                                   page_mtime=page.stat().st_mtime)
    return EntityPictureResponse(entity_id=entity_id, picture=resolved.url, picture_source=resolved.source,
                                 picture_inputs=PictureInputsModel(**inputs.to_fields()))


@router.get("/entities/{entity_id}/picture")
async def get_entity_picture(entity_id: str, request: Request, settings: Settings = Depends(get_settings)):
    """C11 — the page's uploaded or Contacts picture (G146). 404 means neither exists (a logo is `/logo`'s, a thumbnail
    the provider's). The `v=` query the wire adds is the bytes' own hash and is only for the app's caches."""
    page = _entity_page(settings, entity_id)
    found = entity_picture.picture_file(settings.memory_path, entity_id, markdown_parser.parse(page).frontmatter)
    if found is None:
        raise HTTPException(404, "no picture for this entity")
    path, media_type = found
    data = path.read_bytes()
    etag = '"' + entity_picture.sha12(data) + '"'
    headers = {"ETag": etag, "Cache-Control": "private, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type=media_type, headers=headers)


#: G159 (2026-10-09) — at most two people's public-profile lookups at once (`_LOGO_FETCH_SEMAPHORE`'s reason).
_PHOTO_FETCH_SEMAPHORE = asyncio.Semaphore(2)


@router.get("/entities/{entity_id}/photo")
async def get_entity_photo(entity_id: str, request: Request, settings: Settings = Depends(get_settings)):
    """G159 amendment — a person's public-profile photo, fetched ONCE on demand from an identifier already on the page
    (`person_photo`), then served from the copy outside the bank. 404 means none: no identifier, a remembered miss,
    a gate off, or the person's own choice or Contacts photo outranks it. `GET /graph` never comes through here."""
    _entity_page(settings, entity_id)
    async with _PHOTO_FETCH_SEMAPHORE:
        path = await person_photo.ensure_photo(settings.memory_path, entity_id)
    if path is None or not path.is_file():
        raise HTTPException(404, "no photo for this person")
    data = path.read_bytes()
    etag = '"' + entity_picture.sha12(data) + '"'
    headers = {"ETag": etag, "Cache-Control": "private, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type=person_photo.MEDIA_TYPES[path.suffix.lstrip(".")], headers=headers)


@router.post("/entities/{entity_id}/picture", response_model=EntityPictureResponse)
@_admits(PICTURE_BUSY)
async def set_entity_picture(entity_id: str, file: UploadFile, settings: Settings = Depends(get_settings)):
    """C11 — the person's own picture for this page (G146; round-4 decision 9). Kept in the bank at
    `assets/pictures/<id>.<png|jpg>` and committed alone as `Cicada-Author: user` (plan R-PE1, R-PE8). The app sends it
    already shrunk; the server only bounds it (R-PE2)."""
    _entity_page(settings, entity_id)
    data = await file.read(entity_picture.MAX_UPLOAD_BYTES + 1)
    async with _PICTURE_LOCK:
        try:
            ext = entity_picture.validate_upload(data)
            write = await asyncio.to_thread(entity_picture.write_upload, settings.memory_path, entity_id, data, ext,
                                            today=date.today())
        except entity_picture.InvalidPicture as exc:   # a bound refused, or an id no picture path can hold
            raise HTTPException(exc.status, str(exc)) from exc
        await entity_picture.commit(settings.memory_path, write)
        return _picture_payload(settings.memory_path, entity_id)


@router.post("/entities/{entity_id}/picture/initials", response_model=EntityPictureResponse)
@_admits(PICTURE_BUSY)
async def use_entity_initials(entity_id: str, settings: Settings = Depends(get_settings)):
    """C11 / F-12 — "Use initials instead": the person's choice, kept (plan R-PE4)."""
    _entity_page(settings, entity_id)
    async with _PICTURE_LOCK:
        write = await asyncio.to_thread(entity_picture.write_initials, settings.memory_path, entity_id,
                                        today=date.today())
        await entity_picture.commit(settings.memory_path, write)
        return _picture_payload(settings.memory_path, entity_id)


@router.post("/entities/{entity_id}/picture/pdf", response_model=EntityPictureResponse)
async def set_entity_picture_from_pdf(entity_id: str, file: UploadFile, settings: Settings = Depends(get_settings)):
    """A PDF the person gave a saved item (a paper, a saved document): its first page, rendered in the backend
    (`pdf_page`, never the app), becomes the page's picture — the person's own choice, rung 1, kept in the bank and
    committed alone as `user` exactly like an uploaded picture. Nothing is fetched; the PDF itself is not kept. The
    render (a child process, up to `pdf_page.TIMEOUT_S`) runs BEFORE the write admission is taken, so Sleep never
    waits on it; only the write and its commit are admitted."""
    from api.services import pdf_page

    page = _entity_page(settings, entity_id)
    if str(markdown_parser.parse(page).frontmatter.get("type") or "").strip().lower() != "media":
        raise HTTPException(400, "Cicada draws a PDF's first page for saved items only.")
    data = await file.read(pdf_page.MAX_PDF_BYTES + 1)
    if len(data) > pdf_page.MAX_PDF_BYTES:
        raise HTTPException(413, "That PDF is too large — Cicada reads PDFs up to 32 MB.")
    if not pdf_page.looks_like_pdf(data):
        raise HTTPException(400, "That file isn't a PDF.")
    png = await asyncio.to_thread(pdf_page.render_first_page, data)
    if png is None:
        raise HTTPException(422, "Cicada couldn't draw that PDF's first page.")
    try:
        ext = entity_picture.validate_upload(png)
    except entity_picture.InvalidPicture as exc:
        raise HTTPException(exc.status, str(exc)) from exc

    async def store() -> EntityPictureResponse:
        async with _PICTURE_LOCK:
            _entity_page(settings, entity_id)   # still there once admitted
            write = await asyncio.to_thread(entity_picture.write_upload, settings.memory_path, entity_id, png, ext,
                                            today=date.today())
            await entity_picture.commit(settings.memory_path, write)
            return _picture_payload(settings.memory_path, entity_id)

    return await write_admission.run_admitted(settings.memory_path, store, refuse=lambda: SleepWriting(PICTURE_BUSY))


@router.delete("/entities/{entity_id}/picture", response_model=EntityPictureResponse)
@_admits(PICTURE_BUSY)
async def clear_entity_picture(entity_id: str, settings: Settings = Depends(get_settings)):
    """C11 — back to what was detected (plan R-PE4): the person's upload or initials go; nothing to clear commits
    nothing."""
    _entity_page(settings, entity_id)
    async with _PICTURE_LOCK:
        write = await asyncio.to_thread(entity_picture.write_clear, settings.memory_path, entity_id)
        if write is not None:
            await entity_picture.commit(settings.memory_path, write)
        return _picture_payload(settings.memory_path, entity_id)


# Body section whose prose becomes EntityMedia.description (M4 media entities
# write a ``## Summary`` block; ``## Description``/``## Notes`` are secondary).
_SUMMARY_RE = re.compile(
    r"^##\s+Summary\s*$(.*?)(?=^##\s|\Z)", re.IGNORECASE | re.MULTILINE | re.DOTALL
)


def _chapters(raw) -> list[VideoChapter] | None:
    """G140 Q-R12 — keep only well-formed rows: a hand-edited page could carry
    anything, and absent beats a guess (R17)."""
    if not isinstance(raw, list):
        return None
    out = [VideoChapter(t=c["t"], title=str(c["title"]).strip()[:120]) for c in raw
           if isinstance(c, dict) and isinstance(c.get("t"), int) and not isinstance(c.get("t"), bool)
           and c["t"] >= 0 and str(c.get("title") or "").strip()]
    return out or None


def _build_media_block(frontmatter: dict, body: str, *, entity_id: str | None = None) -> EntityMedia | None:
    """Build the structured ``media`` block for a ``type: media`` entity.

    Reads the nested ``media:`` frontmatter block written by
    ``media_ingestor.write_media_entity``; returns ``None`` for any entity that
    lacks a usable block (every non-media entity, plus a defensive guard for a
    ``type: media`` entity missing its block). ``description`` is lifted from the
    body's ``## Summary`` section when present. No key is invented — missing
    optionals stay ``None``.
    """
    media = frontmatter.get("media")
    if not isinstance(media, dict):
        return None
    url = media.get("url")
    media_type = media.get("media_type")
    if not url or not media_type:
        return None

    description = None
    # F1 R-FX8 — the claims fence follows the last section, so on a
    # Summary-only page (a paper's) it would ride into the description.
    match = _SUMMARY_RE.search(strip_claims_block(body or ""))
    if match:
        text = match.group(1).strip()
        if text:
            description = text

    return EntityMedia(
        url=str(url),
        media_type=str(media_type),
        site=media.get("site") or None,
        channel=media.get("channel") or None,
        thumbnail=media.get("thumbnail") or None,
        preview=entity_picture.media_picture(entity_id, frontmatter) if entity_id else None,
        description=description,
        # Track V — both written by `write_media_entity` only when set, so an
        # older page simply has neither. `duration_s` is type-checked rather
        # than coerced: a hand-edited page could carry a string, and R17 says
        # absent beats a guess.
        provider=media.get("provider") or None,
        duration_s=(
            media.get("duration_s") if isinstance(media.get("duration_s"), int)
            and not isinstance(media.get("duration_s"), bool) else None
        ),
        chapters=_chapters(media.get("chapters")),
        # G133 — `paper` on a paper page (R-LS14); absent on every other. Type-checked like
        # `duration_s`: a hand-edited `kind: [paper]` must not 500 the whole page (T4 review r1).
        kind=media.get("kind") if isinstance(media.get("kind"), str) and media.get("kind") else None,
    )


@router.get("/entities/{entity_id}/history", response_model=list[EntityHistoryEntry])
async def get_entity_history(
    entity_id: str,
    include_diff: bool = False,
    skip: int = 0,
    settings: Settings = Depends(get_settings),
):
    """Entity history with per-commit author attribution.

    Pass ``?include_diff=true`` to inline the added/removed diff for each commit
    (opt-in so the default response stays small — backlog A1). ``?skip=N`` reads
    the touching commits older than the newest N — the rows the card leaves out
    when ``history_truncated`` (review round 1).
    """
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")

    return await git_service.get_entity_history(
        entity_id, settings.memory_path, include_diff=include_diff, skip=max(0, skip)
    )


@router.get("/entities/{entity_id}/blame", response_model=PageBlameResponse, response_model_exclude_none=True)
async def get_entity_blame(entity_id: str, lines: bool = False, settings: Settings = Depends(get_settings)):
    """Who wrote each section of the page's prose, when and why (G198) — one ``git blame`` and the commits' trailers,
    never stored. ``?lines=true`` adds the commit behind every prose line."""
    from api.services import page_blame

    if not (settings.memory_path / "entities" / f"{entity_id}.md").is_file():
        raise HTTPException(404, f"Entity {entity_id} not found")
    result = await page_blame.blame(settings.memory_path, entity_id, with_lines=lines)
    if result is None:
        raise HTTPException(404, f"Entity {entity_id} not found")
    return PageBlameResponse(**result)


@router.get("/entities/{entity_id}/citations/{n}", response_model=PageCitationDetail,
            response_model_exclude_none=True)
async def get_entity_citation(entity_id: str, n: int, at: int | None = None, claim: str | None = None,
                              settings: Settings = Depends(get_settings)):
    """A citation marker's popover (ruling 48 (16), DR-80), read when the person hovers or opens it — never on card
    open: reference ``n`` as cited by the article line ending at ``at`` (or by belief ``claim``), with who, when and the
    located words. The numbering is the card's own (``page_citations``, cached per page), so a marker and its popover
    can never disagree."""
    from api.services import page_citations
    from api.services.claims import parse_claims

    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.is_file():
        raise HTTPException(404, f"Entity {entity_id} not found")

    def read() -> dict | None:
        parsed = markdown_parser.parse(entity_path, ledger=False)
        try:
            claims = parse_claims(parsed.body or "")
        except Exception:  # noqa: BLE001
            claims = []
        return page_citations.detail(settings.memory_path, entity_id, n, at=at, claim_id=claim,
                                     fm=parsed.frontmatter, body=parsed.body or "", claims=claims)

    found = await run_in_threadpool(read)
    if found is None:
        raise HTTPException(404, f"No reference {n} on {entity_id}")
    return PageCitationDetail(**found)


@router.get("/entities/{entity_id}/history/{commit_hash}/diff", response_model=EntityDiff)
async def get_entity_commit_diff(
    entity_id: str,
    commit_hash: str,
    settings: Settings = Depends(get_settings),
):
    """Added/removed lines for one entity file at one commit (backlog A1)."""
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")

    return await git_service.get_entity_commit_diff(
        entity_id, commit_hash, settings.memory_path
    )


@router.put("/entities/{entity_id}/decay", response_model=EntityResponse)
@_admits(PAGE_BUSY)
async def update_entity_decay(
    entity_id: str,
    request: EntityDecayUpdate,
    settings: Settings = Depends(get_settings),
):
    """Set an entity's decay class — the user's override (G66 §1.7).

    Writes BOTH the semantic ``decay_class:`` and its mapped numeric
    ``decay_rate:`` so a page stays self-consistent for any reader that only
    knows the old numeric key. Every other frontmatter key and the body are left
    untouched, and ``version`` is deliberately NOT bumped: choosing how fast a
    belief fades is a policy decision about the page, not a revision of its
    content. Commits scoped to this one file — trigger ``user/companion_app``,
    ``Cicada-Author: user``. 409 while Sleep holds the pages (G177).
    """
    message = git_service.build_commit_message(
        f"Set decay class {date.today().isoformat()}",
        [
            f"entities/{entity_id}.md: updated "
            f"(decay_class: {request.decay_class.value}, trigger: user/companion_app)"
        ],
        authors=["user"],
    )
    # Scoped, never ``git add -A``: a decay override must not sweep an unrelated
    # dirty file in memory/ into this commit.
    fields = decay_policy.frontmatter_fields(request.decay_class)
    await run_in_threadpool(
        _rewrite_page_and_commit, settings.memory_path, entity_id, lambda fm: fm.update(fields), message)

    return await get_entity(entity_id, settings=settings)


# Detect an absolute filesystem path inside a location entity's body when no
# ``path:`` frontmatter key is present (TODO: Sleep should extract this into
# frontmatter — see ``get_entity_location``). POSIX-only, anchored at a slash
# or ``~/``; intentionally conservative.
_BODY_PATH_RE = re.compile(r"(?<!\S)(~?/[^\s`'\"()]+)")


def _detect_location_path(frontmatter: dict, body: str) -> str | None:
    """Resolve a location's declared path from the ENTITY only (never a request).

    Prefers an explicit ``path:`` frontmatter key; falls back to the first
    absolute/``~`` path found in the body. Returns the raw declared string
    (un-expanded) or ``None`` when nothing is declared.
    """
    declared = frontmatter.get("path")
    if declared:
        text = str(declared).strip()
        if text:
            return text
    match = _BODY_PATH_RE.search(body or "")
    return match.group(1) if match else None


@router.get("/entities/{entity_id}/location", response_model=LocationListing)
async def get_entity_location(
    entity_id: str,
    settings: Settings = Depends(get_settings),
):
    """The folder a ``directory`` or ``location`` page declares — the path only.

    The path is the one the ENTITY ITSELF declares (frontmatter ``path:`` if
    present, else a path detected in the body), never one the request names.
    The backend never touches it: no ``resolve``, ``stat``, ``is_dir`` or
    listing. The app lists the folder itself (``LocationLister``), so a macOS
    privacy prompt names Cicada, not the launchd backend's interpreter (the
    ``~/Library`` rail: the app reads the person's Mac, the backend parses).
    The envelope keeps ``exists``/``accessible``/``entries`` at their defaults;
    they are the app's to fill.

    TODO (Sleep): the entity extractor should write a ``path:`` key into
    ``type: location`` frontmatter when a description names a directory, so this
    endpoint doesn't have to body-scan. Out of scope for this UI/UX pass.
    """
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")

    parsed = markdown_parser.parse(entity_path)
    fm = parsed.frontmatter or {}
    # G18 — path-listing applies to a `directory` entity; `location` (a physical
    # place) is accepted too for rename-tolerance (legacy graphs filed paths
    # under `location` before the split).
    if str(fm.get("type", "")).lower() not in ("directory", "location"):
        raise HTTPException(400, f"Entity {entity_id} is not a directory or location")

    return LocationListing(path=_detect_location_path(fm, parsed.body))


def _repo_declarations(frontmatter: dict) -> list[dict]:
    """The page's ``repos:`` read leniently — entries come from Sleep and generators
    too: a non-dict is skipped, a scalar is coerced to a string, and ``path`` is
    kept exactly as written (it is the key the app posts back)."""
    raw = frontmatter.get("repos") if isinstance(frontmatter, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict) or entry.get("path") is None or isinstance(entry["path"], (dict, list)):
            continue
        path = entry["path"] if isinstance(entry["path"], str) else str(entry["path"])
        if not path.strip():
            continue
        decl: dict = {"path": path}
        for key in ("device", "remote", "default_branch"):
            value = entry.get(key)
            if value is not None and not isinstance(value, (dict, list)) and str(value).strip():
                decl[key] = str(value).strip()
        worktrees = []
        for w in entry.get("worktrees") if isinstance(entry.get("worktrees"), list) else []:
            if isinstance(w, dict) and w.get("path") is not None and str(w["path"]).strip():
                branch = w.get("branch")
                worktrees.append({
                    "path": str(w["path"]),
                    "branch": str(branch) if branch is not None and not isinstance(branch, (dict, list)) else None,
                    "primary": bool(w.get("primary", False)),
                })
        if worktrees:
            decl["worktrees"] = worktrees
        out.append(decl)
    return out


def _declared_repos(settings: Settings, entity_id: str) -> list[dict]:
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    return _repo_declarations(markdown_parser.parse(entity_path).frontmatter)


def _declarations_payload(entity_id: str, declared: list[dict]) -> RepoDeclarationList:
    return RepoDeclarationList(
        entity_id=entity_id,
        this_device=local_refs.current_device_id(),
        repos=[RepoDeclaration(**d, on_this_device=local_refs.is_this_device(d.get("device"))) for d in declared],
    )


@router.get("/entities/{entity_id}/repos", response_model=RepoDeclarationList)
async def get_entity_repos(
    entity_id: str,
    settings: Settings = Depends(get_settings),
):
    """The repos a page declares (G-repo), and which device this Mac is.

    Declarations only: the backend never runs git, stats or resolves a
    declared path — under launchd its interpreter is what macOS names, so a
    probe here made the Mac ask whether "python3.12" may read the person's
    folder. The app runs ``repo_context.REPO_COMMANDS`` (pinned by
    ``api/tests/fixtures/repo_commands.json``) in each repo on this Mac and
    posts the outputs to ``POST …/repos/observed``. 404 only when the entity
    file does not exist; no ``repos:`` key is ``repos: []``.
    """
    return _declarations_payload(entity_id, _declared_repos(settings, entity_id))


def _match_declaration(declared: list[dict], path: str, device: str | None) -> dict | None:
    """The declaration a posted observation answers: the same path string, and the
    same device when the page declares that path more than once."""
    same_path = [d for d in declared if d["path"] == path]
    if not same_path:
        return None
    device = (device or "").strip() or None
    for d in same_path:
        if d.get("device") == device:
            return d
    return same_path[0]


@router.post("/entities/{entity_id}/repos/observed", response_model=RepoContextList)
async def post_entity_repos_observed(
    entity_id: str,
    request: RepoObservedRequest,
    settings: Settings = Depends(get_settings),
):
    """Parse what the app's git printed in the page's declared repos (G-repo).

    Each observation names a path exactly as the page declares it — any other
    path is a 422, so a request can never make the backend describe a folder
    the page does not claim. ``repo_context.parse_snapshot`` (the one parser the
    MCP tool uses too) turns the outputs into the card's ``RepoContext``; a repo
    declared on another device is ``other_device`` whatever was posted. Only a
    summary is kept — branch, dirty, ahead/behind, status and when — in
    ``$CICADA_HOME/repos/<bank>.json`` (``repo_observations``), never in the
    bank, so ``_state.md`` can name the branch without a probe of its own.
    """
    declared = _declared_repos(settings, entity_id)
    this_device = local_refs.current_device_id()
    contexts: list[dict] = []
    for obs in request.repos:
        decl = _match_declaration(declared, obs.path, obs.device)
        if decl is None:
            raise HTTPException(422, "a posted repo is not one this page declares")
        unknown = set(obs.outputs) - repo_context.COMMAND_KEYS
        if unknown:
            raise HTTPException(422, f"unknown command keys: {', '.join(sorted(unknown))}")
        other = repo_context.is_other_device(decl, this_device)
        if not other and obs.error is None and "inside" not in obs.outputs:
            raise HTTPException(422, "an observation on this device needs the 'inside' output or an error")
        outputs = {} if other else {k: v.model_dump() for k, v in obs.outputs.items()}
        contexts.append(repo_context.parse_snapshot(outputs, decl, error=obs.error, this_device=this_device))
    await run_in_threadpool(repo_observations.record, settings.memory_path, contexts)
    return RepoContextList(entity_id=entity_id, repos=[RepoContext(**c) for c in contexts])


def _repo_input_to_frontmatter(r: RepoInput) -> dict:
    """One validated ``RepoInput`` -> the dict shape written into ``repos:``."""
    out: dict = {"path": r.path}
    if r.device:
        out["device"] = r.device
    if r.remote:
        out["remote"] = r.remote
    if r.default_branch:
        out["default_branch"] = r.default_branch
    if r.worktrees:
        out["worktrees"] = [
            {"path": w.path, "branch": w.branch, "primary": w.primary}
            for w in r.worktrees
        ]
    return out


@router.patch("/entities/{entity_id}/repos", response_model=RepoDeclarationList)
@_admits(PAGE_BUSY)
async def update_entity_repos(
    entity_id: str,
    request: RepoUpdateRequest,
    settings: Settings = Depends(get_settings),
):
    """Rewrite ONLY the ``repos:`` frontmatter key and commit (G-repo).

    Setting ``repos: []`` removes the key entirely rather than persisting an
    empty list, so an entity that never declared a repo stays byte-identical.
    Every other frontmatter key and the body are left untouched. Commits via
    the same structured-commit-message + git_service pattern as every other
    Cicada write: trigger ``user/companion_app``, ``Cicada-Author: user`` —
    scoped to this one page, never ``git add -A`` (G183(a)). 409 while Sleep
    holds the pages (G177). Answers the declarations, like ``GET`` — never a probe.
    """
    repos = [_repo_input_to_frontmatter(r) for r in request.repos]

    def mutate(fm: dict) -> None:
        if repos:
            fm["repos"] = repos
        else:
            fm.pop("repos", None)

    message = git_service.build_commit_message(
        f"Update repo links {date.today().isoformat()}",
        [f"entities/{entity_id}.md: updated (trigger: user/companion_app)"],
        authors=["user"],
    )
    fm = await run_in_threadpool(_rewrite_page_and_commit, settings.memory_path, entity_id, mutate, message)

    return _declarations_payload(entity_id, _repo_declarations(fm))


def _sources_payload(memory_path: Path, entity_id: str) -> EntitySourceList:
    from api.services import source_proposals

    rows = []
    entity_path = memory_path / "entities" / f"{entity_id}.md"
    try:
        page_type = str(markdown_parser.parse(entity_path).frontmatter.get("type") or "").strip().lower()
    except Exception:  # noqa: BLE001 — an unreadable page draws no mark
        page_type = "person"
    for s in fact_sources.list_sources(memory_path, entity_id):
        # A link to a page that is gone (deleted, merged away, dropped) reads as no link.
        s["entity"] = fact_sources.linked_entity(memory_path, s, self_id=entity_id)
        s["effective_access"] = fact_sources.effective_access(s)
        s["trusted"] = fact_sources.trusted(s)
        # G61, ruling 26: whether it is re-checked, by whom, and why it is due now — derived, never stored.
        s["tracked"] = source_refresh.tracked(s)
        s["refresh_checker"] = source_refresh.checker(s) if s["tracked"] else None
        s["refresh_due"] = source_refresh.due_reason(s, date.today())
        if not isinstance(s.get("refresh"), dict):
            s.pop("refresh", None)
        if not isinstance(s.get("recheck_days"), int):
            s.pop("recheck_days", None)
        # G61 "Where to check" (ruling 36 D5): the chip row's words, derived; the icon by the existing icon rule only.
        s["proposed"] = fact_sources.is_proposed(s)
        if not isinstance(s.get("evidence"), dict):
            s.pop("evidence", None)
        s["link_kind"], s["label"] = source_proposals.link_kind(s)
        s["icon_site"] = page_blocks.icon_site(s, page_type)
        rows.append(EntitySource(**s))
    return EntitySourceList(entity_id=entity_id, sources=rows)


async def _commit_sources(memory_path: Path, entity_id: str, verb: str, extra: tuple[str, ...] = ()) -> None:
    paths = [f"entities/{entity_id}.md", *extra]
    message = git_service.build_commit_message(
        f"{verb} fact source {date.today().isoformat()}",
        [f"{p}: updated (trigger: user/companion_app)" for p in paths],
        authors=["user"],
    )
    # Scoped, never ``git add -A``: adding one fact source must not sweep an
    # unrelated dirty file in memory/ into an "Add fact source" commit.
    await git_service.commit_paths(memory_path, message, paths)


@router.get("/entities/{entity_id}/sources", response_model=EntitySourceList)
async def get_entity_sources(
    entity_id: str,
    settings: Settings = Depends(get_settings),
):
    """List an entity's declared refresh sources (G61).

    404 only when the entity file itself is missing; an entity with no
    ``sources:`` key returns ``sources: []`` at 200.
    """
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    return _sources_payload(settings.memory_path, entity_id)


@router.get("/entities/{entity_id}/sources/overview", response_model=SourcesOverview)
async def get_entity_sources_overview(
    entity_id: str,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    """Where this page's knowledge comes from, and how fresh it is (owner 2026-10-14, G61): its sources with the
    beliefs each backs, the links its conversations named, and those conversations by app — the card's one read for
    "Where this comes from" (``page_sources``). Engine-free, never fetches, writes nothing. On demand, not a Store
    domain: the ETag (entities + episodes, the shape and today — what counts as a current belief moves at midnight)
    serves the card's in-memory cache (``ProvenanceCache.sourcesOverview``), so there is no ``VersionVector`` mapping."""
    from api.services import page_sources
    from api.services.claims import current_day
    from api.services.id_utils import resolve_entity_file

    memory_path = settings.memory_path
    page = resolve_entity_file(memory_path, entity_id)
    if page is None or not page.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    etag = sync_service.etag_for(memory_path, "entities", "episodes",
                                 extra=f"{page_sources.SHAPE}|{page.stem}|{current_day()}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    return await run_in_threadpool(page_sources.overview, memory_path, page)


@router.get("/entities/{entity_id}/sources/icon/{site}")
async def get_entity_source_icon(
    entity_id: str,
    site: str,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """G61 S3-b — the mark of a site THIS page lists as a source, for the card's row: the icon service only, the site
    itself is never contacted. Keyed on the site (``reading_hosts.site_of``), never a URL, so no ref, token or path
    reaches a log. Served only for a site one of this page's sources (that is not a note) belongs to — 404 otherwise, with no
    lookup, so this is not a proxy for an arbitrary name — and never for an unverified proposal: nothing draws a
    mark from a site nobody vouched for (`fact_sources.trusted`)."""
    from api.routers.reading import serve_site_icon
    from api.services import reading_hosts

    if not reading_hosts.valid_site_key(site):
        raise HTTPException(404, "no icon for this site")
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, "no icon for this site")
    # G159: a person's page never draws a mark — a personal domain can carry the name, and no service is sent it.
    if str(markdown_parser.parse(entity_path).frontmatter.get("type") or "").strip().lower() in ("person", "media"):
        raise HTTPException(404, "no icon for this site")
    allowed = _icon_sites(settings.memory_path, entity_id, entity_path)
    domain = reading_hosts.icon_host(site) if site in allowed else None
    if not domain:
        raise HTTPException(404, "no icon for this site")
    return await serve_site_icon(request, settings.memory_path, site, domain)


def _icon_sites(memory_path: Path, entity_id: str, entity_path: Path) -> set[str]:
    """The sites whose mark this page may draw: a trusted source's site (G61 S3-b), and — owner rulings 2026-10-14 —
    the site of a page the person **saved** that this page's prose links to (``page_links.linked_sites``). Never a
    site only named or linked: that draws a ring monogram. Callers refuse a ``person`` or ``media`` page first (G159)."""
    from api.services import page_links, reading_hosts

    allowed = {reading_hosts.site_of(str(s.get("ref") or "")) for s in fact_sources.list_sources(memory_path, entity_id)
               if str(s.get("kind") or "") == "url" and fact_sources.trusted(s)}
    try:
        allowed |= page_links.linked_sites(memory_path, markdown_parser.parse(entity_path).body or "")
    except Exception:  # noqa: BLE001 — an unreadable page vouches for nothing
        pass
    return allowed


@router.get("/entities/{entity_id}/links", response_model=PageLinksResponse, response_model_exclude_none=True)
async def get_entity_links(
    entity_id: str,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    """A page's link facts (owner rulings 2026-10-14): per URL in its prose, everything a link card draws — the saved
    page's title, site, description, save and read dates and stored picture, the looks saved of it, its captures
    (empty until site exploration lands) and whether its site's mark may be drawn (``page_links``). Engine-free, never
    fetches, writes nothing. On demand, not a Store domain: the ETag (entities, sources — the URL index — and design,
    plus the shape) serves the card's in-memory cache (``LinkFactsCache``), so there is no ``VersionVector`` mapping."""
    from api.services import page_links
    from api.services.id_utils import resolve_entity_file

    memory_path = settings.memory_path
    page = resolve_entity_file(memory_path, entity_id)
    if page is None or not page.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    etag = sync_service.etag_for(memory_path, "entities", "sources", "design", extra=f"{page_links.SHAPE}|{page.stem}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early

    def build() -> dict:
        kind = str(markdown_parser.parse(page).frontmatter.get("type") or "").strip().lower()
        allowed = set() if kind in ("person", "media") else _icon_sites(memory_path, page.stem, page)
        return page_links.facts(memory_path, page, icon_allowed=allowed)

    return await run_in_threadpool(build)


@router.post("/entities/{entity_id}/edits", response_model=PageEditResponse)
@_admits(PAGE_BUSY)
async def edit_entity_page(
    entity_id: str,
    request: PageEditRequest,
    settings: Settings = Depends(get_settings),
):
    """The person's own edit of a page's words or aliases (owner rulings 2026-10-14) — the link-view switcher's door,
    and any other prose fix the app offers. The same body as ``cicada_edit_page`` (``page_edits.plan``: never the
    claims, never a heading or a fence, ``Related`` refused), applied at once and committed alone under the person
    (``Cicada-Author: user``, trigger ``user/companion_app``) with the reason as its ``Reason:`` line. A second door onto
    one writer, as the CLI is (ruling 21). 400: a request the editor refuses; 409: words no longer on the page, or Sleep
    holding the pages (G177)."""
    from api.services import page_edits

    try:
        reason = page_edits.clean_reason(request.reason)
        edit = page_edits.parse_request(request.edits, request.section, request.text, request.add_aliases,
                                        request.remove_aliases)
    except page_edits.EditError as exc:
        raise HTTPException(400, str(exc)) from exc
    outcome = await run_in_threadpool(_person_edit, settings.memory_path, entity_id, edit, reason)
    return PageEditResponse(entity_id=entity_id, changes=outcome.changes, sections=outcome.sections,
                            pinned=outcome.pinned)


#: The person's page edits commit under this trigger, beside the app's other writes.
PERSON_EDIT_TRIGGER = "user/companion_app"


def _person_edit(memory_path: Path, entity_id: str, edit, reason: str):
    """Plan, write and commit one person's edit as ONE page-lock section, in a worker thread (G183(a)), like
    ``_rewrite_page_and_commit``: an edit already on the page is committed apart first, unauthored."""
    from api.services import bank_index, page_edits
    from api.services.id_utils import resolve_entity_file

    with page_lock.page_lock(memory_path):
        page = resolve_entity_file(memory_path, entity_id)
        if page is None or not page.is_file():
            raise HTTPException(404, f"Entity {entity_id} not found")
        rel = f"entities/{page.name}"
        tracked = (memory_path / ".git").exists()
        before = None
        if tracked:
            before = {rel: page.read_bytes()} if rel in git_service.dirty_paths_sync(memory_path, rel) else {}
        current = page_edits.read(page)
        try:
            outcome = page_edits.plan(current.frontmatter, current.body, edit, author="user")
        except page_edits.EditError as exc:
            raise HTTPException(409, str(exc)) from exc
        page_edits.write(page, outcome)
        if tracked:
            message = git_service.build_commit_message(
                f"{page_edits.COMMIT_SUBJECT} {date.today().isoformat()}",
                page_edits.commit_lines(rel, PERSON_EDIT_TRIGGER, reason), authors=["user"])
            git_service.commit_touched_sync(memory_path, message, [rel], before=before)
    bank_index.invalidate(memory_path)
    return outcome


@router.get("/entities/{entity_id}/paper", response_model=PaperDetailResponse)
async def get_entity_paper(entity_id: str, settings: Settings = Depends(get_settings)):
    """G133 / G121 — a paper page's two tiers, resolved at read (engine-free):
    "why it's in your memory" as spans into the person's own files, then the
    dated world-tier context. 404 for anything that is not a paper page."""
    from api.services import papers

    detail = await asyncio.to_thread(papers.detail, settings.memory_path, entity_id)
    if detail is None:
        raise HTTPException(404, f"{entity_id!r} is not a paper")
    return PaperDetailResponse(**detail)


@router.post("/entities/{entity_id}/sources", response_model=EntitySourceList)
@_admits(SOURCE_BUSY)
async def add_entity_source(
    entity_id: str,
    request: EntitySourceCreate,
    settings: Settings = Depends(get_settings),
):
    """Append one source. ``kind`` is inferred from ``ref`` when not supplied.

    G61 phase 2 S1 (plan R-AC21, R-AC27): the person's ``access``/``accepted``/
    ``only_me`` ride along, and a value the record does not allow is a 400 with
    ``fact_sources.InvalidSource``'s message — never a silently dropped field."""
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    if not (request.ref or "").strip():
        raise HTTPException(400, "ref is required")

    try:
        fact_sources.add_source(
            settings.memory_path,
            entity_id,
            request.ref,
            kind=request.kind,
            predicate=request.predicate,
            added_by="user",
            access=request.access,
            accepted=request.accepted,
            only_me=request.only_me,
            entity=request.entity,
        )
    except fact_sources.InvalidSource as exc:
        raise HTTPException(400, str(exc)) from exc
    await _commit_sources(settings.memory_path, entity_id, "Add")
    return _sources_payload(settings.memory_path, entity_id)


@router.post("/entities/{entity_id}/sources/change", response_model=EntitySourceList)
@_admits(SOURCE_BUSY)
async def change_entity_source(
    entity_id: str,
    request: EntitySourceChange,
    settings: Settings = Depends(get_settings),
):
    """G61 S3-a — change or remove ONE source by its key ``(ref, predicate)``, as the person (any entry).

    ``update`` changes ``access``/``entity`` in place (an explicit ``entity: null`` clears the link) and a
    ``newRef``/``newPredicate`` replaces the entry; ``remove`` drops it and leaves a ``sources_removed``
    tombstone so no machine writer puts it back. 404: no page, or nothing under that key; 400: a value the
    record does not allow. Commits alone as ``user`` (``user/companion_app``), like the other source writes."""
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    if not (request.ref or "").strip():
        raise HTTPException(400, "ref is required")
    removing = next((s for s in fact_sources.list_sources(settings.memory_path, entity_id)
                     if str(s.get("ref", "")).strip() == request.ref.strip()
                     and fact_sources.same_predicate(s.get("predicate"), request.predicate)), None)
    result = fact_sources.change_source(
        settings.memory_path, entity_id, request.ref, request.predicate,
        actor=fact_sources.USER, action=request.action, reason=request.reason,
        new_ref=request.new_ref, new_predicate=request.new_predicate, access=request.access,
        entity=request.entity if "entity" in request.model_fields_set else fact_sources._UNSET,
        accepted=request.accepted, only_me=request.only_me,
    )
    if result.action == "not_found":
        raise HTTPException(404, result.message)
    if result.action in ("refused", "not_yours"):
        raise HTTPException(400, result.message)
    extra: tuple[str, ...] = ()
    if result.action == "removed":
        from api.services import contacts_local

        refused = contacts_local.remember_removal(settings.memory_path, entity_id, removing or {})
        extra = (refused,) if refused else ()
    await _commit_sources(
        settings.memory_path, entity_id, "Remove" if result.action == "removed" else "Change", extra)
    return _sources_payload(settings.memory_path, entity_id)


@router.post("/entities/{entity_id}/sources/refresh", response_model=EntitySourceList)
async def refresh_entity_source(
    entity_id: str,
    request: SourceRefreshRequest,
    settings: Settings = Depends(get_settings),
):
    """G61, ruling 26 — the person asks to re-check ONE tracked source now (or sets how often: ``everyDays``,
    ``clear``). A public page is read now on Cicada's own rail (the person's click: ungated by
    ``CICADA_ALLOW_CONNECTOR_FETCH``, never a walled host) and what it states is folded at once — the newest evidence
    wins — in one ``cicada`` commit (trigger ``user/companion_app``). A login-walled page is never fetched here: it is
    marked asked, so the person's own agent sees it first (``cicada_refresh_claim``), committed as ``user``. The read
    runs before admission and the write and its commit inside it. 409 on the demo bank or while Sleep holds the pages;
    404 no page or no such source; 400 a source that is not re-checked (an agent's unconfirmed proposal, a note, a
    path)."""
    from api.services import demo_guard

    memory_path = settings.memory_path
    if demo_guard.is_demo(memory_path):
        raise HTTPException(409, "this is the demo memory, made up for the tour — there are no real sources to check")
    if not (memory_path / "entities" / f"{entity_id}.md").exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    ref = (request.ref or "").strip()
    entry = next((s for s in fact_sources.list_sources(memory_path, entity_id)
                  if str(s.get("ref", "")).strip() == ref
                  and fact_sources.same_predicate(s.get("predicate"), request.predicate)), None)
    if entry is None:
        raise HTTPException(404, "No source with that link and fact on this page")
    if request.every_days is not None or request.clear:
        def cadence() -> None:
            source_refresh.set_every(memory_path, entity_id, ref, request.predicate,
                                     None if request.clear else request.every_days)

        async def body():
            await asyncio.to_thread(cadence)
            await _commit_sources(memory_path, entity_id, "Change")
        await write_admission.run_admitted(memory_path, body, refuse=lambda: SleepWriting(SOURCE_BUSY))
        return _sources_payload(memory_path, entity_id)
    if not source_refresh.tracked(entry):
        raise HTTPException(400, "Only a source you added or took, or one Cicada's own read confirmed, is re-checked")
    if source_refresh.checker(entry) == source_refresh.AGENT:
        async def ask():
            await asyncio.to_thread(source_refresh.mark_asked, memory_path, entity_id, ref, request.predicate)
            await _commit_sources(memory_path, entity_id, "Ask to re-check")
        await write_admission.run_admitted(memory_path, ask, refuse=lambda: SleepWriting(SOURCE_BUSY))
        return _sources_payload(memory_path, entity_id)
    item = await asyncio.to_thread(source_refresh.asked_item, memory_path, entity_id, ref, request.predicate)
    if item is None:
        raise HTTPException(404, "No source with that link and fact on this page")
    if (memory_path / ".git").exists():
        from api.services import sleep_cycle

        if f"entities/{entity_id}.md" in await sleep_cycle._dirty_paths(memory_path):
            raise HTTPException(409, "this page has changes that are not saved yet — try again in a moment")
    # The fetch first, outside admission (no admission spans a fetch, G183); then the write and its commit admitted.
    planned = await source_refresh.observe_due(memory_path, budget=1, only=item)
    report = source_refresh.Report()

    async def write():
        try:
            await asyncio.to_thread(source_refresh.write_observed, memory_path, planned,
                                    trigger=source_refresh.ROUTE_TRIGGER, report=report)
            if report.paths and (memory_path / ".git").exists():
                await git_service.commit_paths(
                    memory_path,
                    source_refresh.commit_message(report, date.today(), source_refresh.ROUTE_TRIGGER), report.paths)
        except Exception:
            await asyncio.to_thread(source_refresh.restore, memory_path, report)
            raise HTTPException(500, "the re-check could not be saved; nothing was changed")
    await write_admission.run_admitted(memory_path, write, refuse=lambda: SleepWriting(SOURCE_BUSY))
    return _sources_payload(memory_path, entity_id)


@router.delete("/entities/{entity_id}/sources/{index}", response_model=EntitySourceList)
@_admits(SOURCE_BUSY)
async def delete_entity_source(
    entity_id: str,
    index: int,
    settings: Settings = Depends(get_settings),
):
    """Remove the source at ``index`` (0-based, file order)."""
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    # The same list `delete_source` indexes (every dict entry, file order) — `list_sources` also drops ref-less ones.
    raw = markdown_parser.parse(entity_path).frontmatter.get("sources") or []
    current = [s for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []
    removing = current[index] if 0 <= index < len(current) else None
    # G61 S3-a: the person's removal is remembered like an agent's (`sources_removed`, by `user`) — an older client's
    # index delete included — so no machine writer puts the key back. A Contacts card keeps its own memory (below).
    remembered = None if str((removing or {}).get("ref") or "").startswith("addressbook://") else fact_sources.USER
    if not fact_sources.delete_source(settings.memory_path, entity_id, index, remembered_by=remembered):
        raise HTTPException(404, f"No source at index {index} on {entity_id}")
    # Round-4 final review, finding 1: a Contacts entry the person removes stays removed — the next Contacts sync
    # would otherwise put it back under the person's own name. Committed with the removal, one `user` commit.
    from api.services import contacts_local

    refused = contacts_local.remember_removal(settings.memory_path, entity_id, removing or {})
    await _commit_sources(settings.memory_path, entity_id, "Remove", (refused,) if refused else ())
    return _sources_payload(settings.memory_path, entity_id)


@router.get("/entities/{entity_id}/context", response_model=EntityContextResponse)
async def get_entity_context(
    entity_id: str,
    top_k: int = 5,
    settings: Settings = Depends(get_settings),
):
    """Progressive-disclosure context for an entity.

    Returns the entity plus the cheap next-hops a small LLM needs to traverse
    without loading the whole graph: which hubs it belongs to, neighbors
    (LEANN + related + resolved wikilinks), source-episode excerpts, and an
    ordered ``next_hops`` action list. Degrades gracefully when LEANN is absent.
    """
    memory_path = settings.memory_path
    entities_dir = memory_path / "entities"

    name_index = build_name_index(entities_dir)
    resolved_id = resolve_entity_id(entities_dir, entity_id, name_index)
    if not resolved_id:
        raise HTTPException(404, f"Entity {entity_id} not found")
    entity_path = entities_dir / f"{resolved_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")

    parsed = markdown_parser.parse(entity_path)
    fm = parsed.frontmatter or {}
    name = str(fm.get("name", resolved_id.replace("-", " ").title()))

    hubs = _hubs_for_entity(memory_path, resolved_id)
    neighbors, ordered_ids = _build_neighbors(
        memory_path, entities_dir, resolved_id, name, parsed.body, name_index, top_k
    )
    episodes = _build_episodes(memory_path, name, fm.get("source_episodes", []) or [], top_k)

    return EntityContextResponse(
        id=resolved_id,
        name=name,
        type=str(fm.get("type", "concept") or "concept"),
        status=str(fm.get("status", "active") or "active"),
        confidence=float(fm.get("confidence", 0.5) or 0.0),
        markdown_content=served_prose(parsed.body)[0],
        hubs=hubs,
        neighbors=neighbors,
        episodes=episodes,
        next_hops=ordered_ids,
    )


def _hubs_for_entity(memory_path: Path, entity_id: str) -> list[str]:
    """Hub ids (``hub:<stem>``) whose member list includes this entity."""
    hubs_dir = memory_path / "hubs"
    if not hubs_dir.exists():
        return []
    out: list[str] = []
    for filepath in sorted(hubs_dir.glob("*.md")):
        try:
            fm = markdown_parser.parse(filepath).frontmatter or {}
        except Exception:
            continue
        if fm.get("type") != "hub":
            continue
        members = fm.get("members") or []
        if any(isinstance(m, dict) and m.get("id") == entity_id for m in members):
            out.append(f"hub:{filepath.stem}")
    return out


def _leann_entity_neighbors(memory_path: Path, query: str, top_k: int) -> list[dict]:
    """Vector entity hits, or [] when the index is unavailable (caller degrades)."""
    try:
        from api.services.vector_index import SqliteVecIndexer
    except Exception:
        return []
    try:
        indexer = SqliteVecIndexer(memory_path)
        raw = indexer.search_entities(query, top_k=top_k)
    except Exception:
        return []
    out: list[dict] = []
    for r in raw or []:
        meta = r.get("metadata", {}) or {}
        eid = meta.get("entity_id")
        if eid:
            out.append({"id": eid, "score": float(r.get("score", 0.0) or 0.0)})
    return out


def _neighbor_from_id(
    entities_dir: Path, eid: str, via: str, score: float | None
) -> ContextNeighbor | None:
    filepath = entities_dir / f"{eid}.md"
    if not filepath.exists():
        return None
    try:
        parsed = markdown_parser.parse(filepath)
    except Exception:
        return None
    fm = parsed.frontmatter or {}
    return ContextNeighbor(
        id=eid,
        name=str(fm.get("name", eid.replace("-", " ").title())),
        type=str(fm.get("type", "concept") or "concept"),
        confidence=float(fm.get("confidence", 0.5) or 0.0),
        summary=_one_line_summary(parsed.body),
        via=via,
        score=score,
    )


def _build_neighbors(
    memory_path: Path,
    entities_dir: Path,
    entity_id: str,
    name: str,
    body: str,
    name_index: dict[str, str],
    top_k: int,
) -> tuple[list[ContextNeighbor], list[str]]:
    """Merge LEANN + related + resolved wikilinks, deduped, with an ordered id list."""
    fm = markdown_parser.parse(entities_dir / f"{entity_id}.md").frontmatter or {}

    # (id, via, score) candidates in priority order: LEANN, related, wikilink.
    candidates: list[tuple[str, str, float | None]] = []
    query = f"{name} {body[:200]}".strip()
    for hit in _leann_entity_neighbors(memory_path, query, top_k):
        candidates.append((hit["id"], "leann", hit["score"]))
    for ref in fm.get("related", []) or []:
        rid = resolve_entity_id(entities_dir, str(ref), name_index)
        if rid:
            candidates.append((rid, "related", None))
    for display in extract_wikilinks(body):
        wid = resolve_entity_id(entities_dir, display, name_index)
        if wid:
            candidates.append((wid, "wikilink", None))

    neighbors: list[ContextNeighbor] = []
    ordered_ids: list[str] = []
    seen: set[str] = {entity_id}
    cap = top_k * 2
    for nid, via, score in candidates:
        if nid in seen or len(neighbors) >= cap:
            continue
        neighbor = _neighbor_from_id(entities_dir, nid, via, score)
        if not neighbor:
            continue
        seen.add(nid)
        neighbors.append(neighbor)
        ordered_ids.append(nid)
    return neighbors, ordered_ids


def _build_episodes(
    memory_path: Path, name: str, source_episodes: list, top_k: int
) -> list[ContextEpisodeExcerpt]:
    """Excerpts from source_episodes plus a couple of LEANN episode hits."""
    episodes_dir = memory_path / "episodes"
    out: list[ContextEpisodeExcerpt] = []
    seen: set[str] = set()

    for ep_id in source_episodes:
        ep_id = str(ep_id)
        if not ep_id or ep_id in seen:
            continue
        filepath = episodes_dir / f"{ep_id}.md"
        if not filepath.exists():
            continue
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue
        seen.add(ep_id)
        excerpt = " ".join((parsed.body or "").split())[:400]
        out.append(
            ContextEpisodeExcerpt(
                episode_id=ep_id,
                timestamp=str((parsed.frontmatter or {}).get("timestamp", "") or ""),
                excerpt=excerpt,
            )
        )

    # Top-2 episode hits not already covered.
    try:
        from api.services.vector_index import SqliteVecIndexer

        indexer = SqliteVecIndexer(memory_path)
        for r in indexer.search_episodes(name, top_k=2) or []:
            meta = r.get("metadata", {}) or {}
            ep_id = str(meta.get("episode_id", "") or "")
            if not ep_id or ep_id in seen:
                continue
            seen.add(ep_id)
            excerpt = " ".join((r.get("text") or "").split())[:400]
            out.append(
                ContextEpisodeExcerpt(
                    episode_id=ep_id,
                    timestamp=str(meta.get("timestamp", "") or ""),
                    excerpt=excerpt,
                )
            )
    except Exception:
        pass

    return out
