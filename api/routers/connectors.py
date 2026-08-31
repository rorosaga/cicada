"""Saved-content connectors (G71 §2): status, credentials, OAuth, sync-now.

Deliberately NOT part of ``/connections`` (G50): that registry describes LLM
engines — ``engine_role``, ``billing``, ``plan_label`` — and ``/status`` picks
the first connected ``engine_role`` as the engine. A Pinterest account is not
an engine, and registering it there would corrupt engine selection.

Credential values enter through ``PUT .../credentials`` and are written to
``$CICADA_HOME/secrets.env`` (0600). They are never returned, never logged, and
never included in an error message.

``ADAPTERS`` / ``LOGIN_MODES`` are dicts keyed by ``CHANNEL_ID``, so Pinterest
(``oauth``), Reddit (``credentials`` — a script app needs no redirect round
trip), and X (``oauth`` again, but PKCE — a public client, no client secret)
sit side by side as peer connectors.

Both OAuth connectors share ``_pending_states`` — one in-process nonce table
keyed by ``state`` — but each entry also records which connector minted it
(``connector``) so a state minted for one can never be replayed against the
other's callback, and X's entry additionally carries the PKCE ``verifier``
generated at ``authorize()`` time and spent once at ``exchange_code()``.
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
from api.services.connectors import base, pinterest, reddit, x

router = APIRouter(prefix="/sources/connectors")

ADAPTERS = {
    pinterest.CHANNEL_ID: pinterest,
    reddit.CHANNEL_ID: reddit,
    x.CHANNEL_ID: x,
}

LOGIN_MODES = {
    pinterest.CHANNEL_ID: "oauth",
    reddit.CHANNEL_ID: "credentials",
    x.CHANNEL_ID: "oauth",
}

# Single-use OAuth nonces: {state: {"expires": ts, "connector": id,
# "verifier": str | None}}. In-process and deliberately not persisted — an
# interrupted sign-in is retried, not resumed. `verifier` is X's PKCE code
# verifier (None for Pinterest, which has no PKCE step); `connector` stops a
# state minted for one OAuth connector from being replayed against the other's
# callback route.
_pending_states: dict[str, dict] = {}
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
    # Fix round 1, M2: a credential save lands only in secrets.env, outside
    # memory_path — bump sync_state.json so the "sources" SSE component
    # actually changes and the Feed page's channel badge doesn't go stale.
    sync_state.record_credentials_changed(settings.memory_path, connector_id)
    return _status(connector_id, settings.memory_path)


@router.delete("/{connector_id}/credentials", response_model=ConnectorStatus)
async def forget_credentials(connector_id: str, settings: Settings = Depends(get_settings)):
    _adapter(connector_id).forget()
    # Fix round 1, M2: same reasoning as `set_credentials` — disconnect must
    # also be visible to the SSE version vector.
    sync_state.record_credentials_changed(settings.memory_path, connector_id)
    return _status(connector_id, settings.memory_path)


@router.post("/{connector_id}/authorize", response_model=ConnectorAuthorizeResponse)
async def authorize(connector_id: str, settings: Settings = Depends(get_settings)):
    """Mint the vendor consent URL the app opens in the user's own browser."""
    adapter = _adapter(connector_id)
    if LOGIN_MODES.get(connector_id) != "oauth":
        raise HTTPException(
            status_code=400,
            detail=f"{connector_id} uses credentials, not an authorization flow",
        )
    missing = [f["name"] for f in adapter.FIELDS if not secret_store.has_secret(f["name"])]
    if missing:
        raise HTTPException(status_code=422, detail="Save the app credentials first")

    now = time.time()
    for st, entry in list(_pending_states.items()):
        if entry["expires"] < now:
            _pending_states.pop(st, None)

    state = pysecrets.token_urlsafe(24)
    base_url = f"http://{settings.host}:{settings.port}"

    if adapter is pinterest:
        url = pinterest.authorize_url(state, base_url=base_url)
        verifier = None
    elif adapter is x:
        verifier, challenge = x.generate_pkce_pair()
        url = x.authorize_url(state, challenge, base_url=base_url)
    else:  # pragma: no cover — defensive; every OAuth adapter above is handled
        raise HTTPException(status_code=400, detail=f"{connector_id} has no authorize flow wired")

    _pending_states[state] = {
        "expires": now + _STATE_TTL_SECONDS,
        "connector": connector_id,
        "verifier": verifier,
    }
    return ConnectorAuthorizeResponse(authorize_url=url, state=state)


def _pop_valid_state(state: str, connector_id: str) -> dict:
    """Pop and validate a pending OAuth state, or raise the standard 400.

    Shared by both callback routes: unknown, expired, or minted for the OTHER
    OAuth connector are all treated identically — a state is single-use and
    connector-scoped.
    """
    entry = _pending_states.pop(state, None)
    if (
        not state
        or entry is None
        or entry["expires"] < time.time()
        or entry.get("connector") != connector_id
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired sign-in state")
    return entry


@router.get("/pinterest/callback", response_class=HTMLResponse)
async def pinterest_callback(
    code: str = Query(""),
    state: str = Query(""),
    settings: Settings = Depends(get_settings),
):
    """Pinterest's OAuth redirect target.

    This is one of two OAuth callback routes with no bearer token (the browser
    cannot send one), so it is gated by the single-use ``state`` nonce minted
    above: an unknown, expired or replayed state exchanges nothing.
    """
    _pop_valid_state(state, pinterest.CHANNEL_ID)
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

    # Fix round 1, M2: the token landed in secrets.env, outside memory_path —
    # bump sync_state.json so "sources" (and the SSE version vector) reflects
    # the freshly-connected account instead of staying stale forever.
    sync_state.record_credentials_changed(settings.memory_path, pinterest.CHANNEL_ID)

    return HTMLResponse(
        "<html><body style='font:14px -apple-system;padding:40px'>"
        "<h2>Pinterest connected</h2>"
        "<p>You can close this tab and go back to Cicada.</p>"
        "</body></html>"
    )


@router.get("/x/callback", response_class=HTMLResponse)
async def x_callback(
    code: str = Query(""),
    state: str = Query(""),
    settings: Settings = Depends(get_settings),
):
    """X's OAuth PKCE redirect target — same shape as Pinterest's callback,
    plus the stored PKCE ``code_verifier`` for this state, spent exactly once.
    """
    entry = _pop_valid_state(state, x.CHANNEL_ID)
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code returned")

    base_url = f"http://{settings.host}:{settings.port}"
    try:
        await x.exchange_code(code, entry.get("verifier") or "", base_url=base_url)
    except base.ConnectorError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        # Never echo the response body: a token error can carry client context.
        logger.warning(f"X code exchange failed: {type(exc).__name__}")
        raise HTTPException(status_code=502, detail="Could not complete X sign-in")

    # Fix round 1, M2 (extended to X): the token landed in secrets.env, outside
    # memory_path — bump sync_state.json so "sources" reflects the
    # freshly-connected account instead of staying stale forever.
    sync_state.record_credentials_changed(settings.memory_path, x.CHANNEL_ID)

    return HTMLResponse(
        "<html><body style='font:14px -apple-system;padding:40px'>"
        "<h2>X connected</h2>"
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
        resources_read=int(result.get("resources_read") or 0),
    )
