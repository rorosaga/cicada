"""One same-name story through the real Sleep on a scratch bank (2026-11-24).

`same_name_stories.py` replays the judge on a simulated bank, and twice that hid a defect only the real path has: the
stager, Stage 1's own descriptions, `sleep_cycle.run`, the store, the tail review and git. This runs a small multi-phase
story (each phase is one night) through `run.run_leg` on a fresh bank and says what the bank holds under each first name.
A fixture is a benchmark fixture (`conversations` with a `phase`, an empty `gold`) plus ``expect``: the first names that
must end as one person page (``one``) and as two (``two``). About $0.20 a run on a Claude key, Sonnet with Haiku as judge.

    api/.venv/bin/python -m benchmarks.consolidation.same_name_e2e --out /tmp/e2e-1
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


def check(bank: Path, expect: dict) -> dict:
    """What the bank holds against the fixture's ``expect``: per name the pages, and whether the count is right."""
    named = people_named(bank)
    rows = {name: {"pages": named.get(name, []), "ok": len(named.get(name, [])) == 1} for name in expect.get("one", [])}
    rows.update({name: {"pages": named.get(name, []), "ok": len(named.get(name, [])) == 2} for name in expect.get("two", [])})
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
    a = parser.parse_args()
    from benchmarks.consolidation import run as bench
    from benchmarks.consolidation.same_name_battery import key_from, spend

    os.environ["ANTHROPIC_API_KEY"] = key_from(a.key_file)   # inherited by the engine's call, never printed
    bench.PEOPLE["e2e"] = a.fixture
    a.out.mkdir(parents=True, exist_ok=True)
    snap = bench.run_leg(a.model, a.out, clock=a.clock, engine="key", judge=a.judge, person="e2e")
    expect = json.loads(a.fixture.read_text(encoding="utf-8")).get("expect") or {}
    result = check(a.out / "bank", expect)
    result.update(questions=snap.get("questions"), spend=spend(a.out / "home"))
    (a.out / "e2e.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
