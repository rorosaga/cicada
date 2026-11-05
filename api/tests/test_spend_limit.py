"""ROR-102, ruling 63 (g): a run on a key stops at the person's figure, keeping what it read."""
from __future__ import annotations

import asyncio
from pathlib import Path
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


# ---- how far past the line (the #614 review's three cases, on a costly model) ----------------------------------------

OPUS = "anthropic/claude-opus-5-5"
#: One read writing all it may, at the stand-in's three characters a token.
LONG_READ = " " * (sleep_spend.READ_OUTPUT_TOKENS * 3)


def _costly(body):
    system, user = body["system"][0]["text"], body["messages"][-1]["content"]
    text = _answer(system, user)
    return text + LONG_READ if "entities" in system[:400].lower() else text


def _conversations(n):
    return [{"source_id": f"spend:{i}", "day": i - n, "turns": [
        f"alpha-project uses sqlite-tool. gamma{i}-project uses delta-tool.", "Noted.", "alpha-project status building."]}
        for i in range(n)]


def _costly_run(tmp_path, monkeypatch, *, limit, batch, conversations):
    stub = StubAnthropic(answer=_costly, latency=0.01)
    stub.install(monkeypatch)
    monkeypatch.setattr(sleep_run_prefs, "load", lambda _registry: sleep_run_prefs.RunOptions(spend_limit_usd=limit))
    monkeypatch.setattr(engine_parity, "BATCH_SIZE", batch)
    snap = engine_parity.run_leg("key", model=OPUS, judge=OPUS, out=tmp_path / "key", conversations=_conversations(conversations))
    return snap, sleep_cycle.get_sleep_state().drain


@pytest.mark.parametrize("limit, batch, conversations", [(5.0, 25, 14), (1.0, 25, 14), (5.0, 50, 6)])
def test_a_costly_model_passes_the_line_by_about_one_read_and_its_filing(tmp_path, monkeypatch, limit, batch, conversations):
    snap, ds = _costly_run(tmp_path, monkeypatch, limit=limit, batch=batch, conversations=conversations)
    one_read = ds.spend.read_cap_usd
    assert one_read > 1.0, "the point is a model where one read is a large share of the figure"
    assert limit <= ds.spend.spent_usd <= limit + one_read * 1.2, snap["failures"]
    assert snap["failures"]["stop"] == "reserve" and snap["episodes_processed"] < conversations, "the rest wait"
    assert not snap["failures"]["parked"] and not snap["failures"]["unread"], "a read the limit refused is nobody's failure"


def test_the_first_call_goes_alone_and_then_only_what_there_is_room_for():
    guard = sleep_spend.SpendGuard(5.0)
    assert guard.try_admit() and not guard.try_admit(), "no price is known yet"
    guard.observe(1.5)
    guard.release()
    assert guard.try_admit() and guard.try_admit() and guard.try_admit(), "1.5 + 2 out at 1.5 still leaves room"
    assert not guard.try_admit(), "1.5 + 3 out at 1.5 + one more would pass it: wait and see"
    for _ in range(3):
        guard.observe(1.5)
        guard.release()
    with pytest.raises(engine_errors.SpendLimitReached):
        guard.try_admit()


def test_a_batch_is_sized_to_the_allowance_left():
    guard = sleep_spend.SpendGuard(5.0, read_cap_usd=1.5)
    assert guard.batch_size(25) == 3, "before any is known, the most one read may write"
    assert sleep_spend.SpendGuard(5.0, read_cap_usd=0.01).batch_size(25) == 25, "never more than the person's batch"
    assert sleep_spend.SpendGuard(5.0).batch_size(25) == 25
    guard.observe(1.0)
    guard.note_filed(2)
    assert guard.batch_size(25) == 8, "4.00 left at 0.50 each, read and filing together"
    guard.observe(3.9)
    guard.note_filed(0)
    assert guard.batch_size(25) == 1, "a batch that filed nothing teaches nothing, and the line is what stops a run"


# ---- each call answers to the limit, wherever it runs ----------------------------------------------------------------


@pytest.fixture
def past_the_line():
    guard = sleep_spend.SpendGuard(1.0)
    guard.observe(1.0)
    sleep_drain.register_batch("c1", SimpleNamespace(spend=guard, drain_id="d1", note_call=lambda: None))
    yield guard
    sleep_drain.unregister_batch("c1")


