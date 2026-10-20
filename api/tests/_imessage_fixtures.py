"""Synthetic Messages databases for the G179 tests — the real ``chat.db`` tables, placeholder handles and words.

``fixtures/chatdb_tables.sql`` is the structure of macOS 26.6.2's ``chat.db`` (the tables the reader touches, no rows).
``fixtures/imessage_attributed_bodies.json`` holds ``attributedBody`` blobs built by ``NSArchiver`` on that macOS
(``fixtures/imessage_attributed_bodies.swift`` is the generator). :func:`attributed_body` builds a blob for any text
byte-for-byte the way ``NSArchiver`` does — ``test_typedstream`` proves it against every real blob — so a synthetic
conversation can carry its words only in ``attributedBody``, as about a quarter of a real one does.

:func:`read_rows` mirrors the app's reader (``MessagesReader.swift``): the ticked chat's rows past a ROWID cursor, plus
rows edited or unsent after a change watermark, with their attachments' names — the payload the app posts.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = FIXTURES / "chatdb_tables.sql"
APPLE_EPOCH = 978_307_200


def blob_cases() -> list[dict]:
    """Every real blob as ``{name, text, blob}``."""
    data = json.loads((FIXTURES / "imessage_attributed_bodies.json").read_text(encoding="utf-8"))
    out = []
    for c in data["cases"]:
        if "hex" in c:
            out.append({"name": c["name"], "text": c["text"], "blob": bytes.fromhex(c["hex"])})
        else:
            text = c["fill"] * c["count"]
            blob = bytes.fromhex(c["hex_head"]) + text.encode() + bytes.fromhex(c["hex_tail"])
            out.append({"name": c["name"], "text": text, "blob": blob})
    return out


def _int(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    if n < 0x8000:
        return b"\x81" + n.to_bytes(2, "little")
    return b"\x82" + n.to_bytes(4, "little")


def _templates() -> tuple[bytes, bytes, bytes, bytes]:
    cases = {c["name"]: c for c in blob_cases()}
    out = []
    for name in ("plain", "no_attributes"):
        blob, text = cases[name]["blob"], cases[name]["text"].encode()
        at = blob.find(b"\x84\x01+") + 3
        out += [blob[:at], blob[at + 1 + len(text) + 7:]]
    return out[0], out[1], out[2], out[3]


def attributed_body(text: str, *, attributes: bool = True) -> bytes:
    """``NSArchiver.archivedData(withRootObject: NSMutableAttributedString(text))`` — with Messages' part and
    writing-direction attributes over the whole string, or none."""
    head, rest, head_plain, rest_plain = _templates()
    raw = text.encode("utf-8")
    utf16 = len(text.encode("utf-16-le")) // 2
    return ((head if attributes else head_plain) + _int(len(raw)) + raw + b"\x86\x84\x02iI\x01" + _int(utf16)
            + (rest if attributes else rest_plain))


def apple_ns(at: datetime) -> int:
    """``message.date``: nanoseconds since 2001-01-01 UTC."""
    return int((at.timestamp() - APPLE_EPOCH) * 1_000_000_000)


def conversation_id(chat_guid: str) -> str:
    """The app's id for a chat: a hash of ``chat.guid``, never the address inside it (``MessagesReader``)."""
    return hashlib.sha256(chat_guid.encode("utf-8")).hexdigest()[:24]


