"""``GET /sleep/runs/{id}`` — one whole run, assembled at read (Sleep page v5, spec SL-4).

Engine-free: the run's machine-local summary (``sleep_runs``), its batches' ``sleep_run``
ledger rows and every ``llm_call`` tagged with its ``drain_id`` — a paused or discarded
batch's calls included, which a per-commit join can never see — plus, for the pages it
touched, the first batch commits' own manifests. Ids, counts and enums only; unknown is
``null``, never zero; nothing here is a title or a line of a conversation. No model name is
hard-coded to a stage: ``models[].stages`` is the ledger's own ``stage`` per call.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from api.models.schemas import (
    SleepDrainOwnerPage,
    SleepRunBatch,
    SleepRunDetail,
    SleepRunPages,
    SleepRunPause,
)
from api.services import cycle_usage, sleep_runs, telemetry

MAX_FIRST_PAGES = 8


def _ledger_start(summary: dict | None) -> date:
    try:
        return datetime.fromisoformat(str((summary or {}).get("started_at"))).date() - timedelta(days=1)
    except (TypeError, ValueError):
        return date.today() - timedelta(days=35)


async def build(memory_path: Path, drain_id: str) -> SleepRunDetail | None:
    summary = sleep_runs.get(memory_path, drain_id)
    events = telemetry.read_events(start=_ledger_start(summary))
    ledger = cycle_usage.Ledger.build(events)
    rows = sorted(ledger.runs_by_drain.get(drain_id, []), key=lambda r: int((r.refs or {}).get("batch") or 0))
    if summary is None and not rows:
        return None
    summary = summary or {}

    batches: list[SleepRunBatch] = []
    created = 0
    for r in rows:
        refs = r.refs or {}
        plan = cycle_usage._plan_of(refs.get("plan"))
        cycle = str(refs.get("cycle_id") or "")
        batches.append(SleepRunBatch(
            index=int(refs.get("batch") or 0), commit=refs.get("commit"), ts=r.ts,
            filed=int(refs.get("episodes_processed") or 0), not_filed=int(refs.get("episodes_requeued") or 0),
            took_ms=r.duration_ms, calls=len(ledger.calls.get(cycle, [])),
            windows=list(plan.windows) if plan else [],
        ))
        created += int(refs.get("entities_created") or 0)

    usage = cycle_usage.usage_for_drain(ledger, drain_id)
    owner = summary.get("owner")
    owner_touched = None
    if isinstance(owner, dict) and owner.get("beliefs") is not None and owner.get("at_start") is not None:
        owner_touched = int(owner["beliefs"]) != int(owner["at_start"])

    first: list[str] = []
    if rows:
        from api.services import git_service

        for r in rows:
            if len(first) >= MAX_FIRST_PAGES:
                break
            commit = (r.refs or {}).get("commit")
            try:
                detail = await git_service.get_sleep_cycle_detail(memory_path, str(commit))
            except Exception:  # noqa: BLE001 - a list of names for a summary line, never worth failing
                detail = None
            for e in (detail.entities if detail else []):
                if str(e.action).lower().startswith("creat") and e.id not in first:
                    first.append(e.id)
                    if len(first) >= MAX_FIRST_PAGES:
                        break

    filed = int(summary.get("filed")) if summary.get("filed") is not None else sum(b.filed for b in batches)
    return SleepRunDetail(
        id=drain_id, started_by=str(summary.get("started_by") or "user"),
        started_at=summary.get("started_at") or (rows[0].ts if rows else None),
        finished_at=summary.get("finished_at"), state=summary.get("state"),
        filed=filed, frozen=int(summary.get("frozen") or 0), parked=int(summary.get("parked") or 0),
        skipped=int(summary.get("skipped") or 0),
        calls=int(summary["calls"]) if summary.get("calls") is not None else None,
        read_ms=int(summary["read_ms"]) if summary.get("read_ms") is not None else None,
        paused_ms=int(summary["paused_ms"]) if summary.get("paused_ms") is not None else None,
        pauses=[SleepRunPause(started_at=str(p.get("from")), ended_at=p.get("to"), reason=str(p.get("reason") or "engine"),
                              resets_at=p.get("resets_at") if isinstance(p.get("resets_at"), int) else None)
                for p in summary.get("pauses") or []],
        questions_raised=summary.get("questions_raised"),
        owner=SleepDrainOwnerPage(**{k: owner.get(k) for k in ("beliefs", "at_start", "after_first_batch")})
        if isinstance(owner, dict) and owner.get("beliefs") is not None else None,
        batches=batches, models=list(usage.models) if usage else [], usage=usage,
        pages=SleepRunPages(created=created, owner_touched=owner_touched, first=first) if rows else None,
    )
