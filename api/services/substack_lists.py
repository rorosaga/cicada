"""The person's own agent keeps their Substack current — saved posts, reading history and subscriptions (G89, owner
2026-11-04: "a direct app integration is best to see history of read stuff, saved stuff, etc.").

**Why the agent, not a connection (researched 2026-11-04, G89).** Substack offers a reader no API and no OAuth app
programme (its OAuth server serves its own MCP connector, which is publisher analytics for an admin of a Bestseller
publication and "cannot access profile data or Notes activity"), no reader data export (Exports are a publisher's;
a reader can only email a privacy request), and no Mac app whose store the app could read (iPhone, iPad, Apple TV and
Vision Pro only). Its terms forbid crawling or scraping by manual or automated means, and the reader's own pages are
behind sign-in — so the backend never fetches one (the ToS rail). What is left inside the rails is G166's: the person's
own agent, in their own signed-in browser, on their standing ask, reading three pages of their own reader:

* **Saved** (``https://substack.com/inbox`` → Saved) — each post an indexed save (ruling 30), origin ``substack-saved``,
  folder ``Saved``, never read by a model; dedup by URL, so a post a followed feed already brought in is one row.
* **History** (``https://substack.com/home`` → History) — what the person read, as reading days
  (``substack_reads``): one index-only episode per day, never a save, never a mention.
* **Subscriptions** (the account menu → Subscriptions) — each publication followed through its own public feed
  (``feed_registry``, tag ``substack``), which the feed gate polls; a publication the person unsubscribed from in
  Cicada is never followed again by this read.

**Consent.** Agent reading on (its sheet acknowledged) AND the person turned that list on (``reading_settings
.substack_lists``) — off until they do: Substack is an account Cicada cannot see in memory, so no default could tell
it applies (owner 2026-10-26's on-by-default is for accounts the memory shows). Each switch is a standing ask for
exactly that page, never a site grant.

**Bounds** (G206's, shared): a list is offered only when no X, Instagram or LinkedIn list is due (one site's list at a
time), at most one Substack list at a time, and every recorded read spends the same :data:`saved_lists.DAILY_READS` a
day per bank. ``needs_login``/``blocked`` pause all three for a week (one sign-in covers them); turning a list on
again lifts it.

State here is the offer only — when each list was last read for each bank and the pause. One small file outside every
bank (``$CICADA_HOME/substack_lists.json``, 0600, atomic, ``flock``ed). Ids, enums, counts and times only.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from api.services import reading_settings, saved_lists
from api.services.auth import cicada_home

FILENAME = "substack_lists.json"
SITE = "substack.com"
NAME = "Substack"
ORIGIN_SAVED = "substack-saved"
FOLDER_SAVED = "Saved"
#: The tag every feed this read follows carries (the Sources page's Substack entry lists them by it).
FEED_TAG = "substack"
FEED_VIA = "substack-subscriptions"


@dataclass(frozen=True)
class SubstackList:
    key: str
    label: str
    url: str
    how: str
    #: What the agent reads of each row.
    reads: str
    #: The ``items`` shape the tool takes.
    shape: str
    cadence: timedelta


LISTS: dict[str, SubstackList] = {
    "saved": SubstackList(
        "saved", "Saved", "https://substack.com/inbox", " — open Saved",
        "each post's link, its title, its author and its publication as the list shows them",
        "{url, title, author, publication}", timedelta(hours=20)),
    "history": SubstackList(
        "history", "History", "https://substack.com/home",
        " — open History (the clock icon at the top of the page)",
        "each post's link, its title, its author and its publication, and the day it was read when the page shows one",
        "{url, title, author, publication, read_on}", timedelta(hours=20)),
    # A list that changes rarely: read once a week.
    "subscriptions": SubstackList(
        "subscriptions", "Subscriptions", "https://substack.com/home",
        " — open the account menu (top right), then Subscriptions",
        "each publication's name and the link to its home page",
        "{url, name}", timedelta(days=7)),
}
PAUSE = saved_lists.PAUSE
PAUSING = saved_lists.PAUSING
OUTCOMES = saved_lists.OUTCOMES
#: The site-wide pause key: one sign-in covers every list.
_PAUSE_KEY = "substack"


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
    fd, tmp = tempfile.mkstemp(prefix=".substack-lists-", suffix=".tmp", dir=str(target.parent))
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
    """Read-modify-write under an ``flock`` on a sidecar lock file (the backend and every stdio server write it)."""
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


def allowed(name: str) -> bool:
    """Does the person's switch for this list count right now? Off whenever agent reading is off."""
    return name in LISTS and reading_settings.substack_list_allowed(name)


