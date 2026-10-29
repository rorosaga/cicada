"""Live chats from more than one messaging app — the sitting engine WhatsApp and Telegram share (G179, 2026-10-28).

The owner, 2026-10-28: "I want a live tracking like we do with messages plus a historical if I want", group chats
included, "who said what to who, believes what", and one person one page across sources. Messages (`messages_source`)
was built for one source: its keys, settings file and titles are its own. This module is the same discipline, made
source-agnostic, for every chat source added after it: a source module (`whatsapp_source`, `telegram_source`) turns
what its reader produced into :class:`ChatMessage` / :class:`ChatReaction` and hands them here with its
:class:`ChatSpec`; everything below is shared.

**Rails, the Messages ones.** Only a conversation the person ticked is stored — anything else is refused
(:class:`NotSelected`, 409), whatever a reader posts. A tick is consent to LIVE reading: the settings record when it
was ticked (``reads_from``) and a message older than that is dropped (counted ``before_start``) until the person asks
for that chat's history (:func:`update_settings` ``history=True``), which opens it back to the first message the
source holds — history is per chat, on the person's ask, enforced here and not only by the reader. No phone number,
address or platform id reaches the bank: a conversation id and a participant key are hashes the reader makes
(16–64 hex), names pass :func:`messages_source._clean_name`. Every body and extra is scrubbed by the stager under the
spec's writer; nothing here calls a model.

**Shape — one episode per sitting**, split at :data:`messages_source.SITTING_GAP` (3 h, measured for Messages), keyed
``<prefix><conversation>:<first message>`` and kept as the sitting grows; a stored sitting is rebuilt from its own
episode (body, ``turns`` sidecar, ``message_keys``, ``participants``, ``turn_extras``), never from a reader's cache.

**Who is who (G179's speaker rules).** The person's messages are ``user:`` — their own words. In a one-to-one chat
the other side is ``assistant:`` when it is an agent (the source says so — a Telegram bot — or the person marked it),
else ``speaker:<label>:``, and the episode's ``correspondent`` record names them, so Stage 2 lands them on the same
page whichever app the conversation came through (`correspondents.find_page`, by type and folded name — one person,
one page). A group records ``group: true`` and ``participants: [{key, marker, name?, kind}]`` — the record shape the
Messages group slice uses, so `turn_signals` and Sleep read every source alike — and each member speaks under their
own marker; at most one member may be ``assistant`` (two would share it). A member's beliefs stay theirs: in a group
only the person's ``user:`` lines are their words.

**Interaction signals** live beside the words (`turn_extras`): a quoted reply's target (``reply_to``), reactions one
per reactor, an edit (the words replaced in place, ``edited``), a delete for everyone (the words dropped, the place
kept in ``unsent_turns``), attachments named and described (never read, never a path) and a forward's origin
(``forwarded_from``).
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.services import (agent_detectors, contact_identity, episode_ids, episode_staging, evidence, markdown_parser, messages_source,
                          turn_extras)
from api.services.agent_detectors import Actor, Detection
from api.services.episode_staging import EpisodeDraft, Turn
from api.services.id_utils import sanitize_id

#: Every chat source's origin — Messages first. What "a texted conversation" means to every reader that asks.
CHAT_ORIGINS = frozenset({"imessage", "whatsapp", "telegram-chats"})
ID_RE = re.compile(r"^[0-9a-f]{16,64}$")
MAX_MESSAGES_PER_REQUEST = 2000
MAX_MEMBERS = 256
MESSAGE_CAP = messages_source.MESSAGE_CAP
EPOCH = "1970-01-01T00:00:00+00:00"
#: How a person reads a group with nobody named for a line (a member the reader could not place).
UNKNOWN_MEMBER = "speaker:member"
_LOCK = threading.RLock()


class PayloadError(ValueError):
    """A request the backend cannot trust — answered 422, nothing staged."""


class NotSelected(PermissionError):
    """A conversation the person has not ticked — answered 409, nothing staged."""


@dataclass(frozen=True)
class ChatSpec:
    """What makes one chat source its own: where its ticks live, its keys, its words."""
    channel: str          # the Sources row and sync-state id
    origin: str           # the episodes' origin and source
    label: str            # "WhatsApp" — the titles' and the Sources row's word
    settings_filename: str
    writer: str           # the scrub writer (`episode_scrub.WRITERS`)

    @property
    def prefix(self) -> str:
        return f"{self.origin}:"


# --- Settings: which conversations, from when ---------------------------------------------------------------------


def settings_path(memory_path: Path, spec: ChatSpec) -> Path:
    return Path(memory_path) / "sources" / spec.settings_filename


def load_settings(memory_path: Path, spec: ChatSpec) -> dict:
    """``{conversations: {id: {name, group, ticked, reads_from, actor, history}}}`` — never raises."""
    try:
        data = json.loads(settings_path(memory_path, spec).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    raw = data.get("conversations") if isinstance(data, dict) else None
    conversations = {}
    for cid, entry in (raw.items() if isinstance(raw, dict) else ()):
        if not ID_RE.match(str(cid)) or not isinstance(entry, dict):
            continue
        actor = entry.get("actor") if isinstance(entry.get("actor"), dict) else None
        if actor and actor.get("kind") not in agent_detectors.ACTOR_KINDS:
            actor = None
        conversations[str(cid)] = {
            "name": messages_source._clean_name(entry.get("name")),
            "group": bool(entry.get("group")),
            "ticked": bool(entry.get("ticked")),
            "reads_from": episode_staging.normalise_timestamp(entry.get("reads_from")),
            "actor": actor,
            "history": [h for h in entry.get("history") or [] if isinstance(h, dict)][-50:],
        }
    return {"conversations": conversations}


def _write_settings(memory_path: Path, spec: ChatSpec, data: dict) -> None:
    path = settings_path(memory_path, spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def update_settings(memory_path: Path, spec: ChatSpec, conversation: dict, *, now: str | None = None
                    ) -> tuple[dict, bool]:
    """Tick or untick one conversation, ask for its history, or mark who it is with; ``(settings, actor_changed)``.

    ``conversation``: ``{id, name?, group?, ticked?, history?, actor?}``. A first tick sets ``reads_from`` to now —
    live from here; ``history: true`` opens it back to the first message the source holds. Unticking keeps the entry
    and every saved episode; ticking again keeps the earlier start (what was read stays read). Every change is kept in
    the entry's ``history``."""
    at = now or episode_ids.utc_now_iso()
    cid = str(conversation.get("id") or "")
    if not ID_RE.match(cid):
        raise PayloadError("a conversation id is the reader's hash of the chat, 16–64 hex characters")
    with _LOCK:
        data = load_settings(memory_path, spec)
        entry = data["conversations"].setdefault(cid, {"name": "", "group": False, "ticked": False,
                                                       "reads_from": None, "actor": None, "history": []})
        if conversation.get("name"):
            entry["name"] = messages_source._clean_name(conversation["name"])
        if conversation.get("group") is not None:
            entry["group"] = bool(conversation["group"])
        log = entry.setdefault("history", [])
        if conversation.get("ticked") is not None and bool(conversation["ticked"]) != entry["ticked"]:
            entry["ticked"] = bool(conversation["ticked"])
            if entry["ticked"] and not entry.get("reads_from"):
                entry["reads_from"] = at
            log.append({"at": at, "kind": "ticked" if entry["ticked"] else "unticked", "by": "person"})
        if conversation.get("history"):
            if not entry["ticked"]:
                raise NotSelected(f"Tick this conversation on the Sources page → {spec.label} before reading its "
                                  "history.")
            if entry.get("reads_from") != EPOCH:
                entry["reads_from"] = EPOCH
                log.append({"at": at, "kind": "history", "by": "person"})
        changed_actor = False
        if "actor" in conversation:
            raw = conversation.get("actor") if isinstance(conversation.get("actor"), dict) else {}
            kind = raw.get("kind")
            if kind is not None and kind not in agent_detectors.ACTOR_KINDS:
                raise PayloadError("actor kind is agent, person, or null to clear")
            new = {"kind": kind} if kind else None
            if new != entry.get("actor"):
                entry["actor"] = new
                log.append({"at": at, "kind": kind or "cleared", "by": "person"})
                changed_actor = True
        entry["history"] = log[-50:]
        _write_settings(memory_path, spec, data)
        return data, changed_actor


