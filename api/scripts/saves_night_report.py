"""A night's saves, one row each, for the person who reads the first nights one save at a time (ruling 80, G246).

    api/.venv/bin/python -m api.scripts.saves_night_report --bank <path> [--day YYYY-MM-DD]

Prints one JSON object: for every save that stood in tonight's reading — released from the pile that local day
(``turn_released_on``), written waiting that day, or talked about that day — its **ids and enums only, never a title, a
link or a word**: the episode id, its origin and folder, where it stands now (``history_index.save_state``), how it
reached the queue (``pile`` released that day or ``single``), whether he talked about it (the ``read_asked`` reason),
whether a model read it and which engine stamped it, the pages whose sources name it (ids, with whether the page is one
only saves made) and the claims those pages hold from it **by observer kind** (``owner`` = on the owner's page, ``person``
= his own words, ``external`` = the post's author, ``agent`` = Cicada's own reading), plus the questions open about those
pages. Counts alone do not decide whether the day's number is right (the 2026-10-20 sweep wrote eight wrong settles from
counts); the ids let the reader open each save and its pages. A totals block closes it. Frontmatter and claim fences
through the cached scan; it writes nothing. Exit 0 done, 2 not a bank.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path


def _observer_kind(observer: str, on_owner_page: bool) -> str:
    observer = str(observer or "")
    if observer.startswith("external:"):
        return "external"
    if observer in ("user", "person", "owner"):
        return "person"
    if observer in ("agent", "sleep", ""):
        return "agent"
    return "other"


def _day(raw) -> str | None:
    from api.services import episode_ids

    d = episode_ids.local_day(raw)
    return d.isoformat() if d else None


def build(bank: Path, day: str) -> dict:
    from api.services import bank_index, claims as claims_module, history_index, markdown_parser

    episodes = bank_index.files(bank, "episodes")
    in_night: dict[str, dict] = {}
    for f in episodes:
        fm = f.frontmatter or {}
        state = history_index.save_state(fm)
        if state is None or state == "record":
            continue
        released = fm.get(history_index.TURN_KEY) == day
        # A stamp is UTC; the night is the person's local day, so a save made after local midnight is that day's.
        saved_that_day = _day(fm.get("received_at") or fm.get("timestamp")) == day
        talked = _day((fm.get(history_index.WOKEN_KEY) or {}).get("at")) == day
        if not (released or (saved_that_day and state != "pile") or talked):   # a pile save not released has no night
            continue
        ep_id = str(fm.get("id") or f.stem)
        in_night[ep_id] = {
            "episode": ep_id, "origin": str(fm.get("origin") or fm.get("source") or ""), "folder": str(fm.get("folder") or ""),
            "state": state, "reached": "pile" if released else "single", "talked_about": bool(fm.get(history_index.WOKEN_KEY)),
            "talked_reason": str((fm.get(history_index.WOKEN_KEY) or {}).get("why") or "") or None,
            "has_person_words": any(fm.get(k) for k in history_index.PERSON_KEYS),
            "processed_by": fm.get("processed_by"), "pages": [], "claims_by_observer": {}, "questions_open": 0,
        }
    pages_of: dict[str, list[str]] = {}
    owner_pages: set[str] = set()
    claims_from: dict[str, Counter] = {i: Counter() for i in in_night}
    for path in sorted((bank / "entities").glob("*.md")):
        parsed = markdown_parser.parse(path)
        fm = parsed.frontmatter or {}
        names = {str(e).split("#", 1)[0] for e in fm.get("source_episodes") or []}
        hit = [i for i in in_night if i in names]
        owner = bool(fm.get("owner"))
        if owner:
            owner_pages.add(path.stem)
        for c in claims_module.parse_claims(parsed.body):
            eps = {str(e).split("#", 1)[0] for e in (c.source_episodes or [])} | {
                str(e.episode) for e in (getattr(c, "evidence", None) or []) if getattr(e, "episode", None)}
            for ep in eps & set(in_night):
                claims_from[ep][("owner:" if owner else "") + _observer_kind(c.observer, owner)] += 1
                if path.stem not in pages_of.setdefault(ep, []):
                    pages_of[ep].append(path.stem)
        for ep in hit:
            if path.stem not in pages_of.setdefault(ep, []):
                pages_of[ep].append(path.stem)
    inbox = [f.frontmatter or {} for f in bank_index.files(bank, "inbox")]
    for ep_id, row in in_night.items():
        row["pages"] = sorted(pages_of.get(ep_id, []))
        row["claims_by_observer"] = dict(sorted(claims_from[ep_id].items()))
        mine = set(row["pages"])
        row["questions_open"] = sum(1 for q in inbox if str(q.get("status") or "open") == "open"
                                    and mine & {str(x) for x in (q.get("entities") or q.get("entity_ids") or [])})
    rows = sorted(in_night.values(), key=lambda r: r["episode"])
    totals = {
        "saves": len(rows), "by_reach": dict(Counter(r["reached"] for r in rows)),
        "by_state": dict(Counter(r["state"] for r in rows)),
        "by_origin": dict(Counter(r["origin"] for r in rows)),
        "talked_about": sum(1 for r in rows if r["talked_about"]),
        "on_the_owners_page": sum(n for r in rows for k, n in r["claims_by_observer"].items() if k.startswith("owner:")),
        "pages": len({p for r in rows for p in r["pages"]}),
        "questions_open": sum(r["questions_open"] for r in rows),
    }
    return {"day": day, "per_day": history_index.SAVES_PER_DAY, "totals": totals, "saves": rows}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="saves_night_report", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds episodes/)")
    parser.add_argument("--day", default=None, help="the local day, YYYY-MM-DD (default: today)")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "episodes").is_dir():
        print(json.dumps({"error": "not a bank: no episodes/ directory"}))
        return 2
    print(json.dumps(build(bank, args.day or date.today().isoformat()), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
