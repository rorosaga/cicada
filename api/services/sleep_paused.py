"""A paused run, and the sidecar that lets a run outlive its process (Sleep page v5).

A run (``sleep_drain``) that stops before it has filed everything it froze — the
person pressed Pause, the plan's window is full, the engine went away, the reserve
line was reached, or Cicada restarted — leaves a small record here. **Paused is a
fact about a run, not a state of Sleep**: ``status`` stays ``idle`` and nothing is
held (``is_writing`` is false), so the scheduler, the app and an agent all carry on.
Continue rebuilds the drain from the record — same run id, the frozen list minus
what is filed now, the counters carried — so Past nights groups the batches on both
sides of the pause under one ``drain_id``. End this run deletes the record; the
queue is untouched (every conversation is still ``processed: false``).

The record is a sidecar, ``$CICADA_HOME/sleep/<bank>/run.json``, written at the
start of a run, after every batch commit and at each stop, so a backend restart
turns a run that was reading into a paused one (reason ``restart``) instead of
losing it. Whatever was filed stays filed: ``settled`` is never persisted, it is
rebuilt from ``processed: true`` on load, so a stale sidecar can only make
``filed`` slightly low, never re-read filed work. Ids, counts and enums only.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from api.services import bank_index, sleep_local

FILE = "run.json"

#: Why a run is paused (a closed set; the wire carries it).
REASONS = ("user", "plan_window", "plan_weekly", "reserve", "overage", "engine", "restart", "bank_switched", "busy")

#: A scheduled run's pause that no person chose — the process went away (``restart``), the
#: scheduled engine failed (``engine``) or a write held the bank (``busy``, G183) — is the schedule's own to replace
#: with a fresh unattended run (TODO ruling 16, final review): otherwise one quit of the app, or one night
#: the scheduled engine was away, would stop scheduled reading until someone pressed Continue.
#: A person's Pause, a plan or reserve stop, and every run a person started stay theirs.
SCHEDULE_REPLACEABLE = ("restart", "engine", "busy")
#: An engine pause is replaced only once it is this old, so a scheduled engine that stays
#: away costs one failed call every few hours, never one every five minutes.
ENGINE_RETRY_S = 6 * 3600

_cache: dict[str, tuple[tuple[int, int], dict | None]] = {}


def _path(memory_path: Path, *, create: bool = False) -> Path:
    return sleep_local.bank_dir(memory_path, create=create) / FILE


def reason_for(stop) -> str | None:
    """A drain stop as the pause reason it leaves, or ``None`` when the stop is a
    failure that leaves no record (a moved bank, an unexpected error)."""
    r = getattr(stop, "reason", None)
    if r == "cancelled":
        return "user"
    if r == "reserve":
        return "reserve"
    if r == "engine":
        return "engine"
    if r == "busy":
        return "busy"   # a write held the bank when a batch would have read it (G183): nothing of it was read
    if r == "plan_limit":
        limit = getattr(stop, "limit", None)
        return "plan_weekly" if limit == "seven_day" else "overage" if limit == "overage" else "plan_window"
    return None


def load(memory_path: Path) -> dict | None:
    """The sidecar as written (either phase), cached on its stamp so a status poll
    every second costs one ``stat``, never a parse."""
    path = _path(memory_path)
    key = str(path)
    try:
        st = path.stat()
    except OSError:
        _cache.pop(key, None)
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _cache.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    data = sleep_local.read_json(path)
    data = data if isinstance(data, dict) and data.get("run_id") else None
    _cache[key] = (stamp, data)
    return data


def get_paused(memory_path: Path) -> dict | None:
    """The record when the run is paused (not one that is still reading)."""
    rec = load(memory_path)
    return rec if rec and rec.get("phase") == "paused" else None


def exists(memory_path: Path) -> bool:
    return get_paused(memory_path) is not None


def schedule_may_replace(record: dict | None, now: float | None = None) -> bool:
    """Whether the next scheduled run may drop this paused record and read afresh."""
    if not record or record.get("phase") != "paused" or record.get("started_by") != "schedule":
        return False
    reason = record.get("reason")
    if reason not in SCHEDULE_REPLACEABLE:
        return False
    if reason == "engine":
        now = time.time() if now is None else now
        try:
            at = float(record.get("paused_at_ts") or 0)
        except (TypeError, ValueError):
            at = 0.0
        return now - at >= ENGINE_RETRY_S
    return True


def save(memory_path: Path, record: dict) -> None:
    sleep_local.write_json(_path(memory_path, create=True), record)
    _cache.pop(str(_path(memory_path)), None)


def clear(memory_path: Path) -> None:
    sleep_local.remove(_path(memory_path))
    _cache.pop(str(_path(memory_path)), None)


def sync_token(memory_path: Path) -> str:
    """What moves ``/sync/version``'s ``sleep`` component when a pause appears,
    is armed, changes diagnosis or clears: id, auto-continue state and diagnosis hash."""
    rec = get_paused(memory_path)
    if not rec:
        return ""
    ac = rec.get("auto_continue") or {}
    diagnosis = hashlib.sha256(json.dumps([rec.get("engine_kind"), rec.get("sentence")],
                                         ensure_ascii=True).encode()).hexdigest()[:16]
    return f"paused:{rec.get('run_id')}:{int(bool(ac.get('armed')))}:{ac.get('left', '')}:{diagnosis}"


def remaining_ids(memory_path: Path, record: dict) -> list[str]:
    """The frozen ids that are still waiting now, in the frozen (queue) order —
    what is filed since is settled without ever being persisted."""
    waiting = {str(f.frontmatter.get("id", f.stem))
               for f in bank_index.files(memory_path, "episodes") if not f.frontmatter.get("processed", False)}
    return [i for i in record.get("frozen_ids") or [] if i in waiting]


def build(ds, *, phase: str, stop=None, engine_label: str | None = None,
          auto_continue: dict | None = None, paused_at: float | None = None,
          elapsed_ms: int | None = None) -> dict:
    """The record for a drain in memory. ``filed`` and ``calls`` only ever grow."""
    now = time.time()
    rec = {
        "run_id": ds.drain_id, "started_by": ds.started_by, "phase": phase,
        "frozen_ids": list(ds.frozen_ids), "frozen": ds.frozen,
        "filed": ds.filed, "calls": ds.calls, "committed_batches": ds.committed_batches,
        "batch": ds.batch, "batch_size": ds.batch_size,
        "requeued": ds.requeued, "requeued_ids": sorted(ds.requeued_ids), "skipped": ds.skipped,
        "attempts": {k: int(v) for k, v in ds.attempts.items() if v},
        "timeout_attempts": {k: int(v) for k, v in ds.timeout_attempts.items() if v},
        "first_run": bool(ds.first_run), "owner_beliefs": ds.owner_beliefs,
        "engine_label": engine_label or ds.engine_label, "engine_model": ds.engine_model,
        "elapsed_ms": int(elapsed_ms if elapsed_ms is not None else ds.elapsed_ms()),
        "paused_ms": int(ds.paused_ms),
        "options": {"continue_after_reset": bool(ds.continue_after_reset), "reserve_pct": ds.reserve_pct},
        "totals": {k: int(v) for k, v in ds.totals.items()},
        "decay_ran": bool(ds.decay_ran),
        "auto_continue": auto_continue,
        # Ruling 15's "at most twice" outlives a restart and a manual Continue: the count rides
        # every write, running phase included, not only the auto-continue block.
        "auto_used": int(getattr(ds, "auto_used", 0) or 0),
    }
    if phase == "paused":
        reason = reason_for(stop) if stop is not None else "restart"
        rec.update({
            "reason": reason or "engine",
            "engine_kind": ("transient" if getattr(stop, "transient", False) else "needs_fix")
                           if reason == "engine" else None,
            "sentence": (getattr(stop, "sentence", "") or None) if stop is not None else None,
            "resets_at": getattr(stop, "resets_at", None) if stop is not None else None,
            "limit": getattr(stop, "limit", None) if stop is not None else None,
            "paused_at": datetime.fromtimestamp(paused_at or now, tz=timezone.utc).isoformat(timespec="seconds"),
            "paused_at_ts": int(paused_at or now),
        })
    return rec


def auto_used(record: dict | None) -> int:
    """How many automatic continues the run has used — the top-level count, never lower than
    what an older record's auto-continue block says."""
    if not record:
        return 0
    ac = record.get("auto_continue") if isinstance(record.get("auto_continue"), dict) else {}
    try:
        return max(int(record.get("auto_used") or 0), int((ac or {}).get("used") or 0))
    except (TypeError, ValueError):
        return 0


