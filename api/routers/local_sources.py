"""Local sources the APP reads and the backend parses (G133 folders, G134 note-takers).

The app owns the disk — a folder bookmark, another app's SQLite under
``~/Library`` — and posts bytes or a whitelisted projection here; the backend
never opens either (R-F1, R-N1). Every route is bearer-gated like the rest of
the API; none is on the Telegram / OAuth-callback exemption list.

Apple Calendar (G142): EventKit is read by the app; the window's events are
posted here.

Chrome's open tab groups (round 4, G160): the app reads the profile's session
file; one snapshot per group is posted here.

macOS Contacts (round 4, G154): the app reads the address book after one prompt and posts names plus which facts each
card holds; the backend enriches person pages it already has, never creates one.

YouTube watch history (G71, 2026-10-16): the app reads Chrome's own History on this Mac — a copy, YouTube watch pages
only — and posts the visits; the backend keeps one episode per day of what was watched, never a save.

Messages (G179): the app reads the conversations the person ticked from ``chat.db`` (Full Disk Access) and posts their
rows; the backend decodes, splits into sittings and stages them — refusing any conversation not ticked.

LinkedIn connections (2026-10-16, G154's pattern): the person picks their export's ``Connections.csv`` (or the export
``.zip``) in the LinkedIn tile; the app posts its bytes and the backend enriches the person pages it already has.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import (
    CalendarLocalSyncRequest,
    CalendarLocalSyncResponse,
    ContactsLocalSyncRequest,
    ContactsLocalSyncResponse,
    FolderListResponse,
    FolderRecord,
    FolderRegisterRequest,
    FolderRemoveResponse,
    FolderSyncRequest,
    FolderSyncResponse,
    FolderUpdateRequest,
    LinkedInConnectionsImportResponse,
    LinkedInConnectionsPreview,
    LinkedInConnectionsStatus,
    MessagesConversationsRequest,
    MessagesConversationsResponse,
    MessagesPhotosRequest,
    MessagesPhotosResponse,
    MessagesSettings,
    MessagesSettingsUpdate,
    MessagesSyncRequest,
    MessagesSyncResponse,
    MessagesWaitingResponse,
    TabGroupsSyncRequest,
    TabGroupsSyncResponse,
    WatchHistorySyncRequest,
    WatchHistorySyncResponse,
    WisprFlowCaptureResponse,
    WisprFlowPayload,
    WisprFlowSettings,
)
from api.services import (
    calendar_local,
    contacts_local,
    folder_source,
    linkedin_people,
    local_refs,
    messages_photos,
    messages_source,
    paper_metadata,
    papers,
    sync_state,
    tab_groups,
    watch_history,
    wispr_flow,
    write_admission,
)
from api.routers.capture import refuse_capture_into_demo
from api.services.sleep_refusal import SleepWriting

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
    from api.services import write_admission

    if write_admission.holding():   # its callers hold the bank's write admission through their commit (G183)
        folder_source.set_flags(memory_path, folder["id"], papers_pending=True)
        return paths + [f"sources/{folder_source.FOLDERS_FILENAME}"]
    current = folder_source.get_folder(memory_path, folder["id"]) or folder
    report = await run_in_threadpool(papers.reconcile, memory_path, current, touched=moved["touched"], tombstoned={})
    return paths + list(report["paths"])


# L final review (finding 5): `ensure_project` writes a project page — `paths:` onto one Stage 5 may be rewriting, or a
# new page Sleep's `git add -A` would sweep under the model's name. Adding a folder is a person's click, so asking again
# in a minute is the honest answer; asked under the bank's write admission, held through the commit (G183).
@router.post("/sources/folders", response_model=FolderRecord, dependencies=_DEMO_GATE)
@write_admission.route(refuse=lambda: SleepWriting(
    "Cicada is tidying up your memory right now — add the folder again in a minute."))
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
@write_admission.route()   # held, never refused: the paper step waits while Sleep holds the pages (R-LS17)
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
@write_admission.route()   # held, never refused: capture is never gated, the paper step waits (R-LS17, G183)
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
    if write_admission.holding():
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
@write_admission.route()   # held, never refused: the episodes always stage, the to-do claims wait (G183)
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
    # L final review (finding 5): a to-do claim lands on the owner's page, which
    # Stage 5 rewrites — while a cycle runs the episodes stage now and the
    # claims wait for the next sync or the Sleep tail (the R-LS17 rule).
    sleeping = write_admission.holding()
    report = await run_in_threadpool(wispr_flow.ingest, memory_path, req.model_dump(by_alias=False), current,
                                     defer_todos=sleeping)
    sync_state.record_sync(memory_path, wispr_flow.CHANNEL_ID, count=report.pop("live"))
    await folder_source.commit_paths_for(memory_path, report.pop("paths"), subject="Wispr Flow sync",
                                         trigger="wispr-flow/sync", channel=wispr_flow.CHANNEL_ID)
    return WisprFlowCaptureResponse(**report)


@router.post("/sources/calendar-local/sync", response_model=CalendarLocalSyncResponse, dependencies=_DEMO_GATE)
async def sync_calendar_local(req: CalendarLocalSyncRequest, settings: Settings = Depends(get_settings)):
    """G142 (round 4 C6): stage one rolling window the app read through EventKit.
    413 above ``calendar_local.MAX_EVENTS``; 422 for a window with no offset or
    out of order; nothing staged either way. One ``user`` commit per sync
    (trigger ``capture/calendar``), scoped to the episodes it wrote — a
    no-change re-read commits nothing."""
    memory_path = settings.memory_path
    if len(req.events) > calendar_local.MAX_EVENTS:
        raise HTTPException(413, f"at most {calendar_local.MAX_EVENTS} events per sync — send a shorter window")
    try:
        out = await run_in_threadpool(calendar_local.sync, memory_path, req.model_dump(by_alias=False),
                                      bank=memory_path.name)
    except calendar_local.PayloadError as exc:
        raise HTTPException(422, str(exc))
    sync_state.record_sync(memory_path, calendar_local.CHANNEL_ID, count=out.pop("live"))
    await folder_source.commit_paths_for(memory_path, out.pop("paths"), subject="Calendar sync",
                                         trigger="capture/calendar", channel=calendar_local.CHANNEL_ID)
    return CalendarLocalSyncResponse(**out, bank=memory_path.name)


@router.post("/sources/tab-groups/sync", response_model=TabGroupsSyncResponse, dependencies=_DEMO_GATE)
async def sync_tab_groups(req: TabGroupsSyncRequest, settings: Settings = Depends(get_settings)):
    """Round 4 (G160 first slice): stage one browser profile's open tab groups, read by the app. 413 above
    ``tab_groups.MAX_GROUPS`` groups or ``MAX_TABS_PER_REQUEST`` tabs; 422 for a browser or profile the backend does
    not read; nothing staged either way. One ``user`` commit per sync (trigger ``capture/tab-groups``), scoped to the
    episodes it wrote — an unchanged snapshot commits nothing."""
    memory_path = settings.memory_path
    if len(req.groups) > tab_groups.MAX_GROUPS or sum(len(g.tabs) for g in req.groups) > tab_groups.MAX_TABS_PER_REQUEST:
        raise HTTPException(413, "too many tab groups in one request")
    try:
        out = await run_in_threadpool(tab_groups.sync, memory_path, req.model_dump(by_alias=False), bank=memory_path.name)
    except tab_groups.PayloadError as exc:
        raise HTTPException(422, str(exc))
    channel = tab_groups.channel_id(req.browser.strip().lower())
    sync_state.record_sync(memory_path, channel, count=out["groups"], extra={"tabs": out["tabs"]})
    await folder_source.commit_paths_for(memory_path, out.pop("paths"), subject="Tab groups sync",
                                         trigger="capture/tab-groups", channel=channel)
    return TabGroupsSyncResponse(**out, bank=memory_path.name)


@router.post("/sources/watch-history/sync", response_model=WatchHistorySyncResponse, dependencies=_DEMO_GATE)
async def sync_watch_history(req: WatchHistorySyncRequest, settings: Settings = Depends(get_settings)):
    """G71 (2026-10-16): the YouTube videos the person watched in a browser, read by the app from the browser's own
    History file (a copy; only YouTube watch pages leave the app) after the person turned this on. Episodes only —
    one per day of what was watched, through the stager — so it is capture, ungated like every Awake writer. 413
    above ``watch_history.MAX_VISITS``; 422 for a browser or profile the backend does not read. One ``user`` commit
    per sync (trigger ``capture/watch-history``), scoped to the days it wrote — a re-read with nothing new commits
    nothing."""
    memory_path = settings.memory_path
    if len(req.visits) > watch_history.MAX_VISITS:
        raise HTTPException(413, f"at most {watch_history.MAX_VISITS} visits per sync — send them in batches")
    try:
        out = await run_in_threadpool(watch_history.sync_browser, memory_path, req.model_dump(by_alias=False),
                                      bank=memory_path.name)
    except watch_history.PayloadError as exc:
        raise HTTPException(422, str(exc))
    channel = watch_history.channel_id(req.browser.strip().lower())
    # The row's count is what memory holds (every door's days), never this pass's few new visits.
    sync_state.record_sync(memory_path, channel, count=out["videos"], extra={"days": out.pop("days")})
    await folder_source.commit_paths_for(memory_path, out.pop("paths"), subject="Watch history sync",
                                         trigger="capture/watch-history", channel=channel)
    return WatchHistorySyncResponse(**out, bank=memory_path.name)


@router.post("/sources/contacts-local/sync", response_model=ContactsLocalSyncResponse, dependencies=_DEMO_GATE)
@write_admission.route(refuse=lambda: SleepWriting(contacts_local.SLEEP_REFUSAL))
async def sync_contacts_local(req: ContactsLocalSyncRequest, settings: Settings = Depends(get_settings)):
    """G154 (round 4): enrich the person pages Cicada already has from the address book the app read. 409 while Sleep
    runs (this writes entity pages Stage 5 rewrites); 413 above ``contacts_local.MAX_CONTACTS``; 422 for a payload the
    backend cannot trust. One ``user`` commit per sync (trigger ``capture/contacts``), scoped to the pages it changed —
    an unchanged address book commits nothing. Cards that match no page wait outside the bank for a first mention
    (owner ruling 2026-10-20; ``waiting`` counts them)."""
    memory_path = settings.memory_path
    if len(req.contacts) > contacts_local.MAX_CONTACTS:
        raise HTTPException(413, f"at most {contacts_local.MAX_CONTACTS} contacts per sync")
    try:
        out = await run_in_threadpool(contacts_local.sync, memory_path, req.model_dump(by_alias=False),
                                      bank=memory_path.name)
    except contacts_local.PayloadError as exc:
        raise HTTPException(422, str(exc))
    sync_state.record_sync(memory_path, contacts_local.CHANNEL_ID, count=out["contacts"], extra={"people": out["people"]})
    await folder_source.commit_paths_for(memory_path, out.pop("paths"), subject="Contacts sync",
                                         trigger="capture/contacts", channel=contacts_local.CHANNEL_ID)
    return ContactsLocalSyncResponse(**out, bank=memory_path.name)


@router.delete("/sources/contacts-local/waiting")
async def forget_contacts_waiting():
    """Review of #391: the app stopped Contacts (Disconnect, or access found taken away) — every bank's waiting cards
    and thumbnails are deleted (Contacts is app-wide), so no first mention and no tail rematch uses a card again. Writes
    nothing in a bank, so it needs no write admission; counts only, never a name."""
    return {"forgotten": await run_in_threadpool(contacts_local.forget_waiting)}


# --- LinkedIn connections (2026-10-16; G154's pattern) ---------------------------------------------------------------


async def _connections_bytes(file: UploadFile) -> bytes:
    data = await file.read(linkedin_people.MAX_BYTES + 1)
    if len(data) > linkedin_people.MAX_BYTES:
        raise HTTPException(413, "That file is too large to be a LinkedIn connections export.")
    return data


@router.get("/sources/linkedin-connections", response_model=LinkedInConnectionsStatus)
async def linkedin_connections_status(settings: Settings = Depends(get_settings)):
    """The kept export's day and how many connections it lists — what the LinkedIn tile shows. Not a Store domain."""
    bank = settings.memory_path.name
    return LinkedInConnectionsStatus(**linkedin_people.status(bank), bank=bank)


