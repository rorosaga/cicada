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
but issuing and revoking under ``/devices`` (the master token's alone; reading the list is open, G181 phase 3) and the
writes under ``/remote`` that mint or open a G135 connector (a credential that would outlive the device's revocation),
and the device it names is recorded on ``request.state.device`` and bound for the request (``device_context``, so a
new episode records ``device``) — the only way the server learns a call came from one of the person's other machines.

Open paths (no bearer token required): ``GET /healthz`` (installer/doctor
liveness probe; without a token it says only ``status``, ``version`` and the bank ids — the memory's path, its counts
and the search index's state need the token, owner decision 3, 2026-10-16: through an overlay any device on the
person's tailnet could otherwise read the server's account name from the path), ``POST /capture/telegram`` (Telegram's servers hit this
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
    # G213: the agent API's how-to, the same text at both spellings; static, nothing about the person.
    "/llms.txt",
    # G212: a device redeems a one-time pairing code the person's own screen showed; the code is its credential.
    "/pair",
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
        return (path in _STATIC_OPEN_PATHS or _is_oauth_callback_path(path)
                # G213: the agent API checks its own bearer — a connector token, never this one (`routers/agent_api`).
                or path.startswith("/v1/"))


_OPEN_PATHS = _OpenPaths()


def cicada_home() -> Path:
    """Machine-global Cicada state dir (``~/.cicada`` or ``$CICADA_HOME``), 0700."""
    raw = os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")
    home = Path(raw).expanduser()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    return home


def auth_enabled() -> bool:
    return os.environ.get("CICADA_API_AUTH", "on").strip().lower() not in {"off", "0", "false"}


def credential(authorization: str | None) -> str:
    """The token an ``Authorization`` header carries: ``Bearer <token>``, or ``DPoP <token>`` — the scheme RFC 9449
    gives a key-bound token (2026-10-29). Either scheme reaches the same check; what makes a bound token work is the
    proof beside it, never the word in front of it. "" for anything else."""
    if not authorization:
        return ""
    scheme, _, rest = authorization.partition(" ")
    return rest.strip() if scheme.lower() in ("bearer", "dpop") else ""


#: 2026-10-29: the words a refused proof answers (the reason itself rides ``WWW-Authenticate``, an enum).
PROOF_REFUSED = ("This device's token works only with its own key, and this request's proof did not pass. "
                 "Check the device's clock, or pair it again.")


def proof_refusal(reason: str) -> HTTPException:
    return HTTPException(status_code=401, detail=PROOF_REFUSED, headers={
        "WWW-Authenticate": f'DPoP error="invalid_dpop_proof", error_description="{reason}"',
        "Cache-Control": "no-store"})


def check_proof(device, token: str, request: Request) -> str | None:
    """A key-bound device's request must carry a proof of that key for this very request (``device_proof``): the
    thumbprint, else :class:`HTTPException` 401 — never a fall back to bearer. An unbound device: None, nothing
    checked (the proof header, if any, is ignored)."""
    if not getattr(device, "key_thumbprint", None):
        return None
    from api.services import device_proof

    try:
        jkt = device_proof.verify(request.headers.get(device_proof.HEADER), method=request.method,
                                  path=request.url.path, token=token)
    except device_proof.ProofError as exc:
        raise proof_refusal(exc.reason) from None
    if not secrets.compare_digest(jkt, device.key_thumbprint):
        raise proof_refusal("wrong_key")
    return jkt


def bearer_admits(authorization: str | None, request: Request | None = None) -> bool:
    """Whether an ``Authorization`` header carries the master token or an active device token — for an OPEN route that
    says more to a caller who holds one (``/healthz``'s paths, owner decision 3, 2026-10-16). True when auth is off.
    A key-bound device admits only with its proof (``request`` carries it; without one it never admits). Never raises;
    an unreadable device store admits nothing."""
    if not auth_enabled():
        return True
    supplied = credential(authorization)
    if not supplied:
        return False
    if secrets.compare_digest(supplied.encode("utf-8"), get_token().encode("utf-8")):
        return True
    from api.services import device_tokens

    if not device_tokens.looks_like(supplied):
        return False
    try:
        device = device_tokens.store().verify(supplied)
    except Exception:  # noqa: BLE001 — fail closed
        return False
    # G212: a capture-only device (a phone) gets the open answer — liveness and identity, never the memory's path.
    if device is None or device.kind == "capture":
        return False
    if device.key_bound:
        if request is None:
            return False
        try:
            check_proof(device, supplied, request)
        except HTTPException:
            return False
    return True


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
#: the person on the server, never of a device. Reading the list is not (G181 phase 3): a device's app shows the
#: person which of their devices reach this server (ids, names and times only), and still cannot add or revoke one.
MASTER_ONLY_PREFIXES = ("/devices",)
#: G212: a device's app also reads the devices' status (names, connected, how, queue) — reading, never minting.
_DEVICE_READABLE = frozenset({("GET", "/devices"), ("GET", "/devices/status")})
#: Writes only the master token may make under these prefixes: minting, rotating or turning on a G135 remote
#: connector. A connector token a device minted would outlive the device's own revocation (and the listener it turns
#: on faces the person's tunnel), so a device may read the connector state and revoke, never create or open.
#: G132 phase 1: turning publishing on or off, and "publish from here", are the person's acts on the home, never a
#: device's (a device reads the switch and, as a full device, the log).
MASTER_ONLY_WRITE_PREFIXES = ("/remote", "/agent-api", "/sync/publish")
_MASTER_ONLY_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})


#: G212 (owner 2026-10-22): everything a capture-only device token (a paired phone's) may reach — send a link with a
#: note, send a note, send a photo or a file (G91, ruling 38, 2026-10-23), read back its own recent captures. Exact
#: paths, never prefixes; `/healthz` is open to anyone. Every other route answers 403 to it, the device routes included.
CAPTURE_ROUTES = frozenset({("POST", "/sources/save"), ("POST", "/capture/note"), ("POST", "/capture/file"),
                            ("GET", "/capture/mine")})
#: 2026-10-29: what any device token may do to ITSELF, whatever its kind: bind its own key (and narrow itself to
#: capture-only). Under `/devices`, but about the asking device alone — never another, never a new one.
DEVICE_SELF_ROUTES = frozenset({("POST", "/devices/me/key")})


def _master_only(path: str, method: str = "GET") -> bool:
    if (method.upper(), path) in _DEVICE_READABLE:
        return False
    if any(path == p or path.startswith(p + "/") for p in MASTER_ONLY_PREFIXES):
        return True
    return method.upper() in _MASTER_ONLY_WRITE_METHODS and any(
        path == p or path.startswith(p + "/") for p in MASTER_ONLY_WRITE_PREFIXES)


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
    from api.services import device_context

    request.state.device = None
    device_context.bind(None)
    if not auth_enabled() or request.url.path in _OPEN_PATHS:
        return
    supplied = credential(authorization)
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
    # 2026-10-29: a key-bound token is checked against its proof before anything else is said about it (a copied
    # bound token learns nothing from a 403 either).
    request.state.device_jkt = check_proof(device, supplied, request)
    route = (request.method.upper(), request.url.path)
    if route not in DEVICE_SELF_ROUTES:
        if _master_only(request.url.path, request.method):
            raise HTTPException(status_code=403, detail="only the server's own token may do this")
        if device.kind == "capture" and route not in CAPTURE_ROUTES:
            raise HTTPException(status_code=403, detail="this device may only send captures")
    request.state.device = device
    device_context.bind(device.id)
    try:
        device_tokens.store().touch(device.id)
    except Exception:  # noqa: BLE001 - a usage stamp never fails a request
        pass
    from api.services import agent_seen

    # G212: how the device reached this server (loopback = its tunnel, a tailnet address or Serve header = Tailscale),
    # read from the request alone. Throttled to a write a minute; never fails a request.
    agent_seen.stamp_device(device.id, agent_seen.how_from_request(
        peer=request.client.host if request.client else None, headers=request.headers, device=True))
