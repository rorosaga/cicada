"""Give an existing bank's hub pages their new shape once — run by the person, never automatically (owner page,
2026-10-14; ``api.services.hub_pages``).

    api/.venv/bin/python -m api.scripts.split_hub_pages --bank <path>           # dry run: counts only
    api/.venv/bin/python -m api.scripts.split_hub_pages --bank <path> --apply   # one `cicada` commit

A page whose claims fence is over ``claims_ledger.FENCE_MAX_CHARS`` keeps its newest claims and the facts about it on
the page and moves the rest, line for line, into ``entities/<id>.claims.jsonl`` beside it; a page linking more than
``entity_body.RELATED_MAX`` pages rolls its ``## Related`` up (its relations and people a line each, every other link
counted per verb — each link is still an edge, on the linked page, and in the claims). Every page is checked before it
is written: each claim id and evidence span it held reads back from the page and its ledger, and each link it showed is
still a line, an edge or a ``related:`` slug; a page that fails is left as it was (``failed_check``).

The dry run prints the counts (pages, claims moved, bytes before and after, Related lines before and after) and writes
nothing. ``--apply`` writes exactly that in one `cicada` commit (trigger ``maintenance/hub-pages``), refused while Sleep
runs or holds the pages; a page dirty in git or written since the survey is skipped. A second run changes nothing.
The article for such a page is then ``api.scripts.rebuild_page_articles``'s to write.

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
    parser = argparse.ArgumentParser(prog="split_hub_pages", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--apply", action="store_true", help="write and commit; without it, report counts only")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2

    from api.services import hub_pages

    if not args.apply:
        print(json.dumps(hub_pages.survey(bank).counts()))
        return 0
    try:
        result = hub_pages.apply(bank, sleep_running=backend_running)
    except hub_pages.SleepRunning as exc:
        print(json.dumps({"refused": str(exc)}))
        return 3
    print(json.dumps(result.counts()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
