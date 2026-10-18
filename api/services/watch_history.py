"""Watch history as experience, never as saves (G71 §3, G69, G94; owner 2026-10-16).

What a person watched is not something they saved. Before this module a Takeout ``watch-history.json`` read "on
request" became one saved link per video — years of history poured into Saved, one media page each. The owner asked
for YouTube's Watch later and history (2026-10-16); the answer keeps the two apart:

* **Watch later is a save.** It stays where saved videos go (``media_ingestor``: one ``url_index`` row and media page
  per video, folder ``Watch later``), whichever door brings it — a Takeout playlist CSV or the person's own agent.
* **History is experience.** It is aggregated, never dumped (G94: "aggregate into experience, never dump the
  samples"): **one episode per platform per day**, listing what was watched that day in order, keyed
  ``watch-history:<platform>:<YYYY-MM-DD>`` through the one stager (``episode_staging``); Saved never sees a single
  history row. **Indexed, not consolidated** (owner ruling 2026-10-18): a day lands already read
  (``processed_by: index``, ``history_index``) and no model ever reads it — it is looked up (the lexical and vector
  indexes, :func:`lookup` for Ask, the timeline's count), and each month gets a summary counted from its days
  (:func:`rollup`: the channels watched most, the ones come back to across weeks, the videos watched on more than one
  day). A channel that has a page gets one derived line at read (:func:`channel_line`); a watched day is never a
  mention of it.

**Three doors, one record.** A Takeout export (``watch-history.json`` or ``.html``, on request), Chrome's own History
read on this Mac by the app (``POST /sources/sync-watch-history``), and the person's own agent reading their history
page in their signed-in browser (``cicada_record_youtube_list``) all land here. A video is the same identity
everywhere: ``media_ingestor.url_hash`` of its canonical URL — the key a Watch later save, a bookmark and a Takeout
playlist row already share — so a ``youtu.be`` link, a Short and a ``watch?v=`` URL with ``&t=`` are one video. Within
a day a video is ONE row: a re-read, a second door, or a reload of the same page adds nothing; a watch more than
``REWATCH_GAP`` after the last one kept is a re-watch and adds its time. A door that knows only the day (the agent
reading the history page, TikTok's export) merges into the row a timed door wrote. A day's episode is rewritten in
place and re-queued only when its words change (the stager's hash), so an idle re-read writes nothing.

**Days are local.** A watch with an instant falls on the day it was watched on this machine's clock, the clock the
person lived it on; a door that only knows a day passes that day.

No model runs here, nothing is fetched, and every title is scrubbed before it is stored (the stager scrubs the body
too). Pure files: the caller commits ``paths`` and holds whatever admission its door needs (an episode-only write is
capture, ungated, like every Awake writer).
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from api.services import episode_ids, episode_scrub, episode_staging, history_index, markdown_parser, media_ingestor
from api.services.media_ingestor import RawItem

PLATFORMS: dict[str, str] = {"youtube": "YouTube", "tiktok": "TikTok"}
#: The episode's ``origin`` per platform. ``tiktok-history`` is the origin the TikTok parsers already stamp.
ORIGINS: dict[str, str] = {"youtube": "youtube-history", "tiktok": "tiktok-history"}
HISTORY_ORIGINS = frozenset(ORIGINS.values())
SOURCE = "watch-history"
SOURCE_PREFIX = "watch-history:"
SCRUB_WRITER = "watch-history"
#: Which door a watch came through — frontmatter only (``via``), never in the body, so a second door that saw the
#: same watch never re-queues the day.
DOORS = ("takeout", "chrome", "agent", "export")
#: A second watch of the same video this long after the last one kept is a re-watch, not a reload.
REWATCH_GAP = timedelta(minutes=30)
#: At most this many videos are kept for one day, and this many watch times per video.
MAX_PER_DAY = 400
MAX_TIMES = 12
#: Every instant a door reported for one video on one day, the earliest kept (owner, 2026-10-16, from the backend
#: hunt): ``times`` is derived from these each time, so the order doors arrive in never changes the day. Frontmatter
#: only — the body shows ``times``.
MAX_SEEN = 48
TITLE_CAP = 200
CHANNEL_CAP = 120
#: How many days one locked step stages (each step holds the bank's episode lock briefly, never a whole import).
DAYS_PER_STEP = 60
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_TIKTOK_VIDEO = re.compile(r"/video/(\d{6,25})")
_COUNT_PREFIX = re.compile(r"^\(\d{1,4}\)\s+")


@dataclass
class Watch:
    """One watch, as a door saw it."""

    platform: str
    url: str                 # canonical (``media_ingestor.normalize_url``)
    day: date
    at: datetime | None = None   # aware; None when the door knows only the day
    title: str = ""
    channel: str = ""
    door: str = ""

    @property
    def key(self) -> str:
        return media_ingestor.url_hash(self.url)


@dataclass
class RecordResult:
    days_created: int = 0
    days_updated: int = 0
    days_unchanged: int = 0
    #: new videos on a day plus new watch times of a video already there
    added: int = 0
    #: watches given that were kept (a valid video with a day)
    kept: int = 0
    paths: list[str] = field(default_factory=list)
    episodes: dict[str, str] = field(default_factory=dict)   # day key -> episode id

    def as_dict(self) -> dict:
        return {"days_created": self.days_created, "days_updated": self.days_updated,
                "days_unchanged": self.days_unchanged, "added": self.added, "kept": self.kept}


# --- what a watch is -------------------------------------------------------------------------------


def watch_url(url: str | None) -> tuple[str, str] | None:
    """``(platform, canonical url)`` for a video page, else ``None``.

    YouTube: ``youtube.com/watch?v=``, ``youtu.be/<id>``, ``/shorts/<id>`` (and ``m.``/``music.`` hosts) — the
    shapes ``normalize_url`` folds to one ``watch?v=`` URL. TikTok: a ``/video/<digits>`` page. Anything else — a
    channel page, a search, the home feed, a non-http scheme — is not a watch."""
    raw = (url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw if "://" in raw else "https://" + raw)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if host == "youtu.be" or host.endswith(".youtu.be") or host == "youtube.com" or host.endswith(".youtube.com"):
        vid = media_ingestor._youtube_video_id(parsed)
        if not vid or not _VIDEO_ID.match(vid):
            return None
        return "youtube", f"https://www.youtube.com/watch?v={vid}"
    if host in ("tiktok.com", "tiktokv.com") or host.endswith((".tiktok.com", ".tiktokv.com")):
        if not _TIKTOK_VIDEO.search(parsed.path or ""):
            return None
        return "tiktok", media_ingestor.normalize_url(raw)
    return None


def clean_title(title: str | None, *, platform: str = "youtube") -> str:
    """One line, scrubbed, capped. Strips what the doors wrap a title in: Takeout's ``Watched …``, a browser tab's
    ``… - YouTube`` and its ``(3) …`` notification count."""
    text = " ".join(str(title or "").split())
    if platform == "youtube":
        if text.startswith("Watched "):
            text = text[len("Watched "):]
        for suffix in (" - YouTube", " – YouTube", " - YouTube Music"):
            if text.endswith(suffix):
                text = text[: -len(suffix)]
        text = _COUNT_PREFIX.sub("", text)
        if text in ("YouTube", "YouTube Music"):
            text = ""
    text = episode_scrub.scrub(text.strip())[0]
    return text if len(text) <= TITLE_CAP else text[: TITLE_CAP - 1].rstrip() + "…"


def _clean_channel(channel: str | None) -> str:
    text = episode_scrub.scrub(" ".join(str(channel or "").split()))[0]
    return text if len(text) <= CHANNEL_CAP else text[: CHANNEL_CAP - 1].rstrip() + "…"


def parse_instant(value) -> datetime | None:
    """An aware instant from an ISO string (``Z`` allowed) or a datetime; a naive value is read as UTC (Takeout and
    TikTok write UTC). Implausible years are refused."""
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if not 2005 <= dt.year <= 2100:
        return None
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def parse_day(value) -> date | None:
    text = str(value or "").strip()[:10]
    try:
        day = date.fromisoformat(text)
    except ValueError:
        return None
    return day if 2005 <= day.year <= 2100 else None


def local_day(at: datetime) -> date:
    return at.astimezone().date()


def make(url: str | None, *, at=None, day=None, title: str | None = None, channel: str | None = None,
         door: str = "") -> Watch | None:
    """A :class:`Watch` from one door's raw fields, or ``None`` when it is not a video watch or has no date."""
    found = watch_url(url)
    if found is None:
        return None
    platform, canonical = found
    instant = parse_instant(at) if at is not None else None
    the_day = local_day(instant) if instant is not None else parse_day(day)
    if the_day is None:
        return None
    return Watch(platform=platform, url=canonical, day=the_day, at=instant,
                 title=clean_title(title, platform=platform), channel=_clean_channel(channel), door=door)


