"""Activity traces (G218) — the ONE reader and writer of ``$CICADA_HOME/traces/``.

What the person did on this Mac, with times: one row per *focus span* (the app in front, its window title when
allowed, a browser's URL when allowed) and, when the person keeps screenshots on, a downscaled frame now and then with
the text Apple's on-device recognizer read from it. The app captures (it alone holds Screen Recording and
Accessibility) and applies :mod:`trace_policy` before anything leaves it; this module re-applies the policy, seals each
record and keeps it for its retention. No model runs here, nothing is fetched, nothing is logged but counts.

**Outside every bank, never in git, never on the network.** ``$CICADA_HOME/traces/`` beside ``captures/``; Time
Machine is asked to skip it; no route serves it to a device token or the remote listener (``routers/traces.py``); the
telemetry ledger never hears of it (not even ids). What enters a bank is only what the person's switches promote
(:mod:`trace_memory`): YouTube views into the watch history, and a counted day summary.

**Encrypted at rest.** Every record is sealed on its own (:mod:`trace_seal`, AES-256-GCM, bound to its kind and day);
the key's custody is :mod:`trace_keys` (interim: a 0600 file outside this folder). A record that fails its check is
skipped and counted, never guessed at.

Layout::

    traces/settings.enc                  the person's choices, sealed
    traces/timeline/<YYYY-MM-DD>.log     one sealed line per span, by the local day it started (ruling 34)
    traces/frames/<YYYY-MM-DD>.log       one sealed line per screenshot: when, which app, and its recognized text
    traces/shots/<YYYY-MM-DD>/<id>.enc   the screenshot itself, sealed

**Retention** (a sweep on every write, at start and hourly): the timeline 30 days, screenshots and their text 7 days;
the person may shorten either. **Wipe** deletes the folder and the key (crypto-shredding) and so turns traces off.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from api.services import runtime_layout, trace_keys, trace_policy, trace_seal

DIR_NAME = "traces"
#: The sheet's version: turning traces on with an older (or no) consent is refused.
CONSENT_VERSION = 1
TIMELINE_DAYS = 30
SHOT_DAYS = 7
MAX_SPANS_PER_SYNC = 2000
MAX_SPAN = timedelta(hours=12)
#: A row from the future is a clock the store does not trust.
FUTURE_SLACK = timedelta(minutes=5)
MAX_SHOT_BYTES = 2 * 1024 * 1024
MAX_SHOT_SIDE = 2560
OCR_CAP = 8000
SEARCH_LIMIT = 50
QUERY_CAP = 200
_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_DAY_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.log$")
_DAY_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEFAULTS: dict = {
    "enabled": False,
    "consent_version": 0,
    "consented_at": None,
    "screenshots": True,
    "titles": True,
    "title_apps": [],
    "browsers": [],
    "excluded_apps": [],
    "excluded_sites": [],
    "youtube_to_watch_history": True,
    "daily_summary": False,
    "learn_from_summary": False,
    "timeline_days": TIMELINE_DAYS,
    "shot_days": SHOT_DAYS,
    "paused_since": None,
    "paused_until": None,
    "digest_through": None,
}
#: What a person's PUT may change (consent, pause and the digest cursor have their own doors).
EDITABLE = frozenset({"screenshots", "titles", "title_apps", "browsers", "excluded_apps", "excluded_sites",
                      "youtube_to_watch_history", "daily_summary", "learn_from_summary", "timeline_days",
                      "shot_days"})
#: ``paused_until`` for a pause that lasts until the person resumes.
UNTIL_RESUMED = "until-resumed"


class TracesOff(RuntimeError):
    """Traces are off (or paused for this moment): nothing is written."""


class PayloadError(ValueError):
    """A request the store cannot trust — answered 422, nothing written."""


@dataclass
class SyncResult:
    received: int = 0
    kept: int = 0
    excluded: int = 0
    duplicate: int = 0
    invalid: int = 0
    paused: int = 0
    #: kept spans whose URL is a web page — what :mod:`trace_memory` may promote (never logged)
    pages: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"received": self.received, "kept": self.kept, "excluded": self.excluded,
                "duplicate": self.duplicate, "invalid": self.invalid, "paused": self.paused}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_instant(value) -> datetime | None:
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
        return None   # a trace's instant always carries its zone; a naive one is a client bug, never guessed
    return dt.astimezone(timezone.utc)


def local_day(at: datetime) -> date:
    """The day the person lived it on, this Mac's clock (ruling 34)."""
    return at.astimezone().date()


