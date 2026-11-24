"""Replay battery for Sleep's join of a plain misspelling (`api/services/typo_join.py`, ruling 74c, 2026-11-24).

Why: Sleep may join "Marizol Quinn" (held on a line, or a page of its own) to the page "Marisol Quinn" itself when the
record shows the same fact about both, read twice. A wrong join is the worst error this system makes, so the bar is zero
wrong joins on every case where the two names are two people (siblings, a parent and a child, two colleagues, a name near
two pages, two names a conversation names together, a nickname); a missed join only leaves things as they are today. This
builds, per case of `typo_cases.json`, a small scratch bank and runs the product's own `typo_join` guards and reads
(`assess`) ``--repeats`` times with the real main model. Nothing is written to the bank by a read; the bank is thrown away.

    api/.venv/bin/python -m benchmarks.consolidation.typo_battery --repeats 3 --model haiku      # on the Claude plan

A case is ``one`` (the join is expected) or ``two`` (a join is a wrong join); ``guard`` is what the engine-free guards
must say (default ``shape``: the model is asked; anything else: it never is). All names are invented.
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

CASES = Path(__file__).with_name("typo_cases.json")
FILLER = ["Orla Hale", "Pavel Ruiz", "Greta Lindqvist", "Tomas Okafor", "Hana Weber", "Ruben Castillo", "Ilse Brandt", "Omar Haddad",
          "Petra Novotny", "Luis Ferreira", "Anya Volkov", "Jonas Berg", "Selin Kaya", "Felix Morgan", "Ada Lovell", "Viktor Hahn",
          "Nadia Rossi", "Emil Strand", "Zoe Whitaker", "Karim Nasser", "Lotte Jansen", "Mateo Ibarra", "Freya Nilsson", "Cyrus Bell"]


def load_cases(path: Path = CASES) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(bank: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True)


def build_bank(root: Path, case: dict) -> Path:
    from api.services import bank_index, markdown_parser, pending_store, predicates
    from api.services.claims import Claim, write_claims

    bank = root / "bank"
    for sub in ("entities", "episodes", "inbox"):
        (bank / sub).mkdir(parents=True, exist_ok=True)
    predicates.install_predicate_map(bank)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "bench@example.com")
    _git(bank, "config", "user.name", "bench")

    def page(pid: str, name: str, body: str, **fm) -> None:
        meta = {"name": name, "type": "person", "status": "active", "confidence": 0.8, "created": "2026-10-01",
                "last_referenced": "2026-11-14", "source_episodes": [], "related": [], "version": 1, **fm}
        markdown_parser.write(bank / "entities" / f"{pid}.md", meta, body)

    def episode(eid: str, text: str) -> None:
        markdown_parser.write(bank / "episodes" / f"{eid}.md", {"id": eid, "timestamp": f"{eid[3:13]}T10:00:00+00:00",
                                                                 "processed": True, "title": "chat", "source": "claude-code"}, text)

    def claim(cid: str, subject: str, text: str, ep: str, predicate: str) -> Claim:
        return Claim(id=cid, text=text, subject=subject, predicate=predicate, object=text, object_kind="literal",
                     source_episodes=[ep])

    a, b, owner = case["a"], case["b"], case["owner"]
    a_id, b_id = a.lower().replace(" ", "-"), b.lower().replace(" ", "-")
    page("owner", owner, f"## Summary\n{owner}, synthetic.\n", owner=True)
    # A bank of a real size (the shared-fact floor tells a common word from a rare one by how many pages say it): the
    # people around the person, each said to be a colleague at the office, so "is a colleague" is common ground here.
    for i, who in enumerate(FILLER):
        page(f"filler-{i:02d}", who, f"## Summary\n{who} is a colleague at the office and joins the weekly team call.\n")
    e_b, e_a = "ep_2026-10-22_001", "ep_2026-11-14_001"
    episode(e_b, f"user: {case['b_turn']}\nassistant: Noted.\n")
    episode(e_a, f"user: {case['a_turn']}\nassistant: Great.\n")
    page(b_id, b, write_claims(f"## Summary\n{b}, synthetic.\n", [claim("clm_2026-10-22_aaaa0001", b_id, case["b_fact"], e_b, "note-b")]),
         source_episodes=[e_b], **({"aliases_removed": case["b_removed"]} if case.get("b_removed") else {}))
    for other in case.get("other_pages") or []:
        page(other["id"], other["name"], f"## Summary\n{other['name']}, synthetic.\n")
    heard = []
    if case.get("together"):
        episode("ep_2026-11-20_001", f"user: {case['together']}\nassistant: Nice.\n")
        heard = [{"episode": "ep_2026-11-20_001"}]
    if case["form"] == "pages":
        page(a_id, a, write_claims(f"## Summary\n{a}, synthetic.\n", [claim("clm_2026-11-14_bbbb0002", a_id, case["a_fact"], e_a, "note-a")]),
             source_episodes=[e_a])
        markdown_parser.write(bank / "inbox" / "inbox-001.md", {
            "kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.4, "entity_id": a_id,
            "entity_name": a, "title": f"Is {a} the same as {b}?", "created_date": "2026-11-24", "merge_target_hint": b_id,
            "detected": "person_duplicate"}, "They may be one person; asked, never joined: only your answer joins them.")
    else:
        pending_store.upsert(bank, pending_store.PendingEntity(
            name=a, type="person", description="", source_episode=e_a, confidence=0.9, tags=[],
            history_entries=[{"date": "2026-11-14", "event": f"{owner} mentioned {a}."}],
            held_claims=[claim("clm_2026-11-14_bbbb0002", a_id, case["a_fact"], e_a, "note-a").to_dict()], aliases=[], heard_in=heard))
        if case.get("apart"):
            pending_store.mark_apart(bank, a, [b_id])   # the person said "No, different" to this held mention
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "case")
    bank_index.invalidate(bank)
    return bank


async def run_case(case: dict, repeats: int, judge) -> dict:
    from api.services import markdown_parser, typo_join

    with tempfile.TemporaryDirectory(prefix="typo-case-") as tmp:
        bank = build_bank(Path(tmp), case)
        cands = typo_join.candidates(bank) + typo_join.held_candidates(bank)
        row = {"id": case["id"], "kind": case["kind"], "expected_guard": case.get("guard", "shape"), "runs": repeats,
               "outcomes": Counter(), "calls": 0, "wrong_joins": 0, "joins": 0}
        if not cands:
            row["guard"] = "not_a_candidate"
            row["outcomes"]["skip"] = repeats
            return row
        path, fm = cands[0]
        guard_case, why = typo_join.guards(bank, path, fm)
        row["guard"] = "shape" if guard_case else why
        if guard_case is None:
            row["outcomes"]["skip"] = repeats
            return row
        for _ in range(repeats):
            result = await typo_join.assess(bank, path, fm, judge, speaker=case["owner"])
            row["outcomes"][result.outcome] += 1
            row["calls"] += result.reads
        row["joins"] = row["outcomes"].get("join", 0)
        row["wrong_joins"] = row["joins"] if case["kind"] == "two" else 0
        return row


def report(rows: list[dict]) -> str:
    out = []
    for r in rows:
        shown = ", ".join(f"{k} {v}" for k, v in sorted(r["outcomes"].items()))
        out.append(f"{r['kind']:3} {r['id']:28} joined {r['joins']:>2}/{r['runs']}  [{shown}]  calls {r['calls']}"
                   + ("" if r["guard"] == r["expected_guard"] else f"  GUARD {r['guard']} (expected {r['expected_guard']})"))
    ones = [r for r in rows if r["kind"] == "one"]
    twos = [r for r in rows if r["kind"] == "two"]
    out.append(f"WRONG JOINS (two people joined): {sum(r['wrong_joins'] for r in twos)}/{sum(r['runs'] for r in twos)}   "
               f"TRUE JOINS made: {sum(r['joins'] for r in ones)}/{sum(r['runs'] for r in ones)}   "
               f"model calls {sum(r['calls'] for r in rows)}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--cases", type=Path, default=CASES)
    p.add_argument("--only", default="", help="substring of case ids")
    p.add_argument("--model", default="haiku", help="the main model's tier")
    p.add_argument("--json", type=Path, help="write the rows here")
    a = p.parse_args(argv)
    from benchmarks.engine_parity import _leg_environment, settings_for

    os.environ.pop("ANTHROPIC_API_KEY", None)   # `claude -p` must bill the plan, never a key found in the environment
    cases = [c for c in load_cases(a.cases) if a.only in c["id"]]
    root = Path(tempfile.mkdtemp(prefix="typo-battery-"))
    home, scratch = root / "home", root / "scratch"
    home.mkdir()
    scratch.mkdir()
    rows = []
    from benchmarks.consolidation import engines

    with _leg_environment(home, scratch), engines.tally() as counted:
        from api.services import full_name_join, same_name_tend
        from benchmarks.consolidation.run import engine_model

        settings = settings_for("plan", scratch, model=engine_model("plan", a.model), judge=engine_model("plan", a.model))
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
    return 0 if not any(r["wrong_joins"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
