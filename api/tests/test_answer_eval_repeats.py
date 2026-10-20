"""benchmarks/answer_eval.py: repeats, resume, the across-run summary and the compare rule — on a fake engine,
no plan calls, synthetic questions only."""
import json

from benchmarks import answer_eval

QUESTIONS = [
    {"id": "steady", "question": "Q1", "expect": ["f1"], "forbid": [], "abstain": False, "tags": ["people"]},
    {"id": "never", "question": "Q2", "expect": ["f2"], "forbid": [], "abstain": False, "tags": ["projects"]},
    {"id": "flaky", "question": "Q3", "expect": ["f3"], "forbid": [], "abstain": False, "tags": ["people"]},
    {"id": "unknown", "question": "Q4", "expect": [], "forbid": [], "abstain": True, "tags": []},
]

STATED = json.dumps({"expected": [{"n": 1, "verdict": "stated"}], "forbidden": [], "declined": False})
MISSING = json.dumps({"expected": [{"n": 1, "verdict": "missing"}], "forbidden": [], "declined": False})
DECLINED = json.dumps({"expected": [], "forbidden": [], "declined": True})


class FakeEngine:
    """Answers echo the question; the judge's verdict comes from a script keyed by (question text, call number)."""

    def __init__(self, script):
        self.script = script
        self.answers: list[str] = []
        self.judged: dict[str, int] = {}

    def answer(self, question):
        self.answers.append(question)
        return {"answer": f"answer to {question}", "confidence": 0.5, "gaps": [], "citations": []}

    def judge(self, messages):
        q = messages[1]["content"].split("QUESTION:\n", 1)[1].split("\n", 1)[0]
        n = self.judged.get(q, 0)
        self.judged[q] = n + 1
        return self.script(q, n)


def default_script(q, n):
    return {"Q1": STATED, "Q2": MISSING, "Q3": STATED if n % 2 == 0 else MISSING, "Q4": DECLINED}[q]


def _run(tmp_path, out, engine, repeats=3, **kw):
    return answer_eval.run_eval(QUESTIONS, out, repeats=repeats, answer_fn=engine.answer, judge_fn=engine.judge,
                                meta={"engine": "plan", "answer_model": "sonnet", "judge_model": "sonnet",
                                      "effort": None}, **kw)


def test_repeats_answer_every_question_each_run_and_tag_rows_with_their_run(tmp_path):
    out = tmp_path / "a.jsonl"
    eng = FakeEngine(default_script)
    rows = _run(tmp_path, out, eng)
    assert len(rows) == 12 and len(eng.answers) == 12
    assert sorted({(r["id"], r["run"]) for r in rows}) == sorted((q["id"], r) for q in QUESTIONS for r in (1, 2, 3))
    # run-major: run 1 covers every question before run 2 starts
    assert [r["run"] for r in rows] == [1] * 4 + [2] * 4 + [3] * 4
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert [ln["run"] for ln in lines if ln["kind"] == "run"] == [1, 2, 3]
    assert lines[-1]["kind"] == "summary"
    assert oct(out.stat().st_mode & 0o777) == "0o600"


def test_resume_asks_only_the_missing_question_runs(tmp_path):
    out = tmp_path / "a.jsonl"
    _run(tmp_path, out, FakeEngine(default_script), repeats=2)
    eng = FakeEngine(default_script)
    rows = _run(tmp_path, out, eng, repeats=3)
    assert eng.answers == ["Q1", "Q2", "Q3", "Q4"]           # run 3 only
    assert len(rows) == 12
    done, meta = answer_eval.read_results(out)
    assert len(done) == 12 and [m["run"] for m in meta] == [1, 2, 3]
    again = FakeEngine(default_script)
    _run(tmp_path, out, again, repeats=3)
    assert again.answers == []                                # nothing left to ask
    fresh = FakeEngine(default_script)
    _run(tmp_path, out, fresh, repeats=1, fresh=True)
    assert len(fresh.answers) == 4


def test_resume_asks_a_failed_pair_again(tmp_path):
    out = tmp_path / "a.jsonl"
    broken = FakeEngine(lambda q, n: "not json" if q == "Q3" else default_script(q, n))
    rows = _run(tmp_path, out, broken, repeats=1)
    assert [r["grade"]["graded"] for r in rows] == [True, True, False, True]
    retry = FakeEngine(default_script)
    rows = _run(tmp_path, out, retry, repeats=1)
    assert retry.answers == ["Q3"] and all(r["grade"]["graded"] for r in rows) and len(rows) == 4


