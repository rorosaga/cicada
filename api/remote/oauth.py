"""Sign-in for the remote connector (ruling 31, owner 2026-10-19): an OAuth 2.1 authorization server on the G135
listener, so claude.ai (and its phone apps) and ChatGPT can add Cicada as a custom connector.

What it is, end to end:

* **Discovery.** ``/.well-known/oauth-protected-resource[/mcp]`` names this server as the one authorization server;
  ``/.well-known/oauth-authorization-server`` (RFC 8414) lists the endpoints, ``S256`` only, the auth methods and
  ``client_id_metadata_document_supported``. A request to ``/mcp`` without a valid token is a ``401`` whose
  ``WWW-Authenticate`` carries ``resource_metadata`` (what Claude and ChatGPT start from).
* **Registration.** Dynamic Client Registration (RFC 7591, ``POST /register``) or a Client ID Metadata Document
  (``client_id`` is an https URL; the document is fetched through ``net_guard`` under the ToS rail: 4 s,
  ≤ 64 KB, no cookies, no redirects, cached a day). Redirect URIs are matched exactly; only an ``http`` loopback
  redirect (Claude Code's) matches on any port.
* **Consent never happens on the public page.** ``GET /authorize`` validates the client and redirect URI (an error
  there is a page, never a redirect — no open redirect), then shows a short code and waits. The person approves
  the request in the Cicada app on the Mac (``/remote/oauth/requests``, loopback, behind the API token), choosing
  the scopes and the expiry there. There is no password and no approve button on the public surface. The waiting
  page is bound to its browser by a cookie (only that browser can collect the code), and the client's ``state``
  is echoed back untouched, with ``iss`` (RFC 9207) on every response, errors included.
* **Tokens.** An authorization code is single-use, lives 120 s, is bound to the client, the redirect URI, the PKCE
  challenge and the resource; replaying a used code revokes what it issued. Access tokens (``cic_at_``) live an
  hour; refresh tokens (``cic_rt_``) rotate on every use, and a rotated one presented again (past a short grace
  for a client's own concurrent refresh) revokes the whole grant. Every token is stored as its sha256 only,
  compared in constant time, and maps to a connector row — the same hashed, scoped, expiring and revocable row a
  link connector is — so Settings → From anywhere revokes it and the grant can never outlive the connector.
* **Rate limits.** Registration, authorization, token and document fetches each have their own bucket; at most
  :data:`MAX_PENDING` requests wait at once.

Nothing here logs a token, a code, a state or a URL a client sent. Store calls are sqlite on the event loop, the
same single-row millisecond work as ``api/remote/store.py``; the one network call (a metadata document) is async.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import re
import secrets
import sqlite3
import string
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import parse_qsl, unquote, urlencode, urlparse

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from api.remote import catalog, store as remote_store

ACCESS_TTL_S = 3600
CODE_TTL_S = 120
REQUEST_TTL_S = 600
REFRESH_REUSE_GRACE_S = 30
CIMD_TTL_S = 24 * 3600
CIMD_MAX_BYTES = 64 * 1024
CIMD_TIMEOUT_S = 4.0
MAX_PENDING = 5
MAX_CLIENTS = 200
MAX_REDIRECTS = 5
MAX_FORM_BYTES = 16 * 1024
WAIT_REFRESH_S = 3
COOKIE = "cicada_signin"
AUTH_METHODS = ("none", "client_secret_post", "client_secret_basic")
OFFLINE = "offline_access"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})
ACCESS_RE = re.compile(r"^cic_at_([a-z0-9]{8})_([A-Za-z0-9_-]{43})$")
REFRESH_RE = re.compile(r"^cic_rt_([a-z0-9]{8})_([A-Za-z0-9_-]{43})$")
_PKCE_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}(:\d{1,5})?$")
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_ID_ALPHABET = string.ascii_lowercase + string.digits
_NAME_UNSAFE = re.compile(r"[^A-Za-z0-9 ._()/'-]")

PATHS = frozenset({"/.well-known/oauth-authorization-server", "/authorize", "/authorize/wait", "/token",
                   "/register", "/revoke"})
#: Browser navigations: the only OAuth routes a browser reaches, and the only ones an ``Origin`` header may ride.
BROWSER_PATHS = frozenset({"/authorize", "/authorize/wait"})

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS oauth_clients (
        client_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        name TEXT,
        redirect_uris TEXT NOT NULL,
        auth_method TEXT NOT NULL,
        secret_hash TEXT,
        created_at TEXT NOT NULL,
        fetched_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS oauth_requests (
        handle_hash TEXT PRIMARY KEY,
        ref TEXT UNIQUE NOT NULL,
        user_code TEXT NOT NULL,
        client_id TEXT NOT NULL,
        redirect_uri TEXT NOT NULL,
        code_challenge TEXT NOT NULL,
        state TEXT,
        resource TEXT NOT NULL,
        scopes_asked TEXT,
        binding_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        status TEXT NOT NULL,
        connector_id TEXT,
        code_hash TEXT UNIQUE,
        code_expires_at TEXT,
        code_used INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS oauth_tokens (
        token_hash TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        connector_id TEXT NOT NULL,
        client_id TEXT NOT NULL,
        grant_ref TEXT NOT NULL,
        resource TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked_at TEXT,
        rotated INTEGER NOT NULL DEFAULT 0
    )""",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def _at(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _same(stored: str | None, presented: str) -> bool:
    return bool(stored) and hmac.compare_digest(str(stored), _hash(presented))


def pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def clean_name(raw) -> str | None:
    return _NAME_UNSAFE.sub("", str(raw or ""))[:64].strip() or None


def _valid_redirect(uri) -> bool:
    """A redirect URI a client may register: https anywhere, or http on a loopback host (a native app, RFC 8252);
    no fragment, no credentials, bounded."""
    if not isinstance(uri, str) or not uri or len(uri) > 512 or any(c.isspace() for c in uri):
        return False
    parsed = urlparse(uri)
    if parsed.fragment or parsed.username or parsed.password or not parsed.hostname:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and _netloc_host(parsed) in LOOPBACK_HOSTS


def _netloc_host(parsed) -> str:
    host = (parsed.hostname or "").lower()
    return f"[{host}]" if ":" in host else host


def redirect_matches(registered: list[str], presented: str) -> bool:
    """Exact string match (OAuth 2.1), with RFC 8252's one exception: an ``http`` loopback redirect matches on any
    port (Claude Code's callback port changes every session), the rest of it still exact."""
    if not isinstance(presented, str) or not presented:
        return False
    if presented in registered:
        return True
    got = urlparse(presented)
    if got.scheme != "http" or _netloc_host(got) not in LOOPBACK_HOSTS:
        return False
    for uri in registered:
        want = urlparse(uri)
        if (want.scheme == "http" and _netloc_host(want) == _netloc_host(got) and want.path == got.path
                and want.query == got.query and not got.fragment and not got.username and not got.password):
            return True
    return False


def guess_app(client_id: str, redirect_uri: str) -> str:
    """Which catalog app a client is, for the connector's harness label — read from where the code goes, the one
    thing a client cannot fake usefully (a code sent to another app's callback is lost to whoever registered it)."""
    host = (urlparse(redirect_uri).hostname or "").lower()
    if host == "claude.ai":
        return "claude"
    if host in ("chatgpt.com", "chat.openai.com") or host.endswith(".chatgpt.com"):
        return "chatgpt"
    if host in ("localhost", "127.0.0.1", "::1") and (urlparse(client_id).hostname or "").lower() == "claude.ai":
        return "claude-code"
    return "other"


def public_base(request: Request) -> str | None:
    """The https origin this listener is reached at: the person's saved address, else the ``Host`` the tunnel
    forwarded. ``None`` for a Host that is not a plain host[:port]."""
    saved = remote_store.load_settings().public_base_url
    if saved:
        return saved.rstrip("/")
    host = request.headers.get("host", "")
    return f"https://{host.lower()}" if _HOST_RE.match(host) else None


def resources(base: str) -> tuple[str, str]:
    return f"{base}/mcp", base


def _origin_of(resource: str) -> str:
    value = str(resource or "").rstrip("/")
    return value[:-4] if value.endswith("/mcp") else value


class Bucket:
    """A token bucket (in memory; a restart only ever errs toward letting a legitimate app back in)."""

    def __init__(self, per_minute: float, burst: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._rate, self._burst, self._clock = per_minute / 60.0, float(burst), clock
        self._level, self._last = float(burst), clock()

    def take(self) -> bool:
        now = self._clock()
        self._level = min(self._burst, self._level + (now - self._last) * self._rate)
        self._last = now
        if self._level < 1.0:
            return False
        self._level -= 1.0
        return True


@dataclass
class OAuthLimits:
    register: Bucket
    authorize: Bucket
    token: Bucket
    fetch: Bucket

    @classmethod
    def default(cls, clock: Callable[[], float] = time.monotonic) -> "OAuthLimits":
        return cls(register=Bucket(2, 10, clock), authorize=Bucket(10, 20, clock), token=Bucket(60, 60, clock),
                   fetch=Bucket(2, 10, clock))


@dataclass(frozen=True)
class Client:
    client_id: str
    kind: str  # "dcr" | "cimd"
    name: str | None
    redirect_uris: list[str]
    auth_method: str
    secret_hash: str | None = None


@dataclass(frozen=True)
class PendingRequest:
    """One sign-in waiting for the person, as the app shows it — ids, enums, times, the client's self-reported
    name and the host the code would go to. Never the browser handle, the state or a code."""
    ref: str
    user_code: str
    client_name: str | None
    client_kind: str
    client_host: str | None
    redirect_host: str
    loopback: bool
    app: str
    scopes_asked: list[str]
    created_at: str
    expires_at: str


class OAuthError(Exception):
    def __init__(self, error: str, description: str = "", status: int = 400) -> None:
        super().__init__(error)
        self.error, self.description, self.status = error, description, status


Fetcher = Callable[[str], Awaitable[bytes | None]]


async def fetch_metadata_document(url: str) -> bytes | None:
    """A Client ID Metadata Document, under the ToS rail: ``net_guard`` before connecting, 4 s, at most 64 KB, no
    cookies, no redirects followed. ``None`` on anything else."""
    import httpx

    from api.services import net_guard

    if not await net_guard.is_fetchable_url_async(url):
        return None
    try:
        async with httpx.AsyncClient(timeout=CIMD_TIMEOUT_S, follow_redirects=False, cookies=None,
                                     event_hooks={"request": [net_guard.httpx_request_guard]}) as client:
            async with client.stream("GET", url, headers={"Accept": "application/json"}) as resp:
                if resp.status_code != 200:
                    return None
                body = b""
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > CIMD_MAX_BYTES:
                        return None
                return body
    except Exception:  # noqa: BLE001 — an unreachable document is an unknown client, never an error page's trace
        return None


class OAuthServer:
    def __init__(self, path: Path, *, connectors: remote_store.ConnectorStore | None = None,
                 limits: OAuthLimits | None = None, fetcher: Fetcher | None = None,
                 clock: Callable[[], datetime] = _now) -> None:
        self.path = Path(path)
        self.connectors = connectors or remote_store.ConnectorStore(self.path)
        self.limits = limits or OAuthLimits.default()
        self.fetcher = fetcher or fetch_metadata_document
        self.clock = clock
        with self._db() as db:
            for statement in _SCHEMA:
                db.execute(statement)

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── clients ────────────────────────────────────────────────────────────

    def _client_row(self, client_id: str) -> Client | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM oauth_clients WHERE client_id=?", (client_id,)).fetchone()
        if row is None:
            return None
        if row["kind"] == "cimd":
            fetched = _at(row["fetched_at"])
            if fetched is None or (self.clock() - fetched).total_seconds() > CIMD_TTL_S:
                return None
        return Client(client_id=row["client_id"], kind=row["kind"], name=row["name"],
                      redirect_uris=json.loads(row["redirect_uris"]), auth_method=row["auth_method"],
                      secret_hash=row["secret_hash"])

    def get_client(self, client_id: str) -> Client | None:
        """A registered client only — never a fetch (the token and revocation endpoints)."""
        if not client_id or len(client_id) > 512:
            return None
        with self._db() as db:
            row = db.execute("SELECT * FROM oauth_clients WHERE client_id=?", (client_id,)).fetchone()
        if row is None:
            return None
        return Client(client_id=row["client_id"], kind=row["kind"], name=row["name"],
                      redirect_uris=json.loads(row["redirect_uris"]), auth_method=row["auth_method"],
                      secret_hash=row["secret_hash"])

    async def resolve_client(self, client_id: str) -> Client | None:
        """A DCR client by its id, or a CIMD client by its https URL (fetched, checked, cached a day)."""
        if not client_id or len(client_id) > 512:
            return None
        cached = self._client_row(client_id)
        if cached is not None:
            return cached
        parsed = urlparse(client_id)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.path in ("", "/") or parsed.fragment
                or parsed.username or parsed.password):
            return None
        if not self.limits.fetch.take():
            return None
        raw = await self.fetcher(client_id)
        try:
            doc = json.loads(raw or b"null")
        except ValueError:
            return None
        if not isinstance(doc, dict) or doc.get("client_id") != client_id:
            return None
        uris = doc.get("redirect_uris")
        if not isinstance(uris, list) or not uris or len(uris) > MAX_REDIRECTS or not all(map(_valid_redirect, uris)):
            return None
        methods = doc.get("token_endpoint_auth_methods_supported")
        preferred = doc.get("token_endpoint_auth_method")
        offered = {preferred} if isinstance(preferred, str) else set()
        if isinstance(methods, list):
            offered |= {m for m in methods if isinstance(m, str)}
        # A metadata document has no secret to share: only a public client (PKCE) is accepted.
        if offered and "none" not in offered:
            return None
        client = Client(client_id=client_id, kind="cimd", name=clean_name(doc.get("client_name")),
                        redirect_uris=list(uris), auth_method="none")
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO oauth_clients (client_id, kind, name, redirect_uris, auth_method, "
                       "secret_hash, created_at, fetched_at) VALUES (?, 'cimd', ?, ?, 'none', NULL, ?, ?)",
                       (client_id, client.name, json.dumps(client.redirect_uris), _iso(self.clock()),
                        _iso(self.clock())))
        return client

    def register(self, payload) -> dict:
        """RFC 7591. Raises :class:`OAuthError` (``invalid_redirect_uri`` / ``invalid_client_metadata``)."""
        if not isinstance(payload, dict):
            raise OAuthError("invalid_client_metadata", "the body must be a JSON object")
        uris = payload.get("redirect_uris")
        if not isinstance(uris, list) or not uris or len(uris) > MAX_REDIRECTS or not all(map(_valid_redirect, uris)):
            raise OAuthError("invalid_redirect_uri", "redirect_uris must be https (or http on a loopback host)")
        method = payload.get("token_endpoint_auth_method", "client_secret_basic")
        if method not in AUTH_METHODS:
            raise OAuthError("invalid_client_metadata", "token_endpoint_auth_method must be one of "
                             + ", ".join(AUTH_METHODS))
        grants = payload.get("grant_types", ["authorization_code"])
        if not isinstance(grants, list) or not set(grants) <= {"authorization_code", "refresh_token"}:
            raise OAuthError("invalid_client_metadata", "only authorization_code and refresh_token are supported")
        kinds = payload.get("response_types", ["code"])
        if not isinstance(kinds, list) or not set(kinds) <= {"code"}:
            raise OAuthError("invalid_client_metadata", "only the code response type is supported")
        now = self.clock()
        self._prune_clients(now)
        client_id = "cic_client_" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(20))
        secret = secrets.token_urlsafe(32) if method != "none" else None
        name = clean_name(payload.get("client_name"))
        with self._db() as db:
            if db.execute("SELECT COUNT(*) FROM oauth_clients WHERE kind='dcr'").fetchone()[0] >= MAX_CLIENTS:
                raise OAuthError("temporarily_unavailable", "too many registered apps", status=429)
            db.execute("INSERT INTO oauth_clients (client_id, kind, name, redirect_uris, auth_method, secret_hash, "
                       "created_at) VALUES (?, 'dcr', ?, ?, ?, ?, ?)",
                       (client_id, name, json.dumps(uris), method, _hash(secret) if secret else None, _iso(now)))
        out = {"client_id": client_id, "client_id_issued_at": int(now.timestamp()), "redirect_uris": uris,
               "token_endpoint_auth_method": method, "grant_types": grants, "response_types": ["code"]}
        if name:
            out["client_name"] = name
        if secret:
            out["client_secret"] = secret
            out["client_secret_expires_at"] = 0
        return out

    def _prune_clients(self, now: datetime) -> None:
        """A registered client that never got a grant goes after a day — DCR runs on every fresh connection."""
        cutoff = _iso(now - timedelta(days=1))
        with self._db() as db:
            db.execute("DELETE FROM oauth_clients WHERE kind='dcr' AND created_at < ? AND client_id NOT IN "
                       "(SELECT DISTINCT client_id FROM oauth_tokens)", (cutoff,))
            db.execute("DELETE FROM oauth_requests WHERE expires_at < ?", (_iso(now - timedelta(days=1)),))

    # ── authorization requests ────────────────────────────────────────────

    def start_request(self, *, client: Client, redirect_uri: str, code_challenge: str, state: str | None,
                      resource: str, scopes_asked: list[str]) -> tuple[str, str, str]:
        """``(browser handle, binding secret, user code)``. Raises ``OAuthError("slow_down")`` past
        :data:`MAX_PENDING` waiting requests."""
        now = self.clock()
        handle, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        user_code = f"{raw[:4]}-{raw[4:]}"
        ref = "rq_" + secrets.token_hex(8)
        with self._db() as db:
            waiting = db.execute("SELECT COUNT(*) FROM oauth_requests WHERE status='pending' AND expires_at > ?",
                                 (_iso(now),)).fetchone()[0]
            if waiting >= MAX_PENDING:
                raise OAuthError("slow_down", "too many sign-ins are waiting", status=429)
            db.execute(
                "INSERT INTO oauth_requests (handle_hash, ref, user_code, client_id, redirect_uri, code_challenge, "
                "state, resource, scopes_asked, binding_hash, created_at, expires_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                (_hash(handle), ref, user_code, client.client_id, redirect_uri, code_challenge, state, resource,
                 ",".join(scopes_asked), _hash(binding), _iso(now), _iso(now + timedelta(seconds=REQUEST_TTL_S))))
        return handle, binding, user_code

    def _request_by_handle(self, handle: str) -> sqlite3.Row | None:
        with self._db() as db:
            return db.execute("SELECT * FROM oauth_requests WHERE handle_hash=?", (_hash(handle or ""),)).fetchone()

    def pending(self) -> list[PendingRequest]:
        now = _iso(self.clock())
        with self._db() as db:
            rows = db.execute("SELECT r.*, c.name AS client_name, c.kind AS client_kind FROM oauth_requests r "
                              "LEFT JOIN oauth_clients c ON c.client_id = r.client_id "
                              "WHERE r.status='pending' AND r.expires_at > ? ORDER BY r.created_at", (now,)).fetchall()
        out = []
        for row in rows:
            redirect = urlparse(row["redirect_uri"])
            host = _netloc_host(redirect)
            out.append(PendingRequest(
                ref=row["ref"], user_code=row["user_code"], client_name=row["client_name"],
                client_kind=row["client_kind"] or "dcr",
                client_host=(urlparse(row["client_id"]).hostname if row["client_kind"] == "cimd" else None),
                redirect_host=host, loopback=host in LOOPBACK_HOSTS,
                app=guess_app(row["client_id"], row["redirect_uri"]),
                scopes_asked=[s for s in (row["scopes_asked"] or "").split(",") if s],
                created_at=row["created_at"], expires_at=row["expires_at"]))
        return out

    def approve(self, ref: str, *, scopes, expires_in_days: int, label: str | None = None) -> catalog.Connector:
        """The person's yes, from the app: a connector with the scopes and expiry they chose. ``KeyError`` for an
        unknown, decided or expired request; ``ValueError`` for scopes or an expiry the store refuses."""
        now = self.clock()
        with self._db() as db:
            row = db.execute("SELECT * FROM oauth_requests WHERE ref=?", (ref,)).fetchone()
        if row is None or row["status"] != "pending" or (_at(row["expires_at"]) or now) <= now:
            raise KeyError(ref)
        app = guess_app(row["client_id"], row["redirect_uri"])
        client = self.get_client(row["client_id"])
        connector = self.connectors.create_oauth(app=app, label=label or (client.name if client else None),
                                                 scopes=scopes, expires_in_days=expires_in_days, now=now)
        with self._db() as db:
            moved = db.execute("UPDATE oauth_requests SET status='approved', connector_id=? WHERE ref=? "
                               "AND status='pending'", (connector.id, ref)).rowcount
        if moved != 1:
            self.connectors.revoke(connector.id)
            raise KeyError(ref)
        return connector

    def deny(self, ref: str) -> None:
        with self._db() as db:
            moved = db.execute("UPDATE oauth_requests SET status='denied' WHERE ref=? AND status='pending'",
                               (ref,)).rowcount
        if moved != 1:
            raise KeyError(ref)

    def collect(self, handle: str, binding: str | None) -> tuple[str, sqlite3.Row | None, str | None]:
        """What the waiting page does next: ``("unknown"|"expired"|"pending"|"done", row, None)``,
        ``("denied", row, None)`` once, or ``("code", row, code)`` exactly once after the person approved."""
        row = self._request_by_handle(handle)
        if row is None or not binding or not _same(row["binding_hash"], binding):
            return "unknown", None, None
        now = self.clock()
        if row["status"] == "pending":
            if (_at(row["expires_at"]) or now) <= now:
                return "expired", row, None
            return "pending", row, None
        if row["status"] == "denied":
            with self._db() as db:
                moved = db.execute("UPDATE oauth_requests SET status='closed', state=NULL WHERE handle_hash=? "
                                   "AND status='denied'", (row["handle_hash"],)).rowcount
            return ("denied", row, None) if moved == 1 else ("done", row, None)
        if row["status"] == "approved":
            code = secrets.token_urlsafe(32)
            with self._db() as db:
                moved = db.execute(
                    "UPDATE oauth_requests SET status='issued', code_hash=?, code_expires_at=? "
                    "WHERE handle_hash=? AND status='approved'",
                    (_hash(code), _iso(now + timedelta(seconds=CODE_TTL_S)), row["handle_hash"])).rowcount
            if moved == 1:
                return "code", row, code
        return "done", row, None

    # ── tokens ─────────────────────────────────────────────────────────────

    def authenticate_client(self, form: dict, authorization: str | None) -> Client:
        """The client's own credentials, by the method it registered — and no other (``invalid_client``)."""
        basic_id = basic_secret = None
        if authorization and authorization.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(authorization[6:].strip(), validate=True).decode("utf-8")
                basic_id, _, basic_secret = (unquote(p) for p in decoded.partition(":"))
            except (ValueError, UnicodeDecodeError):
                raise OAuthError("invalid_client", "unreadable client credentials", status=401) from None
        client_id = basic_id or form.get("client_id") or ""
        client = self.get_client(client_id)
        if client is None or (form.get("client_id") and basic_id and form.get("client_id") != basic_id):
            raise OAuthError("invalid_client", "unknown client", status=401)
        if client.auth_method == "none":
            if basic_secret or form.get("client_secret"):
                raise OAuthError("invalid_client", "this client has no secret", status=401)
        elif client.auth_method == "client_secret_basic":
            if basic_id is None or not _same(client.secret_hash, basic_secret or ""):
                raise OAuthError("invalid_client", "wrong client credentials", status=401)
        elif client.auth_method == "client_secret_post":
            if basic_id is not None or not _same(client.secret_hash, form.get("client_secret") or ""):
                raise OAuthError("invalid_client", "wrong client credentials", status=401)
        return client

    def _issue(self, db, *, connector: catalog.Connector, client_id: str, grant_ref: str, resource: str,
               now: datetime) -> dict:
        expires = _at(connector.expires_at) or now
        access_until = min(now + timedelta(seconds=ACCESS_TTL_S), expires)
        access = f"cic_at_{connector.id}_{secrets.token_urlsafe(32)}"
        refresh = f"cic_rt_{connector.id}_{secrets.token_urlsafe(32)}"
        for token, kind, until in ((access, "access", access_until), (refresh, "refresh", expires)):
            db.execute("INSERT INTO oauth_tokens (token_hash, kind, connector_id, client_id, grant_ref, resource, "
                       "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (_hash(token), kind, connector.id, client_id, grant_ref, resource, _iso(now), _iso(until)))
        return {"access_token": access, "token_type": "Bearer",
                "expires_in": max(1, int((access_until - now).total_seconds())), "refresh_token": refresh,
                "scope": " ".join(sorted(connector.scopes))}

    def _revoke_grant(self, db, grant_ref: str, now: datetime) -> None:
        db.execute("UPDATE oauth_tokens SET revoked_at=COALESCE(revoked_at, ?) WHERE grant_ref=?",
                   (_iso(now), grant_ref))

    def exchange_code(self, client: Client, form: dict) -> dict:
        code, verifier = form.get("code") or "", form.get("code_verifier") or ""
        now = self.clock()
        with self._db() as db:
            row = db.execute("SELECT * FROM oauth_requests WHERE code_hash=?", (_hash(code),)).fetchone() \
                if code else None
            if row is None:
                raise OAuthError("invalid_grant", "unknown authorization code")
            if row["code_used"]:
                # A replayed code: whoever holds it is not the app that used it — end what it issued (OAuth 2.1).
                self._revoke_grant(db, row["ref"], now)
                db.commit()  # the refusal raises out of the block, which would otherwise roll the revocation back
                raise OAuthError("invalid_grant", "this authorization code was already used")
            if (_at(row["code_expires_at"]) or now) <= now:
                raise OAuthError("invalid_grant", "this authorization code expired")
            if row["client_id"] != client.client_id:
                raise OAuthError("invalid_grant", "this code was issued to another client")
            if form.get("redirect_uri") != row["redirect_uri"]:
                raise OAuthError("invalid_grant", "redirect_uri does not match the authorization request")
            if not _PKCE_RE.match(verifier) or not hmac.compare_digest(pkce_challenge(verifier), row["code_challenge"]):
                raise OAuthError("invalid_grant", "PKCE verification failed")
            if form.get("resource") and _origin_of(form["resource"]) != _origin_of(row["resource"]):
                raise OAuthError("invalid_target", "resource does not match the authorization request")
            if db.execute("UPDATE oauth_requests SET code_used=1, state=NULL WHERE code_hash=? AND code_used=0",
                          (_hash(code),)).rowcount != 1:
                raise OAuthError("invalid_grant", "this authorization code was already used")
            connector = self.connectors.get(row["connector_id"] or "")
            if connector is None or connector.state(now) != "active":
                raise OAuthError("invalid_grant", "this connection was revoked or expired")
            return self._issue(db, connector=connector, client_id=client.client_id, grant_ref=row["ref"],
                               resource=row["resource"], now=now)

    def refresh(self, client: Client, form: dict) -> dict:
        token = form.get("refresh_token") or ""
        now = self.clock()
        if not REFRESH_RE.match(token):
            raise OAuthError("invalid_grant", "unknown refresh token")
        with self._db() as db:
            row = db.execute("SELECT * FROM oauth_tokens WHERE token_hash=? AND kind='refresh'",
                             (_hash(token),)).fetchone()
            if row is None or row["client_id"] != client.client_id:
                raise OAuthError("invalid_grant", "unknown refresh token")
            if row["revoked_at"]:
                revoked = _at(row["revoked_at"]) or now
                if not row["rotated"] or (now - revoked).total_seconds() > REFRESH_REUSE_GRACE_S:
                    # A rotated refresh token used again: it leaked. End the whole grant.
                    self._revoke_grant(db, row["grant_ref"], now)
                    db.commit()  # as above: the raise must not roll the revocation back
                raise OAuthError("invalid_grant", "this refresh token is no longer valid")
            if (_at(row["expires_at"]) or now) <= now:
                raise OAuthError("invalid_grant", "this refresh token expired")
            connector = self.connectors.get(row["connector_id"])
            if connector is None or connector.state(now) != "active":
                raise OAuthError("invalid_grant", "this connection was revoked or expired")
            if db.execute("UPDATE oauth_tokens SET revoked_at=?, rotated=1 WHERE token_hash=? AND revoked_at IS NULL",
                          (_iso(now), row["token_hash"])).rowcount != 1:
                raise OAuthError("invalid_grant", "this refresh token is no longer valid")
            return self._issue(db, connector=connector, client_id=client.client_id, grant_ref=row["grant_ref"],
                               resource=row["resource"], now=now)

    def revoke_token(self, client: Client, token: str) -> None:
        """RFC 7009: a refresh token ends its grant, an access token itself; an unknown token is not an error."""
        now = self.clock()
        with self._db() as db:
            row = db.execute("SELECT * FROM oauth_tokens WHERE token_hash=?", (_hash(token or ""),)).fetchone()
            if row is None or row["client_id"] != client.client_id:
                return
            if row["kind"] == "refresh":
                self._revoke_grant(db, row["grant_ref"], now)
            else:
                db.execute("UPDATE oauth_tokens SET revoked_at=COALESCE(revoked_at, ?) WHERE token_hash=?",
                           (_iso(now), row["token_hash"]))

    def verify_access(self, token: str, base: str | None) -> tuple[catalog.Connector | None, str]:
        """The gate's check for a ``cic_at_`` token, in :meth:`ConnectorStore.verify`'s vocabulary. The token must
        have been issued for this server's resource (its audience)."""
        if not ACCESS_RE.match(token or ""):
            return None, "malformed"
        now = self.clock()
        with self._db() as db:
            row = db.execute("SELECT * FROM oauth_tokens WHERE token_hash=? AND kind='access'",
                             (_hash(token),)).fetchone()
        if row is None:
            return None, "unknown"
        if base is None or row["resource"] not in resources(base):
            return None, "unknown"
        connector = self.connectors.get(row["connector_id"])
        if connector is None:
            return None, "unknown"
        if row["revoked_at"]:
            return connector, "revoked"
        if (_at(row["expires_at"]) or now) <= now:
            return connector, "expired"
        state = connector.state(now)
        return connector, ("ok" if state == "active" else state)

    # ── HTTP ──────────────────────────────────────────────────────────────

    def metadata(self, base: str) -> dict:
        return {
            "issuer": base,
            "authorization_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token",
            "registration_endpoint": f"{base}/register",
            "revocation_endpoint": f"{base}/revoke",
            "response_types_supported": ["code"],
            "response_modes_supported": ["query"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": list(AUTH_METHODS),
            "revocation_endpoint_auth_methods_supported": list(AUTH_METHODS),
            "scopes_supported": [*catalog.SCOPES, OFFLINE],
            "client_id_metadata_document_supported": True,
            "authorization_response_iss_parameter_supported": True,
            "service_documentation": "https://github.com/rorosaga/cicada",
        }

    async def handle(self, request: Request) -> Response:
        path = request.url.path
        base = public_base(request)
        if base is None:
            return _page("Cicada", "This address isn't one Cicada answers on.", status=400)
        if path == "/.well-known/oauth-authorization-server":
            return JSONResponse(self.metadata(base), headers={"Cache-Control": "no-store"})
        try:
            if path == "/register" and request.method == "POST":
                if not self.limits.register.take():
                    raise OAuthError("slow_down", "too many registrations — try again in a minute", status=429)
                body = await _read_body(request)
                try:
                    payload = json.loads(body or b"null")
                except ValueError:
                    raise OAuthError("invalid_client_metadata", "the body must be JSON") from None
                return JSONResponse(self.register(payload), status_code=201, headers=_NO_STORE)
            if path == "/token" and request.method == "POST":
                if not self.limits.token.take():
                    raise OAuthError("slow_down", "too many requests — try again in a minute", status=429)
                form = await _read_form(request)
                client = self.authenticate_client(form, request.headers.get("authorization"))
                grant = form.get("grant_type")
                if grant == "authorization_code":
                    return JSONResponse(self.exchange_code(client, form), headers=_NO_STORE)
                if grant == "refresh_token":
                    return JSONResponse(self.refresh(client, form), headers=_NO_STORE)
                raise OAuthError("unsupported_grant_type", "authorization_code or refresh_token")
            if path == "/revoke" and request.method == "POST":
                if not self.limits.token.take():
                    raise OAuthError("slow_down", "too many requests — try again in a minute", status=429)
                form = await _read_form(request)
                client = self.authenticate_client(form, request.headers.get("authorization"))
                self.revoke_token(client, form.get("token") or "")
                return Response(status_code=200, headers=_NO_STORE)
        except OAuthError as exc:
            headers = dict(_NO_STORE)
            if exc.status == 401:
                headers["WWW-Authenticate"] = 'Basic realm="cicada"'
            if exc.status == 429:
                headers["Retry-After"] = "60"
            return JSONResponse({"error": exc.error, "error_description": exc.description},
                                status_code=exc.status, headers=headers)
        if path == "/authorize" and request.method == "GET":
            return await self._authorize(request, base)
        if path == "/authorize/wait" and request.method == "GET":
            return self._wait(request, base)
        return Response("Method not allowed", status_code=405)

    async def _authorize(self, request: Request, base: str) -> Response:
        q = request.query_params
        if not self.limits.authorize.take():
            return _page("Too many sign-ins", "Too many sign-in attempts reached Cicada. Wait a minute and try "
                         "again from the app.", status=429)
        client = await self.resolve_client(q.get("client_id") or "")
        if client is None:
            return _page("Unknown app", "This app isn't registered with Cicada. Start again from the app you "
                         "are connecting.", status=400)
        redirect_uri = q.get("redirect_uri") or (client.redirect_uris[0] if len(client.redirect_uris) == 1 else "")
        if not redirect_matches(client.redirect_uris, redirect_uri):
            # Never redirect to an address the client did not register (no open redirect).
            return _page("Unknown return address", "This sign-in asks Cicada to send you somewhere the app never "
                         "registered, so Cicada stopped here.", status=400)
        state = q.get("state")
        if state is not None and len(state) > 1024:
            return _page("Sign-in refused", "This sign-in request is too long.", status=400)

        def back(**params) -> Response:
            return _redirect(redirect_uri, {**params, **({"state": state} if state is not None else {}), "iss": base})

        if q.get("response_type") != "code":
            return back(error="unsupported_response_type", error_description="only the code flow is supported")
        if q.get("code_challenge_method") != "S256" or not _CHALLENGE_RE.match(q.get("code_challenge") or ""):
            return back(error="invalid_request", error_description="PKCE with S256 is required")
        resource = (q.get("resource") or f"{base}/mcp").rstrip("/")
        if resource not in resources(base):
            return back(error="invalid_target", error_description="this server is " + f"{base}/mcp")
        asked = [s for s in (q.get("scope") or "").split() if s in catalog.SCOPES]
        try:
            handle, binding, user_code = self.start_request(
                client=client, redirect_uri=redirect_uri, code_challenge=q["code_challenge"], state=state,
                resource=resource, scopes_asked=asked)
        except OAuthError:
            return _page("Too many sign-ins", "Several sign-ins are already waiting for you in Cicada. Approve or "
                         "deny them there, then try again.", status=429)
        response = _wait_page(handle, user_code, client, redirect_uri)
        response.set_cookie(COOKIE, binding, max_age=REQUEST_TTL_S, path="/authorize", secure=True, httponly=True,
                            samesite="lax")
        return response

    def _wait(self, request: Request, base: str) -> Response:
        handle = request.query_params.get("r") or ""
        verdict, row, code = self.collect(handle, request.cookies.get(COOKIE))
        if verdict == "unknown":
            return _page("Sign-in not found", "Cicada doesn't know this sign-in, or it was started in another "
                         "browser. Start again from the app you are connecting.", status=400)
        if verdict == "expired":
            return _page("Sign-in expired", "Nobody approved this sign-in in Cicada in time. Start again from the "
                         "app you are connecting.", status=400)
        if verdict == "pending":
            client = self.get_client(row["client_id"])
            return _wait_page(handle, row["user_code"], client, row["redirect_uri"])
        state = row["state"] if row is not None else None
        extra = {"state": state} if state is not None else {}
        if verdict == "denied":
            return _redirect(row["redirect_uri"], {"error": "access_denied",
                                                   "error_description": "the person declined in Cicada",
                                                   **extra, "iss": base})
        if verdict == "code":
            return _redirect(row["redirect_uri"], {"code": code, **extra, "iss": base})
        return _page("Already done", "This sign-in is finished. You can close this page.", status=400)


_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_PAGE_HEADERS = {**_NO_STORE, "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                 "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
                 "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}
_STYLE = ("body{font:16px -apple-system,system-ui,sans-serif;margin:0;padding:48px 16px;background:#f7f7f5;"
          "color:#1d1d1f}main{max-width:440px;margin:0 auto}h1{font-size:22px;font-weight:600}"
          ".code{font:600 34px ui-monospace,Menlo,monospace;letter-spacing:4px;margin:24px 0}"
          "p{line-height:1.5;color:#45454a}@media (prefers-color-scheme:dark){body{background:#161617;color:#f5f5f7}"
          "p{color:#b0b0b5}}")


def _page(title: str, text: str, *, status: int = 200, extra_head: str = "", body_html: str = "") -> HTMLResponse:
    doc = (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
           f"content=\"width=device-width,initial-scale=1\"><title>{html.escape(title)} · Cicada</title>{extra_head}"
           f"<style>{_STYLE}</style></head><body><main><h1>{html.escape(title)}</h1>{body_html}"
           f"<p>{html.escape(text)}</p></main></body></html>")
    return HTMLResponse(doc, status_code=status, headers=_PAGE_HEADERS)


def _wait_page(handle: str, user_code: str, client: Client | None, redirect_uri: str) -> HTMLResponse:
    who = (client.name if client and client.name else None) or "An app"
    host = _netloc_host(urlparse(redirect_uri))
    refresh = f"<meta http-equiv=\"refresh\" content=\"{WAIT_REFRESH_S};url=/authorize/wait?r={html.escape(handle)}\">"
    return _page(
        "Approve in Cicada",
        f"{who} wants to connect to your memory and will be sent back to {host}. Open Cicada on your Mac — "
        "Settings, Agents, From anywhere — and approve the sign-in showing this code. This page moves on by "
        "itself once you do. Didn't start this? Deny it there.",
        extra_head=refresh, body_html=f"<div class=\"code\">{html.escape(user_code)}</div>")


def _redirect(uri: str, params: dict) -> Response:
    joiner = "&" if urlparse(uri).query else "?"
    return RedirectResponse(uri + joiner + urlencode(params), status_code=302, headers=_NO_STORE)


async def _read_body(request: Request) -> bytes:
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_FORM_BYTES:
            raise OAuthError("invalid_request", "request body too large", status=413)
    return body


async def _read_form(request: Request) -> dict:
    """``application/x-www-form-urlencoded`` only (RFC 6749 §4.1.3); a repeated parameter is refused."""
    if (request.headers.get("content-type") or "").split(";")[0].strip().lower() != "application/x-www-form-urlencoded":
        raise OAuthError("invalid_request", "use application/x-www-form-urlencoded")
    pairs = parse_qsl((await _read_body(request)).decode("utf-8", "replace"), keep_blank_values=True)
    form: dict[str, str] = {}
    for key, value in pairs:
        if key in form:
            raise OAuthError("invalid_request", f"{key} appears twice")
        form[key] = value
    return form
