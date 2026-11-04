"""Reddit — what the person saved, upvoted and joined, through Reddit's own API (G69, G232).

**Two ways to connect, one sync.**

* **Connect Reddit** (G232, owner 2026-11-04: "is there no way to do similar to GitHub"): Cicada's own *installed app*
  — Reddit's app type for software on the person's own device. Reddit: an installed app "cannot keep a secret, and
  therefore, does not receive one", so the code is exchanged with the client id and an empty password, and nothing
  secret ships in the build. The person presses Connect, approves on reddit.com in their own browser, and Reddit sends
  them back to this backend's one callback (``/sources/connectors/reddit/callback``, nonce-gated like every OAuth
  connector's). ``duration=permanent`` gives a refresh token; the hour-long access token is renewed with the client id
  alone. Scopes ``identity history mysubreddits`` — read-only: who the account is, what it saved and upvoted, which
  communities it joined. Disconnect revokes the refresh token at Reddit (``/api/v1/revoke_token``, the client id
  alone) and forgets everything here. Until the app is registered (:data:`CLIENT_ID` is blank — Reddit's Responsible
  Builder Policy, 2025-11-11, ended self-service API keys, so registering is a request Reddit approves), the panel says
  so and offers the other ways in.
* **Your own app** (the older path, kept): a *script* app the person registers for their own account, with its client
  id and secret and their username and password (a password grant). Shown only behind "Use your own app instead".

**What a sync reads** (``GET`` only, ``oauth.reddit.com``): ``/user/<name>/saved`` (newest first, stopping at the
last one seen), ``/user/<name>/upvoted`` (the same), and ``/subreddits/mine/subscriber`` (read whole, it is short).
Each listing stops at Reddit's own ~1,000-item cap; the person's data export backfills past it (the CSV parsers in
``media_ingestor``), and the two dedup on the post's reddit.com permalink.

* A **save** keeps its folder ``r/<subreddit>`` and is read by Sleep as a connector poll always was (ruling 30, 1).
* An **upvote** is a like — folder ``Upvoted``; a **joined community** is a follow — folder ``Joined communities``,
  its link ``https://www.reddit.com/r/<name>/``. Both are index-only, like Instagram's likes and TikTok's favourites
  (ruling 30; ``history_index.LIST_FOLDERS``): found by lookup, never read by a model.

None of these carries the person's words: a post's title is its author's. Reddit gives no date for a save or an
upvote, so none is guessed (ruling 39: ``received_at`` says when Cicada got it).
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from urllib.parse import urlencode

from loguru import logger

from api.services import sync_state
from api.services.connections import secrets
from api.services.connectors import base
from api.services.media_ingestor import RawItem

CHANNEL_ID = "reddit"
LABEL = "Reddit"
#: The fallback's form (a script app's four fields); Connect Reddit is an OAuth sign-in on top (:func:`app_available`).
LOGIN_MODE = "credentials"
CHANNEL_NOUN = "saved item"

CLIENT_ID_ENV = "REDDIT_CLIENT_ID"
CLIENT_SECRET_ENV = "REDDIT_CLIENT_SECRET"
USERNAME_ENV = "REDDIT_USERNAME"
PASSWORD_ENV = "REDDIT_PASSWORD"

FIELDS: tuple[dict, ...] = (
    {"name": CLIENT_ID_ENV, "label": "Client ID", "secret": False},
    {"name": CLIENT_SECRET_ENV, "label": "Client secret", "secret": True},
    {"name": USERNAME_ENV, "label": "Reddit username", "secret": False},
    {"name": PASSWORD_ENV, "label": "Reddit password", "secret": True},
)

#: Cicada's own installed app on Reddit — public by design (it names the app on Reddit's approval page), never a
#: secret. Blank until the app is registered and Reddit approves its access (Responsible Builder Policy); a blank id
#: means Connect Reddit is not offered. :data:`APP_CLIENT_ID_ENV` overrides it (a test, a fork with its own app).
CLIENT_ID = ""
APP_CLIENT_ID_ENV = "CICADA_REDDIT_CLIENT_ID"
#: The one redirect address the app is registered with (Reddit matches it exactly). A backend on another address
#: cannot finish the sign-in, so Connect says so instead of opening a page that would fail.
REDIRECT_PATH = "/sources/connectors/reddit/callback"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
REDIRECT_URI_ENV = "CICADA_REDDIT_REDIRECT_URI"
#: Read-only: the account's name, what it saved and upvoted, the communities it joined.
SCOPES = "identity history mysubreddits"

#: What the sign-in keeps: the tokens, when the access token lapses, the account's name, and how it was made.
TOKEN_ENV = "CICADA_REDDIT_TOKEN"
REFRESH_ENV = "CICADA_REDDIT_REFRESH_TOKEN"
EXPIRES_ENV = "CICADA_REDDIT_TOKEN_EXPIRES"
ACCOUNT_ENV = "CICADA_REDDIT_ACCOUNT"
HOW_ENV = "CICADA_REDDIT_AUTH"
HOW_APP = "app"
#: ``HOW_ENV``'s value once Reddit refused a renewal: the panel says Connect again.
HOW_RECONNECT = "reconnect"
_SIGN_IN_NAMES = (TOKEN_ENV, REFRESH_ENV, EXPIRES_ENV, ACCOUNT_ENV, HOW_ENV)

# Every secret this adapter can write: the fallback's four fields and everything the sign-in keeps (Task 15 §4).
SECRET_NAMES: tuple[str, ...] = (CLIENT_ID_ENV, CLIENT_SECRET_ENV, USERNAME_ENV, PASSWORD_ENV, *_SIGN_IN_NAMES)

AUTH_URL = "https://www.reddit.com/api/v1/authorize"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REVOKE_URL = "https://www.reddit.com/api/v1/revoke_token"
API_BASE = "https://oauth.reddit.com"
BASE_URL = "https://www.reddit.com"
# Reddit requires a descriptive, non-browser User-Agent and rate-limits
# anonymous-looking clients hard.
USER_AGENT = "macos:cicada:0.1 (personal memory system)"

PAGE_SIZE = 100
MAX_PAGES = 10  # 100 x 10 = the documented ~1,000-item listing cap
SEEN_KEY = "last_seen"
UPVOTED_KEY = "last_upvoted"
#: Renew the access token this long before Reddit says it lapses.
REFRESH_MARGIN_S = 120

UPVOTED_FOLDER = "Upvoted"
COMMUNITIES_FOLDER = "Joined communities"

READS = "Read-only: what you saved and upvoted on Reddit, and the communities you joined."
NOT_SET_UP = ("Connecting with Reddit isn't set up in this build yet. Read your saved posts through your browser, "
              "import your Reddit data, or use your own Reddit app.")
WRONG_ADDRESS = ("Connect Reddit works when Cicada runs at its usual address (127.0.0.1:8000). Read your saved posts "
                 "through your browser or import your Reddit data instead.")
RECONNECT_WORDS = "Reddit signed Cicada out. Connect Reddit again to keep your saved posts in sync."

#: Reddit's own shape for an account name: all a listing URL may carry.
_NAME_RE = re.compile(r"[A-Za-z0-9_-]{3,20}")
#: Reddit's community names (letters, digits, underscores, 2–21 characters).
_COMMUNITY_RE = re.compile(r"[A-Za-z0-9_]{2,21}")


# --- credentials -------------------------------------------------------------


def app_client_id() -> str:
    return (os.environ.get(APP_CLIENT_ID_ENV) or "").strip() or (CLIENT_ID or "").strip()


def app_available() -> bool:
    """Whether this build can offer Connect Reddit: false while the app's client id is blank."""
    return bool(app_client_id())


