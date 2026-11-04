"""What the person read on Substack, as reading days — experience, never saves (G89, owner 2026-11-04).

The person's own agent reads their Substack History in their signed-in browser (``substack_lists``) and records it
here. What was read is not something saved (G71's rule for watch history), so it is aggregated, never dumped (G94):
**one episode per day**, ``reading-history:substack:<YYYY-MM-DD>`` through the one stager, ``source: reading-history``,
origin ``substack-history`` — the kind activity traces' reading days already are (``history_index.kind`` →
``reading``): **index-only** (ruling 30), never read by a model, never a mention; found by lookup.

**The day (ruling 39).** A read's day is the one the page shows for it, when it shows one. Substack's History lists
what was read without a time, so a row with no day is filed under the day the agent first saw it there — read on or
before that day, and the day's words say so. The first read of a long history therefore lands on one day; every later
read adds only what is new since.

**One post, one row.** A post is its canonical URL (``substack.post``), the key a saved post and a followed feed's item
share. History shows a post once, so a post already recorded on any day is never recorded again by this door.

Rows live beside the bank's other source records (``sources/reading/substack/<day>.json``, committed with the day),
never in the episode's frontmatter, which every cold start caches (the shape #528 gave Spotify's plays). No model and
no fetch; every word is scrubbed. The caller commits ``paths``.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Iterable

from api.services import episode_ids, episode_scrub, episode_staging, history_index, media_ingestor, substack

PLATFORM = "substack"
PLATFORM_NAME = "Substack"
ORIGIN = "substack-history"
SOURCE = history_index.READING_SOURCE
SOURCE_PREFIX = f"{history_index.READING_PREFIX}{PLATFORM}:"
SCRUB_WRITER = "reading-history"
ROWS_DIR = ("sources", "reading", PLATFORM)
MAX_PER_DAY = 400
TITLE_CAP = 200
NAME_CAP = 120


@dataclass
class Read:
    url: str                     # canonical (``substack.post``)
    day: date
    #: Whether the page showed the day (else ``day`` is when the agent first saw it in the history).
    dated: bool
    title: str = ""
    author: str = ""
    publication: str = ""

    @property
    def key(self) -> str:
        return media_ingestor.url_hash(self.url)


@dataclass
class RecordResult:
    days_created: int = 0
    days_updated: int = 0
    days_unchanged: int = 0
    added: int = 0
    already: int = 0
    paths: list[str] = field(default_factory=list)


def _clip(value, cap: int) -> str:
    text = episode_scrub.scrub(" ".join(str(value or "").split()))[0]
    return text if len(text) <= cap else text[: cap - 1].rstrip() + "…"


def _day(value) -> date | None:
    text = str(value or "").strip()[:10]
    try:
        day = date.fromisoformat(text)
    except ValueError:
        return None
    return day if 2005 <= day.year <= 2100 else None


def make(url, *, read_on=None, seen_on: date, title=None, author=None, publication=None) -> Read | None:
    """One read from the agent's row, or ``None`` when the link is not a Substack post. A ``read_on`` in the future
    is not a day the person read anything: the row is filed as first seen instead."""
    found = substack.post(url)
    if found is None:
        return None
    shown = _day(read_on)
    dated = shown is not None and shown <= seen_on
    return Read(url=found[0], day=shown if dated else seen_on, dated=dated, title=_clip(title, TITLE_CAP),
                author=_clip(author, NAME_CAP), publication=_clip(publication, NAME_CAP))


def source_id(day: date) -> str:
    return f"{SOURCE_PREFIX}{day.isoformat()}"


def rows_path(memory_path: Path, day: date) -> Path:
    return Path(memory_path).joinpath(*ROWS_DIR, f"{day.isoformat()}.json")


def _rows(memory_path: Path, day: date) -> list[dict]:
    try:
        data = json.loads(rows_path(memory_path, day).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in data if isinstance(r, dict) and r.get("key") and r.get("url")] if isinstance(data, list) else []


def held_keys(memory_path: Path) -> set[str]:
    """Every post this door recorded, on any day."""
    folder = Path(memory_path).joinpath(*ROWS_DIR)
    keys: set[str] = set()
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else ():
        day = _day(path.stem)
        if day is not None:
            keys.update(str(r["key"]) for r in _rows(memory_path, day))
    return keys


def _write_rows(memory_path: Path, day: date, rows: list[dict]) -> bool:
    path = rows_path(memory_path, day)
    text = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".rows-", suffix=".tmp", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True


def _row(r: Read) -> dict:
    return {"key": r.key, "url": r.url, "title": r.title, "author": r.author, "publication": r.publication,
            "dated": r.dated}


def render(day: date, rows: list[dict]) -> str:
    n = len(rows)
    undated = sum(1 for r in rows if not r.get("dated"))
    lines = [f"# Read on {PLATFORM_NAME} · {day.strftime('%A')} {day.isoformat()}", "",
             f"{n} post{'s' if n != 1 else ''} from the person's {PLATFORM_NAME} history, recorded by their own agent "
             "with no model — what was read, not something said or saved."]
    if undated:
        lines.append(f"{undated} of them first appeared in the history this day: {PLATFORM_NAME} shows no time for a "
                     "read, so each was read on or before it.")
    lines.append("")
    for r in rows:
        title = r.get("title") or r["url"]
        by = " — ".join(x for x in (r.get("author"), r.get("publication")) if x)
        lines.append(f"- {title}{f' — {by}' if by else ''} · {r['url']}")
    return "\n".join(lines)


def record(memory_path: Path, reads: Iterable[Read], *, bank: str | None = None) -> RecordResult:
    """Fold reads into their days' episodes. Writes files only; the caller commits ``result.paths``."""
    result = RecordResult()
    memory_path = Path(memory_path)
    episodes_dir = memory_path / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    with episode_staging.STAGE_LOCK, episode_ids.episode_lock(episodes_dir):
        held = held_keys(memory_path)
        fresh: dict[date, list[Read]] = {}
        for r in reads:
            if r.key in held:
                result.already += 1
                continue
            held.add(r.key)
            fresh.setdefault(r.day, []).append(r)
        if not fresh:
            return result
        drafts: list[episode_staging.EpisodeDraft] = []
        rows_by_day: dict[date, list[dict]] = {}
        for day in sorted(fresh):
            rows = (_rows(memory_path, day) + [_row(r) for r in fresh[day]])[:MAX_PER_DAY]
            rows_by_day[day] = rows
            result.added += len(fresh[day])
            drafts.append(episode_staging.EpisodeDraft(
                title=f"Read on {PLATFORM_NAME} · {day.isoformat()}", source_id=source_id(day), source=SOURCE,
                origin=ORIGIN, original_date=day.isoformat(),
                timestamp=datetime.combine(day, time(12, 0)).astimezone().isoformat(),
                body=render(day, rows),
                extra={"platform": PLATFORM, "read_on": day.isoformat(), "posts": len(rows),
                       "evidence_kind": "assistant"},
                # Ruling 30: a reading day is indexed, never read by a model.
                queue_for_sleep=False, processed_by=history_index.INDEXED_BY, writer=SCRUB_WRITER))
        staged = episode_staging.stage(drafts, episodes_dir, bank=bank)
        for day, rows in rows_by_day.items():
            if _write_rows(memory_path, day, rows):
                result.paths.append(str(rows_path(memory_path, day).relative_to(memory_path)))
    for verdict in staged.verdicts:
        if verdict == "created":
            result.days_created += 1
        elif verdict == "skipped":
            result.days_unchanged += 1
        else:
            result.days_updated += 1
    result.paths = sorted(set(result.paths) | set(staged.paths))
    return result


def summary(result: RecordResult) -> str:
    days = result.days_created + result.days_updated
    if not result.added:
        return "No new reading history: every post was already in memory."
    return (f"{result.added} read post{'s' if result.added != 1 else ''} kept across {days} "
            f"day{'s' if days != 1 else ''} (one entry per day, not saves).")
