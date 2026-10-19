"""The public-benchmark harness (LoCoMo / LongMemEval through Cicada): loaders, judges, report, isolation, and one
offline end-to-end unit through the production intake, Sleep and Ask with the deterministic engine."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from benchmarks.public import datasets, judges, report
from benchmarks.public.run import RUN_MARKER, unit_env
from benchmarks.system.runner import REPO


def _locomo_sample(sample_id="conv-x"):
    """A LoCoMo-shaped conversation in the deterministic engine's grammar (placeholder names)."""
    return {
        "sample_id": sample_id,
        "conversation": {
            "speaker_a": "alice-example", "speaker_b": "bob-example",
            "session_1_date_time": "1:56 pm on 8 May, 2023",
            "session_1": [
                {"speaker": "alice-example", "dia_id": "D1:1", "text": "alpha-project uses sqlite-tool."},
                {"speaker": "bob-example", "dia_id": "D1:2", "text": "beta-project runs-on primary-machine."},
                {"speaker": "alice-example", "dia_id": "D1:3", "text": "We talked it through.",
                 "blip_caption": "a photo of a whiteboard"},
            ],
            "session_2_date_time": "10:01 am on 20 May, 2023",
            "session_2": [
                {"speaker": "alice-example", "dia_id": "D2:1", "text": "alpha-project uses sqlite-tool."},
                {"speaker": "bob-example", "dia_id": "D2:2", "text": "alpha-project status planning."},
                {"speaker": "alice-example", "dia_id": "D2:3", "text": "beta-project runs-on primary-machine."},
                {"speaker": "bob-example", "dia_id": "D2:4", "text": "Agreed."},
            ],
        },
        "qa": [
            {"question": "What does alpha-project use?", "answer": "sqlite-tool", "evidence": ["D1:1"], "category": 4},
            {"question": "What is the status of alpha-project?", "answer": "planning", "evidence": ["D2:2"],
             "category": 1},
            {"question": "When did gamma happen?", "adversarial_answer": "never", "evidence": [], "category": 5},
        ],
    }


def test_locomo_loader_maps_speakers_dates_captions_and_categories(tmp_path):
    path = tmp_path / "locomo.json"
    path.write_text(json.dumps([_locomo_sample()]))
    [unit] = datasets.locomo_units(path)
    assert unit["owner"] == {"name": "alice-example"} and unit["other"]["name"] == "bob-example"
    first, second = unit["sessions"]
    assert first["date"].startswith("2023-05-08T13:56") and second["date"].startswith("2023-05-20T10:01")
    assert [t["speaker"] for t in first["turns"]] == ["user", "other", "user"]
    assert first["turns"][2]["text"].endswith("[shares a photo: a photo of a whiteboard]")
    cats = [(q["category"], q["abstention"]) for q in unit["questions"]]
    assert cats == [("single-hop", False), ("multi-hop", False), ("adversarial", True)]
    assert unit["questions"][2]["answer"] == "never"
    assert unit["clock"] > second["date"]
    sliced = datasets.select([unit], skip_categories=("adversarial",), per_category=1)
    assert [q["category"] for q in sliced[0]["questions"]] == ["single-hop", "multi-hop"]


def test_longmemeval_loader_one_unit_per_question(tmp_path):
    item = {"question_id": "q1_abs", "question_type": "single-session-user", "question": "Q?", "answer": "A",
            "question_date": "2023/05/30 (Tue) 10:00", "haystack_dates": ["2023/05/20 (Sat) 02:21"],
            "haystack_session_ids": ["s1"], "answer_session_ids": ["s1"],
            "haystack_sessions": [[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]]}
    path = tmp_path / "lme.json"
    path.write_text(json.dumps([item]))
    [unit] = datasets.longmemeval_units(path, "oracle")
    assert unit["owner"] is None and unit["dataset"] == "longmemeval-oracle"
    assert [t["speaker"] for t in unit["sessions"][0]["turns"]] == ["user", "assistant"]
    q = unit["questions"][0]
    assert q["abstention"] and q["question_date"].startswith("2023-05-30T10:00") and unit["clock"] == q["question_date"]


