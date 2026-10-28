"""What activity traces put into memory (G218) — only what the person's switches promote, through writers that exist.

Traces live outside every bank (:mod:`trace_store`). Two things cross into the active bank, each by its own switch,
never a model at capture (2026-10-28, the traces redesign):

* **What you watch and read** (``watch_and_read``, on with traces; generalises ruling 39b from YouTube to every site).
  A page an allowed browser had in front is kept by what it is, never by which site it is on:

  - a **video page** of a platform Cicada knows (``watch_history.watch_url``: YouTube, TikTok), in front for at least
    :data:`MIN_WATCH`, joins the existing watch-history writer (G71, ``watch_history.record``) — ``via: traces``, the
    same video identity every other door uses, with ``dwell_s``;
  - **any other page**, in front for at least :data:`MIN_READ` that day, joins that day's **reading record** — one
    episode per local day (``source: reading-history``, ``reading-history:<day>``): the address (already cleaned by
    ``trace_policy.clean_url``: no query but content keys), its title where the store kept one, its site, when it was
    first in front and for how long. Recomputed from the store for each day new pages touched, so it is idempotent and
    a re-sent span changes nothing.

  Both are **index-only** (ruling 30, ``history_index``): looked up by Ask, recall and the timeline, never read by a
  model, never a mention (a watched or read day is not the person saying anything). Excluded sites and private windows
  never reach the store, so they never reach here.
* **Learn from my day** (``learn_from_day``, off by default — one switch for the old ``daily_summary`` +
  ``learn_from_summary``). One digest per finished local day, ``source: traces-day``, **counted with no model**: time
  on the person's own projects (attributed deterministically, :func:`attribute`), reading, watching and calls by fixed
  lists, and everything else as app names and how often apps switched at the busiest hour. **No window title, no
  address, no screenshot text** is ever in it. Sleep reads it (the only thing a model ever reads from traces); it is a
  record, not the person's words (``evidence_kind: assistant``), and never a mention
  (``episode_time.UNTIMED_SOURCES``). :func:`preview` is the same digest, computed for one day, for the page to show
  before the switch is on.

**Remove from memory** (:func:`remove`) takes back every open belief and progress note whose evidence is only
``traces-day`` digests, as one commit, and :func:`undo` puts them back while they are as it left them.

A demo bank receives nothing (``demo_guard``). The caller commits the returned paths.
"""
from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from api.services import (bank_index, demo_guard, episode_ids, episode_staging, fact_sources, history_index,
                          markdown_parser, media_ingestor, page_lock, project_birth, project_ownership, trace_store,
                          watch_history)
from api.services.trace_store import TraceStore, local_day, parse_instant

#: A video page in front for less than this is a click, not a watch (G156: a stray click is not a memory).
MIN_WATCH = timedelta(seconds=20)
#: A page in front for less than this, summed over the day, is a skim, not a read (G156's minimum dwell). Thirty
#: seconds keeps a page someone stayed on and drops the tab flicked past on the way to another.
MIN_READ = timedelta(seconds=30)
#: At most this many pages in one day's reading record, the longest-read first (a heavy day is ~150).
MAX_READ_PER_DAY = 300
#: Today's reading record is rewritten (and committed) at most this often; a finished day at once.
READING_EVERY = timedelta(minutes=15)
TITLE_CAP = 200
SOURCE = "traces-day"
SOURCE_PREFIX = "traces-day:"
READING_SOURCE = "reading-history"
READING_PREFIX = "reading-history:"
ORIGIN = "traces"
SCRUB_WRITER = "traces-day"
READING_WRITER = "reading-history"
#: The digest's lists stop here (apps, sites, projects).
TOP = 8
#: What the digest counts as a call, a read or a watch — fixed lists, no model (owner 2026-10-28: deterministic).
CALL_APPS = frozenset({"us.zoom.xos", "com.apple.FaceTime", "com.microsoft.teams", "com.microsoft.teams2",
                       "com.cisco.webexmeetingsapp", "com.cisco.webex.meetings", "com.ringcentral.glip"})
CALL_HOSTS = frozenset({"meet.google.com", "zoom.us", "teams.microsoft.com", "teams.live.com", "whereby.com",
                        "meet.jit.si", "webex.com"})
READING_APPS = frozenset({"com.apple.Preview", "com.adobe.Reader", "com.adobe.Acrobat.Pro",
                          "net.sourceforge.skim-app.skim", "com.apple.iBooksX", "com.amazon.Lassen",
                          "com.readdle.PDFExpert-Mac"})
