"""A cover for a row in the book choice list, before any page exists (G233, G39; owner 2026-11-06).

"The list appears like this instead of showing the thumbnails." A Goodreads export row has an ISBN and nothing else
to draw, so the cover comes the way a scan's does: the number goes through the existing lookup (``book_lookup``: the
connector gate, one request a second on the shared pacer, the cache outside every bank) and the catalogue's cover id
(else the number) asks Open Library's cover host through ``media_preview``'s pinned, bounded fetch (the logo gate, the
covers budget, ``net_guard`` on every hop). The picture is kept outside every bank, one file per ISBN under
``$CICADA_HOME/books/choice_covers/``, so a list opened twice asks once; a book with no cover is remembered for a day.
Never a title: the number is the person's own export's, and a row with none draws nothing (ruling 61).
"""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
import time
from pathlib import Path

from loguru import logger

from api.services import book_lookup, media_preview
from api.services.auth import cicada_home

_ISBN13 = re.compile(r"97[89]\d{10}")
MISS_TTL_S = 24 * 3600
_EXTS = tuple(media_preview.MEDIA_TYPES)


def valid(isbn: str) -> bool:
    return bool(_ISBN13.fullmatch(isbn or ""))


def _root() -> Path:
    return cicada_home() / "books" / "choice_covers"


def stored(isbn: str) -> Path | None:
    for ext in _EXTS:
        path = _root() / f"{isbn}.{ext}"
        if path.is_file():
            return path
    return None


def _missed(isbn: str, now: float) -> bool:
    try:
        return now - (_root() / f"{isbn}.miss").stat().st_mtime < MISS_TTL_S
    except OSError:
        return False


def _write(name: str, body: bytes) -> Path:
    root = _root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=root, prefix=".cover-")
    with os.fdopen(fd, "wb") as handle:
        handle.write(body)
    os.chmod(tmp, 0o600)
    target = root / name
    os.replace(tmp, target)
    return target


async def cover_for(isbn: str, *, fetcher=None, lookup_fetch=None, now: float | None = None) -> Path | None:
    """The cover file for ``isbn`` or None (no cover, fetches off, or not asked yet). Injected fetchers run as given;
    the defaults obey the gates."""
    if not valid(isbn):
        return None
    now = time.time() if now is None else now
    if (kept := stored(isbn)) is not None:
        return kept
    if _missed(isbn, now):
        return None
    if fetcher is None and not media_preview.fetch_allowed(unattended=True):
        return None
    entry = book_lookup.cached(isbn)
    if (entry is None or not entry.get("found")) and book_lookup.due(isbn):
        await book_lookup.resolve([isbn], fetch=lookup_fetch, max_isbns=1)
        entry = book_lookup.cached(isbn)
    book = {"isbns": [isbn]}
    if entry and entry.get("found") and entry.get("cover_id"):
        book["cover_id"] = entry["cover_id"]
    source = media_preview._book_network_source(book)
    if source is None:
        return None
    if fetcher is None:
        if not media_preview._take_cover_budget():
            return None   # not asked yet: not a miss
        fetcher = media_preview._http_get
    try:
        body, ext = await media_preview._produce(source, fetcher, media_preview._default_renderer)
    except media_preview._Miss as miss:
        logger.debug(f"choice cover miss: {miss.reason}")
        if not miss.transient:
            await asyncio.to_thread(_write, f"{isbn}.miss", b"")
        return None
    return await asyncio.to_thread(_write, f"{isbn}.{ext}", body)
