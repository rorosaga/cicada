"""Sleep's status, built in one place: the SSE ``sleep`` event and the home's published status frame (G132, 51d).

:func:`sleep_event` is the ``sleep`` event ``/sync/events`` sends (its change key and its payload), moved here from
the router unchanged so the home's frame carries the same keys by construction. :func:`frame` is ``GET
/sync/status``: that payload plus what a replica needs to read the bank's state as the home has it — the schedule and
its next run, the waiting and parked conversations **by id only** (never a title), a provider-neutral engine label
(plan, key, local, auto or none — never a provider's or a model's name: provider-neutral copy) and this machine's
name.
"""
from __future__ import annotations

from pathlib import Path

from api.services import sleep_cycle, sleep_drain, sleep_paused
from api.services.sleep_cycle import progress_pct


def sleep_event(state, debt, memory_path: Path) -> tuple[tuple, dict]:
    """``(change key, payload)`` of the ``sleep`` event for this bank."""
    progress = progress_pct(state)
    # Sleep page v5: the run of THIS bank only (a lingering one of another is hidden), the
    # paused record from its stat-keyed cache, and the drain's compact block with the live
    # arrival count from the debt this tick already computed — no directory scan per tick.
    ds = state.drain
    if ds is not None and getattr(ds, "memory_path", None) not in (None, memory_path):
        ds = None
    drain_sse = sleep_drain.to_sse(ds, debt.unprocessed_count)
    # G177 — the write window the app's controls follow; it flips between batches with no status change.
    writing = sleep_cycle.writing_of(state)
    paused = (None if state.status == "running" and not getattr(state, "tail_only", False)
              else sleep_paused.get_paused(memory_path))
    paused_sse = ({
        "runId": paused.get("run_id"), "reason": paused.get("reason"),
        "engineKind": (paused.get("engine_kind") or "needs_fix") if paused.get("reason") == "engine" else None,
        "autoArmed": bool((paused.get("auto_continue") or {}).get("armed")),
        "autoLeft": (paused.get("auto_continue") or {}).get("left"),
    } if paused else None)
    # Devin PR #27 round 1, finding 4: every discrete debt field the payload carries is in the key exactly; the one
    # continuous field (`hours_since_last_cycle`) is rounded to 0.1h buckets, so any threshold a client reads off it
    # is crossed within one bucket's width without an event every tick.
    hours_bucket = (
        round(debt.hours_since_last_cycle, 1)
        if debt.hours_since_last_cycle is not None else None
    )
    key = (
        state.status, state.cycle_id, state.stage, state.progress,
        debt.rested_pct, debt.volume_pct, debt.age_pct, debt.has_run_before,
        debt.unprocessed_count, progress, hours_bucket,
        # G125 R3: the raw per-episode counter, since `progress` can sit still on a big queue.
        state.stage1_progress,
        # A person-started run's batch / filed count moves between stage ticks.
        drain_sse and tuple(drain_sse.items()),
        # A pause appears, is armed or is cleared without any status change (Sleep page v5).
        paused_sse and tuple(paused_sse.items()),
        debt.parked_count,
        writing,
    )
    payload = {
        "status": state.status, "cycleId": state.cycle_id, "stage": state.stage,
        "totalStages": state.total_stages, "progress": state.progress, "error": state.error,
        "progressPct": progress,
        "restedPct": debt.rested_pct,
        "volumePct": debt.volume_pct,
        "agePct": debt.age_pct,
        "unprocessedCount": debt.unprocessed_count,
        "hasRunBefore": debt.has_run_before,
        "hoursSinceLastCycle": debt.hours_since_last_cycle,
        "queueByOrigin": dict(state.queue_by_origin),
        "readByOrigin": dict(state.read_by_origin),
        "drain": drain_sse,
        "parkedCount": debt.parked_count,
        "readableCount": debt.readable_count,
        "paused": paused_sse,
        "writing": writing,
    }
    return key, payload


