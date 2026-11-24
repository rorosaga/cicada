"""What each source reads, as one list of streams (G245, ruling 78): ``GET /sources/streams``.

A **stream** is one thing a source reads — X's Bookmarks, X's Likes, YouTube's history, Notes' notes. Every stream says the
same things (its name, whether it is on, how it is read, when it was last read and how that went, how many items the
memory holds from it, how deep they go), so the Sources page, the CLI and any later client draw every source one way. The
wire shape is the plan's section 2.1 (``docs/plans/2026-11-24-sources-redesign.md``); a field name here is a contract.

**Where the streams come from.** Nothing is declared twice:

* The lists a person's own agent reads in their signed-in browser are *derived* from the tables that already name them —
  ``saved_lists.PLATFORMS`` (X, Instagram, LinkedIn, Reddit, Pinterest, TikTok, Spotify, Goodreads, and the keys another
  track adds under a ``base`` site), ``youtube_lists.LISTS`` and ``substack_lists.LISTS``. A list added there appears here
  under its source with no second edit; ``_LIST_NAMES`` only annotates (a stream's short name and kind) and every key it
  does not know gets a default from the key itself.
* Everything else (GitHub, Linear, Notion, the browsers, Notes, Calendar, Reminders, Contacts, chats, meetings, agents,
  feeds, books, folders, traces, and the per-Mac "Saves you make" click stream) is the static table in
  :func:`_static_specs`, its state, health and last read taken from the stores that already hold them — the channel rows
  (:mod:`channel_registry`), the connectors' own status and the saved lists' own files. Nothing existing is replaced.

**Counts are list membership**, not the last read's size and not a post's first origin: a post bookmarked first and liked
later keeps the origin ``x-bookmarks`` and holds ``Likes`` only in its page's ``collections:`` (``id_utils.page_lists``),
so a stream counts the pages whose lists name it. One pass over the media pages, kept until the pages' cached headers
change (``bank_index.derived``), serves every stream's count, its members for the items route's ``stream`` filter and the
folders each holds; a second, over the episodes, serves a save's folders (``save_folders``), the days a history holds and
what an agent or a model already read. Nothing is scanned per request, and no body is ever read.

**Checking** (:func:`check`, ``POST /sources/streams/check``) does the backend's half of a check, and nothing more: Cicada
opens no browser (G166), so for a list the person's own agent reads it stamps ``check_requested_at`` — the lists' ``due``
logic serves a requested list first, still inside the daily bound and never lifting a pause; for a stream an app reads
the backend only reports (the app runs its reader); for a stream read through a sign-in the person gave it runs that
connector's own sync, the click the person made.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from api.services import (
    bank_index,
    bookmark_sync,
    episode_ids,
    folder_source,
    history_index,
    id_utils,
    media_ingestor,
    reading_hosts,
    reading_settings,
    saved_at,
    saved_lists,
    save_folders,
    source_overview,
    substack_lists,
    tab_groups,
    watch_history,
    youtube_lists,
)

SHAPE = "streams-1"

# --- the vocabulary of the wire (plan 2.1) ----------------------------------------------------------------------
KINDS = ("saved", "liked", "reposted", "history", "later", "playlists", "connections", "following", "notes", "pages",
         "chats", "events", "tasks", "code", "books", "feed", "files")
HOWS = ("browser", "app", "account", "click")
STATES = ("on", "off", "unavailable")
HEALTHS = ("read", "not_read", "signed_out", "couldnt_read", "paused")

#: What a stream reads of each item, by kind: ``read`` is a stream Sleep reads, ``index`` a stream whose items are kept
#: and findable and read by no model until the person talks about one (rulings 30 and 62).
_READ_KINDS = frozenset({"notes", "pages", "chats", "events", "tasks"})


@dataclass(frozen=True)
class Spec:
    """One stream, before any state is known."""
    id: str                      # "<source>.<stream>", frozen once shipped
    source: str                  # the app catalogue's id (SourceCatalogEntry.id)
    label: str
    kind: str
    how: str
    owner: str = "backend"       # backend | app
    control: str = "switch"      # switch | setup
    depth: str | None = None     # index | read; None: by kind
    #: The items route's channel the stream's rows live under (``/sources/channels/{channel}/items``).
    channel: str | None = None
    #: How the count is made: members (pages whose lists name it) · origin (pages of ``origins``) · days (history days of
    #: ``origins``) · channel (the channel rows' own count) · part (one of a row's parts) · directory (LinkedIn's kept
    #: connections, outside every bank) · conversations (an agent's) · none.
    counts: str = "none"
    origins: tuple[str, ...] = ()
    #: members: the list label the stream is on a page (casefolded compare), or ``rest`` — any list that is none of the
    #: group's own labels (YouTube's playlists). ``origin`` is the stream's own origin, where a page naming no list falls.
    match: str | None = None
    list_label: str | None = None
    origin: str | None = None
    #: The table the stream is a list of, and its key there.
    family: str | None = None    # saved | youtube | substack
    key: str | None = None
    #: The channel rows state, health, last read and (for ``counts == "channel"``) the count come from.
    channel_rows: tuple[str, ...] = ()
    #: The connector (``connectors.ADAPTERS`` id) that reads the stream with a sign-in the person gave, if any.
    connector: str | None = None
    #: Counts this stream's own folders (X's bookmark folders, Instagram's collections, YouTube's playlists).
    folders: str | None = None   # save_folders | playlists
    #: Fixed state for a stream the backend alone cannot see (the per-Mac click stream, a reader only the app runs).
    note: str = ""

    @property
    def switch(self) -> dict | None:
        if self.family == "saved":
            return {"setting": "savedLists", "key": self.key}
        if self.family == "youtube":
            return {"setting": "youtubeLists", "key": self.key}
        if self.family == "substack":
            return {"setting": "substackLists", "key": self.key}
        return None


@dataclass
class Group:
    """One source with its streams."""
    id: str
    label: str
    specs: list[Spec] = field(default_factory=list)
    #: The table key whose handle and profile link are this source's account.
    account_key: str | None = None


# --- the tables the browser lists are derived from ------------------------------------------------------------------

#: A stream's short name and kind, by the table key, for the keys whose own name would not do. Every key not listed gets
#: :func:`_default_name`: its key with the ``<base>-`` prefix dropped, kind from :data:`_KIND_BY_NAME`.
_LIST_NAMES: dict[str, tuple[str, str]] = {
    "x": ("bookmarks", "saved"),
    "tiktok": ("favorites", "saved"),
    "spotify": ("library", "saved"),
    "goodreads": ("shelves", "books"),
    "watch_later": ("watch_later", "later"),
    "history": ("history", "history"),
    "playlists": ("playlists", "playlists"),
    "subscriptions": ("subscriptions", "feed"),
}
_KIND_BY_NAME = {"likes": "liked", "liked": "liked", "upvoted": "liked", "reposts": "reposted",
                 "connections": "connections", "following": "following", "history": "history", "playlists": "playlists", "subscriptions": "feed", "shelves": "books"}

#: The sources a person saves from inside the site itself, whose save click the app notices on this Mac (the plan's
#: "Saves you make" stream). The state is the app's own switch, which the app writes over this row.
_CLICK_SITES = (("x", "X"), ("instagram", "Instagram"), ("github", "GitHub"), ("tiktok", "TikTok"),
                ("reddit", "Reddit"), ("youtube", "YouTube"))

#: Where the sources sit on the page's wire, as the app's catalogue lists them; one a table adds later follows.
_SOURCE_ORDER = ("x", "youtube", "instagram", "linkedin", "reddit", "pinterest", "github", "linear", "spotify", "tiktok",
                 "substack", "browser:chrome", "browser:safari", "browser:brave", "browser:vivaldi", "browser:comet",
                 "browser:dia", "calendar-local", "contacts-local", "reminders-local", "imessage", "whatsapp",
                 "telegram-chats", "traces", "notes", "voice-memos", "folders", "hex", "meeting-folders",
                 "apple-books", "goodreads", "book-scan", "files", "notion", "chat-exports", "rss", "calendar",
                 "telegram")

_SOURCE_LABELS = {
    "youtube": "YouTube", "substack": "Substack", "github": "GitHub", "linear": "Linear", "notion": "Notion",
    "calendar-local": "Calendar", "contacts-local": "Contacts", "reminders-local": "Reminders", "imessage": "Messages",
    "whatsapp": "WhatsApp", "telegram-chats": "Telegram", "telegram": "Telegram bot", "traces": "Activity traces",
    "notes": "Apple Notes", "voice-memos": "Voice Memos", "folders": "Folders", "hex": "Hex",
    "meeting-folders": "Meeting folders", "apple-books": "Apple Books", "book-scan": "Book scans",
    "files": "Files and links", "chat-exports": "Chat exports", "rss": "RSS", "calendar": "Calendar feeds",
}
_BROWSER_NAMES = {"chrome": "Chrome", "safari": "Safari", "brave": "Brave", "vivaldi": "Vivaldi", "comet": "Comet",
                  "dia": "Dia"}


def _default_name(key: str, base: str | None) -> str:
    prefix = f"{base}-" if base else ""
    return (key[len(prefix):] if prefix and key.startswith(prefix) else key).replace("_", "-")


def _list_name(key: str, base: str | None, *, primary: bool = False) -> tuple[str, str]:
    """``(stream name, kind)`` for a table key: the annotation if there is one, else the key itself — a site's own list
    (its key is the source's) is its ``saved`` list, a key with a ``base`` its key less ``<base>-``."""
    if key in _LIST_NAMES:
        return _LIST_NAMES[key]
    name = "saved" if primary else _default_name(key, base)
    return name, _KIND_BY_NAME.get(name, "saved")


def _saved_groups() -> dict[str, Group]:
    """One group per source from ``saved_lists.PLATFORMS``, a key with a ``base`` site under that site (the attribute may
    not exist yet on an older table: a key with none is its own source), the base's stream first, then the others in table
    order."""
    out: dict[str, Group] = {}
    for key, platform in saved_lists.PLATFORMS.items():
        base = getattr(platform, "base", None)
        source = base if base and base in saved_lists.PLATFORMS else key
        group = out.setdefault(source, Group(source, saved_lists.PLATFORMS[source].name, account_key=source))
        name, kind = _list_name(key, base, primary=source == key)
        origins = (platform.origin,) if platform.origin else ()
        connector = key if key in ("x", "reddit", "pinterest") else None
        group.specs.append(Spec(
            id=f"{source}.{name}", source=source, label=platform.label or name.capitalize(), kind=kind, how="browser",
            channel=_items_channel(source),
            counts="channel" if platform.kind == "books" else "directory" if platform.kind in ("people", "accounts")
            else "members",
            origins=origins, match="label", list_label=platform.folder or None, origin=platform.origin or None,
            family="saved", key=key, connector=connector, channel_rows=(key,) if platform.kind == "books" else (),
            folders="save_folders" if key == source and platform.kind == "posts" else None))
    for group in out.values():
        # The base list leads: the order the site itself shows them is the table's own, base first.
        group.specs.sort(key=lambda s: 0 if s.key == group.id else 1)
    return out


def _items_channel(source: str) -> str | None:
    """The items route's channel a source's list rows live under (``channel_items``): the catalogue's own channel for a
    source that has one, else the source's own row id (a saved source with no channel is listed by its Sources row id)."""
    return source


def _youtube_specs() -> list[Spec]:
    specs = []
    labels = {name: str(spec.get("label") or name) for name, spec in youtube_lists.LISTS.items()}
    for name in youtube_lists.LISTS:
        stream, kind = _list_name(name, None)
        if name == "history":
            specs.append(Spec(id=f"youtube.{stream}", source="youtube", label="History", kind=kind, how="browser",
                              channel="youtube-history", counts="days", origins=("youtube-history",), family="youtube",
                              key=name))
        elif name == "playlists":
            specs.append(Spec(id=f"youtube.{stream}", source="youtube", label="Playlists", kind=kind, how="browser",
                              channel="youtube", counts="members", origins=("youtube-playlist",), match="rest",
                              family="youtube", key=name, folders="playlists"))
        else:
            specs.append(Spec(id=f"youtube.{stream}", source="youtube", label=labels[name][:1].upper() + labels[name][1:],
                              kind=kind if kind != "saved" else "later" if name == "watch_later" else "liked",
                              how="browser", channel="youtube", counts="members", origins=("youtube-playlist",),
                              match="label", list_label=_youtube_label(name, labels[name]), family="youtube", key=name))
    return specs


def _youtube_label(name: str, label: str) -> str:
    """The folder label a YouTube list's saves carry: Watch later's own, and Liked videos'."""
    return {"watch_later": "Watch later", "liked": "Liked videos"}.get(name, label)


def _substack_specs() -> list[Spec]:
    specs = []
    for name, spec in substack_lists.LISTS.items():
        stream, kind = _list_name(name, None)
        if name == "history":
            specs.append(Spec(id=f"substack.{stream}", source="substack", label=spec.label, kind=kind, how="browser",
                              channel="substack-history", counts="days", origins=("substack-history",),
                              family="substack", key=name))
        elif name == "subscriptions":
            specs.append(Spec(id=f"substack.{stream}", source="substack", label=spec.label, kind=kind, how="browser",
                              channel="substack-feeds", counts="channel", channel_rows=("substack-feeds",),
                              family="substack", key=name))
        else:
            specs.append(Spec(id=f"substack.{stream}", source="substack", label=spec.label, kind=kind, how="browser",
                              channel="substack", counts="members", origins=(substack_lists.ORIGIN_SAVED,),
                              match="label", list_label=spec.label, origin=substack_lists.ORIGIN_SAVED,
                              family="substack", key=name))
    return specs


def _static_specs() -> dict[str, list[Spec]]:
    """Every stream that is no browser list: a source's own app or sign-in, read from where it already says how it stands."""
    s = Spec
    return {
        "github": [
            s("github.stars", "github", "Stars", "saved", "account", control="setup", channel="github",
              counts="origin", origins=("github-starred",), channel_rows=("github",), connector="github"),
            s("github.repositories", "github", "Your repositories", "code", "account", control="setup",
              channel="github", counts="origin", origins=("github-owned", "github-added"), channel_rows=("github",),
              connector="github"),
        ],
        "linear": [s("linear.issues", "linear", "Issues", "tasks", "account", control="setup", channel="linear-api",
                     counts="origin", origins=("linear-api",), channel_rows=("linear-api",), connector="linear-api",
                     depth="read")],
        "notion": [s("notion.pages", "notion", "Pages you chose", "pages", "account", control="setup",
                     channel="notion-api", counts="origin", origins=("notion-api",), channel_rows=("notion-api",),
                     connector="notion-api")],
        "notes": [s("notes.notes", "notes", "Notes", "notes", "app", "app", "setup", channel="notes", counts="channel",
                    channel_rows=("notes",))],
        "calendar-local": [s("calendar-local.events", "calendar-local", "Events", "events", "app", "app", "setup",
                             channel="calendar-local", counts="channel", channel_rows=("calendar-local",))],
        "reminders-local": [s("reminders-local.reminders", "reminders-local", "Reminders", "tasks", "app", "app",
                              "setup", channel="reminders-local", counts="channel",
                              channel_rows=("reminders-local",))],
        "contacts-local": [s("contacts-local.contacts", "contacts-local", "Contacts", "connections", "app", "app",
                             "setup", channel="contacts-local", counts="channel", channel_rows=("contacts-local",),
                             depth="read")],
        "imessage": [s("imessage.chats", "imessage", "Chats you chose", "chats", "app", "app", "setup",
                       channel="imessage", counts="channel", channel_rows=("imessage",))],
        "whatsapp": [s("whatsapp.chats", "whatsapp", "Chats you chose", "chats", "app", "app", "setup",
                       channel="whatsapp", counts="channel", channel_rows=("whatsapp",))],
        "telegram-chats": [s("telegram-chats.chats", "telegram-chats", "Chats you chose", "chats", "account",
                             control="setup", channel="telegram-chats", counts="channel",
                             channel_rows=("telegram-chats",))],
        "telegram": [s("telegram.messages", "telegram", "Messages to your bot", "chats", "account", control="setup",
                       channel="telegram", counts="channel", channel_rows=("telegram",))],
        "voice-memos": [s("voice-memos.memos", "voice-memos", "Voice memos", "notes", "app", "app", "setup",
                          channel="voice-memos", counts="channel", channel_rows=("voice-memos",), depth="index")],
        "traces": [s("traces.traces", "traces", "Activity", "history", "app", "app", "setup", counts="none",
                     depth="index")],
        "apple-books": [s("apple-books.books", "apple-books", "Books and highlights", "books", "app", "app", "setup",
                          channel="apple-books", counts="channel", channel_rows=("apple-books",), depth="read")],
        "book-scan": [s("book-scan.books", "book-scan", "Books scanned", "books", "app", "backend", "setup",
                        channel="book-scan", counts="channel", channel_rows=("book-scan",), depth="read")],
        "files": [s("files.files", "files", "Files and links", "files", "app", "backend", "setup", channel="files",
                    counts="channel", channel_rows=("files",))],
        "chat-exports": [s("chat-exports.chats", "chat-exports", "Chat exports", "chats", "app", "backend", "setup",
                           counts="channel", depth="read",
                           channel_rows=("chat-export:claude", "chat-export:chatgpt", "chat-export:gemini"))],
        "rss": [s("rss.feeds", "rss", "Feeds you follow", "feed", "app", "backend", "setup", channel="rss",
                  counts="channel", channel_rows=("rss",))],
        "calendar": [s("calendar.calendars", "calendar", "Calendar links", "events", "app", "backend", "setup",
                       channel="calendar", counts="channel", channel_rows=("calendar",))],
    }


def _browser_specs(rows: dict[str, dict]) -> dict[str, list[Spec]]:
    """One source per browser (``browser:<id>``): bookmarks, and what else that browser's app reads (Safari's Reading List
    and iCloud tabs, Chrome's tab groups and YouTube history). Chrome and Safari always; another Chromium browser once it
    has synced, as ``channel_registry`` lists it."""
    out: dict[str, list[Spec]] = {}
    for browser in ("chrome", "safari", *[b for b in bookmark_sync.CHROMIUM_BROWSERS if b != "chrome"]):
        channel = bookmark_sync.channel_for(browser) if browser != "safari" else "safari-bookmarks"
        if browser not in ("chrome", "safari") and channel not in rows:
            continue
        source = f"browser:{browser}"
        specs = [Spec(f"{source}.bookmarks", source, "Bookmarks", "saved", "app", "app", "setup", channel=channel,
                      counts="channel", channel_rows=(channel,))]
        if browser == "safari":
            specs.append(Spec(f"{source}.reading-list", source, "Reading List", "later", "app", "app", "setup",
                              channel=channel, counts="part", channel_rows=(channel,), note="reading-list"))
            specs.append(Spec(f"{source}.icloud-tabs", source, "iCloud tabs", "pages", "app", "app", "setup",
                              channel="safari-tabs", counts="channel", channel_rows=("safari-tabs",)))
        if browser in tab_groups.BROWSERS:
            tabs = tab_groups.channel_id(browser)
            specs.append(Spec(f"{source}.tab-groups", source, "Tab groups", "pages", "app", "app", "setup",
                              channel=tabs, counts="channel", channel_rows=(tabs,)))
        if browser in watch_history.BROWSERS:
            yt = watch_history.channel_id(browser)
            specs.append(Spec(f"{source}.youtube-history", source, "YouTube history", "history", "app", "app", "setup",
                              channel=yt, counts="channel", channel_rows=(yt,)))
        out[source] = specs
    return out


def groups(rows: dict[str, dict] | None = None) -> list[Group]:
    """Every source and its streams, in the order the page lists them. ``rows`` are the channel rows by id (for the
    browsers a Mac may have)."""
    rows = rows or {}
    table: dict[str, Group] = _saved_groups()
    youtube = table.setdefault("youtube", Group("youtube", _SOURCE_LABELS["youtube"]))
    youtube.specs = _youtube_specs() + youtube.specs
    substack = table.setdefault("substack", Group("substack", _SOURCE_LABELS["substack"]))
    substack.specs = _substack_specs() + substack.specs
    for source, specs in _static_specs().items():
        table.setdefault(source, Group(source, _SOURCE_LABELS[source])).specs.extend(specs)
    for source, specs in _browser_specs(rows).items():
        browser = source.split(":", 1)[1]
        table[source] = Group(source, _BROWSER_NAMES.get(browser, browser.capitalize()), specs=specs)
    for source, label in _CLICK_SITES:
        group = table.setdefault(source, Group(source, label))
        group.specs.append(Spec(f"{source}.saves-you-make", source, "Saves you make", "saved", "click", "app",
                                "switch", counts="none", note="click"))
    ordered = sorted(table, key=lambda i: _SOURCE_ORDER.index(i) if i in _SOURCE_ORDER else len(_SOURCE_ORDER))
    return [table[i] for i in ordered if table[i].specs]


def spec_of(stream_id: str) -> Spec | None:
    for group in groups():
        for spec in group.specs:
            if spec.id == stream_id:
                return spec
    return None


# --- membership: one cached pass over the media pages --------------------------------------------------------------


def _cf(text) -> str:
    return " ".join(str(text or "").split()).casefold()


@dataclass
class Members:
    """What one pass over the media pages knows: each stream's members and folders, the pages of an origin, and the lists
    each page is on."""
    members: dict[str, frozenset[str]]
    #: stream id -> {folder name casefolded: (name, members)} for the streams that file into folders.
    playlists: dict[str, dict[str, tuple[str, int]]]
    origin_counts: Counter
    #: page id -> the streams that hold it (the inverse of ``members``), so a row's own lists can be named by the streams it
    #: is really on, whichever door first kept it.
    streams_of: dict[str, tuple[str, ...]] = field(default_factory=dict)


def _site_origins(group_specs: list[Spec], source: str) -> frozenset[str]:
    """The origins a source's saves carry: the catalogue's own, and each list's."""
    origins = {o for spec in source_overview.CATALOG if spec.id == source for o in spec.origins}
    for spec in group_specs:
        origins |= set(spec.origins)
    return frozenset(origins)


#: The hosts a source's own posts live on, for the sources whose list tables do not name them (the saved lists name theirs
#: in ``Platform.profile_hosts``).
_SITE_HOSTS = {"youtube": ("youtube.com", "youtu.be"), "substack": ("substack.com",)}


def _sites_of(source: str) -> frozenset[str]:
    """The site keys (``reading_hosts.site_of``) a source's posts are on: X's ``x``, YouTube's ``youtube.com``. A page kept by
    another door belongs to a source's list only on its own site AND the list's label, because a label alone ("Bookmarks",
    "Saved") is a name several sites use."""
    hosts: list[str] = list(_SITE_HOSTS.get(source, ()))
    for key, platform in saved_lists.PLATFORMS.items():
        if key == source or getattr(platform, "base", None) == source:
            hosts += [platform.site, *platform.profile_hosts]
    return frozenset(site for h in hosts if (site := reading_hosts.site_of(h)))


#: The origins whose pages are filed under the browser's own folders (a Chrome bookmark folder, a Safari tab group), never
#: under a site's list: a folder called "Bookmarks" there is no list of a site.
_BROWSER_ORIGINS = frozenset(o for spec in source_overview.CATALOG if spec.kind == "browser" for o in spec.origins)


def _page_site(fm: dict) -> str:
    media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
    return reading_hosts.site_of(str(media.get("url") or ""))


def _on_site(origin: str, fm: dict, sites: frozenset[str]) -> bool:
    """Is a page of ANOTHER origin (a saved link, a link before pages carried one) on this source's own site?"""
    return origin not in _BROWSER_ORIGINS and bool(sites) and _page_site(fm) in sites


def _signature(specs: list[Spec]) -> str:
    rows = [(s.id, s.match, s.list_label, s.origin, s.origins) for s in specs]
    return hashlib.sha1(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:12]


def _member_groups() -> list[tuple[str, frozenset[str], list[Spec]]]:
    """``(source, its origins, its member streams)`` for every source whose streams are counted by membership."""
    out = []
    for group in groups():
        member_specs = [s for s in group.specs if s.counts == "members"]
        if member_specs:
            out.append((group.id, _site_origins(member_specs, group.id), member_specs))
    return out


def _classify(spec_group: list[Spec], origin: str, lists: list[str]) -> list[Spec]:
    held = {_cf(name) for name in lists}
    labels = {_cf(s.list_label) for s in spec_group if s.match == "label" and s.list_label}
    hit = [s for s in spec_group if s.match == "label" and s.list_label and _cf(s.list_label) in held]
    hit += [s for s in spec_group if s.match == "rest" and held - labels]
    if not hit and not held:
        own = [s for s in spec_group if s.match == "label" and s.origin == origin]
        hit = own[:1]
    elif not hit and not [s for s in spec_group if s.match == "rest"]:
        # A list no stream names (Reddit's connector files under ``r/<sub>``): the stream of the page's own origin.
        own = [s for s in spec_group if s.match == "label" and s.origin == origin]
        hit = own[:1]
    return hit


def members(memory_path: Path) -> Members:
    """The membership pass, kept until the media pages' cached headers change."""
    plan = _member_groups()
    key = "source_streams.members:" + _signature([s for _src, _o, specs in plan for s in specs])
    return bank_index.derived(Path(memory_path), "entities", key, lambda entries: _build_members(entries, plan))


def _build_members(entries, plan) -> Members:
    held: dict[str, set[str]] = {s.id: set() for _src, _o, specs in plan for s in specs}
    playlists: dict[str, dict[str, list]] = {s.id: {} for _src, _o, specs in plan for s in specs if s.folders == "playlists"}
    origin_counts: Counter = Counter()
    sites = {source: _sites_of(source) for source, _o, _s in plan}
    streams_of: dict[str, list[str]] = {}
    for f in entries:
        fm = f.frontmatter or {}
        if fm.get("type") != "media" or source_overview.is_hidden(fm):
            continue
        origin = str(fm.get("origin") or "").strip()
        origin_counts[origin] += 1
        lists = id_utils.page_lists(fm)
        for source, origins, specs in plan:
            # Counts are list membership, not a post's first origin: a post first kept as a saved link and later seen on
            # the site's list is on that list too (its page's own site and the list's label say so).
            if origin not in origins and not _on_site(origin, fm, sites[source]):
                continue
            for spec in _classify(specs, origin, lists):
                held[spec.id].add(f.stem)
                streams_of.setdefault(f.stem, []).append(spec.id)
                if spec.id in playlists:
                    own = {_cf(s.list_label) for s in specs if s.match == "label" and s.list_label}
                    for name in lists:
                        if _cf(name) not in own:
                            slot = playlists[spec.id].setdefault(_cf(name), [name, 0])
                            slot[1] += 1
    return Members({k: frozenset(v) for k, v in held.items()},
                   {k: {c: (v[0], v[1]) for c, v in names.items()} for k, names in playlists.items()}, origin_counts,
                   {k: tuple(v) for k, v in streams_of.items()})


# --- one pass over the episodes ----------------------------------------------------------------------------------------


@dataclass
class Episodes:
    #: episode id -> the folder names a save was filed in on its site (``save_folders``), for the saves that have any.
    folders_of: dict[str, tuple[str, ...]]
    #: (origin, folder casefolded) -> (name, saves) — how many saves each folder holds.
    folder_names: dict[tuple[str, str], list]
    #: origin -> history days (one episode a day watched or read), never a month's summary.
    days: Counter
    #: media page ids whose save a model read, and the url hashes an agent read or watched.
    read_pages: frozenset[str]
    agent_read: frozenset[str]
    #: the url hashes an agent recorded a WATCH of (``video-watch``): the deepest a save goes (``depth: watched``).
    agent_watched: frozenset[str]
    #: source key -> episodes, for the agents' conversations (``harness:<name>``).
    harnesses: Counter
    harness_last: dict[str, str]
    #: episode id -> the day the post itself was published, for the saves whose list showed one (``posted`` in the
    #: episode's frontmatter, written by ``cicada_record_saved_list``).
    posted_of: dict[str, str]


def _build_episodes(entries) -> Episodes:
    folders_of: dict[str, tuple[str, ...]] = {}
    folder_names: dict[tuple[str, str], list] = {}
    days: Counter = Counter()
    read_pages: set[str] = set()
    agent_read: set[str] = set()
    agent_watched: set[str] = set()
    harnesses: Counter = Counter()
    last: dict[str, str] = {}
    posted_of: dict[str, str] = {}
    for f in entries:
        fm = f.frontmatter or {}
        if fm.get("source_deleted_at"):
            continue
        stem = str(fm.get("id") or f.stem)
        kind = history_index.kind(fm)
        origin = str(fm.get("origin") or "")
        if kind == "history":
            days[origin] += 1
        if fm.get("source") in ("page-read", "video-watch") and fm.get("url"):
            agent_read.add(media_ingestor.url_hash(str(fm["url"])))
            if fm.get("source") == "video-watch":
                agent_watched.add(media_ingestor.url_hash(str(fm["url"])))
        if (page := str(fm.get("media_entity_id") or "")) and fm.get("processed") \
                and fm.get("processed_by") not in (history_index.INDEXED_BY, history_index.NO_WORDS_BY) \
                and fm.get("source") not in history_index.NOT_A_SAVE:
            read_pages.add(page)
        if day := saved_at.posted_day(fm.get("posted")):
            posted_of[stem] = day
        held = save_folders.folders_of(fm)
        if held:
            names = tuple(dict.fromkeys(n for _o, n in held))
            folders_of[stem] = names
            for o, n in held:
                slot = folder_names.setdefault((o, _cf(n)), [n, 0])
                slot[1] += 1
        key = source_overview.row_key(fm)
        if key and key.startswith("harness:"):
            harnesses[key] += 1
            stamp = str(fm.get("timestamp") or "")
            if stamp > last.get(key, ""):
                last[key] = stamp
    return Episodes(folders_of, folder_names, days, frozenset(read_pages), frozenset(agent_read),
                    frozenset(agent_watched), harnesses, last, posted_of)


def episodes(memory_path: Path) -> Episodes:
    return bank_index.derived(Path(memory_path), "episodes", "source_streams.episodes", _build_episodes)


# --- state ---------------------------------------------------------------------------------------------------------


def _z(value) -> str | None:
    """An instant as the wire writes it (``...Z``); ``None`` for none or something unreadable."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _newest(values) -> str | None:
    present = [v for v in values if v]
    return max(present) if present else None


def _channel_view(rows: dict[str, dict], ids: tuple[str, ...]) -> dict:
    """What the channel rows say about a stream: connected, the newest last sync, the first failure, the summed count."""
    found = [rows[i] for i in ids if i in rows]
    connected = [r for r in found if r.get("connected")]
    failing = next((r for r in connected if r.get("last_error")), None)
    return {
        "present": bool(found), "connected": bool(connected),
        "last": _z(_newest(r.get("last_sync") for r in found)),
        "error": failing.get("last_error") if failing else None,
        "signin": bool(failing and (failing.get("last_error_code") == "sign-in")),
        "count": sum(int(r.get("count") or 0) for r in found if not r.get("count_is_delta")) if found else None,
        "parts": {p.get("key"): int(p.get("count") or 0) for r in found for p in (r.get("parts") or [])},
        "why": next((r.get("detail") for r in found if r.get("detail") and not r.get("connected")), None),
    }


def _health(view: dict) -> str | None:
    if not view["connected"]:
        return None
    if view["error"]:
        return "signed_out" if view["signin"] else "couldnt_read"
    return "read" if view["last"] else "not_read"


_FAMILIES: dict[str, Any] = {"saved": saved_lists, "youtube": youtube_lists, "substack": substack_lists}


def _family_paused(spec: Spec, memory_path: Path, now) -> datetime | None:
    store = _FAMILIES[spec.family]
    return store.paused_until(spec.key, now) if spec.family == "saved" else store.paused_until(now)


def _sharing_keys(spec: Spec) -> list[str]:
    """The table keys that share this stream's pause: every list of a site (a base's dependents too), or of Substack and
    YouTube, whose one sign-in covers them all."""
    if spec.family == "saved":
        mine = saved_lists.pause_key(spec.key)
        return [k for k in saved_lists.PLATFORMS if saved_lists.pause_key(k) == mine]
    return list(youtube_lists.LISTS if spec.family == "youtube" else substack_lists.LISTS)


def _pause_health(spec: Spec, memory_path: Path) -> str:
    """Why a paused list is paused, in the lists' own words: the newest pausing outcome any list that shares the pause
    recorded (a login wall: ``signed_out``; a block: ``couldnt_read``); ``paused`` when none says."""
    store = _FAMILIES[spec.family]
    newest, outcome = "", None
    for key in _sharing_keys(spec):
        entry = store.last(memory_path, key)
        if entry.get("outcome") in store.PAUSING and str(entry.get("at") or "") >= newest:
            newest, outcome = str(entry.get("at") or ""), entry.get("outcome")
    return saved_lists.state_of(outcome) if outcome else "paused"


def _list_view(spec: Spec, memory_path: Path, now) -> dict:
    """A browser list's own state, from the lists' stores: on only while agent reading counts and the person turned it on;
    its health from its last attempt, or ``paused`` words when a login wall holds it."""
    store = _FAMILIES[spec.family]
    entry = store.last(memory_path, spec.key)
    on = bool(store.allowed(spec.key))
    until = _family_paused(spec, memory_path, now)
    health = None
    if on:
        health = _pause_health(spec, memory_path) if until is not None else (
            "not_read" if entry.get("outcome") in store.PAUSING else saved_lists.state_of(entry.get("outcome")))
    return {"on": on, "health": health, "last": _z(entry.get("read_at")), "until": _z(until.isoformat()) if until else None,
            "checkRequestedAt": _z(entry.get("check_requested_at"))}


def _connector_view(spec: Spec, rows: dict[str, dict], connected: dict[str, bool]) -> dict:
    """A stream read through a sign-in the person gave: the connector's own row, plus its own word that it needs the
    person back (a refused or expired sign-in)."""
    from api.services.connectors import ADAPTERS

    view = _channel_view(rows, (spec.connector,))
    adapter = ADAPTERS.get(spec.connector)
    needs = bool(adapter is not None and getattr(adapter, "needs_reconnect", lambda: False)())
    view["connected"] = bool(connected.get(spec.connector)) or view["connected"]
    if needs and view["connected"]:
        view["error"], view["signin"] = view["error"] or "reconnect", True
    return view


def _depth(spec: Spec) -> str:
    return spec.depth or ("read" if spec.kind in _READ_KINDS else "index")


def _directory_count(spec: Spec, memory_path: Path) -> int | None:
    """How many a directory outside every bank holds, by the list's kind (``Platform.kind``): the people kind is LinkedIn's
    connections, the accounts kind the accounts followed now; a kind with no directory has no count to claim."""
    from api.services import follows_people, linkedin_people

    kind = saved_lists.PLATFORMS[spec.key].kind
    if kind == "people":
        return int(linkedin_people.status(Path(memory_path).name)["connections"] or 0)
    if kind == "accounts" and follows_people.has_site(spec.key):
        return follows_people.following_count(Path(memory_path).name, follows_people.site_of_platform(spec.key).key)
    return None


def _count(spec: Spec, mem: Members, eps: Episodes, view: dict, memory_path: Path) -> int | None:
    if spec.counts == "directory":
        return _directory_count(spec, memory_path)
    if spec.counts == "members":
        return len(mem.members.get(spec.id, ()))
    if spec.counts == "origin":
        return sum(mem.origin_counts.get(o, 0) for o in spec.origins)
    if spec.counts == "days":
        return sum(eps.days.get(o, 0) for o in spec.origins)
    if spec.counts == "channel":
        return view["count"]
    if spec.counts == "part":
        return view["parts"].get(spec.note)
    return None


def _folder_count(spec: Spec, mem: Members, eps: Episodes, origins: frozenset[str]) -> int:
    if spec.folders == "playlists":
        return len(mem.playlists.get(spec.id, {}))
    if spec.folders == "save_folders":
        return len({c for (o, c) in eps.folder_names if o in origins})
    return 0


_NO_VIEW = {"present": False, "connected": False, "last": None, "error": None, "signin": False, "count": None,
            "parts": {}, "why": None}
_FEEDS_OFF = "Feeds and calendar links aren't being checked: turn on Keep memory working in Settings → General."


def _stream(spec: Spec, memory_path: Path, rows, connected, mem, eps, origins, now, feed_fetch: bool) -> dict:
    out: dict[str, Any] = {
        "id": spec.id, "label": spec.label, "kind": spec.kind, "how": spec.how, "owner": spec.owner,
        "control": spec.control, "state": "off", "health": None, "lastReadAt": None, "pausedUntil": None,
        "checkRequestedAt": None, "count": None, "folderCount": 0, "depth": _depth(spec), "switch": spec.switch,
        "why": None, "channel": spec.channel,
    }
    view = _channel_view(rows, spec.channel_rows) if spec.channel_rows else _NO_VIEW
    if spec.connector and connected.get(spec.connector):
        # The sign-in the person gave is the way in use: the same stream, read as an account (plan 2.3), its state the
        # connector's own and not the browser switch's.
        view = _connector_view(spec, rows, connected)
        out.update(how="account", control="setup", switch=None, state="on", health=_health(view),
                   lastReadAt=view["last"])
    elif spec.family is not None:
        lv = _list_view(spec, memory_path, now)
        out.update(state="on" if lv["on"] else "off", health=lv["health"], lastReadAt=lv["last"] or view["last"],
                   pausedUntil=lv["until"], checkRequestedAt=lv["checkRequestedAt"])
    elif spec.note == "click" or spec.id == "traces.traces":
        pass   # the app's own switch and permission write over this row (``owner: app``)
    else:
        out.update(state="on" if view["connected"] else "off", health=_health(view), lastReadAt=view["last"])
        if spec.id in ("chat-exports.chats", "files.files"):
            out["state"] = "on" if (view["count"] or 0) > 0 else "off"
        if spec.id in ("rss.feeds", "calendar.calendars") and not feed_fetch:
            out.update(state="unavailable", health=None, why=_FEEDS_OFF)
    out["count"] = _count(spec, mem, eps, view, memory_path)
    if out["count"] == 0 and out["lastReadAt"] is None:
        # Nothing held and never read: unknown, not empty. A read that found nothing records its day (``read_at``), so
        # "read and empty" stays 0 and the app never draws "Playlists 0" on a list nobody has read.
        out["count"] = None
    out["folderCount"] = _folder_count(spec, mem, eps, origins)
    return out


# --- the whole body ------------------------------------------------------------------------------------------------------


def _groups_for(rows: dict[str, dict], memory_path: Path, eps: Episodes) -> list[Group]:
    """The static groups, plus the sources that exist only as this bank's own data: the agents that held a conversation,
    the folders and meeting recorders the person registered."""
    table = groups(rows)
    by_id = {g.id: g for g in table}
    registered = folder_source.list_folders(memory_path)
    plain = [f for f in registered if not folder_source.is_meetings(f)]
    meetings = [f for f in registered if folder_source.is_meetings(f)]
    by_recorder = {"hex": [f for f in meetings if f.get("recorder") == "hex"],
                   "meeting-folders": [f for f in meetings if f.get("recorder") != "hex"]}
    extra: list[Group] = []
    extra.append(Group("folders", _SOURCE_LABELS["folders"], [Spec(
        "folders.files", "folders", "Files in folders", "files", "app", "app", "setup", counts="channel",
        channel_rows=tuple(folder_source.channel_for(f) for f in plain), depth="read")]))
    for source, folders in by_recorder.items():
        if folders or source == "meeting-folders":
            extra.append(Group(source, _SOURCE_LABELS[source], [Spec(
                f"{source}.meetings", source, "Meetings", "events", "app", "app", "setup", counts="channel",
                channel_rows=tuple(folder_source.channel_for(f) for f in folders), depth="read")]))
    for key in sorted(eps.harnesses, key=lambda k: (-eps.harnesses[k], k)):
        harness = key.split(":", 1)[1]
        label = source_overview.HARNESS_LABELS.get(harness, harness)
        extra.append(Group(f"overview:{key}", label, [Spec(
            f"overview:{key}.conversations", f"overview:{key}", "Conversations", "chats", "app", "backend", "setup",
            counts="conversations", note=key, depth="read")]))
    for group in extra:
        if group.id not in by_id:
            table.append(group)
    order = {i: n for n, i in enumerate(_SOURCE_ORDER)}
    table.sort(key=lambda g: (order.get(g.id, len(order)), 0 if not g.id.startswith("overview:") else 1))
    return table


def build(memory_path: Path, *, channels: list[dict], connectors_connected: dict[str, bool] | None = None,
          feed_fetch_allowed: bool = True, now: datetime | None = None) -> dict:
    """The ``GET /sources/streams`` body. ``channels`` are ``channel_registry.build_channels`` rows (the caller's, so the
    route can cache them), ``connectors_connected`` the connectors' own ``is_connected`` answers."""
    memory_path = Path(memory_path)
    rows = {c["id"]: c for c in channels}
    connected = connectors_connected or {}
    mem, eps = members(memory_path), episodes(memory_path)
    out = []
    for group in _groups_for(rows, memory_path, eps):
        origins = _site_origins([s for s in group.specs if s.counts == "members"], group.id)
        streams = []
        for spec in group.specs:
            stream = _stream(spec, memory_path, rows, connected, mem, eps, origins, now, feed_fetch_allowed)
            if spec.counts == "conversations":
                stream["count"] = eps.harnesses.get(spec.note, 0)
                stream["state"] = "on"
                stream["lastReadAt"] = _z(eps.harness_last.get(spec.note))
            streams.append(stream)
        out.append({"id": group.id, "label": group.label, "account": _account(group, memory_path), "streams": streams})
    return {"shape": SHAPE, "sources": out}


