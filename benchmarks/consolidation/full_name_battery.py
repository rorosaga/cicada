"""Replay battery for Sleep's join of a held full name (`api/services/full_name_join.py`, ruling 74b, 2026-11-24).

Why: Sleep may join "Teodor Brandt" (held on a line) to the page "Teo" itself, on the person's own words, read twice.
A wrong join is the worst error this system makes, so the bar is zero wrong joins on every case where the two names are
two people, and a missed join only leaves the question where it is today. This builds, per case of `full_name_cases.json`,
a small scratch bank (the person's own message, the assistant's reply, the short name's page, the held full name, the
question Stage 2 raised) and runs the product's own `full_name_join.assess` on it ``--repeats`` times with the real
main model: the guards, then the two reads. Nothing is written to the bank by a read; the bank is thrown away.

    api/.venv/bin/python -m benchmarks.consolidation.full_name_battery --repeats 5            # on the Claude plan
    api/.venv/bin/python -m benchmarks.consolidation.full_name_battery --only father --repeats 10

A case is ``one`` (the join is expected) or ``two`` (a join is a wrong join); ``guard`` is what the engine-free guards
must say (``shape``: the model is asked; anything else: it never is). All names are invented.
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

CASES = Path(__file__).with_name("full_name_cases.json")


def load_cases(path: Path = CASES) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(bank: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True)


def build_bank(root: Path, case: dict) -> Path:
    """The scratch bank of one case, committed: owner, the short name's page, the held line, the question."""
    from api.services import bank_index, markdown_parser, pending_store, predicates
    from api.services.claims import Claim, Evidence, write_claims

    bank = root / "bank"
    for sub in ("entities", "episodes", "inbox"):
        (bank / sub).mkdir(parents=True, exist_ok=True)
    predicates.install_predicate_map(bank)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "bench@example.com")
    _git(bank, "config", "user.name", "bench")
    full, short, owner = case["full"], case["short"], case["owner"]

    def page(pid: str, name: str, body: str, **fm) -> None:
        meta = {"name": name, "type": "person", "status": "active", "confidence": 0.8, "created": "2026-10-01",
                "last_referenced": "2026-11-14", "source_episodes": [], "related": [], "version": 1, **fm}
        markdown_parser.write(bank / "entities" / f"{pid}.md", meta, body)

    def episode(eid: str, text: str, **fm) -> None:
        markdown_parser.write(bank / "episodes" / f"{eid}.md", {"id": eid, "timestamp": f"{eid[3:13]}T10:00:00+00:00",
                                                                 "processed": True, "title": "chat", "source": "claude-code", **fm}, text)

    page("owner", owner, f"## Summary\n{owner}, synthetic.\n", owner=True)
    first, second = "ep_2026-10-03_001", "ep_2026-10-22_001"
    episode(first, f"user: {case['turn']}\nassistant: {case['assistant']}\nuser: Thanks.\n")
    episode(second, f"user: {short} wrote to me about the rota.\nassistant: Noted.\n")
    facts = list(case["page_facts"])
    claim = Claim(id="clm_2026-10-22_aaaa0001", text=facts[0], subject=short.lower(), predicate="note", object=facts[0],
                  object_kind="literal", source_episodes=[second])
    page(short.lower(), short, write_claims(f"## Summary\n{facts[0]}\n\n## Key Facts\n" + "\n".join(f"- {f}" for f in facts) + "\n", [claim]),
         source_episodes=[second], aliases=list(case.get("page_aliases") or []))
    for other in case.get("other_pages") or []:
        page(other["id"], other["name"], f"## Summary\n{other['name']}, synthetic.\n")
    held = list(case["held_facts"])
    start = len("user: ") + case["turn"].find(full)
    pending_store.upsert(bank, pending_store.PendingEntity(
        name=full, type="person", description="", source_episode=first, confidence=0.9, tags=[],
        history_entries=[{"date": "2026-10-03", "event": f"{owner} mentioned {full}."}], summary=held[0], key_facts=held[1:],
        aliases=[short],
        held_claims=[Claim(id="clm_2026-10-03_aaaa0002", text=held[0], subject=full.lower().replace(" ", "-"), predicate="note",
                           object=held[0], object_kind="literal", source_episodes=[first],
                           evidence=[Evidence(episode=first, start=max(start, 0), end=max(start, 0) + len(full), kind="user",
                                              hash="0" * 12)]).to_dict()]))
    for other in case.get("other_held") or []:
        pending_store.upsert(bank, pending_store.PendingEntity(
            name=other["name"], type="person", description="", source_episode=second, confidence=0.7, tags=[],
            history_entries=[], aliases=list(other.get("aliases") or [])))
    markdown_parser.write(bank / "inbox" / "inbox-001.md", {
        "kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.6,
        "entity_id": full.lower().replace(" ", "-"), "entity_name": full, "title": f"Is {full} the same as {short}?",
        "uncertainty_type": f"Possible duplicate of {short}", "suggested_confidence": 0.6, "created_date": "2026-11-24",
        "source_episode": first, "merge_target_hint": short.lower()},
        f"A conversation also called {full} “{short}”, the name {short}'s page carries.")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "case")
    bank_index.invalidate(bank)
    return bank


