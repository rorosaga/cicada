"""A Goodreads library, from the person's own "Export Library" CSV (G233; ruling 47's path table).

Goodreads stopped issuing developer keys for its public API in December 2020 and has not reopened it; its pages sit
behind sign-in and bot protection. So there is no connector: the way in is the export Goodreads itself offers its
members (My Books → Import and export → Export Library, a ``goodreads_library_export.csv``), picked by the person in
the app — the quiet second way since ROR-128 (ruling 72), after the person's own agent reading their shelves in their own
browser (``goodreads_waiting``). The backend never fetches a Goodreads page, signed in or not.

The columns read (the export's own headers): ``Book Id``, ``Title``, ``Author``, ``Additional Authors``, ``ISBN``,
``ISBN13`` (written ``="…"`` so a spreadsheet keeps the digits), ``My Rating``, ``Number of Pages``, ``Year
Published``, ``Original Publication Year``, ``Date Read``, ``Date Added`` (``YYYY/MM/DD``), ``Bookshelves``,
``Exclusive Shelf``, ``My Review``, ``Private Notes``. Every other column (average rating, publisher, binding, owned
copies, spoiler flags, read count) is skipped unread.

The exclusive shelf is the status: ``read`` → finished (on ``Date Read``, else ``Date Added``), ``currently-reading``
→ reading, ``to-read`` → want to read (both on ``Date Added``); a custom exclusive shelf records no status. A rating
of 1–5 is the person's own ``rated`` claim. One episode per row (``goodreads:<Book Id>``), a saved record like a
shelf entry is (``page``), the review and the private notes under ``## User note`` — the person's words, and the only
rows Sleep reads; the rest land already read (ruling 30's index-only list).
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path

from api.services import books, episode_staging
from api.services.episode_staging import EpisodeDraft

CHANNEL_ID = "goodreads"
LABEL = "Goodreads"
MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 20_000
REQUIRED = ("Book Id", "Title")
SHELVES = {"read": books.FINISHED, "currently-reading": books.READING, "to-read": books.WANT}
_DATE = re.compile(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$")
_TAG = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML = re.compile(r"<[^>]+>")


class PayloadError(ValueError):
    pass


def _day(value) -> str | None:
    m = _DATE.match(str(value or "").strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date().isoformat()
    except ValueError:
        return None


def _clean(text, limit: int = 300) -> str:
    return " ".join(str(text or "").split())[:limit]


def _prose(text) -> str:
    """A review as plain text: Goodreads writes ``<br/>`` for a new line and keeps a little HTML."""
    raw = _TAG.sub("\n", str(text or ""))
    raw = _HTML.sub("", raw)
    return "\n".join(" ".join(line.split()) for line in raw.splitlines()).strip()[:16_000]


def _rows(data: bytes) -> list[dict]:
    if len(data) > MAX_BYTES:
        raise PayloadError("that file is larger than a Goodreads export")
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or any(h not in reader.fieldnames for h in REQUIRED):
        raise PayloadError("this is not a Goodreads library export (no Book Id and Title columns)")
    rows = []
    for row in reader:
        rows.append(row)
        if len(rows) > MAX_ROWS:
            raise PayloadError(f"at most {MAX_ROWS} books in one import")
    return rows


def draft_for(row: dict, *, now: datetime) -> EpisodeDraft | None:
    book_id = re.sub(r"[^0-9A-Za-z]", "", str(row.get("Book Id") or ""))[:32]
    title = _clean(row.get("Title"))
    if not book_id or not title:
        return None
    authors = [a for a in [_clean(row.get("Author"))] + [_clean(x) for x in str(row.get("Additional Authors") or "")
                                                         .split(",")] if a]
    isbns = [i for i in (books.isbn13(row.get(k)) for k in ("ISBN13", "ISBN")) if i]
    isbns = list(dict.fromkeys(isbns))
    shelf = _clean(row.get("Exclusive Shelf"), 80).lower()
    status = SHELVES.get(shelf)
    added, read = _day(row.get("Date Added")), _day(row.get("Date Read"))
    day = (read or added) if status == books.FINISHED else added
    try:
        rating = int(str(row.get("My Rating") or "0").strip() or 0)
    except ValueError:
        rating = 0
    review, notes = _prose(row.get("My Review")), _prose(row.get("Private Notes"))
    shelves = [s.strip() for s in str(row.get("Bookshelves") or "").split(",") if s.strip() and s.strip() != shelf]
    lines = [books.status_line(status)] if status else []
    if status == books.FINISHED and read:
        lines.append(f"**Finished on:** {read}")
    if 1 <= rating <= 5:
        lines.append(f"**My rating:** {rating} of 5")
    lines += [f"**Book:** {title}"] + ([f"**Author:** {', '.join(authors)}"] if authors else [])
    if shelves:
        lines.append(f"**Shelves:** {', '.join(shelves)[:300]}")
    body = "\n".join(lines) + "\n"
    if review:
        body += f"\n## User note\n{review}\n"
    if notes:
        body += f"\n## User note\n{notes}\n"
    when = day or now.date().isoformat()
    pages = str(row.get("Number of Pages") or "").strip()
    record = {"goodreads_id": book_id, "title": title, "authors": authors, "isbns": isbns, "status": status,
              "day": day, "dated": bool(status == books.FINISHED and read),
              "reviewed": bool(review or notes), "rating": rating if 1 <= rating <= 5 else None, "rated_day": read or added,
              "published": (str(row.get("Original Publication Year") or row.get("Year Published") or "").strip()
                            or None), "pages": int(pages) if pages.isdigit() else None,
              "has_note": bool(review or notes)}
    return EpisodeDraft(
        title=f"{title} — Goodreads", source_id=f"goodreads:{book_id}", timestamp=f"{when}T12:00:00Z",
        original_date=when, source=books.GOODREADS_ORIGIN, origin=books.GOODREADS_ORIGIN, body=body,
        extra={books.EPISODE_KEY: record}, queue_for_sleep=bool(review or notes), processed_by="index",
        writer="goodreads")


def preview(data: bytes) -> dict:
    """What an import would bring — counts plus one row per book (id, title, author, shelf) so the person can choose —
    read from the file, writing nothing."""
    rows = _rows(data)
    by = {s: 0 for s in books.STATUSES}
    reviews = rated = 0
    now = datetime.now(timezone.utc)
    listing = []
    for row in rows:
        d = draft_for(row, now=now)
        if d is None:
            continue
        rec = d.extra[books.EPISODE_KEY]
        listing.append({"id": rec["goodreads_id"], "title": rec["title"],
                        "author": (rec["authors"] or [""])[0], "status": rec["status"],
                        "isbn": (rec["isbns"] or [""])[0]})
        if rec["status"]:
            by[rec["status"]] += 1
        reviews += int(rec["has_note"])
        rated += int(bool(rec["rating"]))
    return {"books": len(rows), "finished": by[books.FINISHED], "reading": by[books.READING],
            "want": by[books.WANT], "reviews": reviews, "rated": rated, "items": listing}


def stage(memory_path: Path, data: bytes, *, bank: str | None = None, now: datetime | None = None,
          ids: set[str] | None = None) -> dict:
    """``ids`` is the person's choice (Goodreads ``Book Id`` values); ``None`` is every book, an empty set none."""
    return stage_rows(memory_path, _rows(data), bank=bank, now=now, ids=ids)


def stage_rows(memory_path: Path, rows: list[dict], *, bank: str | None = None, now: datetime | None = None,
               ids: set[str] | None = None) -> dict:
    """Stage export-shaped rows — a file's, or the books the person's agent read and the person chose
    (``goodreads_waiting``): one writer, one episode per book whichever door."""
    now = now or datetime.now(timezone.utc)
    drafts = [d for d in (draft_for(r, now=now) for r in rows) if d is not None]
    if ids is not None:
        drafts = [d for d in drafts if d.extra[books.EPISODE_KEY]["goodreads_id"] in ids]
    result = episode_staging.stage(drafts, Path(memory_path) / "episodes", bank=bank or Path(memory_path).name)
    return {"books": len(drafts), "created": result.created, "updated": result.updated,
            "unchanged": result.skipped, "queued": sum(1 for d in drafts if d.queue_for_sleep),
            "paths": list(result.paths)}
