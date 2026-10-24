"""Which parts of a recall reply carry the answer: the new-user questions' expected spellings, looked up part by part.

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.perf.recall_use --bank <newuser bank copy> [--embedder e5]

A proxy for "how much of the reply agents actually use": for each question, each expected group (benchmarks/newuser
``questions.json``) is looked up in every part of ``cicada_recall``'s reply for the question's text — the hints block,
each page block by rank, the changed-recently lines, the one-hop blurbs, the conversation excerpts. A part that never
holds a group no other part holds adds characters, not answers. Synthetic persona only.
"""
from __future__ import annotations

from benchmarks.scale import isolate  # noqa: F401  (first)

import argparse
import collections
import json
import re
from pathlib import Path


def parts(text: str) -> list[tuple[str, str]]:
    out, rank = [], 0
    for part in re.split(r"\n\n(?=```cicada-hints|\*\*|### |_\d+ lower-ranked)", text):
        if part.startswith("### "):
            rank += 1
            label = f"page_{rank}"
        elif part.startswith("```cicada-hints"):
            label = "hints"
        elif part.startswith("**Changed recently"):
            label = "changed"
        elif part.startswith("**Related (one hop"):
            label = "related_hop"
        elif part.startswith("**Related conversation"):
            label = "excerpts"
        elif part.startswith("**Open question"):
            label = "inbox"
        else:
            label = "other"
        out.append((label, part))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--embedder", choices=("hash", "e5"), default="e5")
    ap.add_argument("--questions", type=Path, default=Path("benchmarks/newuser/questions.json"))
    a = ap.parse_args()
    bank = a.bank.resolve()
    isolate.pin_bank(bank)
    from benchmarks.perf import probe

    probe._offline()
    probe._embedder(a.embedder)
    from api.services import mcp_tools

    data = json.loads(a.questions.read_text(encoding="utf-8"))
    chars = collections.Counter()
    holds = collections.Counter()      # groups found in this part
    only = collections.Counter()       # groups found ONLY in this part
    groups_total = groups_found = 0
    for q in data["questions"]:
        query = (q.get("args") or {}).get("query")
        if not query or not q.get("expect"):
            continue
        text = str(mcp_tools.recall(probe._recall_ctx(bank), query))
        split = parts(text)
        for label, body in split:
            chars[label if not label.startswith("page_") else ("page_1-3" if int(label[5:]) <= 3 else "page_4-7")] += len(body)
        for group in q["expect"]:
            groups_total += 1
            where = {label for label, body in split if any(s.lower() in body.lower() for s in group)}
            if where:
                groups_found += 1
            buckets = {(w if not w.startswith("page_") else ("page_1-3" if int(w[5:]) <= 3 else "page_4-7"))
                       for w in where}
            for b in buckets:
                holds[b] += 1
            if len(buckets) == 1:
                only[next(iter(buckets))] += 1
    total = sum(chars.values()) or 1
    print(json.dumps({"groups": groups_total, "groups_in_reply": groups_found,
                      "by_part": {k: {"share_pct": round(100 * v / total, 1), "groups_held": holds[k],
                                      "groups_held_only_here": only[k]}
                                  for k, v in chars.most_common()}}, indent=1))


if __name__ == "__main__":
    main()
