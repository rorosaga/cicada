"""Rebuild a bank's fact-sheet pages as articles — run by the person, never automatically (G194 articles;
``api.services.page_article_rebuild``).

    api/.venv/bin/python -m api.scripts.rebuild_page_articles --bank <path>                    # dry run: counts only
    api/.venv/bin/python -m api.scripts.rebuild_page_articles --bank <path> --limit 5 --preview-dir <outside-dir>
    api/.venv/bin/python -m api.scripts.rebuild_page_articles --bank <path> --entity <id> --entity <id> --apply

The dry run makes no model call and prints counts: pages, those skipped (archived, media, human prose, resting on
one conversation, already articles, over the writer's input budget) and those selected, with their prompt
characters. ``--limit N`` and ``--entity <id>`` (repeatable) narrow the sample. ``--preview-dir`` makes the calls and
writes ``<id>.before.md`` / ``<id>.after.md`` there, never touching the bank (the directory must be outside it).
``--apply`` makes the calls, then writes the pages in one commit; it is refused unless the backend says Sleep is
idle. The calls use the engine and model the bank's settings name for Sleep's page writes. ``--rewrite`` also
rewrites pages that already have an article.

The bank is named explicitly; nothing is resolved from the environment's active bank. Prints one JSON object of
counts (never a page name or a word of the bank). Exit 0 done, 2 not a bank or a bad preview directory, 3 refused
because Sleep is running or holds the pages.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from api.scripts.migrate_claims_jsonl import backend_running


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rebuild_page_articles", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--entity", action="append", default=[], help="rebuild only this page id (repeatable)")
    parser.add_argument("--limit", type=int, default=None, help="rebuild at most this many pages (by id)")
    parser.add_argument("--rewrite", action="store_true", help="also rewrite pages that already have an article")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preview-dir", help="write before/after files here (outside the bank); the bank is untouched")
    mode.add_argument("--apply", action="store_true", help="write the pages and commit; refused unless Sleep is idle")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2
    preview = Path(args.preview_dir).expanduser().resolve() if args.preview_dir else None
    if preview is not None and (preview == bank or bank in preview.parents):
        print(json.dumps({"error": "the preview directory must be outside the bank"}))
        return 2

    from api.config import Settings
    from api.services import page_article_rebuild as rebuild

    settings = Settings()   # the engine and model; the bank is always the one named here, passed explicitly
    mode_name = "apply" if args.apply else "preview" if preview is not None else "dry"
    try:
        result = rebuild.run(bank, settings, mode=mode_name, sleep_running=backend_running,
                             entity_ids=args.entity, limit=args.limit, rewrite=args.rewrite, preview_dir=preview)
    except rebuild.SleepRunning as exc:
        print(json.dumps({"refused": str(exc)}))
        return 3
    print(rebuild.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
