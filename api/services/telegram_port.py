"""The one seam between Cicada and Telegram's own client API (ruling 47a, G179, 2026-10-28).

Everything Cicada asks of Telegram goes through :class:`TelegramPort`, in plain values (:class:`TgDialog`,
:class:`TgMessage`, :class:`TgEvent`) — never a library object past this file — so the rest of the backend is tested
against a fake (`api/tests/test_telegram_chats.py`) and never signs in to a real account in a test.

**Why Telethon, not TDLib.** Both are the official MTProto API on the person's own login with Cicada's ``api_id``.
Telethon (MIT, pure Python, 1.45 released 2026-09) installs into the backend's own environment from a hashed wheel on
the Mac and on a Linux server alike, keeps the whole login in one short string (a ``StringSession``) that Cicada
stores 0600 outside every bank, and keeps no message database of its own — what Cicada keeps is only what it stages.
TDLib (Boost licence, Telegram's own C++) is faster at a full sync but ships a native ``libtdjson`` per platform to
sign into the release app, and keeps its own encrypted message database on disk (a second copy of the person's chats
outside the bank, and a database key to custody). At a person's scale — a few ticked chats, live — Telethon's speed is
not the limit; the network is. Telethon v1 only, pinned ``<2`` (v2 is a rewrite).

The real adapter (:class:`TelethonPort`) imports ``telethon`` lazily, the moment the person connects, so an install
that never connects Telegram never loads it and never opens a socket.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable, Protocol


class TelegramError(RuntimeError):
    """A Telegram call that failed, with a sentence the person can read — never the library's message."""


class CodeInvalid(TelegramError):
    pass


class PasswordNeeded(TelegramError):
    """The account has two-step verification: its password is the next step."""


class PasswordInvalid(TelegramError):
    pass


class NotAuthorized(TelegramError):
    """The kept session no longer signs in (ended from Telegram's Active sessions)."""


@dataclass
class TgDialog:
    chat: int                 # Telegram's peer id — hashed before anything is kept
    name: str
    group: bool
    bot: bool | None = None   # a one-to-one chat with a bot
    last: float = 0.0         # unix seconds of the last message
    broadcast: bool = False   # a channel: never listed (nobody's conversation)


@dataclass
class TgMessage:
    id: int
    chat: int
    date: float               # unix seconds
    out: bool                 # sent by the person
    text: str = ""
    sender: int | None = None
    sender_name: str = ""
    sender_bot: bool | None = None
    edited: bool = False
    reply_to: int | None = None
    forward_name: str | None = None
    #: ``{kind, name, size?, mime?}`` — a name and a size, never the file.
    media: dict | None = None
    #: a service message (joined, pinned, renamed) — never a turn.
    service: bool = False
    #: ``[{emoji, from_me, sender?}]`` where Telegram lists who reacted (small chats), else counted without a reactor.
    reactions: list[dict] | None = None


@dataclass
class TgEvent:
    kind: str                 # new | edit | delete | reactions
    chat: int | None = None
    message: TgMessage | None = None
    ids: list[int] = field(default_factory=list)
    reactions: list[dict] | None = None


@dataclass
class TgSentCode:
    """What asking for a login code answers: the hash ``sign_in`` needs and how many digits the code Telegram sent has
    (``sent.type.length``; ``None`` when the delivery kind has no length, e.g. a flash call)."""
    hash: str
    length: int | None = None


@dataclass
class TgQr:
    """A sign-in QR: the ``tg://login`` link the person's phone scans and how long Telegram keeps it (seconds, measured
    on Telegram's clock — a Mac whose clock is off never shortens it). ``signed_in``: asking for a new token found the
    last one already scanned (``auth.loginTokenSuccess``) — the session is live, there is nothing to draw."""
    url: str
    ttl: float
    signed_in: bool = False


class TelegramPort(Protocol):
    async def qr_start(self) -> TgQr: ...
    async def qr_wait(self, timeout: float) -> bool: ...
    async def send_code(self, phone: str) -> TgSentCode | str: ...
    async def sign_in(self, phone: str, code: str, code_hash: str) -> None: ...
    async def sign_in_password(self, password: str) -> None: ...
    async def authorized(self) -> bool: ...
    def session_string(self) -> str: ...
    async def dialogs(self, limit: int) -> list[TgDialog]: ...
    def history(self, chat: int, *, min_id: int = 0, limit: int | None = None) -> AsyncIterator[TgMessage]: ...
    async def listen(self, handler: Callable[[TgEvent], Awaitable[None]]) -> None: ...
    async def log_out(self) -> None: ...
    async def disconnect(self) -> None: ...
    #: chats-ux-v2 — a one-to-one chat's small profile photo (Telegram's own ~160 px JPEG), or None when it has none.
    async def profile_photo(self, chat: int) -> bytes | None: ...


PortFactory = Callable[[int, str, str], TelegramPort]


