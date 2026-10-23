"""Dry run of Sleep's "Where to check" step (G61, G208, ruling 36 D5): what it WOULD propose, per page. Writes nothing.

Lists, for every active page, the profile links (person pages) and own GitHub repositories (project and tool pages)
the record already holds that are not yet a source and were never removed — exactly what
``source_proposals.propose`` would put on the page, and where each was found: the page's own text, or a line of the
person's own words in one of the page's conversations. Every link would be one row of ONE review item ("Confirm N
links"); only a link that passes the strict rule (the person's own line names exactly that page and the link's account
is its name or an alias) would wait apart, for Sleep to settle.

Reads files only: no backend, no git, no index, no network, no telemetry. Run it on a copy if in doubt.

Usage:
  api/.venv/bin/python scripts/where_to_check_dry_run.py --memory /path/to/bank            # per page
  api/.venv/bin/python scripts/where_to_check_dry_run.py --memory /path/to/bank --summary  # counts only

The output names pages and links from the bank: keep it out of commits, PRs and repo docs (the privacy rule).
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from api.services import source_proposals  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--memory", required=True, help="the bank directory (never defaulted)")
    parser.add_argument("--summary", action="store_true", help="counts only — no page ids, no links")
    args = parser.parse_args(argv)
    memory = Path(args.memory).expanduser()
    if not (memory / "entities").is_dir():
        print(f"no entities/ under {memory}", file=sys.stderr)
        return 2
    from api.services import markdown_parser

    rows = source_proposals.plan(memory)
    kinds: Counter = Counter()
    strict = 0
    for page_id, cands in rows:
        page_fm = markdown_parser.parse(memory / "entities" / f"{page_id}.md").frontmatter
        marks = []
        for c in cands:
            kinds[c.predicate] += 1
            ok = source_proposals.strict_quote(memory, page_fm, {"ref": c.ref, "evidence": c.evidence}) is not None
            strict += ok
            marks.append(ok)
        if not args.summary:
            print(page_id)
            for c, ok in zip(cands, marks):
                where = f"your words, {c.evidence['episode']}" if c.evidence.get("episode") else "the page's text"
                print(f"  {c.predicate:<9} {c.ref}  ({where}){'  [Sleep may settle]' if ok else ''}")
    total = sum(kinds.values())
    print(f"\n{len(rows)} page(s), {total} proposal(s): "
          + (", ".join(f"{k} {n}" for k, n in sorted(kinds.items())) or "none")
          + f"; {total - strict} as rows of one review item, {strict} apart for Sleep to settle (strict rule)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
