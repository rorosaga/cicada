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

from api.services import reading_settings
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


PLATFORMS: dict[str, Platform] = {
    "x": Platform("x", "X", "Bookmarks", "https://x.com/i/bookmarks", "", "x-bookmarks", "Bookmarks",
                  "x.com", "to read your bookmarks", ("x.com", "twitter.com")),
    "instagram": Platform("instagram", "Instagram", "Saved", "https://www.instagram.com/",
                          " — open the person's profile, then Saved, then All posts", "instagram-saved", "Saved",
                          "instagram.com", "to read your saved posts", ("instagram.com",)),
    "linkedin": Platform("linkedin", "LinkedIn", "Saved posts", "https://www.linkedin.com/my-items/saved-posts/", "",
                         "linkedin-saved", "Saved Items", "linkedin.com", "to read your saved posts", ("linkedin.com",)),
    # G232 (owner 2026-11-04: "offer the website connection through browser harness, just like a toggle switch …
    # Same for TikTok, same for Pinterest, same for Reddit"). Each files under its export's own origin and folder, so
    # a post the export (or Reddit's connector) brought in is the same row, and every one is index-only (ruling 30).
    # Spotify has none: its terms bar automated reading of the service (`ways_in.SPOTIFY_NO_BROWSER`).
    "reddit": Platform("reddit", "Reddit", "Saved", "https://www.reddit.com/user/me/saved/", "", "reddit-saved",
                       "Saved posts", "reddit.com", "to read your saved posts", ("reddit.com",)),
    "pinterest": Platform("pinterest", "Pinterest", "Saved Pins", "https://www.pinterest.com/",
                          " — open the person's profile, then Saved, then All Pins", "pinterest-saved", "Saved",
                          "pinterest.com", "to read your saved Pins", ("pinterest.com",)),
    "tiktok": Platform("tiktok", "TikTok", "Favorites", "https://www.tiktok.com/",
                       " — open the person's profile, then the Favorites tab (videos)", "tiktok-saved", "Favorites",
                       "tiktok.com", "to read your favorite videos", ("tiktok.com",)),
}
#: A list is offered again this long after its last read (the youtube lists' cadence).
CADENCE = timedelta(hours=20)
#: ``needs_login`` / ``blocked`` pause that site's list this long (the reading queue's own week).
PAUSE = timedelta(days=7)
PAUSING = ("needs_login", "blocked")
OUTCOMES = ("read", "needs_login", "blocked", "failed")
#: Recorded reads a UTC day per bank, across the three sites (G206: the LinkedIn profile read's bound until measured).
DAILY_READS = 10


def path() -> Path:
    return cicada_home() / FILENAME


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


def paused_until(key: str, now: datetime | None = None) -> datetime | None:
    until = _parse((_load().get("paused_until") or {}).get(key))
    return until if until is not None and until > _now(now) else None


def last(memory_path: Path, key: str) -> dict:
    entry = ((_load().get("banks") or {}).get(_bank_key(memory_path)) or {}).get(key)
    return entry if isinstance(entry, dict) else {}


def reads_today(memory_path: Path, now: datetime | None = None) -> int:
    day = ((_load().get("days") or {}).get(_bank_key(memory_path)) or {})
    return int(day.get(_now(now).date().isoformat()) or 0) if isinstance(day, dict) else 0


def due(memory_path: Path, now: datetime | None = None) -> list[str]:
    """The site whose list to offer the person's agent now — at most one (G206: one site's list at a time), in a fixed
    order: allowed, not paused, not read in ``CADENCE``, and the day's reads not spent."""
    if reads_today(memory_path, now) >= DAILY_READS:
        return []
    moment = _now(now)
    for key in PLATFORMS:
        if not allowed(key) or paused_until(key, now) is not None:
            continue
        at = _parse(last(memory_path, key).get("read_at"))
        if at is None or moment - at >= CADENCE:
            return [key]
    return []


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


def note(memory_path: Path, key: str, outcome: str, *, items: int = 0, handle: str | None = None,
         profile_url: str | None = None, now: datetime | None = None) -> None:
    """Record an outcome. A read counts toward the day and clears that site's pause (the agent was signed in);
    ``needs_login``/``blocked`` start one. ``handle`` and ``profile_url`` (already cleaned) are kept beside it, in this
    machine state and never a bank; one not given leaves the last one standing."""
    moment = _now(now)
    with _locked() as data:
        bank = _bank_key(memory_path)
        entry = data.setdefault("banks", {}).setdefault(bank, {}).setdefault(key, {})
        entry.update(at=moment.isoformat(), outcome=outcome)
        if handle:
            entry["handle"] = handle
        if profile_url:
            entry["profile_url"] = profile_url
        pauses = data.setdefault("paused_until", {})
        if outcome == "read":
            entry.update(read_at=moment.isoformat(), items=int(items))
            pauses.pop(key, None)
            _count(data, bank, moment)
        elif outcome in PAUSING:
            pauses[key] = (moment + PAUSE).isoformat()
        if not pauses:
            data.pop("paused_until", None)


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
            pauses.pop(key, None)
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
_LI_POST = re.compile(r"^/(?:feed/update/urn:li:(?:activity|share|ugcPost):\d{5,25}|posts/[^/?#\s]{3,300})(?:/|$)")
#: A post or a comment on Reddit: ``/r/<sub>/comments/<id>[/<slug>[/<comment id>]]``.
_REDDIT_POST = re.compile(r"^/r/(?P<sub>[A-Za-z0-9_]{2,21})/comments/(?P<id>[a-z0-9]{3,12})"
                          r"(?:/(?P<slug>[^/?#\s]{1,120})(?:/(?P<comment>[a-z0-9]{3,12}))?)?/?$")
#: A Pin: ``/pin/<id>/`` on pinterest.com or one of its country hosts.
_PIN = re.compile(r"^/pin/(?P<id>[A-Za-z0-9_-]{5,40})/?$")
_PIN_HOST = re.compile(r"(?:(?:www|[a-z]{2})\.)?pinterest\.(?:com|[a-z]{2}|co\.[a-z]{2}|com\.[a-z]{2})")
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
        tail = f"/{found.group('kind')}/{found.group('code')}/"
        return f"https://www.instagram.com{tail}", (f"https://instagram.com{tail}",)
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
    return None


# --- the offer ------------------------------------------------------------------------------------


def queue_lines(memory_path: Path, *, can_record: bool, now: datetime | None = None) -> list[str]:
    """The reading queue's lines for the list that is due — empty when none is (or agent reading is off)."""
    keys = due(memory_path, now)
    if not keys:
        return []
    p = PLATFORMS[keys[0]]
    lines = [f"- The person's {p.name} {p.label}: {p.url}{p.how} — read each post's link, its author as the page "
             "shows it, and the words the post shows."]
    tail = (f"Record it with `cicada_record_saved_list(platform, outcome, items=[{{url, author, text}}], via)` "
            f"(platform `{p.key}`). If {p.name} asks you to sign in, do not sign in or type credentials: record "
            "`needs_login` and stop."
            if can_record else
            f"If {p.name} asks you to sign in, do not sign in or type credentials: stop and tell the person.")
    return [f"The person asked their agent to keep their saved {p.name} posts current in Cicada. Open this list in "
            "their own signed-in browser session; read only the list (scroll at most a few screens), never their "
            "feed or messages, and never click anything that changes the list (no unsave, like, follow or "
            "reply)."] + lines + [tail]
