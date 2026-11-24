"""Replay Sleep's join of a held full name (`api/services/full_name_join.py`, ruling 74b) over copies of stored banks.

A benchmark leg keeps its scratch bank. Many of them hold the question "Is <Full Name> the same as <Short>?" pending (a
full name said once, held on a line; its short name has a page). This copies each given bank (the original is never
opened for writing), runs the product's own step on the copy and says what it did:

* ``--dry``: the engine-free guards only, no model: which question is of the shape and, when not, why not.
* default: the guards and the two reads with the main model on the Claude plan (``--engine plan``, the default; ``key``
  spends money and reads the key file), then, with ``--apply``, the join itself through `inbox_tend.apply` on the copy.

    api/.venv/bin/python -m benchmarks.consolidation.full_name_replay --dry --out /tmp/replay BANK [BANK ...]
    api/.venv/bin/python -m benchmarks.consolidation.full_name_replay --apply --out /tmp/replay BANK [BANK ...]

``BANK`` is a leg folder (``<out>/<person>``, holding ``bank/``) or a bank folder. One line of JSON per question, and a
summary. Banks are invented people only (the benchmark's); nothing here reads the owner's memory.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def bank_of(path: Path) -> Path:
    return path / "bank" if (path / "bank").is_dir() else path


def label_of(path: Path) -> str:
    parts = [p for p in path.resolve().parts[-5:] if p not in ("bank", "bench")]
    return "-".join(parts[-3:])


def copy_bank(src: Path, dst: Path) -> Path:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=True)
    return dst


def counting(ask, tally: dict):
    async def judge(system: str, prompt: str):
        tally["calls"] += 1
        return await ask(system, prompt)

    return judge


async def replay_one(bank: Path, judge, *, dry: bool, apply: bool, settings) -> list[dict]:
    from api.services import full_name_join as fnj, markdown_parser, pending_store

    rows = []
    for path, fm in fnj.candidates(bank):
        row = {"item": path.stem, "name": fm.get("entity_name"), "page": fm.get("merge_target_hint")}
        case, why = fnj.guards(bank, path, fm)
        if case is None:
            row.update(outcome="skip", why=why)
            rows.append(row)
            continue
        row["turns"] = [t.text for t in case.turns]
        if dry:
            row.update(outcome="shape")
            rows.append(row)
            continue
        from api.services import same_name_tend

        result = await fnj.assess(bank, path, fm, judge, speaker=same_name_tend._speaker(bank))
        row.update(outcome=result.outcome, reads=result.reads)
        if result.decision is not None:
            row["reason"] = result.decision.reason
            if apply:
                from api.services import inbox_tend

                d = result.decision
                d.fingerprint = path.read_bytes()
                row["applied"] = await inbox_tend.apply(bank, settings, d)
                if row["applied"]:
                    page = markdown_parser.parse(bank / "entities" / f"{case.page_id}.md")
                    row["aliases"] = page.frontmatter.get("aliases")
                    row["held_line_left"] = any(ln.name == case.full for ln in pending_store.load(bank))
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("banks", nargs="+", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--dry", action="store_true", help="the engine-free guards only; no model")
    p.add_argument("--apply", action="store_true", help="make the join on the copy")
    p.add_argument("--engine", choices=("plan", "key"), default="plan")
    p.add_argument("--model", default="sonnet", help="the main model's tier")
    p.add_argument("--key-file", type=Path, default=Path("~/.cicada/secrets.env"))
    p.add_argument("--keep", action="store_true", help="keep every copy (default: only those that joined)")
    a = p.parse_args(argv)
    from benchmarks.engine_parity import _leg_environment, settings_for

    if a.engine == "key" and not a.dry:
        from benchmarks.consolidation.same_name_battery import key_from

        os.environ["ANTHROPIC_API_KEY"] = key_from(a.key_file)
    a.out.mkdir(parents=True, exist_ok=True)
    summary: dict[str, int] = {}
    tally = {"calls": 0}
    for src in a.banks:
        label = label_of(src)
        work = a.out / label
        bank = copy_bank(bank_of(src).resolve(), work / "bank")
        home = work / "home"
        home.mkdir(parents=True, exist_ok=True)
        with _leg_environment(home, bank):
            from api.services import entity_resolver, same_name_tend

            from benchmarks.consolidation.run import engine_model

            settings = settings_for("plan" if a.engine == "plan" else "key", bank, model=engine_model(a.engine, a.model),
                                    judge=engine_model(a.engine, a.model))
            strong = same_name_tend.main_tier(settings)

            async def ask(system: str, prompt: str, strong=strong):
                return await entity_resolver._same_name_ask(strong, system, prompt)

            rows = asyncio.run(replay_one(bank, counting(ask, tally), dry=a.dry, apply=a.apply, settings=settings))
        for row in rows:
            row["bank"] = label
            key = row["outcome"] + (f":{row['why']}" if row["outcome"] == "skip" else "")
            summary[key] = summary.get(key, 0) + 1
            print(json.dumps(row, ensure_ascii=False))
        if not a.keep and not any(r.get("applied") for r in rows):
            shutil.rmtree(work, ignore_errors=True)
    print(json.dumps({"summary": dict(sorted(summary.items())), "model_calls": tally["calls"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
