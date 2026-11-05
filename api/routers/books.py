"""Books (G39, G233): a scanned ISBN, Apple Books, a Goodreads export — each staged as episodes, then made pages.

* ``POST /capture/isbn`` — the phone's "Scan a book" (and any client): ``{isbn, status?, id?}``. Capture-only devices
  may call it. **This shape is the phone's contract**: ``isbn`` is the scanned EAN-13 (or an ISBN-10, or the digits
  with hyphens); ``status`` is ``reading`` · ``finished`` · ``want`` · ``not_started`` or absent (a scan with no tap
  says nothing about reading); ``id`` is the client's own id for the scan, and ``Idempotency-Key`` (the phone's item
  id) makes a resend the first answer. Answers ``{status: created|updated|unchanged, episodeId, isbn, book:
  "waiting"}``; 422 for a number that is not a book's. The page is made at the home once the number resolves.
* ``GET|PUT /sources/apple-books/settings`` and ``POST /sources/apple-books/sync`` — the app reads Apple Books after
  the person turned it on and posts a projection (``apple_books``); a sync while it is off is refused (409).
* ``POST /sources/goodreads/preview`` and ``POST /sources/goodreads/import`` — the person's own Goodreads export CSV.
* ``GET /sources/books/scans/{episodeId}`` — what a scan became, so the Mac's Add can say "Already in your books".
* ``GET /sources/books`` — counts for the Reading rows: books by status, and scans waiting for their lookup.
* ``POST /sources/apple-books/covers`` — the covers the app read from Apple Books' cache (ruling 61, ``book_covers``).
* ``GET /entities/{id}/book-status``, ``POST /entities/{id}/book-status/undo`` — the book's status and "Not right".
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.routers.capture import refuse_capture_into_demo
from api.services import apple_books, book_covers, book_jobs, books, episode_staging, folder_source, goodreads_export
from api.services import idempotency, logo_service, sync_state, telemetry, write_admission
from api.services.sleep_refusal import SleepWriting

router = APIRouter()
_DEMO_GATE = [Depends(refuse_capture_into_demo)]

NOT_A_BOOK = ("That is not a book's barcode: an ISBN has 13 digits starting 978 or 979 (or 10 digits) and its last "
              "digit checks.")
APPLE_BOOKS_OFF = "Apple Books is turned off in Cicada. Turn it on in Sources first."


class IsbnCaptureRequest(BaseModel):
    isbn: str = Field(..., min_length=10, max_length=24)
    status: Literal["reading", "finished", "want", "not_started"] | None = None
    id: str | None = Field(None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")


@router.post("/capture/isbn", dependencies=_DEMO_GATE)
async def capture_isbn(req: IsbnCaptureRequest, request: Request, settings: Settings = Depends(get_settings)):
    """A book the person scanned: the number and, when they tapped one, what they are doing with it. Capture (Awake):
    the episode only, staged by ``source_id`` and committed; no model, no Sleep gate. The lookup and the page follow in
    the background at the home (``book_jobs``), behind the network gate; until then the scan waits, never lost."""
    isbn = books.isbn13(req.isbn)
    if isbn is None:
        raise HTTPException(status_code=422, detail=NOT_A_BOOK)
    device = getattr(request.state, "device", None)
    who = device.id if device is not None else "server"
    key = idempotency.clean_key(request.headers.get(idempotency.HEADER))
    now = datetime.now(timezone.utc)
    ident = req.id or (hashlib.sha256(key.encode()).hexdigest()[:24] if key else
                       "scan-" + hashlib.sha256(f"{isbn}|{req.status}|{now.date()}".encode()).hexdigest()[:24])
    memory_path = Path(settings.memory_path)

    async def work():
        draft = books.scan_draft(isbn, req.status, who=who, ident=ident, now=now)
        result = await asyncio.to_thread(
            lambda: episode_staging.stage([draft], memory_path / "episodes", bank=memory_path.name))
        # Like a note, the scan's episode is not committed here: the apply that makes its page commits it with the page.
        book_jobs.schedule(memory_path, author="user", trigger="capture/isbn")
        status = "created" if result.created else ("updated" if result.updated else "unchanged")
        return 200, {"status": status, "episodeId": result.episode_ids.get(draft.source_id), "isbn": isbn,
                     "book": "waiting"}

    _, body, _ = await idempotency.run_once(idempotency.scope_of(request), "/capture/isbn", key, work)
    return body


@router.get("/sources/books/scans/{episode_id}")
async def book_scan_result(episode_id: str, settings: Settings = Depends(get_settings)):
    """What became of one scan (the ``episodeId`` its ``POST /capture/isbn`` answered): ``{state: waiting}`` until the
    number resolves at the home, then ``{state: added, entityId, name, existing}`` — ``existing`` when the book was
    already in the bank (another edition, Apple Books, Goodreads). Not a Store domain: the Add reads it once or twice.
    404 for an id that is no scan."""
    out = await run_in_threadpool(books.scan_result, settings.memory_path, episode_id)
    if out is None:
        raise HTTPException(404, "no such scan")
    return out


@router.get("/sources/books")
async def books_summary(settings: Settings = Depends(get_settings)):
    """Book pages by status, scans waiting for their lookup, and whether Apple Books is on. Counts only."""
    memory_path = settings.memory_path
    out = await run_in_threadpool(books.counts, memory_path)
    waiting = await run_in_threadpool(lambda: sum(1 for f in books.pending(memory_path)
                                                  if (f.frontmatter or {}).get("origin") == books.SCAN_ORIGIN))
    return {**out, "waiting": waiting, "appleBooks": apple_books.load_settings(memory_path)["enabled"],
            "bank": memory_path.name}


class AppleBooksSettings(BaseModel):
    enabled: bool = False


@router.get("/sources/apple-books/settings", response_model=AppleBooksSettings)
async def get_apple_books_settings(settings: Settings = Depends(get_settings)):
    return AppleBooksSettings(**apple_books.load_settings(settings.memory_path))


@router.put("/sources/apple-books/settings", response_model=AppleBooksSettings, dependencies=_DEMO_GATE)
async def put_apple_books_settings(req: AppleBooksSettings, settings: Settings = Depends(get_settings)):
    """The person's switch. Off, the app stops reading and a sync is refused; what came in is kept."""
    out = await run_in_threadpool(apple_books.save_settings, settings.memory_path, enabled=req.enabled)
    return AppleBooksSettings(**out)


