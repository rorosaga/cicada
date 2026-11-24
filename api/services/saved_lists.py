"""The person's own agent keeps their saved lists on X, Instagram and LinkedIn — and, since G232 (2026-11-04), Reddit,
Pinterest and TikTok — current (G206, ruling 36; extends G166 and G71).

Owner, redesign 2026-10-22: the person's saved posts pile up where Cicada cannot see them, and the three sites are
walled (the backend never fetches a login-walled page, the ToS rail). The YouTube lists already come in through the
person's own agent in their signed-in browser (``youtube_lists``, owner 2026-10-16); this is the same shape per site:

* **X** — Bookmarks (``https://x.com/i/bookmarks``), saved as origin ``x-bookmarks``, folder ``Bookmarks`` (the X
  archive's own folder, so a bookmark the archive already brought in is the same row).
* **Instagram** — Saved (the profile's Saved tab), origin ``instagram-saved``, folder ``Saved``.
* **LinkedIn** — Saved posts (``https://www.linkedin.com/my-items/saved-posts/``), origin ``linkedin-saved``, folder
  ``Saved Items``.

All three origins are a platform's saved LIST (``history_index.kind``): each item is saved where saved links go,
**indexed, never read by a model** (ruling 30) — found by lookup, read by a model only if the person asks about one.
An item is a link the agent saw; dedup is by URL (``url_index``, with the other spellings of the same post as
aliases), and the platform's own ids are never asked for.

**The rails are G166's.** Cicada never spawns a browser, never signs in and never fetches a list page: it only
*offers* the task — lines in ``cicada_reading_queue`` (stdio only) and one in the recall hook's count — while agent
reading is on (its first-use sheet acknowledged) **and** the person turned that site's list on (``reading_settings
.saved_lists``, on by default since 2026-10-26 — asked once, pre-ticked, in onboarding, and on an existing install
turned on by ``list_defaults`` only for an account the memory shows, never over an off the person chose; a standing
ask for exactly that page, never a site grant). The agent records through
``cicada_record_saved_list`` (``record`` scope, stdio only). ``needs_login`` or ``blocked`` pauses THAT site's list for
a week (a sign-in on X says nothing about Instagram) and asks the person, through the G205 Inbox kind, to sign in;
turning the list on again lifts the pause (Try again). Bounds until measured (G206): one site's list offered at a time,
and at most :data:`DAILY_READS` recorded reads a UTC day per bank across the three — the LinkedIn profile read's bound.

**G245 (ruling 78b, 2026-11-24)** adds second lists of a site (``Platform.base``: X likes, Instagram likes, Reddit upvoted —
each off until turned on, sharing its site's address rules, handle, profile link and pause), the folder pass (a read is the
All page then up to 12 folders, its calls tied by ``continues`` and counted once against :data:`DAILY_READS`), catching up
(the first read scrolls deeper, a later one stops at what is kept) and a row's own ``posted`` day. See ``folder_pass``.

This module holds only the offer: when each list was last read for each bank, the pauses and the day's count. One
small file outside every bank (``$CICADA_HOME/saved_lists.json``, 0600, atomic, ``flock``ed — the backend and every
stdio server write it). Ids, enums, counts and times only; never a title or a URL of the person's.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from api.services import folder_pass, reading_settings
from api.services.auth import cicada_home

FILENAME = "saved_lists.json"


@dataclass(frozen=True)
class Platform:
    key: str
    #: The site's name, as the person knows it.
    name: str
    #: The list's name on that site.
    label: str
    #: Where the agent starts, and how it reaches the list from there (Instagram's Saved lives under a profile, whose
    #: name Cicada does not keep).
    url: str
    how: str
    origin: str
    folder: str
    #: The host an agent request names (G205), and the words it asks with.
    site: str
    reason: str
    #: The domains the person's own profile link may be on (ROR-114): the platform's own, never another site.
    profile_hosts: tuple[str, ...] = ()
    #: A list that is a second list of a site already here (G245: X likes beside X bookmarks) names that site's key. A
    #: key with a base shares the site's address rules (``canonical``), handle, profile link and pause (a login wall
    #: pauses every list of the site); its own switch, cadence and read are its own.
    base: str = ""
    #: Does the site file this list's posts in folders of their own (X bookmark folders, Instagram collections), each
    #: on its own page? Only then does a read include the folder pass (:data:`FOLDERS_PER_PASS`).
    folders: bool = False
    #: What the agent reads of each post, when the list shows less or more than words (Instagram's grid).
    reads: str = "its author as the page shows it, and the words the post shows"


PLATFORMS: dict[str, Platform] = {
    # Measured 2026-11-24: X now files Bookmarks under History, so this address lands on ``/i/history`` (tabs Bookmarks
    # and Likes); the old address still opens it.
    "x": Platform("x", "X", "Bookmarks", "https://x.com/i/bookmarks",
                  " (X may show it as History, Bookmarks tab, at /i/history: the same list)", "x-bookmarks", "Bookmarks",
                  "x.com", "to read your bookmarks", ("x.com", "twitter.com"), folders=True),
    # G245 (ruling 78b, owner 2026-11-24): the person's own Likes tab — a page that holds only that list. Files under the
    # X archive's like.js origin and label, so a like the archive brought in and the same like read here are one row;
    # a post already kept from Bookmarks gains "Likes" on its page's `collections:` instead of a second page. Off until
    # the person turns it on. Reposts are mixed into the profile timeline, which no list page covers: not read.
    # Measured 2026-11-24: History's Likes tab is ``/i/history/likes``, a page of its own; the profile's Likes tab is
    # the way in where that address does not open.
    "x-likes": Platform("x-likes", "X", "Likes", "https://x.com/i/history/likes",
                        " (History, Likes tab; if that address does not open, the person's own profile, then its Likes "
                        "tab: the page that holds only their likes)",
                        "x-likes", "Likes", "x.com", "to read your likes", ("x.com", "twitter.com"), base="x"),
    "instagram": Platform("instagram", "Instagram", "Saved", "https://www.instagram.com/",
                          " — open the person's profile, then Saved, then All posts", "instagram-saved", "Saved",
                          "instagram.com", "to read your saved posts", ("instagram.com",), folders=True,
                          reads="its author as the page shows it, and the words the post shows (a grid of pictures "
                                "shows none: send the link and author only)"),
    # G245: the posts the person liked, from Your activity — under the export's own origin and label
    # (`liked_posts.json`: `instagram-saved`, "Liked posts"), index-only like every Instagram save.
    "instagram-likes": Platform("instagram-likes", "Instagram", "Likes",
                                "https://www.instagram.com/your_activity/interactions/likes/",
                                " — if it does not open, open Your activity, then Interactions, then Likes",
                                "instagram-saved", "Liked posts", "instagram.com", "to read your likes",
                                ("instagram.com",), base="instagram",
                                reads="its author as the page shows it, and the words the post shows (a grid of "
                                      "pictures shows none: send the link and author only)"),
    # Measured 2026-11-24 on a list of 76: five results showed no link to their post at all (only the author's
    # profile), so a read by links alone lost them; each result still names its post in its own urn.
    "linkedin": Platform("linkedin", "LinkedIn", "Saved posts", "https://www.linkedin.com/my-items/saved-posts/", "",
                         "linkedin-saved", "Saved Items", "linkedin.com", "to read your saved posts", ("linkedin.com",),
                         reads="its author as the page shows it, and the words the post shows (a result that shows no "
                               "link to its post still names it in its own `data-chameleon-result-urn`, "
                               "`urn:li:activity:<number>`: its link is then "
                               "`https://www.linkedin.com/feed/update/<that urn>/`)"),
    # G245 (ruling 78 (c), owner 2026-11-24: "who i have connected with and in chronological order which to me is super
    # important"): the person's connections, read from the connections page (sorted by recently added) into the people
    # directory OUTSIDE every bank (`linkedin_people.record_read`) — never a save, never a page, never a model's read, so
    # no origin and no folder label. It shares LinkedIn's address rules, handle, profile link and pause; off until turned on.
    "linkedin-connections": Platform(
        "linkedin-connections", "LinkedIn", "Connections", "https://www.linkedin.com/mynetwork/invite-connect/connections/",
        " (sorted by Recently added)", "", "", "linkedin.com", "to read your connections", ("linkedin.com",),
        base="linkedin"),
    # G232 (owner 2026-11-04: "offer the website connection through browser harness, just like a toggle switch …
    # Same for TikTok, same for Pinterest, same for Reddit"). Each files under its export's own origin and folder, so
    # a post the export (or Reddit's connector) brought in is the same row, and every one is index-only (ruling 30).
    # ROR-128 (owner 2026-11-06) lifted Spotify's "never": a site's terms do not decide whether the person's own agent
    # reads their own list in their own browser. Spotify's library is a saved list like the rest; Goodreads' shelves
    # are books, held for the person's choice (`goodreads_waiting`) instead of saved as links.
    "reddit": Platform("reddit", "Reddit", "Saved", "https://www.reddit.com/user/me/saved/", "", "reddit-saved",
                       "Saved posts", "reddit.com", "to read your saved posts", ("reddit.com",)),
    # G245: the posts and comments the person upvoted — the export's `post_votes.csv` label on its own origin
    # (`history_index.LIST_FOLDERS` makes it index-only). Reddit has no folders.
    "reddit-upvoted": Platform("reddit-upvoted", "Reddit", "Upvoted", "https://www.reddit.com/user/me/upvoted/", "",
                               "reddit-saved", "Upvoted", "reddit.com", "to read your upvoted posts",
                               ("reddit.com",), base="reddit"),
    "pinterest": Platform("pinterest", "Pinterest", "Saved Pins", "https://www.pinterest.com/",
                          " — open the person's profile, then Saved, then All Pins", "pinterest-saved", "Saved",
                          "pinterest.com", "to read your saved Pins", ("pinterest.com",)),
    "tiktok": Platform("tiktok", "TikTok", "Favorites", "https://www.tiktok.com/",
                       " — open the person's profile, then the Favorites tab (videos)", "tiktok-saved", "Favorites",
                       "tiktok.com", "to read your favorite videos", ("tiktok.com",)),
    "spotify": Platform("spotify", "Spotify", "Library", "https://open.spotify.com/",
                        " — open Your Library, then Liked Songs, then each playlist, album and podcast listed",
                        "spotify-saved", "Library", "spotify.com", "to read your library", ("spotify.com",)),
    "goodreads": Platform("goodreads", "Goodreads", "shelves", "https://www.goodreads.com/review/list", "",
                          "goodreads", "", "goodreads.com", "to read your shelves", ("goodreads.com",)),
}
#: A list is offered again this long after its last read (the youtube lists' cadence).
CADENCE = timedelta(hours=20)
#: ``needs_login`` / ``blocked`` pause that site's list this long (the reading queue's own week).
PAUSE = timedelta(days=7)
PAUSING = ("needs_login", "blocked")
OUTCOMES = ("read", "needs_login", "blocked", "failed")
#: Recorded reads a UTC day per bank, across the three sites (G206: the LinkedIn profile read's bound until measured).
DAILY_READS = 10
#: G245: one *read* of a list is a pass — its All page, then up to :data:`FOLDERS_PER_PASS` folders — recorded in as many
#: calls as it takes (the agent sets ``continues`` on each after the first). The whole pass counts once against
#: :data:`DAILY_READS`: a call that continues an open pass is not counted again. A pass stays open this long after its
#: last call, and for at most :data:`PASS_CALLS` calls, so ``continues`` cannot be a way round the bound.
PASS_WINDOW = timedelta(hours=3)
PASS_CALLS = 20
#: Ruling 78 as amended 2026-11-24 (owner: "check also we capture all my saved x posts and linkedin posts at first
#: correctly"; measured that night on a real list of 377 posts: its end was about 190 screens down, so twenty screens
#: kept one post in ten and nothing ever fetched the rest). **A list is read to its end once**: until a read says it
#: reached the end (``reached_end``, kept as ``whole``), every read of the list is asked to go all the way, known posts
#: are no reason to stop, and its pass may take this many calls (200 posts each). After that a read only looks for what
#: is new. Still one pass, one read against the day.
WHOLE_PASS_CALLS = 500
#: The folders (X bookmark folders, Instagram collections) one read opens after the All page, least recently read first
#: (``folder_pass``).
FOLDERS_PER_PASS = folder_pass.FOLDERS_PER_PASS
#: How far a read scrolls and when it has caught up (``folder_pass``): the first read of a list goes deeper to catch up;
#: a later one stops at what is already kept (the record's reply says when it has). Older items still come with the
#: site's export.
FIRST_READ_SCREENS = folder_pass.FIRST_READ_SCREENS
LATER_READ_SCREENS = folder_pass.LATER_READ_SCREENS
FOLDER_SCREENS = folder_pass.FOLDER_SCREENS
KNOWN_RUN = folder_pass.KNOWN_RUN


def path() -> Path:
    return cicada_home() / FILENAME


def base_of(key: str) -> str:
    """The key whose site ``key`` shares (``x`` for ``x-likes``), or ``key`` itself for a site's first list."""
    platform = PLATFORMS.get(key)
    return (platform.base if platform is not None else "") or key


