"""Replay battery for Sleep's tending of two pages that go by one name (`api/services/alias_collisions.py`, G21, 2026-11-24).

Why: a page that lists another page's title among its aliases is either one thing held twice (the right outcome is ONE
question) or two things (the right outcome is that the alias leaves the page that lists it). Removing a name from a page
that is the same thing is the error this step must never make: the bar is zero wrong removals; a missed removal only
leaves the pair held as it is today. This builds, per case of `alias_collision_cases.json` (invented names), a small
scratch bank with the two pages and runs the product's own `alias_collisions.assess` ``--repeats`` times with the real
model: the two reads. Nothing is written by a read; the bank is thrown away.

    api/.venv/bin/python -m benchmarks.consolidation.alias_collision_battery --engine plan --model haiku --repeats 2

A case is ``same`` (one thing: a removal is a WRONG REMOVAL) or ``two`` (a part, a product, an unrelated thing: a question
asked is a needless ASK, a removal is right). Held (`alias_doubt`) is always allowed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

CASES = Path(__file__).with_name("alias_collision_cases.json")


def load_cases(path: Path = CASES) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(bank: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True)


def build_bank(root: Path, case: dict) -> Path:
    from api.services import bank_index, markdown_parser, predicates

    bank = root / "bank"
    for sub in ("entities", "episodes", "inbox"):
        (bank / sub).mkdir(parents=True, exist_ok=True)
    predicates.install_predicate_map(bank)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "bench@example.com")
    _git(bank, "config", "user.name", "bench")
    for side in ("a", "b"):
        page = case[side]
        listed = page.get("aliases") or []
        if listed and case["listed"] not in ("both", side):
            listed = []
        meta = {"name": page["name"], "type": page["type"], "status": "active", "confidence": 0.8, "created": "2026-10-01",
                "last_referenced": "2026-11-14", "source_episodes": [], "related": [], "version": 1,
                **({"aliases": listed} if listed else {})}
        markdown_parser.write(bank / "entities" / f"{page['id']}.md", meta, f"## Summary\n{page['body']}\n")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "case")
    bank_index.invalidate(bank)
    return bank


async def run_case(case: dict, repeats: int, judge) -> dict:
    from api.services import alias_collisions

    with tempfile.TemporaryDirectory(prefix="alias-collision-case-") as tmp:
        bank = build_bank(Path(tmp), case)
        found = [p for p in alias_collisions.pairs(bank) if not p.skip]
        row = {"id": case["id"], "kind": case["kind"], "runs": repeats, "outcomes": Counter(), "calls": 0,
               "wrong_removals": 0, "needless_asks": 0, "right": 0}
        if len(found) != 1:
            row["outcomes"]["no_pair"] = repeats
            return row
        for _ in range(repeats):
            plan = await alias_collisions.assess(bank, found[0], judge)
            word = {"alias_apart": "removed", "ask": "asked", "alias_doubt": "held"}.get(plan.rule, plan.why or plan.rule)
            row["outcomes"][word] += 1
            row["calls"] += plan.reads
        done = row["outcomes"]
        if case["kind"] == "same":
            row["wrong_removals"] = done.get("removed", 0)
            row["right"] = done.get("asked", 0)
        else:
            row["needless_asks"] = done.get("asked", 0)
            row["right"] = done.get("removed", 0)
        return row


def report(rows: list[dict]) -> str:
    out = []
    for r in rows:
        shown = ", ".join(f"{k} {v}" for k, v in sorted(r["outcomes"].items()))
        out.append(f"{r['kind']:4} {r['id']:26} right {r['right']:>2}/{r['runs']}  [{shown}]  calls {r['calls']}")
    out.append(f"WRONG REMOVALS (one thing, alias removed): {sum(r['wrong_removals'] for r in rows)}/"
               f"{sum(r['runs'] for r in rows if r['kind'] == 'same')}   "
               f"NEEDLESS ASKS (two things, asked): {sum(r['needless_asks'] for r in rows)}/"
               f"{sum(r['runs'] for r in rows if r['kind'] == 'two')}   "
               f"RIGHT removals {sum(r['right'] for r in rows if r['kind'] == 'two')}/"
               f"{sum(r['runs'] for r in rows if r['kind'] == 'two')}   "
               f"RIGHT asks {sum(r['right'] for r in rows if r['kind'] == 'same')}/"
               f"{sum(r['runs'] for r in rows if r['kind'] == 'same')}   "
               f"model calls {sum(r['calls'] for r in rows)}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--cases", type=Path, default=CASES)
    p.add_argument("--only", default="", help="substring of case ids")
    p.add_argument("--engine", choices=("plan", "key"), default="plan")
    p.add_argument("--model", default="haiku", help="the main model's tier")
    p.add_argument("--key-file", type=Path, default=Path("~/.cicada/secrets.env"))
    p.add_argument("--json", type=Path, help="write the rows here")
    a = p.parse_args(argv)
    from benchmarks.engine_parity import _leg_environment, settings_for

    if a.engine == "key":
        from benchmarks.consolidation.same_name_battery import key_from

        os.environ["ANTHROPIC_API_KEY"] = key_from(a.key_file)
    else:
        os.environ.pop("ANTHROPIC_API_KEY", None)   # `claude -p` must bill the plan, never a key found in the environment
    cases = [c for c in load_cases(a.cases) if a.only in c["id"]]
    root = Path(tempfile.mkdtemp(prefix="alias-collision-battery-"))
    home, scratch = root / "home", root / "scratch"
    home.mkdir()
    scratch.mkdir()
    rows = []
    from benchmarks.consolidation import engines

    with _leg_environment(home, scratch), engines.tally() as counted:
        from api.services import full_name_join, same_name_tend
        from benchmarks.consolidation.run import engine_model

        settings = settings_for("plan" if a.engine == "plan" else "key", scratch, model=engine_model(a.engine, a.model),
                                judge=engine_model(a.engine, a.model))
        strong = same_name_tend.main_tier(settings)

        async def judge(system: str, prompt: str) -> object:
            return await full_name_join.ask_main(strong, system, prompt)

        for case in cases:
            rows.append(asyncio.run(run_case(case, a.repeats, judge)))
            print(report(rows[-1:]).splitlines()[0], flush=True)
    print(report(rows))
    print("engine replies:\n" + counted.report())
    if a.json:
        a.json.write_text(json.dumps([{**r, "outcomes": dict(r["outcomes"])} for r in rows], indent=1, ensure_ascii=False))
    return 0 if not any(r["wrong_removals"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
