"""Does a fact said about a part of a page land on that page, and never on a wrong one? (2026-11-25, G148/G98)

`described_landing_cases.json` is a labelled set of invented sentences: ``expect: land`` where the named page IS what the
fact is about, ``expect: left`` for the traps (a person told me, a tool used for the part, two pages in one sentence, an
assistant's words, a company, an ambiguous or archived page, a label the conversation said, a verb between the part and
the page, a part of another thing) and, marked ``semantic``, two the words alone cannot rule out ("the landlord of
<Project>"). Each case is its own scratch bank (the page list, one conversation, one held line with one located claim) and
is run through the real tending step (`described_landing.tend`: code gates, the label read, the sentence read, the landing)
with three judges:

* ``yes``: both reads rigged to always say yes — what the CODE alone lets through. The bar: no trap lands but a ``semantic``
  one (a fact that fails every code gate is left whatever the judge says);
* ``no``: both reads rigged to no — nothing lands;
* ``real``: the engine's main model on the Claude plan (`--engine plan`, haiku: no key is read, no word leaves but the
  invented sentences). Calls: two a pair that passes the gates.

    api/.venv/bin/python -m benchmarks.consolidation.described_landing --judges yes,no,real --engine plan --model haiku

Prints per case and judge ``landed`` / ``left`` against the expectation, then ``right`` (landed and should), ``wrong``
(landed and should not), ``missed`` (left and should have landed), and the number of model calls. Exit 1 when a
non-semantic trap landed under any judge."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
CASES = HERE / "described_landing_cases.json"
DAY, STAMP = "2026-11-20", "2026-11-20T10:00:00+00:00"
EPISODE = "ep_2026-11-20_001"


def load_cases(path: Path = CASES) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def claim_id(case: dict) -> str:
    from api.services.id_utils import sanitize_id

    return f"clm_{DAY}_{sanitize_id(case['id'])}"


def build_bank(root: Path, spec: dict, case: dict) -> Path:
    """One scratch bank: every page of the set, the case's conversation and its one held line with one located claim."""
    from api.services import evidence, markdown_parser, pending_store, predicates
    from api.services.claims import Claim, Evidence
    from api.services.id_utils import sanitize_id

    bank = root / "bank"
    for sub in ("entities", "episodes", "inbox"):
        (bank / sub).mkdir(parents=True)
    predicates.install_predicate_map(bank)
    for p in spec["pages"]:
        markdown_parser.write(bank / "entities" / f"{p['id']}.md",
                              {"id": p["id"], "name": p["name"], "type": p["type"], "status": p.get("status", "active"),
                               "aliases": p.get("aliases", []), **({"owner": True} if p.get("owner") else {}),
                               "source_episodes": []}, f"{p['name']} is something the person works on.\n")
    body = case["conversation"]
    markdown_parser.write(bank / "episodes" / f"{EPISODE}.md",
                          {"id": EPISODE, "processed": True, "source": "import", "origin": "chatgpt", "timestamp": STAMP},
                          body)
    text = evidence.source_text(bank, EPISODE) or ""
    c = case["claim"]
    hit = evidence.locate(text, c["quote"])
    assert hit is not None, case["id"]
    label = case["line"]
    obj = c["object"]
    claim = Claim(id=claim_id(case), text=f"{label} {c['label']} {obj}", subject=sanitize_id(label),
                  predicate=sanitize_id(c["label"]), object=obj if c.get("literal") else sanitize_id(obj),
                  object_kind="literal" if c.get("literal") else "node", valid_from=DAY, recorded_at=DAY,
                  source_episodes=[EPISODE], origin="chatgpt",
                  evidence=[Evidence(episode=EPISODE, start=hit[0], end=hit[1],
                                     kind=evidence.kind_for(EPISODE, text, hit[0]), hash=evidence.body_hash(text))])
    pending_store.save(bank, [pending_store.PendingEntity(
        name=label, type="concept", description="", source_episode=EPISODE, confidence=0.6, tags=[], history_entries=[],
        held_claims=[claim.to_dict()], summary=f"Said once: {label}.")])
    return bank


def rigged(answer: bool):
    """A judge that says the same to every question (``True``: part, for every numbered item)."""
    async def ask(system: str, prompt: str) -> object:
        n = len(re.findall(r"^Item \d+:", prompt, re.M))
        return {"claims": [{"n": i, "verdict": "part" if answer else "no"} for i in range(1, n + 1)]}

    async def part(*_a, **_k) -> bool:
        return answer

    return ask, part


