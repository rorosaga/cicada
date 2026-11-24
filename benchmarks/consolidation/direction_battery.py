"""Replay battery for which way a relationship points (Stage 1 extraction, 2026-11-23).

Why: "my brother-in-law Marc" is sometimes written ``<owner> brother-in-law-of Marc`` (the owner as the brother-in-law).
A reversed relation is a wrong fact that reads right, and a benchmark run states two such relations once each, so a
defect that happens one time in four shows as a coin toss. This replays conversations that state a role one side holds
toward the other (kinship, work, housing, clients, mentoring; English, Spanish, French; plus symmetric relations and ones
the owner holds, which must not be touched) through the product's own Stage 1 (`entity_extractor.extract`: its prompt, its
owner block, its date note, its evidence handling) many times each, and counts how often the relation points the wrong
way. A call is a cent or two.

    api/.venv/bin/python -m benchmarks.consolidation.direction_battery run --repeats 5 --out OUT
    api/.venv/bin/python -m benchmarks.consolidation.direction_battery rescore OUT     # no model: judge the saved answers again

`direction_cases.json` holds the cases. Each names who holds the role (``holder``) and toward whom (``other``), the role
in the words of the case's language (``role``), the role the other side holds back (``inverse``: "<other> daughter of
<holder>" is as right as "<holder> father of <other>"), and, for roles said as a verb ("reports to", "manages"), the label
forms in which the subject (``forms.subject``) or the object (``forms.object``) is the one who holds it. These are the
gold of the case, not a rule of the product. ``kind`` is ``asymmetric`` (the other person holds the role toward the
owner), ``owner-held`` (the owner holds it: it must stay the owner's) or ``symmetric`` (no wrong direction: the relation
must not be doubled).

Needs ``ANTHROPIC_API_KEY`` in the environment or in ``--key-file`` (never printed). Cost is printed.
``--engine plan`` runs the same cases through the signed-in Claude plan instead (no key read; Stage 1 on Sonnet, as a new
user's Sleep does), and prints the replies the engine returned that could not be read (`engines.py`; 2026-11-24).
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

CASES = Path(__file__).with_name("direction_cases.json")
#: A label that says its OBJECT is the one holding the role: "has brother-in-law Marc", "tiene suegra", "a pour beau-frère".
HAS_FORM = re.compile(r"^(?:has|have|had|tiene|tienen|ha|ont|a pour|a un|a une)\b")
#: A passive label ("mentored by", "managed by", "supervise par") makes its OBJECT the one acting: the holder.
PASSIVE_FORM = re.compile(r"\b(?:by|par|por)$")


def norm(text: str) -> str:
    """Lower case, accents folded, hyphens and underscores as spaces, one space between words."""
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[-_/]", " ", text)).strip()


def _has(words: list[str], text: str) -> bool:
    return any(re.search(r"(?<![a-z])" + re.escape(norm(w)), text) for w in words)


def load_cases(path: Path = CASES) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def conversation_of(case: dict, clock: date) -> tuple[str, list[str], date]:
    """(owner, turns, the day it was said) for a case: its own turns, or the fixture's conversation it names."""
    if "fixture" in case:
        from benchmarks.consolidation import run

        fixture = run.load_fixture(REPO / "benchmarks" / "consolidation" / case["fixture"])
        conv = next(c for c in fixture["conversations"] if c["id"] == case["conv"])
        return fixture["owner"], run.render_turns(conv, clock), clock + timedelta(days=conv["day"])
    return case["owner"], list(case["turns"]), clock + timedelta(days=case["day"])


def episode_of(case: dict, clock: date, number: int) -> dict:
    """The case as a stored conversation, as the staging module writes one: ``user:`` / ``assistant:`` lines."""
    owner, turns, day = conversation_of(case, clock)
    body = "\n".join(f"{'user' if i % 2 == 0 else 'assistant'}: {t}" for i, t in enumerate(turns))
    return {"id": f"ep_{day.isoformat()}_{number:03d}", "timestamp": f"{day.isoformat()}T10:00:00+00:00", "content": body,
            "origin": "chatgpt", "source": "import", "title": case["id"], "processed": False}


def side(name: str, case: dict) -> str | None:
    """``H`` (the one who holds the role), ``O`` (the other) or ``None`` (a third thing), by the case's name tokens."""
    n = norm(name)
    h = any(re.search(r"(?<![a-z])" + re.escape(norm(t)), n) for t in case["holder"])
    o = any(re.search(r"(?<![a-z])" + re.escape(norm(t)), n) for t in case["other"])
    if h == o:
        return None
    return "H" if h else "O"


