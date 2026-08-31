"""X (Twitter) bookmarks — the third sanctioned direct API (G71 follow-up, Task 14).

``GET /2/users/:id/bookmarks`` is the sanctioned route: a bookmark on X IS the
save primitive there (no boards, no folders — a flat list). Unlike Pinterest
and Reddit, X's public OAuth 2.0 client needs no client secret at all — it
authenticates the authorization-code exchange with a PKCE ``code_verifier``
instead, so the setup panel asks for exactly one field (the client id) and
this module never stores a secret alongside it.

Billing is pay-per-use ("owned reads" billed per resource returned, no
subscription tier) — the user funds a small credit balance in their own
developer account, same "bring your own app" posture as Pinterest/Reddit. The
channel row and every sync result surface that cost model explicitly (G71:
cost honesty) rather than hiding it behind a plain "connected" checkbox.

The redirect target is the local backend itself, exactly like Pinterest's
``/sources/connectors/pinterest/callback`` — no second HTTP server, no new
port. ``GET /sources/connectors/x/callback`` is the other auth-exempt route
(nonce-gated, same as Pinterest's).
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from urllib.parse import urlencode

from loguru import logger

from api.services import media_ingestor, sync_state
from api.services.connections import secrets
from api.services.connectors import base
from api.services.media_ingestor import RawItem

CHANNEL_ID = "x"
LABEL = "X (Twitter)"
LOGIN_MODE = "oauth"
CHANNEL_NOUN = "bookmark"

CLIENT_ID_ENV = "X_CLIENT_ID"
TOKEN_ENV = "X_ACCESS_TOKEN"
REFRESH_TOKEN_ENV = "X_REFRESH_TOKEN"
USER_ID_ENV = "X_USER_ID"

# What the setup panel asks for, in order. A PUBLIC PKCE client needs no
# secret — there is deliberately no second, `secret: True` field here the way
# Pinterest's app secret is one. `secret: True` on a field renders a
# SecureField and — like every field here — the VALUE is never read back out
# to any caller.
FIELDS: tuple[dict, ...] = (
    {"name": CLIENT_ID_ENV, "label": "Client ID", "secret": False},
)

# Every secret this adapter can write: FIELDS' one name plus every derived
# token — the access/refresh token pair and the resolved user id. This is the
# orphan-fix (Task 15 §4): `forget()` sweeps exactly this tuple, so a token
# this module derives can never outlive a disconnect just because someone
# updates FIELDS without remembering to update a second, separate list.
SECRET_NAMES: tuple[str, ...] = (CLIENT_ID_ENV, TOKEN_ENV, REFRESH_TOKEN_ENV, USER_ID_ENV)

# G71 follow-up (Task 14): OAuth 2.0 PKCE user-context scopes for the X API v2
# bookmarks endpoint (route verified 2026-08-31, docs/goals/saved-content-
# integrations.md). `offline.access` is what grants a refresh token — without
# it a bookmark poll would need a full browser re-auth every ~2h, defeating
# the whole point of a nightly Sleep-tail sync. RE-CHECK before shipping: this
# is a best-effort read of X's developer docs, not independently verified
# against a live app (no network access to check it from here) — treat as a
# to-confirm constant, same caveat Pinterest's SCOPES carries.
SCOPES = "bookmark.read tweet.read users.read offline.access"

# RE-CHECK (pricing churned 3x in 2026, per the brief): pay-per-use "owned
# reads" billed at $0.001 per resource, no monthly subscription tier. Surfaced
# verbatim on the channel row and in every sync summary so the user sees the
# cost model before connecting, never after a surprise invoice.
PRICE_PER_READ = 0.001
PRICE_NOTE = "~$0.001/read · pay-per-use"

AUTH_URL = "https://twitter.com/i/oauth2/authorize"
TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
API_BASE = "https://api.twitter.com/2"
ME_URL = f"{API_BASE}/users/me"
REDIRECT_PATH = "/sources/connectors/x/callback"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"

PAGE_SIZE = 100
# 100 x 10 = 1 000 tweet-reads per sync at worst, each one a billed "owned
# read" — bounded the same conservative way Reddit's ~1,000-item cap is, but
# here it is a cost decision, not a platform limit.
MAX_PAGES = 10
SEEN_KEY = "last_seen_id"

# Title fallback length: enough to recognize the tweet in a list view, short
# enough not to look like the whole body got hoisted into the title.
_TITLE_MAX = 80


# --- credentials -------------------------------------------------------------


def is_connected() -> bool:
    """Connected == a usable access token is stored, same contract as Pinterest.

    App id alone (no token yet) only means the user got as far as the consent
    screen."""
    return secrets.has_secret(TOKEN_ENV)


def credential_fields() -> list[dict]:
    """The setup panel's field list — presence only, NEVER a value."""
    return [{**f, "present": secrets.has_secret(f["name"])} for f in FIELDS]


