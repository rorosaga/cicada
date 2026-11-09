"""Connect Notion by signing in, never by pasting a token (owner 2026-11-05: "any one that you ask for a token … find a
way to sync it properly, either direct integration …").

**Why Notion's hosted MCP server.** ``https://mcp.notion.com/mcp`` speaks OAuth 2.0 with PKCE and *dynamic client
registration* (Notion's guide "Build an MCP client for Notion"; its ``/.well-known/oauth-authorization-server`` lists
``registration_endpoint``, ``code_challenge_methods_supported: [S256]`` and ``token_endpoint_auth_methods_supported``
with ``none``). So there is no secret to ship and nothing for the person to set up: Connect registers a public client
for this backend's own callback, the person approves on Notion in their own browser, and Notion redirects to
``/sources/connectors/notion-api/callback`` (the nonce-gated route Reddit and Pinterest share).

**Read-only is ours.** The grant has one scope (``default``) and the hosted server also offers write tools, so the
guarantee is in code: :class:`Session` calls only tools in :data:`ALLOWED_TOOLS` (search, fetch and the sidebar
lists, all reads) and speaks only ``initialize``, ``notifications/initialized`` and ``tools/call``; any other tool is
refused before a byte is sent (:class:`WriteToolRefused`, a test).

**Differences from the REST path** (``notion.py``), said in the Sources row and ``network.md``: the grant acts as the
person, so it sees every page they can open, not only what they shared with a connection; search has no cursor, so pages
come from the sidebar lists, one search for the pages the person created, and the links inside each fetched page;
a fetched page is the server's Markdown with its properties as JSON, which :func:`notion.page_text` turns into readable
text (no ``<p />``, no header lines); a page unshared or deleted is not detected (kept as it was).

**Choosing what is read** (``scope.py``). A new sign-in reads nothing until the person picks Everything or specific pages
and databases. A chosen page brings the sub-pages printed inside it (its child blocks, never a page it merely mentions);
a chosen database brings its rows. A database is not an episode: each row is one, with the database's title and its
properties, through the same ``drafts_for`` as a page (so a row is classed exactly as a page is). Rows come from the
server's rows query (the first :data:`ROWS_PER_DATABASE`, it has no cursor) and from the child blocks the database prints.

**Tokens.** Access and refresh tokens, the registered client id and the expiry live in ``secrets.env`` (0600) under
:data:`SECRET_NAMES`; the access token takes the old ``CICADA_NOTION_TOKEN`` slot, so a pasted token keeps working
until it is disconnected. Disconnect revokes at Notion (RFC 7009, best effort) then forgets everything.
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
from api.services.connectors import base, scope, tier2

ORIGIN = "https://mcp.notion.com"
MCP_URL = ORIGIN + "/mcp"
METADATA_URL = ORIGIN + "/.well-known/oauth-authorization-server"
REVOKE_FALLBACK = ORIGIN + "/token"
HOST = "mcp.notion.com"
CHANNEL_ID = "notion-api"
CALLBACK_PATH = "/sources/connectors/notion-api/callback"
CLIENT_NAME = "Cicada"
PROTOCOL_VERSION = "2025-06-18"

#: Every tool this module may ever call: reads only. The hosted server's create/update/move/delete tools are not here.
ALLOWED_TOOLS = frozenset({"notion-search", "notion-fetch", "notion-list-private-pages", "notion-list-shared-pages",
                           "notion-query-data-sources"})
_RPC_METHODS = frozenset({"initialize", "notifications/initialized", "tools/call"})

TOKEN_ENV = "CICADA_NOTION_TOKEN"
REFRESH_ENV = "CICADA_NOTION_REFRESH_TOKEN"
EXPIRES_ENV = "CICADA_NOTION_TOKEN_EXPIRES"
CLIENT_ENV = "CICADA_NOTION_CLIENT_ID"
HOW_ENV = "CICADA_NOTION_AUTH"
HOW_APP, HOW_RECONNECT = "app", "reconnect"
SECRET_NAMES = (TOKEN_ENV, REFRESH_ENV, EXPIRES_ENV, CLIENT_ENV, HOW_ENV)

REFRESH_MARGIN_S = 300
STATE_TTL_S = 600
MAX_CALLS_PER_SYNC = 220
MAX_FETCH_PER_SYNC = 60
ROWS_PER_DATABASE = 100
#: Bumped when what a stored page looks like changes; a cursor of another format reads every page once more.
FORMAT = 2
MAX_QUEUE = 2000
LIST_LIMIT = 100

NOT_REACHED = "Notion did not answer the sign-in; try again in a moment."
BAD_ENDPOINT = "Notion's sign-in answered with an address Cicada does not trust, so nothing was started."
SIGNED_OUT = "Notion signed Cicada out. Connect Notion again."


class WriteToolRefused(base.ConnectorError):
    """A tool outside :data:`ALLOWED_TOOLS` was asked for; nothing was sent."""


# --- the sign-in ---------------------------------------------------------------------------------------------------

#: ``state -> {"verifier", "client_id", "redirect", "token_url"}``: one sign-in at a time per state, in this process.
_pending: dict[str, dict] = {}


async def oauth_transport(method: str, url: str, *, data: dict | None = None, json: dict | None = None) -> tier2.Response:
    """The only live path of the sign-in: Notion's own host, no redirect, no cookie, 15 s (tests replace this)."""
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
    """Notion's consent page for a client registered for this backend's callback (PKCE S256)."""
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
        "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "consent"})


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
    fresh = not (secrets.load_secrets().get(TOKEN_ENV) or "").strip()
    if pending is None or pending["expires"] < time.time():
        raise base.ConnectorError("The Notion sign-in expired. Start again.")
    resp = await _send("POST", pending["token_url"], data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": pending["redirect"],
        "client_id": pending["client_id"], "code_verifier": pending["verifier"]})
    if resp.status >= 400 or not isinstance(resp.body, dict):
        raise base.ConnectorError(NOT_REACHED)
    _save_grant(resp.body, pending["client_id"])
    if fresh:
        scope.mark_pending(CHANNEL_ID)      # a new connection reads nothing until the person chooses (`scope.py`)


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
        return      # no refresh grant: the token runs until Notion refuses it
    try:
        token_url = (await _discover())["token_endpoint"]
        resp = await _send("POST", token_url, data={"grant_type": "refresh_token", "refresh_token": refresh,
                                                    "client_id": client_id})
    except Exception as exc:  # noqa: BLE001 — a network miss keeps the token; the sync says what failed
        logger.info(f"notion: token renewal not reached ({type(exc).__name__})")
        return
    if resp.status in (400, 401) and isinstance(resp.body, dict) and resp.body.get("error") == "invalid_grant":
        secrets.set_secret(HOW_ENV, HOW_RECONNECT)
        raise tier2.Refused(SIGNED_OUT, kind="sign-in")
    if resp.status < 400 and isinstance(resp.body, dict):
        _save_grant({**resp.body, "refresh_token": resp.body.get("refresh_token") or refresh}, client_id)