def test_pinned_dataset_refuses_a_tampered_file(tmp_path):
    (tmp_path / "locomo10.json").write_text("[]")
    with pytest.raises(ValueError, match="sha256"):
        datasets.dataset_path("locomo", tmp_path)
    with pytest.raises(FileNotFoundError):
        datasets.dataset_path("longmemeval-oracle", tmp_path)


def test_judges_are_the_published_prompts_and_parsers():
    p = judges.mem0_prompt("Q?", "Gold", "Gen")
    assert p.startswith('Your task is to label an answer to a question as "CORRECT" or "WRONG".')
    assert "Question: Q?\n\nGold answer: Gold\n\nGenerated answer: Gen\n" in p
    assert p.endswith('Just return the label CORRECT or WRONG in a json format with the key as "label".')
    assert judges.parse_mem0('The answer matches. {"label": "CORRECT"}') is True
    assert judges.parse_mem0("Different topic. WRONG") is False
    assert judges.parse_mem0("CORRECT or WRONG?") is None
    lme = judges.lme_prompt("temporal-reasoning", "Q", "A", "R", abstention=False)
    assert "do not penalize off-by-one errors" in lme and lme.endswith("Answer yes or no only.")
    abst = judges.lme_prompt("multi-session", "Q", "A", "R", abstention=True)
    assert "unanswerable" in abst
    # The one amendment: a "none recorded" / "zero as far as the record goes" reply is an abstention; the published
    # sentences are kept whole and in order, the amendment sits just before the question.
    published = judges.LME_TEMPLATES["abstention"].split("\n\nQuestion: {}")[0]
    assert abst.startswith(published + " " + judges.ABSTENTION_AMENDMENT + "\n\nQuestion: Q")
    assert "zero as far as the record goes" in abst and abst.endswith("Answer yes or no only.")
    assert judges.ABSTENTION_AMENDMENT not in judges.lme_prompt("multi-session", "Q", "A", "R", abstention=False)
    assert judges.ABSTENTION_AMENDMENT not in judges.mem0_prompt("Q", "A", "R")
    assert "Rubric: A" in judges.lme_prompt("single-session-preference", "Q", "A", "R", abstention=False)
    with pytest.raises(ValueError):
        judges.lme_prompt("made-up", "Q", "A", "R", abstention=False)
    assert judges.parse_lme("Yes.") and not judges.parse_lme("No")


def test_locomo_f1_follows_the_reference_rules():
    assert judges.locomo_f1("sqlite-tool", "sqlite-tool", 4) == 1.0
    assert judges.locomo_f1("The answer is unrelated", "sqlite tool", 2) == 0.0
    assert judges.locomo_f1("red, blue", "red, blue", 1) == 1.0               # multi-hop: per sub-answer
    assert judges.locomo_f1("x; y", "x; y", 3) == pytest.approx(judges.f1_score("x; y", "x"))  # first of ';'
    assert judges.locomo_f1("Not mentioned in the conversation", "", 5) == 1.0


def test_unit_environment_is_allowlisted_and_pins_the_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "forbidden"))
    monkeypatch.setenv("USER", "alice-example")
    cfg = {"answer_model": "sonnet", "disambiguation_model": "haiku", "concurrency": 2, "embedding_model": ""}
    env = unit_env(tmp_path / "home", tmp_path / "bank", cfg, "/claude-home")
    assert env["CICADA_MEMORY_PATH"] == str(tmp_path / "bank") and env["HOME"] == str(tmp_path / "home")
    assert env["CICADA_LLM_MODE"] == "agent" and env["CICADA_CAPTURE"] == "off" and env["CICADA_TELEMETRY"] == "off"
    assert env["HF_HUB_OFFLINE"] == "1" and env["CICADA_BENCH_CLAUDE_HOME"] == "/claude-home"
    assert "OPENAI_API_KEY" not in env
    assert env["USER"] == "alice-example"     # the CLI's keychain lookup needs the account name