def is_history_item(item: RawItem) -> bool:
    return (item.origin or "") in HISTORY_ORIGINS


def split(items: Iterable[RawItem]) -> tuple[list[RawItem], list[RawItem]]:
    """``(saves, history)``: a parser marks a history row by its ``-history`` origin, and only saves go on to
    ``media_ingestor``."""
    saves: list[RawItem] = []
    history: list[RawItem] = []
    for item in items:
        (history if is_history_item(item) else saves).append(item)
    return saves, history


def from_items(items: Iterable[RawItem], *, door: str) -> tuple[list[Watch], int]:
    """Watches from history rows a parser made (``added_at`` is the instant, else ``added`` the day). Returns
    ``(watches, dropped)`` — a row that is not a video page or has no date is dropped and counted."""
    out: list[Watch] = []
    dropped = 0
    for item in items:
        w = make(item.url, at=item.added_at, day=item.added, title=item.title, channel=item.channel, door=door)
        if w is None:
            dropped += 1
        else:
            out.append(w)
    return out, dropped


def describe(items: Iterable[RawItem]) -> tuple[int, int]:
    """``(videos, days)`` a list of history rows would become — the preview's words, no write."""
    watches, _ = from_items(items, door="")
    return len(watches), len({(w.platform, w.day) for w in watches})