#: Code hosts whose ``/<owner>/<repo>`` path names a repository.
CODE_HOSTS = frozenset({"github.com", "gitlab.com", "bitbucket.org", "codeberg.org", "sr.ht", "git.sr.ht"})
#: A call's spans closer than this are one call.
CALL_GAP = timedelta(minutes=5)
#: A folder or repository name shorter than this, or one of these, names too much to attribute time by.
MIN_TOKEN = 4
GENERIC_FOLDERS = frozenset({"code", "src", "source", "projects", "project", "repos", "repo", "work", "home",
                             "desktop", "documents", "downloads", "github", "dev", "main", "master", "app", "apps",
                             "test", "tests", "docs", "notes", "tmp", "temp", "untitled"})


def _host(row: dict) -> str:
    return str(row.get("host") or urlparse(str(row.get("url") or "")).hostname or "").lower().removeprefix("www.")


def _seconds(row: dict) -> float:
    start, end = parse_instant(row.get("start")), parse_instant(row.get("end"))
    return (end - start).total_seconds() if start and end and end > start else 0.0


def _site_in(host: str, sites: frozenset[str]) -> bool:
    return any(host == s or host.endswith("." + s) for s in sites)


# --- what you watch and read ---------------------------------------------------------------------------------------


def _video(url: str | None) -> tuple[str, str] | None:
    found = watch_history.watch_url(url)
    return found if found and found[0] in watch_history.PLATFORMS else None


def watches(store: TraceStore, pages: list[dict]) -> list[watch_history.Watch]:
    """The new spans that are video watches on any platform Cicada knows, each with the day's dwell for that video
    counted from the store."""
    fresh: list[tuple[str, dict]] = []
    for row in pages:
        found = _video(row.get("url"))
        start, end = parse_instant(row.get("start")), parse_instant(row.get("end"))
        if found and start and end and end - start >= MIN_WATCH:
            fresh.append((found[1], row))
    if not fresh:
        return []
    dwell: dict[tuple[str, date], int] = defaultdict(int)
    for day in sorted({local_day(parse_instant(r["start"])) for _, r in fresh}):
        for span in store.spans_between(day, day):
            found = _video(span.get("url"))
            if found:
                dwell[(media_ingestor.url_hash(found[1]), day)] += int(_seconds(span))
    out: list[watch_history.Watch] = []
    for canonical, row in fresh:
        w = watch_history.make(canonical, at=row["start"], title=row.get("title"), door="traces")
        if w is None:
            continue
        w.dwell_s = dwell.get((w.key, w.day), 0)
        out.append(w)
    return out


#: Kept for callers of the YouTube-only name (Hyrum): it is :func:`watches`.
youtube_watches = watches


def read_rows(spans: list[dict]) -> list[dict]:
    """A day's pages read — every page that is not a video, a call or a site left out, in front for
    :data:`MIN_READ` or more over the day. One row per address, the longest-read first, capped."""
    by_url: dict[str, dict] = {}
    for s in spans:
        url = s.get("url")
        if not url or _video(url) is not None or _site_in(_host(s), CALL_HOSTS):
            continue
        seconds = _seconds(s)
        if seconds <= 0:
            continue
        row = by_url.setdefault(url, {"url": url, "host": _host(s), "first": s["start"], "dwell_s": 0})
        row["dwell_s"] += int(seconds)
        if s.get("title") and not row.get("title"):
            row["title"] = str(s["title"])[:TITLE_CAP]
        if s["start"] < row["first"]:
            row["first"] = s["start"]
    rows = [r for r in by_url.values() if r["dwell_s"] >= MIN_READ.total_seconds()]
    rows.sort(key=lambda r: (-r["dwell_s"], r["first"]))
    return rows[:MAX_READ_PER_DAY]


def render_reading(day: date, rows: list[dict]) -> str:
    sites = len({r["host"] for r in rows})
    lines = [f"# Read on this Mac · {day.strftime('%A')} {day.isoformat()}", "",
             f"{len(rows)} page{'s' if len(rows) != 1 else ''} on {sites} site{'s' if sites != 1 else ''}, from "
             "activity traces with no model — what was in front, not something said or saved.", ""]
    for r in sorted(rows, key=lambda r: r["first"]):
        title = f" · {r['title']}" if r.get("title") else ""
        lines.append(f"- {_clock(r['first'])} · {_minutes(r['dwell_s'])} · {r['host']}{title} · {r['url']}")
    return "\n".join(lines)


