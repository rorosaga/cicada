"""Charge an existing bank's pages and claims the age of what they came from, once — run by the person, never
automatically (owner ruling 2026-10-09, "let age count"; ``api.services.age_recompute``).

    api/.venv/bin/python -m api.scripts.recompute_decay_by_age --bank <path>           # dry run: counts only
    api/.venv/bin/python -m api.scripts.recompute_decay_by_age --bank <path> --apply   # one `cicada` commit

The dry run counts the pages it would lower, by type and by the age of their last mention (under 3 months, 3-12
months, over a year), how many would be archived (below 0.2: one-conversation pages only — they stay in entities/ and
recall still finds them, ranked last), how many would fade to decaying (`would_decay`; `floored_repeats` of them rest on 2+
conversations and are held at 0.39, just under the question line — Sleep then fades and archives them quietly), how
many Sleep would ever ask about (`would_be_asked`: only pages read within a week of being said), and the claims it
would lower. ``--apply`` writes exactly that — confidence, status,
``learned_on`` and the watermark, and the changed claim lines — in one `cicada` commit (trigger
``maintenance/decay-by-age``), refused while Sleep runs or holds the pages; pages dirty in git or written since the
survey are skipped. A second run changes nothing. No inbox item is written.

The bank is named explicitly; nothing is resolved from the environment's active bank. Prints one JSON object of
counts (never a page name or a word of the bank). Exit 0 done, 2 not a bank, 3 refused because Sleep is running or
holds the pages.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from api.scripts.migrate_claims_jsonl import backend_running


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="recompute_decay_by_age", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--apply", action="store_true", help="write and commit; without it, report counts only")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2

    from api.services import age_recompute as recompute

    if not args.apply:
        print(json.dumps(recompute.survey(bank).counts()))
        return 0
    try:
        result = recompute.apply(bank, sleep_running=backend_running)
    except recompute.SleepRunning as exc:
        print(json.dumps({"refused": str(exc)}))
        return 3
    print(json.dumps(result.counts()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
