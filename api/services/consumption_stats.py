"""Aggregations for the Usage page (G51).

Two sources: the telemetry ledger (LLM calls, sleep runs, agentic writes) and
the memory repo's git log (``Cicada-Author``-trailered commits = memory
writes), so the calendar shows history from before the ledger existed.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from api.services import git_service, telemetry
from api.services.telemetry import UsageEvent

_RANGE_RE = re.compile(r"^(\d+)d$")


def resolve_range(range_: str, today: date) -> date | None:
    if range_ == "all":
        return None
    if range_ == "month":
        return today.replace(day=1)
    m = _RANGE_RE.match(range_ or "30d")
    days = int(m.group(1)) if m else 30
    return today - timedelta(days=days - 1)


async def memory_write_days(memory_path: Path) -> dict[str, int]:
    """ISO-day -> attributed-commit count, bucketed by **UTC** calendar day.

    ``git log --date=short`` (or any ``%ad``-based format) buckets by the
    author's recorded UTC *offset*, not UTC itself — a commit authored at
    ``2026-08-27T23:30:00-07:00`` (= ``2026-08-28T06:30Z``) would land on
    ``2026-08-27`` there, one day off from how the telemetry ledger buckets
    its explicit-UTC ``ts[:10]`` timestamps. We instead take the strict-ISO
    author date (``%aI``, includes the offset) and convert to UTC in Python
    so both sources agree on one calendar-day definition.
    """
    if not (memory_path / ".git").exists():
        return {}
    sep, rec = "\x1f", "\x1e"
    try:
        out = await git_service._run_git(memory_path, "log", f"--format=%aI{sep}%b{rec}")
    except git_service.GitError:
        return {}
    days: Counter[str] = Counter()
    for record in out.split(rec):
        if sep not in record:
            continue
        iso_date, body = record.strip("\n").split(sep, 1)
        iso_date = iso_date.strip()
        if not iso_date:
            continue
        try:
            day = datetime.fromisoformat(iso_date).astimezone(timezone.utc).date().isoformat()
        except ValueError:
            continue
        if git_service._parse_authors(body):
            days[day] += 1
    return dict(days)


def streaks(active_days: set[str], today: date) -> tuple[int, int]:
    if not active_days:
        return 0, 0
    days = sorted(date.fromisoformat(d) for d in active_days)
    best = run = 1
    for prev, cur in zip(days, days[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        best = max(best, run)
    cursor = today if today.isoformat() in active_days else today - timedelta(days=1)
    current = 0
    while cursor.isoformat() in active_days:
        current += 1
        cursor -= timedelta(days=1)
    return current, best


def _events_in(range_: str, today: date) -> list[UsageEvent]:
    start = resolve_range(range_, today)
    return telemetry.read_events(start=start, end=today)


def _sum_cost(events: list[UsageEvent], attr: str) -> float | None:
    vals = [getattr(e, attr) for e in events if getattr(e, attr) is not None]
    return round(sum(vals), 6) if vals else None


async def summary(memory_path: Path, *, range_: str, today: date) -> dict:
    events = _events_in(range_, today)
    start = resolve_range(range_, today)
    writes = {d: n for d, n in (await memory_write_days(memory_path)).items()
              if start is None or d >= start.isoformat()}
    active = set(writes) | {e.ts[:10] for e in events}
    cur, best = streaks(active, today)
    return {
        "cost_usd": _sum_cost(events, "cost_usd") or 0.0,
        "equiv_cost_usd": _sum_cost(events, "equiv_cost_usd") or 0.0,
        "invocations": sum(e.invocations for e in events if e.kind in ("llm_call", "ask")),
        "tokens": sum(e.tokens for e in events),
        "memory_writes": sum(writes.values()),
        "sleep_runs": sum(1 for e in events if e.kind == "sleep_run"),
        "agentic_writes": sum(1 for e in events if e.kind == "agentic_write"),
        "streak_current": cur,
        "streak_best": best,
        "range": range_,
        "since": start.isoformat() if start else None,
    }


def _levels(values: dict[str, float]) -> dict[str, int]:
    """Map each day's activity score to a 0-4 heatmap level.

    0 = no activity. Nonzero scores are min-max normalized against the
    range's own nonzero min/max and bucketed into levels 1-4, so the busiest
    day in view is always level 4 and the quietest nonzero day is level 1,
    regardless of the absolute scale of the range being viewed.
    """
    nonzero = [v for v in values.values() if v > 0]
    if not nonzero:
        return {d: 0 for d in values}
    lo, hi = min(nonzero), max(nonzero)
    out: dict[str, int] = {}
    for d, v in values.items():
        if v <= 0:
            out[d] = 0
        elif hi == lo:
            out[d] = 4
        else:
            frac = (v - lo) / (hi - lo)
            out[d] = 1 + min(3, int(frac * 4))
    return out


async def calendar(memory_path: Path, *, weeks: int, today: date) -> list[dict]:
    start = today - timedelta(days=weeks * 7 - 1)
    events = _activity(telemetry.read_events(start=start, end=today))
    writes = await memory_write_days(memory_path)
    per_day: dict[str, dict] = {}
    for i in range(weeks * 7):
        d = (start + timedelta(days=i)).isoformat()
        per_day[d] = {"date": d, "memory_writes": writes.get(d, 0), "events": 0, "tokens": 0,
                      "cost_usd": 0.0, "equiv_cost_usd": 0.0}
    for e in events:
        row = per_day.get(e.ts[:10])
        if row is None:
            continue
        row["events"] += 1
        row["tokens"] += e.tokens
        row["cost_usd"] += e.cost_usd or 0.0
        row["equiv_cost_usd"] += e.equiv_cost_usd or 0.0
    # Activity score for the colour level: memory writes, ledger events, and
    # token volume all contribute — tokens dominate at typical scale (a
    # single sizeable LLM call outweighs a couple of memory-write commits),
    # so a heavy-usage day reads as "busier" than a light memory-only day.
    score = {d: r["memory_writes"] + r["events"] + r["tokens"] / 1000 for d, r in per_day.items()}
    levels = _levels(score)
    for d, r in per_day.items():
        r["level"] = levels[d]
        r["cost_usd"] = round(r["cost_usd"], 6)
        r["equiv_cost_usd"] = round(r["equiv_cost_usd"], 6)
    return list(per_day.values())


def _group(events: list[UsageEvent], key: str, label: str) -> list[dict]:
    groups: dict[str, list[UsageEvent]] = defaultdict(list)
    for e in events:
        groups[getattr(e, key) or "unknown"].append(e)
    rows = []
    for name, evs in groups.items():
        rows.append({
            label: name,
            "invocations": sum(e.invocations for e in evs),
            "input_tokens": sum(e.input_tokens for e in evs),
            "output_tokens": sum(e.output_tokens for e in evs),
            "cache_read_tokens": sum(e.cache_read_tokens for e in evs),
            "cache_write_tokens": sum(e.cache_write_tokens for e in evs),
            "tokens": sum(e.tokens for e in evs),
            "cost_usd": _sum_cost(evs, "cost_usd"),
            "equiv_cost_usd": _sum_cost(evs, "equiv_cost_usd"),
        })
    rows.sort(key=lambda r: -r["tokens"])
    return rows


def _activity(events: list[UsageEvent]) -> list[UsageEvent]:
    """G105 final review F1: a ``capture`` row is a Stop-hook receipt — one per
    reply of every Claude Code/Codex session, zero tokens, zero invocations.
    Counting it as activity made the Usage page's hour-of-day chart, daily
    series, per-bank invocations and (via ``stage=<harness>``) a spurious
    ``by_stage`` row track the person's chat cadence instead of Cicada's own
    work. Feedback kinds (G113 R7) stay — a ``feedback`` stage row is a real
    user action on the graph; a capture row is not an action on anything."""
    return [e for e in events if e.kind != "capture"]


async def stats(memory_path: Path, *, range_: str, today: date) -> dict:
    events = _activity(_events_in(range_, today))
    calls = [e for e in events if e.kind in ("llm_call", "ask")]
    hours = [0] * 24
    for e in events:
        try:
            hours[int(e.ts[11:13])] += 1
        except ValueError:
            pass
    by_day: dict[str, dict] = defaultdict(lambda: {"tokens": 0, "cost_usd": 0.0, "equiv_cost_usd": 0.0, "events": 0})
    for e in events:
        d = by_day[e.ts[:10]]
        d["tokens"] += e.tokens
        d["cost_usd"] += e.cost_usd or 0.0
        d["equiv_cost_usd"] += e.equiv_cost_usd or 0.0
        d["events"] += 1
    series = [{"date": d, **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in row.items()}}
              for d, row in sorted(by_day.items())]
    peak = max(series, key=lambda r: r["tokens"], default=None)
    runs = [e for e in events if e.kind == "sleep_run" and e.duration_ms is not None]
    longest = max(runs, key=lambda e: e.duration_ms, default=None)
    by_model = _group(calls, "model", "model")
    # R7 (G113): feedback rows carry no connection and no spend, so grouping
    # them here would invent an "unknown" connection. ``by_stage``/``by_bank``
    # keep them — a `feedback` stage row is informative there. G105 R10 adds
    # the counts-only `capture` row to the same exclusion (``NON_SPEND_KINDS``);
    # ``_activity`` above already dropped it from every other view.
    spend = [e for e in events if e.kind not in telemetry.NON_SPEND_KINDS]
    all_events = _activity(telemetry.read_events())
    return {
        "by_model": by_model,
        "by_stage": _group(events, "stage", "stage"),
        "by_connection": _group(spend, "connection", "connection"),
        "by_bank": _group(events, "bank", "bank"),
        "hour_histogram": hours,
        "peak_day": {"date": peak["date"], "tokens": peak["tokens"]} if peak else None,
        "longest_sleep_run": (
            {"cycle_id": longest.refs.get("cycle_id"), "duration_ms": longest.duration_ms,
             "episodes_processed": longest.refs.get("episodes_processed"), "date": longest.ts[:10]}
            if longest else None
        ),
        "favorite_model": by_model[0]["model"] if by_model else None,
        "lifetime_tokens": sum(e.tokens for e in all_events),
        "first_event": min((e.ts[:10] for e in all_events), default=None),
        "series": series,
        "range": range_,
    }


def per_connection(events: list[UsageEvent], connection_statuses: list[dict]) -> list[dict]:
    by_conn: dict[str, list[UsageEvent]] = defaultdict(list)
    for e in events:
        by_conn[e.connection or "unknown"].append(e)
    rows = []
    for st in connection_statuses:
        evs = by_conn.get(st["id"], [])
        billing = st.get("billing", "usage")
        rows.append({
            "id": st["id"],
            "label": st.get("label", st["id"]),
            "billing": billing,
            "connected": bool(st.get("connected")),
            "price_usd_month": st.get("priceUsdMonth") if billing == "subscription" else None,
            "cost_usd": _sum_cost(evs, "cost_usd") if billing == "usage" else None,
            "equiv_cost_usd": _sum_cost(evs, "equiv_cost_usd"),
            "invocations": sum(e.invocations for e in evs),
            "tokens": sum(e.tokens for e in evs),
            "throttle_events": sum(1 for e in evs if e.throttled or e.kind == "throttle"),
            "by_model": _group([e for e in evs if e.kind in ("llm_call", "ask")], "model", "model"),
        })
    return rows