def forget() -> None:
    """Remove every stored X credential, including the derived user id and
    refresh token — a disconnect must leave nothing an old session could use."""
    for name in (CLIENT_ID_ENV, TOKEN_ENV, REFRESH_TOKEN_ENV, USER_ID_ENV):
        secrets.remove_secret(name)


# --- OAuth (PKCE) --------------------------------------------------------------


def redirect_uri(base_url: str = DEFAULT_BASE_URL) -> str:
    return base_url.rstrip("/") + REDIRECT_PATH


def generate_pkce_pair() -> tuple[str, str]:
    """RFC 7636 ``(code_verifier, code_challenge)`` for a public PKCE client.

    64 random bytes, base64url-encoded with no padding, land at 86 characters
    of unreserved-alphabet text — comfortably inside RFC 7636's 43-128 char
    verifier bound. The challenge is the verifier's SHA-256, same encoding.
    """
    verifier = base64.urlsafe_b64encode(os.urandom(64)).rstrip(b"=").decode("ascii")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def authorize_url(state: str, code_challenge: str, *, base_url: str = DEFAULT_BASE_URL) -> str:
    """The consent URL the companion app opens in the user's own browser."""
    query = urlencode({
        "client_id": (secrets.load_secrets().get(CLIENT_ID_ENV) or "").strip(),
        "redirect_uri": redirect_uri(base_url),
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })
    return f"{AUTH_URL}?{query}"


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def resolve_user_id(token: str, *, http_fn: base.HttpFn | None = None) -> str:
    """``GET /2/users/me`` — the numeric id the bookmarks route needs.

    X's bookmarks endpoint takes a concrete user id, not a "me" alias, so this
    is resolved once (at connect time) and cached in the secrets store instead
    of spent again on every sync.
    """
    fn = http_fn or base.default_http
    payload = await base.call_http(fn, "GET", ME_URL, headers=_auth_headers(token))
    user_id = str(((payload or {}).get("data") or {}).get("id") or "").strip()
    if not user_id:
        raise base.ConnectorError("X returned no user id")
    return user_id


async def exchange_code(
    code: str,
    code_verifier: str,
    *,
    http_fn: base.HttpFn | None = None,
    base_url: str = DEFAULT_BASE_URL,
) -> None:
    """Trade the authorization code + PKCE verifier for tokens and store them.

    A public client authenticates with ``code_verifier`` instead of a client
    secret — there is no ``auth=`` tuple here, unlike Pinterest's exchange.
    Raises ``ConnectorError`` on a response with no access token — the
    callback route turns that into a plain "couldn't complete sign-in" page,
    never echoing the response body.
    """
    values = secrets.load_secrets()
    client_id = (values.get(CLIENT_ID_ENV) or "").strip()
    if not client_id:
        raise base.ConnectorError("X client id must be saved first")

    fn = http_fn or base.default_http
    payload = await base.call_http(
        fn, "POST", TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(base_url),
            "code_verifier": code_verifier,
            "client_id": client_id,
        },
    )
    token = (payload or {}).get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise base.ConnectorError("X returned no access token")
    token = token.strip()
    secrets.set_secret(TOKEN_ENV, token)

    refresh = (payload or {}).get("refresh_token")
    if isinstance(refresh, str) and refresh.strip():
        secrets.set_secret(REFRESH_TOKEN_ENV, refresh.strip())

    # Best-effort: a `/2/users/me` hiccup must not fail the whole connect —
    # `sync()` resolves and caches the user id lazily if it is still missing.
    try:
        user_id = await resolve_user_id(token, http_fn=fn)
        secrets.set_secret(USER_ID_ENV, user_id)
    except Exception as e:
        logger.warning(f"X: could not resolve user id at connect time: {type(e).__name__}: {e}")