def test_report_scores_paths_and_categories_apart(tmp_path):
    run = tmp_path / "run"
    unit = run / "units" / "u1"
    unit.mkdir(parents=True)
    (run / "config.json").write_text(json.dumps({"dataset": "locomo", "paths": ["ask"], "sleep_model": "s",
                                                 "disambiguation_model": "d", "answer_model": "a",
                                                 "judge_model": "j"}))
    rows = [
        {"key": "1|ask", "qid": "1", "path": "ask", "category": "single-hop", "abstention": False, "correct": True, "f1": 1.0},
        {"key": "2|ask", "qid": "2", "path": "ask", "category": "single-hop", "abstention": False, "correct": False, "f1": 0.0},
        {"key": "3|ask", "qid": "3", "path": "ask", "category": "adversarial", "abstention": True, "correct": True, "f1": 1.0},
    ]
    (unit / "judgments.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (unit / "answers.jsonl").write_text(json.dumps({"key": "1|ask", "path": "ask", "seconds": 2.0, "cited": 1}) + "\n")
    (unit / "calls.jsonl").write_text(json.dumps({"phase": "sleep", "stage": "extraction", "seconds": 3.0, "ok": True}) + "\n")
    s = report.summarize(run)
    ask = s["paths"]["ask"]
    assert ask["n"] == 2 and ask["accuracy"] == 50.0          # adversarial never in the headline
    assert ask["categories"]["adversarial"]["accuracy"] == 100.0
    assert s["calls_total"] == 1 and "J 50.0%" in report.render(s)
    assert s["judge_protocol"] == judges.JUDGE_PROTOCOL and "judging: " in report.render(s)


def test_offline_unit_runs_intake_sleep_ask_and_judge(tmp_path):
    """The whole harness, offline: marked bank, production stager, drain, Ask, judge, resume is a no-op."""
    cache = tmp_path / "cache"
    home = cache / "home"
    home.mkdir(parents=True)
    (home / "_bench_home.yaml").write_text(json.dumps({"kind": "cicada-system-benchmark-v1"}) + "\n")
    data = tmp_path / "locomo.json"
    data.write_text(json.dumps([_locomo_sample()]))
    cmd = [sys.executable, "-m", "benchmarks.public.run", "run", "--cache", str(cache), "--dataset", "locomo",
           "--fake-engine", "--dataset-file", str(data), "--paths", "ask,full-context", "--concurrency", "1",
           "--batch-size", "2", "--claude-home", str(tmp_path / "no-claude")]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=300)
    [run_dir] = list((cache / "runs").iterdir())
    log = (run_dir / "units" / "conv-x" / "child.log").read_text() if (run_dir / "units" / "conv-x" / "child.log").exists() else ""
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-4000:] + log[-8000:]
    assert (run_dir / RUN_MARKER).is_file()
    state = json.loads((run_dir / "units" / "conv-x" / "state.json").read_text())
    assert state["done"] and state["slept"] and state["bank"]["claims"] > 0
    bank = run_dir / "banks" / "conv-x"
    assert (bank / "_bench.yaml").is_file() and (bank / ".git").is_dir()
    summary = json.loads((run_dir / "report.json").read_text())
    ask = summary["paths"]["ask"]
    assert ask["n"] == 2 and ask["categories"]["single-hop"]["accuracy"] == 100.0, summary
    assert summary["paths"]["full-context"]["n"] == 2
    assert summary["calls_by_phase"]["sleep"]["calls"] > 0 and summary["calls_by_phase"]["judge"]["calls"] == 4
    # Resume: nothing is redone.
    calls_before = summary["calls_total"]
    proc = subprocess.run([sys.executable, "-m", "benchmarks.public.run", "run", "--cache", str(cache),
                           "--resume", str(run_dir), "--claude-home", str(tmp_path / "no-claude")],
                          cwd=REPO, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-4000:]
    assert json.loads((run_dir / "report.json").read_text())["calls_total"] == calls_before


