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


def google_enabled() -> bool:
    """Google Books is asked only with the person's own key (2026-11-08): no key, no request, ever."""
    from api.services import google_books_key

    return google_books_key.key() is not None


def _signed(url: str) -> str:
    """``url`` with the person's Google Books key added, only for Google's host; built here at the fetch so no caller,
    cache entry or log line ever holds it."""
    from urllib.parse import urlparse

    if urlparse(url).hostname != "www.googleapis.com":
        return url
    from api.services import google_books_key

    k = google_books_key.key()
    return f"{url}{'&' if '?' in url else '?'}key={k}" if k else url


def _note_google(url: str, resp: "Response") -> None:
    """Remember what Google's answer means for the key (a closed quota, a refused key), or that it works."""
    from urllib.parse import urlparse

    if urlparse(url).hostname != "www.googleapis.com":
        return
    from api.services import google_books_key

    kind = google_books_key.classify(resp.status, resp.body)
    if kind:
        google_books_key.note(kind)
    elif resp.status == 200 and google_books_key.problem():
        google_books_key.note(None)


async def _get(fetch: FetchFn, pacer: "_Pacer", url: str) -> Response:
    """One GET, its redirects followed here — each hop paced like any request (Open Library's ``/isbn/`` answers with
    a redirect to the edition), at most :data:`REDIRECTS`, only to Open Library or Google Books' own hosts. A Google
    request carries the person's key and is never sent without one."""
    from urllib.parse import urljoin, urlparse

    for _ in range(REDIRECTS + 1):
        if urlparse(url).hostname == "www.googleapis.com" and not google_enabled():
            return Response(0)
        await pacer.wait()
        resp = await fetch(_signed(url))
        _note_google(url, resp)
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
                if _lacks(hit) and google_enabled():
                    gb = await _get(fetch, pacer, f"{GOOGLE_BOOKS}?q=isbn:{isbn}")
                    _merge(hit, parse_google(_json(gb.body) or {}) if gb.status == 200 else None)
                return hit
        ol_missing = True   # a 200 that is not an edition
    if not google_enabled():
        # No key of the person's own: Open Library's answer is the whole answer (2026-11-08).
        return {"found": False} if ol_missing else None
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


# --- A title finds the book (ruling 61, amended 2026-11-06) ----------------------------------------------------------
# For a book the person chose to add that carries no ISBN (Apple Books: about one entry in 284 has one), its title and
# author go to the same keyless Open Library, behind the same gate, paced and cached, with no identity sent. Only a
# *confident* match counts: the page's title (or title + subtitle) equals a result's title once case, accents and
# punctuation are set aside, AND every one of the page's authors is among the result's; several works that both qualify with exactly the page's
# authors are one book filed more than once (the most editions wins; a tie is ambiguous); otherwise ambiguous, match nothing. No fuzzy step. The answer is cached under ``title:<hash>`` in the same file
# (a hash of the normalised words, never the words), so a miss is asked again only after :data:`MISS_RETRY_DAYS`.
SEARCH_FIELDS = "key,title,subtitle,author_name,isbn,first_publish_year,edition_count"
SEARCH_LIMIT = 10


def title_key(title, authors) -> str | None:
    """The cache key for a title and its authors, or None when either is empty (a title alone is never sent)."""
    import hashlib

    from api.services import books

    title, authors = books.lookup_names(title, authors)
    t = books.norm_words(title)
    a = "|".join(sorted(books.author_set(authors)))
    if not t or not a:
        return None
    return "title:" + hashlib.sha256(f"{t}\n{a}".encode()).hexdigest()[:20]


def confident_match(data, title, authors) -> dict:
    """``{"match": {work_id, isbn}}`` for one confident work, else ``{"match": None, "why": "none"|"ambiguous"|"no_isbn"}``."""
    from api.services import books

    docs = data.get("docs") if isinstance(data, dict) else None
    title, authors = books.lookup_names(title, authors)
    forms = books.title_forms(title)
    want = books.author_set(authors)
    works: dict[str, list[str]] = {}
    exact: dict[str, int] = {}   # works whose authors are exactly the page's, with their edition counts
    for doc in docs or []:
        if not isinstance(doc, dict):
            continue
        key = str(doc.get("key") or "")
        m = re.fullmatch(r"/works/(OL\d+W)", key)
        if not m:
            continue
        got = books.title_forms(doc.get("title"), doc.get("subtitle"))
        have = books.author_set(doc.get("author_name"))
        if not (forms & got) or not (want & have):
            continue
        isbns = sorted({i for i in (books.isbn13(x) for x in doc.get("isbn") or []) if i})
        works.setdefault(m.group(1), []).extend(isbns)
        if have == want:
            count = doc.get("edition_count")
            exact[m.group(1)] = max(exact.get(m.group(1), 0), count if isinstance(count, int) else 0)
    if not works:
        return {"match": None, "why": "none"}
    if len(works) > 1:
        # Several works carry this exact title and exactly these authors: the same book, filed more than once. The
        # record with the most editions stands for it; a tie, or no work with exactly these authors, stays ambiguous.
        # Never fuzzy, and "not this book" is still the undo.
        ranked = sorted(exact.items(), key=lambda kv: -kv[1])
        if not ranked or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]) or ranked[0][1] <= 0:
            return {"match": None, "why": "ambiguous"}
        works = {ranked[0][0]: works[ranked[0][0]]}
    (work, isbns), = works.items()
    if not isbns:
        return {"match": None, "why": "no_isbn"}
    return {"match": {"work_id": work, "isbn": sorted(set(isbns))[0]}}


