"""Apple Books: the library, what was read and finished, highlights and notes (G39; the app reads, the backend parses).

Apple Books keeps two Core Data SQLite stores in its sandbox on the Mac (paths read on macOS 27.2, 2026-11-04):

* ``~/Library/Containers/com.apple.iBooksX/Data/Documents/BKLibrary/BKLibrary-1-<version>.sqlite`` —
  ``ZBKLIBRARYASSET``: ``ZASSETID``, ``ZTITLE``, ``ZAUTHOR``, ``ZEPUBID`` (sometimes ``urn:isbn:…``), ``ZSTOREID``,
  ``ZCONTENTTYPE``, ``ZISFINISHED``, ``ZDATEFINISHED``, ``ZREADINGPROGRESS``, ``ZLASTOPENDATE``, ``ZCREATIONDATE``,
  ``ZISSAMPLE``, ``ZISHIDDEN``;
* ``~/Library/Containers/com.apple.iBooksX/Data/Documents/AEAnnotation/AEAnnotation_v<version>_local.sqlite`` —
  ``ZAEANNOTATION``: ``ZANNOTATIONASSETID``, ``ZANNOTATIONUUID``, ``ZANNOTATIONTYPE`` (2 is a highlight, with or
  without a note; 1 a bookmark and 3 the reading position are never read), ``ZANNOTATIONSELECTEDTEXT``,
  ``ZANNOTATIONNOTE``, ``ZANNOTATIONDELETED``, ``ZANNOTATIONCREATIONDATE``, ``ZANNOTATIONMODIFICATIONDATE``.

Both are in WAL mode, so the APP copies each with its ``-wal`` and ``-shm`` into a temporary folder and opens the copy
read-only (``AppleBooksReader``, the Chrome-history rule), after the person turned Apple Books on. It posts a
whitelisted projection here; this module is the one parser and re-applies the same filters to whatever arrives
(a hidden asset and a deleted annotation never become memory), so a newer or buggier app cannot widen what is stored.

**One episode per book** (``apple-books:<asset id>``), staged and updated in place: a re-sync that changed nothing
writes nothing; a new highlight edits the book's episode, and Sleep reads only what changed (``episode_revision``).
The body is a saved record (``authorship``: ``apple-books`` is a saving door) — the status line and each highlight are
the book's words (``page``); the person's note under its highlight sits in a ``## User note`` section, their own.
Highlights are ordered by when they were made, so new ones append. A book with a highlight or a note is queued for
Sleep (owner 2026-11-04: highlights are consolidated); a library entry with neither lands already read.

**Status, from Apple Books' own state, never invented** (owner 2026-11-04): ``ZISFINISHED`` → finished (on
``ZDATEFINISHED``); else ``ZREADINGPROGRESS`` above zero → reading (on the last open); else → not started (on the day it
entered the library). Progress itself is not kept: it changes with every page.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from api.services import books, episode_staging
from api.services.episode_staging import EpisodeDraft

CHANNEL_ID = "apple-books"
LABEL = "Apple Books"
SETTINGS_FILENAME = "apple_books.json"
MAX_BOOKS = 5000
#: Per book, so one book never stops another (review of #600): the oldest highlights first (new ones append, so a
#: revision stays a revision), each highlight and note cut at :data:`MAX_TEXT`, the body stopped at
#: :data:`MAX_BODY_CHARS`. Never silent (re-check of #600): what is past a cap is counted in the record's ``trimmed``,
#: returned by the sync and shown on the Apple Books row, and the body says so in one line (:data:`NOT_KEPT_LINE`).
#: The oldest are kept rather than a window rolled forward: a rolled window would drop the earliest highlights on every
#: sync, and Sleep would read each drop as the source withdrawing what it said (``episode_revision`` closes claims
#: only the removed text supported).
MAX_ANNOTATIONS = 3000
MAX_TEXT = 4000
MAX_BODY_CHARS = 400_000
#: The body's own words for a book over its cap. No count in it: a number here would change the body with every later
#: highlight and send the whole book back to Sleep for a line that says nothing new (the count is in ``trimmed``).
NOT_KEPT_LINE = ("**Not kept:** later highlights past this book's cap (3,000 highlights or 400,000 characters) were "
                 "not kept.")
#: Unicode's private-use areas: Apple Books leaves such a character in some text, drawn as nothing or a box, and it would
#: reach the page and recall. Never anyone's words.
_PRIVATE_USE = re.compile("[\ue000-\uf8ff\U000f0000-\U000ffffd\U00100000-\U0010fffd]")
_URN_ISBN = re.compile(r"(?:urn:isbn:|isbn[:\s]*)?([0-9Xx\- ]{10,17})$", re.IGNORECASE)


class PayloadError(ValueError):
    pass


def settings_path(memory_path: Path) -> Path:
    return Path(memory_path) / "sources" / SETTINGS_FILENAME


def load_settings(memory_path: Path) -> dict:
    try:
        data = json.loads(settings_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"enabled": bool(isinstance(data, dict) and data.get("enabled", False))}


def save_settings(memory_path: Path, *, enabled: bool) -> dict:
    path = settings_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"enabled": bool(enabled)}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def _instant(value) -> datetime | None:
    if not value:
        return None
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at).astimezone(timezone.utc)


def _z(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(text, limit: int = 300) -> str:
    return " ".join(_PRIVATE_USE.sub("", str(text or "")).split())[:limit]


#: What Apple Books writes where it knows no author (observed: the literal ``UnknownAuthor`` on a file the person added
#: themselves). Never an author's name.
_NO_AUTHOR = frozenset({"unknownauthor", "unknown author", "unknown", "author unknown", "n/a", "none"})
#: Apple Books cuts a file-name title at this many characters (observed: ``Batman-Year-One-The-Deluxe-Editi``).
FILE_TITLE_CUT = 32
_FILE_EXT = re.compile(r"\.(epub|pdf|cbz|cbr|mobi|azw3?|txt)$", re.IGNORECASE)


def clean_author(raw) -> str:
    """The author, or "" when Apple Books has none (a placeholder is no author)."""
    text = _clean(raw)
    return "" if text.lower() in _NO_AUTHOR else text


def clean_title(raw) -> str:
    """A title as a person reads it. A file the person added themselves has no store metadata: Apple Books gives its
    file name (dashes or underscores, no spaces, cut at ``FILE_TITLE_CUT`` characters). That becomes words, and a cut
    final word is dropped rather than kept as a fragment. Anything with spaces is a real title and is left alone."""
    text = _clean(raw)
    if not text or re.search(r"\s", text) or len(re.findall(r"[-_]", text)) < 2:
        return text
    cut = len(text) >= FILE_TITLE_CUT
    words = [w for w in re.split(r"[-_]+", _FILE_EXT.sub("", text)) if w]
    if cut and len(words) > 2:
        words = words[:-1]
    return " ".join(words) or text


def _block(text: str) -> str:
    """A highlight as a quote block: every line opens with ``> ``, so nothing in a book's words can open a turn."""
    lines = [ln.rstrip() for ln in str(text or "").replace("\r", "").split("\n")]
    lines = [ln for ln in lines if ln.strip()] or [""]
    return "\n".join(f"> {ln}" for ln in lines)


