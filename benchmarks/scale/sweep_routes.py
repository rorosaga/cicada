"""(d): every parameterless GET route, plus the owner's per-entity routes and the MCP read tools, timed in process
against a synthetic bank (ASGI transport, no socket, no lifespan). Ranked by warm time.

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.sweep_routes --bank <dir>/bank
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from . import isolate

SKIP = ("/events", "/stream", "/sse", "/sync/stream", "/logs", "/demo", "/export", "/backup", "/updates")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--owner", default="owner-example")
    ap.add_argument("--reps", type=int, default=2)
    a = ap.parse_args()
    bank = a.bank.resolve()
    isolate.pin_bank(bank)

    import socket

    def no_network(*args, **kwargs):
        raise RuntimeError("offline probe forbids network access")
    socket.socket.connect = no_network
    socket.create_connection = no_network

    import httpx
    from fastapi.routing import APIRoute
    from api.main import app

    paths = sorted({r.path for r in app.routes if isinstance(r, APIRoute) and "GET" in r.methods
                    and "{" not in r.path and not any(s in r.path for s in SKIP)})
    paths += [f"/entities/{a.owner}", f"/entities/{a.owner}/claims?include_superseded=true",
              f"/entities/{a.owner}/provenance", f"/entities/{a.owner}/context", f"/entities/{a.owner}/sources",
              "/search?q=alpha", "/search/quick?q=alp", "/ask?q=what+does+alpha3-project+use"]

    async def run():
        rows = []
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://probe",
                                     timeout=600) as c:
            for path in paths:
                times, status, size = [], None, 0
                for _ in range(a.reps):
                    t = time.perf_counter()
                    try:
                        r = await c.get(path)
                        status, size = r.status_code, len(r.content)
                    except Exception as exc:  # noqa: BLE001 — a probe records, never stops
                        status = type(exc).__name__
                    times.append((time.perf_counter() - t) * 1000)
                rows.append({"path": path.replace(a.owner, "<owner>"), "status": status, "bytes": size,
                             "first_ms": round(times[0], 1), "warm_ms": round(min(times[1:] or times), 1)})
        return rows

    rows = asyncio.run(run())
    rows.sort(key=lambda r: -r["warm_ms"])
    print(json.dumps(rows))
    for r in rows:
        print(f"{r['warm_ms']:>9} {r['first_ms']:>9} {str(r['status']):>5} {r['bytes']:>10,}  {r['path']}")


if __name__ == "__main__":
    main()
