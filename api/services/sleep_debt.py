"""Sleep debt (G106 amendment) — how far behind Sleep is, right now.

Cicada's biological metaphor already treats absence of mention as a signal
(temporal decay); this extends it the other direction: an UNPROCESSED queue
is a debt that accumulates the longer Sleep goes without running. Two
numbers come out of this, both driven off the same raw inputs:

- ``rested_pct``: "outside a cycle" — how caught-up the bank is right now.
  Falls as episodes pile up AND as the oldest one waits longer, whichever is
  worse. Never a black box: ``volume_pct``/``age_pct`` are the two
  components it's built from, and both are exposed alongside it.
- Progress, DURING a cycle, is deliberately NOT computed here — it's
  ``sleep_cycle.progress_pct``, live "episodes processed / episodes in this
  cycle" scoped to Stage 1 (``SleepState.stage1_progress`` /
  ``episodes_total`` — see that function's own docstring for why it's
  Stage-1-only), not a whole-cycle ``episodes_processed`` count (that field
  stays 0 until Stage 5 has already written and committed, so it can't
  report anything live). Needs no filesystem or git read at all — see
  ``api/routers/sleep.py`` / ``api/routers/sync.py``.

No LLM call, no `claude` spawn, no litellm — this is pure filesystem
frontmatter (via the already-cached ``bank_index``) plus one bounded git-log
read, itself cached and invalidated only on a git-HEAD change (see
``_last_cycle_at``) rather than re-run on every call. Safe to compute on
every ``/sleep/status`` request and every SSE tick.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from api.config import Settings
from api.services import bank_index, git_service, sync_service

# Reference points the two debt components are measured against.
# Deliberately simple, round numbers — legibility over precision; both are
# documented in the Copy/UI layer so "why is this 64%?" always has an answer.
#
# AGE_REFERENCE_HOURS: an episode unconsolidated for 3 days is "fully behind"
# on staleness on its own, regardless of how many others are waiting with
# it — one old episode is enough to matter.
AGE_REFERENCE_HOURS = 72.0

# Default episode-cap fallback, used as `volume_pct`'s reference (one full
# cycle's worth of episodes = "fully behind" on volume) when `settings`
# doesn't carry the field. Review fix (L5): reflected off `Settings`'s own
# field default — the SAME expression `sleep_cycle.DEFAULT_EPISODE_CAP`
# uses — rather than a separate hardcoded `25` that could silently drift
# from the real cap if only `api/config.py` were ever changed.
DEFAULT_VOLUME_REFERENCE: int = Settings.model_fields["sleep_max_episodes_per_cycle"].default


@dataclass
class SleepDebt:
    unprocessed_count: int
    oldest_unprocessed_age_hours: float | None   # None: queue is empty
    hours_since_last_cycle: float | None          # None: Sleep has never run in this bank
    has_run_before: bool
    volume_pct: int                                # 0-100: queue size vs. one cycle's cap
    age_pct: int                                    # 0-100: oldest episode's age vs. AGE_REFERENCE_HOURS
    # None ONLY when the queue is empty AND Sleep has never run — there is no
    # baseline to call "rested" (a fresh bank hasn't been evaluated, it just
    # happens to have nothing captured yet). Every other state — including
    # "queue has items, Sleep has never run" — still gets an honest number:
    # the oldest-episode age alone already tells you how far behind it is,
    # with no need for cycle history.
    rested_pct: int | None
    # G125 (4) R7 — the newest unprocessed episode's timestamp (naive local,
    # same normalisation `_parse_episode_timestamp` applies to every stamp
    # shape on disk). The `after_import` schedule mode and its settle probe
    # both need "how long has the queue been quiet" — the newest arrival, not
    # the oldest — and share this one scan rather than each re-deriving it.
    # `None` when the queue is empty.
    newest_unprocessed_at: datetime | None = None


def rested_components(
    unprocessed_count: int,
    oldest_unprocessed_age_hours: float | None,
    volume_reference: int,
) -> tuple[int, int]:
    """The two components ``rested_pct`` is ``100 - max(volume_pct, age_pct)``
    of, as a pure function of already-gathered numbers — no filesystem or git
    access — so the formula itself is unit-testable independent of how the
    raw inputs were gathered.
    """
    ref = max(1, volume_reference)
    volume_pct = round(100 * min(1.0, unprocessed_count / ref))
    if not oldest_unprocessed_age_hours or oldest_unprocessed_age_hours <= 0:
        age_pct = 0
    else:
        age_pct = round(100 * min(1.0, oldest_unprocessed_age_hours / AGE_REFERENCE_HOURS))
    return volume_pct, age_pct


def rested_pct_from_components(
    unprocessed_count: int,
    has_run_before: bool,
    volume_pct: int,
    age_pct: int,
) -> int | None:
    """``100 - max(volume_pct, age_pct)`` — take the WORSE of the two axes,
    not an average: either a lot of episodes piled up, or a single old one
    left waiting, is enough on its own to say the bank isn't caught up. The
    ``None`` case is the one the debt model explicitly refuses to guess at
    (see the docstring on ``SleepDebt.rested_pct``).
    """
    if unprocessed_count == 0 and not has_run_before:
        return None
    return 100 - max(volume_pct, age_pct)


def _parse_episode_timestamp(raw: str) -> datetime | None:
    """Episode timestamps on disk are NOT one shape. Every writer now emits
    aware UTC with an explicit ``+00:00`` (``episode_ids.utc_now_iso``, G114
    R2), but existing files are deliberately never migrated, so a bank also
    holds legacy naive-local stamps (the old ``datetime.now().isoformat()``,
    no zone) and ``Z``-suffixed UTC ones from older imports. All three must
    compare correctly against ``datetime.now()`` (naive local) in
    ``_count_and_oldest``: a naive stamp is read as LOCAL time — what the
    writer that produced it meant — and an aware one is converted down.

    Review fix (M1): this used to do ``raw.replace("Z", "")`` before
    ``fromisoformat`` — which defeated Python 3.11+'s native ``Z`` handling
    and silently discarded the UTC marker, so a ``...Z`` timestamp was read
    as naive *local* time. Verified empirically: a just-captured ``Z``
    episode reported ``age_hours == 2.00`` (a UTC+2 machine's own offset)
    instead of ~0. Fixed by letting ``fromisoformat`` parse the offset for
    real, then converting AWARE results down to local-naive via
    ``astimezone().replace(tzinfo=None)`` — the exact pattern
    ``_last_cycle_at`` below already uses correctly for git's own
    always-offset commit dates; this function was the one place still doing
    it wrong.
    """
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _count_and_oldest(memory_path: Path, *, now: datetime) -> tuple[int, float | None, datetime | None]:
    """Unprocessed episode count, the oldest one's age in hours, and the
    NEWEST one's timestamp (G125 (4) R7 — the after-import probe and
    ``next_run_at`` both need "how long has the queue been quiet", i.e. the
    newest arrival, not the oldest).

    Reads ONLY frontmatter via ``bank_index`` (never ``.body()``) — cheap
    even on a large queue, and cached across calls the way ``sleep_cycle.
    _get_unprocessed_episodes`` already relies on for the same directory.
    """
    count = 0
    oldest_hours: float | None = None
    newest_ts: datetime | None = None
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter
        if fm.get("processed", False):
            continue
        count += 1
        ts = _parse_episode_timestamp(str(fm.get("timestamp", "") or ""))
        if ts is None:
            continue
        age_hours = max(0.0, (now - ts).total_seconds() / 3600.0)
        if oldest_hours is None or age_hours > oldest_hours:
            oldest_hours = age_hours
        if newest_ts is None or ts > newest_ts:
            newest_ts = ts
    return count, oldest_hours, newest_ts


# Review fix (M2): `_last_cycle_at` used to run an uncached `git log`
# subprocess on EVERY call — and `compute()` runs on every `/sleep/status`
# request AND every 1s SSE tick, per connected client. `rested_pct` can only
# move roughly once every 43 minutes at the fastest (1% of
# AGE_REFERENCE_HOURS = 72h), so a subprocess spawn per second to answer a
# question whose answer is almost always identical to the last one was pure
# waste. `sync_service.git_head` (already on the `/sync/version` hot path —
# a `.git/HEAD` file read, no subprocess) changes if and only if a NEW
# commit lands, which is the exact and only event that can change this
# answer — so keying the cache on it is exact, never a time-based
# approximation that could show a stale answer past a real new commit.
# One entry per bank; unbounded but trivially small (a handful of banks).
_last_cycle_cache: dict[str, tuple[str, datetime | None]] = {}


async def _last_cycle_at(memory_path: Path) -> datetime | None:
    """The most recent REAL Sleep-cycle commit's local-naive timestamp.

    Deliberately excludes two commit shapes ``git_service.get_sleep_history``
    otherwise includes: an ``inbox resolution`` commit (a user action, not
    Sleep running) and a ``(decay)`` split-commit (G85 — purely arithmetic,
    always accompanied by that same run's real ``Sleep cycle <date>`` main
    commit at the same timestamp, so excluding it never loses information).
    ``None`` if Sleep has never produced a real cycle commit in this bank —
    including a bank with no ``.git`` at all.

    Cached (M2 above), invalidated only when ``git_head`` changes — never a
    stand-alone TTL, so a real new commit is always visible on the very next
    call, not up to N minutes later.
    """
    if not (memory_path / ".git").exists():
        return None

    key = str(memory_path)
    head = sync_service.git_head(memory_path)
    cached = _last_cycle_cache.get(key)
    if cached is not None and cached[0] == head:
        return cached[1]

    result = await _read_last_cycle_from_git(memory_path)
    _last_cycle_cache[key] = (head, result)
    return result


# Review fix (finding 5): a single bounded `-n 200` scan meant a bank whose
# newest REAL Sleep-cycle commit is older than the 200 most recent commits
# (a long run of manual edits, clarification resolutions, or other non-Sleep
# activity since the last cycle) reported `has_run_before=False` and lost its
# rested baseline entirely — even though Sleep genuinely HAS run before, just
# further back. `_HISTORY_PAGE_SIZE` is the per-page size for the paging scan
# below; `_HISTORY_MAX_PAGES` is a defensive (not expected-to-bite) ceiling —
# any real personal-scale bank's whole history fits in a handful of pages,
# but this stops a pathological repo from scanning forever. This only runs
# on a cache miss (see `_last_cycle_at` above) — once per NEW commit, not
# once per SSE tick — so paging further back costs nothing in the common
# case where the match is still in the first page.
_HISTORY_PAGE_SIZE = 200
_HISTORY_MAX_PAGES = 50


async def _read_last_cycle_from_git(memory_path: Path) -> datetime | None:
    """The actual (uncached) ``git log`` read ``_last_cycle_at`` caches.

    Pages through history in ``_HISTORY_PAGE_SIZE``-sized batches
    (``git log --skip=N -n 200``) until a real cycle commit is found or
    history is exhausted (a page shorter than the page size) — see the
    module-level comment above for why a single bounded scan was wrong.
    """
    sep, rec = "\x1f", "\x1e"
    for page in range(_HISTORY_MAX_PAGES):
        skip = page * _HISTORY_PAGE_SIZE
        try:
            output = await git_service._run_git(
                memory_path, "log", "-n", str(_HISTORY_PAGE_SIZE), "--skip", str(skip),
                f"--format=%aI{sep}%s{rec}",
            )
        except git_service.GitError:
            return None
        records = [r.strip("\n") for r in output.split(rec) if r.strip("\n").strip()]
        for record in records:
            fields = record.split(sep, 1)
            if len(fields) < 2:
                continue
            iso_date, subject = fields[0].strip(), fields[1].strip()
            subj = subject.lower()
            if not subj.startswith("sleep cycle") or "(decay)" in subj:
                continue
            try:
                dt = datetime.fromisoformat(iso_date)
            except ValueError:
                continue
            return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt
        if len(records) < _HISTORY_PAGE_SIZE:
            return None  # history exhausted, no real cycle commit anywhere
    return None


async def compute(memory_path: Path, settings: Settings | None = None) -> SleepDebt:
    """Gather the raw inputs (a cached frontmatter scan + one bounded git-log
    read) and apply the pure formula above. Safe to call on every
    ``/sleep/status`` request and every SSE tick — no LLM, no subprocess
    beyond the one bounded ``git log``.
    """
    now = datetime.now()
    count, oldest_hours, newest_ts = _count_and_oldest(memory_path, now=now)
    last_cycle = await _last_cycle_at(memory_path)
    hours_since = (
        max(0.0, (now - last_cycle).total_seconds() / 3600.0)
        if last_cycle is not None else None
    )

    volume_reference = int(
        getattr(settings, "sleep_max_episodes_per_cycle", DEFAULT_VOLUME_REFERENCE)
        or DEFAULT_VOLUME_REFERENCE
    ) if settings is not None else DEFAULT_VOLUME_REFERENCE

    volume_pct, age_pct = rested_components(count, oldest_hours, volume_reference)
    rested = rested_pct_from_components(count, last_cycle is not None, volume_pct, age_pct)

    return SleepDebt(
        unprocessed_count=count,
        oldest_unprocessed_age_hours=oldest_hours,
        hours_since_last_cycle=hours_since,
        has_run_before=last_cycle is not None,
        volume_pct=volume_pct,
        age_pct=age_pct,
        rested_pct=rested,
        newest_unprocessed_at=newest_ts,
    )
