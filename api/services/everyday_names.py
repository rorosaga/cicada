"""Names the person says in nearly every conversation: naming one is no sign of what a message is about (G149, G115).

2026-10-27 trace: on a message asking to keep a record of the conversation for the person's main project, the prompt
hook raised an open question about that project whose only ties to the message were the project's own name and one
common word. The person's main project and their own name sit in about a third of their conversations, so "the
message names the page" says nothing about whether it is about the page's open question.

This module says which pages those are, from the bank alone — never a hardcoded name (portability): a page is
**everyday** when its name, or an alias of it, is said in at least :data:`SHARE` of the person's most recent
:data:`WINDOW` conversations (the derived word index, ``search_index``), once the bank holds at least
:data:`MIN_CONVERSATIONS` of them. The owner's own page is everyday by definition (G117). Read-only, engine-free,
cached per bank for :data:`TTL_S`; an unready index answers "not everyday" (the gate then works as before).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from api.services import search_index, text_fold

#: A name said in at least this share of the recent conversations is everyday. Measured 2026-10-27 on the owner's bank
#: (latest 200 conversations, each page's own name): the owner's name 36%, their main project 34%, the assistant's name
#: 32%, then a gap down to a cluster at 14–18% (the city they live in, a code host, a harness).
SHARE = 0.25
WINDOW = 200
MIN_CONVERSATIONS = 20
TTL_S = 600.0
#: Episode origins that are conversations; a harness session is one too (its ``harness`` is set).
CONVERSATION_ORIGINS = frozenset({"chatgpt-export", "claude-export", "imessage", "whatsapp", "telegram-chats", "telegram", "mcp", "codex",
                                  "cursor", "gemini-cli", "claude-code", "relay"})
_NOT_CONVERSATIONS = frozenset({"saved-link", "inbox"})

_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str], tuple[float, bool]] = {}
_RECENT: dict[str, tuple[float, frozenset[int]]] = {}


def _recent_conversations(reader: search_index.Reader, key: str) -> frozenset[int]:
    now = time.monotonic()
    with _LOCK:
        hit = _RECENT.get(key)
    if hit and now - hit[0] < TTL_S:
        return hit[1]
    rows = reader.conn.execute("SELECT id, meta FROM docs WHERE kind = 'episode'").fetchall()
    convo: list[tuple[str, int]] = []
    for doc_id, raw in rows:
        try:
            meta = json.loads(raw)
        except (TypeError, ValueError):
            continue
        origin = str(meta.get("origin") or "")
        if origin in _NOT_CONVERSATIONS or meta.get("index_only"):
            continue
        if origin in CONVERSATION_ORIGINS or str(meta.get("harness") or ""):
            convo.append((str(meta.get("timestamp") or ""), int(doc_id)))
    convo.sort(reverse=True)
    ids = frozenset(i for _ts, i in convo[:WINDOW])
    with _LOCK:
        _RECENT[key] = (now, ids)
    return ids


def _said_in(reader: search_index.Reader, phrase: str) -> set[int]:
    words = text_fold.words(phrase)
    if not words:
        return set()
    match = '"' + " ".join(words) + '"'
    sql = f"SELECT DISTINCT rowid >> {search_index.ROW_BITS} FROM pas WHERE pas MATCH ?"
    try:
        return {int(r[0]) for r in reader.conn.execute(sql, (match,))}
    except Exception:  # noqa: BLE001 — a phrase FTS cannot parse is no evidence either way
        return set()


def share(memory_path: Path, names: list[str]) -> float | None:
    """The share of the recent conversations that say any of ``names``; ``None`` when the index is not ready or the
    bank has too few conversations to say."""
    try:
        with search_index.Reader(Path(memory_path)) as reader:
            recent = _recent_conversations(reader, str(memory_path))
            if len(recent) < MIN_CONVERSATIONS:
                return None
            said: set[int] = set()
            for name in names:
                said |= _said_in(reader, name) & recent
            return len(said) / len(recent)
    except Exception:  # noqa: BLE001 — no index is an ordinary state
        return None


def is_everyday(memory_path: Path | None, entity_id: str, names: list[str], *, owner_id: str | None = None) -> bool:
    """Is ``entity_id`` (spelt ``names``) a page the person names in nearly every conversation? Cached per bank."""
    entity_id = str(entity_id or "").strip()
    if not entity_id or memory_path is None:
        return False
    if owner_id and entity_id == owner_id:
        return True
    key = (str(memory_path), entity_id)
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(key)
    if hit and now - hit[0] < TTL_S:
        return hit[1]
    measured = share(Path(memory_path), [n for n in names if len(n) >= 3])
    verdict = measured is not None and measured >= SHARE
    with _LOCK:
        _CACHE[key] = (now, verdict)
    return verdict


def owner_id(memory_path: Path | None) -> str | None:
    """The person's own page (G117, ``_state.md``'s cursor), or ``None``."""
    if memory_path is None:
        return None
    from api.services import state_dictionary

    try:
        state = state_dictionary.read_state(Path(memory_path)) or {}
    except Exception:  # noqa: BLE001
        return None
    return str(state.get("owner_id") or "").strip() or None


def reset() -> None:
    """Forget every cached answer (tests)."""
    with _LOCK:
        _CACHE.clear()
        _RECENT.clear()
