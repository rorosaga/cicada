"""The newest FINISHED Sleep cycle's figures — what the Sleep page's Details › Last cycle shows (2026-10-16).

A run commits once per batch, so a long drain — or one paused waiting on Continue, possibly for days (ruling 15) —
fills any page of ``/sleep/history`` with its own batches, and the app could not find the cycle before it in the
rows it holds. The backend answers instead: walk the newest ``WALK`` "Sleep cycle" commits (the G85 ``(decay)``
commit skipped), newest first, and take the first that is

* a batch of a run whose machine-local summary (``sleep_runs``) says it ended — ``finished``, ``failed`` or
  ``ended``. The figures are the RUN's: its reading time (``read_ms``), the engine its commit names
  (``Cicada-Engine``), and its cost summed by ``drain_id`` over every call of every batch — the same sum as
  ``GET /sleep/runs/{id}``, read from the ledger back to the run's own start (a run can begin days before its last
  commit); or
* a plain cycle — a commit whose ``sleep_run`` row names no run: its own measured time and cost.

A batch of a run still ``running`` or ``paused`` is skipped, and so is any commit dated at or after such a run's start
whose ledger row is missing (telemetry off, or the row not written yet): it can only be that run's. With no ledger row
an ended run is still found by its summary's own span (``started_at`` … ``finished_at``): its time and batches survive
with telemetry off, only its cost is unknown. Ruling 12: the
usage summary carries its basis; the app words it.

Bounded: ``WALK`` = 200 commits, one ``git log`` with trailers only (no bodies) and one ledger read (two when the run
began before the oldest walked commit). Cached in memory per (bank, HEAD, the runs file's stamp): a status poll costs a
HEAD read and one ``stat``. A result whose chosen commit had no ledger row yet is recomputed after ``INCOMPLETE_TTL_S``
— the ``sleep_run`` row is written just after its commit. Ids, counts, enums and numbers only.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from pathlib import Path

from api.models.schemas import LastFinishedCycle

WALK = 200
FINISHED = frozenset({"finished", "failed", "ended"})
LIVE = frozenset({"running", "paused"})
INCOMPLETE_TTL_S = 5.0

_SEP = "\x1f"
_REC = "\x1e"
_cache: dict[str, tuple[tuple, LastFinishedCycle | None, bool, float]] = {}


def _when(value) -> datetime | None:
    try:
        out = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return out if out.tzinfo is not None else None


def _day_before(value) -> date | None:
    moment = _when(value)
    return (moment.date() - timedelta(days=1)) if moment is not None else None


def _runs_stamp(memory_path: Path) -> str:
    from api.services import sleep_runs

    try:
        st = sleep_runs._path(memory_path).stat()
        return f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return ""


async def _walk(memory_path: Path) -> list[tuple[str, str, str | None]]:
    """``(hash, iso date, engine)`` of the newest ``WALK`` consolidation commits, decay commits left out."""
    from api.services import git_service

    try:
        output = await git_service._run_git(
            memory_path, "log", f"-n{WALK}", "--regexp-ignore-case", "--grep=^Sleep cycle",
            f"--format=%H{_SEP}%ad{_SEP}%s{_SEP}%(trailers:key={git_service.ENGINE_TRAILER},valueonly,separator=%x2C){_REC}",
            "--date=iso-strict",
        )
    except git_service.GitError:
        return []
    out = []
    for record in output.split(_REC):
        fields = record.strip("\n").split(_SEP)
        if len(fields) < 4 or git_service._cycle_kind(fields[2].strip()) != "sleep":
            continue
        engine = fields[3].strip().split(",")[0].strip() or None
        out.append((fields[0].strip(), fields[1].strip(), engine))
    return out


def compute(commits: list[tuple[str, str, str | None]], summaries: dict, read_events) -> tuple[LastFinishedCycle | None, bool]:
    """Pure over its inputs: the walk, the run summaries and a ledger reader (``read_events(start=date)``). Returns
    the figures (``None`` = no finished cycle in the walk) and whether they are complete (their ledger row was there,
    or the ledger is off)."""
    from api.services import cycle_usage, telemetry

    if not commits:
        return None, True
    live_starts = [w for w in (_when(s.get("started_at")) for s in summaries.values()
                               if isinstance(s, dict) and s.get("state") in LIVE) if w is not None]
    live_since = min(live_starts) if live_starts else None
    oldest = min((d for d in (_day_before(c[1]) for c in commits) if d is not None), default=None)
    events = read_events(start=oldest)
    ledger = cycle_usage.Ledger.build(events)
    ledger_on = telemetry.enabled()

    def run_figures(commit: str, when: str, engine: str | None, drain_id: str, summary: dict | None):
        start = _day_before((summary or {}).get("started_at"))
        run_ledger = ledger
        if start is not None and oldest is not None and start < oldest:
            run_ledger = cycle_usage.Ledger.build(read_events(start=start))
        batches = run_ledger.runs_by_drain.get(drain_id, [])
        read_ms = int((summary or {}).get("read_ms") or 0) or None
        if read_ms is None:
            took = [int(b.duration_ms) for b in batches if b.duration_ms is not None]
            read_ms = sum(took) if took else None
        return LastFinishedCycle(
            commit_hash=commit, date=when, drain_id=drain_id,
            batches=int((summary or {}).get("committed_batches") or 0) or len(batches) or None,
            duration_ms=read_ms, engine=engine,
            usage_summary=cycle_usage.summarize(cycle_usage.usage_for_drain(run_ledger, drain_id)),
            state=(summary or {}).get("state") or "finished",
        )

    def ended_run_at(moment: datetime | None) -> tuple[str, dict] | None:
        """With no ledger row (telemetry off), the run whose summary spans the commit's time — the summaries are
        machine-local and survive with the ledger off."""
        if moment is None:
            return None
        for run_id, summary in summaries.items():
            if not isinstance(summary, dict) or summary.get("state") not in FINISHED:
                continue
            began, ended = _when(summary.get("started_at")), _when(summary.get("finished_at"))
            if began is not None and ended is not None and began <= moment <= ended:
                return str(run_id), summary
        return None

    for commit, when, engine in commits:
        row = ledger.run_for(commit)
        refs = (row.refs or {}) if row is not None else {}
        drain_id = str(refs["drain_id"]) if refs.get("drain_id") else None
        if drain_id:
            summary = summaries.get(drain_id) if isinstance(summaries.get(drain_id), dict) else None
            if summary is not None and summary.get("state") in LIVE:
                continue
            return run_figures(commit, when, engine, drain_id, summary), True
        if row is None:
            moment = _when(when)
            if live_since is not None and (moment is None or moment >= live_since):
                continue   # no row says otherwise, and a live run was reading then: it is that run's batch
            spanned = ended_run_at(moment)
            if spanned is not None:
                return run_figures(commit, when, engine, spanned[0], spanned[1]), not ledger_on
        return LastFinishedCycle(
            commit_hash=commit, date=when, duration_ms=row.duration_ms if row is not None else None, engine=engine,
            usage_summary=cycle_usage.summarize(cycle_usage.usage_for(ledger, commit)),
        ), row is not None or not ledger_on
    return None, True


async def latest(memory_path: Path) -> LastFinishedCycle | None:
    from api.services import sleep_runs, sync_service, telemetry

    key = (sync_service.git_head(memory_path), _runs_stamp(memory_path))
    hit = _cache.get(str(memory_path))
    if hit is not None and hit[0] == key and (hit[2] or time.monotonic() - hit[3] < INCOMPLETE_TTL_S):
        return hit[1]
    commits = await _walk(memory_path)
    try:
        summaries = sleep_runs.all_runs(memory_path)
    except Exception:  # noqa: BLE001 - a missing or unreadable summary file reads as no runs
        summaries = {}
    value, complete = compute(commits, summaries, telemetry.read_events)
    _cache[str(memory_path)] = (key, value, complete, time.monotonic())
    return value


def reset_cache() -> None:
    _cache.clear()
