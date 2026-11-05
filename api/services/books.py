"""Books: one page per WORK, its ISBNs as aliases, what the person did with it as dated claims (G39, G233).

Three ways a book comes in, each the normal capture path — an episode staged through ``episode_staging`` — and one
writer (:func:`apply_pending`) that turns those episodes into pages and claims, with no model:

* **A scan** (``/capture/isbn``, the phone's "Scan a book", any client): the raw ISBN and, when the person tapped one,
  a status. The episode is the person's act (``origin: book-scan``). It holds no title — the home resolves the number
  (``book_lookup``: Open Library, then Google Books, behind the network gate, cached outside every bank) and the page
  is made then; until it is, the scan waits, never lost (the episode is the record, :func:`pending`).
* **Apple Books** (``apple_books``: the APP reads the two databases, the backend parses what it posts): one episode
  per book — its status and, as the person adds them, its highlights (the book's words) and notes (the person's).
* **A Goodreads export** (``goodreads_export``: the person's own "Export Library" CSV): one episode per row — its
  shelf, rating, dates and the person's review or private notes.

**The page** is a ``media`` page with ``media.kind: book`` (the closed set has no ``book`` type and needs none: a book
is a work someone made and the person consumes, the paper's shape, G133) and a ``book:`` block. It is the work, not
the copy: a paperback's ISBN, the ebook's and an Apple Books asset all land on one page, matched only by an identifier
— any ISBN, an Open Library work id, a source's own id (:func:`identity_keys`). **Title and author join two pages only
when both are exactly the same and only one page holds them** (owner 2026-11-05, amends review of #600, B1: an Apple Books
entry has no ISBN, so a scan of the same book would mint a second page). "Same" is the words with case, accents and
punctuation set aside (:func:`norm_words`), the author names as a set — never a prefix, never a likeness: "Dune" and
"Dune: House Atreides", two volumes of a series, two books whose authors share a surname stay different works. Anything
less sure — a title two pages hold, an author one record lacks or only partly shares — never joins: the record gets its own
page and one "same book?" question for each candidate (:meth:`BookIndex.find_words`, ``role_people.ask_same``). Every ISBN (13 and, for 978, 10 digits) is an alias, so a note that names the number links to the page.

**Statuses** — ``reading``, ``finished``, ``want`` (want to read), ``not_started`` (in Apple Books' library, never
opened; owner 2026-11-04):

* one ``reading-status`` claim per status record, dated (``valid_from``), the newest by its date the open one, every
  earlier one closed (``valid_to`` the next one's day, ``superseded_by`` it) — never deleted;
* ``reading`` and ``finished`` are also happenings, through ``progress.record_happening`` (the one event writer, G141):
  "Started reading" (``ongoing``) and "Finished reading" (``done``, settling the open thread). ``want`` and
  ``not_started`` are not events: nothing happened;
* a conversation can say a status too (ruling 61, ``book_said``): the same records, through these same writers.

**Whose act it is** is read from the episode's own record, never set here (``authorship``): a scan is the person's own
act (its lines are ``user``); an Apple Books or Goodreads episode is a saved record (``page``), except the person's
notes and review, under ``## User note``. So a scanned "reading now" lights its page at once, while a library or a
shelf someone imported stays quiet (``quiet_pages``) until the person marks, writes or talks about the book — a want-to-read
or not-started scan, a save by another name, is stamped ``media_entity_id`` and stays quiet too (ruling 30's indexed
save, owner 2026-11-04).

**What the person marked is kept word for word, with no model** (ruling 64, ``book_marks``): each highlight and note is
a claim on the page with a span of the episode, and a book with one is no longer quiet.

**Sleep reads the highlights** (owner 2026-11-04: "be able to consolidate highlights and such is important"): an Apple
Books episode with a highlight or a note, and a Goodreads row with a review, is queued like any conversation, read for
what its marks share in one bounded chunk (ruling 64); a re-sync that adds highlights edits it in place and Sleep reads
only what changed (``episode_revision``, #581). Everything else — a library entry, a shelf, a scan — lands already read
(``processed_by: index`` / ``parser``): there is nothing in it for a model.

Rails: no model, no network (``book_lookup`` fetches; this module reads its cache), every page write under
``page_lock`` and, from a route, the bank's write admission (the caller's; Sleep's tail calls it inside its own
window); an episode stamp under ``episode_lock`` (lock order: page, then episode); nothing here logs a title.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from loguru import logger

from api.services import bank_index, decay_policy, episode_ids, evidence, markdown_parser, page_lock
from api.services.claims import (RETRACT_PREDICATE, Claim, MalformedClaimsBlockError, is_recovered_history,
                                 parse_claims, write_claims)
from api.services.id_utils import sanitize_id

KIND = "book"
#: ``origin`` of each door's episodes, and of the page and claims this module writes.
SCAN_ORIGIN = "book-scan"
APPLE_ORIGIN = "apple-books"
GOODREADS_ORIGIN = "goodreads"
PAGE_ORIGIN = "book"
DOORS = (SCAN_ORIGIN, APPLE_ORIGIN, GOODREADS_ORIGIN)
#: The frontmatter block every book episode carries (what its door read), and the stamp :func:`apply_pending` leaves
#: (the ``content_hash`` it applied) so a re-sync that changed nothing is not applied twice.
EPISODE_KEY = "book"
APPLIED_KEY = "book_applied"
#: The ``content_hash`` whose highlights and notes ``book_marks`` wrote: a separate stamp, so a record applied before
#: ruling 64 gets its marks without its status being applied twice.
MARKS_KEY = "book_marks"
#: ``media_entity_id`` — the save stamp ``quiet_pages`` and ``authorship`` read.
SAVE_KEY = "media_entity_id"

READING, FINISHED, WANT, NOT_STARTED = "reading", "finished", "want", "not_started"
STATUSES = (READING, FINISHED, WANT, NOT_STARTED)
#: How each status reads on a record, in the person's language (the app shows the same words).
STATUS_WORDS = {READING: "Reading now", FINISHED: "Finished", WANT: "Want to read", NOT_STARTED: "Not started"}
#: The statuses that say the person did something with the book (a happening; a scan of one lights the page).
ACTED = frozenset({READING, FINISHED})
STATUS_PREDICATE = "reading-status"
RATING_PREDICATE = "rated"
HAPPENING_TEXT = {READING: "Started reading", FINISHED: "Finished reading"}
#: How far along each status is: what decides one day's clash that has no time of day to go by (ruling 61).
_RANK = {NOT_STARTED: 0, WANT: 0, READING: 1, FINISHED: 2}
UNDO_REASON = "The person said this status is not right."
#: The most book episodes one apply reads; the rest wait for the next (an import of thousands is many applies).
MAX_APPLY = 3000
#: The most "same book?" questions one new page asks (a title more pages than this hold is a pile for the person's own look).
MAX_SAME_ASKED = 3
#: What each door is called on a book's page when it has more than one way in (``current_status``'s ``ways``).
DOOR_WORDS = {APPLE_ORIGIN: "Apple Books", GOODREADS_ORIGIN: "Goodreads", SCAN_ORIGIN: "Scanned"}

_ISBN_STRIP = re.compile(r"[\s\-‐-―=\"']")


# --------------------------------------------------------------------------- #
# ISBNs
# --------------------------------------------------------------------------- #


def ean13_ok(digits: str) -> bool:
    """The EAN-13 check digit (weights 1, 3 alternating) — what a book's barcode is."""
    if not re.fullmatch(r"\d{13}", digits or ""):
        return False
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(digits[:12]))
    return (10 - total % 10) % 10 == int(digits[12])


