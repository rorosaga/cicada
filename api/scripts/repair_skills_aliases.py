"""Ground the skill pages the old Stage-4 writer left without sources, and drop references recorded as aliases —
run by the person, never automatically (G112 / G118; ``api.services.skill_alias_repair``).

    api/.venv/bin/python -m api.scripts.repair_skills_aliases --bank <path>           # dry run: counts only
    api/.venv/bin/python -m api.scripts.repair_skills_aliases --bank <path> --apply   # one `cicada` commit
    api/.venv/bin/python -m api.scripts.repair_skills_aliases --bank <path> --list    # + page ids and aliases to drop

``--list`` (dry run only) adds ``removals``: each page id and the aliases ``--apply`` would remove, so the person can
check them first. It prints words of the bank: for the person's own terminal, never for the repo, a PR or a log.

The bank is named explicitly; nothing is resolved from the environment's active bank. Prints one JSON object of counts
(never a page name or a word of the bank). Exit 0 done, 2 not a bank, 3 refused because Sleep is running or holds the
pages. Fails closed on the backend's answer exactly as ``migrate_claims_jsonl`` does.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from api.scripts.migrate_claims_jsonl import backend_running


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="repair_skills_aliases", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--apply", action="store_true", help="repair and commit; without it, report counts only")
    parser.add_argument("--list", action="store_true", help="dry run: also print the page ids and aliases to remove")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2

    from api.services import skill_alias_repair as repair

    if not args.apply:
        result = repair.survey(bank)
        out = result.counts()
        if args.list:
            out["removals"] = result._removals
        print(json.dumps(out, ensure_ascii=False))
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