async def revoke() -> None:
    """Disconnect's first half: end the grant at Notion (RFC 7009). Never raises; the local forget runs either way."""
    values = secrets.load_secrets()
    token = (values.get(REFRESH_ENV) or values.get(TOKEN_ENV) or "").strip()
    client_id = (values.get(CLIENT_ENV) or "").strip()
    if (values.get(HOW_ENV) or "").strip() not in (HOW_APP, HOW_RECONNECT) or not token or not client_id:
        return
    try:
        await _send("POST", REVOKE_FALLBACK, data={"token": token, "client_id": client_id})
    except Exception as exc:  # noqa: BLE001
        logger.info(f"notion: revoking at Notion failed ({type(exc).__name__}); forgotten here anyway")


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
            raise WriteToolRefused(f"Notion tool {name!r} is not on the read-only list")
        if self.calls >= MAX_CALLS_PER_SYNC:
            raise base.ConnectorError("Notion: this sync reached its request limit; the next one carries on")
        await self.start()
        self.calls += 1
        rpc = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        return _unwrap(rpc)


def _unwrap(rpc) -> dict:
    if not isinstance(rpc, dict):
        return {}
    if rpc.get("error"):
        raise base.ConnectorError(f"Notion answered an error ({(rpc['error'] or {}).get('code')})")
    result = rpc.get("result") or {}
    if result.get("isError"):
        raise base.ConnectorError("Notion could not run that read")
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    text = "".join(str(c.get("text") or "") for c in (result.get("content") or [])
                   if isinstance(c, dict) and c.get("type") == "text")
    try:
        data = json.loads(text)
    except ValueError:
        return {"text": text}
    return data if isinstance(data, dict) else {"results": data}