def to_wire(record: dict | None, memory_path: Path | None = None) -> dict | None:
    """The ``paused`` block of ``GET /sleep/status`` — only for a paused record."""
    if not record or record.get("phase") != "paused":
        return None
    ac = record.get("auto_continue")
    return {
        "run_id": record.get("run_id"),
        "started_by": record.get("started_by", "user"),
        "reason": record.get("reason"),
        "engine_kind": (record.get("engine_kind") or "needs_fix") if record.get("reason") == "engine" else None,
        "sentence": record.get("sentence"),
        "resets_at": record.get("resets_at"),
        "limit": record.get("limit"),
        "filed": int(record.get("filed") or 0),
        "frozen": int(record.get("frozen") or 0),
        "calls": int(record.get("calls") or 0),
        "committed_batches": int(record.get("committed_batches") or 0),
        "paused_at": record.get("paused_at"),
        "can_continue": bool(record.get("can_continue", True)),
        "engine_label": record.get("engine_label"),
        "auto_continue": ({
            "armed": bool(ac.get("armed")), "at": ac.get("at"), "left": ac.get("left"),
            "blocked": ac.get("blocked"),
        } if isinstance(ac, dict) else None),
    }


def recover_after_restart(memory_path: Path) -> str | None:
    """At backend start: a sidecar that says ``running`` belongs to a process that
    is gone. If everything it froze is filed, delete it; otherwise it becomes a
    paused run with reason ``restart`` (nothing was running; whatever was filed
    stays filed). Returns what it did (``deleted | paused | None``). Never raises."""
    try:
        rec = load(memory_path)
        if not rec or rec.get("phase") != "running":
            return None
        if not remaining_ids(memory_path, rec):
            clear(memory_path)
            try:   # everything it froze is filed: the run is over, not still 'running'
                from api.services import sleep_runs

                sleep_runs.close_open_pause(memory_path, str(rec.get("run_id")))
            except Exception:  # noqa: BLE001
                pass
            return "deleted"
        now = time.time()
        rec = dict(rec)
        rec.update({
            "phase": "paused", "reason": "restart", "engine_kind": None, "sentence": None, "resets_at": None, "limit": None,
            "paused_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(timespec="seconds"),
            "paused_at_ts": int(now), "can_continue": True, "auto_continue": None,
        })
        save(memory_path, rec)
        try:   # Past nights: the run's summary is paused too, with its restart pause open
            from api.services import sleep_runs

            sleep_runs.mark_restart_pause(memory_path, str(rec.get("run_id")), paused_at_ts=now)
        except Exception:  # noqa: BLE001
            pass
        return "paused"
    except Exception:
        return None
