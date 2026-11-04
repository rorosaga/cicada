"""ROR-102, ruling 63 (g): a run on a key stops at the person's figure, keeping what it read."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("anthropic")

from fastapi.testclient import TestClient

from api.config import Settings
from api.services import anthropic_engine, engine_errors, providers, sleep_cycle, sleep_drain, sleep_paused, sleep_run_prefs, sleep_spend
from api.tests.anthropic_stub import StubAnthropic
from api.tests.test_engine_parity import CONVERSATIONS, _answer
from benchmarks import engine_parity

KEY = "anthropic/claude-haiku-5-5"


class Registry:
    def __init__(self, entry=None):
        self.entry = entry if entry is not None else {}

    def prefs(self):
        return {sleep_run_prefs.PREF_KEY: self.entry}

    def set_pref(self, _connection, key, value):
        if value is None:
            self.entry.pop(key, None)
        else:
            self.entry[key] = value


@pytest.fixture(autouse=True)
def _idle():
    state = sleep_cycle.get_sleep_state()
    state.status, state.drain, state.drain_run, state.cancel_requested, state.error = "idle", None, False, False, None
    yield
    state.status, state.drain, state.drain_run, state.cancel_requested = "idle", None, False, False
    anthropic_engine.reset_clients()


# ---- the figure ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("stored, reads", [
    ({}, sleep_spend.DEFAULT_USD), ({"spend_limit_usd": 12.5}, 12.5), ({"spend_limit_usd": 0}, None),
    ({"spend_limit_usd": -3}, sleep_spend.DEFAULT_USD), ({"spend_limit_usd": "lots"}, sleep_spend.DEFAULT_USD),
    ({"spend_limit_usd": True}, sleep_spend.DEFAULT_USD), ({"spend_limit_usd": 1e9}, sleep_spend.DEFAULT_USD),
])
def test_a_figure_is_the_persons_and_nonsense_never_spends_more(stored, reads):
    assert sleep_run_prefs.load(Registry(stored)).spend_limit_usd == reads


def test_off_is_stored_as_the_persons_off_and_survives_a_read():
    reg = Registry()
    sleep_run_prefs.write(reg, spend_limit_usd=None)
    assert reg.entry == {"spend_limit_usd": 0} and sleep_run_prefs.load(reg).spend_limit_usd is None
    sleep_run_prefs.write(reg, spend_limit_usd=20)
    assert sleep_run_prefs.load(reg).spend_limit_usd == 20


def test_the_route_takes_a_figure_or_off_and_refuses_the_rest(tmp_path, monkeypatch):
    from api.config import get_settings
    from api.main import app

    monkeypatch.setenv("CICADA_HOME", str(tmp_path))
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, memory_path=tmp_path / "bank")
    try:
        client = TestClient(app)
        body = client.get("/sleep/run-options").json()
        assert body["spendLimitUsd"] == sleep_spend.DEFAULT_USD and body["spendLimitChoices"] == list(sleep_spend.CHOICES)
        assert client.put("/sleep/run-options", json={"spendLimitUsd": 7.5}).json()["spendLimitUsd"] == 7.5
        assert client.put("/sleep/run-options", json={"spendLimitUsd": None}).json()["spendLimitUsd"] is None
        for bad in (0, -1, 1e12):
            assert client.put("/sleep/run-options", json={"spendLimitUsd": bad}).status_code == 422
    finally:
        app.dependency_overrides.pop(get_settings, None)


# ---- which engines it holds on ---------------------------------------------------------------------------------------


def _resolved(model, **kw):
    return SimpleNamespace(litellm_model=model, effective_consolidation_model=model, litellm_disambiguation_model=model, **kw)


def test_only_a_run_charged_per_use_has_a_limit():
    assert isinstance(sleep_spend.guard_for(_resolved(KEY), 5.0), sleep_spend.SpendGuard)
    assert sleep_spend.guard_for(_resolved(KEY), None) is None, "the person's off"
    assert sleep_spend.guard_for(_resolved("ollama/llama3.1"), 5.0) is None, "a local model costs nothing"


def test_a_model_with_no_known_price_is_told_before_anything_is_read():
    guard = sleep_spend.guard_for(_resolved("anthropic/claude-sonnet-9-9"), 5.0)
    assert guard.is_reached() and guard.spent_usd == 0.0 and guard.sentence == sleep_spend.NO_PRICE_SENTENCE
    assert not sleep_spend.guard_for(_resolved(KEY), 5.0).is_reached()


def test_a_call_that_reports_no_price_stops_the_run_and_a_priced_one_adds_up():
    guard = sleep_spend.SpendGuard(1.0)
    guard.observe(0.4)
    guard.observe(0.4)
    assert not guard.is_reached()
    guard.observe(0.2)
    assert guard.is_reached() and guard.sentence == sleep_spend.SENTENCE
    unpriced = sleep_spend.SpendGuard(1.0)
    unpriced.observe(None)
    assert unpriced.is_reached() and unpriced.sentence == sleep_spend.NO_PRICE_SENTENCE


def test_every_sentence_fits_the_sleep_pages_line_and_names_no_figure():
    for sentence in (sleep_spend.SENTENCE, sleep_spend.NO_PRICE_SENTENCE):
        assert len(sentence) <= 80 and "$" not in sentence   # SentenceLine.maxTail; ruling 12


# ---- the seam --------------------------------------------------------------------------------------------------------


def test_a_paid_failure_counts_and_a_call_never_charged_does_not(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "word " * 900, stop_reason="max_tokens")
    stub.install(monkeypatch)
    seen: list = []
    monkeypatch.setattr(sleep_drain, "note_spend", lambda _cycle, cost: seen.append(cost))
    fn = providers.resolve_llm_fn(Settings(_env_file=None, llm_mode="byok", litellm_model=KEY), model=KEY,
                                  stage="extraction", sink=lambda e: None, bank="b", scope="spend-test")
    with pytest.raises(engine_errors.EngineProtocolError):
        fn(messages=[{"role": "user", "content": "alpha"}])
    assert len(seen) == 1 and seen[0] > 0
    seen.clear()
    from api.tests.anthropic_stub import error_body

    StubAnthropic(fail=[(400, error_body("invalid_request_error", "no"), {})]).install(monkeypatch)
    with pytest.raises(engine_errors.EngineFailed):
        fn(messages=[{"role": "user", "content": "alpha"}])
    assert seen == [], "a request refused before an answer cost nothing, and is not an unknown price"


# ---- through the production drain ------------------------------------------------------------------------------------


def _run(tmp_path, monkeypatch, *, limit, model=KEY):
    stub = StubAnthropic(answer=lambda b: _answer(b["system"][0]["text"], b["messages"][-1]["content"]))
    stub.install(monkeypatch)
    monkeypatch.setattr(sleep_run_prefs, "load", lambda _registry: sleep_run_prefs.RunOptions(spend_limit_usd=limit))
    monkeypatch.setattr(engine_parity, "BATCH_SIZE", 1)
    snap = engine_parity.run_leg("key", model=model, judge=model, out=tmp_path / "key", conversations=CONVERSATIONS)
    return snap, stub


def test_a_run_past_the_limit_is_a_pause_in_words_and_keeps_what_it_read(tmp_path, monkeypatch):
    snap, stub = _run(tmp_path, monkeypatch, limit=0.000001)
    failures = snap["failures"]
    assert failures["error"] is None and failures["stop"] == "reserve", failures
    assert failures["stop_sentence"] == sleep_spend.SENTENCE
    ds = sleep_cycle.get_sleep_state().drain
    assert ds.stop.limit == "spend" and sleep_paused.reason_for(ds.stop) == "spend"
    assert snap["episodes_processed"] == 1, "the batch already read is filed, the rest wait"
    assert snap["engine_trailers"] == ["anthropic-api"] and not failures["parked"]
    assert ds.spend.spent_usd >= ds.spend.limit_usd > 0


def test_off_reads_everything(tmp_path, monkeypatch):
    snap, _stub = _run(tmp_path, monkeypatch, limit=None)
    assert snap["failures"]["stop"] is None and snap["episodes_processed"] == 3


def test_an_unpriced_model_stops_before_any_call_is_made(tmp_path, monkeypatch):
    snap, stub = _run(tmp_path, monkeypatch, limit=5.0, model="anthropic/claude-sonnet-9-9")
    assert snap["failures"]["stop"] == "reserve" and snap["failures"]["stop_sentence"] == sleep_spend.NO_PRICE_SENTENCE
    assert stub.requests == [] and snap["episodes_processed"] == 0
