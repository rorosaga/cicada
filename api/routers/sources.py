from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool
from loguru import logger
from pydantic import BaseModel

from api.config import Settings, get_settings
from api.models.schemas import (
    BookmarkSyncRequest,
    BookmarkSyncResponse,
    BookmarkTreePreview,
    MediaSourceItem,
    NotesSyncRequest,
    NotesSyncResponse,
    SafariTabsDevice,
    SafariTabsPreview,
    SafariTabsSyncRequest,
    SafariTabsSyncResponse,
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
    bookmark_sync,
    calendar_registry,
    channel_registry,
    feed_registry,
    media_ingestor,
    notes_sync,
    safari_tabs,
    saved_at as saved_at_service,
    source_overview,
    sync_service,
    sync_state,
)
from api.services.connectors import ADAPTERS
from api.services.media_ingestor import MAX_BATCH, RawItem

router = APIRouter()

# A media page in either state is a decision the person made (an inbox
# `remove`, G129 slice 2) or one the system already recorded (`dropped`,
# never resurfaced) — hidden from every read path, never deleted (CLAUDE.md's
# status lifecycle).
_HIDDEN_STATUSES = {"archived", "dropped"}


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


@router.post("/sources/save", response_model=SourceSaveResponse)
async def save_source(
    request: SourceSaveRequest,
    settings: Settings = Depends(get_settings),
):
    """Save a single URL (menu-bar quick action, app paste field, MCP tool)."""
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
    idx = media_ingestor.load_url_index(memory_path)
    async with httpx.AsyncClient() as client:
        result = await media_ingestor.ingest_one(item, memory_path, client, idx)
    media_ingestor.save_url_index(memory_path, idx)

    if result.status == "created":
        try:
            await media_ingestor._commit_media(memory_path, 1)
        except Exception as e:
            logger.warning(f"Media commit failed: {type(e).__name__}: {e}")

    message = (
        "Saved — it joins the graph after the next Sleep cycle"
        if result.status == "created"
        else "Already saved"
    )
    return SourceSaveResponse(
        status=result.status,
        media_entity_id=result.media_entity_id,
        episode_id=result.episode_id,
        title=result.title,
        media_type=result.media_type,
        thumbnail=result.thumbnail,
        message=message,
    )


@router.post("/sources/upload", response_model=None)
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

    ``?include_history=true`` opts a TikTok export's Browsing History in (default
    off: ambient exhaust, not saves — G69).
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

    if len(items) > MAX_BATCH:
        raise HTTPException(
            status_code=413,
            detail=f"{len(items)} items exceeds the {MAX_BATCH}-item batch cap",
        )

    memory_path = settings.memory_path
    idx = media_ingestor.load_url_index(memory_path)
    fresh, duplicates, backfilled = media_ingestor._dedup_items(items, idx)
    # G99d (Devin round 1, PR #26 finding 1): this router loads its OWN `idx`
    # object purely to compute `duplicates`/dispatch mode — `ingest_batch`
    # below does an independent reload, so a backfill mutated here must be
    # persisted explicitly or it is silently lost (this is the primary path
    # for backfilling dates on a full re-upload of an already-saved export).
    if backfilled:
        media_ingestor.save_url_index(memory_path, idx)

    if not fresh:
        return SourceUploadResponse(
            status="ok",
            episodes_created=0,
            duplicates_skipped=duplicates,
            message="Nothing new — every URL was already saved",
            source=source_label,
        )

    if len(fresh) <= media_ingestor._INLINE_ENRICH_LIMIT:
        created, _ = await media_ingestor.ingest_batch(
            fresh, memory_path, from_bookmark_file=from_bookmark_file
        )
        message = f"Saved {created} item(s) from {source_label}"
    else:
        background_tasks.add_task(
            media_ingestor.ingest_batch,
            fresh,
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
        message=message,
        source=source_label,
    )


@router.post("/sources/rss", response_model=SourceUploadResponse)
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

        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
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


@router.post("/sources/sync-bookmarks", response_model=None)
async def sync_bookmarks(
    request: BookmarkSyncRequest | None = None,
    preview: bool = Query(False),
    settings: Settings = Depends(get_settings),
) -> BookmarkSyncResponse | BookmarkTreePreview:
    """Keyless bookmark sync: diff Chrome/Safari bookmarks and ingest only new URLs.

    Body is optional. Pass base64 ``chromeDataB64``/``safariDataB64`` (inline
    data — what the companion app sends after reading the files itself, R1,
    and what tests use) to sync against that data hermetically. Omit the body
    (or send neither field) to read the real local bookmark files instead —
    best-effort, offline-safe; see ``bookmark_sync.sync_from_local_files``.
    That fallback exists for ``curl``/tests and is never the app's path: the
    launchd backend has no Full Disk Access.

    ``?preview=true`` (R5) parses the supplied bytes and returns each source's
    folder tree with leaf counts WITHOUT ingesting anything — the same
    staging-free contract as ``/sources/upload?preview=true`` — so the app can
    show the folders before the user picks one. Inline data is required for a
    preview; there is nothing to preview from the local-file fallback.
    ``folders`` on the body narrows the sync to those folder paths (segment-
    boundary prefixes; ``""`` or omitted = everything, unchanged behaviour).

    The "diff" is the existing ``url_index.json`` hash dedup in
    ``media_ingestor.ingest_batch`` — already-saved bookmarks are silently
    skipped, only unseen URLs become new episodes/media entities.
    """
    import base64

    memory_path = settings.memory_path

    chrome_data = None
    safari_data = None
    if request is not None:
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

    if preview:
        if chrome_data is None and safari_data is None:
            raise HTTPException(status_code=422, detail="Preview needs chromeDataB64 and/or safariDataB64")
        # Off the event loop, same reason as the upload preview: a plist the
        # size of a real Safari library is a CPU-bound parse and must not
        # stall the SSE stream.
        result = await run_in_threadpool(
            bookmark_sync.preview_bookmarks, chrome_data=chrome_data, safari_data=safari_data
        )
        return BookmarkTreePreview(**result)

    if chrome_data is not None or safari_data is not None:
        result = await bookmark_sync.sync_bookmarks(
            memory_path,
            chrome_data=chrome_data,
            safari_data=safari_data,
            folders=request.folders if request is not None else None,
        )
    else:
        result = await bookmark_sync.sync_from_local_files(memory_path)

    # G62: the only durable trace that bookmark sync ever ran. `found` is the
    # number of bookmarks seen this pass (new + already-known), which is what
    # the channel row means by "412 bookmarks".
    # R4: one sync_state entry per browser actually synced — the catalog has
    # one tile per browser, and a channel must map to exactly one tile. The
    # legacy combined "bookmarks" key is read as a fallback, never written.
    for s in result.get("sources", []):
        channel = s.get("channel") or bookmark_sync.CHANNEL_BY_ORIGIN.get(s.get("origin", ""))
        if channel:
            sync_state.record_sync(memory_path, channel, count=int(s.get("found") or 0))

    return BookmarkSyncResponse(**result)


