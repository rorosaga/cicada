"""How the person's devices reach each other (G132 phase 3b): the transport, the relay setting, joining and pairing
over the relay, and LAN discovery. Unset or off, every route here answers what is (nothing set, nothing found) and
nothing starts; the relay modules are imported only inside a route that needs one, after a relay was set."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.services import sync_transport

router = APIRouter()


def _own_token_only(request: Request) -> None:
    from api.services import auth

    if auth.request_device(request) is not None or request.scope.get(auth.RELAY_SENDER_SCOPE):
        raise HTTPException(status_code=403, detail="only the server's own token may do this")


def _link():
    return sync_transport._link()   # noqa: SLF001


# --- the transport and the relay setting ----------------------------------------------------------------------------------

@router.get("/sync/transport")
async def get_transport():
    """Which path the last request took, the counts, the last fallback's time, the relay link's state, and where this
    backend listens for the person's devices (the bind shown in words)."""
    from api.services import sync_direct_listen

    return {**sync_transport.stats(), "listen": sync_direct_listen.wire()}


class RelaySetting(BaseModel):
    url: str | None = Field(None, max_length=512)


@router.get("/sync/relay")
async def get_relay():
    url = sync_transport.relay_url()
    return {"url": url, "on": url is not None, "link": (_link().public_state() if _link() else None),
            "text": ("Off. Your devices reach each other directly on your network or tailnet." if url is None else
                     "Your devices reach each other directly when they can, and through this relay when they "
                     "cannot. It carries only sealed messages it cannot read.")}


