"""What a Sleep cycle cost — plan windows recorded per cycle, usage derived at read.

2026-09-28 ruling: the Sleep page's Details and engine menu show plan usage and
model prices. Everything here is a ledger read or a ledger write of numbers and
enums — never claim, query or answer text — and no bank is touched.

Write side. Every ``llm_call`` a cycle makes carries ``refs.cycle_id``
(``providers._emit``, from the ambient ``sleep:<id>`` scope). Two per-cycle
accumulators feed the ``sleep_run`` event's ``refs.plan``:

* Claude plan: each call's ``RateLimitSignal``s (``note_signals``) — the first
  and last utilization per window. Claude reports a window only after a call,
  so ``before`` is the value after the cycle's FIRST call (``before_is_first_seen``).
* ChatGPT plan: one fresh app-server snapshot at cycle start and one at the
  end, each window on its own. A failed probe records no plan block at all.

A plan's percentage is the whole plan's, so a before -> after change includes
anything else the person used meanwhile. The accumulators are popped when the
cycle finalizes and discarded in ``run()``'s ``finally``, so they stay bounded;
an aborted cycle writes no ``sleep_run`` and therefore reads as not recorded.
The engine-independent tail runs outside the cycle's scope, so its calls are
never counted here: this is the cost of consolidation.

Read side. ``Ledger`` indexes one ``telemetry.read_events`` pass; ``usage_for``
and ``summary_for`` join a commit onto its ``sleep_run`` (the same hash-prefix
rule as ``sleep_history.commit_matches``) and that run's ``llm_call`` rows.

Plan share (owner 2026-10-16: "how much of the plan, instead of money"). A plan run's
``plan_share`` says, per window, how much of it the run used, with its basis: ``measured``
(the window's own reading moved), ``under`` (it did not move at the probe's 1-point
resolution — below 1 %, never 0 %) or ``estimated`` (the run's list-price size times the
rate earlier cycles moved that window by, ``plan_share`` below). Dollars stay on the wire as
the secondary "would have cost" figure; the app decides the order.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from api.models.schemas import (
    CycleUsage,
    CycleUsageModel,
    CycleUsagePlan,
    CycleUsagePlanShare,
    CycleUsagePlanWindow,
    CycleUsageSummary,
    CycleUsageSummaryPlan,
)

#: A ``sleep_run`` carrying this ref was written by a build that tags calls;
#: without it, an absent ``llm_call`` set means "not recorded", not "no calls".
TAGGED_REF = "usage_tagged"

CLAUDE_WINDOWS = ("five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet")

_LOCK = threading.Lock()
_CLAUDE: dict[str, dict[str, dict]] = {}
_CODEX_START: dict[str, object] = {}


# --------------------------------------------------------------------------- #
# Write side: the per-cycle accumulators
# --------------------------------------------------------------------------- #


def note_signals(cycle_id: str | None, signals) -> None:
    """Fold one call's rate-limit signals into its cycle's Claude windows.
    Never raises — a signal must not break an LLM call."""
    if not cycle_id:
        return
    try:
        with _LOCK:
            windows = _CLAUDE.setdefault(cycle_id, {})
            for sig in signals or ():
                name = getattr(sig, "limit_type", None)
                u = getattr(sig, "utilization", None)
                if name not in CLAUDE_WINDOWS or u is None:
                    continue
                w = windows.get(name)
                if w is None:
                    windows[name] = {"before": float(u), "after": float(u),
                                     "resets_at": getattr(sig, "resets_at", None)}
                else:
                    reset = getattr(sig, "resets_at", None)
                    if reset is not None and w["resets_at"] is not None and reset != w["resets_at"]:
                        # The window rolled over mid-cycle: keep the pre-reset peak
                        # rather than let a post-reset low read as a fall.
                        continue
                    # Calls run concurrently, so arrival order is not time order:
                    # within one window the peak is the reading that counts.
                    w["after"] = max(w["after"], float(u))
                    if w["resets_at"] is None:
                        w["resets_at"] = reset
    except Exception:  # pragma: no cover - defensive
        return


async def begin_codex(cycle_id: str) -> None:
    """Take the ChatGPT plan's start-of-cycle snapshot (fresh; ~one app-server spawn)."""
    from api.services import codex_app_server

    snap = await codex_app_server.snapshot(fresh=True)
    with _LOCK:
        _CODEX_START[cycle_id] = snap