# --- reading ---------------------------------------------------------------------------------------------------------

_HEX = re.compile(r"[0-9a-f]{32}")
_LINK = re.compile(r"https://(?:www\.)?notion\.(?:so|site)/[^\s\"'<>)\]]+")
_CONTENT = re.compile(r"<content>\s*(.*?)\s*</content>", re.DOTALL)
_PROPS = re.compile(r"<properties>\s*(\{.*?\})\s*</properties>", re.DOTALL)
#: A child block the server prints inside a page: a sub-page or a database (never a mention of some other page).
_CHILD = re.compile(r"<(?:page|database)\b[^>]*?\burl=\"([^\"]+)\"", re.IGNORECASE)
#: A database's data source, however the server spells the tag.
_COLLECTION = re.compile(r"collection://([0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12})", re.IGNORECASE)
_DB_TYPES = frozenset({"database", "data_source", "data-source", "collection"})
DS = "ds:"          # a queue/tree key for a data source (a database's table of rows), never a page


def hex_id(raw) -> str | None:
    found = _HEX.findall(str(raw or "").replace("-", "").lower())
    return found[-1] if found else None


def _entries(data: dict) -> list[dict]:
    for key in ("results", "pages", "items", "entries", "rows"):
        if isinstance(data.get(key), list):
            return [r for r in data[key] if isinstance(r, dict)]
    return []


def _edited(row: dict) -> str:
    for key in ("page_last_edited_at", "last_edited_time", "last_edited", "timestamp", "updated_at"):
        if row.get(key):
            return str(row[key])
    return ""


def _is_database(row: dict) -> bool:
    return str(row.get("type") or row.get("object") or "").lower() in _DB_TYPES


def _page_from(row_id: str, data: dict, listed_edited: str) -> tuple[dict, dict, str]:
    """(the page as the REST shape ``notion.drafts_for`` reads, its Markdown, the fetched text)."""
    from api.services.connectors import notion

    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    text = str(data.get("text") or data.get("markdown") or data.get("content") or "")
    title = str(data.get("title") or meta.get("title") or "").strip()
    body = notion.strip_head((_CONTENT.search(text).group(1) if _CONTENT.search(text) else text).strip(), title).strip()
    lines = []
    if m := _PROPS.search(text):
        try:
            props = json.loads(m.group(1))
        except ValueError:
            props = {}
        for key, value in (props.items() if isinstance(props, dict) else []):
            if key.strip().lower() in ("title", "name") and not title:
                title = str(value or "").strip()
            elif value not in (None, "", []):
                lines.append(f"**{notion._clip(key, 60)}:** {notion._clip(value, notion.PROPERTY_CAP)}")
    edited = _edited(data) or _edited(meta) or listed_edited
    now = datetime.now(timezone.utc).isoformat()
    page = {"id": row_id, "created_time": str(data.get("created_time") or meta.get("created_time") or "") or edited or now,
            "last_edited_time": edited or now,
            "properties": {"title": {"type": "title", "title": [{"plain_text": title or "Untitled"}]}}}
    markdown = "\n".join(lines) + ("\n\n" if lines else "") + body
    return page, {"markdown": markdown, "truncated": bool(data.get("truncated"))}, text


def _title_of(row: dict) -> str:
    for key in ("title", "name"):
        value = row.get(key)
        if isinstance(value, list):
            value = "".join(str((r or {}).get("plain_text") or "") for r in value if isinstance(r, dict))
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:200]
    return "Untitled"


async def containers(client: tier2.Client, query: str = "") -> dict:
    """What the picker lists, right after the sign-in and whenever the sheet is opened: pages and databases the person can
    open, from the sidebar lists, or a search when they type. Reads only. ``{"items": [{id, title, kind}], "more"}``."""
    session = Session(client)
    rows: list[dict] = []
    query = " ".join(str(query or "").split())[:100]
    tools = [("notion-search", {"query": query})] if query else [
        ("notion-list-private-pages", {"limit": LIST_LIMIT}), ("notion-list-shared-pages", {"limit": LIST_LIMIT})]
    for tool, args in tools:
        try:
            rows.extend(_entries(await session.call(tool, args)))
        except (tier2.Refused, WriteToolRefused):
            raise
        except base.ConnectorError:
            continue
    items, seen = [], set()
    for row in rows:
        rid = hex_id(row.get("id") or row.get("url"))
        if not rid or rid in seen:
            continue
        seen.add(rid)
        items.append({"id": rid, "title": _title_of(row), "kind": "database" if _is_database(row) else "page"})
    return {"items": items[:LIST_LIMIT], "more": len(items) > LIST_LIMIT}