async def run_case(spec: dict, case: dict, judge: str, real) -> dict:
    from api.services import described_landing, markdown_parser
    from api.services.claims import parse_claims

    with tempfile.TemporaryDirectory(prefix="described-landing-") as tmp:
        bank = build_bank(Path(tmp), spec, case)
        plan = described_landing.plan_bank(bank)
        calls = {"n": 0}
        if judge == "real":
            ask0, part0, _strong = real

            async def ask(system, prompt):
                calls["n"] += 1
                return await ask0(system, prompt)

            part = part0
        else:
            ask, part = rigged(judge == "yes")
        settings = real[2] if judge == "real" else None
        report = await described_landing.tend(bank, settings, ask, part_read=part, plan=plan)
        landed = False
        why = ",".join(sorted(plan.skipped)) or "-"
        for path in (bank / "entities").glob("*.md"):
            body = markdown_parser.parse(path).body
            if any(c.id == claim_id(case) for c in parse_claims(body)):
                landed = True
        return {"id": case["id"], "judge": judge, "expect": case["expect"], "landed": landed, "gates": bool(plan.items),
                "why": why, "semantic": bool(case.get("semantic")), "reads": report.read, "calls": calls["n"]}


def summarise(rows: list[dict]) -> dict:
    out = {}
    for judge in dict.fromkeys(r["judge"] for r in rows):
        mine = [r for r in rows if r["judge"] == judge]
        out[judge] = {
            "right": sum(1 for r in mine if r["landed"] and r["expect"] == "land"),
            "wrong": sum(1 for r in mine if r["landed"] and r["expect"] == "left"),
            "wrong_semantic": sum(1 for r in mine if r["landed"] and r["expect"] == "left" and r["semantic"]),
            "missed": sum(1 for r in mine if not r["landed"] and r["expect"] == "land"),
            "left_right": sum(1 for r in mine if not r["landed"] and r["expect"] == "left"),
            "model_calls": sum(r["calls"] for r in mine)}
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--judges", default="yes,no,real")
    p.add_argument("--engine", choices=("plan",), default="plan")
    p.add_argument("--model", default="haiku")
    p.add_argument("--only", default="")
    p.add_argument("--json", type=Path)
    a = p.parse_args(argv)
    os.environ.pop("ANTHROPIC_API_KEY", None)   # `claude -p` must bill the plan, never a key found in the environment
    spec = load_cases()
    cases = [c for c in spec["cases"] if a.only in c["id"]]
    judges = [j for j in a.judges.split(",") if j]
    home = Path(tempfile.mkdtemp(prefix="described-landing-home-"))
    from benchmarks.engine_parity import _leg_environment, settings_for

    rows: list[dict] = []
    with _leg_environment(home, home / "scratch"):
        real = None
        if "real" in judges:
            from api.services import full_name_join, part_landing, same_name_tend
            from benchmarks.consolidation.run import engine_model

            settings = settings_for("plan", home / "scratch", model=engine_model("plan", a.model),
                                    judge=engine_model("plan", a.model))
            strong = same_name_tend.main_tier(settings)

            async def ask(system: str, prompt: str) -> object:
                return await full_name_join.ask_main(strong, system, prompt)

            async def part(name, summary, episodes, whole, body, st, *, memory_path=None, **_k):
                return await part_landing.confirms(name, summary, episodes, whole, body, st, memory_path=memory_path)

            real = (ask, part, strong)
        for judge in judges:
            for case in cases:
                row = asyncio.run(run_case(spec, case, judge, real))
                rows.append(row)
                state = "landed" if row["landed"] else "left  "
                ok = "ok   " if (row["landed"]) == (row["expect"] == "land") else "WRONG" if row["landed"] else "missed"
                print(f"{judge:5} {row['id']:26} {state} {ok} gates_passed={row['gates']!s:5} why_left={row['why']}", flush=True)
    summary = summarise(rows)
    print(json.dumps(summary, indent=1))
    if a.json:
        a.json.write_text(json.dumps({"rows": rows, "summary": summary}, indent=1))
    return 1 if any(r["landed"] and r["expect"] == "left" and not r["semantic"] for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