async def match_title(title, authors, *, fetch: FetchFn | None = None, pacer: _Pacer | None = None) -> dict | None:
    """One search, one verdict: ``{"found": True, "isbn", "work_id"}``, ``{"found": False, "why"}`` for a definite
    miss, or None when the service did not answer. Never called without the person having added the book."""
    from urllib.parse import quote

    from api.services import books

    key = title_key(title, authors)
    if key is None:
        return {"found": False, "why": "no_author"}
    fetch = fetch or default_fetch
    pacer = pacer or _shared_pacer()
    title, names = books.lookup_names(title, authors)
    first = _clean(names[0] if names else "")
    url = (f"{OPEN_LIBRARY}/search.json?title={quote(_clean(title)[:200])}&author={quote(first[:120])}"
           f"&fields={SEARCH_FIELDS}&limit={SEARCH_LIMIT}")
    resp = await _get(fetch, pacer, url)
    if resp.status != 200:
        return None
    data = _json(resp.body)
    if not isinstance(data, dict):
        return None
    verdict = confident_match(data, title, authors)
    if verdict["match"]:
        return {"found": True, "v": VERSION, **verdict["match"]}
    return {"found": False, "why": verdict["why"]}


async def resolve_titles(items: list[dict], *, fetch: FetchFn | None = None, max_items: int = RUN_MAX,
                         pacer: _Pacer | None = None, now: datetime | None = None) -> dict:
    """For each ``{title, authors}`` (a book the person added, no ISBN) not yet asked: one title search, and when it
    matched, the normal ISBN lookup of the match (so the description, cover id and subjects are cached as a scan's are).
    Counts only: ``{asked, matched, missing, ambiguous, failed}``."""
    pacer = pacer or _shared_pacer()
    report = {"asked": 0, "matched": 0, "missing": 0, "ambiguous": 0, "failed": 0}
    for item in items:
        if report["asked"] >= max_items:
            break
        key = title_key(item.get("title"), item.get("authors"))
        if key is None or not due(key, now=now):
            continue
        report["asked"] += 1
        answer = await match_title(item.get("title"), item.get("authors"), fetch=fetch, pacer=pacer)
        _remember(key, answer, now=now or _now())
        if answer is None:
            report["failed"] += 1
        elif answer.get("found"):
            report["matched"] += 1
            if due(answer["isbn"], now=now):
                got = await lookup(answer["isbn"], fetch=fetch, pacer=pacer)
                _remember(answer["isbn"], got, now=now or _now())
        elif answer.get("why") == "ambiguous":
            report["ambiguous"] += 1
        else:
            report["missing"] += 1
    return report


# ---- Google Books, the second catalogue for a title (ruling 71, 2026-11-08) ---------------------------------------
# Open Library answers first. When its search found no book, or found one whose record holds no description, ONE Google
# Books volumes search per title (with the person's own key only: the title and its first author, nothing else) asks the same question
# under the same rule — an exact normalised title and an author of the page, on a volume — and its description is the
# page's `external`, boxed paragraph. The answer is cached outside every bank under `gtitle:<hash>`, the volume's
# record under `gb:<id>`. A 429 or a refused key stops the run (and says so in Settings); the title waits out the backoff.
GOOGLE_TITLE_FIELDS = ("items(id,volumeInfo(title,subtitle,authors,publishedDate,pageCount,publisher,categories,"
                       "description,industryIdentifiers))")
GOOGLE_LIMIT = 10


class QuotaReached(Exception):
    """Google Books refused the person's key or closed its quota (429, a refused key): no more requests this run."""


def google_key(title, authors) -> str | None:
    """The cache key of a title's Google Books answer (the same hash as :func:`title_key`), or None."""
    key = title_key(title, authors)
    return "gtitle:" + key[len("title:"):] if key else None


