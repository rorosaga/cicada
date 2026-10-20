"""Put the looks already saved on the pages of the things they show (owner 2026-10-20; ``api.services.looks_attach``)
— run by the person, never automatically.

    api/.venv/bin/python -m api.scripts.attach_looks --bank <path>           # dry run: counts only
    api/.venv/bin/python -m api.scripts.attach_looks --bank <path> --list    # + which looks stay unattached, and moves
    api/.venv/bin/python -m api.scripts.attach_looks --bank <path> --apply   # one `cicada` commit

A look goes on the one page whose trusted site is the look's site, else on the saved link's own page; a look with
neither is left unattached (never a page invented) and ``--list`` names it. Idempotent: run it again and it writes
nothing. ``--list`` prints look ids, which carry site names: for the person's own terminal, never for the repo, a PR
or a log.

The bank is named explicitly; nothing is resolved from the environment's active bank. Prints one JSON object. Exit 0
done, 2 not a bank, 3 refused because Sleep is running or holds the pages (fails closed on the backend's answer, as
``migrate_claims_jsonl`` does).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from api.scripts.migrate_claims_jsonl import backend_running


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="attach_looks", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/ and design/)")
    parser.add_argument("--apply", action="store_true", help="attach and commit; without it, report counts only")
    parser.add_argument("--list", action="store_true", help="dry run: also print the looks left unattached and the moves")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2

    from api.services import looks_attach

    if not args.apply:
        result = looks_attach.survey(bank)
        out = result.counts()
        if args.list:
            out.update(result.listing())
        print(json.dumps(out, ensure_ascii=False))
        return 0
    try:
        result = looks_attach.apply(bank, sleep_running=backend_running)
    except looks_attach.SleepRunning as exc:
        print(json.dumps({"refused": str(exc)}))
        return 3
    print(json.dumps(result.counts()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
