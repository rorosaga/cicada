"""Replay battery for one conversation that names two people who share a first name (Stage 1, 2026-11-24).

"Nico from work finally met my cousin Nico at the party" is the commonest way a person tells two namesakes apart, and
the same-name step (`same_name_people`) works on one mention per bare first name per conversation. What Stage 1 writes
for it decides everything after: one entity (the two blended, or one lost), a bare name and a qualified one ("Nico" and
"Nico (finance lead)"), two qualified. This replays 11 invented conversations (English, Spanish, French, German; two
relatives and a colleague, two colleagues, a friend and a public figure, a boss and a brother; and two controls where
the two names are ONE person said twice) through the product's own Stage 1 (`entity_extractor.extract`) many times each
and counts the shapes and where each person's facts land.

    api/.venv/bin/python -m benchmarks.consolidation.both_named_battery run --repeats 20 --out OUT
    api/.venv/bin/python -m benchmarks.consolidation.both_named_battery rescore OUT     # no model

``both_named_cases.json``: each case names the shared first name (``name``), and for each of its people (``A``, ``B``)
the words that mark their facts (``people``; the gold of the case, not a rule of the product). The raw answers are kept
(``raw.jsonl``) so Stage 2 can be replayed on them (`both_named_stories`).

Needs ``ANTHROPIC_API_KEY`` in the environment or in ``--key-file`` (never printed). Cost is printed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

CASES = Path(__file__).with_name("both_named_cases.json")


def norm(text: object) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", text).strip()


def load_cases(path: Path = CASES) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def episode_of(case: dict, clock: date, number: int) -> dict:
    day = clock + timedelta(days=case["day"])
    body = "\n".join(f"{'user' if i % 2 == 0 else 'assistant'}: {t}" for i, t in enumerate(case["turns"]))
    return {"id": f"ep_{day.isoformat()}_{number:03d}", "timestamp": f"{day.isoformat()}T10:00:00+00:00", "content": body,
            "origin": "chatgpt", "source": "import", "title": case["id"], "processed": False}


def form_of(name: str, first: str) -> str | None:
    """How an entity's name relates to the shared first name: ``bare``, ``paren`` ("Nico (finance lead)"), ``other`` (any
    other name that carries the first name as a word: "Aunt Sara", "Nico from work", "Marie Curie"); ``None`` if it does not."""
    n, f = norm(name), norm(first)
    if n == f:
        return "bare"
    if not re.search(rf"(?<![a-z]){re.escape(f)}(?![a-z])", n):
        return None
    return "paren" if re.match(rf"^{re.escape(f)}\s*\(", n) else "other"


def entity_text(entity: dict, extraction: dict) -> str:
    """Everything one entity says: its summary, facts, aliases, the values and relationships that name it."""
    name = norm(entity.get("name"))
    parts = [entity.get("summary"), entity.get("description"), *(entity.get("key_facts") or []), *(entity.get("aliases") or [])]
    for v in extraction.get("values") or []:
        if norm(v.get("entity")) == name:
            parts += [v.get("attribute"), v.get("value"), v.get("evidence_quote")]
    for r in extraction.get("relationships") or []:
        if name in (norm(r.get("source")), norm(r.get("target"))):
            parts += [r.get("label"), r.get("evidence_quote")]
    return norm(" ".join(str(p) for p in parts if p))


def judge_extraction(case: dict, extraction: dict) -> dict:
    ents = [e for e in extraction.get("entities", []) if str(e.get("type") or "").lower() == "person"
            and form_of(e.get("name", ""), case["name"])]
    forms = sorted(form_of(e["name"], case["name"]) for e in ents)
    shape = "+".join(forms) if forms else "none"
    holds: list[set[str]] = []
    for e in ents:
        text = entity_text(e, extraction)
        holds.append({p for p, marks in case["people"].items() if any(norm(m) in text for m in marks)})
    found = {p for h in holds for p in h}
    if case["kind"] == "one":
        outcome = "one-entity" if len(ents) == 1 else "split" if len(ents) > 1 else "none"
    else:
        blended = any(len(h) > 1 for h in holds)
        outcome = ("lost" if len(found) < 2 else "blended" if blended else "clean")
        if outcome == "clean" and len(ents) < 2:
            outcome = "blended"
    return {"shape": shape, "outcome": outcome, "names": [e["name"] for e in ents], "holds": [sorted(h) for h in holds]}


def summarise(rows: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for r in rows:
        g = out.setdefault(r["case"]["id"], {"runs": 0, "shapes": Counter(), "outcomes": Counter()})
        g["runs"] += 1
        g["shapes"][r["shape"]] += 1
        g["outcomes"][r["outcome"]] += 1
    return out


def report(rows: list[dict], used: dict | None = None) -> str:
    s = summarise(rows)
    out = []
    totals: dict[str, Counter] = defaultdict(Counter)
    for cid, g in s.items():
        kind = next(r["case"]["kind"] for r in rows if r["case"]["id"] == cid)
        out.append(f"{kind:3} {cid:22} runs {g['runs']:>3}  shapes " + ", ".join(f"{k} {v}" for k, v in g["shapes"].most_common())
                   + "  | " + ", ".join(f"{k} {v}" for k, v in g["outcomes"].most_common()))
        totals[kind].update(g["outcomes"])
        totals["shape-" + kind].update(g["shapes"])
    for kind in ("two", "one"):
        n = sum(totals[kind].values())
        out.append(f"TOTAL {kind}: {n} runs  " + ", ".join(f"{k} {v}" for k, v in totals[kind].most_common())
                   + "  | shapes " + ", ".join(f"{k} {v}" for k, v in totals["shape-" + kind].most_common()))
    if used:
        out.append(f"calls {used['calls']} (failed {used['failed']})  in {used['in']}  out {used['out']}  cost ${used['cost']:.3f}")
    return "\n".join(out)


def rows_from_raw(raw: list[dict], cases: dict[str, dict]) -> list[dict]:
    rows = []
    for r in raw:
        case = cases[r["case"]]
        if r.get("extraction") is None:
            rows.append({"case": case, "shape": "failed", "outcome": "failed", "names": [], "holds": []})
        else:
            rows.append({"case": case, **judge_extraction(case, r["extraction"])})
    return rows


async def replay(cases: list[dict], repeats: int, settings, clock: date) -> list[dict]:
    from api.services import entity_extractor

    episodes, owners = [], []
    number = 0
    for case in cases:
        for _ in range(repeats):
            number += 1
            episodes.append(episode_of(case, clock, number))
            owners.append(case)
    results = await entity_extractor.extract(episodes, settings, today=clock)
    by_id = {r["episode_id"]: r for r in results}
    return [{"case": case["id"], "episode": ep["id"], "extraction": by_id.get(ep["id"])} for case, ep in zip(owners, episodes)]


def run(cases: list[dict], repeats: int, out: Path, key_file: Path, clock: date, model: str = "sonnet") -> list[dict]:
    import os

    from benchmarks.consolidation import run as bench
    from benchmarks.consolidation.same_name_battery import key_from, spend
    from benchmarks.engine_parity import _leg_environment, _refuse_real_paths, settings_for

    os.environ["ANTHROPIC_API_KEY"] = key_from(key_file)
    out.mkdir(parents=True, exist_ok=True)
    _refuse_real_paths(out)
    home = out / "home"
    home.mkdir(exist_ok=True)
    bank = out / "bank"
    with _leg_environment(home, bank):
        bench.init_bank(bank, cases[0]["owner"])
        settings = settings_for("key", bank, model=bench.engine_model("key", model), judge=bench.engine_model("key", "haiku"))
        raw = asyncio.run(replay(cases, repeats, settings, clock))
    (out / "raw.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in raw), encoding="utf-8")
    (out / "spend.json").write_text(json.dumps(spend(home)), encoding="utf-8")
    return raw


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--repeats", type=int, default=20)
    r.add_argument("--only", default="", help="substring of case ids")
    r.add_argument("--model", default="sonnet")
    r.add_argument("--clock", default="2026-11-23")
    r.add_argument("--cases", type=Path, default=CASES)
    r.add_argument("--key-file", type=Path, default=Path("~/.cicada/secrets.env"))
    r.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("rescore")
    s.add_argument("out", type=Path)
    s.add_argument("--cases", type=Path, default=CASES)
    a = p.parse_args(argv)
    cases = load_cases(a.cases)
    if a.cmd == "run":
        picked = [c for c in cases if a.only in c["id"]]
        raw = run(picked, a.repeats, a.out.expanduser(), a.key_file, date.fromisoformat(a.clock), a.model)
        used = json.loads((a.out.expanduser() / "spend.json").read_text())
    else:
        raw = [json.loads(line) for line in (a.out.expanduser() / "raw.jsonl").read_text(encoding="utf-8").splitlines()]
        spent = a.out.expanduser() / "spend.json"
        used = json.loads(spent.read_text()) if spent.exists() else None
    print(report(rows_from_raw(raw, {c["id"]: c for c in cases}), used))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
