"""G237: the Claude models a person's own key can use, kept current without a Cicada release.

The Models API answers, for a key, every model with its ``line`` (haiku, sonnet, opus, …), ``lifecycle`` (active,
deprecated, retired), release date, limits and capabilities. Cicada keeps that answer in its own section of
``model_catalogue.json`` (ids and numbers only, outside every bank) and reads everything from it:

* **Tiers.** small = the newest active model of the ``haiku`` line, standard = ``sonnet``, top = ``opus``. A new model
  in a line takes its tier the day the list names it; no id here has to change. A saved ``anthropic/sonnet`` is the
  plan's alias: the line's newest, whatever that is on the day.
* **A retired id moves forward, in words.** A saved model the list says is retired, or that the API answers 404 for,
  is read with the newest active model of its line; the sentence says so on the engine's card and in the run's detail.
  It is never silent, and a model with no known line is never guessed at: the run stops with the model-not-found words.
* **No key, or no answer yet.** ``DOCUMENTED`` is the floor: the three tier models as the vendor's documentation listed
  them on its date, marked ``documented``. A list that fails keeps the last answer. The floor is never a price.

When it reads: the person's Refresh, the moment a key is saved, and the start of a run on a Claude key when the answer
is over a day old. Never from a page view. It bills nothing (a list read), and the key goes only to the vendor's own
host. Prices do not come from here: the API does not give them (``price_supplement``).
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass

from loguru import logger

from api.services import model_catalogue

SECTION = "anthropic"
ENGINE = "anthropic-api"
KEY_ENV = "ANTHROPIC_API_KEY"
PREFIX = "anthropic/"
#: A key's list stays good for a day, like ``claude --help``'s.
STALE_AFTER_S = 24 * 3600.0
LIST_TIMEOUT_S = 6.0

#: small, standard, top, by the vendor's own model lines.
TIER_LINE = {"small": "haiku", "standard": "sonnet", "top": "opus"}
#: The words a person can save instead of an id; the line's newest. The plan's aliases mean the same.
LINE_ALIASES = ("haiku", "sonnet", "opus", "fable")

#: The floor with no key and no list yet (id, line): the vendor's model list as read 2026-11-04. Replaced by the real
#: list the first time a key reads it.
DOCUMENTED: tuple[tuple[str, str], ...] = (
    ("claude-haiku-5-5", "haiku"), ("claude-sonnet-5-5", "sonnet"), ("claude-opus-5-5", "opus"),
)
#: Ids that list showed as retired on that date, for a key with no list yet. The list, once read, is the answer.
RETIRED_LINES: dict[str, str] = {
    "claude-opus-4-1": "opus", "claude-opus-4-1-20250805": "opus", "claude-opus-4-0": "opus",
    "claude-opus-4-20250514": "opus", "claude-3-opus-20240229": "opus", "claude-3-opus-latest": "opus",
    "claude-sonnet-4-0": "sonnet", "claude-sonnet-4-20250514": "sonnet", "claude-3-7-sonnet-20250219": "sonnet",
    "claude-3-5-sonnet-latest": "sonnet", "claude-3-5-sonnet-20241022": "sonnet",
    "claude-3-5-sonnet-20240620": "sonnet", "claude-3-sonnet-20240229": "sonnet",
    "claude-3-haiku-20240307": "haiku", "claude-3-5-haiku-20241022": "haiku", "claude-3-5-haiku-latest": "haiku",
}
_VERSION = re.compile(r"-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$")

_refreshing = threading.Event()


def is_claude(model: str | None) -> bool:
    """A model a Claude key bills directly: ``anthropic/…`` or a bare ``claude-…``. A router's or another cloud's id
    (``openrouter/anthropic/…``, ``bedrock/…``) is that host's, never this."""
    m = (model or "").strip().lower()
    return m.startswith(PREFIX) or m.startswith("claude-")


def bare(model: str | None) -> str:
    m = (model or "").strip()
    return m[len(PREFIX):] if m.lower().startswith(PREFIX) else m


def stored_id(model_id: str) -> str:
    """How a model is stored in the engine's pref: the same prefix every other key's id wears."""
    return f"{PREFIX}{bare(model_id)}"


def _rows() -> list[dict]:
    rows = model_catalogue.read_section(SECTION).get("models")
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str)] if isinstance(rows, list) else []


def _row(model_id: str) -> dict | None:
    return next((r for r in _rows() if r["id"] == model_id), None)