def test_a_file_written_before_repeats_reads_as_run_one(tmp_path):
    out = tmp_path / "old.jsonl"
    old = {"kind": "answer", "id": "steady", "tags": [], "abstain": False, "seconds": 1.0,
           "grade": answer_eval.grade(QUESTIONS[0], json.loads(STATED))}
    out.write_text(json.dumps(old) + "\n")
    eng = FakeEngine(default_script)
    _run(tmp_path, out, eng, repeats=2)
    assert eng.answers.count("Q1") == 1                       # run 1 of "steady" was already there


def test_summary_reports_mean_spread_and_which_questions_flip(tmp_path):
    rows = _run(tmp_path, tmp_path / "a.jsonl", FakeEngine(default_script))
    s = answer_eval.summarize(rows)
    o = s["overall"]
    assert o["runs"] == 3 and o["questions"] == 4
    # per run: steady + unknown right, flaky right on runs 1 and 3 → 3, 2, 3 correct
    assert [b["correct"] for b in o["per_run"].values()] == [3, 2, 3]
    assert o["correct"] == {"mean": 2.67, "min": 2, "max": 3}
    assert o["correct_pct"]["min"] == 50.0 and o["correct_pct"]["max"] == 75.0
    assert o["declined_when_should_know"]["mean"] == 0 and o["answered_when_should_decline"]["mean"] == 0
    st = o["stability"]
    assert (st["always_right"], st["always_wrong"], st["flips"]) == (2, 1, 1) and st["flip_ids"] == ["flaky"]
    people = s["tags"]["people"]
    assert people["questions"] == 2 and people["stability"]["flip_ids"] == ["flaky"]
    assert s["tags"]["projects"]["stability"]["always_wrong"] == 1
    text = answer_eval.format_summary(s)
    assert "flips: flaky" in text and "2.67 (2–3)" in text
    assert "Q1" not in text and "answer to" not in text       # ids and numbers only, never question text


def _rows_for(results: dict[str, list[bool]]) -> list[dict]:
    """Synthetic rows: question id → per-run correctness."""
    rows = []
    for qid, verdicts in results.items():
        for run, ok in enumerate(verdicts, 1):
            rows.append({"kind": "answer", "id": qid, "run": run, "tags": [], "abstain": False, "seconds": 1.0,
                         "grade": {"graded": True, "correct": ok, "fact_recall": 1.0 if ok else 0.0,
                                   "contradicted": 0, "forbidden_asserted": 0, "declined": False}})
    return rows


def test_sign_test_is_exact_and_two_sided():
    assert answer_eval.sign_test_p(0, 0) == 1.0
    assert answer_eval.sign_test_p(6, 0) == 2 / 64
    assert answer_eval.sign_test_p(5, 0) == 2 / 32           # 0.0625: five-nil is not enough at 0.05
    assert answer_eval.sign_test_p(3, 3) == 1.0
    assert answer_eval.sign_test_p(1, 8) == answer_eval.sign_test_p(8, 1)


def test_compare_calls_flipping_noise_within_noise():
    # Same system twice: the flaky questions land on either side of their majority by chance.
    a = {f"s{i}": [True] * 3 for i in range(30)} | {f"w{i}": [False] * 3 for i in range(10)}
    b = dict(a)
    a |= {"f1": [True, True, False], "f2": [False, False, True], "f3": [True, False, True], "f4": [False, True, False]}
    b |= {"f1": [False, True, False], "f2": [True, True, False], "f3": [False, False, True], "f4": [True, True, False]}
    c = answer_eval.compare(_rows_for(a), _rows_for(b))
    assert c["questions"] == 44 and c["gained"] == ["f2", "f4"] and c["lost"] == ["f1", "f3"]
    assert c["sign_test_p"] == 1.0 and c["verdict"] == "within noise"
    out = answer_eval.format_compare(c)
    assert "WITHIN NOISE" in out and "sign test" in out and "rule:" in out