def isbn10_ok(raw: str) -> bool:
    if not re.fullmatch(r"\d{9}[\dX]", raw or ""):
        return False
    total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(raw))
    return total % 11 == 0


def isbn13(raw) -> str | None:
    """``raw`` as a valid ISBN-13 (``978``/``979``), or None. Takes an ISBN-10 (converted), hyphens, spaces and the
    ``="…"`` quoting a spreadsheet export wraps them in. A barcode that is not a book's (another EAN prefix) is None."""
    text = _ISBN_STRIP.sub("", str(raw or "")).upper()
    if text.startswith("ISBN"):
        text = text[4:].lstrip(":")
    if isbn10_ok(text):
        body = "978" + text[:9]
        total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body))
        return body + str((10 - total % 10) % 10)
    if ean13_ok(text) and text[:3] in ("978", "979"):
        return text
    return None


def isbn10(isbn: str) -> str | None:
    """The ISBN-10 of a ``978`` ISBN-13 (a ``979`` has none)."""
    if not (isbn and isbn.startswith("978") and ean13_ok(isbn)):
        return None
    body = isbn[3:12]
    check = (11 - sum((10 - i) * int(d) for i, d in enumerate(body)) % 11) % 11
    return body + ("X" if check == 10 else str(check))


def aliases_for(isbns) -> list[str]:
    out: list[str] = []
    for isbn in isbns or []:
        for alias in (isbn, isbn10(isbn)):
            if alias and alias not in out:
                out.append(alias)
    return out


# --------------------------------------------------------------------------- #
# identity
# --------------------------------------------------------------------------- #


@dataclass
class BookFacts:
    """What one door knows about a book. Every field optional but one way to name it."""
    title: str | None = None
    subtitle: str | None = None
    authors: list[str] = field(default_factory=list)
    isbns: list[str] = field(default_factory=list)
    work_id: str | None = None
    published: str | None = None
    pages: int | None = None
    cover_id: int | None = None
    local_cover: str | None = None
    apple_id: str | None = None
    goodreads_id: str | None = None
    title_from: str = "placeholder"
    #: The door that brought this record (``DOORS``): kept on the page as where the book came in from.
    door: str | None = None


def identity_keys(facts: BookFacts) -> list[str]:
    """The identifiers that make two records one work: an ISBN, the Open Library work id, the source's own id. Never
    the title or an author (B1): a match on words alone is a guess, and a wrong join closes one book's status with
    another's and aliases its ISBNs onto the wrong page."""
    keys = [f"isbn:{i}" for i in facts.isbns]
    if facts.work_id:
        keys.append(f"work:{facts.work_id}")
    if facts.apple_id:
        keys.append(f"apple:{facts.apple_id}")
    if facts.goodreads_id:
        keys.append(f"goodreads:{facts.goodreads_id}")
    return keys


_NOT_WORD = re.compile(r"[^0-9a-z]+")
_AUTHOR_SPLIT = re.compile(r"\s*(?:&|;|\band\b)\s*")
_ISBN_LIKE = re.compile(r"[0-9Xx]{10}|[0-9]{13}")


def norm_words(text) -> str:
    """``text`` with case, accents and punctuation set aside and spaces collapsed: what "exactly the same" means for a
    title or a name. Nothing is dropped or reordered (no article, no subtitle, no series note)."""
    plain = unicodedata.normalize("NFKD", str(text or "")).casefold().replace("&", " and ")
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return _NOT_WORD.sub(" ", plain).strip()


def title_forms(title, subtitle=None, spellings=()) -> frozenset[str]:
    """The ways one work's title reads: the title, the title with its subtitle after it ("Title: A Novel", Apple Books'
    spelling of Open Library's title + subtitle) and a source's own spellings."""
    forms = {norm_words(title)}
    if title and subtitle:
        forms.add(norm_words(f"{title} {subtitle}"))
    forms.update(norm_words(x) for x in spellings or ())
    return frozenset(f for f in forms if f)


def author_set(authors) -> frozenset[str]:
    """A book's authors as a set of normalised names; "A & B" and "A and B" are two."""
    names = set()
    for a in authors or []:
        names.update(norm_words(part) for part in _AUTHOR_SPLIT.split(str(a or "")))
    return frozenset(n for n in names if n)


def is_book(fm: dict) -> bool:
    media = (fm or {}).get("media")
    return isinstance(media, dict) and media.get("kind") == KIND


def _page_facts(fm: dict) -> BookFacts:
    book = fm.get("book") if isinstance(fm.get("book"), dict) else {}
    return BookFacts(title=book.get("title") or fm.get("name"), authors=list(book.get("authors") or []),
                     isbns=list(book.get("isbns") or []), work_id=book.get("work_id"),
                     title_from=str(book.get("title_from") or "page"))


def _page_keys(fm: dict) -> list[str]:
    book = fm.get("book") if isinstance(fm.get("book"), dict) else {}
    keys = identity_keys(_page_facts(fm))
    keys += [f"apple:{a}" for a in book.get("apple_books") or []]
    keys += [f"goodreads:{g}" for g in book.get("goodreads") or []]
    return keys


