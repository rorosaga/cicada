"""One small page for each list of saved things, and for each folder or playlist in one (G246, ruling 81, owner
2026-11-24: "maybe a small entity page that has all the saved posts would be good, no? i want to somehow see saved things
somewhere even if i haven't referred to them yet").

**This module is the one writer of these pages** (the way ``media_pages`` is the one writer of a recording's and
``github_repos`` of a repository's): a list of posts (a site's bookmarks, likes, reposts, saved posts) and each folder,
collection or board on a site that has them is a ``media`` page with ``media.kind: list``, born here by file and git work
alone — no model, nothing at capture time — when the list's **first item arrives and not before**. Stage 1 never produces
``media``; these pages are never projects (ruling 56).

**What the page holds, and what it does not.** It holds what the list *is*: its name, one fixed sentence (the list's kind
and its site, never a model's words), the site's mark, the day it was born, and the list's address (``list:``: its site,
its stream, its folder). It holds nothing that can go stale: **the count, the newest day, the rows, when the list was last
read and a folder's reason are read from the saves every time the page is served** (:func:`block`), newest first, as the
same rows the Sources page uses (``channel_items.items``), so the page cannot be out of date and no read of a list commits
a file. The page is written once, again only if the list's name changes (a name the person gave it stands), and when its
source is removed.

**A list page is not a saved item.** It has ``origin: list`` (never a list's own origin, or it would be a row of its own
list), an id that does not start with ``media-`` (``inject_media_edges``, ``link_enrichment`` and ``link_recon`` glob
``media-*.md``), no link, no ``tags`` and no ``member of`` edge — a list is never a hub (2026-10-19). It is never quiet and
never decays (a ``media`` page is evergreen), never merged (``entity_merge`` refuses), never a project, never asked about
(``inbox_service``), never given facts by Sleep (``entity_resolver`` treats it as a file page, whose name is no one's name),
and no member of any stream or hub. A browser's own bookmark folders get none, and neither do lists of works (a playlist, a
Substack list): those are a property of what they hold.

**Which lists (owner 2026-11-25: "build the whole thing, and then we also do the page per thing").** Every kind of list a
saved page can be on (:func:`kinds`): each stream of a site that counts by membership (X, Instagram, LinkedIn, Reddit,
Pinterest, TikTok, Spotify; YouTube's Watch later, Liked videos and Playlists; Substack's saved), with one page per folder
a site files saves into (``save_folders``) and per YouTube playlist; GitHub's stars and the person's own repositories;
each browser's bookmarks with one page per bookmark folder; the feeds, one per feed; and each door's books. Every saved
thing keeps its own page as well: a list page stands for the list (the graph draws it as one bubble that opens onto its
pages), it replaces nothing. This reverses, for these pages only, "a saved list is provenance, never a tag or a hub" and
"playlists not hubs" (2026-10-19): a list page is still no hub and no tag, and holds no ``member of`` edge. YouTube's watch
history makes no pages (one record a day), so it has no list. A list or folder with nothing in it is not drawn and not
counted (derived on read), so a renamed folder leaves no orphan node; a page the person archived or dropped keeps its key
and is never made again; turning a list off keeps its page; **removing a source retires its pages undoably**
(:func:`retire_source`: status ``archived`` in one commit, git keeps the rest).

**Which list each page is on, and what sits inside it** (:func:`groups`): the one answer the graph, Clusters and Home read.
A member that earned a place in the person's record (``saved_posts.earned_saves``: their note, reason, words, Keep as a
page, a conversation or claim of theirs, a project tie) is drawn outside its list, joined to it; the rest sit inside.

**Ships dark.** While :data:`ON` (or ``saved_posts.HIDE_POSTS``) is ``False`` this module **writes nothing**: no list page
file is born, so there is nothing for any reader of the pages folder — the status count, the search index, a hub, the
graph — to show. :func:`groups` answers either way (with ``has_page`` false). The first sync after the switch makes every
list's page at once.

**Rails.** The writer runs only on the home (a replica refuses), never into a demo bank, inside ``write_admission`` and the
page lock, one commit per batch under ``cicada``, and a bank Sleep holds is tried again (``media_pages.RETRY_S``). The page
holds no per-Mac number (when the list was last read lives outside every bank), and every name comes from the tables
(``saved_lists.PLATFORMS``), never from a person: two computers over one bank make the same pages.
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from loguru import logger

from api.services import (bank_index, decay_policy, demo_guard, git_service, id_utils, markdown_parser, page_lock,
                          replica_guard, saved_at, saved_posts, write_admission)
from api.services.id_utils import sanitize_id

#: **The switch** (owner 2026-11-25: "build the whole thing, and then we also do the page per thing"): list pages are written
#: for every kind of list while every saved thing keeps its own page. ``False`` until the graph draws a list as one bubble;
#: :func:`groups` answers either way. ``saved_posts.HIDE_POSTS`` turns the writer on too, as it did before.
ON = False


def enabled() -> bool:
    """Are list pages written and drawn? :data:`ON`, or the older posts-as-rows switch."""
    return bool(ON or saved_posts.HIDE_POSTS)

KIND = "list"
#: The page's own origin: never a list's (``source_streams._build_members`` would count the page a member of its own list).
PAGE_ORIGIN = "list"
PREFIX = "list-"
TRIGGER_SYNC = "sync/list_pages"
TRIGGER_USER = "user/list_pages"
#: Pages written under one admission and one commit.
BATCH = 100
SETTLE_S = 3.0          # a burst of reads folds into one run
RETRY_S = 60.0          # Sleep held the pages: try again
SLUG_MAX = 40
#: How many of a list's newest rows ride in its block (the app draws its own five from the items route).
RECENT = 5
#: What a page of a list that left the table says it was retired for (``retired_by``).
RETIRED_SOURCE = "source-removed"

#: How a list's own name reads in "Posts you <verb> on <site>." Anything not here reads "Posts in your <label> on <site>."
_VERBS = {"bookmarks": "bookmarked", "likes": "liked", "liked posts": "liked", "reposts": "reposted", "saved": "saved",
          "saved posts": "saved", "upvoted": "upvoted", "favorites": "favorited", "pins": "pinned"}


# --------------------------------------------------------------------------- reading a page


def is_list(fm: dict | None) -> bool:
    """Is this page a list's own page (``media.kind: list``)? Pure: the one test every reader asks."""
    fm = fm or {}
    media = fm.get("media")
    return str(fm.get("type") or "").strip().lower() == "media" and isinstance(media, dict) \
        and str(media.get("kind") or "").strip().lower() == KIND