# --- the owner's own answer-quality runner (benchmarks/answer_eval.py) ---------------------------------------------

def test_answer_eval_example_file_loads_and_validates(tmp_path):
    from benchmarks import answer_eval

    qs = answer_eval.load_questions(REPO / "benchmarks" / "answer_eval.example.yaml")
    assert qs and all(q["expect"] or q["abstain"] for q in qs)
    assert any(q["forbid"] for q in qs) and any(q["abstain"] for q in qs)
    bad = tmp_path / "bad.yaml"
    bad.write_text("questions:\n  - question: 'no facts?'\n")
    with pytest.raises(SystemExit, match="expect"):
        answer_eval.load_questions(bad)
    dup = tmp_path / "dup.yaml"
    dup.write_text("questions:\n  - {id: a, question: q, abstain: true}\n  - {id: a, question: r, abstain: true}\n")
    with pytest.raises(SystemExit, match="twice"):
        answer_eval.load_questions(dup)


def test_answer_eval_grades_facts_stale_values_and_abstention():
    from benchmarks import answer_eval

    q = {"id": "x", "question": "Q", "expect": ["f1", "f2"], "forbid": ["old"], "abstain": False, "tags": ["t"]}
    prompt = answer_eval.judge_prompt(q, "an answer")
    assert "1. f1\n2. f2" in prompt and "1. old" in prompt and "DECLINE" in prompt
    full = answer_eval.grade(q, {"expected": [{"n": 1, "verdict": "stated"}, {"n": 2, "verdict": "stated"}],
                                 "forbidden": [{"n": 1, "asserted": False}], "declined": False})
    assert full["correct"] and full["fact_recall"] == 1.0
    stale = answer_eval.grade(q, {"expected": [{"n": 1, "verdict": "stated"}, {"n": 2, "verdict": "stated"}],
                                  "forbidden": [{"n": 1, "asserted": True}]})
    assert not stale["correct"] and stale["forbidden_asserted"] == 1
    half = answer_eval.grade(q, {"expected": [{"n": 1, "verdict": "stated"}]})   # a missing verdict is "missing"
    assert not half["correct"] and half["fact_recall"] == 0.5
    assert answer_eval.grade(q, None) == {"graded": False}
    a = {"id": "y", "question": "Q", "expect": [], "forbid": [], "abstain": True, "tags": []}
    assert answer_eval.grade(a, {"declined": True})["correct"]
    assert not answer_eval.grade(a, {"declined": False})["correct"]
    rows = [{"tags": ["t"], "abstain": False, "seconds": 1.0, "grade": full},
            {"tags": ["t"], "abstain": False, "seconds": 3.0, "grade": stale},
            {"tags": [], "abstain": True, "seconds": 2.0, "grade": answer_eval.grade(a, {"declined": False})}]
    s = answer_eval.summarize(rows)
    assert s["overall"]["correct_pct"] == 33.3 and s["overall"]["answered_when_should_decline"] == 1
    assert s["tags"]["t"]["n"] == 2 and s["tags"]["(untagged)"]["n"] == 1


