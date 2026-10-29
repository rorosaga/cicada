"""``POST /tools/call`` — the tool door (G181 phase 2): an MCP tool call, or a `cicada` command's tool mirror, from
another of the person's machines, run here where the bank is (``tool_door``).

Bearer-authed like every route: the server's master token or a device token the person issued (``device_tokens``).
The device that signed the call comes from the token (``request.state.device``), never from the body. The bank is the
request's pinned bank (G183(d)); a `cicada` command that names its bank and the bank's id (``X-Cicada-Bank``,
``X-Cicada-Bank-Id``) is refused before anything runs when the active bank moved (``bank_binding``). The body runs off
the event loop.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.config import Settings, get_settings
from api.services import bank_registry, tool_door

router = APIRouter()


class ToolCaller(BaseModel):
    session_id: str | None = Field(None, max_length=200)
    harness: str | None = Field(None, max_length=64)
    project_dir: str | None = Field(None, max_length=4096)
    client_name: str | None = Field(None, max_length=64)
    client_version: str | None = Field(None, max_length=32)


class ToolState(BaseModel):
    skipped_inbox_ids: list[str] = Field(default_factory=list, max_length=tool_door.MAX_SKIPPED)
    state_hint_sent: bool = False
    listed_revisions: dict[str, str] = Field(default_factory=dict)


class ToolCallRequest(BaseModel):
    tool: str = Field(..., min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    caller: ToolCaller = Field(default_factory=ToolCaller)
    state: ToolState = Field(default_factory=ToolState)
    surface: Literal["mcp", "cli"] = "mcp"
    #: Door options a surface needs beside the tool's own arguments: `cwd` (continue), `delivery` (the primer),
    #: `tz` (the command line's primer), `whole` (the command line's `get`).
    options: dict[str, Any] = Field(default_factory=dict)
    #: G132 phase 1 (ruling 51a): the home's seq the sending device had when it made this write. Recorded beside the
    #: seq the write landed on, never enforced.
    base_seq: int | None = Field(None, ge=0)


def _local_headers():
    from api.services.auth import auth_enabled, get_token

    headers = {"Content-Type": "application/json"}
    if auth_enabled():
        headers["Authorization"] = f"Bearer {get_token()}"
    return headers


async def _to_home(req: ToolCallRequest, request: Request, pin) -> dict:
    """G132 phase 1 B (ruling 51a): on a replica a write — and a read of a store the home keeps outside every bank —
    is a transaction to the home, through the outbox (``tx_outbox``: kept until it lands, in order, keyed once). The
    home's answer comes back as it is; its ``seq`` nudges the follower, and the reply waits up to about 2 s for the
    copy to reach it (read-your-writes). Unreachable, the call is queued and says so."""
    from api.services import idempotency, replica, tx_outbox

    entry = tx_outbox.tool_entry(
        req.tool, req.arguments, bank_id=pin.id if pin is not None else None, base_seq=replica.seq(),
        caller=req.caller.model_dump(), surface=req.surface, options=req.options,
        state=req.state.model_dump(), key=idempotency.clean_key(request.headers.get(idempotency.HEADER)))
    verdict, status, answer = await asyncio.to_thread(tx_outbox.submit, entry, replica.send)
    bank = pin.name if pin is not None else None
    bank_id = pin.id if pin is not None else None
    if verdict == "landed" and isinstance(answer, dict):
        await asyncio.to_thread(replica.wait_for_seq, answer.get("seq"))
        return {**answer, "bank": bank, "bankId": bank_id, "homeSeq": answer.get("seq"), "seq": replica.seq()}
    if verdict in ("rejected", "drop") and isinstance(answer, dict):
        text = answer.get("text") or answer.get("detail") or ""
        return {"text": "", "code": answer.get("code"), "data": None, "segments": None,
                "error": text if isinstance(text, str) and text else f"The home did not take this (HTTP {status}).",
                "state": req.state.model_dump(), "bank": bank, "bankId": bank_id}
    return {"text": tx_outbox.QUEUED_TEXT, "code": "queued_for_home", "data": {"queued": True, "id": entry["id"]},
            "error": None, "segments": None, "state": req.state.model_dump(), "bank": bank, "bankId": bank_id}


@router.post("/tools/call")
async def call_tool(req: ToolCallRequest, request: Request, settings: Settings = Depends(get_settings)):
    from api.services import runtime_layout

    device = getattr(request.state, "device", None)
    pin = bank_registry.pinned_bank()
    memory_path = settings.memory_path
    bank_name = pin.name if pin is not None else None
    from api.services import replica_guard

    if replica_guard.active():
        from api.services import cli_map as _map

        row = _map.by_tool().get(req.tool)
        if row is not None and row.replica_side == "home":
            return await _to_home(req, request, pin)
    caller = tool_door.Caller(session_id=req.caller.session_id or "", harness=req.caller.harness or "unknown",
                              project_dir=req.caller.project_dir, client_name=req.caller.client_name,
                              client_version=req.caller.client_version)
    if len(req.state.listed_revisions) > tool_door.MAX_LISTED:
        raise HTTPException(status_code=400, detail="too many listed revisions")
    state = tool_door.SessionState(skipped_inbox_ids=set(req.state.skipped_inbox_ids),
                                   state_hint_sent=req.state.state_hint_sent,
                                   listed_revisions=dict(req.state.listed_revisions))
    from api.services import agent_live, agent_seen

    # G217: last seen without telemetry — the agent by its catalog id, the device by its token's id.
    await asyncio.to_thread(agent_seen.stamp_agent, agent_live.agent_for(caller.harness, caller.client_name),
                            via="tool", device=device.id if device is not None else None)
    ctx = tool_door.context(memory_path=memory_path, bank_name=bank_name, caller=caller, state=state,
                            surface=req.surface, device_id=device.id if device is not None else None,
                            backend_url=runtime_layout.local_backend_url({"CICADA_PORT": str(settings.port)}),
                            headers=_local_headers)
    from api.services import cli_map, idempotency, sync_log, sync_publish, tool_contract

    row = cli_map.by_tool().get(req.tool)
    mutates = bool(row is not None and row.mutates)
    # Off (the default), one environment read and one stat: no thread hop, no reply change.
    publishing = mutates and sync_publish.enabled() and await asyncio.to_thread(sync_publish.publishable, memory_path)
    # G132 phase 1 B: a replica's transaction (it names the seq it was based on) — its saved episode commits alone,
    # under its harness, so the copy that sent it can read it back.
    ctx.commits_saves = bool(publishing and req.base_seq is not None)

    async def work() -> tuple[int, dict]:
        try:
            answer = await asyncio.to_thread(tool_door.run, req.tool, req.arguments, ctx=ctx, state=state,
                                             surface=req.surface, options=req.options,
                                             root=Path(settings.memory_root), bank_name=bank_name)
        except tool_door.DoorError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from None
        body = {"text": answer.text, "code": answer.code, "data": answer.data, "error": answer.error,
                "segments": [list(seg) for seg in answer.segments] if answer.segments else None,
                "state": state.wire(), "bank": bank_name, "bankId": pin.id if pin is not None else None}
        if publishing:
            # G132 phase 1: the home's head once this write committed, so the sending device knows which seq to wait
            # for before it reads its own write back from its replica.
            body["seq"] = await asyncio.to_thread(sync_log.head_seq, memory_path)
            if req.base_seq is not None:
                await asyncio.to_thread(sync_log.note_base, memory_path,
                                        device.id if device is not None else "server", req.base_seq, body["seq"])
        return 200, body

    if not mutates:
        return (await work())[1]
    # G132 phase 1 (ruling 51a): a mutating call keyed by its device is applied once; a resend (the device never heard
    # the answer) replays the first answer. A refusal or an error is never kept, so it runs again when sent again.
    _, body, _ = await idempotency.run_once(
        idempotency.scope_of(request), f"{idempotency.TOOLS_ROUTE_PREFIX}{req.tool}",
        request.headers.get(idempotency.HEADER), work,
        keep=lambda _status, b: b.get("error") is None and not tool_contract.is_error(b.get("code")))
    return body