def siblings(key: str) -> list[str]:
    """Every key of ``key``'s site, its base first."""
    base = base_of(key)
    return [k for k in PLATFORMS if base_of(k) == base]


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)


def _parse(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".saved-lists-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextmanager
def _locked() -> Iterator[dict]:
    """Read-modify-write under an ``flock`` on a sidecar lock file (two processes write this file)."""
    lock = path().with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            data = _load()
            yield data
            _save(data)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _bank_key(memory_path: Path) -> str:
    return Path(memory_path).name[:64]


def mtime() -> float:
    try:
        return path().stat().st_mtime
    except OSError:
        return 0.0


# --- what is allowed, paused and due -------------------------------------------------------------


def allowed(key: str) -> bool:
    """Does the person's switch for this site's list count right now? Off whenever agent reading is off."""
    return key in PLATFORMS and reading_settings.saved_list_allowed(key)


def pause_key(key: str) -> str:
    """The key a list's pause is kept under: its site's (:func:`base_of`). A login wall on a site pauses every list of
    it, and a read of any one proves the sign-in for all; a list with no ``base`` is its own."""
    return base_of(key)


def paused_until(key: str, now: datetime | None = None) -> datetime | None:
    """When ``key``'s pause ends. The pause is the site's: a login wall met on X likes pauses X bookmarks too, and only
    "I signed in" / Try again lifts it (G245: one rule for every list of a site, stored under the site's first key)."""
    until = _parse((_load().get("paused_until") or {}).get(pause_key(key)))
    return until if until is not None and until > _now(now) else None


def last(memory_path: Path, key: str) -> dict:
    banks = (_load().get("banks") or {}).get(_bank_key(memory_path)) or {}
    entry = banks.get(key)
    entry = dict(entry) if isinstance(entry, dict) else {}
    for sibling in siblings(key):
        # Every list of a site is the same person (ROR-114): the handle and profile link one of them recorded show on
        # all. Read, never written to another list's entry, so a list never looks read for want of a read.
        held = banks.get(sibling) if sibling != key else None
        if isinstance(held, dict):
            for who in ("handle", "profile_url"):
                if held.get(who) and not entry.get(who):
                    entry[who] = held[who]
    return entry


def reads_today(memory_path: Path, now: datetime | None = None) -> int:
    day = ((_load().get("days") or {}).get(_bank_key(memory_path)) or {})
    return int(day.get(_now(now).date().isoformat()) or 0) if isinstance(day, dict) else 0


def due(memory_path: Path, now: datetime | None = None) -> list[str]:
    """The site whose list to offer the person's agent now — at most one (G206: one site's list at a time): allowed, not
    paused, and the day's reads not spent. A list the person asked to check (:func:`request_check`) goes first, whatever
    its cadence (the oldest request first); then the list read longest ago, a list never read before any (G245: the first
    key in table order no longer always wins, so a later list is not starved). Ties keep table order. A check never lifts
    a pause, and never goes past :data:`DAILY_READS`."""
    if reads_today(memory_path, now) >= DAILY_READS:
        return []
    moment = _now(now)
    floor = datetime.min.replace(tzinfo=timezone.utc)
    ranked = []
    for order, key in enumerate(PLATFORMS):
        if not allowed(key) or paused_until(key, now) is not None:
            continue
        entry = last(memory_path, key)
        at = _parse(entry.get("read_at"))
        asked = _parse(entry.get("check_requested_at"))
        if asked is None and at is not None and moment - at < CADENCE:
            continue
        ranked.append((0 if asked is not None else 1, asked or at or floor, order, key))
    return [min(ranked)[3]] if ranked else []


def request_check(memory_path: Path, key: str, now: datetime | None = None) -> bool:
    """The person asked to check this list now (G245, ``POST /sources/streams/check``): stamp it so :func:`due` offers it
    first. Cicada opens no browser, so this is all a check can do for a list the person's own agent reads. Stamps only a
    list that is on and not paused — a pause is lifted only by the person's "I signed in" or Try again — and says whether
    it did. The next recorded attempt clears the stamp."""
    if not allowed(key) or paused_until(key, now) is not None:
        return False
    with _locked() as data:
        entry = data.setdefault("banks", {}).setdefault(_bank_key(memory_path), {}).setdefault(key, {})
        entry["check_requested_at"] = _now(now).isoformat()
    return True


def check_requested_at(memory_path: Path, key: str) -> str | None:
    return last(memory_path, key).get("check_requested_at") or None


def state_of(outcome) -> str:
    """Where a list stands, from its last attempt alone: ``read`` is the only healthy one, ``signed_out`` the agent met
    a login wall, ``couldnt_read`` it was blocked or failed, ``not_read`` no attempt yet. Cicada learns this only when
    an agent tries the page, and never reads a cookie."""
    return {"read": "read", "needs_login": "signed_out", "blocked": "couldnt_read",
            "failed": "couldnt_read"}.get(str(outcome or ""), "not_read")


def status(memory_path: Path, now: datetime | None = None) -> dict:
    """The Sources page's view: per site, the last read and its outcome, and its pause, if any."""
    lists = {}
    for key in PLATFORMS:
        entry = last(memory_path, key)
        until = paused_until(key, now)
        lists[key] = {"lastReadAt": entry.get("read_at"), "lastOutcome": entry.get("outcome"),
                      "lastAt": entry.get("at"), "items": int(entry.get("items") or 0),
                      "pausedUntil": until.isoformat() if until else None,
                      # ROR-114: how it is read (the app draws a browser-read source in its own colour), where it
                      # stands (only a last read that succeeded is healthy), and whose list it is.
                      "through": "browser",
                      # A pausing outcome whose pause is lifted (Try again, or the week is up) waits for its next read.
                      "state": "not_read" if entry.get("outcome") in PAUSING and until is None
                      else state_of(entry.get("outcome")),
                      "handle": entry.get("handle") or None, "profileUrl": entry.get("profile_url") or None}
    return {"readsToday": reads_today(memory_path, now), "dailyReads": DAILY_READS, "lists": lists}


# --- what the agent reported ------------------------------------------------------------------------


_HANDLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,38}")


