"""Count what reads like scraps on a bank's pages, and repair the prose losslessly — run by the person, never
automatically (page quality, G194; ``api.services.page_quality_repair``).

    api/.venv/bin/python -m api.scripts.repair_page_quality --bank <path>           # dry run: counts only
    api/.venv/bin/python -m api.scripts.repair_page_quality --bank <path> --apply   # one `cicada` commit

The dry run counts: pages resting on one conversation and whether the measured promotion bar would have written
them (``one_conversation_*``); glued, over-budget and fallback Summaries; "Undated background" History bullets and
how many say something the page does not; facts that only say the thing came up, facts another fact on the page
restates, facts phrased as what the assistant said. ``--apply`` repairs only the prose a Sleep update would now
write, on machine pages: background bullets and displaced Summary sentences become Key Facts when they add
something, the fallback's "not established" clause and the came-up-in-a-conversation facts go. Near-duplicate
facts and one-conversation pages are counted, never changed.

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
    parser = argparse.ArgumentParser(prog="repair_page_quality", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--apply", action="store_true", help="repair and commit; without it, report counts only")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2

    from api.services import page_quality_repair as repair

    if not args.apply:
        print(json.dumps(repair.survey(bank).counts()))
        return 0
    try:
        result = repair.apply(bank, sleep_running=backend_running)
    except repair.SleepRunning as exc:
        print(json.dumps({"refused": str(exc)}))
        return 3
    print(json.dumps(result.counts()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
