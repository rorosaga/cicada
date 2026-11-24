"""Print what the arrival join decided, last night, for a bank — the coordinator's per-item reading (G245, plan 3.8).

    api/.venv/bin/python -m api.scripts.arrival_join_report --bank <path> [--json] [--run] [--names]

The nightly step (`arrival_join.run_tail`, in Sleep's tail) runs every rule and leaves its reading OUTSIDE every bank
(`$CICADA_HOME/people/<bank>/arrival-join-report.json`); while ``arrival_join.LIVE`` is false it writes nothing else, anywhere.
This prints that file: per first-name page that has a namesake in a directory, its day and where the day came from, the arrival
(a hash), both days and the gap, each directory's freshness stamp, every namesake row it counted (a hash, its kind, its day, the
role it played: arrival, blocker or other), the conflict and veto answers, and the decision with its reason — never counts alone.
A page the bank holds is named by its id (the bank's own slug); a directory row is only ever a hash.

``--run`` first runs the decision now (no engine, so the veto is read from its cache or reported as unavailable) and writes the
report, then prints it; it writes nothing into the bank. ``--names`` prints, to this terminal only and never into the report or a
log, each arrival's row name read back from the directory on this Mac, so the coordinator can judge "is this the person?".
The bank is the memory folder; the directories are read from ``$CICADA_HOME`` as Sleep reads them. Exit 0 done, 2 not a bank.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _names(bank: Path, refs: set[str]) -> dict[str, str]:
    """Read back, for the terminal only, the name of each row a hash names (a connection's id, a card's hashed id)."""
    from api.services import contacts_local, linkedin_people

    found: dict[str, str] = {}
    for row in linkedin_people.arrivals(bank, bank.name):
        if row.id in refs:
            found[row.id] = row.name
    for card in contacts_local.load_waiting(bank.name):
        key = contacts_local.card_hash(card["id"])
        if key in refs:
            found[key] = contacts_local.card_name(card)
    return found


def render(report: dict, names: dict[str, str] | None = None) -> str:
    if not report:
        return "No report yet: the arrival join has not run for this bank."
    lines = [f"arrival join, ran {report.get('ran_on')} — {'LIVE' if report.get('live') else 'reporting only (writes nothing)'}",
             f"first-name pages with a namesake in a directory: {report.get('holders_with_namesake')}"
             f" (of {report.get('first_name_pages')} one-word person pages); veto reads paid: {report.get('veto_reads')}",
             "reasons: " + ", ".join(f"{k} {v}" for k, v in (report.get("reasons") or {}).items())]
    for item in report.get("items") or []:
        mark = {"would_join": "WOULD JOIN", "join": "JOINED"}.get(item.get("decision"), "skip")
        lines.append("")
        lines.append(f"[{mark}] page {item['page']}: {item['reason']}")
        lines.append(f"  holder day {item.get('holder_day')} ({item.get('day_from') or 'none'}); arrival day {item.get('arrival_day')};"
                     f" gap {item.get('gap')}; directory stamps {item.get('fresh')}")
        lines.append(f"  conflict {item.get('conflict')}; veto {item.get('veto')}")
        for n in item.get("namesakes") or []:
            who = f" {names[n['ref']]}" if names and n["ref"] in names else ""
            lines.append(f"  - {n['role']:8} {n['kind']:10} {n['ref']} day {n.get('day')} ({n.get('precision')}) gap {n.get('gap')}"
                         f" waiting {n.get('waiting')} page {n.get('page')}{who}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the memory folder")
    parser.add_argument("--json", action="store_true", help="the report as JSON")
    parser.add_argument("--run", action="store_true", help="decide now (no engine) and write the report first")
    parser.add_argument("--names", action="store_true", help="print each arrival's name, to this terminal only")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(f"not a memory bank: {bank}", file=sys.stderr)
        return 2
    from api.services import arrival_join

    if args.run:
        asyncio.run(arrival_join.run_tail(bank, None, user_triggered=False, no_model=True, live=False))
    report = arrival_join.printable(bank.name)
    if args.json:
        print(arrival_join.dumps(report))
        return 0
    refs = {n["ref"] for i in report.get("items") or [] for n in i.get("namesakes") or [] if n.get("role") == "arrival"} \
        if args.names else set()
    print(render(report, _names(bank, refs) if refs else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
