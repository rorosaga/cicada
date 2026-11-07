"""The backend test files one CI shard runs (2026-11-06).

A merge put an `UnboundLocalError` on `dev` that 27 tests could see, and no CI job ran any of them: CI ran only the crucial
tier. The whole suite costs under 9 minutes on six runners, about what a PR already waits for its Swift lint.

Run as a script with `index/total` (from 1), it prints one shard's files."""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def shard(index: int, total: int, tests: Path = TESTS) -> list[str]:
    """Biggest file first into the lightest shard, by size, the best cheap guess at time."""
    files = sorted(((p.stat().st_size, p.name) for p in tests.glob("test_*.py")),
                   key=lambda f: (-f[0], zlib.crc32(f[1].encode())))
    bins: list[list[str]] = [[] for _ in range(total)]
    loads = [0] * total
    for size, name in files:
        lightest = loads.index(min(loads))
        bins[lightest].append(name)
        loads[lightest] += size
    return sorted(bins[index - 1])


if __name__ == "__main__":
    index, total = map(int, sys.argv[1].split("/"))
    for name in shard(index, total):
        print(f"api/tests/{name}")
