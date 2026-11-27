"""A night that stops at the spending limit still closes questions (2026-11-27, ruling 63 (g), `sleep_spend.QUESTIONS_SHARE`).

On a key with a limit, reading stops at the figure less a part kept for the tail's question steps; those steps then spend
the rest, every call admitted or refused against the whole figure. A priced stand-in engine (no network, no key), the real
drain, the real guard, the real provider seam; the steps' own judging is replaced by stand-ins that make priced calls the way
`entity_resolver._same_name_ask` does (the label the batches' own filing shares)."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("anthropic")

from api.config import Settings
from api.services import (anthropic_engine, engine_errors, entity_resolver, providers, question_steps, sleep_cycle,
                          sleep_drain, sleep_run_prefs, sleep_runs, sleep_spend)
from api.tests.anthropic_stub import StubAnthropic
from api.tests.test_engine_parity import _answer
from benchmarks import engine_parity

SONNET = "anthropic/claude-sonnet-5-5"
#: What the stand-in's replies are padded to, in characters (the stub counts three a token): a conversation's reading costs
#: about what the owner's run measured (27 conversations, 5 dollars), a question call about what the plan path
#: measured for one look of a question step (about 1,900 tokens in, 600 out; TODO ruling 63 (g)).
READING_PAD = " " * 6000
QUESTION_PROMPT = "x" * 5700
QUESTION_REPLY = json.dumps({"verdict": "different", "reason": "r" * 1700})
STEPS = ("_same_name_review_safely", "_full_name_join_safely", "_typo_join_safely", "_question_revisit_safely",
         "_described_landing_safely", "_which_one_read_safely")


@pytest.fixture(autouse=True)
def _idle():
    state = sleep_cycle.get_sleep_state()
    state.status, state.drain, state.drain_run, state.cancel_requested, state.error = "idle", None, False, False, None
    yield
    state.status, state.drain, state.drain_run, state.cancel_requested = "idle", None, False, False
    anthropic_engine.reset_clients()


#: A long conversation: six reads of 12,000 characters, so a conversation's cost is six calls (the owner's was thirty) and
#: the guard's dearest call is a small part of the figure, as on a real run.
FILLER = "Nothing else changed that week. " * 2200


def _conversations(n):
    return [{"source_id": f"night:{i}", "day": i - n, "turns": [
        f"alpha-project uses sqlite-tool. gamma{i}-project uses delta-tool. {FILLER}", "Noted.",
        "alpha-project status building."]} for i in range(n)]


def _scripted(body):
    system, user = body["system"][0]["text"], body["messages"][-1]["content"]
    if system.startswith("JUDGE"):
        return QUESTION_REPLY
    text = _answer(system, user)
    return text + READING_PAD if "entities" in system[:400].lower() else text


class Night(SimpleNamespace):
    pass


def night(tmp_path, monkeypatch, *, limit, share=sleep_spend.QUESTIONS_SHARE, conversations=40, work=True, per_step=12,
          batch=5):
    """One night on the stand-in: ``conversations`` waiting, ``per_step`` calls each question step would make."""
    stub = StubAnthropic(answer=_scripted)
    stub.install(monkeypatch)
    monkeypatch.setattr(sleep_run_prefs, "load", lambda _r: sleep_run_prefs.RunOptions(spend_limit_usd=limit))
    monkeypatch.setattr(sleep_spend, "QUESTIONS_SHARE", share)
    monkeypatch.setattr(question_steps, "has_work", lambda *_a, **_k: work)
    monkeypatch.setattr(engine_parity, "BATCH_SIZE", batch)
    seen = SimpleNamespace(made=0, refused=0, settled=0, order=[])

    def asking(name):
        async def step(memory_path, settings, *, user_triggered):
            seen.order.append(name)
            made = 0
            try:
                for _ in range(per_step):
                    await entity_resolver._same_name_ask(settings, "JUDGE: answer in JSON.", QUESTION_PROMPT)
                    made += 1
            except engine_errors.EngineExhausted:      # the limit: the step stops, as every real step does
                seen.refused += 1
            seen.made += made
            sleep_cycle._count_question_settled(made // 3)
            seen.settled += made // 3

        return step

    for name in STEPS:
        monkeypatch.setattr(sleep_cycle, name, asking(name))
    snap = engine_parity.run_leg("key", model=SONNET, judge=SONNET, out=tmp_path / "key", conversations=_conversations(conversations))
    ds = sleep_cycle.get_sleep_state().drain
    ledger = 0.0
    for events in (tmp_path / "key" / "home").rglob("events-*.jsonl"):
        for line in events.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("kind") == "llm_call":
                ledger += float(row.get("cost_usd") or row.get("equiv_cost_usd") or 0)
    with engine_parity._leg_environment(tmp_path / "key" / "home", tmp_path / "key" / "bank"):
        run = sleep_runs.get(tmp_path / "key" / "bank", ds.drain_id)
    return Night(snap=snap, ds=ds, seen=seen, stub=stub, ledger=ledger, read=snap["episodes_processed"],
                 spent=ds.spend.spent_usd, bank=tmp_path / "key" / "bank", run=run)


# ---- the guard ------------------------------------------------------------------------------------------------------


def _spend(guard, total, each=0.1):
    """``total`` spent in calls of ``each`` (the guard learns the dearest call from them)."""
    for _ in range(round(total / each)):
        guard.observe(each)


def test_reading_stops_at_the_figure_less_the_questions_part_and_the_tail_then_has_the_whole_figure():
    guard = sleep_spend.SpendGuard(5.0)
    guard.reserve_usd = 0.75
    guard.observe(0.1)
    assert guard.try_admit() and guard.reserving
    guard.release()
    _spend(guard, 4.0)
    assert not guard.is_reached()
    _spend(guard, 0.2)
    assert guard.is_reached(), "4.30 is past 5.00 less 0.75 less the dearest call (0.1): the last read stays out of the part"
    with pytest.raises(engine_errors.SpendLimitReached):
        guard.try_admit()
    guard.end_reading()
    assert not guard.is_reached() and guard.try_admit(), "the question steps' part is there for the tail"
    guard.release()
    _spend(guard, 0.8)
    assert guard.is_reached()
    with pytest.raises(engine_errors.SpendLimitReached):
        guard.try_admit()


def test_the_part_is_kept_only_if_the_steps_have_something_to_read_asked_once_when_reading_reaches_its_line():
    asked: list = []
    guard = sleep_spend.SpendGuard(5.0)
    guard.reserve_usd = 0.75
    guard.reserve_check = lambda: asked.append(1) or False
    _spend(guard, 4.0)
    assert not guard.is_reached() and asked == [], "not asked while reading is under its own line"
    _spend(guard, 0.3)
    guard.settle_reserve()
    assert not guard.is_reached() and asked == [1], "nothing for them: reading goes on to the whole figure"
    assert guard.try_admit() and asked == [1] and not guard.reserving
    kept = sleep_spend.SpendGuard(5.0)
    kept.reserve_usd = 0.75
    kept.reserve_check = lambda: asked.append(2) or True
    _spend(kept, 4.3)
    kept.settle_reserve()
    assert kept.is_reached() and kept.is_reached() and asked == [1, 2], "something to read: kept, asked once"
    broken = sleep_spend.SpendGuard(5.0)
    broken.reserve_usd = 0.75
    broken.reserve_check = lambda: 1 / 0
    _spend(broken, 4.3)
    broken.settle_reserve()
    assert not broken.is_reached(), "a filter that cannot answer is no work, never a reason to hold reading back"


def test_the_question_is_answered_on_a_thread_of_its_own_and_a_call_at_the_line_waits_for_it(monkeypatch):
    """Review 2026-11-27: the filters read the whole bank, and the guard is reached from the event loop. Nothing that asks the
    guard waits on them: a call at the reading line is told "not yet" (never sent, never refused on a guess) until the answer
    comes, and an answer that does not come in time is "nothing to read"."""
    import threading

    asking, go, asked_on = threading.Event(), threading.Event(), []

    def slow(work):
        def check():
            asked_on.append(threading.current_thread().name)
            asking.set()
            go.wait(5)
            return work
        return check

    for work in (True, False):
        asking.clear(), go.clear()
        guard = sleep_spend.SpendGuard(5.0)
        guard.reserve_usd, guard.reserve_check = 0.75, slow(work)
        _spend(guard, 4.3)
        assert guard.try_admit() is False and asking.wait(5), "not yet: the answer is being worked out elsewhere"
        assert guard.try_admit() is False and guard.is_reached(), "still not yet, and nothing here waited on the filters"
        go.set()
        guard.settle_reserve()
        if work:
            with pytest.raises(engine_errors.SpendLimitReached):
                guard.try_admit()
        else:
            assert guard.try_admit() is True and not guard.is_reached()
    assert asked_on == ["cicada-question-share"] * 2 and threading.current_thread().name not in asked_on

    # No answer within the cap: the part goes back to reading, and a late answer changes nothing.
    asking.clear(), go.clear()
    monkeypatch.setattr(sleep_spend, "ASK_CAP_S", 0.05)
    late = sleep_spend.SpendGuard(5.0)
    late.reserve_usd, late.reserve_check = 0.75, slow(True)
    _spend(late, 4.3)
    late.settle_reserve()
    assert not late.is_reached() and late.try_admit() is True and late.reserve_usd == 0
    go.set()
    asking.wait(5)
    assert late.reserve_usd == 0 and not late.is_reached()


def test_a_batch_is_sized_to_the_reading_part_and_released_it_is_the_whole_figure():
    guard = sleep_spend.SpendGuard(5.0, read_cap_usd=1.5)
    guard.reserve_usd = 1.0
    assert guard.batch_size(25) == 2, "4.00 left to read at the most one read may write"
    guard.release_reserve()
    assert guard.batch_size(25) == 3 and not guard.reserving


def test_a_guard_built_the_old_way_keeps_nothing_back():
    guard = sleep_spend.SpendGuard(5.0)
    assert guard.reserve_usd == 0 and not guard.reserving
    guard.observe(5.0)
    assert guard.is_reached()


def test_the_default_guard_keeps_the_measured_share_of_the_figure():
    guard = sleep_spend.guard_for(SimpleNamespace(litellm_model=SONNET, effective_consolidation_model=SONNET,
                                                  litellm_disambiguation_model=SONNET), 5.0)
    assert guard.reserve_usd == pytest.approx(5.0 * sleep_spend.QUESTIONS_SHARE)


# ---- the seam: the question steps' calls answer to the limit, the batches' own filing does not -------------------------


@pytest.fixture
def past_the_line():
    guard = sleep_spend.SpendGuard(1.0)
    guard.observe(1.0)
    guard.end_reading()
    for cycle in ("c1", "c1-questions"):
        sleep_drain.register_batch(cycle, SimpleNamespace(spend=guard, drain_id="d1", note_call=lambda: None))
    yield guard
    for cycle in ("c1", "c1-questions"):
        sleep_drain.unregister_batch(cycle)


def _fn(scope):
    return providers.resolve_llm_fn(Settings(_env_file=None, llm_mode="byok", litellm_model=SONNET), model=SONNET,
                                    stage="disambiguation", sink=lambda e: None, bank="b", scope=scope, is_async=False)


def test_a_question_step_call_past_the_line_is_never_sent(monkeypatch, past_the_line):
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    with pytest.raises(engine_errors.SpendLimitReached):
        _fn("sleep:c1-questions")(messages=[{"role": "user", "content": "alpha"}])
    assert stub.requests == [] and past_the_line.spent_usd == 1.0


def test_the_same_label_in_a_batch_is_the_filing_and_is_never_refused(monkeypatch, past_the_line):
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    _fn("sleep:c1")(messages=[{"role": "user", "content": "alpha"}])
    assert len(stub.requests) == 1 and past_the_line.spent_usd > 1.0


def test_a_call_in_the_question_scope_is_the_runs_and_counts_into_its_spend(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    guard = sleep_spend.SpendGuard(5.0)
    guard.end_reading()
    sleep_drain.register_batch("c2-questions", SimpleNamespace(spend=guard, drain_id="d2", note_call=lambda: None))
    try:
        _fn("sleep:c2-questions")(messages=[{"role": "user", "content": "alpha"}])
    finally:
        sleep_drain.unregister_batch("c2-questions")
    assert guard.spent_usd > 0, "before this, the question steps' spend never reached the run's figure"


def test_a_question_step_with_no_drain_in_scope_is_as_it_was(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    _fn("sleep:orphan-questions")(messages=[{"role": "user", "content": "alpha"}])
    assert len(stub.requests) == 1


# ---- the night through the real drain -------------------------------------------------------------------------------


def test_a_night_that_would_use_the_whole_figure_reads_to_the_reading_part_and_the_questions_spend_the_rest(tmp_path, monkeypatch):
    limit = 1.0
    before = night(tmp_path / "before", monkeypatch, limit=limit, share=0.0)
    after = night(tmp_path / "after", monkeypatch, limit=limit)
    assert before.seen.made == 0 and before.seen.order == [], "today a night stopped at the line runs no question step"
    assert after.read < before.read, "reading stopped earlier by the questions' part"
    assert after.seen.made > 0 and after.seen.order == list(STEPS), "every step ran, in today's order"
    assert after.seen.refused >= 1, "a step whose next call would cross the line was refused"
    assert after.ds.stop.limit == "spend" and after.snap["failures"]["stop_sentence"] == sleep_spend.SENTENCE
    # The bound: the figure and the one call a line may be passed by (a question's, here a hundredth of the figure).
    one_call = after.ds.spend._dearest
    assert limit <= after.spent <= limit + 3 * one_call, (after.spent, one_call)
    assert after.ledger == pytest.approx(after.spent, rel=0.02), "the guard's figure is the ledger's, the questions' calls included"
    assert before.spent <= limit + 3 * before.ds.spend._dearest


def test_the_run_says_reading_stopped_for_the_questions_and_what_they_used_in_counts(tmp_path, monkeypatch):
    after = night(tmp_path, monkeypatch, limit=1.0)
    run = after.run
    assert run["questions_room"] is True
    assert run["question_steps"] == {"calls": after.seen.made, "settled": after.seen.settled}
    assert after.seen.made > 0
    assert "$" not in json.dumps(run["question_steps"]), "counts only: no figure outside where ruling 12 allows one"


def test_a_night_with_no_question_to_read_reads_with_the_whole_allowance(tmp_path, monkeypatch):
    plain = night(tmp_path / "plain", monkeypatch, limit=1.0, share=0.0)
    quiet = night(tmp_path / "quiet", monkeypatch, limit=1.0, work=False)
    assert quiet.read == plain.read and quiet.seen.made == 0
    assert quiet.ds.stop.limit == "spend" and not quiet.ds.questions_run
    assert quiet.run.get("questions_room") is None


def test_a_run_that_reads_everything_under_the_line_runs_the_steps_held_to_the_figure(tmp_path, monkeypatch):
    done = night(tmp_path, monkeypatch, limit=50.0, conversations=3, per_step=2)
    assert done.snap["failures"]["stop"] is None and done.read == 3
    assert done.seen.made == 2 * len(STEPS) and done.spent < 50.0
    assert done.spent > 0 and done.ledger == pytest.approx(done.spent, rel=0.02), "their calls are the run's: they were not before"


def test_a_plan_limit_stop_runs_no_question_step(tmp_path, monkeypatch):
    stub = StubAnthropic(answer=_scripted)
    stub.install(monkeypatch)
    ran: list = []
    for name in STEPS:
        async def step(*_a, _n=name, **_k):
            ran.append(_n)
        monkeypatch.setattr(sleep_cycle, name, step)
    outcome = sleep_cycle._StageOutcome(skip_links=True, stop=sleep_drain.DrainStop("plan_limit", "limit", None, "five_hour"))
    assert outcome.questions is False
    asyncio.run(sleep_cycle._run_engine_independent_tail(
        tmp_path, Settings(_env_file=None, memory_path=tmp_path), outcome, user_triggered=True, skip_links=True))
    assert ran == [], "a stop on a plan's limit is unchanged: nothing that asks a model runs"


# ---- what a step remembers across a Continue ------------------------------------------------------------------------


def test_a_step_refused_at_the_line_leaves_its_question_and_a_continue_reads_it_once(tmp_path, monkeypatch):
    """`full_name_join`: a refused call is the pause a plan limit is (`SpendLimitReached` is an `EngineExhausted`); what was read
    before it stands, so the next allowance reads only what is left, and what was read is not read again."""
    from api.tests import test_full_name_join as fn

    memory = tmp_path / "memory"
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    from api.services import predicates

    predicates.install_predicate_map(memory)
    fn._git(memory, "init", "-q")
    fn._git(memory, "config", "user.email", "t@example.com")
    fn._git(memory, "config", "user.name", "t")
    fn._page(memory, "ines-varga", "Ines Varga", owner=True)
    fn._commit(memory)
    fn._world(memory, turn=fn.TWO)
    with pytest.raises(engine_errors.SpendLimitReached):
        fn._tend(memory, fn._judge(engine_errors.SpendLimitReached(sleep_spend.SENTENCE)))
    assert (memory / "inbox" / "inbox-001.md").is_file(), "the question stays"
    judge = fn._judge({"verdict": "two", "reason": "the father"})
    assert fn._tend(memory, judge).looked == 1 and len(judge.calls) == 1, "the next allowance reads it"
    assert fn._tend(memory, judge).looked == 0 and len(judge.calls) == 1, "and what was read is not read again"


# ---- does anything wait for them? --------------------------------------------------------------------------------------


def _bank(tmp_path, monkeypatch):
    from api.services import predicates
    from api.tests import test_full_name_join as fn

    memory = tmp_path / "memory"
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    predicates.install_predicate_map(memory)
    fn._git(memory, "init", "-q")
    fn._git(memory, "config", "user.email", "t@example.com")
    fn._git(memory, "config", "user.name", "t")
    fn._page(memory, "ines-varga", "Ines Varga", owner=True)
    fn._commit(memory)
    return memory, fn


def test_a_bank_with_no_open_question_of_their_kinds_has_no_work_and_one_with_one_has(tmp_path, monkeypatch):
    memory, fn = _bank(tmp_path, monkeypatch)
    assert question_steps.has_work(memory) is False, "reading keeps the whole allowance"
    fn._world(memory, turn=fn.TWO)
    assert question_steps.has_work(memory) is True, "a held full name with its question is the full-name join's"


def test_a_filter_that_cannot_answer_is_no_work(tmp_path, monkeypatch):
    memory, _fn = _bank(tmp_path, monkeypatch)
    from api.services import same_name_doubts

    monkeypatch.setattr(same_name_doubts, "flagged", lambda _m: 1 / 0)
    assert question_steps.has_work(memory) is False
