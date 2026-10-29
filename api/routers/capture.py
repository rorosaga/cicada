"""Inbound capture connectors — webhooks that stage episodes/media without
going through MCP or the companion app's own upload flow.

Four today: the Telegram webhook (parse+route logic in
``api/services/telegram_capture.py``; this router is only the token gate +
HTTP surface), the G105 session-capture endpoint the harness's Stop hook
posts to (``api/services/transcript_capture.py`` does the validation, the
extraction and the write), the per-turn capture endpoint Cursor's and Gemini
CLI's hooks post to (``POST /capture/turn``, ``api/services/turn_capture.py``),
and the G149 recall hooks' read,
``POST /capture/hook-context`` (``api/services/hook_recall.py``).
"""

import asyncio
import os
import secrets as _secrets_mod
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from loguru import logger
from pydantic import BaseModel, Field, model_validator

from api.config import Settings, get_settings
from api.services import (
    agent_memory_notes, awake_read, bank_registry, continuity_sessions, demo_guard, episode_ids, harness_integrations,
    hook_recall, write_admission,
)
from api.services.telegram_capture import (
    TELEGRAM_WEBHOOK_SECRET_ENV,
    ensure_webhook_secret,
    ingest_telegram_update,
)
from api.services import turn_capture as turn_capture_mod
from api.services.transcript_capture import capture_posted, capture_transcript

router = APIRouter()


def refuse_capture_into_demo(settings: Settings = Depends(get_settings)) -> None:
    """G141 capture-side track (R-CS15): a route dependency that answers ``409``
    with :data:`demo_guard.REFUSAL` while the ACTIVE bank is a demo bank.

    Route-level, so FastAPI solves it before the body is validated and before
    the handler runs (checked on 0.135.3): FastAPI has already read the body,
    but a folder batch or an upload is refused before any of it is staged.
    Every POST/PUT under ``/capture/`` and ``/sources/`` carries it unless
    ``test_demo_capture_routes.HANDLED_ELSEWHERE`` names why not — the Stop
    hook redirects, Telegram replies, the intake checks its target bank."""
    if demo_guard.is_demo(settings.memory_path):
        raise HTTPException(status_code=409, detail=demo_guard.REFUSAL)


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


#: How long a session-capture route waits for its writer before it answers ``202 accepted`` and lets the write finish
#: on its own (2026-10-29). The Stop hook gives up after ``TIMEOUT_S`` (3 s); a capture is usually done in well under a
#: second, but a long transcript read while other sessions, a notes sweep or Sleep share the process took 3-9 s, and
#: the hook then logged an error for a capture that landed a moment later. The writer is the same either way — same
#: lock, same find-or-create, same refusals — only the answer stops waiting for it.
CAPTURE_ANSWER_S = 2.0
#: Writes that outlived their answer, held so the event loop keeps a reference until they finish.
_LATE_WRITES: set = set()


async def answer_within(work, landed, budget: float | None = None):
    """Run ``work`` (blocking) off the event loop; its result when it finishes within ``budget`` seconds, else ``None``
    — and then, when it does finish, ``landed(result)`` runs on the loop for a write that was not refused (the step a
    route takes after a write: the awake read's queue). Never cancels the write: a request the client dropped still
    finishes, and so does one that answered ``accepted``."""
    budget = CAPTURE_ANSWER_S if budget is None else budget
    task = asyncio.ensure_future(asyncio.to_thread(work))

    def late(t: asyncio.Task) -> None:
        _LATE_WRITES.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.warning(f"capture: a write that answered accepted failed: {type(exc).__name__}")
            return
        result = t.result()
        if result.status == "refused":
            logger.info(f"capture: a write that answered accepted was refused: {result.reason}")
            return
        try:
            landed(result)
        except Exception as e:  # noqa: BLE001 - the write is done; what follows it never takes it back
            logger.warning(f"capture: after a late write: {type(e).__name__}")

    try:
        done, _ = await asyncio.wait({task}, timeout=budget)
    except asyncio.CancelledError:
        _LATE_WRITES.add(task)
        task.add_done_callback(late)
        raise
    if task in done:
        return task.result()
    _LATE_WRITES.add(task)
    task.add_done_callback(late)
    return None


