"""Give an existing bank's placeholder people one page each and ask their names — run by the person, never
automatically (brief 2026-10-14; ``api.services.role_people``).

    api/.venv/bin/python -m api.scripts.repair_placeholder_people --bank <path>           # dry run: counts only
    api/.venv/bin/python -m api.scripts.repair_placeholder_people --bank <path> --apply   # one `cicada` commit

A placeholder person is a person page titled by a relation to the owner rather than a name: "<owner>'s partner",
"Replacement roommate (unnamed)", "my dad". For each one:

* **merge** — when the relation is one only one person holds at a time (partner, spouse, mother, father…) and the
  record names exactly one named person as holding it (an open claim or edge between the owner and that person
  whose predicate names the relation, or a relation the person already confirmed), the page folds into that person
  through the one merge primitive: claims with their provenance, sources, history, edges and every reference move;
* **retitle** — otherwise the page is titled by the relation alone ("Partner", "Former roommate"; never the owner's
  name), keeps its claims and references (they follow the new id), and is marked unnamed;
* **ask** — every page left unnamed gets one inbox question, "What's the name of your partner?" (none when one is
  already open, or when the person said "I'd rather not say").

Two pages are never merged on a resemblance: a relation several people hold (a friend, a roommate) or one the record
does not tie to exactly one named person is asked about, not merged. The dry run prints counts only (never a page
name or a word of the bank). ``--apply`` writes exactly that in one `cicada` commit (trigger
``maintenance/placeholder-people``), refused while Sleep runs or holds the pages; a page dirty in git is skipped. A
second run changes nothing.

The bank is named explicitly; nothing is resolved from the environment's active bank. Exit 0 done, 2 not a bank,
3 refused because Sleep is running or holds the pages.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from api.scripts.migrate_claims_jsonl import backend_running


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="repair_placeholder_people", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--apply", action="store_true", help="write and commit; without it, report counts only")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2

    from api.services import role_people

    if not args.apply:
        print(json.dumps(role_people.survey(bank).counts()))
        return 0
    try:
        plan = role_people.apply(bank, sleep_running=backend_running)
    except role_people.SleepRunning as exc:
        print(json.dumps({"refused": str(exc)}))
        return 3
    print(json.dumps(plan.counts()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