def describe(memory_path: Path, spec: ChatSpec, conversations: list[dict]) -> list[dict]:
    """The tick list's backend half: each listed conversation with the person's tick and whether its history was
    asked for. Computes only — writes and keeps nothing."""
    settings = load_settings(memory_path, spec)["conversations"]
    out = []
    for raw in conversations:
        cid = str(raw.get("id") or "")
        if not ID_RE.match(cid):
            continue
        entry = settings.get(cid) or {}
        out.append({"id": cid, "ticked": bool(entry.get("ticked")), "group": bool(raw.get("group")),
                    "history": entry.get("reads_from") == EPOCH, "reads_from": entry.get("reads_from"),
                    "marked": entry.get("actor")})
    return out


def any_ticked(memory_path: Path, spec: ChatSpec) -> bool:
    return any(c.get("ticked") for c in load_settings(memory_path, spec)["conversations"].values())


def ticked_ids(memory_path: Path, spec: ChatSpec) -> set[str]:
    return {cid for cid, c in load_settings(memory_path, spec)["conversations"].items() if c.get("ticked")}


# --- What a reader hands in ---------------------------------------------------------------------------------------


def hash_id(*parts: str, length: int = 24) -> str:
    """A stable id for a platform id (a chat, a member, a message) that never carries it: sha256, hex, cut."""
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:length]


