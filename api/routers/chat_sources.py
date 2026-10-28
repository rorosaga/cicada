"""Chat sources beyond Messages (G179, 2026-10-28) — the routes over :mod:`chat_live`.

* **WhatsApp** (``/sources/whatsapp/*``): the app reads WhatsApp Desktop's store on this Mac from a copy and posts
  ticked chats' rows; the backend parses and stages them (`whatsapp_source`). Never a path, never a file read here.

Every write is demo-gated (409 in the demo bank) and held under the bank's write admission; every tick change is one
``user`` commit of the settings file, every sync one ``capture`` commit scoped to the sittings it wrote.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import CamelModel
from api.routers.capture import refuse_capture_into_demo
from api.services import chat_live, folder_source, sync_state, whatsapp_source, write_admission

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


class WhatsAppConversation(CamelModel):
    id: str = Field(min_length=16, max_length=64)
    name: str | None = Field(None, max_length=200)
    group: bool = False
    members: list[WhatsAppMember] = Field(default_factory=list, max_length=chat_live.MAX_MEMBERS)


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
