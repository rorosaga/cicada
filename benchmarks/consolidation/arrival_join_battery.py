"""A regression net for the arrival join (`api/services/arrival_join.py`, G245, owner 2026-11-24): hand-written traps with known
answers, and generated scenes, counted. NO model: the veto is answered "fits" for every candidate, so what is scored is what the
RULES let through; a trap that joins when it must not is the one error this system must never make.

    api/.venv/bin/python -m benchmarks.consolidation.arrival_join_battery [--scenes 2000] [--seed 1]

**What this is not.** The planner who wrote the rules also wrote these scenes, so zero false joins here measures the rule against
its author's picture of the world, never against the world's. It is a net: a later edit that opens a hole the traps name fails
here. The bar before any join writes is the coordinator's per-item reading of the real bank (`api.scripts.arrival_join_report`),
and `arrival_join.LIVE` stays false until then. The generated scenes are reported as counts, not as a rate to trust.

A *trap* builds a real scratch bank (`CICADA_HOME` and the bank in one temp folder: a first-name page, its conversations, the
directories, the doubts and refusals the case needs), reads it through `arrival_join.gather`, and decides it. ``expect`` is
``join`` or the reason the rule must refuse with. A *scene* is the same decision over plain data (`arrival_join.Case`), drawn at
random with the truth known from how it was drawn.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

LI = "https://www.linkedin.com/in"
HOLDER_DAY = date(2026, 11, 10)
TODAY = date(2026, 11, 24)


def d(delta: int) -> str:
    return (HOLDER_DAY + timedelta(days=delta)).isoformat()


@dataclass
class Scene:
    """One scratch world. ``conns``: ``(first, last, slug, company, position, day, precision, headline)``; ``cards``:
    ``(given, family, first_seen or None)``."""
    holder: str = "Sam"
    holder_days: tuple = (HOLDER_DAY.isoformat(),)
    holder_fm: dict = field(default_factory=dict)
    holder_source: str | None = None         # the episode's `source` (default: a conversation)
    holder_extra_fm: dict = field(default_factory=dict)    # the episode's own frontmatter (a note's created_at ...)
    holder_claims: list = field(default_factory=list)      # (predicate, object)
    conns: list = field(default_factory=list)
    cards: list = field(default_factory=list)
    connections_read: str = "2026-11-24"
    cards_synced: str = "2026-11-24"
    extra_pages: list = field(default_factory=list)        # (id, frontmatter)
    held_lines: list = field(default_factory=list)
    doubt: bool = False
    rejected: list = field(default_factory=list)
    refused_arrivals: list = field(default_factory=list)   # (holder, folded full name)
    owner: str | None = None


@dataclass
class Trap:
    id: str
    why: str
    scene: Scene
    expect: str            # "join" or a reason


def conn(first="Sam", last="Okafor", day=None, *, slug=None, company="", position="", precision="day", headline=""):
    return (first, last, slug if slug is not None else f"{first}-{last}".lower(), company, position, day, precision, headline)


def _git(bank: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True)


def build(root: Path, scene: Scene) -> Path:
    """The scratch bank of one scene, committed. ``CICADA_HOME`` must already point under ``root``."""
    from api.services import (contacts_local, linkedin_people, markdown_parser, merge_rejections, pending_store, people_directory,
                              predicates, same_name_doubts)
    from api.services.claims import Claim, write_claims

    bank = root / "bank"
    for sub in ("entities", "episodes", "inbox"):
        (bank / sub).mkdir(parents=True, exist_ok=True)
    predicates.install_predicate_map(bank)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "bench@example.com")
    _git(bank, "config", "user.name", "bench")

    def page(pid: str, name: str, body: str = "## Summary\nA synthetic person.\n", **fm) -> None:
        meta = {"name": name, "type": "person", "status": "active", "confidence": 0.8, "created": "2026-10-01",
                "last_referenced": "2026-11-14", "source_episodes": [], "related": [], "version": 1, **fm}
        markdown_parser.write(bank / "entities" / f"{pid}.md", meta, body)

    episodes = []
    for n, day in enumerate(scene.holder_days, start=1):
        eid = f"ep_{day}_{n:03d}"
        fm = {"id": eid, "timestamp": f"{day}T12:00:00+00:00", "processed": True, "harness": "claude-code",
              **({"source": scene.holder_source} if scene.holder_source else {}), **scene.holder_extra_fm}
        markdown_parser.write(bank / "episodes" / f"{eid}.md", fm, f"user: I met {scene.holder} at the event\n")
        episodes.append(eid)
    from api.services.id_utils import sanitize_id

    hid = sanitize_id(scene.holder)
    body = "## Summary\nA synthetic person met at an event.\n"
    if scene.holder_claims:
        claims = [Claim(id=f"clm_{hid}_{i}", text=f"{scene.holder} {pred} {obj}", subject=hid, predicate=pred, object=obj,
                        object_kind="literal", observer="user", context="career", epistemic="explicit", source_trust="user",
                        confidence=0.9, valid_from="2026-11-10", recorded_at="2026-11-10")
                  for i, (pred, obj) in enumerate(scene.holder_claims)]
        body = write_claims(body, claims)
    page(hid, scene.holder, body, source_episodes=episodes, **scene.holder_fm)
    if scene.owner:
        page("owner-page", scene.owner, owner=True)
    for pid, fm in scene.extra_pages:
        page(pid, fm.get("name", pid), **{k: v for k, v in fm.items() if k != "name"})
    if scene.held_lines:
        pending_store.save(bank, [pending_store.PendingEntity(name=n, type="person", description="", source_episode="",
                                                              confidence=0.5, tags=[], history_entries=[])
                                  for n in scene.held_lines])
    if scene.doubt:
        same_name_doubts.add_pairs(bank, [(hid, f"{hid}-2")])
    for a, b in scene.rejected:
        merge_rejections.add_rejected(bank, a, b)
    from api.services import arrival_join

    for holder, full in scene.refused_arrivals:
        merge_rejections.add_arrival_refusal(bank, holder, arrival_join.key_hash(full), on="2026-11-12")
    if scene.conns:
        rows = [linkedin_people.Connection(f, l, f"{LI}/{slug}" if slug else None, co, pos, day, hl, prec if day else None)
                for f, l, slug, co, pos, day, prec, hl in scene.conns]
        linkedin_people.save_directory(bank.name, rows, scene.connections_read)
    if scene.cards:
        people_directory.ensure(bank.name)
        waiting = [{"id": f"card-{i}", "given_name": g, "family_name": f} for i, (g, f, _) in enumerate(scene.cards)]
        contacts_local.save_waiting(bank.name, waiting)
        seen = {contacts_local.card_hash(f"card-{i}"): day for i, (_, _, day) in enumerate(scene.cards)}
        people_directory.save_json(bank.name, contacts_local.SEEN_FILE, {"v": 1, "synced_on": scene.cards_synced, "seen": seen})
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "fixture")
    return bank


def decide_scene(scene: Scene) -> tuple[str, str]:
    """``("join", "ok")`` or ``("skip", reason)`` for the scene's one first-name page, with the veto answering "fits"."""
    from api.services import arrival_join

    with tempfile.TemporaryDirectory(prefix="arrival-battery-") as tmp:
        root = Path(tmp)
        os.environ["CICADA_HOME"] = str(root / "home")
        bank = build(root, scene)
        gathered = arrival_join.gather(bank)
        from api.services.id_utils import sanitize_id

        wanted = [c for c in gathered.cases if c.holder.page == sanitize_id(scene.holder)]
        if not wanted:
            return ("skip", "no_namesake")
        case = wanted[0]
        first = arrival_join.decide(case)
        if first.outcome == "candidate":
            cases = arrival_join.with_pairs(bank, [case], [first])
            first = arrival_join.decide(cases[0], arrival_join.Veto(("fits", "fits")))
        return (first.outcome, first.reason)