def judge_relationship(case: dict, rel: dict) -> str | None:
    """``right``, ``reversed`` or ``None`` (not about this role between these two) for one ``{source, target, label}``.

    Which side the label makes the holder: a passive ("... by") makes the object; else a verb form of the case
    (``forms``); else the role noun, whose subject
    holds it unless the label starts "has ..." (then the object does); else the inverse role noun, whose subject is
    the other side. A label that names neither is not a statement of the role."""
    s, t = side(rel.get("source", ""), case), side(rel.get("target", ""), case)
    if s is None or t is None or s == t:
        return None
    label = norm(rel.get("label", ""))
    forms = case.get("forms", {})
    holder_side: str | None = None
    if PASSIVE_FORM.search(label) or any(re.search(rx, label) for rx in forms.get("object", [])):
        holder_side = t
    elif any(re.search(rx, label) for rx in forms.get("subject", [])):
        holder_side = s
    elif _has(case["role"], label):
        holder_side = t if HAS_FORM.match(label) else s
    elif _has(case.get("inverse", []), label):
        subject_holds_inverse = s if not HAS_FORM.match(label) else t
        holder_side = "H" if subject_holds_inverse == "O" else "O"
    if holder_side is None:
        return None
    return "right" if holder_side == "H" else "reversed"


def judge_extraction(case: dict, relationships: list[dict]) -> dict:
    """One extraction of one case: how many relationships state the role, how many point the wrong way."""
    verdicts = [(judge_relationship(case, r), r) for r in relationships if isinstance(r, dict)]
    stated = [(v, r) for v, r in verdicts if v]
    right = sum(v == "right" for v, _ in stated)
    reversed_ = sum(v == "reversed" for v, _ in stated)
    if case["kind"] == "symmetric":
        # No wrong direction: a symmetric relation is never reversed. Said in both directions at once is a duplicate.
        sides = {(side(r.get("source", ""), case)) for _, r in stated}
        outcome = "none" if not stated else "doubled" if len(sides) > 1 else "right"
        return {"outcome": outcome, "stated": len(stated), "right": right, "reversed": 0,
                "labels": [f"{r.get('source')} | {r.get('label')} | {r.get('target')}" for _, r in stated]}
    outcome = "none" if not stated else "reversed" if reversed_ and not right else "mixed" if reversed_ else "right"
    return {"outcome": outcome, "stated": len(stated), "right": right, "reversed": reversed_,
            "labels": [f"{r.get('source')} | {r.get('label')} | {r.get('target')} [{v}]" for v, r in stated]}


def summarise(rows: list[dict]) -> dict:
    """Totals by case, by family, by language and by kind. ``wrong`` counts an extraction with any reversed relation."""
    def blank() -> dict:
        return {"runs": 0, "wrong": 0, "right": 0, "none": 0, "doubled": 0, "failed": 0}

    groups: dict[str, dict[str, dict]] = {k: defaultdict(blank) for k in ("case", "family", "lang", "kind")}
    for row in rows:
        c = row["case"]
        outcome = row["outcome"]
        for axis, key in (("case", c["id"]), ("family", c["family"]), ("lang", c["lang"]), ("kind", c["kind"])):
            g = groups[axis][key]
            g["runs"] += 1
            if outcome in ("reversed", "mixed"):
                g["wrong"] += 1
            elif outcome in ("right", "none", "doubled", "failed"):
                g[outcome] += 1
    total = blank()
    for g in groups["case"].values():
        for k in total:
            total[k] += g[k]
    return {"total": total, **{axis: dict(g) for axis, g in groups.items()}}


def report(rows: list[dict], used: dict | None = None) -> str:
    s = summarise(rows)
    out = []
    order = [r["case"]["id"] for r in rows]
    for cid in dict.fromkeys(order):
        g = s["case"][cid]
        kind = next(r["case"]["kind"] for r in rows if r["case"]["id"] == cid)
        out.append(f"{kind:10} {cid:20} runs {g['runs']:>3}  REVERSED {g['wrong']:>3}  right {g['right']:>3}  not stated {g['none']:>3}"
                   + (f"  doubled {g['doubled']}" if g["doubled"] else "") + (f"  failed {g['failed']}" if g["failed"] else ""))
    for axis in ("kind", "family", "lang"):
        out.append(f"by {axis}: " + "   ".join(f"{k} {g['wrong']}/{g['runs']}" for k, g in sorted(s[axis].items())))
    t = s["total"]
    out.append(f"TOTAL reversed {t['wrong']}/{t['runs']}  (right {t['right']}, not stated {t['none']}, doubled {t['doubled']}, failed {t['failed']})")
    if used:
        out.append(f"calls {used['calls']} (failed {used['failed']})  in {used['in']}  out {used['out']}  cost ${used['cost']:.3f}")
    return "\n".join(out)


