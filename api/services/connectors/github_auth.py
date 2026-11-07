"""Connect GitHub with a code, never a pasted token (G230, owner 2026-11-03: "why are you asking for a token for github?
cant we just do oauth? like a connect?").

**Why a GitHub App and the device flow.** The person presses *Connect GitHub*; Cicada shows a short code and opens
``github.com/login/device``; they approve on GitHub; Cicada, polling, receives a user access token. The device flow
needs no client secret and no server of Cicada's: the app's client id is public and ships in the build
(:data:`CLIENT_ID`), and nothing is redirected anywhere. A **GitHub App** rather than an OAuth App because its
permissions are fine-grained and read-only — *Metadata* and *Contents* read on repositories (the list and a README),
*Starring* read on the account — where an OAuth App reaches a private repository only through the ``repo`` scope,
which is full read and write. The cost: a GitHub App user token sees an account's repositories only where the app is
installed (GitHub: "The app can only access resources in an account where it is installed"), so the connect has a
second step, *Install on your account* (:func:`install_url`), which the panel offers until an installation on the
person's own account exists (:func:`check_installation`). Stars are an account permission and need no installation.

**The token.** GitHub App user tokens expire after 8 hours and come with a refresh token good for 6 months; a token
made by the device flow is refreshed with the client id alone (GitHub: ``client_secret`` is "Required unless the user
access token was generated using the device flow"), so :func:`fresh_token` renews it before any request once it is
due. Everything lives in ``$CICADA_HOME/secrets.env`` (0600) under the adapter's ``SECRET_NAMES`` — never in a bank, a
log, an error line or a response — and Disconnect forgets all of it (``github.forget``). GitHub's own grant stays on
the person's account until they remove it there (``github.com/settings/applications``): revoking it needs the app's
secret, which Cicada does not have.

**Requests.** ``POST https://github.com/login/device/code`` and ``POST https://github.com/login/oauth/access_token``
only (form-encoded, JSON back), through :func:`oauth_transport`: those two paths on ``github.com``, ``net_guard``'s
address rule, no redirect, no cookie, 4 s, ≤ 64 KB. The device code itself never leaves the backend: the app sees the
user code, the verification address and when to ask again. One sign-in at a time, held in this process only — an
interrupted sign-in is started again, never resumed.

**The app is registered** (the owner, 2026-11-04: ``github.com/apps/cicada-memory``, Device Flow on, no client secret
and no private key made). Only a build whose client id is blank — a fork that cleared it, an override set to nothing —
says *Connect GitHub* is not set up and falls back to the token field behind "Use a token instead".
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse

from loguru import logger

from api.services.connectors import tier2

#: The registered app's client id — public by design (it names the app on GitHub's approval page), never a secret.
#: :data:`CLIENT_ID_ENV` overrides it (a test, a developer build, a fork with its own app). The app's numeric id is not
#: kept: the device flow, the refresh and the install link never use it.
CLIENT_ID = "Iv23li7D46T8IiZpTZ9D"
#: The app's address on GitHub (``github.com/apps/<slug>``), for the install step.
APP_SLUG = "cicada-memory"
CLIENT_ID_ENV = "CICADA_GITHUB_CLIENT_ID"
APP_SLUG_ENV = "CICADA_GITHUB_APP_SLUG"

OAUTH_HOST = "github.com"
DEVICE_CODE_PATH = "/login/device/code"
TOKEN_PATH = "/login/oauth/access_token"
VERIFY_URL = "https://github.com/login/device"
GRANTS_URL = "https://github.com/settings/applications"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

TOKEN_ENV = "CICADA_GITHUB_TOKEN"
REFRESH_ENV = "CICADA_GITHUB_REFRESH_TOKEN"
EXPIRES_ENV = "CICADA_GITHUB_TOKEN_EXPIRES"
#: ``app`` when the token came from this sign-in; absent for a pasted token (the fallback).
HOW_ENV = "CICADA_GITHUB_AUTH"
HOW_APP = "app"
SECRET_NAMES = (TOKEN_ENV, REFRESH_ENV, EXPIRES_ENV, HOW_ENV)

TIMEOUT_SECONDS = 4.0
MAX_BYTES = 64 * 1024
#: Renew this long before the token's stated end, so a sync never starts on a token about to lapse.
REFRESH_MARGIN_S = 300
DEFAULT_INTERVAL_S = 5
#: The account state outside every bank: whether the app is installed on the person's own account. Named under the
#: connector's prefix, so Disconnect's sweep of ``connectors/github-*.json`` forgets it too.
ACCOUNT_FILE = "github-account.json"

NOT_SET_UP = ("Connecting with GitHub isn't set up in this build yet. Use a token instead, or ask whoever made this "
              "build to register its GitHub app.")
DISABLED_WORDS = ("GitHub refused the sign-in: its app has device sign-in turned off. Whoever registered the app turns "
                  "on “Enable Device Flow” in its settings.")
DENIED_WORDS = "You cancelled on GitHub, so nothing was connected."
EXPIRED_WORDS = "The code expired before it was used. Start again for a new one."
FAILED_WORDS = "GitHub did not answer the sign-in; try again in a moment."


def client_id() -> str:
    return (os.environ.get(CLIENT_ID_ENV) or "").strip() or (CLIENT_ID or "").strip()


def app_slug() -> str:
    return (os.environ.get(APP_SLUG_ENV) or "").strip() or (APP_SLUG or "").strip()


def available() -> bool:
    """Whether this build can connect by code: false only when the client id is blank."""
    return bool(client_id())


def install_url() -> str | None:
    slug = app_slug()
    return f"https://github.com/apps/{quote(slug)}/installations/new" if slug else None


def is_app_token() -> bool:
    from api.services.connections import secrets

    return (secrets.load_secrets().get(HOW_ENV) or os.environ.get(HOW_ENV) or "").strip() == HOW_APP


# --- the transport ---------------------------------------------------------------------------------------------------


async def oauth_transport(url: str, form: dict) -> tier2.Response:
    """One ``POST`` to GitHub's sign-in endpoints: those two paths on ``github.com`` only, ``net_guard``'s address
    rule, no redirect, no cookie, 4 s, at most 64 KB read."""
    import httpx

    from api.services import net_guard
    from api.services.connectors import github

    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != OAUTH_HOST \
            or parsed.path not in (DEVICE_CODE_PATH, TOKEN_PATH) or parsed.query:
        raise tier2.base.ConnectorError("GitHub: a sign-in request off its own endpoints was refused")
    headers = {"Accept": "application/json", "User-Agent": "Cicada"}
    async with httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT_SECONDS, transport=github.HTTPX_TRANSPORT,
                                 trust_env=False,
                                 event_hooks={"request": [net_guard.httpx_request_guard]}) as client:
        async with client.stream("POST", url, headers=headers, data=form) as resp:
            chunks, size = [], 0
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise tier2.Refused(FAILED_WORDS, kind="other")
                chunks.append(chunk)
            status = resp.status_code
    try:
        body = json.loads(b"".join(chunks)) if chunks else None
    except ValueError:
        body = None
    return tier2.Response(status, body, {})


#: The suite stands in for the network here (``oauth_transport`` with an ``httpx.MockTransport`` underneath, or a
#: plain fake): ``post(url, form) -> Response``.
POST = oauth_transport


async def _post(path: str, form: dict) -> dict:
    try:
        resp = await POST(f"https://{OAUTH_HOST}{path}", form)
    except tier2.Refused:
        raise
    except Exception as exc:  # noqa: BLE001 — the class only, never the message
        logger.info(f"github: sign-in request failed ({type(exc).__name__})")
        raise tier2.Refused(FAILED_WORDS, kind="network") from exc
    body = resp.body if isinstance(resp.body, dict) else {}
    if resp.status >= 500 or (resp.status >= 400 and not body.get("error")):
        raise tier2.Refused(FAILED_WORDS, kind="other")
    return body


# --- one sign-in, in this process ----------------------------------------------------------------------------------

_pending: dict | None = None


def _now() -> float:
    return time.time()


def pending() -> dict | None:
    """The sign-in under way, as the app may see it (never the device code), or ``None``."""
    if _pending is None:
        return None
    if _now() >= _pending["expires_at"]:
        return None
    return {"user_code": _pending["user_code"], "verification_uri": _pending["verification_uri"],
            "expires_at": int(_pending["expires_at"]), "interval": int(_pending["interval"])}


def cancel() -> None:
    global _pending
    _pending = None


async def start() -> dict:
    """Ask GitHub for a code the person enters at ``github.com/login/device``. Raises :class:`tier2.Refused` (words)."""
    global _pending
    cid = client_id()
    if not cid:
        raise tier2.Refused(NOT_SET_UP, kind="setup")
    body = await _post(DEVICE_CODE_PATH, {"client_id": cid})
    if body.get("error") == "device_flow_disabled":
        raise tier2.Refused(DISABLED_WORDS, kind="setup")
    code, user_code = str(body.get("device_code") or ""), str(body.get("user_code") or "")
    if not code or not user_code or body.get("error"):
        raise tier2.Refused(FAILED_WORDS, kind="other")
    verify = str(body.get("verification_uri") or VERIFY_URL)
    # Only GitHub's own page is ever opened: an answer naming any other address is GitHub's default instead.
    if urlparse(verify).scheme != "https" or (urlparse(verify).hostname or "").lower() != OAUTH_HOST:
        verify = VERIFY_URL
    interval = _int(body.get("interval"), DEFAULT_INTERVAL_S, low=1, high=60)
    _pending = {"device_code": code, "user_code": user_code[:16], "verification_uri": verify,
                "expires_at": _now() + _int(body.get("expires_in"), 900, low=60, high=1800),
                "interval": interval, "next_at": _now() + interval}
    return pending() or {}


def _int(value, default: int, *, low: int, high: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(low, min(n, high))


async def poll() -> dict:
    """One check on the sign-in: ``{state}`` — ``pending`` (ask again after ``interval``), ``connected``, ``denied``,
    ``expired`` or ``none`` (no sign-in under way), with ``words`` when there is something to say. Asks GitHub at
    most once an interval, however often it is called."""
    global _pending
    if _pending is None:
        return {"state": "none"}
    if _now() >= _pending["expires_at"]:
        _pending = None
        return {"state": "expired", "words": EXPIRED_WORDS}
    if _now() < _pending["next_at"]:
        return {"state": "pending", "interval": int(_pending["interval"])}
    _pending["next_at"] = _now() + _pending["interval"]
    body = await _post(TOKEN_PATH, {"client_id": client_id(), "device_code": _pending["device_code"],
                                    "grant_type": DEVICE_GRANT})
    error = str(body.get("error") or "")
    if body.get("access_token") and not error:
        _pending = None
        save(body)
        return {"state": "connected"}
    if error == "authorization_pending":
        return {"state": "pending", "interval": int(_pending["interval"])}
    if error == "slow_down":
        _pending["interval"] = _int(body.get("interval"), int(_pending["interval"]) + 5, low=1, high=120)
        _pending["next_at"] = _now() + _pending["interval"]
        return {"state": "pending", "interval": int(_pending["interval"])}
    _pending = None
    if error == "access_denied":
        return {"state": "denied", "words": DENIED_WORDS}
    if error in ("expired_token", "token_expired"):
        return {"state": "expired", "words": EXPIRED_WORDS}
    if error == "device_flow_disabled":
        return {"state": "error", "words": DISABLED_WORDS}
    logger.info(f"github: sign-in ended ({error or 'no token'})")
    return {"state": "error", "words": FAILED_WORDS}


#: What GitHub answers a refresh whose refresh token is no good any more.
SIGNED_OUT_ERRORS = frozenset({"bad_refresh_token", "unauthorized_client", "incorrect_client_credentials"})
RECONNECT_WORDS = "GitHub signed Cicada out. Connect again to keep your repositories in sync."


def set_reconnect(value: bool) -> None:
    """Mark (or clear) "the sign-in lapsed; connect again", beside the install state outside every bank."""
    data = account()
    if bool(data.get("reconnect")) == value:
        return
    data = {k: v for k, v in data.items() if k != "reconnect"}
    if value:
        data["reconnect"] = True
    _write_account(data)


def needs_reconnect() -> bool:
    return is_app_token() and bool(account().get("reconnect"))


def forget_sign_in() -> None:
    """Everything the code sign-in kept except the token itself: a pasted token now stands alone."""
    from api.services.connections import secrets

    for name in (REFRESH_ENV, EXPIRES_ENV, HOW_ENV):
        secrets.remove_secret(name)
    try:
        _account_path().unlink()
    except OSError:
        pass
    cancel()


def save(body: dict) -> None:
    """Keep what GitHub granted: the token, its refresh token and when it lapses — in ``secrets.env``, never a bank."""
    from api.services.connections import secrets

    secrets.set_secret(TOKEN_ENV, str(body["access_token"]))
    secrets.set_secret(HOW_ENV, HOW_APP)
    if _account_path().exists():
        set_reconnect(False)
    if body.get("refresh_token"):
        secrets.set_secret(REFRESH_ENV, str(body["refresh_token"]))
    else:
        secrets.remove_secret(REFRESH_ENV)
    if body.get("expires_in"):
        secrets.set_secret(EXPIRES_ENV, str(int(_now()) + _int(body.get("expires_in"), 28800, low=60,
                                                                  high=10 ** 8)))
    else:
        secrets.remove_secret(EXPIRES_ENV)


async def fresh_token() -> None:
    """Renew a device-flow token that lapses within :data:`REFRESH_MARGIN_S` (the client id alone, no secret). A
    refusal leaves the old token: the next request is refused in words and the person connects again. Never raises."""
    from api.services.connections import secrets

    if not is_app_token():
        return
    values = secrets.load_secrets()
    refresh, expires = (values.get(REFRESH_ENV) or "").strip(), (values.get(EXPIRES_ENV) or "").strip()
    if not refresh or not expires.isdigit() or int(expires) - REFRESH_MARGIN_S > _now() or not client_id():
        return
    try:
        body = await _post(TOKEN_PATH, {"client_id": client_id(), "grant_type": "refresh_token",
                                        "refresh_token": refresh})
    except tier2.Refused as exc:
        logger.info(f"github: token not renewed ({exc.kind})")
        return
    if body.get("access_token") and not body.get("error"):
        save(body)
        return
    error = str(body.get("error") or "")
    logger.info(f"github: token not renewed ({(error or 'no token')[:40]})")
    if error in SIGNED_OUT_ERRORS:
        # The refresh token itself lapsed (six months) or was revoked: no request can succeed until the person
        # connects again, and the panel says Reconnect rather than Connected.
        set_reconnect(True)


# --- the install step ----------------------------------------------------------------------------------------------


def _account_path() -> Path:
    from api.services.auth import cicada_home

    return cicada_home() / "connectors" / ACCOUNT_FILE


def account() -> dict:
    """``{installed, selection}`` as last checked (``selection``: ``all`` or ``selected`` repositories), or ``{}``."""
    try:
        data = json.loads(_account_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_account(data: dict) -> None:
    path = _account_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


async def check_installation(client: tier2.Client, login: str | None = None) -> dict:
    """Whether the app is installed on the person's own account (``GET /user/installations``, which a user token may
    ask with no permission), kept outside every bank: ``{installed, selection}``. A pasted token sees what it was made
    for, so it never needs one: ``{installed: true}`` without a request."""
    if not is_app_token():
        return {"installed": True, "selection": "token"}
    if login is None:
        me = await client.get("user") or {}
        login = str(me.get("login") or "")
    body = await client.get("user/installations", per_page=100) or {}
    rows = body.get("installations") if isinstance(body, dict) else None
    mine = [r for r in rows or [] if isinstance(r, dict) and isinstance(r.get("account"), dict)
            and str(r["account"].get("login") or "").lower() == login.lower() and login]
    data = {"installed": bool(mine),
            "selection": str(mine[0].get("repository_selection") or "all") if mine else None,
            "checked_at": int(_now())}
    _write_account(data)
    return data


def register_url(*, name: str = "Cicada Memory", homepage: str = "https://cicada.rorosaga.com") -> str:
    """The one-click registration — done once for Cicada's own app (2026-11-04), kept for a fork registering its own:
    GitHub's *Register new GitHub App* form, filled in by URL parameters with :data:`MANIFEST`'s read-only permissions. GitHub's manifest flow says the same thing but needs a
    POST form and a page of Cicada's to receive the result; this is a link. Device sign-in is then one tick in the
    app's settings ("Enable Device Flow"): neither form can set it."""
    params = {"name": name, "description": MANIFEST["description"], "url": homepage, "public": "true",
              "webhook_active": "false", **MANIFEST["default_permissions"]}
    return "https://github.com/settings/apps/new?" + urlencode(params)


#: What the app asks for, in the manifest's own shape (``docs/architecture/network.md`` quotes it): read-only, no
#: webhook, no events, public so anyone running Cicada can install it on their own account. The registered app
#: (``github.com/apps/cicada-memory``) carries exactly these permissions; until its owner makes it public on GitHub,
#: only that account can install it.
MANIFEST: dict = {
    "name": "Cicada Memory",
    "description": "Cicada reads your repositories and the ones you starred, read-only, into your own memory.",
    "url": "https://cicada.rorosaga.com",
    "public": True,
    "hook_attributes": {"url": "https://cicada.rorosaga.com", "active": False},
    "default_events": [],
    "default_permissions": {"metadata": "read", "contents": "read", "starring": "read"},
}
