"""Inbound capture connectors — webhooks that stage episodes/media without
going through MCP or the companion app's own upload flow.

Two today: the Telegram webhook (parse+route logic in
``api/services/telegram_capture.py``; this router is only the token gate +
HTTP surface) and the G105 session-capture endpoint the harness's Stop hook
posts to (``api/services/transcript_capture.py`` does the validation, the
extraction and the write).
"""

import asyncio
import os
import secrets as _secrets_mod
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from loguru import logger
from pydantic import BaseModel

from api.config import Settings, get_settings
from api.services import telemetry
from api.services.telegram_capture import (
    TELEGRAM_WEBHOOK_SECRET_ENV,
    ensure_webhook_secret,
    ingest_telegram_update,
)
from api.services.transcript_capture import capture_transcript

router = APIRouter()

# "attempt once" — this endpoint is hit on every message forwarded to the
# bot; an unconfigured secret must not retry auto-provisioning (or spam a
# fallback warning) on every single request.
_attempted_webhook_secret_setup = False


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
    3. Point that bot's webhook at this endpoint (needs a public HTTPS URL
       reaching this backend, e.g. a tunnel — Cicada does not manage the
       tunnel or poll Telegram itself, only this webhook receiver):

       ``curl "https://api.telegram.org/bot<token>/setWebhook?url=<your-public-url>/capture/telegram"``

    That's it — **the secure path is automatic (G57), not opt-in.** The
    first request that arrives with no ``CICADA_TELEGRAM_WEBHOOK_SECRET``
    configured triggers ``telegram_capture.ensure_webhook_secret``: it
    generates a random secret, asks Telegram (via ``getWebhookInfo``) what
    URL is currently registered, and RE-registers that same URL with the new
    ``secret_token`` via ``setWebhook`` — from the NEXT request on, every
    call is verified against Telegram's ``X-Telegram-Bot-Api-Secret-Token``
    header (constant-time compare) and rejected with 403 otherwise. Only on
    success is the secret persisted; this is the only unauthenticated write
    path into memory (Telegram's own servers can't send our bearer header),
    so "bot token configured" alone was never proof the caller really is
    Telegram. If auto-provisioning fails for any reason (no webhook
    registered yet, no network, a Telegram API error), the endpoint falls
    back to today's behavior — gated only by the bot token being configured
    — with a loud one-time warning naming the risk, so a working bot is
    never locked out by this.

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
        # No secret configured yet — try ONCE to make the secure path the
        # default automatically (G57 / Devin PR #24 finding 5) rather than
        # silently keeping an unauthenticated endpoint as the happy path.
        # Either way, THIS request (which necessarily predates any
        # provisioning that just happened — Telegram doesn't know about the
        # secret yet for a call already in flight) is still processed
        # normally: enforcement begins on the next request, so a working bot
        # is never locked out mid-conversation.
        global _attempted_webhook_secret_setup
        if not _attempted_webhook_secret_setup:
            _attempted_webhook_secret_setup = True
            provisioned, detail = await ensure_webhook_secret(settings.telegram_bot_token)
            if provisioned:
                logger.info(
                    f"Auto-provisioned {TELEGRAM_WEBHOOK_SECRET_ENV} and registered it with "
                    "Telegram's setWebhook — every request from here on is verified."
                )
            else:
                logger.warning(
                    f"POST /capture/telegram has no {TELEGRAM_WEBHOOK_SECRET_ENV} configured, "
                    f"and auto-provisioning it failed ({detail}) — any caller who can reach "
                    "this URL can write to memory until a secret_token is registered."
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


class TranscriptCaptureRequest(BaseModel):
    """What the Stop hook forwards — the harness's own stdin fields, nothing
    computed client-side. Snake_case on purpose: the sender is a stdlib
    script, not the app."""

    harness: Literal["claude-code", "codex"]
    session_id: str
    transcript_path: str
    cwd: str | None = None
    hook_event: str | None = None


@router.post("/capture/transcript")
async def capture_transcript_endpoint(
    req: TranscriptCaptureRequest,
    settings: Settings = Depends(get_settings),
):
    """G105: deterministic session capture from the harness's Stop hook.

    Bearer-authed like every other write path — the hook reads
    ``~/.cicada/api_token`` (the file the app and MCP server already use), so
    nothing is added to ``auth._STATIC_OPEN_PATHS``. The backend, not the
    hook, opens the transcript (R2): the path is validated against the
    harness root before a byte is read, and a refusal is a 400 carrying the
    enum reason plus a ledger row, never a partial write. One episode per
    session, updated in place on every later firing (R3); ``status`` says
    which of ``created | updated | unchanged | empty`` happened. Runs the
    read + parse off the event loop — an 85 MB transcript takes real time
    and must not stall SSE or the app.
    """
    result = await asyncio.to_thread(
        capture_transcript,
        settings.memory_path,
        harness=req.harness,
        session_id=req.session_id,
        transcript_path=req.transcript_path,
        cwd=req.cwd,
        keep_assistant=settings.capture_assistant_replies,
        bank=telemetry.bank_name(settings),
    )
    if result.status == "refused":
        raise HTTPException(status_code=400, detail=result.reason)
    return {
        "status": result.status,
        "episodeId": result.episode_id,
        "turnsUser": result.turns_user,
        "turnsAssistant": result.turns_assistant,
        "summary": result.summary,
    }