# --- the day's record --------------------------------------------------------------------------------


def source_id(platform: str, day: date) -> str:
    return f"{SOURCE_PREFIX}{platform}:{day.isoformat()}"


def _iso(dt: datetime) -> str:
    return episode_ids.to_utc_iso(dt.astimezone(timezone.utc))


def _merge_times(times: list[str]) -> list[str]:
    """Distinct watches, oldest first: an instant within ``REWATCH_GAP`` of the last kept one is the same watch."""
    parsed = sorted({t for t in (parse_instant(x) for x in times) if t is not None})
    kept: list[datetime] = []
    for t in parsed:
        if not kept or t - kept[-1] >= REWATCH_GAP:
            kept.append(t)
    return [_iso(t) for t in kept[:MAX_TIMES]]


def _seen(instants: list[str]) -> list[str]:
    """The raw instants, distinct, oldest first, the earliest ``MAX_SEEN`` kept. Keeping the earliest of a union is
    the same whichever order the parts arrive in, which is what makes every merge order give one day."""
    parsed = sorted({t for t in (parse_instant(x) for x in instants) if t is not None})
    return [_iso(t) for t in parsed[:MAX_SEEN]]


def _rows_of(fm: dict) -> list[dict]:
    raw = fm.get("watched")
    rows: list[dict] = []
    if isinstance(raw, list):
        for r in raw:
            if isinstance(r, dict) and watch_url(str(r.get("url") or "")):
                times = [str(t) for t in (r.get("times") or []) if t]
                # A day written before `seen` existed: its kept watches are the best raw record there is.
                seen = [str(t) for t in (r.get("seen") or []) if t] or times
                rows.append({"url": str(r["url"]), "title": str(r.get("title") or ""),
                             "channel": str(r.get("channel") or ""), "times": times,
                             "via": [str(v) for v in (r.get("via") or []) if str(v) in DOORS],
                             "seen": _seen(seen)})
    return rows


def merge(rows: list[dict], watches: list[Watch]) -> tuple[list[dict], int]:
    """Fold one day's watches into its stored rows. Returns ``(rows, added)``."""
    by_key = {media_ingestor.url_hash(r["url"]): r for r in rows}
    added = 0
    for w in watches:
        row = by_key.get(w.key)
        if row is None:
            if len(by_key) >= MAX_PER_DAY:
                continue
            row = {"url": w.url, "title": "", "channel": "", "times": [], "via": [], "seen": []}
            by_key[w.key] = row
            rows.append(row)
            added += 1
        if w.at is not None:
            before = len(row["times"])
            row["seen"] = _seen(list(row.get("seen") or []) + [_iso(w.at)])
            row["times"] = _merge_times(row["seen"])
            if before and len(row["times"]) > before:
                added += 1   # a re-watch of a video already on this day
        if w.title and not row["title"]:
            row["title"] = w.title
        if w.channel and not row["channel"]:
            row["channel"] = w.channel
        if w.door in DOORS and w.door not in row["via"]:
            row["via"] = sorted(row["via"] + [w.door])
    rows.sort(key=lambda r: (r["times"][0] if r["times"] else "9999", r["url"]))
    return rows, added


def _clock(stamp: str) -> str:
    t = parse_instant(stamp)
    return t.astimezone().strftime("%H:%M") if t is not None else ""


def render(platform: str, day: date, rows: list[dict]) -> str:
    name = PLATFORMS[platform]
    n = len(rows)
    lines = [f"# Watched on {name} · {day.strftime('%A')} {day.isoformat()}", "",
             f"{n} video{'s' if n != 1 else ''} watched on {name} this day — what was watched, not something saved.",
             ""]
    for r in rows:
        clocks = ", ".join(c for c in (_clock(t) for t in r["times"]) if c)
        head = f"{clocks} · " if clocks else ""
        title = r["title"] or r["url"].rsplit("=", 1)[-1]
        by = f" — {r['channel']}" if r["channel"] else ""
        again = f" (watched {len(r['times'])} times)" if len(r["times"]) > 1 else ""
        lines.append(f"- {head}{title}{by}{again} · {r['url']}")
    return "\n".join(lines)


