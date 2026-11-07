"""Measure light web context (owner ruling 44, G121) on a bank copy without writing to it.

    api/.venv/bin/python -m api.scripts.web_context_dry_run --bank <copy> --limit 40 --out rows.json
    api/.venv/bin/python -m api.scripts.web_context_dry_run --bank <copy> --no-engine --out rows.json

Runs the public test on every person page and every candidate page (Wikidata asked only for names that passed the
local test, capped by ``--wikidata``), plans the next ``--limit`` lookups, runs them on the engine a run the person
starts would use (their plan's own web search; a metered key is skipped) and writes, to ``--out`` only, every person
page with its verdict, what each lookup would change with its citation, and "why it matters to you" before/after for a
sample. ``--out`` holds names and facts: it is for the person's own eyes, never a log, a commit or a PR. Stdout gets
counts only. The bank is never written; the memo is read and never saved. Exit 0 done, 2 not a bank.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="web_context_dry_run", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True)
    parser.add_argument("--limit", type=int, default=20, help="plan lookups to run (one engine call each)")
    parser.add_argument("--wikidata", type=int, default=200, help="public-test Wikidata lookups at most")
    parser.add_argument("--sample", type=int, default=30, help="pages in the before/after relevance sample")
    parser.add_argument("--no-engine", action="store_true", help="the public test and the plan only")
    parser.add_argument("--out", required=True, help="where the full rows go (your eyes only)")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2
    from api.config import Settings
    from api.services import web_context

    engine = (None, None, "no_engine_requested") if args.no_engine else None
    out = asyncio.run(web_context.dry_run(bank, Settings(memory_path=bank), limit=max(0, args.limit),
                                          engine=engine, wikidata_budget=args.wikidata, sample=args.sample))
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    people = out["people"]
    actions: dict[str, int] = {}
    for row in out["lookups"]:
        for c in row["changes"]:
            actions[c["action"]] = actions.get(c["action"], 0) + 1
    print(json.dumps({"people": len(people), "people_public": sum(1 for p in people if p["public"]),
                      "verdicts": out["verdicts"], "counts": out["counts"], "engine": out.get("engine"),
                      "reason": out.get("reason"), "lookup_outcomes": _tally(r["reason"] for r in out["lookups"]),
                      "changes": actions}, sort_keys=True))
    return 0


def _tally(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


if __name__ == "__main__":
    sys.exit(main())
