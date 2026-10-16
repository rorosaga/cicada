"""A synthetic labeled query set for ``benchmarks.recall_ab``, drawn from a synthetic bank's own pages.

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.recall_queries --bank <dir>/bank --out <dir>/q.jsonl

Two kinds, half each: a page asked about by its name and a few words of its summary (relevant: that page), and a
claim's own sentence (relevant: the claim's subject and object pages) — the second kind is what an entity vector
loses when its claims fence is left out, the first what a long fence crowds out. Synthetic text only.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

from . import isolate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    bank = a.bank.resolve()
    isolate.pin_bank(bank)
    from api.services import claims, markdown_parser

    rng = random.Random(a.seed)
    pages = sorted((bank / "entities").glob("*.md"))
    ids = {p.stem for p in pages}
    rng.shuffle(pages)
    rows: list[dict] = []
    by_name = by_claim = 0
    for page in pages:
        if by_name >= a.n // 2 and by_claim >= a.n - a.n // 2:
            break
        parsed = markdown_parser.parse(page)
        fm = parsed.frontmatter or {}
        prose = claims.strip_claims_block(parsed.body)
        if by_name < a.n // 2:
            summary = prose.partition("## Summary")[2].split("##")[0]
            words = re.findall(r"[A-Za-z]+", summary.partition("—")[2])
            if len(words) >= 6:
                start = rng.randrange(0, len(words) - 5)
                rows.append({"query": f"{fm.get('name', page.stem)} {' '.join(words[start:start + 5]).lower()}",
                             "relevant": [page.stem], "kind": "name"})
                by_name += 1
                continue
        if by_claim < a.n - a.n // 2:
            found = [c for c in claims.parse_claims(parsed.body) if c.text and c.subject in ids]
            if found:
                c = rng.choice(found)
                relevant = sorted({c.subject} | ({c.object} if c.object in ids else set()))
                rows.append({"query": c.text.split(":")[0], "relevant": relevant, "kind": "claim"})
                by_claim += 1
    a.out.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(json.dumps({"queries": len(rows), "name": by_name, "claim": by_claim, "out": str(a.out)}))


if __name__ == "__main__":
    main()