def test_unit_child_reads_no_settings_file(tmp_path):
    """A checkout's api/.env must not steer a benchmark child: scores never depend on whose machine ran them."""
    dotenv = tmp_path / ".env"
    dotenv.write_text("CICADA_EMBEDDING_MODEL_LOCAL=sentinel-from-dotenv\n")
    code = f"""
import sys
import benchmarks.public.unit as unit
assert not [m for m in sys.modules if m.startswith("api.services")], "unit imports api.services before isolating"
from api import config, settings_file
config.Settings.model_config["env_file"] = {str(dotenv)!r}   # what <checkout>/api/.env does by absolute path
config.get_settings.cache_clear()
assert config.get_settings().embedding_model_local == "sentinel-from-dotenv"   # the leak, reproduced
unit.isolate_settings()
assert settings_file.path() is None and config.Settings.model_config["env_file"] is None
assert config.get_settings().embedding_model_local != "sentinel-from-dotenv"
print("isolated")
"""
    env = unit_env(tmp_path / "home", tmp_path / "bank", {"answer_model": "sonnet", "disambiguation_model": "haiku",
                                                          "concurrency": 1, "embedding_model": ""}, str(tmp_path))
    proc = subprocess.run([sys.executable, "-P", "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0 and "isolated" in proc.stdout, proc.stderr[-3000:]
    import inspect

    from benchmarks.public import unit
    first = [line.strip() for line in inspect.getsource(unit.main).splitlines()[1:] if line.strip()][0]
    assert first.startswith("isolate_settings()"), first


def test_mem0_fallback_reads_whole_words():
    assert judges.parse_mem0("The answer is incorrect.") is None
    assert judges.parse_mem0("The answer is incorrect. WRONG") is False
    assert judges.parse_mem0("Same date, so CORRECT") is True


def test_report_counts_unanswered_and_ungraded_questions(tmp_path):
    run = tmp_path / "run"
    unit = run / "units" / "u1"
    unit.mkdir(parents=True)
    (run / "config.json").write_text(json.dumps({"dataset": "locomo", "paths": ["ask"], "sleep_model": "s",
                                                 "disambiguation_model": "d", "answer_model": "a",
                                                 "judge_model": "j"}))
    qs = [{"qid": str(i), "question": "Q", "answer": "A", "category": "single-hop", "category_id": 4,
           "abstention": False} for i in range(3)]
    (unit / "unit.json").write_text(json.dumps({"questions": qs}))
    (unit / "answers.jsonl").write_text("\n".join(json.dumps(a) for a in [
        {"key": "0|ask", "path": "ask", "seconds": 1.0},
        {"key": "1|ask", "path": "ask", "seconds": 1.0},
        {"key": "2|ask", "path": "ask", "seconds": 1.0, "error": "EngineUnavailable: x"}]) + "\n")
    (unit / "judgments.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"key": "0|ask", "qid": "0", "path": "ask", "category": "single-hop", "abstention": False, "correct": True,
         "f1": 1.0},
        {"key": "1|ask", "qid": "1", "path": "ask", "category": "single-hop", "abstention": False, "correct": None,
         "f1": 0.0}]) + "\n")
    s = report.summarize(run)["paths"]["ask"]
    assert (s["expected"], s["unanswered"], s["ungraded"]) == (3, 1, 1)
    assert s["accuracy"] == 100.0 and s["accuracy_all"] == 33.3
    assert "INCOMPLETE: 1 unanswered, 1 ungraded of 3" in report.render(report.summarize(run))


def test_drain_stops_are_told_apart_and_failed_answers_retried():
    from benchmarks.public import unit

    leg = {"stop": None, "error": None}
    assert unit.stop_exit(leg, paused=False) is None
    assert unit.stop_exit({"stop": "plan_limit", "error": "window"}, paused=True) == unit.PAUSED
    assert unit.stop_exit({"stop": "reserve", "error": "kept for you"}, paused=True) == unit.PAUSED
    assert unit.stop_exit({"stop": "engine", "error": "signed out"}, paused=True) == unit.STOPPED
    assert unit.stop_exit({"stop": "busy", "error": None}, paused=False) == unit.STOPPED
    with pytest.raises(RuntimeError):
        unit.stop_exit({"stop": "error", "error": "boom"}, paused=False)
    qs = [{"qid": "a"}, {"qid": "b"}, {"qid": "c"}]
    rows = {"a|ask": {"error": None}, "b|ask": {"error": "EngineUnavailable"}}
    assert [(q["qid"], p) for q, p in unit.answers_to_do(qs, ["ask"], rows)] == [("b", "ask"), ("c", "ask")]
