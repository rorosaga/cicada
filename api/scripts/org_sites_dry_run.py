"""List, per organisation page, the website Cicada would find and whether it would trust it — writing nothing (ruling 40).

    api/.venv/bin/python -m api.scripts.org_sites_dry_run --bank <path> [--json] [--limit N] [--no-lookup]
        [--no-fetch] [--logos] [--all]

One row per live ``company`` / ``tool`` / ``location`` page with no trusted website (``org_sites.skip_reason`` says
which pages are out of scope, and ``--all`` lists those too): the site found, its basis (``record`` — the page or the
person's own words already carry it; ``lookup`` — Wikidata's official website for exactly one matching item), whether it
would be **trusted** (its homepage names the entity) or only a **proposal** for the "Confirm N links" review, why, and
the logo domain it would yield. ``--logos`` also asks the logo ladder for that domain (bytes are never stored).

Read only: no page, no inbox item and no cache is written, nothing is committed. It does reach the network (Wikidata's
API and each candidate site's homepage, on Cicada's own rail) unless ``--no-lookup`` / ``--no-fetch``; only page
names and aliases are sent, never a person's name. The output carries page names from the bank, so it stays on the
person's machine. Exit 0 done, 2 not a bank.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path


async def survey(bank: Path, *, limit: int | None, lookup: bool, fetch: bool, logos: bool, show_all: bool,
                 only: frozenset[str] = frozenset(),
                 concurrency: int = 4) -> list[dict]:
    from api.services import bank_index, link_enrichment, logo_service, markdown_parser, org_sites

    names = org_sites.bank_names(bank)
    pages = []
    skipped: list[dict] = []
    for f in bank_index.files(bank, "entities"):
        fm = f.frontmatter or {}
        reason = org_sites.skip_reason(fm, names)
        if reason is None:
            pages.append((len(fm.get("source_episodes") or []), f.stem))
        elif show_all and str(fm.get("type") or "") in org_sites.SCOPE_TYPES:
            skipped.append({"id": f.stem, "name": str(fm.get("name") or f.stem), "type": fm.get("type"),
                            "outcome": "skipped", "reason": reason})
    pages.sort(key=lambda r: (-r[0], r[1]))
    if only:
        pages = [p for p in pages if p[1] in only]
    if limit:
        pages = pages[:limit]
    classes = org_sites.Classes(org_sites.wikidata_get)
    sem = asyncio.Semaphore(concurrency)

    async def identity(url: str):
        return await link_enrichment.fetch_identity(url, None)

    async def one(entity_id: str) -> dict:
        try:
            return await _one(entity_id)
        except Exception as exc:  # noqa: BLE001 — one page never ends the survey
            return {"id": entity_id, "name": entity_id, "type": "?", "outcome": "error",
                    "reason": type(exc).__name__}

    async def _one(entity_id: str) -> dict:
        async with sem:
            parsed = markdown_parser.parse(bank / "entities" / f"{entity_id}.md")
            fm = dict(parsed.frontmatter)
            finding = await org_sites.decide(bank, entity_id, fm, parsed.body, names,
                                             get=org_sites.wikidata_get if lookup else None,
                                             classes=classes if lookup else None,
                                             fetch_identity=identity if fetch else None)
            row = {"id": entity_id, "name": finding.name, "type": finding.type,
                   "conversations": len(fm.get("source_episodes") or []), "outcome": finding.outcome,
                   "site": finding.site or (finding.proposals[0] if finding.proposals else None),
                   "proposals": finding.proposals, "basis": finding.basis, "item": finding.item,
                   "why": finding.why, "reason": finding.reason, "evidence": finding.evidence}
            row["logo_domain"] = logo_service._host(finding.site) if finding.trusted else None
            if logos and row["logo_domain"]:
                got = await logo_service.fetch_logo(row["logo_domain"])
                row["logo"] = f"{got[1]} {len(got[0])} bytes" if got else "miss (monogram)"
            return row

    rows = await asyncio.gather(*(one(stem) for _, stem in pages))
    return list(rows) + skipped


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="org_sites_dry_run", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--json", action="store_true", help="one JSON object instead of lines")
    parser.add_argument("--limit", type=int, default=None, help="only the N busiest pages")
    parser.add_argument("--no-lookup", action="store_true", help="the record only: no Wikidata request")
    parser.add_argument("--no-fetch", action="store_true", help="no homepage read (nothing can be trusted by a fetch)")
    parser.add_argument("--logos", action="store_true", help="ask the logo ladder for each trusted site's domain")
    parser.add_argument("--all", action="store_true", help="also list in-scope-type pages that are skipped, and why")
    parser.add_argument("--ids", default="", help="only these page ids, comma-separated")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(f"not a bank: {bank}", file=sys.stderr)
        return 2
    rows = asyncio.run(survey(bank, limit=args.limit, lookup=not args.no_lookup, fetch=not args.no_fetch,
                              logos=args.logos, show_all=args.all,
                              only=frozenset(i for i in args.ids.split(",") if i)))
    totals = Counter(r["outcome"] for r in rows)
    by_basis = Counter(f"{r['outcome']}:{r.get('basis')}" for r in rows if r["outcome"] in ("trusted", "proposal"))
    if args.json:
        print(json.dumps({"rows": rows, "totals": dict(totals), "by_basis": dict(by_basis)}, indent=2, default=str))
        return 0
    for r in rows:
        logo = f" logo={r.get('logo') or r.get('logo_domain') or '-'}" if r["outcome"] == "trusted" else ""
        print(f"{r['outcome']:<8} {r['type']:<8} {r['name'][:48]:<48} {str(r.get('site') or '-'):<36} "
              f"{str(r.get('basis') or '-'):<6} {r.get('item') or '':<10} {r.get('reason') or ''}{logo}")
    print(f"\ntotals: {dict(totals)}  by basis: {dict(by_basis)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
