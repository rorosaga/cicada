"""Keep the signed-in plan account's identity out of memory (perf report 2026-10-24, item 1).

The ``claude`` CLI adds the signed-in account's email address to the context of every call it runs. It does this even
with ``--system-prompt``: on ``claude`` 2.1.310 the CLI's context builder adds ``userEmail`` from the plan's sign-in,
and no flag or variable turns that off while the plan is used. In one benchmark Sleep the extractor wrote that email
onto the owner page as three key facts. No conversation had said it, and it would have followed the person into
every bank.

A model also reads a name out of the address: a newuser benchmark Sleep on dev (2026-10-24) gave the synthetic owner
page an alias made of the two words of the account's address before the ``@``. So the identity has two forms: the
address itself, and, when the part before the ``@`` holds two or more words of three letters or more, those words
together (:func:`_forms`).

``agent_engine.CONTEXT_GUARD`` tells the model the attached context is not part of the request. This module is the
floor under that guard. Stage 1 (:func:`scrub_extraction`) and the merge stage (:func:`scrub_lines`) drop any item
that carries a form, unless the text the item was made from already says that form. The person who types their own
address, or their own full name, keeps it exactly as before, and the evidence rail places its span as it always has.

Only the email is read. Of the account's fields, it is the one the CLI puts in front of the model. The account's
profile name is not filtered by itself, because it is often the owner's own page name.

The value comes from ``claude auth status --json`` on this machine. It is read only when Sleep runs on the Claude
plan (``llm_mode == "agent"``), kept in this process's memory, and never logged, written or sent.
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Callable, Iterable

#: How long a read of the CLI's sign-in is reused. A Sleep drain reads it once; a sign-in change is seen within this.
TTL_S = 600.0
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

_lock = threading.Lock()
_cached: tuple[float, frozenset[str]] | None = None


def _read_claude_account() -> frozenset[str]:
    """The Claude CLI's signed-in email, lowercased, or nothing. Never raises; the value is never logged."""
    from api.services.connections.base import run_cli_sync

    try:
        result = run_cli_sync(["claude", "auth", "status", "--json"], timeout=10.0)
        info = json.loads((result.stdout or "").strip() or "{}") if result.rc == 0 else {}
    except (ValueError, OSError):
        return frozenset()
    email = str((info or {}).get("email") or "").strip().lower() if isinstance(info, dict) else ""
    return frozenset({email}) if _EMAIL.match(email) else frozenset()


#: The reader, swappable in tests (they never spawn the CLI and use a placeholder address).
reader: Callable[[], frozenset[str]] = _read_claude_account


def identities(settings) -> frozenset[str]:
    """The plan account identities to keep out of memory for a run on ``settings``. Empty unless the run is on the
    Claude plan, the only engine that puts the account in front of the model."""
    global _cached
    if str(getattr(settings, "llm_mode", "") or "").strip().lower() != "agent":
        return frozenset()
    with _lock:
        now = time.monotonic()
        if _cached is not None and now - _cached[0] < TTL_S:
            return _cached[1]
        try:
            values = frozenset(v.lower() for v in reader() if v)
        except Exception:  # noqa: BLE001 - an unreadable sign-in costs the floor, never the run
            values = frozenset()
        _cached = (now, values)
        return values


def clear() -> None:
    """Forget the cached read (tests, and a sign-in change)."""
    global _cached
    with _lock:
        _cached = None


_WORD = re.compile(r"[^\W\d_]{3,}")


def _forms(ids: Iterable[str]) -> frozenset[tuple[str, ...]]:
    """Each identity's forms: the address as one piece, and the words before its ``@`` when there are two or more of
    three letters or more (``first.last91`` gives ``("first", "last")``). A one-word part is no name to read."""
    forms: set[tuple[str, ...]] = set()
    for value in ids:
        value = (value or "").strip().lower()
        if not value:
            continue
        forms.add((value,))
        words = tuple(dict.fromkeys(_WORD.findall(value.split("@", 1)[0])))
        if len(words) >= 2:
            forms.add(words)
    return frozenset(forms)


def _says(text: str, form: tuple[str, ...]) -> bool:
    if len(form) == 1:
        return form[0] in text
    return all(re.search(rf"(?<![^\W\d_]){re.escape(word)}(?![^\W\d_])", text) for word in form)


def foreign(ids: Iterable[str], source_text: str) -> frozenset[tuple[str, ...]]:
    """The forms of ``ids`` that ``source_text`` does not itself say: the ones an item may not carry."""
    text = (source_text or "").lower()
    return frozenset(form for form in _forms(ids) if not _says(text, form))


def carries(value, forms: frozenset[tuple[str, ...]]) -> bool:
    """True when ``value`` (text, or a list/dict of text) says any of ``forms`` (from :func:`foreign`),
    case-insensitively: the address anywhere, or every word of a name form as a word."""
    if not forms or value is None:
        return False
    if isinstance(value, dict):
        return any(carries(v, forms) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(carries(v, forms) for v in value)
    text = str(value).lower()
    return any(_says(text, form) for form in forms)


def leaks(value, source_text: str, ids: frozenset[str]) -> bool:
    """True when ``value`` (a model's answer, any shape) carries a plan identity form ``source_text`` does not say."""
    return carries(value, foreign(ids, source_text))


def _without_sentences(text: str, forms) -> str:
    return " ".join(s for s in _SENTENCE.split(text) if not carries(s, forms)).strip()


def scrub_extraction(entities: list, relationships: list, values: list, source_text: str,
                     ids: frozenset[str]) -> int:
    """Drop, in place, every part of one episode's extraction that carries a plan identity the episode does not say.

    An entity named for it is dropped whole. From any other entity, an alias, fact, open question, tag, history
    entry or link carrying it is dropped, and so is a summary sentence or website carrying it. A relationship or
    value carrying it in any field is dropped. Returns how many items went; nothing is logged about which."""
    bad = foreign(ids, source_text)
    if not bad:
        return 0
    dropped = 0
    kept_entities = []
    for entity in entities:
        if not isinstance(entity, dict):
            kept_entities.append(entity)
            continue
        if carries(entity.get("name"), bad):
            dropped += 1
            continue
        for key in ("aliases", "key_facts", "open_questions", "tags", "history_entries", "links"):
            items = entity.get(key)
            if isinstance(items, list):
                kept = [item for item in items if not carries(item, bad)]
                dropped += len(items) - len(kept)
                entity[key] = kept
        for key in ("summary", "description"):
            text = entity.get(key)
            if isinstance(text, str) and carries(text, bad):
                entity[key] = _without_sentences(text, bad)
                dropped += 1
        if carries(entity.get("website"), bad):
            entity["website"] = None
            dropped += 1
        kept_entities.append(entity)
    entities[:] = kept_entities
    for items in (relationships, values):
        kept = [item for item in items if not carries(item, bad)]
        dropped += len(items) - len(kept)
        items[:] = kept
    return dropped


def scrub_lines(body: str, source_text: str, ids: frozenset[str]) -> str:
    """``body`` (markdown a model wrote) without any line, or prose sentence, carrying a plan identity that
    ``source_text`` (everything the model was given) does not say. Unchanged when nothing carries one."""
    bad = foreign(ids, source_text)
    if not bad or not carries(body, bad):
        return body
    out = []
    for line in (body or "").split("\n"):
        if not carries(line, bad):
            out.append(line)
            continue
        stripped = line.lstrip()
        if stripped.startswith(("- ", "* ", "#")) or not stripped:
            continue  # a bullet or heading is one item: it goes whole
        kept = _without_sentences(line, bad)
        if kept:
            out.append(kept)
    return "\n".join(out)