@router.post("/sources/sync-safari-tabs", response_model=None)
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
    etag = sync_service.etag_for(memory_path, "sources", "episodes", "entities", extra=sort)
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    idx = media_ingestor.load_url_index(memory_path)

    items = []
    for entry in idx.values():
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
        entity_path = Path(memory_path) / "entities" / f"{entity_id}.md"
        if entity_path.exists():
            try:
                from api.services import markdown_parser

                parsed = markdown_parser.parse(entity_path)
                fm = parsed.frontmatter or {}
                # G102 R12 — read the excerpt + `about` ids straight after the
                # parse, before any later field: this block is one `try` whose
                # `except: pass` would otherwise drop them if relevance or
                # `media` raised on an odd page.
                description = _description_excerpt(parsed.body)
                about = [str(r) for r in (fm.get("related") or []) if str(r).strip()]
                # G124 R6 — the Sources page filters these items by source and
                # groups them by folder/board/device, straight from the page.
                origin = str(fm.get("origin") or "").strip() or None
                folder = str(fm.get("folder") or "").strip() or None
                related_count = len(fm.get("related") or [])
                status = fm.get("status", "active")
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
            except Exception:
                pass
        if status in _HIDDEN_STATUSES or enrichment_status == "junk":
            continue
        items.append(
            MediaSourceItem(
                media_entity_id=entity_id,
                url=entry.get("url", ""),
                title=entry.get("title", ""),
                media_type=entry.get("media_type", "url"),
                site=site,
                channel=channel,
                thumbnail=entry.get("thumbnail"),
                saved_at=entry.get("saved_at", ""),
                content_saved_at=entry.get("content_saved_at"),
                tags=tags,
                status=status,
                related_count=related_count,
                relevance=round(relevance, 4),
                personal_relevance=personal_relevance,
                description=description,
                about=about,
                origin=origin,
                folder=folder,
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
    etag = sync_service.etag_for(
        memory_path, "sources", "episodes", "entities",
        extra=f"overview|telegram:{settings.telegram_enabled}|connectors:{connector_tag}",
    )
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early

    def _build() -> list[dict]:
        channels = channel_registry.build_channels(
            memory_path,
            telegram_enabled=settings.telegram_enabled,
            connectors_connected=connectors_connected,
        )
        return source_overview.build_overview(memory_path, channels=channels)

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
    # "not connected" forever.
    connector_tag = ",".join(f"{k}:{v}" for k, v in sorted(connectors_connected.items()))
    etag = sync_service.etag_for(
        memory_path, "sources", "episodes", "entities",
        extra=f"telegram:{settings.telegram_enabled}|connectors:{connector_tag}",
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
    )
    return SourceChannelsResponse(channels=[SourceChannel(**c) for c in channels])


# --- Feed subscriptions (registry + poll) -----------------------------------


@router.get("/sources/feeds")
async def list_feed_subscriptions(settings: Settings = Depends(get_settings)):
    """List every subscribed RSS/Atom feed (``<memory>/feeds.yaml``)."""
    feeds = feed_registry.list_feeds(settings.memory_path)
    return {"feeds": feeds, "total": len(feeds)}


@router.post("/sources/feeds")
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


@router.post("/sources/poll-feeds")
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


@router.post("/sources/calendars")
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


@router.post("/sources/poll-calendars")
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


@router.post("/sources/sync-notes", response_model=NotesSyncResponse)
async def sync_notes(
    request: NotesSyncRequest | None = None,
    settings: Settings = Depends(get_settings),
):
    """Keyless Apple Notes sync: enumerate local Notes via ``osascript`` and
    write an episode for every new or modified note.

    Body is optional. Pass an inline ``notesDump`` (the raw delimited dump —
    what tests and a future companion-app path use) to sync against that data
    hermetically. Omit the body to read the real local Notes.app via
    ``osascript`` instead — never exercised in tests.

    Dedup/re-emit is entirely ``memory/sources/notes_index.json`` (keyed on
    note id, last-seen modification date): unchanged notes are skipped,
    edited notes re-emit an updated episode, brand-new notes emit a fresh one.
    """
    memory_path = settings.memory_path

    if request is not None and request.notes_dump is not None:
        result = await notes_sync.sync_notes(memory_path, dump=request.notes_dump)
    else:
        result = await notes_sync.sync_from_local_notes(memory_path)

    sync_state.record_sync(memory_path, "notes", count=int(result.get("total") or 0))

    return NotesSyncResponse(**result)