async def refresh_access_token(*, http_fn: base.HttpFn | None = None) -> str:
    """Rotate the access token via the stored ``offline.access`` refresh token.

    X rotates the refresh token on every use (the old one stops working), so
    the new one returned here is stored right back over the old one — same
    "store and rotate through the secrets seam" contract the brief calls for.
    """
    values = secrets.load_secrets()
    client_id = (values.get(CLIENT_ID_ENV) or "").strip()
    refresh_token = (values.get(REFRESH_TOKEN_ENV) or "").strip()
    if not client_id or not refresh_token:
        raise base.ConnectorError("X refresh token is missing; reconnect required")

    fn = http_fn or base.default_http
    payload = await base.call_http(
        fn, "POST", TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
    )
    token = (payload or {}).get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise base.ConnectorError("X returned no access token on refresh")
    token = token.strip()
    secrets.set_secret(TOKEN_ENV, token)

    new_refresh = (payload or {}).get("refresh_token")
    if isinstance(new_refresh, str) and new_refresh.strip():
        secrets.set_secret(REFRESH_TOKEN_ENV, new_refresh.strip())
    return token


async def _ensure_access_token(*, http_fn: base.HttpFn | None = None) -> str:
    """A stored refresh token means the current access token may be stale (X
    user-context tokens expire in ~2h — every nightly poll needs this); with
    no refresh token on file, fall back to whatever access token is stored."""
    values = secrets.load_secrets()
    refresh_token = (values.get(REFRESH_TOKEN_ENV) or "").strip()
    if refresh_token:
        return await refresh_access_token(http_fn=http_fn)
    return (values.get(TOKEN_ENV) or "").strip()


# --- reads -------------------------------------------------------------------


async def fetch_bookmarks(
    user_id: str,
    token: str,
    *,
    http_fn: base.HttpFn | None = None,
    stop_at: str | None = None,
) -> tuple[list[dict], str | None]:
    """Newest-first pages of bookmarked tweets, stopping at ``stop_at``.

    Mirrors ``reddit.fetch_saved``'s cursor contract: returns
    ``(tweets, newest_id)``. ``newest_id`` is the id of the first tweet on the
    FIRST page — the cursor ``sync()`` stores and passes back in as
    ``stop_at`` next run, which is what keeps a nightly poll — and its
    pay-per-use billing — O(new bookmarks) instead of O(every bookmark ever
    saved).
    """
    fn = http_fn or base.default_http
    url = f"{API_BASE}/users/{user_id}/bookmarks"
    tweets: list[dict] = []
    newest: str | None = None
    next_token: str | None = None

    for _ in range(MAX_PAGES):
        params: dict = {"max_results": PAGE_SIZE, "tweet.fields": "text"}
        if next_token:
            params["pagination_token"] = next_token
        payload = await base.call_http(
            fn, "GET", url, headers=_auth_headers(token), params=params
        )
        page = [t for t in ((payload or {}).get("data") or []) if isinstance(t, dict)]
        if newest is None and page:
            newest = str(page[0].get("id") or "") or None

        hit_cursor = False
        for tweet in page:
            tweet_id = str(tweet.get("id") or "")
            if stop_at and tweet_id == stop_at:
                hit_cursor = True
                break
            tweets.append(tweet)
        if hit_cursor:
            break

        next_token = ((payload or {}).get("meta") or {}).get("next_token") or None
        if not next_token:
            break

    return tweets, newest