class TraceStore:
    """One store. ``root`` and ``keys`` are injected by tests; the backend uses :func:`store`."""

    def __init__(self, root: Path | None = None, keys: trace_keys.KeyProvider | None = None):
        self._root = root
        self._keys = keys
        self._lock = threading.RLock()
        self._key: bytes | None = None
        #: (kind, day) -> the ids a day's file holds, so a re-sent span is skipped without re-reading the file
        self._ids: dict[tuple[str, str], set[str]] = {}

    # --- where, and the key ------------------------------------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root or (runtime_layout.cicada_home() / DIR_NAME)

    @property
    def keys(self) -> trace_keys.KeyProvider:
        return self._keys or trace_keys.provider()

    def _key_or_none(self) -> bytes | None:
        if self._key is None:
            self._key = self.keys.load()
        return self._key

    def _require_key(self) -> bytes:
        key = self._key_or_none()
        if key is None:
            raise TracesOff("traces are off")
        return key

    @contextmanager
    def _locked(self):
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.root, 0o700)
            except OSError:
                pass
            fd = os.open(self.root / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _dir(self, kind: str) -> Path:
        path = self.root / kind
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    # --- settings ----------------------------------------------------------------------------------------------

    def settings(self) -> dict:
        """The person's choices. With no key (never turned on, or wiped) these are the defaults: off."""
        out = dict(DEFAULTS)
        try:
            key = self._key_or_none()
        except trace_keys.KeyRefused:
            return out
        path = self.root / "settings.enc"
        if key is None or not path.is_file():
            return out
        try:
            stored = json.loads(trace_seal.open_sealed(key, path.read_bytes(), "settings"))
        except (trace_seal.Tampered, ValueError, OSError):
            return out   # a settings file that fails its check reads as off: never record on a guess
        if isinstance(stored, dict):
            out.update({k: v for k, v in stored.items() if k in DEFAULTS})
        return out

    def _write_settings(self, values: dict) -> None:
        key = self._require_key()
        data = json.dumps({k: values.get(k, DEFAULTS[k]) for k in DEFAULTS}, sort_keys=True).encode("utf-8")
        _write_atomic(self.root / "settings.enc", trace_seal.seal(key, data, "settings"))

    def turn_on(self, consent_version: int, *, now: datetime | None = None) -> dict:
        """The person agreed to the sheet: make the key (once) and record. Refused for a sheet they did not see."""
        if int(consent_version or 0) != CONSENT_VERSION:
            raise PayloadError("turning traces on needs the current consent sheet")
        with self._locked():
            if self._key_or_none() is None:
                self._key = self.keys.create()
            trace_keys.exclude_from_backup(self.root)
            values = self.settings()
            values.update(enabled=True, consent_version=CONSENT_VERSION,
                          consented_at=_iso(now or _now()), paused_since=None, paused_until=None)
            self._write_settings(values)
            return values

    def turn_off(self) -> dict:
        """Stop recording. What is kept stays until its retention or a wipe."""
        with self._locked():
            values = self.settings()
            if self._key_or_none() is None:
                return values
            values.update(enabled=False, paused_since=None, paused_until=None)
            self._write_settings(values)
            return values

    def update(self, patch: dict) -> dict:
        unknown = set(patch) - EDITABLE
        if unknown:
            raise PayloadError(f"not a traces setting: {', '.join(sorted(unknown))}")
        with self._locked():
            if self._key_or_none() is None:
                raise TracesOff("turn traces on first")
            values = self.settings()
            for name, value in patch.items():
                values[name] = _validate(name, value)
            if not values["daily_summary"]:
                values["learn_from_summary"] = False
            if "daily_summary" in patch or "learn_from_summary" in patch:
                values["digest_through"] = None   # the summary's days are written again under the new switch
            self._write_settings(values)
            return values

    def pause(self, until: str | None, *, now: datetime | None = None) -> dict:
        """Pause until an instant, or :data:`UNTIL_RESUMED`; ``None`` resumes. While paused nothing is recorded."""
        moment = now or _now()
        with self._locked():
            if self._key_or_none() is None:
                raise TracesOff("traces are off")
            values = self.settings()
            if until is None:
                values.update(paused_since=None, paused_until=None)
            else:
                if until != UNTIL_RESUMED:
                    end = parse_instant(until)
                    if end is None or end <= moment:
                        raise PayloadError("a pause ends at a later, zoned instant")
                    until = _iso(end)
                values.update(paused_since=_iso(moment), paused_until=until)
            self._write_settings(values)
            return values

    def set_digest_through(self, day: date | None) -> None:
        with self._locked():
            if self._key_or_none() is None:
                return
            values = self.settings()
            values["digest_through"] = day.isoformat() if day else None
            self._write_settings(values)

    @staticmethod
    def paused_window(values: dict, now: datetime) -> datetime | None:
        """The instant the current pause began, or ``None`` when not paused now."""
        since = parse_instant(values.get("paused_since"))
        until = values.get("paused_until")
        if since is None or not until:
            return None
        if until == UNTIL_RESUMED:
            return since
        end = parse_instant(until)
        return since if end is not None and now < end else None

    # --- writes ------------------------------------------------------------------------------------------------

    def add_spans(self, spans: list, *, now: datetime | None = None) -> SyncResult:
        """Keep the spans the app posted, re-applying the policy. Refused (:class:`TracesOff`) while off."""
        moment = now or _now()
        if len(spans) > MAX_SPANS_PER_SYNC:
            raise PayloadError(f"at most {MAX_SPANS_PER_SYNC} spans per sync")
        result = SyncResult(received=len(spans))
        with self._locked():
            values = self.settings()
            if not values["enabled"]:
                raise TracesOff("traces are off")
            key = self._require_key()
            paused_at = self.paused_window(values, moment)
            oldest = moment - timedelta(days=int(values["timeline_days"]))
            by_day: dict[str, list[dict]] = {}
            for raw in spans:
                row = self._span(raw, values, moment, oldest, result)
                if row is None:
                    continue
                start = parse_instant(row["start"])
                if paused_at is not None:
                    if start >= paused_at:
                        result.paused += 1
                        continue
                    end = parse_instant(row["end"])
                    if end > paused_at:
                        row["end"] = _iso(paused_at)
                day = local_day(start).isoformat()
                if row["id"] in self._day_ids(key, "timeline", day):
                    result.duplicate += 1
                    continue
                by_day.setdefault(day, []).append(row)
            for day, rows in sorted(by_day.items()):
                self._append(key, "timeline", day, rows)
                result.kept += len(rows)
                result.pages.extend(r for r in rows if r.get("url"))
            self._sweep_locked(values, moment)
        return result

    def _span(self, raw, values: dict, now: datetime, oldest: datetime, result: SyncResult) -> dict | None:
        if not isinstance(raw, dict):
            result.invalid += 1
            return None
        sid = str(raw.get("id") or "")
        bundle = str(raw.get("bundle_id") or "")
        start, end = parse_instant(raw.get("start")), parse_instant(raw.get("end"))
        if (not _ID.match(sid) or not trace_policy.valid_bundle(bundle) or start is None or end is None
                or end < start or end - start > MAX_SPAN or end > now + FUTURE_SLACK or end < oldest):
            result.invalid += 1
            return None
        if raw.get("private") or trace_policy.never_recorded(bundle, set(values["excluded_apps"])):
            result.excluded += 1
            return None
        row = {"id": sid, "start": _iso(start), "end": _iso(end), "bundle_id": bundle,
               "app": trace_policy.clean_app_name(raw.get("app")) or bundle}
        if raw.get("url"):
            browser = trace_policy.url_browser(bundle)
            cleaned = trace_policy.clean_url(raw.get("url")) if browser in values["browsers"] else None
            if cleaned is not None:
                if trace_policy.host_excluded(cleaned[1], set(values["excluded_sites"])):
                    result.excluded += 1
                    return None
                row["url"], row["host"] = cleaned
        verified = bundle not in trace_policy.KNOWN_BROWSERS or "url" in row
        if verified and raw.get("title") and trace_policy.title_allowed(bundle, titles_on=bool(values["titles"]),
                                                           title_apps=set(values["title_apps"])):
            title = trace_policy.clean_title(raw.get("title"))
            if title:
                row["title"] = title
        return row

    def add_frame(self, meta: dict, image: bytes, text: str = "", *, now: datetime | None = None) -> str:
        """Keep one screenshot and its recognized text. Refused while off, paused, with screenshots off, or for an
        app or site the person excluded."""
        moment = now or _now()
        fid = str(meta.get("id") or "")
        bundle = str(meta.get("bundle_id") or "")
        at = parse_instant(meta.get("at"))
        if not _ID.match(fid) or not trace_policy.valid_bundle(bundle) or at is None or at > moment + FUTURE_SLACK:
            raise PayloadError("a screenshot needs an id, an app and a zoned time")
        if len(image) > MAX_SHOT_BYTES:
            raise PayloadError("a screenshot is kept downscaled, at most 2 MB")
        if not (image.startswith(b"\xff\xd8\xff") or image.startswith(b"\x89PNG\r\n\x1a\n")):
            raise PayloadError("Cicada keeps screenshots as JPEG or PNG")
        width, height = int(meta.get("width") or 0), int(meta.get("height") or 0)
        if not (0 < width <= MAX_SHOT_SIDE and 0 < height <= MAX_SHOT_SIDE):
            raise PayloadError("a screenshot is kept downscaled")
        with self._locked():
            values = self.settings()
            if not values["enabled"] or not values["screenshots"]:
                raise TracesOff("screenshots are off")
            paused_at = self.paused_window(values, moment)
            if paused_at is not None and at >= paused_at:
                raise TracesOff("traces are paused")
            if meta.get("private") or trace_policy.never_recorded(bundle, set(values["excluded_apps"])):
                raise TracesOff("that app is never recorded")
            host = trace_policy.normalize_host(str(meta.get("host") or ""))
            if host and trace_policy.host_excluded(host, set(values["excluded_sites"])):
                raise TracesOff("that site is never recorded")
            if bundle in trace_policy.KNOWN_BROWSERS and not host:
                raise TracesOff("a browser window is kept only when it is known not to be private")
            if not trace_policy.title_allowed(bundle, titles_on=bool(values["titles"]),
                                              title_apps=set(values["title_apps"])):
                raise TracesOff("that app's screen is not kept")
            if at < moment - timedelta(days=int(values["shot_days"])):
                raise PayloadError("that screenshot is older than screenshots are kept")
            key = self._require_key()
            day = local_day(at).isoformat()
            if fid in self._day_ids(key, "frames", day):
                return fid
            shot_dir = self._dir("shots") / day
            shot_dir.mkdir(exist_ok=True, mode=0o700)
            _write_atomic(shot_dir / f"{fid}.enc", trace_seal.seal(key, image, f"shot/{day}/{fid}"))
            words = _clean_ocr(text)
            row = {"id": fid, "at": _iso(at), "bundle_id": bundle,
                   "app": trace_policy.clean_app_name(meta.get("app")) or bundle,
                   "width": width, "height": height, "kind": "jpeg" if image[:3] == b"\xff\xd8\xff" else "png"}
            if words:
                row["text"] = words
            span_id = str(meta.get("span_id") or "")
            if _ID.match(span_id):
                row["span_id"] = span_id
            self._append(key, "frames", day, [row])
            self._sweep_locked(values, moment)
            return fid

    def forget(self, minutes: int, *, now: datetime | None = None) -> dict:
        """"Forget the last N minutes": every span that reaches into them and every screenshot taken in them."""
        if not 1 <= int(minutes) <= 24 * 60:
            raise PayloadError("forget between 1 minute and a day")
        moment = now or _now()
        cutoff = moment - timedelta(minutes=int(minutes))
        removed = {"spans": 0, "frames": 0}
        with self._locked():
            key = self._key_or_none()
            if key is None:
                return removed
            days = {local_day(cutoff).isoformat(), local_day(moment).isoformat()}
            for day in sorted(days):
                kept, gone = self._partition(key, "timeline", day,
                                             lambda r: parse_instant(r.get("end")) is not None
                                             and parse_instant(r["end"]) <= cutoff)
                if gone:
                    self._rewrite(key, "timeline", day, kept)
                    removed["spans"] += len(gone)
                kept, gone = self._partition(key, "frames", day,
                                             lambda r: parse_instant(r.get("at")) is not None
                                             and parse_instant(r["at"]) < cutoff)
                if gone:
                    self._rewrite(key, "frames", day, kept)
                    for r in gone:
                        _unlink(self.root / "shots" / day / f"{r['id']}.enc")
                    removed["frames"] += len(gone)
        return removed

    def sweep(self, *, now: datetime | None = None) -> dict:
        """Apply retention. Safe to call at any time; creates nothing when traces were never on."""
        if not self.root.exists():
            return {"timeline": 0, "frames": 0}
        with self._locked():
            try:
                key = self._key_or_none()
            except trace_keys.KeyRefused:
                # A key that may have been read: nothing is recorded (settings read as off) and nothing is deleted on
                # Cicada's own initiative; the Traces page says why and offers Wipe.
                return {"timeline": 0, "frames": 0, "key_refused": True}
            if key is None:
                # Sealed bytes with no key are noise: drop them rather than keep what nobody can read.
                self._clear_locked()
                return {"timeline": 0, "frames": 0, "unreadable": True}
            return self._sweep_locked(self.settings(), now or _now())

    def _sweep_locked(self, values: dict, now: datetime) -> dict:
        today = local_day(now)
        keep_timeline = min(int(values.get("timeline_days") or TIMELINE_DAYS), TIMELINE_DAYS)
        keep_shots = min(int(values.get("shot_days") or SHOT_DAYS), SHOT_DAYS)
        out = {"timeline": 0, "frames": 0}
        for kind, keep in (("timeline", keep_timeline), ("frames", keep_shots)):
            for day in self._days(kind):
                if (today - day).days >= keep:
                    _unlink(self.root / kind / f"{day.isoformat()}.log")
                    self._ids.pop((kind, day.isoformat()), None)
                    out[kind] += 1
        shots = self.root / "shots"
        if shots.is_dir():
            for entry in shots.iterdir():
                if not _DAY_DIR.match(entry.name):
                    continue
                if (today - date.fromisoformat(entry.name)).days >= keep_shots:
                    shutil.rmtree(entry, ignore_errors=True)
        for kind in ("timeline", "frames"):
            folder = self.root / kind
            if folder.is_dir():
                for stray in folder.glob(".*.tmp"):
                    _unlink(stray)
        return out

    def wipe(self) -> None:
        """Delete every trace, every screenshot, the settings and the key. Traces are off afterwards."""
        with self._lock:
            if self.root.exists():
                with self._locked():
                    self._clear_locked()
                shutil.rmtree(self.root, ignore_errors=True)
            self.keys.destroy()
            self._key = None
            self._ids.clear()

    def _clear_locked(self) -> None:
        for entry in list(self.root.iterdir()) if self.root.exists() else []:
            if entry.name == ".lock":
                continue
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                _unlink(entry)
        self._ids.clear()

    # --- reads -------------------------------------------------------------------------------------------------

    def timeline(self, day: date) -> dict:
        key = self._key_or_none()
        if key is None:
            return {"day": day.isoformat(), "spans": [], "frames": [], "unreadable": 0}
        spans, bad = self._read(key, "timeline", day.isoformat())
        frames, bad2 = self._read(key, "frames", day.isoformat())
        spans.sort(key=lambda r: r.get("start", ""))
        frames.sort(key=lambda r: r.get("at", ""))
        return {"day": day.isoformat(), "spans": spans,
                "frames": [{k: v for k, v in f.items() if k != "text"} | {"has_text": bool(f.get("text"))}
                           for f in frames],
                "unreadable": bad + bad2}

    def spans_between(self, first: date, last: date) -> list[dict]:
        key = self._key_or_none()
        if key is None:
            return []
        out: list[dict] = []
        for day in self._days("timeline"):
            if first <= day <= last:
                out.extend(self._read(key, "timeline", day.isoformat())[0])
        out.sort(key=lambda r: r.get("start", ""))
        return out

    def days(self) -> list[str]:
        return [d.isoformat() for d in self._days("timeline")]

    def frame(self, frame_id: str) -> tuple[dict, bytes] | None:
        """One screenshot and its record. The app asks the person's Touch ID before it calls this."""
        if not _ID.match(frame_id or ""):
            return None
        key = self._key_or_none()
        if key is None:
            return None
        for day in reversed(self._days("frames")):
            rows, _ = self._read(key, "frames", day.isoformat())
            for row in rows:
                if row.get("id") == frame_id:
                    path = self.root / "shots" / day.isoformat() / f"{frame_id}.enc"
                    try:
                        data = trace_seal.open_sealed(key, path.read_bytes(), f"shot/{day.isoformat()}/{frame_id}")
                    except (OSError, trace_seal.Tampered):
                        return None
                    return row, data
        return None

    def search(self, query: str, *, now: datetime | None = None) -> list[dict]:
        """Spans and screenshots whose words hold every word of ``query`` — titles, sites and recognized text. In
        memory, over what retention kept; no index is written and the query is never logged or stored."""
        words = [w for w in (query or "")[:QUERY_CAP].lower().split() if w]
        key = self._key_or_none()
        if not words or key is None:
            return []
        hits: list[dict] = []
        for day in reversed(self._days("timeline")):
            for r in self._read(key, "timeline", day.isoformat())[0]:
                hay = " ".join(str(r.get(k) or "") for k in ("app", "title", "host", "url")).lower()
                if all(w in hay for w in words):
                    hits.append({"kind": "span", "at": r["start"], "end": r["end"], "app": r.get("app"),
                                 "title": r.get("title"), "url": r.get("url"), "id": r["id"]})
        for day in reversed(self._days("frames")):
            for r in self._read(key, "frames", day.isoformat())[0]:
                text = str(r.get("text") or "")
                low = text.lower()
                if text and all(w in low for w in words):
                    at = low.find(words[0])
                    snippet = text[max(0, at - 60): at + 140].strip()
                    hits.append({"kind": "frame", "at": r["at"], "app": r.get("app"), "snippet": snippet,
                                 "id": r["id"]})
        hits.sort(key=lambda h: h["at"], reverse=True)
        return hits[:SEARCH_LIMIT]

    def status(self, *, now: datetime | None = None) -> dict:
        moment = now or _now()
        values = self.settings()
        size = 0
        if self.root.exists():
            for path in self.root.rglob("*"):
                try:
                    if path.is_file():
                        size += path.stat().st_size
                except OSError:
                    pass
        days = self._days("timeline")
        frames_days = self._days("frames")
        return {"enabled": bool(values["enabled"]), "paused": self.paused_window(values, moment) is not None,
                "paused_until": values["paused_until"] if self.paused_window(values, moment) else None,
                "days": len(days), "oldest_day": days[0].isoformat() if days else None,
                "screenshot_days": len(frames_days), "bytes": size, "key": self.keys.describe(),
                "timeline_days": values["timeline_days"], "shot_days": values["shot_days"]}

    # --- files -------------------------------------------------------------------------------------------------

    def _days(self, kind: str) -> list[date]:
        folder = self.root / kind
        if not folder.is_dir():
            return []
        out = []
        for entry in folder.iterdir():
            m = _DAY_FILE.match(entry.name)
            if m:
                try:
                    out.append(date.fromisoformat(m.group(1)))
                except ValueError:
                    continue
        return sorted(out)

    def _read(self, key: bytes, kind: str, day: str) -> tuple[list[dict], int]:
        path = self.root / kind / f"{day}.log"
        try:
            lines = path.read_text(encoding="ascii", errors="replace").splitlines()
        except FileNotFoundError:
            return [], 0
        rows: list[dict] = []
        bad = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(trace_seal.open_line(key, line, f"{kind}/{day}"))
            except (trace_seal.Tampered, ValueError):
                bad += 1
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows, bad

    def _day_ids(self, key: bytes, kind: str, day: str) -> set[str]:
        cached = self._ids.get((kind, day))
        if cached is None:
            cached = {str(r.get("id")) for r in self._read(key, kind, day)[0]}
            self._ids[(kind, day)] = cached
        return cached

    def _append(self, key: bytes, kind: str, day: str, rows: list[dict]) -> None:
        path = self._dir(kind) / f"{day}.log"
        lines = "".join(trace_seal.seal_line(key, json.dumps(r, sort_keys=True).encode("utf-8"), f"{kind}/{day}")
                        + "\n" for r in rows)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, lines.encode("ascii"))
            os.fsync(fd)
        finally:
            os.close(fd)
        self._day_ids(key, kind, day).update(str(r["id"]) for r in rows)

    def _partition(self, key: bytes, kind: str, day: str, keep) -> tuple[list[dict], list[dict]]:
        rows, _ = self._read(key, kind, day)
        kept = [r for r in rows if keep(r)]
        gone = [r for r in rows if not keep(r)]
        return kept, gone

    def _rewrite(self, key: bytes, kind: str, day: str, rows: list[dict]) -> None:
        path = self._dir(kind) / f"{day}.log"
        lines = "".join(trace_seal.seal_line(key, json.dumps(r, sort_keys=True).encode("utf-8"), f"{kind}/{day}")
                        + "\n" for r in rows)
        _write_atomic(path, lines.encode("ascii"))
        self._ids[(kind, day)] = {str(r.get("id")) for r in rows}