# --------------------------------------------------------------------------- the traps


def traps() -> list[Trap]:
    A = conn("Sam", "Okafor", d(2))
    t: list[Trap] = []

    def add(id_: str, why: str, scene: Scene, expect: str) -> None:
        t.append(Trap(id_, why, scene, expect))

    add("true-match", "one holder, one same-week arrival, nothing against it: the case it exists for", Scene(conns=[A]), "join")
    add("true-match-card", "the arrival is an address-book card first seen in the week", Scene(cards=[("Sam", "Okafor", d(2))]), "join")
    add("card-and-connection-one-lead", "a card and a connection of one full name are one lead",
        Scene(conns=[A], cards=[("Sam", "Okafor", d(3))]), "join")
    add("two-connections-same-week", "two people of one given name connected the same week",
        Scene(conns=[A, conn("Sam", "Adeyemi", d(4))]), "two_arrivals")
    add("connection-and-card-other-names", "a connection and a card of other full names the same week",
        Scene(conns=[A], cards=[("Sam", "Berg", d(3))]), "two_arrivals")
    add("known-full-name-page", "a page already carries the full name", Scene(conns=[A], extra_pages=[("sam-okafor", {"name": "Sam Okafor"})]),
        "other_holder")
    add("second-held-person", "a held person line of that given name", Scene(conns=[A], held_lines=["Sam Berg"]), "other_holder")
    add("second-page-same-word", "another page titled by the word", Scene(conns=[A], extra_pages=[("sam-2", {"name": "Sam"})]),
        "other_holder")
    add("day-7", "exactly seven days apart joins", Scene(conns=[conn("Sam", "Okafor", d(7))]), "join")
    add("day--7", "seven days before joins", Scene(conns=[conn("Sam", "Okafor", d(-7))]), "join")
    add("day-8", "eight days apart does not", Scene(conns=[conn("Sam", "Okafor", d(8))]), "no_arrival")
    add("week-precision", "a row known only to the week is never the arrival", Scene(conns=[conn("Sam", "Okafor", d(2), precision="week")]),
        "no_arrival")
    add("month-precision", "a row known only to the month is never the arrival", Scene(conns=[conn("Sam", "Okafor", d(2), precision="month")]),
        "no_arrival")
    add("fuzzy-namesake-overlaps", "an overlapping fuzzy namesake blocks the true match",
        Scene(conns=[A, conn("Sam", "Adeyemi", d(30), precision="month")]), "namesake_block")
    add("undated-linked-namesake", "a namesake with a link and no day could be the one",
        Scene(conns=[A, conn("Sam", "Adeyemi", None)]), "namesake_block")
    add("namesake-20-days", "a namesake connected three weeks from the holder's day blocks",
        Scene(conns=[A, conn("Sam", "Adeyemi", d(20))]), "namesake_block")
    add("dormant-old-namesake", "a namesake connected years ago is not new and does not block",
        Scene(conns=[A, conn("Sam", "Adeyemi", d(-900))]), "join")
    add("dormant-card-namesake", "an unstamped card is dormant and does not block",
        Scene(conns=[A], cards=[("Sam", "Adeyemi", None)]), "join")
    add("first-mention-untimed", "the only mention is in a source that is no time signal",
        Scene(conns=[A], holder_source="agent_relay"), "no_day")
    add("first-mention-tab-group", "the only mention is a tab group's filing label",
        Scene(conns=[A], holder_source="tab-group"), "no_day")
    add("page-first-said-months-earlier", "the page's first day is months before the arrival",
        Scene(conns=[A], holder_days=("2026-05-01", d(0))), "no_arrival")
    add("old-note-edited-this-week", "a long-lived note edited this week has no day",
        Scene(conns=[A], holder_source="apple-notes", holder_extra_fm={"origin": "apple-notes", "created_at": "2025-01-04T08:00:00+00:00"}),
        "no_day")
    add("living-note", "a note begun two weeks before its last edit is a living note",
        Scene(conns=[A], holder_source="apple-notes", holder_extra_fm={"origin": "apple-notes", "created_at": "2026-10-20T08:00:00+00:00"}),
        "no_day")
    add("new-note", "a note begun on the day it was written is a dated mention",
        Scene(conns=[A], holder_source="apple-notes", holder_extra_fm={"origin": "apple-notes", "created_at": f"{d(0)}T08:00:00+00:00"}),
        "join")
    add("note-with-no-creation-day", "an older app never sent a creation day: the note has none",
        Scene(conns=[A], holder_source="apple-notes", holder_extra_fm={"origin": "apple-notes"}), "no_day")
    add("owner-given-name", "the owner's own first name is never a holder", Scene(conns=[A], holder_fm={"owner": True}), "holder_owner")
    add("owner-namesake-page", "a different page is the owner's; the first-name page stays a holder",
        Scene(conns=[A], owner="Pat Owner"), "join")
    add("relation-titled", "a page titled by a relation to the owner is never a holder",
        Scene(holder="Partner", conns=[conn("Partner", "Okafor", d(2))], holder_fm={"unnamed": True}), "holder_role")
    add("role-word", "a role word as the first name", Scene(holder="Mom", conns=[conn("Mom", "Okafor", d(2))]), "holder_role")
    add("same-name-doubt", "the bank holds a same-name doubt for the first name", Scene(conns=[A], doubt=True), "doubt")
    add("split-pair", "the person called the pair two", Scene(conns=[A], refused_arrivals=[("sam", "sam okafor")]), "history")
    add("alias-the-person-removed", "the person removed this name from the page before",
        Scene(conns=[A], holder_fm={"aliases_removed": [{"alias": "Sam Okafor", "by": "user", "on": "2026-11-01"}]}), "history")
    add("undo-then-rerun", "after the person's Not them, the same pair never joins again",
        Scene(conns=[A], refused_arrivals=[("sam", "sam okafor")]), "history")
    add("page-names-another-profile", "the page already lists another LinkedIn profile",
        Scene(conns=[A], holder_fm={"sources": [{"ref": f"{LI}/someone-else", "kind": "url", "predicate": "linkedin",
                                                 "added_by": "user", "accepted": True}]}), "profile_elsewhere")
    add("page-has-a-full-name-already", "the page already carries another full name", Scene(conns=[A], holder_fm={"aliases": ["Sam Berg"]}),
        "full_name_alias")
    add("arrival-already-a-page", "the full name already belongs to a page under another title",
        Scene(conns=[A], extra_pages=[("okafor", {"name": "Okafor", "aliases": ["Okafor Sam"]})]), "full_name_has_page")
    add("stale-directory", "the directory was last looked at before the week ended", Scene(conns=[A], connections_read=d(5)),
        "directory_not_fresh")
    add("stale-cards", "the address book was last synced before the week ended", Scene(conns=[A], cards=[("Pat", "Lee", None)], cards_synced=d(3)),
        "directory_not_fresh")
    add("two-linkless-rows", "two linkless rows of one name", Scene(conns=[conn("Sam", "Okafor", d(2), slug=""), conn("Sam", "Okafor", d(3), slug="")]),
        "two_arrivals")
    add("non-ascii-name", "a name in another script is its own token and still joins only on equality",
        Scene(holder="José", conns=[conn("José", "Okafor", d(2))]), "join")
    add("plain-word-name", "a name that is also a plain word still needs every rule", Scene(holder="Will", conns=[conn("Will", "Okafor", d(2))]),
        "join")
    add("company-conflict", "the page names one employer, the row another",
        Scene(conns=[conn("Sam", "Okafor", d(2), company="Beta Logistics")], holder_claims=[("works-at", "Alpha Robotics")]),
        "fact_conflict")
    add("company-agrees", "the page and the row name the same employer",
        Scene(conns=[conn("Sam", "Okafor", d(2), company="Alpha Robotics Inc")], holder_claims=[("works-at", "Alpha Robotics")]), "join")
    add("nickname", "a nickname is a miss on purpose", Scene(holder="Sammy", conns=[conn("Samuel", "Okafor", d(2))]), "no_namesake")
    add("compound-given-name", "a compound given name is a miss on purpose", Scene(holder="Mary", conns=[conn("Mary Ann", "Okafor", d(2))]),
        "no_namesake")
    add("short-word", "a two-letter page title", Scene(holder="Al", conns=[conn("Al", "Okafor", d(2))]), "holder_short_word")
    add("no-family-name", "a row with no family name can never be the arrival", Scene(conns=[conn("Sam", "", d(2))]), "arrival_no_family_name")
    return t


