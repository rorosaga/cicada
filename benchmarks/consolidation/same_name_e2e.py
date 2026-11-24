"""One same-name story through the real Sleep on a scratch bank (2026-11-24).

`same_name_stories.py` replays the judge on a simulated bank, and twice that hid a defect only the real path has: the
stager, Stage 1's own descriptions, `sleep_cycle.run`, the store, the tail review and git. This runs a small multi-phase
story (each phase is one night) through `run.run_leg` on a fresh bank and says what the bank holds under each first name.
A fixture is a benchmark fixture (`conversations` with a `phase`, an empty `gold`) plus ``expect``: the first names that
must end as one person page (``one``) and as two (``two``). About $0.20 a run on a Claude key, Sonnet with Haiku as judge; ``--engine plan`` runs it on the signed-in Claude plan
instead (no key is read).

    api/.venv/bin/python -m benchmarks.consolidation.same_name_e2e --out /tmp/e2e-1
    api/.venv/bin/python -m benchmarks.consolidation.same_name_e2e --engine plan --fixture full_name_e2e_true.json --out /tmp/e2e-2

``expect`` may also say ``joined`` (a page that must carry an alias Sleep joined to it: no page of the alias's own, no
held line, no open question, one settled record by rule ``full_name_one``) and ``not_joined`` (the page must not carry it,
and nothing was settled by that rule): the full-name join (`api/services/full_name_join.py`, ruling 74b).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import yaml

JOIN = Path(__file__).with_name("same_name_e2e_join.json")


def people_named(bank: Path) -> dict[str, list[str]]:
    """First name (lower) → the ids of the person pages titled so."""
    found: dict[str, list[str]] = {}
    for path in sorted((bank / "entities").glob("*.md"), key=lambda p: p.stem):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        try:
            front = yaml.safe_load(text.split("---", 2)[1]) or {}
        except yaml.YAMLError:
            continue
        if str(front.get("type") or "").lower() == "person" and front.get("name"):
            found.setdefault(str(front["name"]).strip().lower(), []).append(path.stem)
    return found


def _pages(bank: Path) -> list[dict]:
    out = []
    for path in sorted((bank / "entities").glob("*.md"), key=lambda p: p.stem):
        text = path.read_text(encoding="utf-8")
        if text.startswith("---"):
            try:
                front = yaml.safe_load(text.split("---", 2)[1]) or {}
            except yaml.YAMLError:
                continue
            out.append({"id": path.stem, **front})
    return out


def _fold(text) -> str:
    return " ".join(str(text or "").lower().split())


def joined_row(bank: Path, want: dict, *, joined: bool) -> dict:
    """The full-name join of one alias onto one page, against what the bank holds."""
    alias, page = _fold(want["alias"]), _fold(want["page"])
    pages = _pages(bank)
    carries = any(_fold(p.get("name")) == page and alias in {_fold(a) for a in p.get("aliases") or []} for p in pages)
    own_page = any(_fold(p.get("name")) == alias for p in pages)
    held = False
    store = bank / "pending_entities.jsonl"
    if store.exists():
        held = any(_fold((json.loads(raw) if raw.strip() else {}).get("name")) == alias for raw in store.read_text(encoding="utf-8").splitlines())
    asked, settled = [], []
    for f in sorted((bank / "inbox").glob("inbox-*.md")):
        front = yaml.safe_load(f.read_text(encoding="utf-8").split("---", 2)[1]) or {}
        if _fold(front.get("entity_name")) == alias:
            asked.append(f.stem)
    for f in sorted((bank / "inbox" / "settled").glob("inbox-*.md")) if (bank / "inbox" / "settled").is_dir() else []:
        front = yaml.safe_load(f.read_text(encoding="utf-8").split("---", 2)[1]) or {}
        if _fold(front.get("entity_name")) == alias and (front.get("settled") or {}).get("rule") == "full_name_one":
            settled.append(f.stem)
    if joined:
        ok = carries and not own_page and not held and not asked and len(settled) == 1
    else:
        ok = not carries and not own_page_alias_joined(pages, alias, page) and not settled
    return {"ok": ok, "alias_on_page": carries, "own_page": own_page, "held": held, "open_questions": asked, "settled": settled}


def own_page_alias_joined(pages: list[dict], alias: str, page: str) -> bool:
    return any(alias in {_fold(a) for a in p.get("aliases") or []} and _fold(p.get("name")) != page for p in pages)


def check(bank: Path, expect: dict) -> dict:
    """What the bank holds against the fixture's ``expect``: per name the pages, and whether the count is right."""
    named = people_named(bank)
    rows = {name: {"pages": named.get(name, []), "ok": len(named.get(name, [])) == 1} for name in expect.get("one", [])}
    rows.update({name: {"pages": named.get(name, []), "ok": len(named.get(name, [])) == 2} for name in expect.get("two", [])})
    for want in expect.get("joined", []):
        rows[f"joined:{want['alias']}"] = joined_row(bank, want, joined=True)
    for want in expect.get("not_joined", []):
        rows[f"not_joined:{want['alias']}"] = joined_row(bank, want, joined=False)
    store = bank / "_same_name_doubts.yaml"
    held = (yaml.safe_load(store.read_text(encoding="utf-8")) or {}) if store.exists() else {}
    return {"names": rows, "ok": all(r["ok"] for r in rows.values()),
            "in_doubt": [[p.get("a"), p.get("b")] for p in held.get("pairs") or []],
            "joined_by_sleep": [[p.get("a"), p.get("b")] for p in held.get("joined") or []]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--fixture", type=Path, default=JOIN)
    parser.add_argument("--out", type=Path, required=True, help="a new folder: the scratch bank and home are made in it")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--judge", default="haiku")
    parser.add_argument("--clock", type=date.fromisoformat, default=date(2026, 11, 23))
    parser.add_argument("--key-file", type=Path, default=Path("~/.cicada/secrets.env"))
    parser.add_argument("--engine", choices=("key", "plan"), default="key", help="key: the Claude key in --key-file (default); plan: the signed-in Claude plan, no key read")
    a = parser.parse_args()
    from benchmarks.consolidation import run as bench
    from benchmarks.consolidation.same_name_battery import key_from, spend

    if a.engine == "key":
        os.environ["ANTHROPIC_API_KEY"] = key_from(a.key_file)   # inherited by the engine's call, never printed
    bench.PEOPLE["e2e"] = a.fixture
    a.out.mkdir(parents=True, exist_ok=True)
    from benchmarks.consolidation import engines

    with engines.tally() as counted:
        snap = bench.run_leg(a.model, a.out, clock=a.clock, engine=a.engine, judge=a.judge, person="e2e")
    engines.dump(counted, a.out / "tally.json")   # replies per stage label: how many a parser could not use (2026-11-24)
    expect = json.loads(a.fixture.read_text(encoding="utf-8")).get("expect") or {}
    result = check(a.out / "bank", expect)
    result.update(questions=snap.get("questions"), spend=spend(a.out / "home") if a.engine == "key" else {"engine": "plan"},
                  replies={"calls": counted.total(), "unusable": counted.unusable(), "by_stage": counted.as_dict()["calls"]})
    (a.out / "e2e.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
