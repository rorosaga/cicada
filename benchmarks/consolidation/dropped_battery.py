"""Replay battery for what the person says in passing (Stage 1 extraction, 2026-11-24).

Why: a fact the person says inside a conversation about something else — a book they finished, a film seen, a city
visited, a course completed, a purchase, a race run, a doctor's visit, a decision mentioned as an aside — is sometimes
not written as a claim by Stage 1, and then Sleep never has it to keep. The benchmark sees one such fact ("has read a
book", gold point P18) and misses it in about one run in four. This replays invented conversations of that shape
(English, Spanish, French; plus counter-cases that must NOT become the person's act: the assistant's suggestion, a thing
they only asked about, a plan, someone else's act) through the product's own Stage 1 (`entity_extractor.extract`: its
prompt, its owner block, its date note, its evidence handling) many times each, and says where each fact ended up:

    claim   a relationship between the owner and the thing, or a value on either, that rests on the passing line
    status  only the book rails' mark of the thing (the model's `reading_status`, carried as `book_said`, `book_said`; the scorer reads no claim there)
    prose   only a summary, key fact or history entry that says it (a page's words; Sleep has no claim to keep)
    dropped nowhere

    api/.venv/bin/python -m benchmarks.consolidation.dropped_battery run --repeats 10 --out OUT
    api/.venv/bin/python -m benchmarks.consolidation.dropped_battery rescore OUT     # no model: judge the saved answers again

`dropped_cases.json` holds the cases: ``thing`` (name tokens of what the fact is about, any one), ``also`` (more tokens a
value may carry), ``date_offset`` (the day it happened, in days from the conversation's, when the person says it), and,
for a counter-case (``polarity: counter``), ``wrong`` (label stems that would make it the person's act) and ``ok`` (stems of a label that is the right claim, a plan or a doubt). These are the
gold of the case, not a rule of the product. A call is under a cent.

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
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from benchmarks.consolidation.direction_battery import conversation_of, episode_of, norm  # noqa: E402

CASES = Path(__file__).with_name("dropped_cases.json")
LEVELS = ("claim", "status", "prose", "dropped")


def load_cases(path: Path = CASES) -> list[dict]:
    """The cases; a case that names a fixture conversation gets that fixture's owner."""
    cases = json.loads(path.read_text(encoding="utf-8"))
    for case in cases:
        if "owner" not in case:
            case["owner"] = conversation_of(case, date(2026, 11, 23))[0]
    return cases


def _has(tokens: list[str], text: str) -> bool:
    return any(re.search(r"(?<![a-z0-9])" + re.escape(norm(t)), text) for t in tokens)


def _owner(case: dict, name: str) -> bool:
    n = norm(name)
    return all(re.search(r"(?<![a-z])" + re.escape(t), n) for t in norm(case["owner"]).split())


def _thing(case: dict, name: str) -> bool:
    return _has(case["thing"], norm(name))


def _text(entity: dict) -> str:
    parts = [entity.get("summary") or "", *(entity.get("key_facts") or []),
             *(h.get("event", "") for h in entity.get("history_entries") or [] if isinstance(h, dict))]
    return norm(" ".join(str(p) for p in parts))


def _expected_day(case: dict, clock: date) -> str | None:
    if "date_offset" not in case:
        return None
    return (conversation_of(case, clock)[2] + timedelta(days=int(case["date_offset"]))).isoformat()


