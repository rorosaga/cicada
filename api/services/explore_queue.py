"""The explore queue (G166 slice 1, owner 2026-10-14): the saved sites the person asked their own agent to explore.

A row is an intent, not a memory (R-VU3), so it lives **outside every bank**: ``$CICADA_HOME/explore_queue/<bank>.json``.
It copies :mod:`video_queue` on purpose — the same file discipline, a different lease rule:

* **Keys only.** A row is the url-index key (``media_ingestor.url_hash``) plus the site it belongs to
  (``reading_hosts.site_of``, a bare host-like name) and the depth asked. No URL, no title: they are joined at read
  from the bank's ``sources/url_index.json``.
* **Two processes write it** (the backend and every stdio MCP server): each write is a read-modify-write under an
  ``fcntl.flock`` on a sidecar lock, landed by temp file plus ``os.replace``.
* **Expiry and lease lapse are applied in memory on every read** and persisted only inside a write, so the sync
  component's mtime moves only when something was written (``stamp`` counts what came due with nothing written).
* **One live lease per site, across every agent and session.** Parallelism is only ever across sites. A site is
  also paced: at least :data:`PACE_SECONDS` between page loads and at most :data:`MAX_LOADS_HOUR` loads an hour
  (``sites`` in the file), so N agents never browse one site faster than a person would.
* **A lease is 15 minutes, and any call from the session extends all of its leases.** A lapse is judged only while
  Sleep is not holding the pages (P5), so a long drain never burns a site's three attempts.
* **A wall pauses the whole site** (``needs_login``, ``blocked``): its other rows wait :data:`PAUSE_DAYS` days or until
  the person asks again, and nothing retries it — never with different headers, a different agent or a different
  context (the ToS rail).
* **A record is idempotent on ``(key, lease_token)``**: the token's result is remembered, so the same record sent
  twice returns the first answer and writes nothing.

Nothing here fetches anything or opens a browser. Cicada never spawns a browser and never schedules an agent: a batch
starts only on the person's click or a trusted local agent they asked in chat (D5), stamped with who started it.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import statistics
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from api.services import episode_scrub, video_queue
from api.services.auth import cicada_home

SCHEMA_V = 1
LEASE_MINUTES = 15
MAX_ATTEMPTS = 3
#: Sites one ``cicada_explore_claim`` call leases at most; the default is one — a sub-agent captures one at a time.
CLAIM_MAX = 5
DEFAULT_CLAIM = 1
#: The file's safety ceiling, not a batch cap.
MAX_ROWS = 5000
EXPIRE_FAILED_DAYS = 7
EXPIRE_BATCH_DAYS = 1
PAUSE_DAYS = 7
#: Never faster than a person would browse (design §5.4).
PACE_SECONDS = 8
MAX_LOADS_HOUR = 30
#: Slice 2: a visit the person's reason makes deeper opens at most ``explore_plan.MAX_PAGES`` pages, each at least
#: :data:`PACE_SECONDS` after the one before, and never more than the hour has room for (:func:`room`).
MAX_LOADS_PER_LEASE = 6
RESULTS_KEEP_DAYS = 2
MAX_REASON_CHARS = 200
DEPTHS = ("capture", "look", "product", "read")
STATES = ("queued", "claimed", "failed", "paused")
#: What an agent may hand a site back with. ``needs_login`` and ``blocked`` pause the whole site.
RELEASE_CODES = ("needs_login", "blocked", "not_found", "gone", "skipped", "failed")
PAUSING = ("needs_login", "blocked")
STARTERS = ("person", "agent")
#: What a single ask on one saved link wants beyond its saved reason (looks v2): ``look`` — "Save its look", a design
#: visit whose landing picture becomes a Look even when the look has not changed.
ASKS = ("look",)

_KEY = re.compile(r"^[0-9a-f]{12}$")
_SITE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,79}$")
_TOKEN = re.compile(r"^[0-9a-f]{32}$")
#: A page id a "Save its look" ask came from (owner 2026-10-20): the Look goes on that page.
_SUBJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_BATCH = re.compile(r"^x_[0-9a-f]{6}$")


class QueueError(ValueError):
    """A refusal whose message is a sentence the caller may show."""


class QueueFull(QueueError):
    def __init__(self):
        super().__init__(f"The explore queue holds at most {MAX_ROWS:,} sites. Stop the current run, or wait for it "
                         "to finish, before adding more.")


# ---------------------------------------------------------------- paths + time


def path_for(memory_path: Path) -> Path:
    """The queue file for a bank (the video queue's slug rule). Never creates anything."""
    try:
        slug = video_queue.bank_slug(memory_path)
    except video_queue.QueueError as exc:
        raise QueueError("this memory bank cannot have an explore queue") from exc
    return cicada_home() / "explore_queue" / f"{slug}.json"


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


def clean_text(value, limit: int = MAX_REASON_CHARS) -> str:
    """One scrubbed line (writer ``explore_queue``)."""
    text, n = episode_scrub.scrub(" ".join(str(value or "").split()))
    episode_scrub.record("explore_queue", n)
    return text[:limit].rstrip()


def clean_code(value) -> str:
    code = str(value or "").strip().lower()
    return code if code in RELEASE_CODES else "failed"


def clean_depth(value) -> str:
    depth = str(value or "").strip().lower()
    return depth if depth in DEPTHS else "capture"


# ------------------------------------------------------------------- the file


def _str_fields(raw: dict, out: dict, names) -> None:
    for name in names:
        value = raw.get(name)
        if isinstance(value, str) and value:
            out[name] = value[:120]


def _clean_row(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    key, site, state = str(raw.get("key") or ""), str(raw.get("site") or ""), str(raw.get("state") or "")
    if not _KEY.match(key) or not _SITE.match(site) or state not in STATES:
        return None
    attempts = raw.get("attempts")
    row: dict = {"key": key, "site": site, "state": state, "depth": clean_depth(raw.get("depth")),
                 "requested_at": str(raw.get("requested_at") or ""),
                 "attempts": attempts if isinstance(attempts, int) and not isinstance(attempts, bool)
                 and attempts > 0 else 0}
    _str_fields(raw, row, ("batch", "claimed_by", "claimed_at", "lease_until", "session"))
    if raw.get("asked") in ASKS:
        row["asked"] = raw["asked"]
    if isinstance(raw.get("subject"), str) and _SUBJECT.match(raw["subject"]):
        row["subject"] = raw["subject"]
    token = raw.get("lease_token")
    if isinstance(token, str) and _TOKEN.match(token):
        row["lease_token"] = token
    tokens = [t for t in raw.get("tokens") or [] if isinstance(t, str) and _TOKEN.match(t)]
    if tokens:
        row["tokens"] = tokens[-MAX_ATTEMPTS:]
    for name in ("failed", "paused"):
        held = raw.get(name)
        if isinstance(held, dict):
            row[name] = {"code": clean_code(held.get("code")), "reason": str(held.get("reason") or "")[:MAX_REASON_CHARS],
                         "at": str(held.get("at") or ""), **({"until": str(held["until"])}
                                                            if isinstance(held.get("until"), str) else {})}
    return row


def _clean_batch(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    keys = [str(k) for k in raw.get("keys") or [] if _KEY.match(str(k))]
    done = [str(k) for k in raw.get("done") or [] if _KEY.match(str(k))]
    created = str(raw.get("created_at") or "")
    started = raw.get("started_by") if isinstance(raw.get("started_by"), dict) else {}
    kind = str(started.get("kind") or "person")
    by = {"kind": kind if kind in STARTERS else "person"}
    _str_fields(started, by, ("harness", "session"))
    outcomes = raw.get("outcomes") if isinstance(raw.get("outcomes"), dict) else {}
    seconds = [float(s) for s in raw.get("seconds") or [] if isinstance(s, (int, float)) and not isinstance(s, bool)]
    batch = {"created_at": created, "updated_at": str(raw.get("updated_at") or created), "started_by": by,
             "keys": keys, "done": done,
             "outcomes": {str(k): int(v) for k, v in outcomes.items() if isinstance(v, int) and not isinstance(v, bool)},
             "seconds": seconds[-50:]}
    if isinstance(raw.get("stopped_at"), str):
        batch["stopped_at"] = raw["stopped_at"]
    return batch


def _clean_site(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    out: dict = {"loads": [str(x) for x in raw.get("loads") or [] if isinstance(x, str)][-MAX_LOADS_HOUR * 2:]}
    _str_fields(raw, out, ("next_at", "paused_until", "pause_code"))
    return out


def _clean_result(raw) -> dict | None:
    if not isinstance(raw, dict) or not _KEY.match(str(raw.get("key") or "")):
        return None
    out = {"key": str(raw["key"]), "outcome": str(raw.get("outcome") or ""), "at": str(raw.get("at") or "")}
    if isinstance(raw.get("capture_id"), str):
        out["capture_id"] = raw["capture_id"]
    return out


def _read_file(memory_path: Path) -> dict:
    try:
        data = json.loads(path_for(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    rows = [r for r in (_clean_row(x) for x in data.get("items") or []) if r is not None]
    batches = {str(b): v for b, raw in (data.get("batches") or {}).items()
               if _BATCH.match(str(b)) and (v := _clean_batch(raw)) is not None} \
        if isinstance(data.get("batches"), dict) else {}
    sites = {str(s): v for s, raw in (data.get("sites") or {}).items()
             if _SITE.match(str(s)) and (v := _clean_site(raw)) is not None} \
        if isinstance(data.get("sites"), dict) else {}
    results = {str(t): v for t, raw in (data.get("results") or {}).items()
               if _TOKEN.match(str(t)) and (v := _clean_result(raw)) is not None} \
        if isinstance(data.get("results"), dict) else {}
    return {"items": rows, "batches": batches, "sites": sites, "results": results}


_PARSE_CACHE: dict[str, tuple[int, int, dict]] = {}


def _cached(memory_path: Path) -> dict:
    st = _stat(memory_path)
    if st is None:
        return {"items": [], "batches": {}, "sites": {}, "results": {}}
    key = str(path_for(memory_path))
    hit = _PARSE_CACHE.get(key)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    data = _read_file(memory_path)
    _PARSE_CACHE[key] = (st.st_mtime_ns, st.st_size, data)
    return data


@contextmanager
def _locked(memory_path: Path):
    target = path_for(memory_path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = target.with_name(target.name + ".lock")
    with open(lock_path, "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield target
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _write(target: Path, data: dict) -> None:
    payload = {"v": SCHEMA_V, **data}
    fd, tmp = tempfile.mkstemp(prefix=".explore-queue-", suffix=".tmp", dir=str(target.parent))
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


def _copy(data: dict) -> dict:
    return json.loads(json.dumps(data))


# ------------------------------------------------------------------ settling


def _lapsed(row: dict, now: datetime) -> bool:
    if row["state"] != "claimed":
        return False
    lease = _parse(row.get("lease_until"))
    return lease is None or lease <= now


def _clear_lease(row: dict) -> None:
    for name in ("claimed_by", "claimed_at", "lease_until", "session", "lease_token"):
        row.pop(name, None)


def _until(held: dict | None) -> datetime | None:
    return _parse((held or {}).get("until"))


def _settle(data: dict, now: datetime, *, holding: Callable[[], bool] | None) -> tuple[dict, bool]:
    """Expiry, pause ends and lease lapse, applied to a copy. ``holding`` is asked lazily, only when a lease lapsed;
    while Sleep holds the pages a lapsed lease is left alone (P5)."""
    data = _copy(data)
    changed = False
    rows: list[dict] = []
    for row in data["items"]:
        if row["state"] == "failed":
            at = _parse((row.get("failed") or {}).get("at"))
            if at is not None and at + timedelta(days=EXPIRE_FAILED_DAYS) <= now:
                changed = True
                continue
        if row["state"] == "paused" and (until := _until(row.get("paused"))) is not None and until <= now:
            row["state"] = "queued"
            row.pop("paused", None)
            changed = True
        rows.append(row)
    lapsed = [r for r in rows if _lapsed(r, now)]
    if lapsed and not (holding is not None and holding()):
        for row in lapsed:
            changed = True
            row["attempts"] = int(row.get("attempts") or 0) + 1
            _clear_lease(row)
            if row["attempts"] >= MAX_ATTEMPTS:
                row["state"] = "failed"
                row["failed"] = {"code": "failed", "reason": "no agent recorded it", "at": _iso(now)}
            else:
                row["state"] = "queued"
    data["items"] = rows
    for site, info in list(data["sites"].items()):
        until = _parse(info.get("paused_until"))
        if until is not None and until <= now:
            info.pop("paused_until", None)
            info.pop("pause_code", None)
            changed = True
        hour_ago = now - timedelta(hours=1)
        loads = [x for x in info.get("loads") or [] if (t := _parse(x)) is not None and t > hour_ago]
        if loads != info.get("loads"):
            info["loads"] = loads
        nxt = _parse(info.get("next_at"))
        if not loads and not info.get("paused_until") and (nxt is None or nxt <= now):
            del data["sites"][site]
    cutoff = now - timedelta(days=RESULTS_KEEP_DAYS)
    for token, result in list(data["results"].items()):
        at = _parse(result.get("at"))
        if at is None or at <= cutoff:
            del data["results"][token]
    live = {r["key"] for r in rows}
    for bid, batch in list(data["batches"].items()):
        if live & set(batch["keys"]):
            continue
        stamp = _parse(batch.get("updated_at")) or _parse(batch.get("created_at"))
        if stamp is not None and stamp + timedelta(days=EXPIRE_BATCH_DAYS) <= now:
            del data["batches"][bid]
            changed = True
    return data, changed


def _open(memory_path: Path, now: datetime, holding) -> dict:
    data, _ = _settle(_read_file(memory_path), now, holding=holding)
    return data


def _refresh(rows: list[dict], session: str | None, now: datetime) -> None:
    """Any call by a session extends its other live leases — a slow site is not stolen mid-capture."""
    if not session:
        return
    until = _iso(now + timedelta(minutes=LEASE_MINUTES))
    for row in rows:
        if row["state"] == "claimed" and row.get("session") == session and not _lapsed(row, now):
            row["lease_until"] = until


def _sleep_holds() -> bool:
    try:
        from api.services import write_admission

        return write_admission.probe()   # a stale answer is enough: the queue lives outside every bank (G183)
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ read paths


def view(memory_path: Path, now: datetime | None = None, *, holding: Callable[[], bool] | None = None) -> dict:
    """The settled queue, **in memory**: ``{items, batches, sites, results}``. Pure read."""
    data, _ = _settle(_cached(memory_path), _now(now), holding=holding)
    return data


def stamp(memory_path: Path, now: datetime | None = None, *, holding: Callable[[], bool] | None = None) -> str:
    """The ``exploreQueue`` sync component: ``<mtime>:<due>`` and ``:<held>`` while a lapsed lease is due — the
    video queue's rule, because a lease lapsing and a pause ending write nothing yet change what the app shows."""
    st = _stat(memory_path)
    if st is None:
        return f"{0.0:.6f}:0"
    data = _cached(memory_path)
    moment = _now(now)
    lapsed = sum(1 for r in data["items"] if _lapsed(r, moment))
    due = lapsed + sum(1 for r in data["items"] if r["state"] == "paused"
                       and (u := _until(r.get("paused"))) is not None and u <= moment)
    due += sum(1 for r in data["items"] if r["state"] == "failed"
               and (a := _parse((r.get("failed") or {}).get("at"))) is not None
               and a + timedelta(days=EXPIRE_FAILED_DAYS) <= moment)
    if lapsed:
        held = (holding or _sleep_holds)()
        return f"{st.st_mtime:.6f}:{due}:{int(bool(held))}"
    return f"{st.st_mtime:.6f}:{due}"


def next_change_at(memory_path: Path, now: datetime | None = None) -> str | None:
    """The earliest future instant something changes with nothing written (a lease lapses, a pause ends, a failed
    row expires), ISO, or ``None`` — the app schedules one revalidation there."""
    data = _cached(memory_path)
    moment = _now(now)
    times: list[datetime] = []
    for row in data["items"]:
        if row["state"] == "claimed" and (lease := _parse(row.get("lease_until"))) and lease > moment:
            times.append(lease)
        if row["state"] == "paused" and (until := _until(row.get("paused"))) and until > moment:
            times.append(until)
        if row["state"] == "failed" and (at := _parse((row.get("failed") or {}).get("at"))):
            expiry = at + timedelta(days=EXPIRE_FAILED_DAYS)
            if expiry > moment:
                times.append(expiry)
    return _iso(min(times)) if times else None


def active_batch(data: dict) -> tuple[str, dict] | None:
    if not data["batches"]:
        return None
    bid = max(data["batches"], key=lambda b: (data["batches"][b]["created_at"], b))
    return bid, data["batches"][bid]


def batch_view(data: dict, now: datetime | None = None, *, saved=None) -> dict | None:
    """The active batch as the wire shows it: counts, the agents working, an estimate and who started it."""
    found = active_batch(data)
    if found is None:
        return None
    bid, batch = found
    moment = _now(now)
    keys = [k for k in batch["keys"] if saved is None or k in saved]
    by_key = {r["key"]: r for r in data["items"]}
    state = lambda k: (by_key.get(k) or {}).get("state")  # noqa: E731
    done = [k for k in keys if k in batch["done"] and k not in by_key]
    claimed = [by_key[k] for k in keys if state(k) == "claimed" and not _lapsed(by_key[k], moment)]
    paused = [by_key[k] for k in keys if state(k) == "paused"]
    waiting = sum(1 for k in keys if state(k) == "queued")
    agents = len({r.get("session") or r.get("claimed_by") or "agent" for r in claimed})
    seconds = batch.get("seconds") or []
    eta = None
    if seconds and (waiting or claimed):
        per = statistics.median(seconds)
        eta = max(1, round(per * (waiting + len(claimed)) / max(1, agents) / 60))
    outcomes = dict(batch.get("outcomes") or {})
    return {
        "id": bid, "createdAt": batch["created_at"], "startedBy": batch["started_by"],
        "stoppedAt": batch.get("stopped_at"), "total": len(keys), "done": len(done), "waiting": waiting,
        "claimed": len(claimed), "agents": agents,
        "needsLogin": sum(1 for r in paused if (r.get("paused") or {}).get("code") == "needs_login"),
        "blocked": sum(1 for r in paused if (r.get("paused") or {}).get("code") == "blocked"),
        "failed": sum(1 for k in keys if state(k) == "failed"),
        "gone": int(outcomes.get("gone", 0)) + int(outcomes.get("not_found", 0)),
        "outcomes": outcomes, "etaMinutes": eta,
    }


# ----------------------------------------------------------------- write paths


def start(memory_path: Path, sites, *, started_by: dict, now: datetime | None = None,
          holding: Callable[[], bool] | None = None) -> dict:
    """The run's one write: every selected site into the queue, one batch that replaces the active one, stamped with
    who started it. ``sites`` are ``{key, site, depth}``. Leases nothing; all or nothing on a malformed entry."""
    wanted: dict[str, dict] = {}
    for item in sites or []:
        key, site = str((item or {}).get("key") or ""), str((item or {}).get("site") or "")
        if not _KEY.match(key) or not _SITE.match(site):
            raise QueueError("every site needs its key and its site name")
        wanted[key] = {"site": site, "depth": clean_depth(item.get("depth"))}
    if not wanted:
        raise QueueError("pick at least one saved site")
    kind = str((started_by or {}).get("kind") or "person")
    by = {"kind": kind if kind in STARTERS else "person"}
    _str_fields(started_by or {}, by, ("harness", "session"))
    moment = _now(now)
    with _locked(memory_path) as target:
        data = _open(memory_path, moment, holding)
        rows = data["items"]
        existing = {r["key"]: r for r in rows}
        if len(existing) + sum(1 for k in wanted if k not in existing) > MAX_ROWS:
            raise QueueFull()
        bid = "x_" + secrets.token_hex(3)
        for key, want in wanted.items():
            row = existing.get(key)
            if row is None:
                row = {"key": key, "site": want["site"], "state": "queued", "depth": want["depth"],
                       "requested_at": _iso(moment), "attempts": 0}
                rows.append(row)
            elif row["state"] == "failed":
                row.pop("failed", None)
                row.update(state="queued", attempts=0, requested_at=_iso(moment))
            row["depth"] = want["depth"]
            row["batch"] = bid
        data["batches"] = {bid: {"created_at": _iso(moment), "updated_at": _iso(moment), "started_by": by,
                                 "keys": list(wanted), "done": [], "outcomes": {}, "seconds": []}}
        _write(target, data)
    return {"id": bid, "total": len(wanted), "startedBy": by,
            "queued": sum(1 for r in data["items"] if r["state"] == "queued")}


def ask(memory_path: Path, sites, *, asked: str, started_by: dict, now: datetime | None = None,
        holding: Callable[[], bool] | None = None) -> dict:
    """One ask on one or a few saved links (looks v2: "Save its look") — unlike :func:`start`, it never replaces the
    run: the sites join the active batch when one is still going, else they make a batch of their own. Each row is
    queued with the depth the ask implies and ``asked`` set, so the plan computed at claim and at record (from the
    same row) includes it. A row an agent holds keeps its lease and gains the ask. A paused site is resumed only when
    the person asked (their asking again is what lifts a pause, :func:`retry`); an agent's ask leaves it paused.
    ``sites`` are ``{key, site, subject?}`` — ``subject`` (owner 2026-10-20) the page id the person asked from, so the
    Look goes on that page; the row keeps the id and nothing else of it."""
    if asked not in ASKS:
        raise QueueError("that is not something a saved link can be asked for")
    depth = {"look": "look"}[asked]
    wanted: dict[str, str] = {}
    subjects: dict[str, str] = {}
    for item in sites or []:
        key, site = str((item or {}).get("key") or ""), str((item or {}).get("site") or "")
        if not _KEY.match(key) or not _SITE.match(site):
            raise QueueError("every site needs its key and its site name")
        wanted[key] = site
        subject = str((item or {}).get("subject") or "")
        if subject and _SUBJECT.match(subject):
            subjects[key] = subject
    if not wanted:
        raise QueueError("pick at least one saved site")
    kind = str((started_by or {}).get("kind") or "person")
    by = {"kind": kind if kind in STARTERS else "person"}
    _str_fields(started_by or {}, by, ("harness", "session"))
    moment = _now(now)
    queued = held = paused = 0
    with _locked(memory_path) as target:
        data = _open(memory_path, moment, holding)
        rows = data["items"]
        existing = {r["key"]: r for r in rows}
        if len(existing) + sum(1 for k in wanted if k not in existing) > MAX_ROWS:
            raise QueueFull()
        found = active_batch(data)
        live = found is not None and not found[1].get("stopped_at") and \
            any(k not in found[1]["done"] for k in found[1]["keys"])
        if live:
            bid, batch = found
        else:
            bid = "x_" + secrets.token_hex(3)
            batch = {"created_at": _iso(moment), "updated_at": _iso(moment), "started_by": by, "keys": [], "done": [],
                     "outcomes": {}, "seconds": []}
            data["batches"] = {bid: batch}
        for key, site in wanted.items():
            row = existing.get(key)
            if row is None:
                row = {"key": key, "site": site, "state": "queued", "depth": depth, "requested_at": _iso(moment),
                       "attempts": 0}
                rows.append(row)
            elif row["state"] == "failed":
                row.pop("failed", None)
                row.update(state="queued", attempts=0, requested_at=_iso(moment))
            elif row["state"] == "paused" and by["kind"] == "person":
                _resume(data, row["site"])
                row.update(state="queued", attempts=0, requested_at=_iso(moment))
            if row["depth"] == "capture":   # the plan joins every reason; the row's word only labels the deepest
                row["depth"] = depth
            row["asked"] = asked
            if subjects.get(key):
                row["subject"] = subjects[key]
            row["batch"] = bid
            if key in batch["done"]:
                batch["done"].remove(key)
            if key not in batch["keys"]:
                batch["keys"].append(key)
            queued += row["state"] == "queued"
            held += row["state"] == "claimed"
            paused += row["state"] == "paused"
        batch["updated_at"] = _iso(moment)
        _write(target, data)
    return {"id": bid, "joined": live, "queued": queued, "held": held, "paused": paused,
            "total": len(batch["keys"]), "startedBy": batch["started_by"]}


def stop(memory_path: Path, *, now: datetime | None = None, holding: Callable[[], bool] | None = None) -> dict:
    """Stop the run: rows still waiting (queued, paused, failed) are dropped; a site an agent holds finishes."""
    moment = _now(now)
    with _locked(memory_path) as target:
        data = _open(memory_path, moment, holding)
        found = active_batch(data)
        if found is None:
            return {"stopped": False, "dropped": 0, "finishing": 0}
        bid, batch = found
        members = set(batch["keys"])
        keep, dropped = [], 0
        for row in data["items"]:
            if row["key"] in members and row["state"] != "claimed":
                dropped += 1
                continue
            keep.append(row)
        data["items"] = keep
        batch["stopped_at"] = batch["updated_at"] = _iso(moment)
        batch["keys"] = [k for k in batch["keys"] if k in batch["done"] or any(r["key"] == k for r in keep)]
        _write(target, data)
    return {"stopped": True, "dropped": dropped, "finishing": sum(1 for r in keep if r["key"] in members)}


def retry(memory_path: Path, key: str, *, now: datetime | None = None,
          holding: Callable[[], bool] | None = None) -> dict | None:
    """*Try again* on a failed or paused site: the row goes back to queued, and a paused site's pause is lifted (the
    person asking again is the only thing besides time that lifts it)."""
    moment = _now(now)
    with _locked(memory_path) as target:
        data = _open(memory_path, moment, holding)
        row = next((r for r in data["items"] if r["key"] == key and r["state"] in ("failed", "paused")), None)
        if row is None:
            return None
        _resume(data, row["site"])
        row.pop("failed", None)
        row.update(state="queued", attempts=0, requested_at=_iso(moment))
        _write(target, data)
    return dict(row)


def _resume(data: dict, site: str) -> None:
    info = data["sites"].get(site)
    if info is not None:
        info.pop("paused_until", None)
        info.pop("pause_code", None)
    for row in data["items"]:
        if row["site"] == site and row["state"] == "paused":
            row["state"] = "queued"
            row.pop("paused", None)


def _site_free(data: dict, site: str, now: datetime, leased_now: set[str]) -> bool:
    if site in leased_now:
        return False
    info = data["sites"].get(site) or {}
    if info.get("paused_until"):
        return False
    nxt = _parse(info.get("next_at"))
    if nxt is not None and nxt > now:
        return False
    if len(info.get("loads") or []) >= MAX_LOADS_HOUR:
        return False
    return not any(r["site"] == site and r["state"] == "claimed" and not _lapsed(r, now) for r in data["items"])


def room(memory_path: Path, site: str, now: datetime | None = None) -> int:
    """How many page loads ``site`` may still take this hour (at most :data:`MAX_LOADS_PER_LEASE`): a deep plan is cut
    to it, so no visit ever takes a site past :data:`MAX_LOADS_HOUR` loads an hour. At least 1 for a leased site."""
    data = view(memory_path, now)
    loads = len((data["sites"].get(site) or {}).get("loads") or [])
    return max(1, min(MAX_LOADS_PER_LEASE, MAX_LOADS_HOUR - loads))


def claim(memory_path: Path, *, session: str | None, harness: str | None, limit=None, saved=None,
          now: datetime | None = None, holding: Callable[[], bool] | None = None) -> list[dict]:
    """Lease the oldest queued sites to this session — at most ``min(limit or 1, 5)``, never two of one site, never
    a site another session holds, a paused site, or one whose pace has not come round. Each leased row carries a
    fresh 128-bit ``lease_token``."""
    try:
        wanted = int(limit) if limit is not None else DEFAULT_CLAIM
    except (TypeError, ValueError):
        wanted = DEFAULT_CLAIM
    wanted = max(1, min(wanted, CLAIM_MAX))
    moment = _now(now)
    with _locked(memory_path) as target:
        data = _open(memory_path, moment, holding)
        _refresh(data["items"], session, moment)
        if saved:
            # A waiting site that stopped being eligible (set to Never explore, its page archived) leaves the run as
            # skipped. Only on affirmative evidence: an empty ``saved`` is what an unreadable index looks like.
            gone = [r for r in data["items"] if r["state"] in ("queued", "paused", "failed") and r["key"] not in saved]
            for row in gone:
                data["items"].remove(row)
                for batch in data["batches"].values():
                    if row["key"] in batch["keys"] and row["key"] not in batch["done"]:
                        batch["done"].append(row["key"])
                        batch["outcomes"]["skipped"] = int(batch["outcomes"].get("skipped", 0)) + 1
        queued = sorted((r for r in data["items"] if r["state"] == "queued" and (saved is None or r["key"] in saved)),
                        key=lambda r: (r.get("requested_at") or "", r["key"]))
        leased: list[dict] = []
        sites_now: set[str] = set()
        for row in queued:
            if len(leased) >= wanted:
                break
            if not _site_free(data, row["site"], moment, sites_now):
                continue
            token = secrets.token_hex(16)
            row.update(state="claimed", claimed_by=(harness or "agent").strip()[:60] or "agent",
                       claimed_at=_iso(moment), lease_until=_iso(moment + timedelta(minutes=LEASE_MINUTES)),
                       lease_token=token)
            row["tokens"] = [*(row.get("tokens") or []), token][-MAX_ATTEMPTS:]
            if session:
                row["session"] = str(session)[:80]
            sites_now.add(row["site"])
            leased.append(dict(row))
        _write(target, data)
    return leased


def lease_status(memory_path: Path, key: str, lease_token: str, *, session: str | None,
                 now: datetime | None = None, holding: Callable[[], bool] | None = None) -> tuple[str, dict | None]:
    """Before a record writes anything: ``("ok", row)`` the lease is live and this token's; ``("late", row)`` it lapsed
    and nobody else holds the site's row (accepted, the work is not wasted); ``("duplicate", result)`` this token
    already recorded; ``("taken", None)`` another agent was handed it since; ``("unknown", None)`` not leased."""
    moment = _now(now)
    if not _TOKEN.match(str(lease_token or "")):
        return "unknown", None
    with _locked(memory_path) as target:
        data = _open(memory_path, moment, holding)
        if (result := data["results"].get(lease_token)) is not None and result["key"] == key:
            return "duplicate", dict(result)
        row = next((r for r in data["items"] if r["key"] == key), None)
        if row is None or lease_token not in (row.get("tokens") or []):
            return "unknown", None
        _refresh(data["items"], session, moment)
        _write(target, data)
        if row["state"] == "claimed" and row.get("lease_token") == lease_token:
            return "ok", dict(row)
        if row["state"] == "claimed":
            return "taken", None
        return "late", dict(row)


def complete(memory_path: Path, key: str, lease_token: str, *, outcome: str, capture_id: str | None = None,
             loads: int = 1, session: str | None = None, now: datetime | None = None,
             holding: Callable[[], bool] | None = None) -> dict:
    """A record landed: the row leaves the queue, its batch is credited, the token's result is remembered (so a
    repeat writes nothing) and the site's pace is set — the next page load on it waits :data:`PACE_SECONDS`."""
    moment = _now(now)
    loads = max(1, min(int(loads or 1), MAX_LOADS_PER_LEASE))
    with _locked(memory_path) as target:
        data = _open(memory_path, moment, holding)
        if (result := data["results"].get(lease_token)) is not None:
            return dict(result)
        row = next((r for r in data["items"] if r["key"] == key), None)
        site = row["site"] if row is not None else None
        result = {"key": key, "outcome": str(outcome), "at": _iso(moment)}
        if capture_id:
            result["capture_id"] = capture_id
        data["results"][lease_token] = result
        # A late record (its lease lapsed) must never take the row from another agent that re-claimed it: the row
        # leaves only when nobody holds it or this token does. The capture still stands and the result is remembered.
        held_by_other = row is not None and row["state"] == "claimed" and row.get("lease_token") != lease_token
        if row is not None and not held_by_other:
            data["items"] = [r for r in data["items"] if r["key"] != key]
            for batch in data["batches"].values():
                if key in batch["keys"]:
                    if key not in batch["done"]:
                        batch["done"].append(key)
                    batch["outcomes"][str(outcome)] = int(batch["outcomes"].get(str(outcome), 0)) + 1
                    started = _parse(row.get("claimed_at"))
                    if started is not None:
                        batch["seconds"] = [*batch.get("seconds", []), max(1.0, (moment - started).total_seconds())][-50:]
                    batch["updated_at"] = _iso(moment)
        if site:
            _pace(data, site, moment, loads)
        _refresh(data["items"], session, moment)
        _write(target, data)
    return result


def _pace(data: dict, site: str, moment: datetime, loads: int = 1) -> None:
    """A page of ``site`` was loaded: count it against the hour and hold the site :data:`PACE_SECONDS`."""
    info = data["sites"].setdefault(site, {"loads": []})
    info["loads"] = [*info.get("loads", []), *([_iso(moment)] * max(1, loads))][-MAX_LOADS_HOUR * 2:]
    info["next_at"] = _iso(moment + timedelta(seconds=PACE_SECONDS))


def release(memory_path: Path, releases, *, session: str | None, now: datetime | None = None,
            holding: Callable[[], bool] | None = None, key_of: Callable[[str], str]) -> list[tuple[str, str]]:
    """Hand leased sites back with a code and a scrubbed reason. ``needs_login`` and ``blocked`` pause the whole
    site (:data:`PAUSE_DAYS` days, or until the person asks again); ``skipped`` takes the site out of this run;
    anything else fails the row. Returns ``[(url, outcome)]``: ``paused`` | ``released`` | ``skipped`` |
    ``not_claimed`` | ``not_yours`` | ``unknown``."""
    moment = _now(now)
    out: list[tuple[str, str]] = []
    with _locked(memory_path) as target:
        data = _open(memory_path, moment, holding)
        _refresh(data["items"], session, moment)
        for item in releases or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            key = key_of(url) if url else ""
            row = next((r for r in data["items"] if r["key"] == key), None)
            if row is None:
                out.append((url, "unknown"))
                continue
            if row["state"] != "claimed":
                out.append((url, "not_claimed"))
                continue
            token = str(item.get("lease_token") or "")
            mine = (session and row.get("session") == session) or (token and token == row.get("lease_token"))
            if not mine:
                out.append((url, "not_yours"))
                continue
            code, reason = clean_code(item.get("code")), clean_text(item.get("reason"))
            _clear_lease(row)
            # A hand-back follows a page load (or an attempt at one): it paces the site like a record does, so an
            # agent handing sites back by hand can never hammer a host.
            _pace(data, row["site"], moment)
            if code in PAUSING:
                until = _iso(moment + timedelta(days=PAUSE_DAYS))
                info = data["sites"].setdefault(row["site"], {"loads": []})
                info["paused_until"], info["pause_code"] = until, code
                for other in data["items"]:
                    if other["site"] == row["site"] and other["state"] in ("queued", "paused") or other is row:
                        other["state"] = "paused"
                        other["paused"] = {"code": code, "reason": reason if other is row else "", "at": _iso(moment),
                                           "until": until}
                out.append((url, "paused"))
            elif code == "skipped":
                data["items"] = [r for r in data["items"] if r is not row]
                for batch in data["batches"].values():
                    if row["key"] in batch["keys"]:
                        batch["done"].append(row["key"])
                        batch["outcomes"]["skipped"] = int(batch["outcomes"].get("skipped", 0)) + 1
                        batch["updated_at"] = _iso(moment)
                out.append((url, "skipped"))
            else:
                row["state"] = "failed"
                row["failed"] = {"code": code, "reason": reason, "at": _iso(moment)}
                out.append((url, "released"))
        _write(target, data)
    return out


def resume_site(memory_path: Path, site: str, *, now: datetime | None = None) -> int:
    """The person asked again for a paused site: its rows go back to queued. Returns how many."""
    moment = _now(now)
    if _stat(memory_path) is None:
        return 0
    with _locked(memory_path) as target:
        data = _open(memory_path, moment, None)
        n = sum(1 for r in data["items"] if r["site"] == site and r["state"] == "paused")
        if not n and site not in data["sites"]:
            return 0
        _resume(data, site)
        _write(target, data)
    return n
