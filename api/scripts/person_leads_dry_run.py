"""List the person pages that may be one person, for a bank, without writing anything (G209; ``person_leads``).

    api/.venv/bin/python -m api.scripts.person_leads_dry_run --bank <path> [--json] [--family person|org]

``--family org`` (2026-10-27) lists the same alias leads among organisations, labs, projects and tools
(``person_leads.ORG_TYPES``), grouped: every set of pages tied to one another by a lead is one line, the pages a
"Possible duplicate" question would put side by side the next time one of them is mentioned.

Prints one line per lead, each a pair of page ids and why they met: ``alias`` (the holder lists the other page's name
among its aliases), ``profile:<site>`` (the holder links that account; the other side may be a page or a name still
parked below the promotion bar, ``pending:<name>``), ``named_handle`` (a pending line parked as
"handle (Full Name)" whose full name has a page, which the next Sleep that hears the name folds in). Each lead also
says whether a "Possible duplicate" question is already open for the pair, or the person already said they are
different. What Sleep does with each, the next time a conversation names it: a page↔page lead raises the question
when either page is mentioned; a parked name another page links as an account raises it when that name is mentioned
again; a parked name another page lists as an alias goes to the alias judge when mentioned again (``same`` merges,
``unsure`` asks, ``different`` leaves it parked or promotes it); a ``handle (Full Name)`` line folds in when the full
name is mentioned. Nothing here asks, merges or writes. Output carries page ids and names from the bank, so it stays on the person's machine. Exit 0 done, 2 not a bank.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _pages(bank: Path) -> list[dict]:
    from api.services import markdown_parser

    pages = []
    for path in sorted((bank / "entities").glob("*.md")):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:
            continue
        pages.append({"id": path.stem, "frontmatter": parsed.frontmatter, "body": parsed.body})
    return pages


def org_groups(bank: Path) -> list[dict]:
    """Every group of organisation, lab, project and tool pages joined by alias leads (connected components)."""
    from api.services import merge_rejections, person_leads

    index = person_leads.PersonIndex(_pages(bank), person_leads.ORG_TYPES)
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    leads = [lead for lead in index.all_leads() if not merge_rejections.is_rejected(bank, lead.page, lead.holder)]
    for lead in leads:
        parent[find(lead.page)] = find(lead.holder)
    groups: dict[str, list[str]] = {}
    for pid in parent:
        groups.setdefault(find(pid), []).append(pid)
    out = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort()
        out.append({"pages": members,
                    "names": [person_leads.page_name(index.by_id[m]) for m in members],
                    "types": sorted({str(index.by_id[m]["frontmatter"].get("type")) for m in members}),
                    "keys": sorted({lead.key for lead in leads if lead.page in members})})
    out.sort(key=lambda g: (-len(g["pages"]), g["pages"]))
    return out


def survey(bank: Path) -> list[dict]:
    from api.services import merge_rejections, pending_store, person_leads
    from api.services.id_utils import sanitize_id
    from api.services.inbox_generator import find_open

    index = person_leads.PersonIndex(_pages(bank))
    rows: list[dict] = []
    for lead in index.all_leads():
        rows.append({
            "page": lead.page, "holder": lead.holder, "kind": lead.kind,
            "page_name": person_leads.page_name(index.by_id[lead.page]),
            "holder_name": person_leads.page_name(index.by_id[lead.holder]),
            "question_open": find_open(bank, "merge_suggestion", lead.page, lead.holder) is not None,
            "said_different": merge_rejections.is_rejected(bank, lead.page, lead.holder),
        })
    by_name = {person_leads.handle_key(n): ids for n, ids in index.by_name.items()}
    for line in pending_store.load(bank):
        if str(line.type).lower() != "person":
            continue
        split = person_leads.split_named_handle(line.name)
        if split is None:
            # A parked name another person page carries as an alias or a linked account.
            for holder, kind in index.holders_of(line.name):
                rows.append({"page": f"pending:{line.name}", "holder": holder, "kind": kind,
                             "page_name": line.name, "holder_name": person_leads.page_name(index.by_id[holder]),
                             "question_open": find_open(bank, "merge_suggestion", sanitize_id(line.name), holder)
                             is not None,
                             "said_different": merge_rejections.is_rejected(bank, sanitize_id(line.name), holder)})
            continue
        for holder in by_name.get(person_leads.handle_key(split[0]), ()):
            rows.append({"page": f"pending:{line.name}", "holder": holder, "kind": "named_handle",
                         "page_name": line.name, "holder_name": person_leads.page_name(index.by_id[holder]),
                         "question_open": False, "said_different": False})
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="person_leads_dry_run", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--json", action="store_true", help="one JSON object instead of lines")
    parser.add_argument("--family", choices=("person", "org"), default="person",
                        help="person pages (default) or organisation/lab/project/tool pages, grouped")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2
    if args.family == "org":
        groups = org_groups(bank)
        if args.json:
            print(json.dumps({"groups": groups, "count": len(groups)}, ensure_ascii=False, sort_keys=True))
            return 0
        for group in groups:
            print("\t".join(group["pages"]) + "\t(" + ", ".join(group["types"]) + ")")
        print(f"{len(groups)} group(s), {sum(len(g['pages']) for g in groups)} page(s); nothing written")
        return 0
    rows = survey(bank)
    if args.json:
        print(json.dumps({"leads": rows, "count": len(rows)}, ensure_ascii=False, sort_keys=True))
        return 0
    for row in rows:
        state = "said different" if row["said_different"] else ("question open" if row["question_open"] else "")
        print(f"{row['page']}\t<- {row['holder']}\t{row['kind']}\t{row['page_name']} / {row['holder_name']}"
              + (f"\t({state})" if state else ""))
    print(f"{len(rows)} lead(s); nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
