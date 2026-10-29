"""WhatsApp and Telegram chats the person ticks (G179, 2026-10-28) — the routes over :mod:`chat_live`.

* **WhatsApp** (``/sources/whatsapp/*``): the app reads WhatsApp Desktop's store on this Mac from a copy and posts
  ticked chats' rows; the backend parses and stages them (`whatsapp_source`). Never a path, never a file read here.
* **Telegram** (``/sources/telegram/*``): the backend's own client on the person's own account (ruling 47a,
  `telegram_account`): connect (a QR scanned in Telegram on the phone — the default, owner 2026-10-29 —
  or number → code; a two-step password either way), the tick list (one-to-one chats only), a tick
  that carries the person's confirmation that the other person agreed (ruling 47a amendment, owner 2026-10-28),
  history on ask, disconnect.

Every write is demo-gated (409 in the demo bank) and held under the bank's write admission; every tick change is one
``user`` commit of the settings file, every sync one ``capture`` commit scoped to the sittings it wrote.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import CamelModel
from api.routers.capture import refuse_capture_into_demo
from api.services import (chat_live, folder_source, sync_state, telegram_account, telegram_source, whatsapp_source,
                          write_admission)
from api.services.telegram_port import TelegramError

router = APIRouter()
_DEMO_GATE = [Depends(refuse_capture_into_demo)]


# --- Shapes ----------------------------------------------------------------------------------------------------------


class ChatMark(CamelModel):
    kind: str | None = None


class ChatConversationUpdate(CamelModel):
    id: str = Field(min_length=16, max_length=64)
    name: str | None = Field(None, max_length=200)
    group: bool | None = None
    ticked: bool | None = None
    #: The person's ask: read this chat's history, back to the first message the source holds.
    history: bool | None = None
    actor: ChatMark | None = None
    clear_actor: bool = False
    #: Telegram only (ruling 47a amendment): the person confirms the other person agreed that Cicada's AI reads it.
    consent: bool | None = None


class ChatSettingsUpdate(CamelModel):
    conversation: ChatConversationUpdate


class ChatConversationState(CamelModel):
    id: str
    ticked: bool = False
    group: bool = False
    history: bool = False
    reads_from: str | None = None
    marked: dict | None = None


class ChatSettingsResponse(CamelModel):
    conversations: list[ChatConversationState] = []


class ChatListed(CamelModel):
    id: str = Field(min_length=16, max_length=64)
    group: bool = False


class ChatDescribeRequest(CamelModel):
    conversations: list[ChatListed] = Field(default_factory=list, max_length=2000)


class WhatsAppMember(CamelModel):
    key: str = Field(min_length=16, max_length=64)
    name: str | None = Field(None, max_length=200)
    #: The member's ONE address-book card, by its Contacts id — never a JID or a number (`contact_identity`).
    contact: str | None = Field(None, max_length=200)


class WhatsAppConversation(CamelModel):
    id: str = Field(min_length=16, max_length=64)
    name: str | None = Field(None, max_length=200)
    group: bool = False
    members: list[WhatsAppMember] = Field(default_factory=list, max_length=chat_live.MAX_MEMBERS)
    #: A one-to-one chat's other side: their ONE address-book card, by its Contacts id.
    contact: str | None = Field(None, max_length=200)


class WhatsAppMedia(CamelModel):
    title: str | None = Field(None, max_length=400)
    file: str | None = Field(None, max_length=400)
    size: int | None = None


class WhatsAppRow(CamelModel):
    rowid: int | None = None
    stanza: str = Field(max_length=128)
    date: float
    from_me: bool = False
    text: str | None = Field(None, max_length=65536)
    type: int = 0
    member: str | None = Field(None, max_length=64)
    metadata: str | None = Field(None, max_length=16384)
    media: WhatsAppMedia | None = None
    edited: bool = False


class WhatsAppReaction(CamelModel):
    target: str = Field(max_length=128)
    date: float
    from_me: bool = False
    member: str | None = Field(None, max_length=64)
    emoji: str = Field("", max_length=32)


class WhatsAppSyncRequest(CamelModel):
    conversation: WhatsAppConversation
    messages: list[WhatsAppRow] = []
    reactions: list[WhatsAppReaction] = []


class ChatSyncResponse(CamelModel):
    conversation: str = ""
    messages_seen: int = 0
    kept: int = 0
    unsent: int = 0
    edited: int = 0
    replies: int = 0
    attachments: int = 0
    forwards: int = 0
    reactions: int = 0
    reactions_kept: int = 0
    reactions_orphaned: int = 0
    before_start: int = 0
    sittings: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    tombstoned: int = 0
    recorded: int = 0
    group: bool = False
    bank: str = ""


class ChatWaitingItem(CamelModel):
    conversation: str
    name: str = ""
    group: bool = False
    messages: int = 0
    sittings: int = 0


class ChatWaitingResponse(CamelModel):
    conversations: list[ChatWaitingItem] = []
    messages: int = 0


class TelegramStatus(CamelModel):
    state: str
    consent: str
    consent_ask: str = ""
    credentials: str | None = None
    error: str | None = None
    listening: bool = False
    #: While ``state == "qr"``: the ``tg://login`` link the app draws as a QR, and when Telegram expires it (ISO).
    qr_url: str | None = None
    qr_expires: str | None = None


class TelegramPhone(CamelModel):
    phone: str = Field(min_length=4, max_length=32)


class TelegramCode(CamelModel):
    code: str = Field(min_length=3, max_length=16)


class TelegramPassword(CamelModel):
    password: str = Field(min_length=1, max_length=256)


class TelegramChat(CamelModel):
    id: str
    name: str = ""
    group: bool = False
    bot: bool | None = None
    last: str | None = None
    ticked: bool = False
    history: bool = False
    #: When the person confirmed the other person agreed (ruling 47a amendment), else ``None``.
    consented_at: str | None = None


class TelegramChatsResponse(CamelModel):
    chats: list[TelegramChat] = []


# --- Shared ----------------------------------------------------------------------------------------------------------


def _settings_response(memory_path, spec) -> ChatSettingsResponse:
    data = chat_live.load_settings(memory_path, spec)["conversations"]
    return ChatSettingsResponse(conversations=[
        ChatConversationState(id=cid, ticked=c["ticked"], group=c["group"], history=c["reads_from"] == chat_live.EPOCH,
                              reads_from=c["reads_from"], marked=c["actor"]) for cid, c in data.items()])


async def _update(memory_path, spec, req: ChatSettingsUpdate) -> ChatSettingsResponse:
    c = req.conversation
    conversation = {"id": c.id, "name": c.name, "group": c.group, "ticked": c.ticked, "history": c.history}
    if c.clear_actor:
        conversation["actor"] = None
    elif c.actor is not None:
        conversation["actor"] = c.actor.model_dump(by_alias=False)
    try:
        await run_in_threadpool(chat_live.update_settings, memory_path, spec, conversation)
    except chat_live.NotSelected as exc:
        raise HTTPException(409, str(exc))
    except chat_live.PayloadError as exc:
        raise HTTPException(422, str(exc))
    await folder_source.commit_paths_for(memory_path, [f"sources/{spec.settings_filename}"],
                                         subject=f"{spec.label} settings", trigger="user/companion_app",
                                         channel=spec.channel)
    return _settings_response(memory_path, spec)


def _waiting(memory_path, spec) -> ChatWaitingResponse:
    rows = chat_live.waiting(memory_path, spec)
    return ChatWaitingResponse(conversations=rows, messages=sum(r["messages"] for r in rows))


# --- WhatsApp --------------------------------------------------------------------------------------------------------


@router.get("/sources/whatsapp/settings", response_model=ChatSettingsResponse)
async def get_whatsapp_settings(settings: Settings = Depends(get_settings)):
    return _settings_response(settings.memory_path, whatsapp_source.SPEC)


@router.put("/sources/whatsapp/settings", response_model=ChatSettingsResponse, dependencies=_DEMO_GATE)
@write_admission.route()
async def put_whatsapp_settings(req: ChatSettingsUpdate, settings: Settings = Depends(get_settings)):
    """Tick or untick a chat (live from now), ask for its history, or mark who a one-to-one chat is with. Unticking
    keeps every saved sitting. One ``user`` commit of the settings file."""
    return await _update(settings.memory_path, whatsapp_source.SPEC, req)


@router.post("/sources/whatsapp/conversations", response_model=ChatSettingsResponse, dependencies=_DEMO_GATE)
async def describe_whatsapp(req: ChatDescribeRequest, settings: Settings = Depends(get_settings)):
    """The tick list's backend half: the person's tick for each chat the app listed. Computes only."""
    out = chat_live.describe(settings.memory_path, whatsapp_source.SPEC,
                             [c.model_dump(by_alias=False) for c in req.conversations])
    return ChatSettingsResponse(conversations=out)


@router.post("/sources/whatsapp/sync", response_model=ChatSyncResponse, dependencies=_DEMO_GATE)
@write_admission.route()   # held, never refused: capture is never gated (G183)
async def sync_whatsapp(req: WhatsAppSyncRequest, settings: Settings = Depends(get_settings)):
    """Stage rows of one ticked WhatsApp chat. 409 for a chat not ticked, 422 for a payload the backend cannot trust,
    413 above the per-request cap. One ``capture`` commit scoped to the sittings written."""
    memory_path = settings.memory_path
    if len(req.messages) + len(req.reactions) > chat_live.MAX_MESSAGES_PER_REQUEST:
        raise HTTPException(413, f"at most {chat_live.MAX_MESSAGES_PER_REQUEST} rows per request")
    try:
        out = await run_in_threadpool(whatsapp_source.ingest, memory_path, req.model_dump(by_alias=False),
                                      bank=memory_path.name)
    except chat_live.NotSelected as exc:
        raise HTTPException(409, str(exc))
    except chat_live.PayloadError as exc:
        raise HTTPException(422, str(exc))
    sync_state.record_sync(memory_path, whatsapp_source.SPEC.channel,
                           count=chat_live.live_count(memory_path, whatsapp_source.SPEC))
    await folder_source.commit_paths_for(memory_path, out.pop("paths"), subject="WhatsApp sync",
                                         trigger="capture/whatsapp", channel=whatsapp_source.SPEC.channel)
    return ChatSyncResponse(**out, bank=memory_path.name)


@router.get("/sources/whatsapp/waiting", response_model=ChatWaitingResponse)
async def whatsapp_waiting(settings: Settings = Depends(get_settings)):
    return await run_in_threadpool(_waiting, settings.memory_path, whatsapp_source.SPEC)


# --- Telegram --------------------------------------------------------------------------------------------------------


def _telegram_error(exc: TelegramError) -> HTTPException:
    return HTTPException(422, str(exc))


@router.get("/sources/telegram/status", response_model=TelegramStatus)
async def telegram_status():
    """Whether Telegram is connected, the consent sentence the connect step shows, and whose app id is in use."""
    return TelegramStatus(**telegram_account.ACCOUNT.status())


@router.post("/sources/telegram/qr", response_model=TelegramStatus, dependencies=_DEMO_GATE)
async def telegram_qr():
    """The default connect (owner 2026-10-29): a QR the person scans in Telegram on their phone (Settings → Devices →
    Link Desktop Device). Answers ``state: qr`` with the link to draw; status polls show each refreshed QR, then
    ``connected`` — or ``password`` for a two-step account. Calling it again shows a new QR."""
    try:
        return TelegramStatus(**await telegram_account.ACCOUNT.start_qr())
    except TelegramError as exc:
        raise _telegram_error(exc)


@router.post("/sources/telegram/connect", response_model=TelegramStatus, dependencies=_DEMO_GATE)
async def telegram_connect(req: TelegramPhone):
    """Step 1: Telegram sends a code to the person's own Telegram app. The number is passed on, never stored."""
    try:
        return TelegramStatus(**await telegram_account.ACCOUNT.send_code(req.phone))
    except TelegramError as exc:
        raise _telegram_error(exc)