def _account(group: Group, memory_path: Path) -> dict | None:
    if not group.account_key:
        return None
    entry = saved_lists.last(memory_path, group.account_key)
    handle, url = entry.get("handle") or None, entry.get("profile_url") or None
    return {"handle": handle, "profileUrl": url} if handle or url else None


def etag(body: dict) -> str:
    """The route's ETag: a digest of the body (the ``/reading/settings`` precedent), so a pause that lapses or a read that
    lands changes it with no clock of its own."""
    return '"' + hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16] + '"'


# --- checking a connection -----------------------------------------------------------------------------------------------

#: What a check reported for one stream. ``requested``: the person's own AI app reads it next. ``signed_out`` and
#: ``paused``: a login wall holds the list, and a check never lifts it. ``app``: the app runs its own reader. ``read`` and
#: ``failed``: a sign-in the person gave was asked now. ``off``: the person has not turned it on. ``not_connected``: no
#: sign-in. ``noted``: the stream has nothing to run.
RESULTS = ("requested", "signed_out", "paused", "app", "read", "failed", "off", "not_connected", "noted")


async def check(memory_path: Path, source_ids: list[str] | None, *, channels: list[dict],
                connectors_connected: dict[str, bool] | None, sync: Callable | None = None,
                now: datetime | None = None) -> list[dict]:
    """The backend's half of a check, for the streams of ``source_ids`` (all when none): ``[{stream, result}]``. Browser
    lists are stamped for the lists' ``due`` logic; an app's streams are reported, never run; a connector's own sync runs
    once for the sign-in the person gave, however many streams ride on it. ``sync`` replaces that call in tests."""
    memory_path = Path(memory_path)
    rows = {c["id"]: c for c in channels}
    connected = connectors_connected or {}
    eps = episodes(memory_path)
    wanted = set(source_ids or [])
    results: list[dict] = []
    ran: dict[str, str] = {}
    for group in _groups_for(rows, memory_path, eps):
        if wanted and group.id not in wanted:
            continue
        for spec in group.specs:
            results.append({"stream": spec.id, "result": await _check_one(spec, memory_path, connected, ran, sync, now)})
    return results


