"""Replay battery for the same-name judge (`api/services/same_name_people.py`, 2026-11-23).

Why: the judge decides, once per bare first name per batch, which conversations are one person. It must split two
people called "Marc" and must never split one person whose life changed (a new job, a move, a promotion). A benchmark
run makes about six judge calls and misses a one-in-ten defect; this replays the real inputs and invented ones of the
same shapes, many times each, through the real `same_name_people.plan`, for cents.

`same_name_cases.json` holds the cases: each has the people already on record under the name (``identities``) and the
conversations' descriptions (``mentions``), every one labelled with who it truly is. A **false split** is two things
with one label that ended up apart; a **missed split** is two with different labels that ended up together. The first
cases are rebuilt from stored benchmark runs (the git history of their scratch banks); the rest are invented. A leg of
the benchmark also writes its own calls (`same_name_calls.jsonl`); `--from-calls` turns those into cases, labelled by
hand afterwards.

    api/.venv/bin/python -m benchmarks.consolidation.same_name_battery --model haiku --repeats 20

Needs ``ANTHROPIC_API_KEY`` in the environment or in ``--key-file`` (never printed). Cost is printed.
``--engine plan`` runs the same cases through the signed-in Claude plan instead (no key read), the way a new user's Sleep
does: the small judge on Haiku, and the main model as the second reader of a doubt (``strong``), as in a run. It also
prints the replies the engine could not give in a readable shape (`engines.py`). 2026-11-24.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from api.services import same_name_people as snp  # noqa: E402

CASES = Path(__file__).with_name("same_name_cases.json")


def load_cases(path: Path = CASES) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def build(case: dict) -> tuple[list[snp.Mention], list[snp.Identity]]:
    identities = [snp.Identity("page", f"{case['name'].lower()}" if i["plain"] else f"{case['name'].lower()}-{n + 2}",
                               bool(i["plain"]), i["text"], frozenset(f"ep_known_{n}_{k}" for k in range(int(i.get("conversations", 2)))))
                  for n, i in enumerate(case.get("identities", []))]
    mentions = [snp.Mention(f"ep_{n}", m["text"]) for n, m in enumerate(case["mentions"])]
    return mentions, identities


def partition(case: dict, plan: snp.Plan) -> dict[str, str]:
    """Where each thing of the case ended up: ``stay`` (the plain person), a known person's id, or a new person's label."""
    placed: dict[str, str] = {}
    identities = case.get("identities", [])
    for n, i in enumerate(identities):
        placed[f"i{n}"] = "stay" if i["plain"] else f"page:{case['name'].lower()}-{n + 2}"
    for n, _m in enumerate(case["mentions"]):
        destination = plan.moves.get(f"ep_{n}")
        placed[f"m{n}"] = "stay" if destination is None else f"{destination.kind}:{destination.ref}"
    return placed


def score_case(case: dict, plan: snp.Plan) -> tuple[bool, bool]:
    """(a false split happened, a missed split happened) for one run of one case."""
    placed = partition(case, plan)
    labels = {f"i{n}": i["label"] for n, i in enumerate(case.get("identities", []))}
    labels.update({f"m{n}": m["label"] for n, m in enumerate(case["mentions"])})
    keys = list(labels)
    false_split = missed = False
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            same_truth = labels[keys[a]] == labels[keys[b]]
            same_placed = placed[keys[a]] == placed[keys[b]]
            if same_truth and not same_placed:
                false_split = True
            if not same_truth and same_placed:
                missed = True
    return false_split, missed


def key_from(path: Path) -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    for line in path.expanduser().read_text(encoding="utf-8").splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no ANTHROPIC_API_KEY")


async def run(cases: list[dict], repeats: int, ask, concurrency: int = 24, strong_ask=None, speaker: bool = True) -> list[dict]:
    """Replay every case ``repeats`` times through the real ``same_name_people.plan`` with ``ask(system, prompt)``."""
    gate = asyncio.Semaphore(concurrency)

    async def judge(system: str, prompt: str) -> object:
        async with gate:
            return await ask(system, prompt)

    async def strong(system: str, prompt: str) -> object:
        async with gate:
            return await strong_ask(system, prompt)

    async def one(case: dict) -> dict:
        mentions, identities = build(case)
        extra = (strong,) if strong_ask is not None else ()
        # A case may name the bank's owner (``speaker``): the judge is told whose conversations these are, as in a run.
        named = {"speaker": case["speaker"]} if speaker and case.get("speaker") and "speaker" in inspect.signature(snp.plan).parameters else {}
        runs = await asyncio.gather(*(snp.plan(case["name"], mentions, identities, judge, *extra, **named) for _ in range(repeats)))
        flags = [score_case(case, p) for p in runs]
        return {"id": case["id"], "kind": case["kind"], "runs": len(runs), "false": sum(f for f, _ in flags),
                "missed": sum(m for _, m in flags), "thin": sum(p.thin for p in runs),
                "unanswered": sum(1 for p in runs if not p.called),
                "unreadable": sum(int(getattr(p, "unreadable", 0) or 0) for p in runs)}

    return list(await asyncio.gather(*(one(c) for c in cases)))


def product_ask(tier: str, main: str, home: Path, bank: Path, engine: str = "key"):
    """The product's own judge call (`entity_resolver._same_name_ask`) on a Claude key, through the same settings and
    engine a benchmark leg uses: thinking, the JSON-only suffix and the token room are the product's, not a guess. A
    cut-off or unreadable answer is the product's "one person", exactly as in a run."""
    from api.services import entity_resolver
    from benchmarks.consolidation import engines

    settings = engines.settings(engine, bank, model=main, judge=tier)

    async def ask(system: str, prompt: str) -> object:
        return await entity_resolver._same_name_ask(settings, system, prompt)

    return ask


