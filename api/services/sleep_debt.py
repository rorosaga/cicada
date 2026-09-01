"""Sleep debt (G106 amendment) — how far behind Sleep is, right now.

Cicada's biological metaphor already treats absence of mention as a signal
(temporal decay); this extends it the other direction: an UNPROCESSED queue
is a debt that accumulates the longer Sleep goes without running. Two
numbers come out of this, both driven off the same raw inputs:

- ``rested_pct``: "outside a cycle" — how caught-up the bank is right now.
  Falls as episodes pile up AND as the oldest one waits longer, whichever is
  worse. Never a black box: ``volume_pct``/``age_pct`` are the two
  components it's built from, and both are exposed alongside it.
- Progress, DURING a cycle, is deliberately NOT computed here — it's already
  a straight ``episodes_processed / episodes_total`` of ``SleepState``
  (see ``api/routers/sleep.py`` / ``api/routers/sync.py``), which needs no
  filesystem or git read at all.

No LLM call, no `claude` spawn, no litellm — this is pure filesystem
frontmatter (via the already-cached ``bank_index``) plus one bounded git-log
read. Safe to compute on every ``/sleep/status`` request and every SSE tick.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from api.config import Settings
from api.services import bank_index, git_service

# Reference points the two debt components are measured against.
# Deliberately simple, round numbers — legibility over precision; both are
# documented in the Copy/UI layer so "why is this 64%?" always has an answer.
#
# AGE_REFERENCE_HOURS: an episode unconsolidated for 3 days is "fully behind"
# on staleness on its own, regardless of how many others are waiting with
# it — one old episode is enough to matter.
AGE_REFERENCE_HOURS = 72.0

# Default episode-cap fallback, mirrored from `Settings.
# sleep_max_episodes_per_cycle` / `sleep_cycle.DEFAULT_EPISODE_CAP` — used as
# `volume_pct`'s reference (one full cycle's worth of episodes = "fully
# behind" on volume) when `settings` doesn't carry the field.
DEFAULT_VOLUME_REFERENCE = 25


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
    """Episode timestamps are naive local time throughout this codebase
    (``datetime.now().isoformat()`` at capture, no explicit tz) — parsed the
    same way here so age math never silently applies a spurious UTC offset."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", ""))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _count_and_oldest(memory_path: Path, *, now: datetime) -> tuple[int, float | None]:
    """Unprocessed episode count + the oldest one's age in hours.

    Reads ONLY frontmatter via ``bank_index`` (never ``.body()``) — cheap
    even on a large queue, and cached across calls the way ``sleep_cycle.
    _get_unprocessed_episodes`` already relies on for the same directory.
    """
    count = 0
    oldest_hours: float | None = None
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
    return count, oldest_hours


async def _last_cycle_at(memory_path: Path) -> datetime | None:
    """The most recent REAL Sleep-cycle commit's local-naive timestamp.

    Deliberately excludes two commit shapes ``git_service.get_sleep_history``
    otherwise includes: an ``inbox resolution`` commit (a user action, not
    Sleep running) and a ``(decay)`` split-commit (G85 — purely arithmetic,
    always accompanied by that same run's real ``Sleep cycle <date>`` main
    commit at the same timestamp, so excluding it never loses information).
    ``None`` if Sleep has never produced a real cycle commit in this bank —
    including a bank with no ``.git`` at all.
    """
    if not (memory_path / ".git").exists():
        return None
    sep, rec = "\x1f", "\x1e"
    try:
        # Bounded scan: the most recent real cycle is virtually always within
        # the last handful of commits; 200 comfortably covers a bank that has
        # gone quiet for a long stretch without scanning the entire history
        # of a mature repo on every SSE tick.
        output = await git_service._run_git(
            memory_path, "log", "-n", "200", f"--format=%aI{sep}%s{rec}",
        )
    except git_service.GitError:
        return None
    for record in output.split(rec):
        record = record.strip("\n")
        if not record.strip():
            continue
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
    return None


async def compute(memory_path: Path, settings: Settings | None = None) -> SleepDebt:
    """Gather the raw inputs (a cached frontmatter scan + one bounded git-log
    read) and apply the pure formula above. Safe to call on every
    ``/sleep/status`` request and every SSE tick — no LLM, no subprocess
    beyond the one bounded ``git log``.
    """
    now = datetime.now()
    count, oldest_hours = _count_and_oldest(memory_path, now=now)
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
    )
