"""The in-app catch-up chat (ruling 48 (8), vision item 10): a conversation, not an interrogation.

The questions come from the inbox, most-used page first (``page_use``, already the order ``GET /inbox`` serves), in
their plain words (``inbox_wording``). The person may answer with a tap — the inbox's own resolver, held for Undo in
the app — or in their own words. Words go through :func:`turn`: ONE model call on the person's chosen engine (the Ask
path's seam, ``engine_select.resolve_settings(user_triggered=True)``: rulings 4/31/46 — a person asking is a person
present, and never a metered key nobody chose) that answers like a person would — a follow-up, the same question in
other words, or a move to a related question — and says how it read their words.

Nothing here writes an answer: the app applies each reading through ``POST /inbox/{id}/resolve``, the same resolver
and Undo window as a tap. **When the person's own words clearly answer, it applies at once and says so in one line with
Undo; there is no Yes button (owner 2026-11-05: "if the agent is going to ask for confirmation on everything eventhough
i just told him then thats bad user experience", replacing a coordinator's call on #509).** The model judges clarity in
context, and a hedge from the person about their own life is still their answer; a misread costs one Undo. One message
may answer several things: every grounded part is returned, each on its own question (a chain's pair, or an upcoming
question), and the app holds them as one answer under one Undo. Each part must rest on the person's words: its
``quote`` is found in what they typed (exact, whitespace, case: ``evidence.locate``, never fuzzy), and a free-text
``answer`` too. What cannot be grounded is dropped and its question stays open; so is a question given two answers it
cannot hold together, since the resolver closes a question with one. Who someone is stays on the person's own words
(rulings 29, 41), which is what the quote proves, and a join stays undoable through the same hold.

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

SYSTEM_PROMPT = (
    "You are Cicada, the person's own memory, catching up with them in a short, warm chat — a conversation, never an "
    "interrogation. You are asking about ONE open question (CURRENT). Read what they just said in context. When their "
    "words clearly answer, return the readings: they are applied at once and the app says what was noted, so never "
    "ask them to confirm what they just told you, and never say yourself that you noted anything. A hedge such as \"I "
    "believe\" or \"I think\" from the person about their own life is still their answer. One message may settle "
    "several things: return EVERY part it settles, on CURRENT, on each of its pairs and on any UPCOMING question it "
    "answers, never just one. When their words leave something unclear (a mixed status such as one thing working and "
    "another paused is not a clean answer), return no reading for that part and say in plain words what is unclear; "
    "if it does not answer CURRENT but touches an UPCOMING question, you may move to it naturally. Never invent facts, "
    "never guess who someone is, never push — 'not now' is fine. One or two short sentences at most. Never mention "
    "inboxes, options, keys or tools.\n"
    "Reply with JSON only: {\"reply\": str, \"readings\": [{\"item_id\": str|null, \"option_key\": str|null, "
    "\"answer\": str|null, \"quote\": str} | {\"join\": [str, str], \"quote\": str}], "
    "\"move\": \"stay\"|\"next\"|\"later\"|\"pass\"|\"stop\", \"next_id\": str|null}.\n"
    "- reply: empty when everything they raised is settled and you have nothing to add; else what is unclear, or the "
    "next question in your own words.\n"
    "- readings: one per thing their words answer, [] when none. item_id is the id it answers (CURRENT's, one of "
    "CURRENT's pairs, or an UPCOMING id); option_key is one of that question's answer keys; answer is a short value "
    "copied word for word from their message when no key fits (or a name they gave), and a key plus an answer may go "
    "together in one reading; quote is the exact words of their message you relied on, copied character for "
    "character. A pair is answered \"same\" or \"different\".\n"
    "- join: when they say two of CURRENT's names are one person and no pair holds exactly those two, give the two "
    "names as written, with the quote. Answer the other pairs as usual.\n"
    "- move: stay = keep talking about CURRENT; next = they moved on without answering CURRENT; later = they want it "
    "another day; pass = they let it go; stop = they want to stop.\n"
    "- next_id: when moving, the UPCOMING id you ask next (pick a related one if their answer touched it), and your "
    "reply asks it in your own words with its reason."
)


@dataclass
class Reading:
    item_id: str
    option_key: str | None
    answer: str | None
    quote: str
    #: "A is C" answered on a pair (A, B) the person also parted: A joins C, the page that pair's question never named.
    merge_target: str | None = None
    target_name: str | None = None

    def to_wire(self) -> dict:
        return {"itemId": self.item_id, "optionKey": self.option_key, "answer": self.answer, "quote": self.quote,
                "mergeTarget": self.merge_target, "targetName": self.target_name}


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
    if item.kind.value == "merge_suggestion" and not any(o.key and o.label for o in item.options):
        return [{"key": "same", "label": "Yes, the same"}, {"key": "different", "label": "No, different"}]
    # G227: a name several pages share is answered by picking the page (or "none"), in the item's served keys.
    return [{"key": o.key, "label": o.label} for o in item.options if o.key and o.label]


def context_lines(memory_path: Path, entity_id: str, ctx=None, *, limit: int = 4) -> list[str]:
    """What Cicada holds on the question's page, for a follow-up: its kind, when it was last said and in how many
    conversations, and a few current beliefs in their own sentences. Shared by the app's turn and the harness's
    ``mode="catchup"`` so both doors converse from the same facts."""
    from api.services import inbox_context
    from api.services.claims import is_current, is_mark

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
    beliefs = [c for c in ctx.claims(entity_id)
               if is_current(c) and not is_mark(c) and str(getattr(c, "text", "") or "").strip()]
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


def _chains(memory_path: Path, items: list) -> dict:
    """``{item id: served item}`` for the same-person questions among ``items``, carrying #501's chain and its pairs
    (marked only on the served list). A read that fails costs the pairs, never the turn."""
    from api.services import inbox_service

    if not any(i.kind.value == "merge_suggestion" for i in items):
        return {}
    try:
        return {i.id: i for i in inbox_service.load_inbox(memory_path) if i.chain}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"catch-up: chains unreadable: {type(exc).__name__}")
        return {}


def _pairs(item, chains: dict) -> list[dict]:
    served = chains.get(item.id)
    return [{k: p[k] for k in ("id", "a", "b")} for p in (served.chain_pairs or [])] if served else []


def _prompt(item, ctx, memory_path: Path, message: str, history: list[dict], upcoming: list[dict],
            chains: dict | None = None) -> str:
    served = (chains or {}).get(item.id)
    current = {
        "id": item.id,
        "ask": (served.chain_question if served else None) or item.spoken_question or item.question or item.title,
        "why": item.spoken_reason or "",
        "answers": answer_keys(item),
        "free_answer": bool(item.allow_other or item.asks == "name" or not item.options),
        "what_i_have": context_lines(memory_path, item.entity_id, ctx),
    }
    if served:
        current["pairs"] = _pairs(item, chains)
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


def ground(item, message: str, raw) -> Reading | None:
    """One reading on ``item``, kept only where it rests on the person's words; None otherwise. Never fuzzy."""
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
    return Reading(item_id=item.id, option_key=key, answer=answer, quote=quote)


