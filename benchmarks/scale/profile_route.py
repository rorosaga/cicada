"""cProfile one GET route (first call, cold process) and print the top api/ functions by cumulative time.

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.profile_route --bank <dir>/bank /state /graph
"""
from __future__ import annotations

import argparse
import asyncio
import cProfile
import io
import pstats
from pathlib import Path

from . import isolate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--top", type=int, default=14)
    ap.add_argument("paths", nargs="+")
    a = ap.parse_args()
    isolate.pin_bank(a.bank.resolve())
    import socket

    def no_network(*args, **kwargs):
        raise RuntimeError("offline probe forbids network access")
    socket.socket.connect = no_network
    socket.create_connection = no_network
    import httpx
    from api.main import app

    async def get(path):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://probe",
                                     timeout=600) as c:
            return (await c.get(path)).status_code

    for path in a.paths:
        prof = cProfile.Profile()
        prof.enable()
        status = asyncio.run(get(path))
        prof.disable()
        out = io.StringIO()
        stats = pstats.Stats(prof, stream=out).sort_stats("cumulative")
        stats.print_stats(r"/api/(services|routers)/", a.top)
        lines = [ln for ln in out.getvalue().splitlines() if "/api/" in ln or "function calls" in ln]
        print(f"== {path} ({status})")
        for ln in lines:
            print("  " + ln.replace(str(Path.cwd()) + "/", "").strip()[:170])


if __name__ == "__main__":
    main()
