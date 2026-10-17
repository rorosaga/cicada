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

**Privacy.** The question file is yours and gitignored (``benchmarks/*.local.*``). Answers, judgments and the summary
go to ``--out`` (default ``benchmark_results/answer_eval/<timestamp>.jsonl``, gitignored), written 0600. The terminal
shows question ids and scores only, unless ``--show``. Re-running with the same ``--out`` skips questions already
graded (``--fresh`` to redo them).
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


def summarize(rows: list[dict]) -> dict:
    def block(rs):
        graded = [r for r in rs if r["grade"].get("graded")]
        recalls = [r["grade"]["fact_recall"] for r in graded if r["grade"].get("fact_recall") is not None]
        secs = sorted(r["seconds"] for r in rs)
        return {"n": len(rs), "graded": len(graded),
                "correct_pct": round(100 * sum(r["grade"]["correct"] for r in graded) / len(graded), 1) if graded else None,
                "fact_recall_pct": round(100 * sum(recalls) / len(recalls), 1) if recalls else None,
                "contradictions": sum(r["grade"].get("contradicted", 0) for r in graded),
                "forbidden_asserted": sum(r["grade"].get("forbidden_asserted", 0) for r in graded),
                "declined_when_should_know": sum(1 for r in graded if not r["abstain"] and r["grade"]["declined"]),
                "answered_when_should_decline": sum(1 for r in graded if r["abstain"] and not r["grade"]["declined"]),
                "seconds_p50": secs[len(secs) // 2] if secs else None}

    tags: dict[str, list] = defaultdict(list)
    for r in rows:
        for t in r["tags"] or ["(untagged)"]:
            tags[t].append(r)
    return {"overall": block(rows), "tags": {t: block(rs) for t, rs in sorted(tags.items())}}


def _settings(engine: str, answer_model: str, judge_model: str):
    from api.config import get_settings

    base = get_settings()
    plan = base.model_copy(update={"llm_mode": "agent", "agent_model": judge_model})
    if engine == "plan":
        answer = base.model_copy(update={"llm_mode": "agent", "agent_model": answer_model})
    else:
        answer = base
    return answer, plan


def _read_rows(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("kind") == "answer":
                    rows[row["id"]] = row
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bank", required=True, type=Path, help="the bank folder to ask (named explicitly, never guessed)")
    ap.add_argument("--questions", required=True, type=Path)
    ap.add_argument("--engine", choices=("plan", "configured"), default="plan")
    ap.add_argument("--answer-model", default="sonnet")
    ap.add_argument("--judge-model", default="sonnet")
    ap.add_argument("--top-k", type=int, default=6)
    ap.add_argument("--only", nargs="*", help="these question ids only")
    ap.add_argument("--out", type=Path, help="results (JSON Lines, 0600); default benchmark_results/answer_eval/")
    ap.add_argument("--fresh", action="store_true", help="re-ask questions already in --out")
    ap.add_argument("--show", action="store_true", help="print each question, answer and judge note")
    a = ap.parse_args(argv)

    os.environ.setdefault("CICADA_TELEMETRY", "off")   # a measurement, not the person's use
    os.environ.setdefault("CICADA_CAPTURE", "off")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
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
    done = {} if a.fresh else _read_rows(out)

    from api.services import ask_service, json_parse, providers

    answer_settings, judge_settings = _settings(a.engine, a.answer_model, a.judge_model)
    llm_fn = ask_service._default_llm_fn(answer_settings)
    judge = providers.resolve_llm_fn(judge_settings, stage="judge", is_async=False)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.chmod(out, 0o600)
    rows = [r for r in done.values() if r["id"] in {q["id"] for q in questions}]
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        for q in questions:
            if q["id"] in done:
                continue
            started = time.perf_counter()
            try:
                resp = ask_service.answer_query(bank, q["question"], top_k=a.top_k, llm_fn=llm_fn, no_engine=False)
                error = None
            except Exception as exc:  # noqa: BLE001 — one failure is recorded, never fatal
                resp, error = {"answer": ""}, type(exc).__name__
            seconds = round(time.perf_counter() - started, 2)
            answer = str(resp.get("answer") or "")
            verdict = None
            try:
                reply = judge(messages=[{"role": "system", "content": JUDGE_SYSTEM},
                                        {"role": "user", "content": judge_prompt(q, answer)}],
                              response_format={"type": "json_object"})
                verdict = json_parse.parse_json_object(reply.choices[0].message.content or "")
            except Exception as exc:  # noqa: BLE001
                error = error or f"judge: {type(exc).__name__}"
            row = {"kind": "answer", "id": q["id"], "tags": q["tags"], "abstain": q["abstain"],
                   "question": q["question"], "answer": answer, "confidence": resp.get("confidence"),
                   "gaps": resp.get("gaps"), "cited": [c.get("entity_id") for c in resp.get("citations") or []],
                   "grade": grade(q, verdict), "verdict": verdict, "seconds": seconds, "error": error,
                   "engine": a.engine, "answer_model": a.answer_model if a.engine == "plan" else "configured",
                   "judge_model": a.judge_model}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            rows.append(row)
            g = row["grade"]
            mark = "ungraded" if not g.get("graded") else ("right" if g["correct"] else "wrong")
            line = f"{q['id']:>10}  {mark:8}  facts {g.get('fact_recall') if g.get('graded') else '-'}  {seconds:.1f} s"
            if a.show:
                line += f"\n    Q: {q['question']}\n    A: {answer}\n    judge: {g.get('note', '')}"
            print(line, flush=True)
        summary = summarize(rows)
        fh.write(json.dumps({"kind": "summary", "at": datetime.now(timezone.utc).isoformat(), **summary}) + "\n")
    o = summary["overall"]
    print(f"\n{o['graded']}/{o['n']} graded · correct {o['correct_pct']}% · fact recall {o['fact_recall_pct']}% · "
          f"{o['contradictions']} contradicted · {o['forbidden_asserted']} stale asserted · "
          f"{o['declined_when_should_know']} declined but should know · "
          f"{o['answered_when_should_decline']} answered but should decline · p50 {o['seconds_p50']} s")
    for tag, b in summary["tags"].items():
        print(f"  {tag:24} correct {b['correct_pct']}%  facts {b['fact_recall_pct']}%  (n={b['n']})")
    print(f"\nresults: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