def clean_handle(value) -> str | None:
    """The person's handle on the site as the page shows it, without its leading ``@``: one short token, or ``None``."""
    word = str(value or "").strip().lstrip("@")
    return word if _HANDLE.fullmatch(word) else None


def clean_profile_url(key: str, value) -> str | None:
    """The link to the person's own profile: ``https`` only, no credentials or port, on that platform's own host, the
    query and fragment dropped. ``None`` for anything else (a link is shown and opened on a click, so it is checked)."""
    try:
        parsed = urlparse(str(value or "").strip())
        port = parsed.port
    except ValueError:
        return None
    platform = PLATFORMS.get(key)
    host = (parsed.hostname or "").lower()
    if platform is None or parsed.scheme != "https" or parsed.username or parsed.password or port is not None:
        return None
    ok = bool(_PIN_HOST.fullmatch(host)) if key == "pinterest" else _host_in(host, platform.profile_hosts)
    if not ok or len(parsed.path) < 2 or len(parsed.path) > 200 or any(c.isspace() or ord(c) < 32 for c in parsed.path):
        return None
    return f"https://{host}{parsed.path}"


def whole(memory_path: Path, key: str) -> bool:
    """Has a read of ``key``'s list reached its end (:data:`WHOLE_PASS_CALLS`)? Until one has, the list is not all in
    memory and the next read is asked to go to the end."""
    return last(memory_path, key).get("whole") is True


