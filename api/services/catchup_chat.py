"""The in-app catch-up chat (ruling 48 (8), vision item 10): a conversation, not an interrogation.

The questions come from the inbox, most-used page first (``page_use``, already the order ``GET /inbox`` serves), in
their plain words (``inbox_wording``). The person may answer with a tap — the inbox's own resolver, held for Undo in
the app — or in their own words. Words go through :func:`turn`: ONE model call on the person's chosen engine (the Ask
path's seam, ``engine_select.resolve_settings(user_triggered=True)``: rulings 4/31/46 — a person asking is a person
present, and never a metered key nobody chose) that answers like a person would — a follow-up, the same question in
other words, or a move to a related question — and says how it read their words.

Nothing here writes an answer. A reading is a PROPOSAL the app applies through ``POST /inbox/{id}/resolve`` (the same
resolver and Undo window as a tap), and only when it rests on the person's own words: its ``quote`` must be found in
what they typed (exact, whitespace, case — ``evidence.locate``, never fuzzy), and a free-text ``answer`` too. A
question about who someone is (a same-person pair, a name) is never applied from a reading: the app shows it as a
one-tap confirmation (ruling 41 — identity only on the person's word, and the word here is their tap). Anything the
model cannot ground is dropped and the reply stands alone; the question stays open.

:func:`record` keeps the chat as ONE episode per catch-up session (``episode_staging``, source-keyed, so each post
updates it in place and re-queues it): the person's turns as their own words, Cicada's as its own. Sleep reads it like
any conversation — a follow-up answered in passing becomes memory there, and ruling 29's part 1 may settle a question
from the person's located words. Never into a demo bank.

The harness door is the same conversation with the harness's own model: ``cicada_check_nudges(mode="catchup")``
serves the same questions with the same :func:`context_lines`, and the skill and the ``catch_up`` prompt ask for the
same behaviour. No new MCP tool: a harness agent IS the conversational step.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from loguru import logger

#: The chat's bounds — what the app may send and what a turn hands the model.
MAX_MESSAGE = 2000
MAX_HISTORY = 12
MAX_TURN_TEXT = 600
MAX_UPCOMING = 8
MAX_REPLY = 600
MAX_RECORD_TURNS = 80
#: A catch-up session id: the app's own UUID-ish token (``transcript_capture``'s session-id shape).
_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
_ITEM_RE = re.compile(r"^inbox-[A-Za-z0-9._-]{1,120}$")

#: What the model may say it is doing next.
MOVES = ("stay", "next", "later", "pass", "stop")
#: Kinds whose reading is never applied, only offered for the person's tap (ruling 41).
_IDENTITY_KINDS = frozenset({"merge_suggestion"})

SYSTEM_PROMPT = (
    "You are Cicada, the person's own memory, catching up with them in a short, warm chat — a conversation, never an "
    "interrogation. You are asking about ONE open question (CURRENT). Read what they just said and answer like a "
    "person would: if it answers the question, say in a few words what you noted; if it is unclear, ask a short "
    "follow-up or say the question again in other words; if their answer touches another open question (UPCOMING), "
    "you may move to it naturally. Never invent facts, never guess who someone is, never push — 'not now' is fine. "
    "One or two short sentences. Never mention inboxes, options, keys or tools.\n"
    "Reply with JSON only: {\"reply\": str, \"reading\": {\"option_key\": str|null, \"answer\": str|null, "
    "\"quote\": str} | null, \"move\": \"stay\"|\"next\"|\"later\"|\"pass\"|\"stop\", \"next_id\": str|null}.\n"
    "- reading: only when their words answer CURRENT. option_key is one of CURRENT's answer keys; answer is a short "
    "value copied word for word from their message when none of the keys fits (or a name they gave); quote is the "
    "exact words of their message you relied on, copied character for character.\n"
    "- move: stay = keep talking about CURRENT (a follow-up); next = CURRENT is settled or they moved on; later = they "
    "want it another day; pass = they let it go; stop = they want to stop.\n"
    "- next_id: when moving, the UPCOMING id you ask next (pick a related one if their answer touched it), and your "
    "reply asks it in your own words with its reason."
)


@dataclass
class Reading:
    option_key: str | None
    answer: str | None
    quote: str
    confirm: bool

    def to_wire(self) -> dict:
        return {"optionKey": self.option_key, "answer": self.answer, "quote": self.quote, "confirm": self.confirm}


# --------------------------------------------------------------------------- the question and its context


def _item(memory_path: Path, item_id: str, today: str):
    """The served item (``GET /inbox``'s shape: options labelled, the plain question and reason), or None."""
    from api.services import inbox_context, inbox_service

    if not _ITEM_RE.match(item_id or ""):
        return None
    path = Path(memory_path) / "inbox" / f"{item_id}.md"
    if not path.is_file():
        return None
    ctx = inbox_context.InboxContext(memory_path, today=today)
    try:
        return inbox_service._item_from_file(path, today=today, context=ctx), ctx
    except Exception as exc:  # noqa: BLE001 — an unreadable item is simply not asked
        logger.warning(f"catch-up: {item_id} unreadable: {type(exc).__name__}")
        return None


def answer_keys(item) -> list[dict]:
    """``[{key, label}]`` the model may pick, in the item's own keys. A same-person pair has none stored: it is
    asked as ``same`` / ``different``, which the app turns into the inbox's merge / reject."""
    if item.kind.value == "merge_suggestion":
        return [{"key": "same", "label": "Yes, the same"}, {"key": "different", "label": "No, different"}]
    return [{"key": o.key, "label": o.label} for o in item.options if o.key and o.label]


def context_lines(memory_path: Path, entity_id: str, ctx=None, *, limit: int = 4) -> list[str]:
    """What Cicada holds on the question's page, for a follow-up: its kind, when it was last said and in how many
    conversations, and a few current beliefs in their own sentences. Shared by the app's turn and the harness's
    ``mode="catchup"`` so both doors converse from the same facts."""
    from api.services import inbox_context
    from api.services.claims import is_current

    if not entity_id:
        return []
    ctx = ctx or inbox_context.InboxContext(memory_path, today=date.today().isoformat())
    page = ctx.entity(entity_id)
    if page is None:
        return []
    fm = page.frontmatter or {}
    head = [str(fm.get("type") or "page")]
    if fm.get("last_referenced"):
        head.append(f"last said {fm.get('last_referenced')}")
    eps = fm.get("source_episodes")
    if isinstance(eps, list) and eps:
        head.append(f"in {len(eps)} conversation{'s' if len(eps) != 1 else ''}")
    lines = [f"{fm.get('name') or entity_id}: " + ", ".join(head)]
    beliefs = [c for c in ctx.claims(entity_id) if is_current(c) and str(getattr(c, "text", "") or "").strip()]
    beliefs.sort(key=lambda c: str(getattr(c, "recorded_at", "") or getattr(c, "valid_from", "") or ""), reverse=True)
    for c in beliefs[:limit]:
        lines.append("- " + " ".join(str(c.text).split())[:200])
    return lines


# --------------------------------------------------------------------------- one turn


def _clip(text, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def _history(history: list) -> list[dict]:
    out = []
    for turn in (history or [])[-MAX_HISTORY:]:
        if not isinstance(turn, dict):
            continue
        who = "you" if str(turn.get("who") or "") == "you" else "cicada"
        text = _clip(turn.get("text"), MAX_TURN_TEXT)
        if text:
            out.append({"who": who, "text": text})
    return out


def _prompt(item, ctx, memory_path: Path, message: str, history: list[dict], upcoming: list[dict]) -> str:
    current = {
        "id": item.id,
        "ask": item.spoken_question or item.question or item.title,
        "why": item.spoken_reason or "",
        "answers": answer_keys(item),
        "free_answer": bool(item.allow_other or item.asks == "name" or not item.options),
        "what_i_have": context_lines(memory_path, item.entity_id, ctx),
    }
    lines = ["CURRENT: " + json.dumps(current, ensure_ascii=False)]
    if upcoming:
        lines.append("UPCOMING: " + json.dumps(upcoming, ensure_ascii=False))
    if history:
        lines.append("CHAT SO FAR:")
        lines.extend(f"{t['who']}: {t['text']}" for t in history)
    lines.append("THEY JUST SAID: " + message)
    return "\n".join(lines)


def _json(raw: str) -> dict | None:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _located(message: str, words) -> str | None:
    """``words`` as they stand in ``message`` (the person's own characters), or None when they are not there."""
    from api.services import evidence

    text = str(words or "").strip().strip("\"'“”‘’").strip()
    if not text:
        return None
    hit = evidence.locate(message, text)
    return message[hit[0]:hit[1]] if hit else None


def ground(item, message: str, data: dict) -> Reading | None:
    """The model's reading, kept only where it rests on the person's words; None otherwise. Never fuzzy."""
    raw = data.get("reading")
    if not isinstance(raw, dict):
        return None
    quote = _located(message, raw.get("quote"))
    if quote is None:
        return None
    keys = {a["key"] for a in answer_keys(item)}
    key = str(raw.get("option_key") or "").strip() or None
    if key is not None and key not in keys:
        key = None
    answer = raw.get("answer")
    answer = _located(message, answer) if answer else None
    if key is None and answer is None:
        return None
    if answer is not None and key is None and not (item.allow_other or item.asks == "name" or not item.options):
        return None   # a closed question answered only in free words: the person picks, Cicada does not
    identity = item.kind.value in _IDENTITY_KINDS or item.asks == "name"
    return Reading(option_key=key, answer=answer, quote=quote, confirm=identity)


def turn(memory_path: Path, item_id: str, message: str, history: list, upcoming: list[str], llm_fn,
         *, today: str | None = None) -> dict:
    """One turn: ``{reply, reading, move, nextId, engine: True}``. ``llm_fn(system, prompt) -> str``. Raises
    ``LookupError`` for an item that is not open, ``ValueError`` for an empty message."""
    today = today or date.today().isoformat()
    message = str(message or "").strip()[:MAX_MESSAGE]
    if not message:
        raise ValueError("Say something first.")
    found = _item(memory_path, item_id, today)
    if found is None:
        raise LookupError(item_id)
    item, ctx = found
    if item.status != "pending":
        raise LookupError(item_id)
    nexts: list[dict] = []
    for uid in [u for u in (upcoming or []) if isinstance(u, str) and u != item_id][:MAX_UPCOMING]:
        other = _item(memory_path, uid, today)
        if other is not None and other[0].status == "pending":
            nexts.append({"id": uid, "ask": other[0].spoken_question or other[0].question or other[0].title,
                          "why": other[0].spoken_reason or ""})
    raw = llm_fn(SYSTEM_PROMPT, _prompt(item, ctx, memory_path, message, _history(history), nexts))
    data = _json(raw) or {}
    reply = _clip(data.get("reply"), MAX_REPLY)
    move = str(data.get("move") or "stay").strip().lower()
    if move not in MOVES:
        move = "stay"
    next_id = str(data.get("next_id") or "").strip() or None
    if next_id not in {n["id"] for n in nexts}:
        next_id = None
    reading = ground(item, message, data)
    if not reply:
        # The model said nothing usable: the app keeps the question open and offers the person's own words.
        return {"reply": None, "reading": None, "move": "stay", "nextId": None, "engine": True}
    return {"reply": reply, "reading": reading.to_wire() if reading else None, "move": move, "nextId": next_id,
            "engine": True}


# --------------------------------------------------------------------------- the record


def _instant(value) -> str:
    from api.services import when as when_mod

    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if at.tzinfo is None:
            raise ValueError
    except (TypeError, ValueError):
        at = datetime.now(timezone.utc)
    return when_mod.utc_z(at.astimezone(timezone.utc))


def record(memory_path: Path, session_id: str, turns: list) -> dict:
    """Keep the chat as one episode per session. ``{status, episodeId}``; ``status`` is ``demo`` (nothing written in
    a demo bank), ``empty`` (the person said nothing yet) or the stager's ``created`` / ``updated`` / ``unchanged``."""
    from api.services import demo_guard, episode_ids, episode_staging

    sid = str(session_id or "").strip()
    if not _SESSION_RE.match(sid):
        raise ValueError("A catch-up session id is 8–128 letters, digits, dots, dashes or underscores.")
    if demo_guard.is_demo(memory_path):
        return {"status": "demo", "episodeId": None}
    kept: list[episode_staging.Turn] = []
    for t in (turns or [])[-MAX_RECORD_TURNS:]:
        if not isinstance(t, dict):
            continue
        mine = str(t.get("who") or "") == "you"
        text = str(t.get("text") or "").strip()[: MAX_MESSAGE if mine else MAX_REPLY]
        if text:
            kept.append(episode_staging.Turn(text=text, speaker="user" if mine else "assistant",
                                             ts=_instant(t.get("at"))))
    if not any(t.speaker == "user" for t in kept):
        return {"status": "empty", "episodeId": None}
    first = kept[0].ts or _instant(None)
    draft = episode_staging.EpisodeDraft(
        title="Catching up with Cicada", source_id=f"catchup:{sid}", timestamp=first,
        original_date=episode_ids.id_day(first),
        source="companion_app", origin="catchup", turns=kept, extra={"session_id": sid},
        queue_for_sleep=True, writer="companion_app")
    result = episode_staging.stage([draft], Path(memory_path) / "episodes", bank=Path(memory_path).name)
    status = "created" if result.created else "updated" if result.updated else "unchanged"
    return {"status": status, "episodeId": result.episode_ids.get(draft.source_id)}
