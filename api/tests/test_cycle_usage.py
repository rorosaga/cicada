"""2026-09-28 ruling — what a Sleep cycle cost.

Write side: `llm_call` rows carry their cycle (contextvar, across threads), the
per-cycle plan accumulators, the `sleep_run` plan block. Read side: usage
derived from the ledger onto the history rows and the detail. Synthetic
ledgers only; no model, no network, nothing under the real ~/.cicada.
"""
from __future__ import annotations

import asyncio
import json
import subprocess

import pytest

from api.config import Settings
from api.services import agent_engine, codex_app_server, cycle_usage, git_service, providers, telemetry
from api.services.agent_stream import RateLimitSignal
from api.services.codex_app_server import CodexSnapshot
from api.services.telemetry import UsageEvent


class _Resp:
    usage = {"prompt_tokens": 10, "completion_tokens": 5}
    _hidden_params = {"response_cost": 0.001}


def _fn(events):
    return providers.resolve_llm_fn(Settings(litellm_model="gpt-5.4-mini"), completion=lambda **kw: _Resp(),
                                    stage="extraction", sink=events.append, bank="lab")


# --- tagging -------------------------------------------------------------- #


def test_cycle_id_from_scope_only_names_sleep_scopes():
    assert agent_engine.cycle_id_from_scope("sleep:abc123") == "abc123"
    for scope in ("_unscoped", "links:9f", "ask:1", "sleep:", "", None):
        assert agent_engine.cycle_id_from_scope(scope) is None


def test_a_call_inside_a_cycle_scope_is_tagged_and_outside_is_not():
    events: list[UsageEvent] = []
    fn = _fn(events)
    fn(messages=[{"role": "user", "content": "x"}])
    with agent_engine.use_scope("sleep:cyc1"):
        fn(messages=[{"role": "user", "content": "x"}])
    with agent_engine.use_scope("links:zzz"):
        fn(messages=[{"role": "user", "content": "x"}])
    assert [e.refs.get("cycle_id") for e in events] == [None, "cyc1", None]


def test_the_tag_survives_to_thread_and_gather():
    events: list[UsageEvent] = []
    fn = _fn(events)

    async def go():
        with agent_engine.use_scope("sleep:cyc2"):
            await asyncio.gather(*(asyncio.to_thread(fn, messages=[{"role": "user", "content": "x"}])
                                   for _ in range(3)))

    asyncio.run(go())
    assert [e.refs.get("cycle_id") for e in events] == ["cyc2"] * 3


def test_an_explicit_scope_override_wins_over_the_ambient_one():
    events: list[UsageEvent] = []
    fn = providers.resolve_llm_fn(Settings(litellm_model="gpt-5.4-mini"), completion=lambda **kw: _Resp(),
                                  stage="ask", sink=events.append, scope="ask:abc")
    with agent_engine.use_scope("sleep:cyc3"):
        fn(messages=[{"role": "user", "content": "x"}])
    assert "cycle_id" not in events[0].refs


# --- the plan accumulators ------------------------------------------------- #


def _sig(window, u, resets=1790000000, status="allowed"):
    return RateLimitSignal(status=status, limit_type=window, utilization=u, resets_at=resets)


def test_claude_windows_keep_the_first_and_peak_utilization_and_ignore_a_rolled_window():
    cycle_usage.note_signals("c1", [_sig("five_hour", 0.12, 100), _sig("seven_day", 0.3, 900)])
    cycle_usage.note_signals("c1", [_sig("five_hour", 0.15, 100)])
    cycle_usage.note_signals("c1", [_sig("five_hour", 0.18, 100), _sig("overage", 0.9), _sig("five_hour", None)])
    plan = asyncio.run(cycle_usage.finish("c1", "claude-cli"))
    assert plan == {"connection": "claude-plan", "windows": [
        {"window": "five_hour", "before": 0.12, "after": 0.18, "resets_at": 100, "before_is_first_seen": True},
        {"window": "seven_day", "before": 0.3, "after": 0.3, "resets_at": 900, "before_is_first_seen": True}]}
    assert asyncio.run(cycle_usage.finish("c1", "claude-cli")) is None   # popped: bounded