def engine_label(settings) -> str:
    """Which kind of engine a Sleep started now would use, in a word no provider owns."""
    try:
        from api.services import engine_select, state_dictionary

        _chosen, resolved = engine_select.expected_settings(settings, state_dictionary._registry_for(settings),
                                                            state_dictionary.cached_connected_ids(settings))
        label = engine_select.engine_label(resolved)
        if label == engine_select.AUTO_LABEL:
            return "auto"
        if label == engine_select.NO_ENGINE_LABEL:
            return "none"
        mode = str(getattr(resolved, "llm_mode", None) or "byok").strip().lower()
    except Exception:  # noqa: BLE001 — naming the engine never fails the frame
        return "unknown"
    if mode in engine_select.SUBSCRIPTION_MODES:
        return "plan"
    if mode == "local":
        return "local"
    return "key"


def _waiting_ids(memory_path: Path) -> list[str]:
    """The consolidation queue by id (the same test as ``sleep_debt``'s count), oldest id first. Ids only."""
    from api.services import bank_index, history_index

    out = []
    for f in bank_index.files(memory_path, "episodes"):
        if history_index.waits_for_model(f.frontmatter):
            out.append(str(f.frontmatter.get("id") or f.stem))
    return sorted(out)


def queue(memory_path: Path) -> dict:
    from api.services import sleep_parked

    parked = sorted(sleep_parked.ids(memory_path))
    return {"waiting": _waiting_ids(memory_path), "parked": parked}


def schedule(memory_path: Path, debt) -> dict:
    from api.services import sleep_scheduler

    cfg = sleep_scheduler.load_schedule(memory_path)
    last = None
    if debt.hours_since_last_cycle is not None:
        from datetime import datetime, timedelta

        last = datetime.now() - timedelta(hours=debt.hours_since_last_cycle)
    return {"mode": cfg.mode, "enabled": cfg.enabled, "hour": cfg.hour, "minute": cfg.minute,
            "intervalHours": cfg.interval_hours,
            "nextAt": sleep_scheduler.next_run_at(memory_path, last_cycle_at=last,
                                                  newest_unprocessed_at=debt.newest_unprocessed_at)}


def frame(memory_path: Path, settings, state, debt, *, bank_id: str | None, bank: str | None = None) -> dict:
    """``GET /sync/status``: the home's state of this bank at its published seq."""
    from api.services import device_status, sync_log

    log = sync_log.state(memory_path)
    _key, sleep = sleep_event(state, debt, memory_path)
    try:
        # G132 phase 2: the home's id in its own group (made on the first share), so a copy knows whom it follows.
        from api.services import home_move

        device = home_move.ensure_own_identity()
    except Exception:  # noqa: BLE001 — the frame never fails on it
        device = None
    return {
        "bankId": bank_id,
        "bank": bank,
        "seq": log.get("seq"),
        "log": log,
        "home": {"device": device, "name": device_status.machine_name()},
        "sleep": sleep,
        "schedule": schedule(memory_path, debt),
        "queue": queue(memory_path),
        "engine": {"label": engine_label(settings)},
    }


def outbox_counts() -> dict:
    """What this device still has on its way to the home, counts only: its transactions and its hooks' captures."""
    from api.services import runtime_layout, tx_outbox

    try:
        from api.hooks import hook_client

        captures = hook_client.spool_module().pending(runtime_layout.cicada_home())
    except Exception:  # noqa: BLE001
        captures = 0
    return {**tx_outbox.counts(), "captures": captures}


def replica_frame(memory_path: Path, *, bank_id: str | None, bank: str | None) -> dict:
    """``GET /sync/status`` on a replica (51d): the home's frame — its Sleep event (the home's own ``sleep`` events,
    as the follower last heard them), schedule, engine label and name — with THIS copy's seq and queue, read from the
    copy itself (so at the same seq they are the home's), plus what this device still has on its way (``outbox``,
    counts only), shown beside the queue and never mixed into it."""
    from api.services import replica

    home = replica.home_frame() or {}
    rstate = replica.state()
    return {
        "bankId": bank_id,
        "bank": bank,
        "seq": rstate["seq"],
        "log": {"state": "replica", "seq": rstate["seq"], "homeSeq": rstate["homeSeq"]},
        "home": home.get("home"),
        "sleep": replica.home_sleep() or home.get("sleep"),
        "schedule": home.get("schedule"),
        "queue": queue(memory_path),
        "engine": home.get("engine"),
        "outbox": outbox_counts(),
        "replica": rstate,
    }
