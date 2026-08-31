"""Pinterest v5 — the one platform whose sanctioned API covers saved content.

A save on Pinterest IS a pin on a board, and ``boards:read``/``pins:read`` read
exactly that (G69). The user brings their own OAuth app (Trial tier reads real
user data); Cicada never ships a client secret and never proxies a token.

The redirect target is the local backend itself — it already listens on
127.0.0.1:8000 — so there is no second HTTP server to spawn and nothing binds a
new port. ``GET /sources/connectors/pinterest/callback`` is the only
auth-exempt route added, and it is nonce-gated.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from loguru import logger

from api.services.connections import secrets
from api.services.connectors import base
from api.services.media_ingestor import RawItem

CHANNEL_ID = "pinterest"
LABEL = "Pinterest"
LOGIN_MODE = "oauth"
CHANNEL_NOUN = "pin"

APP_ID_ENV = "PINTEREST_APP_ID"
APP_SECRET_ENV = "PINTEREST_APP_SECRET"
TOKEN_ENV = "PINTEREST_ACCESS_TOKEN"

# What the setup panel asks for, in order. `secret: True` renders a SecureField
# and — like every field here — the VALUE is never read back out to any caller.
FIELDS: tuple[dict, ...] = (
    {"name": APP_ID_ENV, "label": "App ID", "secret": False},
    {"name": APP_SECRET_ENV, "label": "App secret", "secret": True},
)

# Every secret this adapter can write: FIELDS' env names plus the derived
# access token — the single source `forget()` sweeps (Task 15 §4).
SECRET_NAMES: tuple[str, ...] = (APP_ID_ENV, APP_SECRET_ENV, TOKEN_ENV)

# G71: these scope strings are UNVERIFIED against Pinterest's live developer
# docs at the time of writing (no network access to check them from here) —
# they are the plan's best-effort read of the v5 permission model
# ("boards:read" + "pins:read" cover exactly a saved index: boards and their
# pins). Treat as a to-confirm constant, not a verified fact, before shipping
# a real OAuth app against them.
SCOPES = "boards:read,pins:read"
API_BASE = "https://api.pinterest.com/v5"
AUTH_URL = "https://www.pinterest.com/oauth/"
TOKEN_URL = f"{API_BASE}/oauth/token"
REDIRECT_PATH = "/sources/connectors/pinterest/callback"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"

PAGE_SIZE = 100
MAX_PAGES = 20  # 100 x 20 = 2 000 pins per board — well past MAX_BATCH


# --- credentials -------------------------------------------------------------


def is_connected() -> bool:
    """Connected == a usable access token is stored. App id/secret alone only
    means the user got as far as the consent screen."""
    return secrets.has_secret(TOKEN_ENV)


def credential_fields() -> list[dict]:
    """The setup panel's field list — presence only, NEVER a value."""
    return [{**f, "present": secrets.has_secret(f["name"])} for f in FIELDS]


def forget() -> None:
    """Remove every stored Pinterest credential."""
    for name in (APP_ID_ENV, APP_SECRET_ENV, TOKEN_ENV):
        secrets.remove_secret(name)


# --- OAuth -------------------------------------------------------------------


def redirect_uri(base_url: str = DEFAULT_BASE_URL) -> str:
    return base_url.rstrip("/") + REDIRECT_PATH


def authorize_url(state: str, *, base_url: str = DEFAULT_BASE_URL) -> str:
    """The consent URL the companion app opens in the user's own browser."""
    query = urlencode({
        "client_id": (secrets.load_secrets().get(APP_ID_ENV) or "").strip(),
        "redirect_uri": redirect_uri(base_url),
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    })
    return f"{AUTH_URL}?{query}"


