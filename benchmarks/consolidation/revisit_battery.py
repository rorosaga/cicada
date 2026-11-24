"""Battery for Sleep's second look at open questions (`api/services/question_revisit.py`, ruling 81, 2026-11-24).

Why: Sleep may now close a question the record answers, by itself: two people pages it reads as one person (on a located
line, or two kinds of evidence, read twice by the engine's main model), and a conflict or "who is it?" the person's own
newest words answer. A wrong close tells the person things that are not so, so the bar is ZERO wrong settles on every
labelled case, and a question left open only costs today's state. This builds, per case of `revisit_cases.json`, a small
scratch bank (invented names) and runs the product's own step on it ``--repeats`` times with the real main model:

* ``pair`` cases: `question_revisit.assess` (the guards, then the reads); nothing is written, the bank is thrown away;
* ``conflict`` / ``clarification`` cases: `question_revisit.tend` for real (a read, a second read, the settle), then the bank
  says what was settled and how;
* ``decay`` cases: the engine-free policy only (a later mention is the answer; no model).

    api/.venv/bin/python -m benchmarks.consolidation.revisit_battery --repeats 3            # on the Claude plan
    api/.venv/bin/python -m benchmarks.consolidation.revisit_battery --only owner --repeats 5

A case is ``one`` (a settle is expected) or ``two``/``none`` (a settle is a wrong settle). Prints, per case, the outcomes and the
model calls, then settles made, WRONG settles and questions left, and the calls per question read. All names are invented.
The plan's numbers on haiku are a floor: the product runs a stronger main model.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

CASES = Path(__file__).with_name("revisit_cases.json")


def _git(bank: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True)


def _bank(root: Path) -> Path:
    from api.services import markdown_parser, predicates

    bank = root / "bank"
    for sub in ("entities", "episodes", "inbox"):
        (bank / sub).mkdir(parents=True, exist_ok=True)
    predicates.install_predicate_map(bank)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "bench@example.com")
    _git(bank, "config", "user.name", "bench")
    markdown_parser.write(bank / "entities" / "owner.md", {
        "name": "Mira Kolar", "type": "person", "owner": True, "status": "active", "confidence": 0.9, "created": "2026-10-01",
        "last_referenced": "2026-11-14", "source_episodes": [], "related": [], "version": 1}, "## Summary\nMira Kolar, synthetic.\n")
    return bank


def _page(bank: Path, pid: str, name: str, body: str, **fm) -> None:
    from api.services import markdown_parser

    meta = {"name": name, "type": "person", "status": "active", "confidence": 0.8, "created": "2026-10-01",
            "last_referenced": "2026-11-14", "source_episodes": [], "related": [], "version": 1, **fm}
    markdown_parser.write(bank / "entities" / f"{pid}.md", meta, body)


def _episode(bank: Path, eid: str, text: str) -> None:
    from api.services import markdown_parser

    markdown_parser.write(bank / "episodes" / f"{eid}.md", {
        "id": eid, "timestamp": f"{eid[3:13]}T10:00:00+00:00", "processed": True, "title": "chat", "source": "claude-code"}, text)


def _finish(bank: Path) -> None:
    from api.services import bank_index

    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "case")
    bank_index.invalidate(bank)


def build_pair(root: Path, case: dict) -> Path:
    """One scratch bank for a pair case. Optional keys of the case: a page's ``aliases``; ``history`` (conversations each page
    lists of its own, none naming both: the owner's pages list far more than a read can show); an episode with ``"listed":
    false`` (a conversation neither page lists yet: where a later denial lives); ``bank_pages`` (concept pages around the
    pair, so a bank can tell a rare word from a common one) of which the first five carry ``mention``."""
    from api.services import markdown_parser

    bank = _bank(root)
    eps = [e["id"] for e in case["episodes"] if e.get("listed", True)]
    for e in case["episodes"]:
        _episode(bank, e["id"], e["text"])
    for i in range(int(case.get("bank_pages", 24))):
        body = f"## Summary\nNote number {i} about the harbour garden.\n" + (f"\n{case['mention']}\n" if case.get("mention") and i < 5 else "")
        _page(bank, f"filler-{i}", f"Filler Topic {i}", body, type="concept")
    a, b = case["pages"]
    for n, page in enumerate((a, b)):
        own = []
        for i in range(int(case.get("history", 0))):
            eid = f"ep_2026-09-{i + 1:02d}_{n + 1:03d}"
            _episode(bank, eid, f"user: {page['name']} came by on day {i + 1}.\n")
            own.append(eid)
        body = "## Summary\n" + page["facts"][0] + "\n\n## Key Facts\n" + "\n".join(f"- {f}" for f in page["facts"]) + "\n"
        extra = {"aliases": page["aliases"]} if page.get("aliases") else {}
        _page(bank, page["id"], page["name"], body, source_episodes=[*own, *eps], **extra)
    markdown_parser.write(bank / "inbox" / "inbox-001.md", {
        "kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.6, "entity_id": a["id"],
        "entity_name": a["name"], "title": f"Are {a['name']} and {b['name']} the same person?", "created_date": "2026-11-01",
        "merge_target_hint": b["id"], "detected": "person_duplicate", "signals": ["short_in_full"],
        "source_episode": case["source"]}, "Why this is asked: one name is part of the other.")
    _finish(bank)
    return bank


def build_record(root: Path, case: dict) -> Path:
    from api.services import markdown_parser
    from api.services.claims import Claim, Evidence, write_claims

    bank = _bank(root)
    if case["group"] == "conflict":
        old = Claim(id="clm_old", text=f"Mira lives in {case['value_a']}", subject="mira-friend", predicate="lives-in",
                    object=case["value_a"], valid_from="2026-05-01", recorded_at="2026-05-01",
                    evidence=[Evidence(episode="ep_2026-05-01_001", kind="user")])
        new = Claim(id="clm_new", text=f"Mira lives in {case['value_b']}", subject="mira-friend", predicate="lives-in",
                    object=case["value_b"], valid_from="2026-05-01", recorded_at="2026-05-01",
                    evidence=[Evidence(episode="ep_2026-05-01_002", kind="user")])
        _episode(bank, "ep_2026-05-01_001", f"user: My friend Ana Reyes lives in {case['value_a']}.\n")
        _episode(bank, "ep_2026-05-01_002", f"user: My friend Ana Reyes lives in {case['value_b']}.\n")
        _page(bank, "ana-reyes", "Ana Reyes", write_claims("## Summary\nAna Reyes, a friend.\n", [old, new]),
              source_episodes=["ep_2026-05-01_001", "ep_2026-05-01_002"])
        markdown_parser.write(bank / "inbox" / "inbox-002.md", {
            "kind": "conflict", "status": "pending", "priority": 0.5, "created_date": "2026-05-02", "entity_id": "ana-reyes",
            "entity_name": "Ana Reyes", "predicate": "lives-in", "question": "Where does Ana Reyes live?",
            "options": [{"key": "a", "label": case["value_a"], "claim_id": "clm_old"},
                        {"key": "b", "label": case["value_b"], "claim_id": "clm_new"}, {"key": "both", "label": "Both"}]}, "Context.")
        if case["later"]:
            _episode(bank, "ep_2026-10-01_001", case["later"])
    elif case["group"] == "clarification":
        name = case["name"]
        _page(bank, name.lower(), name, f"## Summary\n{name}.\n", type="tool", source_episodes=["ep_2026-09-01_001"])
        _episode(bank, "ep_2026-09-01_001", f"user: I used {name} again today.\n")
        markdown_parser.write(bank / "inbox" / "inbox-003.md", {
            "kind": "clarification", "status": "pending", "priority": 0.5, "created_date": "2026-09-02", "entity_id": name.lower(),
            "entity_name": name, "title": f"Who or what is {name}?", "question": f"Who or what is {name}?",
            "source_episode": "ep_2026-09-01_001"}, "Context.")
        _episode(bank, "ep_2026-10-01_001", case["later"])
    else:   # decay
        status, conf = ("active", 0.8) if case["mentioned"] else ("decaying", 0.35)
        _page(bank, "harbour-quartet", "Harbour Quartet", "## Summary\nA quartet.\n", type="project", status=status,
              confidence=conf, source_episodes=["ep_2026-05-01_001"])
        _episode(bank, "ep_2026-05-01_001", "user: The Harbour Quartet rehearses on Thursdays.\n")
        markdown_parser.write(bank / "inbox" / "inbox-004.md", {
            "kind": "decay", "status": "pending", "priority": 0.4, "created_date": "2026-09-01", "entity_id": "harbour-quartet",
            "entity_name": "Harbour Quartet"}, "Fading?")
    _finish(bank)
    return bank


async def run_pair(case: dict, repeats: int, llm_fn, settings, speaker: str) -> dict:
    from api.services import markdown_parser, question_revisit as qr

    row = {"id": case["id"], "group": "pair", "kind": case["kind"], "runs": repeats, "outcomes": Counter(), "calls": 0,
           "reads": 0, "settles": 0, "wrong": 0, "left": 0}
    with tempfile.TemporaryDirectory(prefix="revisit-case-") as tmp:
        bank = build_pair(Path(tmp), case)
        path = bank / "inbox" / "inbox-001.md"
        fm = dict(markdown_parser.parse(path).frontmatter)
        judge = qr._judge_from(llm_fn)
        for _ in range(repeats):
            result = await qr.assess(bank, path, fm, judge, speaker=speaker)
            row["outcomes"][result.outcome + (f":{result.why}" if result.outcome == "skip" else "")] += 1
            row["calls"] += result.reads
            row["reads"] += 1 if result.reads else 0
            if result.outcome == "join":
                row["settles"] += 1
                row["wrong"] += 1 if case["kind"] != "one" else 0
            else:
                row["left"] += 1
    return row


async def run_record(case: dict, repeats: int, llm_fn, make_settings) -> dict:
    from api.services import question_revisit as qr, web_settle

    row = {"id": case["id"], "group": case["group"], "kind": case["kind"], "runs": repeats, "outcomes": Counter(), "calls": 0,
           "reads": 0, "settles": 0, "wrong": 0, "left": 0}
    for _ in range(repeats):
        with tempfile.TemporaryDirectory(prefix="revisit-case-") as tmp:
            bank = build_record(Path(tmp), case)
            if case["group"] == "decay":
                from api.services import inbox_tend, markdown_parser

                path = bank / "inbox" / "inbox-004.md"
                d, why = inbox_tend.policy(bank, path, dict(markdown_parser.parse(path).frontmatter))
                made = d is not None and d.rule == "not_fading"
                row["outcomes"]["not_fading" if made else f"left:{why or 'rule'}"] += 1
                row["settles"] += 1 if made else 0
                row["wrong"] += 1 if made and case["kind"] != "one" else 0
                row["left"] += 0 if made else 1
                continue
            report = await qr.tend(bank, make_settings(bank), llm_fn, model="haiku")
            row["calls"] += report.calls
            row["reads"] += report.read
            if report.settled:
                rows = web_settle.list_settled(bank)
                answer = str(rows[0].get("answer") or "") if rows else ""
                good = case["kind"] == "one" and (case["group"] != "conflict" or case["pick"].lower() in answer.lower())
                row["outcomes"]["settled:" + ("right" if good else "WRONG")] += 1
                row["settles"] += 1
                row["wrong"] += 0 if good else 1
            else:
                row["outcomes"]["left:" + ",".join(f"{k}={v}" for k, v in sorted((report.by_kind or {}).get(case["group"], {}).items()))] += 1
                row["left"] += 1
    return row


def report(rows: list[dict]) -> str:
    out = []
    for r in rows:
        shown = ", ".join(f"{k} {v}" for k, v in sorted(r["outcomes"].items()))
        out.append(f"{r['group']:13} {r['kind']:4} {r['id']:26} settled {r['settles']:>2}/{r['runs']}  [{shown}]  calls {r['calls']}")
    wrong = sum(r["wrong"] for r in rows)
    made = sum(r["settles"] for r in rows)
    wanted = sum(r["runs"] for r in rows if r["kind"] == "one")
    left = sum(r["left"] for r in rows)
    reads = sum(r["reads"] for r in rows)
    calls = sum(r["calls"] for r in rows)
    out.append(f"SETTLES MADE {made}   WRONG SETTLES {wrong}   LEFT OPEN {left}   (settles wanted {wanted})   "
               f"questions read {reads}, model calls {calls} ({calls / reads:.1f} per question read)" if reads else
               f"SETTLES MADE {made}   WRONG SETTLES {wrong}   LEFT OPEN {left}   no question read")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--cases", type=Path, default=CASES)
    p.add_argument("--only", default="", help="substring of case ids")
    p.add_argument("--kind", default="", help="only cases of this expected kind (one, two or none)")
    p.add_argument("--engine", choices=("plan", "key"), default="plan")
    p.add_argument("--model", default="haiku", help="the main model's tier")
    p.add_argument("--key-file", type=Path, default=Path("~/.cicada/secrets.env"))
    p.add_argument("--json", type=Path, help="write the rows here")
    a = p.parse_args(argv)
    from benchmarks.engine_parity import _leg_environment, settings_for

    if a.engine == "key":
        import os

        from benchmarks.consolidation.same_name_battery import key_from

        os.environ["ANTHROPIC_API_KEY"] = key_from(a.key_file)
    else:
        import os

        os.environ.pop("ANTHROPIC_API_KEY", None)   # `claude -p` must bill the plan, never a key found in the environment
    cases = [c for c in json.loads(a.cases.read_text(encoding="utf-8")) if a.only in c["id"] and (not a.kind or c["kind"] == a.kind)]
    root = Path(tempfile.mkdtemp(prefix="revisit-battery-"))
    home, scratch = root / "home", root / "scratch"
    home.mkdir()
    scratch.mkdir()
    rows = []
    from benchmarks.consolidation import engines

    with _leg_environment(home, scratch), engines.tally() as counted:
        from api.services import inbox_tend, same_name_tend
        from benchmarks.consolidation.run import engine_model

        settings = settings_for("plan" if a.engine == "plan" else "key", scratch, model=engine_model(a.engine, a.model),
                                judge=engine_model(a.engine, a.model))
        strong = same_name_tend.main_tier(settings)
        llm_fn = inbox_tend.default_llm_fn(strong)
        for case in cases:
            if case["group"] == "pair":
                row = asyncio.run(run_pair(case, a.repeats, llm_fn, settings, "Mira Kolar"))
            else:
                row = asyncio.run(run_record(case, a.repeats, llm_fn, lambda bank: settings_for(
                    "plan" if a.engine == "plan" else "key", bank, model=engine_model(a.engine, a.model),
                    judge=engine_model(a.engine, a.model))))
            rows.append(row)
            print(report([row]).splitlines()[0], flush=True)
    print(report(rows).splitlines()[-1])
    print("engine replies:\n" + counted.report())
    if a.json:
        a.json.write_text(json.dumps([{**r, "outcomes": dict(r["outcomes"])} for r in rows], indent=1, ensure_ascii=False))
    return 0 if not any(r["wrong"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