def judge_extraction(case: dict, result: dict, clock: date = date(2026, 11, 23)) -> dict:
    """Where the case's fact went in one extraction: ``level`` (claim|status|prose|dropped), whether it is ``dated``
    (when the case has a day) and, for a counter-case, ``wrong`` (the person's act written) and ``linked``."""
    tokens = case["thing"] + case.get("also", [])
    rels = [r for r in result.get("relationships") or [] if isinstance(r, dict)]
    ents = [e for e in result.get("entities") or [] if isinstance(e, dict)]
    owner_rels = [r for r in rels if (_owner(case, r.get("source", "")) and _thing(case, r.get("target", "")))
                  or (_owner(case, r.get("target", "")) and _thing(case, r.get("source", "")))]
    values = [v for v in result.get("values") or [] if isinstance(v, dict)
              and (_owner(case, v.get("entity", "")) or _thing(case, v.get("entity", "")))
              and _has(tokens, norm(f"{v.get('entity', '')} {v.get('attribute', '')} {v.get('value', '')} {v.get('evidence_quote', '')}"))]
    statuses = [m for m in result.get("book_said") or [] if isinstance(m, dict) and _thing(case, m.get("name", ""))
                and m.get("status") in ("reading", "finished")]
    prose = [e for e in ents if _has(tokens, _text(e))]
    out = {"level": "dropped", "dated": None, "wrong": False, "linked": bool(owner_rels),
           "labels": [f"{r.get('source')} | {r.get('label')} | {r.get('target')}" for r in owner_rels]
           + [f"value {v.get('entity')} | {v.get('attribute')}: {v.get('value')}" for v in values]}
    if case["polarity"] == "counter":
        stems = case.get("wrong", [])
        fine = case.get("ok", [])   # a label that says a plan, a doubt or a request is the right claim
        out["wrong"] = any(_has(stems, norm(r.get("label", ""))) and not _has(fine, norm(r.get("label", "")))
                           for r in owner_rels) or bool(statuses)
        out["level"] = "claim" if owner_rels or values else "status" if statuses else "prose" if prose else "dropped"
        return out
    out["level"] = "claim" if owner_rels or values else "status" if statuses else "prose" if prose else "dropped"
    day = _expected_day(case, clock)
    if day and out["level"] == "claim":
        dated = any(str(r.get("starts") or "") == day for r in owner_rels)
        dated = dated or any(h.get("date") == day for e in ents if _owner(case, e.get("name", "")) or _thing(case, e.get("name", ""))
                             for h in e.get("history_entries") or [] if isinstance(h, dict))
        out["dated"] = dated
    return out


def summarise(rows: list[dict]) -> dict:
    def blank() -> dict:
        return {"runs": 0, "claim": 0, "status": 0, "prose": 0, "dropped": 0, "failed": 0, "wrong": 0, "dated": 0, "dated_of": 0}

    groups: dict[str, dict[str, dict]] = {k: defaultdict(blank) for k in ("case", "kind", "lang", "polarity")}
    for row in rows:
        c = row["case"]
        for axis, key in (("case", c["id"]), ("kind", c["kind"] + "/" + c["polarity"]), ("lang", c["lang"] + "/" + c["polarity"]),
                          ("polarity", c["polarity"])):
            g = groups[axis][key]
            g["runs"] += 1
            if row["level"] == "failed":
                g["failed"] += 1
                continue
            g[row["level"]] += 1
            g["wrong"] += bool(row.get("wrong"))
            if row.get("dated") is not None:
                g["dated_of"] += 1
                g["dated"] += bool(row["dated"])
    return {axis: dict(g) for axis, g in groups.items()}


def report(rows: list[dict], used: dict | None = None) -> str:
    s = summarise(rows)
    out = []
    for cid in dict.fromkeys(r["case"]["id"] for r in rows):
        g = s["case"][cid]
        pol = next(r["case"]["polarity"] for r in rows if r["case"]["id"] == cid)
        line = f"{pol:7} {cid:26} runs {g['runs']:>3}  claim {g['claim']:>3}  status {g['status']:>3}  prose {g['prose']:>3}  dropped {g['dropped']:>3}"
        if pol == "counter":
            line += f"  WRONG {g['wrong']:>3}"
        elif g["dated_of"]:
            line += f"  dated {g['dated']}/{g['dated_of']}"
        out.append(line + (f"  failed {g['failed']}" if g["failed"] else ""))
    for axis in ("kind", "lang", "polarity"):
        out.append(f"by {axis}:")
        for k, g in sorted(s[axis].items()):
            tail = f"WRONG {g['wrong']}" if k.endswith("counter") or k == "counter" else f"dated {g['dated']}/{g['dated_of']}"
            out.append(f"   {k:18} runs {g['runs']:>3}  claim {g['claim']:>3}  status {g['status']:>3}  prose {g['prose']:>3}  dropped {g['dropped']:>3}  {tail}")
    if used:
        out.append(f"calls {used['calls']} (failed {used['failed']})  in {used['in']}  out {used['out']}  cost ${used['cost']:.3f}")
    return "\n".join(out)


