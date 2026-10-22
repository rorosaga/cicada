"""The person's other devices (G181 phase 2, owner ruling 1, 2026-10-16): issue, list and revoke per-device tokens.

Issuing and revoking are the master token's alone (``auth.MASTER_ONLY_PREFIXES``): a device token is refused there
with 403, so a device can never mint another device or keep itself alive past a revoke. Reading the list is open to a
device token (G181 phase 3), so the person can see from any of their devices which ones reach this server. Machine-global, outside every bank, so none of these routes is
pinned to or checked against a bank (``bank_binding.NO_BANK_WRITE``). The token is in exactly one answer — the
``POST`` that issued it — and is never logged.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.services import device_tokens

router = APIRouter()


class DeviceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


@router.get("/devices")
async def list_devices(request: Request):
    """Every device the person issued, newest first: ids, names and times only (``lastUsedAt`` is when its token last
    reached this server, stamped at most once a minute). Readable by a device token too (G181 phase 3: a device's app
    shows the person their devices); ``current`` marks the device whose token asked, so its app can say "this Mac"."""
    devices = await run_in_threadpool(lambda: device_tokens.store().list())
    asking = getattr(request.state, "device", None)
    asking_id = asking.id if asking is not None else None
    return {"devices": [{**d.wire(), "current": d.id == asking_id} for d in devices]}


@router.get("/devices/status")
async def devices_status(request: Request, settings: Settings = Depends(get_settings)):
    """G212: this server and each active device, by its own name — connected or not, how it connects (local, SSH,
    Tailscale, LAN; read from its requests), when it was last seen, and how many of its conversations wait for Sleep.
    One list for the Sleep page's strip and Settings → Devices. Readable by a device token too (``current`` marks the
    asking device). Not a Store domain, no ETag: a small body that changes by the minute; poll it while visible."""
    from api.services import device_status

    asking = getattr(request.state, "device", None)
    return await run_in_threadpool(device_status.snapshot, settings.memory_path,
                                   asking_device=asking.id if asking is not None else None)


@router.post("/devices", status_code=201)
async def create_device(req: DeviceCreateRequest):
    """Issue a token. ``sameName`` lists the ACTIVE devices already called that (case and spaces aside): two devices
    may share a name — it is the person's label, never an identity — but the client says so (headless QA, 2026-10-16),
    since a list of two "laptop" rows cannot say which one to revoke."""
    store = device_tokens.store()

    def work():
        wanted = " ".join(req.name.split()).casefold()
        same = [d.id for d in store.list() if d.active and " ".join(d.name.split()).casefold() == wanted]
        device, token = store.create(req.name)
        return device, token, same

    try:
        device, token, same = await run_in_threadpool(work)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"device": device.wire(), "token": token, "sameName": same}


@router.delete("/devices/{device_id}")
async def revoke_device(device_id: str):
    try:
        device = await run_in_threadpool(device_tokens.store().revoke, device_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such device.") from None
    return {"device": device.wire()}


# ── G212: pairing a new device with a one-time code ─────────────────────────────
# The person's own screen shows the code (the app draws it as a QR, `{v, url, code}`); the new device posts it to
# `POST /pair` — open, the code being its credential — and gets its own device token, exactly as `POST /devices`
# would have issued it. Making a code is the master token's alone (under `/devices`, `auth.MASTER_ONLY_PREFIXES`):
# a device can never mint another device. Possession of a code shown on the person's screen is the person's act
# (ruling 28.1), the trust shape of ruling 32's typed sign-in code.

_WRONG_CODES = None


def _wrong_codes():
    global _WRONG_CODES
    if _WRONG_CODES is None:
        from api.remote.oauth import Bucket

        _WRONG_CODES = Bucket(10, 10)   # a typo is fine; a guessing loop is not
    return _WRONG_CODES


class PairingCreateRequest(BaseModel):
    #: Where the new device will reach this server — the person's overlay address (`https://…`, or `http://` to a
    #: loopback address only, the client rule of ruling 28). Carried in the QR; never fetched. Omit and the app fills it.
    url: str | None = Field(None, max_length=300)


class PairRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=40)
    #: The device's own name for itself (its host name, the phone's name) — what the person sees in Devices.
    name: str = Field(..., min_length=1, max_length=200)


def _pair_url(raw: str | None) -> str | None:
    from urllib.parse import urlparse

    value = (raw or "").strip().rstrip("/")
    if not value:
        return None
    parsed = urlparse(value)
    loopback = parsed.hostname in ("127.0.0.1", "localhost", "::1")
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not (parsed.scheme == "https" or (parsed.scheme == "http" and loopback))):
        raise HTTPException(status_code=400, detail="Use the https:// address your overlay gives this server "
                                                    "(plain http only to this machine itself).")
    return value


@router.post("/devices/pairing", status_code=201)
async def create_pairing(req: PairingCreateRequest):
    url = _pair_url(req.url)
    try:
        pairing, code = await run_in_threadpool(device_tokens.store().create_pairing)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"pairing": pairing.wire(), "code": code, "qr": {"v": 1, "url": url, "code": code}}


@router.get("/devices/pairing/{pairing_id}")
async def get_pairing(pairing_id: str):
    pairing = await run_in_threadpool(device_tokens.store().pairing, pairing_id)
    if pairing is None:
        raise HTTPException(status_code=404, detail="No such pairing.")
    device = None
    if pairing.device_id:
        found = await run_in_threadpool(device_tokens.store().get, pairing.device_id)
        device = found.wire() if found else None
    return {"pairing": pairing.wire(), "device": device}


@router.delete("/devices/pairing/{pairing_id}")
async def cancel_pairing(pairing_id: str):
    try:
        pairing = await run_in_threadpool(device_tokens.store().cancel_pairing, pairing_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such pairing.") from None
    return {"pairing": pairing.wire()}


@router.post("/pair", status_code=201)
async def redeem_pairing(req: PairRequest):
    """Open (``auth._STATIC_OPEN_PATHS``): the code is the credential. Any code that matches nothing waiting is one
    404, whatever the reason, and ten a minute is the most this door answers."""
    if not _wrong_codes().take():
        raise HTTPException(status_code=429, detail="Too many codes — wait a minute.", headers={"Retry-After": "60"})
    try:
        device, token = await run_in_threadpool(lambda: device_tokens.store().redeem(req.code, req.name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except KeyError:
        raise HTTPException(status_code=404, detail="No pairing waits with that code — it was used, cancelled or "
                                                    "expired. Ask for a new one.") from None
    return {"device": device.wire(), "token": token}
