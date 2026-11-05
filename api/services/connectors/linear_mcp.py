"""Connect Linear by signing in, never by pasting a token (ROR-115; owner 2026-11-05: no source ever asks for a token).

**Linear's hosted MCP server.** ``https://mcp.linear.app`` publishes ``/.well-known/oauth-authorization-server``:
OAuth 2.1 with PKCE (``S256``), dynamic client registration (``registration_endpoint``) and public clients
(``token_endpoint_auth_methods_supported`` has ``none``), a ``read`` scope, and a **read-only endpoint**,
``/mcp/readonly`` (its protected-resource document lists ``scopes_supported: ["read"]``). Connect registers a public
client for this backend's callback, asks for ``scope=read`` on that resource, the person approves on Linear in their own
browser, and Linear redirects to ``/sources/connectors/linear-api/callback`` (the nonce-gated route every sign-in shares).

**Read-only three times over.** The grant is scope ``read``; the only URL ever posted to is ``/mcp/readonly``; and
:class:`Session` calls only tools in :data:`ALLOWED_TOOLS` (``whoami``, ``list_issues``, ``list_comments``) and speaks
only ``initialize``, ``notifications/initialized`` and ``tools/call``: any other tool is refused before a byte is sent
(:class:`WriteToolRefused`, a test), so no write tool can be called even if the endpoint offered one.

**Tokens.** Access and refresh tokens, the registered client id and the expiry live in ``secrets.env`` (0600) under
:data:`SECRET_NAMES`. Disconnect revokes at Linear (RFC 7009, best effort) then forgets everything. No field accepts a
pasted token (``FIELDS`` is empty).

What is read, and whose words it is, is in ``linear.py``; this module is the sign-in and the read-only session.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets as pysecrets
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

from loguru import logger

from api.services.connections import secrets
from api.services.connectors import base, tier2

ORIGIN = "https://mcp.linear.app"
MCP_URL = ORIGIN + "/mcp/readonly"
METADATA_URL = ORIGIN + "/.well-known/oauth-authorization-server"
REVOKE_FALLBACK = ORIGIN + "/token"
HOST = "mcp.linear.app"
CALLBACK_PATH = "/sources/connectors/linear-api/callback"
CLIENT_NAME = "Cicada"
PROTOCOL_VERSION = "2025-06-18"

SCOPE = "read"
#: Every tool this module may ever call: reads only. The hosted server's save_* / create_* / delete_* tools are not here.
ALLOWED_TOOLS = frozenset({"whoami", "list_issues", "list_comments"})
_RPC_METHODS = frozenset({"initialize", "notifications/initialized", "tools/call"})

TOKEN_ENV = "CICADA_LINEAR_TOKEN"
REFRESH_ENV = "CICADA_LINEAR_REFRESH_TOKEN"
EXPIRES_ENV = "CICADA_LINEAR_TOKEN_EXPIRES"
CLIENT_ENV = "CICADA_LINEAR_CLIENT_ID"
HOW_ENV = "CICADA_LINEAR_AUTH"
HOW_APP, HOW_RECONNECT = "app", "reconnect"
SECRET_NAMES = (TOKEN_ENV, REFRESH_ENV, EXPIRES_ENV, CLIENT_ENV, HOW_ENV)

REFRESH_MARGIN_S = 300
STATE_TTL_S = 600
MAX_CALLS_PER_SYNC = 150

NOT_REACHED = "Linear did not answer the sign-in; try again in a moment."
BAD_ENDPOINT = "Linear's sign-in answered with an address Cicada does not trust, so nothing was started."
SIGNED_OUT = "Linear signed Cicada out. Connect Linear again."


class RequestLimit(base.ConnectorError):
    """The sync's own budget, not a fault in what it was reading: stop and carry on next time, nothing is unreadable."""


class WriteToolRefused(base.ConnectorError):
    """A tool outside :data:`ALLOWED_TOOLS` was asked for; nothing was sent."""


# --- the sign-in ---------------------------------------------------------------------------------------------------

#: ``state -> {"verifier", "client_id", "redirect", "token_url"}``: one sign-in at a time per state, in this process.
_pending: dict[str, dict] = {}


async def oauth_transport(method: str, url: str, *, data: dict | None = None, json: dict | None = None) -> tier2.Response:
    """The only live path of the sign-in: Linear's own host, no redirect, no cookie, 15 s (tests replace this)."""
    import httpx

    if urlparse(url).hostname != HOST:
        raise base.ConnectorError(BAD_ENDPOINT)
    async with httpx.AsyncClient(follow_redirects=False, timeout=tier2.TIMEOUT_SECONDS) as client:
        resp = await client.request(method, url, data=data, json=json, headers={"Accept": "application/json"})
    try:
        body = resp.json() if resp.content else None
    except ValueError:
        body = None
    return tier2.Response(resp.status_code, body, {k.lower(): v for k, v in resp.headers.items()})


