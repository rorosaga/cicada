"""Are Cicada's answers right about *your* life? Ask your own questions, grade the answers against facts you wrote.

    cp benchmarks/answer_eval.example.yaml benchmarks/answer_eval.local.yaml   # gitignored: fill in your own
    api/.venv/bin/python -m benchmarks.answer_eval --bank <your bank dir> --questions benchmarks/answer_eval.local.yaml

Each question is answered by ``cicada_ask``'s own body (``ask_service.answer_query``) against the bank you name —
in this process, the way ``cicada ask`` does, reading the bank (and refreshing only its disposable derived indexes) —
then graded by a judge that sees the question, the answer and **your expected facts**, never the bank. The question
file says, per question:

- ``expect``: facts a right answer must state (paraphrase is fine; extra detail is fine);
- ``forbid`` (optional): facts it must NOT assert as current — an old job, a moved deadline, a dropped plan;
- ``abstain: true`` (optional): memory should not know this; the right answer says so;
- ``tags`` (optional): your own grouping (``knowledge-update``, ``people``, ``projects`` …), scored apart.

A question is **correct** when every expected fact is stated, none is contradicted and no forbidden fact is asserted
(for ``abstain``: the answer declines and asserts nothing forbidden). Fact recall, contradictions and abstention are
reported beside it, overall and per tag.

**Engine.** ``--engine plan`` (default) answers and judges with ``claude -p`` on your Claude plan, through Cicada's own
plan engine (``CICADA_LLM_MODE=agent``; ``--answer-model``/``--judge-model`` pick the models). ``--engine configured``
answers with the engine your Settings chose (it may be a metered API) and still judges on the plan.

**Repeats.** One run's number moves by chance (the owner's 60 questions: 46, 44, 42, 42 correct on near-identical
code, 13 questions flipping between runs), so each question is answered and judged ``--repeats`` times (default 3),
run after run on the same bank. Every row carries its ``run``; the summary gives each measure's mean and min–max across
runs, overall and per tag, and per question: always right, always wrong, or flips (ids only).

**Compare.** ``--compare A.jsonl B.jsonl`` (no calls) takes each question's majority verdict over its runs in A and in
B and calls B different from A only when the exact two-sided sign test on the questions whose majority changed gives
p < 0.05, the change in mean correct is wider than either file's own min–max, **and** both move the same way.
``--summary FILE`` re-prints a file's summary.

**Variance.** ``claude -p`` exposes no temperature, top-p or seed, so sampling cannot be pinned on the plan. What it
does expose is pinned or recorded: ``--answer-model``/``--judge-model`` take a full model id as well as an alias, the
model the plan actually reported is kept on every row, ``--effort`` pins the CLI's effort for both calls (and drops an
inherited ``CLAUDE_CODE_EFFORT_LEVEL``, which would override it), and each run's header row records the CLI version.
``--compare`` names any of these that differ between A and B.

**Privacy.** The question file is yours and gitignored (``benchmarks/*.local.*``). Answers, judgments and the summary
go to ``--out`` (default ``benchmark_results/answer_eval/<timestamp>.jsonl``, gitignored), written 0600. The terminal
shows question ids and scores only, unless ``--show``; the summary and compare print ids and numbers only. Re-running
with the same ``--out`` skips (question, run) pairs already graded and asks failed ones again; ``--fresh`` starts the
file over (with ``--only``, re-asks just those questions). A file is never resumed under other run settings (models,
effort, CLI version, engine, top-k) than the ones its runs recorded — the eval refuses and says which differ.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

JUDGE_SYSTEM = """You grade one answer from a personal memory system. The person who owns the memory wrote down \
the facts a right answer must contain. Judge ONLY against those facts and the answer's own words; you have no other \
knowledge of this person. Paraphrase, extra detail and different date formats are fine. Return ONLY JSON."""

JUDGE_TEMPLATE = """QUESTION:
{question}

ANSWER FROM MEMORY:
{answer}

EXPECTED FACTS (a right answer states each):
{expected}

FORBIDDEN FACTS (stale or wrong; the answer must not assert any as currently true):
{forbidden}

SHOULD THE ANSWER DECLINE (memory is not supposed to know this)? {abstain}

For each expected fact give "stated" (the answer says it or something equivalent), "missing" (the answer does not \
say it) or "contradicted" (the answer says something incompatible with it). For each forbidden fact give true when \
the answer asserts it as currently true (mentioning it as past history is NOT asserting it). "declined" is true when \
the answer says memory does not have the information.

Return exactly:
{{"expected": [{{"n": 1, "verdict": "stated|missing|contradicted"}}], "forbidden": [{{"n": 1, "asserted": false}}], \
"declined": false, "note": "one short sentence"}}"""


