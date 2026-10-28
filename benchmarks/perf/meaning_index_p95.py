"""``/search`` and recall p95, with and without pictures in the meaning index, on a scratch copy of a bank:

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.perf.meaning_index_p95 --bank <copy> \\
        [--models <folder holding embeddinggemma-2>] [--pictures 400] [--reps 3]

Times ``search_service.search`` (what ``GET /search`` runs in its threadpool) in prefix mode (the palette's
keystroke pass) and hybrid mode with the palette's kinds, the same with ``image`` added, and ``mcp_tools.recall`` on a
local door — each over ``--reps`` passes of 60 queries (40 drawn from page names, 20 fixed phrases), the first pass
dropped as warm-up. With ``--pictures N`` it then draws N synthetic pictures, builds the ``images`` table in the copy
(``image_index.refresh``, the picture child) and times everything again. Only numbers are printed; never a query.
"""
from __future__ import annotations

from benchmarks.scale import isolate  # noqa: F401  (first)

import argparse
import json
import os
import random
import statistics
import time
from pathlib import Path

PHRASES = ("what did I decide about the budget", "the trip next month", "a dark minimal dashboard", "red logo",
           "notes from the meeting", "a video about cooking", "where the project stands", "a screenshot of a site",
           "the book I was reading", "my running plan", "a paper on memory", "the apartment search",
           "a blue landing page", "travel photos", "the tax form", "a podcast episode", "design inspiration",
           "the course I applied to", "a recipe", "a song I liked")
PALETTE = ("entity", "claim", "episode", "media")


def pct(values: list[float], p: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p * (len(values) - 1))))]


def timed(fn, queries: list[str], reps: int) -> dict:
    lat = []
    for rep in range(reps):
        for q in queries:
            t0 = time.perf_counter()
            fn(q)
            if rep:
                lat.append(1000 * (time.perf_counter() - t0))
    return {"p50": round(statistics.median(lat), 1), "p95": round(pct(lat, 0.95), 1), "n": len(lat)}


def measure(bank: Path, queries: list[str], reps: int) -> dict:
    from api.services import mcp_tools, search_service

    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="probe", harness="probe", state_hint_sent=True)
    return {
        "prefix": timed(lambda q: search_service.search(bank, q[:3], kinds=PALETTE, mode="prefix"), queries, reps),
        "hybrid": timed(lambda q: search_service.search(bank, q, kinds=PALETTE, mode="hybrid"), queries, reps),
        "hybrid+image": timed(lambda q: search_service.search(bank, q, kinds=(*PALETTE, "image"), mode="hybrid"),
                              queries, reps),
        "recall": timed(lambda q: mcp_tools.recall(ctx, q), queries, reps),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--models", type=Path)
    ap.add_argument("--pictures", type=int, default=0)
    ap.add_argument("--reps", type=int, default=3)
    a = ap.parse_args()
    bank = a.bank.resolve()
    isolate.pin_bank(bank)
    if a.models:
        target = Path(os.environ["CICADA_HOME"]) / "models"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.symlink_to(a.models.resolve(), target_is_directory=True)
    rng = random.Random(5)
    names = []
    from api.services import bank_index

    for f in bank_index.files(bank, "entities"):
        name = str((f.frontmatter or {}).get("name") or "")
        if name:
            names.append(" ".join(name.split()[:2]))
    queries = rng.sample(names, min(40, len(names))) + list(PHRASES)
    out = {"pages": len(names), "queries": len(queries), "before": measure(bank, queries, a.reps)}
    if a.pictures:
        from api.services import image_index
        from benchmarks.perf import image_index_build as build

        folder = bank / ".probe-pictures"
        folder.mkdir(exist_ok=True)
        drawn = build.make(a.pictures, 640, 400, folder)
        pictures = [image_index.Picture(f"capture:p{i:05d}", "capture", p, title=f"a {c} {s}", entity_id=f"p{i:05d}")
                    for i, (p, s, c) in enumerate(drawn)]
        t0 = time.monotonic()
        counts = image_index.refresh(bank, pictures=pictures)
        out["build"] = {**counts, "seconds": round(time.monotonic() - t0, 1)}
        out["with_pictures"] = measure(bank, queries, a.reps)
        from api.services import embed_worker

        embed_worker.shutdown()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
