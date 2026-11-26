"""A save the person made inside a site, noticed by the app from the control they clicked (G221).

The app sees the person's own click on a site's save control (X's Bookmark, Instagram's Save, GitHub's Star, TikTok's
Favorite, Reddit's Save in a post's menu, a list in YouTube's save sheet) and posts the post's own link. This module decides what that link is here: which site it belongs to, the one
spelling it is stored under, the other spellings the same post arrives by from another door (a list read, a connector,
a pasted link), and the origin and list label that make it the same row those doors write. It also keeps the one mark
an unsave leaves: ``left_site_at`` on the save's episode, cleared when the post is saved again. Nothing here fetches a
page or calls a model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from api.services import episode_scrub, episode_staging, saved_lists

#: The episode key an unsave leaves: when the person took the post off their list on the site.
LEFT_KEY = "left_site_at"
#: The post's own words, as its page showed them to the person: a short preview, never the person's words.
TEXT_MAX = 500
#: A video saved on YouTube: the origin and the list label ``cicada_record_youtube_list`` writes for Watch later.
YOUTUBE_ORIGIN = "youtube-playlist"
YOUTUBE_LIST = "Watch later"
TITLE_MAX = 80


@dataclass(frozen=True)
class Target:
    site: str
    #: The site's name, as the person knows it.
    name: str
    origin: str
    folder: str
    url: str
    aliases: tuple[str, ...]


#: GitHub's own first path segments, which are never an account.
_GITHUB_OWN = frozenset({
    "sponsors", "stars", "orgs", "apps", "topics", "collections", "trending", "settings", "marketplace", "features",
    "explore", "notifications", "pulls", "issues", "search", "login", "join", "about", "pricing", "enterprise", "new",
    "codespaces", "users", "site"})
_GITHUB_REPO = re.compile(r"^/(?P<owner>[A-Za-z0-9-]{1,39})/(?P<repo>[A-Za-z0-9._-]{1,100})/?$")


def _github(url: str) -> tuple[str, tuple[str, ...]] | None:
    try:
        parsed = urlparse(str(url or "").strip())
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() not in ("github.com", "www.github.com"):
        return None
    found = _GITHUB_REPO.match(parsed.path or "")
    if found is None or found.group("owner").lower() in _GITHUB_OWN:
        return None
    return f"https://github.com/{found.group('owner')}/{found.group('repo')}", ()


def target(site: str, url: str) -> Target | None:
    """Where a noticed save goes, or ``None`` for a site with no saved list here or a link that is not a post of it.

    A site of ``saved_lists.PLATFORMS`` uses that table's origin, list label and canonical link, so the row is the one
    ``cicada_record_saved_list`` writes. A starred repository is a saved link under the stars' own origin, which the
    GitHub connector's next sync makes the repository's page in place (``github_repos.upsert``)."""
    if site == "github":
        found = _github(url)
        return None if found is None else Target("github", "GitHub", "github-starred", "Stars", found[0], found[1])
    if site == "youtube":
        # A video put on Watch later or a playlist: the row the YouTube lists' reader and a Takeout write
        # (``youtube-playlist``, by the video's one canonical link), so the three doors are one row.
        from api.services import watch_history

        watched = watch_history.watch_url(url)
        if watched is None or watched[0] != "youtube":
            return None
        return Target("youtube", "YouTube", YOUTUBE_ORIGIN, YOUTUBE_LIST, watched[1], ())
    platform = saved_lists.PLATFORMS.get(site)
    if platform is None or not platform.folder or platform.base:
        return None   # a second list of a site (X likes, G245) is read by the person's agent, never noticed as a click
    found = saved_lists.canonical(site, url)
    if found is None:
        return None
    return Target(site, platform.name, platform.origin, platform.folder, found[0], tuple(found[1]))


def list_label(target: Target, folders) -> str:
    """The list a save is filed under. A site with one saved list uses its own label; on YouTube a video goes to
    Watch later or to a playlist the person named, so the first folder the app read (the playlist's own name, as the
    person wrote it) is the label, as a Takeout names the same playlist."""
    if target.site == "youtube":
        for folder in folders or ():
            name = " ".join(str(folder or "").split())[:120]
            if name:
                return name
    return target.folder


def clean_text(text) -> str:
    """The post's words as one scrubbed line, capped."""
    words = episode_scrub.scrub(" ".join(str(text or "").split()))[0]
    return (words[:TEXT_MAX].rstrip() + "…") if len(words) > TEXT_MAX else words


def title_for(text: str, fallback: str) -> str:
    """The post's first words when the page showed them, else the title made from its link."""
    if not text:
        return fallback
    return (text[:TITLE_MAX].rstrip() + "…") if len(text) > TITLE_MAX else text


def _set_left(path: Path, at: str | None) -> bool:
    def edit(fm: dict) -> bool:
        held = fm.get(LEFT_KEY) or None
        if at is None:
            if held is None:
                return False
            fm.pop(LEFT_KEY, None)
            return True
        if held is not None:
            return False   # already off the list: the moment it left stands (a second click is not a later leaving)
        fm[LEFT_KEY] = at
        return True

    return episode_staging.amend_frontmatter(path, edit)


def mark_left(path: Path, at: str) -> bool:
    """The person took the post off their list on the site. The save and everything said about it stay; only the
    mark is added. Returns whether the file changed."""
    return _set_left(path, at)


def clear_left(path: Path) -> bool:
    """The post is on the person's list again."""
    return _set_left(path, None)


def on_list(memory_path: Path, url: str) -> bool:
    """Whether Cicada holds the post as on the person's list on its site: a save is kept for it and it carries no
    ``left_site_at`` mark. What decides the direction of a click the app saw change a save control but could not read
    the direction of (``POST /sources/site-change``): a post held as on the list was taken off it, any other was
    saved. ``url`` is the canonical link (``Target.url``)."""
    from api.services import markdown_parser, saved_why

    try:
        _, _, path = saved_why.find_episode(memory_path, url)
    except saved_why.SavedWhyError:
        return False
    try:
        return left_at(markdown_parser.parse(path).frontmatter) is None
    except (OSError, ValueError):
        return False


def left_at(fm: dict | None) -> str | None:
    value = (fm or {}).get(LEFT_KEY)
    return str(value) if value else None
