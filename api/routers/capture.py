"""Inbound capture connectors — webhooks that stage episodes/media without
going through MCP or the companion app's own upload flow.

Currently just Telegram. The parse+route logic lives in
``api/services/telegram_capture.py``; this router is only the token gate +
HTTP surface.
"""

from fastapi import APIRouter, Depends, HTTPException

from api.config import Settings, get_settings
from api.services.telegram_capture import ingest_telegram_update

router = APIRouter()


@router.post("/capture/telegram")
async def capture_telegram(update: dict, settings: Settings = Depends(get_settings)):
    """Telegram Bot API webhook target.

    To activate:

    1. Create a bot via `@BotFather` on Telegram (`/newbot`), copy the token
       it gives you.
    2. Set ``CICADA_TELEGRAM_BOT_TOKEN=<token>`` (e.g. in ``api/.env``) and
       restart the backend — until it's set this endpoint always 503s.
    3. Point that bot's webhook at this endpoint (needs a public HTTPS URL
       reaching this backend, e.g. a tunnel — Cicada does not manage the
       tunnel or poll Telegram itself, only this webhook receiver):

       ``curl "https://api.telegram.org/bot<token>/setWebhook?url=<your-public-url>/capture/telegram"``

    Then forward or send any message to the bot: a message containing a URL
    is saved as media (``origin: telegram``); anything else is staged as an
    episode (``origin: telegram``, ``processed: false``) for the next Sleep
    cycle.
    """
    if not settings.telegram_enabled:
        raise HTTPException(status_code=503, detail="telegram not configured")

    return await ingest_telegram_update(settings.memory_path, update)
