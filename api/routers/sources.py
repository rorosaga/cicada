import asyncio
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool
from loguru import logger
from pydantic import BaseModel

from api.config import Settings, get_settings
from api.models.schemas import (
    BookmarkLeft,
    CamelModel,
    BookmarkRemoveRequest,
    BookmarkRemoveResponse,
    BookmarkSyncRequest,
    BookmarkSyncResponse,
    BookmarkTreePreview,
    MediaSourceItem,
    NotesSyncRequest,
    NotesSyncResponse,
    PaperSummary,
    ReadState,
    SafariTabsDevice,
    SafariTabsPreview,
    SafariTabsSyncRequest,
    SafariTabsSyncResponse,
    SavedWhyEditRequest,
    SavedWhyOptions,
    SavedWhyRecord,
    SavedWhyRequest,
    SavedWhyResponse,
    SavedWhySuggestRequest,
    SavedWhySuggestResponse,
    SourceChannel,
    SourceChannelsResponse,
    SourceListResponse,
    SourceOverview,
    SourceOverviewResponse,
    SourceRssRequest,
    SourceSaveRequest,
    SourceSaveResponse,
    SourceUploadCollection,
    SourceUploadPreview,
    SourceUploadResponse,
)
from api.services import (
    agent_commits,
    bank_index,
    bookmark_forget,
    bookmark_seen,
    bookmark_sync,
    calendar_registry,
    channel_items,
    channel_registry,
    entity_picture,
    feed_registry,
    media_ingestor,
    notes_sync,
    reading_asks,
    reading_hosts,
    reading_queue,
    reading_service,
    reading_settings,
    reading_walls,
    safari_tabs,
    saved_at as saved_at_service,
    saved_why,
    site_captures,
    source_overview,
    sync_service,
    sync_state,
    sync_ticker,
    watch_history,
    listening_history,
    write_admission,
)
from api.services.connectors import ADAPTERS
from api.services.media_ingestor import MAX_BATCH, RawItem
from api.routers.capture import refuse_capture_into_demo
from api.services.sleep_refusal import SleepWriting

router = APIRouter()

#: G141 capture-side track (R-CS15): every route below that takes something in
#: answers 409 while the demo bank is open, before its handler runs.
_DEMO_GATE = [Depends(refuse_capture_into_demo)]

# A media page in either state is a decision the person made (an inbox
# `remove`, G129 slice 2) or one the system already recorded (`dropped`,
# never resurfaced) — hidden from every read path, never deleted (CLAUDE.md's
# status lifecycle). Imported, not re-typed (F6): `source_overview` counts the
# `files` card's headline number on its own entity walk, and a card whose
# number disagrees with the list on its page is the defect this shares a
# predicate to prevent.
_HIDDEN_STATUSES = source_overview.HIDDEN_STATUSES


class FeedSubscribeRequest(BaseModel):
    url: str
    tags: list[str] | None = None


class FeedUnsubscribeRequest(BaseModel):
    url: str


class CalendarSubscribeRequest(BaseModel):
    url: str
    tags: list[str] | None = None


class CalendarUnsubscribeRequest(BaseModel):
    url: str


@router.post("/sources/save", response_model=SourceSaveResponse, dependencies=_DEMO_GATE)
async def save_source(
    request: SourceSaveRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
):
    """Save a single URL (menu-bar quick action, app paste field, MCP tool, a paired phone).

    G212: an ``Idempotency-Key`` (the phone's offline queue sends one) makes a resend the first answer, never a second
    write — no second episode and no second "Note on …" (``idempotency``)."""
    from api.services import idempotency

    async def work():
        answer = await _save_source(request, settings)
        return 200, answer.model_dump(by_alias=True, mode="json")

    _, body, _ = await idempotency.run_once(idempotency.scope_of(http_request), "/sources/save",
                                            http_request.headers.get(idempotency.HEADER), work)
    return body


async def _save_source(request: SourceSaveRequest, settings: Settings) -> SourceSaveResponse:
    import httpx

    url = request.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="URL must start with http:// or https://")

    memory_path = settings.memory_path
    item = RawItem(
        url=url,
        tags=request.tags,
        note=request.note,
        # G9 provenance. Without it these pages were the bank's only nil-origin
        # media, so the Sources page could count them but never attribute an
        # episode, a conversation or an entity to them. An MCP save also passes
        # a `session_id`, and `source_overview.source_key` reads that first, so
        # an agent's save still credits its harness row, not this one.
        origin="saved-link",
        session_id=request.session_id,
        harness=request.harness,
        project_dir=request.project_dir,
    )
    # G183: the link's metadata is fetched with no admission held; the page, index and episode are written and
    # committed inside the bank's write admission, and a save that finds Sleep holding the pages is refused (409)
    # with nothing written — a page written inside the window could ride the batch commit under Sleep's author
    # (fix round 2). The person saves again in a moment; the app shows the sentence.
    async with httpx.AsyncClient() as client:
        prepared = await media_ingestor.prepare_one(
            item, memory_path, client, media_ingestor.load_url_index(memory_path))
    return await write_admission.run_admitted(
        memory_path, lambda: _write_saved_source(memory_path, item, prepared, request),
        refuse=lambda: SleepWriting(SAVE_BUSY))


#: A single save while Sleep holds the pages (G183 round 2).
SAVE_BUSY = "Sleep is updating your memory — save the link again in a moment."


async def _write_saved_source(memory_path, item, prepared, request) -> SourceSaveResponse:
    idx = media_ingestor.load_url_index(memory_path)
    result = media_ingestor.write_prepared(prepared, memory_path, idx)
    media_ingestor.save_url_index(memory_path, idx)

    if result.status == "created":
        # G135 R-R12: this call used to omit `paths` and raise a TypeError that
        # the except below swallowed, so no single save was ever committed. An
        # MCP save (it carries a session id) is the agent's, not the person's.
        paths = ["sources/url_index.json", f"entities/{result.media_entity_id}.md",
                 f"episodes/{result.episode_id}.md"]
        by_agent = bool((request.session_id or "").strip())
        author = agent_commits.author_for(request.harness) if by_agent else "user"
        try:
            await media_ingestor._commit_media(
                memory_path, 1, paths, author=author,
                sessions=[request.session_id] if by_agent else None,
                trigger=f"mcp/{author}" if by_agent else "user/media_save",
            )
        except Exception as e:
            logger.warning(f"Media commit failed: {type(e).__name__}: {e}")

    # G140 Q-R10: a note for a link that is already saved is kept, not dropped
    # (G22's save-now-watch-later case). Committed alone, under whoever sent it
    # — the same author rule as the created branch above (G135 R-R12).
    note_episode_id = None
    if result.status == "duplicate":
        note = media_ingestor.write_note_episode(memory_path, item, result)
        if note is not None:
            note_episode_id, created_note = note
            if created_note:
                by_agent = bool((request.session_id or "").strip())
                author = agent_commits.author_for(request.harness) if by_agent else "user"
                trigger = f"mcp/{author}" if by_agent else "user/media_save"
                from api.services import git_service

                try:
                    await git_service.commit_paths(memory_path, git_service.build_commit_message(
                        f"Sources note {date.today().isoformat()}",
                        [f"episodes/{note_episode_id}.md: created (trigger: {trigger})"],
                        authors=[author], sessions=[request.session_id] if by_agent else None,
                    ), [f"episodes/{note_episode_id}.md"])
                except Exception as e:
                    logger.warning(f"Note commit failed: {type(e).__name__}: {e}")

    if result.status == "created":
        message = "Saved — it joins the graph after the next Sleep cycle"
    else:
        message = "Already saved — your note was kept" if note_episode_id else "Already saved"
    return SourceSaveResponse(
        status=result.status,
        media_entity_id=result.media_entity_id,
        episode_id=result.episode_id,
        title=result.title,
        media_type=result.media_type,
        thumbnail=result.thumbnail,
        message=message,
        note_episode_id=note_episode_id,
    )


