"""Full rebuild time of both derived indexes on a synthetic bank, in a fresh process: the lexical (FTS5) index, then
the vector index with the deterministic hashing embedder (no model, no network) — so the vector time is everything but
the model's own embedding, and the texts/characters it would embed are counted for the model's share. Then the same
refresh with nothing changed (an idle night).

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.index_rebuild --bank <dir>/copy
"""
from __future__ import annotations

import argparse
import json
import resource
import time
from pathlib import Path

from . import isolate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    a = ap.parse_args()
    bank = a.bank.resolve()
    isolate.pin_bank(bank)
    from api.services import search_index
    from api.services.vector_index import SqliteVecIndexer
    from benchmarks.system.engine import embed

    texts = {"calls": 0, "texts": 0, "chars": 0}

    def counting(batch, *, is_query=False):
        texts["calls"] += 1
        texts["texts"] += len(batch)
        texts["chars"] += sum(map(len, batch))
        return embed(batch, is_query=is_query)

    out = {}
    t = time.perf_counter()
    out["fts_docs"] = search_index.rebuild(bank)
    out["fts_full_s"] = round(time.perf_counter() - t, 1)
    t = time.perf_counter()
    search_index.refresh(bank)
    out["fts_idle_refresh_ms"] = round((time.perf_counter() - t) * 1000)
    for kind in ("index_entities", "index_episodes", "index_claims"):
        ix = SqliteVecIndexer(bank, embed_fn=counting, model_name="fake-hash-v1")
        before = dict(texts)
        t = time.perf_counter()
        n = getattr(ix, kind)()
        out[f"vec_{kind}_full_s"] = round(time.perf_counter() - t, 1)
        out[f"vec_{kind}_rows"] = n
        out[f"vec_{kind}_embedded_texts"] = texts["texts"] - before["texts"]
        out[f"vec_{kind}_embedded_chars"] = texts["chars"] - before["chars"]
    for kind in ("index_entities", "index_episodes", "index_claims"):
        ix = SqliteVecIndexer(bank, embed_fn=counting, model_name="fake-hash-v1")
        t = time.perf_counter()
        getattr(ix, kind)()
        out[f"vec_{kind}_idle_ms"] = round((time.perf_counter() - t) * 1000)
    out["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6)
    out["db_mb"] = {p.name: round(p.stat().st_size / 1e6) for p in bank.glob("*_index.db")}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