class BookIndex:
    """Identity key → page id over the bank's book pages, kept current as :func:`apply_pending` makes pages."""

    def __init__(self, memory_path: Path):
        self.by_key: dict[str, str] = {}
        self.ids: set[str] = set()
        #: A title as it reads → the book pages that carry it; a page → its author set. Exact words only.
        self.by_title: dict[str, set[str]] = {}
        self.authors: dict[str, frozenset[str]] = {}
        #: A page → what its whole title reads as, a bare title not among them when it has a subtitle ("Harbour" is not
        #: "Harbour: Book Two"), and whether it has one.
        self.whole: dict[str, frozenset[str]] = {}
        self.subtitled: dict[str, bool] = {}
        #: A page :func:`ensure_page` just made → the pages it might be the same book as (never joined; asked).
        self.unsure: dict[str, list[str]] = {}
        for f in bank_index.files(memory_path, "entities"):
            fm = f.frontmatter or {}
            stem = Path(f.path).stem
            self.ids.add(stem)
            if is_book(fm) and str(fm.get("status") or "active") != "dropped":
                self.add(stem, _page_keys(fm), fm)

    def add(self, entity_id: str, keys, fm: dict | None = None) -> None:
        for key in keys:
            self.by_key.setdefault(key, entity_id)
        self.ids.add(entity_id)
        if fm is not None:
            book = fm.get("book") if isinstance(fm.get("book"), dict) else {}
            spellings = [fm.get("name"), *[a for a in fm.get("aliases") or [] if not _ISBN_LIKE.fullmatch(str(a))]]
            title, subtitle = book.get("title") or fm.get("name"), book.get("subtitle")
            for form in title_forms(title, subtitle, spellings):
                self.by_title.setdefault(form, set()).add(entity_id)
            bare = norm_words(title)
            self.subtitled[entity_id] = bool(subtitle)
            self.whole[entity_id] = frozenset(
                form for form in title_forms(title, subtitle, spellings) if not subtitle or form != bare)
            self.authors[entity_id] = author_set(book.get("authors"))

    def find(self, facts: BookFacts) -> str | None:
        return next((self.by_key[k] for k in identity_keys(facts) if k in self.by_key), None)

    def find_words(self, facts: BookFacts) -> tuple[str | None, list[str]]:
        """``(page, [])`` when exactly one page carries this record's title and has exactly its authors; ``(None,
        candidates)`` when the words alone cannot say — a title two pages hold with the same authors, or one page's title
        with an author a side lacks or only partly shares (the caller asks, never joins); ``(None, [])`` otherwise,
        including the same title by different authors, which is two books."""
        if facts.title_from == "placeholder" or not facts.title:
            return None, []
        mine = author_set(facts.authors)
        same = sorted({p for f in title_forms(facts.title, facts.subtitle) for p in self.by_title.get(f, ())})
        # A join needs the whole title on both sides. Two subtitles that differ are two books (a series' volumes); a
        # bare title against a subtitled one may or may not be, so it asks.
        whole = norm_words(f"{facts.title} {facts.subtitle}" if facts.subtitle else facts.title)
        exact = [p for p in same if mine and self.authors.get(p) == mine and whole in self.whole.get(p, ())]
        if len(exact) == 1:
            return exact[0], []
        if exact:
            return None, exact
        return None, [p for p in same if not (facts.subtitle and self.subtitled.get(p))
                      and (not mine or not self.authors.get(p) or mine & self.authors[p])]


def _new_id(index: BookIndex, facts: BookFacts) -> str:
    # The id leaves out a series note ("Title (Series, #1)", Goodreads' spelling); the name keeps the whole title.
    plain = re.sub(r"\s*[\(\[][^)\]]*[\)\]]\s*", " ", str(facts.title or "")).strip()
    base = sanitize_id(plain) if facts.title_from != "placeholder" else ""
    if not base or base == "unnamed":
        base = f"book-{facts.isbns[0]}" if facts.isbns else "book"
    if base not in index.ids:
        return base
    base = f"{base}-book"
    n, cid = 1, base
    while cid in index.ids:
        n += 1
        cid = f"{base}-{n}"
    return cid


def display_title(facts: BookFacts) -> str:
    if facts.title and facts.title_from != "placeholder":
        return " ".join(str(facts.title).split())[:300]
    return f"Book with ISBN {facts.isbns[0]}" if facts.isbns else "Untitled book"


def media_url(book: dict) -> str:
    """A link the person can open (never fetched to draw a card): the Open Library work, else an edition by ISBN."""
    if book.get("work_id"):
        return f"https://openlibrary.org/works/{book['work_id']}"
    isbns = book.get("isbns") or []
    return f"https://openlibrary.org/isbn/{isbns[0]}" if isbns else ""


def _spellings(facts: BookFacts, name) -> list[str]:
    """A source's own spelling of the title when it is not the page's name ("<Title>: A Novel" in Apple Books,
    "<Title> (Series, #1)" on Goodreads): an alias, so a highlight's episode that names the book its way, and Stage 1
    reading it, land on this page instead of a second one."""
    if facts.title_from == "placeholder" or not facts.title:
        return []
    title = " ".join(str(facts.title).split())[:300]
    return [title] if title.casefold() != str(name or "").casefold() else []


def _merge_list(old, new) -> list:
    out = list(old or [])
    for v in new or []:
        if v and v not in out:
            out.append(v)
    return out


def _applied_page(memory_path: Path, was) -> str | None:
    """The page a record was last applied to, or the one it became: a merge carries no book identities, so the index
    can miss a page that holds this record's marks. A dropped page is no answer, as in :class:`BookIndex`."""
    from api.services import page_redirects

    was = str(was or "").strip()
    if not was or "/" in was:
        return None
    entity_id = page_redirects.resolve(memory_path, was) or was
    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    if not path.is_file() or str(markdown_parser.parse(path).frontmatter.get("status") or "active") == "dropped":
        return None
    return entity_id


