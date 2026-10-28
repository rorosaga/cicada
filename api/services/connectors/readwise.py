"""Readwise — the person's highlights with their sources, complete (ruling 47 tier 2, G223's path table).

The browser sees one article at a time; Readwise holds every highlight the person made, from every book, article,
tweet and podcast, with where each came from. Its API is read with the person's own access token (from
``readwise.io/access_token``), only through the documented export endpoint, only ``GET`` — Cicada never writes
back. Readwise's terms (readwise.io/tos, read 2026-10-29) name exactly this use: section 8 lets the person "connect AI
assistants and other tools to your content in any of our apps through our APIs", and section 3's ban on "robots,
scrapers, or similar automated tools" excepts its APIs. The token is the person's whole account (Readwise offers no
read-only scope), so Cicada asks only the read endpoints and says so in the connect step.

What arrives, one episode per natural unit, keyed by Readwise's own ids:

* ``readwise:<book>:doc`` — the saved item: its title, author, kind, its source as a link, and the person's own
  document note as their words (``user:``). Dated by its first highlight.
* ``readwise:<book>:<YYYY-MM-DD>`` — that book's highlights made on one (UTC) day: each highlight is the document's
  words (``attachment [<title>]:`` with every line quoted — ``page`` evidence, never the person's), and the note the
  person wrote on it is their own words (``user:``). Dated when highlighted (read on time: three years of highlights
  are three years of reading, not one day). A highlight edited or deleted later rewrites or empties its day in place.

**Linked, never invented.** A document is linked to a page that already exists when the match is exact — its source
URL is a link already saved (``url_index``), or exactly one page that is not a person has its title — through the
episode's ``media_entity_id``. Nothing here creates a page: Sleep reads the episodes under its usual promotion rules.

**Incremental.** The export's ``updatedAfter`` returns only the highlights that changed, so a book that changed is
read again whole (``ids=``) before its days are rewritten; ``includeDeleted`` tells which books and highlights went.
A first sync reads the whole library, at most ``MAX_PAGES`` export pages a sync, carrying on from the export's own
cursor next time. Rate: Readwise allows 240 requests a minute on this endpoint (20 on its list endpoints); a 429's
``Retry-After`` is honoured once (``tier2.Client``).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.services import episode_ids, episode_scrub, episode_staging, media_ingestor
from api.services.connectors import tier2

CHANNEL_ID = "readwise"
LABEL = "Readwise"
LOGIN_MODE = "credentials"
CHANNEL_NOUN = "highlight day"
TIER = tier2.TIER
ORIGIN = "readwise"
SOURCE_PREFIX = "readwise:"
SCRUB_WRITER = "readwise"
TOKEN_ENV = "CICADA_READWISE_TOKEN"
FIELDS: tuple[dict, ...] = ({"name": TOKEN_ENV, "label": "Readwise access token", "secret": True},)
SECRET_NAMES: tuple[str, ...] = (TOKEN_ENV,)
API_BASE = "https://readwise.io/api/v2/"
TOKEN_HELP = "readwise.io/access_token"
READS = ("Reads your Readwise highlights and the notes you wrote on them, with the book or article each came from, "
         "using your own access token. Cicada only reads; it never changes anything in Readwise. Disconnect forgets "
         "the token; you can also delete it at readwise.io/access_token.")
REFUSED_WORDS = ("Readwise refused the access token. Get a new one at readwise.io/access_token and paste it in "
                 "Settings → Sources → Readwise.")

MAX_PAGES = 50
IDS_PER_REQUEST = 50
#: An incremental read starts a little before the last one did, so an edit made during that sync is not missed.
OVERLAP = timedelta(minutes=5)
TITLE_CAP = 300
TEXT_CAP = 8000
_LABEL_UNSAFE = re.compile(r"[\]\[\n\r]+")


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Token {token}", "Accept": "application/json"}


def is_connected() -> bool:
    return tier2.is_connected(_self())


def credential_fields() -> list[dict]:
    return tier2.credential_fields(_self())


def forget() -> None:
    tier2.forget(_self())


def _self():
    import sys

    return sys.modules[__name__]


async def check(client: tier2.Client) -> None:
    """Readwise's own token check: ``GET /auth/`` answers 204 for a valid token."""
    await client.get("auth/")


async def sync(memory_path: Path, *, http_fn=None, allow_fetch=None, scheduled: bool = False) -> dict:
    return await tier2.run(_self(), memory_path, http_fn=http_fn, allow_fetch=allow_fetch, scheduled=scheduled)


