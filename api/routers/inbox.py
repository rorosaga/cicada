import asyncio
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from loguru import logger

from api.config import Settings, get_settings
from api.models.schemas import (CatchupRecordRequest, CatchupTurnRequest, CheckCensus, InboxItem,
                                InboxResolveRequest, SettledCheck)
from api.services import inbox_service, same_name, same_name_pick, source_check, sync_service, sync_ticker

router = APIRouter()


def _served_day() -> str:
    """The day the inbox's words are said for (its ETag moves with it; review B2 of #509)."""
    from datetime import date

    return date.today().isoformat()


@router.get("/inbox", response_model=list[InboxItem])
async def list_inbox(
    request: Request,
    response: Response,
    kind: Optional[str] = Query(None),
    settings: Settings = Depends(get_settings),
):
    # G97 ship-together trap (G115 R3): the response now embeds entity- and
    # episode-derived context (cause excerpt, entity type), so an entity edit
    # or a new episode must move this ETag too. The CLIENT half — `.inbox`
    # on `VersionVector`'s `entities`/`episodes` mappings — lands in the same
    # commit; without it SnapshotCache serves stale context until the inbox
    # itself changes.
    # G205: agent requests (outside the bank) fold into the `inbox` component's stamp, so this ETag moves with them.
    # Ruling 48 (1): every served question carries its plain words and reason, whose ages ("yesterday", "about 2
    # months ago") are worded at read — so the tag moves with the day, or a 304 would keep yesterday's words (DR-58).
    # Speed 2026-10-29: the ETag and the read share one listing per directory (`shared_scans`; the worker thread
    # copies this context), so the bank is stat-walked once per request, not once for the ETag and again for the read.
    with sync_ticker.request_scans(settings.memory_path):
        # G227: `same_name.SHAPE` — items gained `entityDisplayName`, `mergeTargetDisplayName` and `sameTitle`,
        # derived from the entity files this ETag already covers; the bump makes every client take one 200.
        # `same_name_pick.SHAPE`: a same-title question is served with one option per page plus "none" (2026-10-29).
        etag = sync_service.etag_for(settings.memory_path, "inbox", "entities", "episodes",
                                     extra=f"{kind or ''}|{_served_day()}|{same_name.SHAPE}|{same_name_pick.SHAPE}")
        if (early := sync_service.conditional(request, response, etag)) is not None:
            return early
        # Off the event loop (inbox lag, 2026-10-17): the read parses every inbox file and the pages they name, and a
        # synchronous call here held every other request — the SSE stream, the other panes — behind it.
        items = await asyncio.to_thread(inbox_service.load_inbox, settings.memory_path)
    # G205: requests sit above the questions.
    items = await asyncio.to_thread(inbox_service.agent_request_items, settings.memory_path) + items
    if kind:
        wanted = {k.strip() for k in kind.split(",") if k.strip()}
        items = [i for i in items if i.kind.value in wanted]
    return items


@router.get("/inbox/check-census", response_model=CheckCensus)
async def check_census(settings: Settings = Depends(get_settings)):
    """G61 phase 2 S2 — how much of the pending inbox a source could answer.

    Counts per state, reason, kind, locus, rung and target access — enum keys
    only, never an item id, page id, link or host, so the census can be pasted
    into a PR or a backlog row. Read-only and engine-free; it parses the bank,
    so it runs off the event loop. No ETag: not a Store domain, and no screen
    polls it. The same numbers: ``scripts/check-census.sh <bank>``.
    """
    return CheckCensus(**await asyncio.to_thread(source_check.census, settings.memory_path))


@router.get("/inbox/settled", response_model=list[SettledCheck])
async def list_settled(settings: Settings = Depends(get_settings)):
    """"Settled by a check" (owner ruling 2026-10-16): the questions a web lookup or the person's own agent settled,
    newest first, each with its answer and the citation it rests on. On demand, not a Store domain: the Inbox fetches it
    when it opens and after an undo, and caches it in memory. Engine-free; it reads ``inbox/settled/``."""
    from api.services import web_settle

    return [SettledCheck(**row) for row in await asyncio.to_thread(web_settle.list_settled, settings.memory_path)]


