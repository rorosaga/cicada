"""Books the person's own agent read on their Goodreads shelves, held until the person chooses (ROR-128, G233).

The way in is the saved lists' (G206, G232; ruling 47): the person turned *Read through your browser* on, and their own
agent opens their shelves in their own signed-in browser and reports the books through ``cicada_record_saved_list``
(platform ``goodreads``). Cicada never opens a Goodreads page itself. What the agent reports is **not staged**: the
choice #666 gave the file import (all ticked, add some or all) belongs to this door too, so the books wait here, in one
small file outside every bank (``$CICADA_HOME/goodreads_waiting.json``, 0600, atomic, ``flock``ed), until the person
adds some from the Sources page (``GET /sources/goodreads/waiting``, ``POST /sources/goodreads/waiting/choose``). A book
left out is remembered by id and never asked about again; a book already in memory (any door) is never held.

A held book is a row in the shape of Goodreads' own export (``Book Id``, ``Title``, ``Author``, ``Exclusive Shelf``,
``My Rating``, ``Date Read``, ``Date Added``, ``My Review``, ``Bookshelves``), so choosing it goes through the same
``goodreads_export.draft_for`` and staging as a file: one book, one episode (``goodreads:<Book Id>``), whichever door
brought it, and a file imported later edits it in place.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from api.services import books, episode_staging, goodreads_export
from api.services.auth import cicada_home

FILENAME = "goodreads_waiting.json"
#: At most this many books wait for the person's choice, and this many left-out ids are remembered.
MAX_HELD = 500
MAX_LEFT_OUT = 20_000
SHELVES = tuple(goodreads_export.SHELVES)


def path() -> Path:
    return cicada_home() / FILENAME


def _bank_key(memory_path: Path) -> str:
    return Path(memory_path).name[:64]


def _load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".goodreads-waiting-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, sort_keys=True) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextmanager
def _locked() -> Iterator[dict]:
    lock = path().with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            data = _load()
            yield data
            _save(data)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _bank(data: dict, memory_path: Path) -> dict:
    return data.setdefault("banks", {}).setdefault(_bank_key(memory_path), {"held": {}, "left_out": []})


_ID = re.compile(r"[^0-9A-Za-z]")


def row_from(item) -> dict | None:
    """One book the agent saw → a row in the export's own shape, or ``None`` (no id or no title). The id is
    Goodreads' ``Book Id`` (the number in ``/book/show/<id>``); a link is accepted in its place."""
    if not isinstance(item, dict):
        return None
    raw_id = str(item.get("id") or item.get("book_id") or "")
    link = re.search(r"/book/show/(\d{1,15})", str(item.get("url") or ""))
    book_id = _ID.sub("", raw_id)[:32] or (link.group(1) if link else "")
    shelf = str(item.get("shelf") or "").strip().lower()
    row = {
        "Book Id": book_id,
        "Title": item.get("title"),
        "Author": item.get("author"),
        "Exclusive Shelf": shelf if shelf in SHELVES else "",
        "My Rating": item.get("rating") if str(item.get("rating") or "").isdigit() else "0",
        "Date Read": item.get("date_read"),
        "Date Added": item.get("date_added"),
        "My Review": item.get("review"),
        "Bookshelves": ",".join(str(s) for s in (item.get("shelves") or [])[:20]) if isinstance(
            item.get("shelves"), list) else "",
    }
    return row if goodreads_export.draft_for(row, now=datetime.now(timezone.utc)) is not None else None


def _in_memory(memory_path: Path) -> set[str]:
    by_source, _hashes = episode_staging.scan(Path(memory_path) / "episodes")
    return {sid.split(":", 1)[1] for sid in by_source if sid.startswith("goodreads:")}


def hold(memory_path: Path, items: list) -> dict:
    """Keep the books of one read for the person's choice. Counts: ``held`` new, ``known`` already in memory or
    left out before, ``dropped`` rows that were not books, ``full`` past the cap."""
    rows: dict[str, dict] = {}
    dropped = 0
    for item in items:
        row = row_from(item)
        if row is None:
            dropped += 1
        else:
            rows[row["Book Id"]] = row
    inside = _in_memory(memory_path)
    held = known = full = 0
    with _locked() as data:
        bank = _bank(data, memory_path)
        left = set(bank["left_out"])
        for book_id, row in rows.items():
            if book_id in inside or book_id in left:
                known += 1
            elif book_id in bank["held"]:
                bank["held"][book_id] = row
            elif len(bank["held"]) >= MAX_HELD:
                full += 1
            else:
                bank["held"][book_id] = row
                held += 1
    return {"held": held, "known": known, "dropped": dropped, "full": full}


def waiting(memory_path: Path) -> list[dict]:
    """The pick list — the same shape the file import's preview gives (``id``, ``title``, ``author``, ``status``)."""
    rows = ((_load().get("banks") or {}).get(_bank_key(memory_path)) or {}).get("held") or {}
    out = []
    for book_id, row in rows.items():
        d = goodreads_export.draft_for(row, now=datetime.now(timezone.utc))
        if d is None:
            continue
        rec = d.extra[books.EPISODE_KEY]
        out.append({"id": book_id, "title": rec["title"], "author": (rec["authors"] or [""])[0],
                    "status": rec["status"]})
    return sorted(out, key=lambda b: (b["title"].lower(), b["id"]))


def choose(memory_path: Path, ids) -> list[dict]:
    """The person's choice: the rows of ``ids`` come out to be staged, and every other waiting book is left out for
    good (remembered by id). ``[]`` leaves them all out."""
    wanted = {str(i) for i in ids}
    with _locked() as data:
        bank = _bank(data, memory_path)
        chosen = [row for book_id, row in bank["held"].items() if book_id in wanted]
        left = [b for b in bank["held"] if b not in wanted]
        bank["left_out"] = (bank["left_out"] + left)[-MAX_LEFT_OUT:]
        bank["held"] = {}
    return chosen

