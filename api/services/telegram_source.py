"""Telegram chats the person ticks, on their own account through Telegram's official client API (ruling 47a, G179).

The owner, 2026-10-28: live tracking of Telegram "like we do with messages plus a historical if I want". The Mac app's
own store is encrypted and is not reversed; Cicada signs in as the person instead
(:mod:`telegram_account` holds the session, :mod:`telegram_port` the client) — ruling 47a, the one dated case where
Cicada keeps a signed-in session of a person's account, for ingestion only. This module turns what the client reads
into :class:`chat_live.ChatMessage` and stages it through :mod:`chat_live`, under the same rails as every chat source:
ticked chats only, live from the tick, a chat's history only on the person's ask, one episode per sitting, scrubbed, no
model.

**One-to-one chats only, each with the other person's consent (ruling 47a amendment, owner 2026-10-28).** Telegram's
terms forbid using "data obtained from its platform to … engage in the … deployment of artificial intelligence" except
"where all relevant users individually provide explicit, informed, affirmative and continued consent … strictly limited
to the specific content and chat" (telegram.org/tos/content-licensing; API Terms §1.5). Sleep reads a sitting with a
model, so: a group or a channel is never listed and never staged (:func:`listed`, :func:`ingest`), and a one-to-one
chat is staged only while the person's own dated confirmation that the other person agreed is kept
(`telegram_account.consents`) — given per chat when ticking, withdrawn by unticking. The person is responsible for that
consent; Cicada cannot verify it, and says so where it asks.

**Ids.** A conversation id is ``hash("telegram", <peer id>)`` and a participant key ``hash("telegram", <peer id>,
<user id>)`` — never Telegram's ids themselves in the bank, and a member's key never links two chats by itself. A
message key is ``hash(<conversation>, <message id>)``.

**Who is who.** Telegram STATES whether an account is a bot: a one-to-one chat with a bot is an agent's (``assistant:``
turns, G179's texted-agent rule), with anyone else a person's (``speaker:<name>:``, decided by the source); in a group
a single bot member is ``assistant`` and every other member speaks as themselves. The person's own messages (``out``)
are ``user:`` — their words. A forwarded message keeps the name Telegram shows for its origin (``forwarded_from``).
"""

from __future__ import annotations

from api.services import chat_live, turn_extras
from api.services.chat_live import ChatMessage, ChatSpec
from api.services.telegram_port import TgDialog, TgMessage

SPEC = ChatSpec(channel="telegram-chats", origin="telegram-chats", label="Telegram",
                settings_filename="telegram.json", writer="telegram-chats")


def conversation_id(chat: int) -> str:
    return chat_live.hash_id("telegram", str(int(chat)))


def member_key(chat: int, user: int) -> str:
    return chat_live.hash_id("telegram", str(int(chat)), str(int(user)))


def message_key(cid: str, message_id: int) -> str:
    return chat_live.hash_id(cid, str(int(message_id)), length=12)


class NotOneToOne(PermissionError):
    """A group or a channel: never read (ruling 47a amendment)."""


class NoConsent(PermissionError):
    """A one-to-one chat with no kept confirmation that the other person agreed."""


def is_user_peer(chat) -> bool:
    """Telegram's own answer to "one-to-one?": a chat's marked peer id is a user's (positive) — a basic group's is
    negative and a channel's or supergroup's is ``-100…``. Decided from the peer, never from a flag a client sent
    (#504 review B4)."""
    try:
        return int(chat) > 0
    except (TypeError, ValueError):
        return False


def listed(dialog: TgDialog) -> dict | None:
    """A dialog as the tick list shows it — ``None`` for a group or a channel: never offered (ruling 47a amendment)."""
    if dialog.broadcast or dialog.group or not is_user_peer(dialog.chat):
        return None
    return {"id": conversation_id(dialog.chat), "name": chat_live.messages_source._clean_name(dialog.name),
            "group": bool(dialog.group), "bot": dialog.bot, "last": chat_live.utc_from_unix(dialog.last),
            "own": bool(dialog.is_self)}


def _file(media: dict) -> tuple[dict | None, str]:
    kind = str(media.get("kind") or "")
    if kind == "location":
        return None, "[location]"          # never coordinates
    if kind == "contact":
        return None, "[contact card]"      # never a number
    name = " ".join(str(media.get("name") or "").replace("[", "(").replace("]", ")").split())[:120]
    if kind not in turn_extras.ATTACHMENT_KINDS:
        kind = turn_extras.kind_for(media.get("mime"), name)
    entry = {"kind": kind, "name": name or "unnamed"}
    if isinstance(media.get("size"), int) and media["size"] > 0:
        entry["size"] = media["size"]
    if media.get("mime"):
        entry["mime"] = str(media["mime"])[:80]
    word = "image" if kind == "sticker" else kind
    return entry, f"[{word}: {entry['name']}]"


