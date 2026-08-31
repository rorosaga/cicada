"""Saved-content connectors (G71 §2): status, credentials, OAuth, sync-now.

Deliberately NOT part of ``/connections`` (G50): that registry describes LLM
engines — ``engine_role``, ``billing``, ``plan_label`` — and ``/status`` picks
the first connected ``engine_role`` as the engine. A Pinterest account is not
an engine, and registering it there would corrupt engine selection.

Credential values enter through ``PUT .../credentials`` and are written to
``$CICADA_HOME/secrets.env`` (0600). They are never returned, never logged, and
never included in an error message.

``ADAPTERS`` (the shared registry, ``api/services/connectors/__init__.py``) is
keyed by ``CHANNEL_ID``, so Pinterest (``oauth``), Reddit (``credentials`` — a
script app needs no redirect round trip), and X (``oauth`` again, but PKCE —
a public client, no client secret) sit side by side as peer connectors.
``LOGIN_MODE`` is a per-adapter module constant, not a second parallel dict.

Every OAuth connector shares ``_pending_states`` — one in-process nonce table
keyed by ``(connector_id, state)``, mapping to its expiry timestamp. Keying by
the pair (rather than a bare ``state`` plus a ``connector`` field to check
separately) means a state minted for one connector is rejected by
construction if replayed against another's callback — there is no second
check to remember. Any adapter-specific state (X's PKCE verifier) lives
inside that adapter module instead of here (Task 15 §3) — this router treats
every OAuth adapter identically through ``authorize_url(state, *, base_url)``
and ``exchange_code(code, *, state, base_url)``, with ONE generic callback
route rather than one per connector.
"""

from __future__ import annotations

import html
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
from api.services.connectors import ADAPTERS, base

router = APIRouter(prefix="/sources/connectors")

# Single-use OAuth nonces: {(connector_id, state): expires_ts}. In-process and
# deliberately not persisted — an interrupted sign-in is retried, not resumed.
_pending_states: dict[tuple[str, str], float] = {}
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
        login_mode=adapter.LOGIN_MODE,
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

    All-or-nothing (Devin round-1, finding 3): every submitted field's VALUE
    shape is validated before ANY of them are written. Previously validation
    (via ``set_secret``'s own ``ValueError``) and the write happened in the
    same loop iteration, so a request with one valid field followed by one
    invalid one (blank, multiline) left the valid field persisted even
    though the request as a whole came back 422 — the caller had no way to
    tell a credential had partially changed underneath a failed response.
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
            secret_store.validate_secret_value(value)
        except ValueError as exc:
            # `exc` describes the shape, never the value.
            raise HTTPException(status_code=422, detail=f"{name}: {exc}")
    for name, value in body.fields.items():
        secret_store.set_secret(name, value)
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
    if adapter.LOGIN_MODE != "oauth":
        raise HTTPException(
            status_code=400,
            detail=f"{connector_id} uses credentials, not an authorization flow",
        )
    missing = [f["name"] for f in adapter.FIELDS if not secret_store.has_secret(f["name"])]
    if missing:
        raise HTTPException(status_code=422, detail="Save the app credentials first")

    now = time.time()
    for key, expires in list(_pending_states.items()):
        if expires < now:
            _pending_states.pop(key, None)

    state = pysecrets.token_urlsafe(24)
    base_url = f"http://{settings.host}:{settings.port}"
    url = adapter.authorize_url(state, base_url=base_url)
    _pending_states[(connector_id, state)] = now + _STATE_TTL_SECONDS
    return ConnectorAuthorizeResponse(authorize_url=url, state=state)


def _pop_valid_state(connector_id: str, state: str) -> None:
    """Pop and validate a pending OAuth state, or raise the standard 400.

    Keyed by ``(connector_id, state)``: a state minted for one OAuth
    connector cannot be looked up successfully against another's callback —
    the tuple key rejects the mismatch by construction, no separate
    "which connector minted this" check needed.
    """
    expires = _pending_states.pop((connector_id, state), None)
    if not state or expires is None or expires < time.time():
        raise HTTPException(status_code=400, detail="Invalid or expired sign-in state")


@router.get("/{connector_id}/callback", response_class=HTMLResponse)
async def connector_callback(
    connector_id: str,
    code: str = Query(""),
    state: str = Query(""),
    settings: Settings = Depends(get_settings),
):
    """The one OAuth redirect target every OAuth adapter shares (Task 15 §3
    — replaces the previous ``/pinterest/callback`` + ``/x/callback`` pair).

    No bearer token here (the browser cannot send one), so it is gated by
    the single-use ``state`` nonce minted by ``authorize()`` above: an
    unknown, expired, or cross-connector-replayed state exchanges nothing.
    """
    adapter = _adapter(connector_id)
    if adapter.LOGIN_MODE != "oauth":
        raise HTTPException(
            status_code=400,
            detail=f"{connector_id} uses credentials, not an authorization flow",
        )
    _pop_valid_state(connector_id, state)
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code returned")

    base_url = f"http://{settings.host}:{settings.port}"
    try:
        await adapter.exchange_code(code, state=state, base_url=base_url)
    except base.ConnectorError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        # Never echo the response body: a token error can carry app-secret/client context.
        logger.warning(f"{connector_id} code exchange failed: {type(exc).__name__}")
        raise HTTPException(status_code=502, detail=f"Could not complete {adapter.LABEL} sign-in")

    # Fix round 1, M2: the token landed in secrets.env, outside memory_path —
    # bump sync_state.json so "sources" (and the SSE version vector) reflects
    # the freshly-connected account instead of staying stale forever.
    sync_state.record_credentials_changed(settings.memory_path, connector_id)

    # Devin round-1, finding 6: escape any interpolated value before it lands
    # in raw HTML — `adapter.LABEL` is our own hardcoded constant today
    # ("Pinterest", "Reddit", "X (Twitter)"), so the severity is theoretical,
    # but a future adapter (or a LABEL sourced from config someday) must not
    # be able to inject markup into a page served with no bearer-token gate.
    safe_label = html.escape(adapter.LABEL)
    return HTMLResponse(
        f"<html><body style='font:14px -apple-system;padding:40px'>"
        f"<h2>{safe_label} connected</h2>"
        f"<p>You can close this tab and go back to Cicada.</p>"
        f"</body></html>"
    )


@router.post("/{connector_id}/sync", response_model=ConnectorSyncResult)
async def sync_now(connector_id: str, settings: Settings = Depends(get_settings)):
    """Run one poll immediately, user-initiated — NOT a mirror of the nightly
    Sleep-tail poll (final-review H2: that claim was false). ``allow_fetch=True``
    always bypasses ``CICADA_ALLOW_CONNECTOR_FETCH`` — that gate exists only to
    let an UNATTENDED background poll be turned off; a user who just pressed
    "sync now" always gets the real network call, gate or no gate.
    """
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
