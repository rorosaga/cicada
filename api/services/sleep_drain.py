"""The drain — what "Consolidate reads everything" is made of (owner, 2026-09-29).

A Sleep run — one the person started or a scheduled one (TODO ruling 16) — does
not stop at ``sleep_max_episodes_per_cycle``: it freezes the ids that were waiting
when it started and reads them in batches, each batch a full pipeline that Stage 5
files and commits. The batch size (Reading options; the setting is its default)
means *how often progress is saved*. A cancel or a plan stop loses at most the
batch in progress; Continue resumes with what is left. A scheduled run reads on
the scheduled engine and never on a plan (TODO ruling 4).

This module is the pure half — the state the status route reports, how the next
batch is chosen, how a stop and a per-conversation failure are classified — and
imports nothing from ``sleep_cycle`` (which owns the loop). Everything here is
counts and ids: an episode id is a filename stem, never a title, and no number is
an estimate (G107). A number is a count of finished work from the object that did
it, drain-level counters only grow, a total is fixed when its unit starts, and a
failure is its own count (Sleep page v5, spec 4.2).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from api.services import engine_errors

#: Why a drain stopped before it read everything it froze. ``reserve`` is the
#: person's "leave room in my plan" line (a soft stop that keeps the batch).
STOP_REASONS = ("cancelled", "plan_limit", "engine", "bank_switched", "error", "reserve", "busy")

#: Why one conversation could not be read (a closed enum: ids and enums only).
UNREAD_REASONS = ("empty_answer", "timed_out", "unparseable", "refused", "other")

#: The cumulative counters a drain reports across its batches. ``SleepState``
#: keeps them batch-local (each batch's own values are what its ``sleep_run``
#: ledger row carries); the wire adds them up.
CUMULATIVE_COUNTERS = (
    "entities_created", "entities_updated", "relationships_created", "skills_detected",
    "episodes_processed", "episodes_requeued", "questions_refreshed", "organic_resolutions",
)

#: A conversation that fails for its own reasons gets this many tries before it is parked.
MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class DrainStop:
    """Why a drain stopped. ``sentence`` is a plain sentence for the person (the
    vendor's own, for a plan limit); ``resets_at`` the vendor's unix reset time
    when one was measured — never estimated. ``limit`` says which limit
    (``five_hour | seven_day | overage | unknown``) for a plan stop."""
    reason: str
    sentence: str = ""
    resets_at: int | None = None
    limit: str | None = None
    transient: bool = False                         # internal: a recoverable engine interruption

    def to_wire(self) -> dict:
        return {"reason": self.reason, "sentence": self.sentence or None,
                "resets_at": self.resets_at, "limit": self.limit}


@dataclass
class BatchLive:
    """The running batch's own live counts. A batch's numbers start over with it
    (``index`` says which batch they belong to) and fold into the drain's totals
    when it commits or vanish when it is discarded."""
    index: int = 0
    total: int = 0
    ids: list[str] = field(default_factory=list)
    started: set[str] = field(default_factory=set)
    read: set[str] = field(default_factory=set)
    failed: dict[str, str] = field(default_factory=dict)     # id -> reason enum (content) or "engine"
    engine_failed: set[str] = field(default_factory=set)      # failed because of the engine: never counted against them
    skipped: set[str] = field(default_factory=set)           # never started: the reserve line said stop
    pause_class: bool = False                                # some failure was the engine's, not the conversation's
    pause_sentence: str | None = None
    transient_stop: DrainStop | None = None           # discard this batch before its first write
    sort_done: int = 0
    sort_total: int | None = None
    decide_done: int = 0
    decide_total: int | None = None

    @property
    def reading(self) -> int:
        return len(self.started - self.read - set(self.failed))


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
    #: Frozen ids that are done with for this run: filed, parked, or found read
    #: elsewhere. A conversation that failed and awaits its retry is NOT settled.
    settled: set[str] = field(default_factory=set)
    #: True once the running batch's counters are folded into ``totals`` (or the
    #: batch was discarded) — so the wire never counts them twice.
    batch_counted: bool = True
    #: Whether the once-per-drain work (decay, page reads) has run.
    decay_ran: bool = False
    links_ran: bool = False
    #: The bank this run is pinned to (a status read hides a lingering drain of another).
    memory_path: object | None = None
    #: Unprocessed episodes that were not in the frozen list — they arrived
    #: after the run started and wait for the next one. Live while the run goes.
    arrived_since: int | None = None
    # --- Sleep page v5 ---------------------------------------------------
    started_by: str = "user"                              # user | schedule
    first_run: bool = False                               # no earlier Sleep commit in this bank
    calls: int = 0                                        # engine calls made in this run; never decreases
    started_mono: float = field(default_factory=time.monotonic)
    paused_ms: int = 0                                    # time spent paused before this leg (carried across Continue)
    filed_ids: set[str] = field(default_factory=set)
    requeued_ids: set[str] = field(default_factory=set)   # read but not filed: failed, or stopped by the reserve
    skipped_ids: set[str] = field(default_factory=set)
    origin_of: dict[str, str] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)
    #: Failed once for its own reasons; waiting for its one retry: id -> reason enum.
    unread: dict[str, str] = field(default_factory=dict)
    #: Parked in this run (a second failure): id -> reason enum.
    parked: dict[str, str] = field(default_factory=dict)
    live: BatchLive = field(default_factory=BatchLive)
    new_since: dict[str, int] = field(default_factory=dict)
    owner_beliefs: dict | None = None
    continue_after_reset: bool = False                    # the person's switch, snapshotted at start
    reserve_pct: int | None = None                        # the person's line, snapshotted at start
    reserve: dict | None = None                           # {"pct", "windows": [...]} once observed
    resumed: bool = False                                 # this leg continues an earlier one
    auto_used: int = 0                                    # automatic continues this run has used (ruling 15)
    engine_label: str | None = None                       # the engine the run resolved once, and its model
    engine_model: str | None = None
    guard: object | None = None                           # sleep_reserve.ReserveGuard, when a line is set
    ended_mono: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @property
    def frozen(self) -> int:
        return len(self.frozen_ids)

    def note_call(self) -> None:
        with self._lock:
            self.calls += 1

    def elapsed_ms(self, now: float | None = None) -> int:
        end = self.ended_mono if self.ended_mono is not None else (now if now is not None else time.monotonic())
        return max(0, int((end - self.started_mono) * 1000))


# --------------------------------------------------------------------------- #
# The seam: which drain a batch's engine calls belong to
# --------------------------------------------------------------------------- #

_BATCHES: dict[str, DrainState] = {}
_BATCHES_LOCK = threading.Lock()


def register_batch(batch_cycle_id: str, ds: DrainState) -> None:
    with _BATCHES_LOCK:
        _BATCHES[batch_cycle_id] = ds


def unregister_batch(batch_cycle_id: str) -> None:
    with _BATCHES_LOCK:
        _BATCHES.pop(batch_cycle_id, None)


def drain_for(cycle_id: str | None) -> DrainState | None:
    if not cycle_id:
        return None
    with _BATCHES_LOCK:
        return _BATCHES.get(cycle_id)


def drain_id_for(cycle_id: str | None) -> str | None:
    ds = drain_for(cycle_id)
    return ds.drain_id if ds is not None else None


def note_call(cycle_id: str | None) -> None:
    """One engine call that spawned, made by a batch of a drain. Thread-safe (the
    provider seam runs in ``to_thread``); a discarded batch's calls stay counted."""
    ds = drain_for(cycle_id)
    if ds is not None:
        ds.note_call()


def batches_for(n: int, size: int) -> int:
    """How many batches ``n`` episodes make at ``size`` a batch."""
    if n <= 0:
        return 0
    return -(-n // max(1, size))


def next_batch(frozen_ids: list[str], waiting: set[str], settled: set[str], size: int) -> tuple[list[str], int]:
    """The next batch: the oldest frozen ids still waiting that are not settled,
    and how many more wait after it. Oldest-first because the frozen list keeps
    the queue's own order."""
    todo = [i for i in frozen_ids if i not in settled and i in waiting]
    batch = todo[:max(1, size)]
    return batch, len(todo) - len(batch)


def next_batch_retrying(frozen_ids: list[str], waiting: set[str], settled: set[str], size: int,
                        attempts: dict[str, int]) -> tuple[list[str], int]:
    """``next_batch`` with the retry rule: a conversation that failed for its own
    reasons goes first in the very next batch (its one more try), then the oldest
    frozen ids in queue order."""
    todo = [i for i in frozen_ids if i not in settled and i in waiting]
    retries = [i for i in todo if attempts.get(i, 0) >= 1]
    rest = [i for i in todo if attempts.get(i, 0) < 1]
    ordered = retries + rest
    batch = ordered[:max(1, size)]
    return batch, len(ordered) - len(batch)


def merged(ds: DrainState, name: str, live: int) -> int:
    """A cumulative counter for the wire: what finished batches added, plus the
    running batch's own value until it is counted."""
    return int(ds.totals.get(name, 0)) + (0 if ds.batch_counted else int(live or 0))


def classify(exc: BaseException, breaker_sentence: str | None = None,
             breaker_resets_at: int | None = None, breaker_kind: str | None = None) -> DrainStop:
    """Sort an exception that escaped a batch into a stop.

    A plan limit (throttled, exhausted, overage) is not a failure — the person
    presses Consolidate again after the reset — so it carries the breaker's
    sentence (the vendor's, with the reset time in it) when one was tripped,
    else the error's own. An exhausted transient or unusable engine is an
    ``engine`` stop; anything unexpected is ``error``."""
    resets = getattr(exc, "resets_at", None)
    resets = resets if isinstance(resets, int) and not isinstance(resets, bool) else breaker_resets_at
    if isinstance(exc, (engine_errors.EngineThrottled, engine_errors.EngineExhausted)):
        from api.services import agent_engine

        return DrainStop("plan_limit", (breaker_sentence or str(exc)).strip(), resets,
                         breaker_kind or agent_engine.limit_kind_of(exc))
    if isinstance(exc, engine_errors.RETRYABLE):
        cause = "The engine timed out." if isinstance(exc, engine_errors.EngineTimeout) else "The engine stopped answering."
        return DrainStop("engine", cause + " Continue to try again; the part it was reading will be read again.",
                         transient=True)
    if isinstance(exc, (engine_errors.EngineUnavailable, engine_errors.EngineModelNotFound)):
        return DrainStop("engine", str(exc).strip(), None)
    return DrainStop("error", f"{type(exc).__name__}: {exc}", None)


def classify_episode(exc: BaseException) -> tuple[str, str | None]:
    """One conversation's failure: ``("pause", None)`` when it is the engine's
    (throttled, exhausted, unavailable, model not found, a CLI timeout or unnamed failure, a
    provider 5xx or refused request, the network — never counted against the
    conversation), else ``("content", reason)`` with a ``UNREAD_REASONS`` enum. Only
    classes that clearly belong to the conversation park it (an empty or unparseable
    answer, a provider request timeout, a context-window overflow, a content refusal); an unrecognised
    failure is content here, but a batch where EVERY conversation failed with one is
    the engine's (``sleep_cycle._run_stages``)."""
    from api.services import json_parse

    try:   # the metered rung: a key, a model or a quota is the engine's trouble, never the conversation's
        import litellm

        lx = litellm.exceptions
        if isinstance(exc, lx.Timeout):
            return "content", "timed_out"
        if isinstance(exc, lx.ContextWindowExceededError):
            return "content", "other"           # this conversation is too long for the model
        if isinstance(exc, lx.ContentPolicyViolationError):
            return "content", "refused"
        # Everything else the provider raises — a key, a model, a quota, a 5xx, a refused
        # parameter (BadRequestError on every call) — is the engine's, never one conversation's.
        try:
            import openai   # litellm's provider errors all derive from openai's APIError

            provider_base: tuple = (lx.APIError, openai.APIError)
        except Exception:  # pragma: no cover
            provider_base = (lx.APIError,)
        if isinstance(exc, provider_base) or isinstance(exc, (
                lx.AuthenticationError, lx.NotFoundError, lx.RateLimitError, lx.APIConnectionError,
                lx.BadRequestError, lx.InternalServerError, lx.ServiceUnavailableError)):
            return "pause", None
    except Exception:  # pragma: no cover - litellm missing or renamed
        pass
    if isinstance(exc, (engine_errors.EngineThrottled, engine_errors.EngineExhausted,
                        engine_errors.EngineUnavailable, engine_errors.EngineModelNotFound,
                        engine_errors.EngineFailed, engine_errors.EngineTimeout)):
        # EngineFailed: the CLI reported an error it could not name — after its own retry.
        return "pause", None
    if isinstance(exc, (engine_errors.EngineProtocolError, json_parse.EmptyResponse)):
        return "content", "empty_answer"
    if isinstance(exc, ValueError):        # includes json.JSONDecodeError
        return "content", "unparseable"
    try:   # the network or the machine, never the conversation
        import httpx

        if isinstance(exc, httpx.HTTPError):
            return "pause", None
    except Exception:  # pragma: no cover - httpx missing
        pass
    if isinstance(exc, (OSError, ConnectionError)):
        return "pause", None
    return "content", "other"


# --------------------------------------------------------------------------- #
# The wire
# --------------------------------------------------------------------------- #

#: The five stages the strip draws, in order, with the noun each one counts.
STAGE_UNITS = (("read", "conversations"), ("sort", "names"), ("decide", "pages"),
               ("notice", None), ("file", None))


def stages_wire(ds: DrainState, completed: int, running: bool) -> list[dict]:
    """The running batch's stages. ``completed`` is ``SleepState.stage`` (stages
    finished; 5 once filed). A stage carries a fill only when it counts finished
    work (Read, Sort, Decide); Notice and File carry no number. A stage starts
    over each batch, and ``batchState.index`` says so."""
    live = ds.live
    out = []
    for n, (sid, unit) in enumerate(STAGE_UNITS):
        # Stage numbering: Read=1, Sort=2, Decide=3, Notice=4, File=5.
        state = "done" if completed > n else ("active" if running and completed == n else "pending")
        done, total = 0, None
        if sid == "read":
            done, total = len(live.read) + len(live.failed), live.total or None
            if state == "done":
                done = total or done
        elif sid == "sort":
            done, total = live.sort_done, live.sort_total
            if state == "done" and total is not None:
                done = total
        elif sid == "decide":
            done, total = live.decide_done, live.decide_total
            if state == "done" and total is not None:
                done = total
        out.append({"id": sid, "unit": unit, "done": int(done), "total": total,
                    "failed": len(live.failed) if sid == "read" else 0, "state": state})
    return out


def origin_counts(ds: DrainState) -> dict[str, dict]:
    """Per origin: frozen = filed + read + waiting + could_not_be_read + parked + skipped,
    by construction (waiting is the remainder). ``read`` is read in the running
    batch and not yet committed; ``couldNotBeRead`` failed and awaits its retry
    (or failed in the running batch)."""
    out: dict[str, dict] = {}

    def bucket(o: str) -> dict:
        return out.setdefault(o, {"frozen": 0, "filed": 0, "read": 0, "waiting": 0,
                                  "could_not_be_read": 0, "parked": 0, "skipped": 0,
                                  "new_since": int(ds.new_since.get(o, 0))})

    for i in ds.frozen_ids:
        o = ds.origin_of.get(i, "unknown")
        b = bucket(o)
        b["frozen"] += 1
        if i in ds.filed_ids:
            b["filed"] += 1
        elif i in ds.parked:
            b["parked"] += 1
        elif i in ds.skipped_ids:
            b["skipped"] += 1
        elif i in ds.live.failed or i in ds.unread:
            b["could_not_be_read"] += 1
        elif i in ds.live.read and not ds.batch_counted:
            b["read"] += 1
        else:
            b["waiting"] += 1
    for o in ds.new_since:
        bucket(o)
    return out


def episode_state(ds: DrainState, ep_id: str) -> tuple[str, str | None, int]:
    """One frozen conversation's state for the queue: ``waiting | reading | read |
    filed | could_not_be_read | parked`` with its reason enum and attempts."""
    attempts = int(ds.attempts.get(ep_id, 0))
    if ep_id in ds.filed_ids:
        return "filed", None, attempts
    if ep_id in ds.parked:
        return "parked", ds.parked[ep_id], attempts
    if ep_id in ds.live.failed:
        return "could_not_be_read", ds.live.failed[ep_id], attempts
    if ep_id in ds.unread:
        return "could_not_be_read", ds.unread[ep_id], attempts
    if ep_id in ds.live.read and not ds.batch_counted:
        return "read", None, attempts
    if ep_id in ds.live.started and not ds.batch_counted:
        return "reading", None, attempts
    return "waiting", None, attempts


def live_arrived(ds: DrainState, unprocessed: int | None) -> int | None:
    """Episodes captured since the run began, live: everything waiting now minus
    what is still waiting of the frozen list. ``None`` when the caller has no count."""
    if unprocessed is None:
        return ds.arrived_since
    still = max(0, ds.frozen - len(ds.filed_ids) - len(ds.skipped_ids))
    return max(0, int(unprocessed) - still)


def to_wire(ds: DrainState | None, *, live: dict[str, int] | None = None,
            completed: int = 0, running: bool = False, now: float | None = None,
            unprocessed: int | None = None) -> dict | None:
    """The ``drain`` block of ``GET /sleep/status`` (snake_case; the response
    model camelCases it). Counts only."""
    if ds is None:
        return None
    lv = ds.live
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
        "arrived_since": live_arrived(ds, unprocessed) if ds.active else ds.arrived_since,
        "started_by": ds.started_by,
        "first_run": ds.first_run,
        "committed_batches": ds.committed_batches,
        "calls": ds.calls,
        "elapsed_ms": ds.elapsed_ms(now),
        "paused_ms": ds.paused_ms,
        "batch_state": {"index": lv.index, "of": ds.batches, "total": lv.total,
                        "read": len(lv.read), "reading": 0 if ds.batch_counted else lv.reading,
                        "failed": len(lv.failed)}
                       if lv.index else None,
        "stages": stages_wire(ds, completed, running) if lv.index else None,
        "by_origin": origin_counts(ds),
        "parked": len(ds.parked),
        "owner_page": ds.owner_beliefs,
        "reserve": ds.guard.wire() if ds.guard is not None else None,
        "resumed": ds.resumed,
    }


def to_sse(ds: DrainState | None, unprocessed: int | None = None) -> dict | None:
    """The compact ``drain`` block on the ``sleep`` SSE event. Every key here is
    part of the change key, so a stage tick or a call moves it — at most one event
    a second (the stream's poll)."""
    if ds is None:
        return None
    lv = ds.live
    return {
        "batch": ds.batch, "batches": ds.batches, "filed": ds.filed, "frozen": ds.frozen,
        "active": ds.active, "stop": ds.stop.reason if ds.stop else None,
        "calls": ds.calls, "read": len(lv.read), "failed": len(lv.failed),
        "sort": lv.sort_done, "decide": lv.decide_done, "parked": len(ds.parked),
        "arrived": live_arrived(ds, unprocessed) if ds.active else ds.arrived_since,
    }