def list_of(fm: dict | None) -> dict | None:
    """The page's ``list:`` block (``{site, stream, folder, source, label}``), or None for any other page."""
    raw = (fm or {}).get("list") if is_list(fm) else None
    if not isinstance(raw, dict) or not str(raw.get("stream") or "").strip():
        return None
    folder = " ".join(str(raw.get("folder") or "").split())
    return {"site": str(raw.get("site") or ""), "stream": str(raw["stream"]).strip(), "folder": folder or None,
            "source": str(raw.get("source") or ""), "label": str(raw.get("label") or "")}


def _cf(text) -> str:
    return " ".join(str(text or "").split()).casefold()


# --------------------------------------------------------------------------- the lists there can be


@dataclass(frozen=True)
class Want:
    """One list a page may stand for."""
    id: str                  # the page's id
    site: str                # the source group (``x``)
    site_name: str           # "X"
    stream: str              # ``x.bookmarks``
    channel: str             # the items route's channel
    key: str                 # the saved-lists table key (``x``, ``x-likes``): where "last read" lives, per Mac
    origin: str              # the stream's own origin (the app's mark table has it: ``x-bookmarks``)
    label: str               # "Bookmarks"
    folder: str | None       # the folder's name as the site shows it, or None for the whole list
    folded: str              # the folder, folded, or ""
    name: str
    sentence: str


def _noun(label: str) -> str:
    folded = _cf(label)
    return "saved posts" if folded in ("saved", "saved posts") else folded or "list"


_FOLDER_WORD = {"videos": "playlist", "items": "feed"}


def sentence(site_name: str, label: str, folder: str | None = None, *, noun: str = "posts", site: str = "") -> str:
    """The one fixed line a page says about itself — the list's kind and its site, no model's words."""
    if noun != "posts":
        return _other_sentence(site_name, label, folder, noun, site)
    if _cf(label) == _cf(saved_posts.ANOTHER_LABEL) and not folder:
        return (f"Posts from {site_name} you saved another way: a link you pasted, a browser bookmark, "
                f"or a link an agent or a chat saved for you.")
    if folder:
        return f"Posts in “{folder}”, a folder of your {_noun(label)} on {site_name}."
    verb = _VERBS.get(_cf(label))
    return f"Posts you {verb} on {site_name}." if verb else f"Posts in your {_noun(label)} on {site_name}."


def _other_sentence(site_name: str, label: str, folder: str | None, noun: str, site: str) -> str:
    Noun = noun[:1].upper() + noun[1:]
    if site.startswith("browser:"):
        return (f"Pages in “{folder}”, a folder of your {site_name} bookmarks." if folder
                else f"Pages you bookmarked in {site_name}.")
    if site == "rss":
        return f"Items from “{folder}”, a feed you follow." if folder else "Items from the feeds you follow."
    if noun == "books":
        return f"Books from {site_name}."
    if folder:
        return f"{Noun} in “{folder}”, a {_FOLDER_WORD.get(noun, 'folder')} of yours on {site_name}."
    if noun == "repositories":
        return (f"Repositories you starred on {site_name}." if _cf(label) == "stars"
                else f"Your own repositories on {site_name}.")
    if _cf(label) in ("liked videos", "liked", "likes"):
        return f"{Noun} you liked on {site_name}."
    verb = _VERBS.get(_cf(label))
    if verb:
        return f"{Noun} you {verb} on {site_name}."
    shown = _cf(label) if _cf(label) in ("playlists", "saved") else (label or "list")
    return f"{Noun} in your {shown} on {site_name}."


def page_id(stream: str, folded_folder: str = "") -> str:
    """``list-<stream with dots as dashes>[--<folder slug>-<hash>]``: a pure function of the list, so two computers over one
    bank agree. A folder always carries a short hash of its folded name, so two folders that slug alike never share an id."""
    base = PREFIX + sanitize_id(stream.replace(".", "-"))
    if not folded_folder:
        return base
    slug = sanitize_id(folded_folder)[:SLUG_MAX].strip("-")
    digest = hashlib.sha1(folded_folder.encode("utf-8")).hexdigest()[:6]
    return f"{base}--{slug}-{digest}" if slug else f"{base}--{digest}"


def _name(site_name: str, label: str, folder: str | None) -> str:
    return f"{site_name}: {label}, {folder}" if folder else f"{site_name}: {label}"


def post_specs() -> list[tuple]:
    """``[(group, spec)]``: the streams of a site whose lists hold posts and count by membership, and the site's "Saved another
    way" (the posts every door but its own lists brought, Track 3)."""
    from api.services import source_streams

    out = []
    for group in source_streams.groups():
        if not saved_posts.is_post_site(group.id):
            continue
        out.extend((group, spec) for spec in group.specs if spec.counts == "members"
                   and (spec.family == "saved" or saved_posts.is_another_way(spec.id)))
    return out


