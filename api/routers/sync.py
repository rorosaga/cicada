"""Version vector + SSE change stream for the app's sync engine (G58)."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.services import sync_service, sync_status, sync_ticker
from api.services.sleep_cycle import get_sleep_state

router = APIRouter(prefix="/sync")
POLL_SECONDS = 1.0
# Keep-alive cadence for the SSE stream. This MUST stay comfortably below the
# companion app's SSE idle timeout (`APIClient.syncEventLines` sets
# `timeoutInterval = 3600`, an *idle* timeout): a silent stream longer than
# that interval is torn down client-side and the app falls back to polling.
# It must also stay below any proxy's idle timeout if one is ever put in front.
PING_SECONDS = 15.0
# A tick younger than this is shared with every other subscriber of the bank (audit A10): below POLL_SECONDS, so
# each stream still sees a fresh computation every poll.
SHARED_TICK_SECONDS = 0.9 * POLL_SECONDS


@router.get("/version")
async def get_version(settings: Settings = Depends(get_settings)):
    info = await run_in_threadpool(sync_service.version, settings.memory_path, get_sleep_state())
    return {"version": info.version, "components": info.components}


def _event(name: str, payload) -> str:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


@router.get("/events")
async def events(settings: Settings = Depends(get_settings)):
    from api.services import replica_guard

    replica_on = replica_guard.active()

    async def stream():
        last = None
        last_sleep = None
        since_ping = 0.0
        while True:
            # Audit A10: one version + debt computation per bank per tick, shared by every subscriber, off the loop.
            tick = await sync_ticker.current(settings.memory_path, settings, max_age=SHARED_TICK_SECONDS)
            # Phase-lock onto the shared tick: a stream handed a tick computed `age` seconds ago polls again when it
            # is POLL_SECONDS old, so every stream of a bank converges on one computation per second and none
            # sees a change later than it would have alone (audit A10 review).
            next_poll = sync_ticker.next_poll_delay(tick, POLL_SECONDS)
            info = tick.info
            if info.version != last:
                last = info.version
                yield _event("version", {"version": info.version, "components": info.components})
                since_ping = 0.0
            state = get_sleep_state()
            # G106 amendment: Rested % and Progress % are SSE-driven, computed fresh every tick; the debt comes from
            # the same shared tick as the version (audit A10). The event is built in one place (`sync_status`), so
            # the home's published status frame (G132) carries the same keys by construction.
            sleep_key, sleep_payload = sync_status.sleep_event(state, tick.debt, settings.memory_path)
            if replica_on:
                # G132 phase 1 B (51d): a copy's Sleep is the home's — its own `sleep` events as the follower heard
                # them — with what this device still has on its way beside it (counts only).
                from api.services import replica

                home_sleep = replica.home_sleep()
                if home_sleep:
                    sleep_payload = {**home_sleep, "outbox": sync_status.outbox_counts()}
                    sleep_key = json.dumps(sleep_payload, sort_keys=True, default=str)
            if sleep_key != last_sleep:
                last_sleep = sleep_key
                yield _event("sleep", sleep_payload)
            if since_ping >= PING_SECONDS:
                yield "event: ping\ndata: {}\n\n"
                since_ping = 0.0
            await asyncio.sleep(next_poll)
            since_ping += next_poll

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- G132 phase 1 (ruling 51): the home publishes its log -------------------------------------------------------------
#
# Off by default (`sync_publish`): off, every route below but the switch answers a plain 404 and nothing is written.
# A full device token or the server's own token; a capture-only device is refused by `require_token` (its exact route
# list), the switch's writes are the server's own token only (`auth.MASTER_ONLY_WRITE_PREFIXES`). A demo bank is never
# published. The log carries seq, sha, parent and time only; subjects and paths travel inside the pack alone.


class PublishSwitch(BaseModel):
    publish: bool


def _published_bank(settings: Settings) -> Path:
    from api.services import sync_publish

    if not sync_publish.publishable(settings.memory_path):
        raise HTTPException(status_code=404)
    from api.services import capture_commit

    capture_commit.resume(settings.memory_path)   # records a previous process left are committed once settled
    return settings.memory_path


def _bank_id() -> str | None:
    from api.services import bank_registry

    pin = bank_registry.pinned_bank()
    return pin.id if pin is not None else None


def _refused(exc: Exception) -> JSONResponse:
    from api.services import sync_log

    if isinstance(exc, sync_log.HistoryRewritten):
        return JSONResponse(status_code=409, content=exc.body())
    return JSONResponse(status_code=503, content={
        "code": "unavailable", "detail": "This memory's history could not be read just now; nothing was changed."})


async def _fresh_primer(memory_path: Path, settings: Settings) -> None:
    """A replica never serves an older primer than the home's `_state.md`: bring it current before the log is read
    (it commits alone, and is skipped while Sleep holds the pages — the run's tail refreshes it then)."""
    from api.services import state_dictionary

    await state_dictionary.refresh_admitted(memory_path, settings)


def _switch_body(settings: Settings) -> dict:
    from api.services import sync_log, sync_publish

    from api.services import demo_guard

    on = sync_publish.enabled()
    # The real answer whatever the switch says (review of #567): the app offers sharing only for a memory that is
    # not a demo, and says so when it is one.
    body = {"publish": on, "source": sync_publish.source(), "demo": demo_guard.is_demo(settings.memory_path),
            "log": None}
    if on:
        if sync_publish.publishable(settings.memory_path):
            body["log"] = sync_log.state(settings.memory_path)
    return body


@router.get("/publish")
async def get_publish(settings: Settings = Depends(get_settings)):
    return await run_in_threadpool(_switch_body, settings)


@router.put("/publish")
async def put_publish(body: PublishSwitch, settings: Settings = Depends(get_settings)):
    from api.services import sync_publish

    await run_in_threadpool(sync_publish.set_enabled, body.publish)
    return await run_in_threadpool(_switch_body, settings)


@router.post("/publish/from-here")
async def publish_from_here(settings: Settings = Depends(get_settings)):
    """The person's "publish from here" after a rewritten history (51e3): this history is published from now on, and
    replicas copy the bank again."""
    from api.services import sync_log

    memory_path = _published_bank(settings)
    try:
        head = await run_in_threadpool(sync_log.publish_from_here, memory_path)
    except (sync_log.HistoryRewritten, sync_log.Unavailable) as exc:
        return _refused(exc)
    return {"bankId": _bank_id(), "head": head.wire()}


@router.get("/log")
async def get_log(since: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=1000),
                  settings: Settings = Depends(get_settings)):
    from api.services import sync_log

    memory_path = _published_bank(settings)
    await _fresh_primer(memory_path, settings)
    try:
        head, entries, more = await run_in_threadpool(sync_log.since, memory_path, since, limit)
    except (sync_log.HistoryRewritten, sync_log.Unavailable) as exc:
        return _refused(exc)
    return {"bankId": _bank_id(), "head": head.wire(), "entries": entries, "more": more}