def rows_from_raw(raw: list[dict], cases: dict[str, dict]) -> list[dict]:
    rows = []
    for r in raw:
        case = cases[r["case"]]
        if r.get("relationships") is None:
            rows.append({"case": case, "outcome": "failed", "labels": []})
        else:
            rows.append({"case": case, **judge_extraction(case, r["relationships"])})
    return rows


async def replay(cases: list[dict], repeats: int, settings, clock: date) -> list[dict]:
    """Every case ``repeats`` times (times its ``weight``) through the real ``entity_extractor.extract``."""
    from api.services import entity_extractor

    episodes, owners = [], []
    number = 0
    for case in cases:
        for _ in range(repeats * int(case.get("weight", 1))):
            number += 1
            episodes.append(episode_of(case, clock, number))
            owners.append(case)
    results = await entity_extractor.extract(episodes, settings, today=clock)
    by_id = {r["episode_id"]: r for r in results}
    return [{"case": case["id"], "episode": ep["id"],
             "relationships": [{k: r.get(k) for k in ("source", "target", "label")} for r in by_id[ep["id"]]["relationships"]]
             if ep["id"] in by_id else None}
            for case, ep in zip(owners, episodes)]


def run(cases: list[dict], repeats: int, out: Path, key_file: Path, clock: date, model: str = "sonnet", engine: str = "key") -> list[dict]:
    """One bank and owner per distinct owner name (the owner block of the prompt names them), one leg's environment."""
    import os

    from benchmarks.consolidation import engines, run as bench
    from benchmarks.consolidation.same_name_battery import key_from, spend
    from benchmarks.engine_parity import _leg_environment, _refuse_real_paths

    engines.arm(engine, lambda: os.environ.__setitem__("ANTHROPIC_API_KEY", key_from(key_file)))   # inherited by the call, never printed
    out.mkdir(parents=True, exist_ok=True)
    _refuse_real_paths(out)
    home = out / "home"
    home.mkdir(exist_ok=True)
    raw: list[dict] = []
    by_owner: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        by_owner[conversation_of(case, clock)[0]].append(case)
    with engines.tally() as counted:
        for n, (owner, group) in enumerate(by_owner.items()):
            bank = out / f"bank-{n}"
            with _leg_environment(home, bank):
                bench.init_bank(bank, owner)
                settings = engines.settings(engine, bank, model=model, judge="haiku")
                raw += asyncio.run(replay(group, repeats, settings, clock))
    engines.dump(counted, out / "tally.json")
    (out / "raw.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in raw), encoding="utf-8")
    (out / "spend.json").write_text(json.dumps(spend(home)), encoding="utf-8")
    return raw


def _print_tally(out: Path) -> None:
    """What the engine's replies were (`engines.Tally`), when the run kept it: calls, raised, not a JSON object."""
    path = out / "tally.json"
    if path.exists():
        t = json.loads(path.read_text(encoding="utf-8"))
        print(f"engine replies: {sum(t['calls'].values())} calls, unusable (raised or not JSON) {t['unusable']}; "
              f"raised {t['raised']}, not JSON {t['not_json']}")


def main(argv: list[str] | None = None) -> int:
    from benchmarks.consolidation import engines

    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--repeats", type=int, default=5)
    r.add_argument("--only", default="", help="substring of case ids")
    r.add_argument("--kind", default="")
    r.add_argument("--skip", default="", help="substring of case ids to leave out")
    r.add_argument("--model", default="sonnet", help="Stage 1's tier (the benchmark's main model)")
    r.add_argument("--clock", default="2026-11-23")
    r.add_argument("--cases", type=Path, default=CASES)
    engines.add_argument(r)
    r.add_argument("--key-file", type=Path, default=Path("~/.cicada/secrets.env"))
    r.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("rescore")
    s.add_argument("out", type=Path)
    s.add_argument("--cases", type=Path, default=CASES)
    a = p.parse_args(argv)
    cases = load_cases(a.cases)
    if a.cmd == "run":
        picked = [c for c in cases if a.only in c["id"] and (not a.skip or a.skip not in c["id"])
                  and (not a.kind or c["kind"] == a.kind)]
        raw = run(picked, a.repeats, a.out.expanduser(), a.key_file, date.fromisoformat(a.clock), a.model, a.engine)
        used = json.loads((a.out.expanduser() / "spend.json").read_text())
    else:
        raw = [json.loads(line) for line in (a.out / "raw.jsonl").read_text(encoding="utf-8").splitlines()]
        spent = a.out / "spend.json"
        used = json.loads(spent.read_text()) if spent.exists() else None
    print(report(rows_from_raw(raw, {c["id"]: c for c in cases}), used))
    _print_tally(a.out.expanduser())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
