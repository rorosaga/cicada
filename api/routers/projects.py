"""G141 PJ-1 — a project's timeline over HTTP (spec §10.1).

Both reads are fetched on demand, like the provenance reads (R-PJ7): neither is
a Store domain, so there is no `VersionVector` mapping and the ship-together
rule has nothing to pair. Both ETags fold `entities`, `episodes` and `inbox`
plus the machine zone's NAME, `PROJECT_SHAPE` and `git_service.AUTHOR_SHAPE`
(round 4, R4B-9: the bodies carry claim author kinds and turn models) — never
today, never a viewer zone — so a 304 holds across midnight and moves only when the bank or the Mac's
zone does. (The `inbox` component itself re-validates once a day while a
deferred item is pending — that item's return IS a content change.) The build
runs in the threadpool: it parses pages.

The person's writes (§5.3, PJ-3b): observer through
`owner_identity.resolve_observer`, `user_stated`, `origin: companion_app` —
protected by `is_human` (R-PJ18); `Cicada-Author: user`, trigger
`user/companion_app`, `commit_paths` over its own pages; a 409 while Sleep
runs (the `enrich-links` precedent, `maintenance.py`) — Sleep rewrites the same
pages, and a write between its read and its commit would be swept into the
cycle's commit under a model's name. `on` defaults to today in the machine
zone, may be backdated, never lies in the future. Every event goes through
`progress` (the ONE event writer), so this module decides nothing about
validity: it picks the page, the day and the author. `origin="companion_app"`
is spelled out at each call on purpose: `test_human_origin_pin.py` greps for it,
and only this router (and the synthetic demo) may set it (R-PJB13).
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from loguru import logger
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import (ConversationTie, HappeningCreate, InfluenceCreate, InfluenceWithdraw,
                                MilestoneCreate, MilestonePatch, ProjectAccept, ProjectConversations, ProjectCreate,
                                PageTie, ProjectOwnershipResponse, ProjectPatch, ProjectsResponse, ProjectTimeline,
                                ProjectWriteResponse, ThreadSettle, WithdrawRequest)
from api.services import (bank_index, episode_scrub, git_service, handshake, markdown_parser, owner_identity,
                          progress, project_timeline, search_index, sync_service, telemetry,
                          turn_authorship, when, write_admission)
from api.services.claim_reconciler import is_human
from api.services.claims import HAPPENED, MILESTONE, Claim, MalformedClaimsBlockError, is_event, parse_claims
from api.services.id_utils import resolve_entity_file
from api.services.transclusion_resolver import claim_to_model
from api.services.sleep_refusal import SleepWriting

router = APIRouter()


def _tz() -> str:
    return handshake.local_timezone() or "UTC"


def _project_stem(memory_path, project_id: str) -> str:
    page = resolve_entity_file(memory_path, project_id)
    if page is None:
        raise HTTPException(404, f"No project {project_id!r}")
    fm = next((f.frontmatter for f in bank_index.files(memory_path, "entities") if f.stem == page.stem), {}) or {}
    if str(fm.get("type") or "") != "project" or str(fm.get("status") or "active") == "dropped":
        raise HTTPException(404, f"{page.stem!r} is not a project")
    return page.stem


def _index_state(mp) -> str:
    return search_index.ensure_fresh(mp)


def _unpin_degraded(response: Response, index_state: str, result) -> None:
    """The ETag covers bank content, but the body also depends on the FTS
    index: while it is `building` the reverse-claims layer falls back to a
    capped raw scan (`partial`), and while `stale` it answers from before the
    last bulk change with no flag. A degraded body must never be revalidated
    into a 304 until the bank next changes, so it goes out with no ETag
    (G141 final review — SCHEMA_VERSION 3 makes the first request after an
    upgrade exactly this case)."""
    if index_state != "ready" or getattr(result, "partial", False):
        if "etag" in response.headers:   # MutableHeaders has no `pop`
            del response.headers["etag"]


@router.get("/projects", response_model=ProjectsResponse)
async def list_projects(request: Request, response: Response, settings: Settings = Depends(get_settings)):
    mp, tz = settings.memory_path, _tz()
    etag = sync_service.etag_for(mp, "entities", "episodes", "inbox",
                                 extra=f"projects|{project_timeline.PROJECT_SHAPE}|{git_service.AUTHOR_SHAPE}|{tz}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    index_state = await run_in_threadpool(_index_state, mp)
    result = await run_in_threadpool(project_timeline.list_projects, mp, tz_name=tz)
    _unpin_degraded(response, index_state, result)
    return result


@router.get("/projects/{project_id}/timeline", response_model=ProjectTimeline)
async def get_project_timeline(project_id: str, request: Request, response: Response,
                               since: Optional[str] = None, settings: Settings = Depends(get_settings)):
    mp, tz = settings.memory_path, _tz()
    since_day = None
    if since:
        try:
            since_day = date.fromisoformat(since[:10]).isoformat()
        except ValueError:
            raise HTTPException(400, "since must be a date (YYYY-MM-DD)")
    stem = _project_stem(mp, project_id)
    etag = sync_service.etag_for(mp, "entities", "episodes", "inbox",
                                 extra=f"project|{stem}|{since_day or ''}|{project_timeline.PROJECT_SHAPE}|{git_service.AUTHOR_SHAPE}|{tz}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    index_state = await run_in_threadpool(_index_state, mp)
    result = await run_in_threadpool(project_timeline.build, mp, stem, tz_name=tz, since=since_day)
    if result is None:
        raise HTTPException(404, f"{stem!r} is not a project")
    _unpin_degraded(response, index_state, result)
    # A 200 is an open (a 304 revalidation is not): ids and an enum only (G124 R11).
    telemetry.record_read(stem, surface="project", bank=telemetry.bank_name(settings))
    return result


# --------------------------------------------------------------------------- #
# the person's writes (G141 PJ-3b, §5.3)
# --------------------------------------------------------------------------- #

# One write at a time in this process: two quick taps (Done, then Not right)
# would otherwise read the same page and the second rewrite would drop the
# first's claim before either commit ran.
_write_lock = write_admission.TransactionLock()   # taken inside admitted transactions (writer loop)
BUSY = "Sleep is writing this project, try again in a moment"
TWO_DAYS = "Say one day, or pick it with the date chip"
OUT_OF_RANGE = "That day is outside what Cicada can date — pick it with the date chip"
WITHDRAW_REASON = "The person marked this as not right in Cicada"


def _now() -> datetime:
    return datetime.now(when.zone(_tz()))


def _busy() -> SleepWriting:
    return SleepWriting(BUSY)


#: The route's write admission (G183): 409 while Sleep holds the pages, asked once the hold is taken and held — on
#: the writer loop, through this process's one-write lock and the commit — so a window cannot open between.
_admitted = write_admission.route(refuse=_busy)


def _on(raw: str | None, today: date) -> date:
    if not raw:
        return today
    try:
        day = date.fromisoformat(raw[:10])
    except ValueError:
        raise HTTPException(400, "on must be a date (YYYY-MM-DD)")
    if day > today:
        raise HTTPException(400, "on can't be in the future")
    return day


async def _commit(memory_path, paths: list[str], today: date) -> None:
    message = git_service.build_commit_message(
        f"Project update {today.isoformat()}",
        [f"{p}: updated (source: n/a, trigger: user/companion_app)" for p in dict.fromkeys(paths)],
        authors=["user"])
    try:
        await git_service.commit_paths(memory_path, message, sorted(set(paths)))
    except Exception as exc:  # noqa: BLE001 — the write stands; a later writer's commit picks it up
        logger.warning(f"project write commit skipped: {type(exc).__name__}")


def _page_claims(memory_path: Path, page: str) -> list[Claim]:
    """The page as it is on disk NOW — never the read model's cache, which a
    write this same request made may already have outdated."""
    try:
        return parse_claims(markdown_parser.parse(Path(memory_path) / "entities" / f"{page}.md").body, strict=True)
    except (OSError, MalformedClaimsBlockError):
        return []


def _tree(memory_path: Path, stem: str) -> list[str]:
    bank = project_timeline._Bank(memory_path, _tz())
    return project_timeline._tree(bank, stem)[0]


def _find_event(memory_path: Path, stem: str, claim_id: str) -> tuple[str, Claim]:
    """`(page, claim)` for an event claim on any page of the project's tree —
    the page that holds it is the `subject` every `progress` call gets. A
    claim outside the tree is a 404, so a URL can never reach another project."""
    for page in _tree(memory_path, stem):
        same = [c for c in _page_claims(memory_path, page) if c.id == claim_id and is_event(c)]
        if same:
            return page, next((c for c in same if c.valid_to is None), same[0])
    raise HTTPException(404, f"No happening or milestone {claim_id!r} on this project")


def _find_slot(memory_path: Path, stem: str, slug: str) -> tuple[str, bool]:
    """`(page, is_due)` for a milestone slot in the tree: an open head keyed
    by `slug`, else a read-compat `due-<date>` (R-PJB21) not yet replaced."""
    tree = _tree(memory_path, stem)
    for page in tree:
        if progress._open_head(_page_claims(memory_path, page), slug) is not None:
            return page, False
    m = progress._DUE_SLUG.match(slug or "")
    if m:
        from api.services import claim_expiry

        for page in tree:
            if any(c.predicate == "due" and not c.superseded_by and claim_expiry.stated_end(c) == m.group(1)
                   for c in _page_claims(memory_path, page)):
                return page, True
    raise HTTPException(404, f"No milestone {slug!r} on this project")


def _raise_for(result: dict) -> None:
    action = result.get("action")
    if action == "not_found":
        raise HTTPException(404, result.get("error") or "Not found")
    if action == "error":
        raise HTTPException(400, result.get("error") or "That couldn't be saved")


def _models(memory_path: Path, page: str, ids: list[str | None]) -> list:
    """The written claims as the wire shows them. Callers run it in the
    threadpool: a withdrawn agent claim takes the C3 model join, which scans
    the episode index — never on the event loop (round 4 final review #2)."""
    wanted = [i for i in dict.fromkeys(ids) if i]
    claims = _page_claims(memory_path, page)
    turns = turn_authorship.TurnAuthorship(memory_path)  # round 4 C3: one join per request
    out = []
    for cid in wanted:
        c = next((x for x in claims if x.id == cid and x.valid_to is None), None) or \
            next((x for x in claims if x.id == cid), None)
        if c is not None:
            out.append(claim_to_model(c, turns=turns))
    return out


def _observer(memory_path: Path, settings: Settings) -> str:
    return owner_identity.resolve_observer(memory_path, settings)


@router.post("/projects/{project_id}/milestones", response_model=ProjectWriteResponse)
@_admitted
async def add_milestone(project_id: str, body: MilestoneCreate, settings: Settings = Depends(get_settings)):
    mp = settings.memory_path
    stem = _project_stem(mp, project_id)
    async with _write_lock:
        today = _now().date()
        result = await run_in_threadpool(
            progress.set_milestone, mp, subject=stem, name=body.name, target=body.target,
            observer=_observer(mp, settings), origin="companion_app", authored_by="user", date_basis="person",
            today=today, tz_name=_tz())
        _raise_for(result)
        await _commit(mp, result["paths"], today)
    return ProjectWriteResponse(action=result["action"], claim_id=result["claim_id"], day=today.isoformat(),
                                date_basis="person",
                                claims=await run_in_threadpool(_models, mp, result["entity_id"], [result["claim_id"]]))


@router.patch("/projects/{project_id}/milestones/{slug}", response_model=ProjectWriteResponse)
@_admitted
async def change_milestone(project_id: str, slug: str, body: MilestonePatch,
                           settings: Settings = Depends(get_settings)):
    """A move, a new state, a rename — or a move and a rename together (the
    name first, so the new state carries it). A read-compat `due-<date>` is
    promoted by its first touch (`progress.advance`), and a name sent with it
    renames the milestone that promotion opened."""
    mp = settings.memory_path
    stem = _project_stem(mp, project_id)
    async with _write_lock:
        today = _now().date()
        page, is_due = _find_slot(mp, stem, slug)
        on = _on(body.on, today)
        moves = any(v is not None for v in (body.target, body.status, body.on))
        paths: list[str] = []
        result: dict = {}
        if body.name is not None and not is_due:
            result = await run_in_threadpool(progress.rename_milestone, mp, subject=page, slug=slug, name=body.name)
            _raise_for(result)
            paths += result["paths"]
        if moves or is_due:
            result = await run_in_threadpool(
                progress.advance, mp, subject=page, slug=slug, status=body.status, on=on, target=body.target,
                observer=_observer(mp, settings), origin="companion_app", authored_by="user", date_basis="person",
                today=today, tz_name=_tz())
            _raise_for(result)
            paths += result["paths"]
            if body.name is not None and is_due:
                renamed = await run_in_threadpool(progress.rename_milestone, mp, subject=page,
                                                  slug=result["slug"], name=body.name)
                _raise_for(renamed)
                paths += renamed["paths"]
        if not result:
            raise HTTPException(400, "Say what to change: a name, a date or a state")
        await _commit(mp, paths, today)
    return ProjectWriteResponse(action=result["action"], claim_id=result["claim_id"],
                                day=on.isoformat() if moves or is_due else None,
                                date_basis="person" if moves or is_due else None,
                                claims=await run_in_threadpool(_models, mp, page, [result["claim_id"]]))


@router.post("/projects/{project_id}/happenings", response_model=ProjectWriteResponse)
@_admitted
async def log_happening(project_id: str, body: HappeningCreate, settings: Settings = Depends(get_settings)):
    """The Log. R-PJB15: one time phrase is cut from wherever it sits and
    becomes the day (basis `stated`); two are refused, as is a vaguer time word
    left behind — R-PJ6 keeps every relative word out of the stored sentence.
    The companion episode keeps the words verbatim, and the claim cites it as
    a `user` span (R-PJ18: a span, not a copy). Everything is validated before
    the episode is written, so a refusal writes nothing."""
    mp = settings.memory_path
    stem = _project_stem(mp, project_id)
    text = " ".join((body.text or "").split())
    if not text:
        raise HTTPException(400, "Say what happened")
    if body.status not in ("done", "ongoing"):
        raise HTTPException(400, "A note is done or still going")
    try:
        phrase, rest = when.split_phrase(text)
    except when.TwoDates:
        raise HTTPException(422, TWO_DAYS)
    claim_text = episode_scrub.scrub(rest)[0]
    if not claim_text.strip():
        raise HTTPException(400, "Say what happened")
    if when.has_relative(claim_text):
        raise HTTPException(422, TWO_DAYS)
    async with _write_lock:
        now = _now()
        today = now.date()
        if phrase:
            day, _ = when.resolve(phrase, when.Anchor(now, "turn", when.zone(_tz())), direction=when.PAST)
            if day is None:
                raise HTTPException(422, OUT_OF_RANGE)
            basis = "stated"
        elif body.when:
            day, basis = _on(body.when, today), "person"
        else:
            day, basis = today, "person"
        name = project_timeline._Bank(mp, _tz()).name(stem)
        ep = await run_in_threadpool(progress.write_note_episode, mp, text, origin="companion_app",
                                     title=f"Note on {name}", now=now)
        participants = await run_in_threadpool(progress.link_participants, mp, claim_text)
        result = await run_in_threadpool(
            progress.record_happening, mp, subject=stem, text=claim_text, status=body.status,
            participants=participants, evidence=[{"episode": ep, "quote": episode_scrub.scrub(text)[0]}],
            observer=_observer(mp, settings), origin="companion_app", authored_by="user", day=day, date_basis=basis,
            today=today, now=now, tz_name=_tz())
        if result.get("action") in ("error", "not_found"):
            # The note was written for this claim only: take it back so a
            # refused write leaves nothing behind.
            (Path(mp) / "episodes" / f"{ep}.md").unlink(missing_ok=True)
            bank_index.invalidate()
            _raise_for(result)
        await _commit(mp, [*result["paths"], f"episodes/{ep}.md"], today)
    return ProjectWriteResponse(action=result["action"], claim_id=result["claim_id"], day=result["day"],
                                date_basis=result["date_basis"], episode_id=ep,
                                claims=await run_in_threadpool(_models, mp, result["entity_id"], [result["claim_id"]]))


@router.post("/projects/{project_id}/threads/{claim_id}", response_model=ProjectWriteResponse)
@_admitted
async def settle_thread(project_id: str, claim_id: str, body: ThreadSettle,
                        settings: Settings = Depends(get_settings)):
    """An open thread's answer. Done/dropped writes its own born-closed
    happening that settles the thread; "still going" restates it, which folds
    into the thread (rule 2) and moves `recorded_at` — the quiet clock resets."""
    mp = settings.memory_path
    stem = _project_stem(mp, project_id)
    if body.status not in ("done", "ongoing", "dropped"):
        raise HTTPException(400, "A thread is done, still going or dropped")
    async with _write_lock:
        today = _now().date()
        page, thread = _find_event(mp, stem, claim_id)
        if thread.predicate != HAPPENED or thread.status != "ongoing" or thread.valid_to is not None:
            raise HTTPException(404, f"No open thread {claim_id!r} on this project")
        on = _on(body.on, today)
        result = await run_in_threadpool(
            progress.record_happening, mp, subject=page, text=thread.text, status=body.status,
            participants=thread.participants, settles=claim_id if body.status != "ongoing" else None,
            observer=_observer(mp, settings), origin="companion_app", authored_by="user", day=on, date_basis="person",
            today=today, tz_name=_tz())
        _raise_for(result)
        await _commit(mp, result["paths"], today)
    ids = [result["claim_id"]] + ([claim_id] if result.get("settled") == "closed" else [])
    return ProjectWriteResponse(action=result["action"], claim_id=result["claim_id"], day=result["day"],
                                date_basis=result["date_basis"], claims=await run_in_threadpool(_models, mp, page, ids))


@router.post("/projects/{project_id}/withdraw", response_model=ProjectWriteResponse)
@_admitted
async def withdraw_happening(project_id: str, body: WithdrawRequest, settings: Settings = Depends(get_settings)):
    """"Not right". R-PJB28: happenings only — withdrawing a milestone state
    could leave its slot with no open head. When the claim was not the
    person's own, the withdrawal is an `overruled` verdict (G113, R-PJB24):
    one ids-and-enums ledger row, never the sentence."""
    mp = settings.memory_path
    stem = _project_stem(mp, project_id)
    async with _write_lock:
        today = _now().date()
        page, target = _find_event(mp, stem, body.claim_id)
        if target.predicate == MILESTONE:
            raise HTTPException(400, "Move or drop a milestone with its own controls")
        result = await run_in_threadpool(
            progress.withdraw, mp, subject=page, claim_id=body.claim_id, author="user", reason=WITHDRAW_REASON,
            origin="companion_app", today=today)
        _raise_for(result)
        if result.get("action") == "retracted":
            await _commit(mp, result["paths"], today)
            if not is_human(target):
                telemetry.record(telemetry.UsageEvent(
                    kind="resolution", stage="feedback", bank=mp.name, invocations=0, billing="free",
                    refs={"kind": "happening", "claim_id": body.claim_id, "predicate": HAPPENED, "entity_id": page,
                          "authored_by": target.authored_by or "unknown", "date_basis": target.date_basis,
                          "verdict": "overruled"}))
    return ProjectWriteResponse(action=result["action"], claim_id=body.claim_id, day=today.isoformat(),
                                claims=await run_in_threadpool(_models, mp, page, [body.claim_id]))


# --------------------------------------------------------------------------- #
# whose projects these are, the header, conversations, influences (ruling 45)
# --------------------------------------------------------------------------- #

PROJECT_TRIGGER = "user/companion_app"


def _suggestable_stem(memory_path, project_id: str) -> str:
    """A live project page or a fallback page (a thing called a project) — what accept and dismiss act on."""
    from api.services import project_ownership

    page = resolve_entity_file(memory_path, project_id)
    if page is None:
        raise HTTPException(404, f"No project {project_id!r}")
    fm = markdown_parser.parse(page, ledger=False).frontmatter or {}
    if not project_ownership.is_project_like(fm) or str(fm.get("status") or "active") == "dropped":
        raise HTTPException(404, f"{page.stem!r} is not a project")
    return page.stem


async def _commit_as(memory_path, subject: str, paths: list[str], verb: str = "updated") -> None:
    message = git_service.build_commit_message(
        subject, [f"{p}: {verb} (source: n/a, trigger: {PROJECT_TRIGGER})" for p in dict.fromkeys(paths)],
        authors=["user"])
    try:
        await git_service.commit_paths(memory_path, message, sorted(set(paths)))
    except Exception as exc:  # noqa: BLE001 — the write stands; a later writer's commit picks it up
        logger.warning(f"project write commit skipped: {type(exc).__name__}")


def _refuse(exc: Exception) -> HTTPException:
    return HTTPException(400, str(exc))


@router.post("/projects", response_model=ProjectOwnershipResponse)
@_admitted
async def create_project(body: ProjectCreate, settings: Settings = Depends(get_settings)):
    """New project (the page's one add button): the person typed a name and a description — theirs, listed."""
    from api.services import project_ownership

    mp = settings.memory_path
    async with _write_lock:
        try:
            eid, paths = await run_in_threadpool(
                project_ownership.create, mp, body.name, body.description,
                via=project_ownership.VIA_CLI if body.via == "cli" else project_ownership.VIA_APP, by="user",
                listed=True, today=_now().date())
        except project_ownership.OwnershipError as exc:
            raise HTTPException(409 if "already a page" in str(exc) else 400, str(exc))
        await _commit_as(mp, f"Project created {eid}", paths, "created")
    return ProjectOwnershipResponse(id=eid, action="created", mine=True)


def _group_provider(memory_path, group: str) -> str:
    from api.services import project_conversations

    for f in bank_index.files(memory_path, "episodes"):
        p = project_conversations.ep_provider(f.frontmatter or {})
        if p is not None and p[1] == group:
            return p[0]
    raise HTTPException(404, f"No conversations carry {group!r}")


@router.post("/projects/{project_id}/accept", response_model=ProjectOwnershipResponse)
@_admitted
async def accept_project(project_id: str, body: Optional[ProjectAccept] = None,
                         settings: Settings = Depends(get_settings)):
    """"Add to my projects". A fallback page becomes the project in place; a provider grouping with no page becomes a
    new project page, named by the person, that records the grouping (its conversations are then tied to it)."""
    from api.services import project_ownership

    mp = settings.memory_path
    name = (body.name if body else None) or None
    async with _write_lock:
        today = _now().date()
        try:
            if project_ownership.is_group_id(project_id):
                if not name:
                    raise HTTPException(400, "Name the project to add it")
                provider = _group_provider(mp, project_id)
                eid, paths = await run_in_threadpool(
                    project_ownership.create, mp, name, "", via=project_ownership.VIA_ACCEPTED, by="user",
                    listed=True, provider={"provider": provider, "id": project_id}, today=today)
                await _commit_as(mp, f"Project accepted {eid}", paths, "created")
                return ProjectOwnershipResponse(id=eid, action="created", mine=True)
            stem = _suggestable_stem(mp, project_id)
            paths = await run_in_threadpool(project_ownership.accept, mp, stem, name=name, today=today)
        except project_ownership.OwnershipError as exc:
            raise _refuse(exc)
        if paths:
            await _commit_as(mp, f"Project accepted {stem}", paths)
    return ProjectOwnershipResponse(id=stem, action="accepted" if paths else "unchanged", mine=True)


@router.post("/projects/{project_id}/dismiss", response_model=ProjectOwnershipResponse)
@_admitted
async def dismiss_project(project_id: str, settings: Settings = Depends(get_settings)):
    """"Not mine": nothing is archived, deleted or retyped; the suggestion waits behind "N dismissed"."""
    from api.services import project_ownership

    mp = settings.memory_path
    async with _write_lock:
        today = _now().date()
        try:
            if project_ownership.is_group_id(project_id):
                _group_provider(mp, project_id)
                paths = await run_in_threadpool(project_ownership.dismiss_group, mp, project_id, today=today)
                stem = project_id
            else:
                stem = _suggestable_stem(mp, project_id)
                paths = await run_in_threadpool(project_ownership.dismiss, mp, stem, today=today)
        except project_ownership.OwnershipError as exc:
            raise _refuse(exc)
        if paths:
            await _commit_as(mp, f"Project dismissed {stem}", paths)
    return ProjectOwnershipResponse(id=stem, action="dismissed" if paths else "unchanged", mine=False)


@router.patch("/projects/{project_id}", response_model=ProjectOwnershipResponse)
@_admitted
async def patch_project(project_id: str, body: ProjectPatch, settings: Settings = Depends(get_settings)):
    """The header, edited in place: a rename (the slug never changes; the old name stays findable as an alias) and the
    person's description, which Sleep never rewrites (Q5)."""
    from api.services import project_ownership

    mp = settings.memory_path
    if body.name is None and body.description is None:
        raise HTTPException(400, "Say what to change: a name or a description")
    async with _write_lock:
        stem = _suggestable_stem(mp, project_id)
        try:
            paths = await run_in_threadpool(project_ownership.set_header, mp, stem, name=body.name,
                                            desc=body.description, by="user", today=_now().date())
        except project_ownership.OwnershipError as exc:
            raise _refuse(exc)
        if paths:
            await _commit_as(mp, f"Project header {stem}", paths)
        fm = markdown_parser.parse(Path(mp) / "entities" / f"{stem}.md", ledger=False).frontmatter
    return ProjectOwnershipResponse(id=stem, action="updated" if paths else "unchanged",
                                    mine=project_ownership.is_mine(fm))


@router.get("/projects/{project_id}/conversations", response_model=ProjectConversations)
async def get_project_conversations(project_id: str, request: Request, response: Response, offset: int = 0,
                                    limit: int = 50, settings: Settings = Depends(get_settings)):
    """Every conversation tied to the project and why (repository, the person naming it, Sleep's claims, added by
    hand, the provider's own project, the relaying app's word). Fetched on demand like the timeline (not a Store
    domain); the same ETag folding, and no ETag while the word index builds (`partial`)."""
    from api.services import project_conversations

    mp, tz = settings.memory_path, _tz()
    stem = _project_stem(mp, project_id)
    etag = sync_service.etag_for(mp, "entities", "episodes", "inbox",
                                 extra=f"project-conversations|{stem}|{offset}|{limit}|"
                                       f"{project_timeline.PROJECT_SHAPE}|{tz}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    index_state = await run_in_threadpool(_index_state, mp)
    result = await run_in_threadpool(project_conversations.build, mp, stem, tz_name=tz, offset=offset, limit=limit)
    _unpin_degraded(response, index_state, result)
    return result


@router.post("/projects/{project_id}/conversations", response_model=ProjectOwnershipResponse)
@_admitted
async def tie_conversation(project_id: str, body: ConversationTie, settings: Settings = Depends(get_settings)):
    """Add a conversation to the project, or "Not about this project" (an untie no automatic signal undoes)."""
    from api.services import project_ownership

    mp = settings.memory_path
    async with _write_lock:
        stem = _project_stem(mp, project_id)
        try:
            paths = await run_in_threadpool(project_ownership.tie, mp, stem, body.episode, remove=body.remove)
        except project_ownership.OwnershipError as exc:
            raise _refuse(exc)
        if paths:
            await _commit_as(mp, f"Project conversation {'untied' if body.remove else 'tied'} {stem}", paths)
    return ProjectOwnershipResponse(id=stem, action=("untied" if body.remove else "tied") if paths else "unchanged",
                                    mine=True, episode_id=body.episode)


@router.post("/projects/{project_id}/pages", response_model=ProjectOwnershipResponse)
@_admitted
async def tie_page(project_id: str, body: PageTie, settings: Settings = Depends(get_settings)):
    """"Pages in this project": Add a page by hand, or "Not part of it" — the person's word, which wins over every
    automatic tie and that no agent undoes (decision 10). Adding a page an agent proposed makes it the person's tie."""
    from api.services import project_ownership

    mp = settings.memory_path
    async with _write_lock:
        stem = _project_stem(mp, project_id)
        try:
            paths = await run_in_threadpool(project_ownership.tie_page, mp, stem, body.entity, remove=body.remove)
        except project_ownership.OwnershipError as exc:
            raise _refuse(exc)
        if paths:
            await _commit_as(mp, f"Project page {'not part of it' if body.remove else 'added'} {stem}", paths)
    return ProjectOwnershipResponse(id=stem, action=("removed" if body.remove else "added") if paths else "unchanged",
                                    mine=True, page=body.entity)


@router.post("/projects/{project_id}/influences", response_model=ProjectOwnershipResponse)
@_admitted
async def add_influence(project_id: str, body: InfluenceCreate, settings: Settings = Depends(get_settings)):
    """"Add an influence": a link becomes one of the project's sources (the person's); a page or a name becomes one
    claim as the person's own (a name matching no page stays plain text and never makes a page, Q9). The person's
    optional sentence is a companion episode, cited as their span (R-PJ18)."""
    from api.services import project_influences

    mp = settings.memory_path
    stem = _project_stem(mp, project_id)
    note = " ".join((body.note or "").split())
    async with _write_lock:
        now = _now()
        ep = None
        cited = None
        if note:
            ep = await run_in_threadpool(progress.write_note_episode, mp, note, origin="companion_app",
                                         title=f"Influence on {project_timeline._Bank(mp, _tz()).name(stem)}",
                                         now=now)
            cited = [{"episode": ep, "quote": episode_scrub.scrub(note)[0]}]
        try:
            result = await run_in_threadpool(
                project_influences.add, mp, stem, url=body.url, what=body.what, entity=body.entity, how=body.how,
                observer=_observer(mp, settings), author="user", evidence=cited, today=now.date())
        except project_influences.InfluenceError as exc:
            if ep:
                (Path(mp) / "episodes" / f"{ep}.md").unlink(missing_ok=True)
                bank_index.invalidate()
            raise _refuse(exc)
        await _commit_as(mp, f"Project influence {stem}", [*result["paths"], *([f"episodes/{ep}.md"] if ep else [])])
    return ProjectOwnershipResponse(id=stem, action="added", mine=True, claim_id=result.get("claim_id"),
                                    page=result.get("page"), episode_id=ep)


@router.post("/projects/{project_id}/influences/withdraw", response_model=ProjectOwnershipResponse)
@_admitted
async def withdraw_influence(project_id: str, body: InfluenceWithdraw, settings: Settings = Depends(get_settings)):
    """Undo: a claim is withdrawn and kept as history; a link is removed and remembered (`sources_removed`)."""
    from api.services import fact_sources, project_influences

    mp = settings.memory_path
    stem = _project_stem(mp, project_id)
    async with _write_lock:
        today = _now().date()
        if body.claim_id:
            result = await run_in_threadpool(project_influences.withdraw_claim, mp, body.page or stem, body.claim_id,
                                             today=today)
            if result.get("action") != "retracted":
                raise HTTPException(404, f"No influence {body.claim_id!r} on this project")
            paths = result["paths"]
        elif body.ref:
            changed = await run_in_threadpool(lambda: fact_sources.change_source(
                mp, stem, body.ref, body.predicate, actor=fact_sources.USER, action="remove",
                reason="The person took this influence back"))
            if changed.action != "removed":
                raise HTTPException(404, changed.message or "No such link on this project")
            paths = [f"entities/{stem}.md"]
        else:
            raise HTTPException(400, "Say which influence: its claim or its link")
        await _commit_as(mp, f"Project influence withdrawn {stem}", paths)
    return ProjectOwnershipResponse(id=stem, action="withdrawn", mine=True, claim_id=body.claim_id)