# --------------------------------------------------------------------------- the generated scenes (plain data, no bank)


def _oracle(rows, holder, fresh) -> str:
    """The answer restated with plain integers, written apart from `arrival_join.decide` so that an edit to one that is not made
    to the other shows up here. "join" only for exactly the owner's case."""
    from api.services import arrival_join as aj

    if holder.block or holder.others or holder.doubt or holder.elsewhere or not holder.day:
        return "no"
    base = aj.parse_day(holder.day)
    by_full: dict[str, list] = {}
    for r in rows:
        by_full.setdefault(r.full, []).append(r)
    inside = []
    for full, group in by_full.items():
        days = [(aj.parse_day(r.day) - base).days for r in group if r.day and r.precision == "day"]
        if days and abs(min(days)) <= 7:       # a lead appeared on its earliest day
            inside.append(group)
    people = lambda g: max(sum(r.kind == aj.CONNECTION for r in g), sum(r.kind == aj.CARD for r in g), 1)
    if len(inside) != 1 or people(inside[0]) != 1:
        return "no"
    arrival = inside[0]
    if not arrival[0].full or any(r.page_held or not r.waiting or r.doubt or r.history for r in arrival):
        return "no"
    need = (base + timedelta(days=7)).isoformat()
    if any(stamp is None or stamp < need for stamp in fresh.values()):
        return "no"
    for group in by_full.values():
        if group is arrival:
            continue
        for r in group:
            off = (aj.parse_day(r.day) - base).days if r.day else None
            if off is None:
                if r.kind == aj.CONNECTION and (r.linked or r.dup):
                    return "no"
            elif r.precision == "day" and abs(off) <= 30:
                return "no"
            elif r.precision in ("week", "month") and abs(off) <= 30 + (7 if r.precision == "week" else 30):
                return "no"
    return "join"