def _timestamp(day: date, rows: list[dict]) -> str:
    firsts = [parse_instant(r["times"][0]) for r in rows if r["times"]]
    firsts = [t for t in firsts if t is not None]
    if firsts:
        return _iso(min(firsts))
    return _iso(datetime.combine(day, time(12, 0)).astimezone())


def record(memory_path: Path, watches: Iterable[Watch], *, bank: str | None = None) -> RecordResult:
    """Fold watches into their days' episodes. Writes episodes only; the caller commits ``result.paths``."""
    result = RecordResult()
    groups: dict[tuple[str, date], list[Watch]] = {}
    for w in watches:
        if w.platform not in PLATFORMS:
            continue
        groups.setdefault((w.platform, w.day), []).append(w)
        result.kept += 1
    if not groups:
        return result
    episodes_dir = Path(memory_path) / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    keys = sorted(groups)
    for start in range(0, len(keys), DAYS_PER_STEP):
        step = keys[start:start + DAYS_PER_STEP]
        # The stager's process lock first, the bank's episode lock second (episode_ids' lock order): the read of a
        # day's rows and its rewrite are one step, so a second door writing the same day — another process
        # included — merges after this one, never over it.
        with episode_staging.STAGE_LOCK, episode_ids.episode_lock(episodes_dir):
            index, _ = episode_staging.scan(episodes_dir)
            drafts: list[episode_staging.EpisodeDraft] = []
            for platform, day in step:
                sid = source_id(platform, day)
                entry = index.get(sid)
                rows, added = merge(_rows_of(entry.fm) if entry else [], groups[(platform, day)])
                result.added += added
                drafts.append(episode_staging.EpisodeDraft(
                    title=f"Watched on {PLATFORMS[platform]} · {day.isoformat()}", source_id=sid, source=SOURCE,
                    origin=ORIGINS[platform], original_date=day.isoformat(), timestamp=_timestamp(day, rows),
                    body=render(platform, day, rows),
                    extra={"platform": platform, "watched_on": day.isoformat(), "videos": len(rows),
                           "watched": rows},
                    # Owner ruling 2026-10-18: a watched day is indexed, never read by a model.
                    queue_for_sleep=False, processed_by=history_index.INDEXED_BY,
                    writer=SCRUB_WRITER))
            staged = episode_staging.stage(drafts, episodes_dir, bank=bank)
            # A day whose words did not move may still have learnt a raw instant (`seen`): kept in its frontmatter
            # alone, under the same locks, never re-queued — the next merge needs it to be order-free.
            for verdict, draft in zip(staged.verdicts, drafts):
                entry = index.get(draft.source_id)
                if verdict == "skipped" and entry is not None and _refresh_seen(entry.path, draft.extra["watched"]):
                    result.paths.append(str(entry.path.relative_to(Path(memory_path))))
        for verdict, draft in zip(staged.verdicts, drafts):
            if verdict == "created":
                result.days_created += 1
            elif verdict == "skipped":
                result.days_unchanged += 1
            else:
                result.days_updated += 1
        # A day whose words did not change is left as it was — frontmatter included, so `via` names the doors
        # that wrote its words, not every door that later saw the same watches.
        result.paths.extend(staged.paths)
        result.episodes.update(staged.episode_ids)
    # The months these days fall in get their summary rewritten when a day's words moved (the stager's hash).
    months = {(platform, _month_key(day)) for platform, day in keys}
    result.paths.extend(rollup(memory_path, months=months, bank=bank).paths)
    result.paths = sorted(set(result.paths))
    return result


def _refresh_seen(path: Path, rows: list[dict]) -> bool:
    """A day whose words did not change keeps its frontmatter as it was (``via`` names only the doors that wrote its
    words) except each video's raw instants, ``seen``, which the next merge needs. Body, hashes and queue untouched."""
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    stored = fm.get("watched")
    if not isinstance(stored, list):
        return False
    seen_by_url = {media_ingestor.url_hash(r["url"]): r.get("seen") or [] for r in rows}
    changed = False
    updated = []
    for r in stored:
        if isinstance(r, dict) and r.get("url"):
            want = seen_by_url.get(media_ingestor.url_hash(str(r["url"])))
            if want is not None and list(r.get("seen") or []) != want:
                r = {**r, "seen": want}
                changed = True
        updated.append(r)
    if not changed:
        return False
    fm["watched"] = updated   # a watch day carries no `turns` sidecar, so the key order is the stored one
    markdown_parser.write(path, fm, parsed.body)
    return True