async def _check_one(spec: Spec, memory_path: Path, connected, ran: dict, sync, now) -> str:
    if spec.connector and connected.get(spec.connector):
        if spec.connector not in ran:
            ran[spec.connector] = await _run_connector(spec.connector, memory_path, sync)
        return ran[spec.connector]
    if spec.family is not None:
        store = _FAMILIES[spec.family]
        if not store.allowed(spec.key):
            return "off"
        if _family_paused(spec, memory_path, now) is not None:
            return "paused" if _pause_health(spec, memory_path) == "paused" else _pause_health(spec, memory_path)
        return "requested" if store.request_check(memory_path, spec.key, now) else "off"
    if spec.connector:
        return "not_connected"
    if spec.note == "click" or spec.how == "click":
        return "noted"
    return "app"


async def _run_connector(connector: str, memory_path: Path, sync: Callable | None) -> str:
    """The connector's own sync, the person's click (``allow_fetch`` always: the opt-out gate stops only an unattended
    poll). Never raises: a refusal is a word, never an exception's message."""
    from api.services.connectors import ADAPTERS

    adapter = ADAPTERS.get(connector)
    if adapter is None:
        return "not_connected"
    try:
        result = await (sync or _default_sync)(adapter, memory_path)
    except Exception:  # noqa: BLE001 - the class is all a caller needs; a message could carry a credential
        return "failed"
    status = (result or {}).get("status")
    return "read" if status == "ok" else "not_connected" if status == "skipped" else "failed"