def test_out_of_order_readings_keep_the_peak_and_a_rollover_keeps_the_pre_reset_peak():
    cycle_usage.note_signals("c_peak", [_sig("five_hour", 0.3, resets=100)])
    cycle_usage.note_signals("c_peak", [_sig("five_hour", 0.5, resets=100)])
    cycle_usage.note_signals("c_peak", [_sig("five_hour", 0.4, resets=100)])   # a slower, earlier call
    cycle_usage.note_signals("c_peak", [_sig("five_hour", 0.02, resets=999)])  # the window rolled over
    w = asyncio.run(cycle_usage.finish("c_peak", "claude-cli"))["windows"][0]
    assert (w["before"], w["after"], w["resets_at"]) == (0.3, 0.5, 100)


def test_no_signals_means_no_plan_block_never_zeros():
    assert asyncio.run(cycle_usage.finish("never-seen", "claude-cli")) is None
    cycle_usage.note_signals(None, [_sig("five_hour", 0.5)])
    cycle_usage.note_signals("c2", [])
    assert asyncio.run(cycle_usage.finish("c2", "claude-cli")) is None


def test_discard_frees_a_cycle_that_never_finalized():
    cycle_usage.note_signals("c3", [_sig("five_hour", 0.5)])
    cycle_usage.discard("c3")
    assert asyncio.run(cycle_usage.finish("c3", "claude-cli")) is None


def _snap(*windows):
    return CodexSnapshot(signed_in=True, windows=tuple(windows))


def test_codex_brackets_the_cycle_with_two_snapshots_window_by_window(monkeypatch):
    seen = iter([_snap(("primary", 20, 100), ("secondary", 60, 900)),
                 _snap(("primary", 24, 100), ("secondary", 61, 900))])
    calls = []

    async def snap(*, fresh=False, **_kw):
        calls.append(fresh)
        return next(seen)

    monkeypatch.setattr(codex_app_server, "snapshot", snap)

    async def go():
        await cycle_usage.begin_codex("c4")
        return await cycle_usage.finish("c4", "codex-cli")

    plan = asyncio.run(go())
    assert calls == [True, True]
    assert plan["connection"] == "chatgpt-plan"
    assert plan["windows"] == [
        {"window": "primary", "before": 0.2, "after": 0.24, "resets_at": 100, "before_is_first_seen": False},
        {"window": "secondary", "before": 0.6, "after": 0.61, "resets_at": 900, "before_is_first_seen": False}]


@pytest.mark.parametrize("start_ok,end_ok", [(False, True), (True, False)])
def test_a_failed_snapshot_records_no_plan_block(monkeypatch, start_ok, end_ok):
    answers = iter([_snap(("primary", 20, 1)) if start_ok else None, _snap(("primary", 30, 1)) if end_ok else None])

    async def snap(**_kw):
        return next(answers)

    monkeypatch.setattr(codex_app_server, "snapshot", snap)

    async def go():
        await cycle_usage.begin_codex("c5")
        return await cycle_usage.finish("c5", "codex-cli")

    assert asyncio.run(go()) is None


def test_parse_snapshot_keeps_each_window_separately():
    replies = {"account/read": {"result": {"account": {"type": "chatgpt", "planType": "plus"}}},
               "account/rateLimits/read": {"result": {"rateLimits": {
                   "primary": {"usedPercent": 12, "resetsAt": 111},
                   "secondary": {"usedPercent": 40, "resetsAt": 222}}}}}
    snap = codex_app_server.parse_snapshot(replies)
    assert snap.windows == (("primary", 12, 111), ("secondary", 40, 222))
    assert snap.used_percent == 40 and snap.resets_at == 222


def test_the_plan_block_is_numbers_and_enums_only():
    cycle_usage.note_signals("c6", [_sig("five_hour", 0.1)])
    plan = asyncio.run(cycle_usage.finish("c6", "claude-cli"))

    def leaves(node):
        if isinstance(node, dict):
            for v in node.values():
                yield from leaves(v)
        elif isinstance(node, list):
            for v in node:
                yield from leaves(v)
        else:
            yield node

    allowed_words = {"claude-plan", "five_hour"}
    for leaf in leaves(plan):
        assert isinstance(leaf, (int, float, bool)) or leaf in allowed_words