def _clean_ocr(text: str | None) -> str:
    from api.services import episode_scrub

    words = " ".join(str(text or "").split())
    words = episode_scrub.scrub(words)[0]
    return words[:OCR_CAP]


def _validate(name: str, value):
    if name in ("screenshots", "titles", "youtube_to_watch_history", "daily_summary", "learn_from_summary"):
        if not isinstance(value, bool):
            raise PayloadError(f"{name} is true or false")
        return value
    if name == "timeline_days":
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= TIMELINE_DAYS:
            raise PayloadError(f"the timeline is kept between 1 and {TIMELINE_DAYS} days")
        return value
    if name == "shot_days":
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= SHOT_DAYS:
            raise PayloadError(f"screenshots are kept between 1 and {SHOT_DAYS} days")
        return value
    if not isinstance(value, list) or len(value) > 500 or not all(isinstance(v, str) for v in value):
        raise PayloadError(f"{name} is a list of names")
    if name in ("title_apps", "excluded_apps"):
        bad = [v for v in value if not trace_policy.valid_bundle(v)]
        if bad:
            raise PayloadError(f"{name} holds app identifiers (com.example.App)")
        return sorted(set(value))
    if name == "browsers":
        bad = [v for v in value if v not in trace_policy.URL_BROWSERS]
        if bad:
            raise PayloadError(f"addresses are read only from {', '.join(trace_policy.URL_BROWSERS)}")
        return sorted(set(value))
    if name == "excluded_sites":
        hosts = [trace_policy.normalize_host(v) for v in value]
        if any(h is None for h in hosts):
            raise PayloadError("excluded_sites holds site names (bank.example)")
        return sorted(set(h for h in hosts if h))
    raise PayloadError(f"not a traces setting: {name}")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except (FileNotFoundError, IsADirectoryError):
        pass


_STORE: TraceStore | None = None
_STORE_LOCK = threading.Lock()


def store() -> TraceStore:
    """The backend's one store for this ``$CICADA_HOME`` (re-resolved when the home moves, as tests do)."""
    global _STORE
    with _STORE_LOCK:
        root = runtime_layout.cicada_home() / DIR_NAME
        if _STORE is None or _STORE.root != root:
            _STORE = TraceStore(root=root, keys=trace_keys.FileKeyProvider(runtime_layout.cicada_home()
                                                                           / trace_keys.KEY_FILE_NAME))
        return _STORE


def sweep_if_present() -> None:
    """The hourly and start-up retention sweep. Never raises, never creates the store."""
    try:
        s = store()
        if s.root.exists():
            s.sweep()
    except Exception as exc:  # noqa: BLE001 — retention retries next hour; a sweep never takes the backend down
        from loguru import logger

        logger.warning(f"traces sweep failed ({type(exc).__name__})")
