"""Message conversations the person ticks — iMessage first (G179), over the shared stager (G188's minimal slice).

**Who reads what.** The APP opens ``~/Library/Messages/chat.db`` (it holds Full Disk Access; the launchd backend
never does and never opens that path) and reads only the conversations the person ticked in Settings → Integrations
→ Messages: each message row's id, time, direction, words (``text``, or the archived ``attributedBody`` bytes),
reaction/edit/unsend columns and its attachments' *names*. This module parses what it posts — the ``attributedBody``
through :mod:`typedstream` — and stages it through ``episode_staging``; nothing here reads a database or a file the
request names. A conversation the person has not ticked is refused (409) whatever the app posts, so a newer or buggier
app cannot widen what is stored. Group chats are out of this slice.

**Shape.** One episode per *sitting*: messages more than :data:`SITTING_GAP` apart start a new one. The coordinator's
measurement of the owner's agent conversation (907 rows since 2026-09-03): a 1 h gap gives 87 sittings, 3 h gives 55
and 6 h gives 44. 3 h is the choice — at 1 h the agent's bursts and the person's slow replies over one afternoon split
into pieces of a few messages each (each its own Sleep read, each too thin to promote anything), and at 6 h a morning
and an evening about different things merge; 3 h keeps about one sitting per part of a day, ~15 real messages each,
and it is G179's own "a gap of a few hours closes it". A sitting's key is ``imessage:<conversation>:<first message>``
and stays with the sitting as it grows (G104's one-episode-per-session reading): the app posts only rows past its
``message.ROWID`` cursor plus rows edited or unsent since its last pass, and this module merges them into the stored
sittings they touch — rebuilt from each episode's own body, ``turns`` sidecar and ``message_keys``.

**Who is who.** The person's messages are ``user:`` turns — their own words. The other side's are never ``user``:
an AI agent's (the person's mark, or an ``identified`` detection — :mod:`agent_detectors`) are ``assistant:`` turns,
the agent-reply rule of G105, named by the conversation's name in the episode's ``correspondent`` record; anyone else
(a person, or not yet known) is ``speaker:<label>:``, the meeting rule (G134). Changing the mark re-renders every
stored sitting of that conversation in place, from the stored episodes — nothing is re-read from the Mac.

**Edits, unsends, reactions, replies, attachments** (2026-10-20, :mod:`turn_extras`). An edited message replaces its
words in place (the sitting is re-queued) and is marked ``edited``; an unsent one leaves the words — its text is never
kept — and stays only as WHERE it was and who sent it (``unsent_turns``), so the Reader can say "Unsent"; a sitting
left with nothing said is tombstoned, never unlinked. A tapback (``associated_message_type`` 2000–2007 adds, 3000–3007
removes, 1000 a placed sticker; ``associated_message_guid`` names its target) is never a turn: a tapback row is the
*reactor's* row quoting the other side's words ("Loved “…”"), so its text is never read — only who reacted and with
what lands on the target message's ``reactions``, one per reactor (a new one replaces theirs, a removal drops it), and
a reaction to a message that is not stored is counted and dropped. An inline reply (``thread_originator_guid``)
points at its target turn, or at its key when the target is in another sitting. An attachment is named
(``[image: <file name>]`` in the words, as before) and described beside them (kind, name, size, type) — never read,
never a path; its U+FFFC placeholder is dropped. A message's line breaks are folded to spaces, so nothing inside a
message can open a turn. Every body and every extra is scrubbed by the stager (R-N3; writer ``imessage``). No LLM
anywhere here.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.services import (agent_detectors, episode_ids, episode_staging, evidence, markdown_parser, turn_extras,
                          typedstream)
from api.services.agent_detectors import Actor, ConversationMeta
from api.services.episode_staging import EpisodeDraft, Turn
from api.services.id_utils import sanitize_id

CHANNEL_ID = "imessage"
ORIGIN = "imessage"
SOURCE = "imessage"
SCRUB_WRITER = "imessage"
LABEL = "Messages"
SETTINGS_FILENAME = "messages.json"
SOURCE_PREFIX = "imessage:"
SERVICES = frozenset({"iMessage", "SMS", "RCS"})
#: The gap that closes a sitting (see the module docstring for the measurement it was chosen from).
SITTING_GAP = timedelta(hours=3)
MAX_MESSAGES_PER_REQUEST = 2000
#: One message's line, after folding — an agent's essay is kept to this, with an ellipsis.
MESSAGE_CAP = 4000
ATTACHMENT_NAME_CAP = 120
#: A conversation id is a hash the app makes of ``chat.guid`` — never the phone number or address inside it.
CONVERSATION_ID_RE = re.compile(r"^[0-9a-f]{16,64}$")
#: Seconds from 1970-01-01 to Apple's 2001-01-01 epoch, which ``message.date`` counts from.
APPLE_EPOCH = 978_307_200
_LOCK = threading.RLock()


class PayloadError(ValueError):
    """A request the backend cannot trust — answered 422, nothing staged."""


class NotSelected(PermissionError):
    """A conversation the person has not ticked — answered 409, nothing staged."""


# --- Settings (in the bank: which conversations, and who each one is with) -----------------------------------------


def settings_path(memory_path: Path) -> Path:
    return Path(memory_path) / "sources" / SETTINGS_FILENAME


_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"^[\d\s()+\-.]{7,}$")


def _clean_name(value) -> str:
    """A name the person sees — never a phone number or an address (the app never sends its handle; a newer or buggier
    one cannot make the bank keep one either)."""
    name = " ".join(str(value or "").split())[:80]
    if _EMAIL_RE.search(name) or (_PHONE_RE.match(name) and sum(c.isdigit() for c in name) >= 7):
        return ""
    return name


def load_settings(memory_path: Path) -> dict:
    """``{suggest_agents, conversations: {id: {name, service, ticked, actor?, history}}}`` — never raises."""
    try:
        data = json.loads(settings_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    conversations = {}
    raw = data.get("conversations")
    for cid, entry in (raw.items() if isinstance(raw, dict) else ()):
        if not CONVERSATION_ID_RE.match(str(cid)) or not isinstance(entry, dict):
            continue
        actor = entry.get("actor") if isinstance(entry.get("actor"), dict) else None
        if actor and actor.get("kind") not in agent_detectors.ACTOR_KINDS:
            actor = None
        conversations[str(cid)] = {
            "name": _clean_name(entry.get("name")),
            "service": str(entry.get("service") or "iMessage"),
            "ticked": bool(entry.get("ticked")),
            "actor": actor,
            "history": [h for h in entry.get("history") or [] if isinstance(h, dict)][-50:],
        }
    return {"suggest_agents": bool(data.get("suggest_agents", True)), "conversations": conversations}


def _write_settings(memory_path: Path, data: dict) -> None:
    path = settings_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def update_settings(memory_path: Path, *, suggest_agents: bool | None = None, conversation: dict | None = None,
                    now: str | None = None) -> tuple[dict, bool]:
    """Tick or untick one conversation, or mark who it is with; ``(settings, actor_changed)``.

    ``conversation``: ``{id, name?, service?, ticked?, actor?}`` where ``actor`` is ``{kind: agent|person, label?}``
    or ``{kind: null}`` to clear the person's mark. Every mark is kept in the entry's ``history`` (the spec: "persist
    attribution corrections with their history"). Unticking keeps the entry, and every saved episode."""
    memory_path = Path(memory_path)
    at = now or episode_ids.utc_now_iso()
    with _LOCK:
        data = load_settings(memory_path)
        changed_actor = False
        if suggest_agents is not None:
            data["suggest_agents"] = bool(suggest_agents)
        if conversation is not None:
            cid = str(conversation.get("id") or "")
            if not CONVERSATION_ID_RE.match(cid):
                raise PayloadError("a conversation id is the app's hash of the chat, 16–64 hex characters")
            entry = data["conversations"].setdefault(cid, {"name": "", "service": "iMessage", "ticked": False,
                                                            "actor": None, "history": []})
            if conversation.get("name"):
                entry["name"] = _clean_name(conversation["name"])
            if conversation.get("service") in SERVICES:
                entry["service"] = conversation["service"]
            if conversation.get("ticked") is not None:
                entry["ticked"] = bool(conversation["ticked"])
            if "actor" in conversation:
                raw = conversation.get("actor") if isinstance(conversation.get("actor"), dict) else {}
                kind = raw.get("kind")
                if kind is not None and kind not in agent_detectors.ACTOR_KINDS:
                    raise PayloadError("actor kind is agent, person, or null to clear")
                new = {"kind": kind, "label": _clean_name(raw.get("label"))} if kind else None
                if new and not new["label"]:
                    new.pop("label")
                if new != entry.get("actor"):
                    entry["actor"] = new
                    entry["history"] = (entry.get("history") or []) + [
                        {"at": at, "kind": kind or "cleared", "by": "person", **({"label": new["label"]}
                                                                                 if new and new.get("label") else {})}]
                    changed_actor = True
        _write_settings(memory_path, data)
        return data, changed_actor


def conversation_meta(payload: dict) -> ConversationMeta:
    return ConversationMeta(name=_clean_name(payload.get("name")), display_name=_clean_name(payload.get("display_name")),
                            group=bool(payload.get("group")), from_me=_int(payload.get("from_me")),
                            from_them=_int(payload.get("from_them")))


def actor_for(settings: dict, cid: str, meta: ConversationMeta) -> Actor:
    entry = settings["conversations"].get(cid) or {}
    detection = agent_detectors.detect(meta, enabled=settings.get("suggest_agents", True))
    return agent_detectors.resolve_actor(meta.name or entry.get("name") or "", entry.get("actor"), detection)


def describe(memory_path: Path, conversations: list[dict]) -> list[dict]:
    """The Settings list: each conversation the app found, with the person's tick and mark and the detector's
    suggestion. Computes only — writes nothing, keeps nothing (the names never leave this answer)."""
    settings = load_settings(memory_path)
    out = []
    for raw in conversations:
        cid = str(raw.get("id") or "")
        if not CONVERSATION_ID_RE.match(cid):
            continue
        meta = conversation_meta(raw)
        entry = settings["conversations"].get(cid) or {}
        detection = agent_detectors.detect(meta, enabled=settings["suggest_agents"])
        actor = agent_detectors.resolve_actor(meta.name or entry.get("name") or "", entry.get("actor"), detection)
        out.append({"id": cid, "ticked": bool(entry.get("ticked")), "group": meta.group,
                    "actor": actor.to_dict(), "suggestion": detection.to_dict(),
                    "marked": entry.get("actor")})
    return out


# --- One message ----------------------------------------------------------------------------------------------------


@dataclass
class Message:
    key: str              # a short hash of the message's guid: its identity across passes and devices
    ts: str               # aware UTC
    from_me: bool
    text: str             # one line, folded — before the stager's scrub; empty for an unsent message
    edited: bool = False
    attachments: int = 0
    order: int = 0        # the row's own order (ROWID), or its stored position
    #: Unsent by its sender: kept only as a position, never its words.
    unsent: bool = False
    #: The key of the message this one replies to inline.
    reply_to: str | None = None
    #: ``[{kind, name, size?, mime?}]`` — never a path, never a byte.
    files: list[dict] = field(default_factory=list)
    #: ``[{from_me, kind, emoji?}]``, one per reactor, in the order they reacted.
    reactions: list[dict] = field(default_factory=list)


@dataclass
class Reaction:
    """A tapback row: who reacted to which message with what — never the row's words."""
    target: str           # the target message's key
    from_me: bool
    kind: str             # one of `turn_extras.REACTION_KINDS`
    emoji: str | None
    remove: bool
    ts: str
    order: int


#: ``associated_message_type`` → kind: 2000–2007 add a tapback, 3000–3007 remove it; 1000 is a sticker placed on a
#: message.
REACTION_TYPES = {0: "love", 1: "like", 2: "dislike", 3: "laugh", 4: "emphasize", 5: "question", 6: "emoji",
                  7: "sticker"}
PLACED_STICKER = 1000


@dataclass
class Counts:
    seen: int = 0
    reactions: int = 0
    reactions_kept: int = 0
    reactions_orphaned: int = 0
    replies: int = 0
    events: int = 0
    empty: int = 0
    unsent: int = 0
    edited: int = 0
    attachments: int = 0
    decoded: int = 0


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def message_key(guid: str) -> str:
    return hashlib.sha256(str(guid).encode("utf-8")).hexdigest()[:12]


def apple_time(value) -> str | None:
    """``message.date`` as aware UTC: nanoseconds since 2001 on every recent macOS, seconds on an old database."""
    raw = _int(value)
    if raw <= 0:
        return None
    seconds = raw / 1e9 if raw > 1e11 else float(raw)
    try:
        return episode_ids.to_utc_iso(datetime.fromtimestamp(APPLE_EPOCH + seconds, tz=timezone.utc).replace(microsecond=0))
    except (OverflowError, OSError, ValueError):
        return None


def _attachment_word(att: dict) -> str:
    mime = str(att.get("mime_type") or "").lower()
    uti = str(att.get("uti") or "").lower()
    for word, hints in (("image", ("image/", "public.image", "public.jpeg", "public.png", "public.heic")),
                        ("video", ("video/", "public.movie", "public.mpeg-4")),
                        ("audio", ("audio/", "public.audio", "com.apple.coreaudio"))):
        if mime.startswith(hints[0]) or any(h in uti for h in hints[1:]):
            return word
    return "file"


def _attachment_name(att: dict) -> str:
    """The file's own name, never a path (``attachment.filename`` is a path and is never sent)."""
    name = str(att.get("name") or att.get("transfer_name") or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = " ".join(name.replace("[", "(").replace("]", ")").split())
    return name[:ATTACHMENT_NAME_CAP] or "unnamed"


def _target_key(value) -> str | None:
    """A tapback's or reply's target guid — ``p:<part>/<guid>``, ``bp:<guid>`` or bare — as a message key."""
    raw = str(value or "").strip()
    if raw.startswith("bp:"):
        raw = raw[3:]
    elif raw.startswith("p:") and "/" in raw:
        raw = raw.split("/", 1)[1]
    return message_key(raw) if raw else None


def reaction_from_row(row: dict, ts: str) -> Reaction | None:
    """A tapback row as who reacted with what; ``None`` for an associated row that is not one (its text is never
    read either way)."""
    kind_code = _int(row.get("associated_message_type"))
    target = _target_key(row.get("associated_message_guid"))
    if target is None:
        return None
    if kind_code == PLACED_STICKER:
        kind, remove = "sticker", False
    elif 2000 <= kind_code <= 2007 or 3000 <= kind_code <= 3007:
        kind, remove = REACTION_TYPES[kind_code % 1000], kind_code >= 3000
    else:
        return None
    emoji = " ".join(str(row.get("associated_message_emoji") or "").split())[:turn_extras.EMOJI_CAP] or None
    if kind != "emoji":
        emoji = turn_extras.REACTION_EMOJI.get(kind)
    return Reaction(target=target, from_me=bool(row.get("is_from_me")), kind=kind, emoji=emoji, remove=remove,
                    ts=ts, order=_int(row.get("rowid")))


def _file(att: dict) -> dict:
    entry = {"kind": "sticker" if att.get("is_sticker") else _attachment_word(att), "name": _attachment_name(att)}
    if (size := _int(att.get("total_bytes"))) > 0:
        entry["size"] = size
    if mime := str(att.get("mime_type") or "").strip().lower():
        entry["mime"] = mime
    return entry


def _fold(text: str) -> str:
    line = " ".join(str(text or "").split())
    return line if len(line) <= MESSAGE_CAP else line[: MESSAGE_CAP - 1].rstrip() + "…"


def message_from_row(row: dict, counts: Counts) -> tuple[str, Message | Reaction | None]:
    """``(verdict, item)``: ``kept`` with the message, ``unsent`` with its placeholder (``Message.unsent``, no words),
    ``reaction`` with the tapback (or ``None`` for an associated row that is not one), or a skip verdict —
    ``event`` | ``empty`` | ``invalid``."""
    guid = str(row.get("guid") or "").strip()
    ts = apple_time(row.get("date"))
    if not guid or ts is None:
        return "invalid", None
    counts.seen += 1
    if _int(row.get("item_type")) != 0 or row.get("is_system_message"):
        counts.events += 1
        return "event", None
    if _int(row.get("associated_message_type")) != 0:
        counts.reactions += 1
        return "reaction", reaction_from_row(row, ts)
    key = message_key(guid)
    text = str(row.get("text") or "")
    if not typedstream.visible_text(text) and row.get("attributed_body"):
        try:
            blob = base64.b64decode(str(row["attributed_body"]), validate=True)
        except (binascii.Error, ValueError):
            blob = b""
        decoded = typedstream.decode(blob)
        if decoded is not None:
            counts.decoded += 1
            text = decoded
    words = typedstream.visible_text(text)
    attachments = [a for a in row.get("attachments") or [] if isinstance(a, dict)]
    retracted = _int(row.get("date_retracted")) > 0
    edited = _int(row.get("date_edited")) > 0
    # macOS keeps an unsent message's row with its words gone and `date_edited` set; `date_retracted` where present.
    if retracted or (edited and not words and not attachments):
        counts.unsent += 1
        return "unsent", Message(key=key, ts=ts, from_me=bool(row.get("is_from_me")), text="", unsent=True,
                                 order=_int(row.get("rowid")))
    named = [f"[{_attachment_word(a)}: {_attachment_name(a)}]" for a in attachments[:10]]
    if not words and not named:
        counts.empty += 1
        return "empty", None
    counts.attachments += len(named)
    counts.edited += int(edited)
    reply = _target_key(row.get("thread_originator_guid"))
    if reply == key:
        reply = None
    counts.replies += int(reply is not None)
    line = _fold(" ".join([words] + named if words else named))
    return "kept", Message(key=key, ts=ts, from_me=bool(row.get("is_from_me")), text=line, edited=edited,
                           attachments=len(named), order=_int(row.get("rowid")), reply_to=reply,
                           files=[_file(a) for a in attachments[:10]])


# --- Stored sittings ------------------------------------------------------------------------------------------------


@dataclass
class Sitting:
    source_id: str
    messages: list[Message] = field(default_factory=list)


def _counterpart_marker(actor: Actor) -> str:
    if actor.kind == agent_detectors.AGENT:
        return "assistant"
    label = sanitize_id(actor.label)[:48].strip("-")
    return f"speaker:{label if label and label != 'unnamed' else 'contact'}"


def stored_sitting(entry: episode_staging.IndexEntry) -> Sitting | None:
    """A sitting rebuilt from its own episode: one body line per message (``user: …`` the person's, any other
    marker the other side's), each line's time from the ``turns`` sidecar, each key from ``message_keys``. ``None``
    when they disagree — the episode is then left as it is rather than rewritten from a guess."""
    keys = entry.fm.get("message_keys")
    if not isinstance(keys, list):
        return None
    parsed = markdown_parser.parse(entry.path)   # the sidecar is the file's, never the header cache's
    body = parsed.body
    stamps = evidence.turn_stamps(parsed.frontmatter)
    extras = turn_extras.by_offset(parsed.frontmatter)
    lines = body.split("\n") if body else []
    if len(lines) != len(keys):
        return None
    starts: dict[int, str] = {}
    offset = 0
    for line, key in zip(lines, keys):
        starts[offset] = str(key)
        offset += len(line) + 1
    messages: list[Message] = []
    offset = 0
    previous: str | None = None
    for i, (line, key) in enumerate(zip(lines, keys)):
        marker, sep, text = line.partition(": ") if not line.startswith("speaker:") else _split_speaker(line)
        # Past the sidecar's head-stable cap (500) a turn carries no time: it is no earlier than the one before it.
        ts = episode_staging.normalise_timestamp((stamps.get(offset) or {}).get("ts")) or previous
        if not sep or not ts or marker not in ("user", "assistant") and not marker.startswith("speaker:"):
            return None
        # Odd positions for what was said, even ones for an unsent message before it: same-second ties keep order.
        message = Message(key=str(key), ts=ts, from_me=marker == "user", text=text, order=2 * i + 1)
        _restore_extras(message, extras.get(offset) or {}, starts)
        messages.append(message)
        previous = ts
        offset += len(line) + 1
    for gone in turn_extras.unsent(parsed.frontmatter):
        ts = episode_staging.normalise_timestamp(gone.get("ts"))
        if not gone.get("ref") or not ts:
            continue
        before = sum(1 for at in starts if at < int(gone["at"]))
        messages.append(Message(key=str(gone["ref"]), ts=ts, from_me=gone.get("speaker") == "user", text="",
                                unsent=True, order=2 * before))
    return Sitting(source_id=str(entry.fm.get("source_id")), messages=messages)


def _restore_extras(message: Message, stored: dict, starts: dict[int, str]) -> None:
    """A stored turn's extras back onto its message, so a pass that rebuilds the sitting keeps them."""
    message.edited = stored.get("edited") is True
    message.files = [f for f in stored.get("attachments") or [] if isinstance(f, dict)]
    message.attachments = len(message.files)
    reply = stored.get("reply_to")
    if isinstance(reply, int) and not isinstance(reply, bool):
        message.reply_to = starts.get(reply)
    elif isinstance(reply, dict) and reply.get("ref"):
        message.reply_to = str(reply["ref"])
    message.reactions = [{"from_me": r.get("by") == "user", "kind": r.get("kind"),
                          **({"emoji": r["emoji"]} if r.get("emoji") else {})}
                         for r in stored.get("reactions") or [] if isinstance(r, dict) and r.get("kind")]


def _split_speaker(line: str) -> tuple[str, str, str]:
    head, sep, text = line[len("speaker:"):].partition(": ")
    return (f"speaker:{head}", sep, text) if ":" not in head else ("", "", "")


def _instant(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def split_sittings(messages: list[Message], gap: timedelta = SITTING_GAP) -> list[list[Message]]:
    """Chronological runs of messages, a new run after a silence longer than ``gap``."""
    ordered = sorted(messages, key=lambda m: (_instant(m.ts), m.order))
    runs: list[list[Message]] = []
    for message in ordered:
        if runs and _instant(message.ts) - _instant(runs[-1][-1].ts) <= gap:
            runs[-1].append(message)
        else:
            runs.append([message])
    return runs


def _title(actor: Actor, first_ts: str) -> str:
    if actor.label == agent_detectors.UNNAMED:
        return f"Messages · {first_ts[:10]}"
    return f"Messages with {actor.label} · {first_ts[:10]}"


def sitting_draft(cid: str, source_id: str, messages: list[Message], actor: Actor, service: str) -> EpisodeDraft:
    """One sitting's episode: a line per message said, and beside the words (`turn_extras`) each message's reactions,
    reply target, attachments and edit, and where an unsent message was. ``messages`` are in order; at least one was
    said."""
    counterpart = _counterpart_marker(actor)
    spoken = [m for m in messages if not m.unsent]
    index_of = {m.key: i for i, m in enumerate(spoken)}
    turns: list[Turn] = []
    unsent: list[dict] = []
    for m in messages:
        marker = "user" if m.from_me else counterpart
        if m.unsent:
            unsent.append({"before": len(turns), "speaker": marker, "ts": m.ts, "ref": m.key})
            continue
        extras: dict = {}
        if m.reactions:
            extras["reactions"] = [{"by": "user" if r.get("from_me") else counterpart, "kind": r.get("kind"),
                                    **({"emoji": r["emoji"]} if r.get("emoji") else {})} for r in m.reactions]
        if m.reply_to:
            extras["reply_to"] = index_of[m.reply_to] if m.reply_to in index_of else {"ref": m.reply_to}
        if m.files:
            extras["attachments"] = m.files
        if m.edited:
            extras["edited"] = True
        turns.append(Turn(m.text, marker, m.ts, extras=extras or None))
    first, last = spoken[0].ts, spoken[-1].ts
    return EpisodeDraft(
        title=_title(actor, first), source_id=source_id, source_updated_at=last, timestamp=first,
        original_date=first[:10], source=SOURCE, origin=ORIGIN, turns=turns, unsent=unsent,
        extra={"conversation": cid, "service": service, "correspondent": actor.to_dict(),
               "message_count": len(spoken), "from_person": sum(1 for m in spoken if m.from_me),
               "sitting_first_at": first, "sitting_last_at": last,
               "message_keys": [m.key for m in spoken]},
        writer=SCRUB_WRITER,
    )


def _conversation_entries(index: dict, cid: str) -> dict[str, episode_staging.IndexEntry]:
    prefix = f"{SOURCE_PREFIX}{cid}:"
    return {sid: e for sid, e in index.items() if sid.startswith(prefix) and not e.fm.get("source_deleted_at")}


def _keys(entry: episode_staging.IndexEntry) -> set[str]:
    """Every message a stored sitting holds: those said, and those unsent where they were."""
    return set(entry.fm.get("message_keys") or []) | {str(u["ref"]) for u in turn_extras.unsent(entry.fm)
                                                       if u.get("ref")}


def _touches(entry: episode_staging.IndexEntry, incoming: list[Message], gap: timedelta) -> bool:
    keys = _keys(entry)
    try:
        lo = _instant(str(entry.fm.get("sitting_first_at"))) - gap
        hi = _instant(str(entry.fm.get("sitting_last_at"))) + gap
    except (TypeError, ValueError):
        return bool(keys & {m.key for m in incoming})
    return any(m.key in keys or lo <= _instant(m.ts) <= hi for m in incoming)


def apply_reactions(by_key: dict[str, Message], reactions: list[Reaction], counts: Counts | None = None) -> None:
    """Each tapback onto its message, in the order they were made: one reaction per reactor (a new one replaces
    theirs), a removal drops theirs of that kind. A reaction to a message that is not here, or was unsent, is dropped."""
    for r in sorted(reactions, key=lambda r: (_instant(r.ts), r.order)):
        target = by_key.get(r.target)
        if target is None or target.unsent:
            if counts is not None:
                counts.reactions_orphaned += 1
            continue
        if r.remove:
            target.reactions = [x for x in target.reactions
                                if not (bool(x.get("from_me")) == r.from_me and x.get("kind") == r.kind)]
        else:
            target.reactions = [x for x in target.reactions if bool(x.get("from_me")) != r.from_me] + [
                {"from_me": r.from_me, "kind": r.kind, **({"emoji": r.emoji} if r.emoji else {})}]
        if counts is not None:
            counts.reactions_kept += 1


def plan_sittings(cid: str, stored: list[Sitting], incoming: list[Message], reactions: list[Reaction] = (),
                  gap: timedelta = SITTING_GAP, reserved: frozenset[str] = frozenset(), counts: Counts | None = None
                  ) -> tuple[list[tuple[str, list[Message]]], list[str]]:
    """``([(source_id, messages)], tombstoned source ids)`` for the stored sittings an update touches.

    Incoming messages replace stored ones with the same key (an edit keeps its reactions; an unsend becomes a
    placeholder with no words), the reactions land on their messages, and the union is split again. A resulting
    sitting keeps the key of the earliest stored sitting it holds messages of — so a sitting whose first message was
    unsent, or that a late message bridged to the next, keeps its episode; a stored sitting left with nothing said,
    or absorbed into another, is tombstoned."""
    by_key: dict[str, Message] = {}
    owner: dict[str, str] = {}
    for sitting in stored:
        for m in sitting.messages:
            by_key[m.key] = m
            owner[m.key] = sitting.source_id
    for m in incoming:
        if m.key in by_key:
            old = by_key[m.key]
            m.order = old.order
            if not m.unsent and not m.reactions:
                m.reactions = old.reactions
        by_key[m.key] = m
    apply_reactions(by_key, list(reactions), counts)
    planned: list[tuple[str, list[Message]]] = []
    used: set[str] = set()
    stored_order = [s.source_id for s in stored]
    for run in split_sittings(list(by_key.values()), gap):
        spoken = [m for m in run if not m.unsent]
        if not spoken:
            continue
        mine = [sid for sid in stored_order if sid not in used and any(owner.get(m.key) == sid for m in run)]
        sid = mine[0] if mine else f"{SOURCE_PREFIX}{cid}:{spoken[0].key}"
        # A fresh key never lands on a sitting this pass could not rebuild (``reserved``): that episode is left as it
        # is rather than overwritten with only the new messages.
        if sid in used or (not mine and sid in reserved):
            sid = f"{SOURCE_PREFIX}{cid}:{spoken[0].key}-{len(planned) + 1}"
        used.add(sid)
        planned.append((sid, run))
    gone = [s for s in stored_order if s not in used]
    return planned, gone


#: What a sitting's draft decides beyond its words: who the conversation is with, and the title that names them.
RECORD_KEYS = ("correspondent", "title")


def _stage(drafts: list[EpisodeDraft], episodes_dir: Path, index: dict[str, episode_staging.IndexEntry], *,
           deleted: list[str] = (), bank: str | None = None) -> tuple[episode_staging.StageResult, int]:
    """Stage the drafts, then record the decision on every sitting the stager skipped because its words did not move.

    The stager's unchanged-hash check skips a draft whose scrubbed body it already holds — right for the words, wrong
    for the ``correspondent`` record beside them: marking an unknown chat as a person keeps every line
    ``speaker:<name>:``, so the mark never reached the episode, Sleep never saw it and the chat never got its page
    (#312 review). The record is frontmatter (`episode_staging.reattribute`): no new episode, the body and its hash —
    so every evidence span — untouched, and the queue left as it was, because who said what did not move. A mark that
    DOES move it (an unknown chat marked an agent: ``speaker:`` becomes ``assistant:``) changes the body, and the stager
    rewrites and re-queues the sitting as it always has. ``(result, sittings recorded)``; their paths join
    ``result.paths``."""
    staged = episode_staging.stage(drafts, episodes_dir, deleted_source_ids=list(deleted), bank=bank)
    recorded = 0
    for draft, verdict in zip(drafts, staged.verdicts):
        entry = index.get(str(draft.source_id)) if verdict == "skipped" else None
        if entry is None:
            continue
        wanted = {"correspondent": draft.extra.get("correspondent"), "title": draft.title}
        if all(entry.fm.get(k) == wanted[k] for k in RECORD_KEYS):
            continue
        if episode_staging.reattribute(entry.path, extra=wanted, queue_for_sleep=draft.queue_for_sleep):
            recorded += 1
            staged.paths.append(f"{episodes_dir.name}/{entry.path.name}")
    return staged, recorded


# --- Ingest ---------------------------------------------------------------------------------------------------------


def _messages(rows: list, counts: Counts) -> tuple[list[Message], list[Reaction]]:
    """The posted rows as messages (a later row for the same key wins: an edit, an unsend) and tapbacks."""
    kept: dict[str, Message] = {}
    reactions: list[Reaction] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        verdict, item = message_from_row(row, counts)
        if verdict in ("kept", "unsent") and isinstance(item, Message):
            kept[item.key] = item
        elif verdict == "reaction" and isinstance(item, Reaction):
            reactions.append(item)
    return list(kept.values()), reactions


def ingest(memory_path: Path, payload: dict, *, bank: str | None = None) -> dict:
    """Stage one posted batch of one ticked conversation. Raises :class:`PayloadError` (422) or
    :class:`NotSelected` (409); nothing is written then."""
    memory_path = Path(memory_path)
    conversation = payload.get("conversation") if isinstance(payload.get("conversation"), dict) else {}
    cid = str(conversation.get("id") or "")
    if not CONVERSATION_ID_RE.match(cid):
        raise PayloadError("a conversation id is the app's hash of the chat, 16–64 hex characters")
    if conversation.get("group"):
        raise PayloadError("group conversations are not read yet")
    service = str(conversation.get("service") or "iMessage")
    if service not in SERVICES:
        raise PayloadError(f"service is one of {', '.join(sorted(SERVICES))}")
    rows = payload.get("messages") or []
    if not isinstance(rows, list):
        raise PayloadError("messages is a list")
    if len(rows) > MAX_MESSAGES_PER_REQUEST:
        raise PayloadError(f"at most {MAX_MESSAGES_PER_REQUEST} messages per request")
    settings = load_settings(memory_path)
    entry = settings["conversations"].get(cid)
    if not entry or not entry.get("ticked"):
        raise NotSelected("This conversation isn't ticked in Settings → Integrations → Messages, so nothing was saved.")
    meta = conversation_meta(conversation)
    actor = actor_for(settings, cid, meta)
    counts = Counts()
    incoming, reactions = _messages(rows, counts)
    targets = {r.target for r in reactions}
    episodes_dir = memory_path / "episodes"
    with episode_staging.STAGE_LOCK:
        index, _ = episode_staging.scan(episodes_dir)
        mine = _conversation_entries(index, cid)
        touched = [e for e in mine.values() if _touches(e, incoming, SITTING_GAP) or _keys(e) & targets]
        stored: list[Sitting] = []
        unreadable: set[str] = set()
        for e in sorted(touched, key=lambda e: str(e.fm.get("sitting_first_at") or "")):
            sitting = stored_sitting(e)
            if sitting is not None:
                stored.append(sitting)
            else:
                unreadable.add(str(e.fm.get("source_id")))
        planned, gone = plan_sittings(cid, stored, incoming, reactions, reserved=frozenset(unreadable), counts=counts)
        drafts = [sitting_draft(cid, sid, msgs, actor, service) for sid, msgs in planned]
        staged, recorded = _stage(drafts, episodes_dir, index, deleted=gone, bank=bank)
    return {"conversation": cid, "messages_seen": counts.seen, "kept": sum(1 for m in incoming if not m.unsent),
            "reactions": counts.reactions, "reactions_kept": counts.reactions_kept,
            "reactions_orphaned": counts.reactions_orphaned, "replies": counts.replies,
            "events": counts.events, "empty": counts.empty, "unsent": counts.unsent, "edited": counts.edited,
            "attachments": counts.attachments, "decoded": counts.decoded, "sittings": len(planned),
            "created": staged.created, "updated": staged.updated, "skipped": staged.skipped,
            "tombstoned": staged.tombstoned, "recorded": recorded, "actor": actor.to_dict(), "paths": staged.paths}


def reattribute(memory_path: Path, cid: str, *, bank: str | None = None) -> dict:
    """Re-render every stored sitting of ``cid`` under its current actor — the person just marked who the
    conversation is with. Nothing is re-read from the Mac. A sitting whose words move (``speaker:`` ↔ ``assistant:``)
    is rewritten and queued for Sleep again; one whose words do not still gets the decision in its ``correspondent``
    record (``recorded``, `_stage`), so the mark always reaches Sleep and the chat's page."""
    memory_path = Path(memory_path)
    settings = load_settings(memory_path)
    entry = settings["conversations"].get(cid) or {}
    episodes_dir = memory_path / "episodes"
    with episode_staging.STAGE_LOCK:
        index, _ = episode_staging.scan(episodes_dir)
        mine = _conversation_entries(index, cid)
        drafts = []
        for e in mine.values():
            sitting = stored_sitting(e)
            if sitting is None or not any(not m.unsent for m in sitting.messages):
                continue
            stored_actor = e.fm.get("correspondent") if isinstance(e.fm.get("correspondent"), dict) else {}
            name = entry.get("name") or str(stored_actor.get("name") or "")
            detection = agent_detectors.Detection() if not settings.get("suggest_agents", True) else agent_detectors.Detection(
                outcome=str(stored_actor.get("detection") or agent_detectors.UNKNOWN),
                detector=(str(stored_actor["detector"]).partition("@")[0] if stored_actor.get("detector") else None),
                version=(_int(str(stored_actor["detector"]).partition("@")[2]) if stored_actor.get("detector") else None),
                signal=stored_actor.get("signal"))
            actor = agent_detectors.resolve_actor(name, entry.get("actor"), detection)
            ordered = sorted(sitting.messages, key=lambda m: (_instant(m.ts), m.order))
            drafts.append(sitting_draft(cid, sitting.source_id, ordered, actor,
                                        str(e.fm.get("service") or entry.get("service") or "iMessage")))
        staged, recorded = _stage(drafts, episodes_dir, mine, bank=bank)
    return {"updated": staged.updated, "recorded": recorded, "skipped": staged.skipped - recorded,
            "paths": staged.paths}


# --- What is waiting (the Sleep page's and Home's bubbles) --------------------------------------------------------


def waiting(memory_path: Path) -> list[dict]:
    """One entry per conversation with sittings Sleep has not read: its name, who it is with, and how many messages
    those sittings hold (a re-queued sitting is read whole, so all of its messages count). Frontmatter only.

    ``page`` is the correspondent's own page when one exists (2026-10-16, so the app draws the chat with that page's
    picture): found by the newest sitting's decided ``correspondent`` record — the person's mark or an ``identified``
    detection, never ``unknown`` — through `correspondents.find_page`, the very rule Stage 2 resolves it by (its type,
    its folded name). Never a page that merely shares the chat's display name; ``None`` while the correspondent is
    undecided or still held below the promotion bar."""
    from api.services import bank_index, correspondents

    settings = load_settings(memory_path)
    out: dict[str, dict] = {}
    records: dict[str, dict] = {}
    for f in bank_index.files(Path(memory_path), "episodes"):
        fm = f.frontmatter or {}
        if fm.get("origin") != ORIGIN or fm.get("processed") or fm.get("source_deleted_at"):
            continue
        cid = str(fm.get("conversation") or "")
        if not CONVERSATION_ID_RE.match(cid):
            continue
        actor = fm.get("correspondent") if isinstance(fm.get("correspondent"), dict) else {}
        row = out.setdefault(cid, {"conversation": cid, "service": str(fm.get("service") or "iMessage"),
                                   "name": "", "kind": agent_detectors.UNKNOWN, "messages": 0, "sittings": 0,
                                   "latest": ""})
        row["messages"] += _int(fm.get("message_count"))
        row["sittings"] += 1
        last = str(fm.get("sitting_last_at") or fm.get("timestamp") or "")
        if last >= row["latest"]:
            row["latest"] = last
            row["name"] = str(actor.get("name") or "")
            row["kind"] = str(actor.get("kind") or agent_detectors.UNKNOWN)
            records[cid] = actor
    idents = {cid: correspondents.identity(record) for cid, record in records.items()}
    pages = ([{"id": f.stem, "frontmatter": f.frontmatter or {}} for f in bank_index.files(Path(memory_path), "entities")]
             if any(idents.values()) else [])
    for cid, row in out.items():
        entry = settings["conversations"].get(cid) or {}
        row["name"] = entry.get("name") or row["name"] or agent_detectors.UNNAMED
        row["ticked"] = bool(entry.get("ticked"))
        ident = idents.get(cid)
        page = correspondents.find_page(pages, ident) if ident is not None else None
        row["page"] = str(page["id"]) if page is not None else None
    return sorted(out.values(), key=lambda r: (-r["messages"], r["name"]))


def live_count(memory_path: Path) -> int:
    index, _ = episode_staging.scan(Path(memory_path) / "episodes")
    return sum(1 for sid, e in index.items() if sid.startswith(SOURCE_PREFIX) and not e.fm.get("source_deleted_at"))


def any_ticked(memory_path: Path) -> bool:
    return any(c.get("ticked") for c in load_settings(memory_path)["conversations"].values())