async def _default_sync(adapter, memory_path: Path) -> dict:
    return await adapter.sync(memory_path, allow_fetch=True)


# --- the items route's half ------------------------------------------------------------------------------------------------


def list_origins() -> frozenset[str]:
    """The origins of every stream counted by list membership: a row on one of them carries ``lists``, ``folders``,
    ``depth`` and ``posted``."""
    return frozenset(o for _src, origins, _specs in _member_groups() for o in origins)


def stream_members(memory_path: Path, stream_id: str) -> frozenset[str] | None:
    """The media pages a stream holds, or ``None`` when its items are not members of a list (the stream is the channel)."""
    spec = spec_of(stream_id)
    if spec is None or spec.counts != "members":
        return None
    return members(memory_path).members.get(spec.id, frozenset())


def folder_matches(memory_path: Path, rows: list[dict], pages: dict[str, dict], folder: str) -> list[dict]:
    """The rows filed in ``folder``: on the site (``save_folders``, by the save's episode) or as a list of the page itself
    (a playlist, a board). Compared the way folders are everywhere, ignoring case."""
    wanted = _cf(folder)
    eps = episodes(memory_path)
    out = []
    for row in rows:
        names = {_cf(n) for n in eps.folders_of.get(str(row.get("_episode") or ""), ())}
        names |= {_cf(n) for n in id_utils.page_lists(pages.get(row.get("id"), {}))}
        if wanted in names:
            out.append(row)
    return out


