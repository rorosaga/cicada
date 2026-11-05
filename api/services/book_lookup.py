"""An ISBN to a book, at the home, from two keyless public APIs (G233).

A scan carries only the number (the phone checks the checksum and sends it, so a scan works offline and is resolved
when it reaches the home). This module asks, in order:

1. **Open Library** — ``GET https://openlibrary.org/isbn/<isbn13>.json`` (the edition; it redirects to
   ``/books/<OL…M>.json``), then ``/authors/<OL…A>.json`` for up to three authors' names. Free and keyless. Its
   developer page (read 2026-11-04) asks for "1 request per second" from a client that does not identify itself with a
   contact (3 with one), a ``User-Agent`` naming the application, caching, and no bulk downloads. Cicada names the
   software, never the person (no email is ever sent), so it keeps to one request a second and caches every answer.
2. ``GET /works/<OL…W>.json`` (the work: the authors an edition lacks, a description, subjects), one request.
3. **Google Books** — ``GET https://www.googleapis.com/books/v1/volumes?q=isbn:<isbn13>`` when Open Library has no
   edition, or has one that lacks an author, a description, a publisher, a page count or a year: the two sources are
   **merged**, Open Library's value kept and Google Books filling what is missing. Keyless.

The description is the source's own words, cut to :data:`DESCRIPTION_CAP` characters (a blurb to read at a glance on the
head of a page that is an article; the full text is one click away at the source's link) and never written by a model.

Each request takes the ToS rail's numbers (4 s, ≤ 512 KB read, no cookies, ≤ 3 redirects) and goes through
``net_guard`` on every hop; a redirect is followed here, one paced request at a time, and the pacer is shared across
runs in the process. Callers check ``CICADA_ALLOW_CONNECTOR_FETCH`` (``connectors.base.network_allowed``) first:
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
import html
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
MAX_SUBJECTS = 4
#: A blurb, not the publisher's page: about a short paragraph, so the page's first screen stays the cover and the facts.
DESCRIPTION_CAP = 700
#: The cache entry's shape version. An entry made before this one (no description, publisher or subjects) is asked
#: again once, through the same pacing; the answer carries this number and is never asked again.
VERSION = 2
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
    #: A redirect's target, followed by :func:`_get` one paced hop at a time (never by the HTTP client).
    location: str | None = None


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
            if int(entry.get("v") or 1) >= VERSION:
                return False
            fail = data["failures"].get(isbn)   # a stale hit is asked again once; a failed try backs off like any
            if isinstance(fail, dict):
                try:
                    return now >= datetime.fromisoformat(str(fail.get("next_at")))
                except ValueError:
                    return True
            return True
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

        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False, trust_env=False,
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
                return Response(resp.status_code, b"".join(chunks)[:MAX_BYTES], resp.headers.get("location"))
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


_SHARED: "_Pacer | None" = None
REDIRECTS = 3
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})


def _shared_pacer() -> "_Pacer":
    """One pacer for the process (review of #600): a second run right after a first — the next scan's background job,
    the Sleep tail — still keeps one request a second, because the spacing does not reset when a run ends."""
    global _SHARED
    if _SHARED is None:
        _SHARED = _Pacer(SPACING_S)
    return _SHARED


async def _get(fetch: FetchFn, pacer: "_Pacer", url: str) -> Response:
    """One GET, its redirects followed here — each hop paced like any request (Open Library's ``/isbn/`` answers with
    a redirect to the edition), at most :data:`REDIRECTS`, only to Open Library or Google Books' own hosts."""
    from urllib.parse import urljoin, urlparse

    for _ in range(REDIRECTS + 1):
        await pacer.wait()
        resp = await fetch(url)
        if resp.status not in _REDIRECT_CODES or not resp.location:
            return resp
        nxt = urljoin(url, resp.location)
        if urlparse(nxt).hostname not in ("openlibrary.org", "www.googleapis.com"):
            return Response(0)
        url = nxt
    return Response(0)


def description_text(value) -> str:
    """A source's description as one capped paragraph: Open Library's is a string or ``{value}`` and may trail a rule and
    a list of editions or links, Google Books' may carry markup. Cut at a sentence end inside the cap, else at a word."""
    if isinstance(value, dict):
        value = value.get("value")
    text = str(value or "")
    text = re.split(r"\r?\n\s*(?:-{3,}|\*{3,}|_{3,})", text)[0]
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\(\[source\]\[\d+\]\)|\[\d+\]:\s*\S+", " ", text)
    text = re.sub(r"[*_`#]{1,3}", "", text)
    text = _clean(text)
    if len(text) <= DESCRIPTION_CAP:
        return text
    cut = text[:DESCRIPTION_CAP]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end >= DESCRIPTION_CAP // 2:
        return cut[:end + 1]
    return cut.rsplit(" ", 1)[0].rstrip(",;:- ") + "…"


def _subjects(values) -> list[str]:
    """A few readable subjects; a machine tag (``nyt:fiction=2020``, ``series_x``, anything with an underscore, colon or
    equals sign) is dropped, here, so it is never cached nor stored."""
    out: list[str] = []
    for v in values or []:
        name = _clean(v.get("name") if isinstance(v, dict) else v)
        if name and 1 < len(name) <= 60 and not any(c in name for c in "_:=") and name.casefold() not in {o.casefold() for o in out}:
            out.append(name)
        if len(out) >= MAX_SUBJECTS:
            break
    return out


readable_subjects = _subjects   # for a cached answer or a page that predates the filter


def _author_keys(refs) -> list[str]:
    keys: list[str] = []
    for ref in refs or []:
        if isinstance(ref, dict) and isinstance(ref.get("author"), dict):
            ref = ref["author"]
        m = _OL_KEY.match(str((ref or {}).get("key") or "")) if isinstance(ref, dict) else None
        if m and m.group(1) not in keys:
            keys.append(m.group(1))
    return keys[:MAX_AUTHORS]


def parse_open_library(edition: dict, authors: list[str]) -> dict | None:
    title = _clean(edition.get("title"))
    if not title:
        return None
    works = [w.get("key") for w in edition.get("works") or [] if isinstance(w, dict)]
    work = next((m.group(1) for m in (_OL_KEY.match(str(k or "")) for k in works) if m), None)
    covers = [c for c in edition.get("covers") or [] if isinstance(c, int) and c > 0]
    pages = edition.get("number_of_pages")
    publishers = [_clean(p) for p in edition.get("publishers") or [] if _clean(p)]
    return {"found": True, "v": VERSION, "source": "openlibrary", "title": title,
            "subtitle": _clean(edition.get("subtitle")) or None,
            "authors": authors, "work_id": work, "published": _year(edition.get("publish_date")),
            "pages": pages if isinstance(pages, int) and pages > 0 else None, "cover_id": covers[0] if covers else None,
            "publisher": publishers[0][:120] if publishers else None, "subjects": [],
            "description": None, "description_source": None, "description_url": None,
            "isbns": [str(i) for i in (edition.get("isbn_13") or []) + (edition.get("isbn_10") or [])][:8]}


def parse_google(data: dict) -> dict | None:
    items = data.get("items") if isinstance(data, dict) else None
    if not items:
        return None
    item = items[0] or {}
    info = item.get("volumeInfo") or {}
    title = _clean(info.get("title"))
    if not title:
        return None
    ids = [str(i.get("identifier")) for i in info.get("industryIdentifiers") or []
           if isinstance(i, dict) and str(i.get("type") or "").startswith("ISBN")]
    pages = info.get("pageCount")
    vid = str(item.get("id") or "")
    desc = description_text(info.get("description"))
    link = f"https://books.google.com/books?id={vid}" if desc and re.fullmatch(r"[\w-]{4,24}", vid) else None
    return {"found": True, "v": VERSION, "source": "googlebooks", "title": title,
            "subtitle": _clean(info.get("subtitle")) or None,
            "authors": [_clean(a) for a in info.get("authors") or [] if _clean(a)][:MAX_AUTHORS], "work_id": None,
            "published": _year(info.get("publishedDate")),
            "pages": pages if isinstance(pages, int) and pages > 0 else None,
            "cover_id": None, "publisher": _clean(info.get("publisher"))[:120] or None,
            "subjects": _subjects(info.get("categories")),
            "description": desc or None, "description_source": "googlebooks" if desc else None,
            "description_url": link, "isbns": ids[:8]}


def _lacks(hit: dict) -> bool:
    return not (hit.get("authors") and hit.get("description") and hit.get("publisher") and hit.get("pages")
                and hit.get("published"))


def _merge(hit: dict, other: dict | None) -> dict:
    """``hit`` with what it lacks taken from ``other`` (Open Library's value always kept)."""
    if not other:
        return hit
    for key in ("subtitle", "authors", "published", "pages", "publisher", "subjects", "isbns"):
        if not hit.get(key) and other.get(key):
            hit[key] = other[key]
    if not hit.get("description") and other.get("description"):
        for key in ("description", "description_source", "description_url"):
            hit[key] = other.get(key)
    return hit


async def _names(fetch: FetchFn, pacer: "_Pacer", keys: list[str]) -> list[str]:
    names: list[str] = []
    for key in keys:
        got = await _get(fetch, pacer, f"{OPEN_LIBRARY}/authors/{key}.json")
        name = _clean((_json(got.body) or {}).get("name")) if got.status == 200 else ""
        if name:
            names.append(name)
    return names


async def lookup(isbn: str, *, fetch: FetchFn | None = None, pacer: _Pacer | None = None) -> dict | None:
    """``isbn``'s answer: a hit, ``{"found": False}`` for a definite miss, or None when neither service answered."""
    fetch = fetch or default_fetch
    pacer = pacer or _shared_pacer()
    ol = await _get(fetch, pacer, f"{OPEN_LIBRARY}/isbn/{isbn}.json")
    ol_missing = ol.status == 404
    if ol.status == 200:
        edition = _json(ol.body)
        if isinstance(edition, dict):
            hit = parse_open_library(edition, await _names(fetch, pacer, _author_keys(edition.get("authors"))))
            if hit is not None:
                if hit.get("work_id"):
                    work = await _get(fetch, pacer, f"{OPEN_LIBRARY}/works/{hit['work_id']}.json")
                    data = _json(work.body) if work.status == 200 else None
                    if isinstance(data, dict):
                        if not hit["authors"]:
                            hit["authors"] = await _names(fetch, pacer, _author_keys(data.get("authors")))
                        desc = description_text(data.get("description"))
                        if desc:
                            hit.update(description=desc, description_source="openlibrary",
                                       description_url=f"{OPEN_LIBRARY}/works/{hit['work_id']}")
                        hit["subjects"] = _subjects(data.get("subjects"))
                if _lacks(hit):
                    gb = await _get(fetch, pacer, f"{GOOGLE_BOOKS}?q=isbn:{isbn}")
                    _merge(hit, parse_google(_json(gb.body) or {}) if gb.status == 200 else None)
                return hit
        ol_missing = True   # a 200 that is not an edition
    gb = await _get(fetch, pacer, f"{GOOGLE_BOOKS}?q=isbn:{isbn}")
    if gb.status == 200:
        data = _json(gb.body)
        hit = parse_google(data or {})
        if hit is not None:
            return hit
        if ol_missing and isinstance(data, dict):
            return {"found": False}
    return None


def stale(isbns) -> list[str]:
    """The numbers whose cached hit predates :data:`VERSION` and that may be asked now: refreshed once each."""
    try:
        books = _read(_cache_path())["books"]
    except Exception:  # noqa: BLE001
        return []
    return [i for i in dict.fromkeys(str(x) for x in isbns or [])
            if isinstance(books.get(i), dict) and books[i].get("found") and int(books[i].get("v") or 1) < VERSION
            and due(i)]


async def resolve(isbns: list[str], *, fetch: FetchFn | None = None, max_isbns: int = RUN_MAX,
                  pacer: _Pacer | None = None, now: datetime | None = None) -> dict:
    """Ask about each due ISBN (at most ``max_isbns``), one request a second; remember every answer. The caller has
    checked the network gate. Returns ``{asked, found, missing, failed}`` — counts only."""
    pacer = pacer or _shared_pacer()
    report = {"asked": 0, "found": 0, "missing": 0, "failed": 0}
    for isbn in isbns:
        if report["asked"] >= max_isbns:
            break
        if not due(isbn, now=now):
            continue
        report["asked"] += 1
        old = cached(isbn)
        answer = await lookup(isbn, fetch=fetch, pacer=pacer)
        if old and old.get("found"):
            # Asked again for the fields it lacked: what it already holds is kept; a miss never erases it.
            if answer and answer.get("found"):
                answer = {**old, **{k: v for k, v in answer.items() if v not in (None, [], "")}, "v": VERSION}
            elif answer is not None:
                answer = {**old, "v": VERSION}
        _remember(isbn, answer, now=now or _now())
        if answer is None:
            report["failed"] += 1
        elif answer.get("found"):
            report["found"] += 1
        else:
            report["missing"] += 1
    return report
