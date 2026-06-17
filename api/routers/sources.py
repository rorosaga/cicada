from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile
from loguru import logger

from api.config import Settings, get_settings
from api.models.schemas import (
    MediaSourceItem,
    SourceListResponse,
    SourceRssRequest,
    SourceSaveRequest,
    SourceSaveResponse,
    SourceUploadResponse,
)
from api.services import media_ingestor
from api.services.media_ingestor import MAX_BATCH, RawItem

router = APIRouter()


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
            except Exception:
                pass
        items.append(
            MediaSourceItem(
                media_entity_id=entity_id,
                url=entry.get("url", ""),
                title=entry.get("title", ""),
                media_type=entry.get("media_type", "url"),
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
