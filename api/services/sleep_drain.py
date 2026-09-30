"""The drain — what "Consolidate reads everything" is made of (owner, 2026-09-29).

A person-started Sleep run does not stop at ``sleep_max_episodes_per_cycle``: it
freezes the ids that were waiting when it started and reads them in batches of
that size, each batch a full pipeline that Stage 5 files and commits. The setting
keeps its name and now means *how often progress is saved*. A cancel or a plan
stop loses at most the batch in progress; the next Consolidate continues with
what is left. A scheduled cycle never drains (TODO ruling 4 — it runs on an API
key): it stays one batch.

This module is the pure half — the state the status route reports, how the next
batch is chosen, how a stop is classified — and imports nothing from
``sleep_cycle`` (which owns the loop). Everything here is counts and ids: an
episode id is a filename stem, never a title, and no number is an estimate (G107).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from api.services import engine_errors

#: Why a drain stopped before it read everything it froze.
STOP_REASONS = ("cancelled", "plan_limit", "engine", "bank_switched", "error")

#: The cumulative counters a drain reports across its batches. ``SleepState``
#: keeps them batch-local (each batch's own values are what its ``sleep_run``
#: ledger row carries); the wire adds them up.
CUMULATIVE_COUNTERS = (
    "entities_created", "entities_updated", "relationships_created", "skills_detected",
    "episodes_processed", "episodes_requeued", "questions_refreshed", "organic_resolutions",
)


@dataclass(frozen=True)
class DrainStop:
    """Why a drain stopped. ``sentence`` is a plain sentence for the person (the
    vendor's own, for a plan limit); ``resets_at`` the vendor's unix reset time
    when one was measured — never estimated."""
    reason: str
    sentence: str = ""
    resets_at: int | None = None

    def to_wire(self) -> dict:
        return {"reason": self.reason, "sentence": self.sentence or None, "resets_at": self.resets_at}


@dataclass
class DrainState:
    drain_id: str
    frozen_ids: list[str] = field(default_factory=list)   # private: never on the wire
    batch_size: int = 25
    #: Planned batches, recomputed as batches run: ``batch`` done or running plus
    #: what is still to do — a measured count, so an id another writer marked
    #: processed shrinks it rather than leaving "batch 11 of 12".
    batches: int = 0
    batch: int = 0
    filed: int = 0
    requeued: int = 0
    skipped: int = 0
    committed_batches: int = 0
    active: bool = True
    finished: bool = False
    stop: DrainStop | None = None
    totals: dict[str, int] = field(default_factory=lambda: {k: 0 for k in CUMULATIVE_COUNTERS})
    #: Frozen ids that have had their one attempt (or were found already read).
    settled: set[str] = field(default_factory=set)
    #: True once the running batch's counters are folded into ``totals`` (or the
    #: batch was discarded) — so the wire never counts them twice.
    batch_counted: bool = True
    #: Whether the once-per-drain work (decay, page reads) has run.
    decay_ran: bool = False
    #: Unprocessed episodes that were not in the frozen list — they arrived
    #: after the run started and wait for the next one. Set when the run ends.
    arrived_since: int | None = None

    @property
    def frozen(self) -> int:
        return len(self.frozen_ids)


def batches_for(n: int, size: int) -> int:
    """How many batches ``n`` episodes make at ``size`` a batch."""
    if n <= 0:
        return 0
    return -(-n // max(1, size))


def next_batch(frozen_ids: list[str], waiting: set[str], settled: set[str], size: int) -> tuple[list[str], int]:
    """The next batch: the oldest frozen ids still waiting that have not had
    their attempt, and how many more wait after it. Oldest-first because the
    frozen list keeps the queue's own order."""
    todo = [i for i in frozen_ids if i not in settled and i in waiting]
    batch = todo[:max(1, size)]
    return batch, len(todo) - len(batch)


def merged(ds: DrainState, name: str, live: int) -> int:
    """A cumulative counter for the wire: what finished batches added, plus the
    running batch's own value until it is counted."""
    return int(ds.totals.get(name, 0)) + (0 if ds.batch_counted else int(live or 0))


def classify(exc: BaseException, breaker_sentence: str | None = None,
             breaker_resets_at: int | None = None) -> DrainStop:
    """Sort an exception that escaped a batch into a stop.

    A plan limit (throttled, exhausted, overage) is not a failure — the person
    presses Consolidate again after the reset — so it carries the breaker's
    sentence (the vendor's, with the reset time in it) when one was tripped,
    else the error's own. An unusable engine is an ``engine`` stop, anything else
    ``error``."""
    resets = getattr(exc, "resets_at", None)
    resets = resets if isinstance(resets, int) and not isinstance(resets, bool) else breaker_resets_at
    if isinstance(exc, (engine_errors.EngineThrottled, engine_errors.EngineExhausted)):
        return DrainStop("plan_limit", (breaker_sentence or str(exc)).strip(), resets)
    if isinstance(exc, (engine_errors.EngineUnavailable, engine_errors.EngineModelNotFound)):
        return DrainStop("engine", str(exc).strip(), None)
    return DrainStop("error", f"{type(exc).__name__}: {exc}", None)


def to_wire(ds: DrainState | None, *, live: dict[str, int] | None = None) -> dict | None:
    """The ``drain`` block of ``GET /sleep/status`` (snake_case; the response
    model camelCases it). Counts only."""
    if ds is None:
        return None
    return {
        "id": ds.drain_id,
        "frozen": ds.frozen,
        "batch_size": ds.batch_size,
        "batch": ds.batch,
        "batches": ds.batches,
        "filed": ds.filed,
        "requeued": ds.requeued,
        "skipped": ds.skipped,
        "active": ds.active,
        "finished": ds.finished,
        "stop": ds.stop.to_wire() if ds.stop else None,
        "arrived_since": ds.arrived_since,
    }


def to_sse(ds: DrainState | None) -> dict | None:
    """The compact ``drain`` block on the ``sleep`` SSE event."""
    if ds is None:
        return None
    return {
        "batch": ds.batch, "batches": ds.batches, "filed": ds.filed, "frozen": ds.frozen,
        "active": ds.active, "stop": ds.stop.reason if ds.stop else None,
    }