# --- the read side --------------------------------------------------------- #

H = "abc1234" + "0" * 33


def _call(cycle, model="gpt-5.4-mini", engine="litellm", cost=0.01, equiv=0.012, ok=True, i=100, o=20,
          billing="usage", connection="byok-openai"):
    return UsageEvent(kind="llm_call", engine=engine, model=model, connection=connection, billing=billing,
                      input_tokens=i if ok else 0, output_tokens=o if ok else 0, cost_usd=cost if ok else None,
                      equiv_cost_usd=equiv if ok else None, ok=ok, refs={"cycle_id": cycle})


def _run(cycle, commit=H[:12], engine="litellm", connection="byok-openai", tagged=True, plan=None):
    refs = {"cycle_id": cycle, "commit": commit}
    if tagged:
        refs[cycle_usage.TAGGED_REF] = True
    if plan:
        refs["plan"] = plan
    return UsageEvent(kind="sleep_run", engine=engine, connection=connection, refs=refs)


def _usage(events, commit=H):
    return cycle_usage.usage_for(cycle_usage.Ledger.build(events), commit)


def test_a_charged_key_cycle_groups_by_engine_and_model_with_null_safe_sums():
    u = _usage([_run("k"), _call("k"), _call("k"), _call("k", model="gpt-5.4-nano", cost=0.001, equiv=0.001),
                _call("k", ok=False), _call("other")])
    by_model = {m.model: m for m in u.models}
    main = by_model["gpt-5.4-mini"]
    assert (main.calls, main.failed_calls, main.input_tokens, main.output_tokens) == (3, 1, 200, 40)
    assert main.cost_usd == 0.02 and main.basis == "charged"
    assert u.total_cost_usd == 0.021 and u.basis == "charged" and u.recorded is True
    assert cycle_usage.summarize(u).cost_usd == 0.021


def test_a_claude_plan_cycle_is_list_priced_never_charged():
    plan = {"connection": "claude-plan", "windows": [
        {"window": "five_hour", "before": 0.12, "after": 0.18, "resets_at": 5, "before_is_first_seen": True}]}
    u = _usage([_run("p", engine="claude-cli", connection="claude-plan", plan=plan),
                _call("p", engine="claude-cli", model="claude-sonnet-5-5", cost=None, equiv=0.42,
                      billing="subscription", connection="claude-plan")])
    assert u.basis == "list" and u.total_cost_usd is None and u.total_equiv_usd == 0.42
    assert u.plan.windows[0].before == 0.12 and u.plan.windows[0].before_is_first_seen is True
    s = cycle_usage.summarize(u)
    assert (s.basis, s.cost_usd, s.equiv_cost_usd) == ("list", None, 0.42)
    assert (s.plan.window, s.plan.before, s.plan.after) == ("five_hour", 0.12, 0.18)


def test_a_chatgpt_plan_cycle_has_calls_and_a_window_but_no_cost():
    u = _usage([_run("g", engine="codex-cli", connection="chatgpt-plan"),
                _call("g", engine="codex-cli", model="gpt-6-astra", cost=None, equiv=None, i=0, o=0,
                      billing="subscription", connection="chatgpt-plan")])
    assert u.basis == "plan" and u.total_cost_usd is None and u.total_equiv_usd is None
    assert u.models[0].calls == 1 and u.models[0].input_tokens == 0


def test_mixed_engines_in_one_cycle_are_keyed_by_engine_and_model_and_read_mixed():
    u = _usage([_run("m"), _call("m", engine="claude-cli", model="sonnet", cost=None, equiv=0.1),
                _call("m", engine="litellm", model="sonnet", cost=0.2, equiv=0.2)])
    assert len(u.models) == 2 and u.basis == "mixed"


def test_a_local_model_reads_free():
    u = _usage([_run("l", engine="ollama"), _call("l", engine="ollama", model="ollama/llama3", cost=None,
                                                   equiv=None, billing="free", connection="ollama-local")])
    assert u.basis == "free"


def test_a_cycle_before_calls_were_tagged_is_not_recorded():
    assert _usage([_run("old", tagged=False)]) is None
    assert cycle_usage.summarize(None) is None


