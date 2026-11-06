"""Aggregate a run folder into scores comparable to the published ones, with their cost (standard library only).

Per answer path (``ask`` = ``cicada_ask``; ``full-context`` = the raw-history control), per category:

- **LoCoMo:** J (Mem0's judge; categories 1–4, adversarial apart) and LoCoMo's token F1. The headline is J over
  categories 1–4, the number Mem0 (66.9, full-context 72.9), Zep (75.1 by its own re-run) and Letta (74.0) report —
  their reader and judge models differ from this run's, so the comparison is indicative, never a leaderboard.
- **LongMemEval:** accuracy with the original per-type judge prompts, per type and overall (task-averaged too, as
  some vendors report it), abstention apart.

Cost is what the run measured: plan calls by phase and stage, their wall seconds, and Sleep's wall time. No dollar
figure: a plan call has no per-call price.
"""
from __future__ import annotations

import json
from collections import defaultdict
from math import comb
from pathlib import Path


def _rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    last: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            last[row.get("key") or str(len(last))] = row
    return list(last.values())


def _calls(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _pct(hits: int, n: int) -> float | None:
    return round(100.0 * hits / n, 1) if n else None


def summarize(run_dir: Path) -> dict:
    cfg = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    judged, answers, calls, units, expected = [], [], [], [], []
    for unit_dir in sorted((run_dir / "units").glob("*")) if (run_dir / "units").is_dir() else []:
        judged += _rows(unit_dir / "judgments.jsonl")
        answers += _rows(unit_dir / "answers.jsonl")
        calls += _calls(unit_dir / "calls.jsonl")
        if (unit_dir / "unit.json").is_file():
            unit = json.loads((unit_dir / "unit.json").read_text(encoding="utf-8"))
            expected += [q for q in unit["questions"] if not (cfg["dataset"] == "locomo" and q["abstention"])]
        state = json.loads((unit_dir / "state.json").read_text()) if (unit_dir / "state.json").is_file() else {}
        units.append({"unit": unit_dir.name, "done": bool(state.get("done")), "sleep_seconds":
                      (state.get("sleep") or {}).get("seconds"), "bank": state.get("bank")})
    locomo = cfg["dataset"] == "locomo"
    paths: dict[str, dict] = {}
    for path in [p for p in cfg["paths"] if p != "doors"]:
        rows = [r for r in judged if r["path"] == path]
        cats: dict[str, list] = defaultdict(list)
        for r in rows:
            cats[("abstention" if r["abstention"] and not locomo else r["category"])].append(r)
        per_cat = {}
        for cat, rs in sorted(cats.items()):
            graded = [r for r in rs if r["correct"] is not None]
            entry = {"n": len(graded), "accuracy": _pct(sum(r["correct"] for r in graded), len(graded)),
                     "ungraded": len(rs) - len(graded)}
            if locomo:
                f1s = [r["f1"] for r in rs if r.get("f1") is not None]
                entry["f1"] = round(100 * sum(f1s) / len(f1s), 1) if f1s else None
            per_cat[cat] = entry
        head = [r for r in rows if r["correct"] is not None and not (locomo and r["abstention"])]
        block = {"categories": per_cat, "n": len(head), "accuracy": _pct(sum(r["correct"] for r in head), len(head))}
        if locomo:
            f1s = [r["f1"] for r in rows if r.get("f1") is not None and not r["abstention"]]
            block["f1"] = round(100 * sum(f1s) / len(f1s), 1) if f1s else None
        else:
            accs = [c["accuracy"] for k, c in per_cat.items() if c["accuracy"] is not None and k != "abstention"]
            block["task_averaged"] = round(sum(accs) / len(accs), 1) if accs else None
        ans = [a for a in answers if a["path"] == path]
        by_key = {a.get("key"): a for a in ans}
        wrong = [r for r in head if r["correct"] is False]
        # A wrong answer that named a gap at least admitted something was missing; one that named none was a
        # confident wrong answer — the worse failure. (Ask fills `gaps` generously, so the first is an upper bound
        # on honest misses, not proof that the answer abstained.)
        block["wrong_with_gap"] = sum(1 for r in wrong if (by_key.get(r.get("key")) or {}).get("gaps"))
        block["wrong_confident"] = len(wrong) - block["wrong_with_gap"]
        block["answer_errors"] = sum(1 for a in ans if a.get("error"))
        # Honest denominators: a question with no answer (it failed) or no verdict (the judge failed) is never
        # silently left out — it is counted here, and `accuracy_all` scores it as not correct.
        graded_keys = {r["key"] for r in head}
        answered = {a["key"] for a in ans if not a.get("error")}
        want = [f"{q['qid']}|{path}" for q in expected]
        block["expected"] = len(want)
        block["unanswered"] = sum(1 for k in want if k not in answered)
        block["ungraded"] = sum(1 for k in want if k in answered and k not in graded_keys)
        block["accuracy_all"] = _pct(sum(r["correct"] for r in head), len(want)) if want else None
        block["abstained"] = sum(1 for a in ans if not a.get("cited") and path == "ask")
        if path == "ask":
            block["retrieval"] = retrieval_stats(ans, by_cat={r["key"]: c for c, rs in cats.items() for r in rs})
        spent = [int(a["tokens"]) for a in ans if a.get("tokens")]
        right = sum(1 for r in head if r["correct"])
        block["tokens"] = {"n": len(spent), "spent": sum(spent), "p50": _quantile(spent, 0.5) or 0,
                           "per_right": round(sum(spent) / right) if right else None,
                           "door_chars_p50": _quantile([a["door_chars"] for a in ans if "door_chars" in a], 0.5),
                           "door_chars_p95": _quantile([a["door_chars"] for a in ans if "door_chars" in a], 0.95)}
        secs = sorted(a["seconds"] for a in ans if a.get("seconds") is not None)
        block["answer_seconds_p50"] = secs[len(secs) // 2] if secs else None
        block["answer_seconds_p95"] = secs[min(len(secs) - 1, int(0.95 * len(secs)))] if secs else None
        paths[path] = block
    cost: dict[str, dict] = defaultdict(lambda: {"calls": 0, "failed": 0, "seconds": 0.0})
    for c in calls:
        key = f"{c['phase']}/{c['stage']}"
        cost[key]["calls"] += 1
        cost[key]["failed"] += 0 if c["ok"] else 1
        cost[key]["seconds"] = round(cost[key]["seconds"] + c["seconds"], 1)
    by_phase: dict[str, dict] = defaultdict(lambda: {"calls": 0, "seconds": 0.0})
    for c in calls:
        by_phase[c["phase"]]["calls"] += 1
        by_phase[c["phase"]]["seconds"] = round(by_phase[c["phase"]]["seconds"] + c["seconds"], 1)
    doors = door_stats([row for unit_dir in sorted((run_dir / "units").glob("*")) if (run_dir / "units").is_dir()
                        for row in _rows(unit_dir / "doors.jsonl")])
    return {"config": cfg, "units": units, "paths": paths, "doors": doors, "calls_by_stage": dict(cost),
            "calls_by_phase": dict(by_phase), "calls_total": len(calls),
            "sleep_wall_seconds": round(sum(u["sleep_seconds"] or 0 for u in units), 1)}


def door_stats(rows: list[dict]) -> dict:
    """Per door and category: questions with at least one answer turn handed over, answer turns handed over, and how
    much the door said. The abstention questions count only as how often a door said anything."""
    out: dict[str, dict] = {}
    for door in sorted({d for r in rows for d in r["doors"]}):
        cats: dict[str, list] = defaultdict(list)
        for r in rows:
            cats["abstention" if r["abstention"] else r["category"]].append(r["doors"][door])
            cats["(all)"].append(r["doors"][door])
        block = {}
        for cat, ds in sorted(cats.items()):
            marked = [d for d in ds if d["evidence_turns"]]
            block[cat] = {"n": len(ds), "any": sum(1 for d in marked if d["evidence_shown"]), "marked": len(marked),
                          "turns": sum(d["evidence_shown"] for d in marked),
                          "turns_marked": sum(d["evidence_turns"] for d in marked),
                          "spoke": sum(1 for d in ds if d["chars"]), "chars_p50": _quantile([d["chars"] for d in ds], .5),
                          "ms_p50": _quantile([d["ms"] for d in ds], .5), "ms_p95": _quantile([d["ms"] for d in ds], .95),
                          "errors": sum(1 for d in ds if d.get("error"))}
        out[door] = block
    return out


def per_question(run_dir: Path, path: str) -> dict[str, dict]:
    """Every graded question on ``path``: its category and verdict, the row a method comparison reads."""
    out: dict[str, dict] = {}
    for unit_dir in sorted((run_dir / "units").glob("*")) if (run_dir / "units").is_dir() else []:
        for r in _rows(unit_dir / "judgments.jsonl"):
            if r["path"] == path and r["correct"] is not None:
                out[r["qid"]] = {"category": "abstention" if r["abstention"] else r["category"],
                                 "correct": bool(r["correct"])}
    return out


def _sign_p(wins: int, losses: int) -> float:
    """The two-sided sign test over the questions that changed."""
    n = wins + losses
    if not n:
        return 1.0
    tail = sum(comb(n, k) for k in range(0, min(wins, losses) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def compare(a: dict[str, dict], b: dict[str, dict], *, a_name: str = "A", b_name: str = "B") -> dict:
    """Which method got what right, question by question, over the questions both graded: the score per category, what
    each alone got, both, neither, and the sign test on the difference. The same question can flip between runs of one
    method: a difference is read against a repeat, never on its own."""
    shared = sorted(set(a) & set(b))
    cats: dict[str, list] = defaultdict(list)
    for qid in shared:
        cats[a[qid]["category"]].append(qid)
        cats["(all)"].append(qid)
    rows = {}
    for cat, qids in sorted(cats.items()):
        only_a = [q for q in qids if a[q]["correct"] and not b[q]["correct"]]
        only_b = [q for q in qids if b[q]["correct"] and not a[q]["correct"]]
        rows[cat] = {"n": len(qids), a_name: sum(a[q]["correct"] for q in qids), b_name: sum(b[q]["correct"] for q in qids),
                     f"only_{a_name}": only_a, f"only_{b_name}": only_b,
                     "neither": sum(1 for q in qids if not a[q]["correct"] and not b[q]["correct"]),
                     "sign_p": round(_sign_p(len(only_a), len(only_b)), 4)}
    return rows


def render_compare(rows: dict, a_name: str, b_name: str, *, show_ids: bool = True) -> str:
    lines = [f"{'category':28} {'n':>4} {a_name:>12} {b_name:>12} {'only ' + a_name:>12} {'only ' + b_name:>12} "
             f"{'neither':>8} {'sign p':>7}"]
    for cat, r in rows.items():
        lines.append(f"{cat:28} {r['n']:>4} {r[a_name]:>12} {r[b_name]:>12} {len(r['only_' + a_name]):>12} "
                     f"{len(r['only_' + b_name]):>12} {r['neither']:>8} {r['sign_p']:>7}")
    if show_ids and "(all)" in rows:
        lines.append(f"only {a_name}: {' '.join(rows['(all)']['only_' + a_name]) or '-'}")
        lines.append(f"only {b_name}: {' '.join(rows['(all)']['only_' + b_name]) or '-'}")
    return "\n".join(lines)


def render_doors(doors: dict) -> str:
    lines = ["\n  what each door hands over (no model): questions with an answer turn · answer turns · spoke · chars p50 · ms p50/p95"]
    for door, block in doors.items():
        lines.append(f"  {door}")
        for cat, c in block.items():
            lines.append(f"    {cat:28} {c['any']:>4}/{c['marked']:<4} {c['turns']:>4}/{c['turns_marked']:<4} "
                         f"spoke {c['spoke']:>4}/{c['n']:<4} {str(c['chars_p50']):>7} ch  {c['ms_p50']}/{c['ms_p95']} ms"
                         + (f"  {c['errors']} errors" if c["errors"] else ""))
    return "\n".join(lines)


def _quantile(values: list[float], q: float) -> float | None:
    vals = sorted(values)
    return vals[min(len(vals) - 1, int(q * len(vals)))] if vals else None


def retrieval_stats(ans: list[dict], *, by_cat: dict[str, str]) -> dict:
    """What reached Ask's prompt: questions with at least one of the dataset's answer turns shown verbatim (over the
    questions whose answer turns the dataset marks), prompt size, and the time spent before the model call."""
    rows = [a for a in ans if not a.get("error") and "evidence_turns" in a]
    out: dict = {"n": len(rows), "model_called": sum(1 for a in rows if a.get("model_called"))}
    marked = [a for a in rows if a["evidence_turns"]]
    out["answer_turn_shown"] = sum(1 for a in marked if a["evidence_shown"])
    out["answer_turn_marked"] = len(marked)
    out["answer_turn_shown_pct"] = _pct(out["answer_turn_shown"], len(marked))
    per: dict[str, list] = defaultdict(list)
    for a in marked:
        per[by_cat.get(a["key"], "?")].append(a)
    out["by_category"] = {c: f"{sum(1 for a in rs if a['evidence_shown'])}/{len(rs)}" for c, rs in sorted(per.items())}
    chars = [a["prompt_chars"] for a in rows if a.get("model_called")]
    ms = [a["context_ms"] for a in rows if a.get("context_ms") is not None]
    out["prompt_chars_p50"], out["prompt_chars_p95"] = _quantile(chars, 0.5), _quantile(chars, 0.95)
    out["prompt_chars_max"] = max(chars) if chars else None
    out["context_ms_p50"], out["context_ms_p95"] = _quantile(ms, 0.5), _quantile(ms, 0.95)
    return out


def render(s: dict) -> str:
    cfg = s["config"]
    locomo = cfg["dataset"] == "locomo"
    lines = [f"\n{cfg['dataset']} · Cicada {cfg.get('revision', '?')} · Sleep {cfg['sleep_model']} "
             f"(+{cfg['disambiguation_model']}) · answer {cfg['answer_model']} · judge {cfg['judge_model']} · "
             f"{len(s['units'])} unit(s), {sum(1 for u in s['units'] if u['done'])} done"]
    metric = "J" if locomo else "accuracy"
    for path, b in s["paths"].items():
        extra = f" · F1 {b['f1']}" if locomo and b.get("f1") is not None else \
            (f" · task-averaged {b['task_averaged']}" if b.get("task_averaged") is not None else "")
        lines.append(f"\n  {path}: {metric} {b['accuracy']}% over {b['n']} questions{extra}"
                     f" · answer p50 {b['answer_seconds_p50']} s, p95 {b['answer_seconds_p95']} s"
                     + (f" · {b['answer_errors']} answer errors" if b["answer_errors"] else ""))
        if b.get("unanswered") or b.get("ungraded"):
            lines.append(f"    INCOMPLETE: {b['unanswered']} unanswered, {b['ungraded']} ungraded of {b['expected']} — "
                         f"counting them as not correct: {b['accuracy_all']}% (--resume retries them)")
        if b.get("wrong_with_gap") or b.get("wrong_confident"):
            lines.append(f"    wrong: {b['wrong_with_gap']} named a gap, {b['wrong_confident']} confidently wrong")
        cost = b.get("tokens")
        if cost and cost.get("spent"):
            lines.append(f"    tokens: {cost['spent']:,} on {cost['n']} answers · p50 {cost['p50']:,} · "
                         f"per right answer {cost['per_right'] or 0:,}"
                         + (f" · door chars p50 {cost['door_chars_p50']:,} p95 {cost['door_chars_p95']:,}"
                            if cost.get("door_chars_p50") is not None else ""))
        rv = b.get("retrieval")
        if rv and rv.get("n"):
            lines.append(f"    answer turn in the prompt: {rv['answer_turn_shown']}/{rv['answer_turn_marked']} "
                         f"({rv['answer_turn_shown_pct']}%) · model called {rv['model_called']}/{rv['n']} · prompt "
                         f"chars p50 {rv['prompt_chars_p50']} p95 {rv['prompt_chars_p95']} · context build ms p50 "
                         f"{rv['context_ms_p50']} p95 {rv['context_ms_p95']}")
        for cat, c in b["categories"].items():
            f1 = f"  F1 {c['f1']}" if locomo and c.get("f1") is not None else ""
            lines.append(f"    {cat:28} {str(c['accuracy']):>6}%  (n={c['n']}){f1}"
                         + (f"  ungraded {c['ungraded']}" if c["ungraded"] else ""))
    if s.get("doors"):
        lines.append(render_doors(s["doors"]))
    lines.append(f"\n  plan calls: {s['calls_total']} · Sleep wall {s['sleep_wall_seconds']} s")
    for phase, c in sorted(s["calls_by_phase"].items()):
        lines.append(f"    {phase:8} {c['calls']:5} calls  {c['seconds']:8.1f} call-seconds")
    if locomo:
        lines.append("\n  Published LoCoMo J (categories 1-4, gpt-4o-mini readers, different judges): Mem0 66.9, "
                     "Mem0g 68.4, full-context 72.9, Zep 75.1 (its re-run), Letta filesystem 74.0. Indicative only.")
    else:
        lines.append("\n  Published LongMemEval (gpt-4o reader + judge): full-context S 60.6, oracle 87.0 (paper); "
                     "Zep 71.2 on S. Indicative only.")
    return "\n".join(lines)
