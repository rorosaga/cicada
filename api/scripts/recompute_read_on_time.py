"""Place an existing bank's late-read conversations on the day they were said, once — run by the person, never
automatically (owner ruling 2026-10-16, "read on time"; ``api.services.read_on_time_recompute``).

    api/.venv/bin/python -m api.scripts.recompute_read_on_time --bank <path>           # dry run: counts only
    api/.venv/bin/python -m api.scripts.recompute_read_on_time --bank <path> --apply   # one `cicada` commit

The dry run counts, overall and by type, the pages whose newest mention was read late under the old rule
(`read_late`), how many reading it on time lifts (`lifted`: `to_active`, `to_decaying`, `still_archived`;
`faded_by_age` of them stay below 0.4 and are never asked), and the claims (`claims_read_late`, `claims_lifted`).
``--apply`` writes exactly that — confidence, status, the watermark, the faded mark and the changed claim lines — in
one `cicada` commit (trigger ``maintenance/read-on-time``), refused while Sleep runs or holds the pages; pages dirty in
git or written since the survey are skipped. It only raises. A second run changes nothing. No inbox item is written.

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
    parser = argparse.ArgumentParser(prog="recompute_read_on_time", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--apply", action="store_true", help="write and commit; without it, report counts only")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2

    from api.services import read_on_time_recompute as recompute

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