def discard(cycle_id: str | None) -> None:
    if not cycle_id:
        return
    with _LOCK:
        _CLAUDE.pop(cycle_id, None)
        _CODEX_START.pop(cycle_id, None)


def _codex_plan(start, end) -> dict | None:
    if start is None or end is None:
        return None
    before = {name: (pct, at) for name, pct, at in getattr(start, "windows", ())}
    windows = []
    for name, pct, at in getattr(end, "windows", ()):
        if name in before:
            windows.append({"window": name, "before": before[name][0] / 100.0,
                            "after": pct / 100.0, "resets_at": at, "before_is_first_seen": False})
    return {"connection": "chatgpt-plan", "windows": windows} if windows else None


async def finish(cycle_id: str, engine: str | None) -> dict | None:
    """Pop the cycle's accumulators into the ``refs.plan`` block (numbers and
    enums only), or ``None`` when nothing was observed."""
    with _LOCK:
        claude = _CLAUDE.pop(cycle_id, None)
        start = _CODEX_START.pop(cycle_id, None)
    if engine == "claude-cli" and claude:
        return {"connection": "claude-plan", "windows": [
            {"window": name, "before": w["before"], "after": w["after"],
             "resets_at": w["resets_at"], "before_is_first_seen": True}
            for name, w in claude.items()]}
    if engine == "codex-cli" and start is not None:
        from api.services import codex_app_server

        return _codex_plan(start, await codex_app_server.snapshot(fresh=True))
    return None


# --------------------------------------------------------------------------- #
# Read side: derive usage from the ledger
# --------------------------------------------------------------------------- #


def _sum(values: list[float | None]) -> float | None:
    real = [v for v in values if v is not None]
    return round(sum(real), 6) if real else None


def _model_basis(engine: str | None, billing: str | None, cost: float | None, equiv: float | None) -> str:
    if engine == "claude-cli":
        return "list"
    if engine == "codex-cli":
        return "plan"
    if billing == "free" or engine == "ollama":
        return "free"
    if cost is not None:
        return "charged"
    return "list"


@dataclass
class Ledger:
    """One pass over the ledger, grouped for the joins below."""
    runs: list = field(default_factory=list)                 # sleep_run events with a commit
    calls: dict[str, list] = field(default_factory=dict)     # cycle_id -> llm_call events
    runs_by_drain: dict[str, list] = field(default_factory=dict)    # drain_id -> its batches' sleep_run rows
    calls_by_drain: dict[str, list] = field(default_factory=dict)   # drain_id -> every llm_call of the run
    _rates: dict | None = field(default=None, repr=False)

    def rates(self) -> dict:
        """The observed plan rates (``rates_of``): this ledger's own samples over the recent
        machine-wide ones (``_recent_samples``) — a run detail's ledger opens at the run's own start,
        too late to hold the earlier cycles a rate rests on. Computed once per ledger."""
        if self._rates is None:
            samples = dict(_recent_samples())
            samples.update(rate_samples(self))
            self._rates = rates_of(samples)
        return self._rates

    @classmethod
    def build(cls, events) -> "Ledger":
        ledger = cls()
        for e in events:
            kind = getattr(e, "kind", "")
            refs = e.refs if isinstance(getattr(e, "refs", None), dict) else {}
            if kind == "sleep_run" and refs.get("commit"):
                ledger.runs.append(e)
                if refs.get("drain_id"):
                    ledger.runs_by_drain.setdefault(str(refs["drain_id"]), []).append(e)
            elif kind == "llm_call" and refs.get("cycle_id"):
                ledger.calls.setdefault(str(refs["cycle_id"]), []).append(e)
                if refs.get("drain_id"):
                    ledger.calls_by_drain.setdefault(str(refs["drain_id"]), []).append(e)
        return ledger

    def run_for(self, commit_hash: str):
        from api.services import sleep_history

        for run in self.runs:
            if sleep_history.commit_matches(commit_hash, str(run.refs.get("commit") or "")):
                return run
        return None