def isbn_of(epub_id) -> str | None:
    m = _URN_ISBN.match(str(epub_id or "").strip())
    return books.isbn13(m.group(1)) if m else None


def status_of(book: dict) -> tuple[str, datetime | None, bool]:
    """``(status, the record's day, whether that day is the status's own)``. Only ``ZDATEFINISHED`` dates a finish;
    Apple Books keeps no day a reading began (the last open is not one), so a reading or not-started record is dated
    by what the library holds but is never a dated happening (review of #600, B2)."""
    if book.get("isFinished"):
        finished = _instant(book.get("finishedAt"))
        if finished is not None:
            return books.FINISHED, finished, True
        return books.FINISHED, _instant(book.get("lastOpenedAt")) or _instant(book.get("addedAt")), False
    try:
        progress = float(book.get("progress") or 0)
    except (TypeError, ValueError):
        progress = 0.0
    if progress > 0:
        return books.READING, _instant(book.get("lastOpenedAt")) or _instant(book.get("addedAt")), False
    return books.NOT_STARTED, _instant(book.get("addedAt")), False


def draft_for(book: dict, *, now: datetime) -> EpisodeDraft | None:
    asset = _clean(book.get("assetId"), 128)
    title = clean_title(book.get("title"))
    if not asset or not title or book.get("isHidden"):
        return None
    author = clean_author(book.get("author"))
    status, on, dated = status_of(book)
    notes = []
    for a in book.get("annotations") or []:
        if not isinstance(a, dict) or a.get("deleted"):
            continue
        text = _PRIVATE_USE.sub("", str(a.get("selectedText") or "")).strip()[:MAX_TEXT]
        note = _PRIVATE_USE.sub("", str(a.get("note") or "")).strip()[:MAX_TEXT]
        if not text and not note:
            continue
        notes.append((_instant(a.get("createdAt")) or now, str(a.get("uuid") or ""), text, note))
    notes.sort(key=lambda n: (n[0], n[1]))
    total = len(notes)
    notes = notes[:MAX_ANNOTATIONS]
    day = books.utc_day(on.isoformat()) if on else None
    lines = [books.status_line(status)]
    if status == books.FINISHED and dated and day:
        lines.append(f"**Finished on:** {day}")
    lines += [f"**Book:** {title}"] + ([f"**Author:** {author}"] if author else [])
    body = "\n".join(lines) + "\n"
    kept = 0
    for at, _, text, note in notes:
        part = f"\n## Highlight, {books.utc_day(at.isoformat())}\n{_block(text)}\n" if text else ""
        part += f"\n## User note\n{note}\n" if note else ""
        if len(body) + len(part) + len(NOT_KEPT_LINE) + 2 > MAX_BODY_CHARS:
            break
        body += part
        kept += 1
    notes = notes[:kept]
    if total > kept:
        body += f"\n{NOT_KEPT_LINE}\n"
    isbn = isbn_of(book.get("epubId"))
    moment = max((n[0] for n in notes), default=None) or on or _instant(book.get("addedAt")) or now
    kind = {1: "book", 3: "pdf", 5: "audiobook"}.get(book.get("contentType"), "book")
    record = {"asset_id": asset, "title": title, "authors": [author] if author else [],
              "isbns": [isbn] if isbn else [], "status": status, "day": day, "dated": dated, "kind": kind,
              "highlights": sum(1 for n in notes if n[2]), "notes": sum(1 for n in notes if n[3]),
              "trimmed": total - kept}
    return EpisodeDraft(
        title=f"{title} — Apple Books", source_id=f"apple-books:{asset}", timestamp=_z(moment),
        original_date=books.utc_day(moment.isoformat()), source=books.APPLE_ORIGIN, origin=books.APPLE_ORIGIN,
        body=body, extra={books.EPISODE_KEY: record}, queue_for_sleep=bool(notes), processed_by="index",
        writer="apple-books", redate=True)