def pass_calls(memory_path: Path, key: str) -> int:
    """The calls one pass of ``key``'s list may take: far more while the list has not been read to its end."""
    return PASS_CALLS if whole(memory_path, key) else WHOLE_PASS_CALLS


def pass_open(memory_path: Path, key: str, now: datetime | None = None) -> bool:
    """Is a pass of ``key``'s list open — a read whose first call was counted, whose last was within
    :data:`PASS_WINDOW`, with calls to spare? Only such a pass can be continued (G245)."""
    entry = last(memory_path, key)
    return _pass_open(entry.get("pass"), _now(now), entry.get("whole") is True)


def _pass_open(held, moment: datetime, is_whole: bool = True) -> bool:
    if not isinstance(held, dict):
        return False
    at = _parse(held.get("at"))
    calls = PASS_CALLS if is_whole else WHOLE_PASS_CALLS
    return at is not None and moment - at < PASS_WINDOW and int(held.get("calls") or 0) < calls


def note(memory_path: Path, key: str, outcome: str, *, items: int = 0, handle: str | None = None,
         profile_url: str | None = None, continues: bool = False, reached_end: bool = False,
         now: datetime | None = None) -> bool:
    """Record an outcome. A read counts toward the day and clears that site's pause (the agent was signed in);
    ``needs_login``/``blocked`` start one. ``handle`` and ``profile_url`` (already cleaned) are kept beside it, in this
    machine state and never a bank; one not given leaves the last one standing.

    ``continues`` (G245): this read carries on an open pass of the same list (:func:`pass_open`) — it adds to the pass's
    items and is **not** counted again. With no open pass it is a new read, counted like any. Returns whether the call
    was counted against the day.

    ``reached_end``: this read got to the end of the list (the page stopped growing), so the whole list is in memory
    from now on (:func:`whole`); kept until the list's entry is gone."""
    moment = _now(now)
    counted = False
    with _locked() as data:
        bank = _bank_key(memory_path)
        banks = data.setdefault("banks", {}).setdefault(bank, {})
        entry = banks.setdefault(key, {})
        entry.update(at=moment.isoformat(), outcome=outcome)
        entry.pop("check_requested_at", None)   # an attempt, whatever its outcome, answers a requested check
        if handle:
            entry["handle"] = handle
        if profile_url:
            entry["profile_url"] = profile_url
        base = pause_key(key)
        pauses = data.setdefault("paused_until", {})
        if outcome == "read":
            held_pass = entry.get("pass")
            if continues and _pass_open(held_pass, moment, entry.get("whole") is True):
                entry["pass"] = {"at": moment.isoformat(), "calls": int(held_pass.get("calls") or 0) + 1}
                items = int(entry.get("items") or 0) + int(items)
            else:
                entry["pass"] = {"at": moment.isoformat(), "calls": 1}
                _count(data, bank, moment)
                counted = True
            entry.update(read_at=moment.isoformat(), items=int(items))
            if reached_end:
                entry["whole"] = True
            pauses.pop(base, None)
        elif outcome in PAUSING:
            pauses[base] = (moment + PAUSE).isoformat()
            entry.pop("pass", None)
        if not pauses:
            data.pop("paused_until", None)
    return counted