def write_reading(memory_path: Path, store: TraceStore, days: set[date], *, until: datetime,
                  bank: str | None = None) -> list[str]:
    """Rewrite the reading record of each day new pages touched, from the store (only spans ended by ``until``, so
    nothing inside the forget window). Index-only; the stager skips a day whose words did not move."""
    drafts: list[episode_staging.EpisodeDraft] = []
    for day in sorted(days):
        spans = [s for s in store.spans_between(day, day)
                 if (parse_instant(s.get("end")) or until) <= until and local_day(parse_instant(s["start"])) == day]
        rows = read_rows(spans)
        if not rows:
            continue
        first = min(parse_instant(r["first"]) for r in rows)
        drafts.append(episode_staging.EpisodeDraft(
            title=f"Read on this Mac · {day.isoformat()}", source_id=f"{READING_PREFIX}{day.isoformat()}",
            source=READING_SOURCE, origin=ORIGIN, original_date=day.isoformat(), timestamp=episode_ids.to_utc_iso(first),
            body=render_reading(day, rows),
            extra={"read_on": day.isoformat(), "pages": len(rows), "evidence_kind": "assistant"},
            # Like a watched day (ruling 30): indexed, never read by a model.
            queue_for_sleep=False, processed_by=history_index.INDEXED_BY, writer=READING_WRITER))
    if not drafts:
        return []
    episodes_dir = Path(memory_path) / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    with episode_staging.STAGE_LOCK, episode_ids.episode_lock(episodes_dir):
        staged = episode_staging.stage(drafts, episodes_dir, bank=bank)
    return list(staged.paths)


def _due_reading(memory_path: Path, store: TraceStore, *, until: datetime, bank: str | None) -> list[str]:
    """Write the reading days waiting (``reading_pending``) once :data:`READING_EVERY` has passed since the last write,
    or at once for a day that is already over — so a sync a minute rewrites and commits a reading day at most four
    times an hour (measured: rewriting it on every sync doubled the promoting sync's p50)."""
    values = store.settings()
    pending = sorted({date.fromisoformat(d) for d in values.get("reading_pending") or [] if _is_day(d)})
    if not pending:
        return []
    last = parse_instant(values.get("reading_written_at"))
    today = local_day(until)
    if last is not None and until - last < READING_EVERY and all(d >= today for d in pending):
        return []
    paths = write_reading(memory_path, store, set(pending), until=until, bank=bank)
    store.reading_written(until)
    return paths


def _is_day(value) -> bool:
    try:
        date.fromisoformat(str(value))
        return True
    except ValueError:
        return False


# --- the person's projects, for attribution ---------------------------------------------------------------------


@dataclass
class ProjectKey:
    """What ties time to one of the person's own projects: folder and repository names, and the addresses tied to it
    by hand. Nothing else — never a name guessed from a title."""
    id: str
    name: str
    folders: set[str] = field(default_factory=set)
    urls: list[str] = field(default_factory=list)


def _folder_name(path: str) -> str | None:
    """A folder's own name from its path as written (``~/src/alpha-project`` → ``alpha-project``; a worktree's is its
    repository's, as ``project_birth.repo_names`` reads one) — from the string alone, never a stat."""
    parts = [p for p in re.split(r"[\\/]", str(path or "").strip()) if p and p not in (".", "~")]
    name = parts[-1] if parts else ""
    for i, part in enumerate(parts):
        if part in project_birth._WORKTREE_DIRS and i:
            name = parts[i - 1]
            break
    name = name.strip().lower()
    return name if len(name) >= MIN_TOKEN and name not in GENERIC_FOLDERS else None


def _url_key(url: str) -> str:
    try:
        p = urlparse(url if "://" in url else "https://" + url)
    except ValueError:
        return ""
    host = (p.hostname or "").lower().removeprefix("www.")
    return f"{host}{(p.path or '').rstrip('/')}".lower() if host else ""


def _logged_progress(page: Path) -> bool:
    """Ruling 45's last door, derived on read like the Projects page does: the person logged progress on it in the app."""
    from api.services.claims import parse_claims

    try:
        # Cheap first: a page whose bytes never name the app's progress origin cannot pass (measured on a copy of the
        # owner's bank, 707 project pages: parsing each took ~95 ms warm; this read ~10).
        if project_ownership._HUMAN_PROGRESS_ORIGIN not in page.read_text(encoding="utf-8", errors="replace"):
            return False
        return project_ownership.logged_progress(parse_claims(markdown_parser.parse(page).body))
    except Exception:  # noqa: BLE001 — an unreadable page is not the person's by this door
        return False