TRANSPORT = oauth_transport


async def _send(method: str, url: str, *, data: dict | None = None, json: dict | None = None) -> tier2.Response:
    out = TRANSPORT(method, url, data=data, json=json)
    if hasattr(out, "__await__"):
        out = await out
    return out


def _trusted(url) -> str:
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or parsed.hostname != HOST:
        raise base.ConnectorError(BAD_ENDPOINT)
    return str(url)


async def _discover() -> dict:
    resp = await _send("GET", METADATA_URL)
    meta = resp.body if resp.status == 200 and isinstance(resp.body, dict) else None
    if not meta or "S256" not in (meta.get("code_challenge_methods_supported") or []):
        raise base.ConnectorError(NOT_REACHED)
    return {k: _trusted(meta[k]) for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint")
            if meta.get(k)} | ({"revocation_endpoint": _trusted(meta["revocation_endpoint"])}
                               if meta.get("revocation_endpoint") else {})


async def _register(endpoint: str, redirect: str) -> str:
    """Dynamic client registration (RFC 7591): a public client, no secret, for this backend's own callback."""
    resp = await _send("POST", endpoint, json={
        "client_name": CLIENT_NAME, "redirect_uris": [redirect], "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"], "token_endpoint_auth_method": "none"})
    client_id = (resp.body or {}).get("client_id") if isinstance(resp.body, dict) else None
    if resp.status >= 400 or not isinstance(client_id, str) or not client_id.strip():
        raise base.ConnectorError(NOT_REACHED)
    return client_id.strip()


def app_available() -> bool:
    return True


async def authorize_url(state: str, *, base_url: str = "http://127.0.0.1:8000") -> str:
    """Linear's consent page for a client registered for this backend's callback (PKCE S256)."""
    redirect = base_url.rstrip("/") + CALLBACK_PATH
    meta = await _discover()
    for key in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
        if key not in meta:
            raise base.ConnectorError(NOT_REACHED)
    client_id = await _register(meta["registration_endpoint"], redirect)
    now = time.time()
    for key in [k for k, v in _pending.items() if v["expires"] < now]:
        _pending.pop(key, None)
    verifier = pysecrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    _pending[state] = {"verifier": verifier, "client_id": client_id, "redirect": redirect,
                       "token_url": meta["token_endpoint"], "expires": now + STATE_TTL_S}
    return meta["authorization_endpoint"] + "?" + urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256", "scope": SCOPE,
        "resource": MCP_URL, "prompt": "consent"})


def _save_grant(payload: dict, client_id: str) -> None:
    token = (payload or {}).get("access_token")
    if not isinstance(token, str) or not token.strip() or (payload or {}).get("error"):
        raise base.ConnectorError(NOT_REACHED)
    try:
        lifetime = max(60, int(payload.get("expires_in") or 3600))
    except (TypeError, ValueError):
        lifetime = 3600
    secrets.set_secret(TOKEN_ENV, token.strip())
    if isinstance(payload.get("refresh_token"), str) and payload["refresh_token"].strip():
        secrets.set_secret(REFRESH_ENV, payload["refresh_token"].strip())
    secrets.set_secret(EXPIRES_ENV, str(int(time.time()) + lifetime))
    secrets.set_secret(CLIENT_ENV, client_id)
    secrets.set_secret(HOW_ENV, HOW_APP)


async def exchange_code(code: str, *, state: str = "", http_fn=None, base_url: str = "") -> None:
    pending = _pending.pop(state, None)
    if pending is None or pending["expires"] < time.time():
        raise base.ConnectorError("The Linear sign-in expired. Start again.")
    resp = await _send("POST", pending["token_url"], data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": pending["redirect"],
        "client_id": pending["client_id"], "code_verifier": pending["verifier"]})
    if resp.status >= 400 or not isinstance(resp.body, dict):
        raise base.ConnectorError(NOT_REACHED)
    _save_grant(resp.body, pending["client_id"])


def how() -> str | None:
    """``app`` (signed in), ``reconnect`` (the sign-in lapsed), ``token`` (a token pasted before this existed), or None."""
    values = secrets.load_secrets()
    signed = (values.get(HOW_ENV) or "").strip()
    if signed == HOW_RECONNECT:
        return HOW_RECONNECT
    if signed == HOW_APP and (values.get(TOKEN_ENV) or "").strip():
        return HOW_APP
    return "token" if (values.get(TOKEN_ENV) or "").strip() else None