def load_telethon():
    """Import Telethon, first giving it ``pyaes`` from ``api.vendor`` when no installed one exists — PyPI ships pyaes
    as an sdist only and the release installs wheels only (#504 review B5). ``cryptg`` (a wheel) does the AES when
    installed; pyaes is then only imported, never used."""
    import importlib
    import importlib.util
    import sys

    if "pyaes" not in sys.modules and importlib.util.find_spec("pyaes") is None:
        sys.modules["pyaes"] = importlib.import_module("api.vendor.pyaes")
    return importlib.import_module("telethon")


def _media(message) -> dict | None:
    """A message's attachment as a name and a size — never its bytes, never a path."""
    file = getattr(message, "file", None)
    if getattr(message, "media", None) is None or file is None:
        return None
    if getattr(message, "geo", None) is not None or getattr(message, "venue", None) is not None:
        return {"kind": "location"}
    if getattr(message, "contact", None) is not None:
        return {"kind": "contact"}
    mime = str(getattr(file, "mime_type", "") or "")
    kind = "sticker" if getattr(message, "sticker", None) is not None else (
        "image" if getattr(message, "photo", None) is not None else "")
    entry = {"kind": kind, "name": str(getattr(file, "name", "") or ""), "mime": mime}
    size = getattr(file, "size", None)
    if isinstance(size, int) and size > 0:
        entry["size"] = size
    return entry


def _reactions(message, me: int | None) -> list[dict] | None:
    block = getattr(message, "reactions", None)
    if block is None:
        return None
    out: list[dict] = []
    for recent in getattr(block, "recent_reactions", None) or []:
        emoji = getattr(getattr(recent, "reaction", None), "emoticon", None)
        peer = getattr(getattr(recent, "peer_id", None), "user_id", None)
        if emoji:
            out.append({"emoji": str(emoji), "from_me": bool(getattr(recent, "my", False)) or (peer is not None
                                                                                            and peer == me),
                        "sender": peer})
    return out