@router.get("/pack")
async def get_pack(have: str | None = Query(None, max_length=64), settings: Settings = Depends(get_settings)):
    from api.services import sync_log, sync_pack

    memory_path = _published_bank(settings)
    import time

    started = time.perf_counter()
    try:
        pack = await run_in_threadpool(sync_pack.build, memory_path, have)
    except sync_pack.UnknownBase:
        return JSONResponse(status_code=404, content={
            "code": "unknown_base", "detail": "That commit is not one this memory published; ask without `have`."})
    except sync_pack.TooLarge:
        return JSONResponse(status_code=413, content={
            "code": "too_large", "detail": "This memory's history is larger than one pack may be."})
    except (sync_log.HistoryRewritten, sync_log.Unavailable) as exc:
        return _refused(exc)
    headers = {"X-Cicada-Seq": str(pack.seq), "X-Cicada-Head": pack.sha, "X-Cicada-Bank-Id": _bank_id() or "",
               # G132 phase 1 B: how long the bundle took to build here, so a replica splits its fetch time.
               "X-Cicada-Build-Ms": f"{(time.perf_counter() - started) * 1000:.1f}"}
    if pack.path is None:
        return Response(status_code=204, headers=headers)
    return FileResponse(pack.path, media_type="application/x-git-bundle", headers=headers,
                        background=BackgroundTask(pack.cleanup))


@router.get("/status")
async def get_status(settings: Settings = Depends(get_settings)):
    from api.services import replica_guard

    if replica_guard.active():
        # G132 phase 1 B (51d): a copy shows the home's frame at its own seq, with its own outbox beside it.
        return await run_in_threadpool(sync_status.replica_frame, settings.memory_path, bank_id=_bank_id(),
                                       bank=_bank_name())
    memory_path = _published_bank(settings)
    await _fresh_primer(memory_path, settings)
    tick = await sync_ticker.current(memory_path, settings, max_age=SHARED_TICK_SECONDS)
    return await run_in_threadpool(sync_status.frame, memory_path, settings, get_sleep_state(), tick.debt,
                                   bank_id=_bank_id(), bank=_bank_name())


