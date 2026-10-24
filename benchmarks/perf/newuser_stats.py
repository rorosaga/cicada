"""Latency and reply size per tool from a ``benchmarks.newuser.ask`` results file (or two, to compare).

    api/.venv/bin/python -m benchmarks.perf.newuser_stats <results.jsonl> [<after.jsonl>]

Reply tokens are the results file's own ~characters/4 estimate. Synthetic persona only.
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
from pathlib import Path


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(q * (len(ordered) - 1))))
    return ordered[k]


def stats(path: Path) -> dict:
    by_tool: dict[str, dict[str, list]] = collections.defaultdict(lambda: collections.defaultdict(list))
    verdicts = collections.Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        t = by_tool[row["tool"]]
        t["seconds"].append(float(row.get("seconds") or 0))
        t["tokens"].append(int(row.get("tokens") or 0))
        verdicts[row.get("verdict")] += 1
    out = {"verdicts": dict(verdicts),
           "score": verdicts.get("correct", 0) + 0.5 * verdicts.get("partial", 0)}
    for tool, t in sorted(by_tool.items()):
        out[tool] = {"n": len(t["seconds"]),
                     "p50_s": round(statistics.median(t["seconds"]), 2), "p95_s": round(pct(t["seconds"], 0.95), 2),
                     "max_s": round(max(t["seconds"]), 2),
                     "p50_tokens": int(statistics.median(t["tokens"])), "max_tokens": max(t["tokens"])}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("results", type=Path, nargs="+")
    a = ap.parse_args()
    print(json.dumps({str(p): stats(p) for p in a.results}, indent=1))


if __name__ == "__main__":
    main()