@dataclass
class ChatMessage(messages_source.Message):
    #: A group member's participant key, or the one-to-one other side's; ``None`` for the person's own message.
    sender: str | None = None
    #: Whose words a forwarded message really are — a name, never an id.
    forwarded_from: str | None = None
    #: ``reactions`` is the source's whole current set (Telegram lists it), so an empty one clears what was stored.
    reactions_final: bool = False


@dataclass
class ChatReaction:
    target: str
    from_me: bool
    kind: str
    emoji: str | None
    remove: bool
    ts: str
    order: int = 0
    sender: str | None = None


@dataclass
class Member:
    key: str
    name: str = ""
    agent: bool = False


@dataclass
class Counts:
    seen: int = 0
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


def fold_text(text: str) -> str:
    line = " ".join(str(text or "").split())
    return line if len(line) <= MESSAGE_CAP else line[: MESSAGE_CAP - 1].rstrip() + "…"


def emoji_reaction(emoji: str) -> tuple[str, str | None]:
    """A free emoji reaction as ``(kind, emoji)`` in `turn_extras`' set: a classic tapback's emoji keeps its kind."""
    emoji = " ".join(str(emoji or "").split())[: turn_extras.EMOJI_CAP]
    for kind, shown in turn_extras.REACTION_EMOJI.items():
        if emoji and emoji == shown:
            return kind, shown
    return "emoji", emoji or None


# --- Who is who --------------------------------------------------------------------------------------------------


@dataclass
class Cast:
    """A conversation's speakers: participant key -> marker; the record written beside the words."""
    group: bool
    title: str
    markers: dict[str, str]
    actor: Actor | None = None
    record: list[dict] = field(default_factory=list)
    #: A one-to-one chat's other side: their ONE address-book card, by Contacts id (`contact_identity`).
    contact: str | None = None
    #: chats-ux-v2 — the person's chat with themselves: every line is theirs, there is no other side.
    self_chat: bool = False

    def marker(self, from_me: bool, sender: str | None) -> str:
        if from_me:
            return "user"
        if not self.group:
            return self.markers.get("", "speaker:contact")
        return self.markers.get(str(sender or ""), UNKNOWN_MEMBER)


def _label(name: str, key: str, used: set[str]) -> str:
    label = sanitize_id(name)[:48].strip("-") if name else ""
    if not label or label == "unnamed":
        label = f"member-{key[:6]}"
    base, n = label, 2
    while label in used:
        label, n = f"{base}-{n}", n + 1
    used.add(label)
    return label


def one_to_one_actor(name: str, mark: dict | None, *, agent: bool | None) -> Actor:
    """The other side of a one-to-one chat: the person's mark, else what the SOURCE states (a Telegram account says
    whether it is a bot — ``agent`` True/False), else a name-only detector suggestion, else unknown."""
    detection = agent_detectors.detect(agent_detectors.ConversationMeta(name=name))
    if isinstance(mark, dict) and mark.get("kind") in agent_detectors.ACTOR_KINDS:
        return agent_detectors.resolve_actor(name, mark, detection)
    if agent is not None:
        label = " ".join(str(name or "").split())[:80] or agent_detectors.UNNAMED
        return Actor(kind=agent_detectors.AGENT if agent else agent_detectors.PERSON, label=label,
                     decided_by="source", detection=Detection())
    return agent_detectors.resolve_actor(name, None, detection)


