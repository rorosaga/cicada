"""What the person chose to let Cicada read from a connected service (owner 2026-11-09, ROR-connect-choose).

Connecting a service used to be all or nothing: the sign-in sees everything the person can open and the first sync read
all of it. Now, right after the sign-in, the person picks — **Everything**, or specific containers (Notion pages and
databases, Linear teams and projects) — and nothing is read before they do.

* One small JSON file per connector, ``$CICADA_HOME/connectors/<channel>-scope.json``, outside every bank and git: the
  choice belongs to the sign-in (the account), not to a bank. It holds ids, titles and a kind, nothing else. Disconnect
  removes it with the cursors (``tier2.forget`` sweeps ``<channel>-*.json``).
* **Three states.** ``pending`` — just connected, the person has not chosen, so no sync reads anything; ``everything``;
  ``chosen`` with the list. **No file means ``everything``**: a connection made before this existed keeps working
  exactly as it did. Only a *fresh* sign-in (no token before it) writes ``pending``; signing in again after a lapse
  never resets an earlier choice.
* **Un-choosing stops reading, it deletes nothing.** What a container already put in the bank stays (ruling 62's
  spirit: nothing the person had is taken away by a settings change); the person removes it from its page. The sheet
  says so in words (:data:`UNCHOOSE_WORDS`).
* The choice is part of the sync's cursor key (:func:`signature`): when it changes, an adapter starts that part of the
  walk again rather than trust a position made under another choice.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

EVERYTHING, CHOSEN, PENDING = "everything", "chosen", "pending"
MODES = (EVERYTHING, CHOSEN)
MAX_ITEMS = 500
#: What the picker says about un-choosing, in the person's words (one place, so the app and the API agree).
UNCHOOSE_WORDS = ("Cicada stops reading anything you take out. What it already saved from it stays in your memory "
                  "until you remove it from its page.")
CHOOSE_WORDS = "Choose what Cicada may read, and nothing is read until you do."


def _path(channel: str) -> Path:
    from api.services.auth import cicada_home

    return cicada_home() / "connectors" / f"{channel}-scope.json"


def _clean_item(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    item_id = str(raw.get("id") or "").strip()
    if not item_id or len(item_id) > 120 or any(c in item_id for c in "\n\r\x00"):
        return None
    title = " ".join(str(raw.get("title") or "").split())[:200] or "Untitled"
    kind = " ".join(str(raw.get("kind") or "").split())[:24] or "page"
    return {"id": item_id, "title": title, "kind": kind}


def clean_items(raw) -> list[dict]:
    """The submitted list as stored: well-formed, de-duplicated by id, at most :data:`MAX_ITEMS`."""
    out: list[dict] = []
    seen: set[str] = set()
    for entry in raw if isinstance(raw, list) else []:
        item = _clean_item(entry)
        if item and item["id"] not in seen:
            seen.add(item["id"])
            out.append(item)
    return out[:MAX_ITEMS]


def read(channel: str) -> dict:
    """``{"mode": everything|chosen|pending, "items": [...]}`` — no file (or an unreadable one) is ``everything``."""
    try:
        data = json.loads(_path(channel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"mode": EVERYTHING, "items": []}
    if not isinstance(data, dict):
        return {"mode": EVERYTHING, "items": []}
    mode = data.get("mode")
    items = clean_items(data.get("items"))
    if mode == PENDING:
        return {"mode": PENDING, "items": []}
    if mode == CHOSEN and items:
        return {"mode": CHOSEN, "items": items}
    return {"mode": EVERYTHING, "items": []}


def exists(channel: str) -> bool:
    return _path(channel).is_file()


def _write(channel: str, mode: str, items: list[dict]) -> None:
    path = _path(channel)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".scope-", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"mode": mode, "items": items}, fh, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def write(channel: str, mode: str, items: list | None = None) -> dict:
    """The person's choice. ``chosen`` needs at least one item (``ValueError`` otherwise: choosing nothing is not a
    choice — Disconnect is the way to read nothing)."""
    if mode not in MODES:
        raise ValueError("mode must be everything or chosen")
    clean = clean_items(items) if mode == CHOSEN else []
    if mode == CHOSEN and not clean:
        raise ValueError("Choose at least one, or pick Everything.")
    _write(channel, mode, clean)
    return read(channel)


def mark_pending(channel: str) -> None:
    """A fresh sign-in: nothing is read until the person chooses. Only when there is no choice on file."""
    if not exists(channel):
        _write(channel, PENDING, [])


def clear(channel: str) -> None:
    try:
        _path(channel).unlink()
    except OSError:
        pass


def is_pending(channel: str) -> bool:
    return read(channel)["mode"] == PENDING


def signature(scope: dict) -> str:
    """A short stable key of the choice, for a cursor to notice that it changed."""
    if scope.get("mode") != CHOSEN:
        return scope.get("mode") or EVERYTHING
    ids = sorted(i["id"] for i in scope.get("items") or [])
    return "chosen:" + hashlib.sha256("\n".join(ids).encode()).hexdigest()[:12]


def summary(channel: str) -> dict:
    """What the Sources row and the picker read: the mode and how many items, never more."""
    scope = read(channel)
    return {"mode": scope["mode"], "count": len(scope["items"]), "items": scope["items"]}