def bookmarks_to_items(tweets: list) -> list[RawItem]:
    """One ``RawItem`` per bookmarked tweet.

    A bookmark's own permalink is the media url — there is no separate
    "outbound link" concept the way a Pinterest pin or a Reddit link-post has;
    the saved thing IS the tweet. There is no board/subreddit-equivalent
    either, so ``folder`` stays unset (the brief's "no folder"). Tweet text
    rides ``note`` so it lands in the episode body's "## User note" section
    even when best-effort enrichment fails to scrape it back off x.com — a
    JS-rendered page frequently unreachable without an authenticated session,
    exactly why the text is captured here instead of left to enrichment.
    """
    items: list[RawItem] = []
    for tweet in tweets or []:
        if not isinstance(tweet, dict):
            continue
        tweet_id = str(tweet.get("id") or "").strip()
        if not tweet_id:
            continue
        text = str(tweet.get("text") or "").strip()
        title = (text[:_TITLE_MAX].rstrip() + "…") if len(text) > _TITLE_MAX else (text or None)
        items.append(RawItem(
            url=f"https://x.com/i/web/status/{tweet_id}",
            title=title,
            note=(text or None),
            origin="x-bookmarks",
        ))
    return items


# --- sync --------------------------------------------------------------------


async def sync(
    memory_path: Path,
    *,
    http_fn: base.HttpFn | None = None,
    allow_fetch: bool | None = None,
) -> dict:
    """Pull bookmarks newer than the stored cursor and ingest them. NEVER raises.

    Returns ``{"status": "ok"|"skipped"|"error", "new", "seen",
    "resources_read", "error", "reason"}``. ``resources_read`` is the
    pay-per-use-billed count (every tweet the API returned this run,
    dedup or not) — distinct from ``new`` (post-dedup, actually ingested)
    and ``seen`` (total pulled), so the cost-honesty story in the sync
    summary is exact, not an approximation. Idempotent: ``ingest_batch``
    dedups on ``url_index.json``, so re-running costs API reads but never
    writes duplicate episodes.
    """
    empty = {"new": 0, "seen": 0, "resources_read": 0, "error": None}
    if not is_connected():
        return {"status": "skipped", "reason": "not connected", **empty}
    if http_fn is None and not base.network_allowed(allow_fetch):
        return {"status": "skipped", "reason": "network disabled", **empty}

    values = secrets.load_secrets()
    user_id = (values.get(USER_ID_ENV) or "").strip()
    stop_at = (sync_state.read_sync_state(memory_path).get(CHANNEL_ID) or {}).get(SEEN_KEY)

    try:
        token = await _ensure_access_token(http_fn=http_fn)
        if not user_id:
            user_id = await resolve_user_id(token, http_fn=http_fn)
            secrets.set_secret(USER_ID_ENV, user_id)
        tweets, newest = await fetch_bookmarks(user_id, token, http_fn=http_fn, stop_at=stop_at)
    except Exception as e:
        message = f"{type(e).__name__}: {e}"
        logger.warning(f"X sync failed: {message}")
        sync_state.record_error(memory_path, CHANNEL_ID, message)
        return {"status": "error", "reason": None, **empty, "error": message}

    items = bookmarks_to_items(tweets)
    created, _ = await media_ingestor.ingest_batch(
        items[: media_ingestor.MAX_BATCH], memory_path, from_bookmark_file=False
    )
    sync_state.record_sync(
        memory_path, CHANNEL_ID, count=len(items),
        extra={SEEN_KEY: newest} if newest else None,
    )
    return {"status": "ok", "reason": None, "new": created, "seen": len(items),
            "resources_read": len(tweets), "error": None}
