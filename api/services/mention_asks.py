"""Depth on mention (G245, ruling 78 (e), owner 2026-11-24): the ask a talked-about save leaves for the person's own agent.

A save from a platform's list stays light — a title, a link, the words the list showed, found by words and meaning, read
by no model. When the person **talks about** it (their own located words name its link or its whole title,
``saved_mentions``), two things follow: Sleep reads it once like a bare save, and — here — **an ask is left for the
person's own agent** to go deeper:

* a provider video (what ``video_state`` recognises: YouTube, TikTok, …) goes on the video queue, as a transcript job;
* a post on a walled site (X, Instagram, LinkedIn, Reddit post pages) goes on the reading queue.

Each row is marked ``origin: mention`` and carries the key of the list the save came from. The agent is told "the person
talked about this", never "asked <date>" (the mark survives both stores' cleaning; ``reading_asks``, ``video_queue``).

What this is not. **Cicada starts no agent, downloads nothing and derives no stream:** it is one row in a queue the
person's agent reads the next time it asks. The row is honoured (listed, leased, counted, recordable) only while **agent
reading is on and that save's list is on** (:func:`gate`); turning either off dequeues it (:func:`sweep`, and every read
already hides it); the person removes it from the queue's own list as they remove their own asks. The agent cannot plant
one: only :func:`offer` writes the mark, from Sleep's own step, and ``reading_queue.authorizes`` honours it only while
the gate holds.

Bounds (no expiry, said): **at most** :data:`DAILY_CAP` **asks a day per bank across both queues**, kept in a small
machine-wide file beside the queues (a day and a count, never in a bank); at most :data:`MAX_WAITING` waiting at once. A
waiting mention ask **never expires** — an expiry would turn the card's "asked" back into "kept" with no word to the
person; the two bounds keep the file small instead, and a person who does not want one removes it. A link is offered
**once**: the hash of an offered link is remembered (:data:`MAX_OFFERED`), so a removal holds against every later mention.

Rails: no model, no network; an ask names only the save's own link, already kept; the telemetry ledger is untouched; a
demo bank is never asked about.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import media_ingestor, reading_asks, reading_hosts, reading_settings, video_queue, video_state
from api.services.auth import cicada_home

ORIGIN = reading_asks.ORIGIN_MENTION
#: Asks a day per bank, both queues together (owner brief, 2026-11-24).
DAILY_CAP = 5
#: Mention asks waiting at once per bank, both queues together.
MAX_WAITING = 50
#: Links remembered as offered, per bank (a removal holds against every later mention).
MAX_OFFERED = 5000

_YOUTUBE = "youtube:"

#: ``(origin, folder)`` and ``origin`` -> the settings key of the list a save came from, derived from the one table every
#: list is registered in (``saved_lists.PLATFORMS``): a list nobody registered is never asked about.
_BY_ORIGIN_FOLDER: dict[tuple[str, str], str] = {}
_BY_ORIGIN: dict[str, str] = {}


def _tables() -> None:
    if _BY_ORIGIN:
        return
    from api.services import saved_lists

    for key, p in saved_lists.PLATFORMS.items():
        if not p.origin or not p.folder:
            continue
        _BY_ORIGIN_FOLDER[(p.origin, p.folder)] = key
        _BY_ORIGIN.setdefault(p.origin, key)   # a site's first list (its base) is the fallback for any other folder


def list_key(origin: str, folder: str) -> str | None:
    """The settings key of the list a save came from (``x-likes``, ``instagram``, ``youtube:watch_later``), or ``None``
    for a save no list of the person's registered. A folder the person made on a site (a collection, a playlist's name)
    belongs to the site's base list (``playlists`` for YouTube)."""
    origin, folder = str(origin or ""), str(folder or "")
    if origin == "youtube-playlist":
        return _YOUTUBE + {"Watch later": "watch_later", "Liked videos": "liked"}.get(folder, "playlists")
    _tables()
    return _BY_ORIGIN_FOLDER.get((origin, folder)) or _BY_ORIGIN.get(origin)


def gate() -> Callable[[dict], bool]:
    """A predicate over a mention row, with the person's switches read once: agent reading on and the row's list on."""
    if not reading_settings.agent_enabled():
        return lambda row: False
    yt, saved = reading_settings.youtube_lists(), reading_settings.saved_lists()

    def honoured(row: dict) -> bool:
        key = str((row or {}).get("list") or "")
        return key[len(_YOUTUBE):] in yt if key.startswith(_YOUTUBE) else key in saved

    return honoured


def honoured(row: dict) -> bool:
    """Does this mention row count right now? Anything that is not a mention row always does."""
    return (row or {}).get("origin") != ORIGIN or gate()(row)


# --- the day's counter, outside every bank ----------------------------------------------------------------------------


def _path(memory_path: Path) -> Path:
    return cicada_home() / "mention_asks" / f"{video_queue.bank_slug(memory_path)}.json"


def _day(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"day": "", "count": 0, "offered": {}}
    if not isinstance(data, dict):
        return {"day": "", "count": 0, "offered": {}}
    offered = data.get("offered") if isinstance(data.get("offered"), dict) else {}
    count = data.get("count")
    return {"day": str(data.get("day") or ""), "count": count if isinstance(count, int) and count > 0 else 0,
            "offered": {str(h): str(d) for h, d in offered.items() if re.fullmatch(r"[0-9a-f]{12}", str(h))}}