def google_match(data, title, authors) -> dict:
    """``{"match": {volume, hit}}`` for the best volume whose exact normalised title is the page's and one of whose authors
    is the page's, that holds a description; else ``{"match": None, "why": "none"|"no_description"}``. Volumes whose authors
    are exactly the page's rank first, then the ones with the most to say; Google's own order breaks a tie. Never fuzzy."""
    from api.services import books

    items = data.get("items") if isinstance(data, dict) else None
    title, names = books.lookup_names(title, authors)
    forms = books.title_forms(title)
    want = books.author_set(names)
    ranked: list[tuple[int, int, int, dict]] = []
    matched = False
    for pos, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        info = item.get("volumeInfo") or {}
        if not (forms & books.title_forms(info.get("title"), info.get("subtitle"))):
            continue
        have = books.author_set(info.get("authors"))
        if not (want & have):
            continue
        matched = True
        hit = parse_google({"items": [item]})
        vid = str(item.get("id") or "")
        if not hit or not hit.get("description") or not re.fullmatch(r"[\w-]{4,24}", vid):
            continue
        ranked.append((0 if have == want else 1, -len(hit["description"]), pos, {"volume": vid, "hit": hit}))
    if not ranked:
        return {"match": None, "why": "no_description" if matched else "none"}
    return {"match": min(ranked, key=lambda r: r[:3])[3]}


async def match_google(title, authors, *, fetch: FetchFn | None = None, pacer: _Pacer | None = None) -> dict | None:
    """One Google Books search, one verdict: ``{"found": True, "volume", "hit"}``, ``{"found": False, "why"}``, or None when
    the service did not answer. Raises :class:`QuotaReached` on a 429."""
    from urllib.parse import quote

    from api.services import books

    if google_key(title, authors) is None:
        return {"found": False, "why": "no_author"}
    title, names = books.lookup_names(title, authors)
    first = _clean(names[0] if names else "")
    q = quote(f'intitle:"{_clean(title)[:200]}" inauthor:"{first[:120]}"')
    url = f"{GOOGLE_BOOKS}?q={q}&printType=books&maxResults={GOOGLE_LIMIT}&fields={quote(GOOGLE_TITLE_FIELDS)}"
    resp = await _get(fetch or default_fetch, pacer or _shared_pacer(), url)
    from api.services import google_books_key

    if google_books_key.classify(resp.status, resp.body):
        raise QuotaReached()
    if resp.status != 200:
        return None
    data = _json(resp.body)
    if not isinstance(data, dict):
        return None
    verdict = google_match(data, title, names)
    if verdict["match"]:
        return {"found": True, "v": VERSION, **verdict["match"]}
    return {"found": False, "why": verdict["why"]}


async def resolve_google_titles(items: list[dict], *, fetch: FetchFn | None = None, max_items: int = RUN_MAX,
                                pacer: _Pacer | None = None, now: datetime | None = None) -> dict:
    """For each ``{title, authors}`` Open Library has ANSWERED and left without a description: one Google Books search.
    Counts only: ``{asked, matched, missing, failed, quota}``. A title Open Library has not answered waits (Open Library
    stays first); one it described is not asked."""
    pacer = pacer or _shared_pacer()
    report = {"asked": 0, "matched": 0, "missing": 0, "failed": 0, "quota": False}
    if not google_enabled():
        return {**report, "off": True}   # no key of the person's own: nothing asked, nothing cached, nothing said
    for item in items:
        if report["asked"] >= max_items:
            break
        title, authors = item.get("title"), item.get("authors")
        key, first_key = google_key(title, authors), title_key(title, authors)
        if key is None or first_key is None or not due(key, now=now):
            continue
        first = cached(first_key)
        if first is None:
            continue
        if first.get("found"):
            held = cached(first["isbn"])
            if held and held.get("found") and held.get("description"):
                continue
        report["asked"] += 1
        try:
            answer = await match_google(title, authors, fetch=fetch, pacer=pacer)
        except QuotaReached:
            _remember(key, None, now=now or _now())
            report["quota"] = True
            report["failed"] += 1
            break
        if answer is None:
            _remember(key, None, now=now or _now())
            report["failed"] += 1
        elif answer.get("found"):
            report["matched"] += 1
            record = f"gb:{answer['volume']}"
            _remember(record, answer["hit"], now=now or _now())
            _remember(key, {"found": True, "v": VERSION, "volume": answer["volume"], "hit": record}, now=now or _now())
        else:
            report["missing"] += 1
            _remember(key, {"found": False, "why": answer.get("why")}, now=now or _now())
    return report