@router.post("/inbox/settled/{item_id}/undo")
async def undo_settled(item_id: str, settings: Settings = Depends(get_settings)):
    """The one-tap undo: the check's claim is withdrawn, what it closed reopens (only a claim still as the check left
    it), and the question returns to the inbox. Committed as the person's (``Web check undone <date>``). 409 while
    Sleep holds the pages, 404 for no such settled question."""
    from api.services import git_service, page_lock, state_dictionary, web_settle, write_admission
    from api.services.sleep_refusal import SleepWriting

    memory_path = settings.memory_path
    if _settled_group(memory_path, item_id) == "sleep":
        return await _undo_sleep_settle(item_id, settings)
    from api.services import web_context

    if web_context.is_record_id(item_id):
        return await _undo_context(item_id, settings)
    # An edit already on a page the undo rewrites is committed apart, never as the person's undo (audit P1-3).
    before = await git_service.snapshot_dirty(memory_path)

    def work() -> str:
        with page_lock.page_lock(memory_path):
            target, paths, lines = web_settle.undo(memory_path, item_id)
            web_settle.commit_sync(memory_path, web_settle.commit_message("Web check undone", lines, authors=["user"]),
                                   paths, before=before)
            return target

    try:
        target = await write_admission.run_admitted(
            memory_path, lambda: asyncio.to_thread(work),
            refuse=lambda: SleepWriting(inbox_service.SLEEP_BUSY))
    except web_settle.NotSettleable as exc:
        raise HTTPException(404, str(exc)) from exc
    web_settle.record_event(memory_path, action="undo", item_id=item_id, entity_id=None, by_kind="person")
    await state_dictionary.refresh_admitted(memory_path, settings)   # admitted; skipped while Sleep holds the pages
    return {"status": "reopened", "id": target}


async def _undo_context(item_id: str, settings: Settings) -> dict:
    """Owner ruling 44 — a light-context lookup taken back (``web_context.undo``): its claims withdrawn, what it closed
    reopened, each value remembered so no lookup writes it again. Committed as the person's (``Web context undone``)."""
    from api.services import git_service, page_lock, state_dictionary, web_context, web_settle, write_admission
    from api.services.sleep_refusal import SleepWriting

    memory_path = settings.memory_path
    before = await git_service.snapshot_dirty(memory_path)

    def work() -> None:
        with page_lock.page_lock(memory_path):
            paths, lines = web_context.undo(memory_path, item_id)
            web_settle.commit_sync(memory_path, web_settle.commit_message("Web context undone", lines,
                                                                          authors=["user"]), paths, before=before)

    try:
        await write_admission.run_admitted(memory_path, lambda: asyncio.to_thread(work),
                                           refuse=lambda: SleepWriting(inbox_service.SLEEP_BUSY))
    except web_settle.NotSettleable as exc:
        raise HTTPException(404, str(exc)) from exc
    web_settle.record_event(memory_path, action="context_undo", item_id=item_id, entity_id=None, by_kind="person")
    await state_dictionary.refresh_admitted(memory_path, settings)
    return {"status": "undone", "id": item_id}


def _settled_group(memory_path, item_id: str) -> str:
    import re

    from api.services import markdown_parser

    if not re.fullmatch(r"inbox-\d{3,}", item_id or ""):
        return ""
    path = memory_path / "inbox" / "settled" / f"{item_id}.md"
    try:
        rec = markdown_parser.parse(path).frontmatter.get("settled") if path.is_file() else None
    except Exception:  # noqa: BLE001 — an unreadable record is no record
        return ""
    return str(rec.get("group") or "check") if isinstance(rec, dict) else ""


async def _undo_sleep_settle(item_id: str, settings: Settings) -> dict:
    """Ruling 29 — "Settled by Sleep" undo: Sleep's commit for this question is taken back (three-way, onto each page
    as it is now; refused whole, nothing written, when something since overlaps it) and the question returns, marked
    so Sleep never settles it again. Committed as the person's (``Sleep's settle undone <date>``)."""
    from api.services import git_service, inbox_tend, page_lock, state_dictionary, web_settle, write_admission
    from api.services.sleep_refusal import SleepWriting

    memory_path = settings.memory_path
    before = await git_service.snapshot_dirty(memory_path)
    out: dict = {}

    def work() -> str:
        with page_lock.page_lock(memory_path):
            target, paths, lines, rec = inbox_tend.undo(memory_path, item_id)
            web_settle.commit_sync(memory_path, web_settle.commit_message("Sleep's settle undone", lines,
                                                                          authors=["user"]), paths, before=before)
            out["rec"] = rec
            return target

    try:
        target = await write_admission.run_admitted(
            memory_path, lambda: asyncio.to_thread(work),
            refuse=lambda: SleepWriting(inbox_service.SLEEP_BUSY))
    except inbox_tend.NotUndoable as exc:
        raise HTTPException(409 if "changed" in str(exc) or "moved" in str(exc) else 404, str(exc)) from exc
    inbox_tend.record_undo(memory_path, item_id, out.get("rec") or {})
    await state_dictionary.refresh_admitted(memory_path, settings)   # admitted; skipped while Sleep holds the pages
    return {"status": "reopened", "id": target}


