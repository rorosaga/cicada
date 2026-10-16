"""The app's hot routes and its Store hydration payloads, timed in process (ASGI transport, no socket) on a synthetic
bank: the first call in a fresh process, then ``--reps`` warm calls for p50/p95, then a conditional re-read
(``If-None-Match`` with the ETag just served: what a steady-state Store refresh costs).

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.hot_routes --bank <dir>/bank [--reps 30]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from . import isolate

#: The routes the app polls or opens on, plus the read tools an agent calls every turn.
HOT = ["/status", "/sleep/status", "/graph", "/inbox", "/search?q=alpha", "/search?q=alp&mode=prefix",
       "/sources/messages/waiting", "/sync/version"]
#: Every Store domain's GET (`SyncAPI` / `APIClient.getConditional`): the cold-launch hydration set.
STORE = ["/graph", "/inbox", "/banks", "/sources?sort=relevance", "/sources/channels", "/sources/feeds",
         "/sources/calendars", "/contributors", "/origins", "/sources/overview", "/connections", "/status",
         "/consumption/summary?range=7d"]


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(p / 100 * len(ordered)) - 1))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--reps", type=int, default=30)
    ap.add_argument("--only", nargs="*", default=[])
    a = ap.parse_args()
    isolate.pin_bank(a.bank.resolve())

    import socket

    def no_network(*args, **kwargs):
        raise RuntimeError("offline probe forbids network access")
    socket.socket.connect = no_network
    socket.create_connection = no_network

    from api.services import providers
    from benchmarks.system.engine import embed
    providers.resolve_embed_fn = lambda *a, **k: (embed, "fake-hash-v1")
    providers.resolve_embed_fn_for_model = lambda *a, **k: (embed, "fake-hash-v1")

    import resource
    import httpx
    t0 = time.perf_counter()
    from api.main import app
    import_ms = (time.perf_counter() - t0) * 1000
    rss_after_import = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6   # macOS: bytes

    paths = a.only or list(dict.fromkeys(HOT + STORE))

    async def run():
        rows = []
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://probe",
                                     timeout=600) as c:
            for path in paths:
                warm, status, size, etag, cond_ms = [], None, 0, None, None
                t = time.perf_counter()
                r = await c.get(path)
                first = (time.perf_counter() - t) * 1000
                status, size, etag = r.status_code, len(r.content), r.headers.get("etag")
                for _ in range(a.reps):
                    t = time.perf_counter()
                    r = await c.get(path)
                    warm.append((time.perf_counter() - t) * 1000)
                if etag:
                    times = []
                    for _ in range(max(3, a.reps // 3)):
                        t = time.perf_counter()
                        r2 = await c.get(path, headers={"If-None-Match": etag})
                        times.append((time.perf_counter() - t) * 1000)
                    cond_ms = (round(statistics.median(times), 1), r2.status_code)
                rows.append({"path": path, "status": status, "bytes": size, "first_ms": round(first, 1),
                             "p50_ms": round(pct(warm, 50), 1), "p95_ms": round(pct(warm, 95), 1),
                             "etag_304": cond_ms})
        return rows

    rows = asyncio.run(run())
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
    print(json.dumps({"import_ms": round(import_ms), "maxrss_mb_after_import": round(rss_after_import),
                      "maxrss_mb_end": round(rss), "rows": rows}))
    print(f"import {import_ms:.0f} ms; peak RSS {rss_after_import:.0f} MB after import, {rss:.0f} MB at end")
    print(f"{'p50':>8} {'p95':>8} {'first':>9} {'304':>12} {'st':>4} {'bytes':>11}  path")
    for r in rows:
        cond = f"{r['etag_304'][0]}/{r['etag_304'][1]}" if r["etag_304"] else "-"
        print(f"{r['p50_ms']:>8} {r['p95_ms']:>8} {r['first_ms']:>9} {cond:>12} {r['status']!s:>4} "
              f"{r['bytes']:>11,}  {r['path']}")


if __name__ == "__main__":
    main()
