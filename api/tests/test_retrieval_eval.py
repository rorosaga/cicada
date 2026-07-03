import yaml
from benchmarks import run_retrieval_eval as ev


def test_load_questions(tmp_path):
    p = tmp_path / "q.yaml"
    p.write_text(yaml.safe_dump({"questions": [
        {"id": 1, "question": "Q?", "ground_truth": "A", "expected_entities": ["e"],
         "category": "fact", "difficulty": "hard"},
    ]}))
    qs = ev.load_questions(str(p))
    assert qs[0]["id"] == 1 and qs[0]["category"] == "fact"


def test_judge_answer_uses_injected_llm():
    # injected judge returns a fixed structured verdict; no network
    def fake_llm(*, messages, response_format=None, **kw):
        import json
        content = json.dumps({"verdict": "correct", "score": 0.9, "diagnosis": "matches"})
        return {"choices": [{"message": {"content": content}}]}
    v = ev.judge_answer(
        {"question": "Q?", "ground_truth": "A", "category": "fact", "expected_entities": []},
        "haiku", "A is the answer", llm_fn=fake_llm,
    )
    assert v["verdict"] == "correct" and v["score"] == 0.9


def test_aggregate_computes_per_model_average():
    rows = [
        {"model": "haiku", "score": 1.0, "verdict": "correct"},
        {"model": "haiku", "score": 0.0, "verdict": "wrong"},
        {"model": "sonnet", "score": 0.8, "verdict": "partial"},
    ]
    agg = ev.aggregate(rows)
    assert agg["haiku"]["avg"] == 0.5 and agg["haiku"]["n"] == 2
    assert agg["sonnet"]["avg"] == 0.8


def test_run_one_uses_injected_runner():
    def fake_runner(prompt, model, mcp_config):
        return (0, "The answer is A.")  # (exit_code, stdout)
    out = ev.run_one({"id": 1, "question": "Q?"}, "haiku", "/tmp/cfg.json", runner=fake_runner)
    assert out["exit_ok"] is True and "answer is a" in out["answer"].lower()


def test_run_one_marks_tool_failure_on_nonzero_exit():
    def fake_runner(prompt, model, mcp_config):
        return (1, "boom")
    out = ev.run_one({"id": 1, "question": "Q?"}, "haiku", "/tmp/cfg.json", runner=fake_runner)
    assert out["exit_ok"] is False
