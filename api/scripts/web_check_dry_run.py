"""Measure the web check on a bank without writing anything (owner brief, 2026-10-16; the sweep, owner ruling
2026-10-19: ``web_lookup.sweep``).

    api/.venv/bin/python -m api.scripts.web_check_dry_run --bank <path> --census          # no engine call at all
    api/.venv/bin/python -m api.scripts.web_check_dry_run --bank <path> --limit 20
    api/.venv/bin/python -m api.scripts.web_check_dry_run --bank <path> --limit 20 --include-recent
    api/.venv/bin/python -m api.scripts.web_check_dry_run --bank <path> --limit 20 --include-recent --trace

Prints one JSON object of COUNTS. Always the census: per kind, how many open questions a lookup may answer
(``public``), a trusted local agent may (``repo_state``), or stay for the person and why (``person``,
``private_type``, ``own_settings``, ``no_page`` …). Then — unless ``--census`` — it runs the engine the person chose,
as a run they start would (their Claude plan's own web search when that is the engine), on up to ``--limit`` of the
eligible questions and counts how many were looked up and would settle, with the reasons by kind (``clarification``,
``conflict``, ``type_conflict``). Never an item id, a name, a query, a link or a quote. It writes nothing: no settle,
no commit, no memo row, no ledger row. ``--include-recent`` also re-measures questions a run looked up in the last 30
days. The bank is named explicitly; nothing is resolved from the active bank. Exit 0 done, 2 not a bank.

``--trace`` (for the person running it, never a log): the same counts plus, per looked-up question, only its pinned
query (the name and the category word that would be searched), where that word came from (``description``,
``context`` or ``none``), how many context lines it carried, how many people's names the context had replaced, and the
outcome (``would_settle`` or the reason). Never the context's words, a link, a quote or an answer. It also counts how
the bank's person names are redacted (``web_settle.person_name_census``: split, whole phrase, skipped, relations, and
person-typed names that read as a thing — the data to fix in the bank, never a name).

The real sweep is the running backend's own route (it holds the bank's write admission and Sleep's window, ruling
21a): ``POST /inbox/web-check?dryRun=false[&limit=N]`` with the token, then ``GET /inbox/web-check`` for its counts;
each settle is undoable under "Settled by a check".
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="web_check_dry_run", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/ and inbox/)")
    parser.add_argument("--limit", type=int, default=20, help="look up at most this many questions (default 20)")
    parser.add_argument("--include-recent", action="store_true",
                        help="also re-measure questions looked up in the last 30 days")
    parser.add_argument("--census", action="store_true", help="count what a lookup may answer; no engine call")
    parser.add_argument("--trace", action="store_true",
                        help="also print each lookup's pinned query, redaction count and outcome (for your eyes)")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir() or not (bank / "inbox").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ or inbox/ directory"}))
        return 2

    from api.config import Settings
    from api.services import web_lookup, web_settle

    rows: list[dict] = []
    facts = web_settle.bank_facts(bank) if args.trace else None

    def trace(c, context, a) -> None:
        stats: dict = {}
        web_settle.local_context(bank, c, facts, stats=stats)   # the same lines again, only to count the redactions
        rows.append({"query": web_settle.query_for(c), "category_from": c.category_from or "none",
                     "context_lines": len(context), "people_redacted": stats.get("people", 0),
                     "outcome": "would_settle" if a.ok else a.reason})

    counts = asyncio.run(web_lookup.sweep(bank, Settings(), dry_run=True, limit=0 if args.census else args.limit,
                                          include_recent=args.include_recent, on_lookup=trace if args.trace else None))
    if args.trace:
        counts["trace"] = rows
        counts["person_names"] = web_settle.person_name_census(facts)
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
