"""Replay stories for the same-name rule (`api/services/same_name_people.py`, `same_name_review.py`, 2026-11-23).

`same_name_battery.py` replays one judge call at a time. A story is what the owner's words are about: a name that comes
up over several days, two people who turn out to be one, one page that turns out to hold two, a doubt that nothing ever
settles. A story is a short run of batches for one invented name; each batch is a few conversations' descriptions, each
labelled with who it truly is. A story may start from people already on record (``seed``, a page that was joined by
mistake). Each replay plays the batches in order through the real `plan` (the product's own judge call), applies its
decisions to a small simulated bank exactly as `entity_resolver` and `same_name_tend` apply theirs to the real one, then
runs the end-of-drain review (`same_name_review`, the main model's call) on what the batches flagged.

The simulated bank keeps only what the decisions read: each person's conversations (a page when it has two or more, or one
that stands on its own; a line below that), the pairs held in doubt, the pairs kept apart, and the questions asked.

Scored per replay: **blend** (one person holds conversations that truly are two people: a wrong join), **cut** (one
person's conversations are on two people: a wrong split, or a doubt held apart that was one person), **questions** asked,
and whether the end state is what the story expects (``two``: two people and no blend or cut; else one person; ``q``: the
range of questions).

    api/.venv/bin/python -m benchmarks.consolidation.same_name_stories --repeats 20 --judge haiku --main sonnet
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from api.services import same_name_people as snp  # noqa: E402
from api.services import same_name_review as snr  # noqa: E402

STORIES = Path(__file__).with_name("same_name_stories.json")


def load_stories(path: Path = STORIES) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def text_of(conv: dict) -> str:
    """The description `same_name_people.describe` makes of an extraction with this summary and these facts."""
    return snp.describe({"summary": conv["t"], "key_facts": conv.get("f", []), "source_episode_timestamp": conv["d"]})


@dataclass
class Conv:
    ep: str
    who: str
    text: str
    sub: bool = False


@dataclass
class Person:
    id: str
    convs: list[Conv] = field(default_factory=list)

    @property
    def page(self) -> bool:
        return len(self.convs) >= 2 or any(c.sub for c in self.convs)


@dataclass
class World:
    name: str
    persons: dict[str, Person] = field(default_factory=dict)
    doubts: set[tuple[str, str]] = field(default_factory=set)
    apart: set[tuple[str, str]] = field(default_factory=set)
    asked: set[tuple[str, str]] = field(default_factory=set)
    questions: int = 0
    review_pages: set[str] = field(default_factory=set)
    review_pairs: set[tuple[str, str]] = field(default_factory=set)
    review_all: bool = False
    calls: int = 0
    review_calls: int = 0

    @property
    def slug(self) -> str:
        return self.name.lower()

    def identities(self) -> list:
        out = []
        for p in self.persons.values():
            blended = " ".join(c.text for c in p.convs)
            eps = frozenset(c.ep for c in p.convs)
            if not hasattr(snp, "Item"):   # the code before the doubt state (`--module`): one blended text a person
                out.append(snp.Identity("page" if p.page else "line", p.id, p.id == self.slug, blended, eps))
                continue
            items = tuple(snp.Item(c.text, (c.ep,)) for c in p.convs) if p.page else (snp.Item(blended, tuple(sorted(eps))),)
            doubt = frozenset(b if a == p.id else a for a, b in self.doubts if p.id in (a, b))
            out.append(snp.Identity("page" if p.page else "line", p.id, p.id == self.slug, blended, eps,
                                    items if p.page else (), doubt))
        out.sort(key=lambda i: (not i.plain, -len(i.episodes), i.ref))
        return out


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))  # type: ignore[return-value]


async def step(world: World, batch: list[Conv], judge, ep_n: list[int]) -> None:
    """One batch of one name, as `entity_resolver._plan_same_name_people` and `_resolve_same_name_people` carry it out."""
    mentions = [snp.Mention(c.ep, c.text) for c in batch]
    by_ep = {c.ep: c for c in batch}
    identities = world.identities()
    moves: dict[str, snp.Destination] = {}
    result = snp.Plan()
    if mentions and (len(mentions) >= 2 or identities):
        result = await snp.plan(world.name, mentions, identities, judge)
        world.calls += 1 if result.called else 0
        moves = result.moves
    compared = {i.ref for i in identities[: snp.MAX_IDENTITIES]}
    taken = set(world.persons)
    news: dict[str, str] = {}
    for c in batch:
        dest = moves.get(c.ep)
        if dest is None:
            target = world.slug
        elif dest.kind == "new":
            if dest.ref not in news:
                doubt = getattr(dest, "doubt", False)
                news[dest.ref] = snp.free_id(world.slug, taken)
                taken.add(news[dest.ref])
                for other in compared | ({world.slug} if world.slug in world.persons else set()):
                    if other in world.persons or True:
                        (world.doubts if doubt else world.apart).add(pair(news[dest.ref], other))
            target = news[dest.ref]
        else:
            target = dest.ref
        world.persons.setdefault(target, Person(target)).convs.append(c)
    # a new person's pairs with others that do not exist (an unseen plain) are dropped
    world.doubts = {p for p in world.doubts if p[0] in world.persons and p[1] in world.persons}
    world.apart = {p for p in world.apart if p[0] in world.persons and p[1] in world.persons}
    if getattr(result, "review", False):
        world.review_pages |= result.review_pages
        world.review_pairs |= result.review_pairs
        world.review_all = True


def merge_persons(world: World, loser: str, winner: str) -> None:
    world.persons[winner].convs.extend(world.persons.pop(loser).convs)
    world.doubts = {pair(winner if x == loser else x, winner if y == loser else y) for x, y in world.doubts}
    world.doubts = {p for p in world.doubts if p[0] != p[1]}
    world.apart = {p for p in world.apart if loser not in p}


async def tend(world: World, judge) -> None:
    """The end-of-drain review (`same_name_tend`): a flagged page is read once for two people in it (the main model; a
    located contrast splits it), then each doubt that is a pair of pages once for the same, different or neither; a doubt
    nothing settles is asked, once."""
    if not world.review_all:
        return
    for ref in sorted(world.review_pages):
        person = world.persons.get(ref)
        if person is None or not person.page:
            continue
        page = snr.Page(ref, tuple(snp.Item(c.text, (c.ep,)) for c in person.convs))
        world.review_calls += 1
        split = await snr.holds_two(world.name, page, judge)
        if split.episodes and len(split.episodes) < len(person.convs):
            new = snp.free_id(world.slug, set(world.persons))
            moved = [c for c in person.convs if c.ep in split.episodes]
            person.convs = [c for c in person.convs if c.ep not in split.episodes]
            world.persons[new] = Person(new, moved)
            world.apart.add(pair(ref, new))
    for a, b in sorted(world.doubts):
        pa, pb = world.persons.get(a), world.persons.get(b)
        if pa is None or pb is None or not (pa.page and pb.page) or pair(a, b) in world.apart:
            continue
        # a page in two doubt pairs waits for the person
        busy = sum(1 for x, y in world.doubts if a in (x, y)) > 1 or sum(1 for x, y in world.doubts if b in (x, y)) > 1
        world.review_calls += 1
        verdict = await snr.settle_pair(world.name, snr.Page(a, tuple(snp.Item(c.text, (c.ep,)) for c in pa.convs)),
                                        snr.Page(b, tuple(snp.Item(c.text, (c.ep,)) for c in pb.convs)), judge)
        if verdict.verdict == "same" and not busy:
            loser, winner = (b, a) if (a == world.slug or not b == world.slug) else (a, b)
            merge_persons(world, loser, winner)
        elif verdict.verdict == "apart":
            world.apart.add(pair(a, b))
            world.doubts.discard(pair(a, b))
        elif pair(a, b) not in world.asked:
            world.asked.add(pair(a, b))
            world.questions += 1


def score(world: World, story: dict) -> dict:
    blend = cut = False
    labels: dict[str, set[str]] = {}
    for person in world.persons.values():
        who = {c.who for c in person.convs}
        blend |= len(who) > 1
        for w in who:
            labels.setdefault(w, set()).add(person.id)
    cut = any(len(ids) > 1 for ids in labels.values())
    lo, hi = story["q"]
    end_ok = (not blend) and (not cut if not story["two"] else len(labels) == len(world.persons) or not cut)
    if story["two"]:
        end_ok = (not blend) and (not cut) and len(labels) >= 2
    else:
        end_ok = (len(world.persons) == 1) and not blend
    q_ok = lo <= world.questions <= hi
    return {"blend": blend, "cut": cut, "questions": world.questions, "end_ok": end_ok, "q_ok": q_ok,
            "ok": end_ok and q_ok, "persons": len(world.persons), "doubt_left": len(world.doubts),
            "calls": world.calls, "review_calls": world.review_calls}


async def replay(story: dict, judge, review_judge, n: int = 0) -> dict:
    world = World(story["name"])
    ep = [0]

    def conv(c: dict) -> Conv:
        ep[0] += 1
        return Conv(f"ep_{story['id']}_{ep[0]}", c["who"], text_of(c), bool(c.get("sub")))

    for seeded in story.get("seed", []):
        world.persons[seeded["id"]] = Person(seeded["id"], [conv(c) for c in seeded["convs"]])
    for batch in story["batches"]:
        await step(world, [conv(c) for c in batch], judge, ep)
    await tend(world, review_judge)
    return score(world, story)


async def run(stories: list[dict], repeats: int, judge_ask, review_ask, concurrency: int = 24) -> list[dict]:
    gate = asyncio.Semaphore(concurrency)

    async def gated(ask):
        async def call(system: str, prompt: str) -> object:
            async with gate:
                return await ask(system, prompt)
        return call

    judge, review_judge = await gated(judge_ask), await gated(review_ask)

    async def one(story: dict) -> dict:
        runs = await asyncio.gather(*(replay(story, judge, review_judge, i) for i in range(repeats)))
        return {"id": story["id"], "shape": story["shape"], "runs": runs}

    return list(await asyncio.gather(*(one(s) for s in stories)))


def report(rows: list[dict], used: dict | None = None) -> str:
    out = []
    shapes: dict[str, list[dict]] = {}
    for r in rows:
        runs = r["runs"]
        n = len(runs)
        out.append(f"{r['shape']:22} {r['id']:30} ok {sum(x['ok'] for x in runs):>3}/{n}  blend {sum(x['blend'] for x in runs):>3}"
                   f"  cut {sum(x['cut'] for x in runs):>3}  q/run {sum(x['questions'] for x in runs) / n:.2f}"
                   f"  persons {sum(x['persons'] for x in runs) / n:.1f}  calls {sum(x['calls'] for x in runs) / n:.1f}"
                   f"+{sum(x['review_calls'] for x in runs) / n:.1f}")
        shapes.setdefault(r["shape"], []).extend(runs)
    out.append("")
    for shape, runs in shapes.items():
        n = len(runs)
        out.append(f"{shape:22} replays {n:>4}  ok {sum(x['ok'] for x in runs):>4} ({100 * sum(x['ok'] for x in runs) / n:.0f}%)"
                   f"  wrong joins {sum(x['blend'] for x in runs):>3}  wrong splits {sum(x['cut'] for x in runs):>3}"
                   f"  questions {sum(x['questions'] for x in runs)}")
    if used:
        out.append(f"judge calls {used['calls']} (failed {used['failed']})  in {used['in']}  out {used['out']}  cost ${used['cost']:.3f}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    from benchmarks.consolidation import same_name_battery as battery

    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--judge", default="haiku")
    p.add_argument("--main", default="sonnet")
    p.add_argument("--repeats", type=int, default=20)
    p.add_argument("--stories", type=Path, default=STORIES)
    p.add_argument("--only", default="", help="substring of story ids or shapes")
    p.add_argument("--home", type=Path)
    p.add_argument("--key-file", type=Path, default=Path("~/.cicada/secrets.env"))
    p.add_argument("--json", type=Path, help="write the rows here")
    p.add_argument("--module", type=Path, help="another copy of same_name_people.py (the code before a change): no review step")
    a = p.parse_args(argv)
    if a.module:
        battery.load_module(a.module)
        globals()["snp"] = battery.snp
    from benchmarks.engine_parity import _leg_environment

    os.environ["ANTHROPIC_API_KEY"] = battery.key_from(a.key_file)
    stories = [s for s in load_stories(a.stories) if a.only in s["id"] or a.only in s["shape"]]
    root = a.home or Path(tempfile.mkdtemp(prefix="same-name-stories-"))
    home, bank = root / "home", root / "bank"
    home.mkdir(parents=True, exist_ok=True)
    bank.mkdir(parents=True, exist_ok=True)
    with _leg_environment(home, bank):
        judge = battery.product_ask(a.judge, a.main, home, bank)
        review = battery.product_ask(a.main, a.main, home, bank)
        rows = asyncio.run(run(stories, a.repeats, judge, review))
        print(report(rows, battery.spend(home)))
    if a.json:
        a.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