def scene_case(rng: random.Random):
    """One random ``(Case, truth)``; the truth is the oracle's, over what was drawn."""
    from api.services import arrival_join as aj

    h_day = d(0)
    rows = []
    for i in range(rng.randint(1, 5)):
        kind = rng.choice((aj.CONNECTION, aj.CARD))
        r = rng.random()
        if i == 0:
            day, prec = d(rng.randint(-8, 8)), "day"
        elif r < 0.3:
            day, prec = d(rng.randint(-1000, -60)), "day"
        elif r < 0.5:
            day, prec = d(rng.choice((rng.randint(8, 31), rng.randint(-31, -8)))), "day"
        elif r < 0.62:
            day, prec = d(rng.randint(-80, 80)), rng.choice(("week", "month"))
        elif r < 0.75:
            day, prec = None, None
        elif r < 0.85:
            day, prec = d(rng.randint(-7, 7)), "day"
        else:
            day, prec = d(rng.randint(-400, -60)), "day"
        linked = kind == aj.CONNECTION and (i == 0 or rng.random() < 0.8)
        rows.append(aj.Row(f"r{i}", kind, "sam", f"sam fam{i}", day, prec, linked=linked,
                           dup=1 if (kind == aj.CONNECTION and not linked and rng.random() < 0.5) else 0))
    flaw = rng.random()
    holder_kw: dict = {}
    fresh = {aj.CONNECTION: "2026-11-24"}
    if flaw < 0.08:
        holder_kw["others"] = 1
    elif flaw < 0.16:
        holder_kw["doubt"] = True
    elif flaw < 0.24:
        fresh = {aj.CONNECTION: d(rng.randint(-20, 8))}
    elif flaw < 0.30:
        holder_kw["elsewhere"] = "profile_elsewhere"
    elif flaw < 0.36:
        first = rows[0]
        rows[0] = aj.Row("r0", first.kind, "sam", first.full, first.day, first.precision, linked=first.linked,
                         history=rng.choice(("removed", "refused", "split")))
    elif flaw < 0.42:
        first = rows[0]
        rows[0] = aj.Row("r0", first.kind, "sam", first.full, first.day, first.precision, linked=first.linked,
                         page_held=True, waiting=False)
    if any(r.kind == aj.CARD for r in rows):
        fresh[aj.CARD] = "2026-11-24"
    holder = aj.Holder("sam", "sam", h_day, "conversation", **holder_kw)
    return aj.Case(holder, tuple(rows), fresh), _oracle(rows, holder, fresh)