# --------------------------------------------------------------------------- every kind of list (owner 2026-11-25)


@dataclass(frozen=True)
class Kind:
    """One kind of list a saved page can be on: a site's list, a browser's bookmarks, a door's books, the feeds."""
    stream: str              # ``x.bookmarks``, ``youtube.playlists``, ``browser:chrome.bookmarks``, ``github.stars``
    site: str                # the source group (``x``, ``browser:chrome``)
    site_name: str           # "X", "Chrome"
    label: str               # "Bookmarks"
    channel: str             # the items route's channel
    key: str                 # the saved-lists table key where "last read" lives, or "" for a list with none
    origin: str              # the list's own origin, where it has one
    mark: str                # the app's mark key (``source_overview.CATALOG``'s ``mark``)
    noun: str                # what it holds: posts | videos | pages | repositories | books | items
    how: str                 # members (``source_streams``) | origin | book
    origins: tuple = ()
    #: How a list files into folders: save_folders (the site's own, by the save) | playlists (a video's other lists) |
    #: page_lists (a bookmark's folder) | feed (the feed an item came from) | None.
    folders: str | None = None
    #: playlists: the labels that are this source's own lists, never a playlist (Watch later, Liked videos).
    own_labels: frozenset = frozenset()


def _mark(origin: str, fallback: str) -> str:
    from api.services import source_overview

    sid = source_overview._ORIGIN_TO_ID.get(origin)
    spec = source_overview._BY_ID.get(sid) if sid else None
    return spec.mark if spec is not None else (origin or fallback)


_NOUNS = {"youtube": "videos", "github": "repositories", "rss": "items", "spotify": "items", "goodreads": "books",
          "apple-books": "books", "book-scan": "books"}


def _noun_of(site: str) -> str:
    if site.startswith("browser:"):
        return "pages"
    return _NOUNS.get(site, "posts")


def kinds() -> list[Kind]:
    """Every kind of list there can be, from the tables that already name them (``source_streams``, ``bookmark_sync``,
    ``books``): a list added there appears here with no second edit."""
    from api.services import bookmark_sync, books, saved_lists, source_streams

    out: list[Kind] = []
    table = source_streams.groups()
    for group in table:
        own = frozenset(_cf(s.list_label) for s in group.specs if s.match == "label" and s.list_label)
        for spec in group.specs:
            if spec.counts != "members" or not (spec.family in ("saved", "youtube", "substack")
                                                or saved_posts.is_another_way(spec.id)):
                continue
            folders = {"save_folders": "save_folders", "playlists": "playlists"}.get(spec.folders or "")
            origin = spec.origin or (spec.origins[0] if spec.origins else "")
            key = (spec.key if spec.key in saved_lists.PLATFORMS else group.id) if spec.family == "saved" else ""
            out.append(Kind(stream=spec.id, site=group.id, site_name=group.label, label=spec.label,
                            channel=spec.channel or group.id, key=key, origin=origin, mark=_mark(origin, group.id),
                            noun=_noun_of(group.id), how="members", folders=folders,
                            own_labels=own if folders == "playlists" else frozenset()))
    names = {g.id: g.label for g in table}

    def static(stream, site, label, channel, origins, noun, *, how="origin", folders=None, name=None):
        origin = origins[0] if origins else ""
        out.append(Kind(stream=stream, site=site, site_name=name or names.get(site, site), label=label, channel=channel,
                        key="", origin=origin, mark=_mark(origin, site), noun=noun, how=how, origins=tuple(origins),
                        folders=folders))

    static("github.stars", "github", "Stars", "github", ("github-starred",), "repositories")
    static("github.repositories", "github", "Your repositories", "github", ("github-owned", "github-added"),
           "repositories")
    browsers = (*bookmark_sync.CHROMIUM_BROWSERS, "safari")
    for browser in browsers:
        origin = bookmark_sync.SAFARI_ORIGIN if browser == "safari" else bookmark_sync.origin_for(browser)
        site = f"browser:{browser}"
        static(f"{site}.bookmarks", site, "Bookmarks", bookmark_sync.CHANNEL_BY_ORIGIN.get(origin, origin), (origin,),
               "pages", folders="page_lists", name=source_streams._BROWSER_NAMES.get(browser, browser.capitalize()))
    static("rss.feeds", "rss", "Feeds you follow", "rss", ("rss",), "items", folders="feed", name="RSS")
    for door, stream, label in ((books.APPLE_ORIGIN, "apple-books.books", "Books"),
                                (books.GOODREADS_ORIGIN, "goodreads.shelves", "Shelves"),
                                (books.SCAN_ORIGIN, "book-scan.books", "Books scanned")):
        static(stream, door, label, door, (door,), "books", how="book", name=books.DOOR_WORDS.get(door, door))
    return out


@dataclass(frozen=True)
class ListInfo:
    """One list as the graph, Clusters and Home draw it: what it is, what it holds (newest first) and which of those sit
    inside it (never earned a place of their own)."""
    key: str                 # the list's page id (:func:`page_id`): a pure function, so a list exists before its page
    stream: str
    folder: str | None
    parent: str | None       # a folder's whole list, always set for a folder
    site: str
    site_name: str
    label: str
    name: str
    mark: str
    kind_noun: str
    count: int
    newest: str | None
    has_page: bool
    members: tuple           # page ids, newest first by the item's own saved date, an unknown date last
    inside: tuple            # the members that sit inside the list: not earned (``saved_posts.earned_saves``)


