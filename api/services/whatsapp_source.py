"""WhatsApp chats the person ticks, read live from WhatsApp Desktop's own store on this Mac (G179, 2026-10-28).

**Why this way.** WhatsApp has no API for a personal account; the unofficial clients (Baileys, whatsmeow …) speak its
protocol against its terms and get accounts banned — ruled out. WhatsApp Desktop for Mac keeps the person's chats in a
plain (unencrypted) Core Data SQLite store, ``ChatStorage.sqlite``, in its group container
``~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/`` — the iOS app's schema (public forensic write-ups,
the open-source exporters). So this is the Messages model exactly: the APP (Full Disk Access, which also covers
another app's group container without the "access data from other apps" prompt) copies the store with its ``-wal``
into a private temp folder, reads only the TICKED chats from the copy, watches the container with FSEvents and posts
a projection here; the backend never opens a path (CLAUDE.md's Awake rail), parses what it is given and stages it
through :mod:`chat_live` → :mod:`episode_staging`. No LLM.

**What the app posts, per ticked chat** (``ZWACHATSESSION`` / ``ZWAMESSAGE`` / ``ZWAMEDIAITEM`` /
``ZWAGROUPMEMBER``): the conversation as its id (the app's hash of ``ZCONTACTJID`` — never the number in it), the name
the person sees (their Contacts card for the number, else WhatsApp's partner name; never the number), whether it is a
group and its members as participant keys (the app's hash of the chat's and the member's JID) with their names. Each
message row: ``stanza`` (``ZSTANZAID``), ``date`` (``ZMESSAGEDATE``, seconds since 2001), ``from_me``, ``text``,
``type`` (``ZMESSAGETYPE``), ``member`` (the participant key, groups only), ``metadata`` (``ZMETADATA`` as base64 — the
quoted reply lives there) and ``media`` (``{title?, file?, size?}`` — the file's own name, never ``ZMEDIALOCALPATH``,
never a byte).

**What each row becomes.** ``ZMESSAGETYPE`` 6 is a group event (joined, renamed) — skipped; 14 is a message deleted
for everyone — its place kept, its words never (``unsent_turns``); 15 is a sticker; 4 a contact card and 5 a location —
named, never their contents (no vCard, no coordinates); any row with a media item is an attachment, named and
described. A quoted reply is protobuf field 5 of ``ZMETADATA`` — the quoted message's stanza id (KnugiHK's
WhatsApp-Chat-Exporter reads the same bytes); a message key is a hash of the chat and the stanza id's first 16
characters, because the quoted id is stored truncated. Reactions and edits are accepted when the reader posts them
(``reactions: [{target, member?, from_me, emoji, date}]``, a row's ``edited``) — the desktop store's columns for them
are not publicly documented, so the reader does not post them yet (the area doc lists it).
"""

from __future__ import annotations

import base64
import binascii
import re

from api.services import chat_live, messages_source, turn_extras
from api.services.chat_live import ChatMessage, ChatReaction, ChatSpec

SPEC = ChatSpec(channel="whatsapp", origin="whatsapp", label="WhatsApp", settings_filename="whatsapp.json",
                writer="whatsapp")
#: ``ZMESSAGETYPE`` values whose meaning public sources agree on (KnugiHK/Whatsapp-Chat-Exporter, forensic notes).
SYSTEM_TYPE = 6
DELETED_TYPE = 14
STICKER_TYPE = 15
CONTACT_TYPE = 4
LOCATION_TYPE = 5
_MEDIA_KIND = {1: "image", 2: "video", 3: "audio", STICKER_TYPE: "sticker"}
STANZA_KEY_CHARS = 16
#: A group @mention as WhatsApp stores it — the member's number in the words. The app replaces each with the member's
#: name where it knows them; one left (an older app, a number nobody named) reads "@someone" here, before the scrub's
#: own phone rule (``episode_scrub.PHONE_WRITERS``) would catch it anyway.
_MENTION_RE = re.compile(r"(?<![\w@])@\+?\d{6,15}(?!\w)")


def message_key(cid: str, stanza: str) -> str:
    return chat_live.hash_id(cid, str(stanza).strip()[:STANZA_KEY_CHARS], length=12)


def quoted_stanza(metadata_b64) -> str | None:
    """The quoted message's stanza id from ``ZMETADATA``: top-level protobuf field 5 (length-delimited). Never raises;
    ``None`` for anything else (a reply, a forward or a link preview the blob may also describe)."""
    try:
        blob = base64.b64decode(str(metadata_b64 or ""), validate=True)
    except (binascii.Error, ValueError):
        return None
    i, n = 0, len(blob)
    while i < n:
        tag, i = _varint(blob, i)
        if tag is None:
            return None
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            _, i = _varint(blob, i)
            if i is None:
                return None
        elif wire == 2:
            length, i = _varint(blob, i)
            if length is None or i + length > n:
                return None
            if field == 5:
                raw = blob[i:i + length]
                try:
                    text = raw.decode("ascii")
                except UnicodeDecodeError:
                    return None
                return text if text.isprintable() and text.strip() else None
            i += length
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        else:
            return None
    return None


