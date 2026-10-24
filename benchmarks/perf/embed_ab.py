"""Does leaving decay's bookkeeping out of an entity's embedded text move search? Both texts embedded with the same
model, side by side, in memory (no index is written):

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.perf.embed_ab --bank <bank> [--embedder e5] [--pages 600]

For each sampled page: the cosine between its vector before (claims fence as stored) and after
(``vector_index.without_decay_marks``). Then labeled queries (a page's name, or a claim's own words — the
``recall_queries`` shapes) ranked against every sampled page both ways: MRR of the labeled page and how many of the
top 8 are the same. Synthetic text only.
"""
from __future__ import annotations

from benchmarks.scale import isolate  # noqa: F401  (first)

import argparse
import json
import random
import statistics
from pathlib import Path

import numpy as np


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--embedder", choices=("hash", "e5"), default="e5")
    ap.add_argument("--pages", type=int, default=600)
    ap.add_argument("--queries", type=int, default=200)
    a = ap.parse_args()
    bank = a.bank.resolve()
    isolate.pin_bank(bank)
    from benchmarks.perf import probe

    probe._offline()
    fn, model = probe._embedder(a.embedder)
    from api.services import claims as claims_mod
    from api.services import markdown_parser, vector_index

    rng = random.Random(11)
    pages = sorted((bank / "entities").glob("*.md"))
    rng.shuffle(pages)
    pages = pages[: a.pages]
    import re

    def nightly(text: str) -> str:
        """The same page after one night's decay under the old text: every claim's confidence 0.02 lower, its
        watermark a week on — the reshuffle the current scheme already causes every night (the noise floor)."""
        text = re.sub(r'"confidence": (-?\d+(?:\.\d+)?)',
                      lambda m: f'"confidence": {max(0.0, round(float(m.group(1)) - 0.02, 2))}', text)
        return re.sub(r'"decayed_through": "[^"]*"', '"decayed_through": "2026-10-31"', text)

    before, after, decayed, labels, queries = [], [], [], [], []
    changed = 0
    for i, page in enumerate(pages):
        parsed = markdown_parser.parse(page)
        fm, body = parsed.frontmatter or {}, parsed.body or ""
        header = [str(fm.get("name", page.stem))] + ([f"({fm['type']})"] if fm.get("type") else [])
        if fm.get("aliases"):
            header.append("aka: " + ", ".join(str(x) for x in fm["aliases"]))
        old = "\n".join(p for p in [" ".join(header), body] if p).strip()
        new = vector_index._entity_embed_text(fm, body, page.stem, mode="full")
        changed += old != new
        before.append(old)
        after.append(new)
        decayed.append(nightly(old))
        if len(queries) < a.queries:
            rows = claims_mod.parse_claims(body) or []
            texts = [c.text for c in rows if c.text]
            if i % 2 == 0 or not texts:
                queries.append(str(fm.get("name") or page.stem))
            else:
                queries.append(" ".join(rng.choice(texts).split()[:8]))
            labels.append(i)

    def embed(texts):
        out = [fn(texts[s:s + 64]) for s in range(0, len(texts), 64)]
        m = np.vstack(out).astype(np.float32)
        return m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)

    B, A, D = embed(before), embed(after), embed(decayed)
    cos = (B * A).sum(axis=1)
    Q = embed([q for q in queries]) if a.embedder == "hash" else np.vstack(
        [fn([q], is_query=True) for q in queries]).astype(np.float32)
    Q = Q / np.maximum(np.linalg.norm(Q, axis=1, keepdims=True), 1e-9)

    def ranks(M):
        scores = Q @ M.T
        order = np.argsort(-scores, axis=1)
        return order

    ob, oa, od = ranks(B), ranks(A), ranks(D)
    def mrr(order):
        return statistics.mean(1.0 / (1 + int(np.where(order[k] == labels[k])[0][0])) for k in range(len(labels)))
    def overlap(x, y):
        return round(statistics.mean(len(set(x[k][:8]) & set(y[k][:8])) / 8 for k in range(len(labels))), 4)

    def top1(x, y):
        return sum(int(x[k][0] == y[k][0]) for k in range(len(labels)))
    print(json.dumps({"bank": bank.name, "embedder": model, "pages": len(pages), "texts_changed": changed,
                      "cosine_min": round(float(cos.min()), 4), "cosine_p50": round(float(np.median(cos)), 4),
                      "cosine_one_night_min": round(float((B * D).sum(axis=1).min()), 4),
                      "queries": len(labels), "mrr_before": round(mrr(ob), 4), "mrr_after": round(mrr(oa), 4),
                      "mrr_one_night_old_text": round(mrr(od), 4),
                      "top8_overlap_change": overlap(ob, oa), "top1_same_change": top1(ob, oa),
                      "top8_overlap_one_night": overlap(ob, od), "top1_same_one_night": top1(ob, od)}, indent=1))


if __name__ == "__main__":
    main()
