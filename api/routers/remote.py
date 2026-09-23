"""The app's side of the remote connector (G135 R-R7, R-R20, R-R31..R-R33) —
loopback only, behind the existing bearer like every other route.

`GET /remote/status` detects, never changes, a tunnel, and self-probes the
public URL only when asked (`?probe=true`, 3 s). `PUT /remote/settings` starts
or stops the listener live. A connector's token appears in exactly one
response: the create or the rotate that minted it. A listing never carries a
token or a hash. Not a sync domain (R-R33): the Settings window polls, so no
ETag or `VersionVector` changes ride with this router.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from api.models.schemas import (RemoteConnectorCreatedOut, RemoteConnectorIn, RemoteConnectorOut,
                                RemoteSettingsIn, RemoteStatusOut)
from api.remote import catalog, reach, store
from api.remote.listener import LISTENER
from api.services import telemetry

router = APIRouter(prefix="/remote")


def _out(connector: catalog.Connector) -> RemoteConnectorOut:
    return RemoteConnectorOut(
        id=connector.id, label=connector.label, app=connector.app, scopes=sorted(connector.scopes),
        created_at=connector.created_at, expires_at=connector.expires_at, revoked_at=connector.revoked_at,
        last_used_at=connector.last_used_at, last_client=connector.last_client, state=connector.state(),
    )


def _auth_event(connector: catalog.Connector, event: str) -> None:
    telemetry.record(telemetry.UsageEvent(
        kind="connector_auth", stage="remote", connection=None, engine=None, model=None, bank=None,
        billing="free", invocations=0, refs={"connector_id": connector.id, "app": connector.app, "event": event},
    ))


async def _reach() -> tuple[reach.Reach, str | None]:
    found = await run_in_threadpool(reach.detect, store.remote_port())
    return found, (store.load_settings().public_base_url or found.funnel_url)


NO_ADDRESS = "no public address yet — set up a way to reach this Mac first"


async def _base_or_409() -> str:
    """The public base a token is about to be shown against, or a 409 BEFORE
    anything is minted (G135 final review). With no base — the tunnel down, or
    the 2 s tailscale detection timing out — create/rotate used to mint anyway
    and return a null `link`/`mcpUrl`: a link app's shown-once sheet then had
    nothing to show, and a rotate had already killed the old secret."""
    _, base = await _reach()
    if not base:
        raise HTTPException(409, NO_ADDRESS)
    return base


def _created(connector: catalog.Connector, token: str, base: str | None) -> RemoteConnectorCreatedOut:
    return RemoteConnectorCreatedOut(
        connector=_out(connector), token=token,
        link=f"{base}/c/{token}/mcp" if base else None, mcp_url=f"{base}/mcp" if base else None,
    )


@router.get("/status", response_model=RemoteStatusOut)
async def get_status(probe: bool = False) -> RemoteStatusOut:
    settings = store.load_settings()
    port = store.remote_port()
    found, effective = await _reach()
    reachable = await run_in_threadpool(reach.probe, effective) if (probe and effective) else None
    return RemoteStatusOut(
        enabled=settings.enabled, port=port, listener_up=LISTENER.up, listener_error=LISTENER.error,
        public_base_url=settings.public_base_url, detected_url=found.funnel_url, effective_url=effective,
        tailscale=found.tailscale, ngrok_installed=found.ngrok, reachable=reachable,
        funnel_command=f"tailscale funnel --bg {port}", ngrok_command=f"ngrok http {port} --inspect=false",
    )


@router.put("/settings", response_model=RemoteStatusOut)
async def put_settings(req: RemoteSettingsIn) -> RemoteStatusOut:
    current = store.load_settings()
    enabled, url = current.enabled, current.public_base_url
    if "public_base_url" in req.model_fields_set:
        try:
            url = store.normalize_public_url(req.public_base_url)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if "enabled" in req.model_fields_set and req.enabled is not None:
        enabled = bool(req.enabled)
    store.save_settings(store.RemoteSettings(enabled=enabled, public_base_url=url))
    if enabled and not LISTENER.up:
        await LISTENER.start()
    elif not enabled:
        await LISTENER.stop()
    return await get_status(probe=False)


@router.get("/connectors", response_model=list[RemoteConnectorOut])
def list_connectors() -> list[RemoteConnectorOut]:
    return [_out(c) for c in store.ConnectorStore().list()]


@router.post("/connectors", response_model=RemoteConnectorCreatedOut)
async def create_connector(req: RemoteConnectorIn) -> RemoteConnectorCreatedOut:
    base = await _base_or_409()
    try:
        connector, token = store.ConnectorStore().create(
            app=req.app, label=req.label, scopes=req.scopes, expires_in_days=req.expires_in_days)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _auth_event(connector, "created")
    return _created(connector, token, base)


@router.post("/connectors/{connector_id}/rotate", response_model=RemoteConnectorCreatedOut)
async def rotate_connector(connector_id: str) -> RemoteConnectorCreatedOut:
    db = store.ConnectorStore()
    existing = db.get(connector_id)
    if existing is None:
        raise HTTPException(404, "no such connector")
    if existing.state() != "active":
        raise HTTPException(409, f"this connector is {existing.state()} — make a new one instead")
    base = await _base_or_409()  # the old secret keeps working until a new one can be shown
    try:
        connector, token = db.rotate(connector_id)
    except KeyError as exc:
        raise HTTPException(404, "no such connector") from exc
    except ValueError as exc:
        raise HTTPException(409, f"this connector is {exc} — make a new one instead") from exc
    _auth_event(connector, "rotated")
    return _created(connector, token, base)


@router.delete("/connectors/{connector_id}", response_model=RemoteConnectorOut)
def revoke_connector(connector_id: str) -> RemoteConnectorOut:
    try:
        connector = store.ConnectorStore().revoke(connector_id)
    except KeyError as exc:
        raise HTTPException(404, "no such connector") from exc
    _auth_event(connector, "revoked")
    return _out(connector)
