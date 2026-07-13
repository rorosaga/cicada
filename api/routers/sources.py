from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile
from loguru import logger
from pydantic import BaseModel

from api.config import Settings, get_settings
from api.models.schemas import (
    BookmarkSyncRequest,
    BookmarkSyncResponse,
    MediaSourceItem,
    NotesSyncRequest,
    NotesSyncResponse,
    SourceListResponse,
    SourceRssRequest,
    SourceSaveRequest,
    SourceSaveResponse,
    SourceUploadResponse,
)
from api.services import bookmark_sync, calendar_registry, feed_registry, media_ingestor, notes_sync
from api.services.media_ingestor import MAX_BATCH, RawItem

router = APIRouter()


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
    item = RawItem(url=url, tags=request.tags, note=request.note)
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


@router.post("/sources/upload", response_model=SourceUploadResponse)
async def upload_sources(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """Ingest a bookmarks/Takeout/URL-list export.

    Parses and dedups synchronously so counts come back immediately; enrichment
    and the episode/entity writes run in the background for large batches.
    """
    content = await file.read()
    filename = file.filename or ""
    logger.info(f"Sources upload: {filename} ({len(content)} bytes)")

    try:
        items, source_label, from_bookmark_file = media_ingestor.parse_upload(content, filename)
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
    fresh, duplicates = media_ingestor._dedup_items(items, idx)

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
    fresh, duplicates = media_ingestor._dedup_items(items, idx)
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


@router.post("/sources/sync-bookmarks", response_model=BookmarkSyncResponse)
async def sync_bookmarks(
    request: BookmarkSyncRequest | None = None,
    settings: Settings = Depends(get_settings),
):
    """Keyless bookmark sync: diff local Chrome/Safari bookmarks and ingest only new URLs.

    Body is optional. Pass base64 ``chromeDataB64``/``safariDataB64`` (inline
    data — what tests and a future companion-app file picker use) to sync
    against that data hermetically. Omit the body (or send neither field) to
    read the real local bookmark files instead — best-effort, offline-safe;
    see ``bookmark_sync.sync_from_local_files``.

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

    if chrome_data is not None or safari_data is not None:
        result = await bookmark_sync.sync_bookmarks(
            memory_path, chrome_data=chrome_data, safari_data=safari_data
        )
    else:
        result = await bookmark_sync.sync_from_local_files(memory_path)

    return BookmarkSyncResponse(**result)


@router.get("/sources", response_model=SourceListResponse)
async def list_sources(
    sort: str = Query("recent", pattern="^(recent|relevance)$"),
    settings: Settings = Depends(get_settings),
):
    """List saved media items with a relevance score.

    ``sort=recent`` (default, back-compat) orders newest-first; ``sort=relevance``
    orders by the §3.4 metric (``confidence x recency-decay x personal weight``)
    computed from each entity's frontmatter.
    """
    memory_path = settings.memory_path
    idx = media_ingestor.load_url_index(memory_path)

    items = []
    for entry in idx.values():
        entity_id = entry.get("media_entity_id", "")
        related_count = 0
        status = "active"
        tags: list[str] = []
        relevance = 0.0
        personal_relevance = None
        site = None
        channel = None
        entity_path = Path(memory_path) / "entities" / f"{entity_id}.md"
        if entity_path.exists():
            try:
                from api.services import markdown_parser

                fm = markdown_parser.parse(entity_path).frontmatter or {}
                related_count = len(fm.get("related") or [])
                status = fm.get("status", "active")
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
                tags=tags,
                status=status,
                related_count=related_count,
                relevance=round(relevance, 4),
                personal_relevance=personal_relevance,
            )
        )

    if sort == "relevance":
        items.sort(key=lambda i: (i.relevance, i.saved_at), reverse=True)
    else:
        items.sort(key=lambda i: i.saved_at, reverse=True)
    return SourceListResponse(items=items, total=len(items))


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

    return NotesSyncResponse(**result)