def newest(line: str) -> str | None:
    """The newest active model of a line: the list's, else the documented floor's."""
    listed = [r for r in _rows() if r.get("line") == line and r.get("lifecycle") == "active"]
    if listed:
        return max(listed, key=lambda r: str(r.get("created") or ""))["id"]
    return next((m for m, ln in DOCUMENTED if ln == line), None)


def tier(name: str) -> str | None:
    """The model of a tier (``small``, ``standard``, ``top``) today, as stored in the pref. ``None`` for no such tier."""
    line = TIER_LINE.get(name)
    model = newest(line) if line else None
    return stored_id(model) if model else None


def default_model() -> str:
    """What the API-key card writes for this provider, and the judge's model on a Claude key: the small tier, as on the
    plan (``agent_disambiguation_model``)."""
    return tier("small") or stored_id(DOCUMENTED[0][0])


def _line_of(model_id: str) -> str | None:
    row = _row(model_id)
    if row and row.get("line"):
        return str(row["line"])
    if model_id in RETIRED_LINES:
        return RETIRED_LINES[model_id]
    return next((ln for m, ln in DOCUMENTED if m == model_id), None)


def _line_from_words(model_id: str) -> str | None:
    """Only after the API has already refused the id: the alternative is a stopped run. The vendor says not to read a
    line from an id for anything else, and nothing else here does."""
    return next((w for w in re.split(r"[^a-z]+", model_id.lower()) if w in LINE_ALIASES), None)


@dataclass(frozen=True)
class Served:
    """The id to send for a saved model, and the sentence when that is not what was saved."""
    model: str
    note: str | None = None


def forward_sentence(old: str, new: str) -> str:
    return f"{old} is no longer offered, so this reads with {new}. Choose another model on the engine's card if you prefer."


def resolve(model: str | None) -> Served:
    """The id a call sends. An alias is its line's newest (no sentence: that is what it means). A retired id is its
    line's newest, with the sentence (and a record for the card)."""
    wanted = bare(model)
    if wanted.lower() in LINE_ALIASES:
        return Served(newest(wanted.lower()) or wanted)
    row = _row(wanted)
    retired = (row.get("lifecycle") == "retired") if row else wanted in RETIRED_LINES
    if retired:
        line = _line_of(wanted)
        target = newest(line) if line else None
        if target and target != wanted:
            note_forwarded(wanted, target)
            return Served(target, forward_sentence(wanted, target))
    return Served(wanted)


def forward_after_refusal(model_id: str) -> Served | None:
    """The API answered 404 for this id: the newest active model of its line, once, with the sentence. ``None`` when
    its line is not known or the line's newest is this very id (a key without access: the refusal stands)."""
    line = _line_of(model_id) or _line_from_words(model_id)
    target = newest(line) if line else None
    if not target or target == model_id:
        return None
    note_forwarded(model_id, target)
    return Served(target, forward_sentence(model_id, target))


def note_forwarded(old: str, new: str) -> None:
    """Remember a move for the card's line. Written on change only: this runs on every call of a run."""
    known = model_catalogue.read_section(SECTION).get("forwarded") or {}
    if isinstance(known, dict) and (known.get(old) or {}).get("id") == new:
        return

    def change(section: dict) -> None:
        section.setdefault("forwarded", {})[old] = {"id": new, "at": time.time()}

    model_catalogue.update_section(SECTION, change)


def forwarded_sentence(model: str | None) -> str | None:
    """The card's line for a saved model that reads with another, while it still does."""
    wanted = bare(model)
    if not wanted or wanted.lower() in LINE_ALIASES:
        return None
    served = resolve(wanted)
    if served.note:
        return served.note
    moved = (model_catalogue.read_section(SECTION).get("forwarded") or {}).get(wanted)
    return forward_sentence(wanted, moved["id"]) if isinstance(moved, dict) and moved.get("id") else None


def max_output(model_id: str) -> int | None:
    value = (_row(model_id) or {}).get("max_tokens")
    return value if isinstance(value, int) and value > 0 else None


def takes_effort(model_id: str, level: str) -> bool:
    """Whether the API takes this effort on this model: the list's capability when read, else by version (it refuses
    effort on the 4.5 Haiku and Sonnet and on anything older)."""
    levels = (_row(model_id) or {}).get("effort")
    if isinstance(levels, list):
        return level in levels
    m = _VERSION.search(model_id)
    if not m:
        return False
    version = (int(m.group(1)), int(m.group(2) or 0))
    if version > (4, 5):
        return True
    return version == (4, 5) and "opus" in model_id