# --- reading ---------------------------------------------------------------------------------------------------------


async def _export(client: tier2.Client, **params) -> tuple[list[dict], str | None, bool]:
    """Every export page from ``params`` on, at most ``MAX_PAGES``: (books, the cursor to resume from, finished)."""
    books: list[dict] = []
    cursor = params.pop("pageCursor", None)
    for _ in range(MAX_PAGES):
        body = await client.get("export/", pageCursor=cursor, **params) or {}
        books.extend(r for r in (body.get("results") or []) if isinstance(r, dict))
        cursor = body.get("nextPageCursor") or None
        if not cursor:
            return books, None, True
    return books, cursor, False


async def fetch(client: tier2.Client, cursor: dict, memory_path: Path) -> tier2.Batch:
    started = datetime.now(timezone.utc)
    since = cursor.get("updated_after")
    resume = cursor.get("page_cursor")
    params: dict = {"includeDeleted": "true"}
    if since:
        params["updatedAfter"] = since
    if resume:
        params["pageCursor"] = resume
    changed, next_page, finished = await _export(client, **params)
    deleted = [b for b in changed if b.get("is_deleted")]
    live = {int(b["user_book_id"]): b for b in changed if not b.get("is_deleted") and b.get("user_book_id") is not None}
    if since and live:
        # An incremental page holds only the highlights that changed: read each changed book whole.
        ids = sorted(live)
        live = {}
        for start in range(0, len(ids), IDS_PER_REQUEST):
            chunk = ",".join(str(i) for i in ids[start:start + IDS_PER_REQUEST])
            books, _, _ = await _export(client, ids=chunk)
            live.update({int(b["user_book_id"]): b for b in books if b.get("user_book_id") is not None})
    links = _Links(memory_path)
    drafts: list[episode_staging.EpisodeDraft] = []
    for book in live.values():
        drafts.extend(drafts_for(book, links))
    batch = tier2.Batch(
        drafts=drafts,
        replaced=[f"{SOURCE_PREFIX}{i}" for i in live],
        deleted=[f"{SOURCE_PREFIX}{int(b['user_book_id'])}" for b in deleted if b.get("user_book_id") is not None],
        seen=sum(len(_live_highlights(b)) for b in live.values()),
    )
    if finished:
        batch.cursor = {"updated_after": (started - OVERLAP).isoformat()}
    else:
        # Not done: keep the old starting point and carry on from the export's own cursor next time.
        batch.cursor = {**({"updated_after": since} if since else {}), "page_cursor": next_page}
        batch.words = "Part of your library came in; the next sync brings the rest."
    return batch


# --- one book as episodes ------------------------------------------------------------------------------------------


def _clip(value, cap: int = TITLE_CAP) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= cap else text[: cap - 1].rstrip() + "…"


def _when(value) -> datetime | None:
    if not value:
        return None
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else None


def _live_highlights(book: dict) -> list[dict]:
    return [h for h in (book.get("highlights") or [])
            if isinstance(h, dict) and not h.get("is_deleted") and not h.get("is_discard") and (h.get("text") or "")]


def _source_link(book: dict) -> str | None:
    url = str(book.get("source_url") or "").strip()
    return url if url.startswith(("https://", "http://")) else None


class _Links:
    """Exact matches only: a saved link with the same URL, or the one non-person page with exactly this title."""

    def __init__(self, memory_path: Path):
        self.memory_path = Path(memory_path)
        self._urls: dict | None = None
        self._titles: dict[str, list[str]] | None = None

    def _title_map(self) -> dict[str, list[str]]:
        if self._titles is None:
            from api.services import bank_index

            titles: dict[str, list[str]] = {}
            for f in bank_index.files(self.memory_path, "entities"):
                fm = f.frontmatter or {}
                if str(fm.get("type") or "") == "person" or str(fm.get("status") or "") in ("archived", "dropped"):
                    continue
                for name in {str(fm.get("title") or ""), str(fm.get("name") or "")}:
                    if key := _title_key(name):
                        titles.setdefault(key, []).append(str(fm.get("id") or f.stem))
            self._titles = titles
        return self._titles

    def page_for(self, book: dict) -> str | None:
        if url := _source_link(book):
            if self._urls is None:
                self._urls = media_ingestor.load_url_index(self.memory_path)
            entry = self._urls.get(media_ingestor.url_hash(url))
            if isinstance(entry, dict) and entry.get("media_entity_id"):
                return str(entry["media_entity_id"])
        hits = sorted(set(self._title_map().get(_title_key(book.get("title")), [])))
        return hits[0] if len(hits) == 1 else None


