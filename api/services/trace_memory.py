"""What activity traces put into memory (G218) — only what the person's switches promote, through writers that exist.

Traces live outside every bank (:mod:`trace_store`). Two things cross into the active bank, each by its own switch,
never a model at capture:

* **YouTube views** (``youtube_to_watch_history``, on with traces): a span whose URL is a YouTube video, in front for at
  least :data:`MIN_WATCH`, becomes a watch in the existing watch-history writer (G71, ``watch_history.record``) —
  ``via: traces``, the same video identity every other door uses, with ``dwell_s``: how long it was in front that day,
  counted from the store. So "what was that video at 15:20" is answered by the watched day Ask and recall already read,
  index-only like every watched day (ruling 30).
* **A day summary** (``daily_summary``, off by default, because it puts window titles into git): one episode per
  finished local day, ``source: traces-day``, counted with no model — time per app, the sites with the most time, the
  longest stretches. Index-only (``history_index.kind`` → ``traces``) unless the person also turns on
  ``learn_from_summary``, the only way a model ever reads anything traces hold; even then the summary is a record, not
  the person's words (``evidence_kind: assistant``), and it is never a mention (``episode_time.UNTIMED_SOURCES``).

A demo bank receives nothing (``demo_guard``). The caller commits the returned paths.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from api.services import demo_guard, episode_ids, episode_staging, history_index, media_ingestor, watch_history
from api.services.trace_store import TraceStore, local_day, parse_instant

#: A YouTube page in front for less than this is a click, not a watch (G156: a stray click is not a memory).
MIN_WATCH = timedelta(seconds=20)
SOURCE = "traces-day"
SOURCE_PREFIX = "traces-day:"
ORIGIN = "traces"
SCRUB_WRITER = "traces-day"
TOP_APPS = 10
TOP_SITES = 10
LONGEST = 5


def _video(url: str | None) -> str | None:
    found = watch_history.watch_url(url)
    return found[1] if found and found[0] == "youtube" else None


def youtube_watches(store: TraceStore, pages: list[dict]) -> list[watch_history.Watch]:
    """The new spans that are YouTube watches, each with the day's dwell for that video counted from the store."""
    fresh: list[tuple[str, dict]] = []
    for row in pages:
        canonical = _video(row.get("url"))
        start, end = parse_instant(row.get("start")), parse_instant(row.get("end"))
        if canonical and start and end and end - start >= MIN_WATCH:
            fresh.append((canonical, row))
    if not fresh:
        return []
    dwell: dict[tuple[str, date], int] = defaultdict(int)
    for day in sorted({local_day(parse_instant(r["start"])) for _, r in fresh}):
        for span in store.spans_between(day, day):
            canonical = _video(span.get("url"))
            start, end = parse_instant(span.get("start")), parse_instant(span.get("end"))
            if canonical and start and end:
                dwell[(media_ingestor.url_hash(canonical), day)] += int((end - start).total_seconds())
    out: list[watch_history.Watch] = []
    for canonical, row in fresh:
        w = watch_history.make(canonical, at=row["start"], title=row.get("title"), door="traces")
        if w is None:
            continue
        w.dwell_s = dwell.get((w.key, w.day), 0)
        out.append(w)
    return out


# --- the day summary ---------------------------------------------------------------------------------------------