def test_a_tagged_idle_cycle_is_recorded_with_no_calls():
    u = _usage([_run("idle")])
    assert u.recorded is True and u.models == [] and u.basis is None and u.total_cost_usd is None
    assert cycle_usage.summarize(u).basis is None


def test_no_sleep_run_for_the_commit_is_not_recorded_and_orphan_calls_are_ignored():
    assert _usage([_call("orphan")]) is None
    assert _usage([_run("x", commit="fffffff")]) is None


def test_the_commit_join_is_a_prefix_match_either_way_of_seven_or_more_characters():
    assert _usage([_run("a", commit=H[:7])], H) is not None
    assert _usage([_run("a", commit=H)], H[:9]) is not None
    assert _usage([_run("a", commit=H[:6])], H) is None


def test_decay_and_inbox_rows_never_get_usage():
    from api.models.schemas import SleepHistoryEntry

    rows = [SleepHistoryEntry(commit_hash=H, date="2026-09-01", message="m", files_changed=[], kind=k)
            for k in ("decay", "inbox", "sleep")]
    cycle_usage.attach_usage(rows, [_run("k"), _call("k")])
    assert [r.usage_summary is not None for r in rows] == [False, False, True]


def test_a_malformed_plan_block_is_ignored_not_raised():
    u = _usage([_run("bad", plan={"connection": "claude-plan", "windows": [{"window": "five_hour"}, "x"]})])
    assert u.plan is None


def test_wire_shape_is_camel_case_with_the_documented_fields():
    plan = {"connection": "claude-plan", "windows": [
        {"window": "five_hour", "before": 0.1, "after": 0.2, "resets_at": 7, "before_is_first_seen": True}]}
    u = _usage([_run("w", engine="claude-cli", connection="claude-plan", plan=plan),
                _call("w", engine="claude-cli", model="m", cost=None, equiv=0.5)])
    body = json.loads(u.model_dump_json(by_alias=True))
    assert set(body) == {"recorded", "engine", "connection", "models", "totalCostUsd", "totalEquivUsd",
                         "basis", "plan"}
    assert set(body["models"][0]) == {"model", "engine", "calls", "failedCalls", "inputTokens", "outputTokens",
                                      "costUsd", "equivCostUsd", "basis"}
    assert set(body["plan"]["windows"][0]) == {"window", "before", "after", "resetsAt", "beforeIsFirstSeen"}
    summary = json.loads(cycle_usage.summarize(u).model_dump_json(by_alias=True))
    assert set(summary) == {"basis", "costUsd", "equivCostUsd", "engine", "connection", "plan"}


def test_last_cycles_reads_the_newest_window_and_charge_per_card():
    old = _run("o", engine="claude-cli", connection="claude-plan", commit="1" * 12, plan={
        "connection": "claude-plan", "windows": [{"window": "five_hour", "before": 0.1, "after": 0.2,
                                                   "resets_at": 5, "before_is_first_seen": True}]})
    old.ts = "2026-09-01T00:00:00.000Z"
    new = _run("n", engine="claude-cli", connection="claude-plan", commit="2" * 12, plan={
        "connection": "claude-plan", "windows": [{"window": "seven_day", "before": 0.4, "after": 0.5,
                                                   "resets_at": 9, "before_is_first_seen": True},
                                                  {"window": "five_hour", "before": 0.2, "after": 0.33,
                                                   "resets_at": 6, "before_is_first_seen": True}]})
    new.ts = "2026-09-02T00:00:00.000Z"
    orr = _run("r", connection="byok-openrouter", commit="3" * 12)
    orr.ts = "2026-09-03T00:00:00.000Z"
    last = cycle_usage.last_cycles([old, new, orr, _call("r", cost=0.42, connection="byok-openrouter"),
                                    _call("n", engine="claude-cli", cost=None, equiv=0.1)])
    assert last["claude-plan"] == {"window": "five_hour", "used_fraction": 0.33, "resets_at": 6,
                                   "as_of": "2026-09-02T00:00:00.000Z"}
    assert last["openrouter"]["cost_usd"] == 0.42 and "byok" not in last


