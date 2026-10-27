"""Who was on the other side of a conversation, in words, from the episode's own fields (lean reads, 2026-10-27).

An answer that rests on a conversation said "the assistant", while the episode already knew it was a Claude Code session
(resumable by its id), Instinct over Messages, or a relayed claude.ai chat. :func:`actor` reads only the episode's
frontmatter — ``harness``, ``session_id``, ``source``, ``origin``, ``correspondent``, ``service``, ``relay`` and the
last agent turn's ``model`` — and never guesses: an episode whose fields name nobody answers ``None``, and the caller
says nothing rather than invent a speaker.

The person is the person: an episode they captured alone (a dictation, a note) has no other side, so ``None`` again.
Recall's excerpts, Ask's speaker labels and Ask's "From conversations no page cites" lines all read this one function.
"""
from __future__ import annotations

from pathlib import Path

#: Harnesses whose session id resumes the conversation in that harness (the handshake promises `claude --resume`).
RESUMABLE = {"claude-code": "claude --resume", "codex": "codex resume"}
#: Episode ``source`` values an agent wrote through a tool door (``ask_sources.AGENT_SOURCES``): a saved note, not a
#: captured conversation.
SAVED_NOTE_SOURCES = frozenset({"mcp", "mcp-remote", "cli"})
#: Export origins: the person's own downloaded history from a chat app — the other side is that app's assistant.
EXPORT_APPS = {"chatgpt-export": "ChatGPT", "claude-export": "Claude"}
EXPORT_SUFFIX = ", from the person's exported conversations"
#: A Messages conversation's service, as the person sees it.
MESSAGE_SERVICES = {"iMessage": "Messages", "SMS": "Messages", "RCS": "Messages"}


def _label(harness: str) -> str:
    from api.services.source_overview import HARNESS_LABELS

    return HARNESS_LABELS.get(harness, harness)


def _last_model(fm: dict) -> str | None:
    turns = fm.get("turns")
    if not isinstance(turns, list):
        return None
    for turn in reversed(turns):
        if isinstance(turn, dict) and turn.get("speaker") == "assistant" and turn.get("model"):
            return str(turn["model"]).strip() or None
    return None


def actor(fm: dict | None, *, ids: bool = True) -> str | None:
    """The other side of this episode in words, or ``None`` when its own fields do not say.

    - a hook-captured agent session: ``a Claude Code session (id <session>, resumable, model <m>)`` — "resumable"
      only for a harness whose id resumes it (:data:`RESUMABLE`), the model only when its last agent turn recorded it;
    - an agent's saved note: ``an agent's saved note from a Claude Code session (id <session>)``;
    - a turn a hookless app relayed (ruling 32): ``Claude, relayed through the remote connector``;
    - a texted correspondent: ``Instinct (an AI agent), over Messages`` / ``<name>, over Messages``;
    - an export: ``ChatGPT, from the person's exported conversations``.

    ``ids=False`` drops the parenthesis (session id, resumable, model): Ask's speaker label on every quoted line, where
    the id would repeat; the reply's own conversation lines carry it.
    """
    if not isinstance(fm, dict):
        return None
    harness = str(fm.get("harness") or "").strip()
    session = str(fm.get("session_id") or "").strip()
    source = str(fm.get("source") or "").strip()
    origin = str(fm.get("origin") or "").strip()
    if isinstance(fm.get("relay"), dict):
        return f"{_label(harness) if harness else 'an app'}, relayed through the remote connector"
    if harness and harness != "unknown" and (session or source in SAVED_NOTE_SOURCES):
        label = _label(harness)
        if source in SAVED_NOTE_SOURCES:
            return f"an agent's saved note from a {label} session" + (f" (id {session})" if session and ids else "")
        if not ids:
            return f"a {label} session"
        parts = []
        if session:
            parts.append(f"id {session}")
            if harness in RESUMABLE:
                parts.append("resumable")
        model = _last_model(fm)
        if model:
            parts.append(f"model {model}")
        return f"a {label} session" + (f" ({', '.join(parts)})" if parts else "")
    corr = fm.get("correspondent")
    if isinstance(corr, dict) and str(corr.get("name") or "").strip():
        name = str(corr["name"]).strip()
        service = str(fm.get("service") or "").strip()
        over = f", over {MESSAGE_SERVICES.get(service, service)}" if service else ""
        kind = str(corr.get("kind") or "")
        return f"{name} (an AI agent){over}" if kind == "agent" else f"{name}{over}"
    if origin in EXPORT_APPS:
        return f"{EXPORT_APPS[origin]}{EXPORT_SUFFIX}"
    if source in SAVED_NOTE_SOURCES:
        return "an agent's saved note"
    return None


def actor_for(memory_path: Path, episode_id: str, *, ids: bool = True) -> str | None:
    """:func:`actor` of one stored episode, read through the bank index; ``None`` for a missing or unreadable one.
    ``ids=False`` for a caller without the person's verbatim words (a remote connection without ``sources``): the
    agent is named, its session id is not — an id resumes the conversation's words."""
    from api.services import bank_index, episode_ids

    if not episode_ids.EPISODE_ID_RE.match(str(episode_id or "")):
        return None
    try:
        f = bank_index.file(memory_path, "episodes", f"{episode_id}.md")
    except Exception:  # noqa: BLE001 — a derived label never fails a read
        return None
    return actor(f.frontmatter, ids=ids) if f is not None else None
