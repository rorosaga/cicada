"""How often the person (and their agents) actually read each page - a small counter that orders the inbox and
nothing else (TODO ruling 70, 2026-11-06; ``question_order``).

Owner (2026-11-06): "the questions should have in order the impact they might have on current accesses knowledge,
and things that might have big impact." ``page_use`` is derived from what was *said*; this is what was *read*. It is
deliberately **not** the telemetry ledger: the ledger's rail is "nothing learned from it is auto-applied", and an
order learned from it would be exactly that. The ledger event and this count share one choke point
(``telemetry.record_read``) and nothing else.

**Where, and what a row is.** ``$CICADA_HOME/page-reads/<bank id>.db`` (0700 dir, 0600 file, sqlite WAL), one file per
memory, named by the bank's id from ``banks.yaml`` (survives a rename; a copy gets a new id, so nothing mixes; the name
never holds a bank name). A row is ``(page id, value, day, weight)``: ``value`` is the decayed count of the days before
``day``, ``weight`` is the largest weight seen on ``day``. No query, no text, no timestamp beyond a day, no per-day
history. Outside every bank, never in git, never on the network, never served by any route, tool, ``/v1``, export, sync
or replica (a test walks the routes).

**What counts, once a page a day.** A day's weight is the largest seen: :data:`OPENED` (1.0) when the person opened
the card, or an agent read the page (``cicada_recall_detail``, ``cicada_project``); :data:`SHOWN` (0.25) when recall
showed it or Ask read it. Half-life :data:`HALF_LIFE_DAYS`. A looping agent adds at most 1 a day, and
:func:`reads_fraction` saturates, so no loop can pin a page.

**Today's reads count from tomorrow.** :func:`table` leaves today's weight out, so the order cannot move during a
session, cannot feed back on itself the same day, and the table is exact for the whole day (cached per day).

**Not counted:** the recall hook's automatic injection (it is picked by the person's words, which ``page_use`` already
credits through ``source_episodes``, and no one chose it); ``cicada_backlog`` (reads backlog items, not the page); Sleep;
any process with ``CICADA_CAPTURE=off`` or ``CICADA_RECALL=off`` (Cicada's own spawns); a demo bank; a replica; and
anything while ``telemetry.enabled()`` is false (no new setting: a person who turned recording off gets no counting, and
the order runs on ``page_use`` alone).

**Derived and disposable.** A missing, wiped, locked or corrupt file is an empty table, never an error; a corrupt file
is removed and starts over. Nothing here raises into a read; it logs a class name, never a page id. Deleting a bank
deletes its file (:func:`forget_bank`); a page that no longer exists is pruned once a day by the backend's inbox read.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from loguru import logger

from api.services.auth import cicada_home

#: A page the person opened, or an agent read in full; a page recall showed or Ask read.
OPENED = 1.0
SHOWN = 0.25
HALF_LIFE_DAYS = 30.0
#: ``reads = r / (r + SATURATION)``: three opened days are half a page's exposure, a looping agent never more than 1 a day.
SATURATION = 3.0
#: A row this faint and this old is dropped on a prune.
_FAINT = 0.005
DIRNAME = "page-reads"

_SCHEMA = ("""CREATE TABLE IF NOT EXISTS reads (
    page TEXT PRIMARY KEY, value REAL NOT NULL, day TEXT NOT NULL, weight REAL NOT NULL)""",)

_LOCK = threading.Lock()
#: ``(bank id, page) -> (day, largest weight written that day)``: a burst of recall hits is one write.
_WRITTEN: dict[tuple[str, str], tuple[str, float]] = {}
#: ``bank id -> (day, {page: r}, digest)``: exact for the whole day (see the module docstring).
_TABLES: dict[str, tuple[str, dict[str, float], str]] = {}
#: ``(root, name) -> (registry stamp, bank id)``
_IDS: dict[tuple[str, str], tuple[tuple[int, int], str | None]] = {}
_PRUNED: dict[str, str] = {}


def surface_weight(surface: str | None) -> float | None:
    """The weight of a ``telemetry.record_read`` surface, or None when it is not a read this counter takes."""
    s = str(surface or "").strip()
    if not s:
        return None
    if s.endswith("-backlog"):
        return None
    if s.endswith("-recall") or s == "ask":
        return SHOWN
    if s in {"app", "mcp", "cli", "remote", "project"} or s.endswith("-project"):
        return OPENED
    return None


def _decay(days: int) -> float:
    return 0.5 ** (max(0, days) / HALF_LIFE_DAYS)


def _off() -> bool:
    """The process-wide reasons not to count: recording is off, or this is one of Cicada's own spawns."""
    from api.services import telemetry

    if not telemetry.enabled():
        return True
    return any(str(os.environ.get(k, "")).strip().lower() == "off" for k in ("CICADA_CAPTURE", "CICADA_RECALL"))