def ensure_page(memory_path: Path, index: BookIndex, facts: BookFacts, episode_id: str,
                today: str, *, was=None) -> tuple[str, bool, bool]:
    """``(entity_id, created, changed)``: the work's page, made or upgraded in place with what ``facts`` adds. A
    placeholder title gives way to a real one; a title from Open Library or a source is never replaced by another
    source's spelling (the first real title stays, the person may rename it). ``was``: the page this record was last
    applied to, followed when no book holds its identities. A page that is no book holds what the record says and is
    never turned into one."""
    entity_id = index.find(facts) or _applied_page(memory_path, was)
    unsure: list[str] = []
    if not entity_id:
        entity_id, unsure = index.find_words(facts)
    path = Path(memory_path) / "entities" / f"{entity_id}.md" if entity_id else None
    if path is not None and path.exists():
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        if not is_book(fm):
            return entity_id, False, False
        before = repr(sorted(fm.items(), key=lambda kv: kv[0]))
        book = dict(fm.get("book") or {})
        book["isbns"] = _merge_list(book.get("isbns"), facts.isbns)
        if facts.apple_id:
            book["apple_books"] = _merge_list(book.get("apple_books"), [facts.apple_id])
        if facts.goodreads_id:
            book["goodreads"] = _merge_list(book.get("goodreads"), [facts.goodreads_id])
        if facts.door:
            book["doors"] = _merge_list(book.get("doors"), [facts.door])
        upgrade = book.get("title_from") == "placeholder" and facts.title_from != "placeholder"
        for key in ("work_id", "subtitle", "published", "pages", "cover_id", "local_cover"):
            if getattr(facts, key) and (upgrade or not book.get(key)):
                book[key] = getattr(facts, key)
        if facts.authors and (upgrade or not book.get("authors")):
            book["authors"] = list(facts.authors)
        if upgrade:
            book["title"], book["title_from"] = facts.title, facts.title_from
            fm["name"] = display_title(facts)
        fm["book"] = book
        fm["aliases"] = _merge_list(fm.get("aliases"),
                                    aliases_for(book["isbns"]) + _spellings(facts, fm.get("name")))
        media = dict(fm.get("media") or {})
        media["kind"] = KIND
        media["url"] = media.get("url") or media_url(book)
        media["channel"] = media.get("channel") or (book.get("authors") or [None])[0]
        fm["media"] = media
        episodes = list(fm.get("source_episodes") or [])
        if episode_id not in episodes:
            episodes.append(episode_id)
        fm["source_episodes"] = episodes
        if repr(sorted(fm.items(), key=lambda kv: kv[0])) == before:
            return entity_id, False, False
        markdown_parser.write(path, fm, parsed.body)
        index.add(entity_id, _page_keys(fm), fm)
        return entity_id, False, True
    entity_id = _new_id(index, facts)
    name = display_title(facts)
    book = {"title": facts.title if facts.title_from != "placeholder" else None, "subtitle": facts.subtitle,
            "authors": list(facts.authors), "isbns": list(facts.isbns), "work_id": facts.work_id,
            "published": facts.published, "pages": facts.pages, "cover_id": facts.cover_id,
            **({"local_cover": facts.local_cover} if facts.local_cover else {}),
            "apple_books": [facts.apple_id] if facts.apple_id else [],
            "goodreads": [facts.goodreads_id] if facts.goodreads_id else [], "title_from": facts.title_from,
            **({"doors": [facts.door]} if facts.door else {})}
    url = media_url(book)
    fm = {
        "name": name, "type": "media", "status": "active", "confidence": 0.8,
        "created": today, "last_referenced": today,
        **decay_policy.frontmatter_fields(decay_policy.default_class_for("media", source="media")),
        "source_episodes": [episode_id], "aliases": aliases_for(facts.isbns) + _spellings(facts, name), "tags": [KIND],
        "related": [], "version": 1, "origin": PAGE_ORIGIN,
        # A book page is described by the book APIs and the person's own records — never a scraped page.
        "enrichment_attempted": True,
        "media": {"url": url, "media_type": KIND, "kind": KIND, "site": "openlibrary.org" if url else None,
                  "channel": facts.authors[0] if facts.authors else None, "thumbnail": None,
                  "saved_at": episode_ids.utc_now_iso()},
        "book": book,
    }
    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    by = f" by {', '.join(facts.authors[:3])}" if facts.authors else ""
    markdown_parser.write(path, fm, f"## Summary\n{name}{by} — a book.")
    index.add(entity_id, _page_keys(fm), fm)
    if unsure:
        index.unsure[entity_id] = unsure
    return entity_id, True, True


# --------------------------------------------------------------------------- #
# claims
# --------------------------------------------------------------------------- #


def _claim_id(*parts: str) -> str:
    return "clm_book_" + hashlib.sha1("\x00".join(parts).encode()).hexdigest()[:10]


def _claim_ids(memory_path: Path, entity_id: str, *parts: str) -> list[str]:
    """The id a claim gets on this page, then the ids it holds if a page merged or renamed into this one wrote it: an id
    is derived from the page's, and a claim keeps its id through a merge."""
    from api.services import page_redirects

    return [_claim_id(eid, *parts) for eid in (entity_id, *page_redirects.former_ids(memory_path, entity_id))]


def _span(memory_path: Path, episode_id: str, quote: str):
    """A span over ``quote`` in the episode, its kind the episode's own (``authorship``, through ``evidence.verify``)
    — or ``reasoning``. Never raises (provenance never blocks memory)."""
    return evidence.verify(memory_path, episode_id, quote)


def _status_claims(claims: list[Claim]) -> list[Claim]:
    return [c for c in claims if c.predicate == STATUS_PREDICATE and c.origin == PAGE_ORIGIN
            and not is_recovered_history(c)]


def _withdrawn(claims: list[Claim]) -> set[str]:
    return {str(c.object) for c in claims if c.predicate == RETRACT_PREDICATE}


def live_status_claims(claims: list[Claim]) -> list[Claim]:
    """The status records in force: never one the person took back (:func:`undo_status`)."""
    gone = _withdrawn(claims)
    return [c for c in _status_claims(claims) if c.id not in gone]


def _current_record(claims: list[Claim]) -> Claim | None:
    """The record in force: the open one, else the newest by day (an edited conversation can withdraw the open record
    from outside this module, ``episode_revision``; what it had closed is what stands until the next write re-chains)."""
    live = live_status_claims(claims)
    return next((c for c in live if not c.valid_to), None) or max(live, key=lambda c: c.valid_from or "", default=None)


def _rechain(mine: list[Claim], today: str) -> bool:
    """The newest by its day open, each earlier one closed on the next one's day. On one day, in the order they stand on
    the page (the later tap wins), unless an answer already put one above the other (a closed record pointing at its
    same-day winner, the conflict path)."""
    order = {id(c): n for n, c in enumerate(mine)}
    ordered = sorted(mine, key=lambda c: (c.valid_from or "", order[id(c)]))
    for i in range(len(ordered) - 1):
        a, b = ordered[i], ordered[i + 1]
        if (a.valid_from or "") == (b.valid_from or "") and b.superseded_by == a.id:
            ordered[i], ordered[i + 1] = b, a
    changed = False
    for here, nxt in zip(ordered, ordered[1:]):
        if here.valid_to != (nxt.valid_from or today) or here.superseded_by != nxt.id:
            here.valid_to, here.superseded_by = nxt.valid_from or today, nxt.id
            changed = True
    if ordered and (ordered[-1].valid_to or ordered[-1].superseded_by):
        ordered[-1].valid_to, ordered[-1].superseded_by = None, None
        changed = True
    return changed


def _said_again(mine: list[Claim], status: str, day: str) -> Claim | None:
    """The record a conversation dated ``day`` only says again: its neighbour by day already holds this status, with
    nothing different between them. A reading in between makes a second finish a second reading, not a repeat."""
    ordered = sorted(mine, key=lambda c: c.valid_from or "")
    before = [c for c in ordered if (c.valid_from or "") <= day]
    after = [c for c in ordered if (c.valid_from or "") > day]
    for near in (before[-1:] + after[:1]):
        if near.object == status:
            return near
    return None


