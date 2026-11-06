"""What a ``media`` page is, as a person would sort it, and where it came from (ROR-138, owner 2026-11-06: "the media
page is extremely dense... separate stuff to new categories. Books, Articles, Videos, Pictures, etc. ... show a small
logo of where it comes from, like provenance").

Derived on every read from the page's own frontmatter (``media.kind``, ``media.media_type``, ``origin``) — never stored,
no I/O, no fetch. The app draws the kind's name and the origin's mark; a feed item (RSS/Atom) is its own kind because
someone published it to the person, who never saved it (ruling 39), and the app keeps a feed item the person has not
mentioned out of Media's main view.
"""
from __future__ import annotations

from api.services import episode_time

#: The kinds, in the order the app lists them. The app words each one; the ids are the wire.
KINDS = ("book", "article", "video", "picture", "paper", "repository", "link", "file", "feed")

#: A saved post or article an origin brought in as a read, rather than a bare bookmark.
_ARTICLE_ORIGINS = frozenset({"substack-saved", "saved-link"})
_PICTURE_TYPES = frozenset({"instagram", "image", "photo", "pinterest"})
_VIDEO_TYPES = frozenset({"youtube", "video"})


def _media(fm: dict) -> dict:
    media = (fm or {}).get("media")
    return media if isinstance(media, dict) else {}


def origin_of(fm: dict) -> str | None:
    """The origin id the page was brought in by (its ``origin:``), as the app's mark table knows it; None when none."""
    origin = str((fm or {}).get("origin") or "").strip().lower()
    return origin or None


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
    if declared in ("book", "paper", "repository"):
        return declared
    media_type = str(media.get("media_type") or "").strip().lower()
    if declared == "file":
        return "video" if media_type in _VIDEO_TYPES else "picture" if media_type in _PICTURE_TYPES else "file"
    if episode_time.is_feed_item(fm):
        return "feed"
    if media_type in _VIDEO_TYPES:
        return "video"
    if media_type in _PICTURE_TYPES:
        return "picture"
    return "article" if origin_of(fm) in _ARTICLE_ORIGINS else "link"
