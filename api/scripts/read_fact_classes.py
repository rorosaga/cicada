"""Give facts that have no class one, once — run by the person, never automatically (ROR-129, owner 2026-11-07;
``api.services.fact_class_pass``).

    api/.venv/bin/python -m api.scripts.read_fact_classes --bank <path>                    # dry run: counts and the estimate
    api/.venv/bin/python -m api.scripts.read_fact_classes --bank <path> --limit 200 --apply   # a sample
    api/.venv/bin/python -m api.scripts.read_fact_classes --bank <path> --apply               # all of them

A fact has its own relevance apart from its page, but every fact already in a memory has no class, and on an evergreen
page (the owner's, a pinned one) such a fact is lent ``active`` and fades with the rest. This asks the model for each
one's class — the same rule Stage 1 has, by meaning, in any language, no word list — and writes the answers. **Run it
before** ``reset_fact_clocks``. Never a fact the person set ("Keep this fact", or let fade) nor one that has a class.

The dry run makes no model call: it prints the facts it would ask about, the calls, the estimated tokens and the estimated
cost at the model's list price (``cost_usd_estimated``, with its ``cost_basis``), and the engine that would answer. ``--apply``
makes the calls (60 facts each) and writes every answer in ONE commit authored by the model that answered — undo it by
reverting that commit. It is refused while Sleep runs; the engine is the one a Sleep run the person starts would use, named
in the output; an API key, billed per call, is refused unless ``--allow-metered`` is passed. The bank is named explicitly.
Prints one JSON object of counts (never a page name or a word of the bank). Exit 0 done, 2 not a bank, 3 refused because
Sleep is running or holds the pages, 4 refused because no engine resolves or it is metered without ``--allow-metered``,
5 stopped early (a plan limit, an unreachable engine): the answers before the stop are written; run it again for the rest.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from api.scripts.migrate_claims_jsonl import backend_problem, backend_running


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="read_fact_classes", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--limit", type=int, default=None, help="ask about at most this many facts (a sample)")
    parser.add_argument("--allow-metered", action="store_true",
                        help="allow an API-key engine, billed per call (refused without this)")
    parser.add_argument("--apply", action="store_true", help="make the calls and write; without it, counts only")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2

    from api.config import Settings
    from api.services import fact_class_pass as passes

    try:
        result = passes.run(bank, Settings(), mode="apply" if args.apply else "dry", sleep_running=backend_running,
                            limit=args.limit, allow_metered=args.allow_metered, backend_problem=backend_problem)
    except passes.SleepRunning as exc:
        print(json.dumps({"refused": str(exc)}))
        return 3
    except passes.EngineRefused as exc:
        print(json.dumps({"refused": str(exc), "engine": exc.engine}))
        return 4
    print(passes.dumps(result))
    return 5 if result.stopped else 0


if __name__ == "__main__":
    sys.exit(main())