def _models_of(calls: list) -> list[CycleUsageModel]:
    groups: dict[tuple[str | None, str | None], list] = {}
    for c in calls:
        groups.setdefault((c.engine, c.model), []).append(c)
    models: list[CycleUsageModel] = []
    for (engine, model), rows in groups.items():
        cost = _sum([r.cost_usd for r in rows])
        equiv = _sum([r.equiv_cost_usd for r in rows])
        billing = rows[0].billing
        models.append(CycleUsageModel(
            model=model, engine=engine, calls=len(rows),
            failed_calls=sum(1 for r in rows if not r.ok),
            input_tokens=sum(int(r.input_tokens) for r in rows),
            output_tokens=sum(int(r.output_tokens) for r in rows),
            cost_usd=cost, equiv_cost_usd=equiv,
            basis=_model_basis(engine, billing, cost, equiv),
            stages=sorted({str(r.stage) for r in rows if getattr(r, "stage", None)}),
        ))
    models.sort(key=lambda m: (-m.calls, m.model or ""))
    return models


def _plan_of(raw) -> CycleUsagePlan | None:
    if not (isinstance(raw, dict) and isinstance(raw.get("windows"), list)):
        return None
    wins = []
    for w in raw["windows"]:
        try:
            wins.append(CycleUsagePlanWindow(
                window=str(w["window"]), before=float(w["before"]), after=float(w["after"]),
                resets_at=w.get("resets_at") if isinstance(w.get("resets_at"), int) else None,
                before_is_first_seen=bool(w.get("before_is_first_seen"))))
        except (KeyError, TypeError, ValueError):
            continue
    return CycleUsagePlan(connection=raw.get("connection"), windows=wins) if wins else None


def usage_of_run(run, calls: list, ledger: "Ledger | None" = None) -> CycleUsage | None:
    """The usage of one ``sleep_run`` and its cycle's ``llm_call`` rows. ``ledger`` (its ``rates``) lets a
    plan run's share be estimated where its own reading says too little; without it, no estimate. The rates
    are read only for a plan run that called something — a metered history page never pays for them."""
    refs = run.refs or {}
    if not refs.get(TAGGED_REF):
        return None   # written before calls were tagged: not recorded
    models = _models_of(calls)
    bases = {m.basis for m in models}
    basis = None if not bases else (bases.pop() if len(bases) == 1 else "mixed")
    plan = _plan_of(refs.get("plan"))
    connection = plan_connection(run.engine, run.connection, plan)
    return CycleUsage(
        recorded=True, engine=run.engine, connection=run.connection, models=models,
        total_cost_usd=_sum([m.cost_usd for m in models]),
        total_equiv_usd=_sum([m.equiv_cost_usd for m in models]),
        basis=basis, plan=plan,
        plan_share=plan_share(plan, connection, run_size(calls),
                              ledger.rates() if ledger is not None and connection else {},
                              ended_at=_epoch(run.ts)) if models else [],
    )


def usage_for_drain(ledger: Ledger, drain_id: str) -> CycleUsage | None:
    """A whole run's usage, summed by ``refs.drain_id`` over every ``llm_call`` — a paused
    or discarded batch's calls included, which a per-commit join can never see. ``None``
    (not recorded, never zero) when no batch of the run was tagged. Its plan block lists a
    window only when every batch saw the same reset time: across a reset a first-to-last
    figure is meaningless, and the per-batch windows on the run detail show it instead."""
    rows = ledger.runs_by_drain.get(drain_id) or []
    tagged = [r for r in rows if (r.refs or {}).get(TAGGED_REF)]
    if not tagged:
        return None
    rows = sorted(rows, key=lambda r: int((r.refs or {}).get("batch") or 0))
    calls = ledger.calls_by_drain.get(drain_id, [])
    models = _models_of(calls)
    bases = {m.basis for m in models}
    basis = None if not bases else (bases.pop() if len(bases) == 1 else "mixed")
    plans = [p for p in (_plan_of((r.refs or {}).get("plan")) for r in rows) if p is not None]
    plan = None
    if plans:
        merged: dict[str, CycleUsagePlanWindow] = {}
        broken: set[str] = set()
        for p in plans:
            for w in p.windows:
                cur = merged.get(w.window)
                if cur is None:
                    merged[w.window] = w
                elif cur.resets_at != w.resets_at:
                    broken.add(w.window)
                else:
                    merged[w.window] = CycleUsagePlanWindow(
                        window=w.window, before=cur.before, after=w.after, resets_at=w.resets_at,
                        before_is_first_seen=cur.before_is_first_seen)
        wins = [w for n, w in merged.items() if n not in broken]
        if wins:
            plan = CycleUsagePlan(connection=plans[0].connection, windows=wins)
    first = rows[0]
    connection = plan_connection(first.engine, first.connection, plan)
    return CycleUsage(
        recorded=True, engine=first.engine, connection=first.connection, models=models,
        total_cost_usd=_sum([m.cost_usd for m in models]),
        total_equiv_usd=_sum([m.equiv_cost_usd for m in models]),
        basis=basis, plan=plan,
        plan_share=plan_share(plan, connection, run_size(calls), ledger.rates() if connection else {},
                              ended_at=max((e for e in (_epoch(r.ts) for r in rows) if e is not None),
                                           default=None))
        if models else [],
    )


