"""The person's own agent keeps their YouTube lists current (G71 / G166, owner 2026-10-16).

Owner, 2026-10-16: "the agent being able to go to youtube using the browser to monitor stuff i think its cool, like
for youtube watch later/history". YouTube's API exposes neither list to anyone, and a Takeout is a one-off; the
person's own agent, in their own signed-in browser, can read both pages. This is the third door onto the same record:

* **Watch later** (``https://www.youtube.com/playlist?list=WL``) — saves, written where saved videos go
  (``media_ingestor``: one ``url_index`` row per video, folder ``Watch later``), so a video already saved by Takeout,
  a bookmark or a link is a duplicate, never a second page.
* **Watch history** (``https://www.youtube.com/feed/history``) — experience, aggregated by ``watch_history`` into one
  episode per day; the page shows days, not times, so a row carries the day and merges into the row Chrome's history
  or Takeout wrote for the same video that day.

**The rails are G166's (``mcp.md``, "Reading with the person's own agent").** Cicada never spawns a browser, never
signs in and never fetches either page: it only *offers* the task — one line in ``cicada_reading_queue`` and one in
the recall hook's count — and only while agent reading is on (its first-use sheet acknowledged) **and** the person
turned on this list (``reading_settings.youtube_lists``, on by default since 2026-10-26 — onboarding asks once,
pre-ticked; ``list_defaults`` for an existing install — and an off is remembered; the switch is
a standing ask for exactly that page, never a youtube.com site grant — owner 2026-10-16, CLAUDE.md's rail). The agent records through ``cicada_record_youtube_list`` (``record``
scope, stdio only). ``needs_login`` or ``blocked`` pauses BOTH lists for a week — the agent was not signed in, and it
is never asked again in a loop — until the week ends or the person turns a list on again (Try again).

This module holds only the offer: when each list was last read for each bank, and the pause. One small file outside
every bank (``$CICADA_HOME/youtube_lists.json``, 0600, atomic, ``flock``ed — the backend and every stdio server write
it). Ids, enums, counts and times only; never a title or a URL of the person's.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from api.services import reading_settings
from api.services.auth import cicada_home

FILENAME = "youtube_lists.json"
#: The lists an agent may read, their page and their words.
LISTS: dict[str, dict[str, str]] = {
    "watch_later": {"url": "https://www.youtube.com/playlist?list=WL", "label": "Watch later"},
    "history": {"url": "https://www.youtube.com/feed/history", "label": "watch history"},
}
#: A list is offered again this long after its last read (Watch later changes when the person adds a video; history
#: every day they watch one).
CADENCE = timedelta(hours=20)
#: ``needs_login`` / ``blocked`` pause the lists this long (the reading queue's own week).
PAUSE = timedelta(days=7)
PAUSING = ("needs_login", "blocked")
OUTCOMES = ("read", "needs_login", "blocked", "failed")


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
    fd, tmp = tempfile.mkstemp(prefix=".youtube-lists-", suffix=".tmp", dir=str(target.parent))
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


def allowed(name: str) -> bool:
    """Does the person's switch for this list count right now? Off whenever agent reading is off."""
    return name in LISTS and reading_settings.youtube_list_allowed(name)


def paused_until(now: datetime | None = None) -> datetime | None:
    until = _parse(_load().get("paused_until"))
    return until if until is not None and until > _now(now) else None


def last(memory_path: Path, name: str) -> dict:
    entry = ((_load().get("banks") or {}).get(_bank_key(memory_path)) or {}).get(name)
    return entry if isinstance(entry, dict) else {}


def due(memory_path: Path, now: datetime | None = None) -> list[str]:
    """The lists to offer the person's agent now, in a fixed order: allowed, not paused, not read in ``CADENCE``."""
    if paused_until(now) is not None:
        return []
    moment = _now(now)
    out = []
    for name in LISTS:
        if not allowed(name):
            continue
        at = _parse(last(memory_path, name).get("read_at"))
        if at is None or moment - at >= CADENCE:
            out.append(name)
    return out


def status(memory_path: Path, now: datetime | None = None) -> dict:
    """The settings page's view: per list, the last read and its outcome; the pause, if any."""
    until = paused_until(now)
    lists = {}
    for name in LISTS:
        entry = last(memory_path, name)
        lists[name] = {"lastReadAt": entry.get("read_at"), "lastOutcome": entry.get("outcome"),
                       "lastAt": entry.get("at"), "videos": int(entry.get("videos") or 0)}
    return {"pausedUntil": until.isoformat() if until else None, "lists": lists}


# --- what the agent reported ------------------------------------------------------------------------


def note(memory_path: Path, name: str, outcome: str, *, videos: int = 0, now: datetime | None = None) -> None:
    """Record an outcome. A read clears a pause (the agent was signed in); ``needs_login``/``blocked`` start one."""
    moment = _now(now)
    with _locked() as data:
        banks = data.setdefault("banks", {})
        entry = banks.setdefault(_bank_key(memory_path), {}).setdefault(name, {})
        entry.update(at=moment.isoformat(), outcome=outcome)
        if outcome == "read":
            entry.update(read_at=moment.isoformat(), videos=int(videos))
            data.pop("paused_until", None)
        elif outcome in PAUSING:
            data["paused_until"] = (moment + PAUSE).isoformat()


def resume() -> None:
    """The person turned a list on again: lift the pause (their Try again)."""
    if not path().exists():
        return
    with _locked() as data:
        data.pop("paused_until", None)


# --- the offer ------------------------------------------------------------------------------------


def queue_lines(memory_path: Path, *, can_record: bool, now: datetime | None = None) -> list[str]:
    """The reading queue's lines for the lists that are due — empty when none is (or agent reading is off)."""
    names = due(memory_path, now)
    if not names:
        return []
    lines = []
    for name in names:
        spec = LISTS[name]
        what = ("each video's link, title and channel" if name == "watch_later"
                else "each video's link, title and channel, and the day the page files it under")
        lines.append(f"- The person's YouTube {spec['label']}: {spec['url']} — read {what}.")
    tail = ("Record each list with `cicada_record_youtube_list(list, outcome, videos=[{url, title, channel, "
            "watched_on}], via)` (list `watch_later` or `history`; `watched_on` is YYYY-MM-DD, for history). "
            "If YouTube asks you to sign in, do not sign in or type credentials: record `needs_login` and stop."
            if can_record else
            "If YouTube asks you to sign in, do not sign in or type credentials: stop and tell the person.")
    return ["The person asked their agent to keep these YouTube lists current in Cicada. Open each in their own "
            "signed-in browser session; read only what the page shows (scroll at most a few screens), never click "
            "anything that changes the list."] + lines + [tail]