def owned_projects(memory_path: Path) -> list[ProjectKey]:
    """The person's own projects (ruling 45, ``project_ownership.is_mine``), each with its folders (``paths:``), the
    repositories it declares (``repos:``) or was born from (``born.repo``), and the local paths and addresses the
    person tied to it as sources (trusted ``path``/``repo``/``url`` sources — never a proposal)."""
    out: list[ProjectKey] = []
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        if fm.get("type") != "project" or fm.get("status") in ("archived", "dropped"):
            continue
        if not project_ownership.is_mine(fm) and not _logged_progress(f.path):
            continue
        key = ProjectKey(id=f.path.stem, name=str(fm.get("name") or f.path.stem))
        for p in fm.get("paths") or []:
            if isinstance(p, dict) and p.get("path"):
                key.folders.add(_folder_name(str(p["path"])) or "")
        for r in fm.get("repos") or []:
            path = r.get("path") if isinstance(r, dict) else r
            if path:
                key.folders.add(_folder_name(str(path)) or "")
        born_repo = (fm.get("born") or {}).get("repo") if isinstance(fm.get("born"), dict) else None
        if isinstance(born_repo, dict) and born_repo.get("name"):
            key.folders.add(_folder_name(str(born_repo["name"])) or "")
        for s in fact_sources.as_sources(fm.get("sources")):
            if not fact_sources.trusted(s) or fact_sources.is_proposed(s):
                continue
            ref = str(s.get("ref") or "")
            kind = str(s.get("kind") or fact_sources.infer_kind(ref))
            if kind in (fact_sources.KIND_PATH, fact_sources.KIND_REPO):
                key.folders.add(_folder_name(ref) or "")
            elif kind == fact_sources.KIND_URL and _url_key(ref):
                key.urls.append(_url_key(ref))
        key.folders.discard("")
        if key.folders or key.urls:
            out.append(key)
    return out


def _token_in(token: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text) is not None


def attribute(span: dict, projects: list[ProjectKey]) -> str | None:
    """The project this span's time belongs to, or ``None``. A span is a project's when its window title names one of
    the project's folder or repository names as a whole word, its address is that repository on a code host, or its
    address is at or under an address tied to the project. The longest match wins; two projects matching equally
    leave the span unattributed — never guessed."""
    title = str(span.get("title") or "").lower()
    url = str(span.get("url") or "")
    url_key = _url_key(url) if url else ""
    host = _host(span)
    repo_seg = ""
    if host in CODE_HOSTS:
        parts = [p for p in (urlparse(url).path or "").split("/") if p]
        repo_seg = parts[1].lower().removesuffix(".git") if len(parts) >= 2 else ""
    best: tuple[int, str] | None = None
    tied = False
    for p in projects:
        score = 0
        for folder in p.folders:
            if (title and _token_in(folder, title)) or folder == repo_seg:
                score = max(score, len(folder))
        for tie in p.urls:
            if url_key and (url_key == tie or url_key.startswith(tie + "/")):
                score = max(score, len(tie))
        if not score:
            continue
        if best is None or score > best[0]:
            best, tied = (score, p.id), False
        elif score == best[0] and p.id != best[1]:
            tied = True
    return None if best is None or tied else best[1]


# --- the day's digest ---------------------------------------------------------------------------------------------