@dataclass(frozen=True)
class Groups:
    lists: dict = field(default_factory=dict)       # key -> ListInfo
    #: page id -> the lists it is on, most specific first (a folder before its whole list)
    of_page: dict = field(default_factory=dict)
    #: page id -> the lists it is on, for a member that EARNED a place: drawn outside, joined to these
    earned_of: dict = field(default_factory=dict)
    stamp: str = ""


_NO_GROUPS = Groups()


def _when(fm: dict):
    media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
    for value in (media.get("saved_at"), fm.get("saved_at"), fm.get("created")):
        if value:
            got = saved_at.sort_instant(str(value))
            if got.year > 1:
                return got
    return saved_at.sort_instant(None)


def _book_doors(fm: dict) -> set[str]:
    book = fm.get("book") if isinstance(fm.get("book"), dict) else {}
    doors = {str(d) for d in (book.get("doors") or []) if d}
    if book.get("apple_books"):
        doors.add("apple-books")
    if book.get("goodreads"):
        doors.add("goodreads")
    return doors


@dataclass
class _Membership:
    kinds: dict             # stream -> Kind
    held: dict              # (stream, folded folder) -> set of page ids
    folder_names: dict      # (stream, folded folder) -> the folder's name as shown
    when: dict              # page id -> sort instant
    pages: set              # live list page ids


def _build_membership(memory_path: Path, entities, episodes) -> _Membership:
    from api.services import quiet_pages, save_folders, source_overview, source_streams

    table = {k.stream: k for k in kinds()}
    mem = source_streams.members(memory_path).members
    held: dict[tuple, set] = {}
    names: dict[tuple, str] = {}
    when: dict[str, object] = {}
    pages: set[str] = set()
    by_origin: dict[str, list] = {}
    for k in table.values():
        for o in k.origins:
            by_origin.setdefault(o, []).append(k)
        if k.how == "members" and mem.get(k.stream):
            held[(k.stream, "")] = set(mem[k.stream])
    member_of: dict[str, list] = {}
    for (stream, _f), ids in list(held.items()):
        for pid in ids:
            member_of.setdefault(pid, []).append(table[stream])

    def put(k: Kind, pid: str, folder: str | None = None):
        held.setdefault((k.stream, ""), set()).add(pid)
        name = " ".join(str(folder or "").split())
        if name:
            slot = (k.stream, _cf(name))
            held.setdefault(slot, set()).add(pid)
            names.setdefault(slot, name)

    for entry in entities:
        fm = entry.frontmatter or {}
        if str(fm.get("type") or "") != "media":
            continue
        if is_list(fm):
            if _live(fm):
                pages.add(entry.stem)
            continue
        if source_overview.is_hidden(fm):
            continue
        pid = entry.stem
        when[pid] = _when(fm)
        origin = str(fm.get("origin") or "").strip()
        for k in member_of.get(pid, ()):
            if k.folders == "playlists":
                for name in id_utils.page_lists(fm):
                    if _cf(name) not in k.own_labels:
                        put(k, pid, name)
        for k in by_origin.get(origin, ()):
            if k.how != "origin":
                continue
            if k.folders == "page_lists":
                lists = id_utils.page_lists(fm)
                put(k, pid, lists[0] if lists else None)
                for name in lists[1:]:
                    put(k, pid, name)
            elif k.folders == "feed":
                media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
                put(k, pid, str(media.get("channel") or "") or None)
            else:
                put(k, pid)
        if origin == "book" or fm.get("book"):
            for door in _book_doors(fm):
                for k in by_origin.get(door, ()):
                    if k.how == "book":
                        put(k, pid)
    # A site's own folders (X's bookmark folders), filed by the save: the save's episode names its page.
    filing = {k.origin: k for k in table.values() if k.folders == "save_folders" and k.origin}
    if filing:
        for entry in episodes:
            fm = entry.frontmatter or {}
            pid = str(fm.get(quiet_pages.SAVE_KEY) or "").strip()
            if not pid or fm.get("source_deleted_at") or pid not in when:
                continue
            for origin, name in save_folders.folders_of(fm):
                k = filing.get(origin)
                if k is not None and pid in held.get((k.stream, ""), ()):
                    put(k, pid, name)
    return _Membership(table, held, names, when, pages)


def _membership(memory_path: Path) -> _Membership:
    memory_path = Path(memory_path)
    return bank_index.derived_over(memory_path, ("entities", "episodes"), "list_pages.membership",
                                   lambda entities, episodes: _build_membership(memory_path, entities, episodes))


_GROUPS: dict[str, tuple] = {}
_GROUPS_LOCK = threading.Lock()


def _order(ids, when) -> tuple:
    floor = saved_at.sort_instant(None)
    return tuple(sorted(ids, key=lambda p: (-(when.get(p, floor) - floor).total_seconds(), p)))


def groups(memory_path: Path) -> Groups:
    """Which list each saved page is on, which page stands for each list, and which members sit inside their list — the
    one answer the graph's bubbles, Clusters and Home read (owner 2026-11-25: "a single symbolic bubble ... when clicked
    we zoom into it"). Every kind of list (:func:`kinds`), whether or not its page has been written (``has_page``).
    Derived on read, never stored, kept until the pages, the saves or the earned set move. Never raises."""
    memory_path = Path(memory_path)
    try:
        m = _membership(memory_path)
        try:
            earned = saved_posts.earned_saves(memory_path)
        except Exception as exc:  # noqa: BLE001 - nothing earned is the safe answer: every member sits inside
            logger.debug(f"list pages: earned skipped ({type(exc).__name__})")
            earned = frozenset()
        slot = str(memory_path)
        with _GROUPS_LOCK:
            hit = _GROUPS.get(slot)
        if hit is not None and hit[0] is m and hit[1] == earned:
            return hit[2]
        out = _groups_of(m, earned)
        with _GROUPS_LOCK:
            _GROUPS[slot] = (m, earned, out)
        return out
    except Exception as exc:  # noqa: BLE001 - no bubbles is the safe answer
        logger.debug(f"list pages: groups skipped ({type(exc).__name__})")
        return _NO_GROUPS


