"""Listening history as experience, never as saves — the Spotify export's plays (G32, ruling 47's path table, ruling 30).

Spotify is export-only (ruling 47 amended 2026-10-29: its Developer Terms §IV.2(b)(i) and §IV.3(a) bar an API
connector). The person asks Spotify for their data on its privacy page and drops the zip it sends them; this module
keeps what they listened to the way ``watch_history`` keeps what they watched:

* **One episode per listening day** (the person's local day, the clock they lived it on), keyed
  ``listening-history:spotify:<YYYY-MM-DD>``, listing what was played that day — each track, episode or audiobook
  once, with when, how many times and for how long. A play is never a saved item.
* **Indexed, never read by a model** (ruling 30, the 2026-10-18 owner ruling on watch history): a day lands already
  read (``processed_by: index``, ``history_index.kind == "listening"``), so it is looked up — search, recall's
  excerpts, the timeline — and never consolidated; a listening day is never a mention of anything it names.
* **Both of Spotify's files meet without doubling.** Account data's ``StreamingHistory_*.json`` (the last year,
  ``endTime`` to the minute, no URI) and Extended streaming history's ``Streaming_History_*.json`` (the whole account,
  ``ts`` to the second, with URIs) describe the same plays. A play's identity is what was played (kind and name,
  case- and space-folded; never the creator, which the two files name differently for a compilation) and the minute it
  ended, in UTC — the precision both files share, one minute either way allowed — looked up on its day and the day
  either side (the local day moves with the Mac's time zone), so the same play
  read from either file, or from both, or imported twice, is one play. A day is rewritten in place and re-queued only
  when its words change (the stager's hash), so a repeat import writes nothing.

A day's play rows live in ``sources/listening/spotify/<day>.json``, never in the episode's frontmatter: every episode
header is cached for the backend's life (review of #528).

No model runs here, nothing is fetched (no Spotify page or API is ever asked), every name is scrubbed before it is
stored, and the stager scrubs the body too. Pure files: the caller commits ``paths``.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable

from api.services import episode_ids, episode_scrub, episode_staging, history_index
from api.services.media_ingestor import RawItem

PLATFORM = "spotify"
PLATFORM_NAME = "Spotify"
#: The play's ``RawItem.origin`` (a ``-history`` origin: every export door keeps it off the save path) and the day
#: episode's ``origin``.
ORIGIN = "spotify-history"
SOURCE = history_index.LISTENING_SOURCE
SOURCE_PREFIX = f"{history_index.LISTENING_PREFIX}{PLATFORM}:"
SCRUB_WRITER = "listening-history"
KINDS = ("music", "podcast", "audiobook", "video")
#: At most this many plays are kept for one day (a heavy day is a few hundred).
MAX_PER_DAY = 1500
#: How many days one locked step stages.
DAYS_PER_STEP = 60
NAME_CAP = 200
#: Spotify counts a stream from 30 seconds; a shorter play is shown as skipped.
STREAM_MS = 30_000


@dataclass
class Play:
    at: datetime                 # when it ended, aware UTC
    title: str
    by: str = ""
    album: str = ""
    kind: str = "music"
    ms: int = 0
    uri: str = ""

    @property
    def key(self) -> str:
        return key_at(self.kind, self.title, self.at)

    def keys_near(self) -> tuple[str, ...]:
        """The keys this same play may carry in a file read at another precision: the minute before and after (one
        file truncating, the other rounding)."""
        return tuple(key_at(self.kind, self.title, self.at + timedelta(minutes=m)) for m in (-1, 0, 1))

    @property
    def day(self) -> date:
        return self.at.astimezone().date()


@dataclass
class RecordResult:
    kept: int = 0
    added: int = 0
    days_created: int = 0
    days_updated: int = 0
    days_unchanged: int = 0
    paths: list[str] = field(default_factory=list)


def key_at(kind: str, title: str, at: datetime) -> str:
    """A play's identity: what it was (kind and name, case- and space-folded) and the UTC minute it ended. The creator
    is left out on purpose (review of #528): Account data names a track's own artist and Extended streaming history
    its album artist, so a compilation track would read as two plays; one listener cannot end two plays of the same
    name in the same minute."""
    return "|".join((kind, _fold(title), at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")))


def _fold(text: str) -> str:
    return " ".join(str(text or "").split()).casefold()


def _clip(text, cap: int = NAME_CAP) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= cap else value[: cap - 1].rstrip() + "…"


def is_play(item: RawItem) -> bool:
    return (item.origin or "") == ORIGIN and isinstance(item.play, dict)


def split(items: Iterable[RawItem]) -> tuple[list[RawItem], list[RawItem]]:
    """``(everything else, plays)``: every door takes the plays out before the save path sees a row."""
    rest: list[RawItem] = []
    plays: list[RawItem] = []
    for item in items:
        (plays if is_play(item) else rest).append(item)
    return rest, plays


def play_item(play: Play) -> RawItem:
    """A play as the export walker's row: it never reaches ``media_ingestor`` (``split``), so ``url`` is only an
    identity for the walker's bookkeeping."""
    return RawItem(url=play.uri or f"spotify-play:{play.key}", title=play.title, channel=play.by, origin=ORIGIN,
                   added_at=play.at.isoformat(), play={"title": play.title, "by": play.by, "album": play.album,
                                                       "kind": play.kind, "ms": play.ms, "uri": play.uri})


def from_items(items: Iterable[RawItem]) -> list[Play]:
    out: list[Play] = []
    for item in items:
        if not is_play(item) or not item.added_at:
            continue
        try:
            at = datetime.fromisoformat(item.added_at)
        except ValueError:
            continue
        p = item.play or {}
        out.append(Play(at=at, title=str(p.get("title") or ""), by=str(p.get("by") or ""),
                        album=str(p.get("album") or ""), kind=str(p.get("kind") or "music"),
                        ms=int(p.get("ms") or 0), uri=str(p.get("uri") or "")))
    return out


def describe(items: Iterable[RawItem]) -> tuple[int, int]:
    """``(plays, days)`` a list of play rows would become — the preview's words, no write. Doubled plays count once."""
    seen: set[str] = set()
    days: set[date] = set()
    n = 0
    for p in sorted(from_items(items), key=lambda p: p.at):
        if seen.intersection(p.keys_near()):
            continue
        seen.add(p.key)
        days.add(p.day)
        n += 1
    return n, len(days)


def source_id(day: date) -> str:
    return f"{SOURCE_PREFIX}{day.isoformat()}"


def _row(p: Play) -> dict:
    return {"key": p.key, "at": p.at.astimezone(timezone.utc).isoformat(), "title": p.title, "by": p.by,
            "album": p.album, "kind": p.kind, "ms": int(p.ms), **({"uri": p.uri} if p.uri else {})}


def _rows_of(fm: dict | None) -> list[dict]:
    rows = (fm or {}).get("played")
    return [r for r in rows if isinstance(r, dict) and r.get("key")] if isinstance(rows, list) else []


#: A day's play rows live beside the bank's other source records, never in the episode: every episode's header is
#: read on a cold start and cached for the process's life (``bank_index``), and a decade of plays there cost a cold
#: scan 9.5 s and +300 MB against 0.5 s without (review of #528). One small JSON file per day, committed with its day.
ROWS_DIR = ("sources", "listening", PLATFORM)


def rows_path(memory_path: Path, day: date) -> Path:
    return Path(memory_path).joinpath(*ROWS_DIR, f"{day.isoformat()}.json")


def _stored_rows(memory_path: Path, day: date) -> list[dict]:
    try:
        data = json.loads(rows_path(memory_path, day).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return _rows_of({"played": data})


def _write_rows(memory_path: Path, day: date, rows: list[dict]) -> bool:
    """The day's rows, atomically; ``False`` when the file already says exactly this."""
    path = rows_path(memory_path, day)
    text = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".rows-", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return True


def merge(rows: list[dict], plays: list[Play]) -> tuple[list[dict], int]:
    """A day's stored plays plus new ones; a play already held (same key) is never added again. A later read with a
    URI fills one an earlier read lacked (account data has none). Sorted by when each ended, capped head-stable."""
    by_key = {r["key"]: dict(r) for r in rows}
    added = 0
    for p in plays:
        held = by_key.get(p.key)
        if held is None:
            by_key[p.key] = _row(p)
            added += 1
        elif p.uri and not held.get("uri"):
            held["uri"] = p.uri
        if held is not None and p.ms > int(held.get("ms") or 0):
            held["ms"] = int(p.ms)
    merged = sorted(by_key.values(), key=lambda r: (str(r.get("at") or ""), r["key"]))
    return merged[:MAX_PER_DAY], added


def _minutes(ms: int) -> int:
    return int(round(ms / 60000))


def render(day: date, rows: list[dict]) -> str:
    """The day's words: what was played, grouped by what it was, in the order first played."""
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for r in rows:
        groups.setdefault((str(r.get("kind")), _fold(r.get("by")), _fold(r.get("title"))), []).append(r)
    total_ms = sum(int(r.get("ms") or 0) for r in rows)
    n = len(rows)
    lines = [f"# Listened on {PLATFORM_NAME} · {day.strftime('%A')} {day.isoformat()}", "",
             f"{n} play{'s' if n != 1 else ''}, about {_minutes(total_ms)} min, on {PLATFORM_NAME} this day — what "
             "was played, not something saved.", ""]
    for _key, plays in groups.items():
        first = plays[0]
        clocks = ", ".join(datetime.fromisoformat(str(r["at"])).astimezone().strftime("%H:%M") for r in plays[:12])
        by = f" — {first['by']}" if first.get("by") else ""
        album = f" ({first['album']})" if first.get("album") and first.get("kind") == "music" else ""
        kind = "" if first.get("kind") == "music" else f" · {first.get('kind')}"
        ms = sum(int(r.get("ms") or 0) for r in plays)
        again = f" · played {len(plays)} times" if len(plays) > 1 else ""
        skipped = " · skipped" if all(int(r.get("ms") or 0) < STREAM_MS for r in plays) else ""
        lines.append(f"- {clocks} · {first['title']}{by}{album}{kind}{again} · {_minutes(ms)} min{skipped}")
    return "\n".join(lines)


def _timestamp(day: date, rows: list[dict]) -> str:
    if rows:
        return str(rows[0]["at"])
    return datetime.combine(day, time(12, 0)).astimezone().isoformat()


def record(memory_path: Path, plays: Iterable[Play], *, bank: str | None = None) -> RecordResult:
    """Fold plays into their days' episodes. Writes episodes only; the caller commits ``result.paths``.

    A play already held anywhere it could have landed — its day or the day either side, its minute or the minute
    either side — is never added again: the day a play falls on is the Mac's local day, which moves when the Mac's
    time zone does (review of #528), and the two downloads differ in how they cut the minute."""
    result = RecordResult()
    groups: dict[date, list[Play]] = {}
    for p in plays:
        if not p.title or p.kind not in KINDS:
            continue
        p.title = episode_scrub.scrub(_clip(p.title))[0]
        p.by = episode_scrub.scrub(_clip(p.by))[0]
        p.album = episode_scrub.scrub(_clip(p.album))[0]
        groups.setdefault(p.day, []).append(p)
        result.kept += 1
    if not groups:
        return result
    episodes_dir = Path(memory_path) / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    days = sorted(groups)
    for start in range(0, len(days), DAYS_PER_STEP):
        step = days[start:start + DAYS_PER_STEP]
        with episode_staging.STAGE_LOCK, episode_ids.episode_lock(episodes_dir):
            index, _ = episode_staging.scan(episodes_dir)
            stored: dict[date, list[dict]] = {}

            def rows_for(day: date) -> list[dict]:
                if day not in stored:
                    stored[day] = _stored_rows(memory_path, day)
                return stored[day]

            held: set[str] = set()
            for day in step:
                for near in (day - timedelta(days=1), day, day + timedelta(days=1)):
                    held.update(r["key"] for r in rows_for(near))
            drafts: list[episode_staging.EpisodeDraft] = []
            rows_by_day: dict[date, list[dict]] = {}
            for day in step:
                fresh: list[Play] = []
                for p in groups[day]:
                    if p.key in {r["key"] for r in rows_for(day)}:
                        fresh.append(p)          # the same day's own row: merge may fill its URI or its length
                    elif not held.intersection(p.keys_near()):
                        fresh.append(p)
                        held.add(p.key)
                if not fresh and source_id(day) not in index:
                    continue
                rows, added = merge(rows_for(day), fresh)
                rows_by_day[day] = rows
                result.added += added
                drafts.append(episode_staging.EpisodeDraft(
                    title=f"Listened on {PLATFORM_NAME} · {day.isoformat()}", source_id=source_id(day), source=SOURCE,
                    origin=ORIGIN, original_date=day.isoformat(), timestamp=_timestamp(day, rows),
                    body=render(day, rows),
                    extra={"platform": PLATFORM, "listened_on": day.isoformat(), "plays": len(rows),
                           "minutes": _minutes(sum(int(r.get("ms") or 0) for r in rows))},
                    # Ruling 30: a listening day is indexed, never read by a model.
                    queue_for_sleep=False, processed_by=history_index.INDEXED_BY, writer=SCRUB_WRITER))
            staged = episode_staging.stage(drafts, episodes_dir, bank=bank)
            for day, rows in rows_by_day.items():
                if _write_rows(memory_path, day, rows):
                    result.paths.append(str(rows_path(memory_path, day).relative_to(Path(memory_path))))
        for verdict in staged.verdicts:
            if verdict == "created":
                result.days_created += 1
            elif verdict == "skipped":
                result.days_unchanged += 1
            else:
                result.days_updated += 1
        result.paths.extend(staged.paths)
    result.paths = sorted(set(result.paths))
    return result


async def import_history(memory_path: Path, rows: list[RawItem], *, trigger: str, author: str = "user") -> RecordResult:
    """Play rows an export walker made into their days, committed alone under ``author`` (the upload route, the
    command line). The file work runs off the event loop."""
    import asyncio

    from api.services import folder_source

    memory_path = Path(memory_path)
    result = await asyncio.to_thread(record, memory_path, from_items(rows), bank=memory_path.name)
    if result.paths:
        await folder_source.commit_paths_for(memory_path, result.paths, subject="Listening history", trigger=trigger,
                                             author=author)
    return result


def summary(result: RecordResult) -> str:
    days = result.days_created + result.days_updated
    if not result.added and not days:
        return "No new listening history: every play was already in memory."
    return (f"{result.added:,} play{'s' if result.added != 1 else ''} of listening history kept across {days:,} "
            f"day{'s' if days != 1 else ''} (one entry per day, not saves).")
