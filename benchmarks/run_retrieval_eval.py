"""Repeatable retrieval eval: run each question x model through the cicada MCP,
score with an LLM judge, aggregate. Personal questions live in a gitignored
*.local.yaml; results go to benchmark_results/ (gitignored)."""
from __future__ import annotations
import json
import subprocess
import yaml
from pathlib import Path

RUBRIC = ("correct: matches ground truth; partial: some right; wrong: confidently incorrect; "
          "hallucinated: asserts facts not in memory; honest-gap: correctly says memory lacks it "
          "(CORRECT only for negative-category); tool-failure: session errored / no tools used.")


def load_questions(path: str) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text())
    return list(data.get("questions", []))


def _extract_json(text: str) -> dict:
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return {}


def judge_answer(question: dict, model: str, answer: str, *, llm_fn=None) -> dict:
    prompt = (
        f"Judge a memory-retrieval answer.\nRUBRIC: {RUBRIC}\n\n"
        f"QUESTION: {question.get('question')}\nCATEGORY: {question.get('category')}\n"
        f"GROUND TRUTH: {question.get('ground_truth')}\n"
        f"EXPECTED ENTITIES: {question.get('expected_entities')}\n\nANSWER: {answer}\n\n"
        'Reply with JSON: {"verdict": <one rubric label>, "score": <0..1>, "diagnosis": <why>}.'
    )
    if llm_fn is None:  # pragma: no cover - resolved at runtime
        from api.config import get_settings
        from api.services.providers import resolve_llm_fn
        llm_fn = resolve_llm_fn(get_settings())
    resp = llm_fn(messages=[{"role": "user", "content": prompt}],
                  response_format={"type": "json_object"})
    content = resp["choices"][0]["message"]["content"]
    obj = _extract_json(content)
    return {
        "verdict": str(obj.get("verdict", "tool-failure")),
        "score": float(obj.get("score", 0.0) or 0.0),
        "diagnosis": str(obj.get("diagnosis", "")),
    }


def aggregate(rows: list[dict]) -> dict:
    agg: dict[str, dict] = {}
    for r in rows:
        m = r["model"]
        a = agg.setdefault(m, {"total": 0.0, "n": 0, "by_verdict": {}})
        a["total"] += float(r.get("score", 0.0) or 0.0)
        a["n"] += 1
        a["by_verdict"][r["verdict"]] = a["by_verdict"].get(r["verdict"], 0) + 1
    for a in agg.values():
        a["avg"] = round(a["total"] / a["n"], 3) if a["n"] else None
    return agg


PROMPT_TMPL = (
    "You have access to cicada memory tools (MCP 'cicada'). Use them (cicada_recall first; "
    "then cicada_recall_detail / cicada_open_hub / cicada_ask / cicada_sources as needed — DO "
    "follow through to recall_detail for full pages before concluding a fact is absent, and state "
    "only facts present in tool results) to answer this about the user. If genuinely absent, say so.\n"
    "Question: {q}"
)


def _default_runner(prompt: str, model: str, mcp_config: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["claude", "-p", "--model", model, "--mcp-config", mcp_config,
         "--strict-mcp-config", "--allowedTools", "mcp__cicada", "--max-turns", "14"],
        input=prompt, capture_output=True, text=True, timeout=300,
    )
    return proc.returncode, (proc.stdout or "")


def run_one(question: dict, model: str, mcp_config: str, *, runner=None) -> dict:
    runner = runner or _default_runner
    prompt = PROMPT_TMPL.format(q=question.get("question", ""))
    try:
        code, out = runner(prompt, model, mcp_config)
    except Exception as exc:  # subprocess timeout/crash never aborts the batch
        return {"model": model, "answer": f"(runner error: {exc})", "exit_ok": False}
    out = (out or "").strip()
    return {"model": model, "answer": out or "(empty)", "exit_ok": code == 0 and bool(out)}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True)
    ap.add_argument("--mcp-config", required=True)
    ap.add_argument("--models", default="claude-haiku-4-5-20251001,claude-sonnet-5")
    ap.add_argument("--out", default="benchmark_results/retrieval_eval")
    args = ap.parse_args(argv)

    questions = load_questions(args.questions)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    rows = []
    for q in questions:
        for m in models:
            r = run_one(q, m, args.mcp_config)
            v = (judge_answer(q, m, r["answer"]) if r["exit_ok"]
                 else {"verdict": "tool-failure", "score": 0.0, "diagnosis": "runner failed"})
            rows.append({"id": q["id"], "model": m, **v, "answer": r["answer"][:1000]})
    agg = aggregate(rows)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    (outdir / "aggregate.json").write_text(json.dumps(agg, indent=2))
    for m, a in agg.items():
        print(f"{m}: avg={a['avg']} n={a['n']} {a['by_verdict']}")
    return agg


if __name__ == "__main__":  # pragma: no cover
    main()
