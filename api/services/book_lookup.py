"""An ISBN to a book, at the home, from two keyless public APIs (G233).

A scan carries only the number (the phone checks the checksum and sends it, so a scan works offline and is resolved
when it reaches the home). This module asks, in order:

1. **Open Library** — ``GET https://openlibrary.org/isbn/<isbn13>.json`` (the edition; it redirects to
   ``/books/<OL…M>.json``), then ``/authors/<OL…A>.json`` for up to three authors' names. Free and keyless. Its
   developer page (read 2026-11-04) asks for "1 request per second" from a client that does not identify itself with a
   contact (3 with one), a ``User-Agent`` naming the application, caching, and no bulk downloads. Cicada names the
   software, never the person (no email is ever sent), so it keeps to one request a second and caches every answer.
2. **Google Books** — ``GET https://www.googleapis.com/books/v1/volumes?q=isbn:<isbn13>`` when Open Library has no
   edition or does not answer. Keyless.

Each request takes the ToS rail's numbers (4 s, ≤ 512 KB read, no cookies, ≤ 3 redirects) and goes through
``net_guard`` on every hop. Callers check ``CICADA_ALLOW_CONNECTOR_FETCH`` (``connectors.base.network_allowed``) first:
the capture route's background resolve and Sleep's tail both stop when the person turned fetches off, and the scans
wait — nothing is lost, the episode is the record (``books.pending``).

**The cache** is outside every bank, ``$CICADA_HOME/books/isbn_cache.json`` (0600, atomic, ``flock``ed): an answer
(``found: true`` with what was read), a definite miss (Open Library 404 and Google Books zero results: a placeholder
page is made, and the number is asked again after :data:`MISS_RETRY_DAYS`), and a transient failure (no answer, 429,
5xx: asked again after a growing wait, never a page). It holds ISBNs and book metadata only — never a bank's name, a
title the person typed, or who asked. Shared by every bank on the machine (a book's metadata is the same anywhere).
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable, Iterator

from loguru import logger

from api.services.auth import cicada_home

OPEN_LIBRARY = "https://openlibrary.org"
GOOGLE_BOOKS = "https://www.googleapis.com/books/v1/volumes"
TIMEOUT_S = 4.0
MAX_BYTES = 512_000
SPACING_S = 1.0
MAX_AUTHORS = 3
#: ISBNs one run asks about (each is 1–5 requests at one a second).
RUN_MAX = 30
MISS_RETRY_DAYS = 30
#: Waits after a transient failure: 10 min, 1 h, 6 h, then a day.
BACKOFF_S = (600, 3600, 6 * 3600, 24 * 3600)
#: Names the software, never a person (the `paper_metadata` rule).
USER_AGENT = "CicadaBooks/1.0 (+https://github.com/rorosaga/cicada)"
_OL_KEY = re.compile(r"^/(?:works|authors|books)/(OL\d+[WAM])$")


@dataclass
class Response:
    status: int
    body: bytes = b""


FetchFn = Callable[[str], Awaitable[Response]]


def _cache_path() -> Path:
    return cicada_home() / "books" / "isbn_cache.json"


@contextmanager
def _locked() -> Iterator[Path]:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = path.with_suffix(".lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield path
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"books": {}, "failures": {}}
    if not isinstance(data, dict):
        return {"books": {}, "failures": {}}
    data.setdefault("books", {})
    data.setdefault("failures", {})
    return data


def _write(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".isbn_cache.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _now() -> datetime:
    return datetime.now(timezone.utc)


def cached(isbn: str) -> dict | None:
    """The answer for ``isbn``: a hit, a definite miss (``found: false``), or None while it has not been answered."""
    try:
        books = _read(_cache_path())["books"]
    except Exception:  # noqa: BLE001 — an unreadable cache is an empty one
        return None
    entry = books.get(str(isbn or ""))
    return entry if isinstance(entry, dict) else None


def due(isbn: str, *, now: datetime | None = None) -> bool:
    """Whether ``isbn`` may be asked now: never asked, a miss older than :data:`MISS_RETRY_DAYS`, or a transient
    failure whose wait is over. A hit is never asked again."""
    now = now or _now()
    data = _read(_cache_path())
    entry = data["books"].get(isbn)
    if isinstance(entry, dict):
        if entry.get("found"):
            return False
        try:
            return now - datetime.fromisoformat(str(entry.get("at"))) > timedelta(days=MISS_RETRY_DAYS)
        except ValueError:
            return True
    fail = data["failures"].get(isbn)
    if isinstance(fail, dict):
        try:
            return now >= datetime.fromisoformat(str(fail.get("next_at")))
        except ValueError:
            return True
    return True


def _remember(isbn: str, entry: dict | None, *, now: datetime) -> None:
    with _locked() as path:
        data = _read(path)
        if entry is None:
            fail = data["failures"].get(isbn) if isinstance(data["failures"].get(isbn), dict) else {}
            tries = int(fail.get("tries") or 0) + 1
            wait = BACKOFF_S[min(tries, len(BACKOFF_S)) - 1]
            data["failures"][isbn] = {"tries": tries, "next_at": (now + timedelta(seconds=wait)).isoformat()}
        else:
            data["books"][isbn] = {**entry, "at": now.isoformat()}
            data["failures"].pop(isbn, None)
        _write(path, data)


async def default_fetch(url: str) -> Response:
    """One GET under the ToS rail through ``net_guard`` on every hop. Never raises: no answer is ``status 0``."""
    try:
        import httpx

        from api.services import net_guard

        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True, max_redirects=3, trust_env=False,
                                     headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                                     event_hooks={"request": [net_guard.httpx_request_guard]}) as client:
            async with client.stream("GET", url) as resp:
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= MAX_BYTES:
                        break
                return Response(resp.status_code, b"".join(chunks)[:MAX_BYTES])
    except Exception as exc:  # noqa: BLE001 — recorded as no answer, never raised
        logger.info(f"book lookup: no answer ({type(exc).__name__})")
        return Response(0)


def _json(body: bytes):
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        return None


def _clean(text) -> str:
    return " ".join(str(text or "").split())


def _year(text) -> str | None:
    m = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", str(text or ""))
    return m.group(1) if m else None


class _Pacer:
    def __init__(self, spacing: float, clock=time.monotonic, sleep=asyncio.sleep):
        self.spacing, self.clock, self.sleep, self.last = spacing, clock, sleep, None

    async def wait(self) -> None:
        if self.last is not None:
            gap = self.spacing - (self.clock() - self.last)
            if gap > 0:
                await self.sleep(gap)
        self.last = self.clock()


def parse_open_library(edition: dict, authors: list[str]) -> dict | None:
    title = _clean(edition.get("title"))
    if not title:
        return None
    works = [w.get("key") for w in edition.get("works") or [] if isinstance(w, dict)]
    work = next((m.group(1) for m in (_OL_KEY.match(str(k or "")) for k in works) if m), None)
    covers = [c for c in edition.get("covers") or [] if isinstance(c, int) and c > 0]
    pages = edition.get("number_of_pages")
    return {"found": True, "source": "openlibrary", "title": title, "subtitle": _clean(edition.get("subtitle")) or None,
            "authors": authors, "work_id": work, "published": _year(edition.get("publish_date")),
            "pages": pages if isinstance(pages, int) and pages > 0 else None, "cover_id": covers[0] if covers else None,
            "isbns": [str(i) for i in (edition.get("isbn_13") or []) + (edition.get("isbn_10") or [])][:8]}


def parse_google(data: dict) -> dict | None:
    items = data.get("items") if isinstance(data, dict) else None
    if not items:
        return None
    info = (items[0] or {}).get("volumeInfo") or {}
    title = _clean(info.get("title"))
    if not title:
        return None
    ids = [str(i.get("identifier")) for i in info.get("industryIdentifiers") or []
           if isinstance(i, dict) and str(i.get("type") or "").startswith("ISBN")]
    pages = info.get("pageCount")
    return {"found": True, "source": "googlebooks", "title": title, "subtitle": _clean(info.get("subtitle")) or None,
            "authors": [_clean(a) for a in info.get("authors") or [] if _clean(a)][:MAX_AUTHORS], "work_id": None,
            "published": _year(info.get("publishedDate")),
            "pages": pages if isinstance(pages, int) and pages > 0 else None,
            "cover_id": None, "isbns": ids[:8]}


async def lookup(isbn: str, *, fetch: FetchFn | None = None, pacer: _Pacer | None = None) -> dict | None:
    """``isbn``'s answer: a hit, ``{"found": False}`` for a definite miss, or None when neither service answered."""
    fetch = fetch or default_fetch
    pacer = pacer or _Pacer(SPACING_S)
    await pacer.wait()
    ol = await fetch(f"{OPEN_LIBRARY}/isbn/{isbn}.json")
    ol_missing = ol.status == 404
    if ol.status == 200:
        edition = _json(ol.body)
        if isinstance(edition, dict):
            names: list[str] = []
            for ref in (edition.get("authors") or [])[:MAX_AUTHORS]:
                m = _OL_KEY.match(str((ref or {}).get("key") or "")) if isinstance(ref, dict) else None
                if not m:
                    continue
                await pacer.wait()
                got = await fetch(f"{OPEN_LIBRARY}/authors/{m.group(1)}.json")
                name = _clean((_json(got.body) or {}).get("name")) if got.status == 200 else ""
                if name:
                    names.append(name)
            hit = parse_open_library(edition, names)
            if hit is not None and names:
                return hit
            if hit is not None:
                # An edition with no author we could read: Google Books may name one; keep Open Library's work.
                await pacer.wait()
                gb = await fetch(f"{GOOGLE_BOOKS}?q=isbn:{isbn}")
                other = parse_google(_json(gb.body) or {}) if gb.status == 200 else None
                if other and other.get("authors"):
                    hit["authors"] = other["authors"]
                return hit
        ol_missing = True   # a 200 that is not an edition
    await pacer.wait()
    gb = await fetch(f"{GOOGLE_BOOKS}?q=isbn:{isbn}")
    if gb.status == 200:
        data = _json(gb.body)
        hit = parse_google(data or {})
        if hit is not None:
            return hit
        if ol_missing and isinstance(data, dict):
            return {"found": False}
    return None


async def resolve(isbns: list[str], *, fetch: FetchFn | None = None, max_isbns: int = RUN_MAX,
                  pacer: _Pacer | None = None, now: datetime | None = None) -> dict:
    """Ask about each due ISBN (at most ``max_isbns``), one request a second; remember every answer. The caller has
    checked the network gate. Returns ``{asked, found, missing, failed}`` — counts only."""
    pacer = pacer or _Pacer(SPACING_S)
    report = {"asked": 0, "found": 0, "missing": 0, "failed": 0}
    for isbn in isbns:
        if report["asked"] >= max_isbns:
            break
        if not due(isbn, now=now):
            continue
        report["asked"] += 1
        answer = await lookup(isbn, fetch=fetch, pacer=pacer)
        _remember(isbn, answer, now=now or _now())
        if answer is None:
            report["failed"] += 1
        elif answer.get("found"):
            report["found"] += 1
        else:
            report["missing"] += 1
    return report