async def exchange_code(
    code: str, *, state: str = "", http_fn: base.HttpFn | None = None,
    base_url: str = DEFAULT_BASE_URL,
) -> None:
    """Trade the authorization code for an access token and store it (0600).

    ``state`` is accepted but unused — Pinterest's exchange needs only the
    saved app id/secret and the code. It exists so the router can call every
    OAuth adapter's ``exchange_code`` with the same ``(code, state=...)``
    shape; X's implementation of this same signature DOES need it, to recover
    its internally-stashed PKCE verifier (Task 15 §3).

    Raises ``ConnectorError`` on a response with no token — the callback route
    turns that into a plain "couldn't complete sign-in" page, never echoing the
    response body (it can contain the app secret's error context).
    """
    values = secrets.load_secrets()
    client_id = (values.get(APP_ID_ENV) or "").strip()
    client_secret = (values.get(APP_SECRET_ENV) or "").strip()
    if not client_id or not client_secret:
        raise base.ConnectorError("Pinterest app id and secret must be saved first")

    fn = http_fn or base.default_http
    payload = await base.call_http(
        fn, "POST", TOKEN_URL,
        auth=(client_id, client_secret),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(base_url),
        },
    )
    token = (payload or {}).get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise base.ConnectorError("Pinterest returned no access token")
    secrets.set_secret(TOKEN_ENV, token.strip())


# --- reads -------------------------------------------------------------------


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {(secrets.load_secrets().get(TOKEN_ENV) or '').strip()}"}


async def _paged(url: str, http_fn: base.HttpFn) -> list[dict]:
    """Walk Pinterest's ``bookmark`` cursor, bounded by ``MAX_PAGES``."""
    out: list[dict] = []
    bookmark: str | None = None
    for _ in range(MAX_PAGES):
        params: dict = {"page_size": PAGE_SIZE}
        if bookmark:
            params["bookmark"] = bookmark
        payload = await base.call_http(
            http_fn, "GET", url, headers=_auth_headers(), params=params
        )
        items = (payload or {}).get("items")
        if isinstance(items, list):
            out.extend(i for i in items if isinstance(i, dict))
        bookmark = (payload or {}).get("bookmark") or None
        if not bookmark:
            break
    return out


async def fetch_boards(*, http_fn: base.HttpFn | None = None) -> list[dict]:
    return await _paged(f"{API_BASE}/boards", http_fn or base.default_http)


async def fetch_pins(board_id: str, *, http_fn: base.HttpFn | None = None) -> list[dict]:
    return await _paged(f"{API_BASE}/boards/{board_id}/pins", http_fn or base.default_http)


def pins_to_items(board_name: str, pins: list) -> list[RawItem]:
    """One ``RawItem`` per pin.

    The pin's outbound ``link`` is what the user actually saved; a pin without
    one (an uploaded image) falls back to its own Pinterest permalink so it is
    still addressable and still dedups. ``folder`` is the board name — G69 names
    board/collection names the strongest unused signal in the whole corpus.
    """
    items: list[RawItem] = []
    for pin in pins or []:
        if not isinstance(pin, dict):
            continue
        url = str(pin.get("link") or "").strip()
        pin_id = str(pin.get("id") or "").strip()
        if not url and pin_id:
            url = f"https://www.pinterest.com/pin/{pin_id}/"
        if not url:
            continue
        items.append(RawItem(
            url=url,
            title=(str(pin.get("title") or "").strip() or None),
            note=(str(pin.get("description") or "").strip() or None),
            added=(str(pin.get("created_at") or "").strip() or None),
            folder=board_name or "Pinterest",
            origin="pinterest",
        ))
    return items


# --- sync --------------------------------------------------------------------


async def sync(
    memory_path: Path,
    *,
    http_fn: base.HttpFn | None = None,
    allow_fetch: bool | None = None,
) -> dict:
    """Pull every board's pins and ingest the new ones. NEVER raises.

    Returns ``{"status": "ok"|"skipped"|"error", "new", "seen", "error",
    "reason"}`` (``base.run_sync``'s canonical shape). Idempotent:
    ``ingest_batch`` dedups on ``url_index.json``, so re-running costs
    nothing but the reads.
    """

    async def fetch(fn: base.HttpFn) -> tuple[list[RawItem], None]:
        boards = await fetch_boards(http_fn=fn)
        items: list[RawItem] = []
        for board in boards:
            board_id = str(board.get("id") or "").strip()
            if not board_id:
                continue
            pins = await fetch_pins(board_id, http_fn=fn)
            items.extend(pins_to_items(str(board.get("name") or "Pinterest"), pins))
        logger.info(f"Pinterest: pulled {len(items)} pin(s) from {len(boards)} board(s)")
        return items, None

    return await base.run_sync(
        CHANNEL_ID, memory_path, fetch,
        http_fn=http_fn, allow_fetch=allow_fetch, is_connected=is_connected,
    )
