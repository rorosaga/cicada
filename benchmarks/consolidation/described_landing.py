"""Does a fact said about a thing nobody named land on the page the conversation says it is about, and never on a wrong one?
(2026-11-25, G148/G98)

`described_landing_cases.json` is a labelled set of invented conversations. Each case is its own scratch bank (the page list,
one conversation, one held line with one or several located claims) and each claim carries ``expect``: ``land`` where the
conversation says the fact is about a page it names (in the claim's own sentence, or a turn or two earlier), ``left`` for the
rest. A ``left`` case says who must refuse it: ``by: code`` (the code before the read: an assistant's words, a company, an
owner's, an archived or ambiguous page, a tool or a concept page, a label the conversation said, no page named) or ``by: reader`` (the engine's main
model: a fact about neither of two projects, about the person, a person named nearby, a project used with the page, a relation noun
such as "the maintainer of <Page>", a topic switch). Each case is run through the real tending step
(`described_landing.tend`: code gates, two reads, the landing) with these judges:

* ``yes``: the reader rigged to always name the SAME candidate, the first by name, and to copy the claim's own turn — what the
  CODE conditions alone let through. ``yes-last`` does the same with the last by name. The bar for these is only on the cases
  the code must refuse (``by: code``): none may land. What lands among the ``by: reader`` traps is the honest size of what rests
  on the reader;
* ``no``: the reader rigged to always say none — nothing lands;
* ``real``: the engine's main model on the Claude plan (`--engine plan`, haiku: no key is read, no word leaves but the
  invented sentences). Two calls a group of claims said in one conversation.

    api/.venv/bin/python -m benchmarks.consolidation.described_landing --judges yes,yes-last,no,real --engine plan --model haiku

Prints per claim and judge ``landed`` / ``left`` against the expectation, then ``right`` (landed and should), ``wrong``
(landed and should not; split into those the code must refuse and those the reader must), ``missed`` (left and should have
landed), and the number of model calls. ``--group-size 1`` reads each claim on its own (to compare with a call a group).
Exit 1 when a case the code must refuse landed under any judge."""
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


def claim_id(case: dict, index: int = 0) -> str:
    from api.services.id_utils import sanitize_id

    return f"clm_{DAY}_{sanitize_id(case['id'])}_{index}"


def build_bank(root: Path, spec: dict, case: dict) -> Path:
    """One scratch bank: every page of the set, the case's conversation and its one held line with its located claims."""
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
    label = case["line"]
    held = []
    for k, c in enumerate(case["claims"]):
        hit = evidence.locate(text, c["quote"])
        assert hit is not None, (case["id"], k)
        obj = c["object"]
        claim = Claim(id=claim_id(case, k), text=f"{label} {c['label']} {obj}", subject=sanitize_id(label),
                      predicate=sanitize_id(c["label"]), object=obj if c.get("literal") else sanitize_id(obj),
                      object_kind="literal" if c.get("literal") else "node", valid_from=DAY, recorded_at=DAY,
                      source_episodes=[EPISODE], origin="chatgpt",
                      evidence=[Evidence(episode=EPISODE, start=hit[0], end=hit[1],
                                         kind=evidence.kind_for(EPISODE, text, hit[0]), hash=evidence.body_hash(text))])
        held.append(claim.to_dict())
    pending_store.save(bank, [pending_store.PendingEntity(
        name=label, type="concept", description="", source_episode=EPISODE, confidence=0.6, tags=[], history_entries=[],
        held_claims=held, summary=f"Said once: {label}.")])
    return bank


_FACT = re.compile(r"^(\d+)\. .*\(said in turn \[(\d+)\]\)\s*$", re.M)
_CAND = re.compile(r"^([A-F])\. (.+?) — ", re.M)


def rigged(mode: str):
    """A judge that answers every question the same way. ``none``: no candidate for every fact. ``first`` / ``last``: always
    the candidate that sorts first / last by name (whatever letter it has in this reading), copying the turn the fact was said in
    — the worst a reader that never looks can do once the code conditions let a claim through."""
    async def ask(system: str, prompt: str) -> object:
        facts = _FACT.findall(prompt)
        if mode == "none":
            return {"claims": [{"n": int(n), "page": "none"} for n, _t in facts]}
        cands = sorted(_CAND.findall(prompt), key=lambda c: c[1].lower())
        letter = (cands[0] if mode == "first" else cands[-1])[0] if cands else "none"
        rows = []
        for n, turn in facts:
            m = re.search(rf"^\[{turn}\] [^:\n]+: (.*?)(?=^\[\d+\] |^\.\.\.$|\n\n|\Z)", prompt, re.M | re.S)
            rows.append({"n": int(n), "page": letter, "scope": "whole", "sentence": " ".join((m.group(1) if m else "").split())[:200]})
        return {"claims": rows}

    return ask


