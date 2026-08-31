"""Reddit saved items — the second sanctioned direct API (G69).

``GET /user/{name}/saved`` with the ``history`` scope is official, free for
non-commercial personal use, and pollable at any cadence (100 QPM; nightly is
far under). Its one documented limit is the ~1,000-item listing cap, which the
one-shot GDPR export parser (``media_ingestor.parse_reddit_saved_csv``) exists
to backfill past — the two paths dedup against each other through ``url_hash``
whenever they resolve to the same absolute URL (always true for a self post:
both land on the same ``reddit.com`` permalink; a link post's CSV permalink and
its API-derived outbound URL are two different resources and are expected to
stay two entries).

A *script* app is used deliberately: it is the only Reddit app type a single
user can create for their own account without a redirect URI, so there is no
OAuth round trip and no callback route for this connector.
"""

from __future__ import annotations

from pathlib import Path

from api.services import sync_state
from api.services.connections import secrets
from api.services.connectors import base
from api.services.media_ingestor import RawItem

CHANNEL_ID = "reddit"
LABEL = "Reddit"
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

# Every secret this adapter can write. Reddit has no derived token (a script
# app's password grant is re-run on every sync) — FIELDS' names are the whole
# surface, but this is declared explicitly rather than derived from FIELDS at
# `forget()` time, matching the other two adapters (Task 15 §4).
SECRET_NAMES: tuple[str, ...] = (CLIENT_ID_ENV, CLIENT_SECRET_ENV, USERNAME_ENV, PASSWORD_ENV)

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"
BASE_URL = "https://www.reddit.com"
# Reddit requires a descriptive, non-browser User-Agent and rate-limits
# anonymous-looking clients hard.
USER_AGENT = "macos:cicada:0.1 (personal memory system)"

PAGE_SIZE = 100
MAX_PAGES = 10  # 100 x 10 = the documented ~1,000-item listing cap
SEEN_KEY = "last_seen"


# --- credentials -------------------------------------------------------------


def is_connected() -> bool:
    return all(secrets.has_secret(f["name"]) for f in FIELDS)


def credential_fields() -> list[dict]:
    """The setup panel's field list — presence only, NEVER a value."""
    return [{**f, "present": secrets.has_secret(f["name"])} for f in FIELDS]


def forget() -> None:
    for field in FIELDS:
        secrets.remove_secret(field["name"])


# --- reads -------------------------------------------------------------------


async def fetch_token(*, http_fn: base.HttpFn | None = None) -> str:
    """Password grant against the user's own script app.

    Raises ``ConnectorError`` with no response body attached — a token error
    can echo back credential context and must never reach a log or the app.
    """
    values = secrets.load_secrets()
    payload = await base.call_http(
        http_fn or base.default_http, "POST", TOKEN_URL,
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


async def fetch_saved(
    token: str,
    username: str,
    *,
    http_fn: base.HttpFn | None = None,
    stop_at: str | None = None,
) -> tuple[list[dict], str | None]:
    """Newest-first pages of saved things, stopping at ``stop_at``.

    Returns ``(children, newest_fullname)``. ``newest_fullname`` is the first
    item of the FIRST page — the cursor to pass as ``stop_at`` next run, which
    is what keeps a nightly poll O(new items) instead of O(everything).
    """
    fn = http_fn or base.default_http
    url = f"{API_BASE}/user/{username}/saved"
    children: list[dict] = []
    newest: str | None = None
    after: str | None = None

    for _ in range(MAX_PAGES):
        params: dict = {"limit": PAGE_SIZE, "raw_json": 1}
        if after:
            params["after"] = after
        payload = await base.call_http(
            fn, "GET", url, headers={"User-Agent": USER_AGENT,
                                     "Authorization": f"Bearer {token}"},
            params=params,
        )
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


def children_to_items(children: list) -> list[RawItem]:
    """One ``RawItem`` per saved thing.

    A link post keeps its outbound ``url``; a self post or a saved comment uses
    the reddit permalink. Titles come straight off the listing, so an offline
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
        if not url:
            permalink = str(data.get("permalink") or "").strip()
            url = (BASE_URL + permalink) if permalink.startswith("/") else permalink
        if not url.startswith(("http://", "https://")):
            continue
        subreddit = str(data.get("subreddit") or "").strip()
        items.append(RawItem(
            url=url,
            title=(str(data.get("title") or data.get("link_title") or "").strip() or None),
            folder=f"r/{subreddit}" if subreddit else "Reddit saved",
            origin="reddit-saved",
        ))
    return items


# --- sync --------------------------------------------------------------------


async def sync(
    memory_path: Path,
    *,
    http_fn: base.HttpFn | None = None,
    allow_fetch: bool | None = None,
) -> dict:
    """Pull saved items newer than the stored cursor and ingest them. NEVER raises.

    Returns ``{"status": "ok"|"skipped"|"error", "new", "seen", "error",
    "reason"}`` (``base.run_sync``'s canonical shape).
    """

    async def fetch(fn: base.HttpFn) -> tuple[list[RawItem], dict | None]:
        username = (secrets.load_secrets().get(USERNAME_ENV) or "").strip()
        stop_at = (sync_state.read_sync_state(memory_path).get(CHANNEL_ID) or {}).get(SEEN_KEY)
        token = await fetch_token(http_fn=fn)
        children, newest = await fetch_saved(token, username, http_fn=fn, stop_at=stop_at)
        return children_to_items(children), ({SEEN_KEY: newest} if newest else None)

    return await base.run_sync(
        CHANNEL_ID, memory_path, fetch,
        http_fn=http_fn, allow_fetch=allow_fetch, is_connected=is_connected,
    )
