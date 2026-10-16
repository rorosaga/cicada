"""The person's other devices (G181 phase 2, owner ruling 1, 2026-10-16): issue, list and revoke per-device tokens.

Issuing and revoking are the master token's alone (``auth.MASTER_ONLY_PREFIXES``): a device token is refused there
with 403, so a device can never mint another device or keep itself alive past a revoke. Reading the list is open to a
device token (G181 phase 3), so the person can see from any of their devices which ones reach this server. Machine-global, outside every bank, so none of these routes is
pinned to or checked against a bank (``bank_binding.NO_BANK_WRITE``). The token is in exactly one answer — the
``POST`` that issued it — and is never logged.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

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


@router.post("/devices", status_code=201)
async def create_device(req: DeviceCreateRequest):
    try:
        device, token = await run_in_threadpool(device_tokens.store().create, req.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"device": device.wire(), "token": token}


@router.delete("/devices/{device_id}")
async def revoke_device(device_id: str):
    try:
        device = await run_in_threadpool(device_tokens.store().revoke, device_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such device.") from None
    return {"device": device.wire()}
