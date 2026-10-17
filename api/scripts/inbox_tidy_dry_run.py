"""Measure the one-time inbox tidy on a bank without writing anything (ruling 29; ``inbox_tend.tidy``).

    api/.venv/bin/python -m api.scripts.inbox_tidy_dry_run --bank <path>
    api/.venv/bin/python -m api.scripts.inbox_tidy_dry_run --bank <path> --judge [--limit N]

Applies Sleep's inbox policy to every open question and prints one JSON object of COUNTS: how many Sleep would settle
and how many stay for the person, per kind and per decision (``same_spelling``, ``one_off``, ``ask:person`` …). Never
an item id, a title, a name or any text. It writes nothing: no settle, no commit, no ledger row. Without ``--judge``
the questions only a judge can read (duplicates, conflicts, label folds, fading pages) are counted as
``ask:needs_judge``; with it, the person's chosen engine reads them, one call each (their Claude plan included — owner,
2026-10-17; a plan limit stops it with ``stopped: plan_limit``), and each is counted by the judge's decision
(``judged_*``) or why it stays (``ask:unsure``, ``ask:meaning_changes``, ``ask:person``). The engine's usage is not
written to the ledger in a dry run.

The real tidy is the running backend's own route (it holds the bank's write admission and Sleep's window, ruling
21a): ``POST /inbox/tidy?dryRun=false[&judge=true]`` with the token, then ``GET /inbox/tidy`` for its counts. The bank
is named explicitly here; nothing is resolved from the active bank. Exit 0 done, 2 not a bank.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="inbox_tidy_dry_run", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/ and inbox/)")
    parser.add_argument("--limit", type=int, default=None, help="decide at most this many questions")
    parser.add_argument("--judge", action="store_true", help="let the judges read what the rules cannot settle (one engine call each)")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir() or not (bank / "inbox").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ or inbox/ directory"}))
        return 2

    from api.config import Settings
    from api.services import inbox_tend

    settings = Settings().model_copy(update={"memory_path": bank})
    counts = asyncio.run(inbox_tend.tidy(bank, settings, dry_run=True, limit=args.limit, judge=args.judge))
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
