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

* **Playlists** (``https://www.youtube.com/feed/playlists``, then each playlist's own page, G245) and **Liked videos**
  (``https://www.youtube.com/playlist?list=LL``) — saves like Watch later; a playlist is the save's folder (the label a
  Takeout's playlist file gives), so a video in two playlists is one page on both lists. Off until the person turns each on.
  Playlists are a pass: the index names the playlists, then at most :data:`FOLDERS_PER_PASS` of them are opened, the ones
  read longest ago first (``folder_pass``). Like Watch later and history they are outside the saved lists' daily bound,
  on their own cadence: one page-and-its-playlists a day, each playlist capped, and a pause stops them all.

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

from api.services import folder_pass, reading_settings
from api.services.auth import cicada_home

FILENAME = "youtube_lists.json"
#: The lists an agent may read, their page and their words.
LISTS: dict[str, dict[str, str]] = {
    "watch_later": {"url": "https://www.youtube.com/playlist?list=WL", "label": "Watch later"},
    "history": {"url": "https://www.youtube.com/feed/history", "label": "watch history"},
    # G245 (ruling 78b): the playlists index (each playlist is its own page and the saved video's folder) and the liked
    # videos (``list=LL``, a playlist of its own). Both are saves under the Takeout playlists' origin, index-only.
    "playlists": {"url": "https://www.youtube.com/feed/playlists", "label": "Playlists"},
    "liked": {"url": "https://www.youtube.com/playlist?list=LL", "label": "Liked videos"},
}
#: The folder a list's saves are filed under (a playlist's own name for ``playlists``, named per row).
FOLDERS: dict[str, str] = {"watch_later": "Watch later", "liked": "Liked videos"}
#: The lists whose rows are saves (history is watched days, never saves).
SAVE_LISTS = ("watch_later", "playlists", "liked")
FOLDERS_PER_PASS = folder_pass.FOLDERS_PER_PASS
#: A read of ``playlists`` spans calls (the index, then each playlist): its videos add up within this long.
PASS_WINDOW = timedelta(hours=3)
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


def due(memory_path: Path, now: datetime | None = None, *, unattended: bool = False) -> list[str]:
    """The lists to offer the person's agent now: allowed, not paused, and either asked for (:func:`request_check`, G245 —
    whatever the cadence) or not read in ``CADENCE``. Requested lists come first, the oldest request first; then the
    list read longest ago, a list never read before any; ties keep table order. ``unattended`` (a read nobody watches)
    never offers a list that has never been read: its first read goes deeper (:func:`screens_words`) and is the
    person's to start."""
    if paused_until(now) is not None:
        return []
    moment = _now(now)
    floor = datetime.min.replace(tzinfo=timezone.utc)
    ranked = []
    for order, name in enumerate(LISTS):
        if not allowed(name):
            continue
        entry = last(memory_path, name)
        at = _parse(entry.get("read_at"))
        asked = _parse(entry.get("check_requested_at"))
        if unattended and at is None:
            continue
        if asked is None and at is not None and moment - at < CADENCE:
            continue
        ranked.append((0 if asked is not None else 1, asked or at or floor, order, name))
    return [row[3] for row in sorted(ranked)]


def request_check(memory_path: Path, name: str, now: datetime | None = None) -> bool:
    """The person asked to check this list now (G245): stamp it so :func:`due` offers it first. Only a list that is on and
    not paused — a check never lifts the pause — and the next recorded attempt clears the stamp. Says whether it stamped."""
    if not allowed(name) or paused_until(now) is not None:
        return False
    with _locked() as data:
        entry = data.setdefault("banks", {}).setdefault(_bank_key(memory_path), {}).setdefault(name, {})
        entry["check_requested_at"] = _now(now).isoformat()
    return True


def check_requested_at(memory_path: Path, name: str) -> str | None:
    return last(memory_path, name).get("check_requested_at") or None


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
    """Record an outcome. A read clears a pause (the agent was signed in); ``needs_login``/``blocked`` start one. A
    ``playlists`` read is several calls (the index, then each playlist): its videos add up within :data:`PASS_WINDOW`."""
    moment = _now(now)
    with _locked() as data:
        banks = data.setdefault("banks", {})
        entry = banks.setdefault(_bank_key(memory_path), {}).setdefault(name, {})
        before = _parse(entry.get("read_at"))
        entry.update(at=moment.isoformat(), outcome=outcome)
        entry.pop("check_requested_at", None)   # an attempt, whatever its outcome, answers a requested check
        if outcome == "read":
            if name == "playlists" and before is not None and moment - before < PASS_WINDOW:
                videos = int(entry.get("videos") or 0) + int(videos)
            entry.update(read_at=moment.isoformat(), videos=int(videos))
            data.pop("paused_until", None)
        elif outcome in PAUSING:
            data["paused_until"] = (moment + PAUSE).isoformat()


def note_folders(memory_path: Path, name: str, names: list[str]) -> None:
    """The playlists the index listed (``names``, cleaned; empty for an account with none): how many, kept as a count.
    Nothing else of them is kept here."""
    with _locked() as data:
        entry = data.setdefault("banks", {}).setdefault(_bank_key(memory_path), {}).setdefault(name, {})
        entry["folder_count"] = len(names)


def folder_count(memory_path: Path, name: str) -> int:
    """How many playlists the index last listed; 0 when it showed none or was never read."""
    return int(last(memory_path, name).get("folder_count") or 0)


def next_folders(memory_path: Path, names: list[str], name: str) -> list[str]:
    """The playlists to open next: at most :data:`FOLDERS_PER_PASS`, the never-read first, then the least recently read."""
    return folder_pass.order(names, last(memory_path, name).get("folder_reads"))


def stamp_folder(memory_path: Path, name: str, folder: str, now: datetime | None = None) -> None:
    """One playlist's own page was read now. Only a hash of its name is kept (``folder_pass``)."""
    with _locked() as data:
        entry = data.setdefault("banks", {}).setdefault(_bank_key(memory_path), {}).setdefault(name, {})
        entry["folder_reads"] = folder_pass.stamped(entry.get("folder_reads"), folder, _now(now).isoformat())


def resume() -> None:
    """The person turned a list on again: lift the pause (their Try again)."""
    if not path().exists():
        return
    with _locked() as data:
        data.pop("paused_until", None)


# --- the offer ------------------------------------------------------------------------------------


def screens_words(memory_path: Path, name: str) -> str:
    """How far this read goes (G245): the first read of a list catches up; a later one stops where the list reaches
    videos already in memory, and the record's reply says when it has."""
    if not last(memory_path, name).get("read_at"):
        return (f"This is the first read of this list, so go deeper than usual to catch up: scroll up to "
                f"{folder_pass.FIRST_READ_SCREENS} screens. Older videos than that come only with a Takeout the person "
                "can drop on the Cicada window.")
    return (f"Scroll only until you reach videos already in memory, and at most {folder_pass.LATER_READ_SCREENS} "
            "screens: the reply says when you have reached them.")


def queue_lines(memory_path: Path, *, can_record: bool, now: datetime | None = None,
                unattended: bool = False) -> list[str]:
    """The reading queue's lines for the lists that are due — empty when none is (or agent reading is off)."""
    names = due(memory_path, now, unattended=unattended)
    if not names:
        return []
    lines = []
    for name in names:
        spec = LISTS[name]
        what = ("each video's link, title and channel, and the day the page files it under" if name == "history"
                else "each video's link, title and channel")
        if name == "playlists":
            lines.append(
                f"- The person's YouTube {spec['label']}: {spec['url']} — first send the playlists' names as "
                f"`playlist_names` (an empty list when there are none); the reply names the {FOLDERS_PER_PASS} at most to "
                f"open next. Open each playlist's own page and read {what}, scrolling at most "
                f"{folder_pass.FOLDER_SCREENS} screens of it, and set `playlist` to its name on every row. "
                f"{screens_words(memory_path, name)}")
        elif name == "history":
            lines.append(f"- The person's YouTube {spec['label']}: {spec['url']} — read {what} (scroll at most a few "
                         "screens).")
        else:
            lines.append(f"- The person's YouTube {spec['label']}: {spec['url']} — read {what}. "
                         f"{screens_words(memory_path, name)}")
    tail = ("Record each list with `cicada_record_youtube_list(list, outcome, videos=[{url, title, channel, "
            "watched_on, playlist}], via)` (list `watch_later`, `history`, `playlists` or `liked`; `watched_on` is "
            "YYYY-MM-DD, for history; `playlist` is for playlists). "
            "If YouTube asks you to sign in, do not sign in or type credentials: record `needs_login` and stop."
            if can_record else
            "If YouTube asks you to sign in, do not sign in or type credentials: stop and tell the person.")
    return ["The person asked their agent to keep these YouTube lists current in Cicada. Open each in their own "
            "signed-in browser session; read only what the page shows, never click "
            "anything that changes the list."] + lines + [tail]