# No per-field length limits here (review of #600): one book with thousands of highlights or one very long highlight
# would 422 its whole 500-book request on every sync and block the rest. `apple_books.draft_for` trims each book —
# its text, its count of highlights, its body — so one book can never stop another.
class AppleBooksAnnotation(BaseModel):
    uuid: str | None = None
    createdAt: str | None = None
    selectedText: str | None = None
    note: str | None = None
    deleted: bool = False


class AppleBooksBook(BaseModel):
    assetId: str | None = None
    title: str | None = None
    author: str | None = None
    epubId: str | None = None
    contentType: int | None = None
    isFinished: bool = False
    isHidden: bool = False
    progress: float | None = None
    finishedAt: str | None = None
    lastOpenedAt: str | None = None
    addedAt: str | None = None
    annotations: list[AppleBooksAnnotation] = Field(default_factory=list)


class AppleBooksSyncRequest(BaseModel):
    books: list[AppleBooksBook] = Field(default_factory=list)


@router.post("/sources/apple-books/sync", dependencies=_DEMO_GATE)
async def sync_apple_books(req: AppleBooksSyncRequest, settings: Settings = Depends(get_settings)):
    """Stage the books the app read (one episode per book, edited in place as highlights grow), commit them, then
    make their pages. 409 while the person has Apple Books off; 413 above ``apple_books.MAX_BOOKS``."""
    memory_path = settings.memory_path
    if not apple_books.load_settings(memory_path)["enabled"]:
        raise HTTPException(409, APPLE_BOOKS_OFF)
    if len(req.books) > apple_books.MAX_BOOKS:
        raise HTTPException(413, f"at most {apple_books.MAX_BOOKS} books per sync")
    payload = req.model_dump()
    try:
        out = await run_in_threadpool(apple_books.sync, memory_path, payload, bank=memory_path.name)
    except apple_books.PayloadError as exc:
        raise HTTPException(422, str(exc))
    sync_state.record_sync(memory_path, apple_books.CHANNEL_ID, count=out["books"])
    paths = out.pop("paths")
    if paths:
        await folder_source.commit_paths_for(memory_path, paths, subject="Apple Books sync",
                                             trigger="capture/apple-books", channel=apple_books.CHANNEL_ID)
    applied = await book_jobs.apply_admitted(memory_path, author="user", trigger="capture/apple-books")
    return {**out, "pages": applied.get("pages_created", 0), "deferred": bool(applied.get("deferred")),
            "bank": memory_path.name}


class AppleBooksCover(BaseModel):
    assetId: str
    coverB64: str


class AppleBooksCoversRequest(BaseModel):
    covers: list[AppleBooksCover] = Field(default_factory=list)