def happening_stands(memory_path: Path, entity_id: str, status: str, day: str) -> bool:
    """A chat dated ``day`` says this status again and the page already holds its happening: nothing more to record."""
    if status not in HAPPENING_TEXT:
        return False
    claims = parse_claims(markdown_parser.parse(Path(memory_path) / "entities" / f"{entity_id}.md").body)
    mine = live_status_claims(claims)
    if {c.id for c in mine}.intersection(_claim_ids(memory_path, entity_id, STATUS_PREDICATE, status, day)) \
            or not _said_again(mine, status, day):
        return False
    from api.services.claims import HAPPENED

    gone = _withdrawn(claims)
    return any(c.predicate == HAPPENED and c.object == HAPPENING_TEXT[status].lower() and c.id not in gone
               for c in claims)


def set_status(memory_path: Path, entity_id: str, *, status: str, day: str, episode_id: str, quote: str,
               observer: str, today: str, span=None, ranked: bool = False) -> bool:
    """One dated ``reading-status`` record on the page; the newest by its day stays open, each earlier one closed on
    the next one's day. Idempotent: the same status, day and episode change nothing, and a record the person took back
    is never written again.

    ``span``: the located words it rests on, when the caller holds them (a conversation, ``book_said``). ``ranked``: a
    record whose time of day means nothing (a chat read late) never closes a further-along status of the same day, so
    what it says does not depend on when it was read; a door's record stays the later wins. It also only says a status
    again (:func:`_said_again`), adding its episode as evidence, and what the person took back stays taken back from
    that conversation whatever day a re-read gives it."""
    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    parsed = markdown_parser.parse(path)
    try:
        claims = parse_claims(parsed.body, strict=True)
    except MalformedClaimsBlockError:
        logger.warning("book page has an unreadable claims block; its status was not written")
        return False
    ids = _claim_ids(memory_path, entity_id, STATUS_PREDICATE, status, day)
    cid = ids[0]
    gone = _withdrawn(claims)
    if gone.intersection(ids) or (ranked and any(c.id in gone and c.object == status and episode_id in c.source_episodes
                                      for c in _status_claims(claims))):
        return False
    mine = {c.id: c for c in live_status_claims(claims)}
    changed = False
    old = next((mine[i] for i in ids if i in mine), None) or (_said_again(list(mine.values()), status, day) if ranked else None)
    if old is not None:
        if episode_id not in old.source_episodes:
            old.source_episodes.append(episode_id)
            if span is not None:
                old.evidence.append(span)
            changed = True
    else:
        made = Claim(id=cid, text=f"{STATUS_WORDS[status]}.", subject=entity_id, predicate=STATUS_PREDICATE,
                     object=status, object_kind="literal", observer=observer, context="general",
                     epistemic="explicit", source_trust="user_stated", confidence=0.9, valid_from=day,
                     recorded_at=today, source_episodes=[episode_id], origin=PAGE_ORIGIN, authored_by="user",
                     evidence=[span if span is not None else _span(memory_path, episode_id, quote)])
        above = [i for i, c in enumerate(claims) if ranked and c.id in mine and (c.valid_from or "") == day
                 and _RANK[str(c.object)] > _RANK[status]]
        claims.insert(above[0] if above else len(claims), made)
        changed = True
    changed = _rechain(live_status_claims(claims), today) or changed
    if not changed:
        return False
    fm = parsed.frontmatter
    if span is not None and episode_id not in (fm.get("source_episodes") or []):
        fm = {**fm, "source_episodes": [*(fm.get("source_episodes") or []), episode_id]}
    markdown_parser.write(path, fm, write_claims(parsed.body, claims))
    return True


def undo_status(memory_path: Path, entity_id: str, claim_id: str, *, today: str | None = None) -> dict:
    """"Not right": the person takes a status record back. The record is kept as history (the withdrawal record, one
    shape however many writers say it), the status before it opens again, its happening goes with it and the reading
    thread that happening settled opens again. Returns
    ``{action, status, paths}``; ``not_found`` for no such live record. Never written again (:func:`set_status`)."""
    from api.services import progress
    from api.services.agentic_write import _withdrawal_record
    from api.services.claims import HAPPENED

    memory_path = Path(memory_path)
    today = today or date.today().isoformat()
    path = memory_path / "entities" / f"{entity_id}.md"
    with page_lock.page_lock(memory_path):
        if not path.is_file():
            return {"action": "not_found"}
        parsed = markdown_parser.parse(path)
        try:
            claims = parse_claims(parsed.body, strict=True)
        except MalformedClaimsBlockError:
            return {"action": "error"}
        target = next((c for c in live_status_claims(claims) if c.id == claim_id), None)
        if target is None:
            return {"action": "not_found"}
        record = _withdrawal_record(target, claims, reason=UNDO_REASON, author="user", origin=PAGE_ORIGIN,
                                    session_id=None, spans=[evidence.reasoning("")], day=today,
                                    fallback_subject=entity_id)
        target.valid_to, target.superseded_by = target.valid_to or max(today, target.valid_from or today), record.id
        claims.append(record)
        _rechain(live_status_claims(claims), today)
        markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, claims))
        paths = [f"entities/{entity_id}.md"]
        said = HAPPENING_TEXT.get(str(target.object), "").lower()
        for c in claims:
            if (c.predicate == HAPPENED and c.object == said and c.valid_from == target.valid_from
                    and not c.superseded_by and set(c.source_episodes) & set(target.source_episodes)):
                out = progress.withdraw(memory_path, subject=entity_id, claim_id=c.id, author="user",
                                        reason=UNDO_REASON, origin=PAGE_ORIGIN, reopen_settled=True)
                paths += [p for p in out.get("paths") or [] if p not in paths]
        current = next((c for c in live_status_claims(parse_claims(markdown_parser.parse(path).body))
                        if not c.valid_to), None)
    bank_index.invalidate(memory_path)
    return {"action": "retracted", "status": current.object if current else None, "paths": paths}


def current_status(memory_path: Path, entity_id: str) -> dict | None:
    """The open status record, for the book's page: ``{status, day, claimId, episode, fromChat}`` or None."""
    entry = bank_index.file(Path(memory_path), "entities", f"{entity_id}.md")
    if entry is None or not is_book(entry.frontmatter or {}):
        return None
    try:
        claims = parse_claims(markdown_parser.parse(Path(entry.path)).body)
    except Exception:  # noqa: BLE001 — an unreadable page says no status
        return None
    current = _current_record(claims)
    if current is None:
        return None
    episode = (current.source_episodes or [None])[0]
    record = bank_index.file(Path(memory_path), "episodes", f"{episode}.md") if episode else None
    origin = str((record.frontmatter or {}).get("origin") or "") if record is not None else ""
    return {"status": current.object, "day": current.valid_from, "claimId": current.id, "episode": episode,
            "fromChat": bool(episode) and origin not in DOORS, "ways": ways_in(entry.frontmatter or {})}