def has_key() -> bool:
    return bool((os.environ.get(KEY_ENV) or "").strip())


def _row_from(info) -> dict | None:
    """One ``ModelInfo`` as the cache keeps it: ids, numbers and enums. A row with no id is the list's shape moving."""
    model_id = getattr(info, "id", None)
    if not isinstance(model_id, str) or not model_id:
        return None
    created = getattr(info, "created_at", None)
    caps = getattr(info, "capabilities", None)
    effort = getattr(caps, "effort", None) if caps is not None else None
    levels = None
    if effort is not None and getattr(effort, "supported", False):
        levels = [lv for lv in ("low", "medium", "high", "xhigh", "max")
                  if getattr(getattr(effort, lv, None), "supported", False)]
    elif effort is not None:
        levels = []
    return {"id": model_id, "name": str(getattr(info, "display_name", "") or ""),
            "line": getattr(info, "line", None), "lifecycle": getattr(info, "lifecycle", None) or "active",
            "created": created.isoformat() if hasattr(created, "isoformat") else None,
            "max_tokens": getattr(info, "max_tokens", None), "max_input": getattr(info, "max_input_tokens", None),
            "effort": levels}


def refresh(*, client=None) -> bool:
    """Read the list now. ``False`` with no key, or on any failure: the last answer stays, the failure is recorded as
    a time only. A list with no usable row is drift (said on the card), never an empty catalogue."""
    if client is None:
        if not has_key():
            return False
        from api.services import anthropic_engine

        try:
            client = anthropic_engine.make_client(timeout=LIST_TIMEOUT_S, max_retries=1)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Claude model list unavailable: {type(exc).__name__}")
            return False
    now = time.time()
    try:
        rows = [r for r in map(_row_from, client.models.list(limit=1000, lifecycle=["active", "deprecated", "retired"]))
                if r is not None]
    except Exception as exc:  # noqa: BLE001 — never the message: it can carry a request id or an account
        logger.warning(f"Claude model list not read: {type(exc).__name__}")
        model_catalogue.update_section(SECTION, lambda section: section.update(checked=now))
        return False
    active = [r for r in rows if r.get("lifecycle") == "active"]

    def change(section: dict) -> None:
        section["checked"] = now
        section["drift"] = not active
        if active:
            section["models"] = rows
            section["at"] = now

    model_catalogue.update_section(SECTION, change)
    if not active:
        logger.warning("Claude model list: no active model in the answer")
    return bool(active)


def refresh_if_stale() -> bool:
    """The start of a run on a Claude key: once a day. A failure waits a day like a success, so a broken network never
    adds a pause to every batch."""
    section = model_catalogue.read_section(SECTION)
    last = section.get("checked") or section.get("at") or 0
    if time.time() - float(last) < STALE_AFTER_S or not has_key():
        return False
    return refresh()


def refresh_in_background() -> None:
    """A key was just saved: read its list without holding the save. One at a time."""
    if _refreshing.is_set():
        return
    _refreshing.set()

    def run() -> None:
        try:
            refresh()
        finally:
            _refreshing.clear()

    threading.Thread(target=run, name="claude-model-list", daemon=True).start()


def card(saved: str | None) -> tuple[list[str], dict]:
    """The API-key card's models for a Claude key and their catalogue. First the saved choice (a tap writes the card's
    first, R-HS7, and must keep it), then small, standard, top, then every other active model, newest first.
    Deprecated and retired ids stay off the list unless saved."""
    section = model_catalogue.read_section(SECTION)
    active = sorted((r for r in _rows() if r.get("lifecycle") == "active"),
                    key=lambda r: str(r.get("created") or ""), reverse=True)
    how = "harness" if active else "documented"
    ordered: list[str] = []
    for tier_name in ("small", "standard", "top"):
        model = tier(tier_name)
        if model and model not in ordered:
            ordered.append(model)
    ordered += [stored_id(r["id"]) for r in active if stored_id(r["id"]) not in ordered]
    saved_id = stored_id(saved) if saved else None
    ids = list(dict.fromkeys(([saved_id] if saved_id else []) + ordered))
    cat = model_catalogue.catalogue(ENGINE, [(m, how) for m in ordered], as_of=section.get("at"),
                                    source="your key" if active else "documented",
                                    drift=bool(section.get("drift")), saved=saved_id)
    return ids, cat