def device_label() -> tuple[str, str, str]:
    """``(device_model, system_version, app_version)`` — what Telegram → Settings → Devices shows for this session:
    "Cicada", the OS family (never the Mac's name, never a serial) and Cicada's version. Honest and nothing more."""
    import platform
    from pathlib import Path

    system = {"Darwin": "macOS"}.get(platform.system(), platform.system() or "")
    try:
        version = (Path(__file__).resolve().parents[2] / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        version = ""
    return "Cicada", system, version or "cicada"


class TelethonPort:  # pragma: no cover — the real network adapter; every caller is tested against a fake
    def __init__(self, api_id: int, api_hash: str, session: str = ""):
        load_telethon()
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        model, system, version = device_label()
        self._client = TelegramClient(StringSession(session or None), api_id, api_hash,
                                      device_model=model, app_version=version, system_version=system,
                                      receive_updates=True)
        self._me: int | None = None
        self._phone: str | None = None
        self._qr = None

    async def qr_start(self) -> TgQr:
        """``auth.exportLoginToken`` (Telethon's ``qr_login``): a fresh token, or a new one for the same login. A scan
        that landed between two tokens answers ``loginTokenSuccess`` (or a DC move to import it) instead of a token:
        that is a signed-in session, finished here like ``QRLogin.wait`` does."""
        import time

        from telethon import errors, functions, types

        await self._connect()
        if self._qr is None:
            from telethon.tl.custom.qrlogin import QRLogin

            self._qr = QRLogin(self._client, [])
        try:
            resp = await self._client(self._qr._request)
            if isinstance(resp, types.auth.LoginTokenMigrateTo):
                await self._client._switch_dc(resp.dc_id)
                resp = await self._client(functions.auth.ImportLoginTokenRequest(resp.token))
        except errors.SessionPasswordNeededError as exc:
            raise PasswordNeeded("This account has two-step verification: enter its password.") from exc
        except errors.FloodWaitError as exc:
            raise TelegramError(f"Telegram asked to wait {exc.seconds} seconds before another code.") from exc
        if isinstance(resp, types.auth.LoginTokenSuccess):
            await self._client._on_login(resp.authorization.user)
            return TgQr(url="", ttl=0.0, signed_in=True)
        self._qr._resp = resp
        offset = getattr(getattr(self._client._sender, "_state", None), "time_offset", 0) or 0
        return TgQr(url=self._qr.url, ttl=self._qr.expires.timestamp() - (time.time() + offset))

    async def qr_wait(self, timeout: float) -> bool:
        """``True`` once the person's phone accepted the QR; ``False`` when it expired unscanned. A two-step account
        raises :class:`PasswordNeeded` — its password is the one thing still typed."""
        from telethon import errors

        try:
            await self._qr.wait(timeout=timeout)
        except asyncio.TimeoutError:
            return False
        except errors.SessionPasswordNeededError as exc:
            raise PasswordNeeded("This account has two-step verification: enter its password.") from exc
        return True

    async def _connect(self) -> None:
        if not self._client.is_connected():
            await self._client.connect()

    async def send_code(self, phone: str) -> str:
        from telethon import errors

        await self._connect()
        try:
            sent = await self._client.send_code_request(phone)
        except errors.PhoneNumberInvalidError as exc:
            raise TelegramError("Telegram didn't accept that phone number.") from exc
        except errors.FloodWaitError as exc:
            raise TelegramError(f"Telegram asked to wait {exc.seconds} seconds before another code.") from exc
        self._phone = phone
        length = getattr(getattr(sent, "type", None), "length", None)
        return TgSentCode(hash=sent.phone_code_hash, length=length if isinstance(length, int) and length > 0 else None)

    async def sign_in(self, phone: str, code: str, code_hash: str) -> None:
        from telethon import errors

        await self._connect()
        try:
            await self._client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
        except errors.SessionPasswordNeededError as exc:
            raise PasswordNeeded("This account has two-step verification: enter its password.") from exc
        except (errors.PhoneCodeInvalidError, errors.PhoneCodeExpiredError) as exc:
            raise CodeInvalid("That code didn't work — ask Telegram for a new one.") from exc

    async def sign_in_password(self, password: str) -> None:
        from telethon import errors

        await self._connect()
        try:
            await self._client.sign_in(password=password)
        except errors.PasswordHashInvalidError as exc:
            raise PasswordInvalid("That password didn't work.") from exc

    async def authorized(self) -> bool:
        await self._connect()
        ok = await self._client.is_user_authorized()
        if ok and self._me is None:
            self._me = (await self._client.get_me(input_peer=True)).user_id
        return ok

    def session_string(self) -> str:
        return self._client.session.save()

    async def dialogs(self, limit: int) -> list[TgDialog]:
        await self._connect()
        out = []
        async for d in self._client.iter_dialogs(limit=limit):
            entity = d.entity
            out.append(TgDialog(chat=d.id, name=d.name or "", group=bool(d.is_group),
                                bot=bool(getattr(entity, "bot", False)) if d.is_user else None,
                                last=d.date.timestamp() if d.date else 0.0, broadcast=bool(d.is_channel and not d.is_group)))
        return out

    async def history(self, chat: int, *, min_id: int = 0, limit: int | None = None) -> AsyncIterator[TgMessage]:
        await self._connect()
        async for m in self._client.iter_messages(chat, min_id=min_id, limit=limit, reverse=True):
            yield await self._message(m)

    async def _message(self, m) -> TgMessage:
        sender = getattr(m, "sender", None)
        if sender is None and not m.out:
            try:
                sender = await m.get_sender()
            except Exception:  # noqa: BLE001 — an unknown sender is a member with no name
                sender = None
        name = " ".join(x for x in (getattr(sender, "first_name", None), getattr(sender, "last_name", None)) if x)
        forward = getattr(m, "forward", None)
        forward_name = (getattr(forward, "from_name", None) or (getattr(getattr(forward, "sender", None), "first_name",
                                                                        None) if forward else None)) if forward else None
        return TgMessage(id=m.id, chat=m.chat_id, date=m.date.timestamp(), out=bool(m.out), text=m.message or "",
                         sender=m.sender_id, sender_name=name or getattr(sender, "title", "") or "",
                         sender_bot=getattr(sender, "bot", None), edited=m.edit_date is not None,
                         reply_to=getattr(m, "reply_to_msg_id", None),
                         forward_name=(forward_name or ("someone" if forward else None)), media=_media(m),
                         service=m.action is not None, reactions=_reactions(m, self._me))

    async def listen(self, handler: Callable[[TgEvent], Awaitable[None]]) -> None:
        from telethon import events, types

        await self._connect()

        async def on_new(event):
            await handler(TgEvent("new", event.chat_id, await self._message(event.message)))

        async def on_edit(event):
            await handler(TgEvent("edit", event.chat_id, await self._message(event.message)))

        async def on_delete(event):
            await handler(TgEvent("delete", event.chat_id, ids=list(event.deleted_ids or [])))

        async def on_raw(update):
            if isinstance(update, types.UpdateMessageReactions):
                from telethon import utils

                fake = type("R", (), {"reactions": update.reactions})()
                await handler(TgEvent("reactions", utils.get_peer_id(update.peer), ids=[update.msg_id],
                                      reactions=_reactions(fake, self._me) or []))

        self._client.add_event_handler(on_new, events.NewMessage())
        self._client.add_event_handler(on_edit, events.MessageEdited())
        self._client.add_event_handler(on_delete, events.MessageDeleted())
        self._client.add_event_handler(on_raw, events.Raw())
        await self._client.run_until_disconnected()

    async def log_out(self) -> None:
        await self._connect()
        await self._client.log_out()

    async def profile_photo(self, chat: int) -> bytes | None:
        """The chat's small profile photo, in memory (``file=bytes``), from Telegram itself — nothing else is asked."""
        await self._connect()
        data = await self._client.download_profile_photo(chat, file=bytes, download_big=False)
        return bytes(data) if data else None

    async def disconnect(self) -> None:
        result = self._client.disconnect()
        if asyncio.iscoroutine(result):
            await result


def telethon_factory(api_id: int, api_hash: str, session: str) -> TelegramPort:  # pragma: no cover
    return TelethonPort(api_id, api_hash, session)