# --- the month's summary: counted, never read (owner ruling 2026-10-18) --------------------------------------------

#: English month names, fixed: the summary's words never depend on the machine's locale.
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
#: Lines per section of a month's summary.
TOP_CHANNELS = 15
TOP_RETURNED = 15
TOP_REWATCHED = 10


@dataclass
class RollupResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    paths: list[str] = field(default_factory=list)


def _month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def month_source_id(platform: str, month: str) -> str:
    return f"{history_index.MONTH_PREFIX}{platform}:{month}"


def _day_of(sid: str) -> tuple[str, date] | None:
    """``watch-history:<platform>:<YYYY-MM-DD>`` → ``(platform, day)``."""
    if not sid.startswith(SOURCE_PREFIX):
        return None
    platform, _, raw = sid[len(SOURCE_PREFIX):].partition(":")
    if platform not in PLATFORMS:
        return None
    try:
        return platform, date.fromisoformat(raw)
    except ValueError:
        return None


def _fold(name: str) -> str:
    return " ".join(name.split()).casefold()


def render_month(platform: str, month: str, days: list[tuple[date, list[dict]]]) -> str:
    """A month of watch history as counts: the channels watched most, the ones come back to across weeks, the videos
    watched on more than one day, and the days. Deterministic — the same days always give the same words."""
    name = PLATFORMS[platform]
    year, mon = int(month[:4]), int(month[5:7])
    label = f"{_MONTHS[mon - 1]} {year}"
    days = sorted(days, key=lambda d: d[0])
    total = sum(len(rows) for _, rows in days)
    channels: dict[str, dict] = {}
    videos: dict[str, dict] = {}
    for day, rows in days:
        week = day.isocalendar()[:2]
        for r in rows:
            ch = " ".join((r.get("channel") or "").split())
            if ch:
                c = channels.setdefault(_fold(ch), {"name": ch, "videos": 0, "days": set(), "weeks": set()})
                c["videos"] += 1
                c["days"].add(day)
                c["weeks"].add(week)
            v = videos.setdefault(media_ingestor.url_hash(r["url"]),
                                  {"title": r.get("title") or r["url"], "channel": ch, "days": set()})
            v["days"].add(day)
    lines = [f"# Watched on {name} · {label}", "",
             f"{total} video{'s' if total != 1 else ''} watched on {name} over {len(days)} "
             f"day{'s' if len(days) != 1 else ''} in {label} ({len(videos)} different), counted from the day-by-day "
             f"watch history — a record to look up, not a conversation.", ""]
    ranked = sorted(channels.values(), key=lambda c: (-c["videos"], -len(c["days"]), c["name"].casefold()))
    if ranked:
        lines += ["## Channels watched most"]
        lines += [f"- {c['name']} — {c['videos']} video{'s' if c['videos'] != 1 else ''} on {len(c['days'])} "
                  f"day{'s' if len(c['days']) != 1 else ''}" for c in ranked[:TOP_CHANNELS]]
        lines.append("")
    returned = sorted((c for c in channels.values() if len(c["weeks"]) >= 2),
                      key=lambda c: (-len(c["weeks"]), -c["videos"], c["name"].casefold()))
    if returned:
        lines += ["## Came back to across weeks"]
        lines += [f"- {c['name']} — in {len(c['weeks'])} different weeks" for c in returned[:TOP_RETURNED]]
        lines.append("")
    again = sorted((v for v in videos.values() if len(v["days"]) >= 2),
                   key=lambda v: (-len(v["days"]), v["title"].casefold()))
    if again:
        lines += ["## Watched on more than one day"]
        for v in again[:TOP_REWATCHED]:
            by = f" — {v['channel']}" if v["channel"] else ""
            on = ", ".join(d.isoformat() for d in sorted(v["days"]))
            lines.append(f"- {v['title']}{by} · {len(v['days'])} days: {on}")
        lines.append("")
    lines += ["## Days"]
    lines += [f"- {d.isoformat()} {_WEEKDAYS[d.weekday()]} · {len(rows)} video{'s' if len(rows) != 1 else ''}"
              for d, rows in days]
    return "\n".join(lines)