def _row_ids(data: dict) -> list[str]:
    """The pages of a data-source query: each row's own id or page address, whichever key the server uses."""
    out: list[str] = []
    for row in _entries(data):
        lowered = {str(k).lower(): v for k, v in row.items()}
        for key in ("url", "id", "page_id", "page_url", "notion_url"):
            if (rid := hex_id(lowered.get(key))) is not None:
                if rid not in out:
                    out.append(rid)
                break
    return out


class _Run:
    """One sync's working state: what is known, what waits, what the cursor will keep."""

    def __init__(self, cursor: dict, sel: dict):
        self.sel = sel
        self.sig = scope.signature(sel)
        fresh_format = cursor.get("fmt") == FORMAT
        self.known: dict = dict(cursor.get("known") or {}) if fresh_format else {}
        self.queue: list[str] = [i for i in (cursor.get("queue") or []) if i not in self.known]
        self.tree: dict = {k: list(v) for k, v in (cursor.get("tree") or {}).items()}
        self.titles: dict = dict(cursor.get("titles") or {})        # a row's / data source's database title
        self.checked: dict = dict(cursor.get("checked") or {})
        self.batch = tier2.Batch()
        self.fetched = 0
        self.unreadable = 0
        self.rows_capped = 0

    @property
    def chosen(self) -> bool:
        return self.sel["mode"] == scope.CHOSEN


async def _read_page(session: Session, run: _Run, rid: str, listed_edited: str, mine: set, kind: str) -> list[str]:
    """Fetch one page or database. A page is staged (a row with its database's title); a database is not an episode, it
    leads to its rows. Returns the keys it leads to: sub-pages, and data sources to query."""
    from api.services.connectors import notion

    data = await session.call("notion-fetch", {"id": rid})
    run.fetched += 1
    page, md, raw = _page_from(rid, data, listed_edited)
    title = page["properties"]["title"]["title"][0]["plain_text"]
    body = _CONTENT.search(raw).group(1) if _CONTENT.search(raw) else raw
    sources = list({m.replace("-", "").lower(): m.lower() for m in _COLLECTION.findall(raw)}.values())   # as spelled
    is_db = kind == "database" or (not _CONTENT.search(raw) and bool(sources))
    kids: list[str] = []
    if run.chosen:
        scan = _CHILD.findall(body)
    else:
        scan = _LINK.findall(raw)
    for link in scan:
        child = hex_id(link)
        if child and child != rid and child not in kids:
            kids.append(child)
            if is_db:
                run.titles.setdefault(child, title)         # a row of this database, by the table's name
    for cid in sources:
        key = DS + cid
        run.titles.setdefault(key, title)
        kids.append(key)
    edited = page["last_edited_time"] if (data.get("page_last_edited_at") or listed_edited) else ""
    if not is_db and not (edited and run.known.get(rid) == edited):
        run.batch.drafts.extend(notion.drafts_for(page, md, db_title=run.titles.get(rid), mine=rid in mine))
        run.batch.replaced.append(notion.SOURCE_PREFIX + rid)
        run.batch.seen += 1
    run.known[rid] = edited
    return kids


async def _read_rows(session: Session, run: _Run, key: str) -> list[str]:
    """A data source's rows (up to :data:`ROWS_PER_DATABASE`; the server's rows mode has no cursor)."""
    cid = key[len(DS):]
    data = await session.call("notion-query-data-sources", {
        "mode": "rows", "data_source_url": f"collection://{cid}", "limit": ROWS_PER_DATABASE})
    ids = _row_ids(data)
    if data.get("has_more") or len(ids) >= ROWS_PER_DATABASE:
        run.rows_capped += 1
    title = run.titles.get(key) or ""
    for rid in ids:
        if title:
            run.titles.setdefault(rid, title)
    return ids


