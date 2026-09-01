"""Inbound capture connectors — webhooks that stage episodes/media without
going through MCP or the companion app's own upload flow.

Currently just Telegram. The parse+route logic lives in
``api/services/telegram_capture.py``; this router is only the token gate +
HTTP surface.
"""

import os
import secrets as _secrets_mod

from fastapi import APIRouter, Depends, Header, HTTPException
from loguru import logger

from api.config import Settings, get_settings
from api.services.telegram_capture import ingest_telegram_update

router = APIRouter()

# G57 / Wave-1 1.5: the webhook secret Telegram is asked to echo back on every
# request (``setWebhook?secret_token=...``), stored in the same
# ``~/.cicada/secrets.env`` seam as every other Cicada-held credential
# (``api.services.connections.secrets``) — never through ``Settings``, which
# is constructed (and cached) BEFORE that seam is projected into
# ``os.environ`` at lifespan startup, so a value living only in secrets.env
# would never be visible through a Settings field.
TELEGRAM_WEBHOOK_SECRET_ENV = "CICADA_TELEGRAM_WEBHOOK_SECRET"

# "log once" — this endpoint is hit on every message forwarded to the bot;
# an unconfigured secret must not spam a warning on every single request.
_warned_unauthenticated = False


def _configured_webhook_secret() -> str:
    return (os.environ.get(TELEGRAM_WEBHOOK_SECRET_ENV) or "").strip()


@router.post("/capture/telegram")
async def capture_telegram(
    update: dict,
    settings: Settings = Depends(get_settings),
    x_telegram_bot_api_secret_token: str | None = Header(
        default=None, alias="X-Telegram-Bot-Api-Secret-Token"
    ),
):
    """Telegram Bot API webhook target.

    To activate:

    1. Create a bot via `@BotFather` on Telegram (`/newbot`), copy the token
       it gives you.
    2. Set ``CICADA_TELEGRAM_BOT_TOKEN=<token>`` (e.g. in ``api/.env``) and
       restart the backend — until it's set this endpoint always 503s.
    3. (Recommended, G57) Generate a random secret and store it in the
       existing secrets seam, e.g.::

           python -c "import secrets; print(secrets.token_urlsafe(32))"
           # then, from a Python shell with the backend's venv:
           # api.services.connections.secrets.set_secret("CICADA_TELEGRAM_WEBHOOK_SECRET", "<value>")

       Once set, every request is verified against Telegram's
       ``X-Telegram-Bot-Api-Secret-Token`` header (constant-time compare) and
       rejected with 403 otherwise — this is the only unauthenticated write
       path into memory (Telegram's own servers can't send our bearer
       header), and without a secret_token it is gated only by the bot token
       being *configured*, not by proof the caller really is Telegram.
    4. Point that bot's webhook at this endpoint (needs a public HTTPS URL
       reaching this backend, e.g. a tunnel — Cicada does not manage the
       tunnel or poll Telegram itself, only this webhook receiver), passing
       the SAME secret as ``secret_token`` if you generated one above:

       ``curl "https://api.telegram.org/bot<token>/setWebhook?url=<your-public-url>/capture/telegram&secret_token=<value>"``

    Then forward or send any message to the bot: a message containing a URL
    is saved as media (``origin: telegram``); anything else is staged as an
    episode (``origin: telegram``, ``processed: false``) for the next Sleep
    cycle.

    The response doubles as the bot's reply: when there is something to
    acknowledge it carries ``method: sendMessage`` so Telegram echoes
    "Saved with note: …" back into the chat.
    """
    if not settings.telegram_enabled:
        raise HTTPException(status_code=503, detail="telegram not configured")

    configured_secret = _configured_webhook_secret()
    if configured_secret:
        supplied = (x_telegram_bot_api_secret_token or "").strip()
        if not supplied or not _secrets_mod.compare_digest(
            supplied.encode("utf-8"), configured_secret.encode("utf-8")
        ):
            raise HTTPException(status_code=403, detail="invalid telegram webhook secret")
    else:
        # No secret configured — keep today's behavior (gated only by the bot
        # token being configured) so an already-working bot is never locked
        # out by this fix, but say so once so the gap is visible rather than
        # silent (G57).
        global _warned_unauthenticated
        if not _warned_unauthenticated:
            _warned_unauthenticated = True
            logger.warning(
                f"POST /capture/telegram has no {TELEGRAM_WEBHOOK_SECRET_ENV} configured — "
                "any caller who can reach this URL can write to memory. Set a secret_token on "
                f"setWebhook and store it as {TELEGRAM_WEBHOOK_SECRET_ENV} to close this."
            )

    result = await ingest_telegram_update(settings.memory_path, update)

    # Telegram executes a `method` returned in the webhook RESPONSE body, so the
    # bot can answer without an outgoing HTTP call and without the bot token
    # ever entering this process's request path (G71 §1).
    ack = result.get("ack")
    chat_id = result.get("chat_id")
    if ack and chat_id is not None:
        return {**result, "method": "sendMessage", "chat_id": chat_id, "text": ack}
    return result
