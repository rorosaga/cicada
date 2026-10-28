"""How much the person's life uses each page — a derived signal that orders the inbox (vision item 10, S1).

The owner (2026-10-28): "just have the user answer at first those things linked to more accessed entities". No
per-page view counter exists, and the one place card opens and recall hits are counted — the telemetry ledger — is
machine-global, holds no bank, and carries the rail "nothing learned from it is auto-applied", so an order learned
from it would be exactly that. The signal is therefore **derived from the record**, on read, from each page's own
frontmatter through ``bank_index`` (no body, no claims, no model, nothing stored):

* **conversations** — the distinct conversations the page was said in (``source_episodes``), log-scaled: a page
  said in 30 conversations is used more than one said in 3, but not ten times more;
* **recency** — halved every :data:`HALF_LIFE_DAYS` since the page was last said (``last_referenced``), so a page
  the person lived with last year ranks under one they talk about this month;
* **links** — a small lift for the pages it is tied to (``related``), the graph's own sense of centrality.

The person's own page is always the most used (1.0); every other score is scaled into ``[0, 1]`` against the
busiest page. A question about two pages (a duplicate pair) takes the busier side's score.

:data:`USE_WEIGHT` is how far use moves a question against Sleep's own priority (``rank``): at 0.5 a question on the
busiest page outranks an equally-prioritised one on a forgotten page by half a priority point, and a high-priority
question on a quiet page still comes first. A default, flagged as one; the owner tunes it, never a setting.
"""
from __future__ import annotations

import math
import os
import threading
import time
from datetime import date
from pathlib import Path

from api.services import bank_index

HALF_LIFE_DAYS = 90
LINK_WEIGHT = 0.25
USE_WEIGHT = 0.5
#: The ledger's enum for a score (G113: ids and enums only, never a number that could fingerprint a page).
BUCKETS = (("high", 0.5), ("mid", 0.15), ("low", 0.0))

#: A table younger than this is reused even after a page write (91 ms p50 to rebuild at 8,028 pages, measured).
MAX_AGE_S = 60.0

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[tuple, dict[str, float], float]] = {}


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def _conversations(fm: dict) -> int:
    raw = fm.get("source_episodes") or []
    if not isinstance(raw, list):
        return 0
    return len({str(e).strip() for e in raw if str(e).strip()})


def raw_score(fm: dict, today: date) -> float:
    """One page's unscaled use: log-scaled conversations, halved per :data:`HALF_LIFE_DAYS` of silence, plus a
    small lift for its links."""
    said = _day(fm.get("last_referenced")) or _day(fm.get("created"))
    age = max(0, (today - said).days) if said else 365
    recency = 0.5 ** (age / HALF_LIFE_DAYS)
    related = fm.get("related") or []
    links = len(related) if isinstance(related, list) else 0
    return math.log2(1 + _conversations(fm)) * recency + LINK_WEIGHT * math.log2(1 + links) * recency


def scores(memory_path: Path, *, today: date | None = None) -> dict[str, float]:
    """``{page id: use in [0, 1]}`` for every page that is not dropped. Cached per bank on the entities directory's
    mtime and the day, so a second inbox read in the same state costs one stat."""
    memory_path = Path(memory_path)
    today = today or date.today()
    stamp = (_dir_mtime(memory_path / "entities"), today.isoformat())
    key = str(memory_path)
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(key)
        # The same state, or the same day within a minute: an answer rewrites a page (moving the stamp), and a
        # catch-up's run of answers must not rescan 8k pages after each one for an order that cannot move by much.
        if hit is not None and (hit[0] == stamp or (hit[0][1] == stamp[1] and now - hit[2] < MAX_AGE_S)):
            return hit[1]
    from api.services import everyday_names

    owner = everyday_names.owner_id(memory_path)
    raw: dict[str, float] = {}
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("status") or "") == "dropped":
            continue
        raw[f.stem] = raw_score(fm, today)
    top = max((v for k, v in raw.items() if k != owner), default=0.0)
    out = {k: (min(1.0, v / top) if top > 0 else 0.0) for k, v in raw.items()}
    if owner and owner in out:
        out[owner] = 1.0
    with _LOCK:
        _CACHE[key] = (stamp, out, now)
    return out


def _dir_mtime(directory: Path) -> int:
    """The entities directory's own mtime: one stat, not a scan of 8k pages. Every page write is atomic (a temp file
    renamed into place, the storage rail), so each one moves it; a hand edit in place may not, and then the order is
    one page's frontmatter behind until the next write — a derived ranking, never a fact."""
    try:
        return os.stat(directory).st_mtime_ns
    except OSError:
        return 0


def item_use(table: dict[str, float], fm: dict) -> float:
    """A question's use: its page's, or the busier of a duplicate pair's two pages (a held name has no page of its
    own, so its proposed page speaks for it)."""
    ids = [str(fm.get("entity_id") or ""), str(fm.get("merge_target_hint") or "")]
    return max((table.get(i, 0.0) for i in ids if i), default=0.0)


def rank(priority, use: float) -> float:
    """Sleep's priority, moved by use (:data:`USE_WEIGHT`). Higher asks first."""
    try:
        p = float(priority or 0.0)
    except (TypeError, ValueError):
        p = 0.0
    return p + USE_WEIGHT * max(0.0, min(1.0, use))


def bucket(use: float | None) -> str | None:
    """The ledger's enum for a use score, or None when it was not known."""
    if use is None:
        return None
    return next(name for name, floor in BUCKETS if use >= floor)


def reset() -> None:
    """Forget every cached table (tests)."""
    with _LOCK:
        _CACHE.clear()
