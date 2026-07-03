"""Repeatable retrieval eval: run each question x model through the cicada MCP,
score with an LLM judge, aggregate. Personal questions live in a gitignored
*.local.yaml; results go to benchmark_results/ (gitignored)."""
from __future__ import annotations
import json
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
