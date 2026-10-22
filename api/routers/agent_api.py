"""The agent API on the backend's own port (G213): ``POST /v1/<op>`` for an agent that speaks HTTP, not MCP, plus
the person's management of agent tokens at ``/agent-api/tokens``.

``/v1/*`` and the two documents are not behind the app-wide bearer check (``auth._OpenPaths``): the master token and
a device token are the person's own machines, and an agent is not, so these routes check their own bearer — a
connector token, through ``ConnectorStore.verify_agent`` — and refuse any other. Every operation runs through
``api/remote/agent_api.call`` and the shared remote runtime, exactly as on the G135 listener. A request that carries
an ``Origin`` is refused: no web page drives an agent door from someone's browser.

``/agent-api/tokens`` is behind the app-wide bearer like every route; making one is the master token's alone
(``auth.MASTER_ONLY_WRITE_PREFIXES``), so a device cannot mint a credential that outlives its own revocation. The
token is in exactly one answer — the one that made it — beside the hand-off paragraph for the agent.
"""
from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api.remote import agent_api, catalog, store
from api.remote.app import Limits, _REASONS
from api.remote.runtime import shared as shared_runtime
from api.services import telemetry

router = APIRouter()
LIMITS = Limits()


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _json(status: int, body: dict, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=headers or None)


def _bearer(request: Request) -> str:
    value = (request.headers.get("authorization") or "").strip()
    return value[7:].strip() if value.lower().startswith("bearer ") else ""


def _connector_or_refusal(request: Request):
    """``(connector, None)`` or ``(None, response)``. Also the Origin refusal and the rate limits (R-R28's)."""
    if request.headers.get("origin"):
        return None, _json(*agent_api.refusal(403, "origin", "Browsers can't use the agent API.")[:2])
    connector, reason = store.ConnectorStore().verify_agent(_bearer(request))
    if reason != "ok":
        if not LIMITS.allow_failed_auth():
            return None, _json(429, agent_api.envelope("Too many requests — slow down.", is_error=True,
                                                       code="rate_limited"), {"Retry-After": "60"})
        text = _REASONS.get(reason, _REASONS["unknown"]).replace("connector", "agent")
        return None, _json(401, agent_api.envelope(f"Not allowed: {text}.", is_error=True, code="invalid_token"),
                           {"WWW-Authenticate": 'Bearer realm="cicada"'})
    wait = LIMITS.allow(connector.id)
    if wait is not None:
        return None, _json(429, agent_api.envelope("Too many requests — slow down.", is_error=True,
                                                   code="rate_limited"),
                           {"Retry-After": str(max(1, math.ceil(wait)))})
    return connector, None


@router.get("/llms.txt", include_in_schema=False)
@router.get("/v1/llms.txt", include_in_schema=False)
async def llms_txt(request: Request):
    return PlainTextResponse(agent_api.llms_txt(_base(request)))


@router.get("/v1/openapi.json", include_in_schema=False)
async def openapi(request: Request):
    return JSONResponse(agent_api.openapi(_base(request)))


@router.get("/v1/me", include_in_schema=False)
async def me(request: Request):
    connector, refused = _connector_or_refusal(request)
    if refused is not None:
        return refused
    await run_in_threadpool(store.ConnectorStore().touch, connector.id)
    return agent_api.me(connector)


@router.post("/v1/{op}", include_in_schema=False)
async def operation(op: str, request: Request):
    connector, refused = _connector_or_refusal(request)
    if refused is not None:
        return refused
    raw = await request.body()
    if len(raw) > agent_api.MAX_BODY_BYTES:
        return _json(413, agent_api.envelope("Request body too large.", is_error=True, code="too_large"))
    db = store.ConnectorStore()
    await run_in_threadpool(db.touch, connector.id)
    status, body, headers = await run_in_threadpool(agent_api.call, shared_runtime(), connector, op, raw)
    return _json(status, body, headers)


# ── The person's agent tokens ─────────────────────────────────────────────────


class AgentTokenIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    scopes: list[str] = Field(default_factory=lambda: sorted(catalog.DEFAULT_SCOPES))
    expires_in_days: int = Field(30, alias="expiresInDays")
    #: Where the agent will reach this server — the person's overlay or public address. Only shaped into the
    #: hand-off paragraph; never fetched. Default: the address this request came in on.
    base_url: str | None = Field(None, alias="baseUrl", max_length=300)

    model_config = {"populate_by_name": True}


def _token_out(c: catalog.Connector) -> dict:
    return {"id": c.id, "name": c.label, "scopes": sorted(c.scopes), "createdAt": c.created_at,
            "expiresAt": c.expires_at, "revokedAt": c.revoked_at, "lastUsedAt": c.last_used_at,
            "state": c.state(), "author": c.author}


def _clean_base(raw: str | None, fallback: str) -> str:
    from urllib.parse import urlparse

    value = (raw or "").strip().rstrip("/")
    if not value:
        return fallback
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.query \
            or parsed.fragment:
        raise HTTPException(400, "baseUrl must be an http(s) address with nothing after the host and path.")
    return value


def _event(connector: catalog.Connector, event: str) -> None:
    telemetry.record(telemetry.UsageEvent(
        kind="connector_auth", stage="remote", connection=None, engine=None, model=None, bank=None,
        billing="free", invocations=0, refs={"connector_id": connector.id, "app": "agent-api", "event": event},
    ))


@router.get("/agent-api/tokens")
def list_tokens() -> dict:
    return {"tokens": [_token_out(c) for c in store.ConnectorStore().list() if c.auth == "api"]}


@router.post("/agent-api/tokens", status_code=201)
def create_token(req: AgentTokenIn, request: Request) -> dict:
    base = _clean_base(req.base_url, _base(request))
    try:
        connector, token = store.ConnectorStore().create(app="other", label=req.name, scopes=req.scopes,
                                                         expires_in_days=req.expires_in_days, auth="api")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    _event(connector, "created")
    return {"token": token, "agent": _token_out(connector),
            "prompt": agent_api.handoff_prompt(base, token, connector.label), "baseUrl": base}


@router.delete("/agent-api/tokens/{token_id}")
def revoke_token(token_id: str) -> dict:
    db = store.ConnectorStore()
    existing = db.get(token_id)
    if existing is None or existing.auth != "api":
        raise HTTPException(404, "No such agent token.")
    connector = db.revoke(token_id)
    _event(connector, "revoked")
    return {"agent": _token_out(connector)}