def usage_for(ledger: Ledger, commit_hash: str) -> CycleUsage | None:
    run = ledger.run_for(commit_hash)
    if run is None:
        return None
    return usage_of_run(run, ledger.calls.get(str(run.refs.get("cycle_id") or ""), []), ledger)


def summarize(usage: CycleUsage | None) -> CycleUsageSummary | None:
    """The one flat value a history row carries; ``None`` = not recorded."""
    if usage is None:
        return None
    plan = None
    if usage.plan and usage.plan.windows:
        w = usage.plan.windows[0]
        plan = CycleUsageSummaryPlan(window=w.window, before=w.before, after=w.after)
    return CycleUsageSummary(
        basis=usage.basis, cost_usd=usage.total_cost_usd, equiv_cost_usd=usage.total_equiv_usd,
        engine=usage.engine, connection=usage.connection, plan=plan, plan_share=list(usage.plan_share),
    )


def attach_usage(entries, events, *, detail: bool = False, memory_path=None) -> None:
    """Join usage onto history entries: ``usage_summary`` on every row, and the
    full ``usage`` on a detail. Decay and inbox commits never have a
    ``sleep_run``, so theirs stay ``None``. One ledger pass, one index.

    Sleep page v5: a batch commit also learns its run (``drain_id``, ``batch``, ``batches``
    from the ledger row's refs) and, from the run's machine-local summary, the run's own
    numbers — never summed from the visible page of history."""
    ledger = Ledger.build(events)
    summaries: dict = {}
    if memory_path is not None:
        try:
            from api.services import sleep_runs

            summaries = sleep_runs.all_runs(memory_path)
        except Exception:  # noqa: BLE001 - a grouping hint must never fail a history read
            summaries = {}
    for entry in entries:
        if getattr(entry, "kind", "sleep") != "sleep":
            continue
        usage = usage_for(ledger, entry.commit_hash)
        entry.usage_summary = summarize(usage)
        if detail:
            entry.usage = usage
        run = ledger.run_for(entry.commit_hash)
        refs = (run.refs or {}) if run is not None else {}
        if refs.get("drain_id"):
            entry.drain_id = str(refs["drain_id"])
            entry.batch = refs.get("batch") if isinstance(refs.get("batch"), int) else None
            entry.batches = refs.get("batches") if isinstance(refs.get("batches"), int) else None
            summary = summaries.get(entry.drain_id)
            if summary:
                from api.services import sleep_runs
                from api.models.schemas import SleepRunRef

                entry.run = SleepRunRef(**sleep_runs.to_run_ref(summary))


# --------------------------------------------------------------------------- #
# The engine menu's caption sources
# --------------------------------------------------------------------------- #

_LAST_TTL_S = 30.0
_last_cache: dict[str, tuple[float, dict]] = {}


