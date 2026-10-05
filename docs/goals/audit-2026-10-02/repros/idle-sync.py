"""A10: warmed synthetic cost of one version + Sleep debt tick, no HTTP server.

Creates only generated markdown under /private/tmp. This is not a measurement
of the user's API process. Run with the repository API virtualenv interpreter.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))


async def benchmark(root: Path) -> None:
    for key, value in {
        "CICADA_HOME": str(root / "home"), "CICADA_MEMORY_PATH": str(root / "bank"),
        "CICADA_CAPTURE": "off", "PYTHON_DOTENV_DISABLED": "1",
        "CICADA_API_AUTH": "off", "CICADA_ALLOW_CONNECTOR_FETCH": "off",
        "CICADA_ALLOW_FEED_FETCH": "off", "CICADA_ALLOW_LOGO_FETCH": "off",
    }.items():
        os.environ[key] = value
    from api.services import bank_index, markdown_parser, sleep_cycle, sleep_debt, sync_service

    for episode_count in (2000, 10000):
        bank = root / f"bank-{episode_count}"
        for directory, count in {"entities": 1900, "hubs": 20, "inbox": 250,
                                 "nudges": 25, "episodes": episode_count}.items():
            folder = bank / directory
            folder.mkdir(parents=True)
            for index in range(count):
                fm = {"id": f"synthetic-{index:05}", "type": "concept",
                      "processed": True, "status": "active",
                      "timestamp": "2026-10-02T10:00:00+00:00"}
                markdown_parser.write(folder / f"synthetic-{index:05}.md", fm, "Synthetic audit fixture.")
        bank_index.invalidate(bank)
        wall, cpu, version_wall, debt_wall = [], [], [], []
        for index in range(28):  # Three warmups followed by 25 observations.
            start_wall, start_cpu = time.perf_counter(), time.process_time()
            sync_service.version(bank, sleep_cycle.get_sleep_state())
            after_version = time.perf_counter()
            await sleep_debt.compute(bank)
            end = time.perf_counter()
            if index >= 3:
                wall.append((end - start_wall) * 1000)
                cpu.append((time.process_time() - start_cpu) * 1000)
                version_wall.append((after_version - start_wall) * 1000)
                debt_wall.append((end - after_version) * 1000)
        print(json.dumps({"finding": "A10", "episodes": episode_count, "entities": 1900,
            "samples": len(wall), "wall_median_ms": round(statistics.median(wall), 2),
            "wall_p95_ms": round(sorted(wall)[math.ceil(0.95 * len(wall)) - 1], 2),
            "cpu_median_ms": round(statistics.median(cpu), 2),
            "version_median_ms": round(statistics.median(version_wall), 2),
            "debt_median_ms": round(statistics.median(debt_wall), 2)}))


if __name__ == "__main__":
    with TemporaryDirectory(prefix="cicada-audit-sync-", dir="/private/tmp") as scratch:
        asyncio.run(benchmark(Path(scratch)))