def cast_for(spec: ChatSpec, entry: dict, conversation: dict, stored: list[dict] = ()) -> Cast:
    """Who speaks in this conversation, from what the reader posted over what the stored sittings recorded, so a
    member keeps their marker when a pass names nobody new."""
    title = messages_source._clean_name(conversation.get("name")) or entry.get("name") or ""
    members = [m for m in conversation.get("members") or [] if isinstance(m, dict)][:MAX_MEMBERS]
    if not conversation.get("group") and conversation.get("self_chat"):
        # chats-ux-v2 (owner 2026-10-29: "he sends himself a lot") — the person's notes to themselves: every line is
        # the person's own words, whichever of their devices sent it; no correspondent, no card (their own card belongs
        # to their own page, G169), nobody else's consent to ask.
        return Cast(group=False, title=title, markers={"": "user"}, self_chat=True)
    if not conversation.get("group"):
        other = members[0] if members else {}
        bot = other.get("agent")
        actor = one_to_one_actor(title, entry.get("actor"), agent=None if bot is None else bool(bot))
        if actor.kind == agent_detectors.AGENT:
            marker = "assistant"
        else:
            label = sanitize_id(actor.label)[:48].strip("-")
            marker = f"speaker:{label if label and label != 'unnamed' else 'contact'}"
        # One person across sources (2026-10-28): the reader's ONE address-book card for the other side, by id.
        # Absent (None) keeps the stored one; "" says none or several cards hold the handle now, and clears it.
        posted = other.get("contact") if other.get("contact") is not None else conversation.get("contact")
        card = (contact_identity.clean_card_id(conversation.get("_stored_contact")) if posted is None
                else contact_identity.clean_card_id(posted))
        return Cast(group=False, title=title, markers={"": marker}, actor=actor,
                    contact=card if actor.kind == agent_detectors.PERSON else None)
    names: dict[str, str] = {}
    agents: dict[str, bool] = {}
    cards: dict[str, str | None] = {}
    order: list[str] = []
    for p in stored:
        key = str(p.get("key") or "")
        if ID_RE.match(key) and key not in names:
            order.append(key)
            names[key] = messages_source._clean_name(p.get("name"))
            agents[key] = p.get("kind") == agent_detectors.AGENT
            cards[key] = contact_identity.clean_card_id(p.get("contact"))
    for raw in members:
        key = str(raw.get("key") or "").strip().lower()
        if not ID_RE.match(key):
            continue
        if key not in names:
            order.append(key)
        names[key] = messages_source._clean_name(raw.get("name")) or names.get(key, "")
        if raw.get("contact") is not None:   # absent keeps the stored card; "" clears it (none or several now)
            cards[key] = contact_identity.clean_card_id(raw.get("contact"))
        if raw.get("agent") is not None:
            agents[key] = bool(raw.get("agent"))
    bots = [k for k in order if agents.get(k)]
    agent_key = bots[0] if len(bots) == 1 else None
    used: set[str] = set()
    markers: dict[str, str] = {}
    record: list[dict] = []
    for key in order:
        marker = "assistant" if key == agent_key else f"speaker:{_label(names[key], key, used)}"
        markers[key] = marker
        record.append({"key": key, "marker": marker, **({"name": names[key]} if names[key] else {}),
                       "kind": agent_detectors.AGENT if key == agent_key else agent_detectors.PERSON,
                       **({"contact": cards[key]} if cards.get(key) and key != agent_key else {})})
    return Cast(group=True, title=title, markers=markers, record=record)


def participants_of(fm: dict | None) -> list[dict]:
    return [p for p in (fm or {}).get("participants") or []
            if isinstance(p, dict) and ID_RE.match(str(p.get("key") or "")) and p.get("marker")]


# --- Stored sittings -----------------------------------------------------------------------------------------------


@dataclass
class Sitting:
    source_id: str
    messages: list[ChatMessage] = field(default_factory=list)


