"""OpenRouter sign-in (round 4 providers; R-AG10).

OpenRouter is the one provider whose sign-in hands a desktop app a key of its
own (public-client PKCE, no client secret); Anthropic, OpenAI, Google and xAI
restrict their plan sign-ins to their own clients, so they stay paste-a-key.

Flow: ``begin`` mints a PKCE S256 pair and a single-use nonce (10 minutes) and
returns OpenRouter's consent URL whose ``callback_url`` is this backend's own
loopback route with the nonce in the PATH. OpenRouter appends only ``code`` to
``callback_url``, so a ``state`` parameter is not guaranteed to come back; a
path segment survives whatever query handling it applies. The browser cannot
send the bearer token, so ``auth._is_oauth_callback_path`` opens exactly this
path and the nonce is the gate. ``complete`` spends the nonce FIRST (a codeless
or failed callback cannot be replayed), posts ``{code, code_verifier,
code_challenge_method}`` to ``/api/v1/auth/keys``, and stores the returned key
as ``OPENROUTER_API_KEY`` through ``secrets.set_secret``. The key is never
returned, logged or put in an error, and the verifier never leaves this
process — so a ``code`` that reaches an access log cannot be exchanged.

User-initiated, so no fetch gate applies (every OAuth exchange is ungated);
the paste-a-key path of ``ByokAdapter`` keeps working beside it.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import secrets as pysecrets
import threading
import time
import uuid
from typing import Awaitable, Callable
from urllib.parse import urlencode

from api.models.schemas import ConnectionStatus, LoginHint, LoginSession
from api.services.connections import byok, secrets

CONNECTION_ID = "byok-openrouter"
OAUTH_CONNECTION_IDS = frozenset({CONNECTION_ID})
AUTH_URL = "https://openrouter.ai/auth"
KEYS_URL = "https://openrouter.ai/api/v1/auth/keys"
DEFAULT_BASE_URL = "http://localhost:8000"
KEY_LABEL = "Cicada"   # what the person sees on openrouter.ai/settings/keys, to revoke it there
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{32}$")   # secrets.token_urlsafe(24)
TTL_SECONDS = 600
EXCHANGE_TIMEOUT_S = 10.0

PostJson = Callable[[str, dict], Awaitable[dict]]

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0"})


def callback_base(host: str, port: int) -> str:
    """Where OpenRouter's consent page sends the browser back to. OpenRouter documents localhost callbacks as
    ``http://localhost:<any port>``, and a numeric loopback address is not what it names, so a loopback bind is
    spelled ``localhost`` (the browser still reaches the 127.0.0.1 listener). Found by the round-4 orchestrator
    live pass, which could not confirm a ``127.0.0.1`` callback against the live consent page."""
    host = (host or "").strip().strip("[]").lower()
    return f"http://{'localhost' if host in _LOOPBACK_HOSTS else host}:{port}"



class InvalidState(Exception):
    """Unknown, spent or expired nonce, or no code came back."""


class ExchangeError(Exception):
    """OpenRouter did not hand back a key. Carries no response text."""


_pending: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


def callback_path(nonce: str) -> str:
    return f"/connections/{CONNECTION_ID}/callback/{nonce}"


def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(64)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=")
    return verifier, challenge.decode("ascii")


def begin(base_url: str = DEFAULT_BASE_URL, *, now: float | None = None) -> tuple[str, str]:
    now = time.time() if now is None else now
    verifier, challenge = _pkce()
    nonce = pysecrets.token_urlsafe(24)
    with _lock:
        for key, (_, expires) in list(_pending.items()):
            if expires < now:
                _pending.pop(key, None)
        _pending[nonce] = (verifier, now + TTL_SECONDS)
    query = urlencode({"callback_url": base_url.rstrip("/") + callback_path(nonce), "code_challenge": challenge,
                       "code_challenge_method": "S256", "key_label": KEY_LABEL})
    return nonce, f"{AUTH_URL}?{query}"


async def _default_post(url: str, body: dict) -> dict:
    import httpx

    async with httpx.AsyncClient(follow_redirects=False, timeout=EXCHANGE_TIMEOUT_S) as client:
        response = await client.post(url, json=body)
        response.raise_for_status()
        return response.json()


async def complete(nonce: str, code: str, *, post: PostJson | None = None, now: float | None = None) -> None:
    now = time.time() if now is None else now
    with _lock:
        entry = _pending.pop(nonce, None)
    if entry is None or entry[1] < now:
        raise InvalidState("unknown or expired sign-in")
    if not code:
        raise InvalidState("no authorization code came back")
    try:
        payload = await (post or _default_post)(KEYS_URL, {"code": code, "code_verifier": entry[0],
                                                           "code_challenge_method": "S256"})
    except Exception as exc:  # noqa: BLE001 — the type only: a body can carry a key
        raise ExchangeError(type(exc).__name__) from None
    key = payload.get("key") if isinstance(payload, dict) else None
    if not isinstance(key, str) or not key.strip():
        raise ExchangeError("no key in the response")
    secrets.set_secret(byok.provider("openrouter").env, key.strip())


class OpenRouterAdapter(byok.ByokAdapter):
    """The OpenRouter key card: sign in (R-AG10) or paste a key (unchanged)."""

    LOGIN_MODE = "oauth"

    def __init__(self) -> None:
        super().__init__("openrouter")

    async def status(self) -> ConnectionStatus:
        status = await super().status()
        status.login = LoginHint(mode="oauth")
        if not status.connected:
            status.detail = f"Sign in with OpenRouter, or paste a key; it is stored in {secrets.secrets_path()} (0600)."
        return status

    async def begin_login(self, *, base_url: str = DEFAULT_BASE_URL) -> LoginSession:
        _nonce, url = begin(base_url)
        return LoginSession(session_id=uuid.uuid4().hex, connection_id=self.id, mode="oauth", url=url,
                            detail="Finish signing in in your browser; this card updates itself.")
