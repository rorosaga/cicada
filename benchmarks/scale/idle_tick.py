"""The SSE stream's idle cost while the app is open: the CPU one bank's tick takes per second, and how long a page
written by another process takes to move the version the app is sent.

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.idle_tick --bank <dir>/bank [--seconds 30]

Runs ``sync_ticker.current`` once a second (the stream's ``POLL_SECONDS``) for ``--seconds`` with nothing changing and
reports the process CPU it took (every thread: the tick's workers and, with file-change events, the watcher), then
rewrites one page in place from a child process ``--edits`` times and reports how long the version took to move.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

from . import isolate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--edits", type=int, default=5)
    a = ap.parse_args()
    bank = a.bank.resolve()
    isolate.pin_bank(bank)

    from api.config import Settings
    from api.services import bank_index, sync_ticker

    settings = Settings(_env_file=None, CICADA_MEMORY_PATH=str(bank))
    page = sorted((bank / "entities").glob("*.md"))[1]

    async def run():
        # Warm: the first tick parses every episode's frontmatter (a cold `bank_index`), not an idle cost.
        await sync_ticker.current(bank, settings, max_age=0.0)
        await asyncio.sleep(1.0)
        await sync_ticker.current(bank, settings, max_age=0.0)
        cpu0, wall0 = time.process_time(), time.perf_counter()
        tick_ms = []
        for _ in range(a.seconds):
            t = time.perf_counter()
            await sync_ticker.current(bank, settings, max_age=0.9)
            tick_ms.append((time.perf_counter() - t) * 1000)
            await asyncio.sleep(1.0)
        cpu = time.process_time() - cpu0
        wall = time.perf_counter() - wall0

        latencies = []
        for i in range(a.edits):
            before = (await sync_ticker.current(bank, settings, max_age=0.9)).info.version
            await asyncio.sleep(0.37)   # somewhere inside the tick interval, as an editor would be
            # Another process rewrites the page in place (an editor), as the app's stream would never see coming.
            subprocess.run([sys.executable, "-c",
                            "import sys,pathlib;p=pathlib.Path(sys.argv[1]);"
                            "p.write_text(p.read_text()+'\\n<!-- edit -->\\n')", str(page)], check=True)
            edited = time.perf_counter()
            while True:   # what the stream does: a tick a second
                tick = await sync_ticker.current(bank, settings, max_age=0.9)
                if tick.info.version != before:
                    latencies.append((time.perf_counter() - edited) * 1000)
                    break
                if time.perf_counter() - edited > 30:
                    latencies.append(None)
                    break
                await asyncio.sleep(sync_ticker.next_poll_delay(tick, 1.0))
        return cpu, wall, tick_ms, latencies

    cpu, wall, tick_ms, latencies = asyncio.run(run())
    seen = [x for x in latencies if x is not None]
    out = {
        "files": sum(len(bank_index._scan_uncached(bank / d)) for d in ("entities", "episodes", "hubs", "inbox",
                                                                         "sources")),
        "watch": os.environ.get("CICADA_SYNC_WATCH", "on"),
        "cpu_ms_per_s": round(cpu * 1000 / wall, 1),
        "tick_ms_p50": round(statistics.median(tick_ms), 1),
        "tick_ms_max": round(max(tick_ms), 1),
        "edit_seen_ms": [round(x) if x is not None else None for x in latencies],
        "edit_seen_ms_max": round(max(seen)) if seen else None,
    }
    print(json.dumps(out))


if __name__ == "__main__":
    main()