def _bank_name() -> str | None:
    from api.services import bank_registry

    pin = bank_registry.pinned_bank()
    return pin.name if pin is not None else None


# --- G132 phase 1 B: this computer keeps a copy (replica mode) -------------------------------------------------------


class ReplicaSetup(BaseModel):
    home: str
    #: A device token the home issued (`cicada device add`), or the one-time ``code`` its Devices page shows for
    #: "Pair a device" (a computer's, full) — redeemed here at the home's ``/pair``, the token never shown.
    token: str | None = None
    code: str | None = None


@router.get("/replica")
async def get_replica():
    """Where this computer stands: ``mode`` (local, client, replica), the follower's words and seqs, and what is on its
    way to the home — counts only. A full device or the server's own token may read it."""
    from api.services import replica, runtime_layout

    body = {"mode": runtime_layout.mode(), "conflict": runtime_layout.mode_conflict(), "replica": None,
            "outbox": None}
    if body["mode"] == "replica":
        body["replica"] = replica.state()
        body["outbox"] = await run_in_threadpool(sync_status.outbox_counts)
        try:
            from api.services import tool_client

            body["home"] = tool_client.host_of(runtime_layout.replica_of())
        except ValueError:
            body["home"] = None
    return body


@router.put("/replica")
async def put_replica(body: ReplicaSetup):
    """The person's "Keep a full copy here": check the home answers with this token and publishes a memory that is
    not a demo, then write ``$CICADA_HOME/replica_of`` and ``device_token`` (0600). Used from the next start of this
    computer's backend (the app restarts it). The server's own token only; never while this computer is a client."""
    from api.services import runtime_layout, tool_client

    if runtime_layout.is_client():
        raise HTTPException(status_code=409, detail=runtime_layout.MODE_CONFLICT_TEXT)
    from api.config import get_settings as _settings
    from api.services import sleep_cycle, write_admission

    # Review of #567: never while Sleep runs or a write is in flight here — the switch takes effect at the restart that
    # follows, and that restart would wait on (or cut) the run. Nothing is written.
    if sleep_cycle.get_sleep_state().status == "running" or write_admission.holders(_settings().memory_path) > 0:
        raise HTTPException(status_code=409, detail="Sleep is running on this computer; keep a copy once it is done.")
    env = {"CICADA_REPLICA_OF": body.home.strip(), "CICADA_HOME": str(runtime_layout.cicada_home())}
    try:
        base = runtime_layout.replica_of(env)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    from api.services import replica

    token = (body.token or "").strip()
    if not token and (body.code or "").strip():
        from api.services import device_status

        status, _h, paired = await run_in_threadpool(
            replica.request, "POST", "/pair",
            body=json.dumps({"code": body.code.strip(), "name": device_status.machine_name(), "kind": "full"}).encode(),
            headers={"Content-Type": "application/json"}, environ=env, timeout=10, open_route=True)
        if status is None:
            raise HTTPException(status_code=502, detail="That computer did not answer. Check its address.")
        if status not in (200, 201) or not isinstance(paired, dict) or not paired.get("token"):
            detail = paired.get("detail") if isinstance(paired, dict) else None
            raise HTTPException(status_code=400, detail=detail or "That code was not accepted.")
        token = paired["token"]
    if not token.startswith(runtime_layout.DEVICE_TOKEN_PREFIX):
        # Only a device token the home issued is ever saved or sent — never this computer's own master token.
        raise HTTPException(status_code=400, detail="Give the code that computer shows, or its device token.")
    status, _h, frame = await run_in_threadpool(replica.request, "GET", "/sync/status", environ=env, timeout=10,
                                                token=token)
    if status is None:
        raise HTTPException(status_code=502, detail="That computer did not answer. Check its address.")
    if status in (401, 403):
        raise HTTPException(status_code=403, detail="That computer did not accept this code.")
    if status == 404:
        raise HTTPException(status_code=409, detail="That computer is not sharing its memory yet (\"Share this "
                                                    "memory with my other computers\" is off there), or it holds a "
                                                    "demo, which is never copied.")
    if status != 200 or not isinstance(frame, dict) or not frame.get("bankId"):
        raise HTTPException(status_code=502, detail="That computer answered something unexpected.")
    home = runtime_layout.cicada_home()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, value in ((runtime_layout.DEVICE_TOKEN_FILE, token), (runtime_layout.REPLICA_FILE, base)):
        tmp = home / f".{name}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value + "\n")
        os.replace(tmp, home / name)
    return {"mode": "replica", "home": tool_client.host_of(base), "restart": True,
            "text": "This computer will keep a copy of that memory from its next start."}