def _fn(stage, *, scope="sleep:c1", sink=lambda e: None, **kw):
    return providers.resolve_llm_fn(Settings(_env_file=None, llm_mode="byok", litellm_model=KEY), model=KEY,
                                    stage=stage, sink=sink, bank="b", scope=scope, **kw)


@pytest.mark.parametrize("stage", sorted(sleep_spend.LINE_STAGES))
def test_a_read_or_a_paid_step_past_the_line_is_never_sent(monkeypatch, past_the_line, stage):
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    with pytest.raises(engine_errors.SpendLimitReached):
        _fn(stage, is_async=False)(messages=[{"role": "user", "content": "alpha"}])
    assert stub.requests == [] and past_the_line.spent_usd == 1.0


def test_a_waiting_read_is_checked_again_once_it_holds_its_permit(monkeypatch):
    """The stop_check before the permit passed: the run crossed the line while this read queued."""
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    guard = sleep_spend.SpendGuard(1.0)
    sleep_drain.register_batch("c1", SimpleNamespace(spend=guard, drain_id="d1", note_call=lambda: None))
    try:
        fn = _fn("extraction")
        assert not guard.is_reached()
        guard.observe(1.0)

        async def go():
            await fn(messages=[{"role": "user", "content": "alpha"}])

        with pytest.raises(engine_errors.SpendLimitReached):
            asyncio.run(go())
    finally:
        sleep_drain.unregister_batch("c1")
    assert stub.requests == [] and guard._out == 0


def test_another_keys_read_past_the_line_is_never_sent_and_holds_no_place(past_the_line):
    sent = []

    async def completion(**kw):
        sent.append(kw)
        raise AssertionError("never sent")

    fn = providers.resolve_llm_fn(Settings(_env_file=None, llm_mode="byok", litellm_model="gpt-5.4-mini"), model="gpt-5.4-mini",
                                  completion=completion, stage="extraction", sink=lambda e: None, bank="b", scope="sleep:c1")

    async def go():
        await fn(messages=[{"role": "user", "content": "alpha"}])

    with pytest.raises(engine_errors.SpendLimitReached):
        asyncio.run(go())
    assert sent == [] and past_the_line._out == 0


def test_filing_what_was_read_is_never_refused(monkeypatch, past_the_line):
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    _fn("merge", is_async=False)(messages=[{"role": "user", "content": "alpha"}])
    assert len(stub.requests) == 1, "otherwise the reads already paid for are lost"
    assert past_the_line.spent_usd > 1.0, "and what it cost still counts"


def test_a_call_outside_a_run_is_not_limited_and_shows_in_the_ledger(monkeypatch, past_the_line):
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    events: list = []
    _fn("ask", scope="ask:one", sink=events.append, is_async=False)(messages=[{"role": "user", "content": "alpha"}])
    assert len(stub.requests) == 1 and past_the_line.spent_usd == 1.0, "Ask is not the run's, whatever the run has spent"
    assert len(events) == 1 and events[0].cost_usd > 0, "and what it cost is on the record"


def test_the_words_say_what_the_limit_does_not_cover():
    swift = (Path(__file__).parents[2] / "app/CicadaApp/Sources/CicadaApp/Theme/Copy+SleepV5.swift").read_text(encoding="utf-8")
    words = swift.split("static let spendHelp =", 1)[1].split("static let", 1)[0]
    for said in ("Sleep runs only", "about one read over at most"):
        assert said in words, said
    assert "a little past" not in words


# ---- a charged call whose cost cannot be read ------------------------------------------------------------------------


def _unspent_drain():
    guard = sleep_spend.SpendGuard(5.0)
    sleep_drain.register_batch("c1", SimpleNamespace(spend=guard, drain_id="d1", note_call=lambda: None))
    return guard


def test_a_cost_that_cannot_be_read_stops_the_run(monkeypatch):
    StubAnthropic(answer=lambda b: "{}").install(monkeypatch)
    guard = _unspent_drain()
    try:
        def unreadable(_resp):
            raise ValueError("usage")

        monkeypatch.setattr(providers.telemetry, "usage_from_response", unreadable)
        _fn("extraction", is_async=False)(messages=[{"role": "user", "content": "alpha"}])
    finally:
        sleep_drain.unregister_batch("c1")
    assert guard.is_reached() and guard.no_price and guard.sentence == sleep_spend.NO_PRICE_SENTENCE