def stored_sitting(entry: episode_staging.IndexEntry) -> Sitting | None:
    """A sitting rebuilt from its own episode; ``None`` when its parts disagree (the episode is then left as it is)."""
    keys = entry.fm.get("message_keys")
    if not isinstance(keys, list):
        return None
    parsed = markdown_parser.parse(entry.path)
    body = parsed.body
    stamps = evidence.turn_stamps(parsed.frontmatter)
    extras = turn_extras.by_offset(parsed.frontmatter)
    senders = {p["marker"]: p["key"] for p in participants_of(parsed.frontmatter)}
    lines = body.split("\n") if body else []
    if len(lines) != len(keys):
        return None
    starts: dict[int, str] = {}
    offset = 0
    for line, key in zip(lines, keys):
        starts[offset] = str(key)
        offset += len(line) + 1
    messages: list[ChatMessage] = []
    offset = 0
    previous: str | None = None
    for i, (line, key) in enumerate(zip(lines, keys)):
        marker, sep, text = (line.partition(": ") if not line.startswith("speaker:")
                             else messages_source._split_speaker(line))
        ts = episode_staging.normalise_timestamp((stamps.get(offset) or {}).get("ts")) or previous
        if not sep or not ts or marker not in ("user", "assistant") and not marker.startswith("speaker:"):
            return None
        stored = extras.get(offset) or {}
        message = ChatMessage(key=str(key), ts=ts, from_me=marker == "user", text=text, order=2 * i + 1,
                              sender=senders.get(marker) if marker != "user" else None,
                              edited=stored.get("edited") is True,
                              forwarded_from=stored.get("forwarded_from") or None)
        message.files = [f for f in stored.get("attachments") or [] if isinstance(f, dict)]
        message.attachments = len(message.files)
        reply = stored.get("reply_to")
        if isinstance(reply, int) and not isinstance(reply, bool):
            message.reply_to = starts.get(reply)
        elif isinstance(reply, dict) and reply.get("ref"):
            message.reply_to = str(reply["ref"])
        message.reactions = [{"from_me": r.get("by") == "user", "kind": r.get("kind"),
                              **({"emoji": r["emoji"]} if r.get("emoji") else {}),
                              **({"sender": senders[r["by"]]} if r.get("by") in senders else {})}
                             for r in stored.get("reactions") or [] if isinstance(r, dict) and r.get("kind")]
        messages.append(message)
        previous = ts
        offset += len(line) + 1
    for gone in turn_extras.unsent(parsed.frontmatter):
        ts = episode_staging.normalise_timestamp(gone.get("ts"))
        if not gone.get("ref") or not ts:
            continue
        before = sum(1 for at in starts if at < int(gone["at"]))
        messages.append(ChatMessage(key=str(gone["ref"]), ts=ts, from_me=gone.get("speaker") == "user", text="",
                                    unsent=True, order=2 * before, sender=senders.get(str(gone.get("speaker") or ""))))
    return Sitting(source_id=str(entry.fm.get("source_id")), messages=messages)