async def fetch(client: tier2.Client, cursor: dict, memory_path: Path) -> tier2.Batch:
    session = Session(client)
    run = _Run(cursor, scope.read(CHANNEL_ID))
    mine: set[str] = set()
    try:
        data = await session.call("notion-search", {"query": "", "filters": {"created_by_user_ids": ["me"]}})
        for row in _entries(data):
            if rid := hex_id(row.get("id") or row.get("url")):
                mine.add(rid)
    except (tier2.Refused, WriteToolRefused):
        raise
    except base.ConnectorError:
        pass        # a plan that does not take the filter: nothing is credited to the person on a guess
    listed: dict[str, str] = {}
    kinds: dict[str, str] = {}
    if run.chosen:
        roots = []
        for item in run.sel["items"]:
            roots.append(item["id"])
            kinds[item["id"]] = item.get("kind") or "page"
        todo = _chosen_order(roots, run)
    else:
        # Roots: the sidebar lists (databases included), then the pages the person created.
        for tool in ("notion-list-private-pages", "notion-list-shared-pages"):
            try:
                data = await session.call(tool, {"limit": LIST_LIMIT})
            except (tier2.Refused, WriteToolRefused):
                raise
            except base.ConnectorError:
                continue
            for row in _entries(data):
                if rid := hex_id(row.get("id") or row.get("url")):
                    listed[rid] = _edited(row)
                    if _is_database(row):
                        kinds[rid] = "database"
        for rid in mine:
            listed.setdefault(rid, "")
        todo = list(run.queue)
        for rid, edited in listed.items():
            if rid in todo or (run.known.get(rid) and edited and run.known[rid] == edited):
                continue
            todo.insert(0, rid)
    seen_keys = set(todo)
    while todo and run.fetched < MAX_FETCH_PER_SYNC:
        key = todo.pop(0)
        try:
            if key.startswith(DS):
                kids = await _read_rows(session, run, key)
                run.fetched += 1
            else:
                kids = await _read_page(session, run, key, listed.get(key, ""), mine, kinds.get(key, "page"))
        except (tier2.Refused, WriteToolRefused):
            raise
        except base.ConnectorError as exc:
            if "request limit" in str(exc):
                todo.insert(0, key)
                break
            run.unreadable += 1
            run.known.setdefault(key, "")
            continue
        run.checked[key] = time.time()
        if run.chosen:
            run.tree[key] = kids
        for kid in kids:
            fresh = (kid.startswith(DS) or kid not in run.known) and kid not in seen_keys and len(todo) < MAX_QUEUE
            if fresh or (run.chosen and kid not in seen_keys and kid not in run.tree):
                seen_keys.add(kid)
                todo.append(kid)
    run.queue = [] if run.chosen else todo
    return _finish(run, todo, bool(mine))


def _chosen_order(roots: list[str], run: _Run) -> list[str]:
    """Everything reachable from the chosen roots, never-read first, then the longest-unchecked: a big tree is read over
    several syncs and re-checked in turn, never starved."""
    order, seen, queue = [], set(), list(roots)
    while queue:
        node = queue.pop(0)
        if node in seen:
            continue
        seen.add(node)
        order.append(node)
        queue.extend(run.tree.get(node, []))
    return sorted(order, key=lambda n: run.checked.get(n, 0.0))


def _finish(run: _Run, todo: list[str], credited: bool) -> tier2.Batch:
    from api.services.connectors import notion

    words = []
    if run.chosen:
        waiting = [n for n in todo if n not in run.checked]
        if waiting:
            words.append(f"Reading what you chose: {len(run.known)} so far; the next sync carries on.")
    elif run.queue:
        words.append(f"Reading your Notion pages: {len(run.known)} so far; the next sync carries on.")
    elif not run.known and not run.batch.seen:
        words.append("Notion listed no pages to read.")
    if run.rows_capped:
        words.append(f"{run.rows_capped} database(s) hold more than {ROWS_PER_DATABASE} rows; the newest "
                     f"{ROWS_PER_DATABASE} are read.")
    if not credited and run.batch.seen:
        words.append(notion.UNKNOWN_AUTHOR_WORDS)
    if run.unreadable:
        words.append(f"{run.unreadable} page(s) could not be read.")
    run.batch.cursor = {"fmt": FORMAT, "sig": run.sig, "known": run.known, "queue": run.queue, "tree": run.tree,
                        "titles": run.titles, "checked": run.checked}
    run.batch.words = " ".join(words) or None
    return run.batch