class ChatDB:
    """A synthetic ``chat.db``: the real tables, rows written as Messages writes them."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.db = sqlite3.connect(self.path)
        self.db.executescript(SCHEMA.read_text(encoding="utf-8"))
        self._guid = 0

    def close(self) -> None:
        self.db.commit()
        self.db.close()

    def chat(self, identifier: str, *, display_name: str = "", style: int = 45, service: str = "iMessage") -> int:
        cur = self.db.execute("INSERT INTO handle (id, service) VALUES (?, ?)", (identifier, service))
        handle = cur.lastrowid
        guid = f"{service};{'-' if style == 45 else '+'};{identifier}"
        cur = self.db.execute(
            "INSERT INTO chat (guid, style, chat_identifier, service_name, display_name) VALUES (?, ?, ?, ?, ?)",
            (guid, style, identifier, service, display_name))
        self.db.execute("INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (?, ?)", (cur.lastrowid, handle))
        self.db.commit()
        return cur.lastrowid

    def chat_guid(self, chat: int) -> str:
        return self.db.execute("SELECT guid FROM chat WHERE ROWID = ?", (chat,)).fetchone()[0]

    def message(self, chat: int, at: datetime, *, from_me: bool, text: str | None = None, body_only: bool = False,
                associated_type: int = 0, item_type: int = 0, attachments: list[dict] | None = None,
                guid: str | None = None, associated_guid: str | None = None, emoji: str | None = None,
                reply_to: str | None = None) -> int:
        """One row. ``body_only`` leaves ``text`` empty and keeps the words only in ``attributedBody``.
        ``associated_guid`` is a tapback's target as Messages writes it (``p:0/<guid>``); ``reply_to`` an inline
        reply's ``thread_originator_guid``."""
        self._guid += 1
        guid = guid or f"SYNTH-{self._guid:06d}-0000-0000-000000000000"
        handle = self.db.execute("SELECT handle_id FROM chat_handle_join WHERE chat_id = ?", (chat,)).fetchone()[0]
        words = text if text is not None else ""
        if attachments:
            words = "￼" * len(attachments) + words
        blob = attributed_body(words) if words else None
        cur = self.db.execute(
            "INSERT INTO message (guid, text, attributedBody, handle_id, service, date, is_from_me, "
            "associated_message_type, associated_message_guid, associated_message_emoji, thread_originator_guid, "
            "item_type, cache_has_attachments) VALUES (?, ?, ?, ?, 'iMessage', ?, ?, ?, ?, ?, ?, ?, ?)",
            (guid, None if body_only else (words or None), blob, handle, apple_ns(at), int(from_me),
             associated_type, associated_guid, emoji, reply_to, item_type, int(bool(attachments))))
        rowid = cur.lastrowid
        self.db.execute("INSERT INTO chat_message_join (chat_id, message_id, message_date) VALUES (?, ?, ?)",
                        (chat, rowid, apple_ns(at)))
        for i, att in enumerate(attachments or []):
            a = self.db.execute(
                "INSERT INTO attachment (guid, original_guid, filename, mime_type, uti, transfer_name, total_bytes, "
                "is_sticker) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"{guid}-att{i}", f"{guid}-att{i}", f"~/Library/Messages/Attachments/xx/{att['name']}",
                 att.get("mime"), att.get("uti"), att["name"], att.get("bytes", 1000), int(att.get("sticker", 0))))
            self.db.execute("INSERT INTO message_attachment_join (message_id, attachment_id) VALUES (?, ?)",
                            (rowid, a.lastrowid))
        self.db.commit()
        return rowid

    def edit(self, rowid: int, text: str, at: datetime) -> None:
        self.db.execute("UPDATE message SET text = ?, attributedBody = ?, date_edited = ? WHERE ROWID = ?",
                        (text, attributed_body(text), apple_ns(at), rowid))
        self.db.commit()

    def guid(self, rowid: int) -> str:
        return self.db.execute("SELECT guid FROM message WHERE ROWID = ?", (rowid,)).fetchone()[0]

    def retract(self, rowid: int, at: datetime) -> None:
        """An unsend on a macOS that stamps ``date_retracted`` (the words gone too)."""
        self.db.execute("UPDATE message SET text = NULL, attributedBody = NULL, date_retracted = ? WHERE ROWID = ?",
                        (apple_ns(at), rowid))
        self.db.commit()

    def unsend(self, rowid: int, at: datetime) -> None:
        """What Messages leaves of an unsent message: the row, its words gone, ``date_edited`` set."""
        self.db.execute("UPDATE message SET text = NULL, attributedBody = NULL, date_edited = ? WHERE ROWID = ?",
                        (apple_ns(at), rowid))
        self.db.commit()


_ROWS_SQL = """
SELECT m.ROWID AS rowid, m.guid, m.date, m.is_from_me, m.text, m.attributedBody, m.associated_message_type,
       m.associated_message_guid, m.associated_message_emoji, m.thread_originator_guid,
       m.item_type, m.is_system_message, COALESCE(m.date_edited, 0) AS date_edited,
       COALESCE(m.date_retracted, 0) AS date_retracted
FROM message m JOIN chat_message_join j ON j.message_id = m.ROWID
WHERE j.chat_id = ?1 AND (m.ROWID > ?2 OR COALESCE(m.date_edited, 0) > ?3 OR COALESCE(m.date_retracted, 0) > ?3)
ORDER BY m.ROWID LIMIT ?4
"""


def read_rows(path: Path, chat: int, *, after_rowid: int = 0, changed_after: int = 0, limit: int = 500) -> list[dict]:
    """The rows the app posts for one ticked chat (``MessagesReader.read``'s query), JSON-ready."""
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        rows = []
        for r in db.execute(_ROWS_SQL, (chat, after_rowid, changed_after, limit)):
            atts = [{"name": a["transfer_name"], "mimeType": a["mime_type"], "uti": a["uti"],
                     "totalBytes": a["total_bytes"], **({"isSticker": True} if a["is_sticker"] else {})}
                    for a in db.execute("SELECT a.transfer_name, a.mime_type, a.uti, a.total_bytes, a.is_sticker "
                                        "FROM attachment a "
                                        "JOIN message_attachment_join j ON j.attachment_id = a.ROWID "
                                        "WHERE j.message_id = ?", (r["rowid"],))]
            rows.append({"rowid": r["rowid"], "guid": r["guid"], "date": r["date"], "isFromMe": bool(r["is_from_me"]),
                         "text": r["text"],
                         "attributedBody": base64.b64encode(r["attributedBody"]).decode() if r["attributedBody"] else None,
                         "associatedMessageType": r["associated_message_type"] or 0, "itemType": r["item_type"] or 0,
                         "isSystemMessage": bool(r["is_system_message"]), "dateEdited": r["date_edited"],
                         "dateRetracted": r["date_retracted"], "attachments": atts,
                         **{k: r[c] for k, c in (("associatedMessageGuid", "associated_message_guid"),
                                                 ("associatedMessageEmoji", "associated_message_emoji"),
                                                 ("threadOriginatorGuid", "thread_originator_guid")) if r[c]}})
        return rows
    finally:
        db.close()


def payload(chat_guid: str, rows: list[dict], *, name: str = "Instinct", from_me: int = 0, from_them: int = 0) -> dict:
    return {"conversation": {"id": conversation_id(chat_guid), "name": name, "service": "iMessage",
                             "fromMe": from_me, "fromThem": from_them}, "messages": rows}


def utc(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