def run_scenes(count: int, seed: int) -> dict:
    from api.services import arrival_join as aj

    rng = random.Random(seed)
    out = {"scenes": count, "joined": 0, "should_join": 0, "false_joins": 0, "missed_joins": 0, "reasons": {}}
    bad: list[str] = []
    for i in range(count):
        case, truth = scene_case(rng)
        d_ = aj.decide(case, aj.Veto(("fits", "fits")))
        out["should_join"] += truth == "join"
        out["joined"] += d_.joins
        out["reasons"][d_.reason] = out["reasons"].get(d_.reason, 0) + 1
        if d_.joins and truth != "join":
            out["false_joins"] += 1
            bad.append(f"scene {i}: {d_.reason}")
        if truth == "join" and not d_.joins:
            out["missed_joins"] += 1
            bad.append(f"missed {i}: {d_.reason}")
    out["examples"] = bad[:10]
    return out


def run_traps() -> dict:
    results = []
    for trap in traps():
        outcome, reason = decide_scene(trap.scene)
        got = "join" if outcome == "join" else reason
        results.append({"id": trap.id, "expect": trap.expect, "got": got, "ok": got == trap.expect, "why": trap.why})
    wrong_joins = [r for r in results if r["got"] == "join" and r["expect"] != "join"]
    return {"traps": len(results), "ok": sum(r["ok"] for r in results), "wrong_joins": len(wrong_joins),
            "failed": [r for r in results if not r["ok"]]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--scenes", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    traps_result = run_traps()
    scenes_result = run_scenes(args.scenes, args.seed)
    print(json.dumps({"traps": traps_result, "scenes": scenes_result}, indent=1, default=str))
    return 0 if not traps_result["failed"] and not scenes_result["false_joins"] else 1


if __name__ == "__main__":
    sys.exit(main())
