"""The person's yes to having their agent request a chat export (ROR-126).

``GET /export-requests`` lists the live requests for the active bank, ``POST /export-requests/{vendor}`` is the
person's yes for one provider and ``DELETE`` stops one (the export arrived, or they stopped waiting). The agent reports
back through ``cicada_export_requests``; Cicada never opens a browser (``export_requests``). Not a Store domain and no
ETag: a small file read, like ``/agent-methods``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.routers.capture import refuse_capture_into_demo
from api.services import export_requests

router = APIRouter()


def _bank(settings: Settings):
    return settings.memory_path


@router.get("/export-requests")
async def list_requests(settings: Settings = Depends(get_settings)) -> dict:
    try:
        rows = await run_in_threadpool(export_requests.rows, _bank(settings))
    except export_requests.RequestError:
        rows = []
    return {"requests": rows}


@router.post("/export-requests/{vendor}", dependencies=[Depends(refuse_capture_into_demo)])
async def grant(vendor: str, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return await run_in_threadpool(export_requests.grant, _bank(settings), vendor)
    except export_requests.RequestError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/export-requests/{vendor}")
async def stop(vendor: str, settings: Settings = Depends(get_settings)) -> dict:
    try:
        cleared = await run_in_threadpool(export_requests.clear, _bank(settings), vendor)
    except export_requests.RequestError:
        cleared = False
    return {"cleared": cleared}