def to_chat(m: TgMessage, *, group: bool) -> ChatMessage | None:
    """One Telegram message as a sitting's message; ``None`` for a service message or one with nothing said."""
    if m.service:
        return None
    ts = chat_live.utc_from_unix(m.date)
    if ts is None:
        return None
    cid = conversation_id(m.chat)
    words = chat_live.fold_text(m.text)
    files: list[dict] = []
    named: list[str] = []
    if m.media:
        entry, word = _file(m.media)
        if entry:
            files.append(entry)
        named.append(word)
    if not words and not named:
        return None
    sender = None
    if not m.out and m.sender is not None:
        sender = member_key(m.chat, m.sender) if group else None
    return ChatMessage(key=message_key(cid, m.id), ts=ts, from_me=bool(m.out),
                       text=chat_live.fold_text(" ".join([words] + named) if words else " ".join(named)),
                       order=int(m.id), sender=sender, edited=bool(m.edited), files=files, attachments=len(files),
                       reply_to=message_key(cid, m.reply_to) if m.reply_to else None,
                       forwarded_from=(chat_live.messages_source._clean_name(m.forward_name) or None)
                       if m.forward_name else None,
                       reactions=reaction_set(m.chat, m.reactions, group=group) if m.reactions is not None else [],
                       reactions_final=m.reactions is not None)


def reaction_set(chat: int, listed: list[dict], *, group: bool) -> list[dict]:
    """The reactions Telegram lists on a message — its whole current set, one per listed reactor. Telegram names the
    reactors only in small chats; a reaction it only counts has no reactor and is not kept."""
    out: dict[str, dict] = {}
    for r in listed:
        kind, emoji = chat_live.emoji_reaction(str(r.get("emoji") or ""))
        from_me = bool(r.get("from_me"))
        if not from_me and r.get("sender") is None:
            continue
        sender = member_key(chat, int(r["sender"])) if not from_me and group else None
        out["me" if from_me else str(r.get("sender"))] = {"from_me": from_me, "kind": kind,
                                                           **({"emoji": emoji} if emoji else {}),
                                                           **({"sender": sender} if sender else {})}
    return list(out.values())


def members_of(messages: list[TgMessage], *, group: bool) -> list[dict]:
    """Who spoke in this batch, as participant keys with the names Telegram shows — never an id, never a number."""
    seen: dict[str, dict] = {}
    for m in messages:
        if m.out or m.sender is None:
            continue
        key = member_key(m.chat, m.sender)
        seen[key] = {"key": key, "name": m.sender_name, "agent": m.sender_bot}
    if not group:
        bots = [v["agent"] for v in seen.values() if v["agent"] is not None]
        return [{"key": "0" * 16, "agent": bots[0]}] if bots else []
    return list(seen.values())


def ingest(memory_path, dialog: dict, messages: list[TgMessage], *, deleted: list[int] = (),
           reacted: dict[int, list[dict]] | None = None, bank: str | None = None) -> dict:
    """Stage what the client read for one chat: new and edited messages, deletes by id, and a reaction change by id
    (``reacted``: message id -> Telegram's whole current set). ``dialog``: ``{id, chat, name, group, bot?}``."""
    from api.services import telegram_account

    # One-to-one is the PEER's, and every message's peer must be the same user (#504 review B4) — the `group` flag is
    # not trusted either way.
    if (dialog.get("group") or not is_user_peer(dialog.get("chat"))
            or any(not is_user_peer(m.chat) or int(m.chat) != int(dialog["chat"]) for m in messages)):
        raise NotOneToOne("Telegram group chats aren't read: Telegram's terms need every member's consent.")
    cid = str(dialog["id"])
    if cid != conversation_id(int(dialog["chat"])):
        raise NotOneToOne("This conversation isn't the one-to-one chat Telegram names.")
    given = telegram_account.consents()
    if cid not in given:
        raise NoConsent("This chat has no confirmation that the other person agreed, so nothing was saved.")
    # Saved Messages (ruling 47a amendment 2026-10-29): the person's chat with themselves, ticked by them alone.
    own = bool(given[cid].get("self"))
    group = False
    chat_messages: list[ChatMessage] = []
    for m in messages:
        cm = to_chat(m, group=group)
        if cm is not None:
            chat_messages.append(cm)
    for message_id, listed_now in (reacted or {}).items():
        stored = chat_live.stored_message(memory_path, SPEC, cid, message_key(cid, message_id))
        if stored is not None and not stored.unsent:
            stored.reactions = reaction_set(int(dialog["chat"]), listed_now, group=group)
            stored.reactions_final = True
            chat_messages.append(stored)
    for message_id in deleted:
        key = message_key(cid, message_id)
        stored = chat_live.stored_message(memory_path, SPEC, cid, key)
        if stored is not None:
            chat_messages.append(ChatMessage(key=key, ts=stored.ts, from_me=stored.from_me, text="", unsent=True,
                                             sender=stored.sender))
    members = members_of(messages, group=group)
    if not group and dialog.get("bot") is not None:
        members = [{"key": "0" * 16, "agent": bool(dialog["bot"])}]
    conversation = {"id": cid, "name": dialog.get("name") or "", "group": group, "members": members,
                    "self_chat": own}
    return chat_live.ingest(memory_path, SPEC, conversation, chat_messages, bank=bank)