def plan_asks(tier: str, main: str, bank: Path, strong: bool = True):
    """The judge and, as in a run, the main model on the same engine as the second reader (`same_name_tend.main_tier`)."""
    from api.services import entity_resolver, same_name_tend
    from benchmarks.consolidation import engines

    settings = engines.settings("plan", bank, model=main, judge=tier)

    async def ask(system: str, prompt: str) -> object:
        return await entity_resolver._same_name_ask(settings, system, prompt)

    async def second(system: str, prompt: str) -> object:
        return await entity_resolver._same_name_ask(same_name_tend.main_tier(settings), system, prompt)

    return ask, (second if strong else None)


def spend(home: Path) -> dict:
    from benchmarks.engine_parity import _usage_events

    events = _usage_events(home)
    return {"calls": len(events), "failed": sum(1 for e in events if not e.get("ok", True)),
            "in": sum(e.get("input_tokens") or 0 for e in events), "out": sum(e.get("output_tokens") or 0 for e in events),
            "cost": sum(e.get("cost_usd") or 0.0 for e in events)}


def report(rows: list[dict], used: dict) -> str:
    out = []
    for r in rows:
        out.append(f"{r['kind']:4} {r['id']:34} false-split {r['false']:>3}/{r['runs']}  missed-split {r['missed']:>3}/{r['runs']}"
                   + (f"  (cut by the 15-word floor {r['thin']})" if r["thin"] else ""))
    one = [r for r in rows if r["kind"] == "one"]
    two = [r for r in rows if r["kind"] == "two"]
    f, n = sum(r["false"] for r in one), sum(r["runs"] for r in one)
    t, m = sum(r["runs"] - r["missed"] for r in two), sum(r["runs"] for r in two)
    out.append(f"FALSE SPLITS of one person: {f}/{n}   TRUE SPLITS kept of two people: {t}/{m}")
    out.append(f"judge calls {used['calls']} (failed {used['failed']})  in {used['in']}  out {used['out']}  cost ${used['cost']:.3f}")
    return "\n".join(out)