def test_last_cycles_is_scoped_to_one_bank_and_reset_drops_the_cache():
    a = _run("a", connection="byok-openrouter", commit="1" * 12)
    a.bank, a.ts = "alpha", "2026-09-01T00:00:00.000Z"
    b = _run("b", connection="byok-openrouter", commit="2" * 12)
    b.bank, b.ts = "beta", "2026-09-02T00:00:00.000Z"
    evs = [a, b, _call("a", cost=0.11, connection="byok-openrouter"), _call("b", cost=0.99, connection="byok-openrouter")]
    assert cycle_usage.last_cycles(evs, "alpha")["openrouter"]["cost_usd"] == 0.11
    assert cycle_usage.last_cycles(evs, "beta")["openrouter"]["cost_usd"] == 0.99
    assert cycle_usage.last_cycles(evs, "gamma") == {}
    cycle_usage._last_cache["x"] = (0.0, {})
    cycle_usage.reset_cache()
    assert cycle_usage._last_cache == {}


def test_list_price_reads_litellm_with_the_provider_prefix_fallback(monkeypatch):
    import litellm

    monkeypatch.setattr(litellm, "model_cost", {"x/y": {"input_cost_per_token": 4e-7,
                                                        "output_cost_per_token": 1.6e-6}})
    cycle_usage._PRICE_CACHE.clear()
    assert cycle_usage.list_price_per_million("openrouter/x/y") == (0.4, 1.6)
    assert cycle_usage.list_price_per_million("unknown-model") == (None, None)
    assert cycle_usage.list_price_per_million("ollama/llama3") == (None, None)
    cycle_usage._PRICE_CACHE.clear()


# --- routes: a real ledger on disk, a real bank in git ----------------------- #


def _git(memory, *args):
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args], cwd=memory, check=True)


@pytest.fixture
def ledger_bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "entities" / "alpha-project.md").write_text("---\ntype: project\n---\nbody\n")
    subprocess.run(["git", "init", "-q"], cwd=memory, check=True)
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m",
         "Sleep cycle 2026-09-29\n\nentities/alpha-project.md: created (source: n/a, trigger: sleep/extraction)"
         "\n\nCicada-Author: gpt-5.4-mini\nCicada-Engine: litellm")
    full = subprocess.run(["git", "rev-parse", "HEAD"], cwd=memory, capture_output=True, text=True,
                          check=True).stdout.strip()
    return memory, full


def test_history_and_detail_join_usage_from_the_ledger(ledger_bank):
    memory, full = ledger_bank
    when = "2026-09-29T10:00:00.000Z"
    for ev in (_run("k", commit=full), _call("k"), _call("k")):
        ev.ts = when
        telemetry.record(ev)
    rows = asyncio.run(git_service.get_sleep_history(memory, limit=5))
    assert rows[0].usage_summary.cost_usd == 0.02 and rows[0].usage_summary.basis == "charged"
    detail = asyncio.run(git_service.get_sleep_cycle_detail(memory, full))
    assert detail.usage.models[0].calls == 2 and detail.usage.total_cost_usd == 0.02
    # a call written later shows without HEAD moving: usage is joined after the cache copy
    more = _call("k")
    more.ts = when
    telemetry.record(more)
    rows = asyncio.run(git_service.get_sleep_history(memory, limit=5))
    assert rows[0].usage_summary.cost_usd == 0.03


def test_usage_is_null_when_the_ledger_has_nothing(ledger_bank):
    memory, full = ledger_bank
    rows = asyncio.run(git_service.get_sleep_history(memory, limit=5))
    assert rows[0].usage_summary is None
    assert asyncio.run(git_service.get_sleep_cycle_detail(memory, full)).usage is None


def test_calls_the_day_before_the_commit_still_join_across_a_month_boundary(ledger_bank):
    memory, full = ledger_bank
    # the commit is dated today by git, so date the fixture's rows around the real commit day
    commit_day = asyncio.run(git_service.get_sleep_history(memory, limit=1))[0].date[:10]
    from datetime import date, timedelta
    day_before = (date.fromisoformat(commit_day) - timedelta(days=1)).isoformat()
    for ev, ts in ((_call("mid"), f"{day_before}T23:59:58.000Z"), (_run("mid", commit=full), f"{commit_day}T00:00:05.000Z")):
        ev.ts = ts
        telemetry.record(ev)
    detail = asyncio.run(git_service.get_sleep_cycle_detail(memory, full))
    assert detail.usage is not None and detail.usage.models[0].calls == 1