@router.delete("/sources/linkedin-connections")
async def forget_linkedin_connections(settings: Settings = Depends(get_settings)):
    """Review of #391: forget this bank's kept LinkedIn export — Sleep's rematch never reads it again. Pages already
    enriched keep what they gained. Counts only."""
    bank = settings.memory_path.name
    return {"forgotten": await run_in_threadpool(linkedin_people.forget_directory, bank), "bank": bank}


@router.post("/sources/linkedin-connections/preview", response_model=LinkedInConnectionsPreview,
             dependencies=_DEMO_GATE)
async def preview_linkedin_connections(file: UploadFile = File(...), exported_on: str | None = Query(None),
                                       settings: Settings = Depends(get_settings)):
    """What an import of this ``Connections.csv`` (or export ``.zip``) would do: how many connections match a person
    page Cicada already has, how many are ambiguous or unknown. Reads pages, writes nothing, keeps nothing."""
    data = await _connections_bytes(file)
    try:
        out = await run_in_threadpool(linkedin_people.preview, settings.memory_path, data, file.filename or "",
                                      exported_on=exported_on)
    except linkedin_people.PayloadError as exc:
        raise HTTPException(422, str(exc))
    return LinkedInConnectionsPreview(**out, bank=settings.memory_path.name)


@router.post("/sources/linkedin-connections/import", response_model=LinkedInConnectionsImportResponse,
             dependencies=_DEMO_GATE)