def _after_write(memory_path, target, req, settings):
    """What a session-capture route does once its writer returned a write that was not refused — at once, or later
    for one that answered ``accepted``: name a demo redirect in the log and queue the awake read."""
    def landed(result) -> None:
        if target is not None and target.redirected_from:
            logger.info(f"capture: the demo bank is open — saved the {req.harness} session into '{target.name}'")
        awake_read.after_capture(memory_path, result.episode_id, status=result.status, settings=settings,
                                 hook_event=req.hook_event)
    return landed


def accepted(*, bank: str | None, redirected_from: str | None, bank_id: str | None = None):
    """``202``: the capture is being written and was not done within :data:`CAPTURE_ANSWER_S`. Nothing is lost by not
    waiting — the next Stop re-sends the whole session and is idempotent."""
    from fastapi.responses import JSONResponse

    body = {"status": "accepted", "episodeId": None, "turnsUser": None, "turnsAssistant": None, "summary": None,
            "bank": bank, "redirectedFrom": redirected_from}
    if bank_id is not None:
        body["bankId"] = bank_id
    return JSONResponse(status_code=202, content=body)


class TranscriptCaptureRequest(BaseModel):
    """What the Stop hook forwards — harness stdin plus D2's git observation.
    Snake_case on purpose: the sender is a stdlib
    script, not the app."""

    harness: Literal["claude-code", "codex"]
    session_id: str
    transcript_path: str
    cwd: str | None = None
    # Stop, or a PreCompact/SessionEnd flush (G110 gate A); free text on the
    # wire (never refused: a capture must not fail on it), an enum in the ledger.
    hook_event: str | None = None
    # Round 4 C1: the Stop hook's `effort.level` for the reply it fired after —
    # validated by the capture writer (`agent_turns.clean_effort`), unknown dropped.
    effort: str | None = Field(default=None, max_length=32)
    # D2: plain hook-observed git values; only parsed/hashed, never opened.
    workspace: Any = None
    # G228, additive: the app that launched the harness (T3 Code), read by the hook from its own ancestors. Free text
    # on the wire — an unknown value is dropped by the writer, never a refused capture.
    host: str | None = Field(default=None, max_length=32)


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
    which of ``created | updated | unchanged | metadata | superseded | empty`` happened. Runs the
    read + parse off the event loop — an 85 MB transcript takes real time
    and must not stall SSE or the app.

    G141 capture-side track (R-CS12): the demo bank is never the target. While
    it is open, the session is saved into the real bank left most recently
    (``bank_registry.capture_bank``) and the response names it — ``bank`` and
    ``redirectedFrom`` — so the hook's log says where it went; with no real
    bank to choose, ``409`` and nothing is read. Every Stop re-captures the
    whole session, so the first reply after switching back saves it in full.
    """
    target = bank_registry.capture_bank(settings.memory_root)
    # No real bank to fall back to: the service is handed the demo path and
    # refuses it unread, so the refusal lands in the ledger like any other.
    memory_path = target.path if target is not None else settings.memory_path
    def _capture():
        return capture_transcript(
            memory_path,
            harness=req.harness,
            session_id=req.session_id,
            transcript_path=req.transcript_path,
            cwd=req.cwd,
            keep_assistant=settings.capture_assistant_replies,
            bank=memory_path.name,
            effort=req.effort,
            hook_event=req.hook_event,
            workspace=req.workspace,
            host=req.host,
            # G110: the continuity registry's every-bank guard needs the root and
            # every configured bank — resolved once, off the event loop.
            bank_paths=continuity_sessions.bank_paths_for(settings.memory_root),
        )

    _landed = _after_write(memory_path, target, req, settings)
    result = await answer_within(_capture, _landed)
    if result is None:
        return accepted(bank=target.name if target is not None else None,
                        redirected_from=target.redirected_from if target is not None else None)
    if target is None or result.status == "refused":
        if target is None or result.reason == "demo_bank":
            raise HTTPException(status_code=409, detail=demo_guard.HOOK_REFUSAL)
        raise HTTPException(status_code=400, detail=result.reason)
    _landed(result)
    return {
        "status": result.status,
        "episodeId": result.episode_id,
        "turnsUser": result.turns_user,
        "turnsAssistant": result.turns_assistant,
        "summary": result.summary,
        "bank": target.name,
        "redirectedFrom": target.redirected_from,
    }


class SessionCaptureRequest(BaseModel):
    """A harness session read on the machine where it lives, by Cicada's own extractor (G181 phase 2, owner ruling
    2): what the extractor kept, never a path. Snake_case: the sender is the Stop hook."""

    harness: Literal["claude-code", "codex"]
    session_id: str = Field(..., min_length=1, max_length=200)
    conversation: dict
    transcript_bytes: int = Field(..., ge=0)
    transcript_size: int = Field(..., ge=0)
    cwd: str | None = Field(None, max_length=4096)
    hook_event: str | None = Field(None, max_length=64)
    effort: str | None = Field(default=None, max_length=32)
    workspace: Any = None
    #: Ruling 34 (2026-10-22), additive: the client's UTC offset in minutes at the conversation's first turn (east
    #: positive), so a new episode's id carries the person's day, not this server's. Absent: this server's zone.
    utc_offset_minutes: int | None = Field(None, ge=-episode_ids.MAX_UTC_OFFSET_MINUTES,
                                           le=episode_ids.MAX_UTC_OFFSET_MINUTES)
    #: G202 (D1), additive: a spooled resend names the bank it was captured for (the ``bankId`` an earlier answer
    #: gave); when no bank of this server's memory has that id it is refused (409 ``bank_mismatch``) and the client
    #: holds it for its own memory. Absent (every live post): filed where a capture goes now, as before.
    bank_id: str | None = Field(None, max_length=128)
    #: G228, additive: the app that launched the harness on the client (an unknown value is dropped).
    host: str | None = Field(None, max_length=32)


def _filed_in(settings: Settings, target, claimed: str | None) -> str | None:
    """The id of the bank a capture is filed in (the demo redirect counts: the id is the bank written).

    A resend names the bank its client last heard this address file in (G202, D1). It is refused —
    ``bank_binding.BankMismatch``, 409 ``bank_mismatch``, nothing read or written — only when that id is no bank of
    this server's memory: the address now leads to another memory. A bank switch on this server is the person's own
    move, and the resend is filed where a live capture of the same session goes now, so a session is never split
    between the bank it started in and the one it continues in (G104; review of #408)."""
    from api.services import bank_binding

    filed = bank_registry.bank_id(settings.memory_root, target.name) if target is not None else None
    if claimed and claimed != filed and claimed not in bank_registry.bank_ids(settings.memory_root):
        raise bank_binding.BankMismatch()
    return filed

@router.post("/capture/session")
async def capture_session_endpoint(req: SessionCaptureRequest, request: Request,
                                   settings: Settings = Depends(get_settings)):
    """G181 phase 2: a Claude Code or Codex session from another machine. The transcript was read there, by Cicada's
    own extractor (the transcript rail, amended by owner ruling 2, 2026-10-16); the backend opens nothing, re-checks
    what arrived and writes it with ``/capture/transcript``'s writer (``transcript_capture.capture_posted``): one
    episode per session, ids minted here, the same demo redirect and answers. The device that signed the post
    (its token, ``request.state.device``) is recorded on the episode."""
    target = bank_registry.capture_bank(settings.memory_root)
    filed = _filed_in(settings, target, req.bank_id)
    memory_path = target.path if target is not None else settings.memory_path
    device = getattr(request.state, "device", None)

    def _capture():
        return capture_posted(
            memory_path, harness=req.harness, session_id=req.session_id, conversation=req.conversation,
            transcript_bytes=req.transcript_bytes, transcript_size=req.transcript_size, cwd=req.cwd,
            keep_assistant=settings.capture_assistant_replies, bank=memory_path.name, effort=req.effort,
            hook_event=req.hook_event, workspace=req.workspace,
            bank_paths=continuity_sessions.bank_paths_for(settings.memory_root),
            device=device.id if device is not None else None, utc_offset_minutes=req.utc_offset_minutes,
            host=req.host)

    _landed = _after_write(memory_path, target, req, settings)
    result = await answer_within(_capture, _landed)
    if result is None:
        return accepted(bank=target.name if target is not None else None, bank_id=filed,
                        redirected_from=target.redirected_from if target is not None else None)
    if target is None or result.status == "refused":
        if target is None or result.reason == "demo_bank":
            raise HTTPException(status_code=409, detail=demo_guard.HOOK_REFUSAL)
        raise HTTPException(status_code=400, detail=result.reason)
    _landed(result)
    return {"status": result.status, "episodeId": result.episode_id, "turnsUser": result.turns_user,
            "turnsAssistant": result.turns_assistant, "summary": result.summary, "bank": target.name,
            "bankId": filed, "redirectedFrom": target.redirected_from}


class PostedTurn(BaseModel):
    speaker: Literal["user", "assistant"]
    # The hook trims to this before posting; the writer keeps ≤16k/≤2k after cleaning.
    text: str = Field(..., max_length=turn_capture_mod.TEXT_MAX_CHARS)


class TurnCaptureRequest(BaseModel):
    """What a per-turn capture hook forwards (Cursor's ``beforeSubmitPrompt`` /
    ``afterAgentResponse``, Gemini CLI's ``AfterAgent``): the turn's own words
    from the harness's stdin, never a path. Snake_case: the sender is a stdlib
    script."""

    harness: Literal[*turn_capture_mod.HARNESSES]
    session_id: str = Field(..., min_length=1, max_length=200)
    messages: list[PostedTurn] = Field(..., min_length=1, max_length=2)
    turn_id: str | None = Field(None, max_length=128)
    retry: bool = False
    model: str | None = Field(None, max_length=200)
    cwd: str | None = Field(None, max_length=4096)
    hook_event: str | None = Field(None, max_length=64)
    #: Ruling 34 (2026-10-22), additive: the client's UTC offset in minutes at the conversation's first turn (east
    #: positive), so a new episode's id carries the person's day, not this server's. Absent: this server's zone.
    utc_offset_minutes: int | None = Field(None, ge=-episode_ids.MAX_UTC_OFFSET_MINUTES,
                                           le=episode_ids.MAX_UTC_OFFSET_MINUTES)
    #: G202 (D1), additive: a spooled resend names the bank it was captured for (the ``bankId`` an earlier answer
    #: gave); when no bank of this server's memory has that id it is refused (409 ``bank_mismatch``) and the client
    #: holds it for its own memory. Absent (every live post): filed where a capture goes now, as before.
    bank_id: str | None = Field(None, max_length=128)
    #: G228, additive: the app that launched the harness (T3 Code driving Cursor); an unknown value is dropped.
    host: str | None = Field(None, max_length=32)


@router.post("/capture/turn")
async def capture_turn_endpoint(req: TurnCaptureRequest, request: Request,
                                settings: Settings = Depends(get_settings)):
    """Capture-everywhere: a harness whose hook carries each turn's text (Cursor,
    Gemini CLI) instead of a transcript path. Bearer-authed like
    ``/capture/transcript``, the same one-episode-per-session write
    (``turn_capture``), and the same demo rule: while the demo bank is open the
    turn is saved into the real bank left most recently and the response names
    it; with no real bank, ``409`` and nothing is written."""
    target = bank_registry.capture_bank(settings.memory_root)
    filed = _filed_in(settings, target, req.bank_id)
    memory_path = target.path if target is not None else settings.memory_path

    def _capture():
        return turn_capture_mod.capture_turns(
            memory_path, harness=req.harness, session_id=req.session_id,
            turns=[turn_capture_mod.Posted(t.speaker, t.text) for t in req.messages],
            turn_id=req.turn_id, retry=req.retry, model=req.model, cwd=req.cwd,
            keep_assistant=settings.capture_assistant_replies, bank=memory_path.name,
            bank_paths=continuity_sessions.bank_paths_for(settings.memory_root), hook_event=req.hook_event,
            utc_offset_minutes=req.utc_offset_minutes, host=req.host,
            device=getattr(getattr(request.state, "device", None), "id", None))

    result = await asyncio.to_thread(_capture)
    if target is None or result.status == "refused":
        if target is None or result.reason == "demo_bank":
            raise HTTPException(status_code=409, detail=demo_guard.HOOK_REFUSAL)
        raise HTTPException(status_code=400, detail=result.reason)
    if target.redirected_from:
        logger.info(f"capture: the demo bank is open — saved the {req.harness} turn into '{target.name}'")
    awake_read.after_capture(memory_path, result.episode_id, status=result.status, settings=settings,
                             hook_event=req.hook_event)
    return {"status": result.status, "episodeId": result.episode_id, "turnsUser": result.turns_user,
            "turnsAssistant": result.turns_assistant, "bank": target.name, "bankId": filed,
            "redirectedFrom": target.redirected_from}


class HookContextRequest(BaseModel):
    """What the recall hook forwards (G149): the harness's own stdin fields.
    Snake_case like ``TranscriptCaptureRequest``, because the sender is a stdlib
    script. The prompt rides in this JSON body and nowhere else, never a query
    string, so uvicorn's access line can never hold it (G136 R22, R-H1).

    G110 slice 1a: ``cwd`` is now the folder a continuity block is matched on —
    an exact string, never logged, never stored (the registry keeps its hash).
    ``source`` is the harness's SessionStart kind; it is ``Any`` so a value a
    newer harness invents still answers 200 (normalized in the handler)."""

    event: Literal["session_start", "user_prompt_submit"]
    harness: Literal[*continuity_sessions.HARNESSES]
    session_id: str = Field(..., min_length=1, max_length=200)
    cwd: str | None = Field(None, max_length=4096)
    prompt: str | None = Field(None, max_length=hook_recall.PROMPT_MAX_CHARS)
    model: str | None = Field(None, max_length=200)
    source: Any = None
    workspace: Any = None

    @model_validator(mode="after")
    def supported_event(self):
        adapter = harness_integrations.LOCAL.get(self.harness)
        if adapter and self.event not in adapter.EVENTS:
            raise ValueError("Event unsupported by this startup integration")
        return self


@router.post("/capture/hook-context")
async def hook_context_endpoint(req: HookContextRequest, settings: Settings = Depends(get_settings)):
    """G149: what a harness's SessionStart / UserPromptSubmit hook puts in front
    of the model. Engine-free and read-only; ``additionalContext: null`` when
    there is nothing worth saying, so a miss costs zero tokens.

    Bearer-authed like ``/capture/transcript``. Never gated by
    ``refuse_capture_into_demo``: it writes nothing, and it reads the bank a
    capture would write into (``bank_registry.capture_bank``), the real bank
    left most recently while the demo is open, nothing when there is none
    (R-H16). The work runs off the event loop under a hard budget, 300 ms for a
    prompt and 800 ms for the primer; past it the answer is ``timeout`` with no
    note (R-H6). The session's window is updated only when an answer actually
    came back (R-H7). Nothing here logs the prompt: a failure is logged by its
    class name alone (K9, R-H10)."""
    started = time.perf_counter()
    arrived = episode_ids.utc_now_iso()   # G110: the event's own time, before any work
    source = req.source if isinstance(req.source, str) and req.source in hook_recall.SESSION_SOURCES else None
    budget = hook_recall.PRIMER_BUDGET_S if req.event == "session_start" else hook_recall.PROMPT_BUDGET_S
    deadline = time.monotonic() + budget
    bank = None
    try:
        result, bank = await asyncio.wait_for(asyncio.to_thread(
            hook_recall.respond, settings.memory_root, event=req.event, harness=req.harness,
            session_id=req.session_id, prompt=req.prompt or "", deadline=deadline, cwd=req.cwd, source=source,
            start=arrived, workspace=req.workspace), timeout=budget)
        if req.event == "user_prompt_submit":
            hook_recall.RECENT.remember(req.session_id, result.injected)
    except TimeoutError:
        result = hook_recall.Injection.none("timeout")
    except Exception as exc:  # noqa: BLE001 — K9: the class, never the message or a traceback
        logger.warning(f"hook-context: failed ({type(exc).__name__})")
        result = hook_recall.Injection.none("error")
    latency_ms = int((time.perf_counter() - started) * 1000)
    hook_recall.record(req.event, req.harness, result, latency_ms=latency_ms, model=req.model, bank=bank)
    return {"additionalContext": result.text, "injected": list(result.injected),
            "reason": result.reason, "latencyMs": latency_ms}


# ── Ruling 43 (owner 2026-10-27): an agent's own memory notes ──────────────────────────────────────────────────────
# The harness's hook reads `~/.claude/projects/*/memory/*.md` on the machine where they live and posts their bytes;
# the backend opens nothing (`agent_memory_notes`). One switch per memory, on by default.


class AgentMemoryNote(BaseModel):
    project: str = Field(..., min_length=1, max_length=255)
    file: str = Field(..., min_length=1, max_length=255)
    text: str = Field(..., max_length=agent_memory_notes.MAX_NOTE_CHARS)
    #: The file's modification time, aware ISO-8601 — the note's own date when its head names none.
    modified_at: str | None = Field(None, max_length=64)


class AgentMemoryRequest(BaseModel):
    """Every note under the harness root, read by its hook. Snake_case: the sender is a stdlib script."""

    harness: Literal[*agent_memory_notes.HARNESSES]
    notes: list[AgentMemoryNote] = Field(..., max_length=agent_memory_notes.MAX_NOTES)
    #: True when ``notes`` is everything the root holds — only then is a note missing from it tombstoned.
    complete: bool = False


class AgentMemorySettings(BaseModel):
    enabled: bool


@router.get("/capture/agent-memory/settings", response_model=AgentMemorySettings)
async def get_agent_memory_settings(settings: Settings = Depends(get_settings)):
    return AgentMemorySettings(**agent_memory_notes.load_settings(settings.memory_path))


@router.put("/capture/agent-memory/settings", response_model=AgentMemorySettings,
            dependencies=[Depends(refuse_capture_into_demo)])
@write_admission.route()
async def put_agent_memory_settings(req: AgentMemorySettings, settings: Settings = Depends(get_settings)):
    from api.services import folder_source

    saved = agent_memory_notes.save_settings(settings.memory_path, enabled=req.enabled)
    await folder_source.commit_paths_for(
        settings.memory_path, [f"sources/{agent_memory_notes.SETTINGS_FILENAME}"],
        subject="Agent memory notes setting", trigger="user/companion_app")
    return AgentMemorySettings(**saved)


@router.post("/capture/agent-memory", dependencies=[Depends(refuse_capture_into_demo)])
@write_admission.route()   # held, never refused: notes stage while Sleep runs, as a session does
async def capture_agent_memory(req: AgentMemoryRequest, request: Request, settings: Settings = Depends(get_settings)):
    """Ruling 43: one episode per note, the agent's words (``evidence_kind: assistant``), dated when the note was last
    written; an edit updates in place, a note gone from a complete post is tombstoned. ``{"status": "off"}`` when the
    person turned the source off for this memory — nothing is read. 409 in a demo bank. The device that signed the
    post files its own notes, so two machines never tombstone each other's."""
    from api.services import folder_source

    memory_path = settings.memory_path
    if not agent_memory_notes.load_settings(memory_path)["enabled"]:
        return {"status": "off", "bank": memory_path.name}
    device = getattr(request.state, "device", None)
    report = await asyncio.to_thread(
        agent_memory_notes.ingest, memory_path, [n.model_dump() for n in req.notes], harness=req.harness,
        device=device.id if device is not None else None, complete=req.complete)
    paths = report.pop("paths")
    if paths:
        await folder_source.commit_paths_for(memory_path, paths, subject="Agent memory notes",
                                             trigger="capture/agent_memory", author=req.harness)
    return {"status": "ok", "bank": memory_path.name, **report}


# ── G212 (owner 2026-10-22): a paired phone's captures ─────────────────────────────────────────────────────────────
# A phone paired as `capture` (`device_tokens.KINDS`) reaches only `/sources/save` (a link and its note), the note and
# file routes below, and its own recent captures (`auth.CAPTURE_ROUTES`). The writes take any token; the list is a
# device's.


NOTE_MAX_CHARS = 16_000
MINE_LIMIT = 20
MINE_SCAN = 500


class NoteCaptureRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=NOTE_MAX_CHARS)
    title: str | None = Field(None, max_length=200)
    #: The client's own id for this note. A resend with the same id (or the same ``Idempotency-Key``) is the same note:
    #: one episode, staged by ``source_id``. With neither, the words themselves are the identity (the same words twice
    #: are kept once).
    id: str | None = Field(None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    #: G91 (ruling 38): ``voice`` when the person spoke the note and their phone transcribed it on the device (no audio
    #: is ever sent); recorded as ``note_kind: voice`` so a reader knows the words are a transcript. ``text`` (the
    #: default) records nothing, so a typed note's episode is unchanged.
    kind: Literal["text", "voice"] = "text"


@router.post("/capture/note", dependencies=[Depends(refuse_capture_into_demo)])
async def capture_note(req: NoteCaptureRequest, request: Request, settings: Settings = Depends(get_settings)):
    """A thought the person typed or shared on another of their devices: **their own words** (a ``user:`` turn, never
    an agent's ``origin: mcp``), one episode per note, scrubbed and staged like every source-keyed writer
    (``episode_staging``), queued for Sleep. Capture (Awake): no Sleep gate, no model. The device that sent it is
    stamped by ``device_context``; a capture-only phone's note is ``origin: phone``, any other ``origin: note``.
    ``Idempotency-Key`` makes a resend the first answer (``idempotency``)."""
    import hashlib
    from datetime import datetime, timezone
    from pathlib import Path

    from api.services import episode_staging, idempotency, when as when_mod

    if not req.text.strip():
        raise HTTPException(status_code=400, detail="The note is empty.")
    device = getattr(request.state, "device", None)
    who = device.id if device is not None else "server"
    key = idempotency.clean_key(request.headers.get(idempotency.HEADER))
    ident = req.id or (hashlib.sha256(key.encode()).hexdigest()[:24] if key else
                       "words-" + hashlib.sha256(req.text.strip().encode()).hexdigest()[:24])
    memory_path = Path(settings.memory_path)

    async def work():
        now = datetime.now(timezone.utc)
        instant = when_mod.utc_z(now)
        origin = "phone" if device is not None and device.kind == "capture" else "note"
        draft = episode_staging.EpisodeDraft(
            title=(req.title or "").strip() or ("Voice note" if req.kind == "voice" else "Note"), source_id=f"note:{who}:{ident}", timestamp=instant,
            original_date=now.date().isoformat(), source=origin, origin=origin,
            turns=[episode_staging.Turn(text=req.text, speaker="user", ts=instant)], writer="note",
            extra={"note_kind": "voice"} if req.kind == "voice" else {})
        result = await asyncio.to_thread(
            lambda: episode_staging.stage([draft], memory_path / "episodes", bank=memory_path.name))
        status = "created" if result.created else ("updated" if result.updated else "unchanged")
        return 200, {"status": status, "episodeId": result.episode_ids.get(draft.source_id)}

    _, body, _ = await idempotency.run_once(idempotency.scope_of(request), "/capture/note", key, work)
    return body


@router.post("/capture/file", dependencies=[Depends(refuse_capture_into_demo)])
async def capture_file(
    request: Request,
    file: UploadFile = File(...),
    caption: str | None = Form(None, max_length=16_000),
    title: str | None = Form(None, max_length=200),
    id: str | None = Form(None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$"),
    settings: Settings = Depends(get_settings),
):
    """A photo (JPEG, PNG, HEIC), a PDF or a plain-text file the person shared from another of their devices, with an
    optional caption in **their own words** (G91, ruling 38). Multipart: ``file``, ``caption?``, ``title?``, ``id?``.

    The bytes are kept outside every bank, content-addressed (``capture_files``: ``$CICADA_HOME/files/<bank>/``) and
    never served back; the bank gets one episode — a ``user:`` turn with the caption and the file's name, plus a plain
    text file's words — staged like every source-keyed capture (``episode_staging``: scrub, one id rule, queued for
    Sleep). The type is read from the bytes, never the client's word (415 otherwise); past 25 MB is 413. Capture
    (Awake): no Sleep gate, no model reads the file. ``device`` stamped; ``origin: phone`` from a capture-only phone,
    ``device-file`` from any other token. Identity: ``id``, else the ``Idempotency-Key``, else the file's own bytes
    (the same file twice is kept once); ``Idempotency-Key`` makes a resend the first answer."""
    import hashlib
    from datetime import datetime, timezone
    from pathlib import Path

    from api.services import capture_files, episode_staging, idempotency, when as when_mod

    data = await file.read(capture_files.MAX_BYTES + 1)
    try:
        accepted = capture_files.accept(data, file.content_type, file.filename)
    except capture_files.Refused as refused:
        raise HTTPException(status_code=refused.status, detail=str(refused)) from None
    name = capture_files.clean_name(file.filename, accepted)
    device = getattr(request.state, "device", None)
    who = device.id if device is not None else "server"
    key = idempotency.clean_key(request.headers.get(idempotency.HEADER))
    ident = id or (hashlib.sha256(key.encode()).hexdigest()[:24] if key else "bytes-" + accepted.sha256[:24])
    memory_path = Path(settings.memory_path)
    file_record = capture_files.record(accepted, name)

    async def work():
        now = datetime.now(timezone.utc)
        instant = when_mod.utc_z(now)
        origin = "phone" if device is not None and device.kind == "capture" else "device-file"
        texts = capture_files.turn_texts(accepted, name, caption)
        attachment = {"kind": accepted.kind, "name": name, "size": accepted.size, "mime": accepted.mime}
        turns = [episode_staging.Turn(text=texts[0], speaker="user", ts=instant, extras={"attachments": [attachment]})]
        turns += [episode_staging.Turn(text=t, speaker="user", ts=instant) for t in texts[1:]]
        draft = episode_staging.EpisodeDraft(
            title=(title or "").strip() or capture_files.default_title(accepted, name),
            source_id=f"file:{who}:{ident}", timestamp=instant, original_date=now.date().isoformat(),
            source=origin, origin=origin, turns=turns, writer="file", extra={"file": file_record})

        def write():
            capture_files.keep(memory_path, data, accepted)   # the bytes first: an episode never names a missing file
            return episode_staging.stage([draft], memory_path / "episodes", bank=memory_path.name)

        result = await asyncio.to_thread(write)
        status = "created" if result.created else ("updated" if result.updated else "unchanged")
        return 200, {"status": status, "episodeId": result.episode_ids.get(draft.source_id),
                     "file": {"kind": file_record["kind"], "size": accepted.size, "sha256": accepted.sha256}}

    _, body, _ = await idempotency.run_once(idempotency.scope_of(request), "/capture/file", key, work)
    return body


@router.get("/capture/mine")
async def my_captures(request: Request, settings: Settings = Depends(get_settings)):
    """The newest captures the asking device sent (at most 20 of the newest 500 episodes): ids, titles, times,
    whether Sleep has read each, and a saved link's URL — never another device's, never the body. A device token
    only: the server's own token has no captures of its own here."""
    from pathlib import Path

    from api.services import markdown_parser

    device = getattr(request.state, "device", None)
    if device is None:
        raise HTTPException(status_code=400, detail="Only a device's own token has captures to list.")
    episodes_dir = Path(settings.memory_path) / "episodes"

    def scan() -> list[dict]:
        files = sorted(episodes_dir.glob("ep_*.md"), key=lambda p: p.name, reverse=True)[:MINE_SCAN]
        mine: list[dict] = []
        for path in files:
            try:
                fm = markdown_parser.parse(path).frontmatter or {}
            except Exception:  # noqa: BLE001 — one unreadable file never hides the rest
                continue
            if fm.get("device") != device.id:
                continue
            mine.append({"id": fm.get("id") or path.stem, "title": fm.get("title"),
                         "timestamp": str(fm.get("timestamp") or ""), "processed": bool(fm.get("processed")),
                         "url": fm.get("url") or fm.get("source_url")})
            if len(mine) >= MINE_LIMIT:
                break
        mine.sort(key=lambda e: e["timestamp"], reverse=True)
        return mine

    return {"captures": await asyncio.to_thread(scan)}