def test_a_corrupt_ledger_line_is_skipped(ledger_bank):
    memory, full = ledger_bank
    ev = _run("c", commit=full)
    telemetry.record(ev)
    path = next((telemetry.telemetry_dir()).glob("events-*.jsonl"))
    with open(path, "a") as fh:
        fh.write("{not json\n")
    detail = asyncio.run(git_service.get_sleep_cycle_detail(memory, full))
    assert detail.usage is not None and detail.usage.models == []


def test_the_llm_call_ledger_row_stays_ids_enums_and_numbers(ledger_bank):
    events: list[UsageEvent] = []
    with agent_engine.use_scope("sleep:idc"):
        _fn(events)(messages=[{"role": "user", "content": "secret words"}])
    row = json.loads(events[0].to_json())
    assert row["refs"] == {"cycle_id": "idc"}
    assert "secret words" not in events[0].to_json()


# --- the sleep_run event gains the marker and the plan block ------------------- #


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    mem = tmp_path / "memory"
    (mem / "entities").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=mem, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=mem, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=mem, check=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(mem))
    return mem


def test_finalize_marks_the_run_tagged_and_carries_the_plan_block(repo):
    from api.services import sleep_cycle

    (repo / "entities" / "a.md").write_text("---\ntype: concept\n---\n")
    settings = Settings(memory_root=repo, litellm_model="gpt-5.4-mini")
    cycle_usage.note_signals("sleep_plan", [_sig("five_hour", 0.1), _sig("five_hour", 0.2)])
    changes = [{"id": "a", "action": "created", "source_episode": "ep1", "trigger": "sleep/extraction"}]
    asyncio.run(sleep_cycle._finalize(repo, "sleep_plan", changes, settings, started=0.0, engine="claude-cli",
                                      connection="claude-plan", billing="subscription"))
    run = next(e for e in telemetry.read_events() if e.kind == "sleep_run")
    assert run.refs[cycle_usage.TAGGED_REF] is True
    assert run.refs["plan"]["windows"][0]["after"] == 0.2
    # and the read side agrees end to end
    detail = asyncio.run(git_service.get_sleep_cycle_detail(repo, run.refs["commit"]))
    assert detail.usage.recorded is True and detail.usage.plan.connection == "claude-plan"


def test_finalize_without_a_plan_omits_the_key(repo):
    from api.services import sleep_cycle

    (repo / "entities" / "a.md").write_text("---\ntype: concept\n---\n")
    settings = Settings(memory_root=repo, litellm_model="gpt-5.4-mini")
    changes = [{"id": "a", "action": "created", "source_episode": "ep1", "trigger": "sleep/extraction"}]
    asyncio.run(sleep_cycle._finalize(repo, "sleep_noplan", changes, settings, started=0.0))
    run = next(e for e in telemetry.read_events() if e.kind == "sleep_run")
    assert "plan" not in run.refs and run.refs[cycle_usage.TAGGED_REF] is True


# --- the write path, end to end ---------------------------------------------- #

_RL = [{"status": "allowed", "rateLimitType": "five_hour", "utilization": 0.25, "resetsAt": 1790000000}]


def _agent_fn(runner):
    return providers.resolve_llm_fn(Settings(llm_mode="agent", agent_model="sonnet"), stage="extraction",
                                    sink=lambda e: None, runner=runner)


def test_an_agent_call_in_a_cycle_scope_reaches_the_plan_block(repo, agent_runner, claude_stream):
    from api.services import sleep_cycle
    from api.services.connections.base import CliResult

    fn = _agent_fn(agent_runner(CliResult(0, claude_stream("success", rate_limits=_RL), "")))
    with agent_engine.use_scope("sleep:e2e1"):
        fn(messages=[{"role": "user", "content": "x"}])
    assert cycle_usage._CLAUDE["e2e1"]["five_hour"]["after"] == 0.25
    (repo / "entities" / "a.md").write_text("---\ntype: concept\n---\n")
    settings = Settings(memory_root=repo, litellm_model="gpt-5.4-mini")
    changes = [{"id": "a", "action": "created", "source_episode": "ep1", "trigger": "sleep/extraction"}]
    asyncio.run(sleep_cycle._finalize(repo, "e2e1", changes, settings, started=0.0, engine="claude-cli",
                                      connection="claude-plan", billing="subscription"))
    run = next(e for e in telemetry.read_events() if e.kind == "sleep_run")
    assert run.refs["plan"]["windows"][0]["after"] == 0.25
    assert "e2e1" not in cycle_usage._CLAUDE


