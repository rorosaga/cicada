"""Is an unnamed person asked their name only on the second conversation? Real Sleeps on a scratch bank (2026-11-24).

`name_ask_e2e.json`: night one reads three conversations that each mention someone by a description (a swimming teacher in
Spanish, a Portuguese guitar teacher, "my partner") and one that mentions nobody; night two reads two more that bring the
guitar teacher and the partner up again. After each night the bank's open name questions are read: none after night one,
exactly one each for the two who came up again after night two, none for the swimming teacher. The plan, Sonnet main and
Haiku judge; no key.

    api/.venv/bin/python -m benchmarks.consolidation.name_ask_e2e --out ~/cicada-bench/fable/askname/e2e-1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

import yaml

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1]))


def name_questions(bank: Path) -> list[dict]:
    out = []
    for path in sorted((bank / "inbox").glob("inbox-*.md")):
        front = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1]) or {}
        if front.get("asks") == "name":
            out.append({"file": path.name, "entity": front.get("entity_id"), "question": front.get("question"),
                        "status": front.get("status"), "source_episode": front.get("source_episode")})
    return out


def pages_by_name(bank: Path) -> dict[str, dict]:
    from api.services import markdown_parser

    found = {}
    for path in sorted((bank / "entities").glob("*.md")):
        fm = markdown_parser.parse(path).frontmatter or {}
        found[path.stem] = {"name": fm.get("name"), "unnamed": bool(fm.get("unnamed")), "episodes": fm.get("source_episodes")}
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fixture", type=Path, default=HERE / "name_ask_e2e.json")
    ap.add_argument("--clock", type=date.fromisoformat, default=date(2026, 11, 24))
    a = ap.parse_args()
    os.environ.pop("ANTHROPIC_API_KEY", None)
    from benchmarks.consolidation import run as bench
    from benchmarks.consolidation.findability import _fetch_model, _settings
    from benchmarks.engine_parity import _leg_environment, _refuse_real_paths

    _refuse_real_paths(a.out)
    bank, home = a.out / "bank", a.out / "home"
    home.mkdir(parents=True, exist_ok=True)
    _fetch_model(home)
    data = json.loads(a.fixture.read_text(encoding="utf-8"))
    nights = {}
    with _leg_environment(home, bank):
        from api.services import sleep_cycle

        bench.init_bank(bank, data["owner"])
        settings = _settings(bank, "sonnet", "haiku")
        for phase in sorted({c["phase"] for c in data["conversations"]}):
            bench.stage(bank, [c for c in data["conversations"] if c["phase"] == phase], a.clock, f"Bench intake, night {phase}")
            asyncio.run(sleep_cycle.run(settings, f"sleep_name_{phase}", user_triggered=True, drain=True))
            state = sleep_cycle.get_sleep_state()
            nights[phase] = {"questions": name_questions(bank), "error": state.error}
    pages = pages_by_name(bank)
    expect = data["expect"]
    after1, after2 = nights[1]["questions"], nights[2]["questions"]

    def about(questions, words):
        return [q for q in questions if any(w in _fold(f"{q['entity']} {q['question']} {(pages.get(q['entity']) or {}).get('name')}") for w in words)]

    def _fold(t):
        return " ".join(str(t).lower().split())

    checks = {"night 1 asks nothing": not after1,
              **{f"night 2 asks about the {w} once": len(about(after2, [w])) == 1 for w in expect["second"]},
              **{f"never asks about the {w}": not about(after2, [w]) for w in expect["first_only"][:1]}}
    result = {"ok": all(checks.values()), "checks": checks, "night1": nights[1], "night2": nights[2], "pages": pages}
    (a.out / "e2e.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({"ok": result["ok"], "checks": checks}, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