def last_cycles(events=None, bank: str | None = None) -> dict:
    """Newest recorded cycle per card: ``{"claude-plan": {...window...},
    "byok-openrouter": {"cost_usd", "as_of"}, "byok": {...}, "last-run": {connection: {...}}}``.
    ``last-run`` is a plan card's newest RUN (a drain's whole run, else the cycle): its
    ``share`` of each window (``CycleUsagePlanShare``) and its list-price ``equiv_usd`` — what the
    engine menu leads with on a plan instead of dollars (owner 2026-10-16). The ledger is
    machine-global, so ``bank`` scopes the runs to one bank (plan windows are
    the account's, but the cycle that last reported one is still that bank's).
    Cached 30 s per bank and dropped when a cycle finalizes or the bank
    switches — ``/sleep/engine`` is polled and each read re-parses the month files."""
    now = time.monotonic()
    cacheable = events is None
    key = bank or ""
    hit = _last_cache.get(key)
    if cacheable and hit is not None and now - hit[0] < _LAST_TTL_S:
        return hit[1]
    if cacheable:
        from datetime import date, timedelta

        from api.services import telemetry

        events = telemetry.read_events(start=date.today() - timedelta(days=35))
    ledger = Ledger.build(events)
    out: dict = {}
    newest_plan_run: dict[str, object] = {}
    for run in sorted(ledger.runs, key=lambda r: r.ts):
        if bank is not None and getattr(run, "bank", None) != bank:
            continue
        usage = usage_of_run(run, ledger.calls.get(str(run.refs.get("cycle_id") or ""), []))
        if usage is None:
            continue
        if usage.plan and usage.plan.connection == "claude-plan" and usage.plan.windows:
            by_name = {w.window: w for w in usage.plan.windows}
            w = by_name.get("five_hour") or usage.plan.windows[0]
            out["claude-plan"] = {"window": w.window, "used_fraction": w.after,
                                  "resets_at": w.resets_at, "as_of": run.ts}
        if usage.basis == "charged" and usage.total_cost_usd is not None:
            card = "openrouter" if (usage.connection or "") == "byok-openrouter" else "byok"
            out[card] = {"cost_usd": usage.total_cost_usd, "as_of": run.ts}
        connection = plan_connection(run.engine, run.connection, usage.plan)
        if connection is not None and usage.models:
            newest_plan_run[connection] = run
    # Only the newest run per plan is worded, so a whole drain is summed once, not once per batch.
    for connection, run in newest_plan_run.items():
        drain = (run.refs or {}).get("drain_id")
        whole = usage_for_drain(ledger, str(drain)) if drain else None
        if whole is None:
            whole = usage_of_run(run, ledger.calls.get(str(run.refs.get("cycle_id") or ""), []), ledger)
        if whole is not None and whole.plan_share:
            out.setdefault("last-run", {})[connection] = {
                "share": list(whole.plan_share), "equiv_usd": whole.total_equiv_usd, "as_of": run.ts}
    if cacheable:
        _last_cache[key] = (now, out)
    return out


def reset_cache() -> None:
    global _samples_cache
    _last_cache.clear()
    _samples_cache = None


# --------------------------------------------------------------------------- #
# A plan run's share of each window (owner 2026-10-16)
# --------------------------------------------------------------------------- #

#: A window's reading is a fraction to two places (Claude's utilization, the ChatGPT plan's whole
#: percent), so a change under one point is invisible: "under 1%", never "0%".
RESOLUTION = 0.01
#: A cycle teaches a window's rate only when it moved the reading by at least this much — one point
#: of rounding on a two-point move is already a 50% error, so smaller moves are left out.
MIN_SAMPLE_MOVE = 0.02
#: A rate rests on at least this many such cycles, or no estimate is made.
MIN_RATE_SAMPLES = 2
#: How far back the machine-wide samples reach (the engine menu's own ledger window).
RATE_DAYS = 35
_SAMPLES_TTL_S = 300.0
#: The order a run's windows are said in: the weekly limit first (the one a person runs out of for
#: days), then the short window, then a model's own windows.
SHARE_ORDER = ("seven_day", "secondary", "five_hour", "primary", "seven_day_opus", "seven_day_sonnet")
#: A model's own window moves only for that model, so it is never estimated for a run that did not
#: report it.
_MODEL_WINDOWS = frozenset({"seven_day_opus", "seven_day_sonnet"})
_PLAN_ENGINES = {"claude-cli": "claude-plan", "codex-cli": "chatgpt-plan"}
_PLAN_CONNECTIONS = frozenset(_PLAN_ENGINES.values())

