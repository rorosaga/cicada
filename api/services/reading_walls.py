"""Which saved pages Cicada's own reader could not read — the wall pages (G166, ruling 14 amended 2026-09-30).

There is no pre-picked list of sites. A page is a **wall page** when Cicada's
reader (save-time enrichment, the in-cycle pass, the tail backfill) failed to
open it because of a wall, or because the backend never requests its host at
all (R-RW4). Wall pages are grouped by site (``reading_hosts.site_of``); the
sites they belong to are what Settings, Reading the web, lists for the person to
allow an agent to read with their own browser.

Pure over a page's frontmatter and URL: no network, no DNS, no file written.
Every kind comes from a stamp the fetchers already write (``fetch_status``),
plus the closed host set:

* ``walled``  — a host the backend never requests (``reading_hosts.is_walled``);
* ``refused`` — ``fetch_status: blocked`` (401/403/407/451, or a redirect onto a
  login or consent host);
* ``consent`` — ``interstitial`` / ``skipped:interstitial`` (a cookie or consent page);
* ``login``   — ``skipped:login_wall``.

``js`` is reserved for G164/G167 (a page that needs JavaScript). Never a wall
page: ``failed:*`` (a timeout, a 500, an empty body), an archived or dropped
page, a paper, any URL the structural gate refuses (video, local, secret-bearing,
vendor), a URL that is itself a sign-in or consent page (nothing behind it to
read), and **a page that already holds words** — a live ``describes`` claim, an
agent's read stamp, a substantive ``## Description`` or a ``description_source``.
That last rule keeps a connector-saved post whose text Cicada already holds out
of the list (the reuse tier never runs for a walled host, so such a page has a
description and no claim). A connector whose saved item IS the post (``x-bookmarks``:
the post's text rides ``RawItem.note`` into the page's ``## Notes``) holds words
through any non-empty ``## Notes`` too. A Reddit or Pinterest save is a link out: its
title or pin description is not the linked page, so such a page is surfaced on purpose.

The words check parses a page body, so it runs only for the small set of
candidates that passed the stamp rules, memoised per ``(bank, id, mtime_ns,
size)`` in a bounded LRU (a long-lived backend never leaks).
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from api.services import bank_index, media_ingestor, reading_hosts

WALL_KINDS = ("walled", "login", "consent", "refused")  # closed; "js" is reserved (G164/G167)
_MEMO_MAX = 4096
_HIDDEN = frozenset({"archived", "dropped"})
#: Connector origins whose ``## Notes`` is the saved item's own text (the post), not a note about it.
_TEXT_IN_NOTES_ORIGINS = frozenset({"x-bookmarks"})

_lock = threading.Lock()
_words_memo: "OrderedDict[tuple, bool]" = OrderedDict()
#: Counts body parses done for the words check — read by the "only candidates are parsed" test.
body_parses = 0


class DeadlineExceeded(Exception):
    """A scan given a ``deadline`` ran out of time. Pages already judged stay memoised, so the
    next (or a background) scan finishes what this one began."""


@dataclass(frozen=True)
class WallPage:
    entity_id: str
    url: str
    url_hash: str
    site: str
    wall: str
    title: str
    saved_at: str
    origin: str
    read_by_agent: bool
    words: bool  # the page already holds words (a claim, an agent read, a description)
    episodes: tuple = ()  # the page's source episodes (an agent's save is told by the episode's session_id)

    @property
    def waiting(self) -> bool:
        """A wall page nobody has put words on yet — what an allowed site queues."""
        return not self.words and not self.read_by_agent


def _min_len() -> int:
    try:
        from api.config import get_settings

        return int(getattr(get_settings(), "link_enrich_min_desc_len", 120) or 120)
    except Exception:  # noqa: BLE001
        return 120


def wall_kind(url: str, fm: dict) -> str | None:
    """The wall kind of a page from its URL and stamps alone (first match wins),
    or ``None``. Does not look at the body — :func:`scan` adds the words check."""
    from api.services import link_enrichment

    if not url:
        return None
    status = str((fm or {}).get("fetch_status") or "")
    if reading_hosts.is_walled(url):
        kind = "walled"
    elif status == "blocked":
        kind = "refused"
    elif status in ("interstitial", "skipped:interstitial"):
        kind = "consent"
    elif status == "skipped:login_wall":
        kind = "login"
    else:
        return None
    # The saved URL is itself a sign-in or consent page (a bookmark of one): there
    # is nothing behind it to read, and its host would list as a "site".
    if link_enrichment.classify_page("", url) is not None:
        return None
    return kind


def _agent_read(fm: dict) -> bool:
    read = (fm or {}).get("read")
    return isinstance(read, dict) and read.get("by") == "agent"


def _notes_section(body: str) -> str:
    from api.services.claims import strip_claims_block
    from api.services.entity_body import parse_sections

    return (parse_sections(strip_claims_block(body)).get("Notes", "") or "").strip()


def _holds_words(entity_id: str, fm: dict, body_fn, key: tuple) -> bool:
    """A live ``describes`` claim, a substantive ``## Description``, a
    ``description_source``, or (a post connector) the post's own text in ``## Notes``
    — memoised, bounded."""
    global body_parses
    if _agent_read(fm) or fm.get("description_source"):
        return True
    with _lock:
        if key in _words_memo:
            _words_memo.move_to_end(key)
            return _words_memo[key]
    body = body_fn()
    with _lock:
        body_parses += 1
    from api.services import link_enrichment
    from api.services.claims import parse_claims

    min_len = _min_len()
    words = False
    try:
        words = any(c.predicate == "describes" and not c.valid_to for c in parse_claims(body or ""))
    except Exception:  # noqa: BLE001
        words = False
    if not words:
        text = link_enrichment._claim_description(link_enrichment._extract_description_section(body or ""), min_len)
        words = link_enrichment._is_substantive(text, min_len)
    if not words and str(fm.get("origin") or "").strip().lower() in _TEXT_IN_NOTES_ORIGINS:
        words = bool(_notes_section(body or ""))
    with _lock:
        _words_memo[key] = words
        while len(_words_memo) > _MEMO_MAX:
            _words_memo.popitem(last=False)
    return words


def _page(memory_path: Path, entity_id: str, fm: dict, body_fn, mtime_ns: int, size: int) -> WallPage | None:
    from api.services import papers

    if fm.get("type") != "media" or str(fm.get("status") or "active") in _HIDDEN or papers.is_paper(fm):
        return None
    media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
    url = str(media.get("url") or "").strip()
    if not url:
        return None
    kind = wall_kind(url, fm)  # cheap: stamps and the closed host set
    if kind is None or not reading_hosts.classify(url).ok:
        return None
    words = _holds_words(entity_id, fm, body_fn, (str(memory_path), entity_id, mtime_ns, size))
    return WallPage(
        entity_id=entity_id, url=url, url_hash=str(media.get("url_hash") or media_ingestor.url_hash(url)),
        site=reading_hosts.site_of(url), wall=kind, title=str(fm.get("name") or entity_id),
        saved_at=str(fm.get("saved_at") or fm.get("created") or media.get("saved_at") or "")[:10],
        origin=str(fm.get("origin") or ""), read_by_agent=_agent_read(fm), words=words,
        episodes=tuple(str(e) for e in (fm.get("source_episodes") or []) if isinstance(e, str))[:4],
    )


def page_for(memory_path: Path, entity_id: str, fm: dict, body: str, *, mtime_ns: int = 0, size: int = 0) -> WallPage | None:
    """A page the caller already parsed (``GET /sources`` does), as a wall page or
    ``None`` — the same rules as :func:`scan`, no second parse."""
    try:
        return _page(memory_path, entity_id, fm or {}, lambda: body, mtime_ns, size)
    except Exception:  # noqa: BLE001
        return None


def scan(memory_path: Path, *, deadline: float | None = None, clock=time.monotonic) -> list[WallPage]:
    """Every wall page in the bank, oldest saved first. One ``bank_index`` pass
    over the media pages (their frontmatter is already cached); only pages that
    pass the stamp rules have their body read, and only once per file version.
    ``deadline`` (a ``clock()`` value) bounds a caller with a hard budget — the recall
    hook: past it the scan raises :class:`DeadlineExceeded` instead of parsing on."""
    out: list[WallPage] = []
    for f in bank_index.files(Path(memory_path), "entities"):
        if not f.stem.startswith("media-"):
            continue
        if deadline is not None and clock() >= deadline:
            raise DeadlineExceeded
        try:
            page = _page(memory_path, f.stem, f.frontmatter or {}, f.body, f.mtime_ns, f.size)
        except Exception:  # noqa: BLE001 — one odd page is no list
            continue
        if page is not None:
            out.append(page)
    out.sort(key=lambda p: (p.saved_at, p.entity_id))
    return out


def scan_one(memory_path: Path, url: str) -> WallPage | None:
    """One saved page by URL (through the dedup index), or ``None`` when it is not
    saved or is not a wall page — the record path uses this, so it never walks
    the bank."""
    from api.services import markdown_parser

    entry = media_ingestor.load_url_index(Path(memory_path)).get(media_ingestor.url_hash(url))
    entity_id = str((entry or {}).get("media_entity_id") or "")
    if not entity_id:
        return None
    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    try:
        st = path.stat()
        parsed = markdown_parser.parse(path)
    except (OSError, ValueError):
        return None
    try:
        return _page(memory_path, entity_id, parsed.frontmatter or {}, lambda: parsed.body, st.st_mtime_ns, st.st_size)
    except Exception:  # noqa: BLE001
        return None


def reset_memo() -> None:
    """Tests only."""
    global body_parses
    with _lock:
        _words_memo.clear()
        body_parses = 0
