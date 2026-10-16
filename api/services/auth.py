"""Bearer-token auth for the localhost API.

Cicada's backend will start holding provider API keys (connections layer) and
writing files on the user's behalf, so an unauthenticated port 8000 is not
acceptable (claude-mem's port-37777 audit is the cautionary tale). The token
is generated once into ``$CICADA_HOME/api_token`` (0600); the companion app,
the MCP server and ``doctor.sh`` read the same file. ``CICADA_API_TOKEN``
overrides the file; ``CICADA_API_AUTH=off`` disables the check (tests/dev only
— logged loudly at startup).

**Device tokens (G181 phase 2, owner ruling 1, 2026-10-16).** Besides the master token, a request may carry a
per-device token the person issued on this server (``device_tokens``: named, hashed, revocable). It opens every route
but ``/devices`` (issuing and revoking devices is the master token's alone), and the device it names is recorded on
``request.state.device`` — the only way the server learns a call came from one of the person's other machines.

Open paths (no bearer token required): ``GET /healthz`` (installer/doctor
liveness probe), ``POST /capture/telegram`` (Telegram's servers hit this
webhook through a public tunnel and cannot send our bearer header), and
``GET /sources/connectors/<id>/callback`` for every OAuth connector in the
registry (G71, generalized Task 15 §3 — Pinterest and X today) — each OAuth
redirect lands in the user's own browser, which likewise cannot send it, so
each is gated instead by its own single-use, 10-minute ``state`` nonce; and
``GET /connections/byok-openrouter/callback/<nonce>`` (R-AG10), OpenRouter's
sign-in landing in the same browser, gated by its own single-use 10-minute
nonce carried in the PATH (OpenRouter appends only ``code``). The
Telegram route is gated by Telegram being *configured*
(``CICADA_TELEGRAM_BOT_TOKEN`` set) plus, when ``CICADA_TELEGRAM_WEBHOOK_SECRET``
is set in the same ``~/.cicada/secrets.env`` seam, a per-request constant-time
check of Telegram's ``X-Telegram-Bot-Api-Secret-Token`` header (set via
``setWebhook?secret_token=...``) — both checked in ``api/routers/capture.py``.
**The secret is provisioned automatically, not opt-in** (Devin PR #24 round 1,
finding 5): the first request that arrives with none configured triggers
``telegram_capture.ensure_webhook_secret``, which generates one, asks
Telegram what URL is currently registered (``getWebhookInfo``), and
re-registers it with the new ``secret_token`` (``setWebhook``) — only on
success is it persisted. Only if that auto-provisioning fails (no webhook
registered yet, no network, a Telegram API error) does the endpoint fall back
to the old token-only gate, logged loudly once so the gap is visible rather
than silently kept as the happy path — see G57.
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
    connectors registry whose ``LOGIN_MODE`` is ``"oauth"`` (Task 15 §3), and
    ``/connections/<id>/callback/<nonce>`` for a provider sign-in (R-AG10) —
    only an OAuth connection id with a nonce of the exact minted shape, so a
    stray path under ``/connections`` never loses its bearer check.

    Import is local: ``api.services.connections.secrets`` (which every
    connector module uses for credential storage) imports ``cicada_home``
    from THIS module, so a top-level import of the connectors registry here
    would be circular.
    """
    from api.services.connectors import ADAPTERS

    parts = path.split("/")
    if len(parts) == 5 and parts[1] == "connections" and parts[3] == "callback":
        from api.services.connections import openrouter

        return parts[2] in openrouter.OAUTH_CONNECTION_IDS and bool(openrouter.NONCE_RE.match(parts[4]))
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


#: Paths only the master token may use (G181 phase 2, owner ruling 1): issuing and revoking device tokens is an act of
#: the person on the server, never of a device.
MASTER_ONLY_PREFIXES = ("/devices",)


def _master_only(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in MASTER_ONLY_PREFIXES)


def request_device(request: Request):
    """The device whose token signed this request (``device_tokens.Device``), or None for the master token, an open
    path, or auth turned off. Set only by :func:`require_token` from the token itself — never from anything the client
    says about itself."""
    return getattr(request.state, "device", None)


async def require_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """App-wide dependency: 401 unless the bearer token is the master token or an active device token
    (``device_tokens``, G181 phase 2). A device token is refused (403) on the master-only paths."""
    request.state.device = None
    if not auth_enabled() or request.url.path in _OPEN_PATHS:
        return
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if supplied and secrets.compare_digest(supplied.encode("utf-8"), get_token().encode("utf-8")):
        return
    from api.services import device_tokens

    device = None
    if device_tokens.looks_like(supplied):
        try:
            device = device_tokens.store().verify(supplied)
        except Exception:  # noqa: BLE001 - an unreadable store admits no device (fail closed)
            device = None
    if device is None:
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")
    if _master_only(request.url.path):
        raise HTTPException(status_code=403, detail="only the server's own token may manage devices")
    request.state.device = device
    try:
        device_tokens.store().touch(device.id)
    except Exception:  # noqa: BLE001 - a usage stamp never fails a request
        pass
