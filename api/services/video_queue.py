"""The video queue (G162, spec §4.3): what the person asked their own agent to read or watch.

A row is an intent, not a memory (R-VU3). **Machine-wide and never in a bank**:
``$CICADA_HOME/video_queue/<bank>.json`` — beside the reading asks' precedent, so
a request and its outcome write no bank file, make no commit and need no Sleep
gate. Its mtime (and the count of leases and expiries that have come due, see
:func:`stamp`) moves the ``videoQueue`` sync component, which is what makes
"Picked up" appear within a second and a lapsed lease go back to "Waiting".

* **No URL and no title is stored.** A row is a key: the url-index key
  (``media_ingestor.url_hash``, R-VU8), joined at read to the bank's
  ``sources/url_index.json``. The file is machine-wide, so it holds no link the
  person saved.
* **Two processes write it** (the backend and every stdio MCP server), so every
  write is a read-modify-write under an ``fcntl.flock`` on a sidecar lock and
  lands by temp file plus ``os.replace``: a reader never sees half a file.
* **Expiry and lease lapse are applied in memory on every read and persisted
  only inside a write.** A read that wrote would move the mtime the sync
  component polls about once a second, and two processes could chase each
  other's refreshes.
* **No batch cap** (P1, owner 2026-09-29): a hand-off accepts every selected
  video. The one ceiling is a file-safety limit, :data:`MAX_ROWS`, with a
  sentence. A claim still leases at most :data:`CLAIM_PAGE` per call; the
  prompt loops until it returns nothing.
* **A lease is judged only when Sleep is not holding the pages** (P5): a long
  drain must not burn a video's three attempts. ``holding`` is asked lazily,
  only when a lease has actually lapsed, so an ordinary claim never pays the
  probe's worst case.
* **Free text is scrubbed** (writer ``video_queue``): a release reason is one
  line of at most :data:`MAX_REASON_CHARS` characters, rendered as plain text.

Nothing here fetches a video, a caption, a frame or a stream (Track V).
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import tempfile
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from api.services import episode_scrub, media_ingestor, video_state
from api.services.auth import cicada_home

SCHEMA_V = 1
LEASE_MINUTES = 45
MAX_ATTEMPTS = 3
#: Videos one ``cicada_video_claim`` call leases at most. The prompt loops.
CLAIM_PAGE = 10
DEFAULT_CLAIM = 5
#: The queue file's safety ceiling — not a batch cap (P1, Q10).
MAX_ROWS = 2000
EXPIRE_FAILED_DAYS = 7
EXPIRE_BATCH_DAYS = 1
MAX_REASON_CHARS = 200
WANTS = ("transcript", "watch")
STATES = ("queued", "claimed", "failed")
FAIL_CODES = ("needs_login", "no_captions", "not_found", "blocked", "failed")
METHODS = ("auto", "captions", "link")

_BANK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class QueueError(ValueError):
    """A refusal whose message is a sentence the caller may show."""


class NotAVideo(QueueError):
    def __init__(self, keys):
        self.keys = list(keys)
        super().__init__("not a saved video")


class QueueFull(QueueError):
    def __init__(self):
        super().__init__(
            f"The video queue holds at most {MAX_ROWS:,} videos. Remove some, or wait for an agent to "
            "finish them, before adding more.")


# ---------------------------------------------------------------- paths + time


def bank_slug(memory_path: Path) -> str:
    """The queue file's stem for a bank — always a plain slug, never a refusal.

    A directory name that is already a plain slug is used as it is (so an existing
    file keeps its name). Any other name (non-ASCII letters, an apostrophe, an
    ampersand, a leading underscore, more than 64 characters) becomes an ASCII
    slug of itself plus a short sha1 of the full name, so two banks never share a
    file and a crafted name can never reach another path."""
    name = Path(memory_path).name
    if _BANK_RE.match(name):
        return name
    if not name or name in (".", ".."):
        raise QueueError("this memory bank cannot have a video queue")
    ascii_part = re.sub(r"[^A-Za-z0-9._-]+", "-", unicodedata.normalize("NFKD", name)
                        .encode("ascii", "ignore").decode("ascii")).strip("-._")[:40]
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
    return f"{ascii_part}-{digest}" if ascii_part else f"bank-{digest}"


def path_for(memory_path: Path) -> Path:
    """The queue file for a bank. Never creates anything (a read must not)."""
    return cicada_home() / "video_queue" / f"{bank_slug(memory_path)}.json"


def _stat(memory_path: Path):
    try:
        return path_for(memory_path).stat()
    except (OSError, ValueError):
        return None


def mtime(memory_path: Path) -> float:
    st = _stat(memory_path)
    return st.st_mtime if st else 0.0


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------- free text


def clean_text(value, limit: int = MAX_REASON_CHARS) -> str:
    """One scrubbed line, at most ``limit`` characters (writer ``video_queue``)."""
    text, n = episode_scrub.scrub(" ".join(str(value or "").split()))
    episode_scrub.record("video_queue", n)
    return text[:limit].rstrip()


def clean_code(value) -> str:
    code = str(value or "").strip().lower()
    return code if code in FAIL_CODES else "failed"


# ------------------------------------------------------------------- the file


def _clean_row(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    key = str(raw.get("key") or "")
    want, state = str(raw.get("want") or ""), str(raw.get("state") or "")
    if not re.fullmatch(r"[0-9a-f]{12}", key) or want not in WANTS or state not in STATES:
        return None
    row: dict = {"key": key, "want": want, "state": state,
                 "requested_at": str(raw.get("requested_at") or ""),
                 "attempts": int(raw["attempts"]) if isinstance(raw.get("attempts"), int)
                 and not isinstance(raw.get("attempts"), bool) and raw["attempts"] > 0 else 0}
    for name in ("batch", "claimed_by", "claimed_at", "lease_until", "session"):
        value = raw.get(name)
        if isinstance(value, str) and value:
            row[name] = value
    failed = raw.get("failed")
    if isinstance(failed, dict):
        row["failed"] = {"code": clean_code(failed.get("code")), "reason": str(failed.get("reason") or "")[:MAX_REASON_CHARS],
                         "at": str(failed.get("at") or "")}
    return row


def _clean_batch(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    keys = [str(k) for k in raw.get("keys") or [] if re.fullmatch(r"[0-9a-f]{12}", str(k))]
    done = [str(k) for k in raw.get("done") or [] if re.fullmatch(r"[0-9a-f]{12}", str(k))]
    method = str(raw.get("method") or "auto")
    created = str(raw.get("created_at") or "")
    return {"created_at": created, "updated_at": str(raw.get("updated_at") or created),
            "method": method if method in METHODS else "auto", "keys": keys, "done": done}


def _read_file(memory_path: Path) -> tuple[list[dict], dict[str, dict]]:
    try:
        data = json.loads(path_for(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], {}
    if not isinstance(data, dict):
        return [], {}
    rows = [r for r in (_clean_row(x) for x in data.get("items") or []) if r is not None]
    batches = {}
    if isinstance(data.get("batches"), dict):
        for bid, raw in data["batches"].items():
            batch = _clean_batch(raw)
            if batch is not None and re.fullmatch(r"b_[0-9a-f]{3,12}", str(bid)):
                batches[str(bid)] = batch
    return rows, batches


#: (path, mtime_ns, size) -> parsed file, so the ~1 Hz component poll costs a
#: ``stat`` when nothing changed and a parse only when the file did.
_PARSE_CACHE: dict[str, tuple[int, int, list[dict], dict[str, dict]]] = {}


def _cached(memory_path: Path) -> tuple[list[dict], dict[str, dict]]:
    st = _stat(memory_path)
    if st is None:
        return [], {}
    key = str(path_for(memory_path))
    hit = _PARSE_CACHE.get(key)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2], hit[3]
    rows, batches = _read_file(memory_path)
    _PARSE_CACHE[key] = (st.st_mtime_ns, st.st_size, rows, batches)
    return rows, batches


@contextmanager
def _locked(memory_path: Path):
    """Read-modify-write under one exclusive lock, across processes."""
    target = path_for(memory_path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = target.with_name(target.name + ".lock")
    with open(lock_path, "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield target
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _write(target: Path, rows: list[dict], batches: dict[str, dict]) -> None:
    payload = {"v": SCHEMA_V, "items": rows, "batches": batches}
    fd, tmp = tempfile.mkstemp(prefix=".video-queue-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=1, sort_keys=True) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ------------------------------------------------------------ settle (pure-ish)


def _live_batch_keys(rows: list[dict]) -> set[str]:
    return {r["key"] for r in rows}


def _batch_expiry(batch: dict) -> datetime | None:
    stamp = _parse(batch.get("updated_at")) or _parse(batch.get("created_at"))
    return stamp + timedelta(days=EXPIRE_BATCH_DAYS) if stamp else None


def _failed_expiry(row: dict) -> datetime | None:
    stamp = _parse((row.get("failed") or {}).get("at"))
    return stamp + timedelta(days=EXPIRE_FAILED_DAYS) if stamp else None


def _lapsed(row: dict, now: datetime) -> bool:
    if row["state"] != "claimed":
        return False
    lease = _parse(row.get("lease_until"))
    return lease is None or lease <= now


def _derived_reason(records: list[video_state.Record], since: str | None) -> str:
    """Why a third lapse failed, from what exists: a record that did not meet the
    request, else nothing at all."""
    for r in records:
        if not video_state.newer_than(r, since):
            continue
        return "an agent recorded it as a transcript only" if video_state.T in r.facts and video_state.F not in r.facts \
            else "an agent recorded it without saying how"
    return "no agent recorded it"


def _settle(rows: list[dict], batches: dict[str, dict], now: datetime, *,
            records: Callable[[], dict[str, list[video_state.Record]]] | None,
            holding: Callable[[], bool] | None) -> tuple[list[dict], dict[str, dict], bool]:
    """Apply expiry and lease lapse to copies of ``rows`` and ``batches``.

    ``records`` and ``holding`` are called lazily and at most once, only when a
    lease has lapsed. While Sleep holds the pages a lapsed lease is left alone
    (P5)."""
    rows = [dict(r) for r in rows]
    batches = {k: {**v, "keys": list(v["keys"]), "done": list(v["done"])} for k, v in batches.items()}
    changed = False

    kept = []
    for row in rows:
        expiry = _failed_expiry(row) if row["state"] == "failed" else None
        if expiry is not None and expiry <= now:
            changed = True
            continue
        kept.append(row)
    rows = kept

    lapsed = [r for r in rows if _lapsed(r, now)]
    if lapsed and not (holding is not None and holding()):
        recs = records() if records is not None else {}
        finished: set[str] = set()
        for row in lapsed:
            changed = True
            mine = recs.get(row["key"], [])
            if video_state.satisfies(mine, row["want"], since=row.get("requested_at")):
                finished.add(row["key"])
                bid = row.get("batch")
                if bid in batches and row["key"] not in batches[bid]["done"]:
                    batches[bid]["done"].append(row["key"])
                    batches[bid]["updated_at"] = _iso(now)
                continue
            row["attempts"] = int(row.get("attempts") or 0) + 1
            for name in ("claimed_by", "claimed_at", "lease_until", "session"):
                row.pop(name, None)
            if row["attempts"] >= MAX_ATTEMPTS:
                row["state"] = "failed"
                row["failed"] = {"code": "failed", "reason": _derived_reason(mine, row.get("requested_at")),
                                 "at": _iso(now)}
            else:
                row["state"] = "queued"
        rows = [r for r in rows if r["key"] not in finished]

    live = _live_batch_keys(rows)
    for bid in list(batches):
        batch = batches[bid]
        if live & set(batch["keys"]):
            continue
        expiry = _batch_expiry(batch)
        if expiry is not None and expiry <= now:
            del batches[bid]
            changed = True
    return rows, batches, changed


def _drop_orphans(rows: list[dict], batches: dict[str, dict], saved) -> tuple[list[dict], dict[str, dict], bool]:
    """M5: a row whose key no longer resolves (an archived page, a junk verdict, a
    removed index entry) is dropped, and its batch shrinks the way Remove does."""
    keep = [r for r in rows if r["key"] in saved]
    if len(keep) == len(rows):
        return rows, batches, False
    gone = {r["key"] for r in rows} - {r["key"] for r in keep}
    for batch in batches.values():
        batch["keys"] = [k for k in batch["keys"] if k not in gone]
        batch["done"] = [k for k in batch["done"] if k not in gone]
    return keep, batches, True


# ------------------------------------------------------------------ read paths


def view(memory_path: Path, now: datetime | None = None, *, records=None,
         holding: Callable[[], bool] | None = None) -> tuple[list[dict], dict[str, dict]]:
    """The live rows and batches, settled **in memory**. Pure read: no write, no mtime moved."""
    rows, batches = _cached(memory_path)
    rows, batches, _ = _settle(rows, batches, _now(now), records=records or _records_fn(memory_path),
                               holding=holding)
    return rows, batches


def stamp(memory_path: Path, now: datetime | None = None) -> str:
    """The ``videoQueue`` sync component: ``<mtime>:<due>``.

    The mtime alone is blind to the two things that happen with nothing written —
    a lease lapsing and a row or batch aging out — yet both change what
    ``/videos/state`` says. ``due`` counts them, so the component (and both
    ETags) move at the instant they happen (H2). A parse happens only when the
    file changed; otherwise this is a ``stat`` and a walk over a small list."""
    st = _stat(memory_path)
    if st is None:
        return f"{0.0:.6f}:0"
    rows, batches = _cached(memory_path)
    moment = _now(now)
    live = _live_batch_keys(rows)
    due = sum(1 for r in rows if _lapsed(r, moment))
    due += sum(1 for r in rows if r["state"] == "failed" and (_failed_expiry(r) or moment + timedelta(days=1)) <= moment)
    for batch in batches.values():
        if not (live & set(batch["keys"])) and (_batch_expiry(batch) or moment + timedelta(days=1)) <= moment:
            due += 1
    return f"{st.st_mtime:.6f}:{due}"


def next_change_at(memory_path: Path, now: datetime | None = None) -> str | None:
    """The earliest future instant something changes with no write (a lease
    lapses, a failed row or a finished batch expires), ISO, or ``None``. The app
    schedules one revalidation there (H2)."""
    rows, batches = _cached(memory_path)
    moment = _now(now)
    live = _live_batch_keys(rows)
    times: list[datetime] = []
    for row in rows:
        if row["state"] == "claimed" and (lease := _parse(row.get("lease_until"))) and lease > moment:
            times.append(lease)
        if row["state"] == "failed" and (expiry := _failed_expiry(row)) and expiry > moment:
            times.append(expiry)
    for batch in batches.values():
        if not (live & set(batch["keys"])) and (expiry := _batch_expiry(batch)) and expiry > moment:
            times.append(expiry)
    return _iso(min(times)) if times else None


def batch_view(rows: list[dict], batches: dict[str, dict], saved) -> dict | None:
    """The active batch (the newest) as the wire shows it. Members that stopped
    resolving are ignored; ``total`` shrinks when one is removed."""
    if not batches:
        return None
    bid = max(batches, key=lambda b: (batches[b]["created_at"], b))
    batch = batches[bid]
    keys = [k for k in batch["keys"] if k in saved]
    by_key = {r["key"]: r for r in rows}
    done = [k for k in keys if k in batch["done"] and k not in by_key]
    state = lambda k: (by_key.get(k) or {}).get("state")  # noqa: E731
    return {"id": bid, "createdAt": batch["created_at"], "method": batch["method"], "total": len(keys),
            "done": len(done), "claimed": sum(1 for k in keys if state(k) == "claimed"),
            "waiting": sum(1 for k in keys if state(k) == "queued"),
            "failed": sum(1 for k in keys if state(k) == "failed"), "keys": keys}


# ----------------------------------------------------------------- write paths


def _saved(memory_path: Path, saved):
    return saved if saved is not None else video_state.saved_videos(memory_path)


def _records_fn(memory_path: Path):
    cache: dict = {}

    def records():
        if "r" not in cache:
            cache["r"] = video_state.watch_records(memory_path)
        return cache["r"]

    return records


def _open(memory_path: Path, now: datetime, saved, holding):
    """Load under the lock, settle, drop orphans. Returns rows, batches, changed."""
    rows, batches = _read_file(memory_path)
    rows, batches, c1 = _settle(rows, batches, now, records=_records_fn(memory_path), holding=holding)
    # Orphans are dropped only on affirmative evidence: an empty ``saved`` is what an
    # unreadable or half-written url index looks like (``save_url_index`` was once a
    # truncate-then-write), and must never wipe the person's queue.
    c2 = False
    if saved:
        rows, batches, c2 = _drop_orphans(rows, batches, saved)
    return rows, batches, c1 or c2


def _reset(row: dict) -> None:
    for name in ("claimed_by", "claimed_at", "lease_until", "session", "failed"):
        row.pop(name, None)
    row["state"], row["attempts"] = "queued", 0


def _upsert(rows: list[dict], key: str, want: str, now: datetime) -> dict:
    """Add or update one row in ``rows``. A watch is never downgraded to a
    transcript (it includes one); a failed row is reset to queued (Try again)."""
    row = next((r for r in rows if r["key"] == key), None)
    if row is None:
        row = {"key": key, "want": want, "state": "queued", "requested_at": _iso(now), "attempts": 0}
        rows.append(row)
        return row
    if want == "watch":
        row["want"] = "watch"
    if row["state"] == "failed":
        _reset(row)
        row["requested_at"] = _iso(now)
    return row


def put(memory_path: Path, key: str, want: str, *, saved=None, now: datetime | None = None,
        holding: Callable[[], bool] | None = None) -> dict:
    """Queue one video (idempotent). Raises :class:`NotAVideo` / :class:`QueueFull`."""
    if want not in WANTS:
        raise QueueError("want must be transcript or watch")
    moment, saved = _now(now), _saved(memory_path, saved)
    if key not in saved:
        raise NotAVideo([key])
    with _locked(memory_path) as target:
        rows, batches, _ = _open(memory_path, moment, saved, holding)
        if not any(r["key"] == key for r in rows) and len(rows) >= MAX_ROWS:
            raise QueueFull()
        row = _upsert(rows, key, want, moment)
        _write(target, rows, batches)
    return dict(row)


def remove(memory_path: Path, key: str, *, saved=None, now: datetime | None = None,
           holding: Callable[[], bool] | None = None) -> bool:
    """Remove a row and drop its key from its batch (the batch total shrinks)."""
    moment, saved = _now(now), _saved(memory_path, saved)
    with _locked(memory_path) as target:
        rows, batches, changed = _open(memory_path, moment, saved, holding)
        kept = [r for r in rows if r["key"] != key]
        if len(kept) == len(rows):
            if changed:
                _write(target, rows, batches)
            return False
        for batch in batches.values():
            batch["keys"] = [k for k in batch["keys"] if k != key]
            batch["done"] = [k for k in batch["done"] if k != key]
            batch["updated_at"] = _iso(moment)
        _write(target, kept, batches)
    return True


def retry(memory_path: Path, key: str, *, saved=None, now: datetime | None = None,
          holding: Callable[[], bool] | None = None) -> dict | None:
    """A failed row goes back to queued with its attempts reset. ``None`` when the
    key has no failed row."""
    moment, saved = _now(now), _saved(memory_path, saved)
    with _locked(memory_path) as target:
        rows, batches, changed = _open(memory_path, moment, saved, holding)
        row = next((r for r in rows if r["key"] == key and r["state"] == "failed"), None)
        if row is None:
            if changed:
                _write(target, rows, batches)
            return None
        _reset(row)
        _write(target, rows, batches)
    return dict(row)


def handoff(memory_path: Path, items, method: str, *, saved=None, now: datetime | None = None,
            holding: Callable[[], bool] | None = None) -> tuple[dict, int]:
    """The run's one write: upsert every selected video and stamp one batch that
    replaces the active one. Leases nothing. **No cap** (P1). All or nothing: an
    unknown key raises :class:`NotAVideo` naming every such key and writes nothing.

    Returns ``(batch, queued)`` — the batch as ``{id, total, method}`` and how many
    videos are waiting in the queue afterwards (the prompt's count)."""
    method = method if method in METHODS else None
    if method is None:
        raise QueueError("method must be auto, captions or link")
    wanted: dict[str, str] = {}
    for item in items or []:
        key = str((item or {}).get("key") if isinstance(item, dict) else "")
        want = str((item or {}).get("want") if isinstance(item, dict) else "")
        if want not in WANTS:
            raise QueueError("every video needs want: transcript or watch")
        wanted[key] = "watch" if "watch" in (want, wanted.get(key)) else "transcript"
    if not wanted:
        raise QueueError("pick at least one video")
    moment, saved = _now(now), _saved(memory_path, saved)
    unknown = [k for k in wanted if k not in saved]
    if unknown:
        raise NotAVideo(unknown)
    with _locked(memory_path) as target:
        rows, batches, _ = _open(memory_path, moment, saved, holding)
        existing = {r["key"] for r in rows}
        if len(existing) + len([k for k in wanted if k not in existing]) > MAX_ROWS:
            raise QueueFull()
        bid = "b_" + secrets.token_hex(3)
        for key, want in wanted.items():
            row = _upsert(rows, key, want, moment)
            row["batch"] = bid
        batches = {bid: {"created_at": _iso(moment), "updated_at": _iso(moment), "method": method,
                         "keys": list(wanted), "done": []}}
        _write(target, rows, batches)
        queued = sum(1 for r in rows if r["state"] == "queued")
    return {"id": bid, "total": len(wanted), "method": method}, queued


def _refresh(rows: list[dict], session: str | None, now: datetime) -> None:
    """Any call by a session extends its other leases: a sub-agent working a long
    video is not judged lapsed."""
    if not session:
        return
    until = _iso(now + timedelta(minutes=LEASE_MINUTES))
    for row in rows:
        if row["state"] == "claimed" and row.get("session") == session and not _lapsed(row, now):
            row["lease_until"] = until


def claim(memory_path: Path, *, session: str | None, harness: str | None, limit=None, saved=None,
          now: datetime | None = None, holding: Callable[[], bool] | None = None) -> list[dict]:
    """Lease the oldest ``queued`` videos to this session: at most
    ``min(limit or 5, 10)``, never the same video to two sessions. Returns the
    leased rows (the caller joins them to the saved pages)."""
    try:
        wanted = int(limit) if limit is not None else DEFAULT_CLAIM
    except (TypeError, ValueError):
        wanted = DEFAULT_CLAIM
    wanted = max(1, min(wanted, CLAIM_PAGE))
    moment, saved = _now(now), _saved(memory_path, saved)
    with _locked(memory_path) as target:
        rows, batches, _ = _open(memory_path, moment, saved, holding)
        _refresh(rows, session, moment)
        queued = sorted((r for r in rows if r["state"] == "queued"), key=lambda r: (r.get("requested_at") or "", r["key"]))
        leased = []
        for row in queued[:wanted]:
            row["state"] = "claimed"
            row["claimed_by"] = (harness or "agent").strip()[:60] or "agent"
            row["claimed_at"] = _iso(moment)
            row["lease_until"] = _iso(moment + timedelta(minutes=LEASE_MINUTES))
            if session:
                row["session"] = str(session)[:80]
            leased.append(dict(row))
        _write(target, rows, batches)
    return leased


def release(memory_path: Path, releases, *, session: str | None, saved=None, now: datetime | None = None,
            holding: Callable[[], bool] | None = None) -> list[tuple[str, str]]:
    """Hand claimed videos back as ``failed`` with a code and a scrubbed reason.

    ``releases`` are ``{url, code?, reason?}``. Returns ``[(url, outcome)]`` with
    outcome ``released`` | ``needs_login`` | ``not_claimed`` | ``unknown``."""
    moment, saved = _now(now), _saved(memory_path, saved)
    out: list[tuple[str, str]] = []
    with _locked(memory_path) as target:
        rows, batches, _ = _open(memory_path, moment, saved, holding)
        _refresh(rows, session, moment)
        for item in releases or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            key = media_ingestor.url_hash(url) if url else ""
            row = next((r for r in rows if r["key"] == key), None)
            if row is None:
                out.append((url, "unknown"))
                continue
            if row["state"] != "claimed":
                out.append((url, "not_claimed"))
                continue
            code = clean_code(item.get("code"))
            for name in ("claimed_by", "claimed_at", "lease_until", "session"):
                row.pop(name, None)
            row["state"] = "failed"
            row["failed"] = {"code": code, "reason": clean_text(item.get("reason")), "at": _iso(moment)}
            out.append((url, "needs_login" if code == "needs_login" else "released"))
        _write(target, rows, batches)
    return out


def complete(memory_path: Path, key: str, basis, *, session: str | None, saved=None,
             now: datetime | None = None, holding: Callable[[], bool] | None = None) -> str:
    """A record landed for ``key``: apply §4.3's satisfaction table to its queue row.

    ``done`` (row removed, batch credited), ``stays`` (a transcript against a
    watch request: the row stays), ``left`` (no basis and not the leaseholder:
    the row stays) or ``none`` (nothing was queued). Written even when the bank
    commit did not run — the queue is outside the bank."""
    moment, saved = _now(now), _saved(memory_path, saved)
    if _stat(memory_path) is None:
        return "none"
    with _locked(memory_path) as target:
        rows, batches, changed = _open(memory_path, moment, saved, holding)
        row = next((r for r in rows if r["key"] == key), None)
        if row is None:
            if changed:
                _write(target, rows, batches)
            return "none"
        stated = video_state.clean_basis(basis)
        if stated:
            done = stated in ("frames", "both") or (stated == "transcript" and row["want"] == "transcript")
        else:
            done = row["state"] == "claimed" and bool(session) and row.get("session") == session
        _refresh(rows, session, moment)
        if not done:
            _write(target, rows, batches)
            return "stays" if stated else "left"
        rows = [r for r in rows if r["key"] != key]
        bid = row.get("batch")
        if bid in batches:
            if key not in batches[bid]["done"]:
                batches[bid]["done"].append(key)
            batches[bid]["updated_at"] = _iso(moment)
        _write(target, rows, batches)
    return "done"