def load_questions(path: Path) -> list[dict]:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out, seen = [], set()
    for i, q in enumerate(data.get("questions") or [], 1):
        if not isinstance(q, dict) or not str(q.get("question") or "").strip():
            raise SystemExit(f"question #{i}: needs a `question`")
        qid = str(q.get("id") or f"q{i:03d}")
        if qid in seen:
            raise SystemExit(f"question id {qid} appears twice")
        seen.add(qid)
        expect = [str(f) for f in (q.get("expect") or []) if str(f).strip()]
        abstain = bool(q.get("abstain"))
        if not expect and not abstain:
            raise SystemExit(f"question {qid}: give `expect` facts, or `abstain: true`")
        out.append({"id": qid, "question": str(q["question"]).strip(), "expect": expect,
                    "forbid": [str(f) for f in (q.get("forbid") or []) if str(f).strip()],
                    "abstain": abstain, "tags": [str(t) for t in (q.get("tags") or [])]})
    return out


def judge_prompt(q: dict, answer: str) -> str:
    def numbered(items):
        return "\n".join(f"{n}. {text}" for n, text in enumerate(items, 1)) or "(none)"

    return JUDGE_TEMPLATE.format(question=q["question"], answer=answer or "(empty)", expected=numbered(q["expect"]),
                                 forbidden=numbered(q["forbid"]), abstain="yes" if q["abstain"] else "no")


def grade(q: dict, verdict: dict | None) -> dict:
    """Scores from the judge's verdict. ``None`` (unparseable) grades nothing — it is reported as ungraded."""
    if not isinstance(verdict, dict):
        return {"graded": False}
    by_n = {int(v.get("n", 0)): str(v.get("verdict", "")).lower() for v in verdict.get("expected") or []
            if isinstance(v, dict) and str(v.get("n", "")).isdigit()}
    states = [by_n.get(n, "missing") for n in range(1, len(q["expect"]) + 1)]
    asserted = sum(1 for v in verdict.get("forbidden") or [] if isinstance(v, dict) and v.get("asserted") is True)
    declined = verdict.get("declined") is True
    stated, contradicted = states.count("stated"), states.count("contradicted")
    if q["abstain"]:
        correct = declined and asserted == 0 and not stated
    else:
        correct = stated == len(states) and contradicted == 0 and asserted == 0
    return {"graded": True, "correct": correct, "fact_recall": stated / len(states) if states else None,
            "contradicted": contradicted, "forbidden_asserted": asserted, "declined": declined,
            "note": str(verdict.get("note") or "")[:300]}




# --------------------------------------------------------------------------------------------------------------------
# Repeats: one run's number moves by chance, so every measure is a mean over runs with its min–max beside it
# --------------------------------------------------------------------------------------------------------------------

#: The measures a run is scored on, in print order. Each is reported per run and as mean / min–max across runs.
MEASURES = ("correct", "correct_pct", "fact_recall_pct", "contradictions", "forbidden_asserted",
            "declined_when_should_know", "answered_when_should_decline", "seconds_p50")

#: The compare rule's significance level for the paired sign test (two-sided).
ALPHA = 0.05


def _run_of(row: dict) -> int:
    """A row's run index; a file written before repeats existed is run 1."""
    try:
        return int(row.get("run") or 1)
    except (TypeError, ValueError):
        return 1