def test_a_call_that_ends_on_a_rate_limit_still_records_its_window(agent_runner, claude_stream):
    from api.services import engine_errors
    from api.services.connections.base import CliResult

    limited = [{"status": "rejected", "rateLimitType": "five_hour", "utilization": 1.0, "resetsAt": 1790000000}]
    fn = _agent_fn(agent_runner(CliResult(1, claude_stream("rate_limited", rate_limits=limited), "")))
    with agent_engine.use_scope("sleep:e2e2"):
        with pytest.raises(Exception) as exc:
            fn(messages=[{"role": "user", "content": "x"}])
    assert isinstance(exc.value, (engine_errors.EngineThrottled, engine_errors.EngineExhausted, Exception))
    assert cycle_usage._CLAUDE["e2e2"]["five_hour"]["after"] == 1.0
    cycle_usage.discard("e2e2")


def test_run_stages_brackets_a_codex_cycle_and_run_discards_an_aborted_one(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from api.services import engine_select, sleep_cycle

    seen = iter([_snap(("primary", 20, 100)), _snap(("primary", 30, 100))])

    async def snap(*, fresh=False, **_kw):
        return next(seen)

    async def resolved(settings, *a, **k):
        return SimpleNamespace(llm_mode="codex"), "why"

    class _Stop(Exception):
        pass

    monkeypatch.setattr(codex_app_server, "snapshot", snap)
    monkeypatch.setattr(engine_select, "resolve_settings", resolved)
    monkeypatch.setattr(sleep_cycle, "_get_unprocessed_episodes", lambda mp: [{"id": "ep"}])
    monkeypatch.setattr(sleep_cycle, "_engine_label", lambda s: "codex-cli")
    monkeypatch.setattr(engine_select, "author_model", lambda s: "m")
    real_flush = sleep_cycle._flush_pending_commits_safely

    async def stop_after_start(*_a, **_k):
        raise _Stop()

    # _run_stages calls begin_codex, then the next awaited seam raises: the cycle aborts.
    monkeypatch.setattr(sleep_cycle, "_flush_pending_commits_safely", real_flush)
    monkeypatch.setattr(sleep_cycle, "_state", sleep_cycle._state)
    orig_begin = cycle_usage.begin_codex

    async def begin_then_abort(cycle_id):
        await orig_begin(cycle_id)
        assert cycle_id in cycle_usage._CODEX_START
        raise _Stop()

    monkeypatch.setattr(cycle_usage, "begin_codex", begin_then_abort)
    with pytest.raises(_Stop):
        asyncio.run(sleep_cycle._run_stages(SimpleNamespace(sleep_max_episodes_per_cycle=5), "cx1", tmp_path))
    assert "cx1" in cycle_usage._CODEX_START   # started, so a finalize would write a two-snapshot block
    plan = asyncio.run(cycle_usage.finish("cx1", "codex-cli"))
    assert plan["windows"][0]["before"] == 0.2 and plan["windows"][0]["after"] == 0.3

    # run(): an aborted cycle frees both accumulators
    cycle_usage.note_signals("cx2", [_sig("five_hour", 0.1)])
    cycle_usage._CODEX_START["cx2"] = _snap(("primary", 1, 1))

    async def boom(*_a, **_k):
        raise _Stop()

    async def tail(*_a, **_k):
        return None

    monkeypatch.setattr(sleep_cycle, "_run_stages", boom)
    monkeypatch.setattr(sleep_cycle, "_run_engine_independent_tail", tail)
    asyncio.run(sleep_cycle.run(SimpleNamespace(memory_path=tmp_path), "cx2"))
    assert "cx2" not in cycle_usage._CLAUDE and "cx2" not in cycle_usage._CODEX_START