def ways_in(fm: dict) -> list[str]:
    """Where a book came in from, in the person's words, in a fixed order — read from the page (``book.doors``; a page
    made before that field is known by its Apple Books and Goodreads ids)."""
    book = fm.get("book") if isinstance(fm.get("book"), dict) else {}
    doors = set(book.get("doors") or [])
    if book.get("apple_books"):
        doors.add(APPLE_ORIGIN)
    if book.get("goodreads"):
        doors.add(GOODREADS_ORIGIN)
    return [DOOR_WORDS[d] for d in (APPLE_ORIGIN, GOODREADS_ORIGIN, SCAN_ORIGIN) if d in doors]


def scan_result(memory_path: Path, episode_id: str) -> dict | None:
    """What became of a scan, for the Add that made it: ``{state: waiting}`` until the number resolves, then ``{state:
    added, entityId, name, existing}`` — ``existing`` when the page was there before this scan (a copy from another door
    or another edition). None for an id that is no scan."""
    from api.services import page_redirects

    entry = bank_index.file(Path(memory_path), "episodes", f"{episode_id}.md")
    fm = (entry.frontmatter or {}) if entry is not None else {}
    if str(fm.get("origin") or "") != SCAN_ORIGIN:
        return None
    page = _applied_page(Path(memory_path), fm.get("book_entity_id"))
    if not page or fm.get(APPLIED_KEY) != fm.get("content_hash"):
        return {"state": "waiting"}
    page = page_redirects.resolve(Path(memory_path), page) or page
    page_fm = (bank_index.file(Path(memory_path), "entities", f"{page}.md").frontmatter or {})
    first = (page_fm.get("source_episodes") or [None])[0]
    return {"state": "added", "entityId": page, "name": str(page_fm.get("name") or page), "existing": first != episode_id}


def set_rating(memory_path: Path, entity_id: str, *, rating: int, day: str, episode_id: str, quote: str,
               observer: str, today: str) -> bool:
    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    parsed = markdown_parser.parse(path)
    try:
        claims = parse_claims(parsed.body, strict=True)
    except MalformedClaimsBlockError:
        return False
    ids = _claim_ids(memory_path, entity_id, RATING_PREDICATE, str(rating), episode_id)
    cid = ids[0]
    if any(c.id in ids for c in claims):
        return False
    for c in claims:
        if c.predicate == RATING_PREDICATE and c.origin == PAGE_ORIGIN and not c.valid_to:
            c.valid_to, c.superseded_by = day, cid
    claims.append(Claim(id=cid, text=f"Rated it {rating} out of 5.", subject=entity_id, predicate=RATING_PREDICATE,
                        object=f"{rating}/5", object_kind="literal", observer=observer, context="general",
                        epistemic="explicit", source_trust="user_stated", confidence=0.9, valid_from=day,
                        recorded_at=today, source_episodes=[episode_id], origin=PAGE_ORIGIN, authored_by="user",
                        evidence=[_span(memory_path, episode_id, quote)]))
    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, claims))
    return True


def _open_reading_thread(memory_path: Path, entity_id: str) -> str | None:
    from api.services.claims import HAPPENED

    try:
        parsed = markdown_parser.parse(Path(memory_path) / "entities" / f"{entity_id}.md")
        claims = parse_claims(parsed.body)
    except Exception:  # noqa: BLE001 — no thread to settle is the safe answer
        return None
    return next((c.id for c in claims if c.predicate == HAPPENED and c.status == "ongoing" and c.valid_to is None
                 and c.object == HAPPENING_TEXT[READING].lower()), None)


def record_happening(memory_path: Path, entity_id: str, *, status: str, day: str, episode_id: str, quote: str,
                     observer: str, basis: str = "stated", span=None) -> list[str]:
    """``reading`` / ``finished`` as a happening, through the one event writer. Returns the paths it wrote. ``span``:
    the located words, so the same words said earlier by someone else are never what it cites."""
    from api.services import progress

    if status not in ACTED:
        return []
    try:
        on = date.fromisoformat(day[:10])
    except ValueError:
        return []
    settles = _open_reading_thread(memory_path, entity_id) if status == FINISHED else None
    if settles is not None:
        # An open thread that began after this finish is another reading; never settle it backwards.
        thread_day = settles.rsplit("_", 1)[-1][:10]
        if thread_day > on.isoformat():
            settles = None
    out = progress.record_happening(
        memory_path, subject=entity_id, text=HAPPENING_TEXT[status],
        status="ongoing" if status == READING else "done",
        evidence=[{"episode": episode_id, "quote": quote, **({"window": [span.start, span.end]} if span else {})}],
        observer=observer, origin=PAGE_ORIGIN, authored_by="user", source_episode=episode_id, day=on,
        date_basis=basis, settles=settles)
    if out.get("action") not in ("written", "reinforced"):
        logger.info(f"book happening not written ({out.get('action')})")
        return []
    return [p for p in out.get("paths") or [] if p != f"entities/{entity_id}.md"]


# --------------------------------------------------------------------------- #
# episodes
# --------------------------------------------------------------------------- #


def status_line(status: str | None) -> str:
    return f"**Status:** {STATUS_WORDS[status]}" if status in STATUS_WORDS else ""


def _owner(memory_path: Path) -> str:
    from api.config import get_settings
    from api.services import owner_identity

    return owner_identity.resolve_observer(memory_path, get_settings())


def pending(memory_path: Path, *, limit: int = MAX_APPLY) -> list:
    """The book episodes not applied as they stand now (a new one, one a re-sync changed, one whose ISBN waited for
    its lookup) — derived from the bank, so nothing waits anywhere a move or a restore could lose it."""
    out = []
    for f in bank_index.files(Path(memory_path), "episodes"):
        fm = f.frontmatter or {}
        if not isinstance(fm.get(EPISODE_KEY), dict) or fm.get("source_deleted_at"):
            continue
        if str(fm.get("origin") or "") not in DOORS:
            continue
        if fm.get(APPLIED_KEY) and fm.get(APPLIED_KEY) == fm.get("content_hash") and not _marks_due(fm):
            continue
        out.append(f)
        if len(out) >= limit:
            break
    return out


def _marks_due(fm: dict) -> bool:
    """A record that says it holds marks, or last wrote some, whose marks are not those of this body."""
    rec = fm.get(EPISODE_KEY) or {}
    has = rec.get("highlights") or rec.get("notes") or rec.get("reviewed") or fm.get(MARKS_KEY)
    return bool(has) and fm.get(MARKS_KEY) != fm.get("content_hash")