@write_admission.route(refuse=lambda: SleepWriting(linkedin_people.SLEEP_REFUSAL))
async def import_linkedin_connections(file: UploadFile = File(...), exported_on: str | None = Query(None),
                                      settings: Settings = Depends(get_settings)):
    """Enrich the person pages Cicada already has from the person's LinkedIn connections — never a new page (the
    promotion rail): a matched page gains its profile link as a source and its company, position and day connected as
    dated ``external:linkedin`` claims, newest export winning. The rest is kept outside the bank for later matches.
    409 while Sleep runs; 422 for a file that is not the export. One ``user`` commit (trigger
    ``capture/linkedin-connections``), scoped to the pages it changed — a re-import commits nothing."""
    memory_path = settings.memory_path
    data = await _connections_bytes(file)
    try:
        report = await run_in_threadpool(linkedin_people.import_connections, memory_path, data, file.filename or "",
                                         exported_on=exported_on, bank=memory_path.name)
    except linkedin_people.PayloadError as exc:
        raise HTTPException(422, str(exc))
    await folder_source.commit_paths_for(memory_path, report.paths, subject="LinkedIn connections",
                                         trigger=linkedin_people.TRIGGER_IMPORT, channel=linkedin_people.CHANNEL_ID)
    counts = report.counts()
    return LinkedInConnectionsImportResponse(**counts, bank=memory_path.name)


