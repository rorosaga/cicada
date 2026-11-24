"""Count the connector posts written as the person's own words (G245; ``connector_text``).

    api/.venv/bin/python -m api.scripts.connector_text_dry_run --bank <path> [--ids]

Prints one JSON object of COUNTS, never a word of a post, a title or a link: how many X and Pinterest connector
episodes still hold the post's text under the person's ``## User note`` (``found``, by origin), how many of those Sleep
already read (``read_by_sleep``: their claims stay in git), how many wait for Sleep, how many the index read, and how
many pages and claims rest on them (``pages_citing``, ``claims_not_the_authors``). ``--ids`` adds the episode ids.
It changes nothing — no file, no commit — whatever ``connector_text.REPAIR`` says. Exit 0 done, 2 not a bank.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="connector_text_dry_run", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds episodes/)")
    parser.add_argument("--ids", action="store_true", help="also list the episode ids (ids only, never text)")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "episodes").is_dir():
        print(json.dumps({"error": "not a bank: no episodes/ directory"}))
        return 2

    from api.services import connector_text

    found = connector_text.repair(bank, apply=False)
    out = found.counts()
    if args.ids:
        out["ids"] = sorted(p.removeprefix("episodes/").removesuffix(".md") for p in found.paths)
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