def _list_display_names() -> dict[tuple[str, str], str]:
    """``(stream id, folded list name)`` -> the label of the stream that list is, for the lists whose stored name is not the
    stream's own name (``Saved Items`` -> ``Saved posts``); a list that already carries it is not in the map. Keyed by the
    stream, not the page's origin, so a post first kept by another door is named the same way. Built once a request."""
    out: dict[tuple[str, str], str] = {}
    for group in groups():
        for spec in group.specs:
            if spec.counts == "members" and spec.list_label and spec.label and _cf(spec.list_label) != _cf(spec.label):
                out[(spec.id, _cf(spec.list_label))] = spec.label
    return out


def row_fields(memory_path: Path, rows: list[dict], pages: dict[str, dict], posted: Callable[[dict], str | None]) -> dict[str, dict]:
    """The three fields a list row gains (plan 2.2), by row id: ``lists`` (the labels of the lists the item is on),
    ``folders`` (the site's own folder names), ``depth`` and ``posted`` (the post's own day, when the list showed one).
    ``depth`` (ruling 78 (e)), deepest first: ``watched`` (the person's own agent recorded a watch) · ``asked`` (the person
    talked about it and an ask waits on a queue for their agent, honoured now) · ``read`` (Sleep read it, or an agent read
    its page) · ``kept`` (indexed, no model has read it). Built from maps computed once per request; only a media row of a
    list origin gets any."""
    from api.services import mention_asks

    eps = episodes(memory_path)
    origins = list_origins()
    streams_of = members(memory_path).streams_of
    asked = mention_asks.waiting_hashes(memory_path)
    names = _list_display_names()
    out: dict[str, dict] = {}
    for row in rows:
        if row.get("kind") != "media":
            continue
        fm = pages.get(row.get("id")) or {}
        # A row of a list: a post of a list's own origin, or one another door kept first that a list holds (the same
        # membership the counts and the ``stream`` filter use).
        on = streams_of.get(row.get("id"), ())
        if str(fm.get("origin") or "").strip() not in origins and not on:
            continue
        lists = id_utils.page_lists(fm)
        held = {_cf(n) for n in lists}
        # A list is drawn under the stream's own name (LinkedIn's saved posts were filed under the export's "Saved Items").
        lists = list(dict.fromkeys(next((names[(sid, _cf(n))] for sid in on if (sid, _cf(n)) in names), n) for n in lists))
        folders = [n for n in eps.folders_of.get(str(row.get("_episode") or ""), ()) if _cf(n) not in held]
        h = media_ingestor.url_hash(str(row["_url"])) if row.get("_url") else ""
        read = row.get("id") in eps.read_pages or (bool(h) and h in eps.agent_read)
        depth = "watched" if h and h in eps.agent_watched else "asked" if h and h in asked else \
            "read" if read else "kept"
        fields: dict[str, Any] = {"depth": depth}
        if lists:
            fields["lists"] = lists
        if folders:
            fields["folders"] = folders
        if day := eps.posted_of.get(str(row.get("_episode") or "")) or posted(row):
            fields["posted"] = day
        # Who wrote the post: the page's channel, which the record tool keeps (`media.channel`, as a video's channel).
        media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
        if who := " ".join(str(media.get("channel") or "").split())[:60]:
            fields["author"] = who
        out[row["id"]] = fields
    return out