def rows_from_raw(raw: list[dict], cases: dict[str, dict], clock: date = date(2026, 11, 23)) -> list[dict]:
    rows = []
    for r in raw:
        case = cases[r["case"]]
        if r.get("result") is None:
            rows.append({"case": case, "level": "failed", "labels": []})
        else:
            rows.append({"case": case, **judge_extraction(case, r["result"], clock)})
    return rows


def _trim(result: dict) -> dict:
    """What the judge reads, nothing more."""
    return {"entities": [{k: e.get(k) for k in ("name", "type", "summary", "key_facts", "history_entries", "reading_status")}
                         for e in result.get("entities") or []],
            "relationships": [{k: r.get(k) for k in ("source", "target", "label", "starts", "ends", "evidence_quote")}
                              for r in result.get("relationships") or []],
            "values": [{k: v.get(k) for k in ("entity", "attribute", "value", "evidence_quote")} for v in result.get("values") or []],
            # the book rails' route: the model's reading status, checked and carried on the result (`book_said`)
            "book_said": [{k: m.get(k) for k in ("name", "status", "stated")} for m in result.get("book_said") or [] if isinstance(m, dict)]}


async def replay(cases: list[dict], repeats: int, settings, clock: date) -> list[dict]:
    """Every case ``repeats`` times through the real ``entity_extractor.extract``."""
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
    return [{"case": case["id"], "episode": ep["id"], "result": _trim(by_id[ep["id"]]) if ep["id"] in by_id else None}
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
    r.add_argument("--repeats", type=int, default=10)
    r.add_argument("--only", default="", help="substring of case ids")
    r.add_argument("--skip", default="", help="substring of case ids to leave out")
    r.add_argument("--polarity", default="", help="said or counter")
    r.add_argument("--model", default="sonnet", help="Stage 1's tier (the benchmark's main model)")
    r.add_argument("--clock", default="2026-11-23")
    r.add_argument("--cases", type=Path, default=CASES)
    engines.add_argument(r)
    r.add_argument("--key-file", type=Path, default=Path("~/.cicada/secrets.env"))
    r.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("rescore")
    s.add_argument("out", type=Path)
    s.add_argument("--cases", type=Path, default=CASES)
    s.add_argument("--clock", default="2026-11-23")
    a = p.parse_args(argv)
    cases = load_cases(a.cases)
    clock = date.fromisoformat(a.clock)
    if a.cmd == "run":
        picked = [c for c in cases if a.only in c["id"] and (not a.skip or a.skip not in c["id"])
                  and (not a.polarity or c["polarity"] == a.polarity)]
        raw = run(picked, a.repeats, a.out.expanduser(), a.key_file, clock, a.model, a.engine)
        used = json.loads((a.out.expanduser() / "spend.json").read_text())
    else:
        raw = [json.loads(line) for line in (a.out.expanduser() / "raw.jsonl").read_text(encoding="utf-8").splitlines()]
        spent = a.out.expanduser() / "spend.json"
        used = json.loads(spent.read_text()) if spent.exists() else None
    print(report(rows_from_raw(raw, {c["id"]: c for c in cases}, clock), used))
    _print_tally(a.out.expanduser())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
