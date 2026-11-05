"""Recordings and videos the person adds to search (meaning index 2; G195 stage 2; ``media_files``).

The app reads the file the person picked or dropped and posts only its derivatives — the words it transcribed on the
Mac, a video's kept frames — never the file's path or bytes. Nothing here fetches, embeds or reads a bank: the words
and frames are stored outside every bank and the background refresher (``image_index.start_refresh``) puts them in
the one meaning index later, outside Sleep. A demo bank refuses (``demo_guard``), like every capture door.
"""
from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import CamelModel
from api.services import demo_guard, git_service, image_index, media_files, media_pages

router = APIRouter()


class Segment(CamelModel):
    start: float = 0.0
    end: float | None = None
    text: str = ""


class MediaIn(CamelModel):
    name: str = Field("", max_length=1000)
    kind: str
    sha256: str
    size: int = 0
    duration_s: float | None = None
    language: str | None = None
    transcribed_by: str | None = Field(None, max_length=200)
    segments: list[Segment] = Field(default_factory=list, max_length=media_files.MAX_SEGMENTS)


class VoiceMemoIn(CamelModel):
    key: str
    name: str = Field("", max_length=1000)
    recorded_at: str
    sha256: str | None = None
    size: int = 0
    duration_s: float | None = None
    language: str | None = None
    transcribed_by: str | None = Field(None, max_length=200)
    segments: list[Segment] = Field(default_factory=list, max_length=media_files.MAX_SEGMENTS)


class VoiceMemosIn(CamelModel):
    memos: list[VoiceMemoIn] = Field(default_factory=list, max_length=20)
    #: Every recording the store holds now, sent only after a complete read: what it no longer lists is retired.
    present: list[str] | None = Field(None, max_length=50_000)


class FrameIn(CamelModel):
    t: float
    jpeg: str                         # base64 of a ≤ 640 × 400 JPEG


class FramesIn(CamelModel):
    frames: list[FrameIn] = Field(default_factory=list, max_length=media_files.MAX_FRAMES_PER_CALL)


def _not_demo(settings: Settings = Depends(get_settings)) -> None:
    if demo_guard.is_demo(settings.memory_path):
        raise HTTPException(status_code=409, detail=demo_guard.REFUSAL)


@router.post("/files/media", dependencies=[Depends(_not_demo)])
async def post_media(body: MediaIn, settings: Settings = Depends(get_settings)) -> dict:
    """One added file's description and the words the app transcribed (``segments``: start/end in seconds). The same
    file posted again (same sha256) replaces its words. 422 for anything out of shape, nothing written."""
    try:
        out = await run_in_threadpool(
            media_files.record_media, settings.memory_path, name=body.name, kind=body.kind, sha256=body.sha256,
            size=body.size, duration_s=body.duration_s, language=body.language, transcribed_by=body.transcribed_by,
            segments=[s.model_dump() for s in body.segments])
    except media_files.FileRefused as exc:
        raise HTTPException(422, str(exc)) from None
    image_index.start_refresh(settings.memory_path, delay_s=image_index.SETTLE_S)
    media_pages.start_sync(settings.memory_path, delay_s=media_pages.SETTLE_S)    # its page, moments later
    return out


@router.post("/files/voice-memos", dependencies=[Depends(_not_demo)])
async def post_voice_memos(body: VoiceMemosIn, settings: Settings = Depends(get_settings)) -> dict:
    """G43 — Voice Memos, read by the app: each recording's words with its id and its own date, then (after a complete
    read) the ids the store still lists. One item per recording; an edit re-stages it, a deletion is tombstoned.
    422 for anything out of shape."""
    out = {"added": 0, "updated": 0, "unchanged": 0, "retired": 0}
    for memo in body.memos:
        try:
            got = await run_in_threadpool(
                media_files.record_media, settings.memory_path, name=memo.name, kind="audio", sha256=memo.sha256,
                size=memo.size, duration_s=memo.duration_s, language=memo.language, source="voice_memos",
                source_key=memo.key, recorded_at=memo.recorded_at, transcribed_by=memo.transcribed_by,
                segments=[s.model_dump() for s in memo.segments])
        except media_files.FileRefused as exc:
            raise HTTPException(422, str(exc)) from None
        out[got["action"]] += 1
    if body.present is not None:
        out["retired"] = await run_in_threadpool(
            media_files.retire_source, settings.memory_path, "voice_memos", set(body.present))
    if any(out.values()):
        image_index.start_refresh(settings.memory_path, delay_s=image_index.SETTLE_S)
        media_pages.start_sync(settings.memory_path, delay_s=media_pages.SETTLE_S)
    return out


@router.post("/files/{file_id}/frames", dependencies=[Depends(_not_demo)])
async def post_frames(file_id: str, body: FramesIn, settings: Settings = Depends(get_settings)) -> dict:
    """A video's kept frames, at most 64 a call (each ≤ 640 × 400, ≤ 200 KB JPEG, with its time in seconds)."""
    frames = []
    for f in body.frames:
        try:
            frames.append((f.t, base64.b64decode(f.jpeg, validate=True)))
        except (binascii.Error, ValueError):
            raise HTTPException(422, "a frame isn't base64") from None
    try:
        out = await run_in_threadpool(media_files.record_frames, settings.memory_path, file_id, frames)
    except media_files.FileRefused as exc:
        raise HTTPException(422, str(exc)) from None
    image_index.start_refresh(settings.memory_path, delay_s=image_index.SETTLE_S)
    return out


@router.get("/files")
async def get_files(settings: Settings = Depends(get_settings)) -> dict:
    """The recordings and videos added to search, newest first (descriptions only, never their words)."""
    files = await run_in_threadpool(media_files.list_files, settings.memory_path)
    return {"files": [{k: v for k, v in f.items() if k != "sha256"} for f in files]}


@router.get("/files/{file_id}/transcript")
async def get_transcript(file_id: str, settings: Settings = Depends(get_settings)) -> dict:
    """A file's words with their times, drawn on its page at view time. They live outside every bank and are never
    kept in git or indexed as page text; the app's token reaches this, no agent door does. 404 for a file that is gone."""
    out = await run_in_threadpool(media_files.transcript, settings.memory_path, file_id)
    if out is None:
        raise HTTPException(404, "no such file")
    return out


@router.get("/files/{file_id}/frames/{ms}")
async def get_frame(file_id: str, ms: int, settings: Settings = Depends(get_settings)):
    """A kept frame (the thumbnail a frame hit names). 404 for one the file's own list doesn't name."""
    path = await run_in_threadpool(media_files.frame_file, settings.memory_path, file_id, ms)
    if path is None:
        raise HTTPException(404, "no such frame")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/files/{file_id}")
async def delete_file(file_id: str, settings: Settings = Depends(get_settings)) -> dict:
    """Take a file out of search: its words and frames go now, its vectors at the next refresh (moments later), and
    its page in one commit under the person's name (while Sleep holds the pages, as soon as it lets go)."""
    if not await run_in_threadpool(media_files.delete, settings.memory_path, file_id, by=git_service.USER_AUTHOR):
        raise HTTPException(404, "no such file")
    image_index.start_refresh(settings.memory_path, even_empty=True)
    if not demo_guard.is_demo(settings.memory_path):
        await run_in_threadpool(media_pages.sync_or_later, settings.memory_path)
    return {"deleted": file_id}
