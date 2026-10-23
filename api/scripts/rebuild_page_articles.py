"""Rebuild a bank's fact-sheet pages as articles — run by the person, never automatically (G194 articles;
``api.services.page_article_rebuild``).

    api/.venv/bin/python -m api.scripts.rebuild_page_articles --bank <path>                    # dry run: counts only
    api/.venv/bin/python -m api.scripts.rebuild_page_articles --bank <path> --limit 5 --preview-dir <outside-dir>
    api/.venv/bin/python -m api.scripts.rebuild_page_articles --bank <path> --entity <id> --entity <id> --apply

The dry run makes no model call and prints counts: pages, those skipped (archived, media, human prose, stubs — one
conversation and less than ``CICADA_PAGE_ARTICLE_MIN_MATERIAL`` inputs —, already articles, over the writer's input
budget) and those selected, newest-mentioned first, with how many rest on one conversation, their prompt characters,
the estimated calls (one a page) and the batches an apply commits. ``--limit N`` and ``--entity <id>`` (repeatable)
narrow the sample. ``--preview-dir`` makes the calls and writes ``<id>.before.md`` / ``<id>.after.md`` there, never
touching the bank (the directory must be outside it). ``--apply`` makes the calls and writes the pages
``--batch-size`` (25) at a time, one commit a batch; it is refused unless the backend says Sleep is idle, and stops
between batches if Sleep starts. A slow or absent backend is asked again before either, and the refusal or stop says
which it was — Sleep running, or the backend slow, unreachable or unreadable. ``--rewrite`` also rewrites pages that already have an article (one written today
counts as done, so a rerun continues).

The engine is the one a Sleep run the person starts would use: the engine chosen in Settings → Intelligence (a plan when
one is chosen and connected), resolved before any call and named in the output (``engine``, never a key). Nothing
connected: refused before any call. An API key, billed per call: refused unless ``--allow-metered`` is passed — a
rebuild on a metered key spends money, so it is agreed to by name.

The bank is named explicitly; nothing is resolved from the environment's active bank. Prints one JSON object of
counts (never a page name or a word of the bank). Exit 0 done, 2 not a bank or a bad preview directory, 3 refused
because Sleep is running or holds the pages, 4 refused because no engine resolves or it is metered without
``--allow-metered``, 5 stopped early (a plan limit, an unreachable engine, pages failing in a row, or Sleep starting — or the backend not
confirming it idle — between batches): every batch before the stop is committed, and the stopped batch's finished pages too (``stopped`` says why,
``not_attempted`` how many were never asked; run it again to continue — finished pages are already articles). One page's malformed answer, timeout or refusal never
stops the run: that page is skipped and counted under ``page_failures``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from api.scripts.migrate_claims_jsonl import backend_problem, backend_running


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rebuild_page_articles", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--entity", action="append", default=[], help="rebuild only this page id (repeatable)")
    parser.add_argument("--limit", type=int, default=None, help="rebuild at most this many pages (by id)")
    parser.add_argument("--rewrite", action="store_true", help="also rewrite pages that already have an article")
    parser.add_argument("--batch-size", type=int, default=25, help="pages per commit with --apply (default 25)")
    parser.add_argument("--allow-metered", action="store_true",
                        help="allow an API-key engine, billed per call (refused without this)")
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

    # The engine settings; `rebuild.run` resolves the engine the person chose, as a person-started Sleep does. The bank
    # is always the one named here, passed explicitly.
    settings = Settings()
    mode_name = "apply" if args.apply else "preview" if preview is not None else "dry"
    try:
        result = rebuild.run(bank, settings, mode=mode_name, sleep_running=backend_running,
                             entity_ids=args.entity, limit=args.limit, rewrite=args.rewrite, preview_dir=preview,
                             allow_metered=args.allow_metered, batch_size=max(1, args.batch_size),
                             backend_problem=backend_problem)
    except rebuild.SleepRunning as exc:
        print(json.dumps({"refused": str(exc)}))
        return 3
    except rebuild.EngineRefused as exc:
        print(json.dumps({"refused": str(exc), "engine": exc.engine}))
        return 4
    print(rebuild.dumps(result))
    return 5 if result.stopped else 0


if __name__ == "__main__":
    sys.exit(main())
