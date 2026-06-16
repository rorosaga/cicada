from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from loguru import logger

from api.config import Settings, get_settings
from api.models.schemas import (
    MediaSourceItem,
    SourceListResponse,
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


@router.get("/sources", response_model=SourceListResponse)
async def list_sources(settings: Settings = Depends(get_settings)):
    """List saved media, newest first, straight from the URL index."""
    memory_path = settings.memory_path
    idx = media_ingestor.load_url_index(memory_path)

    items = []
    for entry in idx.values():
        entity_id = entry.get("media_entity_id", "")
        related_count = 0
        status = "active"
        tags: list[str] = []
        entity_path = Path(memory_path) / "entities" / f"{entity_id}.md"
        if entity_path.exists():
            try:
                from api.services import markdown_parser

                fm = markdown_parser.parse(entity_path).frontmatter or {}
                related_count = len(fm.get("related") or [])
                status = fm.get("status", "active")
                tags = fm.get("tags") or []
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
            )
        )

    items.sort(key=lambda i: i.saved_at, reverse=True)
    return SourceListResponse(items=items, total=len(items))