def rollup(memory_path: Path, *, months: Iterable[tuple[str, str]] | None = None,
           bank: str | None = None) -> RollupResult:
    """Write each month's summary of watch history as one episode, ``watch-history-month:<platform>:<YYYY-MM>``,
    through the one stager, already read (``processed_by: index``) — never queued for a model. ``months``: only
    these ``(platform, YYYY-MM)``; ``None`` = every month the bank's history holds. A month whose words did not move
    writes nothing (the stager's hash). Pure files; the caller commits ``paths``."""
    out = RollupResult()
    episodes_dir = Path(memory_path) / "episodes"
    if not episodes_dir.is_dir():
        return out
    want = set(months) if months is not None else None
    with episode_staging.STAGE_LOCK, episode_ids.episode_lock(episodes_dir):
        index, _ = episode_staging.scan(episodes_dir)
        grouped: dict[tuple[str, str], list[tuple[date, list[dict], dict]]] = {}
        for sid, entry in index.items():
            parsed = _day_of(sid)
            if parsed is None or entry.fm.get("source_deleted_at"):
                continue
            platform, day = parsed
            key = (platform, _month_key(day))
            if want is not None and key not in want:
                continue
            rows = _rows_of(entry.fm)
            if rows:
                grouped.setdefault(key, []).append((day, rows, entry.fm))
        drafts: list[episode_staging.EpisodeDraft] = []
        for (platform, month), entries in sorted(grouped.items()):
            days = [(d, rows) for d, rows, _ in entries]
            last_day, last_rows, _ = max(entries, key=lambda e: e[0])
            year, mon = int(month[:4]), int(month[5:7])
            drafts.append(episode_staging.EpisodeDraft(
                title=f"Watched on {PLATFORMS[platform]} · {_MONTHS[mon - 1]} {year}",
                source_id=month_source_id(platform, month), source=history_index.MONTH_SOURCE,
                origin=ORIGINS[platform], original_date=last_day.isoformat(),
                timestamp=_timestamp(last_day, last_rows), body=render_month(platform, month, days),
                extra={"platform": platform, "month": month, "days": len(days),
                       "videos": sum(len(r) for _, r in days)},
                queue_for_sleep=False, processed_by=history_index.INDEXED_BY, writer=SCRUB_WRITER))
        if not drafts:
            return out
        staged = episode_staging.stage(drafts, episodes_dir, bank=bank)
    for verdict in staged.verdicts:
        if verdict == "created":
            out.created += 1
        elif verdict == "skipped":
            out.unchanged += 1
        else:
            out.updated += 1
    out.paths = sorted(set(staged.paths))
    return out


# --- a channel with a page: what the history says about it, derived at read (owner ruling 2026-10-18) -------------

#: Per bank: (signature of the history days, {folded channel: totals}). Derived, in memory, never stored.
_CHANNEL_CACHE: dict[str, tuple[tuple, dict[str, dict]]] = {}
_CHANNEL_LOCK = threading.Lock()


def channel_totals(memory_path: Path) -> dict[str, dict]:
    """``{folded channel name: {name, videos, days, first, last, platforms}}`` over every watched day the bank holds.
    Frontmatter only (the cached scan), recomputed only when a day file moved."""
    from api.services import bank_index

    memory_path = Path(memory_path)
    entries = [f for f in bank_index.files(memory_path, "episodes")
               if history_index.kind(f.frontmatter) == "history" and not f.frontmatter.get("source_deleted_at")]
    signature = tuple(sorted((f.path.name, f.mtime_ns, f.size) for f in entries))
    key = str(memory_path)
    with _CHANNEL_LOCK:
        cached = _CHANNEL_CACHE.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1]
    totals: dict[str, dict] = {}
    for f in entries:
        parsed = _day_of(str(f.frontmatter.get("source_id") or ""))
        if parsed is None:
            continue
        platform, day = parsed
        for r in _rows_of(f.frontmatter):
            ch = " ".join((r.get("channel") or "").split())
            if not ch:
                continue
            t = totals.setdefault(_fold(ch), {"name": ch, "videos": 0, "days": set(), "platforms": set()})
            t["videos"] += 1
            t["days"].add(day)
            t["platforms"].add(platform)
    out = {k: {"name": t["name"], "videos": t["videos"], "days": len(t["days"]), "first": min(t["days"]),
               "last": max(t["days"]), "platforms": sorted(t["platforms"])} for k, t in totals.items()}
    with _CHANNEL_LOCK:
        _CHANNEL_CACHE[key] = (signature, out)
    return out