def _minutes(seconds: float) -> str:
    m = int(round(seconds / 60))
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h {m % 60} min" if m % 60 else f"{m // 60} h"


def _clock(stamp: str) -> str:
    t = parse_instant(stamp)
    return t.astimezone().strftime("%H:%M") if t else ""


def render_day(day: date, spans: list[dict]) -> str | None:
    """The day, counted: no model, no screenshot text, titles only where the store kept one."""
    by_app: dict[str, float] = defaultdict(float)
    by_site: dict[str, float] = defaultdict(float)
    timed: list[tuple[float, dict]] = []
    for s in spans:
        start, end = parse_instant(s.get("start")), parse_instant(s.get("end"))
        if not start or not end:
            continue
        seconds = (end - start).total_seconds()
        by_app[str(s.get("app") or s.get("bundle_id") or "?")] += seconds
        if s.get("host"):
            by_site[str(s["host"]).removeprefix("www.")] += seconds
        timed.append((seconds, s))
    total = sum(by_app.values())
    if total < 60:
        return None
    lines = [f"# On this Mac · {day.strftime('%A')} {day.isoformat()}", "",
             f"{_minutes(total)} in front of this Mac, counted from activity traces with no model — what was on "
             "screen, not something said or saved.", "", "## Time by app", ""]
    for app, seconds in sorted(by_app.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_APPS]:
        if seconds >= 60:
            lines.append(f"- {app} — {_minutes(seconds)}")
    sites = [(h, s) for h, s in sorted(by_site.items(), key=lambda kv: (-kv[1], kv[0])) if s >= 60][:TOP_SITES]
    if sites:
        lines += ["", "## Sites with the most time", ""]
        lines += [f"- {host} — {_minutes(seconds)}" for host, seconds in sites]
    longest = [s for seconds, s in sorted(timed, key=lambda t: -t[0])[:LONGEST] if seconds >= 300]
    if longest:
        lines += ["", "## Longest stretches", ""]
        for s in sorted(longest, key=lambda r: r["start"]):
            what = f" · {s['title']}" if s.get("title") else ""
            lines.append(f"- {_clock(s['start'])}–{_clock(s['end'])} · {s.get('app') or s.get('bundle_id')}{what}")
    return "\n".join(lines)


def write_digests(memory_path: Path, store: TraceStore, values: dict, *, now: datetime | None = None,
                  bank: str | None = None) -> list[str]:
    """One summary per finished day the store holds and the summary has not covered yet. Returns bank-relative paths
    to commit. Runs at most once a day per day (``digest_through``), so a sync a minute costs a settings read."""
    if not values.get("daily_summary"):
        return []
    moment = now or datetime.now(timezone.utc)
    yesterday = local_day(moment) - timedelta(days=1)
    through = values.get("digest_through")
    try:
        done = date.fromisoformat(str(through)) if through else None
    except ValueError:
        done = None
    if done is not None and done >= yesterday:
        return []
    learn = bool(values.get("learn_from_summary"))
    days = [date.fromisoformat(d) for d in store.days()]
    todo = [d for d in days if d <= yesterday and (done is None or d > done)]
    drafts: list[episode_staging.EpisodeDraft] = []
    for day in todo:
        spans = store.spans_between(day, day)
        body = render_day(day, spans)
        if body is None:
            continue
        first = min(parse_instant(s["start"]) for s in spans if parse_instant(s.get("start")))
        drafts.append(episode_staging.EpisodeDraft(
            title=f"On this Mac · {day.isoformat()}", source_id=f"{SOURCE_PREFIX}{day.isoformat()}", source=SOURCE,
            origin=ORIGIN, original_date=day.isoformat(), timestamp=episode_ids.to_utc_iso(first),
            body=body,
            # A counted record, never the person's own words; the switch it was written under travels with it.
            extra={"traces_day": day.isoformat(), "evidence_kind": "assistant", "learn_from_traces": learn},
            queue_for_sleep=learn,
            processed_by=history_index.INDEXED_BY if not learn else episode_staging.PARSED_ONLY,
            writer=SCRUB_WRITER))
    paths: list[str] = []
    if drafts:
        episodes_dir = Path(memory_path) / "episodes"
        episodes_dir.mkdir(parents=True, exist_ok=True)
        with episode_staging.STAGE_LOCK, episode_ids.episode_lock(episodes_dir):
            staged = episode_staging.stage(drafts, episodes_dir, bank=bank)
        paths = list(staged.paths)
    store.set_digest_through(yesterday)
    return paths


def promote(memory_path: Path, store: TraceStore, pages: list[dict], values: dict, *,
            now: datetime | None = None, bank: str | None = None) -> list[str]:
    """Everything a sync may put into the active bank: YouTube watches and, behind its switch, the day summaries.
    Nothing for a demo bank. Returns bank-relative paths for the caller's one commit."""
    if demo_guard.is_demo(Path(memory_path)):
        return []
    paths: list[str] = []
    if values.get("youtube_to_watch_history", True):
        watches = youtube_watches(store, pages)
        if watches:
            paths += watch_history.record(Path(memory_path), watches, bank=bank).paths
    paths += write_digests(Path(memory_path), store, values, now=now, bank=bank)
    return sorted(set(paths))
