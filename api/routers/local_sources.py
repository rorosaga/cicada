"""Local sources the APP reads and the backend parses (G133 folders, G134 note-takers).

The app owns the disk — a folder bookmark, another app's SQLite under
``~/Library`` — and posts bytes or a whitelisted projection here; the backend
never opens either (R-F1, R-N1). Every route is bearer-gated like the rest of
the API; none is on the Telegram / OAuth-callback exemption list.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
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
    WisprFlowCaptureResponse,
    WisprFlowPayload,
    WisprFlowSettings,
)
from api.services import folder_source, local_refs, paper_metadata, papers, sync_state, wispr_flow
from api.routers.capture import refuse_capture_into_demo

router = APIRouter()

#: G141 capture-side track (R-CS15): every route below that takes something in
#: answers 409 while the demo bank is open, before its handler runs.
_DEMO_GATE = [Depends(refuse_capture_into_demo)]


def _record(folder: dict) -> FolderRecord:
    return FolderRecord(**folder, channel_id=folder_source.channel_id(folder["id"]))


@router.get("/sources/folders", response_model=FolderListResponse)
async def list_folders(settings: Settings = Depends(get_settings)):
    return FolderListResponse(folders=[_record(f) for f in folder_source.list_folders(settings.memory_path)])


async def _reapply_authorship(memory_path, folder: dict) -> list[str]:
    """F2-back R-B6/R-B7: re-derive every existing episode's authorship from the
    folder's current rules, then bring its papers' why-claims in line — through
    `papers.reconcile`, which reads the authorship each episode now declares.
    While Sleep runs the paper step waits (R-LS17): the folder is flagged
    `papers_pending` and the next sync or the Sleep tail re-parses it. Returns
    the bank-relative paths written, for the caller's one commit."""
    moved = await run_in_threadpool(folder_source.reapply_authorship, memory_path, folder["id"])
    paths = list(moved["paths"])
    if not moved["touched"]:
        return paths
    from api.services import sleep_cycle

    if sleep_cycle.get_sleep_state().status == "running":
        folder_source.set_flags(memory_path, folder["id"], papers_pending=True)
        return paths + [f"sources/{folder_source.FOLDERS_FILENAME}"]
    current = folder_source.get_folder(memory_path, folder["id"]) or folder
    report = await run_in_threadpool(papers.reconcile, memory_path, current, touched=moved["touched"], tombstoned={})
    return paths + list(report["paths"])


@router.post("/sources/folders", response_model=FolderRecord, dependencies=_DEMO_GATE)
async def register_folder(req: FolderRegisterRequest, settings: Settings = Depends(get_settings)):
    memory_path = settings.memory_path
    from api.services import sleep_cycle

    if sleep_cycle.get_sleep_state().status == "running":
        # L final review (finding 5): `ensure_project` writes a project page —
        # `paths:` onto one Stage 5 may be rewriting, or a new page Sleep's
        # `git add -A` would sweep under the model's name. Adding a folder is a
        # person's click, so asking again in a minute is the honest answer.
        raise HTTPException(409, "Cicada is tidying up your memory right now — add the folder again in a minute.")
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
    trigger = "user/companion_app"
    if req.authorship is not None:
        # A re-pick that carries rules is a rules change too (R-B6); a new folder has nothing to move.
        moved = await _reapply_authorship(memory_path, folder)
        if moved:
            paths += moved
            trigger = folder_source.AUTHORSHIP_TRIGGER
    await folder_source.commit_paths_for(
        memory_path, paths, subject=f"Folder added ({folder['label']})", trigger=trigger,
        channel=folder_source.channel_id(folder["id"]))
    return _record(folder)