def block(rs: list[dict]) -> dict:
    """One run's scores over ``rs`` (rows of that run only)."""
    graded = [r for r in rs if r["grade"].get("graded")]
    recalls = [r["grade"]["fact_recall"] for r in graded if r["grade"].get("fact_recall") is not None]
    secs = sorted(r["seconds"] for r in rs)
    right = sum(1 for r in graded if r["grade"]["correct"])
    return {"n": len(rs), "graded": len(graded), "correct": right,
            "correct_pct": round(100 * right / len(graded), 1) if graded else None,
            "fact_recall_pct": round(100 * sum(recalls) / len(recalls), 1) if recalls else None,
            "contradictions": sum(r["grade"].get("contradicted", 0) for r in graded),
            "forbidden_asserted": sum(r["grade"].get("forbidden_asserted", 0) for r in graded),
            "declined_when_should_know": sum(1 for r in graded if not r["abstain"] and r["grade"]["declined"]),
            "answered_when_should_decline": sum(1 for r in graded if r["abstain"] and not r["grade"]["declined"]),
            "seconds_p50": secs[len(secs) // 2] if secs else None}


def stability(rs: list[dict]) -> dict:
    """Per question, across the runs it was graded in: always right, always wrong, or flips (ids only)."""
    verdicts: dict[str, list[bool]] = defaultdict(list)
    for r in rs:
        verdicts.setdefault(r["id"], [])   # a question never graded is still counted
        if r["grade"].get("graded"):
            verdicts[r["id"]].append(bool(r["grade"]["correct"]))
    right = sorted(q for q, v in verdicts.items() if v and all(v))
    wrong = sorted(q for q, v in verdicts.items() if v and not any(v))
    flips = sorted(q for q, v in verdicts.items() if v and any(v) and not all(v))
    return {"always_right": len(right), "always_wrong": len(wrong), "flips": len(flips),
            "ungraded": sum(1 for v in verdicts.values() if not v), "flip_ids": flips}


def aggregate(rs: list[dict]) -> dict:
    """Mean and min–max of every measure across the runs in ``rs``, the per-run blocks, and per-question stability."""
    by_run: dict[int, list] = defaultdict(list)
    for r in rs:
        by_run[_run_of(r)].append(r)
    per_run = {run: block(by_run[run]) for run in sorted(by_run)}
    out: dict = {"runs": len(per_run), "questions": len({r["id"] for r in rs})}
    for m in MEASURES:
        vals = [b[m] for b in per_run.values() if b[m] is not None]
        out[m] = ({"mean": round(sum(vals) / len(vals), 2), "min": min(vals), "max": max(vals)}
                  if vals else {"mean": None, "min": None, "max": None})
    out["stability"] = stability(rs)
    out["per_run"] = per_run
    return out


def summarize(rows: list[dict]) -> dict:
    """Overall and per tag: each measure's mean and min–max across runs, and which questions flip."""
    tags: dict[str, list] = defaultdict(list)
    for r in rows:
        for t in r["tags"] or ["(untagged)"]:
            tags[t].append(r)
    return {"overall": aggregate(rows), "tags": {t: aggregate(rs) for t, rs in sorted(tags.items())}}


def _fmt(stat: dict, pct: bool = False) -> str:
    if stat["mean"] is None:
        return "-"
    unit = "%" if pct else ""
    if stat["min"] == stat["max"]:
        return f"{stat['mean']:g}{unit}"
    return f"{stat['mean']:g}{unit} ({stat['min']:g}–{stat['max']:g})"


def format_summary(summary: dict) -> str:
    """The terminal summary — measures, counts and question ids only, never question or answer text."""
    o = summary["overall"]
    st = o["stability"]
    lines = [f"{o['questions']} questions × {o['runs']} run(s) · mean (min–max across runs)",
             f"  correct              {_fmt(o['correct'])} questions · {_fmt(o['correct_pct'], True)}",
             f"  fact recall          {_fmt(o['fact_recall_pct'], True)}",
             f"  contradicted         {_fmt(o['contradictions'])}",
             f"  stale asserted       {_fmt(o['forbidden_asserted'])}",
             f"  declined, should know {_fmt(o['declined_when_should_know'])}",
             f"  answered, should decline {_fmt(o['answered_when_should_decline'])}",
             f"  p50 seconds          {_fmt(o['seconds_p50'])}",
             f"  per question: {st['always_right']} always right · {st['always_wrong']} always wrong · "
             f"{st['flips']} flip" + (f" · {st['ungraded']} never graded" if st["ungraded"] else "")]
    if st["flip_ids"]:
        lines.append("  flips: " + " ".join(st["flip_ids"]))
    for tag, b in summary["tags"].items():
        s = b["stability"]
        lines.append(f"  {tag:24} correct {_fmt(b['correct_pct'], True)}  facts {_fmt(b['fact_recall_pct'], True)}"
                     f"  (n={b['questions']}; {s['always_right']} right · {s['always_wrong']} wrong · "
                     f"{s['flips']} flip)")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------------------------------
# Compare: accept or reject a change on per-question majorities, not on one run's number
# --------------------------------------------------------------------------------------------------------------------

def majorities(rows: list[dict]) -> dict[str, bool | None]:
    """Per question: True when it was right in more than half of its graded runs, False when in fewer, None on a tie
    (or never graded) — a tie has no majority and is left out of the sign test."""
    votes: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        votes.setdefault(r["id"], [])
        if r["grade"].get("graded"):
            votes[r["id"]].append(bool(r["grade"]["correct"]))
    out: dict[str, bool | None] = {}
    for q, v in votes.items():
        right = sum(v)
        out[q] = None if not v or 2 * right == len(v) else 2 * right > len(v)
    return out


def sign_test_p(gained: int, lost: int) -> float:
    """Exact two-sided sign test: under no change, a question whose majority moved is equally likely to have moved
    either way, so the count that moved up is Binomial(gained + lost, 1/2)."""
    from math import comb

    n = gained + lost
    if n == 0:
        return 1.0
    k = min(gained, lost)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def _like_for_like(meta_a: list[dict], meta_b: list[dict]) -> list[str]:
    """What differs between the two files' runs besides the code: models, effort, CLI version, engine, top-k."""
    notes = []
    for key in ("engine", "answer_model", "judge_model", "effort", "effort_env", "top_k", "claude_version"):
        va = sorted({str(m.get(key)) for m in meta_a})
        vb = sorted({str(m.get(key)) for m in meta_b})
        if meta_a and meta_b and va != vb:
            notes.append(f"{key} differs: {', '.join(va)} → {', '.join(vb)}")
    return notes


def _models_used(rows: list[dict]) -> list[str]:
    return sorted({m for r in rows for m in (r.get("answer_models") or []) + (r.get("judge_models") or [])})


def compare(rows_a: list[dict], rows_b: list[dict], meta_a: list[dict] | None = None,
            meta_b: list[dict] | None = None) -> dict:
    """Before (A) vs after (B), on the questions both files graded.

    The rule (stated in the output): B differs from A only when ALL hold —
    1. the exact two-sided sign test on questions whose majority verdict changed gives p < ``ALPHA``,
    2. the difference in mean correct (count, over the shared questions) is larger than the runs' own spread
       (the wider of the two files' min–max of correct), and
    3. the two point the same way (more majorities gained than lost and the mean up, or both down).
    Anything else is within noise.
    """
    ids = sorted({r["id"] for r in rows_a} & {r["id"] for r in rows_b})
    keep = set(ids)
    ra = [r for r in rows_a if r["id"] in keep]
    rb = [r for r in rows_b if r["id"] in keep]
    ma, mb = majorities(ra), majorities(rb)
    gained = sorted(q for q in ids if ma.get(q) is False and mb.get(q) is True)
    lost = sorted(q for q in ids if ma.get(q) is True and mb.get(q) is False)
    no_majority = sorted(q for q in ids if ma.get(q) is None or mb.get(q) is None)
    agg_a, agg_b = aggregate(ra), aggregate(rb)
    ca, cb = agg_a["correct"], agg_b["correct"]
    delta = round(cb["mean"] - ca["mean"], 2) if ca["mean"] is not None and cb["mean"] is not None else None
    spread_a = ca["max"] - ca["min"] if ca["mean"] is not None else 0
    spread_b = cb["max"] - cb["min"] if cb["mean"] is not None else 0
    spread = max(spread_a, spread_b)
    p = sign_test_p(len(gained), len(lost))
    beyond_spread = delta is not None and abs(delta) > spread
    significant = p < ALPHA
    # The two readings must point the same way: majorities moving up while the mean falls (or the reverse) is noise.
    agree = delta is not None and (len(gained) - len(lost)) * delta > 0
    if significant and beyond_spread and agree:
        verdict = "better" if delta > 0 else "worse"
    elif significant and beyond_spread:
        verdict = "within noise (directions disagree)"
    else:
        verdict = "within noise"
    notes = _like_for_like(meta_a or [], meta_b or [])
    if _models_used(ra) and _models_used(rb) and _models_used(ra) != _models_used(rb):
        notes.append(f"models the engine reported differ: {', '.join(_models_used(ra))} → "
                     f"{', '.join(_models_used(rb))}")
    if min(agg_a["runs"], agg_b["runs"]) < 3:
        notes.append("fewer than 3 runs on a side: its spread is not measured well (use --repeats 3 or more)")
    only = sorted(({r["id"] for r in rows_a} ^ {r["id"] for r in rows_b}))
    return {"questions": len(ids), "runs_a": agg_a["runs"], "runs_b": agg_b["runs"],
            "correct_a": ca, "correct_b": cb, "delta_correct": delta, "spread": spread,
            "fact_recall_a": agg_a["fact_recall_pct"], "fact_recall_b": agg_b["fact_recall_pct"],
            "gained": gained, "lost": lost, "no_majority": no_majority, "sign_test_p": round(p, 4),
            "significant": significant, "beyond_spread": beyond_spread, "directions_agree": agree,
            "verdict": verdict,
            "only_in_one": only, "notes": notes,
            "rule": (f"B differs from A only when the exact two-sided sign test on questions whose majority verdict "
                     f"changed gives p < {ALPHA} AND |mean correct B − mean correct A| exceeds the wider min–max "
                     f"of correct across either file's runs, AND both move the same way; otherwise within noise")}


def format_compare(c: dict) -> str:
    lines = [f"{c['questions']} shared questions · A {c['runs_a']} run(s), B {c['runs_b']} run(s)",
             f"  correct   A {_fmt(c['correct_a'])}  →  B {_fmt(c['correct_b'])}   Δ {c['delta_correct']:+g}"
             f"   spread {c['spread']:g}" if c["delta_correct"] is not None else "  correct: not graded",
             f"  facts     A {_fmt(c['fact_recall_a'], True)}  →  B {_fmt(c['fact_recall_b'], True)}",
             f"  majority changed: {len(c['gained'])} wrong→right, {len(c['lost'])} right→wrong · "
             f"sign test p = {c['sign_test_p']:g}"
             + (f" · {len(c['no_majority'])} without a majority left out" if c["no_majority"] else "")]
    if c["gained"]:
        lines.append("  wrong→right: " + " ".join(c["gained"]))
    if c["lost"]:
        lines.append("  right→wrong: " + " ".join(c["lost"]))
    if c["only_in_one"]:
        lines.append(f"  {len(c['only_in_one'])} question(s) in one file only, left out: " + " ".join(c["only_in_one"]))
    lines.append(f"  verdict: {c['verdict'].upper()}"
                 f" (sign test {'p < ' if c['significant'] else 'p ≥ '}{ALPHA}; "
                 f"Δ {'beyond' if c['beyond_spread'] else 'within'} the runs' spread; "
                 f"majority moves and Δ {'agree' if c['directions_agree'] else 'disagree'})")
    for n in c["notes"]:
        lines.append(f"  note: {n}")
    lines.append(f"  rule: {c['rule']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------------------------------
# Results file
# --------------------------------------------------------------------------------------------------------------------

def read_results(path: Path) -> tuple[dict[tuple[str, int], dict], list[dict]]:
    """Answer rows keyed by (question id, run) — the last one written wins — and the run header rows."""
    rows: dict[tuple[str, int], dict] = {}
    meta: list[dict] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("kind") == "answer":
                rows[(row["id"], _run_of(row))] = row
            elif row.get("kind") == "run":
                meta.append(row)
    return rows, meta


def _settings(engine: str, answer_model: str, judge_model: str, effort: str | None = None):
    from api.config import get_settings

    base = get_settings()
    # The plan's `--effort` rides the seam's one effort channel (R-E11: "reasoning off" → `--effort
    # <agent_low_effort>`), set here to the pinned level for this eval's own calls only.
    pin = {"agent_low_effort": effort} if effort else {}
    plan = base.model_copy(update={"llm_mode": "agent", "agent_model": judge_model, **pin})
    if engine == "plan":
        answer = base.model_copy(update={"llm_mode": "agent", "agent_model": answer_model, **pin})
    else:
        answer = base
    return answer, plan


def _claude_version() -> str | None:
    """The plan CLI's version (no model call) — a CLI upgrade between two runs can move its defaults."""
    import subprocess

    try:
        out = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=15)
        return out.stdout.strip().split()[0] if out.returncode == 0 and out.stdout.strip() else None
    except Exception:  # noqa: BLE001
        return None


#: The settings a run is made under. A results file holds runs of ONE set of them: resuming into a file written under
#: other settings would mix two systems into one mean.
RUN_SETTINGS = ("engine", "answer_model", "judge_model", "effort", "effort_env", "top_k", "claude_version")


def settings_conflicts(recorded: list[dict], meta: dict) -> list[str]:
    """Each run setting this invocation would change in a file whose runs recorded others."""
    out = []
    for key in RUN_SETTINGS:
        before = sorted({str(m.get(key)) for m in recorded if key in m})
        if before and before != [str(meta.get(key))]:
            out.append(f"{key}: file has {', '.join(before)}, this run {meta.get(key)}")
    return out


def run_eval(questions: list[dict], out: Path, *, repeats: int, answer_fn, judge_fn, meta: dict,
             fresh: bool = False, only: bool = False, show: bool = False, models_fn=None) -> list[dict]:
    """Answer and judge every (question, run) not already in ``out``; append each row as it lands.

    Run-major: run 1 covers every question before run 2 starts, so a stopped eval leaves whole runs behind.
    ``answer_fn(question) -> resp`` and ``judge_fn(messages) -> str`` are the engine; ``models_fn()`` (optional)
    returns and clears the models the engine reported since the last call.

    ``fresh`` over every question (``only`` false) starts the file over; ``fresh`` with ``only`` re-asks those
    questions into it. Either way a file is never resumed under run settings other than the ones it recorded.
    """
    if fresh and not only and out.exists():
        out.write_text("", encoding="utf-8")
    done, recorded = read_results(out)
    conflicts = settings_conflicts(recorded, meta)
    if conflicts:
        raise SystemExit(f"{out} holds runs made under other settings — " + "; ".join(conflicts)
                         + ". Give a new --out, or --fresh (without --only) to start this file over.")
    if fresh:
        done = {}
    # A pair that failed (no verdict) is asked again; only graded pairs are kept.
    done = {k: r for k, r in done.items() if r["grade"].get("graded")}
    wanted = {q["id"] for q in questions}
    rows = [r for (qid, run), r in done.items() if qid in wanted and run <= repeats]
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.chmod(out, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        for run in range(1, repeats + 1):
            todo = [q for q in questions if (q["id"], run) not in done]
            if not todo:
                continue
            fh.write(json.dumps({"kind": "run", "run": run, "at": datetime.now(timezone.utc).isoformat(),
                                 **meta}) + "\n")
            for q in todo:
                started = time.perf_counter()
                if models_fn:
                    models_fn()
                try:
                    resp = answer_fn(q["question"])
                    error = None
                except Exception as exc:  # noqa: BLE001 — one failure is recorded, never fatal
                    resp, error = {"answer": ""}, type(exc).__name__
                seconds = round(time.perf_counter() - started, 2)
                answer_models = models_fn() if models_fn else []
                answer = str(resp.get("answer") or "")
                verdict = None
                try:
                    from api.services import json_parse

                    verdict = json_parse.parse_json_object(judge_fn(
                        [{"role": "system", "content": JUDGE_SYSTEM},
                         {"role": "user", "content": judge_prompt(q, answer)}]) or "")
                except Exception as exc:  # noqa: BLE001
                    error = error or f"judge: {type(exc).__name__}"
                judge_models = models_fn() if models_fn else []
                row = {"kind": "answer", "id": q["id"], "run": run, "tags": q["tags"], "abstain": q["abstain"],
                       "question": q["question"], "answer": answer, "confidence": resp.get("confidence"),
                       "gaps": resp.get("gaps"), "cited": [c.get("entity_id") for c in resp.get("citations") or []],
                       "grade": grade(q, verdict), "verdict": verdict, "seconds": seconds, "error": error,
                       "answer_models": answer_models, "judge_models": judge_models,
                       **{k: meta.get(k) for k in ("engine", "answer_model", "judge_model", "effort")}}
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                rows.append(row)
                g = row["grade"]
                mark = "ungraded" if not g.get("graded") else ("right" if g["correct"] else "wrong")
                line = (f"{q['id']:>10}  run {run}  {mark:8}  "
                        f"facts {g.get('fact_recall') if g.get('graded') else '-'}  {seconds:.1f} s")
                if show:
                    line += f"\n    Q: {q['question']}\n    A: {answer}\n    judge: {g.get('note', '')}"
                print(line, flush=True)
        summary = summarize(rows)
        fh.write(json.dumps({"kind": "summary", "at": datetime.now(timezone.utc).isoformat(), **summary}) + "\n")
    return rows


def _load_for_report(path: Path) -> tuple[list[dict], list[dict]]:
    if not path.is_file():
        raise SystemExit(f"no results file at {path}")
    rows, meta = read_results(path)
    if not rows:
        raise SystemExit(f"no answer rows in {path}")
    return list(rows.values()), meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bank", type=Path, help="the bank folder to ask (named explicitly, never guessed)")
    ap.add_argument("--questions", type=Path)
    ap.add_argument("--engine", choices=("plan", "configured"), default="plan")
    ap.add_argument("--answer-model", default="sonnet")
    ap.add_argument("--judge-model", default="sonnet")
    ap.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"),
                    help="pin the plan CLI's --effort for the answer and judge calls (default: the model's own)")
    ap.add_argument("--top-k", type=int, default=6)
    ap.add_argument("--repeats", type=int, default=3, help="answer and judge each question this many times (3)")
    ap.add_argument("--only", nargs="*", help="these question ids only")
    ap.add_argument("--out", type=Path, help="results (JSON Lines, 0600); default benchmark_results/answer_eval/")
    ap.add_argument("--fresh", action="store_true",
                    help="start --out over (with --only: re-ask just those questions into it)")
    ap.add_argument("--show", action="store_true", help="print each question, answer and judge note")
    ap.add_argument("--summary", type=Path, metavar="RESULTS", help="print the summary of a results file; no calls")
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("A", "B"),
                    help="before (A) vs after (B) results files: majority changes and the accept rule; no calls")
    ap.add_argument("--json", action="store_true", help="with --summary or --compare: print JSON")
    a = ap.parse_args(argv)

    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    if a.summary:
        rows, _ = _load_for_report(a.summary)
        s = summarize(rows)
        print(json.dumps(s, indent=1) if a.json else format_summary(s))
        return 0
    if a.compare:
        (ra, ma), (rb, mb) = _load_for_report(a.compare[0]), _load_for_report(a.compare[1])
        c = compare(ra, rb, ma, mb)
        print(json.dumps(c, indent=1) if a.json else format_compare(c))
        return 0
    if not a.bank or not a.questions:
        ap.error("--bank and --questions are required to run (or give --summary / --compare)")
    if a.repeats < 1:
        ap.error("--repeats is at least 1")

    os.environ.setdefault("CICADA_TELEMETRY", "off")   # a measurement, not the person's use
    os.environ.setdefault("CICADA_CAPTURE", "off")
    if a.effort:
        # The CLI lets this variable override --effort; a pin the shell can undo is no pin.
        os.environ.pop("CLAUDE_CODE_EFFORT_LEVEL", None)
    bank = a.bank.expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(f"no entities/ under {bank} — --bank takes a bank folder", file=sys.stderr)
        return 2
    questions = load_questions(a.questions)
    if a.only:
        questions = [q for q in questions if q["id"] in set(a.only)]
    if not questions:
        print("no questions", file=sys.stderr)
        return 2
    out = a.out or REPO / "benchmark_results" / "answer_eval" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.resolve() == bank or bank in out.resolve().parents:
        print("--out must be outside the bank", file=sys.stderr)
        return 2

    from api.services import agent_engine, ask_service, providers

    answer_settings, judge_settings = _settings(a.engine, a.answer_model, a.judge_model, a.effort)
    pin = {"extra_body": {"reasoning": {"enabled": False}}} if a.effort else {}
    llm_fn = ask_service._default_llm_fn(answer_settings, **(pin if a.engine == "plan" else {}))
    judge = providers.resolve_llm_fn(judge_settings, stage="judge", is_async=False)

    def answer_fn(question: str) -> dict:
        return ask_service.answer_query(bank, question, top_k=a.top_k, llm_fn=llm_fn, no_engine=False)

    def judge_fn(messages: list[dict]) -> str:
        reply = judge(messages=messages, response_format={"type": "json_object"}, **pin)
        return reply.choices[0].message.content or ""

    def models_fn() -> list[str]:
        used = agent_engine.models_used()
        agent_engine.reset_models_used()
        return used

    meta = {"engine": a.engine, "answer_model": a.answer_model if a.engine == "plan" else "configured",
            "judge_model": a.judge_model, "effort": a.effort, "top_k": a.top_k,
            "effort_env": os.environ.get("CLAUDE_CODE_EFFORT_LEVEL"), "claude_version": _claude_version()}
    rows = run_eval(questions, out, repeats=a.repeats, answer_fn=answer_fn, judge_fn=judge_fn, meta=meta,
                    fresh=a.fresh, only=bool(a.only), show=a.show, models_fn=models_fn)
    print("\n" + format_summary(summarize(rows)))
    print(f"\nresults: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
