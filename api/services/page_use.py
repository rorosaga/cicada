"""How much the person's life uses each page — a derived signal, one input of the inbox order (vision item 10, S1).

**Since ruling 70 (2026-11-06) this is an input, not the order.** The inbox is ordered by the expected change in what
gets read (``question_order``), whose ``exposure`` term combines this table (what was *said*) with the read counter
(``page_reads``, what was *read*); an empty or absent counter leaves exactly this signal. ``rank`` and ``USE_WEIGHT``
(priority + 0.5 x use) are gone; ``scores``, ``item_use`` and ``bucket`` stay (``still_questions``, the nickname
proposer, the ``page_use`` bucket on resolution rows).

The owner (2026-10-28): "just have the user answer at first those things linked to more accessed entities". No
per-page view counter existed (``page_reads`` now adds one, apart from the ledger), and the one place card opens and recall
hits were counted — the telemetry ledger — is machine-global, holds no bank, and carries the rail "nothing learned from it is auto-applied", so an order learned
from it would be exactly that. The signal is therefore **derived from the record**, on read, from each page's own
frontmatter through ``bank_index`` (no body, no claims, no model, nothing stored):

* **conversations** — the distinct conversations the page was said in (``source_episodes``), log-scaled: a page
  said in 30 conversations is used more than one said in 3, but not ten times more;
* **recency** — halved every :data:`HALF_LIFE_DAYS` since the page was last said (``last_referenced``), so a page
  the person lived with last year ranks under one they talk about this month;
* **links** — a small lift for the pages it is tied to (``related``), the graph's own sense of centrality.

The person's own page is always the most used (1.0); every other score is scaled into ``[0, 1]`` against the
busiest page. A question about two pages (a duplicate pair) takes the busier side's score.

:func:`lately` is apart from ``scores`` (Rodrigo, 2026-11-06: "<a-person> and <another> have come up a lot lately. Thats
why recency is important"). ``scores`` holds a lifetime, so a person said in three conversations this week stays far under
a page said in two hundred over the years. ``lately`` counts only recent conversations, each by how long ago it was said: the id's day is the conversation's own (ruling 34), never
``last_referenced``, which an inbox answer or a sync also bumps, and a memory export entry or feed item is no mention.
"""
from __future__ import annotations

import math
import os
import threading
import time
from datetime import date
from pathlib import Path

from api.services import bank_index, episode_ids, episode_time

HALF_LIFE_DAYS = 90
#: A conversation counts half after this long in :func:`lately`. Judgment: "this week" counts nearly whole, last month
#: a quarter.
LATELY_HALF_LIFE_DAYS = 14
#: Older than this a conversation counts under 5% and no header is read for it: the bank's history stays unread.
LATELY_WINDOW_DAYS = 60
LINK_WEIGHT = 0.25
#: The ledger's enum for a score (G113: ids and enums only, never a number that could fingerprint a page).
BUCKETS = (("high", 0.5), ("mid", 0.15), ("low", 0.0))

#: A table younger than this is reused even after a page write (91 ms p50 to rebuild at 8,028 pages, measured).
MAX_AGE_S = 60.0

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[tuple, dict[str, float], float]] = {}
_LATELY: dict[str, tuple[tuple, dict[str, float], float]] = {}


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


def said_lately(said_days, today: date) -> float:
    """How many conversations a page was said in on ``said_days``, each counted by its age: today 1, two weeks ago .5."""
    return sum(0.5 ** (max(0, (today - d).days) / LATELY_HALF_LIFE_DAYS) for d in said_days)


def lately(memory_path: Path, *, today: date | None = None) -> dict[str, float]:
    """``{page id: [0, 1]}`` for the pages said within :data:`LATELY_WINDOW_DAYS`; a page not listed is 0. Log-scaled
    against the page said most lately, as :func:`scores` is against the busiest: a plain share saturates in a bank with
    thousands of conversations (measured on a real one, the ten most-said pages all read .98 or more and their questions
    fell). Cached like :func:`scores`. Only a conversation inside the window has its header read, once."""
    memory_path = Path(memory_path)
    today = today or date.today()
    stamp = (_dir_mtime(memory_path / "entities"), today.isoformat())
    key = str(memory_path)
    now = time.monotonic()
    with _LOCK:
        hit = _LATELY.get(key)
        if hit is not None and (hit[0] == stamp or (hit[0][1] == stamp[1] and now - hit[2] < MAX_AGE_S)):
            return hit[1]
    timed: dict[str, date | None] = {}

    def said(episode: str) -> date | None:
        if episode not in timed:
            parsed = episode_ids.parse_episode_id(episode)
            day = _day(parsed[0]) if parsed else None
            if day is not None and (today - day).days > LATELY_WINDOW_DAYS:
                day = None
            elif day is not None:
                f = bank_index.file(memory_path, "episodes", f"{episode}.md")
                if f is not None and not episode_time.counts_as_activity(f.frontmatter):
                    day = None
            timed[episode] = day
        return timed[episode]

    out: dict[str, float] = {}
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        raw = fm.get("source_episodes")
        if str(fm.get("status") or "") == "dropped" or not isinstance(raw, list):
            continue
        days = [d for d in (said(e) for e in {str(x).strip() for x in raw}) if d is not None]
        if days:
            out[f.stem] = math.log2(1 + said_lately(days, today))
    from api.services import everyday_names

    owner = everyday_names.owner_id(memory_path)
    top = max((v for k, v in out.items() if k != owner), default=0.0)
    out = {k: (min(1.0, v / top) if top > 0 else 0.0) for k, v in out.items()}
    with _LOCK:
        _LATELY[key] = (stamp, out, now)
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


def bucket(use: float | None) -> str | None:
    """The ledger's enum for a use score, or None when it was not known."""
    if use is None:
        return None
    return next(name for name, floor in BUCKETS if use >= floor)


def reset() -> None:
    """Forget every cached table (tests)."""
    with _LOCK:
        _CACHE.clear()
        _LATELY.clear()