async def run_case(spec: dict, case: dict, judge: str, real) -> list[dict]:
    from api.services import described_landing, markdown_parser
    from api.services.claims import parse_claims

    with tempfile.TemporaryDirectory(prefix="described-landing-") as tmp:
        bank = build_bank(Path(tmp), spec, case)
        plan = described_landing.plan_bank(bank)
        calls = {"n": 0}
        if judge == "real":
            ask0, strong = real

            async def ask(system, prompt):
                calls["n"] += 1
                return await ask0(system, prompt)

            settings = strong
        else:
            inner = rigged({"yes": "first", "yes-last": "last", "no": "none"}[judge])

            async def ask(system, prompt):
                calls["n"] += 1
                return await inner(system, prompt)

            settings = None
        await described_landing.tend(bank, settings, ask, plan=plan)
        landed_on: dict[str, str] = {}
        for path in (bank / "entities").glob("*.md"):
            for c in parse_claims(markdown_parser.parse(path).body):
                landed_on[c.id] = path.stem
        rows = []
        for k, c in enumerate(case["claims"]):
            got = landed_on.get(claim_id(case, k))
            rows.append({"id": f"{case['id']}#{k}", "judge": judge, "expect": c["expect"], "landed": got is not None,
                         "page": got or "", "by": case.get("by", ""), "gates": bool(plan.groups), "multi": len(case["claims"]) > 1,
                         "calls": calls["n"] if k == 0 else 0, "why": ",".join(sorted(plan.skipped)) or "-"})
        return rows


def summarise(rows: list[dict]) -> dict:
    out = {}
    for judge in dict.fromkeys(r["judge"] for r in rows):
        mine = [r for r in rows if r["judge"] == judge]
        out[judge] = {
            "claims": len(mine),
            "right": sum(1 for r in mine if r["landed"] and r["expect"] == "land"),
            "wrong": sum(1 for r in mine if r["landed"] and r["expect"] == "left"),
            "wrong_code_must_refuse": sum(1 for r in mine if r["landed"] and r["expect"] == "left" and r["by"] == "code"),
            "wrong_reader_must_refuse": sum(1 for r in mine if r["landed"] and r["expect"] == "left" and r["by"] == "reader"),
            "missed": sum(1 for r in mine if not r["landed"] and r["expect"] == "land"),
            "left_right": sum(1 for r in mine if not r["landed"] and r["expect"] == "left"),
            "model_calls": sum(r["calls"] for r in mine)}
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--judges", default="yes,yes-last,no,real")
    p.add_argument("--engine", choices=("plan",), default="plan")
    p.add_argument("--model", default="haiku")
    p.add_argument("--only", default="", help="run the cases whose id contains this text")
    p.add_argument("--group-size", type=int, default=0, help="claims read in one call (default: the module's)")
    p.add_argument("--json", type=Path)
    a = p.parse_args(argv)
    os.environ.pop("ANTHROPIC_API_KEY", None)   # `claude -p` must bill the plan, never a key found in the environment
    from api.services import described_landing

    if a.group_size:
        described_landing.MAX_CLAIMS_PER_CALL = a.group_size
    spec = load_cases()
    cases = [c for c in spec["cases"] if a.only in c["id"]]
    judges = [j for j in a.judges.split(",") if j]
    home = Path(tempfile.mkdtemp(prefix="described-landing-home-"))
    from benchmarks.engine_parity import _leg_environment, settings_for

    rows: list[dict] = []
    with _leg_environment(home, home / "scratch"):
        real = None
        if "real" in judges:
            from api.services import full_name_join, same_name_tend
            from benchmarks.consolidation.run import engine_model

            settings = settings_for("plan", home / "scratch", model=engine_model("plan", a.model),
                                    judge=engine_model("plan", a.model))
            strong = same_name_tend.main_tier(settings)

            async def ask(system: str, prompt: str) -> object:
                return await full_name_join.ask_main(strong, system, prompt)

            real = (ask, strong)
        for judge in judges:
            for case in cases:
                for row in asyncio.run(run_case(spec, case, judge, real)):
                    rows.append(row)
                    state = "landed" if row["landed"] else "left  "
                    ok = "ok   " if row["landed"] == (row["expect"] == "land") else "WRONG" if row["landed"] else "missed"
                    print(f"{judge:8} {row['id']:40} {state} {ok} by={row['by'] or '-':6} gates_passed={row['gates']!s:5} "
                          f"why_left={row['why']}", flush=True)
    summary = summarise(rows)
    print(json.dumps(summary, indent=1))
    if a.json:
        a.json.write_text(json.dumps({"rows": rows, "summary": summary}, indent=1))
    return 1 if any(r["landed"] and r["expect"] == "left" and r["by"] == "code" for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
