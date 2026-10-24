"""Where a live run's model tokens and time went, read from a scratch run's telemetry ledger (ids and enums only).

    api/.venv/bin/python -m benchmarks.perf.ledger <run>/cicada-home/telemetry/events-YYYY-MM.jsonl [--since ISO] [--until ISO]

Prints one row per (kind, stage): calls, gross prompt tokens, how much of it the engine served from its prompt cache
(read) or wrote to it, output tokens and the summed model wall time. Works on any ledger a verify-cicada run writes —
never point it at the person's own ``~/.cicada``.
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
from pathlib import Path


def summarize(lines, since: str | None = None, until: str | None = None) -> dict:
    rows: dict[tuple[str, str], dict] = collections.defaultdict(lambda: collections.defaultdict(float))
    durations: dict[tuple[str, str], list[float]] = collections.defaultdict(list)
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        ts = str(ev.get("ts") or "")
        if (since and ts < since) or (until and ts > until):
            continue
        if not (ev.get("input_tokens") or ev.get("output_tokens")):
            continue
        key = (str(ev.get("kind")), str(ev.get("stage")))
        r = rows[key]
        r["calls"] += int(ev.get("invocations") or 1)
        r["input"] += int(ev.get("input_tokens") or 0)
        r["cache_read"] += int(ev.get("cache_read_tokens") or 0)
        r["cache_write"] += int(ev.get("cache_write_tokens") or 0)
        r["output"] += int(ev.get("output_tokens") or 0)
        if ev.get("duration_ms") is not None:
            durations[key].append(float(ev["duration_ms"]))
    out = []
    for (kind, stage), r in sorted(rows.items(), key=lambda kv: -kv[1]["input"]):
        d = durations.get((kind, stage), [])
        out.append({
            "kind": kind, "stage": stage, "calls": int(r["calls"]),
            "input_tokens": int(r["input"]), "cache_read": int(r["cache_read"]),
            "cache_write": int(r["cache_write"]), "uncached": int(r["input"] - r["cache_read"] - r["cache_write"]),
            "output_tokens": int(r["output"]),
            "model_s": round(sum(d) / 1000, 1),
            "p50_call_s": round(statistics.median(d) / 1000, 2) if d else None,
            "input_per_call": int(r["input"] / max(1, r["calls"])),
        })
    total = {k: sum(row[k] for row in out) for k in ("calls", "input_tokens", "cache_read", "cache_write",
                                                       "uncached", "output_tokens")}
    total["model_s"] = round(sum(row["model_s"] for row in out), 1)
    return {"rows": out, "total": total}


def render(result: dict) -> str:
    lines = [f"{'kind/stage':32} {'calls':>5} {'input':>9} {'c.read':>8} {'c.write':>8} {'uncached':>9} {'out':>7} "
             f"{'model_s':>8} {'p50_s':>6}"]
    for r in result["rows"] + [{"kind": "TOTAL", "stage": "", "p50_call_s": None, **result["total"]}]:
        p50 = r.get("p50_call_s")
        lines.append(f"{(r['kind'] + '/' + r['stage'])[:32]:32} {r['calls']:>5} {r['input_tokens']:>9} "
                     f"{r['cache_read']:>8} {r['cache_write']:>8} {r['uncached']:>9} {r['output_tokens']:>7} "
                     f"{r['model_s']:>8} {p50 if p50 is not None else '':>6}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ledger", type=Path)
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    result = summarize(a.ledger.read_text(encoding="utf-8").splitlines(), a.since, a.until)
    print(json.dumps(result, indent=1) if a.json else render(result))


if __name__ == "__main__":
    main()