@router.post("/inbox/tidy")
async def tidy_inbox(
    dry_run: bool = Query(True, alias="dryRun"),
    limit: Optional[int] = Query(None, ge=1),
    judge: bool = Query(False),
    settings: Settings = Depends(get_settings),
):
    """Ruling 29 — the one-time tidy of the backlog: Sleep's own policy (``inbox_tend``) over every open question.
    ``dryRun`` (the default) writes nothing and answers COUNTS per kind and per decision — never a title, a name or
    any text. ``judge`` lets the judge read duplicates, conflicts, label folds and fading pages with the person's
    chosen engine (their plan included; a plan limit pauses it). A real run starts in the background — each question settles alone under the bank's
    write admission and commits — and ``GET /inbox/tidy`` reports it. 409 while Sleep runs or a tidy is running."""
    from api.services import inbox_tend, write_admission

    if write_admission.probe():
        raise HTTPException(409, inbox_service.SLEEP_BUSY)
    from api.services import web_lookup

    if inbox_tend.tidy_status()["running"] or web_lookup.sweep_running():
        raise HTTPException(409, "The inbox is already being tidied.")
    if dry_run:
        return await inbox_tend.tidy(settings.memory_path, settings, dry_run=True, limit=limit, judge=judge)
    if not inbox_tend.start_tidy(settings.memory_path, settings, limit=limit, judge=judge):
        raise HTTPException(409, "The inbox is already being tidied.")
    return {"status": "started"}


@router.post("/inbox/tidy/apply")
async def tidy_apply_vetted(payload: dict = Body(...), settings: Settings = Depends(get_settings)):
    """Owner rule 2026-10-20 — the vetted apply: settle exactly the rows a coordinator kept from a trace
    (``api/scripts/inbox_tidy_trace.py``), each as the dry run decided it, through the person's own resolver as Sleep's
    undoable commit, one at a time under the bank's write admission. A row whose question or pages moved since the
    trace is left as it is (``changed``); one asking for anything the rules never ask is ``refused``. Answers per id
    and counts — no text. 409 while Sleep runs or a tidy, a sweep or another apply is running."""
    from api.services import inbox_tend, web_lookup, write_admission

    rows = payload.get("decisions") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise HTTPException(422, "Send {\"decisions\": [...]}: the trace rows to apply.")
    if len(rows) > inbox_tend.MAX_VETTED:
        raise HTTPException(422, f"At most {inbox_tend.MAX_VETTED} decisions at once.")
    if write_admission.probe():
        raise HTTPException(409, inbox_service.SLEEP_BUSY)
    if inbox_tend.tidy_status()["running"] or web_lookup.sweep_running():
        raise HTTPException(409, "The inbox is already being tidied.")
    return await inbox_tend.apply_vetted(settings.memory_path, settings, rows)


@router.get("/inbox/tidy")
async def tidy_status(settings: Settings = Depends(get_settings)):
    """The running (or last) tidy's counts — ids never, text never. A run a restart cut short is read back from its
    saved counts, marked ``interrupted``."""
    from api.services import inbox_tend

    return inbox_tend.tidy_status(settings.memory_path)


@router.post("/inbox/web-check")
async def web_check_sweep(
    dry_run: bool = Query(True, alias="dryRun"),
    limit: Optional[int] = Query(None, ge=1),
    include_recent: bool = Query(False, alias="includeRecent"),
    settings: Settings = Depends(get_settings),
):
    """Owner ruling 2026-10-19 — the one-off sweep: the backlog's questions about public things (a tool, a company, a
    concept, a film, a paper, a dataset — never a person, the person's files, projects or life) looked up on the web
    with the engine a run you start would use, and settled when a search answers them, each with its link and quote and
    undoable under "Settled by a check". ``dryRun`` (the default) writes nothing and answers COUNTS: the census of what
    a lookup may answer and why the rest stays, then what the lookups would settle — never a title, a name or any text.
    ``limit`` caps the lookups (one engine call each). A real run starts in the background, each settle under the bank's
    write admission with its own commit, and ``GET /inbox/web-check`` reports it. 409 while Sleep runs or a sweep or a
    tidy is running."""
    from api.services import inbox_tend, web_lookup, write_admission

    if write_admission.probe():
        raise HTTPException(409, inbox_service.SLEEP_BUSY)
    if web_lookup.sweep_running() or inbox_tend.tidy_status()["running"]:
        raise HTTPException(409, "The inbox is already being tidied.")
    if dry_run:
        return await web_lookup.sweep(settings.memory_path, settings, dry_run=True, limit=limit,
                                      include_recent=include_recent)
    if not web_lookup.start_sweep(settings.memory_path, settings, limit=limit, include_recent=include_recent):
        raise HTTPException(409, "The inbox is already being tidied.")
    return {"status": "started"}


@router.get("/inbox/web-check")
async def web_check_status():
    """The running (or last) sweep's counts — ids never, text never."""
    from api.services import web_lookup

    return web_lookup.sweep_status()