@router.delete("/replica")
async def delete_replica(settings: Settings = Depends(get_settings)):
    """Stop keeping a copy: remove ``replica_of`` and make the bank this computer had open before it kept one active
    again (``replica.leave_copy``) — the copy stays on disk, inactive, and is never written outside replica mode. The
    token stays. Takes effect from the backend's next start (the app restarts it)."""
    from api.services import replica, runtime_layout

    back_to = await run_in_threadpool(replica.stop_keeping_a_copy, Path(settings.memory_root))
    return {"mode": runtime_layout.mode(), "restart": True, "bank": back_to}


@router.post("/replica/restart")
async def post_restart():
    """Start this computer's backend again so a change of mode (keeping a copy, or no longer) takes effect: the same
    process image re-executed in place a moment after this answer (``os.execv`` of its own command line), so whatever
    started it — the background service or the app — keeps it. Refused while Sleep is running here (DR-41)."""
    from api.services import sleep_cycle

    if sleep_cycle.get_sleep_state().status == "running":
        raise HTTPException(status_code=409, detail="Sleep is running on this computer; restart once it is done.")
    import sys
    import threading

    from api.config import get_settings as _settings
    from api.services import git_service, replica, replica_guard

    memory_path = _settings().memory_path

    def again():
        import time

        time.sleep(0.5)
        if replica_guard.active():
            # Review of #566: never cut an apply short — the follower stops taking new work, and the bank's write lock
            # (held for the whole of an apply) is taken before the process image is replaced.
            replica._STOP.set()
            replica.wake()
            git_service.write_lock(memory_path).acquire(timeout=120)
        os.execv(sys.executable, list(getattr(sys, "orig_argv", None) or [sys.executable, *sys.argv]))

    threading.Thread(target=again, name="cicada-restart", daemon=True).start()
    return {"restarting": True}


@router.post("/replica/recopy")
async def post_recopy():
    """The person's "Copy again" after the home's history changed (51e3): the home's whole tree over this copy."""
    from api.services import replica, replica_guard

    if not replica_guard.active():
        raise HTTPException(status_code=404)
    try:
        timings = await run_in_threadpool(replica.recopy)
    except replica.NoDeviceToken:
        return JSONResponse(status_code=409, content={"code": "no_device_token", "detail": replica.TEXTS["no_token"]})
    except replica.NoLongerACopy:
        # Review of #567: "Stop keeping a copy" landed while this copy was being replaced — nothing was written.
        return JSONResponse(status_code=409, content={"code": "no_longer_a_copy", "detail": replica.TEXTS["stopping"]})
    except replica.HomeError as exc:
        return JSONResponse(status_code=502, content={"code": "home_away" if exc.status is None else "home_refused",
                                                      "detail": replica.TEXTS["offline"]})
    return {"replica": replica.state(), "timings": timings}


# --- G132 phase 2 (ruling 51a): moving the home -----------------------------------------------------------------------
#
# One concept, the home: the device that orders every write and runs Sleep. `GET /sync/home` is what the Sleep page
# draws (the home with its state, every other device online or not and how far behind); a computer that shares nothing
# answers `{"shared": false}` and nothing new is drawn. A move is asked of the home (`POST /sync/home/move`, the
# person's own token or one of their full devices — a copy's Sleep page forwards it there); a take-over is this
# computer's own act on the person's OK (`POST /sync/home/take-over`, this computer's token only). Devices tell their
# home about themselves (`POST /sync/devices/me`) and mirror the group's registry (`GET /sync/devices`); any device
# asks another which home it knows (`GET /sync/peer`, checked by the route itself).


class MoveBody(BaseModel):
    device: str


class TakeOverBody(BaseModel):
    #: How far behind the person was shown (the preview's ``behind``): a take-over goes ahead only on that number.
    behind: int
    confirm: bool = False


class AnnounceBody(BaseModel):
    signKey: dict | None = None
    address: str | None = None
    bankId: str | None = None
    seq: int | None = None


def _refused_move(exc) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"code": exc.code, "detail": exc.text})


@router.get("/home")
async def get_home(settings: Settings = Depends(get_settings)):
    from api.services import home_move

    return await run_in_threadpool(home_move.overview, settings.memory_path)