@router.put("/sources/folders/{folder_id}", response_model=FolderRecord, dependencies=_DEMO_GATE)
async def update_folder(folder_id: str, req: FolderUpdateRequest, settings: Settings = Depends(get_settings)):
    memory_path = settings.memory_path
    folder = folder_source.update(
        memory_path, folder_id, label=req.label,
        authorship=[r.model_dump() for r in req.authorship] if req.authorship is not None else None)
    if folder is None:
        raise HTTPException(404, f"No folder {folder_id!r}")
    paths = [f"sources/{folder_source.FOLDERS_FILENAME}"]
    trigger = "user/companion_app"
    if req.authorship is not None:
        # F2-back R-B6: the rules and the episodes they relabel land in ONE `user` commit.
        paths += await _reapply_authorship(memory_path, folder)
        trigger = folder_source.AUTHORSHIP_TRIGGER
    await folder_source.commit_paths_for(
        memory_path, paths, subject=f"Folder settings ({folder['label']})", trigger=trigger,
        channel=folder_source.channel_id(folder_id))
    return _record(folder)


@router.delete("/sources/folders/{folder_id}", response_model=FolderRemoveResponse)
async def remove_folder(folder_id: str, settings: Settings = Depends(get_settings)):
    if not folder_source.remove(settings.memory_path, folder_id):
        raise HTTPException(404, f"No folder {folder_id!r}")
    await folder_source.commit_paths_for(
        settings.memory_path, [f"sources/{folder_source.FOLDERS_FILENAME}"],
        subject="Folder removed", trigger="user/companion_app")
    return FolderRemoveResponse(removed=True)


@router.post("/sources/folders/{folder_id}/sync", response_model=FolderSyncResponse, dependencies=_DEMO_GATE)
async def sync_folder(
    folder_id: str,
    req: FolderSyncRequest,
    background: BackgroundTasks,
    preview: bool = Query(False),
    resolve: bool = Query(False),
    settings: Settings = Depends(get_settings),
):
    """Stage one batch of files the app read (R-F1). ``?preview=true`` counts
    and writes nothing — the add-folder sheet shows it before anything lands.
    ``?resolve=true`` (the first add, or "Sync now") also fetches paper
    details from the arXiv and Crossref APIs after the response (R-LS18)."""
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
    texts = out.pop("_texts")
    if preview:
        # The sheet shows how many papers a folder holds before anything lands
        # — counted from the posted bytes, nothing written (R-F3).
        out["papers_found"] = await run_in_threadpool(papers.count_papers, list(texts.values()))
        return FolderSyncResponse(**out)
    attempted = len(files)
    if attempted and len(out["errors"]) == attempted:
        sync_state.record_error(memory_path, folder_source.channel_id(folder_id),
                                f"{attempted} file(s) could not be read")
    else:
        sync_state.record_sync(memory_path, folder_source.channel_id(folder_id),
                               count=folder_source.live_file_count(memory_path, folder_id))
    paths = list(staged.paths)
    registry_moved = bool(staged.paths)  # ``sync`` stamped ``last_sync``
    paper_work = bool(staged.touched or staged.tombstoned_sources)
    from api.services import sleep_cycle

    if sleep_cycle.get_sleep_state().status == "running":
        # R-LS17: Stage 5 may be rewriting the same pages; the episodes are
        # staged, the paper step waits for the next sync or the Sleep tail.
        if paper_work and not folder.get("papers_pending"):
            folder_source.set_flags(memory_path, folder_id, papers_pending=True)
            registry_moved = True
        out["papers_pending"] = bool(paper_work or folder.get("papers_pending"))
    elif folder.get("papers_pending") or paper_work:
        if folder.get("papers_pending"):
            report = await run_in_threadpool(
                papers.reparse_folder, memory_path, folder, tombstoned=staged.tombstoned_sources)
            folder_source.set_flags(memory_path, folder_id, papers_pending=False)
            registry_moved = True
        else:
            report = await run_in_threadpool(
                papers.reconcile, memory_path, folder, touched=staged.touched,
                tombstoned=staged.tombstoned_sources, renamed=staged.renamed_sources)
        out.update(papers_found=report["papers_found"], papers_created=report["papers_created"],
                   removals_proposed=report["removals_proposed"])
        paths += report["paths"]
    if registry_moved:
        paths.append(f"sources/{folder_source.FOLDERS_FILENAME}")
    # Nothing moved → no commit: a no-change rescan (the app's full pass on
    # launch) must not churn git or the sources ETag (Task 2 review, R-LS30).
    if paths:
        await folder_source.commit_paths_for(
            memory_path, paths, subject=f"Folder sync ({folder['label']})", trigger="folder/sync",
            channel=folder_source.channel_id(folder_id))
    if resolve:
        # R-LS18: the person asked (first add, or "Sync now") — fetch details
        # after the response, one run per process, skipped while Sleep runs.
        background.add_task(paper_metadata.resolve_in_background, memory_path)
    return FolderSyncResponse(**out)