# --- Messages (G179; G188's minimal slice) ---------------------------------------------------------------------------


@router.get("/sources/messages/settings", response_model=MessagesSettings)
async def get_messages_settings(settings: Settings = Depends(get_settings)):
    return MessagesSettings(**messages_source.load_settings(settings.memory_path))


@router.put("/sources/messages/settings", response_model=MessagesSettings, dependencies=_DEMO_GATE)
async def put_messages_settings(req: MessagesSettingsUpdate, settings: Settings = Depends(get_settings)):
    """Tick or untick a conversation, mark who it is with, or turn agent suggestions on or off. A changed mark
    re-renders that conversation's saved sittings in place (from the episodes themselves; nothing is re-read from the
    Mac), so the next Sleep reads the agent's turns as the agent's. Unticking stops the next sync and keeps every
    saved episode. One ``user`` commit: the settings file plus any episode re-rendered."""
    memory_path = settings.memory_path
    conversation = None
    if req.conversation is not None:
        c = req.conversation
        conversation = {"id": c.id, "name": c.name, "service": c.service, "ticked": c.ticked}
        if c.clear_actor:
            conversation["actor"] = None
        elif c.actor is not None:
            conversation["actor"] = c.actor.model_dump(by_alias=False)
    try:
        data, actor_changed = await run_in_threadpool(messages_source.update_settings, memory_path,
                                                      suggest_agents=req.suggest_agents, conversation=conversation)
    except messages_source.PayloadError as exc:
        raise HTTPException(422, str(exc))
    if conversation is not None and conversation.get("ticked") is False:
        # Unticking takes the chat's shared photo with it (2026-10-16): nothing of an unticked chat is kept outside
        # the bank either. Every saved sitting stays, as before.
        await run_in_threadpool(messages_photos.forget, memory_path, conversation["id"])
    paths = [f"sources/{messages_source.SETTINGS_FILENAME}"]
    reattributed = 0
    if actor_changed or req.suggest_agents is not None:
        ids = [conversation["id"]] if conversation is not None else list(data["conversations"])
        for cid in ids:
            out = await run_in_threadpool(messages_source.reattribute, memory_path, cid, bank=memory_path.name)
            reattributed += out["updated"] + out["recorded"]
            paths += out["paths"]
    await folder_source.commit_paths_for(memory_path, paths, subject="Messages settings",
                                         trigger="user/companion_app", channel=messages_source.CHANNEL_ID)
    return MessagesSettings(**data, reattributed=reattributed)


