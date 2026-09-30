"""The reading asks (G166, spec §8.4): what the person asked their own agent to read.

A person's "Ask an agent" on a link is a row here; the agent's outcome for it —
``read``, ``needs_login``, ``blocked``, ``not_found`` or ``failed`` — lands on the
same row. **Machine-wide and never in a bank**: ``$CICADA_HOME/reading_asks/<bank>.json``
beside the video queue's precedent. That is what lets a login wall be stored and
shown at once, with no bank write, no commit and no Sleep gate: the outcome is
this file, its mtime moves the ``reading`` sync component (SSE, then the app
refreshes), and the link's wire joins the row at read time.

* **No URL is stored.** A row is ``{url_hash, host, host_class, asked_at,
  state, outcome_at?, via?, harness?, note?}``; the URL is joined at read from
  the bank's ``sources/url_index.json``, so this file (outside the bank, machine
  global) never holds a link the person saved.
* **Rows expire after** ``EXPIRES_AFTER_DAYS``. Expiry is applied IN MEMORY on
  every read and persisted only inside a write — a read that wrote would move
  the mtime the sync component polls about once a second, and two processes
  could then chase each other's refreshes.
* **Two processes write it** (the backend and each stdio MCP server), so every
  write is read-modify-write under an ``fcntl.flock`` on a sidecar lock file and
  lands by temp file plus ``os.replace``. A reader never sees half a file.
* An ask on a URL that already has a row resets it to ``waiting``: that is
  "Ask again".

``note`` is one short sentence the agent may leave (at most 200 characters,
scrubbed); it is never served to a remote connection and never shown as the
person's words.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.services import episode_ids, episode_scrub
from api.services.auth import cicada_home

SCHEMA_V = 1
EXPIRES_AFTER_DAYS = 7
MAX_NOTE_CHARS = 200
MAX_VIA_CHARS = 40
MAX_ROWS = 500
#: Rows an agent's outcome created for a page of a site the person allowed (no
#: explicit ask behind them). They are evicted before any explicit ask and
#: capped, so a big allowed site can never push the person's own asks out.
MAX_SITE_ROWS = 200
ORIGIN_SITE = "site"
STATES = ("waiting", "read", "needs_login", "blocked", "not_found", "failed")
#: What an agent may record. ``waiting`` is the person's, never an outcome.
OUTCOMES = STATES[1:]

_BANK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_VIA_SAFE = re.compile(r"[^A-Za-z0-9 ._:/+-]")


def bank_slug(memory_path: Path) -> str:
    """The bank's directory name, refused unless it is a plain slug — the file
    name is derived from it, so a crafted name can never reach another path."""
    name = Path(memory_path).name
    if not _BANK_RE.match(name):
        raise ValueError(f"bank name {name!r} cannot name a reading file")
    return name


def path_for(memory_path: Path) -> Path:
    """The ask file for a bank. Never creates anything (a read must not)."""
    return cicada_home() / "reading_asks" / f"{bank_slug(memory_path)}.json"


def mtime(memory_path: Path) -> float:
    """The file's mtime, 0.0 when absent or the bank name is unusable."""
    try:
        return path_for(memory_path).stat().st_mtime
    except (OSError, ValueError):
        return 0.0


def clean_via(via) -> str | None:
    """Which tool the agent says it read with: self-reported, so kept short and
    plain (letters, digits and a few separators) and shown only as its word."""
    text = _VIA_SAFE.sub("", " ".join(str(via or "").split()))[:MAX_VIA_CHARS].strip()
    return text or None


def clean_note(note) -> str | None:
    text, _n = episode_scrub.scrub(" ".join(str(note or "").split()))
    text = text[:MAX_NOTE_CHARS].strip()
    return text or None


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _alive(row: dict, now: datetime) -> bool:
    stamp = _parse(row.get("outcome_at")) or _parse(row.get("asked_at"))
    return stamp is not None and now - stamp < timedelta(days=EXPIRES_AFTER_DAYS)