def note_folders(memory_path: Path, key: str, names: list[str]) -> None:
    """The folders the site listed on the All page (``names``, cleaned; empty for a site or account with none): how many
    there are, kept as a count. Nothing else of them is kept here."""
    with _locked() as data:
        entry = data.setdefault("banks", {}).setdefault(_bank_key(memory_path), {}).setdefault(key, {})
        entry["folder_count"] = len(names)


def folder_count(memory_path: Path, key: str) -> int:
    """How many folders the site last listed for this list; 0 when it showed none or was never asked."""
    return int(last(memory_path, key).get("folder_count") or 0)


def next_folders(memory_path: Path, names: list[str], key: str) -> list[str]:
    """The folders to open after the All page: at most :data:`FOLDERS_PER_PASS` of ``names``, the ones never read first
    (in the order the site listed them), then the least recently read."""
    return folder_pass.order(names, last(memory_path, key).get("folder_reads"))


def stamp_folder(memory_path: Path, key: str, name: str, now: datetime | None = None) -> None:
    """One folder's own page was read now (the order :func:`next_folders` rotates by). Only a hash is kept."""
    with _locked() as data:
        entry = data.setdefault("banks", {}).setdefault(_bank_key(memory_path), {}).setdefault(key, {})
        entry["folder_reads"] = folder_pass.stamped(entry.get("folder_reads"), name, _now(now).isoformat())