def waiting_isbns(memory_path: Path) -> list[str]:
    """The ISBNs to ask about: a scan whose page waits for its lookup, then a placeholder page's numbers (a definite
    miss, asked again when ``book_lookup.due`` says so). ``book_lookup.resolve`` skips any not yet due."""
    from api.services import book_lookup

    out: list[str] = []
    for f in pending(memory_path):
        fm = f.frontmatter or {}
        isbn = (fm.get(EPISODE_KEY) or {}).get("isbn")
        if fm.get("origin") == SCAN_ORIGIN and isbn and book_lookup.cached(isbn) is None and isbn not in out:
            out.append(isbn)
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        book = fm.get("book") if is_book(fm) and isinstance(fm.get("book"), dict) else None
        if book and book.get("title_from") == "placeholder":
            out += [i for i in book.get("isbns") or [] if i not in out]
    return out


def scan_draft(isbn: str, status: str | None, *, who: str, ident: str, now: datetime):
    """The episode a scan is: the person's act, already read (nothing in it for a model)."""
    from api.services import episode_staging, when as when_mod

    instant = when_mod.utc_z(now)
    day = episode_ids.id_day(now)
    lines = ([status_line(status)] if status else []) + [f"**ISBN:** {isbn}"]
    return episode_staging.EpisodeDraft(
        title="Book scan", source_id=f"isbn:{who}:{ident}", timestamp=instant, original_date=day,
        source=SCAN_ORIGIN, origin=SCAN_ORIGIN, body="\n".join(lines) + "\n",
        extra={EPISODE_KEY: {"isbn": isbn, "status": status, "day": day, "dated": True}}, queue_for_sleep=False,
        writer=SCAN_ORIGIN)


def _upgrade_placeholders(memory_path: Path, index: BookIndex, today: str) -> list[str]:
    """A placeholder page (its number was a definite miss) whose number has an answer now takes the real title."""
    from api.services import book_lookup

    paths: list[str] = []
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        book = fm.get("book") if is_book(fm) and isinstance(fm.get("book"), dict) else None
        if not book or book.get("title_from") != "placeholder":
            continue
        for isbn in book.get("isbns") or []:
            hit = book_lookup.cached(isbn)
            if not (hit and hit.get("found")):
                continue
            facts = BookFacts(title=hit.get("title"), subtitle=hit.get("subtitle"),
                              authors=list(hit.get("authors") or []),
                              isbns=list(book.get("isbns") or []), work_id=hit.get("work_id"),
                              published=hit.get("published"), pages=hit.get("pages"), cover_id=hit.get("cover_id"),
                              title_from=str(hit.get("source") or "lookup"))
            episode = (fm.get("source_episodes") or [""])[0]
            entity_id, _, changed = ensure_page(memory_path, index, facts, episode, today)
            if changed:
                paths.append(f"entities/{entity_id}.md")
            break
    return paths


def _stamp_local_covers(memory_path: Path) -> list[str]:
    """Each Apple Books page takes the cover the app last posted for its asset (``book_covers``), by the index kept
    outside the bank. A page with none, or a changed cover, is one frontmatter write; otherwise nothing is touched."""
    from api.services import book_covers, logo_service

    covers = book_covers.read_index(logo_service.bank_name(memory_path))
    if not covers:
        return []
    paths: list[str] = []
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        book = fm.get("book") if is_book(fm) and isinstance(fm.get("book"), dict) else None
        sha = next((covers[a] for a in (book or {}).get("apple_books") or [] if a in covers), None)
        if not sha or book.get("local_cover") == sha:
            continue
        path = Path(f.path)
        parsed = markdown_parser.parse(path)
        markdown_parser.write(path, {**parsed.frontmatter, "book": {**book, "local_cover": sha}}, parsed.body)
        paths.append(f"entities/{path.name}")
    return paths


def _stamp_marks(path: Path, digest: str) -> None:
    with episode_ids.episode_lock(path.parent):
        parsed = markdown_parser.parse(path)
        if parsed.frontmatter.get("content_hash") == digest:
            markdown_parser.write(path, {**parsed.frontmatter, MARKS_KEY: digest}, parsed.body)


def _stamp_episode(path: Path, *, digest: str, entity_id: str, save: bool) -> bool:
    """Mark the episode applied (and, for a save, whose page it is) — under the episode lock, re-read first: a re-sync
    that landed meanwhile keeps its new body, and its new hash keeps it pending."""
    with episode_ids.episode_lock(path.parent):
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        if fm.get("content_hash") != digest:
            return False
        fm[APPLIED_KEY] = digest
        fm["book_entity_id"] = entity_id
        if save:
            fm[SAVE_KEY] = entity_id
        markdown_parser.write(path, fm, parsed.body)
        return True


def _facts_from_episode(fm: dict) -> BookFacts | None:
    """What the episode itself says, or None for a scan whose lookup has not answered yet."""
    from api.services import book_lookup

    rec = fm.get(EPISODE_KEY) or {}
    origin = str(fm.get("origin") or "")
    isbns = [i for i in (isbn13(x) for x in rec.get("isbns") or [rec.get("isbn")]) if i]
    if origin == SCAN_ORIGIN:
        if not isbns:
            return None
        hit = book_lookup.cached(isbns[0])
        if hit is None:
            return None
        if not hit.get("found"):
            return BookFacts(isbns=isbns, title_from="placeholder", door=origin)
        return BookFacts(title=hit.get("title"), subtitle=hit.get("subtitle"), authors=list(hit.get("authors") or []),
                         isbns=_merge_list(isbns, [i for i in (isbn13(x) for x in hit.get("isbns") or []) if i]),
                         work_id=hit.get("work_id"), published=hit.get("published"), pages=hit.get("pages"),
                         cover_id=hit.get("cover_id"), title_from=str(hit.get("source") or "lookup"), door=origin)
    title = str(rec.get("title") or "").strip()
    if not title and not isbns:
        return None
    return BookFacts(title=title or None, authors=[str(a) for a in rec.get("authors") or [] if str(a).strip()],
                     isbns=isbns, published=rec.get("published"), pages=rec.get("pages"),
                     apple_id=rec.get("asset_id") if origin == APPLE_ORIGIN else None,
                     goodreads_id=rec.get("goodreads_id") if origin == GOODREADS_ORIGIN else None,
                     title_from=origin if title else "placeholder", door=origin)


def _ask_same_book(memory_path: Path, entity_id: str, others: list[str]) -> list[str]:
    """The words of a new page's record fit these pages but not surely: one "same book?" question each, answered by
    folding one into the other — never a join without the person's answer. Never stops an apply."""
    from api.services import role_people

    paths: list[str] = []
    for other in others[:MAX_SAME_ASKED]:
        try:
            item = role_people.ask_same(memory_path, entity_id, other, "Two records of your books share a title.",
                                        classification=KIND)
        except Exception as exc:  # noqa: BLE001
            from api.services import tool_contract

            logger.warning(f"book question not asked: {tool_contract.where(exc)}")
            continue
        if item:
            paths.append(item)
    return paths