def redirect_uri() -> str:
    return (os.environ.get(REDIRECT_URI_ENV) or "").strip() or DEFAULT_BASE_URL + REDIRECT_PATH


def how() -> str | None:
    """``app`` (Connect Reddit), ``own-app`` (the person's script app), ``reconnect`` (the sign-in lapsed) or None."""
    values = secrets.load_secrets()
    signed = (values.get(HOW_ENV) or "").strip()
    if signed == HOW_RECONNECT:
        return HOW_RECONNECT
    if signed == HOW_APP and (values.get(REFRESH_ENV) or "").strip():
        return HOW_APP
    if all((values.get(f["name"]) or "").strip() for f in FIELDS):
        return "own-app"
    return None


def is_app_token() -> bool:
    return how() == HOW_APP


def needs_reconnect() -> bool:
    return how() == HOW_RECONNECT


def is_connected() -> bool:
    return how() in (HOW_APP, "own-app")


def credential_fields() -> list[dict]:
    """The setup panel's field list — presence only, NEVER a value."""
    return [{**f, "present": secrets.has_secret(f["name"])} for f in FIELDS]


def forget() -> None:
    """Remove every stored Reddit credential (Task 15 §4)."""
    base.forget(SECRET_NAMES)


def on_token_saved() -> None:
    """The person saved their own app's fields: they replace a sign-in made before (one way connected at a time)."""
    for name in _SIGN_IN_NAMES:
        secrets.remove_secret(name)


