"""Split a page that absorbed a message conversation's correspondent — run by the person, never automatically (G179;
``api.services.correspondent_repair``).

    api/.venv/bin/python -m api.scripts.repair_correspondent_pages --bank <path>           # dry run: counts only
    api/.venv/bin/python -m api.scripts.repair_correspondent_pages --bank <path> --apply   # one `cicada` commit

Before Stage 2 knew a conversation's own correspondent, a texted agent named like an existing page (an archived
``concept`` about the ordinary word) landed on that page. For each such page — its own name the correspondent's,
crediting the conversation, of another type — only the conversation's part leaves it, as it is now: the claims resting
on the conversation alone, its source credit, and the prose and list values it added when nothing else touched them
since (else the prose stays and the new page's facts come from its claims). Nothing else moves or reverts. The part
goes to a page of the right type (``tool`` for an agent, ``person`` for a person), re-rendered without a model.

The dry run prints counts only (never a page name or a word of the bank). ``--apply`` writes exactly that in one
`cicada` commit (trigger ``maintenance/correspondent-split``), refused while Sleep runs or holds the pages; a page
dirty in git is skipped. A second run changes nothing.

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
    parser = argparse.ArgumentParser(prog="repair_correspondent_pages", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--apply", action="store_true", help="write and commit; without it, report counts only")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2

    from api.services import correspondent_repair

    if not args.apply:
        print(json.dumps(correspondent_repair.survey(bank).counts()))
        return 0
    try:
        plan = correspondent_repair.apply(bank, sleep_running=backend_running)
    except correspondent_repair.SleepRunning as exc:
        print(json.dumps({"refused": str(exc)}))
        return 3
    print(json.dumps(plan.counts()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