def paused_until(now: datetime | None = None) -> datetime | None:
    until = _parse((_load().get("paused_until") or {}).get(_PAUSE_KEY))
    return until if until is not None and until > _now(now) else None


def last(memory_path: Path, name: str) -> dict:
    entry = ((_load().get("banks") or {}).get(_bank_key(memory_path)) or {}).get(name)
    return entry if isinstance(entry, dict) else {}


def due(memory_path: Path, now: datetime | None = None) -> list[str]:
    """The Substack list to offer the person's agent now — at most one, and only when no other site's saved list is
    due and the day's shared reads are not spent (G206's bounds)."""
    if saved_lists.reads_today(memory_path, now) >= saved_lists.DAILY_READS or paused_until(now) is not None:
        return []
    if saved_lists.due(memory_path, now):
        return []
    moment = _now(now)
    for name, spec in LISTS.items():
        if not allowed(name):
            continue
        at = _parse(last(memory_path, name).get("read_at"))
        if at is None or moment - at >= spec.cadence:
            return [name]
    return []


def status(memory_path: Path, now: datetime | None = None) -> dict:
    """The Sources page's view: per list, the last read and its outcome; the site's pause."""
    until = paused_until(now)
    lists = {}
    for name in LISTS:
        entry = last(memory_path, name)
        lists[name] = {"lastReadAt": entry.get("read_at"), "lastOutcome": entry.get("outcome"),
                       "lastAt": entry.get("at"), "items": int(entry.get("items") or 0)}
    return {"pausedUntil": until.isoformat() if until else None, "lists": lists}


# --- what the agent reported ------------------------------------------------------------------------


def note(memory_path: Path, name: str, outcome: str, *, items: int = 0, now: datetime | None = None) -> None:
    """Record an outcome. A read spends one of the day's shared reads and lifts the pause (the agent was signed in);
    ``needs_login``/``blocked`` pause every Substack list."""
    moment = _now(now)
    with _locked() as data:
        entry = data.setdefault("banks", {}).setdefault(_bank_key(memory_path), {}).setdefault(name, {})
        entry.update(at=moment.isoformat(), outcome=outcome)
        pauses = data.setdefault("paused_until", {})
        if outcome == "read":
            entry.update(read_at=moment.isoformat(), items=int(items))
            pauses.pop(_PAUSE_KEY, None)
        elif outcome in PAUSING:
            pauses[_PAUSE_KEY] = (moment + PAUSE).isoformat()
        if not pauses:
            data.pop("paused_until", None)
    if outcome == "read":
        saved_lists.count_read(memory_path, now)


def resume() -> None:
    """The person turned a list on again, or said they signed in: lift the pause (their Try again)."""
    if not path().exists():
        return
    with _locked() as data:
        data.pop("paused_until", None)


# --- the offer ------------------------------------------------------------------------------------


def queue_lines(memory_path: Path, *, can_record: bool, now: datetime | None = None) -> list[str]:
    """The reading queue's lines for the Substack list that is due — empty when none is (or agent reading is off)."""
    names = due(memory_path, now)
    if not names:
        return []
    spec = LISTS[names[0]]
    lines = [f"- The person's Substack {spec.label}: {spec.url}{spec.how} — read {spec.reads}."]
    tail = (f"Record it with `cicada_record_substack_list(list, outcome, items=[{spec.shape}], via)` (list "
            f"`{spec.key}`). If Substack asks you to sign in, do not sign in or type credentials: record "
            "`needs_login` and stop."
            if can_record else
            "If Substack asks you to sign in, do not sign in or type credentials: stop and tell the person.")
    return ["The person asked their agent to keep their Substack current in Cicada. Open this page in their own "
            "signed-in browser session; read only this list (scroll at most a few screens), never a post's full text, "
            "their inbox or messages, and never click anything that changes it (no unsave, like, restack, subscribe, "
            "unsubscribe or reply)."] + lines + [tail]