def _count(data: dict, bank: str, moment: datetime) -> None:
    today = moment.date().isoformat()
    # Only today's count is kept: the bound is a day's, and older days are never read.
    days = data.setdefault("days", {})
    days[bank] = {today: int((days.get(bank) or {}).get(today) or 0) + 1}


def count_read(memory_path: Path, now: datetime | None = None) -> None:
    """A saved list kept elsewhere was read (Substack's, ``substack_lists``, G89): it spends the same day's bound —
    :data:`DAILY_READS` across every walled site's list, one site at a time."""
    with _locked() as data:
        _count(data, _bank_key(memory_path), _now(now))


def resume(keys) -> None:
    """The person turned a list on again: lift its pause (their Try again)."""
    if not path().exists():
        return
    with _locked() as data:
        pauses = data.get("paused_until") or {}
        for key in keys:
            pauses.pop(pause_key(key), None)
        if not pauses:
            data.pop("paused_until", None)


def resume_site(site: str) -> None:
    """The person tapped "I signed in" on an agent request for one of these sites (G205): lift that list's pause."""
    resume([k for k, p in PLATFORMS.items() if p.site == str(site or "").lower().removeprefix("www.")])


# --- one saved item ---------------------------------------------------------------------------------

_X_HOSTS = ("x.com", "twitter.com")
_X_STATUS = re.compile(r"^/(?:(?P<user>[A-Za-z0-9_]{1,15})|i(?:/web)?)/status/(?P<id>\d{1,25})(?:/|$)")
_X_RESERVED = frozenset({"i", "home", "search", "explore", "settings", "messages", "notifications"})
_IG_POST = re.compile(r"^/(?:[A-Za-z0-9._]{1,30}/)?(?P<kind>p|reel|tv)/(?P<code>[A-Za-z0-9_-]{5,64})(?:/|$)")
#: A saved article is listed with the other saved posts, as ``urn:li:article`` (measured 2026-11-24: one in 76).
_LI_POST = re.compile(r"^/(?:feed/update/urn:li:(?:activity|share|ugcPost|article):\d{5,25}|posts/[^/?#\s]{3,300})(?:/|$)")
#: A post or a comment on Reddit: ``/r/<sub>/comments/<id>[/<slug>[/<comment id>]]``.
_REDDIT_POST = re.compile(r"^/r/(?P<sub>[A-Za-z0-9_]{2,21})/comments/(?P<id>[a-z0-9]{3,12})"
                          r"(?:/(?P<slug>[^/?#\s]{1,120})(?:/(?P<comment>[a-z0-9]{3,12}))?)?/?$")
#: A Pin: ``/pin/<id>/`` on pinterest.com or one of its country hosts.
_PIN = re.compile(r"^/pin/(?P<id>[A-Za-z0-9_-]{5,40})/?$")
_PIN_HOST = re.compile(r"(?:(?:www|[a-z]{2})\.)?pinterest\.(?:com|[a-z]{2}|co\.[a-z]{2}|com\.[a-z]{2})")
#: A Spotify item: ``/<kind>/<id>`` on open.spotify.com (a locale prefix such as ``/intl-es`` is dropped).
_SPOTIFY = re.compile(r"^(?:/intl-[a-z]{2}(?:-[A-Za-z]{2})?)?/(?P<kind>track|album|show|episode|playlist|artist)/"
                      r"(?P<id>[A-Za-z0-9]{8,40})/?$")
#: A video or photo post on TikTok: ``/@<user>/video/<id>``.
_TIKTOK_POST = re.compile(r"^/@(?P<user>[A-Za-z0-9._]{2,24})/(?P<kind>video|photo)/(?P<id>\d{8,25})/?$")