_samples_cache: tuple[str, float, dict] | None = None   # (ledger dir, read at, samples)


def plan_connection(engine: str | None, connection: str | None, plan: CycleUsagePlan | None) -> str | None:
    """The plan a run spent, or ``None`` for a metered or local run."""
    if plan is not None and plan.connection in _PLAN_CONNECTIONS:
        return plan.connection
    if connection in _PLAN_CONNECTIONS:
        return connection
    return _PLAN_ENGINES.get(engine or "")


def run_size(calls: list) -> float | None:
    """A run's size as its list-price equivalent: the Claude CLI's own metering of the same tokens,
    weighted by model and by cache use — a plan's meter weighs them too, which raw token counts do not
    (an Opus token is not a Haiku token; a cache read is a tenth of a fresh one). ``None`` when a
    successful call has no figure (a partial sum would understate) or nothing was spent."""
    ok = [c for c in calls if getattr(c, "ok", True)]
    if not ok or any(c.equiv_cost_usd is None for c in ok):
        return None
    total = sum(float(c.equiv_cost_usd) for c in ok)
    return total if total > 0 else None


def rate_samples(ledger: "Ledger") -> dict:
    """``(cycle_id, window) -> (connection, moved, size)`` for every cycle that moved a plan window by
    ``MIN_SAMPLE_MOVE`` or more and whose calls all carry a list-price figure. Per cycle (one
    ``sleep_run``), where a window's reading is within one reset (``note_signals`` keeps it so)."""
    out: dict = {}
    for run in ledger.runs:
        refs = run.refs or {}
        cycle = str(refs.get("cycle_id") or "")
        plan = _plan_of(refs.get("plan"))
        if not cycle or plan is None:
            continue
        connection = plan_connection(run.engine, run.connection, plan)
        size = run_size(ledger.calls.get(cycle, []))
        if connection is None or size is None:
            continue
        ended = _epoch(run.ts)
        for w in plan.windows:
            if _rolled_over(w, ended):
                continue   # its after is the pre-reset peak: the move undercounts the cycle
            moved = w.after - w.before
            if moved >= MIN_SAMPLE_MOVE - 1e-9:
                out[(cycle, w.window)] = (connection, moved, size)
    return out


def rates_of(samples: dict) -> dict:
    """``(connection, window) -> (share per list-price dollar, samples)``, pooled (total moved over
    total size) so a big cycle weighs more than a small one. A window with fewer than
    ``MIN_RATE_SAMPLES`` cycles has no rate. Honest limits, said in the app's help: a cycle's move
    covers all use of the plan meanwhile (the rate reads high), and a Claude ``before`` is the reading
    after the cycle's first call (it reads a little low)."""
    acc: dict = {}
    for (_cycle, window), (connection, moved, size) in samples.items():
        m, total, n = acc.get((connection, window), (0.0, 0.0, 0))
        acc[(connection, window)] = (m + moved, total + size, n + 1)
    return {k: (m / total, n) for k, (m, total, n) in acc.items() if n >= MIN_RATE_SAMPLES and total > 0}


def _recent_samples() -> dict:
    """The machine-wide samples of the last ``RATE_DAYS`` days, cached ``_SAMPLES_TTL_S`` (a plan's
    rate is the account's, not a bank's). Never raises: no samples means no estimate."""
    global _samples_cache
    now = time.monotonic()
    try:
        from datetime import date, timedelta

        from api.services import telemetry

        where = str(telemetry.telemetry_dir())
        if _samples_cache is not None and _samples_cache[0] == where and now - _samples_cache[1] < _SAMPLES_TTL_S:
            return _samples_cache[2]
        samples = rate_samples(Ledger.build(telemetry.read_events(start=date.today() - timedelta(days=RATE_DAYS))))
    except Exception:  # noqa: BLE001 - an estimate's input, never worth failing a read
        return {}
    _samples_cache = (where, now, samples)
    return samples