async def revoke(*, http_fn: base.HttpFn | None = None) -> None:
    """Disconnect's first half: end the grant at Reddit itself (an installed app revokes with its client id and an
    empty password). Never raises — the local forget runs either way, and Reddit's own apps page
    (reddit.com/prefs/apps) lists any grant left."""
    values = secrets.load_secrets()
    refresh = (values.get(REFRESH_ENV) or "").strip()
    if not refresh or not app_client_id() or (values.get(HOW_ENV) or "").strip() not in (HOW_APP, HOW_RECONNECT):
        return
    try:
        await base.call_http(http_fn or base.default_http, "POST", REVOKE_URL,
                             headers={"User-Agent": USER_AGENT}, auth=(app_client_id(), ""),
                             data={"token": refresh, "token_type_hint": "refresh_token"})
    except Exception as exc:  # noqa: BLE001 — the class only
        logger.info(f"reddit: revoking at Reddit failed ({type(exc).__name__}); forgotten here anyway")


# --- Connect Reddit (Cicada's installed app) --------------------------------------


def authorize_url(state: str, *, base_url: str = DEFAULT_BASE_URL) -> str:
    """Reddit's consent page for Cicada's installed app. Raises ``ConnectorError`` (words) when the build has no
    client id, or the backend is not at the address the app is registered with."""
    cid = app_client_id()
    if not cid:
        raise base.ConnectorError(NOT_SET_UP)
    if base_url.rstrip("/") + REDIRECT_PATH != redirect_uri():
        raise base.ConnectorError(WRONG_ADDRESS)
    return f"{AUTH_URL}?" + urlencode({"client_id": cid, "response_type": "code", "state": state,
                                       "redirect_uri": redirect_uri(), "duration": "permanent", "scope": SCOPES})


def _save_grant(payload: dict) -> str:
    token = (payload or {}).get("access_token")
    if not isinstance(token, str) or not token.strip() or (payload or {}).get("error"):
        raise base.ConnectorError("Reddit returned no access token")
    secrets.set_secret(TOKEN_ENV, token.strip())
    refresh = (payload or {}).get("refresh_token")
    if isinstance(refresh, str) and refresh.strip():
        secrets.set_secret(REFRESH_ENV, refresh.strip())
    try:
        lasts = max(60, min(int((payload or {}).get("expires_in") or 3600), 86400))
    except (TypeError, ValueError):
        lasts = 3600
    secrets.set_secret(EXPIRES_ENV, str(int(time.time()) + lasts))
    secrets.set_secret(HOW_ENV, HOW_APP)
    return token.strip()