def channel_line(memory_path: Path, names: Iterable[str]) -> str | None:
    """One line for a page whose name or an alias IS a channel in the watch history (exact, case and spacing folded —
    never fuzzy): how much was watched and when, with what it is not. ``None`` for any other page. The history is
    never a mention: this line moves no date, no confidence and no decay clock, and nothing is written."""
    folded = [_fold(str(n)) for n in names if str(n or "").strip()]
    if not folded:
        return None
    totals = channel_totals(memory_path)
    hit = next((totals[n] for n in folded if n in totals), None)
    if hit is None:
        return None
    where = " and ".join(PLATFORMS.get(p, p) for p in hit["platforms"])
    span = (hit["first"].isoformat() if hit["first"] == hit["last"]
            else f"{hit['first'].isoformat()} to {hit['last'].isoformat()}")
    return (f"**Watch history:** {hit['videos']} video{'s' if hit['videos'] != 1 else ''} from a {where} channel "
            f"named {hit['name']}, on {hit['days']} day{'s' if hit['days'] != 1 else ''}, {span} (counted from the "
            "watch history at read time — a record, not a mention: it never keeps this page from fading).")


# --- looking it up: the lines a question about watching is answered from (owner ruling 2026-10-18) ---------------

_ABOUT_WATCHING = re.compile(r"\b(watch(?:ed|es|ing)?|youtube|tiktok|videos?|channels?)\b", re.IGNORECASE)
_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?", re.UNICODE)
_MONTH_NUM = re.compile(r"\b(20\d\d)-(0[1-9]|1[0-2])\b")
_YEAR = re.compile(r"\b(20\d\d)\b")
_LOOKUP_STOP = frozenset("""
a an and any are at be been by can could did do does for from had has have how i in into is it its me my of on or
our that the their them then there these they this those to was we were what when where which while who whom why
with would you your watch watched watches watching youtube tiktok video videos channel channels ever last first
time times again day days week weeks month months year years about show tell list find many much most often some
""".split())
LOOKUP_LIMIT = 40


def is_about_watching(query: str) -> bool:
    return bool(_ABOUT_WATCHING.search(query or ""))


def _asked_month(query: str) -> tuple[int | None, int] | None:
    """``(year or None, month)`` a question names: ``2026-09``, or a month's English name — ``May`` only beside a
    year, where it cannot be the verb."""
    m = _MONTH_NUM.search(query)
    if m:
        return int(m.group(1)), int(m.group(2))
    words = [w.casefold() for w in _WORD.findall(query)]
    year = _YEAR.search(query)
    for i, name in enumerate(_MONTHS, start=1):
        if name.casefold() in words and (name != "May" or year):
            return (int(year.group(1)) if year else None), i
    return None


def lookup(memory_path: Path, query: str, *, limit: int = LOOKUP_LIMIT) -> list[str]:
    """What the watch history says about a question, as dated lines naming their episode — no model, no index
    needed. A question naming a month gets that month's summary; otherwise the watched videos whose title or
    channel holds the question's words (whole words, case folded; the rows matching the most words), oldest first,
    the newest ``limit`` kept. ``[]`` when nothing matches. Frontmatter and summary bodies only."""
    from api.services import bank_index

    memory_path = Path(memory_path)
    files = [f for f in bank_index.files(memory_path, "episodes")
             if history_index.kind(f.frontmatter) in ("history", "month")
             and not f.frontmatter.get("source_deleted_at")]
    if not files:
        return []
    asked = _asked_month(query or "")
    if asked is not None:
        year, mon = asked
        months = sorted((f for f in files if history_index.kind(f.frontmatter) == "month"
                         and str(f.frontmatter.get("month") or "")[5:7] == f"{mon:02d}"
                         and (year is None or str(f.frontmatter.get("month") or "")[:4] == str(year))),
                        key=lambda f: str(f.frontmatter.get("month") or ""), reverse=True)
        lines: list[str] = []
        for f in months[:2]:
            body = [ln for ln in f.body().splitlines() if ln.strip()]
            lines += [f"[{f.stem}] {ln}" for ln in body[:limit]]
        return lines
    tokens = {w.casefold() for w in _WORD.findall(query or "")} - _LOOKUP_STOP
    tokens = {t for t in tokens if len(t) >= 3 or t.isdigit()}
    if not tokens:
        return []
    hits: list[tuple[int, str, str, str]] = []
    for f in files:
        if history_index.kind(f.frontmatter) != "history":
            continue
        parsed = _day_of(str(f.frontmatter.get("source_id") or ""))
        if parsed is None:
            continue
        platform, day = parsed
        for r in _rows_of(f.frontmatter):
            words = {w.casefold() for w in _WORD.findall(f"{r['title']} {r['channel']}")}
            n = len(tokens & words)
            if not n:
                continue
            at = ", ".join(c for c in (_clock(t) for t in r["times"]) if c)
            by = f" — {r['channel']}" if r["channel"] else ""
            line = (f"{day.isoformat()}{' ' + at if at else ''} · {r['title'] or r['url']}{by} "
                    f"({PLATFORMS[platform]}) [{f.stem}]")
            hits.append((n, day.isoformat(), at, line))
    if not hits:
        return []
    best = max(h[0] for h in hits)
    chosen = sorted((h for h in hits if h[0] == best), key=lambda h: (h[1], h[2]))
    if len(chosen) > limit:
        dropped = len(chosen) - limit
        first = chosen[0][1]
        chosen = chosen[-limit:]
        return [f"({dropped} earlier match{'es' if dropped != 1 else ''} not shown; the first on {first})"] + [
            h[3] for h in chosen]
    return [h[3] for h in chosen]