def _epoch(ts) -> float | None:
    """A ledger ``ts`` (ISO-8601, ``Z``) as unix seconds; ``None`` when it does not parse."""
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def _rolled_over(w: CycleUsagePlanWindow, ended_at: float | None) -> bool:
    """The window reset before the run ended. Claude's ``after`` is then the pre-reset peak
    (``note_signals`` drops the post-reset readings), so after − before misses whatever the run used
    after the reset: neither a measurement nor "under 1%" can be said from it."""
    if w.resets_at is None or ended_at is None:
        return False
    reset = float(w.resets_at)
    if reset > 1e11:   # milliseconds, defensively
        reset /= 1000.0
    return reset <= ended_at


def _order(window: str) -> tuple[int, str]:
    return (SHARE_ORDER.index(window) if window in SHARE_ORDER else len(SHARE_ORDER), window)


def plan_share(plan: CycleUsagePlan | None, connection: str | None, size: float | None,
               rates: dict, *, ended_at: float | None = None) -> list[CycleUsagePlanShare]:
    """How much of each window a plan run used, each with its basis (``CycleUsagePlanShare``):

    * the reading moved by a point or more: ``measured``, the move itself;
    * it did not move: ``estimated`` when a rate gives a figure under a point (the reading caps it),
      else ``under`` — below one point, never zero;
    * it fell, or it reset before the run ended (``ended_at``, unix seconds; ``_rolled_over``), or it
      was never read: ``estimated`` when a rate exists and the window is not a model's own unread one,
      else left out — unknown.
    """
    if connection is None:
        return []
    readings = {w.window: w for w in (plan.windows if plan else [])}
    names = set(readings) | {w for (c, w) in rates if c == connection and w not in _MODEL_WINDOWS}
    out: list[CycleUsagePlanShare] = []
    for name in sorted(names, key=_order):
        rate = rates.get((connection, name))
        estimate = (size * rate[0], rate[1]) if rate is not None and size else None
        if estimate is not None and estimate[0] >= 1.0:
            estimate = None   # more than a whole window from one run is no estimate worth stating
        w = readings.get(name)
        moved = (w.after - w.before) if w is not None and not _rolled_over(w, ended_at) else None
        if moved is not None and moved >= RESOLUTION - 1e-9:
            out.append(CycleUsagePlanShare(window=name, basis="measured", share=round(moved, 4)))
        elif moved is not None and moved >= 0:
            if estimate is not None and estimate[0] < RESOLUTION:
                out.append(CycleUsagePlanShare(window=name, basis="estimated", share=round(estimate[0], 5),
                                               under=RESOLUTION, samples=estimate[1]))
            else:
                out.append(CycleUsagePlanShare(window=name, basis="under", under=RESOLUTION))
        elif estimate is not None and (w is not None or name not in _MODEL_WINDOWS):
            out.append(CycleUsagePlanShare(window=name, basis="estimated", share=round(estimate[0], 5),
                                           samples=estimate[1]))
    return out


_PRICE_CACHE: dict[str, tuple[float | None, float | None]] = {}


def list_price_per_million(model: str | None) -> tuple[float | None, float | None]:
    """A model's list price (USD per million input / output tokens) from
    litellm's bundled table — offline, tried as given then without its
    provider prefix (as ``pricing.estimate_cost`` does). ``(None, None)`` when
    unknown or for a local model. Imports litellm lazily (a multi-second import)."""
    if not model or model.lower().startswith("ollama/"):
        return None, None
    if model in _PRICE_CACHE:
        return _PRICE_CACHE[model]
    result: tuple[float | None, float | None] = (None, None)
    try:
        import litellm

        table = litellm.model_cost
        candidates = [model] + ([model.split("/", 1)[1]] if "/" in model else [])
        for cand in candidates:
            entry = table.get(cand)
            if isinstance(entry, dict):
                i, o = entry.get("input_cost_per_token"), entry.get("output_cost_per_token")
                if isinstance(i, (int, float)) or isinstance(o, (int, float)):
                    result = (round(float(i) * 1e6, 6) if isinstance(i, (int, float)) else None,
                              round(float(o) * 1e6, 6) if isinstance(o, (int, float)) else None)
                    break
    except Exception:
        result = (None, None)
    _PRICE_CACHE[model] = result
    return result
