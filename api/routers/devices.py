"""The person's other devices (G181 phase 2, owner ruling 1, 2026-10-16): issue, list and revoke per-device tokens.

Master token only (``auth.MASTER_ONLY_PREFIXES``): a device token is refused here with 403, so a device can never
mint another device or keep itself alive past a revoke. Machine-global, outside every bank, so none of these routes is
pinned to or checked against a bank (``bank_binding.NO_BANK_WRITE``). The token is in exactly one answer — the
``POST`` that issued it — and is never logged.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api.services import device_tokens

router = APIRouter()


class DeviceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


@router.get("/devices")
async def list_devices():
    devices = await run_in_threadpool(lambda: device_tokens.store().list())
    return {"devices": [d.wire() for d in devices]}


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