def _groups_of(m: _Membership, earned: frozenset) -> Groups:
    lists: dict[str, ListInfo] = {}
    of_page: dict[str, list] = {}
    for (stream, folded), ids in sorted(m.held.items(), key=lambda kv: (kv[0][0], kv[0][1] != "", kv[0][1])):
        if not ids:
            continue
        k = m.kinds[stream]
        folder = m.folder_names.get((stream, folded)) if folded else None
        key = page_id(stream, folded)
        members = _order(ids, m.when)
        newest = next((m.when[p].date().isoformat() for p in members if m.when.get(p) and m.when[p].year > 1), None)
        lists[key] = ListInfo(
            key=key, stream=stream, folder=folder, parent=page_id(stream) if folded else None, site=k.site,
            site_name=k.site_name, label=k.label, name=_name(k.site_name, k.label, folder), mark=k.mark,
            kind_noun=k.noun, count=len(members), newest=newest, has_page=key in m.pages, members=members,
            inside=tuple(p for p in members if p not in earned))
        for pid in members:
            of_page.setdefault(pid, []).append(key)
    # Most specific first: a folder before its whole list.
    ordered = {pid: tuple(sorted(keys, key=lambda key: lists[key].parent is None)) for pid, keys in of_page.items()}
    earned_of = {pid: keys for pid, keys in ordered.items() if pid in earned}
    digest = hashlib.sha1()
    for key, li in sorted(lists.items()):
        digest.update(f"{key}\x1f{li.has_page}\x1f{len(li.inside)}\x1f{'|'.join(li.members)}\x1e".encode())
    return Groups(lists=lists, of_page=ordered, earned_of=earned_of, stamp=digest.hexdigest()[:12] if lists else "")


def kind_of_stream(stream: str) -> Kind | None:
    return next((k for k in kinds() if k.stream == stream), None)


def _want_of(li: ListInfo, k: Kind) -> Want:
    folded = _cf(li.folder) if li.folder else ""
    return Want(id=li.key, site=k.site, site_name=k.site_name, stream=k.stream, channel=k.channel, key=k.key,
                origin=k.origin, label=k.label, folder=li.folder, folded=folded, name=li.name,
                sentence=sentence(k.site_name, k.label, li.folder, noun=k.noun, site=k.site))


def wanted(memory_path: Path) -> list[Want]:
    """Every list that holds something and could have a page right now: one per list of every kind and one per folder."""
    memory_path = Path(memory_path)
    g = groups(memory_path)
    table = {k.stream: k for k in kinds()}
    return [_want_of(li, table[li.stream]) for _key, li in sorted(g.lists.items()) if li.count > 0
            and li.stream in table]


# --------------------------------------------------------------------------- what a list holds, read now


def _read(memory_path: Path, stream: str, folder: str | None, *, limit: int) -> dict | None:
    """The items route's own answer for one list (``{all, latest, items}``), so a page's count is the number its cards say."""
    from api.services import channel_items, source_streams

    spec = source_streams.spec_of(stream)
    if spec is None or not spec.channel:
        return None
    try:
        return channel_items.items(Path(memory_path), spec.channel, limit=limit, stream=stream, folder=folder)
    except channel_items.UnknownStream:
        return None


def _row(item: dict) -> dict:
    out = {"title": str(item.get("title") or "")}
    for key, src in (("author", "author"), ("posted", "posted"), ("saved", "day"), ("host", "host")):
        if item.get(src):
            out[key] = str(item[src])
    return out


def _why(memory_path: Path, origin: str, folder: str | None) -> dict | None:
    """The person's own reason for a whole folder (``save_folders``), read now: it belongs here and nowhere else."""
    if not folder or not origin:
        return None
    from api.services import save_folders

    record = save_folders.reason_for(memory_path, origin, folder)
    text = str((record or {}).get("text") or "").strip()
    return {"text": text, "at": str(record.get("at") or "")[:10] or None} if text else None


def _last_read(memory_path: Path, key: str) -> str | None:
    """When this Mac's list was last read, from outside the bank (per Mac): never stored on the page."""
    from api.services import saved_lists, source_streams

    try:
        return source_streams._z(saved_lists.last(Path(memory_path), key).get("read_at"))
    except Exception:  # noqa: BLE001 - a missing record is no read
        return None


def _page_row(memory_path: Path, entity_id: str) -> dict | None:
    """One member's row, from its page's own header: its name, the day it was saved and its site."""
    entry = bank_index.file(Path(memory_path), "entities", f"{entity_id}.md")
    fm = entry.frontmatter if entry is not None else None
    if not isinstance(fm, dict):
        return None
    media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
    out = {"title": str(fm.get("name") or entity_id)}
    when = _when(fm)
    if when.year > 1:
        out["saved"] = when.date().isoformat()
    if media.get("site"):
        out["host"] = str(media["site"])
    return out


