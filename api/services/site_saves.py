"""A save the person made inside a site, noticed by the app from the control they clicked (G221).

The app sees the person's own click on a site's save control (X's Bookmark, Instagram's Save, GitHub's Star, TikTok's
Favorite) and posts the post's own link. This module decides what that link is here: which site it belongs to, the one
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

from api.services import episode_ids, episode_scrub, markdown_parser, saved_lists
from api.services.episode_staging import STAGE_LOCK

#: The episode key an unsave leaves: when the person took the post off their list on the site.
LEFT_KEY = "left_site_at"
#: The post's own words, as its page showed them to the person: a short preview, never the person's words.
TEXT_MAX = 500
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
    platform = saved_lists.PLATFORMS.get(site)
    if platform is None or not platform.folder:
        return None
    found = saved_lists.canonical(site, url)
    if found is None:
        return None
    return Target(site, platform.name, platform.origin, platform.folder, found[0], tuple(found[1]))


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
    with STAGE_LOCK, episode_ids.episode_lock(Path(path).parent):
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        if (fm.get(LEFT_KEY) or None) == at:
            return False
        if at is None:
            fm.pop(LEFT_KEY, None)
        else:
            fm[LEFT_KEY] = at
        if "turns" in fm:
            fm["turns"] = fm.pop("turns")  # the sidecar stays the last key
        markdown_parser.write(path, fm, parsed.body)
        return True


def mark_left(path: Path, at: str) -> bool:
    """The person took the post off their list on the site. The save and everything said about it stay; only the
    mark is added. Returns whether the file changed."""
    return _set_left(path, at)


def clear_left(path: Path) -> bool:
    """The post is on the person's list again."""
    return _set_left(path, None)


def left_at(fm: dict | None) -> str | None:
    value = (fm or {}).get(LEFT_KEY)
    return str(value) if value else None
