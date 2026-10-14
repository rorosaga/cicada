"""Retitle captured sessions whose title is a wrapper tag, once — run by the person, never automatically
(2026-10-14; ``api.services.episode_title``).

    api/.venv/bin/python -m api.scripts.retitle_wrapped_episodes --bank <path>           # dry run: counts only
    api/.venv/bin/python -m api.scripts.retitle_wrapped_episodes --bank <path> --apply   # one `cicada` commit

Before the fix a Claude Code or Codex session whose first message opened with a wrapper (``<pasted_content …>`` around
a paste) was titled by the bare tag. This reads every transcript episode (``capture_kind: transcript``), and one whose
title opens with a tag is retitled from its OWN stored body by the capture's current rule — the transcript is never
re-read. The title is outside ``content_hash``: nothing is re-queued for Sleep. ``--apply`` writes exactly what the dry
run counted, in one `cicada` commit (trigger ``maintenance/episode-titles``), refused while Sleep runs or holds the
pages; an episode dirty in git or captured again since the survey is skipped (a later capture of a live session titles
it by the new rule anyway). A second run changes nothing.

The bank is named explicitly; nothing is resolved from the environment's active bank. Prints one JSON object of counts
(never a title or a word of the bank). Exit 0 done, 2 not a bank, 3 refused because Sleep is running or holds the pages.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from api.scripts.migrate_claims_jsonl import backend_running


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="retitle_wrapped_episodes", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds episodes/)")
    parser.add_argument("--apply", action="store_true", help="write and commit; without it, report counts only")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "episodes").is_dir():
        print(json.dumps({"error": "not a bank: no episodes/ directory"}))
        return 2

    from api.services import episode_title

    if not args.apply:
        print(json.dumps(episode_title.survey(bank).counts()))
        return 0
    try:
        result = episode_title.apply(bank, sleep_running=backend_running)
    except episode_title.SleepRunning as exc:
        print(json.dumps({"refused": str(exc)}))
        return 3
    print(json.dumps(result.counts()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