def block(memory_path: Path, entity_id: str, fm: dict | None) -> dict | None:
    """The page's ``list`` block (``page_blocks``): what the list is, how many it holds, the newest day and the
    :data:`RECENT` newest rows, read from the saves now. None for any other page. Never raises."""
    info = list_of(fm)
    if info is None:
        return None
    memory_path = Path(memory_path)
    try:
        k = kind_of_stream(info["stream"])
        if k is None or k.how == "members":
            read = _read(memory_path, info["stream"], info["folder"], limit=RECENT) or {}
            count, newest = int(read.get("all") or 0), read.get("latest")
            recent = [_row(item) for item in (read.get("items") or [])[:RECENT]]
        else:
            li = groups(memory_path).lists.get(entity_id)
            count, newest = (li.count, li.newest) if li is not None else (0, None)
            recent = [row for pid in (li.members[:RECENT] if li is not None else ())
                      if (row := _page_row(memory_path, pid)) is not None]
        key = k.key if k is not None else info["site"]
        return {
            "site": info["site"], "stream": info["stream"], "folder": info["folder"],
            "channel": k.channel if k is not None else info["site"],
            "label": info["label"], "source": info["source"],
            "count": count, "newest": newest,
            # Nothing reads "Saved another way" (it holds what other doors brought) or a list with no list table of its
            # own (a browser's bookmarks, the feeds): neither has a read time.
            "lastReadAt": _last_read(memory_path, key) if key and not saved_posts.is_another_way(info["stream"]) else None,
            "why": _why(memory_path, info["source"], info["folder"]),
            "recent": recent,
        }
    except Exception as exc:  # noqa: BLE001 - a derived block never fails a page read
        logger.debug(f"list pages: block skipped ({type(exc).__name__})")
        return None


# --------------------------------------------------------------------------- what an agent is told, and what it is refused


#: The one sentence every agent write to a list's own page is refused with, on every door (the stdio tools, the remote
#: connection, the command line, the agent API): the page stands for the list, so it takes no belief, edit, merge, split, link or
#: look. No name in it: a folder's name is the person's own word.
AGENT_REFUSAL = ("That page is a list of saved things, read from the person's saves each time, so it takes no fact, edit, "
                 "merge, split, link or look and nothing was changed; record a fact on the page of the saved thing itself "
                 "instead.")


def line_for(memory_path: Path, entity_id: str, *, rows: bool = False) -> dict | None:
    """What an agent reading this page is told when it is a list's own page, else None: ``{"words", "count", "newest"}``.
    The count and the newest rows come from the saves now (:func:`block`), never from the page's text. ``rows`` adds the
    :data:`RECENT` newest titles — the person's saved words, so only for a caller that may read them. Never raises."""
    memory_path = Path(memory_path)
    try:
        entry = bank_index.file(memory_path, "entities", f"{entity_id}.md")
        fm = entry.frontmatter if entry is not None else None
        info = list_of(fm)
        if info is None:
            return None
        got = block(memory_path, entity_id, fm) or {}
        count, newest = int(got.get("count") or 0), got.get("newest")
        kind = kind_of_stream(info["stream"])
        head = (f"This page is a list of saved {kind.noun if kind else 'posts'} ({fm.get('name') or entity_id}): {count} saved"
                + (f", newest {newest}" if newest else "")
                + ". It holds no posts or facts of its own: the count and the rows are read from the person's saves each "
                  "time, so find a post by its words in a search, never by this page's text.")
        out = [head]
        if rows and got.get("recent"):
            out.append("Newest first: " + "; ".join(
                f"{r.get('title') or '(untitled)'}" + (f" ({r['posted'] if r.get('posted') else r.get('saved')})"
                                                       if r.get("posted") or r.get("saved") else "")
                for r in got["recent"]) + ".")
        return {"words": " ".join(out), "count": count, "newest": newest}
    except Exception as exc:  # noqa: BLE001 - a derived line never fails a read
        logger.debug(f"list pages: line skipped ({type(exc).__name__})")
        return None


# --------------------------------------------------------------------------- which pages are drawn


@dataclass(frozen=True)
class Drawn:
    stream: str
    folder: str | None
    count: int
    newest: str | None


@dataclass(frozen=True)
class State:
    """What the pages say about the lists that are on screen: the live list pages with their counts, and which folders each
    page's saves are filed in (for the read-time edges)."""
    drawn: dict = field(default_factory=dict)       # page id -> Drawn
    stamp: str = ""


_EMPTY = State()


def _live(fm: dict) -> bool:
    return str(fm.get("status") or "active").strip().lower() not in ("archived", "dropped")


def _state_of(g: Groups) -> State:
    drawn = {key: Drawn(li.stream, li.folder, li.count, li.newest) for key, li in g.lists.items()
             if li.has_page and li.count > 0}
    stamp = hashlib.sha1("\x1f".join(f"{pid}:{d.count}:{d.newest}" for pid, d in sorted(drawn.items())).encode()
                         ).hexdigest()[:12] if drawn else ""
    return State(drawn=drawn, stamp=stamp)


_STATE: dict[str, tuple] = {}


def state(memory_path: Path) -> State:
    """The lists whose pages are drawn, from :func:`groups`. Empty while :func:`enabled` is off, so every reader behaves
    as before."""
    if not enabled():
        return _EMPTY
    slot = str(Path(memory_path))
    g = groups(memory_path)
    hit = _STATE.get(slot)
    if hit is not None and hit[0] is g:
        return hit[1]
    out = _state_of(g)
    _STATE[slot] = (g, out)
    return out


def stamp(memory_path: Path) -> str:
    """Moves when a list is drawn or gone, or its count or newest day moves (a graph's cache key and a node's hash fold
    it in); empty while dark."""
    return state(memory_path).stamp


def drawn_ids(memory_path: Path) -> frozenset:
    return frozenset(state(memory_path).drawn)


def stream_pages(memory_path: Path) -> dict[str, dict]:
    """``{stream id: {"page": id | None, "folders": {folder name: id}}}`` for every list that is drawn now: which page stands
    for a stream on the Sources page. Empty while dark, so a stream row carries no page and no link shows."""
    out: dict[str, dict] = {}
    for pid, d in sorted(state(memory_path).drawn.items()):
        row = out.setdefault(d.stream, {"page": None, "folders": {}})
        if d.folder:
            row["folders"][d.folder] = pid
        else:
            row["page"] = pid
    return out