def _title_key(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def _quote(text: str) -> str:
    return "\n".join("> " + line if line.strip() else ">" for line in str(text).strip()[:TEXT_CAP].splitlines())


def _note_lines(note) -> list[str]:
    text = " ".join(str(note or "").split())
    return [f"user: {text[:TEXT_CAP]}"] if text else []


def _head(book: dict) -> list[str]:
    title = _clip(book.get("readable_title") or book.get("title")) or "Untitled"
    lines = [f"# {title}", ""]
    meta = []
    if author := _clip(book.get("author")):
        meta.append(f"**By:** {author}")
    if category := _clip(book.get("category"), 40):
        meta.append(f"**Kind:** {category}")
    lines.extend(meta)
    if link := _source_link(book):
        lines.append(f"**Source:** [{title}]({link})")
    tags = [_clip(t.get("name"), 60) for t in (book.get("book_tags") or []) if isinstance(t, dict) and t.get("name")]
    if tags:
        lines.append("**Tags:** " + ", ".join(tags))
    return lines


def drafts_for(book: dict, links: _Links) -> list[episode_staging.EpisodeDraft]:
    """The saved item plus one episode per highlight day. A book with no live highlight is its saved item alone."""
    book_id = int(book["user_book_id"])
    title = _clip(book.get("readable_title") or book.get("title")) or "Untitled"
    label = _LABEL_UNSAFE.sub(" ", title)[:120].strip() or "highlight"
    page = links.page_for(book)
    common = {"readwise_book": book_id, "readwise_category": _clip(book.get("category"), 40)
              or None, "media_entity_id": page, "url": _source_link(book)}
    highlights = sorted(_live_highlights(book), key=lambda h: (str(h.get("highlighted_at") or h.get("created_at")
                                                                   or ""), h.get("location") or 0))
    by_day: dict[str, list[dict]] = {}
    for h in highlights:
        at = _when(h.get("highlighted_at")) or _when(h.get("created_at"))
        day = at.astimezone(timezone.utc).date().isoformat() if at else "undated"
        by_day.setdefault(day, []).append(h)
    first = next((at for h in highlights if (at := _when(h.get("highlighted_at")) or _when(h.get("created_at")))),
                 None)
    drafts = [_draft(f"{SOURCE_PREFIX}{book_id}:doc", title, _doc_body(book), first, common,
                     kind="document", updated=_newest(highlights))]
    for day, items in sorted(by_day.items()):
        at = min((a for h in items if (a := _when(h.get("highlighted_at")) or _when(h.get("created_at")))),
                 default=None)
        lines = _head(book) + ["", f"## Highlights{' on ' + day if day != 'undated' else ''}", ""]
        for h in items:
            lines.append(f"attachment [{label}]:")
            lines.append(_quote(h.get("text") or ""))
            lines.extend(_note_lines(h.get("note")))
            lines.append("")
        drafts.append(_draft(f"{SOURCE_PREFIX}{book_id}:{day}", f"{title} · highlights", "\n".join(lines).strip(),
                             at, {**common, "readwise_highlights": len(items)}, kind="highlights",
                             updated=_newest(items)))
    return drafts


def _newest(highlights: list[dict]) -> str | None:
    stamps = sorted(str(h.get("updated_at") or "") for h in highlights if h.get("updated_at"))
    return stamps[-1] if stamps else None


def _doc_body(book: dict) -> str:
    lines = _head(book)
    if note := _note_lines(book.get("document_note")):
        lines += ["", "## Your note", *note]
    lines.append("")
    lines.append(f"{len(_live_highlights(book))} highlight(s) in Readwise.")
    return "\n".join(lines).strip()


def _draft(sid: str, title: str, body: str, at: datetime | None, common: dict, *, kind: str,
           updated: str | None) -> episode_staging.EpisodeDraft:
    scrubbed_title, _ = episode_scrub.scrub(title)
    extra = dict(common)
    extra["readwise_unit"] = kind
    when = at.astimezone(timezone.utc) if at else None
    return episode_staging.EpisodeDraft(
        title=scrubbed_title, source_id=sid, source_updated_at=updated,
        timestamp=when.isoformat() if when else None,
        original_date=episode_ids.id_day(when) if when else None,
        source=ORIGIN, origin=ORIGIN, body=body, extra=extra, writer=SCRUB_WRITER, redate=True)
