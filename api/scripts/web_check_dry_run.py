"""Measure the web check on a bank without writing anything (owner brief, 2026-10-16; ``web_lookup.dry_run``).

    api/.venv/bin/python -m api.scripts.web_check_dry_run --bank <path> --limit 8
    api/.venv/bin/python -m api.scripts.web_check_dry_run --bank <path> --limit 8 --include-recent

Runs the engine the person chose — as a person-started Sleep would, so the Claude plan's own web search when that is the
engine (ruling 4 binds a scheduled run; this is the person's command) — on the next ``--limit`` questions the web check
would look up, and prints one JSON object of COUNTS: how many were eligible, looked up, would have settled, how many
prompts carried a mention line or a description, how many queries were a bare name, and the reasons by kind
(``clarification``, ``conflict``, ``type_conflict``). Never an item id, a name, a query, a link or a quote. It writes
nothing: no settle, no commit, no memo row, no ledger row. ``--include-recent`` also re-measures questions a run looked
up in the last 30 days. The bank is named explicitly; nothing is resolved from the active bank. Exit 0 done, 2 not a
bank.
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
    parser.add_argument("--limit", type=int, default=8, help="look up at most this many questions (default 8)")
    parser.add_argument("--include-recent", action="store_true",
                        help="also re-measure questions looked up in the last 30 days")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir() or not (bank / "inbox").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ or inbox/ directory"}))
        return 2

    from api.config import Settings
    from api.services import web_lookup

    counts = asyncio.run(web_lookup.dry_run(bank, Settings(), limit=args.limit, include_recent=args.include_recent))
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