def read_time_edges(memory_path: Path, entity_ids, earned) -> list[tuple[str, str, str]]:
    """``[(source, target, label)]`` for the graph, computed on read and never stored: each earned member of a drawn list
    is joined to that list's page (its folder's and its whole list's), and each drawn folder's page to its list's page.
    Only between pages that are nodes (``entity_ids``). A list with no earned member has none, on purpose: a fake edge
    would be worse than none."""
    st = state(memory_path)
    if not st.drawn:
        return []
    g = groups(memory_path)
    out: list[tuple[str, str, str]] = []
    for pid in sorted(st.drawn):
        li = g.lists.get(pid)
        if li is not None and li.parent and pid in entity_ids and li.parent in st.drawn and li.parent in entity_ids:
            out.append((pid, li.parent, "part of"))
    for post in sorted(set(earned) & set(entity_ids)):
        for key in g.of_page.get(post, ()):
            if key in st.drawn and key in entity_ids:
                out.append((post, key, "saved in"))
    return out


# --------------------------------------------------------------------------- the page


def _frontmatter(w: Want, today: str) -> dict:
    return {
        "name": w.name, "type": "media", "status": "active", "confidence": 0.8,
        "created": today, "last_referenced": today,
        **decay_policy.frontmatter_fields(decay_policy.default_class_for("media", source="media")),
        "source_episodes": [], "aliases": [], "tags": [], "related": [], "version": 1, "origin": PAGE_ORIGIN,
        # Described by the list's own table, never a fetched page.
        "enrichment_attempted": True,
        "media": {"kind": KIND, "media_type": KIND},
        "list": _list_block(w),
    }


def _list_block(w: Want) -> dict:
    return {"site": w.site, "stream": w.stream, "folder": w.folder, "source": w.origin, "label": w.label,
            "named": w.name, "said": w.sentence}


_SUMMARY = "## Summary\n"


def _body(w: Want) -> str:
    # Under the heading every page's one line lives under: the app lifts a page's `## Summary` as its row's line, and a
    # full page with no Summary has none, so a bare sentence drew the row's line until the page was first opened (seen on
    # the scratch app with the switch on).
    return _SUMMARY + w.sentence + "\n"


def _pages(memory_path: Path) -> dict[str, dict]:
    """Every list page, in any status, by id."""
    return {e.stem: e.frontmatter or {} for e in bank_index.files(memory_path, "entities")
            if is_list(e.frontmatter)}


# --------------------------------------------------------------------------- committing


def _commit(memory_path: Path, rows: list[tuple[str, str]], *, trigger: str, author: str) -> None:
    paths = [p for p, _ in rows]
    message = git_service.build_commit_message(
        f"Lists of saved posts {datetime.now(timezone.utc).date().isoformat()}",
        [f"{p}: {action} (source: n/a, trigger: {trigger})" for p, action in rows], authors=[author])
    git_service.commit_paths_sync(memory_path, message, paths)


# --------------------------------------------------------------------------- the sync


def _refused(memory_path: Path) -> bool:
    return not enabled() or demo_guard.is_demo(memory_path) or replica_guard.blocks()


def sync(memory_path: Path) -> dict:
    """Make the page of every list that holds something and has none, bring a page's name up to its list's, and retire the
    pages of a list whose source is gone. Idempotent: a second run writes and commits nothing. Raises
    :class:`write_admission.SleepHolding` when Sleep holds the pages — the caller tries again, nothing is lost. A demo
    bank, a replica and (until the flip) every bank do nothing. ``{"created", "updated", "retired", "pending"}``."""
    memory_path = Path(memory_path)
    out = {"created": 0, "updated": 0, "retired": 0, "pending": 0}
    if _refused(memory_path):
        return out
    pages = _pages(memory_path)
    todo = wanted(memory_path)
    lists = {w.id: w for w in todo}
    have = set(pages)
    make = [w for w in todo if w.id not in have]    # a page in any status holds its key; ``wanted`` holds something
    gone = _gone_streams(pages)
    changed = [pid for pid, fm in pages.items() if _live(fm) and pid in lists and _rename_due(fm, lists[pid])]
    retire = [pid for pid, fm in pages.items() if _live(fm) and (list_of(fm) or {}).get("stream") in gone]
    work = [("make", w) for w in make] + [("update", pid) for pid in changed] + [("retire", pid) for pid in retire]
    today = date.today().isoformat()
    for start in range(0, len(work), BATCH):
        chunk = work[start:start + BATCH]
        try:
            with write_admission.admitted(memory_path), page_lock.page_lock(memory_path):
                rows = _write_chunk(memory_path, chunk, lists, today, out)
                if rows:
                    _commit(memory_path, rows, trigger=TRIGGER_SYNC, author=git_service.CICADA_AUTHOR)
                bank_index.invalidate(memory_path)
        except write_admission.SleepHolding:
            out["pending"] = len(work) - start
            raise
    return out


def _gone_streams(pages: dict[str, dict]) -> set[str]:
    """The streams a page names that no longer exist in the table: their source was removed."""
    known = {k.stream for k in kinds()}
    if not known:
        return set()           # a table that could not be read retires nothing
    return {info["stream"] for fm in pages.values() if (info := list_of(fm)) and info["stream"] not in known}


def _rename_due(fm: dict, w: Want) -> bool:
    """Has the list's own name changed since the page was written, and has the person left the page's name alone?"""
    info = fm.get("list") if isinstance(fm.get("list"), dict) else {}
    written = str(info.get("named") or "")
    return bool(written) and written != w.name and str(fm.get("name") or "") == written


