"""Stage 2 on what Stage 1 really wrote for a conversation that names two people of one first name (2026-11-24).

`both_named_battery.py` replays Stage 1 alone and keeps every answer (``raw.jsonl``). This takes those answers as they are
(its shapes: "Nico" and "Nico (finance lead)", two qualified, two bare-looking names) and plays each through the same-name
step of Stage 2 (`same_name_people.plan`, the product's own judge call) into a simulated bank in five states, then one more
batch: a later bare-name conversation of each of the two. The states: **empty** (nobody of the name on record), **a-known**
(the first person is a page), **b-known** (the second is), **both** (both are pages, kept apart), **one-and-doubt** (one is a page, the other
a held line in doubt against it). Each is scored the way `same_name_stories` scores: **blend** (one person holds the facts of
both), **cut** (one person's facts end on two people), **questions**, and **ok** (two people, no blend, no cut).
``--legacy`` plays the code before: a name with a qualifier is no mention of the bare name, a person of its own.

    api/.venv/bin/python -m benchmarks.consolidation.both_named_stories --raw OUT/raw.jsonl [--legacy]

Needs ``ANTHROPIC_API_KEY`` in the environment or in ``--key-file`` (never printed). Cost is printed.
``--engine plan`` plays Stage 2's judge on the signed-in Claude plan (no key read) and prints the replies that were not a
JSON object (`engines.py`; 2026-11-24). The raw answers it replays are whatever ``--raw`` holds.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from api.services import same_name_people as snp  # noqa: E402
from benchmarks.consolidation import both_named_battery as b1  # noqa: E402
from benchmarks.consolidation import same_name_stories as sns  # noqa: E402

SEEDS = Path(__file__).with_name("both_named_seeds.json")
STATES = ("empty", "a-known", "b-known", "both", "one-and-doubt")


def label_of(case: dict, text: str) -> str | None:
    hits = {p: sum(b1.norm(m) in text for m in marks) for p, marks in case["people"].items()}
    best = max(hits.values())
    top = [p for p, n in hits.items() if n == best]
    return top[0] if best and len(top) == 1 else None


def batch_from(case: dict, extraction: dict, n: int) -> list[sns.Conv] | None:
    """The conversation's mentions of the shared name as Stage 1 wrote them, each labelled with the person whose markers it holds."""
    ents = [e for e in extraction.get("entities", []) if str(e.get("type") or "").lower() == "person"
            and b1.form_of(e.get("name", ""), case["name"])]
    episode = extraction["episode_id"]
    out: list[sns.Conv] = []
    for e in ents:
        who = label_of(case, b1.entity_text(e, extraction))
        if who is None:
            continue
        name = str(e["name"]).strip()
        bare = snp.is_bare(name)
        out.append(sns.Conv(snp.mention_key(episode, name) if (bare or snp.stem_of(name)) else f"{episode}\x1f{name.lower()}", who,
                            snp.describe(e), conversation=episode, written="" if bare else name.lower(),
                            judged=bare or snp.stem_of(name) is not None))
    if len({c.who for c in out}) < 2:
        return None   # Stage 1 did not write two people of the name (or one of them is not told by its words): not a Stage 2 matter
    bare_eps = {c.conversation for c in out if not c.written}
    for c in out:
        c.no_rename = bool(c.written) and c.conversation in bare_eps
    return out


def seed_conv(case_id: str, who: str, k: int, seeds: dict, n: int) -> sns.Conv:
    c = seeds[case_id][who][k]
    return sns.Conv(f"ep_seed_{n}_{who}{k}", who, sns.text_of(c))


async def play(case: dict, extraction: dict, state: str, seeds: dict, judge, strong, legacy: bool, n: int) -> dict | None:
    batch = batch_from(case, extraction, n)
    if batch is None:
        return None
    world = sns.World(case["name"].capitalize(), legacy=legacy)
    world.name = case["name"]
    slug = world.slug
    mk = lambda who, k: seed_conv(case["id"], who, k, seeds, n)  # noqa: E731
    if state in ("a-known", "both", "one-and-doubt"):
        world.persons[slug] = sns.Person(slug, [mk("A", 0), mk("A", 1)])
    if state == "b-known":
        world.persons[slug] = sns.Person(slug, [mk("B", 0), mk("B", 1)])
    if state == "both":
        world.persons[f"{slug}-2"] = sns.Person(f"{slug}-2", [mk("B", 0), mk("B", 1)])
        world.apart.add(sns.pair(slug, f"{slug}-2"))
    if state == "one-and-doubt":
        world.persons[f"{slug}-2"] = sns.Person(f"{slug}-2", [mk("B", 0)])
        world.doubts.add(sns.pair(slug, f"{slug}-2"))
    await sns.step(world, batch, judge, [0], strong)
    # the next conversation of each of the two, named by the bare name, in one later batch
    later = [sns.Conv(f"ep_later_{n}_{w}", w, sns.text_of(seeds[case["id"]][w][2])) for w in ("A", "B")]
    await sns.step(world, later, judge, [0], strong)
    await sns.tend(world, strong)
    out = sns.score(world, {"two": True, "q": [0, 99]})
    out["shape"] = "+".join(sorted(b1.form_of(c.written or case["name"], case["name"]) or "?" for c in batch))
    return out