@router.post("/sources/telegram/code", response_model=TelegramStatus, dependencies=_DEMO_GATE)
async def telegram_code(req: TelegramCode):
    """Step 2: the code. A two-step-verification account answers ``state: password``."""
    try:
        return TelegramStatus(**await telegram_account.ACCOUNT.submit_code(req.code))
    except TelegramError as exc:
        raise _telegram_error(exc)


@router.post("/sources/telegram/password", response_model=TelegramStatus, dependencies=_DEMO_GATE)
async def telegram_password(req: TelegramPassword):
    try:
        return TelegramStatus(**await telegram_account.ACCOUNT.submit_password(req.password))
    except TelegramError as exc:
        raise _telegram_error(exc)


@router.post("/sources/telegram/disconnect", response_model=TelegramStatus)
async def telegram_disconnect():
    """Log the session out at Telegram and forget it here. Every saved sitting stays. Mid sign-in (a QR on screen, a
    code or password asked) it only stops the sign-in: nothing was signed in, so nothing is logged out."""
    return TelegramStatus(**await telegram_account.ACCOUNT.disconnect())


@router.get("/sources/telegram/chats", response_model=TelegramChatsResponse)
async def telegram_chats(settings: Settings = Depends(get_settings)):
    """The tick list: the person's chats as Telegram lists them (names only, channels left out), with their ticks.
    Computes only — nothing about an unticked chat is kept."""
    try:
        rows = await telegram_account.ACCOUNT.chats()
    except TelegramError as exc:
        raise HTTPException(409, str(exc))
    states = chat_live.load_settings(settings.memory_path, telegram_source.SPEC)["conversations"]
    given = telegram_account.consents()
    return TelegramChatsResponse(chats=[
        TelegramChat(**r, ticked=bool((states.get(r["id"]) or {}).get("ticked")) and r["id"] in given,
                     history=(states.get(r["id"]) or {}).get("reads_from") == chat_live.EPOCH,
                     consented_at=(given.get(r["id"]) or {}).get("at")) for r in rows])