@router.post("/sources/messages/conversations", response_model=MessagesConversationsResponse,
             dependencies=_DEMO_GATE)
async def describe_messages_conversations(req: MessagesConversationsRequest, settings: Settings = Depends(get_settings)):
    """The Settings list's backend half: each conversation the app listed (names and counts only), with the person's
    tick and mark and the agent detectors' suggestion. Computes only — stores and logs nothing."""
    out = messages_source.describe(settings.memory_path, [c.model_dump(by_alias=False) for c in req.conversations])
    current = messages_source.load_settings(settings.memory_path)
    return MessagesConversationsResponse(suggest_agents=current["suggest_agents"], conversations=out)


@router.post("/sources/messages/sync", response_model=MessagesSyncResponse, dependencies=_DEMO_GATE)
async def sync_messages(req: MessagesSyncRequest, settings: Settings = Depends(get_settings)):
    """G179: stage rows of one ticked conversation. 409 for a conversation the person has not ticked (the app only
    posts ticked ones, so a 409 means the two disagree); 422 for a payload the backend cannot trust; 413 above
    ``MAX_MESSAGES_PER_REQUEST``. Episodes only — Awake capture, never an entity page. One ``user`` commit per sync
    (trigger ``capture/messages``), scoped to the sittings it wrote — an unchanged pass commits nothing."""
    memory_path = settings.memory_path
    if len(req.messages) > messages_source.MAX_MESSAGES_PER_REQUEST:
        raise HTTPException(413, f"at most {messages_source.MAX_MESSAGES_PER_REQUEST} messages per request")
    try:
        out = await run_in_threadpool(messages_source.ingest, memory_path, req.model_dump(by_alias=False),
                                      bank=memory_path.name)
    except messages_source.NotSelected as exc:
        raise HTTPException(409, str(exc))
    except messages_source.PayloadError as exc:
        raise HTTPException(422, str(exc))
    sync_state.record_sync(memory_path, messages_source.CHANNEL_ID, count=messages_source.live_count(memory_path))
    await folder_source.commit_paths_for(memory_path, out.pop("paths"), subject="Messages sync",
                                         trigger="capture/messages", channel=messages_source.CHANNEL_ID)
    return MessagesSyncResponse(**out, bank=memory_path.name)


@router.put("/sources/messages/photos", response_model=MessagesPhotosResponse, dependencies=_DEMO_GATE)
async def put_messages_photos(req: MessagesPhotosRequest, settings: Settings = Depends(get_settings)):
    """The photos ticked chats share through Messages (2026-10-16): the app reads them (``~/Library/Messages`` is
    its), shrinks them and posts the bytes; this keeps them outside every bank (`messages_photos`) and draws each at the
    page its chat's correspondent record links — the picture rung after the Contacts photo. Writes nothing to the bank
    and commits nothing. 409 for a chat that is not ticked, 422 for anything that is not a small PNG or JPEG."""
    memory_path = settings.memory_path
    try:
        out = await run_in_threadpool(messages_photos.store, memory_path,
                                      [p.model_dump(by_alias=False) for p in req.photos])
    except messages_source.NotSelected as exc:
        raise HTTPException(409, str(exc))
    except messages_photos.PayloadError as exc:
        raise HTTPException(422, str(exc))
    return MessagesPhotosResponse(**out)


@router.get("/sources/messages/waiting", response_model=MessagesWaitingResponse)
async def messages_waiting(settings: Settings = Depends(get_settings)):
    """The message conversations Sleep has not read yet, each with how many messages are waiting — the Sleep page's
    and Home's bubbles. Frontmatter only. Not a Store domain: the app fetches it with the Sleep queue."""
    rows = await run_in_threadpool(messages_source.waiting, settings.memory_path)
    return MessagesWaitingResponse(conversations=rows, messages=sum(r["messages"] for r in rows))
