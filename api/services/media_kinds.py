"""What a ``media`` page is, as a person would sort it, and where it came from (ROR-138, owner 2026-11-06: "the media
page is extremely dense... separate stuff to new categories. Books, Articles, Videos, Pictures, etc. ... show a small
logo of where it comes from, like provenance").

Derived on every read from the page's own frontmatter (``media.kind``, ``media.media_type``, ``origin``) — never stored,
no I/O, no fetch. The app draws the kind's name and the origin's mark; a feed item (RSS/Atom) is its own kind because
someone published it to the person, who never saved it (ruling 39), and the app keeps a feed item the person has not
mentioned out of Media's main view.
"""
from __future__ import annotations

from api.services import episode_time, saved_posts

#: The kinds, in the order the app lists them. The app words each one; the ids are the wire.
#: G246 (ruling 81): ``post`` is a saved post drawn as a page (one that earned its page), named only once the flip is on
#: (``saved_posts.HIDE_POSTS``); ``list`` is a list's own small page (``media.kind: list``).
KINDS = ("book", "article", "video", "picture", "paper", "repository", "link", "file", "feed", "post", "list")

#: A saved post or article an origin brought in as a read, rather than a bare bookmark.
_ARTICLE_ORIGINS = frozenset({"substack-saved", "saved-link"})
_PICTURE_TYPES = frozenset({"instagram", "image", "photo", "pinterest"})
_VIDEO_TYPES = frozenset({"youtube", "video"})


def _media(fm: dict) -> dict:
    media = (fm or {}).get("media")
    return media if isinstance(media, dict) else {}


#: An origin the saved-lists table files under that the app's mark table spells another way (``source_overview`` gives
#: Pinterest's both origins the one mark ``pinterest``).
_MARK_ALIASES = {"pinterest-saved": "pinterest"}


def origin_of(fm: dict) -> str | None:
    """The origin id the page was brought in by (its ``origin:``), as the app's mark table knows it; None when none."""
    origin = str((fm or {}).get("origin") or "").strip().lower()
    listed = (fm or {}).get("list")
    if _media(fm).get("kind") == "list" and isinstance(listed, dict):
        # A list's page: the source it is a list of is its origin (the app's mark table), never the word "list".
        source = str(listed.get("source") or "").strip().lower()
        if not source:
            # "Saved another way" is no list of one source (its page records ``source: ""``): it wears its site's mark.
            from api.services import saved_lists

            platform = saved_lists.PLATFORMS.get(str(listed.get("site") or "").strip().lower())
            source = platform.origin if platform is not None else ""
        return _MARK_ALIASES.get(source, source) or None
    if origin == "book":
        # A book page's own origin is the kind, not a source: the door it came in through is the source (Apple Books,
        # Goodreads, a scan), in the same fixed order the page's words use (`books.door_words`).
        book = (fm or {}).get("book")
        doors = {str(d) for d in ((book.get("doors") if isinstance(book, dict) else None) or [])}
        if isinstance(book, dict):
            doors |= {"apple-books"} if book.get("apple_books") else set()
            doors |= {"goodreads"} if book.get("goodreads") else set()
        return next((d for d in ("apple-books", "goodreads", "book-scan") if d in doors), None)
    return _MARK_ALIASES.get(origin, origin) or None


def channel_of(fm: dict) -> str | None:
    """The channel or publication a page came from, as its ``media.channel`` names it (a YouTube channel, a Substack
    publication); None when it names none. A name only — no picture is fetched for it (`storage.md`, pictures)."""
    channel = " ".join(str(_media(fm).get("channel") or "").split())[:80]
    return channel or None


def kind_of(fm: dict) -> str | None:
    """The kind of a ``media`` page; None for every other page."""
    fm = fm or {}
    if str(fm.get("type") or "").strip().lower() != "media":
        return None
    media = _media(fm)
    declared = str(media.get("kind") or "").strip().lower()
    if declared in ("book", "paper", "repository", "list"):
        return declared
    media_type = str(media.get("media_type") or "").strip().lower()
    if declared == "file":
        return "video" if media_type in _VIDEO_TYPES else "picture" if media_type in _PICTURE_TYPES else "file"
    if episode_time.is_feed_item(fm):
        return "feed"
    if saved_posts.HIDE_POSTS and saved_posts.is_post(fm):
        return "post"   # one that earned its page: a row is no node, so only an earned post reaches a reader here
    if media_type in _VIDEO_TYPES:
        return "video"
    if media_type in _PICTURE_TYPES:
        return "picture"
    return "article" if origin_of(fm) in _ARTICLE_ORIGINS else "link"
