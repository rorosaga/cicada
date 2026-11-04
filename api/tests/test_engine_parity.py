"""G237: the same synthetic conversations through the production drain on each path, and what each made.

Stand-ins at the transport only: the plan leg's `claude -p` subprocess and the key leg's HTTP. The same deterministic
answer on both means any difference in pages, claims, spans, questions or failures is the path's own, never a model's.
That is what this proves; whether a real model reads as well is the owner's run (`benchmarks/engine_parity.py`).
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("anthropic")

from api.services import agent_engine, anthropic_engine, sleep_cycle
from api.services.connections.base import CliResult
from api.tests.anthropic_stub import StubAnthropic, error_body
from benchmarks import engine_parity
from benchmarks.system.engine import extraction

CONVERSATIONS = [
    {"source_id": "parity:a", "day": -3, "turns": [
        "alpha-project uses sqlite-tool. alpha-project status planning.", "Noted.", "beta-project runs-on primary-machine."]},
    {"source_id": "parity:b", "day": -2, "turns": [
        "alpha-project uses sqlite-tool. The second conversation confirms it.", "Understood.",
        "beta-project status building."]},
    {"source_id": "parity:c", "day": -1, "turns": ["gamma-project uses delta-tool.", "Good.", "gamma-project status planning."]},
]


def _answer(system: str, user: str) -> str:
    """One answer per kind of prompt, whichever path asked. Extraction from the conversation's own sentences."""
    if '"entities"' in system or "entities" in system[:400].lower():
        return json.dumps(extraction(user))
    if "same" in system.lower() and "decision" in system.lower():
        return json.dumps({"decision": "different", "reason": "Distinct identifiers."})
    if "skills" in system.lower():
        return json.dumps({"skills": []})
    if "contradiction" in system.lower():
        return json.dumps({"has_unresolvable_contradiction": False})
    if "updating an entity page" in system:
        return json.dumps({"summary": "A synthetic page.", "history": []})
    return "{}"


def _plan_runner(calls: list):
    """A `claude -p` that answers in the stream's shape, with the cache counters the CLI was measured reporting."""

    def run(argv, *, stdin=None, timeout=None, cwd=None, env_overrides=None):
        if "auth" in argv[:3]:
            return CliResult(rc=0, stdout=json.dumps({"loggedIn": True, "authMethod": "claude.ai"}), stderr="")
        system = next(a[len("--system-prompt="):] for a in argv if a.startswith("--system-prompt="))
        calls.append(argv)
        text = _answer(system, stdin or "")
        result = {"type": "result", "subtype": "success", "is_error": False, "result": text, "stop_reason": "end_turn",
                  "num_turns": 1, "total_cost_usd": 0.001,
                  "usage": {"input_tokens": 2, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 50,
                            "output_tokens": 20},
                  "modelUsage": {"claude-haiku-5-5": {"outputTokens": 20, "costUSD": 0.001}}}
        return CliResult(rc=0, stdout=json.dumps(result) + "\n", stderr="")

    return run


@pytest.fixture(autouse=True)
def _idle(monkeypatch):
    state = sleep_cycle.get_sleep_state()
    state.status, state.drain, state.drain_run, state.cancel_requested, state.error = "idle", None, False, False, None
    yield
    state.status, state.drain, state.drain_run, state.cancel_requested = "idle", None, False, False
    anthropic_engine.reset_clients()


