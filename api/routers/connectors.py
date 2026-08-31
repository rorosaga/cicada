"""Saved-content connectors (G71 §2): status, credentials, OAuth, sync-now.

Deliberately NOT part of ``/connections`` (G50): that registry describes LLM
engines — ``engine_role``, ``billing``, ``plan_label`` — and ``/status`` picks
the first connected ``engine_role`` as the engine. A Pinterest account is not
an engine, and registering it there would corrupt engine selection.

Credential values enter through ``PUT .../credentials`` and are written to
``$CICADA_HOME/secrets.env`` (0600). They are never returned, never logged, and
never included in an error message.

``ADAPTERS`` / ``LOGIN_MODES`` are dicts keyed by ``CHANNEL_ID``, so Pinterest
(``oauth``) and Reddit (``credentials`` — a script app needs no redirect round
trip) sit side by side as peer connectors; a third would be additive too.
"""

from __future__ import annotations

import secrets as pysecrets
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from loguru import logger
from pydantic import BaseModel

from api.config import Settings, get_settings
from api.models.schemas import (
    ConnectorAuthorizeResponse,
    ConnectorField,
    ConnectorStatus,
    ConnectorSyncResult,
    ConnectorsResponse,
)
from api.services import sync_state
from api.services.connections import secrets as secret_store
from api.services.connectors import base, pinterest, reddit

router = APIRouter(prefix="/sources/connectors")

ADAPTERS = {
    pinterest.CHANNEL_ID: pinterest,
    reddit.CHANNEL_ID: reddit,
}

LOGIN_MODES = {pinterest.CHANNEL_ID: "oauth", reddit.CHANNEL_ID: "credentials"}

# Single-use OAuth nonces: {state: expires_at}. In-process and deliberately not
# persisted — an interrupted sign-in is retried, not resumed.
_pending_states: dict[str, float] = {}
_STATE_TTL_SECONDS = 600


class CredentialsBody(BaseModel):
    fields: dict[str, str]


def _adapter(connector_id: str):
    adapter = ADAPTERS.get(connector_id)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"unknown connector '{connector_id}'")
    return adapter


def _status(connector_id: str, memory_path) -> ConnectorStatus:
    adapter = _adapter(connector_id)
    entry = sync_state.read_sync_state(memory_path).get(connector_id) or {}
    return ConnectorStatus(
        id=connector_id,
        label=adapter.LABEL,
        connected=adapter.is_connected(),
        fields=[ConnectorField(**f) for f in adapter.credential_fields()],
        last_sync=entry.get("last_sync") or None,
        last_error=entry.get("last_error") or None,
        detail=None,
        login_mode=LOGIN_MODES[connector_id],
    )


@router.get("", response_model=ConnectorsResponse)
async def list_connectors(settings: Settings = Depends(get_settings)):
    return ConnectorsResponse(
        connectors=[_status(cid, settings.memory_path) for cid in ADAPTERS]
    )


@router.get("/{connector_id}", response_model=ConnectorStatus)
async def get_connector(connector_id: str, settings: Settings = Depends(get_settings)):
    return _status(connector_id, settings.memory_path)


@router.put("/{connector_id}/credentials", response_model=ConnectorStatus)
async def set_credentials(
    connector_id: str, body: CredentialsBody, settings: Settings = Depends(get_settings)
):
    """Store this connector's credentials in ``secrets.env`` (0600).

    Only field names the adapter declares are accepted — an unknown name is a
    422, not a silent write, so this endpoint can never be used to set an
    arbitrary environment variable (an LLM API key, say) by name.
    """
    adapter = _adapter(connector_id)
    allowed = {f["name"] for f in adapter.FIELDS}
    unknown = sorted(set(body.fields) - allowed)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"unknown field(s) for {connector_id}: {', '.join(unknown)}",
        )
    for name, value in body.fields.items():
        try:
            secret_store.set_secret(name, value)
        except ValueError as exc:
            # `exc` describes the shape, never the value.
            raise HTTPException(status_code=422, detail=str(exc))
    logger.info(f"{connector_id}: stored {len(body.fields)} credential field(s)")
    return _status(connector_id, settings.memory_path)


@router.delete("/{connector_id}/credentials", response_model=ConnectorStatus)
async def forget_credentials(connector_id: str, settings: Settings = Depends(get_settings)):
    _adapter(connector_id).forget()
    return _status(connector_id, settings.memory_path)


@router.post("/{connector_id}/authorize", response_model=ConnectorAuthorizeResponse)
async def authorize(connector_id: str, settings: Settings = Depends(get_settings)):
    """Mint the vendor consent URL the app opens in the user's own browser."""
    adapter = _adapter(connector_id)
    if adapter is not pinterest:
        raise HTTPException(
            status_code=400,
            detail=f"{connector_id} uses credentials, not an authorization flow",
        )
    if not secret_store.has_secret(pinterest.APP_ID_ENV) or not secret_store.has_secret(
        pinterest.APP_SECRET_ENV
    ):
        raise HTTPException(status_code=422, detail="Save the app ID and secret first")

    now = time.time()
    for state, expires in list(_pending_states.items()):
        if expires < now:
            _pending_states.pop(state, None)

    state = pysecrets.token_urlsafe(24)
    _pending_states[state] = now + _STATE_TTL_SECONDS
    base_url = f"http://{settings.host}:{settings.port}"
    return ConnectorAuthorizeResponse(
        authorize_url=pinterest.authorize_url(state, base_url=base_url), state=state
    )


@router.get("/pinterest/callback", response_class=HTMLResponse)
async def pinterest_callback(
    code: str = Query(""),
    state: str = Query(""),
    settings: Settings = Depends(get_settings),
):
    """Pinterest's OAuth redirect target.

    This is the one route in the API with no bearer token (the browser cannot
    send one), so it is gated by the single-use ``state`` nonce minted above:
    an unknown, expired or replayed state exchanges nothing.
    """
    expires = _pending_states.pop(state, None)
    if not state or expires is None or expires < time.time():
        raise HTTPException(status_code=400, detail="Invalid or expired sign-in state")
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code returned")

    base_url = f"http://{settings.host}:{settings.port}"
    try:
        await pinterest.exchange_code(code, base_url=base_url)
    except base.ConnectorError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        # Never echo the response body: a token error can carry app-secret context.
        logger.warning(f"Pinterest code exchange failed: {type(exc).__name__}")
        raise HTTPException(status_code=502, detail="Could not complete Pinterest sign-in")

    return HTMLResponse(
        "<html><body style='font:14px -apple-system;padding:40px'>"
        "<h2>Pinterest connected</h2>"
        "<p>You can close this tab and go back to Cicada.</p>"
        "</body></html>"
    )


@router.post("/{connector_id}/sync", response_model=ConnectorSyncResult)
async def sync_now(connector_id: str, settings: Settings = Depends(get_settings)):
    """Run one poll immediately. Mirrors the nightly Sleep-tail poll exactly."""
    adapter = _adapter(connector_id)
    result = await adapter.sync(settings.memory_path, allow_fetch=True)
    return ConnectorSyncResult(
        status=result.get("status", "error"),
        reason=result.get("reason"),
        new=int(result.get("new") or 0),
        seen=int(result.get("seen") or 0),
        error=result.get("error"),
    )