def is_app_token() -> bool:
    return how() == HOW_APP


def needs_reconnect() -> bool:
    return how() == HOW_RECONNECT


async def prepare() -> None:
    """Before a sync: renew an access token that is about to lapse. A refusal marks the sign-in lapsed."""
    values = secrets.load_secrets()
    if (values.get(HOW_ENV) or "").strip() != HOW_APP:
        return
    try:
        due = float(values.get(EXPIRES_ENV) or 0) - time.time() < REFRESH_MARGIN_S
    except ValueError:
        due = True
    if not due:
        return
    refresh, client_id = (values.get(REFRESH_ENV) or "").strip(), (values.get(CLIENT_ENV) or "").strip()
    if not refresh or not client_id:
        return      # no refresh grant: the token runs until Linear refuses it
    try:
        token_url = (await _discover())["token_endpoint"]
        resp = await _send("POST", token_url, data={"grant_type": "refresh_token", "refresh_token": refresh,
                                                    "client_id": client_id})
    except Exception as exc:  # noqa: BLE001 — a network miss keeps the token; the sync says what failed
        logger.info(f"linear: token renewal not reached ({type(exc).__name__})")
        return
    if resp.status in (400, 401) and isinstance(resp.body, dict) and resp.body.get("error") == "invalid_grant":
        secrets.set_secret(HOW_ENV, HOW_RECONNECT)
        raise tier2.Refused(SIGNED_OUT, kind="sign-in")
    if resp.status < 400 and isinstance(resp.body, dict):
        _save_grant({**resp.body, "refresh_token": resp.body.get("refresh_token") or refresh}, client_id)


async def revoke() -> None:
    """Disconnect's first half: end the grant at Linear (RFC 7009). Never raises; the local forget runs either way."""
    values = secrets.load_secrets()
    token = (values.get(REFRESH_ENV) or values.get(TOKEN_ENV) or "").strip()
    client_id = (values.get(CLIENT_ENV) or "").strip()
    if (values.get(HOW_ENV) or "").strip() not in (HOW_APP, HOW_RECONNECT) or not token or not client_id:
        return
    try:
        await _send("POST", REVOKE_FALLBACK, data={"token": token, "client_id": client_id})
    except Exception as exc:  # noqa: BLE001
        logger.info(f"linear: revoking at Linear failed ({type(exc).__name__}); forgotten here anyway")


# --- the read-only MCP session ---------------------------------------------------------------------------------------


class Session:
    """One sync's MCP conversation: initialize once, then ``tools/call`` on the allow-list only."""

    def __init__(self, client: tier2.Client):
        self.client = client
        self._id: str | None = None
        self._n = 0
        self.calls = 0
        self.started = False

    async def _rpc(self, method: str, params: dict | None = None, *, notify: bool = False):
        if method not in _RPC_METHODS:
            raise WriteToolRefused("an MCP method outside the read-only list was refused")
        body: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self._n += 1
            body["id"] = self._n
        headers = {"MCP-Protocol-Version": PROTOCOL_VERSION}
        if self._id:
            headers["Mcp-Session-Id"] = self._id
        out = await self.client.request("POST", MCP_URL, json=body, headers=headers)
        self._id = self._id or self.client.last_headers.get("mcp-session-id")
        return out

    async def start(self) -> None:
        if self.started:
            return
        await self._rpc("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                       "clientInfo": {"name": CLIENT_NAME, "version": "1"}})
        await self._rpc("notifications/initialized", notify=True)
        self.started = True

    async def call(self, name: str, arguments: dict) -> dict:
        if name not in ALLOWED_TOOLS:
            raise WriteToolRefused(f"Linear tool {name!r} is not on the read-only list")
        if self.calls >= MAX_CALLS_PER_SYNC:
            raise RequestLimit("Linear: this sync reached its request limit; the next one carries on")
        await self.start()
        self.calls += 1
        rpc = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        return _unwrap(rpc)


def _unwrap(rpc) -> dict:
    if not isinstance(rpc, dict):
        return {}
    if rpc.get("error"):
        raise base.ConnectorError(f"Linear answered an error ({(rpc['error'] or {}).get('code')})")
    result = rpc.get("result") or {}
    if result.get("isError"):
        raise base.ConnectorError("Linear could not run that read")
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    text = "".join(str(c.get("text") or "") for c in (result.get("content") or [])
                   if isinstance(c, dict) and c.get("type") == "text")
    try:
        data = json.loads(text)
    except ValueError:
        return {"text": text}
    return data if isinstance(data, dict) else {"results": data}