def test_compare_accepts_a_real_gain_and_names_the_questions():
    a = {f"s{i}": [True] * 3 for i in range(30)} | {f"w{i}": [False] * 3 for i in range(10)}
    a |= {"f1": [True, False, True], "f2": [False, True, False]}
    b = dict(a)
    for i in range(7):                                        # a change that fixes seven always-wrong questions
        b[f"w{i}"] = [True, True, True]
    c = answer_eval.compare(_rows_for(a), _rows_for(b))
    assert c["gained"] == [f"w{i}" for i in range(7)] and c["lost"] == []
    assert c["sign_test_p"] < answer_eval.ALPHA and c["delta_correct"] == 7 and c["spread"] == 0
    assert c["verdict"] == "better"
    worse = answer_eval.compare(_rows_for(b), _rows_for(a))
    assert worse["verdict"] == "worse" and worse["lost"] == [f"w{i}" for i in range(7)]


def test_compare_needs_both_the_sign_test_and_a_gap_wider_than_the_spread():
    a = {f"s{i}": [True] * 3 for i in range(20)} | {f"w{i}": [False] * 3 for i in range(10)}
    # A's runs spread widely (a block of questions that all fail together on one run)
    a |= {f"v{i}": [True, True, False] for i in range(10)}
    b = dict(a)
    for i in range(6):
        b[f"w{i}"] = [True, True, False]                      # six majority gains, p = 0.03, but Δ 4 < spread 16
    c = answer_eval.compare(_rows_for(a), _rows_for(b))
    assert c["significant"] and not c["beyond_spread"] and c["verdict"] == "within noise"


def test_compare_leaves_out_ties_and_one_sided_questions_and_flags_unlike_runs():
    a = _rows_for({"x": [True, False], "y": [True, True], "only-a": [True, True]})
    b = _rows_for({"x": [False, False], "y": [False, False]})
    meta_a = [{"engine": "plan", "answer_model": "sonnet", "effort": None, "claude_version": "2.1.300"}]
    meta_b = [{"engine": "plan", "answer_model": "sonnet", "effort": None, "claude_version": "2.1.304"}]
    c = answer_eval.compare(a, b, meta_a, meta_b)
    assert c["no_majority"] == ["x"] and c["lost"] == ["y"] and c["only_in_one"] == ["only-a"]
    assert any("claude_version differs" in n for n in c["notes"])
    assert any("fewer than 3 runs" in n for n in c["notes"])


def test_summary_and_compare_commands_make_no_calls(tmp_path, capsys):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _run(tmp_path, a, FakeEngine(default_script))
    _run(tmp_path, b, FakeEngine(lambda q, n: STATED if q != "Q4" else DECLINED))
    assert answer_eval.main(["--summary", str(a)]) == 0
    assert "flips: flaky" in capsys.readouterr().out
    assert answer_eval.main(["--compare", str(a), str(b), "--json"]) == 0
    c = json.loads(capsys.readouterr().out)
    assert c["gained"] == ["never"] and c["verdict"] == "within noise"   # one question moved: p = 1


def test_effort_pin_reaches_the_plan_cli_for_answer_and_judge(monkeypatch, agent_runner, claude_stream):
    from api.services import agent_engine, ask_service, providers
    from api.services.connections.base import CliResult

    runner = agent_runner(CliResult(0, claude_stream("success"), ""))
    monkeypatch.setattr(agent_engine, "_default_runner", lambda: runner)
    pin = {"extra_body": {"reasoning": {"enabled": False}}}
    answer_s, judge_s = answer_eval._settings("plan", "sonnet", "haiku", "medium")
    ask_service._default_llm_fn(answer_s, **pin)("prompt")
    providers.resolve_llm_fn(judge_s, stage="judge", is_async=False)(messages=[{"role": "user", "content": "x"}],
                                                                      **pin)
    plain_answer, _ = answer_eval._settings("plan", "sonnet", "haiku", None)
    ask_service._default_llm_fn(plain_answer)("prompt")
    argvs = [c["argv"] for c in runner.calls]
    assert argvs[0][argvs[0].index("--effort") + 1] == "medium" and "sonnet" in argvs[0]
    assert argvs[1][argvs[1].index("--effort") + 1] == "medium" and "haiku" in argvs[1]
    assert "--effort" not in argvs[2]                         # no pin: the model's own default, as before
