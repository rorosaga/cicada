"""List every project page of a bank with where it came from, without writing anything (G141, ruling 36 D4).

    api/.venv/bin/python -m api.scripts.project_origins_dry_run --bank <path> [--json] [--quotes]

One line per page whose ``type`` is ``project`` (any status): its id, the origin the bank can show — ``repo`` (a
repository the person works in with an agent, or one they declared on the page), ``words`` (their own words, or a
watched folder they named) or ``neither`` — and one sentence saying why, with the conversation that shows it. A page
that already carries its birth record says ``stored``; every other answer is derived now, read only, from the page's
own frontmatter and the conversations it cites (``project_birth.classify``). ``--quotes`` adds the person's sentence
for a ``words`` origin. Nothing is asked, archived, deleted or committed: the review list for ``neither`` pages is raised
only after the owner reads this. Output carries page ids, names and (with ``--quotes``) the person's words from the
bank, so it stays on the person's machine. Exit 0 done, 2 not a bank.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def survey(bank: Path, *, quotes: bool = False) -> list[dict]:
    from api.services import evidence, markdown_parser, project_birth

    docs: dict[str, tuple[dict, str] | None] = {}

    def document(ep: str):
        if ep not in docs:
            docs[ep] = evidence.source_document(bank, ep)
        return docs[ep]

    rows = []
    for path in sorted((bank / "entities").glob("*.md")):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 - an unreadable page is reported, never fixed here
            rows.append({"id": path.stem, "name": path.stem, "origin": "unreadable", "why": "The page did not parse."})
            continue
        fm = parsed.frontmatter or {}
        if str(fm.get("type") or "") != "project":
            continue
        o = project_birth.classify(bank, path.stem, fm, documents=document)
        row = {"id": path.stem, "name": str(fm.get("name") or path.stem), "status": str(fm.get("status") or "active"),
               "origin": o.kind or "neither", "stored": o.stored, "why": o.why, "day": o.day, "episode": o.episode,
               "repo": (o.repo or {}).get("name"), "via": o.via, "conversations_read": o.episodes_read}
        if quotes and o.kind == project_birth.WORDS and o.span:
            row["quote"] = project_birth.quote(bank, {"episode": o.episode, "span": o.span})
        rows.append(row)
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="project_origins_dry_run", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--json", action="store_true", help="one JSON object instead of lines")
    parser.add_argument("--quotes", action="store_true", help="add the person's sentence for a words origin")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2
    rows = survey(bank, quotes=args.quotes)
    counts = Counter(r["origin"] for r in rows)
    if args.json:
        print(json.dumps({"projects": rows, "counts": dict(counts), "count": len(rows)}, ensure_ascii=False,
                         sort_keys=True))
        return 0
    for r in rows:
        where = " · ".join(x for x in (r.get("day"), r.get("episode"), r.get("repo") and f"repo {r['repo']}") if x)
        print(f"{r['origin']:<8} {'stored ' if r.get('stored') else 'derived'} {r['id']}  ({r.get('status')})"
              f"{'  ' + where if where else ''}\n         {r['why']}")
        if r.get("quote"):
            print(f"         “{r['quote']}”")
    print(f"\n{len(rows)} project page(s): " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