def _plan(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(agent_engine, "_default_runner", lambda: _plan_runner(calls))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return engine_parity.run_leg("plan", model="haiku", judge="haiku", out=tmp_path / "plan", conversations=CONVERSATIONS), calls


def _key(tmp_path, monkeypatch, *, fail=None):
    def answer(body):
        return _answer(body["system"][0]["text"], body["messages"][-1]["content"])

    stub = StubAnthropic(answer=answer, fail=list(fail or []))
    stub.install(monkeypatch)
    snap = engine_parity.run_leg("key", model="anthropic/claude-haiku-5-5", judge="anthropic/claude-haiku-5-5",
                                 out=tmp_path / "key", conversations=CONVERSATIONS)
    return snap, stub


def test_same_answers_make_the_same_memory_on_both_paths(tmp_path, monkeypatch):
    plan, plan_calls = _plan(tmp_path, monkeypatch)
    state = sleep_cycle.get_sleep_state()
    state.status, state.drain, state.drain_run, state.cancel_requested, state.error = "idle", None, False, False, None
    key, stub = _key(tmp_path, monkeypatch)
    assert plan_calls and stub.requests, "both legs reached their transport"

    report = engine_parity.compare(plan, key)
    assert report["episodes_processed"] == {"a": 3, "b": 3}
    assert report["pages"]["a"] > 0 and report["pages"]["jaccard"] == 1.0, report["pages"]
    assert report["claims"]["a"] > 0 and report["claims"]["jaccard_exact"] == 1.0, report["claims"]
    assert report["claims"]["located_a"] == report["claims"]["located_b"], report["claims"]
    assert report["questions"]["jaccard"] == 1.0, report["questions"]
    assert report["failures"]["a"]["error"] is None and report["failures"]["b"]["error"] is None
    assert report["failures"]["a"]["stop"] is None and report["failures"]["b"]["stop"] is None
    # The same stages asked the same number of times: nothing runs on one path only.
    assert all(row["a"] == row["b"] for row in report["calls_by_stage"].values()), report["calls_by_stage"]
    # Who served it is the difference, and it is said.
    assert report["engine_trailers"] == {"a": ["claude-cli"], "b": ["anthropic-api"]}
    usage = report["usage"]["b"]
    assert usage["cache_read"] > 0 and usage["cost_usd"] and usage["hit_rate"] > 0
    assert report["usage"]["a"]["cost_usd"] is None, "a plan call is not money"
    # Past reads, from the same function the page uses: a charged figure on the key, an equivalent on the plan.
    assert key["past_reads"]["basis"] == "charged" and key["past_reads"]["cost_usd"] == pytest.approx(usage["cost_usd"], abs=1e-5)
    assert key["past_reads"]["connection"] == "byok-anthropic"
    assert plan["past_reads"]["basis"] == "list" and plan["past_reads"]["cost_usd"] is None
    # What was sent on the key path is what the API takes, on every call of the run.
    allowed = {"model", "max_tokens", "system", "messages", "output_config", "stream"}
    assert all(set(r) <= allowed for r in stub.requests)


def test_a_rate_limit_in_the_middle_of_a_run_is_a_pause_with_the_words_and_nothing_is_lost(tmp_path, monkeypatch):
    limit = (429, error_body("rate_limit_error", "Number of requests exceeded"), {"retry-after": "1"})
    monkeypatch.setattr(engine_parity, "BATCH_SIZE", 2)   # a second batch waits, so the run has somewhere to stop
    snap, stub = _key(tmp_path, monkeypatch, fail=[limit])
    failures = snap["failures"]
    assert failures["error"] is None
    assert failures["stop"] == "plan_limit", failures
    assert "rate-limiting the API key" in failures["stop_sentence"] and "plan" not in failures["stop_sentence"].lower()
    ds = sleep_cycle.get_sleep_state().drain
    assert ds.stop.limit == "key_limit" and ds.stop.resets_at
    assert not failures["parked"], "a limit is never charged to a conversation"
    # The conversation already read is filed (its later stages waited out the limit); the others wait.
    assert snap["episodes_processed"] == 1, snap["usage"]["by_stage"]
    assert snap["engine_trailers"] == ["anthropic-api"], "the batch's paid read was committed, not lost"


def test_a_spending_limit_stops_without_waiting_and_says_so(tmp_path, monkeypatch):
    spent = (429, error_body("rate_limit_error", "You have reached your API usage limits", "enforced_spend_limit_reached"), {})
    monkeypatch.setattr(engine_parity, "BATCH_SIZE", 2)
    snap, stub = _key(tmp_path, monkeypatch, fail=[spent])
    assert snap["failures"]["stop"] == "plan_limit" and "spending limit" in snap["failures"]["stop_sentence"]
    assert snap["failures"]["error"] is None


def test_the_gold_score_reads_prose_and_claims_about_the_subject(tmp_path):
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    (bank / "entities" / "alpha-project.md").write_text("alpha-project now uses theta-tool.")
    gold = [{"about": "alpha-project", "says": ["theta-tool"]}, {"about": "alpha-project", "says": ["sqlite-tool"]},
            {"about": "beta-project", "says": ["gamma-theory"]}]
    assert engine_parity.score_gold(bank, gold) == {
        "held": 1, "of": 3, "missing": ["alpha-project: sqlite-tool", "beta-project: gamma-theory"]}


def test_estimate_reads_the_measured_tokens_at_list_prices():
    snap = {"usage": {"by_stage": {
        "extraction": {"calls": 3, "input": 30_000, "output": 3_000, "cache_read": 14_000, "cache_write": 7_000},
        "disambiguation": {"calls": 1, "input": 1_000, "output": 100, "cache_read": 0, "cache_write": 0}}}}
    report = engine_parity.estimate(snap)
    assert report["total"]["calls"] == 4 and report["total"]["cache_read"] == 14_000
    assert report["by_stage"]["extraction"]["cost_usd"] < report["by_stage"]["extraction"]["cost_without_cache_usd"] * 2
    assert report["total"]["cost_usd"] > 0 and "pricing" in report["basis"]
    assert set(engine_parity.cost_table(snap)) >= {"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"}


def test_the_key_leg_refuses_without_the_spend_flags_and_a_real_path_refuses(tmp_path, capsys):
    assert engine_parity.main(["run", "--leg", "key", "--model", "anthropic/claude-haiku-5-5", "--out", str(tmp_path)]) == 2
    assert "spends money" in capsys.readouterr().err
    from pathlib import Path

    with pytest.raises(SystemExit):
        engine_parity._refuse_real_paths(Path.home() / ".cicada" / "x")


def test_a_key_file_gives_only_its_own_line(tmp_path):
    secrets = tmp_path / "secrets.env"
    secrets.write_text("OPENAI_API_KEY=not-this\nANTHROPIC_API_KEY=stub-key\n")
    assert engine_parity.read_key_file(secrets) == "stub-key"