def _clean_row(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    url_hash = str(raw.get("url_hash") or "")
    state = str(raw.get("state") or "")
    if not re.fullmatch(r"[0-9a-f]{12}", url_hash) or state not in STATES:
        return None
    row = {"url_hash": url_hash, "host": str(raw.get("host") or "")[:120],
           "host_class": "walled" if raw.get("host_class") == "walled" else "public",
           "asked_at": str(raw.get("asked_at") or ""), "state": state}
    for key in ("outcome_at", "via", "harness", "note"):
        value = raw.get(key)
        if isinstance(value, str) and value:
            row[key] = value
    if raw.get("origin") == ORIGIN_SITE:
        row["origin"] = ORIGIN_SITE
    return row


def _read_file(memory_path: Path) -> list[dict]:
    try:
        data = json.loads(path_for(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = data.get("asks") if isinstance(data, dict) else None
    return [r for r in (_clean_row(x) for x in rows or []) if r is not None]


def all_rows(memory_path: Path, *, now: datetime | None = None) -> list[dict]:
    """Every live row, oldest ask first. Pure read: expiry is in memory only."""
    moment = _now(now)
    try:
        rows = _read_file(memory_path)
    except ValueError:
        return []
    return sorted((r for r in rows if _alive(r, moment)), key=lambda r: r["asked_at"])


def expiry_state(memory_path: Path, *, now: datetime | None = None) -> tuple[int, float | None]:
    """``(expired rows still on disk, epoch of the next expiry)`` — the clock the
    ``reading`` sync component folds in. Expiry writes nothing, so the file's mtime
    alone never moves when a ``needs_login`` pause ages out; the expired count moves
    on exactly those transitions (the logo cache's ``expiry_state`` precedent)."""
    moment = _now(now)
    try:
        rows = _read_file(memory_path)
    except ValueError:
        return 0, None
    expired = 0
    next_at: float | None = None
    for row in rows:
        stamp = _parse(row.get("outcome_at")) or _parse(row.get("asked_at"))
        if stamp is None:
            continue
        deadline = stamp + timedelta(days=EXPIRES_AFTER_DAYS)
        if moment >= deadline:
            expired += 1
        else:
            ts = deadline.timestamp()
            next_at = ts if next_at is None else min(next_at, ts)
    return expired, next_at


def get(memory_path: Path, url_hash: str, *, now: datetime | None = None) -> dict | None:
    return next((r for r in all_rows(memory_path, now=now) if r["url_hash"] == url_hash), None)


def waiting(memory_path: Path, *, now: datetime | None = None) -> list[dict]:
    return [r for r in all_rows(memory_path, now=now) if r["state"] == "waiting"]


@contextmanager
def _locked(memory_path: Path):
    """Read-modify-write under one exclusive lock, across processes. Yields the
    live rows; the caller returns the new list through ``commit``."""
    target = path_for(memory_path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = target.with_name(target.name + ".lock")
    with open(lock_path, "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield target
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _bounded(rows: list[dict]) -> list[dict]:
    """The rows a write keeps: site-origin rows first to go (newest 200 of them
    stay), then the oldest of the rest past ``MAX_ROWS`` — list order is time."""
    site = [r for r in rows if r.get("origin") == ORIGIN_SITE]
    if len(site) > MAX_SITE_ROWS:
        drop = {id(r) for r in site[:-MAX_SITE_ROWS]}
        rows = [r for r in rows if id(r) not in drop]
    if len(rows) > MAX_ROWS:
        overflow = len(rows) - MAX_ROWS
        # Evict site rows before any explicit one, oldest first within each class.
        order = [i for i, r in enumerate(rows) if r.get("origin") == ORIGIN_SITE] + \
                [i for i, r in enumerate(rows) if r.get("origin") != ORIGIN_SITE]
        gone = set(order[:overflow])
        rows = [r for i, r in enumerate(rows) if i not in gone]
    return rows


def _write(target: Path, rows: list[dict]) -> None:
    rows = _bounded(rows)
    fd, tmp = tempfile.mkstemp(prefix=".asks-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"v": SCHEMA_V, "asks": rows}, indent=1, sort_keys=True) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def ask(memory_path: Path, url_hash: str, *, host: str, host_class: str, now: datetime | None = None) -> dict:
    """The person's ask. A row for the same URL is reset to ``waiting`` — that is
    "Ask again" — and forgets the last outcome, its tool and its note."""
    moment = _now(now)
    with _locked(memory_path) as target:
        rows = [r for r in _read_file(memory_path) if _alive(r, moment) and r["url_hash"] != url_hash]
        row = {"url_hash": url_hash, "host": str(host or "")[:120],
               "host_class": "walled" if host_class == "walled" else "public",
               "asked_at": _iso(moment), "state": "waiting"}
        rows.append(row)
        _write(target, rows)
    return row


def record_outcome(memory_path: Path, url_hash: str, state: str, *, host: str = "", host_class: str = "public",
                   via=None, harness: str | None = None, note=None, now: datetime | None = None,
                   create: bool = False, origin: str | None = None) -> dict | None:
    """The agent's outcome for a link. The row keeps its ask time and host.
    **A link with no live row gets none** unless ``create`` is set: an outcome is
    an answer to an ask, so an agent cannot plant a state on a link nobody asked
    about (returns ``None``, writes nothing). The one caller that passes
    ``create=True`` is ``mcp_tools.record_read``, and only after
    ``reading_queue.authorizes`` said the page is on a site the person allowed
    (the row then carries ``origin: site``). ``host`` and ``host_class`` are used
    only when the stored row lacks them."""
    if state not in OUTCOMES:
        raise ValueError(f"outcome must be one of {', '.join(OUTCOMES)}")
    moment = _now(now)
    with _locked(memory_path) as target:
        rows = [r for r in _read_file(memory_path) if _alive(r, moment)]
        current = next((r for r in rows if r["url_hash"] == url_hash), None)
        if current is None and not create:
            return None
        rows = [r for r in rows if r["url_hash"] != url_hash]
        row = {"url_hash": url_hash,
               "host": (current or {}).get("host") or str(host or "")[:120],
               "host_class": (current or {}).get("host_class") or ("walled" if host_class == "walled" else "public"),
               "asked_at": (current or {}).get("asked_at") or _iso(moment), "state": state,
               "outcome_at": _iso(moment)}
        keep_origin = (current or {}).get("origin") or (origin if create and current is None else None)
        if keep_origin == ORIGIN_SITE:
            row["origin"] = ORIGIN_SITE
        for key, value in (("via", clean_via(via)), ("harness", (harness or "").strip()[:60] or None),
                           ("note", clean_note(note))):
            if value:
                row[key] = value
        rows.append(row)
        _write(target, rows)
    return row


def drop_where(memory_path: Path, predicate, *, now: datetime | None = None) -> int:
    """Remove every live row ``predicate(row)`` is true for and return how many.
    Prunes whatever expired beside them. Used to lift a site's ``needs_login``
    pause when the person switches the site on again."""
    moment = _now(now)
    with _locked(memory_path) as target:
        raw = _read_file(memory_path)
        rows = [r for r in raw if _alive(r, moment)]
        kept = [r for r in rows if not predicate(r)]
        if len(kept) != len(raw):
            _write(target, kept)
    return len(rows) - len(kept)


def drop(memory_path: Path, url_hash: str, *, now: datetime | None = None) -> bool:
    """Cancel an ask (or clear an outcome). True when a row was removed."""
    moment = _now(now)
    with _locked(memory_path) as target:
        raw = _read_file(memory_path)
        rows = [r for r in raw if _alive(r, moment)]
        kept = [r for r in rows if r["url_hash"] != url_hash]
        if len(kept) != len(raw):
            _write(target, kept)  # removes the ask, and prunes whatever expired beside it
    return len(kept) != len(rows)


def counts(memory_path: Path, *, now: datetime | None = None) -> dict[str, int]:
    out = {state: 0 for state in STATES}
    for row in all_rows(memory_path, now=now):
        out[row["state"]] += 1
    return out