def _varint(blob: bytes, i: int) -> tuple[int | None, int | None]:
    shift, value = 0, 0
    while i < len(blob) and shift < 64:
        byte = blob[i]
        value |= (byte & 0x7F) << shift
        i += 1
        if not byte & 0x80:
            return value, i
        shift += 7
    return None, None


def _file(media: dict, kind_hint: str | None) -> dict:
    name = str(media.get("file") or media.get("title") or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = " ".join(name.replace("[", "(").replace("]", ")").split())[: messages_source.ATTACHMENT_NAME_CAP]
    kind = kind_hint or turn_extras.kind_for(media.get("mime"), name)
    entry = {"kind": kind, "name": name or "unnamed"}
    try:
        size = int(media.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if size > 0:
        entry["size"] = size
    return entry


def parse_rows(cid: str, rows: list, counts: chat_live.Counts, *, group: bool) -> tuple[list[ChatMessage],
                                                                                     list[ChatReaction]]:
    out: list[ChatMessage] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        stanza = str(row.get("stanza") or "").strip()
        ts = messages_source.apple_time(row.get("date"))
        if not stanza or ts is None:
            continue
        try:
            kind = int(row.get("type") or 0)
        except (TypeError, ValueError):
            kind = 0
        if kind == SYSTEM_TYPE:
            continue
        from_me = bool(row.get("from_me"))
        member = str(row.get("member") or "").strip().lower()
        sender = None if from_me else (member if group and chat_live.ID_RE.match(member) else None)
        key = message_key(cid, stanza)
        order = int(row.get("rowid") or 0) if str(row.get("rowid") or "0").isdigit() else 0
        if kind == DELETED_TYPE:
            out.append(ChatMessage(key=key, ts=ts, from_me=from_me, text="", unsent=True, order=order, sender=sender))
            continue
        words = chat_live.fold_text(_MENTION_RE.sub("@someone", str(row.get("text") or "")))
        media = row.get("media") if isinstance(row.get("media"), dict) else None
        files: list[dict] = []
        named: list[str] = []
        if kind == CONTACT_TYPE:
            named.append("[contact card]")
            words = ""                     # a contact card's text is the person's name and number — never kept
        elif kind == LOCATION_TYPE:
            named.append("[location]")
            words = ""                     # never coordinates or a place name the row carries
        elif media is not None or kind in _MEDIA_KIND:
            entry = _file(media or {}, _MEDIA_KIND.get(kind))
            files.append(entry)
            named.append(f"[{'image' if entry['kind'] == 'sticker' else entry['kind']}: {entry['name']}]")
            if media and words and words == " ".join(str(media.get("title") or "").split()):
                words = ""                 # a document's title doubles as ZTEXT: name it once
        if not words and not named:
            continue
        quoted = quoted_stanza(row.get("metadata"))
        reply = message_key(cid, quoted) if quoted else None
        out.append(ChatMessage(key=key, ts=ts, from_me=from_me, text=chat_live.fold_text(" ".join([words] + named)
                                                                                         if words else " ".join(named)),
                               order=order, sender=sender, files=files, attachments=len(files),
                               reply_to=reply if reply != key else None, edited=row.get("edited") is True))
    reactions: list[ChatReaction] = []
    return out, reactions


def parse_reactions(cid: str, rows: list, *, group: bool) -> list[ChatReaction]:
    out = []
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict) or not row.get("target"):
            continue
        ts = messages_source.apple_time(row.get("date"))
        if ts is None:
            continue
        member = str(row.get("member") or "").strip().lower()
        from_me = bool(row.get("from_me"))
        emoji = str(row.get("emoji") or "")
        kind, shown = chat_live.emoji_reaction(emoji)
        out.append(ChatReaction(target=message_key(cid, str(row["target"])), from_me=from_me, kind=kind, emoji=shown,
                                remove=not emoji.strip(), ts=ts,
                                sender=None if from_me else (member if group and chat_live.ID_RE.match(member) else None)))
    return out


def ingest(memory_path, payload: dict, *, bank: str | None = None) -> dict:
    conversation = payload.get("conversation") if isinstance(payload.get("conversation"), dict) else {}
    cid = str(conversation.get("id") or "")
    rows = payload.get("messages") or []
    if not isinstance(rows, list):
        raise chat_live.PayloadError("messages is a list")
    counts = chat_live.Counts()
    group = bool(conversation.get("group"))
    messages, _ = parse_rows(cid, rows, counts, group=group)
    reactions = parse_reactions(cid, payload.get("reactions") or [], group=group)
    return chat_live.ingest(memory_path, SPEC, conversation, messages, reactions, bank=bank, counts=counts)