@router.post("/home/move")
async def post_home_move(body: MoveBody, settings: Settings = Depends(get_settings)):
    """Make ``device`` the home: this computer closes to writes, parks Sleep, commits the signed record naming it as
    its last commit, and follows it once it answers as the home. Answers at once (202) with the progress; the Sleep
    page follows ``GET /sync/home``."""
    from api.services import home_move

    try:
        progress = await run_in_threadpool(home_move.start_move, settings.memory_path, body.device.strip())
    except home_move.MoveRefused as exc:
        return _refused_move(exc)
    return JSONResponse(status_code=202, content={"moving": progress})


@router.get("/home/take-over")
async def get_take_over(settings: Settings = Depends(get_settings)):
    """What the person is shown before a take-over: how far behind this copy is of the last home it saw, and when."""
    from api.services import home_move

    return await run_in_threadpool(home_move.take_over_preview, settings.memory_path)


@router.post("/home/take-over")
async def post_take_over(body: TakeOverBody, settings: Settings = Depends(get_settings)):
    """The person confirmed (``confirm`` and the ``behind`` they were shown): this copy becomes the home."""
    from api.services import home_move

    if not body.confirm:
        return JSONResponse(status_code=400, content={"code": "not_confirmed",
                                                      "detail": "A take-over needs your confirmation."})
    try:
        return await run_in_threadpool(lambda: home_move.take_over(settings.memory_path, behind_seen=body.behind))
    except home_move.MoveRefused as exc:
        return _refused_move(exc)


async def _shared(settings: Settings) -> None:
    from api.services import home_move

    if await run_in_threadpool(home_move.role, settings.memory_path) == "local":
        raise HTTPException(status_code=404)


@router.get("/devices")
async def get_sync_devices(settings: Settings = Depends(get_settings)):
    """The group's registry, for a full device to mirror: ids, names, kinds, times, the sha256 of each token (never a
    token), the public signing key, the address. Only while this memory is shared."""
    from api.services import home_move

    await _shared(settings)
    rows = await run_in_threadpool(home_move.registry, settings.memory_path)
    return {"devices": rows}


@router.get("/keys")
async def get_sync_keys(since: float = Query(0, ge=0), settings: Settings = Depends(get_settings)):
    """The idempotency keys this home kept (their sha256 and the answers they replay, 8 days), for the person's other
    full devices: a write sent again after the home moved is applied once there too (review of #569). Only while
    this memory is shared."""
    from api.services import idempotency

    await _shared(settings)
    return {"keys": await run_in_threadpool(idempotency.export_since, since)}


@router.post("/devices/me")
async def post_sync_devices_me(body: AnnounceBody, request: Request, settings: Settings = Depends(get_settings)):
    """A device of the group says where it is reached, the key it signs a hand-off with (set once) and how far its
    copy is. Its own token only; never this computer's own."""
    from api.services import device_tokens, home_move, runtime_layout

    await _shared(settings)
    device = getattr(request.state, "device", None)
    if device is None:
        raise HTTPException(status_code=400, detail="Only a device of the group says this about itself.")
    address = None
    if body.address is not None:
        if body.address.strip():
            try:
                address = runtime_layout._checked_base(body.address.strip(), "address")   # noqa: SLF001
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from None
        else:
            address = ""
    try:
        await run_in_threadpool(lambda: device_tokens.store().announce(
            device.id, sign_jwk=body.signKey, address=address, bank_id=body.bankId, seq=body.seq))
    except KeyError:
        raise HTTPException(status_code=404, detail="No such device.") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    rows = await run_in_threadpool(home_move.registry, settings.memory_path)
    return {"ok": True, "term": await run_in_threadpool(home_move.term, settings.memory_path),
            "registry": home_move.registry_digest(rows)}


@router.get("/peer")
async def get_peer(request: Request, settings: Settings = Depends(get_settings)):
    """Another device of the group asks which home this computer knows (open path, checked here: the bearer must be a
    device of this computer's store or of the registry it mirrored). Ids and numbers only."""
    from api.services import auth, home_move

    token = auth.credential(request.headers.get("authorization"))
    if await run_in_threadpool(home_move.peer_caller, settings.memory_path, token) is None:
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")
    if await run_in_threadpool(home_move.role, settings.memory_path) == "local":
        raise HTTPException(status_code=404)
    return await run_in_threadpool(home_move.peer_answer, settings.memory_path)