def bank_key(memory_path: Path) -> str | None:
    """The bank's id from the registry beside it, or None (no registry, or no id minted yet: nothing is counted
    until the backend has given the bank one, so a path-keyed file can never split the counter)."""
    from api.services import bank_registry

    mp = Path(memory_path)
    try:
        if mp.parent.name == bank_registry.BANKS_SUBDIR and bank_registry.registry_path(mp.parent.parent).exists():
            root, name = mp.parent.parent, mp.name
        else:
            root, name = mp, bank_registry.name_of(mp)
        reg = bank_registry.registry_path(root)
        st = reg.stat()
    except Exception:  # noqa: BLE001 - an id is never worth an error
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    slot = (str(root), name)
    with _LOCK:
        hit = _IDS.get(slot)
        if hit is not None and hit[0] == stamp:
            return hit[1]
    found = bank_registry.bank_id(root, name)
    with _LOCK:
        _IDS[slot] = (stamp, found)
    return found


def _active(memory_path: Path) -> str | None:
    """The bank key when this process may count or read for ``memory_path``, else None."""
    from api.services import runtime_layout

    if _off() or runtime_layout.is_replica() or _is_demo(memory_path):
        return None
    return bank_key(memory_path)


#: ``path -> (checked at, is a demo)``: `demo_guard.is_demo` reads two files, and this runs on every inbox read.
_DEMO: dict[str, tuple[float, bool]] = {}
_DEMO_TTL_S = 30.0


def _is_demo(memory_path: Path) -> bool:
    from api.services import demo_guard

    now = time.monotonic()
    key = str(memory_path)
    with _LOCK:
        hit = _DEMO.get(key)
        if hit is not None and now - hit[0] < _DEMO_TTL_S:
            return hit[1]
    found = demo_guard.is_demo(memory_path)
    with _LOCK:
        _DEMO[key] = (now, found)
    return found


def path_for(key: str) -> Path:
    return cicada_home() / DIRNAME / f"{key}.db"


def _files(key: str) -> list[Path]:
    base = path_for(key)
    return [base, base.with_name(base.name + "-wal"), base.with_name(base.name + "-shm")]


@contextmanager
def _db(key: str, create: bool):
    target = path_for(key)
    if not create and not target.is_file():
        yield None
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass
    conn = sqlite3.connect(str(target), timeout=0.5)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        for statement in _SCHEMA:
            conn.execute(statement)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        yield conn
        conn.commit()
    finally:
        conn.close()


def _corrupt(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.DatabaseError) and not isinstance(exc, sqlite3.OperationalError)


def _discard(key: str) -> None:
    for f in _files(key):
        try:
            f.unlink()
        except OSError:
            pass
    with _LOCK:
        _TABLES.pop(key, None)
        for k in [k for k in _WRITTEN if k[0] == key]:
            _WRITTEN.pop(k, None)


def _failed(key: str, exc: BaseException, what: str) -> None:
    """Class name only - never a page id or a message."""
    logger.warning(f"page reads: {what} skipped ({type(exc).__name__})")
    if _corrupt(exc):
        _discard(key)


def count(memory_path: Path, page_id: str, surface: str, *, today: date | None = None) -> bool:
    """One read of ``page_id`` on this surface. True when a row was written. Never raises."""
    try:
        weight = surface_weight(surface)
        pid = str(page_id or "").strip()
        if weight is None or not pid:
            return False
        key = _active(memory_path)
        if key is None:
            return False
        day = (today or date.today()).isoformat()
        with _LOCK:
            seen = _WRITTEN.get((key, pid))
            if seen is not None and seen[0] == day and seen[1] >= weight:
                return False
    except Exception as exc:  # noqa: BLE001 - a count never reaches the read
        logger.warning(f"page reads: count skipped ({type(exc).__name__})")
        return False
    try:
        wrote = False
        with _db(key, create=True) as conn:
            row = conn.execute("SELECT value, day, weight FROM reads WHERE page = ?", (pid,)).fetchone()
            if row is None:
                conn.execute("INSERT INTO reads (page, value, day, weight) VALUES (?, 0, ?, ?)", (pid, day, weight))
                wrote = True
            else:
                value, row_day, row_weight = float(row[0]), str(row[1]), float(row[2])
                if row_day >= day:
                    if weight > row_weight:
                        conn.execute("UPDATE reads SET weight = ? WHERE page = ?", (weight, pid))
                        wrote = True
                else:
                    gap = (date.fromisoformat(day) - date.fromisoformat(row_day)).days
                    conn.execute("UPDATE reads SET value = ?, day = ?, weight = ? WHERE page = ?",
                                 ((value + row_weight) * _decay(gap), day, weight, pid))
                    wrote = True
        with _LOCK:
            before = _WRITTEN.get((key, pid))
            _WRITTEN[(key, pid)] = (day, max(weight, before[1]) if before is not None and before[0] == day else weight)
        return wrote
    except Exception as exc:  # noqa: BLE001
        _failed(key, exc, "count")
        return False