@router.post("/inbox/catchup/turn")
async def catchup_turn(request: CatchupTurnRequest, settings: Settings = Depends(get_settings)):
    """Ruling 48 (8): one turn of the in-app catch-up chat — the person's own words about one open question, answered
    the way a person would (a follow-up, other words, a related question) on the person's chosen engine, resolved like
    Ask (`engine_select.resolve_settings(user_triggered=True)`; rulings 4/31/46: never a metered key nobody chose).
    Writes nothing: a reading grounded in their words is the app's to apply through the inbox's own resolver
    (`catchup_chat`). ``{"engine": false, "why": …}`` when no engine may answer — the chat then takes taps only."""
    import uuid

    from api.services import agent_engine, catchup_chat, engine_readiness, engine_select

    resolved, why = await engine_select.resolve_settings(settings, user_triggered=True)
    if engine_readiness.key_missing(resolved):
        return {"engine": False, "why": engine_select.no_engine_sentence(why), "reply": None, "reading": None,
                "move": "stay", "nextId": None}

    def llm_fn(system: str, prompt: str) -> str:
        import litellm

        from api.services.providers import resolve_llm_fn

        call = resolve_llm_fn(resolved, model=resolved.litellm_model, completion=litellm.completion, stage="catchup")
        # Its own self-purging breaker scope, like Ask's (one throttle stops this turn, never every later one).
        with agent_engine.use_scope(f"catchup:{uuid.uuid4().hex}"):
            response = call(messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                            response_format={"type": "json_object"})
        return response.choices[0].message.content or ""

    try:
        return await asyncio.to_thread(catchup_chat.turn, resolved.memory_path, request.item_id, request.message,
                                       request.history, request.upcoming, llm_fn)
    except LookupError:
        raise HTTPException(404, "That question is no longer open.") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except Exception as exc:  # noqa: BLE001 — the engine failed: the chat keeps the question and the person's words
        logger.warning(f"catch-up turn failed: {type(exc).__name__}")
        return {"engine": True, "error": True, "reply": None, "reading": None, "move": "stay", "nextId": None}


@router.post("/inbox/catchup/record")
async def catchup_record(request: CatchupRecordRequest, settings: Settings = Depends(get_settings)):
    """Ruling 48 (8): the catch-up chat kept as ONE episode per session (source-keyed, updated in place), so Sleep
    reads what the person said in passing as it reads any conversation. Never into a demo bank."""
    from api.services import catchup_chat

    try:
        return await asyncio.to_thread(catchup_chat.record, settings.memory_path, request.session_id, request.turns)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/inbox/{item_id}/resolve")
async def resolve_inbox(
    item_id: str,
    request: InboxResolveRequest,
    settings: Settings = Depends(get_settings),
):
    from api.services import agent_requests

    if agent_requests.is_request_id(item_id):
        # G205: an agent request is the person's tap alone, never a bank write, so no Sleep gate. An agent may not
        # answer it for them (its tools never see it; this refuses one that tries).
        if (request.via or "").strip().lower() == "agent" or request.relayed_by or request.quote:
            raise HTTPException(403, "An agent request is the person's to answer, in the app.")
        action = (request.option_key or request.action or "").strip().lower()
        try:
            done = await asyncio.to_thread(agent_requests.resolve, settings.memory_path, item_id, action)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if done is None:
            raise HTTPException(404, f"Inbox item {item_id} not found")
        return done
    return await inbox_service.resolve(item_id, request, settings)


@router.post("/agent-requests", status_code=201)
async def file_agent_request(payload: dict = Body(...), settings: Settings = Depends(get_settings)):
    """G205's REST door: an agent that cannot use Cicada's MCP tools asks the person to sign in to a site so it can
    read a page. ``{"site": "example.com", "reason": "to read the post you talked about", "agent": "<catalog id>"}``;
    ``agent`` is display only (an unknown id is "An agent"). One open request per (agent, site, reason). Answers the
    request with the notification the app posts. Never into a demo bank (409)."""
    from api.services import agent_requests, demo_guard

    if not isinstance(payload, dict):
        raise HTTPException(422, "Send {\"site\": ..., \"reason\": ...}.")
    if demo_guard.is_demo(settings.memory_path):
        raise HTTPException(409, "This is the demo bank; requests go to your own memory.")
    kind = str(payload.get("kind") or "sign_in")
    row = await asyncio.to_thread(agent_requests.ask, settings.memory_path, agent=str(payload.get("agent") or "") or None,
                                  site=str(payload.get("site") or ""), reason=payload.get("reason"), kind=kind)
    if row is None:
        raise HTTPException(422, f"'site' must be a host name (like example.com) and 'kind' one of "
                                 f"{', '.join(agent_requests.KINDS)}.")
    return {"id": row["id"], **agent_requests.wire(row)}