def _instant(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def apply_reactions(by_key: dict[str, ChatMessage], reactions: list[ChatReaction], counts: Counts) -> None:
    """Each reaction onto its message, in the order made: one per reactor (a new one replaces theirs), a removal drops
    theirs. A reaction to a message not held here, or deleted, is counted and dropped."""
    for r in sorted(reactions, key=lambda r: (_instant(r.ts), r.order)):
        target = by_key.get(r.target)
        if target is None or target.unsent:
            counts.reactions_orphaned += 1
            continue

        def mine(x: dict) -> bool:
            return bool(x.get("from_me")) == r.from_me and (r.from_me or x.get("sender") == r.sender)

        target.reactions = [x for x in target.reactions if not mine(x)]
        if not r.remove:
            target.reactions.append({"from_me": r.from_me, "kind": r.kind, **({"emoji": r.emoji} if r.emoji else {}),
                                     **({"sender": r.sender} if r.sender and not r.from_me else {})})
        counts.reactions_kept += 1


def plan_sittings(spec: ChatSpec, cid: str, stored: list[Sitting], incoming: list[ChatMessage],
                  reactions: list[ChatReaction], counts: Counts, *, gap: timedelta = messages_source.SITTING_GAP,
                  reserved: frozenset[str] = frozenset()) -> tuple[list[tuple[str, list[ChatMessage]]], list[str]]:
    """The Messages algorithm (`messages_source.plan_sittings`), keyed by this spec: incoming messages replace stored
    ones with the same key (an edit keeps its reactions), reactions land, what was said is split again, each deleted
    placeholder joins the sitting nearest it, and a resulting sitting keeps the earliest stored key it holds."""
    by_key: dict[str, ChatMessage] = {}
    owner: dict[str, str] = {}
    for sitting in stored:
        for m in sitting.messages:
            by_key[m.key] = m
            owner[m.key] = sitting.source_id
    for m in incoming:
        old = by_key.get(m.key)
        if old is not None:
            m.order = old.order
            if not m.unsent and not m.reactions and not m.reactions_final:
                m.reactions = old.reactions
            if not m.unsent and m.reply_to is None:
                m.reply_to = old.reply_to
            if old.text and not m.unsent and old.text != m.text:
                m.edited = True
        by_key[m.key] = m
    apply_reactions(by_key, reactions, counts)
    said = messages_source.split_sittings([m for m in by_key.values() if not m.unsent], gap)
    for gone in (m for m in by_key.values() if m.unsent):
        if said:
            messages_source._nearest_run(said, gone).append(gone)
    planned: list[tuple[str, list[ChatMessage]]] = []
    used: set[str] = set()
    order = [s.source_id for s in stored]
    for run in said:
        run.sort(key=lambda m: (_instant(m.ts), m.order))
        spoken = [m for m in run if not m.unsent]
        mine = [sid for sid in order if sid not in used and any(owner.get(m.key) == sid for m in spoken)]
        sid = mine[0] if mine else f"{spec.prefix}{cid}:{spoken[0].key}"
        if sid in used or (not mine and sid in reserved):
            sid = f"{spec.prefix}{cid}:{spoken[0].key}-{len(planned) + 1}"
        used.add(sid)
        planned.append((sid, run))
    return planned, [s for s in order if s not in used]


def sitting_draft(spec: ChatSpec, cid: str, source_id: str, messages: list[ChatMessage], cast: Cast) -> EpisodeDraft:
    """One sitting's episode: a line per message said, its signals beside the words, who each marker is."""
    spoken = [m for m in messages if not m.unsent]
    index_of = {m.key: i for i, m in enumerate(spoken)}
    turns: list[Turn] = []
    unsent: list[dict] = []
    for m in messages:
        marker = cast.marker(m.from_me, m.sender)
        if m.unsent:
            unsent.append({"before": len(turns), "speaker": marker, "ts": m.ts, "ref": m.key})
            continue
        extras: dict = {}
        if m.reactions:
            extras["reactions"] = [{"by": cast.marker(bool(r.get("from_me")), r.get("sender")), "kind": r.get("kind"),
                                    **({"emoji": r["emoji"]} if r.get("emoji") else {})} for r in m.reactions]
        if m.reply_to:
            extras["reply_to"] = index_of[m.reply_to] if m.reply_to in index_of else {"ref": m.reply_to}
        if m.files:
            extras["attachments"] = m.files
        if m.edited:
            extras["edited"] = True
        if m.forwarded_from:
            extras["forwarded_from"] = m.forwarded_from
        turns.append(Turn(m.text, marker, m.ts, extras=extras or None))
    first, last = spoken[0].ts, spoken[-1].ts
    if cast.group:
        said = {cast.marker(m.from_me, m.sender) for m in messages} | {
            cast.marker(bool(r.get("from_me")), r.get("sender")) for m in messages for r in m.reactions}
        record = {"group": True, "participants": [p for p in cast.record if p["marker"] in said]}
        title = f"{spec.label} · {cast.title or 'group'} · {first[:10]}"
    elif cast.self_chat:
        record = {"self_chat": True}
        title = f"{spec.label} · notes to yourself · {first[:10]}"
    else:
        actor = cast.actor or one_to_one_actor(cast.title, None, agent=None)
        record = {"correspondent": {**actor.to_dict(), **({"contact": cast.contact} if cast.contact else {})}}
        title = (f"{spec.label} · {first[:10]}" if actor.label == agent_detectors.UNNAMED
                 else f"{spec.label} with {actor.label} · {first[:10]}")
    return EpisodeDraft(
        title=title, source_id=source_id, source_updated_at=last, timestamp=first,
        original_date=episode_ids.id_day(first), source=spec.origin, origin=spec.origin, turns=turns, unsent=unsent,
        extra={"conversation": cid, "service": spec.label, **record, "message_count": len(spoken),
               "from_person": sum(1 for m in spoken if m.from_me), "sitting_first_at": first,
               "sitting_last_at": last, "message_keys": [m.key for m in spoken]},
        writer=spec.writer,
    )


#: What a sitting's draft decides beyond its words: re-recorded even when the words did not move (`messages_source`).
RECORD_KEYS = ("correspondent", "title", "participants", "self_chat")


def _stage(drafts: list[EpisodeDraft], episodes_dir: Path, index: dict, *, deleted: list[str] = (),
           bank: str | None = None) -> tuple[episode_staging.StageResult, int]:
    staged = episode_staging.stage(drafts, episodes_dir, deleted_source_ids=list(deleted), bank=bank)
    recorded = 0
    for draft, verdict in zip(drafts, staged.verdicts):
        entry = index.get(str(draft.source_id)) if verdict == "skipped" else None
        if entry is None:
            continue
        wanted = {k: (draft.title if k == "title" else draft.extra.get(k)) for k in RECORD_KEYS}
        if all(entry.fm.get(k) == wanted[k] for k in RECORD_KEYS):
            continue
        if episode_staging.reattribute(entry.path, extra=wanted, queue_for_sleep=draft.queue_for_sleep):
            recorded += 1
            staged.paths.append(f"{episodes_dir.name}/{entry.path.name}")
    return staged, recorded


def _entries(spec: ChatSpec, index: dict, cid: str) -> dict[str, episode_staging.IndexEntry]:
    prefix = f"{spec.prefix}{cid}:"
    return {sid: e for sid, e in index.items() if sid.startswith(prefix) and not e.fm.get("source_deleted_at")}


def _keys(entry: episode_staging.IndexEntry) -> set[str]:
    return set(entry.fm.get("message_keys") or []) | {str(u["ref"]) for u in turn_extras.unsent(entry.fm)
                                                       if u.get("ref")}


def _touches(entry: episode_staging.IndexEntry, incoming: list[ChatMessage], gap: timedelta) -> bool:
    keys = _keys(entry)
    try:
        lo = _instant(str(entry.fm.get("sitting_first_at"))) - gap
        hi = _instant(str(entry.fm.get("sitting_last_at"))) + gap
    except (TypeError, ValueError):
        return bool(keys & {m.key for m in incoming})
    return any(m.key in keys or lo <= _instant(m.ts) <= hi for m in incoming)


# --- Ingest -------------------------------------------------------------------------------------------------------


def ingest(memory_path: Path, spec: ChatSpec, conversation: dict, messages: list[ChatMessage],
           reactions: list[ChatReaction] = (), *, bank: str | None = None, counts: Counts | None = None) -> dict:
    """Stage one batch of one ticked conversation. Raises :class:`PayloadError` (422) or :class:`NotSelected` (409);
    nothing is written then. ``conversation``: ``{id, name?, group?, members?: [{key, name?, agent?}]}``."""
    memory_path = Path(memory_path)
    counts = counts or Counts()
    cid = str(conversation.get("id") or "")
    if not ID_RE.match(cid):
        raise PayloadError("a conversation id is the reader's hash of the chat, 16–64 hex characters")
    if len(messages) + len(reactions) > MAX_MESSAGES_PER_REQUEST:
        raise PayloadError(f"at most {MAX_MESSAGES_PER_REQUEST} messages per request")
    entry = load_settings(memory_path, spec)["conversations"].get(cid)
    if not entry or not entry.get("ticked"):
        raise NotSelected(f"This conversation isn't ticked on the Sources page → {spec.label}, so nothing was saved.")
    start = entry.get("reads_from") or EPOCH
    lo = _instant(start)
    incoming: dict[str, ChatMessage] = {}
    for m in messages:
        counts.seen += 1
        if _instant(m.ts) < lo:
            counts.before_start += 1
            continue
        incoming[m.key] = m          # a later row for the same key wins: an edit, a delete
    kept_reactions = list(reactions)
    counts.reactions += len(kept_reactions)
    batch = list(incoming.values())
    counts.kept += sum(1 for m in batch if not m.unsent)
    counts.unsent += sum(1 for m in batch if m.unsent)
    counts.replies += sum(1 for m in batch if m.reply_to)
    counts.attachments += sum(len(m.files) for m in batch)
    counts.forwards += sum(1 for m in batch if m.forwarded_from)
    targets = {r.target for r in kept_reactions}
    episodes_dir = memory_path / "episodes"
    with episode_staging.STAGE_LOCK:
        index, _ = episode_staging.scan(episodes_dir)
        mine = _entries(spec, index, cid)
        touched = [e for e in mine.values()
                   if _touches(e, batch, messages_source.SITTING_GAP) or _keys(e) & targets
                   or _keys(e) & {m.key for m in batch}]
        stored: list[Sitting] = []
        unreadable: set[str] = set()
        for e in sorted(touched, key=lambda e: str(e.fm.get("sitting_first_at") or "")):
            sitting = stored_sitting(e)
            if sitting is not None:
                stored.append(sitting)
            else:
                unreadable.add(str(e.fm.get("source_id")))
        planned, gone = plan_sittings(spec, cid, stored, batch, kept_reactions, counts,
                                      reserved=frozenset(unreadable))
        known = [p for e in mine.values() for p in participants_of(e.fm)]
        stored_card = next((c for e in mine.values() if isinstance(e.fm.get("correspondent"), dict)
                            and (c := (e.fm.get("correspondent") or {}).get("contact"))), None)
        cast = cast_for(spec, entry, {**conversation, "group": conversation.get("group", entry.get("group")),
                                      "_stored_contact": stored_card}, known)
        drafts = [sitting_draft(spec, cid, sid, msgs, cast) for sid, msgs in planned
                  if any(not m.unsent for m in msgs)]
        staged, recorded = _stage(drafts, episodes_dir, index, deleted=gone, bank=bank)
    counts.edited += sum(1 for _sid, msgs in planned for m in msgs if m.edited and m.key in incoming)
    return {"conversation": cid, "messages_seen": counts.seen, "kept": counts.kept, "unsent": counts.unsent,
            "edited": counts.edited, "replies": counts.replies, "attachments": counts.attachments,
            "forwards": counts.forwards, "reactions": counts.reactions, "reactions_kept": counts.reactions_kept,
            "reactions_orphaned": counts.reactions_orphaned, "before_start": counts.before_start,
            "sittings": len(drafts), "created": staged.created, "updated": staged.updated,
            "skipped": staged.skipped, "tombstoned": staged.tombstoned, "recorded": recorded,
            "group": cast.group, "paths": staged.paths}


def holding(memory_path: Path, spec: ChatSpec, keys: set[str]) -> dict[str, set[str]]:
    """``conversation -> keys`` for stored messages among ``keys`` — a delete that names only message ids (Telegram's
    private chats) finds its conversation here. Frontmatter only."""
    index, _ = episode_staging.scan(Path(memory_path) / "episodes")
    out: dict[str, set[str]] = {}
    for sid, e in index.items():
        if not sid.startswith(spec.prefix) or e.fm.get("source_deleted_at"):
            continue
        hit = _keys(e) & keys
        if hit:
            out.setdefault(str(e.fm.get("conversation") or ""), set()).update(hit)
    return out


def stored_message(memory_path: Path, spec: ChatSpec, cid: str, key: str) -> ChatMessage | None:
    """One stored message by key (a delete becomes this message with its words dropped)."""
    index, _ = episode_staging.scan(Path(memory_path) / "episodes")
    for e in _entries(spec, index, cid).values():
        if key in _keys(e):
            sitting = stored_sitting(e)
            for m in (sitting.messages if sitting else []):
                if m.key == key:
                    return m
    return None


def live_count(memory_path: Path, spec: ChatSpec) -> int:
    index, _ = episode_staging.scan(Path(memory_path) / "episodes")
    return sum(1 for sid, e in index.items() if sid.startswith(spec.prefix) and not e.fm.get("source_deleted_at"))


def waiting(memory_path: Path, spec: ChatSpec) -> list[dict]:
    """Per conversation, how many messages its unread sittings hold. Frontmatter only."""
    from api.services import bank_index

    names = load_settings(memory_path, spec)["conversations"]
    out: dict[str, dict] = {}
    for f in bank_index.files(Path(memory_path), "episodes"):
        fm = f.frontmatter or {}
        if fm.get("origin") != spec.origin or fm.get("processed") or fm.get("source_deleted_at"):
            continue
        cid = str(fm.get("conversation") or "")
        if not ID_RE.match(cid):
            continue
        row = out.setdefault(cid, {"conversation": cid, "name": (names.get(cid) or {}).get("name") or "",
                                   "group": bool(fm.get("group")), "messages": 0, "sittings": 0})
        row["messages"] += int(fm.get("message_count") or 0)
        row["sittings"] += 1
    return sorted(out.values(), key=lambda r: (-r["messages"], r["name"]))


def utc_from_unix(seconds) -> str | None:
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    try:
        return episode_ids.to_utc_iso(datetime.fromtimestamp(value, tz=timezone.utc).replace(microsecond=0))
    except (OverflowError, OSError, ValueError):
        return None