def _join(raw: dict, message: str, pairs: list, readings: dict[str, Reading]) -> tuple[Reading | None, dict | None]:
    """A person's "A is C" over a chain, as ``(reading, None)``, or ``(None, {a, b})`` when no question can carry it.

    A pair holding exactly those two answers it. Otherwise the resolver can still do it through a pair the same
    message parted, (A, B) with A its subject: resolving that question merges A into C, and B stays apart from both.
    A question the person did not answer is never closed to carry someone else's join."""
    names = raw.get("join")
    quote = _located(message, raw.get("quote"))
    if not (isinstance(names, list) and len(names) == 2 and quote):
        return None, None
    wanted = [" ".join(str(n).split()).casefold() for n in names]
    if wanted[0] == wanted[1]:
        return None, None
    ids: dict[str, tuple[str, str]] = {}
    for pair in pairs:
        ids[pair["a"].casefold()] = (pair["subject"], pair["a"])
        ids[pair["b"].casefold()] = (pair["hint"], pair["b"])
    if not all(w in ids for w in wanted):
        return None, None
    for pair in pairs:
        if {pair["a"].casefold(), pair["b"].casefold()} == set(wanted):
            return Reading(item_id=pair["id"], option_key="same", answer=None, quote=quote), None
    for pair in pairs:
        parted = readings.get(pair["id"])
        subject = pair["a"].casefold()
        if parted is None or parted.option_key != "different" or subject not in wanted:
            continue
        target_id, target_name = ids[wanted[1] if subject == wanted[0] else wanted[0]]
        return Reading(item_id=pair["id"], option_key="same", answer=None, quote=quote, merge_target=target_id,
                       target_name=target_name), None
    return None, {"a": ids[wanted[0]][1], "b": ids[wanted[1]][1]}