async def exchange_code(code: str, *, state: str = "", http_fn: base.HttpFn | None = None,
                        base_url: str = DEFAULT_BASE_URL) -> None:
    """Trade the code for tokens with the client id and an empty password (an installed app has no secret), then ask
    the account's own name (``/api/v1/me``) — the listings are addressed by it."""
    cid = app_client_id()
    if not cid:
        raise base.ConnectorError(NOT_SET_UP)
    fn = http_fn or base.default_http
    payload = await base.call_http(fn, "POST", TOKEN_URL, headers={"User-Agent": USER_AGENT}, auth=(cid, ""),
                                   data={"grant_type": "authorization_code", "code": code,
                                         "redirect_uri": redirect_uri()})
    if not isinstance((payload or {}).get("refresh_token"), str) or not payload["refresh_token"].strip():
        raise base.ConnectorError("Reddit gave no lasting sign-in; try Connect Reddit again")
    # A sign-in replaces the person's own app: one way connected at a time.
    for f in FIELDS:
        secrets.remove_secret(f["name"])
    token = _save_grant(payload)
    try:
        await _account_name(token, fn)
    except Exception as exc:  # noqa: BLE001 — the first sync asks again
        logger.info(f"reddit: account name not read at connect ({type(exc).__name__})")


def _headers(token: str) -> dict:
    return {"User-Agent": USER_AGENT, "Authorization": f"Bearer {token}"}


async def _account_name(token: str, fn: base.HttpFn) -> str:
    me = await base.call_http(fn, "GET", f"{API_BASE}/api/v1/me", headers=_headers(token))
    name = str((me or {}).get("name") or "").strip()
    if not _NAME_RE.fullmatch(name):
        raise base.ConnectorError("Reddit returned no account name")
    secrets.set_secret(ACCOUNT_ENV, name)
    return name


