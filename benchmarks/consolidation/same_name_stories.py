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
and whether the end state is what the story expects (``two``: two people and no blend or cut; else one person, or one
person held as two in doubt with the one question open and the located link in it (**linked**: the two reads of the
pair did not agree, so the person's tap joins them); ``q``: the range of questions).

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


def text_of(conv: dict, name: str = "") -> str:
    """The description `same_name_people.describe` makes of an extraction with this summary and these facts (and, when
    it is written with a qualifier, this name)."""
    return snp.describe({"name": name, "summary": conv["t"], "key_facts": conv.get("f", []), "source_episode_timestamp": conv["d"]})


@dataclass
class Conv:
    ep: str
    who: str
    text: str
    sub: bool = False
    #: A person the conversation wrote with a qualifier ("Nico (finance lead)", 2026-11-24): the real conversation id, the
    #: name as written (``""``: the bare name), and whether its conversation also names the bare name.
    conversation: str = ""
    written: str = ""
    no_rename: bool = False
    judged: bool = True    # False: a name that is neither bare nor "bare (qualifier)" ("Aunt Sara"): not a mention of the name


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
    linked: set[tuple[str, str]] = field(default_factory=set)   # asked with a located link: one tap joins them
    questions: int = 0
    review_pages: set[str] = field(default_factory=set)
    review_pairs: set[tuple[str, str]] = field(default_factory=set)
    calls: int = 0
    review_calls: int = 0
    legacy: bool = False   # the code before 2026-11-24: a name with a qualifier is not a mention of the bare name

    @property
    def slug(self) -> str:
        return self.name.lower()

    def identities(self) -> list:
        out = []
        for p in self.persons.values():
            if "~" in p.id:
                continue   # a name with a qualifier, held under itself: never an identity of the bare name
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


async def step(world: World, batch: list[Conv], judge, ep_n: list[int], strong=None) -> None:
    """One batch of one name, as `entity_resolver._plan_same_name_people` and `_resolve_same_name_people` carry it out."""
    mentions = [snp.Mention(c.ep, c.text, c.conversation or c.ep, bool(c.written), c.no_rename) for c in batch
                if c.judged and not (world.legacy and c.written)]
    by_ep = {c.ep: c for c in batch}
    identities = world.identities()
    moves: dict[str, snp.Destination] = {}
    result = snp.Plan()
    if mentions and (len(mentions) >= 2 or identities):
        result = await (snp.plan(world.name, mentions, identities, judge, strong) if strong is not None and hasattr(snp, 'Item')
                       else snp.plan(world.name, mentions, identities, judge))
        world.calls += 1 if result.called else 0
        moves = result.moves
    compared = {i.ref for i in identities[: snp.MAX_IDENTITIES]}
    taken = set(world.persons)
    news: dict[str, str] = {}
    for c in batch:
        dest = moves.get(c.ep)
        if dest is None and c.written:
            target = f"{world.slug}~{c.written}"   # the code before: a name with a qualifier is a name of its own, never matched
        elif dest is None or dest.kind == "plain":
            target = world.slug
        elif dest.kind == "new":
            if dest.ref not in news:
                doubt = getattr(dest, "doubt", False)
                news[dest.ref] = snp.free_id(world.slug, taken)
                taken.add(news[dest.ref])
                for other in compared | ({world.slug} if world.slug in world.persons else set()):
                    if other in world.persons or True:
                        (world.doubts if doubt else world.apart).add(pair(news[dest.ref], other))
                        if doubt:   # a doubt just recorded is flagged for the tail (`entity_resolver._record_doubt_pairs`)
                            world.review_pairs.add(pair(news[dest.ref], other))
            target = news[dest.ref]
        else:
            target = dest.ref
        world.persons.setdefault(target, Person(target)).convs.append(c)
    # The people one conversation named together know of each other (`Destination.siblings`, 2026-11-24): apart for good when it
    # wrote both with a qualifier, else a doubt, whatever was recorded of either against the rest (`_resolve_same_name_people`).
    for c in batch:
        dest = moves.get(c.ep)
        if dest is None or dest.kind != "new" or not getattr(dest, "siblings", ()):
            continue
        for kind, ref, apart in dest.siblings:
            there = world.slug if kind == "plain" else (news.get(ref) if kind == "new" else ref)
            if there is None or there == news[dest.ref]:
                continue
            p = pair(news[dest.ref], there)
            world.doubts.discard(p)
            world.apart.discard(p)
            if apart:
                world.apart.add(p)
            else:
                world.doubts.add(p)
                world.review_pairs.add(p)
    # a new person's pairs with others that do not exist (an unseen plain) are dropped
    world.doubts = {p for p in world.doubts if p[0] in world.persons and p[1] in world.persons}
    world.apart = {p for p in world.apart if p[0] in world.persons and p[1] in world.persons}
    world.review_pages |= result.review_pages
    world.review_pairs |= result.review_pairs


def merge_persons(world: World, loser: str, winner: str) -> None:
    world.persons[winner].convs.extend(world.persons.pop(loser).convs)
    world.doubts = {pair(winner if x == loser else x, winner if y == loser else y) for x, y in world.doubts}
    world.doubts = {p for p in world.doubts if p[0] != p[1]}
    world.apart = {p for p in world.apart if loser not in p}


async def tend(world: World, judge) -> None:
    """The end-of-drain review (`same_name_tend`): a flagged page is read once for two people in it (the main model; a
    located contrast splits it), then each doubt that is a pair of pages for the same, different or neither. A located
    contrast keeps the pair apart for good; a located link two reads agree on joins the two (ruling 74a); a pair that
    reads like two people waits apart and nobody is asked; one that reads like one person, or like nothing, is asked
    once (with the link, when one read found it); a read that could not be stood on asks nothing."""
    flagged_pages, flagged_pairs = sorted(world.review_pages), sorted(world.review_pairs)
    world.review_pages, world.review_pairs = set(), set()   # a flag is looked at once (`same_name_doubts.clear_flags`)
    for ref in flagged_pages:
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
    for a, b in flagged_pairs:   # only what Stage 2 flagged, as the product: a doubt nobody flagged is never read
        if pair(a, b) not in world.doubts:
            continue
        pa, pb = world.persons.get(a), world.persons.get(b)
        if pa is None or pb is None or not (pa.page and pb.page) or pair(a, b) in world.apart:
            continue
        busy = sum(1 for x, y in world.doubts if a in (x, y)) > 1 or sum(1 for x, y in world.doubts if b in (x, y)) > 1
        sides = (snr.Page(a, tuple(snp.Item(c.text, (c.ep,)) for c in pa.convs)),
                 snr.Page(b, tuple(snp.Item(c.text, (c.ep,)) for c in pb.convs)))
        world.review_calls += 1
        verdict = await snr.settle_pair(world.name, *sides, judge)
        if verdict.verdict == "same" and not busy:
            world.review_calls += 1
            if (await snr.settle_pair(world.name, *sides, judge)).verdict == "same":
                loser, winner = (b, a) if (a == world.slug or not b == world.slug) else (a, b)
                merge_persons(world, loser, winner)
                continue
        if verdict.verdict == "apart":
            world.apart.add(pair(a, b))
            world.doubts.discard(pair(a, b))
        elif not verdict.answered or (verdict.verdict != "same" and verdict.leaning == "two"):
            continue
        elif pair(a, b) not in world.asked:
            world.asked.add(pair(a, b))
            world.questions += 1
            if verdict.verdict == "same":
                world.linked.add(pair(a, b))


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
    # One person held as two in doubt, with the one question open and the link in it: the person's tap joins them, and
    # nothing was blended meanwhile. Counted apart from "joined with no one asked" (`linked`).
    held = [pair(x, y) for x in world.persons for y in world.persons if x < y]
    linked = (not story["two"]) and len(world.persons) == 2 and not blend and all(p in world.linked for p in held)
    if story["two"]:
        end_ok = (not blend) and (not cut) and len(labels) >= 2
    else:
        end_ok = ((len(world.persons) == 1) and not blend) or linked
    q_ok = lo <= world.questions <= hi
    return {"blend": blend, "cut": cut and not linked, "linked": linked, "questions": world.questions, "end_ok": end_ok, "q_ok": q_ok,
            "ok": end_ok and q_ok, "persons": len(world.persons), "doubt_left": len(world.doubts),
            "calls": world.calls, "review_calls": world.review_calls}


async def replay(story: dict, judge, review_judge, n: int = 0, legacy: bool = False) -> dict:
    world = World(story["name"], legacy=legacy)
    ep = [0]

    def conv(c: dict) -> Conv:
        ep[0] += 1
        return Conv(f"ep_{story['id']}_{ep[0]}", c["who"], text_of(c), bool(c.get("sub")))

    def convs(c: dict) -> list[Conv]:
        """A batch item is one conversation naming one person, or (``pair``) one conversation naming several of the name,
        each written bare or with a qualifier (``q``: "Tomas (finance)"; 2026-11-24)."""
        if "pair" not in c:
            return [conv(c)]
        ep[0] += 1
        episode = f"ep_{story['id']}_{ep[0]}"
        out = []
        for m in c["pair"]:
            written = f"{story['name']} ({m['q']})".lower() if m.get("q") else ""
            key = snp.mention_key(episode, f"{story['name']} ({m['q']})" if m.get("q") else story["name"])
            out.append(Conv(key, m["who"], text_of(m, f"{story['name']} ({m['q']})" if m.get("q") else ""),
                            conversation=episode, written=written))
        bare = {x.conversation for x in out if not x.written}
        for x in out:
            x.no_rename = bool(x.written) and x.conversation in bare
        return out

    for seeded in story.get("seed", []):
        world.persons[seeded["id"]] = Person(seeded["id"], [conv(c) for c in seeded["convs"]])
    world.apart |= {pair(a, b) for a, b in story.get("seed_apart", [])}
    world.doubts |= {pair(a, b) for a, b in story.get("seed_doubt", [])}
    for batch in story["batches"]:   # each batch is a night: the tail review runs after it, on what it flagged
        await step(world, [x for c in batch for x in convs(c)], judge, ep, review_judge)
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
                   f"  cut {sum(x['cut'] for x in runs):>3}  linked {sum(x.get('linked', False) for x in runs):>3}  q/run {sum(x['questions'] for x in runs) / n:.2f}"
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
