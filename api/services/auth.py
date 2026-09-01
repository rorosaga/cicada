"""Bearer-token auth for the localhost API.

Cicada's backend will start holding provider API keys (connections layer) and
writing files on the user's behalf, so an unauthenticated port 8000 is not
acceptable (claude-mem's port-37777 audit is the cautionary tale). The token
is generated once into ``$CICADA_HOME/api_token`` (0600); the companion app,
the MCP server and ``doctor.sh`` read the same file. ``CICADA_API_TOKEN``
overrides the file; ``CICADA_API_AUTH=off`` disables the check (tests/dev only
— logged loudly at startup).

Open paths (no bearer token required): ``GET /healthz`` (installer/doctor
liveness probe), ``POST /capture/telegram`` (Telegram's servers hit this
webhook through a public tunnel and cannot send our bearer header), and
``GET /sources/connectors/<id>/callback`` for every OAuth connector in the
registry (G71, generalized Task 15 §3 — Pinterest and X today) — each OAuth
redirect lands in the user's own browser, which likewise cannot send it, so
each is gated instead by its own single-use, 10-minute ``state`` nonce. The
Telegram route is gated by Telegram being *configured*
(``CICADA_TELEGRAM_BOT_TOKEN`` set) plus, when ``CICADA_TELEGRAM_WEBHOOK_SECRET``
is set in the same ``~/.cicada/secrets.env`` seam, a per-request constant-time
check of Telegram's ``X-Telegram-Bot-Api-Secret-Token`` header (set via
``setWebhook?secret_token=...``) — both checked in ``api/routers/capture.py``.
The secret is opt-in: an install with none configured keeps the old
token-only gate (logged once, not silently) so upgrading never locks out an
already-working bot — see G57.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Header, HTTPException, Request
from loguru import logger

TOKEN_FILE_NAME = "api_token"

# The two literal always-open paths. The OAuth callback path is NOT a fixed
# literal here — see `_is_oauth_callback_path` below.
_STATIC_OPEN_PATHS = frozenset({
    "/healthz",
    "/capture/telegram",
})


def _is_oauth_callback_path(path: str) -> bool:
    """``/sources/connectors/<id>/callback`` for an ``id`` currently in the
    connectors registry whose ``LOGIN_MODE`` is ``"oauth"`` (Task 15 §3).

    Import is local: ``api.services.connections.secrets`` (which every
    connector module uses for credential storage) imports ``cicada_home``
    from THIS module, so a top-level import of the connectors registry here
    would be circular.
    """
    from api.services.connectors import ADAPTERS

    parts = path.split("/")
    if len(parts) != 5 or parts[1:3] != ["sources", "connectors"] or parts[4] != "callback":
        return False
    adapter = ADAPTERS.get(parts[3])
    return adapter is not None and getattr(adapter, "LOGIN_MODE", None) == "oauth"


class _OpenPaths:
    """Supports ``path in _OPEN_PATHS`` like the frozenset it replaces, but
    resolves the OAuth-callback half live against the connectors registry
    instead of hardcoding one literal per adapter — so a new OAuth connector
    is auth-exempt on its callback route for free, and a credentials-only
    adapter (Reddit) never gets one."""

    def __contains__(self, path: object) -> bool:
        if not isinstance(path, str):
            return False
        return path in _STATIC_OPEN_PATHS or _is_oauth_callback_path(path)


_OPEN_PATHS = _OpenPaths()


def cicada_home() -> Path:
    """Machine-global Cicada state dir (``~/.cicada`` or ``$CICADA_HOME``), 0700."""
    raw = os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")
    home = Path(raw).expanduser()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    return home


def auth_enabled() -> bool:
    return os.environ.get("CICADA_API_AUTH", "on").strip().lower() not in {"off", "0", "false"}


def get_token() -> str:
    env = (os.environ.get("CICADA_API_TOKEN") or "").strip()
    if env:
        return env
    path = cicada_home() / TOKEN_FILE_NAME
    if path.exists():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    token = secrets.token_urlsafe(32)
    path.write_text(token + "\n", encoding="utf-8")
    path.chmod(0o600)
    logger.info(f"Generated API token at {path}")
    return token


async def require_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """App-wide dependency: 401 unless the bearer token matches."""
    if not auth_enabled() or request.url.path in _OPEN_PATHS:
        return
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not secrets.compare_digest(supplied.encode("utf-8"), get_token().encode("utf-8")):
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")