async def run(raw: list[dict], cases: dict, seeds: dict, judge_ask, review_ask, legacy: bool, only: set[str], states, concurrency: int = 24) -> list[dict]:
    gate = asyncio.Semaphore(concurrency)

    def gated(ask):
        async def call(system: str, prompt: str) -> object:
            async with gate:
                return await ask(system, prompt)
        return call

    judge, strong = gated(judge_ask), gated(review_ask)
    jobs, meta = [], []
    for n, r in enumerate(raw):
        case = cases[r["case"]]
        if r["case"] not in only or case["kind"] != "two" or r.get("extraction") is None or r["case"] not in seeds:
            continue
        for state in states:
            jobs.append(play(case, r["extraction"], state, seeds, judge, strong, legacy, n))
            meta.append((r["case"], state))
    done = await asyncio.gather(*jobs)
    return [{"case": c, "state": s, **d} for (c, s), d in zip(meta, done) if d is not None]


def report(rows: list[dict], used: dict | None = None) -> str:
    out = []
    for state in STATES:
        rs = [r for r in rows if r["state"] == state]
        if not rs:
            continue
        n = len(rs)
        out.append(f"{state:14} runs {n:>4}  ok {sum(r['ok'] for r in rs):>4} ({100 * sum(r['ok'] for r in rs) / n:.0f}%)  blend {sum(r['blend'] for r in rs):>3}"
                   f"  cut {sum(r['cut'] for r in rs):>3}  questions {sum(r['questions'] for r in rs):>3}  persons/run {sum(r['persons'] for r in rs) / n:.1f}")
    n = len(rows)
    if n:
        out.append(f"{'ALL':14} runs {n:>4}  ok {sum(r['ok'] for r in rows):>4} ({100 * sum(r['ok'] for r in rows) / n:.0f}%)  blend {sum(r['blend'] for r in rows):>3}"
                   f"  cut {sum(r['cut'] for r in rows):>3}  questions {sum(r['questions'] for r in rows):>3}")
    by_shape: dict[str, Counter] = {}
    for r in rows:
        by_shape.setdefault(r["shape"], Counter()).update({"runs": 1, "ok": int(r["ok"])})
    out.append("by Stage 1 shape: " + ", ".join(f"{k} {v['ok']}/{v['runs']}" for k, v in sorted(by_shape.items())))
    by_case: dict[str, Counter] = {}
    for r in rows:
        by_case.setdefault(r["case"], Counter()).update({"runs": 1, "ok": int(r["ok"])})
    out.append("by case: " + ", ".join(f"{k} {v['ok']}/{v['runs']}" for k, v in sorted(by_case.items())))
    if used:
        out.append(f"judge calls {used['calls']} (failed {used['failed']})  in {used['in']}  out {used['out']}  cost ${used['cost']:.3f}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    from benchmarks.consolidation import same_name_battery as battery

    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--raw", type=Path, required=True)
    p.add_argument("--legacy", action="store_true")
    p.add_argument("--judge", default="haiku")
    p.add_argument("--main", default="sonnet")
    p.add_argument("--only", default="", help="comma list of case ids")
    p.add_argument("--states", default=",".join(STATES))
    p.add_argument("--limit", type=int, default=0, help="at most this many Stage 1 answers per case")
    p.add_argument("--key-file", type=Path, default=Path("~/.cicada/secrets.env"))
    p.add_argument("--json", type=Path)
    from benchmarks.consolidation import engines

    engines.add_argument(p)
    a = p.parse_args(argv)
    from benchmarks.engine_parity import _leg_environment

    engines.arm(a.engine, lambda: os.environ.__setitem__("ANTHROPIC_API_KEY", battery.key_from(a.key_file)))
    cases = {c["id"]: c for c in b1.load_cases()}
    seeds = json.loads(SEEDS.read_text(encoding="utf-8"))
    raw = [json.loads(line) for line in a.raw.expanduser().read_text(encoding="utf-8").splitlines()]
    if a.limit:
        seen: Counter = Counter()
        kept = []
        for r in raw:
            seen[r["case"]] += 1
            if seen[r["case"]] <= a.limit:
                kept.append(r)
        raw = kept
    only = set(a.only.split(",")) if a.only else set(seeds)
    root = Path(tempfile.mkdtemp(prefix="both-named-stories-"))
    home, bank = root / "home", root / "bank"
    home.mkdir(parents=True)
    bank.mkdir(parents=True)
    with _leg_environment(home, bank), engines.tally() as counted:
        judge = battery.product_ask(a.judge, a.main, home, bank, a.engine)
        review = battery.product_ask(a.main, a.main, home, bank, a.engine)
        rows = asyncio.run(run(raw, cases, seeds, judge, review, a.legacy, only, a.states.split(","),
                               **({"concurrency": 2} if a.engine == "plan" else {})))
        print(report(rows, battery.spend(home)))
        if a.engine == "plan":
            print(counted.report())
    if a.json:
        a.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