def _host_in(host: str, domains) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def canonical(key: str, url) -> tuple[str, tuple[str, ...]] | None:
    """``(url, aliases)`` for one saved item of ``key``'s list, or ``None`` when the link is not a post of that site
    (a profile, a search, another site). The aliases are the other spellings the same post is saved under by another
    door (an archive, a connector, a pasted link), so it is one row in ``url_index``, never two."""
    try:
        parsed = urlparse(str(url or "").strip())
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    key = base_of(key)   # a second list of a site (X likes) holds the site's own posts: one address rule
    host = (parsed.hostname or "").lower()
    path_ = parsed.path or "/"
    if key == "x":
        found = _X_STATUS.match(path_) if _host_in(host, _X_HOSTS) else None
        if found is None:
            return None
        user, sid = found.group("user"), found.group("id")
        generic = f"https://x.com/i/web/status/{sid}"
        if not user or user.lower() in _X_RESERVED:
            return generic, (f"https://twitter.com/i/web/status/{sid}",)
        return (f"https://x.com/{user}/status/{sid}",
                (generic, f"https://twitter.com/{user}/status/{sid}", f"https://twitter.com/i/web/status/{sid}"))
    if key == "instagram":
        found = _IG_POST.match(path_) if _host_in(host, ("instagram.com",)) else None
        if found is None:
            return None
        kind, code = found.group("kind"), found.group("code")
        tail = f"/{kind}/{code}/"
        # One post answers at ``/p/``, ``/reel/`` and ``/tv/``: a save noticed in the browser (G221) names it by the
        # first, a list read by whichever the list shows, and they are one row.
        others = tuple(f"https://{host}/{other}/{code}/" for other in ("p", "reel", "tv") if other != kind
                       for host in ("www.instagram.com", "instagram.com"))
        return f"https://www.instagram.com{tail}", (f"https://instagram.com{tail}", *others)
    if key == "linkedin":
        found = _LI_POST.match(path_) if _host_in(host, ("linkedin.com",)) else None
        if found is None:
            return None
        tail = found.group(0).rstrip("/") + "/"
        return f"https://www.linkedin.com{tail}", (f"https://linkedin.com{tail}",)
    if key == "reddit":
        found = _REDDIT_POST.match(path_) if _host_in(host, ("reddit.com",)) else None
        if found is None:
            return None
        tail = "/" + "/".join(p for p in (f"r/{found.group('sub')}", "comments", found.group("id"), found.group("slug"),
                                          found.group("comment")) if p) + "/"
        # The export's permalink is ``www.reddit.com``; old Reddit and the bare host are the same post.
        return f"https://www.reddit.com{tail}", (f"https://old.reddit.com{tail}", f"https://reddit.com{tail}")
    if key == "pinterest":
        found = _PIN.match(path_) if _PIN_HOST.fullmatch(host) else None
        if found is None:
            return None
        pin = found.group("id")
        return f"https://www.pinterest.com/pin/{pin}/", (f"https://pinterest.com/pin/{pin}/",)
    if key == "tiktok":
        found = _TIKTOK_POST.match(path_) if _host_in(host, ("tiktok.com",)) else None
        if found is None:
            return None
        user, kind, vid = found.group("user"), found.group("kind"), found.group("id")
        # The export lists a favourite as ``tiktokv.com/share/video/<id>/``: the same video, one row.
        return f"https://www.tiktok.com/@{user}/{kind}/{vid}", (f"https://www.tiktokv.com/share/video/{vid}/",
                                                                 f"https://tiktok.com/@{user}/{kind}/{vid}")
    if key == "spotify":
        found = _SPOTIFY.match(path_) if host == "open.spotify.com" else None
        if found is None:
            return None
        return f"https://open.spotify.com/{found.group('kind')}/{found.group('id')}", ()
    return None


# --- the offer ------------------------------------------------------------------------------------


def screens_words(memory_path: Path, key: str) -> str:
    """How far this read goes, in the words the agent gets (G245): the first read of a list catches up; a later one stops
    where the list reaches what is already kept."""
    if not whole(memory_path, key):
        return ("This list has not been read to its end yet, so read all of it this time: keep scrolling until the list "
                "stops growing (a few more tries bring no new post), however long it is, recording as you go in calls "
                "of up to 200 posts, newest first. Posts already in memory are no reason to stop this time. On the last "
                "call set `reached_end=true`; if you have to stop before the end, leave it out and the next read "
                "carries on.")
    return (f"Scroll only until you reach posts already in memory, and at most {LATER_READ_SCREENS} screens: the reply to "
            "each call says when you have reached them. Record as you go, newest first.")