def _minutes(seconds: float) -> str:
    m = int(round(seconds / 60))
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h {m % 60} min" if m % 60 else f"{m // 60} h"


def _clock(stamp: str) -> str:
    t = parse_instant(stamp)
    return t.astimezone().strftime("%H:%M") if t else ""


def count_day(day: date, spans: list[dict], projects: list[ProjectKey]) -> dict | None:
    """The day, counted — no model, no title, no address, no screenshot text. ``None`` under a minute in front."""
    timed = sorted((s for s in spans if _seconds(s) > 0), key=lambda s: s["start"])
    total = sum(_seconds(s) for s in timed)
    if total < 60:
        return None
    names = {p.id: p.name for p in projects}
    proj: dict[str, dict] = {}
    reading = {"seconds": 0.0, "pages": set(), "sites": defaultdict(float), "apps": set()}
    watching = {"seconds": 0.0, "videos": set(), "platforms": set()}
    calls = {"seconds": 0.0, "count": 0, "apps": set()}
    rest_apps: dict[str, float] = defaultdict(float)
    rest = 0.0
    last_call_end: datetime | None = None
    switches: dict[str, int] = defaultdict(int)
    for s in timed:
        seconds = _seconds(s)
        app = str(s.get("app") or s.get("bundle_id") or "?")
        bundle = str(s.get("bundle_id") or "")
        host = _host(s)
        start = parse_instant(s["start"])
        switches[start.astimezone().strftime("%H")] += 1
        pid = attribute(s, projects)
        if pid is not None:
            row = proj.setdefault(pid, {"id": pid, "name": names.get(pid, pid), "seconds": 0.0, "apps": defaultdict(float)})
            row["seconds"] += seconds
            row["apps"][app] += seconds
            continue
        if bundle in CALL_APPS or (host and _site_in(host, CALL_HOSTS)):
            calls["seconds"] += seconds
            calls["apps"].add(app if bundle in CALL_APPS else host)
            if last_call_end is None or start - last_call_end > CALL_GAP:
                calls["count"] += 1
            last_call_end = parse_instant(s["end"])
            continue
        video = _video(s.get("url"))
        if video is not None:
            watching["seconds"] += seconds
            watching["videos"].add(video[1])
            watching["platforms"].add(watch_history.PLATFORMS[video[0]])
            continue
        if s.get("url") or bundle in READING_APPS:
            reading["seconds"] += seconds
            if s.get("url"):
                reading["pages"].add(s["url"])
                reading["sites"][host] += seconds
            else:
                reading["apps"].add(app)
            continue
        rest += seconds
        rest_apps[app] += seconds
    projects_out = sorted(({"id": r["id"], "name": r["name"], "seconds": int(r["seconds"]),
                            "apps": [a for a, _ in sorted(r["apps"].items(), key=lambda kv: -kv[1])][:3]}
                           for r in proj.values() if r["seconds"] >= 60), key=lambda r: -r["seconds"])[:TOP]
    sites = [h for h, sec in sorted(reading["sites"].items(), key=lambda kv: (-kv[1], kv[0])) if sec >= 60][:5]
    return {
        "day": day.isoformat(),
        "total_seconds": int(total),
        "projects": projects_out,
        "reading": {"seconds": int(reading["seconds"]), "pages": len(reading["pages"]), "sites": sites,
                    "site_count": len(reading["sites"]), "apps": sorted(reading["apps"])},
        "watching": {"seconds": int(watching["seconds"]), "videos": len(watching["videos"]),
                     "platforms": sorted(watching["platforms"])},
        "calls": {"seconds": int(calls["seconds"]), "count": calls["count"], "apps": sorted(calls["apps"])},
        "else": {"seconds": int(rest),
                 "apps": [a for a, sec in sorted(rest_apps.items(), key=lambda kv: (-kv[1], kv[0])) if sec >= 60][:TOP],
                 "busiest_switches": max(switches.values()) if switches else 0},
    }


def render_counts(c: dict) -> str:
    day = date.fromisoformat(c["day"])
    lines = [f"# On this Mac · {day.strftime('%A')} {day.isoformat()}", "",
             f"{_minutes(c['total_seconds'])} in front of this Mac, counted from activity traces with no model — what "
             "was on screen, not something said or saved. Time is matched to a project only through its folders, its "
             "repository or an address tied to it.", ""]
    if c["projects"]:
        lines += ["## Your projects", ""]
        lines += [f"- {p['name']} — {_minutes(p['seconds'])}" + (f" ({', '.join(p['apps'])})" if p["apps"] else "")
                  for p in c["projects"]]
        lines.append("")
    r = c["reading"]
    if r["seconds"] >= 60:
        what = []
        if r["pages"]:
            what.append(f"{r['pages']} page{'s' if r['pages'] != 1 else ''} on {r['site_count']} "
                        f"site{'s' if r['site_count'] != 1 else ''}")
        if r["apps"]:
            what.append(", ".join(r["apps"]))
        lines += ["## Reading", "", f"- {_minutes(r['seconds'])}: {'; '.join(what)}"]
        if r["sites"]:
            lines.append(f"- Most time on {', '.join(r['sites'])}")
        lines.append("")
    w = c["watching"]
    if w["seconds"] >= 60:
        lines += ["## Watching", "", f"- {_minutes(w['seconds'])}: {w['videos']} video{'s' if w['videos'] != 1 else ''}"
                  + (f" ({', '.join(w['platforms'])})" if w["platforms"] else ""), ""]
    k = c["calls"]
    if k["seconds"] >= 60:
        lines += ["## Calls", "", f"- {_minutes(k['seconds'])}: {k['count']} call{'s' if k['count'] != 1 else ''}"
                  + (f" ({', '.join(k['apps'])})" if k["apps"] else ""), ""]
    e = c["else"]
    lines += ["## Everything else", "", f"- {_minutes(e['seconds'])}" + (f": {', '.join(e['apps'])}" if e["apps"] else "")]
    if e["busiest_switches"]:
        lines.append(f"- At the busiest hour, {e['busiest_switches']} switches between apps")
    return "\n".join(lines).rstrip() + "\n"


def render_day(day: date, spans: list[dict], projects: list[ProjectKey] | None = None) -> str | None:
    """The digest Sleep reads for ``day`` (and the preview shows): :func:`count_day` in words."""
    counted = count_day(day, spans, projects or [])
    return render_counts(counted) if counted else None


def preview(memory_path: Path, store: TraceStore, day: date) -> dict:
    """Exactly what Sleep would read for ``day`` — computed here, with no model, before the switch is on."""
    spans = store.spans_between(day, day)
    counted = count_day(day, spans, owned_projects(memory_path))
    return {"day": day.isoformat(), "counts": counted, "text": render_counts(counted) if counted else None}


def write_digests(memory_path: Path, store: TraceStore, values: dict, *, now: datetime | None = None,
                  bank: str | None = None) -> list[str]:
    """One digest per finished day the store holds and the digest has not covered yet, behind ``learn_from_day``.
    Returns bank-relative paths to commit. Runs at most once a day per day (``digest_through``), so a sync a minute
    costs a settings read."""
    if not values.get("learn_from_day"):
        return []
    moment = now or datetime.now(timezone.utc)
    # A day is summarised only once its last moments are past the forget window too (B1).
    yesterday = local_day(moment - trace_store.PROMOTE_HOLD) - timedelta(days=1)
    through = values.get("digest_through")
    try:
        done = date.fromisoformat(str(through)) if through else None
    except ValueError:
        done = None
    if done is not None and done >= yesterday:
        return []
    days = [date.fromisoformat(d) for d in store.days()]
    todo = [d for d in days if d <= yesterday and (done is None or d > done)]
    projects = owned_projects(memory_path) if todo else []
    drafts: list[episode_staging.EpisodeDraft] = []
    for day in todo:
        spans = store.spans_between(day, day)
        body = render_day(day, spans, projects)
        if body is None:
            continue
        first = min(parse_instant(s["start"]) for s in spans if parse_instant(s.get("start")))
        drafts.append(episode_staging.EpisodeDraft(
            title=f"On this Mac · {day.isoformat()}", source_id=f"{SOURCE_PREFIX}{day.isoformat()}", source=SOURCE,
            origin=ORIGIN, original_date=day.isoformat(), timestamp=episode_ids.to_utc_iso(first),
            body=body,
            # A counted record, never the person's own words; the switch it was written under travels with it.
            extra={"traces_day": day.isoformat(), "evidence_kind": "assistant", "learn_from_traces": True},
            queue_for_sleep=True, processed_by=episode_staging.PARSED_ONLY, writer=SCRUB_WRITER))
    paths: list[str] = []
    if drafts:
        episodes_dir = Path(memory_path) / "episodes"
        episodes_dir.mkdir(parents=True, exist_ok=True)
        with episode_staging.STAGE_LOCK, episode_ids.episode_lock(episodes_dir):
            staged = episode_staging.stage(drafts, episodes_dir, bank=bank)
        paths = list(staged.paths)
    store.set_digest_through(yesterday)
    return paths


def promote(memory_path: Path, store: TraceStore, values: dict, *, now: datetime | None = None,
            bank: str | None = None) -> list[str]:
    """Everything a sync may put into the active bank: what was watched and read and, behind its switch, the digests.

    **Held until forget can no longer reach it** (review of #456, B1): only spans that ended at least
    ``trace_store.PROMOTE_HOLD`` ago are offered, from the store, past a cursor (``promoted_through``) — so "Forget the
    last 15 minutes" always runs before anything it covers reaches the bank or git. Nothing for a demo bank (the
    cursor does not move there, so the watches wait for the real bank). Returns bank-relative paths for one commit."""
    if demo_guard.is_demo(Path(memory_path)):
        return []
    moment = now or datetime.now(timezone.utc)
    until = moment - trace_store.PROMOTE_HOLD
    after = parse_instant(values.get("promoted_through"))
    paths: list[str] = []
    if after is None or after < until:
        pages = [s for s in store.spans_ended_between(after, until) if s.get("url")]
        if values.get("watch_and_read", True) and pages:
            found = watches(store, pages)
            if found:
                paths += watch_history.record(Path(memory_path), found, bank=bank).paths
            read_days = {local_day(parse_instant(s["start"])) for s in pages if _video(s.get("url")) is None}
            if read_days:
                store.add_reading_pending(read_days)
        store.set_promoted_through(until)
    paths += _due_reading(Path(memory_path), store, until=until, bank=bank)
    paths += write_digests(Path(memory_path), store, values, now=moment, bank=bank)
    return sorted(set(paths))


# --- what traces added, and taking it back -------------------------------------------------------------------------

REMOVE_REASON = "Removed from memory with what activity traces added."
REMOVAL_AUTHOR = "user"
REMOVAL_ORIGIN = "traces-remove"


def digest_episodes(memory_path: Path) -> dict[str, str]:
    """``episode id -> day`` for every ``traces-day`` digest in the bank."""
    out: dict[str, str] = {}
    for f in bank_index.files(Path(memory_path), "episodes"):
        fm = f.frontmatter or {}
        if fm.get("source") == SOURCE or str(fm.get("source_id") or "").startswith(SOURCE_PREFIX):
            out[str(fm.get("id") or f.path.stem)] = str(fm.get("traces_day") or "")
    return out


def _cited(claim) -> set[str]:
    eps = {str(e) for e in (claim.source_episodes or []) if e}
    eps |= {str(e.episode) for e in (claim.evidence or []) if getattr(e, "episode", "")}
    return eps


def _from_traces_only(claim, digests: set[str]) -> bool:
    """A claim every cited episode of which is a digest, not yet taken back, and not itself a retraction. Closed is no
    bar (review of #508, B2): a done happening — the "worked on X" a digest produces — is born closed
    (``valid_to = valid_from``, ``claim_reconciler._stamp_event``), and it is still what traces added."""
    from api.services.claims import RETRACT_PREDICATE

    cited = _cited(claim)
    return (bool(cited) and cited <= digests and not claim.superseded_by and claim.predicate != RETRACT_PREDICATE)


def _pages_citing(memory_path: Path, digests: set[str]) -> list[Path]:
    """Entity pages whose bytes name a digest — the page or its claims ledger. Read, never parsed, so it does not depend
    on which writer listed the episode among the page's conversations (a direct claim write does not)."""
    if not digests:
        return []
    needles = [d.encode() for d in digests]
    out = []
    entities = Path(memory_path) / "entities"
    if not entities.is_dir():
        return out
    # Each file is read again only when its size or time moved, or the digests did (measured on a copy of the owner's
    # bank, 8,028 pages: reading every one took ~330 ms warm; unchanged files answer from here).
    key = str(entities)
    known_digests, seen = _CITING.get(key, (None, {}))
    if known_digests != frozenset(digests):
        seen = {}
    fresh: dict[str, tuple] = {}
    with os.scandir(entities) as it:
        files = [(e.name, e.stat()) for e in it if e.name.endswith((".md", ".claims.jsonl"))]
    for name, st in files:
        stamp = (st.st_mtime_ns, st.st_size)
        hit = seen.get(name)
        if hit is None or hit[0] != stamp:
            try:
                data = (entities / name).read_bytes()
            except OSError:
                continue
            hit = (stamp, any(n in data for n in needles))
        fresh[name] = hit
    _CITING[key] = (frozenset(digests), fresh)
    pages = {name.removesuffix(".claims.jsonl") + ".md" if name.endswith(".claims.jsonl") else name
             for name, (_, found) in fresh.items() if found}
    return [entities / name for name in sorted(pages) if (entities / name).exists()]


#: entities dir -> (the digests last looked for, {file name: ((mtime_ns, size), names a digest)})
_CITING: dict[str, tuple] = {}


def added(memory_path: Path, *, limit: int = 200) -> dict:
    """What traces added: every belief and progress note whose only evidence is a ``traces-day`` digest."""
    from api.services.claims import EVENT_PREDICATES, parse_claims

    digests = digest_episodes(memory_path)
    items: list[dict] = []
    beliefs = progress = 0
    if not digests:
        return {"beliefs": 0, "progress": 0, "digests": 0, "since": None, "items": []}
    for page in _pages_citing(memory_path, set(digests)):
        try:
            claims = parse_claims(markdown_parser.parse(page).body)
        except Exception:  # noqa: BLE001 — an unreadable page is skipped here; Remove refuses to touch it
            continue
        for c in claims:
            if not _from_traces_only(c, set(digests)):
                continue
            is_progress = c.predicate in EVENT_PREDICATES
            progress += is_progress
            beliefs += not is_progress
            if len(items) < limit:
                days = sorted(digests[e] for e in _cited(c) if digests.get(e))
                items.append({"entity_id": page.stem, "claim_id": c.id, "text": c.text, "predicate": c.predicate,
                              "progress": is_progress, "day": days[0] if days else None})
    days = sorted(d for d in digests.values() if d)
    return {"beliefs": beliefs, "progress": progress, "digests": len(digests), "since": days[0] if days else None,
            "items": items}


def removal_id(day: str, keys: list[str]) -> str:
    return "trm_" + hashlib.sha1(("\x00".join([day, *sorted(keys)])).encode()).hexdigest()[:10]


class NoUndoPossible(RuntimeError):
    """The traces store has no key (wiped or never on): a removal could not be undone, so none is made."""


def remove(memory_path: Path, store: TraceStore, *, today: date | None = None) -> dict:
    """Take back every belief and progress note whose only evidence is a digest: each is marked superseded by a
    born-closed ``retracts`` record beside it (``agentic_write._withdrawal_record``, the reason in words), so its
    history stays. An open claim is closed today; a claim already closed by its own dates (a done happening) keeps
    them. Returns ``{removal_id, removed, paths}``; the caller commits the paths as ONE commit. Each claim's
    ``[page, record, target, valid_to before]`` is kept in the traces settings (sealed) so :func:`undo` restores exactly
    what was there. Refused (:class:`NoUndoPossible`) when the store has no key to keep that in (review of #508, B3)."""
    from api.services import agentic_write, evidence as evidence_mod
    from api.services.claims import MalformedClaimsBlockError, parse_claims, write_claims

    memory_path = Path(memory_path)
    if demo_guard.is_demo(memory_path):
        return {"removal_id": None, "removed": 0, "paths": []}   # a demo bank never receives a digest
    if not store.can_keep():
        raise NoUndoPossible("Traces were wiped or never turned on here, so a removal could not be undone; turn traces "
                             "on to remove what they added.")
    day = (today or date.today()).isoformat()
    digests = set(digest_episodes(memory_path))
    taken: list[list] = []
    writes: list[tuple[Path, dict, str]] = []
    with page_lock.page_lock(memory_path):
        for page in _pages_citing(memory_path, digests):
            parsed = markdown_parser.parse(page)
            try:
                claims = parse_claims(parsed.body, strict=True)
            except MalformedClaimsBlockError:
                continue   # never rewrite a page whose claims cannot be read
            records = []
            for c in claims:
                if not _from_traces_only(c, digests):
                    continue
                record = agentic_write._withdrawal_record(
                    c, [*claims, *records], reason=REMOVE_REASON, author=REMOVAL_AUTHOR, origin=REMOVAL_ORIGIN,
                    session_id=None, spans=[evidence_mod.reasoning("")], day=day, fallback_subject=page.stem)
                taken.append([page.stem, record.id, c.id, c.valid_to])
                if c.valid_to is None:
                    c.valid_to = day
                c.superseded_by = record.id
                records.append(record)
            if records:
                writes.append((page, parsed.frontmatter, write_claims(parsed.body, [*claims, *records])))
        if not taken:
            return {"removal_id": None, "removed": 0, "paths": []}
        rid = removal_id(day, [f"{p}/{c}" for p, _, c, _ in taken])
        # The undo record first: if it cannot be kept, nothing in the bank moves.
        store.record_removal({"id": rid, "day": day, "items": taken})
        for page, fm, body in writes:
            markdown_parser.write(page, fm, body)
    bank_index.invalidate(memory_path)
    return {"removal_id": rid, "removed": len(taken), "paths": sorted(f"entities/{p.name}" for p, _, _ in writes)}


def undo(memory_path: Path, store: TraceStore, rid: str) -> dict:
    """Put a removal back: each claim it took back gets exactly its dates again — only while it is still as the
    removal left it (superseded by that record) — and the record goes. Returns ``{restored, paths}``; ``KeyError``
    for an unknown removal."""
    from api.services.claims import MalformedClaimsBlockError, parse_claims, write_claims

    memory_path = Path(memory_path)
    entry = store.removal(rid)
    if entry is None or demo_guard.is_demo(memory_path):
        raise KeyError(rid)
    by_page: dict[str, list[tuple]] = defaultdict(list)
    for item in entry.get("items") or []:
        page, record_id, target_id = (str(x) for x in item[:3])
        before = item[3] if len(item) > 3 else None
        by_page[page].append((record_id, target_id, before))
    restored = 0
    paths: list[str] = []
    with page_lock.page_lock(memory_path):
        for stem, triples in sorted(by_page.items()):
            page = memory_path / "entities" / f"{stem}.md"
            if not page.exists():
                continue
            parsed = markdown_parser.parse(page)
            try:
                claims = parse_claims(parsed.body, strict=True)
            except MalformedClaimsBlockError:
                continue
            drop: set[str] = set()
            for record_id, target_id, before in triples:
                target = next((c for c in claims if c.id == target_id and c.superseded_by == record_id), None)
                if target is None:
                    continue
                target.valid_to = before
                target.superseded_by = None
                drop.add(record_id)
                restored += 1
            if drop:
                kept = [c for c in claims if c.id not in drop]
                markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, kept))
                paths.append(f"entities/{page.name}")
    store.drop_removal(rid)
    bank_index.invalidate(memory_path)
    return {"restored": restored, "paths": sorted(paths)}