@router.put("/sync/relay")
async def put_relay(body: RelaySetting, request: Request, settings: Settings = Depends(get_settings)):
    """Settings → Devices: the relay address, off by default. Set, the link starts now (when this memory is shared);
    cleared, it stops. The server's own token only."""
    _own_token_only(request)
    try:
        await run_in_threadpool(sync_transport.set_relay_url, body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    from api.services import sync_net

    await sync_net.restart_link(request.app, settings.memory_path)
    return await get_relay()


# --- a device of the group joins the relay group over the direct path ---------------------------------------------------

class EnrolBody(BaseModel):
    ed: str = Field(..., min_length=40, max_length=48)
    x: str = Field(..., min_length=40, max_length=48)


@router.post("/sync/enrol")
async def post_enrol(body: EnrolBody, request: Request):
    """A paired device (its own token, checked by the gate) gives its relay keys' public halves and joins the relay
    group: a new epoch, posted before this answer. Only on a home whose relay link runs."""
    from api.services import auth, device_tokens

    device = auth.request_device(request)
    link = _link()
    if device is None or device.kind != "full":
        raise HTTPException(status_code=403, detail="Only one of your computers joins the relay group.")
    if link is None or not link.is_home:
        return JSONResponse(status_code=404, content={"code": "no_relay", "detail": "No relay is set here."})
    try:
        await run_in_threadpool(device_tokens.store().set_relay_key, device.id, body.ed, body.x)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except KeyError:
        raise HTTPException(status_code=404, detail="No such device.") from None
    return await link.enrol({"ed": body.ed, "x": body.x})


# --- pairing over the relay: the home's screen ----------------------------------------------------------------------------

@router.post("/devices/pairing/relay", status_code=201)
async def post_relay_pairing():
    """Settings → Devices, "Add a computer" with a relay set: a one-time code (``device_tokens``, ten minutes, single
    use), the QR (v2: the code, the relay, a random slot and this home's public keys — and its direct address when it
    has one), and the typed path's slot opened too. The screen then polls the session."""
    link = _link()
    if link is None or not link.is_home or not link.connected.is_set():
        return JSONResponse(status_code=409, content={
            "code": "no_relay", "detail": "The relay is not reachable from this computer right now. Pair on your "
                                          "network instead, or try again in a moment."})
    from api.services import device_tokens, home_move, sync_relay_link
    from api.services.sync_relay_pairing import qr_payload

    try:
        pairing, code = await run_in_threadpool(lambda: device_tokens.store().create_pairing(kind="full"))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    session = sync_relay_link.PairingSession(link, pairing.id, code)
    try:
        await sync_relay_link._open_slots(link, session)   # noqa: SLF001
    except Exception:  # noqa: BLE001
        await run_in_threadpool(device_tokens.store().cancel_pairing, pairing.id)
        return JSONResponse(status_code=503, content={"code": "relay_busy",
                                                      "detail": "The relay did not open the pairing; try again."})
    link.pairings[pairing.id] = session
    url = await run_in_threadpool(home_move.own_address)
    return {"session": session.wire(), "code": code, "expiresAt": pairing.expires_at,
            "qr": qr_payload(code, link.url.removesuffix("/v1"), session.qr.slot, link.ep.keys, url=url)}


def _session(session_id: str):
    link = _link()
    session = link.pairings.get(session_id) if link is not None else None
    if session is None:
        raise HTTPException(status_code=404, detail="No such pairing.")
    return link, session


@router.get("/devices/pairing/relay/{session_id}")
async def get_relay_pairing(session_id: str):
    _link_, session = _session(session_id)
    return {"session": session.wire()}


@router.post("/devices/pairing/relay/{session_id}/confirm")
async def confirm_relay_pairing(session_id: str):
    """The person confirmed on this screen: the digits match (typed), or the named computer is theirs (scanned)."""
    from api.services import sync_relay_link
    from api.services.sync_relay_crypto import Refused

    link, session = _session(session_id)
    try:
        return {"session": await sync_relay_link.confirm_pairing(link, session)}
    except Refused as exc:
        return JSONResponse(status_code=409, content={"code": exc.code, "session": session.wire()})
    except KeyError:
        session.state = "expired"
        return JSONResponse(status_code=409, content={"code": "expired", "session": session.wire()})


@router.delete("/devices/pairing/relay/{session_id}")
async def cancel_relay_pairing(session_id: str):
    from api.services import device_tokens, sync_relay_link

    link, session = _session(session_id)
    session.state = "cancelled"
    await sync_relay_link._close_slots(link, session)   # noqa: SLF001
    with __import__("contextlib").suppress(KeyError):
        await run_in_threadpool(device_tokens.store().cancel_pairing, session.id)
    link.pairings.pop(session_id, None)
    return {"session": session.wire()}


# --- pairing over the relay: the new computer's screen ----------------------------------------------------------------

class JoinBody(BaseModel):
    qr: dict | None = None
    code: str | None = Field(None, max_length=32)
    relay: str | None = Field(None, max_length=512)


@router.post("/sync/relay/join", status_code=202)
async def post_join(body: JoinBody, request: Request):
    _own_token_only(request)
    from api.services import device_status, runtime_layout, sync_relay_join
    from api.services.sync_relay_crypto import Refused

    if runtime_layout.is_client():
        raise HTTPException(status_code=409, detail=runtime_layout.MODE_CONFLICT_TEXT)
    if body.qr is None and not (body.code and body.relay):
        raise HTTPException(status_code=400, detail="Scan the code the other computer shows, or type it with its "
                                                    "relay address.")
    if body.relay:
        try:
            sync_transport.check_relay_url(body.relay)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
    try:
        join = sync_relay_join.begin(qr=body.qr, code=body.code, relay=body.relay, name=device_status.machine_name())
    except (Refused, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="That code is not one this computer can read.") from exc
    return join.wire()


@router.get("/sync/relay/join")
async def get_join(request: Request):
    _own_token_only(request)
    from api.services import sync_relay_join

    return sync_relay_join.JOIN.wire() if sync_relay_join.JOIN is not None else {"state": None}


@router.post("/sync/relay/join/confirm")
async def confirm_join(request: Request):
    _own_token_only(request)
    from api.services import sync_relay_join
    from api.services.sync_relay_crypto import Refused

    try:
        return sync_relay_join.confirm()
    except Refused as exc:
        return JSONResponse(status_code=409, content={"code": exc.code})


@router.delete("/sync/relay/join")
async def cancel_join(request: Request):
    _own_token_only(request)
    from api.services import sync_relay_join

    sync_relay_join.cancel()
    return {"state": None}


# --- LAN discovery (the app advertises and browses; the backend checks) ----------------------------------------------

@router.get("/sync/discovery")
async def get_discovery(request: Request, settings: Settings = Depends(get_settings)):
    """What the app advertises and browses for, with a fresh nonce to ask a found peer's ``/sync/hello`` with. Nothing
    while this memory is not shared."""
    _own_token_only(request)
    from api.services import sync_discovery

    got = await run_in_threadpool(sync_discovery.plan, settings.memory_path)
    if got is None:
        raise HTTPException(status_code=404)
    return got


@router.get("/sync/hello")
async def get_hello(nonce: str = Query(..., min_length=8, max_length=128),
                    for_: str = Query(..., alias="for", min_length=8, max_length=32),
                    settings: Settings = Depends(get_settings)):
    """Open: this device signs a nonce for a device of the same memory (the hash), so that device trusts this address
    before any token is sent to it. A device id and a signature only."""
    from api.services import sync_discovery

    got = await run_in_threadpool(sync_discovery.hello, settings.memory_path, nonce, for_)
    if got is None:
        raise HTTPException(status_code=404)
    return got


class Candidate(BaseModel):
    url: str = Field(..., max_length=256)
    nonce: str = Field(..., max_length=128)
    answer: dict


class DiscoveredBody(BaseModel):
    candidates: list[Candidate] = Field(default_factory=list, max_length=16)
    #: The person allowed Cicada to find devices on the local network (the app's own permission state).
    lanAllowed: bool = False


@router.post("/sync/discovered")
async def post_discovered(body: DiscoveredBody, request: Request, settings: Settings = Depends(get_settings)):
    _own_token_only(request)
    from api.services import sync_discovery

    kept = await run_in_threadpool(lambda: sync_discovery.accept(
        settings.memory_path, [c.model_dump() for c in body.candidates], lan_allowed=body.lanAllowed))
    return {"kept": kept, "dial": bool(body.lanAllowed and sync_discovery.associated())}