def queue_lines(memory_path: Path, *, can_record: bool, now: datetime | None = None) -> list[str]:
    """The reading queue's lines for the list that is due — empty when none is (or agent reading is off)."""
    keys = due(memory_path, now)
    if not keys:
        return []
    p = PLATFORMS[keys[0]]
    if p.key == "goodreads":
        return _goodreads_lines(can_record)
    if p.key == "linkedin-connections":
        return _connections_lines(memory_path, can_record)
    lines = [f"- The person's {p.name} {p.label}: {p.url}{p.how} — read each post's link, {p.reads}."]
    lines.append(f"{screens_words(memory_path, p.key)} Add `posted` (YYYY-MM-DD) to a row only when the page shows the "
                 "post's own date as a day; leave it out for \"3 days ago\" or nothing.")
    if p.folders:
        lines.append(
            f"If {p.name} lets the person keep these posts in folders ({'bookmark folders' if p.key == 'x' else 'collections'}), "
            f"each folder is its own page: after the All page, send the folders' names as `folder_names` (an empty list "
            f"when there are none, which is common), and the reply names the {FOLDERS_PER_PASS} at most to open next. "
            "Open each and record it with `folder=\"<its name>\"` and `continues=true` (scroll at most "
            f"{FOLDER_SCREENS} screens; its posts need no `folders`). One read of this list, all its calls together, "
            "counts once.")
    tail = (f"Record it with `cicada_record_saved_list(platform, outcome, items=[{{url, author, text, posted}}], via)` "
            f"(platform `{p.key}`); when a read takes more than one call, set `continues=true` on every call after the "
            f"first. If {p.name} asks you to sign in, do not sign in or type credentials: record "
            "`needs_login` and stop."
            if can_record else
            f"If {p.name} asks you to sign in, do not sign in or type credentials: stop and tell the person.")
    return [f"The person asked their agent to keep their {p.name} {_what(p)} current in Cicada. Open this list in "
            "their own signed-in browser session; read only the list, never their "
            "feed, timeline or messages, and never click anything that changes the list (no unsave, like, follow or "
            "reply)."] + lines + [tail]


def _what(p: Platform) -> str:
    """What the list is called in a sentence: the saved posts of a site's first list, the list's own name for a second."""
    return f"{p.label.lower()}" if p.base else "saved posts"


def _connections_lines(memory_path: Path, can_record: bool) -> list[str]:
    """LinkedIn's connections page: who the person connected with, and when (G245, ruling 78 (c)). People, not posts —
    kept outside every bank in the people directory, never read by a model."""
    p = PLATFORMS["linkedin-connections"]
    tail = ("Record it with `cicada_record_saved_list(platform=\"linkedin-connections\", outcome, items=[{name, "
            "profile_url, headline, connected}], via)`: `profile_url` is the member's own `/in/` link (a row with none is "
            "left out), `headline` the line under the name as shown, `connected` the date the page shows for that row — "
            "give an exact day as YYYY-MM-DD, otherwise the page's own words (\"3 weeks ago\"), never a guess. When a read "
            "takes more than one call, set `continues=true` on every call after the first. If LinkedIn asks you to sign "
            "in, do not sign in or type credentials: record `needs_login` and stop."
            if can_record else
            "If LinkedIn asks you to sign in, do not sign in or type credentials: stop and tell the person.")
    return ["The person asked their agent to keep who they are connected with current in Cicada. Open this page in their "
            "own signed-in browser session: read only the connections list, never a profile, the contact info overlay, "
            "their feed or messages, and never click anything that changes a connection (no message, remove or follow).",
            f"- The person's LinkedIn connections: {p.url}{p.how} — per row: the person's name, their profile link, the "
            "headline under the name, and when you connected as the page shows it.",
            screens_words(memory_path, p.key) + " Rows already kept are no reason to stop on a first read.", tail]


def _goodreads_lines(can_record: bool) -> list[str]:
    """Goodreads' shelves are books, not posts: what to read per book, and where it goes (held for the person's pick)."""
    p = PLATFORMS["goodreads"]
    tail = ("Record it with `cicada_record_saved_list(platform=\"goodreads\", outcome, items=[{id, title, author, shelf, "
            "rating, date_read, date_added, review}], via)`: `id` is the number in the book's link "
            "(`/book/show/<id>`), `shelf` is `read`, `currently-reading` or `to-read`, dates are YYYY-MM-DD. Nothing "
            "enters memory until the person chooses which books to add. If Goodreads asks you to sign in, do not sign "
            "in or type credentials: record `needs_login` and stop."
            if can_record else
            "If Goodreads asks you to sign in, do not sign in or type credentials: stop and tell the person.")
    return ["The person asked their agent to keep their Goodreads shelves current in Cicada. Open this page in their "
            "own signed-in browser session; read only their shelves Read, Currently Reading and Want to Read (scroll "
            "at most a few screens), never their feed, friends or messages, and never click anything that changes a "
            "shelf (no rating, review, shelving or follow).",
            f"- The person's Goodreads shelves: {p.url} — per book: its id, title, author, which shelf, the person's "
            "own star rating, the dates read and added, and the person's own review if they wrote one.", tail]