def table(memory_path: Path, *, today: date | None = None, live: set[str] | frozenset[str] | None = None) -> dict[str, float]:
    """``{page id: r}`` - each page's decayed count of the days BEFORE today. ``{}`` when the counter is off, absent,
    locked or corrupt. Cached for the day. ``live`` (the backend's list of pages that exist) prunes the rest once a day."""
    try:
        key = _active(memory_path)
        if key is None:
            return {}
        day = (today or date.today())
        iso = day.isoformat()
        with _LOCK:
            hit = _TABLES.get(key)
            if hit is not None and hit[0] == iso:
                cached = hit[1]
            else:
                cached = None
        if cached is not None:
            if live is not None:
                _prune(key, iso, live)
            return cached
        out: dict[str, float] = {}
        with _db(key, create=False) as conn:
            if conn is not None:
                for page, value, row_day, weight in conn.execute("SELECT page, value, day, weight FROM reads"):
                    try:
                        gap = (day - date.fromisoformat(str(row_day))).days
                    except ValueError:
                        continue
                    r = float(value) if gap <= 0 else (float(value) + float(weight)) * _decay(gap)
                    if r > 0:
                        out[str(page)] = r
        with _LOCK:
            _TABLES[key] = (iso, out, _digest(out))
        if live is not None:
            _prune(key, iso, live)
        return out
    except Exception as exc:  # noqa: BLE001
        k = None
        try:
            k = bank_key(memory_path)
        except Exception:  # noqa: BLE001
            pass
        logger.warning(f"page reads: table skipped ({type(exc).__name__})")
        if k is not None and _corrupt(exc):
            _discard(k)
        return {}


def _digest(rows: dict[str, float]) -> str:
    if not rows:
        return ""
    h = hashlib.blake2b(digest_size=8)
    for page in sorted(rows):
        h.update(f"{page}\0{rows[page]:.4f}\0".encode("utf-8"))
    return h.hexdigest()


def stamp(memory_path: Path, *, today: date | None = None) -> str:
    """What the order's ETag and built list fold in: the day-cut table's digest ("" when empty or off). Today's reads are
    not in it, so it moves at most when the day does."""
    try:
        if not table(memory_path, today=today):
            return ""
        key = _active(memory_path)
        with _LOCK:
            hit = _TABLES.get(key or "")
        return hit[2] if hit is not None else ""
    except Exception:  # noqa: BLE001
        return ""


def reads_fraction(r: float) -> float:
    return r / (r + SATURATION) if r > 0 else 0.0


def _prune(key: str, iso: str, live) -> None:
    """Once a day, in the process that owns the table (the backend's inbox read): rows for pages that no longer exist, and
    rows too faint to matter. An empty ``live`` prunes nothing - a bank that cannot list its pages is not a wipe."""
    with _LOCK:
        if _PRUNED.get(key) == iso:
            return
        _PRUNED[key] = iso
    if not live:
        return
    try:
        dropped = False
        with _db(key, create=False) as conn:
            if conn is None:
                return
            for (page,) in conn.execute("SELECT page FROM reads").fetchall():
                if page not in live:
                    conn.execute("DELETE FROM reads WHERE page = ?", (page,))
                    dropped = True
        if dropped:
            with _LOCK:
                _TABLES.pop(key, None)
    except Exception as exc:  # noqa: BLE001
        _failed(key, exc, "prune")


def forget_bank(bank_id: str | None) -> None:
    """Deleting a bank deletes its counter, and the WAL and shared-memory files beside it. Never raises."""
    key = str(bank_id or "").strip()
    if not key or "/" in key or "\\" in key or key.startswith("."):
        return
    try:
        _discard(key)
        with _LOCK:
            _PRUNED.pop(key, None)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"page reads: wipe skipped ({type(exc).__name__})")


def reset() -> None:
    """Forget every in-process memo (tests)."""
    with _LOCK:
        _WRITTEN.clear()
        _TABLES.clear()
        _IDS.clear()
        _PRUNED.clear()
        _DEMO.clear()