def ground_all(message: str, data: dict, current, answerable: dict, pairs: list) -> tuple[list[Reading], list[dict]]:
    """Every part of the answer that rests on the person's words, at most one per question, and the joins no question
    could carry. A question given two different answers holds neither: its one resolve could not keep both."""
    raws = data.get("readings")
    raws = [r for r in raws if isinstance(r, dict)] if isinstance(raws, list) else []
    found: dict[str, Reading] = {}
    torn: set[str] = set()
    for raw in raws:
        if "join" in raw:
            continue
        target = answerable.get(str(raw.get("item_id") or current.id))
        reading = ground(target, message, raw) if target is not None else None
        if reading is None:
            continue
        held = found.get(reading.item_id)
        if held is not None and (held.option_key, held.answer) != (reading.option_key, reading.answer):
            torn.add(reading.item_id)
        found.setdefault(reading.item_id, reading)
    for item_id in torn:
        del found[item_id]
    unjoined: list[dict] = []
    for raw in raws:
        if "join" not in raw:
            continue
        reading, missing = _join(raw, message, pairs, found)
        if missing:
            unjoined.append(missing)
        if reading is not None and reading.item_id not in torn:
            found[reading.item_id] = reading
    return list(found.values()), unjoined


def turn(memory_path: Path, item_id: str, message: str, history: list, upcoming: list[str], llm_fn,
         *, today: str | None = None) -> dict:
    """One turn: ``{reply, readings, unjoined, move, nextId, engine: True}``. ``llm_fn(system, prompt) -> str``.
    Raises ``LookupError`` for an item that is not open, ``ValueError`` for an empty message."""
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
    others: list = []
    for uid in [u for u in (upcoming or []) if isinstance(u, str) and u != item_id][:MAX_UPCOMING]:
        other = _item(memory_path, uid, today)
        if other is not None and other[0].status == "pending":
            others.append(other[0])
    chains = _chains(memory_path, [item, *others])
    nexts = []
    for other in others:
        entry = {"id": other.id, "ask": other.spoken_question or other.question or other.title,
                 "why": other.spoken_reason or "", "answers": answer_keys(other)}
        if other_pairs := _pairs(other, chains):
            entry["pairs"] = other_pairs
        nexts.append(entry)
    answerable = {i.id: i for i in [item, *others]}
    # A chain's pairs are questions of their own. Ids and pages from the served list, so a join can name a page.
    pairs: list[dict] = []
    for pair in _pairs(item, chains):
        member = chains.get(pair["id"])
        if member is None:
            continue
        answerable[pair["id"]] = member
        pairs.append({**pair, "subject": member.entity_id, "hint": member.merge_target_hint})
    for other in others:
        for pair in _pairs(other, chains):
            if pair["id"] in chains:
                answerable.setdefault(pair["id"], chains[pair["id"]])
    raw = llm_fn(SYSTEM_PROMPT, _prompt(item, ctx, memory_path, message, _history(history), nexts, chains))
    data = _json(raw) or {}
    reply = _clip(data.get("reply"), MAX_REPLY)
    move = str(data.get("move") or "stay").strip().lower()
    if move not in MOVES:
        move = "stay"
    next_id = str(data.get("next_id") or "").strip() or None
    if next_id not in {n["id"] for n in nexts}:
        next_id = None
    readings, unjoined = ground_all(message, data, item, answerable, pairs)
    if not reply and not readings and move != "later":
        # The model said nothing usable: the app keeps the question open and offers the person's own words.
        return {"reply": None, "readings": [], "unjoined": [], "move": "stay", "nextId": None, "engine": True}
    return {"reply": reply or None, "readings": [r.to_wire() for r in readings], "unjoined": unjoined, "move": move,
            "nextId": next_id, "engine": True}


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