@router.get("/capture/local-source/wispr-flow/settings", response_model=WisprFlowSettings)
async def get_wispr_settings(settings: Settings = Depends(get_settings)):
    return WisprFlowSettings(**wispr_flow.load_settings(settings.memory_path))


@router.put("/capture/local-source/wispr-flow/settings", response_model=WisprFlowSettings, dependencies=_DEMO_GATE)
async def put_wispr_settings(req: WisprFlowSettings, settings: Settings = Depends(get_settings)):
    saved = wispr_flow.save_settings(settings.memory_path, enabled=req.enabled,
                                     include_dictation=req.include_dictation,
                                     owner_speaker_names=req.owner_speaker_names)
    await folder_source.commit_paths_for(
        settings.memory_path, [f"sources/{wispr_flow.SETTINGS_FILENAME}"],
        subject="Wispr Flow settings", trigger="user/companion_app", channel=wispr_flow.CHANNEL_ID)
    return WisprFlowSettings(**saved)


@router.post("/capture/local-source/wispr-flow", response_model=WisprFlowCaptureResponse, dependencies=_DEMO_GATE)
async def capture_wispr_flow(req: WisprFlowPayload, settings: Settings = Depends(get_settings)):
    """Stage what the app read from Wispr Flow (R-N1). 409 while the source is off
    for this memory — the app only posts when it is on, so a 409 means the two
    disagree, and staging would ignore the person's choice."""
    memory_path = settings.memory_path
    current = wispr_flow.load_settings(memory_path)
    if not current["enabled"]:
        raise HTTPException(409, "Wispr Flow is turned off for this memory — turn it on in Settings → Integrations.")
    if len(req.meetings) > wispr_flow.MAX_MEETINGS or len(req.history or []) > wispr_flow.MAX_HISTORY:
        raise HTTPException(413, "too many rows in one request — send them in smaller batches")
    # `by_alias=False` is load-bearing: `CamelModel` sets `serialize_by_alias=True`, so a bare
    # `model_dump()` returns `deletedMeetingIds`/`deletedNoteIds` and `ingest` (which reads the
    # snake_case keys) would silently never tombstone anything. `test_the_routes` pins it.
    from api.services import sleep_cycle

    # L final review (finding 5): a to-do claim lands on the owner's page, which
    # Stage 5 rewrites — while a cycle runs the episodes stage now and the
    # claims wait for the next sync or the Sleep tail (the R-LS17 rule).
    sleeping = sleep_cycle.get_sleep_state().status == "running"
    report = await run_in_threadpool(wispr_flow.ingest, memory_path, req.model_dump(by_alias=False), current,
                                     defer_todos=sleeping)
    sync_state.record_sync(memory_path, wispr_flow.CHANNEL_ID, count=report.pop("live"))
    await folder_source.commit_paths_for(memory_path, report.pop("paths"), subject="Wispr Flow sync",
                                         trigger="wispr-flow/sync", channel=wispr_flow.CHANNEL_ID)
    return WisprFlowCaptureResponse(**report)