@router.get("/sources/telegram/settings", response_model=ChatSettingsResponse)
async def get_telegram_settings(settings: Settings = Depends(get_settings)):
    return _settings_response(settings.memory_path, telegram_source.SPEC)


@router.put("/sources/telegram/settings", response_model=ChatSettingsResponse, dependencies=_DEMO_GATE)
@write_admission.route()
async def put_telegram_settings(req: ChatSettingsUpdate, background: BackgroundTasks,
                                settings: Settings = Depends(get_settings)):
    """Tick or untick a one-to-one chat (live from now), or ask for its history — read in the background from
    Telegram, back to the first message it holds (at most ``HISTORY_CAP``). Ruling 47a amendment: a group is refused
    (422); a tick needs ``consent: true``, the person's confirmation that the other person agreed (409 without), kept
    with its date outside the bank; unticking withdraws it."""
    c = req.conversation
    if c.group:
        raise HTTPException(422, "Telegram group chats aren't read: Telegram's terms need every member's consent.")
    if (c.ticked is True or c.history) and not await telegram_account.ACCOUNT.one_to_one(c.id):
        # Decided from Telegram's own peer, never the client's flag (#504 review B4): only a one-to-one chat with a
        # user that Telegram lists to this account can be ticked or read.
        raise HTTPException(422, "Only a one-to-one Telegram chat with a person can be read — Telegram doesn't list "
                                 "this one as that (connect first if Telegram isn't connected).")
    if c.ticked is True and c.consent is not True:
        raise HTTPException(409, "Confirm that the other person agreed before ticking this chat.")
    if c.history and c.id not in telegram_account.consents():
        raise HTTPException(409, "Tick this chat, with the other person's consent, before reading its history.")
    out = await _update(settings.memory_path, telegram_source.SPEC, req)
    if c.ticked is True:
        telegram_account.set_consent(c.id, True)
    elif c.ticked is False or c.consent is False:
        telegram_account.set_consent(c.id, False)
    if req.conversation.history:
        background.add_task(_read_history, req.conversation.id)
    return out


async def _read_history(cid: str) -> None:
    from loguru import logger

    try:
        await telegram_account.ACCOUNT.read(cid)
    except Exception as exc:  # noqa: BLE001 — the row shows the error; nothing half-written stays unstaged
        logger.warning(f"telegram: history read failed ({type(exc).__name__})")


@router.get("/sources/telegram/waiting", response_model=ChatWaitingResponse)
async def telegram_waiting(settings: Settings = Depends(get_settings)):
    return await run_in_threadpool(_waiting, settings.memory_path, telegram_source.SPEC)