async def run_case(case: dict, repeats: int, judge) -> dict:
    from api.services import full_name_join as fnj, markdown_parser

    with tempfile.TemporaryDirectory(prefix="full-name-case-") as tmp:
        bank = build_bank(Path(tmp), case)
        path = bank / "inbox" / "inbox-001.md"
        fm = dict(markdown_parser.parse(path).frontmatter)
        guard_case, why = fnj.guards(bank, path, fm)
        row = {"id": case["id"], "kind": case["kind"], "guard": "shape" if guard_case else why, "expected_guard": case.get("guard", "shape"),
               "runs": repeats, "outcomes": Counter(), "calls": 0, "wrong_joins": 0, "joins": 0}
        if guard_case is None:
            row["outcomes"]["skip"] = repeats
            return row
        for _ in range(repeats):
            result = await fnj.assess(bank, path, fm, judge, speaker=case["owner"])
            row["outcomes"][result.outcome] += 1
            row["calls"] += result.reads
        row["joins"] = row["outcomes"].get("join", 0)
        row["wrong_joins"] = row["joins"] if case["kind"] == "two" else 0
        return row


def report(rows: list[dict]) -> str:
    out = []
    for r in rows:
        shown = ", ".join(f"{k} {v}" for k, v in sorted(r["outcomes"].items()))
        out.append(f"{r['kind']:3} {r['id']:26} joined {r['joins']:>2}/{r['runs']}  [{shown}]  calls {r['calls']}"
                   + ("" if r["guard"] == r["expected_guard"] else f"  GUARD {r['guard']} (expected {r['expected_guard']})"))
    ones = [r for r in rows if r["kind"] == "one"]
    twos = [r for r in rows if r["kind"] == "two"]
    out.append(f"WRONG JOINS (two people joined): {sum(r['wrong_joins'] for r in twos)}/{sum(r['runs'] for r in twos)}   "
               f"TRUE JOINS made: {sum(r['joins'] for r in ones)}/{sum(r['runs'] for r in ones)}   "
               f"model calls {sum(r['calls'] for r in rows)}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--repeats", type=int, default=5)
    p.add_argument("--cases", type=Path, default=CASES)
    p.add_argument("--only", default="", help="substring of case ids")
    p.add_argument("--engine", choices=("plan", "key"), default="plan")
    p.add_argument("--model", default="sonnet", help="the main model's tier")
    p.add_argument("--key-file", type=Path, default=Path("~/.cicada/secrets.env"))
    p.add_argument("--json", type=Path, help="write the rows here")
    a = p.parse_args(argv)
    from benchmarks.engine_parity import _leg_environment, settings_for

    if a.engine == "key":
        from benchmarks.consolidation.same_name_battery import key_from

        os.environ["ANTHROPIC_API_KEY"] = key_from(a.key_file)
    cases = [c for c in load_cases(a.cases) if a.only in c["id"]]
    root = Path(tempfile.mkdtemp(prefix="full-name-battery-"))
    home, scratch = root / "home", root / "scratch"
    home.mkdir()
    scratch.mkdir()
    rows = []
    with _leg_environment(home, scratch):
        from api.services import full_name_join, same_name_tend
        from benchmarks.consolidation.run import engine_model

        settings = settings_for("plan" if a.engine == "plan" else "key", scratch, model=engine_model(a.engine, a.model),
                                judge=engine_model(a.engine, a.model))
        strong = same_name_tend.main_tier(settings)

        async def judge(system: str, prompt: str) -> object:
            return await full_name_join.ask_main(strong, system, prompt)

        for case in cases:
            rows.append(asyncio.run(run_case(case, a.repeats, judge)))
            print(report(rows[-1:]).splitlines()[0], flush=True)
    print(report(rows))
    if a.json:
        a.json.write_text(json.dumps([{**r, "outcomes": dict(r["outcomes"])} for r in rows], indent=1, ensure_ascii=False))
    return 0 if not any(r["wrong_joins"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
