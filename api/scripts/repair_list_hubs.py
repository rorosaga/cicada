"""Take saved lists' tags off their pages and remove the hubs they made — run by the person, never automatically.

    api/.venv/bin/python -m api.scripts.repair_list_hubs --bank <path>            # dry run: counts only
    api/.venv/bin/python -m api.scripts.repair_list_hubs --bank <path> --apply    # one `cicada` commit

A playlist, board, collection or bookmark folder is where a save came from (its page's ``folder:``), never a hub
(owner 2026-10-19). The rule and the rails are in ``api.services.list_hub_repair``. The bank is named explicitly;
nothing is resolved from the environment's active bank. Exit 0 done, 2 not a bank, 3 refused because Sleep is running
or holds the pages.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _sleep_running() -> bool:
    """The entity-type repair's check: an unreachable backend is said as such, never as a Sleep run."""
    from api.scripts.repair_entity_types import _sleep_running as asked
    from api.services import entity_type_repair, list_hub_repair

    try:
        return asked()
    except entity_type_repair.SleepRunning as exc:
        raise list_hub_repair.SleepRunning(str(exc)) from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="repair_list_hubs", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--apply", action="store_true", help="untag, regenerate the hubs and commit; without it, counts only")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2

    from api.services import list_hub_repair as repair

    if not args.apply:
        print(json.dumps(repair.survey(bank).counts()))
        return 0
    try:
        result = repair.apply(bank, sleep_running=_sleep_running)
    except repair.SleepRunning as exc:
        print(json.dumps({"refused": str(exc)}))
        return 3
    print(json.dumps(result.counts()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
