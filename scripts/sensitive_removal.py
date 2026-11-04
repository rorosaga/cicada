"""What Remove would touch on a bank, and applying it (G235, ruling 60). A dry run unless ``--apply``.

The dry run reads the bank's episode files only: no backend, git, index, network or telemetry. It prints one line per
conversation (a row id, kinds with counts, how many are unsure, source, day, whether Sleep has read it) and totals. Never a
value, a title, a path or a line of text; a source outside the known list prints as ``other``.

``--apply`` asks the RUNNING backend to do it (`POST /sensitive/remove`, the same writer as the review card's Remove): one
git writer per bank, under Sleep's write window. It needs ``--plan``, the stamp a dry run printed (ids and counts, nothing
of what they hold), so it removes what that dry run listed or nothing: the backend refuses if a row was swapped, added or
grew since. It prints counts only, including how many files still hold a removed value.

**What Remove does and does not do.** The older version is committed first; if it cannot be, nothing is removed. The value
leaves the conversation, every other conversation holding the same distinctive value, and every file that repeated it; a
value that could be an ordinary word stays out of that spread (only its own place, and a tied file's line that speaks of a
secret). The word index is rebuilt and the vector index's passages holding it are deleted. Git history keeps the older
version, and is never rewritten. The source (the Notes app, a chat, the transcript) still holds it: Cicada never edits a source, and takes it out
again if that source sends it. What an engine already read cannot be unread. A wrong alarm loses that word from the
conversation too, so read the dry run first; the older version in git is how to get it back.

Usage:
  api/.venv/bin/python scripts/sensitive_removal.py --memory /path/to/bank
  api/.venv/bin/python scripts/sensitive_removal.py --memory /path/to/bank --apply --plan <stamp> \\
      --api http://127.0.0.1:<port> --token-file <CICADA_HOME>/api_token [--rows id,id]
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from api.services import sensitive_flags  # noqa: E402


def _print_plan(rows: list[dict]) -> None:
    for r in rows:
        kinds = " ".join(f"{k}:{n}" for k, n in sorted(r["kinds"].items()))
        unsure = f" unsure:{r['unsure']}" if r["unsure"] else ""
        print(f"{r['row']}  {kinds}{unsure}  {r['source']}  {r['day'] or 'no-date'}  {'read' if r['read'] else 'waiting'}")
    by_kind: Counter = Counter()
    for r in rows:
        by_kind.update(r["kinds"])
    print(f"conversations: {len(rows)}  read: {sum(r['read'] for r in rows)}  waiting: {sum(not r['read'] for r in rows)}")
    print(f"hits by kind: {dict(sorted(by_kind.items()))}  unsure: {sum(r['unsure'] for r in rows)}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--memory", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--api", help="the running backend, for --apply")
    parser.add_argument("--token-file", type=Path, help="its api_token file, for --apply")
    parser.add_argument("--rows", help="comma-separated row ids; absent: every conversation listed")
    parser.add_argument("--plan", help="the stamp the dry run printed, for --apply")
    args = parser.parse_args(argv)
    if not (args.memory / "episodes").is_dir():
        print("no episodes directory")
        return 2

    rows = sensitive_flags.plan(args.memory)
    wanted = [r.strip() for r in args.rows.split(",") if r.strip()] if args.rows else None
    if wanted is not None:
        unknown = set(wanted) - {r["row"] for r in rows}
        if unknown:
            print(f"{len(unknown)} row id(s) are not in the plan")
            return 2
        rows = [r for r in rows if r["row"] in wanted]
    _print_plan(rows)
    stamp = sensitive_flags.plan_stamp(rows)
    print(f"plan: {stamp}")
    if not args.apply:
        print("dry run: nothing written. --apply --plan <the stamp above> to remove these.")
        return 0
    if not args.api or not args.token_file or not args.plan:
        print("--apply needs --plan, --api and --token-file: the running backend does the writing")
        return 2
    if args.plan != stamp:
        print("refused: this is not what the dry run listed. Run the dry run again.")
        return 1
    if not rows:
        print("nothing to remove")
        return 0

    body = {"rows": [r["row"] for r in rows], "plan": stamp}
    request = urllib.request.Request(
        f"{args.api.rstrip('/')}/sensitive/remove", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {args.token_file.read_text().strip()}"})
    try:
        with urllib.request.urlopen(request, timeout=1800) as response:   # noqa: S310 - the person's own backend
            answer = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        print(f"refused: {exc.code}")     # never the body: nothing from the bank goes to a terminal unchecked
        return 1
    print(f"removed: {answer.get('removed')}  failed: {answer.get('failed')}  files: {answer.get('files')}  "
          f"committed: {answer.get('committed')}  left: {answer.get('left')}  still found in files: {answer.get('still_found')}")
    return 1 if answer.get("failed") or not answer.get("committed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