def sync(memory_path: Path, payload: dict, *, bank: str | None = None, now: datetime | None = None) -> dict:
    """Stage the posted books; returns counts and the episodes written (memory-relative), never a title."""
    items = payload.get("books")
    if not isinstance(items, list):
        raise PayloadError("books must be a list")
    if len(items) > MAX_BOOKS:
        raise PayloadError(f"at most {MAX_BOOKS} books per sync")
    now = now or datetime.now(timezone.utc)
    drafts = [d for d in (draft_for(b, now=now) for b in items if isinstance(b, dict)) if d is not None]
    result = episode_staging.stage(drafts, Path(memory_path) / "episodes", bank=bank or Path(memory_path).name)
    return {"books": len(drafts), "created": result.created, "updated": result.updated,
            "unchanged": result.skipped, "highlights": sum(d.extra[books.EPISODE_KEY]["highlights"] for d in drafts),
            "notes": sum(d.extra[books.EPISODE_KEY]["notes"] for d in drafts),
            "queued": sum(1 for d in drafts if d.queue_for_sleep),
            "trimmed": sum(d.extra[books.EPISODE_KEY].get("trimmed", 0) for d in drafts),
            # Per book, so the app can keep the count for books a later sync does not send again (unchanged).
            "trimmedBooks": {d.extra[books.EPISODE_KEY]["asset_id"]: d.extra[books.EPISODE_KEY]["trimmed"]
                             for d in drafts if d.extra[books.EPISODE_KEY].get("trimmed")},
            "paths": list(result.paths)}
