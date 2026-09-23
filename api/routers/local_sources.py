"""Local sources the APP reads and the backend parses (G133 folders, G134 note-takers).

The app owns the disk — a folder bookmark, another app's SQLite under
``~/Library`` — and posts bytes or a whitelisted projection here; the backend
never opens either (R-F1, R-N1). Every route is bearer-gated like the rest of
the API; none is on the Telegram / OAuth-callback exemption list.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import (
    FolderListResponse,
    FolderRecord,
    FolderRegisterRequest,
    FolderRemoveResponse,
    FolderSyncRequest,
    FolderSyncResponse,
    FolderUpdateRequest,
)
from api.services import folder_source, local_refs, sync_state

router = APIRouter()


def _record(folder: dict) -> FolderRecord:
    return FolderRecord(**folder, channel_id=folder_source.channel_id(folder["id"]))


@router.get("/sources/folders", response_model=FolderListResponse)
async def list_folders(settings: Settings = Depends(get_settings)):
    return FolderListResponse(folders=[_record(f) for f in folder_source.list_folders(settings.memory_path)])


@router.post("/sources/folders", response_model=FolderRecord)
async def register_folder(req: FolderRegisterRequest, settings: Settings = Depends(get_settings)):
    memory_path = settings.memory_path
    device = local_refs.current_device_id()
    name = req.label if req.project_name is None else req.project_name
    project_id, created = await run_in_threadpool(
        folder_source.ensure_project, memory_path, name, path=req.path, device=device)
    folder = folder_source.register(
        memory_path, label=req.label, path=req.path, include=req.include, exclude=req.exclude,
        authorship=[r.model_dump() for r in req.authorship] if req.authorship is not None else None,
        project_id=project_id or None, device=device)
    paths = [f"sources/{folder_source.FOLDERS_FILENAME}"]
    if project_id:
        paths.append(f"entities/{project_id}.md")
    await folder_source.commit_paths_for(
        memory_path, paths, subject=f"Folder added ({folder['label']})", trigger="user/companion_app")
    return _record(folder)


@router.put("/sources/folders/{folder_id}", response_model=FolderRecord)
async def update_folder(folder_id: str, req: FolderUpdateRequest, settings: Settings = Depends(get_settings)):
    folder = folder_source.update(
        settings.memory_path, folder_id, label=req.label,
        authorship=[r.model_dump() for r in req.authorship] if req.authorship is not None else None)
    if folder is None:
        raise HTTPException(404, f"No folder {folder_id!r}")
    await folder_source.commit_paths_for(
        settings.memory_path, [f"sources/{folder_source.FOLDERS_FILENAME}"],
        subject=f"Folder settings ({folder['label']})", trigger="user/companion_app")
    return _record(folder)


@router.delete("/sources/folders/{folder_id}", response_model=FolderRemoveResponse)
async def remove_folder(folder_id: str, settings: Settings = Depends(get_settings)):
    if not folder_source.remove(settings.memory_path, folder_id):
        raise HTTPException(404, f"No folder {folder_id!r}")
    await folder_source.commit_paths_for(
        settings.memory_path, [f"sources/{folder_source.FOLDERS_FILENAME}"],
        subject="Folder removed", trigger="user/companion_app")
    return FolderRemoveResponse(removed=True)


@router.post("/sources/folders/{folder_id}/sync", response_model=FolderSyncResponse)
async def sync_folder(
    folder_id: str,
    req: FolderSyncRequest,
    preview: bool = Query(False),
    settings: Settings = Depends(get_settings),
):
    """Stage one batch of files the app read (R-F1). ``?preview=true`` counts
    and writes nothing — the add-folder sheet shows it before anything lands."""
    memory_path = settings.memory_path
    folder = folder_source.get_folder(memory_path, folder_id)
    if folder is None:
        raise HTTPException(404, f"No folder {folder_id!r}")
    if len(req.files) > folder_source.MAX_BATCH_FILES:
        raise HTTPException(413, f"at most {folder_source.MAX_BATCH_FILES} files per request")
    if sum(len(f.content_b64) for f in req.files) * 3 // 4 > folder_source.MAX_BATCH_BYTES:
        raise HTTPException(413, "batch too large — send fewer files per request")
    files = [folder_source.IncomingFile(f.relpath, f.mtime, f.sha256, f.content_b64) for f in req.files]
    out = await run_in_threadpool(folder_source.sync, memory_path, folder, files, req.deleted, preview=preview)
    staged = out.pop("_staged")
    out.pop("_texts")
    if not preview:
        attempted = len(files)
        if attempted and len(out["errors"]) == attempted:
            sync_state.record_error(memory_path, folder_source.channel_id(folder_id),
                                    f"{attempted} file(s) could not be read")
        else:
            sync_state.record_sync(memory_path, folder_source.channel_id(folder_id),
                                   count=folder_source.live_file_count(memory_path, folder_id))
        await folder_source.commit_paths_for(
            memory_path, (staged.paths if staged else []) + [f"sources/{folder_source.FOLDERS_FILENAME}"],
            subject=f"Folder sync ({folder['label']})", trigger="folder/sync")
    return FolderSyncResponse(**out)