def _status_of(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


async def _app_token(fn: base.HttpFn) -> str:
    """The access token, renewed with the refresh token (client id alone) once it is due. Reddit refusing the
    renewal marks the connection as needing Connect again, and raises in words."""
    values = secrets.load_secrets()
    token, expires = (values.get(TOKEN_ENV) or "").strip(), (values.get(EXPIRES_ENV) or "").strip()
    if token and expires.isdigit() and int(expires) - REFRESH_MARGIN_S > time.time():
        return token
    try:
        payload = await base.call_http(fn, "POST", TOKEN_URL, headers={"User-Agent": USER_AGENT},
                                       auth=(app_client_id(), ""),
                                       data={"grant_type": "refresh_token",
                                             "refresh_token": (values.get(REFRESH_ENV) or "").strip()})
    except Exception as exc:  # noqa: BLE001
        if _status_of(exc) in (400, 401, 403):
            secrets.set_secret(HOW_ENV, HOW_RECONNECT)
            raise base.ConnectorError(RECONNECT_WORDS) from exc
        raise
    if (payload or {}).get("error"):
        secrets.set_secret(HOW_ENV, HOW_RECONNECT)
        raise base.ConnectorError(RECONNECT_WORDS)
    return _save_grant(payload)


# --- reads -------------------------------------------------------------------


async def fetch_token(*, http_fn: base.HttpFn | None = None) -> str:
    """The access token for this sync: Cicada's app's (renewed when due) or, for the person's own script app, a
    password grant.

    Raises ``ConnectorError`` with no response body attached — a token error
    can echo back credential context and must never reach a log or the app.
    """
    fn = http_fn or base.default_http
    if is_app_token():
        return await _app_token(fn)
    values = secrets.load_secrets()
    payload = await base.call_http(
        fn, "POST", TOKEN_URL,
        headers={"User-Agent": USER_AGENT},
        auth=((values.get(CLIENT_ID_ENV) or "").strip(),
              (values.get(CLIENT_SECRET_ENV) or "").strip()),
        data={
            "grant_type": "password",
            "username": (values.get(USERNAME_ENV) or "").strip(),
            "password": (values.get(PASSWORD_ENV) or "").strip(),
        },
    )
    token = (payload or {}).get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise base.ConnectorError("Reddit returned no access token")
    return token.strip()


async def account_name(token: str, *, http_fn: base.HttpFn | None = None) -> str:
    """Whose listings to read: the signed-in account (kept from ``/api/v1/me``) or the fallback's username field."""
    values = secrets.load_secrets()
    if not is_app_token():
        return (values.get(USERNAME_ENV) or "").strip()
    name = (values.get(ACCOUNT_ENV) or "").strip()
    return name if _NAME_RE.fullmatch(name) else await _account_name(token, http_fn or base.default_http)


async def fetch_listing(
    token: str,
    url: str,
    *,
    http_fn: base.HttpFn | None = None,
    stop_at: str | None = None,
) -> tuple[list[dict], str | None]:
    """Newest-first pages of one listing, stopping at ``stop_at``.

    Returns ``(children, newest_fullname)``. ``newest_fullname`` is the first
    item of the FIRST page — the cursor to pass as ``stop_at`` next run, which
    is what keeps a nightly poll O(new items) instead of O(everything).
    """
    fn = http_fn or base.default_http
    children: list[dict] = []
    newest: str | None = None
    after: str | None = None

    for _ in range(MAX_PAGES):
        params: dict = {"limit": PAGE_SIZE, "raw_json": 1}
        if after:
            params["after"] = after
        payload = await base.call_http(fn, "GET", url, headers=_headers(token), params=params)
        data = (payload or {}).get("data") or {}
        page = [c for c in (data.get("children") or []) if isinstance(c, dict)]
        if newest is None and page:
            newest = str((page[0].get("data") or {}).get("name") or "") or None

        hit_cursor = False
        for child in page:
            name = str((child.get("data") or {}).get("name") or "")
            if stop_at and name == stop_at:
                hit_cursor = True
                break
            children.append(child)
        if hit_cursor:
            break

        after = data.get("after") or None
        if not after:
            break

    return children, newest


async def fetch_saved(
    token: str,
    username: str,
    *,
    http_fn: base.HttpFn | None = None,
    stop_at: str | None = None,
) -> tuple[list[dict], str | None]:
    """The account's saved things (``/user/<name>/saved``), newest first, stopping at ``stop_at``."""
    return await fetch_listing(token, f"{API_BASE}/user/{username}/saved", http_fn=http_fn, stop_at=stop_at)


async def fetch_upvoted(token: str, username: str, *, http_fn: base.HttpFn | None = None,
                        stop_at: str | None = None) -> tuple[list[dict], str | None]:
    """The account's upvoted posts (``/user/<name>/upvoted``, visible to the account alone), newest first."""
    return await fetch_listing(token, f"{API_BASE}/user/{username}/upvoted", http_fn=http_fn, stop_at=stop_at)


async def fetch_communities(token: str, *, http_fn: base.HttpFn | None = None) -> list[dict]:
    """Every community the account joined (``/subreddits/mine/subscriber``), read whole."""
    children, _ = await fetch_listing(token, f"{API_BASE}/subreddits/mine/subscriber", http_fn=http_fn)
    return children


def children_to_items(children: list) -> list[RawItem]:
    """One ``RawItem`` per saved thing.

    A link post keeps its outbound ``url``; a self post or a saved comment uses
    the reddit permalink, and a link post also carries its permalink as an alias
    (the data export knows only that). Titles come straight off the listing, so an offline
    install still gets a real title with no hydration call (G69's ``/api/info``
    suggestion is unnecessary here). ``folder`` is the subreddit — the same
    user-authored topic label the board/collection paths use.
    """
    items: list[RawItem] = []
    for child in children or []:
        data = child.get("data") if isinstance(child, dict) else None
        if not isinstance(data, dict):
            continue
        url = str(data.get("url") or "").strip()
        if data.get("is_self") or url.startswith("/"):
            url = ""
        permalink = str(data.get("permalink") or "").strip()
        permalink = (BASE_URL + permalink) if permalink.startswith("/") else permalink
        if not url:
            url = permalink
        if not url.startswith(("http://", "https://")):
            continue
        subreddit = str(data.get("subreddit") or "").strip()
        items.append(RawItem(
            url=url,
            title=(str(data.get("title") or data.get("link_title") or "").strip() or None),
            folder=f"r/{subreddit}" if subreddit else "Reddit saved",
            origin="reddit-saved",
            # Reddit's own data export lists a save by its permalink only; kept
            # as an alias so the export and this connector are one page.
            aliases=[permalink] if permalink.startswith(("http://", "https://")) and permalink != url else [],
        ))
    return items


def upvoted_to_items(children: list) -> list[RawItem]:
    """An upvote is a like: the same item a save makes, filed under ``Upvoted`` — index-only (ruling 30)."""
    return [RawItem(url=i.url, title=i.title, folder=UPVOTED_FOLDER, origin=i.origin, aliases=i.aliases)
            for i in children_to_items(children)]


def communities_to_items(children: list) -> list[RawItem]:
    """A joined community is a follow: its own page's link, titled by its name, filed under ``Joined communities``
    — index-only (ruling 30). Only a community's own name makes a link (a person's profile, ``u_<name>``, never)."""
    items: list[RawItem] = []
    for child in children or []:
        data = child.get("data") if isinstance(child, dict) else None
        if not isinstance(data, dict):
            continue
        name = str(data.get("display_name") or "").strip()
        if not _COMMUNITY_RE.fullmatch(name) or name.lower().startswith("u_"):
            continue
        items.append(RawItem(url=f"{BASE_URL}/r/{name}/", title=f"r/{name}", folder=COMMUNITIES_FOLDER,
                             origin="reddit-saved", defer_enrich=True))
    return items


# --- sync --------------------------------------------------------------------


async def sync(
    memory_path: Path,
    *,
    http_fn: base.HttpFn | None = None,
    allow_fetch: bool | None = None,
) -> dict:
    """Pull what was saved and upvoted since the stored cursors, and the joined communities, and ingest them. NEVER
    raises.

    Returns ``{"status": "ok"|"skipped"|"error", "new", "seen", "error",
    "reason"}`` (``base.run_sync``'s canonical shape).
    """

    async def fetch(fn: base.HttpFn) -> tuple[list[RawItem], dict | None]:
        state = sync_state.read_sync_state(memory_path).get(CHANNEL_ID) or {}
        token = await fetch_token(http_fn=fn)
        username = await account_name(token, http_fn=fn)
        if not _NAME_RE.fullmatch(username or ""):
            raise base.ConnectorError("Reddit: no account name to read")
        children, newest = await fetch_saved(token, username, http_fn=fn, stop_at=state.get(SEEN_KEY))
        upvoted, newest_up = await fetch_upvoted(token, username, http_fn=fn, stop_at=state.get(UPVOTED_KEY))
        communities = await fetch_communities(token, http_fn=fn)
        items = children_to_items(children) + upvoted_to_items(upvoted) + communities_to_items(communities)
        cursor = {k: v for k, v in ((SEEN_KEY, newest or state.get(SEEN_KEY)),
                                    (UPVOTED_KEY, newest_up or state.get(UPVOTED_KEY))) if v}
        return items, (cursor or None)

    return await base.run_sync(
        CHANNEL_ID, memory_path, fetch,
        http_fn=http_fn, allow_fetch=allow_fetch, is_connected=is_connected,
    )