def _apply_marks(memory_path: Path, entity_id: str, episode_id: str, ep_path: Path, digest: str, *, observer: str,
                 today: str) -> list[str]:
    """What the person marked, word for word (``book_marks``, ruling 64), then its stamp. A page's marks are written
    before the stamp, so a stop re-does them, and the writer is idempotent."""
    from api.services import book_marks, page_redirects

    rel = [f"episodes/{ep_path.name}"]
    # The page may have been merged away since the record was applied: its marks follow the page it became. One with no
    # page at all has nowhere to go until a re-sync makes one, so it is stamped, not retried on every apply.
    entity_id = page_redirects.resolve(memory_path, entity_id) or entity_id
    if book_marks.apply(memory_path, entity_id, episode_id, observer=observer, today=today):
        rel.append(f"entities/{entity_id}.md")
    _stamp_marks(ep_path, digest)
    return rel


def apply_pending(memory_path: Path, *, today: date | None = None, limit: int = MAX_APPLY) -> dict:
    """Make every pending book episode's page, status, rating and marks (``book_marks``), with no model and no network.
    Returns ``{applied, waiting, pages_created, paths}`` (memory-relative, for the caller's own commit). The caller holds
    the bank's write admission (a route) or Sleep's window (the tail); this holds the page lock."""
    memory_path = Path(memory_path)
    today_s = (today or date.today()).isoformat()
    out = {"applied": 0, "waiting": 0, "pages_created": 0, "paths": []}
    todo = pending(memory_path, limit=limit)
    paths: list[str] = []
    with page_lock.page_lock(memory_path):
        index = BookIndex(memory_path)
        observer = _owner(memory_path)
        for entry in todo:
            fm = entry.frontmatter or {}
            try:
                facts = _facts_from_episode(fm)
                if facts is None:
                    out["waiting"] += 1
                    continue
                episode_id = str(fm.get("id") or Path(entry.path).stem)
                digest = str(fm.get("content_hash") or "")
                if fm.get(APPLIED_KEY) == digest and fm.get("book_entity_id"):   # only its marks are due
                    paths += _apply_marks(memory_path, str(fm["book_entity_id"]), episode_id, Path(entry.path), digest,
                                          observer=observer, today=today_s)
                    continue
                rec = fm.get(EPISODE_KEY) or {}
                status = rec.get("status") if rec.get("status") in STATUSES else None
                entity_id, created, changed = ensure_page(memory_path, index, facts, episode_id, today_s,
                                                          was=fm.get("book_entity_id"))
                out["pages_created"] += int(created)
                if changed:
                    paths.append(f"entities/{entity_id}.md")
                paths += _ask_same_book(memory_path, entity_id, index.unsure.pop(entity_id, []))
                # A scan of a book the person did nothing with yet is a save (quiet, ruling 30); Apple Books and
                # Goodreads records are saves by their origin, stamped too so every reader agrees.
                save = fm.get("origin") != SCAN_ORIGIN or status not in ACTED
                ep_path = Path(entry.path)
                if not _stamp_episode(ep_path, digest=str(fm.get("content_hash") or ""), entity_id=entity_id,
                                      save=save):
                    continue
                paths.append(f"episodes/{ep_path.name}")
                if status:
                    day = str(rec.get("day") or "")[:10] or today_s
                    quote = STATUS_WORDS[status]
                    if set_status(memory_path, entity_id, status=status, day=day, episode_id=episode_id,
                                  quote=quote, observer=observer, today=today_s):
                        paths.append(f"entities/{entity_id}.md")
                    # A happening needs a day that is the act's own (review of #600, B2): a scan is dated by when it
                    # was made (`episode`); a record only by the day its source gives for that status (`stated`: a
                    # finish date, a Date Read). A fallback day — the last open, the day it was shelved, the import —
                    # dates the status record and nothing more.
                    is_scan = fm.get("origin") == SCAN_ORIGIN
                    if status in ACTED and rec.get("day") and (is_scan or rec.get("dated") is True):
                        paths += record_happening(memory_path, entity_id, status=status, day=day,
                                                  episode_id=episode_id, quote=quote, observer=observer,
                                                  basis="episode" if is_scan else "stated")
                        paths.append(f"entities/{entity_id}.md")
                rating = rec.get("rating")
                if isinstance(rating, int) and 1 <= rating <= 5:
                    day = str(rec.get("rated_day") or rec.get("day") or "")[:10] or today_s
                    if set_rating(memory_path, entity_id, rating=rating, day=day, episode_id=episode_id,
                                  quote=f"{rating} of 5", observer=observer, today=today_s):
                        paths.append(f"entities/{entity_id}.md")
                if _marks_due(fm):
                    paths += _apply_marks(memory_path, entity_id, episode_id, ep_path, digest, observer=observer,
                                          today=today_s)
                out["applied"] += 1
            except Exception as exc:  # noqa: BLE001 — one bad record never stops the rest
                from api.services import tool_contract

                logger.warning(f"book episode not applied: {tool_contract.where(exc)}")
        try:
            paths += _upgrade_placeholders(memory_path, index, today_s)
        except Exception as exc:  # noqa: BLE001
            from api.services import tool_contract

            logger.warning(f"book placeholders not upgraded: {tool_contract.where(exc)}")
        try:
            bank_index.invalidate(memory_path)
            paths += _stamp_local_covers(memory_path)
        except Exception as exc:  # noqa: BLE001
            from api.services import tool_contract

            logger.warning(f"book covers not stamped: {tool_contract.where(exc)}")
    bank_index.invalidate(memory_path)
    # Ruling 61: a page a door just made may be the one a conversation already named.
    from api.services import book_said

    try:
        paths += book_said.apply_waiting(memory_path, today=today)
    except Exception as exc:  # noqa: BLE001
        from api.services import tool_contract

        logger.warning(f"book statuses said in a conversation not applied: {tool_contract.where(exc)}")
    out["paths"] = list(dict.fromkeys(paths))
    return out


def counts(memory_path: Path) -> dict:
    """Book pages by their current status (the open ``reading-status``), for a source row. Frontmatter scan plus one
    body parse per book page; no titles."""
    by = {s: 0 for s in STATUSES}
    total = 0
    for f in bank_index.files(Path(memory_path), "entities"):
        if not is_book(f.frontmatter or {}):
            continue
        total += 1
        try:
            claims = parse_claims(markdown_parser.parse(Path(f.path)).body)
        except Exception:  # noqa: BLE001
            continue
        record = _current_record(claims)
        current = record.object if record is not None else None
        if current in by:
            by[current] += 1
    return {"books": total, **by}


def utc_day(value) -> str | None:
    """A source's instant as the local calendar day it fell on (ruling 34's day), or None."""
    if not value:
        return None
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return episode_ids.id_day(at)