@router.post("/sources/apple-books/covers", dependencies=_DEMO_GATE)
async def post_apple_books_covers(req: AppleBooksCoversRequest, settings: Settings = Depends(get_settings)):
    """The covers the app read from Apple Books' own cache on this Mac, as a small JPEG each (ruling 61): kept outside
    every bank, each book's page then names its picture. 409 while the person has Apple Books off; 422 for too many in
    one post; a picture that is not one is refused alone (``refused``)."""
    memory_path = settings.memory_path
    if not apple_books.load_settings(memory_path)["enabled"]:
        raise HTTPException(409, APPLE_BOOKS_OFF)
    try:
        out = await run_in_threadpool(book_covers.store, logo_service.bank_name(memory_path),
                                      [c.model_dump() for c in req.covers])
    except book_covers.PayloadError as exc:
        raise HTTPException(422, str(exc))
    applied = await book_jobs.apply_admitted(memory_path, author="cicada", trigger="capture/apple-books-covers")
    return {**out, "deferred": bool(applied.get("deferred"))}


class BookStatusUndo(BaseModel):
    claimId: str = Field(..., min_length=1, max_length=200)


@router.get("/entities/{entity_id}/book-status")
async def get_book_status(entity_id: str, settings: Settings = Depends(get_settings)):
    """The book's open status record for its page (`books.current_status`): not a Store domain, the card reads it on
    open. 404 for a page that is no book or has no status."""
    out = await run_in_threadpool(books.current_status, settings.memory_path, entity_id)
    if out is None:
        raise HTTPException(404, "no status on this page")
    return out


@router.post("/entities/{entity_id}/book-status/undo")
async def undo_book_status(entity_id: str, req: BookStatusUndo, settings: Settings = Depends(get_settings)):
    """"Not right" (ruling 61): the person takes a status record back; the one before it opens again, its happening goes
    with it, and nothing writes it again. Committed as the person's. 404 for no such record; 409 while Sleep holds the
    pages."""
    memory_path = Path(settings.memory_path)

    async def body():
        out = await asyncio.to_thread(books.undo_status, memory_path, entity_id, req.claimId)
        if out.get("paths"):
            await folder_source.commit_paths_for(memory_path, out["paths"], subject="Book status taken back",
                                                 trigger="books/undo", author="user", channel=book_jobs.CHANNEL)
        return out

    out = await write_admission.run_admitted(
        memory_path, body, refuse=lambda: SleepWriting("Sleep is updating your memory — try again in a moment."))
    if out.get("action") != "retracted":
        raise HTTPException(404, "no such status on this page")
    telemetry.record(telemetry.UsageEvent(
        kind="resolution", stage="feedback", bank=memory_path.name, invocations=0, billing="free",
        refs={"kind": "book-status", "claim_id": req.claimId, "predicate": books.STATUS_PREDICATE,
              "entity_id": entity_id, "verdict": "overruled"}))
    return {"status": out.get("status")}


async def _export_bytes(file: UploadFile) -> bytes:
    data = await file.read(goodreads_export.MAX_BYTES + 1)
    if len(data) > goodreads_export.MAX_BYTES:
        raise HTTPException(413, "That file is too large to be a Goodreads export.")
    return data


@router.post("/sources/goodreads/preview", dependencies=_DEMO_GATE)
async def preview_goodreads(file: UploadFile = File(...), settings: Settings = Depends(get_settings)):
    """What importing this export would bring, in counts. Reads the file, writes nothing, keeps nothing."""
    data = await _export_bytes(file)
    try:
        out = await run_in_threadpool(goodreads_export.preview, data)
    except goodreads_export.PayloadError as exc:
        raise HTTPException(422, str(exc))
    return {**out, "bank": settings.memory_path.name}


@router.post("/sources/goodreads/import", dependencies=_DEMO_GATE)
async def import_goodreads(file: UploadFile = File(...), settings: Settings = Depends(get_settings)):
    """Stage one episode per book in the export (a re-import edits in place), commit them, make the pages. 422 for a
    file that is not a Goodreads library export."""
    memory_path = settings.memory_path
    data = await _export_bytes(file)
    try:
        out = await run_in_threadpool(goodreads_export.stage, memory_path, data, bank=memory_path.name)
    except goodreads_export.PayloadError as exc:
        raise HTTPException(422, str(exc))
    sync_state.record_sync(memory_path, goodreads_export.CHANNEL_ID, count=out["books"])
    paths = out.pop("paths")
    if paths:
        await folder_source.commit_paths_for(memory_path, paths, subject="Goodreads import",
                                             trigger="capture/goodreads", channel=goodreads_export.CHANNEL_ID)
    applied = await book_jobs.apply_admitted(memory_path, author="user", trigger="capture/goodreads")
    return {**out, "pages": applied.get("pages_created", 0), "deferred": bool(applied.get("deferred")),
            "bank": memory_path.name}