@router.post("/sources/upload", response_model=None, dependencies=_DEMO_GATE)
async def upload_sources(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    preview: bool = Query(False),
    include_history: bool = Query(False),
    settings: Settings = Depends(get_settings),
) -> SourceUploadResponse | SourceUploadPreview:
    """Ingest — or, with ``?preview=true``, merely *describe* — a saved-content export.

    Parses and dedups synchronously so counts come back immediately; enrichment
    and the episode/entity writes run in the background for large batches.

    ``?preview=true`` (G71 §4.3) STAGES NOTHING: it runs the identical sniff and
    parse, then returns the collection/board/playlist breakdown with per-item
    counts so the import overlay can show the user what they are about to import
    before they commit to it. Nothing is cached server-side — Confirm re-posts
    the same file without the flag.

    ``?include_history=true`` opts watch and browsing history in (default off:
    history is not a save — G69). Brought in, it never becomes saved links: its
    rows go to ``watch_history`` (one episode per day of what was watched,
    committed alone) and only the saves go on to ``media_ingestor``.
    """
    content = await file.read()
    filename = file.filename or ""

    if preview:
        # Off the event loop: parsing a large export (a Takeout zip) is CPU-bound
        # and would otherwise stall the SSE stream, same reason /sources/channels
        # threadpools its origin scan.
        result = await run_in_threadpool(
            media_ingestor.preview_upload,
            content,
            filename,
            include_history=include_history,
        )
        logger.info(
            f"Sources preview: {filename} ({len(content)} bytes) -> "
            f"{result.platform}, {result.total} item(s)"
        )
        return SourceUploadPreview(
            recognized=result.recognized,
            platform=result.platform,
            total=result.total,
            collections=[SourceUploadCollection(**c) for c in result.collections],
            warnings=result.warnings,
            history_excluded=result.history_excluded,
            history_videos=result.history_videos,
            history_days=result.history_days,
        )

    logger.info(f"Sources upload: {filename} ({len(content)} bytes)")

    try:
        items, source_label, from_bookmark_file = media_ingestor.parse_upload(
            content, filename, include_history=include_history
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse {filename}: {e}")

    # Read at call time (not the import-time name): a whole archive of likes
    # runs past one batch and is imported MAX_BATCH at a time below.
    cap = media_ingestor.MAX_UPLOAD_ITEMS
    # G32: a Spotify play is never a save — a whole account's listening runs past the saves' cap, and becomes days.
    saves = sum(1 for it in items if not listening_history.is_play(it))
    if saves > cap:
        raise HTTPException(
            status_code=413,
            detail=f"{saves} items exceeds the {cap}-item import cap",
        )

    memory_path = settings.memory_path
    # History is experience, never a save (G71, 2026-10-16): its days are written first, alone.
    items, history_rows = watch_history.split(items)
    history_note = ""
    if history_rows:
        history = await watch_history.import_history(memory_path, history_rows, door="takeout",
                                                     trigger="user/watch_history")
        history_note = " " + watch_history.summary(history)
    # G32: Spotify's plays likewise — one listening day each, committed alone, never a saved link.
    items, play_rows = listening_history.split(items)
    if play_rows:
        listened = await listening_history.import_history(memory_path, play_rows, trigger="user/listening_history")
        history_note += " " + listening_history.summary(listened)
        history_rows = history_rows + play_rows
    idx = media_ingestor.load_url_index(memory_path)
    fresh, duplicates, backfilled = media_ingestor._dedup_items(items, idx)
    # G99d (Devin round 1, PR #26 finding 1): this router loads its OWN `idx`
    # object purely to compute `duplicates`/dispatch mode — `ingest_batch`
    # below does an independent reload, so a backfill mutated here must be
    # persisted explicitly or it is silently lost (this is the primary path
    # for backfilling dates on a full re-upload of an already-saved export).
    if backfilled:
        media_ingestor.save_url_index(memory_path, idx)

    # The upload's repeats (a video already saved, or one in two playlists of this export) go to `ingest_batch`
    # too: it appends each one's list to its page's `collections:` (owner 2026-10-19).
    if not fresh:
        if any((it.folder or "").strip() for it in items):
            await media_ingestor.ingest_batch(items, memory_path, from_bookmark_file=from_bookmark_file)
        return SourceUploadResponse(
            status="ok",
            episodes_created=0,
            duplicates_skipped=duplicates,
            message=("Nothing new — every URL was already saved" if items or not history_rows
                     else "No saved links in this file.") + history_note,
            source=source_label,
        )

    if len(fresh) <= media_ingestor._INLINE_ENRICH_LIMIT:
        created, _ = await media_ingestor.ingest_batch(
            items, memory_path, from_bookmark_file=from_bookmark_file
        )
        message = f"Saved {created} item(s) from {source_label}"
    else:
        background_tasks.add_task(
            media_ingestor.ingest_chunked,
            items,
            memory_path,
            from_bookmark_file=from_bookmark_file,
        )
        created = len(fresh)
        message = (
            f"Queued {created} item(s) from {source_label} — "
            "enrichment continues in the background"
        )

    return SourceUploadResponse(
        status="ok",
        episodes_created=created,
        duplicates_skipped=duplicates,
        message=message + history_note,
        source=source_label,
    )


@router.post("/sources/rss", response_model=SourceUploadResponse, dependencies=_DEMO_GATE)
async def ingest_rss(
    request: SourceRssRequest,
    settings: Settings = Depends(get_settings),
):
    """Ingest an RSS/Atom feed (Substack + most blogs) as media items.

    Keyless and offline-safe: pass ``feedXml`` (the parsed feed body) and it is
    ingested inline through the same dedup/episode/entity path as bookmarks — the
    Sleep pipeline absorbs the results with zero new consolidation code.
    ``feedUrl`` is only honored when ``CICADA_ALLOW_FEED_FETCH=1`` (network fetch
    is off by default; tests never hit it).
    """
    import os

    xml = (request.feed_xml or "").strip()

    if not xml and request.feed_url:
        if os.environ.get("CICADA_ALLOW_FEED_FETCH") != "1":
            raise HTTPException(
                status_code=422,
                detail="Live feed fetch is disabled. Set CICADA_ALLOW_FEED_FETCH=1 "
                "or pass feedXml directly.",
            )
        import httpx

        from api.services import net_guard

        try:
            # Every hop through the SSRF guard, as the feed poll (2026-10-23).
            async with httpx.AsyncClient(follow_redirects=True,
                                         event_hooks={"request": [net_guard.httpx_request_guard]}) as client:
                resp = await client.get(request.feed_url, timeout=10.0)
                resp.raise_for_status()
                xml = resp.text
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Could not fetch feed: {e}")

    if not xml:
        raise HTTPException(status_code=422, detail="Provide feedXml or feedUrl")

    memory_path = settings.memory_path
    items = media_ingestor.parse_rss(xml)
    if not items:
        raise HTTPException(status_code=422, detail="No feed items found — not a valid RSS/Atom feed?")

    # Bound the batch the same way /sources/upload does (sources.py:84-88): a
    # large or malicious feed must not trigger N enrichment fetches + 2N file
    # writes + a commit inline.
    if len(items) > MAX_BATCH:
        raise HTTPException(
            status_code=413,
            detail=f"{len(items)} feed items exceeds the {MAX_BATCH}-item batch cap",
        )

    # Carry request-level tags onto every item.
    if request.tags:
        for it in items:
            it.tags = sorted(set((it.tags or []) + request.tags))

    idx = media_ingestor.load_url_index(memory_path)
    fresh, duplicates, backfilled = media_ingestor._dedup_items(items, idx)
    # G99d (Devin round 1, PR #26 finding 1) — see the /sources/upload
    # handler's identical comment above.
    if backfilled:
        media_ingestor.save_url_index(memory_path, idx)
    if not fresh:
        return SourceUploadResponse(
            status="ok",
            episodes_created=0,
            duplicates_skipped=duplicates,
            message="Nothing new — every feed item was already saved",
            source="RSS Feed",
        )

    created, _ = await media_ingestor.ingest_batch(
        fresh, memory_path, from_bookmark_file=False
    )
    return SourceUploadResponse(
        status="ok",
        episodes_created=created,
        duplicates_skipped=duplicates,
        message=f"Saved {created} item(s) from the feed",
        source="RSS Feed",
    )


# One bookmark sync per bank at a time (round 4 phase A final review, finding
# 2). The app's × cancels only its own URLSession request: the route keeps
# enriching and writing, while the app forgets the run at once and its Sync
# now skips the file watcher's minimum interval. A second sync of the same
# file started then would load `url_index.json` before the first saved, so
# both would treat the same URLs as new — duplicate media episodes, an index
# holding only the last writer's entries, and the seen-set and removal diff
# run twice. The second caller gets a 409 rather than queueing, the
# `POST /maintenance/enrich-links` precedent: process-local on purpose (the
# backend is one uvicorn process), keyed by the resolved bank so a sync into
# another bank is never held up. A preview stages nothing and takes no lock.
_bookmark_sync_locks: dict[str, asyncio.Lock] = {}
BOOKMARK_SYNC_BUSY = "A bookmark sync is still finishing"


def _bookmark_sync_lock(memory_path: Path) -> asyncio.Lock:
    key = str(Path(memory_path).resolve())
    lock = _bookmark_sync_locks.get(key)
    if lock is None:
        lock = _bookmark_sync_locks[key] = asyncio.Lock()
    return lock


@router.post("/sources/sync-bookmarks", response_model=None, dependencies=_DEMO_GATE)
async def sync_bookmarks(
    request: BookmarkSyncRequest,
    preview: bool = Query(False),
    settings: Settings = Depends(get_settings),
) -> BookmarkSyncResponse | BookmarkTreePreview:
    """Keyless bookmark sync: diff Chrome/Safari bookmarks and ingest only new URLs.

    The body carries base64 ``chromeDataB64``/``safariDataB64``/``chromium`` —
    the files the companion app read itself (R1), or a test's inline bytes.
    The backend never reads a browser's file (the ``~/Library`` rail), so a
    request without a body, or with one that carries no bookmark data, is a
    422, never a local read. An unknown field is a 422 too
    (``extra="forbid"``). Round 4 phase A final review, finding 3: a
    pre-round-4 route dropped the new ``chromium`` field, saw no data, and
    read the Chrome file the person had not turned on — Chrome's profile is
    not behind Full Disk Access, so the backend could.

    409 while another bookmark sync of this bank is still running (see
    ``_bookmark_sync_locks``).

    ``?preview=true`` (R5) parses the supplied bytes and returns each source's
    folder tree with leaf counts WITHOUT ingesting anything — the same
    staging-free contract as ``/sources/upload?preview=true`` — so the app can
    show the folders before the user picks one.
    ``folders`` on the body narrows the sync to those folder paths (segment-
    boundary prefixes; ``""`` or omitted = everything, unchanged behaviour).
    ``chromium`` (round 4, C9) carries the Chromium-family browsers; 422 for an
    unknown browser, one sent twice, or bad base64.

    The "diff" is the existing ``url_index.json`` hash dedup in
    ``media_ingestor.ingest_batch`` — already-saved bookmarks are silently
    skipped, only unseen URLs become new episodes/media entities.
    """
    import base64

    memory_path = settings.memory_path

    chrome_data = None
    safari_data = None
    chromium: list[tuple[str, bytes]] = []
    if request.chrome_data_b64:
        try:
            chrome_data = base64.b64decode(request.chrome_data_b64)
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid chromeDataB64")
    if request.safari_data_b64:
        try:
            safari_data = base64.b64decode(request.safari_data_b64)
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid safariDataB64")
    # Round 4 (C9): the Chromium family. Each browser once, Chrome once across
    # both fields — a browser sent twice would ingest its file twice and write
    # two seen-sets for one channel.
    for entry in request.chromium or []:
        browser = entry.browser.strip().lower()
        if browser not in bookmark_sync.CHROMIUM_BROWSERS:
            raise HTTPException(status_code=422, detail=f"Unknown browser {entry.browser!r}")
        if (browser == "chrome" and chrome_data is not None) or any(b == browser for b, _ in chromium):
            raise HTTPException(status_code=422, detail=f"{browser} was sent twice")
        try:
            chromium.append((browser, base64.b64decode(entry.data_b64, validate=True)))
        except Exception:
            raise HTTPException(status_code=422, detail=f"Invalid dataB64 for {browser}")

    if chrome_data is None and safari_data is None and not chromium:
        if preview:
            raise HTTPException(status_code=422, detail="Preview needs chromeDataB64, safariDataB64 or chromium")
        raise HTTPException(status_code=422, detail="Send chromeDataB64, safariDataB64 or chromium")

    if preview:
        # Off the event loop, same reason as the upload preview: a plist the
        # size of a real Safari library is a CPU-bound parse and must not
        # stall the SSE stream.
        result = await run_in_threadpool(
            bookmark_sync.preview_bookmarks, chrome_data=chrome_data, safari_data=safari_data, chromium=chromium
        )
        return BookmarkTreePreview(**result)

    lock = _bookmark_sync_lock(memory_path)
    if lock.locked():
        raise HTTPException(status_code=409, detail=BOOKMARK_SYNC_BUSY)
    async with lock:
        result = await bookmark_sync.sync_bookmarks(
            memory_path,
            chrome_data=chrome_data,
            safari_data=safari_data,
            chromium=chromium,
            folders=request.folders,
        )

    # G62: the only durable trace that bookmark sync ever ran. `found` is the
    # number of bookmarks seen this pass (new + already-known), which is what
    # the channel row means by "412 bookmarks".
    # R4: one sync_state entry per browser actually synced — the catalog has
    # one tile per browser, and a channel must map to exactly one tile. The
    # legacy combined "bookmarks" key is read as a fallback, never written.
    for s in result.get("sources", []):
        channel = s.get("channel") or bookmark_sync.CHANNEL_BY_ORIGIN.get(s.get("origin", ""))
        if channel:
            # R-SR14: Safari's two counts ride the entry as `extra`, so the row can say them.
            extra = {k: int(s[k]) for k in bookmark_sync.PART_KEYS if k in s}
            sync_state.record_sync(memory_path, channel, count=int(s.get("found") or 0), extra=extra or None)

    return BookmarkSyncResponse(**result)


@router.post("/sources/sync-bookmarks/fresh", response_model=BookmarkSyncResponse, dependencies=_DEMO_GATE)
async def sync_bookmarks_fresh(
    request: BookmarkSyncRequest, settings: Settings = Depends(get_settings),
) -> BookmarkSyncResponse:
    """G191 — the early look (``bookmark_sync.fresh_preview``): the bookmarks in these bytes this bank does not hold
    yet, and whether each channel was ever synced, WITHOUT ingesting. The app asks why from this a moment after the
    save; the real ``/sources/sync-bookmarks`` follows with the same bytes. Read-only, so it takes no lock and is never
    a 409 for a sync in progress. 422 without bookmark data, for bad base64 or an unknown browser, as the sync."""
    import base64

    def decode(value: str | None, name: str) -> bytes | None:
        if not value:
            return None
        try:
            return base64.b64decode(value, validate=True)
        except Exception:
            raise HTTPException(status_code=422, detail=f"Invalid {name}")

    chrome_data = decode(request.chrome_data_b64, "chromeDataB64")
    safari_data = decode(request.safari_data_b64, "safariDataB64")
    chromium: list[tuple[str, bytes]] = []
    for entry in request.chromium or []:
        browser = entry.browser.strip().lower()
        if browser not in bookmark_sync.CHROMIUM_BROWSERS:
            raise HTTPException(status_code=422, detail=f"Unknown browser {entry.browser!r}")
        if (browser == "chrome" and chrome_data is not None) or any(b == browser for b, _ in chromium):
            raise HTTPException(status_code=422, detail=f"{browser} was sent twice")
        chromium.append((browser, decode(entry.data_b64, f"dataB64 for {browser}") or b""))
    if chrome_data is None and safari_data is None and not chromium:
        raise HTTPException(status_code=422, detail="Send chromeDataB64, safariDataB64 or chromium")
    # Off the event loop: a real Safari plist is a CPU-bound parse (the preview's reason).
    result = await run_in_threadpool(bookmark_sync.fresh_preview, settings.memory_path, chrome_data=chrome_data,
                                     safari_data=safari_data, chromium=chromium)
    return BookmarkSyncResponse(**result)


#: G191 — an answer that finds Sleep holding the pages.
SAVED_WHY_BUSY = "Sleep is updating your memory — your answer wasn't saved. Try again in a moment."


@router.get("/sources/saved-why/options", response_model=SavedWhyOptions)
async def saved_why_options(settings: Settings = Depends(get_settings)) -> SavedWhyOptions:
    """G191 — the one-tap answers to "What made you save this?": the four fixed reasons (v4), the bank the panel
    suggests a few from (`more`, v7) and the cap on the words; `projects` always empty. Deterministic — no model call."""
    return SavedWhyOptions.model_validate(await run_in_threadpool(saved_why.options, settings.memory_path))


@router.post("/sources/saved-why/suggest", response_model=SavedWhySuggestResponse)
async def saved_why_suggest(request: SavedWhySuggestRequest) -> SavedWhySuggestResponse:
    """G191 v7 — how close each reason in the bank is to the saved link's title and site, by the search model **only
    when it is already installed** (never a download, never a metered service): `basis: none` otherwise, and the
    panel ranks by the site and the person's past picks alone. Read-only, no model of a new kind, nothing logged."""
    return SavedWhySuggestResponse.model_validate(
        await run_in_threadpool(lambda: saved_why.model_scores(title=request.title, url=request.url)))


@router.post("/sources/saved-why", response_model=SavedWhyResponse, dependencies=_DEMO_GATE)
async def save_why(request: SavedWhyRequest, settings: Settings = Depends(get_settings)) -> SavedWhyResponse:
    """G191 — the person's answer to "What made you save this?", attached to that link's episode.

    The episode gains (or rewrites) its ``## Why it was saved`` section, scrubbed, with the time the answer was
    given beside the time the browser says the bookmark was made, and is queued for Sleep again; its frontmatter
    carries the structured answer (``saved_why``) that ``GET /sources`` serves as ``savedWhy``. 404 for a link that
    is not saved, 422 for an answer that names nothing or something unknown, 409 in a demo bank or while Sleep holds
    the pages. Committed alone, as the person (``Cicada-Author: user``). An optional ``at`` (review B1) is when the
    person answered, as the app recorded it — an answer the app held through a 409 keeps its own time; 422 when it is
    naive, in the future or more than a day old."""
    memory_path = settings.memory_path
    try:
        answer = saved_why.validate(memory_path, reasons=request.reasons, project=request.project, text=request.text)
        said_at = saved_why.client_at(request.at)
        saved_why.find_episode(memory_path, request.url)
    except saved_why.SavedWhyError as e:
        raise HTTPException(status_code=e.status, detail=str(e))

    async def write() -> dict:
        result = await run_in_threadpool(saved_why.attach, memory_path, url=request.url, answer=answer, at=said_at,
                                         added_at=request.added_at)
        if result["changed"]:
            from api.services import git_service

            try:
                await git_service.commit_paths(memory_path, saved_why.commit_message(result["episode_id"]),
                                               [f"episodes/{result['episode_id']}.md"])
            except Exception as e:  # noqa: BLE001 — a non-git bank (tests) keeps the answer
                logger.warning(f"saved-why commit failed: {type(e).__name__}: {e}")
        return result

    try:
        result = await write_admission.run_admitted(memory_path, write, refuse=lambda: SleepWriting(SAVED_WHY_BUSY))
    except saved_why.SavedWhyError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return _saved_why_response(result)


def _saved_why_response(result: dict) -> SavedWhyResponse:
    return SavedWhyResponse(episode_id=result["episode_id"], media_entity_id=result["media_entity_id"],
                            saved_why=SavedWhyRecord.model_validate(result["saved_why"]),
                            history=[SavedWhyRecord.model_validate(h) for h in result.get("history") or []])


@router.put("/sources/saved-why", response_model=SavedWhyResponse, dependencies=_DEMO_GATE)
async def edit_saved_why(request: SavedWhyEditRequest, settings: Settings = Depends(get_settings)) -> SavedWhyResponse:
    """G191 v3 — the person changes one of a bookmark's answers (the one given at ``at``) from its page in the app, or
    any client of this route. Its time and moment of saving are kept, ``editedAt`` says when it changed, every other
    answer is untouched; the section is rewritten, scrubbed and queued for Sleep, committed alone as the person. 404
    for a link not saved or no answer at ``at``; 422 for an empty or unknown answer; 409 in a demo bank or while Sleep
    holds the pages."""
    memory_path = settings.memory_path
    try:
        answer = saved_why.validate(memory_path, reasons=request.reasons, project=request.project, text=request.text,
                                    editing=True)
        saved_why.find_episode(memory_path, request.url)
    except saved_why.SavedWhyError as e:
        raise HTTPException(status_code=e.status, detail=str(e))

    async def write() -> dict:
        result = await run_in_threadpool(saved_why.edit, memory_path, url=request.url, at=request.at, answer=answer)
        if result["changed"]:
            from api.services import git_service

            try:
                await git_service.commit_paths(memory_path, saved_why.commit_message(result["episode_id"]),
                                               [f"episodes/{result['episode_id']}.md"])
            except Exception as e:  # noqa: BLE001 — a non-git bank (tests) keeps the answer
                logger.warning(f"saved-why edit commit failed: {type(e).__name__}: {e}")
        return result

    try:
        result = await write_admission.run_admitted(memory_path, write, refuse=lambda: SleepWriting(SAVED_WHY_BUSY))
    except saved_why.SavedWhyError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return _saved_why_response(result)


#: G191 v3 — a removal that finds Sleep holding the pages.
BOOKMARK_REMOVE_BUSY = "Sleep is updating your memory — the bookmark wasn't removed. Try again in a moment."


@router.post("/sources/bookmarks/remove", response_model=BookmarkRemoveResponse, dependencies=_DEMO_GATE)
async def remove_bookmark(request: BookmarkRemoveRequest,
                          settings: Settings = Depends(get_settings)) -> BookmarkRemoveResponse:
    """G191 v3 — forget a bookmark in Cicada on the person's click (the bookmark page's Remove, or any client of this
    route): its media page is archived — never deleted — and its episode stamped ``source_deleted_at``, the tombstone
    path; the person's answers stay. Committed alone as the person (trigger ``user/bookmark_remove``). The browser's
    own bookmark is the app's to remove (the backend never opens a browser). A link saved again later comes back.
    404 for a link Cicada does not hold, 422 for a URL that is not one, 409 in a demo bank or while Sleep holds the
    pages. Idempotent: a second call changes nothing."""
    memory_path = settings.memory_path
    try:
        saved_why.find_episode(memory_path, request.url)
    except saved_why.SavedWhyError as e:
        raise HTTPException(status_code=e.status, detail=str(e))

    async def write() -> dict:
        result = await run_in_threadpool(bookmark_forget.forget, memory_path, url=request.url)
        if result["paths"]:
            from api.services import git_service

            try:
                await git_service.commit_paths(memory_path, bookmark_forget.commit_message(result["paths"]),
                                               result["paths"])
            except Exception as e:  # noqa: BLE001 — a non-git bank (tests) keeps the change
                logger.warning(f"bookmark remove commit failed: {type(e).__name__}: {e}")
        return result

    try:
        result = await write_admission.run_admitted(memory_path, write,
                                                    refuse=lambda: SleepWriting(BOOKMARK_REMOVE_BUSY))
    except saved_why.SavedWhyError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return BookmarkRemoveResponse(episode_id=result["episode_id"], media_entity_id=result["media_entity_id"],
                                  status=result["status"])


@router.post("/sources/sync-safari-tabs", response_model=None, dependencies=_DEMO_GATE)
async def sync_safari_tabs(
    request: SafariTabsSyncRequest,
    preview: bool = Query(False),
    settings: Settings = Depends(get_settings),
) -> SafariTabsSyncResponse | SafariTabsPreview:
    """Import Safari's iCloud tabs from CloudTabs.db bytes the app read (R1).

    ``?preview=true`` parses and returns per-device counts WITHOUT ingesting
    anything — same staging-free contract as ``/sources/upload?preview=true``
    — so the app can show "iPhone · 202 tabs" before the user picks devices.
    Nothing is cached server-side; the import re-posts the same bytes.

    Unlike ``/sources/sync-bookmarks`` the body is REQUIRED: there is no
    local-file fallback for tabs (R1 — the backend never opens ``~/Library``
    for them), so a missing-FDA failure surfaces once, in the app.
    """
    import base64

    try:
        db = base64.b64decode(request.safari_tabs_db_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid safariTabsDbB64")
    wal = None
    if request.safari_tabs_wal_b64:
        try:
            wal = base64.b64decode(request.safari_tabs_wal_b64, validate=True)
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid safariTabsWalB64")

    if preview:
        # Off the event loop, same reason as the upload preview: the parse
        # is a temp-file write + SQLite scan and must not stall the SSE stream.
        try:
            snap = await run_in_threadpool(safari_tabs.load_tabs, db, wal)
        except safari_tabs.SafariTabsError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return SafariTabsPreview(
            total=snap.total,
            devices=[SafariTabsDevice(**d) for d in snap.devices],
            warnings=snap.warnings,
        )

    try:
        result = await safari_tabs.sync_tabs(
            settings.memory_path, db, wal=wal, devices=request.devices
        )
    except safari_tabs.SafariTabsError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return SafariTabsSyncResponse(**result)


def _description_excerpt(body: str, limit: int = 280) -> str | None:
    """First ~``limit`` chars of the page's ``## Description``, cut on a word
    boundary with an ellipsis — the Feed row's own copy of what the backfill
    or ingest-time OpenGraph stored (G102 R12), so the preview sheet renders
    instantly instead of fetching the entity first. Read from the page the
    endpoint already parses: no extra I/O, and the existing ``entities`` ETag
    component (max FILE mtime) already invalidates on the in-place edit that
    writes a description. ``None`` when the section is absent — never a guess
    from the title.

    Read through ``link_enrichment._extract_description_section`` rather than a
    bare ``parse_sections``: the ```claims fence is not an H2, so on every page
    whose ``## Description`` is the last section before it — every backfilled
    page (``_describe`` appends the block at the end), every G71
    ``/save <url> <reason>`` page, every recon-touched page — the raw section
    runs to EOF and the Feed row would carry the serialized claim YAML, which
    the preview sheet renders verbatim (final review H1; the same trap Task 1
    review H1 closed inside the backfill)."""
    from api.services.link_enrichment import _extract_description_section

    text = " ".join(_extract_description_section(body or "").split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{cut}…"


def _read_block(entry, fm_read, ask_rows, *, enabled: bool, allowed, wall=None, paused=()) -> ReadState | None:
    """G166: one link's ``read`` block — never raises (a bad row is no block)."""
    try:
        url = str(entry.get("url") or "")
        if not url:
            return None
        state = reading_service.read_state(
            url, fm_read, ask_rows.get(media_ingestor.url_hash(url)), enabled=enabled, wall=wall,
            allowed_sites=allowed, paused_sites=paused)
        return ReadState.model_validate(state) if state is not None else None
    except Exception:  # noqa: BLE001
        return None


def _saved_why_of(fm: dict) -> SavedWhyRecord | None:
    """G191: the source record's ``savedWhy`` from its episode's frontmatter — never raises."""
    try:
        shaped = saved_why.wire(fm.get("saved_why"), added_at=str(fm.get("added_at") or "") or None)
        return SavedWhyRecord.model_validate(shaped) if shaped is not None else None
    except Exception:  # noqa: BLE001
        return None


def _saved_why_history_of(fm: dict) -> list[SavedWhyRecord]:
    """G191 v3: every answer on the episode, oldest first — never raises."""
    try:
        records = saved_why.records_of(fm)
        if len(records) < 2:   # one answer is `savedWhy` itself; the list repeats it only beside others
            return []
        return [SavedWhyRecord.model_validate(h) for h in
                saved_why.history_wire(records, added_at=str(fm.get("added_at") or "") or None)]
    except Exception:  # noqa: BLE001
        return []


def _left_browser(left_by_hash: dict, raw_key: str, entry: dict) -> list[BookmarkLeft]:
    """G191 v4 — the source record's ``leftBrowser``: each browser the link left, named, with since when. The seen-set
    keys a link by the hash of the URL the browser holds, the index by its own key; both are looked up."""
    marks = left_by_hash.get(str(raw_key)) or left_by_hash.get(media_ingestor.url_hash(str(entry.get("url") or ""))) or []
    return [BookmarkLeft(browser=bookmark_sync.BROWSER_BY_CHANNEL.get(channel, channel), channel=channel, since=at)
            for channel, at in marks]


def _capture_thumbs(memory_path: Path) -> dict[str, str]:
    """G191 v3: the newest capture thumbnail of every captured page, as its route (`/explore/captures/...`) — one
    listing of `captures/` (only the pages someone explored have a folder), never a fetch. Never raises."""
    out: dict[str, str] = {}
    try:
        root = Path(memory_path) / site_captures.CAPTURES_DIR
        if not root.is_dir():
            return out
        for folder in root.iterdir():
            if not folder.is_dir() or folder.name.startswith("_"):
                continue
            for cap in site_captures.list_captures(memory_path, folder.name):
                thumb = cap.get("thumb") if isinstance(cap.get("thumb"), dict) else None
                if thumb and site_captures.thumb_file(memory_path, thumb.get("file")) is not None:
                    out[folder.name] = f"/explore/captures/{folder.name}/{cap['id']}/thumb"
                    break
    except Exception:  # noqa: BLE001
        return out
    return out


#: The `/sources` payload's shape version, folded into its ETag: `saved-why-2` added `savedWhyHistory`,
#: `lastSavedAt` and `captureThumb` (G191 v3); `saved-why-3` added `leftBrowser` (G191 v4) and the four reason labels;
#: `device-1` added `device` (G181 phase 3: which of the person's devices posted the save); `site-key-1` added
#: `siteKey` (owner 2026-10-20: the key every surface draws the item's own site mark under).
SHAPE = "site-key-1"


def _device_of(fm: dict) -> str | None:
    """G181 phase 3: the device id the save's episode records (``device_context``), or None for the server's own."""
    value = fm.get("device")
    return value.strip() if isinstance(value, str) and value.strip() else None


@router.get("/sources", response_model=SourceListResponse)
async def list_sources(
    request: Request,
    response: Response,
    sort: str = Query("recent", pattern="^(recent|relevance)$"),
    settings: Settings = Depends(get_settings),
):
    """List saved media items with a relevance score.

    ``sort=recent`` (default, back-compat) orders newest-first; ``sort=relevance``
    orders by the §3.4 metric (``confidence x recency-decay x personal weight``)
    computed from each entity's frontmatter.
    """
    memory_path = settings.memory_path
    # G166: the `reading` component (the ask store and the reading settings, both
    # outside the bank) is an ETag input, so an agent's outcome or a per-site
    # switch reaches the Feed's read state without a bank write.
    # `SHAPE` moves the tag once when the payload gains a field (`preview`), so a client holding the older body
    # re-reads it instead of keeping a 304'd copy without the field.
    # G191 v3: `captures` too — a new site capture gives a bookmark row its thumbnail.
    etag = sync_service.etag_for(memory_path, "sources", "episodes", "entities", "reading", "captures",
                                 extra=f"{sort}|{SHAPE}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    idx = media_ingestor.load_url_index(memory_path)
    reading_enabled = reading_settings.agent_enabled()
    reading_allowed = tuple(reading_settings.allowed_sites())
    try:
        ask_rows = {r["url_hash"]: r for r in reading_asks.all_rows(memory_path)}
    except ValueError:
        ask_rows = {}
    reading_paused = reading_queue.paused_sites(list(ask_rows.values()))
    # G191: the person's answer lives on the link's episode; one cached listing of `episodes/` answers every row.
    episode_fm = {f.stem: f.frontmatter for f in bank_index.files(memory_path, "episodes")}
    capture_thumbs = _capture_thumbs(memory_path)
    # G191 v4: the links that left a browser ride the bookmark seen-set (`sources/`, already an input of the ETag).
    left_by_hash = bookmark_seen.left_by_hash(memory_path)

    items = []
    for raw_key, entry in idx.items():
        # R-LS14: a paper's second canonical URL is an alias of its first; one
        # paper is one Feed row.
        if isinstance(entry, dict) and entry.get("alias_of"):
            continue
        entity_id = entry.get("media_entity_id", "")
        related_count = 0
        status = "active"
        enrichment_status = ""
        tags: list[str] = []
        relevance = 0.0
        personal_relevance = None
        site = None
        channel = None
        description: str | None = None
        about: list[str] = []
        origin: str | None = None
        folder: str | None = None
        provider: str | None = None
        duration_s: int | None = None
        kind: str | None = None
        paper: PaperSummary | None = None
        preview: str | None = None
        fm_read = None
        wall_page = None
        saved_page = False
        entity_path = Path(memory_path) / "entities" / f"{entity_id}.md"
        if entity_path.exists():
            try:
                from api.services import markdown_parser

                parsed = markdown_parser.parse(entity_path)
                fm = parsed.frontmatter or {}
                # Review of #372: a site key only where the media icon route would answer (one predicate).
                saved_page = channel_items.is_saved_link_page(fm)
                # G102 R12 — read the excerpt + `about` ids straight after the
                # parse, before any later field: this block is one `try` whose
                # `except: pass` would otherwise drop them if relevance or
                # `media` raised on an odd page.
                description = _description_excerpt(parsed.body)
                # The page's own picture as Cicada stores it (the person's upload, else the stored preview) — the
                # row never loads a provider's URL itself.
                preview = entity_picture.media_picture(entity_id, fm)
                about = [str(r) for r in (fm.get("related") or []) if str(r).strip()]
                # G124 R6 — the Sources page filters these items by source and
                # groups them by folder/board/device, straight from the page.
                origin = str(fm.get("origin") or "").strip() or None
                folder = str(fm.get("folder") or "").strip() or None
                related_count = len(fm.get("related") or [])
                status = fm.get("status", "active")
                fm_read = fm.get("read")
                # G166: is this a page Cicada's own reader could not read (and that holds no
                # words)? Decided from the page this loop already parsed — no second read.
                try:
                    st = entity_path.stat()
                    wall_page = reading_walls.page_for(
                        memory_path, entity_id, fm, parsed.body, mtime_ns=st.st_mtime_ns, size=st.st_size)
                except OSError:
                    wall_page = None
                # Track P R5 — what the person removed, and what enrichment
                # retired, must stop rendering. G129 slice 2's `remove`
                # ARCHIVES the media entity (`inbox_service.py:962-966`) and
                # never deletes it, so the page is still on disk and this read
                # path was still emitting a row for it — the answer read as
                # ignored. `enrichment_status: "junk"` is `link_enrichment`'s
                # permanent verdict on a consent or login interstitial
                # (`:886`); until now its only readers were the enrichment
                # scan (`:670`) and `link_recon` (`:145`), so a retired page
                # kept a Feed row. Filtered HERE, on the one read path both
                # the Feed and a source page's item list use, so the two
                # agree.
                enrichment_status = str(fm.get("enrichment_status") or "")
                tags = fm.get("tags") or []
                relevance = media_ingestor.compute_relevance(fm)
                pr = fm.get("personal_relevance")
                personal_relevance = pr if isinstance(pr, str) and pr else None
                # site/channel live in the entity frontmatter (media.site /
                # media.channel), not the url_index — read them back so the
                # FeedRow site line and site search filter actually work.
                media = fm.get("media") or {}
                if isinstance(media, dict):
                    s = media.get("site")
                    site = s if isinstance(s, str) and s else None
                    c = media.get("channel")
                    channel = c if isinstance(c, str) and c else None
                    # Track V (R15) — same rule as site/channel: the two video
                    # keys live on the page, never in `url_index.json`, so the
                    # Feed row can show a play badge and a duration pill
                    # without a second index to migrate.
                    pv = media.get("provider")
                    provider = pv if isinstance(pv, str) and pv else None
                    d = media.get("duration_s")
                    duration_s = d if isinstance(d, int) and not isinstance(d, bool) and d > 0 else None
                    # G133 — a paper page's byline, from its own `paper:`
                    # block (never the index), so the Feed can show and
                    # search authors, the arXiv id and the DOI.
                    k = media.get("kind")
                    kind = k if isinstance(k, str) and k else None
                    pp = fm.get("paper")
                    if kind == "paper" and isinstance(pp, dict):
                        paper = PaperSummary(
                            authors=[str(a) for a in (pp.get("authors") or [])][:8],
                            arxiv_id=pp.get("arxiv_id"), doi=pp.get("doi"),
                            published=pp.get("published"), venue=pp.get("venue") or pp.get("journal_ref"))
            except Exception:
                pass
        if status in _HIDDEN_STATUSES:
            continue
        if enrichment_status == "junk" and wall_page is None and not (
                isinstance(fm_read, dict) and fm_read.get("by") == "agent"):
            # Track P R5, amended 2026-09-30 (ruling 14): a retired interstitial stays hidden
            # unless it is a wall an agent can be asked to read, or an agent already read it —
            # the person can find it, ask for it, or see what the agent brought back.
            continue
        items.append(
            MediaSourceItem(
                media_entity_id=entity_id,
                url=entry.get("url", ""),
                title=entry.get("title", ""),
                media_type=entry.get("media_type", "url"),
                site=site,
                site_key=reading_hosts.mark_key(str(entry.get("url") or "")) if saved_page else None,
                channel=channel,
                thumbnail=entry.get("thumbnail"),
                preview=preview,
                saved_at=entry.get("saved_at", ""),
                content_saved_at=entry.get("content_saved_at"),
                saved_why=_saved_why_of(episode_fm.get(str(entry.get("episode_id") or "")) or {}),
                saved_why_history=_saved_why_history_of(episode_fm.get(str(entry.get("episode_id") or "")) or {}),
                last_saved_at=saved_why.last_saved(episode_fm.get(str(entry.get("episode_id") or "")) or {}),
                capture_thumb=capture_thumbs.get(entity_id),
                left_browser=_left_browser(left_by_hash, raw_key, entry),
                device=_device_of(episode_fm.get(str(entry.get("episode_id") or "")) or {}),
                tags=tags,
                status=status,
                related_count=related_count,
                relevance=round(relevance, 4),
                personal_relevance=personal_relevance,
                description=description,
                about=about,
                origin=origin,
                folder=folder,
                provider=provider,
                duration_s=duration_s,
                kind=kind,
                paper=paper,
                read=_read_block(
                    entry, fm_read, ask_rows, enabled=reading_enabled, allowed=reading_allowed,
                    wall=wall_page.wall if wall_page is not None and wall_page.waiting else None,
                    paused=reading_paused),
            )
        )

    # G99d — recency prefers the recovered true save date, falling back to
    # the ingest timestamp only when no source date was recoverable. This
    # deliberately reorders the Feed relative to the old ingest-only sort.
    # Parsed to a real instant (review finding) rather than compared as raw
    # strings — a bare content_saved_at date and a full saved_at timestamp
    # otherwise mix formats and tie-break by string length, not by time. See
    # `saved_at.sort_instant`'s docstring for the exact same-day rule.
    def _recency_key(i: MediaSourceItem) -> datetime:
        return saved_at_service.sort_instant(i.content_saved_at or i.saved_at)

    if sort == "relevance":
        items.sort(key=lambda i: (i.relevance, _recency_key(i)), reverse=True)
    else:
        items.sort(key=_recency_key, reverse=True)
    return SourceListResponse(items=items, total=len(items))


@router.get("/sources/due")
async def sources_due(settings: Settings = Depends(get_settings)):
    """G61, ruling 26 — the tracked sources due a re-check, and who works each: ``cicada`` (a public page, read on the
    Sleep tail) or ``agent`` (a login-walled page, or one that changed past what Cicada's own read can state — only the
    person's own agent reads it). Listing costs nothing: no fetch, no model. An agent row says why it cannot be worked
    yet (``waitingFor``: a Reading-the-web switch), else null."""
    from api.services import source_refresh

    memory_path = settings.memory_path
    items = await asyncio.to_thread(source_refresh.due, memory_path) or []
    totals = await asyncio.to_thread(source_refresh.tracked_count, memory_path)
    paused = source_refresh.paused_sites(memory_path)
    consent = source_refresh.Consent.load()
    rows = []
    for d in items:
        row = d.to_dict()
        waiting = source_refresh.agent_refusal(d, consent) if d.checker == source_refresh.AGENT else None
        if waiting is None and d.checker == source_refresh.AGENT and d.site in paused:
            waiting = f"{d.site} asked for a sign-in; paused for a week"
        row["waitingFor"] = waiting
        rows.append(row)
    agent_rows = [r for r in rows if r["checker"] == source_refresh.AGENT]
    return {
        "counts": {"tracked": totals["tracked"], "dead": totals["dead"], "due": len(rows),
                   "cicada": len(rows) - len(agent_rows), "agent": len(agent_rows),
                   "agentReady": sum(1 for r in agent_rows if r["waitingFor"] is None)},
        "items": rows[:200],
        "total": len(rows),
    }


class WhereToCheckRow(CamelModel):
    entity_id: str
    entity_name: str
    entity_type: str = ""
    who: str
    agent: str | None = None
    added_by: str
    ref: str
    kind: str
    predicate: str | None = None
    added_at: str = ""
    proposed: bool = False


class WhereToCheckResponse(CamelModel):
    items: list[WhereToCheckRow]
    total: int


@router.get("/sources/where-to-check", response_model=WhereToCheckResponse)
async def sources_where_to_check(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    """G61 (owner 2026-10-26) — every page's sources the person or one of their agents added, newest first, for the
    Sources page's "Reading in your browser" area (``source_roster``). Engine-free, never fetches, writes nothing; the
    adds and removals go through the page's own source routes, so each store keeps its one writer. On demand, not a
    Store domain: the ETag (entities, plus the shape) serves the area's in-memory copy (``AddedSourcesModel``), so there
    is no ``VersionVector`` mapping."""
    from api.services import source_roster

    memory_path = settings.memory_path
    etag = sync_service.etag_for(memory_path, "entities", extra=source_roster.SHAPE)
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    rows = await run_in_threadpool(source_roster.roster, memory_path)
    return WhereToCheckResponse(items=[WhereToCheckRow(**r) for r in rows[:source_roster.LIMIT]], total=len(rows))


@router.get("/sources/overview", response_model=SourceOverviewResponse)
async def sources_overview(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    """One card per memory source (G124) — the Sources page's grid.

    Same ETag recipe as ``/sources/channels`` (R7): the payload is computed
    from episodes, entities, ``sync_state.json``, the feed/calendar registries
    and the url index — all inside the ``sources``/``episodes``/``entities``
    components — plus the Telegram flag and connector credentials, which are
    config facts no component sees. Off the event loop for the same reason
    ``/origins`` and ``/sources/channels`` are: a cold ``bank_index`` re-parses
    every frontmatter.
    """
    memory_path = settings.memory_path
    connectors_connected = {cid: adapter.is_connected() for cid, adapter in ADAPTERS.items()}
    connector_tag = ",".join(f"{k}:{v}" for k, v in sorted(connectors_connected.items()))
    # Sources v4: `photos` too — a Messages face carries its chat photo's hash (`messages_photos`, outside the bank).
    # marks-2: `siteIcons` too — a saved row's faces put sites with a cached own icon first (`VersionVector` maps it to
    # `.sourcesOverview` in the same PR).
    feed_fetch = feed_registry.fetch_allowed()

    def _build() -> list[dict]:
        channels = channel_registry.build_channels(
            memory_path,
            telegram_enabled=settings.telegram_enabled,
            connectors_connected=connectors_connected,
            feed_fetch_allowed=feed_fetch,
        )
        return source_overview.build_overview(memory_path, channels=channels)

    # Source page speed (2026-10-29): the ETag and the build share one listing per directory (`request_scans`).
    with sync_ticker.request_scans(memory_path):
        etag = sync_service.etag_for(
            memory_path, "sources", "episodes", "entities", "photos", "siteIcons",
            extra=(f"{source_overview.SHAPE}|telegram:{settings.telegram_enabled}|connectors:{connector_tag}"
                   f"|feeds:{feed_fetch}"),
        )
        if (early := sync_service.conditional(request, response, etag)) is not None:
            return early
        rows = await run_in_threadpool(_build)
    return SourceOverviewResponse(sources=[SourceOverview(**r) for r in rows])


@router.get("/sources/channels", response_model=SourceChannelsResponse)
async def list_source_channels(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    """Every capture channel + whether it is actually connected (G62).

    The Capture page renders its "Connected" list straight from this. State is
    derived from what is on disk (feeds/calendars registries, sync_state.json,
    origin counts, the saved-URL index) plus the Telegram env flag — nothing
    here reflects the result of the last button press, so the page is correct
    on a cold launch.
    """
    memory_path = settings.memory_path
    connectors_connected = {cid: adapter.is_connected() for cid, adapter in ADAPTERS.items()}
    # `telegram_enabled` and connector credentials are config/secrets facts, not
    # filesystem-in-the-bank ones: configuring a bot token, or connecting an
    # account, flips a channel to "connected" without touching any component
    # below, so without them in the ETag a warm client 304s and keeps showing
    # "not connected" forever. `CHANNELS_SHAPE` covers the other case: the body
    # changing for the same files (a new always-listed row), round 4 final review #3.
    connector_tag = ",".join(f"{k}:{v}" for k, v in sorted(connectors_connected.items()))
    # The feed gate is an env fact too: a feed row is connected only while feeds are fetched (2026-10-23).
    feed_fetch = feed_registry.fetch_allowed()
    with sync_ticker.request_scans(memory_path):   # one listing per directory for ETag and build (2026-10-29)
        etag = sync_service.etag_for(
            memory_path, "sources", "episodes", "entities",
            extra=(f"{channel_registry.CHANNELS_SHAPE}|telegram:{settings.telegram_enabled}"
                   f"|connectors:{connector_tag}|feeds:{feed_fetch}"),
        )
        if (early := sync_service.conditional(request, response, etag)) is not None:
            return early
        # Off the event loop: `build_channels` runs the same full episode+entity
        # origin scan `/origins` does, which on a cold `bank_index` re-parses every
        # frontmatter inline and would stall the SSE stream (see `/origins`).
        channels = await run_in_threadpool(
            channel_registry.build_channels,
            memory_path,
            telegram_enabled=settings.telegram_enabled,
            connectors_connected=connectors_connected,
            feed_fetch_allowed=feed_fetch,
        )
    return SourceChannelsResponse(channels=[SourceChannel(**c) for c in channels])


@router.get("/sources/channels/{channel_id}/items")
async def list_channel_items(
    channel_id: str,
    request: Request,
    response: Response,
    offset: int = Query(0, ge=0),
    limit: int = Query(channel_items.LIMIT_DEFAULT, ge=1, le=channel_items.LIMIT_MAX),
    q: str | None = Query(None, max_length=channel_items.Q_MAX),
    settings: Settings = Depends(get_settings),
):
    """What a channel brought in, by name (G161): each item's title and day, newest first, a page at a time.

    source-page-v3 (owner 2026-10-29): `q` narrows the page to what a source page's one search finds — titles, a
    chat's name, a saved link's host, and the words of the episodes behind the rows where the words index has them
    (`channel_items._search`); the body carries `all` (the channel's whole count) and `latest` (the day the newest
    item came in). The query rides only the ETag's digest, never a log.

    Derived at read from the set the row's count means (`channel_items`' docstring names it per channel) —
    titles only, never a body; for Contacts, the matched page's name only. Engine-free and read-only, and NOT a
    Store domain: the app keeps each page in memory and revalidates it with this ETag, like provenance. The
    ETag rides `sources` (the notes index, the bookmark seen-set and the url index live there), `episodes` and
    `entities`, plus the shape, the channel and the page asked for.
    """
    memory_path = settings.memory_path
    if not channel_items.known(memory_path, channel_id):
        raise HTTPException(status_code=404, detail="Unknown channel")
    # Source page speed (2026-10-29): the ETag and the read share one listing per directory (the worker thread copies
    # this context) — the SSE walk's when its gate allows (`request_scans`), so a list reads only its own source's files.
    with sync_ticker.request_scans(memory_path):
        # Sources v4 (review of #358): `photos` too — a Messages row carries its chat photo's hash.
        etag = sync_service.etag_for(
            memory_path, "sources", "episodes", "entities", "photos",
            extra=f"{channel_items.SHAPE}|{channel_id}|{offset}|{limit}|{q or ''}",
        )
        if (early := sync_service.conditional(request, response, etag)) is not None:
            return early
        # Off the event loop: a cold `bank_index` re-parses every frontmatter (the `/sources/channels` reason).
        page = await run_in_threadpool(channel_items.items, memory_path, channel_id, offset=offset, limit=limit, q=q)
    if page is None:
        raise HTTPException(status_code=404, detail="Unknown channel")
    return page


_OWN_ICON_SEMAPHORE = asyncio.Semaphore(4)


@router.get("/sources/saved/{media_entity_id}/site-icon")
async def get_saved_link_site_icon(media_entity_id: str, request: Request, settings: Settings = Depends(get_settings)):
    """A saved link's own site icon (owner ruling 2026-10-19), for its row in a list the person opened. Asked of that
    site only — its homepage's declared icons (or a CDN URL that page names), then `/apple-touch-icon.png` and
    `/favicon.ico` (discovery amended 2026-10-20), then a declared SVG drawn to a PNG by `svg_raster` (2026-10-20; SVG
    is never served) — never of an icon service, so no one else learns what was saved; behind `CICADA_ALLOW_LOGO_FETCH`; cached under `logos/<bank>/sites/own/`
    with misses. 404 means "draw the monogram": a page that is not a live saved link, a walled or private host, the
    gate off, a miss. Nothing calls this but the app's row; Sleep never does."""
    memory_path = settings.memory_path
    site = await run_in_threadpool(channel_items.saved_link_site, memory_path, media_entity_id)
    return await _serve_own_site_icon(request, memory_path, site)


@router.get("/sources/saved/episodes/{episode_id}/site-icon")
async def get_saved_episode_site_icon(episode_id: str, request: Request, settings: Settings = Depends(get_settings)):
    """The same icon for a saved link Sleep has not made a page of yet (owner 2026-10-20): a Waiting row of a bookmark
    or a saved post is an episode, so it is asked by the episode's id. The site is read from THAT episode's own `url`,
    only for a live episode of a saved source (`channel_items.saved_episode_site`); the same gate, the same per-site
    cache and the same fetch as the saved-link route. 404 means "draw the monogram"."""
    memory_path = settings.memory_path
    site = await run_in_threadpool(channel_items.saved_episode_site, memory_path, episode_id)
    return await _serve_own_site_icon(request, memory_path, site)


async def _serve_own_site_icon(request: Request, memory_path, site: str | None):
    """Serve `site`'s own icon from the cache, asking the site at most once (`ensure_own_site_icon`, ≤ 4 at a time)."""
    import hashlib

    from fastapi.responses import FileResponse

    from api.services import logo_service

    if not site:
        raise HTTPException(404, "no icon for this site")
    bank = logo_service.own_site_bank(logo_service.bank_name(memory_path))
    path = logo_service.cached_path(bank, site)
    if path is None:
        async with _OWN_ICON_SEMAPHORE:
            path = await logo_service.ensure_own_site_icon(memory_path, site)
    if path is None or not path.exists():
        raise HTTPException(404, "no icon for this site")
    stat = path.stat()
    etag = '"' + hashlib.sha1(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()[:16] + '"'
    headers = {"ETag": etag, "Cache-Control": "max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    types = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp", "ico": "image/x-icon"}
    return FileResponse(path, media_type=types.get(path.suffix.lstrip("."), "application/octet-stream"), headers=headers)


@router.get("/sources/watch-history/days/{episode_id}")
async def get_watched_day(episode_id: str, request: Request, response: Response,
                          settings: Settings = Depends(get_settings)):
    """Sources v4 — one watched day's videos, in the order watched (`channel_items.watched_day`): what the person sees
    when they open that day. Read from the day's own record; nothing fetched, no model (ruling 30). Not a Store domain:
    the app keeps it in memory and revalidates with this ETag (`episodes` for the day, `sources`+`entities` for which
    videos are also saved)."""
    memory_path = settings.memory_path
    etag = sync_service.etag_for(memory_path, "sources", "episodes", "entities",
                                 extra=f"{channel_items.SHAPE}|day|{episode_id}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    day = await run_in_threadpool(channel_items.watched_day, memory_path, episode_id)
    if day is None:
        raise HTTPException(status_code=404, detail="Not a watched day")
    # The app's wire is camelCase (`CamelModel`'s rule), spelled here for the two keys that have an underscore.
    return {**day, "videos": [{("videoId" if k == "video_id" else "mediaEntityId" if k == "media_entity_id" else k): v
                               for k, v in video.items()} for video in day["videos"]]}


_STILL_SEMAPHORE = asyncio.Semaphore(4)


@router.get("/sources/watch-history/days/{episode_id}/videos/{video_id}/thumbnail")
async def get_watched_video_thumbnail(episode_id: str, video_id: str, request: Request,
                                      settings: Settings = Depends(get_settings)):
    """Sources v4 (owner direction 2026-10-19, `storage.md`) — a watched YouTube video's still, for its row in the day
    the person opened. Keyed by that day (review of #358): the id must be one THIS day records
    (`channel_items.day_has_video`, one file read), and the backend asks YouTube's own thumbnail host for that id only;
    behind `CICADA_ALLOW_LOGO_FETCH`, through the ToS rail, cached outside every bank
    (`media_preview.ensure_video_still`), at most four at a time. 404 = no picture. Sleep never calls it; no model
    reads history."""
    from api.services import media_preview

    memory_path = settings.memory_path
    async with _STILL_SEMAPHORE:
        known = await run_in_threadpool(channel_items.day_has_video, memory_path, episode_id, video_id)
        if not known:
            raise HTTPException(404, "no picture for this video")
        path = await media_preview.ensure_video_still(memory_path, video_id)
    return _serve_still(request, path)


@router.get("/sources/saved/{media_entity_id}/still")
async def get_saved_video_still(media_entity_id: str, request: Request, settings: Settings = Depends(get_settings)):
    """marks-2 (owner 2026-10-20: "none of the YouTube stuff shows thumbnails, just low-res YouTube logos") — a saved
    YouTube video's still, for its row in a list the person opened: the same fetch and cache as a watched video's
    (`media_preview.ensure_video_still`, YouTube's own thumbnail host, that id only, behind `CICADA_ALLOW_LOGO_FETCH`,
    outside every bank), keyed by the id THIS page's own URL names (`channel_items.media_video_id`) — never an id the
    request names. 404 = no picture (the row keeps its site mark). Sleep never calls it."""
    from api.services import media_preview

    memory_path = settings.memory_path
    async with _STILL_SEMAPHORE:
        video_id = await run_in_threadpool(channel_items.media_video_id, memory_path, media_entity_id)
        if not video_id:
            raise HTTPException(404, "no picture for this video")
        path = await media_preview.ensure_video_still(memory_path, video_id)
    return _serve_still(request, path)


def _serve_still(request: Request, path):
    import hashlib

    from fastapi.responses import FileResponse

    from api.services import media_preview

    if path is None or not path.exists():
        raise HTTPException(404, "no picture for this video")
    stat = path.stat()
    etag = '"' + hashlib.sha1(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()[:16] + '"'
    headers = {"ETag": etag, "Cache-Control": "max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    media_type = media_preview.MEDIA_TYPES.get(path.suffix.lstrip("."), "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers=headers)


@router.get("/sources/messages/chats/{conversation}/sittings")
async def get_messages_chat_sittings(conversation: str, request: Request, response: Response,
                                     settings: Settings = Depends(get_settings)):
    """Sources v4 (review of #358) — one Messages chat's sittings, newest first: what its row opens to
    (`channel_items.chat_sittings`; each sitting opens in the Reader). Titles only, never a body; not a Store domain —
    the app keeps it in memory and revalidates with this ETag."""
    memory_path = settings.memory_path
    etag = sync_service.etag_for(memory_path, "episodes", extra=f"{channel_items.SHAPE}|sittings|{conversation}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    page = await run_in_threadpool(channel_items.chat_sittings, memory_path, conversation)
    if page is None:
        raise HTTPException(status_code=404, detail="No such chat")
    return page


@router.get("/sources/messages/chats/{conversation}/photo")
async def get_messages_chat_photo(conversation: str, request: Request, settings: Settings = Depends(get_settings)):
    """Sources v4 — the photo a ticked Messages chat shares, as that chat's face on the Sources row and in its list
    (owner 2026-10-19: "the profile pictures of the chats that have contributed"). The bytes the app already posted
    (`messages_photos`, outside every bank, never sent anywhere); nothing is fetched. 404 = draw the monogram: an id
    that is not a chat hash, a chat not ticked, or no photo stored."""
    import hashlib

    from fastapi.responses import FileResponse

    from api.services import logo_service, messages_photos, messages_source

    memory_path = settings.memory_path
    if not messages_source.CONVERSATION_ID_RE.match(conversation or ""):
        raise HTTPException(404, "no photo for this chat")
    ticked = await run_in_threadpool(messages_photos.ticked_chats, memory_path)
    entry = messages_photos.read_meta(logo_service.bank_name(memory_path)).get(conversation)
    if conversation not in ticked or not isinstance(entry, dict):
        raise HTTPException(404, "no photo for this chat")
    path = messages_photos.photo_path(logo_service.bank_name(memory_path), conversation, str(entry.get("ext") or "png"))
    if path is None or not path.is_file():
        raise HTTPException(404, "no photo for this chat")
    etag = '"' + hashlib.sha1(f"{conversation}:{entry.get('sha')}".encode()).hexdigest()[:16] + '"'
    headers = {"ETag": etag, "Cache-Control": "max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    media_type = "image/jpeg" if path.suffix == ".jpg" else "image/png"
    return FileResponse(path, media_type=media_type, headers=headers)


# --- Feed subscriptions (registry + poll) -----------------------------------


@router.get("/sources/feeds")
async def list_feed_subscriptions(settings: Settings = Depends(get_settings)):
    """List every subscribed RSS/Atom feed (``<memory>/feeds.yaml``)."""
    feeds = feed_registry.list_feeds(settings.memory_path)
    return {"feeds": feeds, "total": len(feeds)}


@router.post("/sources/feeds", dependencies=_DEMO_GATE)
async def subscribe_feed(
    request: FeedSubscribeRequest,
    settings: Settings = Depends(get_settings),
):
    """Subscribe to an RSS/Atom feed. Idempotent — re-subscribing dedups on URL."""
    url = request.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="URL must start with http:// or https://")
    record = feed_registry.subscribe_feed(settings.memory_path, url, tags=request.tags)
    return record


@router.delete("/sources/feeds")
async def unsubscribe_feed(
    request: FeedUnsubscribeRequest,
    settings: Settings = Depends(get_settings),
):
    """Unsubscribe a feed by URL."""
    removed = feed_registry.unsubscribe_feed(settings.memory_path, request.url)
    if not removed:
        raise HTTPException(status_code=404, detail="Feed not subscribed")
    return {"status": "ok", "url": request.url}


@router.post("/sources/poll-feeds", dependencies=_DEMO_GATE)
async def poll_feeds(settings: Settings = Depends(get_settings)):
    """Run a poll cycle over every subscribed feed.

    Respects the same network gate as ``POST /sources/rss``
    (``CICADA_ALLOW_FEED_FETCH=1``) — with no fetch allowed, this is a no-op
    that reports ``skipped_no_network`` instead of hitting the network.
    """
    memory_path = settings.memory_path
    result = await feed_registry.poll_feeds(memory_path)
    return result


# --- Calendar subscriptions (registry + poll) --------------------------------


@router.get("/sources/calendars")
async def list_calendar_subscriptions(settings: Settings = Depends(get_settings)):
    """List every subscribed calendar (``<memory>/calendars.yaml``)."""
    calendars = calendar_registry.list_calendars(settings.memory_path)
    return {"calendars": calendars, "total": len(calendars)}


@router.post("/sources/calendars", dependencies=_DEMO_GATE)
async def subscribe_calendar(
    request: CalendarSubscribeRequest,
    settings: Settings = Depends(get_settings),
):
    """Subscribe to an ICS/webcal calendar. Idempotent — re-subscribing dedups
    on the normalized URL. ``webcal://`` is normalized to ``https://``."""
    url = request.url.strip()
    if not url.lower().startswith(("http://", "https://", "webcal://")):
        raise HTTPException(
            status_code=422, detail="URL must start with http://, https://, or webcal://"
        )
    record = calendar_registry.subscribe_calendar(settings.memory_path, url, tags=request.tags)
    return record


@router.delete("/sources/calendars")
async def unsubscribe_calendar(
    request: CalendarUnsubscribeRequest,
    settings: Settings = Depends(get_settings),
):
    """Unsubscribe a calendar by URL."""
    removed = calendar_registry.unsubscribe_calendar(settings.memory_path, request.url)
    if not removed:
        raise HTTPException(status_code=404, detail="Calendar not subscribed")
    return {"status": "ok", "url": request.url}


@router.post("/sources/poll-calendars", dependencies=_DEMO_GATE)
async def poll_calendars(settings: Settings = Depends(get_settings)):
    """Run a poll cycle over every subscribed calendar.

    Respects the same network gate as feed polling
    (``CICADA_ALLOW_FEED_FETCH=1``) — with no fetch allowed, this is a no-op
    that reports ``skipped_no_network`` instead of hitting the network. Each
    VEVENT within the ingestion window becomes one episode (dedup: UID +
    DTSTART + SEQUENCE).
    """
    memory_path = settings.memory_path
    result = await calendar_registry.poll_calendars(memory_path)
    return result


# --- Apple Notes one-way import ----------------------------------------------


@router.post("/sources/sync-notes", response_model=NotesSyncResponse, dependencies=_DEMO_GATE)
async def sync_notes(
    request: NotesSyncRequest,
    settings: Settings = Depends(get_settings),
):
    """Keyless Apple Notes sync: parse the dump the app read from Notes.app
    (``notesDump``) and write an episode for every new or modified note. The
    backend never reads Notes itself — the ``~/Library`` rail — so a request
    without a dump is a 422, never a local read.

    Dedup/re-emit is entirely ``memory/sources/notes_index.json`` (keyed on
    note id, last-seen modification date): unchanged notes are skipped,
    edited notes re-emit an updated episode, brand-new notes emit a fresh one.
    """
    memory_path = settings.memory_path

    result = await notes_sync.sync_notes(memory_path, dump=request.notes_dump)

    sync_state.record_sync(memory_path, "notes", count=int(result.get("total") or 0))

    return NotesSyncResponse(**result)
