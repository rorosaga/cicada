"""One line per Sleep run — what Past nights groups its batches by (Sleep page v5).

A run is many batches: each commits and writes its own ``sleep_run`` ledger row, and a
paused run has batches on both sides of the pause. The ledger has no run-level facts
(how long it read, how long it was paused, how many conversations could not be read,
how many questions it raised), and ``GET /sleep/history`` returns one page of commits
that a long run alone can fill. So each leg of a run leaves a summary here, machine-local
in ``$CICADA_HOME/sleep/<bank>/runs.json`` (ids, counts and enums — never a title or a
line of text; the newest ``CAP`` runs), and the history entries and ``GET
/sleep/runs/{id}`` read it. A bank handed to someone else carries none of it.

Telemetry may be off: this file is not the ledger, so the grouping and the run's own
numbers survive; only the cost and per-call figures need the ledger.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from api.services import sleep_local

FILE = "runs.json"
CAP = 100


def _iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else datetime.now().timestamp(),
                                  tz=timezone.utc).isoformat(timespec="seconds")


def _path(memory_path: Path, *, create: bool = False) -> Path:
    return sleep_local.bank_dir(memory_path, create=create) / FILE


def load(memory_path: Path) -> dict:
    data = sleep_local.read_json(_path(memory_path))
    if not isinstance(data, dict):
        return {"runs": {}, "order": []}
    runs = data.get("runs") if isinstance(data.get("runs"), dict) else {}
    order = [i for i in (data.get("order") or []) if i in runs]
    return {"runs": runs, "order": order}


def get(memory_path: Path, run_id: str) -> dict | None:
    return load(memory_path)["runs"].get(run_id)


def all_runs(memory_path: Path) -> dict[str, dict]:
    return load(memory_path)["runs"]


def _save(memory_path: Path, data: dict) -> None:
    order = data["order"][-CAP:]
    data = {"runs": {i: data["runs"][i] for i in order}, "order": order}
    sleep_local.write_json(_path(memory_path, create=True), data)


def record_leg(memory_path: Path, ds, *, state: str, stop=None, reason: str | None = None,
               questions_leg: int | None = None) -> dict:
    """Fold a run's current leg into its summary. ``state``: ``running`` (a leg began),
    ``paused``, ``finished`` or ``failed``. Never raises past the caller's guard."""
    data = load(memory_path)
    prev = data["runs"].get(ds.drain_id) or {}
    now = _iso()
    pauses = [dict(p) for p in prev.get("pauses") or []]
    if state == "running" and pauses and pauses[-1].get("to") is None:
        pauses[-1]["to"] = now                      # Continue closes the open pause
    if state == "paused":
        pauses.append({"from": now, "to": None, "reason": reason or "engine",
                       "resets_at": getattr(stop, "resets_at", None)})
    questions = (int(prev.get("questions_raised") or 0) + int(questions_leg)) if questions_leg is not None \
        else prev.get("questions_raised")
    owner = ds.owner_beliefs if ds.owner_beliefs else prev.get("owner")
    summary = {
        "id": ds.drain_id,
        "started_by": ds.started_by,
        "started_at": prev.get("started_at") or now,
        "finished_at": now if state in ("finished", "failed") else None,
        "state": state,
        "frozen": ds.frozen,
        "filed": ds.filed,
        "parked": len(ds.parked),
        "skipped": ds.skipped,
        "committed_batches": ds.committed_batches,
        "batches": max(ds.batches, ds.committed_batches),
        "calls": ds.calls,
        "read_ms": ds.elapsed_ms(),
        "paused_ms": ds.paused_ms,
        "pauses": pauses,
        "questions_raised": questions,
        "owner": owner,
        "first_run": bool(ds.first_run),
    }
    data["runs"][ds.drain_id] = summary
    if ds.drain_id in data["order"]:
        data["order"].remove(ds.drain_id)
    data["order"].append(ds.drain_id)
    _save(memory_path, data)
    return summary


def close_open_pause(memory_path: Path, run_id: str) -> None:
    """Ending a paused run without continuing it: the pause has no end but the person's."""
    data = load(memory_path)
    run = data["runs"].get(run_id)
    if not run:
        return
    pauses = run.get("pauses") or []
    if pauses and pauses[-1].get("to") is None:
        pauses[-1]["to"] = _iso()
    run["state"] = "ended"
    run["finished_at"] = run.get("finished_at") or _iso()
    _save(memory_path, data)


def mark_restart_pause(memory_path: Path, run_id: str, *, paused_at_ts: float | None = None) -> None:
    """A run that was reading when its process went away (``sleep_paused.recover_after_restart``):
    its summary becomes a paused run with one open ``restart`` pause from the moment it was
    recovered — the same moment Continue measures ``paused_ms`` from — so the run's detail never
    shows 'running' for a run nothing is reading, or a pause time with no pause."""
    data = load(memory_path)
    run = data["runs"].get(run_id)
    if not run:
        return
    pauses = [dict(p) for p in run.get("pauses") or []]
    if not (pauses and pauses[-1].get("to") is None):
        pauses.append({"from": _iso(paused_at_ts), "to": None, "reason": "restart", "resets_at": None})
    run["pauses"] = pauses
    run["state"] = "paused"
    _save(memory_path, data)


def to_run_ref(summary: dict) -> dict:
    """The small ``run`` block a history entry carries."""
    return {
        "id": summary.get("id"), "batches": int(summary.get("committed_batches") or 0),
        "filed": int(summary.get("filed") or 0), "parked": int(summary.get("parked") or 0),
        "started_at": summary.get("started_at"), "finished_at": summary.get("finished_at"),
        "state": summary.get("state"), "frozen": int(summary.get("frozen") or 0),
        "started_by": summary.get("started_by", "user"),
        "pauses": len(summary.get("pauses") or []),
        "read_ms": int(summary.get("read_ms") or 0), "paused_ms": int(summary.get("paused_ms") or 0),
    }