# --- the doors' one tail ---------------------------------------------------------------------------


async def import_history(memory_path: Path, rows: list[RawItem], *, door: str, trigger: str,
                         author: str = "user", channel: str | None = None) -> RecordResult:
    """History rows a parser made (a Takeout export, TikTok's) into their days, committed alone under ``author``.
    For the upload route and the command line; the file work runs off the event loop."""
    import asyncio

    from api.services import folder_source

    watches, _dropped = from_items(rows, door=door)
    for w in watches:
        if w.platform == "tiktok":
            w.door = "export"   # TikTok's own export, not a Takeout
    memory_path = Path(memory_path)
    result = await asyncio.to_thread(record, memory_path, watches, bank=memory_path.name)
    if result.paths:
        await folder_source.commit_paths_for(memory_path, result.paths, subject="Watch history", trigger=trigger,
                                             author=author, channel=channel)
    return result


def summary(result: RecordResult) -> str:
    """One sentence for a door's reply."""
    days = result.days_created + result.days_updated
    if not result.added and not days:
        return "No new watch history: every watch was already in memory."
    return (f"{result.added:,} watch{'es' if result.added != 1 else ''} of history kept across {days:,} "
            f"day{'s' if days != 1 else ''} (one entry per day, not saves).")


def totals(memory_path: Path, platform: str = "youtube") -> tuple[int, int]:
    """``(videos, days)`` the bank's history holds for a platform — summed from the days' frontmatter (one cached
    read of the episodes directory, ``bank_index``), for a channel row's count."""
    episodes_dir = Path(memory_path) / "episodes"
    if not episodes_dir.is_dir():
        return 0, 0
    index, _ = episode_staging.scan(episodes_dir)
    prefix = f"{SOURCE_PREFIX}{platform}:"
    videos = days = 0
    for sid, entry in index.items():
        if sid.startswith(prefix) and not entry.fm.get("source_deleted_at"):
            days += 1
            try:
                videos += int(entry.fm.get("videos") or 0)
            except (TypeError, ValueError):
                continue
    return videos, days


# --- the browser door (the app reads Chrome's History on this Mac) -------------------------------------------------

#: Browsers whose History file the app reads, and the channel each sync is recorded under.
BROWSERS: dict[str, str] = {"chrome": "Chrome"}
#: At most this many visits in one request (Chrome keeps about 90 days; the app sends past a cursor, in batches).
MAX_VISITS = 20_000
_PROFILE = re.compile(r"^(Default|Profile \d{1,3})$")


class PayloadError(ValueError):
    """A request the backend cannot trust — answered 422, nothing written."""


def channel_id(browser: str) -> str:
    return f"{browser}-youtube-history"


def sync_browser(memory_path: Path, payload: dict, *, bank: str | None = None) -> dict:
    """The YouTube videos watched in a browser, as the app read them from the browser's own History on this Mac.

    The app sends YouTube watch pages only (its query names them); this re-checks every row, so a page that is not
    a YouTube video — another site, a YouTube search or channel page — is counted and dropped, never written.
    Returns the counts and the bank-relative ``paths`` to commit."""
    browser = str(payload.get("browser") or "").strip().lower()
    if browser not in BROWSERS:
        raise PayloadError(f"watch history is read from {', '.join(BROWSERS)} only")
    profile = str(payload.get("profile") or "Default").strip()
    if not _PROFILE.match(profile):
        raise PayloadError("profile must be the browser's own profile folder name")
    visits = payload.get("visits") or []
    watches: list[Watch] = []
    ignored = 0
    for visit in visits:
        if not isinstance(visit, dict):
            ignored += 1
            continue
        at = visit.get("visited_at")
        w = make(visit.get("url"), at=at, title=visit.get("title"), door="chrome") if at else None
        if w is None or w.platform != "youtube":
            ignored += 1
            continue
        watches.append(w)
    result = record(Path(memory_path), watches, bank=bank)
    videos, days = totals(Path(memory_path), "youtube")
    return {"received": len(visits), "kept": result.kept, "ignored": ignored, "added": result.added,
            "days_created": result.days_created, "days_updated": result.days_updated,
            "days_unchanged": result.days_unchanged, "paths": result.paths,
            "videos": videos, "days": days}
