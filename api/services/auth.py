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
``GET /sources/connectors/pinterest/callback`` (G71 — Pinterest's OAuth
redirect lands in the user's own browser, which likewise cannot send it;
gated instead by a single-use, 10-minute ``state`` nonce). Today the Telegram
route is gated only by Telegram being *configured* (``CICADA_TELEGRAM_BOT_TOKEN``
set, checked in ``api/routers/capture.py``), not by a per-request secret
verifying the caller really is Telegram — see G57.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Header, HTTPException, Request
from loguru import logger

TOKEN_FILE_NAME = "api_token"
_OPEN_PATHS = frozenset({
    "/healthz",
    "/capture/telegram",
    # G71: Pinterest's OAuth redirect lands in the user's browser, which cannot
    # send the bearer token. Gated instead by a single-use, 10-minute `state`
    # nonce minted by POST /sources/connectors/pinterest/authorize.
    "/sources/connectors/pinterest/callback",
})


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