def from_calls(path: Path) -> list[dict]:
    """Turn a leg's `same_name_calls.jsonl` into cases to label by hand (every label ``?``)."""
    cases = []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines()):
        call = json.loads(raw)
        prompt = call["prompt"]
        name = re.search(r'someone is called "([^"]+)"', prompt)
        known = re.search(r"KNOWN PEOPLE with this name[^\n]*\n(.*?)\nCONVERSATIONS", prompt, re.S)
        identities = []
        if known:
            pieces = re.split(r"(?m)^\[\d+\] ", known.group(1))[1:]
            identities = [{"text": p.strip(), "label": "?", "plain": k == 0} for k, p in enumerate(pieces)]
        convs = re.search(r"CONVERSATIONS[^\n]*\n(.*?)\nRules:", prompt, re.S)
        mentions = [{"text": p.strip(), "label": "?"} for p in re.split(r"(?m)^\([A-Z]\) ", convs.group(1))[1:]] if convs else []
        cases.append({"id": f"{path.parent.name}-{n}", "name": name.group(1) if name else "?", "kind": "?",
                      "identities": identities, "mentions": mentions, "answer": call.get("answer")})
    return cases


def load_module(path: Path) -> None:
    """Replay with another copy of the module (e.g. `git show origin/dev:api/services/same_name_people.py`), to measure
    the code before a change with the same cases."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("same_name_people_alt", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["same_name_people_alt"] = module
    spec.loader.exec_module(module)
    globals()["snp"] = module


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--judge", default="haiku", help="the tier Sleep's small judge is set to (the product default: haiku)")
    p.add_argument("--main", default="sonnet", help="the tier of Sleep's main model")
    p.add_argument("--repeats", type=int, default=20)
    p.add_argument("--cases", type=Path, default=CASES)
    p.add_argument("--only", default="", help="substring of case ids")
    p.add_argument("--kind", default="", help="one or two")
    p.add_argument("--home", type=Path, help="scratch home for the telemetry (default: a new temporary folder)")
    p.add_argument("--key-file", type=Path, default=Path("~/.cicada/secrets.env"))
    p.add_argument("--strong", default="", help="the tier of the main model that reads a one-person answer again (the product's second reading; default none)")
    p.add_argument("--module", type=Path, help="another copy of same_name_people.py to replay (default: this checkout's)")
    p.add_argument("--from-calls", type=Path, help="print cases built from a leg's same_name_calls.jsonl and exit")
    from benchmarks.consolidation import engines

    engines.add_argument(p)
    p.add_argument("--no-strong", action="store_true", help="--engine plan: leave the main model's second reading out (default: in, as in a run)")
    p.add_argument("--no-speaker", action="store_true", help="do not tell the judge the owner's name (the code before 2026-11-24)")
    a = p.parse_args(argv)
    if a.from_calls:
        print(json.dumps(from_calls(a.from_calls), indent=1, ensure_ascii=False))
        return 0
    if a.module:
        load_module(a.module)
    from benchmarks.engine_parity import _leg_environment

    engines.arm(a.engine, lambda: os.environ.__setitem__("ANTHROPIC_API_KEY", key_from(a.key_file)))   # inherited by the call, never printed
    cases = [c for c in load_cases(a.cases) if a.only in c["id"] and (not a.kind or c["kind"] == a.kind)]
    root = a.home or Path(tempfile.mkdtemp(prefix="same-name-battery-"))
    home, bank = root / "home", root / "bank"
    home.mkdir(parents=True, exist_ok=True)
    bank.mkdir(parents=True, exist_ok=True)
    with _leg_environment(home, bank), engines.tally() as counted:
        if a.engine == "plan":
            ask, strong = plan_asks(a.judge, a.main, bank, strong=not a.no_strong)
            rows = asyncio.run(run(cases, a.repeats, ask, concurrency=2, strong_ask=strong, speaker=not a.no_speaker))
        else:
            strong = product_ask(a.strong, a.strong, home, bank) if a.strong else None
            rows = asyncio.run(run(cases, a.repeats, product_ask(a.judge, a.main, home, bank), strong_ask=strong,
                                   speaker=not a.no_speaker))
        print(report(rows, spend(home)))
        if a.engine == "plan":
            print(f"answers the parser could not use (`Plan.unreadable`): {sum(r['unreadable'] for r in rows)} "
                  f"of {sum(r['runs'] for r in rows)} runs")
            print(counted.report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
