"""Reset facts' decay clocks by real age, once — run by the person, never automatically (ROR-129, owner 2026-11-06;
``api.services.fact_clock_reset``).

    api/.venv/bin/python -m api.scripts.reset_fact_clocks --bank <path>           # dry run: counts only
    api/.venv/bin/python -m api.scripts.reset_fact_clocks --bank <path> --apply   # one `cicada` commit

Facts on an evergreen page that is not media (the owner's page, a pinned one) were never charged the silence their
conversations prove, so their clocks sit at the day they were read. The dry run counts the facts it would lower
(`claims_lowered`) and how many that takes under the question line (`claims_below_nudge`, marked so Sleep never asks);
``--apply`` writes exactly that in one `cicada` commit (trigger ``maintenance/fact-clocks``), refused while Sleep runs
or holds the pages. A second run changes nothing. The bank is named explicitly; nothing is resolved from the
environment's active bank. Prints one JSON object of counts. Exit 0 done, 2 not a bank, 3 refused.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from api.scripts.migrate_claims_jsonl import backend_running


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="reset_fact_clocks", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--apply", action="store_true", help="write and commit; without it, report counts only")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2

    from api.services import fact_clock_reset as reset

    if not args.apply:
        print(json.dumps(reset.survey(bank).counts()))
        return 0
    try:
        result = reset.apply(bank, sleep_running=backend_running)
    except reset.SleepRunning as exc:
        print(json.dumps({"refused": str(exc)}))
        return 3
    print(json.dumps(result.counts()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