def _write_chunk(memory_path: Path, chunk, lists: dict[str, Want], today: str, out: dict) -> list[tuple[str, str]]:
    entities = memory_path / "entities"
    rows: list[tuple[str, str]] = []
    for action, item in chunk:
        if action == "make":
            w: Want = item
            path = entities / f"{w.id}.md"
            if path.exists():
                continue                            # the id names another page: never overwritten
            try:
                markdown_parser.write_new(path, _frontmatter(w, today), _body(w))
            except FileExistsError:
                continue
            rows.append((f"entities/{w.id}.md", "created"))
            out["created"] += 1
            continue
        path = entities / f"{item}.md"
        if not path.is_file():
            continue
        parsed = markdown_parser.parse(path)
        fm = parsed.frontmatter
        if not is_list(fm) or not _live(fm):
            continue
        if action == "update":
            w = lists[item]
            fm["name"] = w.name
            held = fm.get("list") if isinstance(fm.get("list"), dict) else {}
            # The words stay the person's when they edited them: only the sentence this writer wrote is replaced.
            said = str(held.get("said") or "").strip()
            body = _body(w) if parsed.body.strip() in (said, (_SUMMARY + said).strip()) else parsed.body
            fm["list"] = {**held, **_list_block(w)}
            markdown_parser.write(path, fm, body)
            rows.append((f"entities/{item}.md", "updated"))
            out["updated"] += 1
        else:
            _archive(path, fm, parsed.body)
            rows.append((f"entities/{item}.md", "archived"))
            out["retired"] += 1
    return rows


def _archive(path: Path, fm: dict, body: str) -> None:
    fm["status"] = "archived"
    fm["retired_by"] = RETIRED_SOURCE
    markdown_parser.write(path, fm, body)


def retire_source(memory_path: Path, site: str, *, by: str = git_service.USER_AUTHOR) -> int:
    """The person removed a source: archive each of its list pages in one commit under ``by`` (undoable: the page and its
    history stay, a revert brings it back, and ``sync`` never makes it again or wakes it). Raises
    :class:`write_admission.SleepHolding` while Sleep holds the pages. Returns how many pages were retired."""
    memory_path = Path(memory_path)
    if demo_guard.is_demo(memory_path) or replica_guard.blocks():
        return 0
    rows: list[tuple[str, str]] = []
    with write_admission.admitted(memory_path), page_lock.page_lock(memory_path):
        for pid, fm in _pages(memory_path).items():
            info = list_of(fm)
            if info is None or info["site"] != site or not _live(fm):
                continue
            path = memory_path / "entities" / f"{pid}.md"
            parsed = markdown_parser.parse(path)
            _archive(path, parsed.frontmatter, parsed.body)
            rows.append((f"entities/{pid}.md", "archived"))
        if rows:
            _commit(memory_path, rows, trigger=TRIGGER_USER if by == git_service.USER_AUTHOR else TRIGGER_SYNC, author=by)
        bank_index.invalidate(memory_path)
    return len(rows)


# --------------------------------------------------------------------------- the background run


class _Runner:
    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.timer: threading.Timer | None = None
        self.again = False


_RUNNERS: dict[str, _Runner] = {}
_GUARD = threading.Lock()


def start_sync(memory_path, *, delay_s: float = 0.0) -> bool:
    """Make the pages in the background: one run per bank at a time (a trigger during a run runs once more after it), a
    short ``delay_s`` folding a burst into one run, and a bank Sleep holds tried again later. Never raises. A demo bank, a
    replica and a bank before the flip do nothing."""
    try:
        memory_path = Path(memory_path)
        if _refused(memory_path):
            return False
        key = str(memory_path.resolve())
        with _GUARD:
            runner = _RUNNERS.setdefault(key, _Runner())
            if runner.thread is not None and runner.thread.is_alive():
                runner.again = True
                return False
            if delay_s > 0:
                if runner.timer is not None and runner.timer.is_alive():
                    return False
                runner.timer = threading.Timer(delay_s, start_sync, args=(memory_path,))
                runner.timer.daemon = True
                runner.timer.start()
                return True
            runner.thread = threading.Thread(target=_run, args=(memory_path, runner), name="cicada-list-pages",
                                             daemon=True)
            runner.thread.start()
        return True
    except Exception as exc:  # noqa: BLE001 - a page is never a reason for a request to fail
        logger.debug(f"list pages: not started ({type(exc).__name__})")
        return False


def _run(memory_path: Path, runner: _Runner) -> None:
    while True:
        runner.again = False
        try:
            out = sync(memory_path)
            if out["created"] or out["updated"] or out["retired"]:
                logger.info(f"list pages: {out['created']} made, {out['updated']} updated, {out['retired']} retired")
        except write_admission.SleepHolding:
            _retry(memory_path)
            return
        except Exception as exc:  # noqa: BLE001 - the next trigger tries again
            logger.debug(f"list pages: skipped ({type(exc).__name__})")
            return
        if not runner.again:
            return


def _retry(memory_path: Path) -> None:
    with _GUARD:
        runner = _RUNNERS.setdefault(str(memory_path.resolve()), _Runner())
        if runner.timer is not None and runner.timer.is_alive():
            return
        runner.timer = threading.Timer(RETRY_S, start_sync, args=(memory_path,))
        runner.timer.daemon = True
        runner.timer.start()


__all__ = ["KIND", "PAGE_ORIGIN", "is_list", "list_of", "wanted", "block", "state", "stamp", "drawn_ids",
           "read_time_edges", "sync", "start_sync", "retire_source", "page_id", "sentence", "stream_pages",
           "line_for", "AGENT_REFUSAL"]