@contextmanager
def _locked(memory_path: Path):
    target = _path(memory_path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(target.with_name(target.name + ".lock"), "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield target
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _save(target: Path, state: dict) -> None:
    offered = state["offered"]
    if len(offered) > MAX_OFFERED:
        state["offered"] = dict(list(offered.items())[-MAX_OFFERED:])   # insertion order is time
    fd, tmp = tempfile.mkstemp(prefix=".mention-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"v": 1, **state}, indent=1, sort_keys=True) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def stamp(memory_path: Path) -> str:
    """The two queue files' mtimes: a row's ``depth: asked`` moves with a queue write that touches no bank file (the
    person removing the ask, an agent releasing it)."""
    return f"{reading_asks.mtime(memory_path):.3f}:{video_queue.mtime(memory_path):.3f}"


def asked_today(memory_path: Path, now: datetime | None = None) -> int:
    state = _load(_path(memory_path))
    return state["count"] if state["day"] == _day(now) else 0


# --- what is waiting ----------------------------------------------------------------------------------------------


def waiting_hashes(memory_path: Path, *, now: datetime | None = None) -> frozenset[str]:
    """The links with a mention ask waiting right now — on either queue, honoured — as url hashes. One read of each
    queue file, no bank read: what the items rows' ``depth: asked`` and the waiting bound both come from."""
    memory_path = Path(memory_path)
    ok = gate()
    held: set[str] = set()
    try:
        held |= {r["url_hash"] for r in reading_asks.all_rows(memory_path, now=now)
                 if r.get("origin") == ORIGIN and r["state"] == "waiting" and ok(r)}
    except ValueError:
        pass
    try:
        rows, _ = video_queue.view(memory_path, now, records=lambda: video_state.watch_records(memory_path))
        held |= {r["key"] for r in rows if r.get("origin") == ORIGIN and r["state"] in ("queued", "claimed") and ok(r)}
    except (OSError, ValueError):
        pass
    return frozenset(held)


# --- leaving the ask ----------------------------------------------------------------------------------------------


def offer(memory_path: Path, saves: dict[str, dict], *, now: datetime | None = None) -> list[str]:
    """Leave an ask for each save the person talked about (``saved_mentions``). ``saves`` is ``{episode id: {url, origin,
    folder}}`` in the order said. Returns the url hashes asked, in order. Nothing is left, and nothing counted, for a
    save whose list is off or unknown, that was offered before, that an agent already read or watched, that is neither a
    provider video nor a post on a walled site, or that already has a row on a queue; and none past the day's bound or
    the waiting bound. A demo bank is never asked about."""
    memory_path = Path(memory_path)
    if not reading_settings.agent_enabled():
        return []
    from api.services import demo_guard, source_streams

    if demo_guard.is_demo(memory_path):
        return []
    sweep(memory_path)
    out: list[str] = []
    ok = gate()
    videos = None
    index = None
    done = source_streams.episodes(memory_path).agent_read
    try:
        with _locked(memory_path) as target:
            state = _load(target)
            moment_day = _day(now)
            if state["day"] != moment_day:
                state["day"], state["count"] = moment_day, 0
            waiting = len(waiting_hashes(memory_path, now=now))
            for info in saves.values():
                if state["count"] >= DAILY_CAP or waiting >= MAX_WAITING:
                    break
                key = list_key(info.get("origin", ""), info.get("folder", ""))
                url = str(info.get("url") or "").strip()
                if key is None or not url or not ok({"list": key}):
                    continue
                h = media_ingestor.url_hash(url)
                if h in state["offered"] or h in done:
                    continue
                if videos is None:
                    videos = video_state.saved_videos(memory_path)
                    index = media_ingestor.load_url_index(memory_path)
                made = False
                if h in videos:
                    made = video_queue.offer_mention(memory_path, h, key, now=now)
                else:
                    entry = (index or {}).get(h) or {}
                    verdict = reading_hosts.agent_may_read(str(entry.get("url") or ""), enabled=True)
                    if verdict.ok and verdict.walled:
                        made = reading_asks.mention(
                            memory_path, h, host=reading_hosts.display_host(verdict.host), host_class="walled",
                            list_key=key, now=now) is not None
                if made:
                    state["count"] += 1
                    state["offered"][h] = moment_day
                    waiting += 1
                    out.append(h)
            _save(target, state)
    except Exception as exc:  # noqa: BLE001 — an ask not left tonight is left by a later mention
        logger.warning(f"Mention asks skipped: {type(exc).__name__}")
    return out


def sweep(memory_path: Path) -> int:
    """Remove the mention asks that no longer count — agent reading or their list turned off — from both queues. Reads
    already hide them; this makes the removal real, so turning a switch back on never brings an old ask back. Returns how
    many rows went."""
    memory_path = Path(memory_path)
    ok = gate()
    gone = 0
    try:
        if reading_asks.path_for(memory_path).exists():
            gone += reading_asks.drop_where(memory_path, lambda r: r.get("origin") == ORIGIN and not ok(r))
        gone += video_queue.drop_mentions(memory_path, keep=ok)
    except (OSError, ValueError):
        pass
    return gone


__all__ = ["DAILY_CAP", "MAX_OFFERED", "MAX_WAITING", "ORIGIN", "asked_today", "gate", "honoured", "list_key", "offer",
           "stamp", "sweep", "waiting_hashes"]
