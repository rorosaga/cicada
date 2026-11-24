"""Replay of the name-asked-on-the-second-mention rule over stored benchmark banks, no model (2026-11-24).

For every open "What's <description>'s name?" question (`asks: name`) in the banks under the given roots, did the person's
page rest on one conversation (`role_people.heard_again` false: the question would not have been asked, and Sleep's
`name_once` rule would retire it) or on two or more (asked as before)? Reads copies under ~/cicada-bench only.

    api/.venv/bin/python -m benchmarks.consolidation.name_question_replay ~/cicada-bench/fable --show 10
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def questions(root: Path):
    for inbox in sorted(root.rglob("bank/inbox")):
        bank = inbox.parent
        for path in sorted(inbox.glob("inbox-*.md")):
            yield bank, path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root", type=Path, nargs="+")
    ap.add_argument("--show", type=int, default=10)
    a = ap.parse_args()
    from api.services import markdown_parser, role_people
    from api.services.id_utils import resolve_entity_file

    seen, rows = set(), []
    for root in a.root:
        for bank, path in questions(root):
            fm = markdown_parser.parse(path).frontmatter or {}
            if fm.get("asks") != "name" or str(fm.get("status") or "pending") != "pending":
                continue
            page = resolve_entity_file(bank, str(fm.get("entity_id") or ""))
            if page is None:
                continue
            pfm = markdown_parser.parse(page).frontmatter or {}
            key = (str(bank), path.name)
            if key in seen:
                continue
            seen.add(key)
            eps = [str(e) for e in pfm.get("source_episodes") or [] if e]
            rows.append({"bank": str(bank), "question": fm.get("question"), "episodes": eps,
                         "again": role_people.heard_again(bank, pfm)})
    out = [r for r in rows if not r["again"]]
    print(f"{len(rows)} open name questions in {len({r['bank'] for r in rows})} banks; {len(out)} would no longer be asked "
          f"(one conversation), {len(rows) - len(out)} stay (two or more)")
    for r in rows[: a.show]:
        print(("RETIRED " if not r["again"] else "STAYS   "), len(r["episodes"]), "episode(s)", r["question"], "|", Path(r["bank"]).parent.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
