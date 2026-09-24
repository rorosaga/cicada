"""Provider connections (G50): probe, connect, disconnect, keys, prefs, and
OpenRouter's browser sign-in callback (R-AG10)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from loguru import logger
from pydantic import BaseModel

from api.config import Settings, get_settings
from api.models.schemas import CamelModel, ConnectionsResponse, ConnectionStatus, LoginSession
from api.services import engine_select
from api.services.connections import byok, codex_cli, openrouter
from api.services.connections.registry import VALID_TIERS, Registry, get_registry

router = APIRouter(prefix="/connections")


class KeyBody(BaseModel):
    key: str


class PrefsBody(CamelModel):
    # CamelModel so `useForSleep` on the wire (what the app sends) binds to
    # `use_for_sleep` here — `populate_by_name=True` still accepts the
    # snake_case spelling too, so existing `tier`/`enabled` callers (both
    # single-word, alias-invariant) are unaffected.
    tier: str | None = None
    enabled: bool | None = None
    use_for_sleep: bool | None = None


def _registry(settings: Settings = Depends(get_settings)) -> Registry:
    return get_registry(settings)


def _adapter(reg: Registry, connection_id: str):
    try:
        return reg.get(connection_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown connection '{connection_id}'")


@router.get("", response_model=ConnectionsResponse)
async def list_connections(fresh: bool = False, reg: Registry = Depends(_registry)):
    return ConnectionsResponse(connections=await reg.statuses(fresh=fresh))


@router.get("/{connection_id}", response_model=ConnectionStatus)
async def get_connection(connection_id: str, fresh: bool = False, reg: Registry = Depends(_registry)):
    _adapter(reg, connection_id)
    return await reg.status_with_powers(connection_id, fresh=fresh)


@router.post("/{connection_id}/login", response_model=LoginSession)
async def login(connection_id: str, reg: Registry = Depends(_registry),
                settings: Settings = Depends(get_settings)):
    adapter = _adapter(reg, connection_id)
    reg.invalidate()
    if isinstance(adapter, openrouter.OpenRouterAdapter):
        # R-AG10: the consent page sends the browser back to THIS backend, so the
        # callback URL is built from the address it actually listens on.
        return await adapter.begin_login(base_url=openrouter.callback_base(settings.host, settings.port))
    return await adapter.begin_login()


@router.get("/{connection_id}/login/{session_id}", response_model=LoginSession)
async def login_state(connection_id: str, session_id: str, reg: Registry = Depends(_registry)):
    _adapter(reg, connection_id)
    sess = codex_cli.login_sessions.get(session_id)
    if sess is None or sess.connection_id != connection_id:
        raise HTTPException(status_code=404, detail="unknown login session")
    if sess.state == "done":
        reg.invalidate()
    return sess


@router.get("/{connection_id}/callback/{nonce}", response_class=HTMLResponse)
async def oauth_callback(connection_id: str, nonce: str, code: str = Query(""),
                         reg: Registry = Depends(_registry)) -> HTMLResponse:
    """R-AG10: the browser lands here with no bearer token; the single-use nonce
    in the path is the gate (``auth._is_oauth_callback_path``)."""
    if connection_id not in openrouter.OAUTH_CONNECTION_IDS:
        raise HTTPException(status_code=404, detail=f"unknown sign-in for '{connection_id}'")
    try:
        await openrouter.complete(nonce, code)
    except openrouter.InvalidState:
        raise HTTPException(status_code=400, detail="This sign-in link is invalid or has expired. Start again from Cicada.")
    except openrouter.ExchangeError:
        logger.warning("OpenRouter sign-in: the key exchange failed")
        raise HTTPException(status_code=502, detail="Could not complete OpenRouter sign-in")
    reg.invalidate()
    return HTMLResponse("<html><body style='font:14px -apple-system;padding:40px'><h2>OpenRouter connected</h2>"
                        "<p>You can close this tab and go back to Cicada.</p></body></html>")


@router.post("/{connection_id}/logout", response_model=ConnectionStatus)
async def logout(connection_id: str, reg: Registry = Depends(_registry)):
    adapter = _adapter(reg, connection_id)
    await adapter.logout()
    reg.invalidate()
    return await reg.status_with_powers(connection_id, fresh=True)


@router.put("/{connection_id}/key", response_model=ConnectionStatus)
async def set_key(connection_id: str, body: KeyBody, reg: Registry = Depends(_registry)):
    adapter = _adapter(reg, connection_id)
    if not isinstance(adapter, byok.ByokAdapter):
        raise HTTPException(status_code=400, detail="only API-key connections accept a key")
    try:
        adapter.set_key(body.key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    reg.invalidate()
    return await reg.status_with_powers(connection_id, fresh=True)


@router.delete("/{connection_id}/key", response_model=ConnectionStatus)
async def delete_key(connection_id: str, reg: Registry = Depends(_registry)):
    adapter = _adapter(reg, connection_id)
    if not isinstance(adapter, byok.ByokAdapter):
        raise HTTPException(status_code=400, detail="only API-key connections hold a key")
    adapter.remove_key()
    reg.invalidate()
    return await reg.status_with_powers(connection_id, fresh=True)


@router.put("/{connection_id}/prefs", response_model=ConnectionStatus)
async def set_prefs(connection_id: str, body: PrefsBody, reg: Registry = Depends(_registry)):
    _adapter(reg, connection_id)
    if body.tier is not None and body.tier not in VALID_TIERS:
        raise HTTPException(status_code=422, detail=f"tier must be one of {VALID_TIERS}")
    if "tier" in body.model_fields_set:
        reg.set_pref(connection_id, "tier", body.tier)
    if body.enabled is not None:
        reg.set_pref(connection_id, "enabled", body.enabled)
    if body.use_for_sleep is not None:
        # Exactly one connection can be the Sleep engine, and only the Claude
        # plan implements the rung — accepting it elsewhere would store a
        # preference nothing reads.
        if connection_id != engine_select.CLAUDE_CONNECTION_ID:
            raise HTTPException(
                status_code=400,
                detail="only the Claude plan can be used as the Sleep engine",
            )
        reg.set_pref(connection_id, engine_select.USE_FOR_SLEEP_PREF,
                     True if body.use_for_sleep else None)
    return await reg.status_with_powers(connection_id, fresh=True)
