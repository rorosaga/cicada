"""Measure what the next Sleep would mark read without a model (owner ruling 2026-10-18; ``history_index``).

    api/.venv/bin/python -m api.scripts.history_index_dry_run --bank <path>

Prints one JSON object of COUNTS, never an id, a title or a channel: every episode waiting for Sleep
(``waiting``), how many of those are index-only and would be marked read (``index_only_queued``, by kind — ``history``
for a watched day, ``list`` for a save from a platform's saved list, ``month`` for a month's summary — and by
origin), what the model would still read (``for_model``), the episodes already read by the index, and the months of
watch history against the month summaries that exist (``months_in_history``, ``month_summaries``). Frontmatter only,
through the cached scan; it writes nothing — no flag, no summary, no commit. The real step runs at the start of the
next Sleep run (``sleep_cycle._index_without_model_safely``). Exit 0 done, 2 not a bank.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="history_index_dry_run", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds episodes/)")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "episodes").is_dir():
        print(json.dumps({"error": "not a bank: no episodes/ directory"}))
        return 2

    from api.services import bank_index, history_index, watch_history

    out = history_index.count(bank).as_dict()
    months: set[tuple[str, str]] = set()
    summaries = 0
    for f in bank_index.files(bank, "episodes"):
        fm = f.frontmatter or {}
        k = history_index.kind(fm)
        if k == "month":
            summaries += 1
        elif k == "history" and not fm.get("source_deleted_at"):
            parsed = watch_history._day_of(str(fm.get("source_id") or ""))
            if parsed is not None:
                months.add((parsed[0], watch_history._month_key(parsed[1])))
    out["months_in_history"] = len(months)
    out["month_summaries"] = summaries
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
