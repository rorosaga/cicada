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
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from api.models.schemas import (
    CycleUsage,
    CycleUsageModel,
    CycleUsagePlan,
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

    @classmethod
    def build(cls, events) -> "Ledger":
        ledger = cls()
        for e in events:
            kind = getattr(e, "kind", "")
            refs = e.refs if isinstance(getattr(e, "refs", None), dict) else {}
            if kind == "sleep_run" and refs.get("commit"):
                ledger.runs.append(e)
            elif kind == "llm_call" and refs.get("cycle_id"):
                ledger.calls.setdefault(str(refs["cycle_id"]), []).append(e)
        return ledger

    def run_for(self, commit_hash: str):
        from api.services import sleep_history

        for run in self.runs:
            if sleep_history.commit_matches(commit_hash, str(run.refs.get("commit") or "")):
                return run
        return None


def usage_of_run(run, calls: list) -> CycleUsage | None:
    """The usage of one ``sleep_run`` and its cycle's ``llm_call`` rows."""
    refs = run.refs or {}
    if not refs.get(TAGGED_REF):
        return None   # written before calls were tagged: not recorded
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
        ))
    models.sort(key=lambda m: (-m.calls, m.model or ""))
    bases = {m.basis for m in models}
    basis = None if not bases else (bases.pop() if len(bases) == 1 else "mixed")
    plan = None
    raw = refs.get("plan")
    if isinstance(raw, dict) and isinstance(raw.get("windows"), list):
        wins = []
        for w in raw["windows"]:
            try:
                wins.append(CycleUsagePlanWindow(
                    window=str(w["window"]), before=float(w["before"]), after=float(w["after"]),
                    resets_at=w.get("resets_at") if isinstance(w.get("resets_at"), int) else None,
                    before_is_first_seen=bool(w.get("before_is_first_seen"))))
            except (KeyError, TypeError, ValueError):
                continue
        if wins:
            plan = CycleUsagePlan(connection=raw.get("connection"), windows=wins)
    return CycleUsage(
        recorded=True, engine=run.engine, connection=run.connection, models=models,
        total_cost_usd=_sum([m.cost_usd for m in models]),
        total_equiv_usd=_sum([m.equiv_cost_usd for m in models]),
        basis=basis, plan=plan,
    )


def usage_for(ledger: Ledger, commit_hash: str) -> CycleUsage | None:
    run = ledger.run_for(commit_hash)
    if run is None:
        return None
    return usage_of_run(run, ledger.calls.get(str(run.refs.get("cycle_id") or ""), []))


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
        engine=usage.engine, connection=usage.connection, plan=plan,
    )


def attach_usage(entries, events, *, detail: bool = False) -> None:
    """Join usage onto history entries: ``usage_summary`` on every row, and the
    full ``usage`` on a detail. Decay and inbox commits never have a
    ``sleep_run``, so theirs stay ``None``. One ledger pass, one index."""
    ledger = Ledger.build(events)
    for entry in entries:
        if getattr(entry, "kind", "sleep") != "sleep":
            continue
        usage = usage_for(ledger, entry.commit_hash)
        entry.usage_summary = summarize(usage)
        if detail:
            entry.usage = usage


# --------------------------------------------------------------------------- #
# The engine menu's caption sources
# --------------------------------------------------------------------------- #

_LAST_TTL_S = 30.0
_last_cache: dict[str, tuple[float, dict]] = {}


def last_cycles(events=None, bank: str | None = None) -> dict:
    """Newest recorded cycle per card: ``{"claude-plan": {...window...},
    "byok-openrouter": {"cost_usd", "as_of"}, "byok": {...}}``. The ledger is
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
            key = "openrouter" if (usage.connection or "") == "byok-openrouter" else "byok"
            out[key] = {"cost_usd": usage.total_cost_usd, "as_of": run.ts}
    if cacheable:
        _last_cache[key] = (now, out)
    return out


def reset_cache() -> None:
    _last_cache.clear()


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