def test_a_ledger_that_cannot_write_is_not_a_cost_nobody_knows(monkeypatch):
    StubAnthropic(answer=lambda b: "{}").install(monkeypatch)
    guard = _unspent_drain()
    try:
        def broken(_event):
            raise OSError("disk")

        _fn("extraction", sink=broken, is_async=False)(messages=[{"role": "user", "content": "alpha"}])
    finally:
        sleep_drain.unregister_batch("c1")
    assert guard.spent_usd > 0 and not guard.no_price


# ---- the tail ---------------------------------------------------------------------------------------------------------


def test_a_run_past_the_limit_with_nothing_left_to_read_skips_the_paid_tail(tmp_path, monkeypatch):
    ran: list = []

    def spy(name):
        async def step(*_a, **_k):
            ran.append(name)
        return step

    for name in ("_in_short_safely", "_media_read_safely", "_web_check_safely", "_web_context_safely", "_backfill_links_safely"):
        monkeypatch.setattr(sleep_cycle, name, spy(name))
    stub = StubAnthropic(answer=lambda b: _answer(b["system"][0]["text"], b["messages"][-1]["content"]))
    stub.install(monkeypatch)
    monkeypatch.setattr(sleep_run_prefs, "load", lambda _registry: sleep_run_prefs.RunOptions(spend_limit_usd=0.000001))
    snap = engine_parity.run_leg("key", model=KEY, judge=KEY, out=tmp_path / "key", conversations=CONVERSATIONS[:1])
    assert snap["episodes_processed"] == 1 and snap["failures"]["stop"] is None, "everything was read: a finished run"
    assert sleep_cycle.get_sleep_state().drain.spend.is_reached()
    assert ran == [], "past the line, the tail's paid steps do not start"


def test_link_backfill_is_the_runs_counted_and_held_to_the_limit(tmp_path, monkeypatch):
    from api.services import agent_engine, engine_select, link_enrichment

    guard = sleep_spend.SpendGuard(1.0)
    drain = SimpleNamespace(spend=guard, drain_id="d1", note_call=lambda: None)
    state = sleep_cycle.get_sleep_state()
    monkeypatch.setattr(state, "cycle_id", "c9", raising=False)
    monkeypatch.setattr(state, "drain", drain, raising=False)
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    seen: dict = {}

    async def backfill(_memory, _resolved, **_kw):
        scope = agent_engine.current_scope()
        seen["drain"] = sleep_drain.drain_for(agent_engine.cycle_id_from_scope(scope))
        fn = _fn("enrichment", scope=None, is_async=False)
        fn(messages=[{"role": "user", "content": "alpha"}])
        guard.observe(1.0)
        with pytest.raises(engine_errors.SpendLimitReached):
            fn(messages=[{"role": "user", "content": "alpha"}])
        return SimpleNamespace(selected=0, related=0, skipped=0, reused=0, summarized=0)

    async def resolve(settings, **_kw):
        return settings, "test"

    monkeypatch.setattr(link_enrichment, "backfill", backfill)
    monkeypatch.setattr(link_enrichment, "scan_backfill", lambda *_a: SimpleNamespace(junk=[], reuse=[], fetch=[1]))
    monkeypatch.setattr(engine_select, "resolve_settings", resolve)
    settings = Settings(_env_file=None, llm_mode="byok", litellm_model=KEY, memory_path=tmp_path)
    asyncio.run(sleep_cycle._backfill_links_safely(tmp_path, settings, user_triggered=True))
    assert seen["drain"] is drain and guard.spent_usd > 1.0 and len(stub.requests) == 1
    assert sleep_drain.drain_for("c9-links") is None


def test_a_claude_keys_call_goes_through_the_one_door_for_sensitive_text(monkeypatch):
    """G235, ruling 60 meets G237: a key's direct path is no way around what is held back."""
    from api.services import sensitive_hold

    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    monkeypatch.setattr(sensitive_hold, "hold_back", lambda messages, _bank: [{"role": "user", "content": "held"}])
    _fn("ask", scope="ask:one", is_async=False)(messages=[{"role": "user", "content": "alpha"}])
    assert stub.requests[0]["messages"][-1]["content"] == "held"
