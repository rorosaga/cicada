"""Owner 2026-10-16 — on a plan, a run says how much of the plan it used, not dollars.

``cycle_usage.plan_share``: per window, ``measured`` when the window's own reading moved, ``under`` (below one
point, never 0 %) when it did not, ``estimated`` from the run's list-price size against the rate earlier cycles
moved that window by — always with its basis, never an estimate passed off as a measurement. Unknown is left out.
Synthetic ledgers only; nothing under the real ~/.cicada.
"""
from __future__ import annotations

import pytest

from api.models.schemas import CycleUsagePlan, CycleUsagePlanWindow
from api.services import cycle_usage
from api.services.telemetry import UsageEvent

_REAL_RECENT = cycle_usage._recent_samples


@pytest.fixture(autouse=True)
def _no_machine_samples(monkeypatch):
    """The machine-wide samples are their own test; every other test sees only its own ledger."""
    monkeypatch.setattr(cycle_usage, "_recent_samples", lambda: {})
    cycle_usage.reset_cache()


#: A reset time after every run's ``ts`` here (a window that reset before the run ended is its own test).
_FUTURE = 4_000_000_000


def _plan(*windows, connection="claude-plan", resets_at=_FUTURE):
    return {"connection": connection, "windows": [
        {"window": name, "before": b, "after": a, "resets_at": resets_at, "before_is_first_seen": True}
        for name, b, a in windows]}


def _run(cycle, commit, *, plan=None, engine="claude-cli", connection="claude-plan", drain=None, batch=None,
         ts="2026-10-01T00:00:00.000Z", bank=None):
    refs = {"cycle_id": cycle, "commit": commit, cycle_usage.TAGGED_REF: True}
    if plan:
        refs["plan"] = plan
    if drain:
        refs["drain_id"], refs["batch"] = drain, batch or 1
    return UsageEvent(kind="sleep_run", engine=engine, connection=connection, refs=refs, ts=ts, bank=bank)


def _call(cycle, equiv, *, engine="claude-cli", connection="claude-plan", drain=None, ok=True, i=1000, o=100):
    refs = {"cycle_id": cycle}
    if drain:
        refs["drain_id"] = drain
    return UsageEvent(kind="llm_call", engine=engine, model="claude-sonnet-5-5", connection=connection,
                      billing="subscription", input_tokens=i, output_tokens=o, cost_usd=None,
                      equiv_cost_usd=equiv, ok=ok, refs=refs)


def _history():
    """Two earlier cycles that moved the weekly window: 4 points on $2 and 2 points on $1 — 2 points per dollar."""
    return [_run("e1", "1" * 12, plan=_plan(("seven_day", 0.10, 0.14), ("five_hour", 0.05, 0.20))),
            _call("e1", 2.0),
            _run("e2", "2" * 12, plan=_plan(("seven_day", 0.20, 0.22), ("five_hour", 0.30, 0.40))),
            _call("e2", 1.0)]


def _share(usage):
    return {s.window: (s.basis, s.share, s.under, s.samples) for s in usage.plan_share}


# --- the four bases -------------------------------------------------------- #


def test_a_window_that_moved_is_measured_and_the_weekly_limit_leads():
    ledger = cycle_usage.Ledger.build([_run("p", "a" * 12, plan=_plan(("five_hour", 0.12, 0.18),
                                                                      ("seven_day", 0.28, 0.29))),
                                       _call("p", 0.49)])
    u = cycle_usage.usage_for(ledger, "a" * 40)
    assert [s.window for s in u.plan_share] == ["seven_day", "five_hour"]
    assert _share(u) == {"seven_day": ("measured", 0.01, None, None), "five_hour": ("measured", 0.06, None, None)}


def test_an_unmoved_window_with_no_rate_is_under_one_point_never_zero():
    ledger = cycle_usage.Ledger.build([_run("p", "a" * 12, plan=_plan(("seven_day", 0.27, 0.27))), _call("p", 0.49)])
    (s,) = cycle_usage.usage_for(ledger, "a" * 12).plan_share
    assert (s.basis, s.share, s.under) == ("under", None, 0.01)


def test_an_unmoved_window_is_estimated_from_earlier_cycles_and_capped_by_the_reading():
    ledger = cycle_usage.Ledger.build(_history() + [_run("p", "a" * 12, plan=_plan(("seven_day", 0.27, 0.27))),
                                                    _call("p", 0.25)])
    u = cycle_usage.usage_for(ledger, "a" * 12)
    # $0.25 at 2 points per dollar = half a point, on two earlier cycles; the reading's own cap rides along.
    assert _share(u)["seven_day"] == ("estimated", 0.005, 0.01, 2)


def test_an_estimate_the_reading_contradicts_gives_way_to_the_reading():
    ledger = cycle_usage.Ledger.build(_history() + [_run("p", "a" * 12, plan=_plan(("seven_day", 0.27, 0.27))),
                                                    _call("p", 3.0)])
    assert _share(cycle_usage.usage_for(ledger, "a" * 12))["seven_day"] == ("under", None, 0.01, None)


def test_a_window_never_read_is_estimated_when_a_rate_exists_and_left_out_when_not():
    ledger = cycle_usage.Ledger.build(_history() + [_run("p", "a" * 12, plan=None), _call("p", 0.5)])
    shares = _share(cycle_usage.usage_for(ledger, "a" * 12))
    # five_hour: (0.15 + 0.10) / $3 per dollar; no `under` — nothing was read.
    assert shares["seven_day"] == ("estimated", 0.01, None, 2)
    assert shares["five_hour"][0] == "estimated" and shares["five_hour"][2] is None
    assert shares["five_hour"][1] == pytest.approx(0.5 * 0.25 / 3.0, abs=1e-5)
    lone = cycle_usage.Ledger.build([_run("q", "b" * 12, plan=None), _call("q", 0.5)])
    assert cycle_usage.usage_for(lone, "b" * 12).plan_share == []   # unknown, never zero


def test_a_models_own_window_is_never_estimated_for_a_run_that_did_not_report_it():
    hist = [_run(f"o{n}", f"{n}" * 12, plan=_plan(("seven_day_opus", 0.1, 0.2))) for n in (3, 4)]
    hist += [_call("o3", 1.0), _call("o4", 1.0)]
    ledger = cycle_usage.Ledger.build(hist + [_run("p", "a" * 12, plan=None), _call("p", 0.5)])
    assert cycle_usage.usage_for(ledger, "a" * 12).plan_share == []


def test_a_window_that_fell_reset_meanwhile_and_is_estimated_or_left_out():
    fell = _plan(("seven_day", 0.30, 0.02))
    alone = cycle_usage.Ledger.build([_run("p", "a" * 12, plan=fell), _call("p", 0.25)])
    assert cycle_usage.usage_for(alone, "a" * 12).plan_share == []
    with_rate = cycle_usage.Ledger.build(_history() + [_run("p", "a" * 12, plan=fell), _call("p", 0.25)])
    assert _share(cycle_usage.usage_for(with_rate, "a" * 12))["seven_day"] == ("estimated", 0.005, None, 2)


def test_a_window_that_reset_before_the_run_ended_is_neither_measured_nor_under():
    """Claude keeps a window's pre-reset peak as ``after`` (``note_signals``), so a window whose reset time
    passed before the run ended read too little: no "measured", no "under 1%" — estimated or left out."""
    rolled = _plan(("seven_day", 0.27, 0.29), ("five_hour", 0.40, 0.40), resets_at=1_759_276_800)  # 2025-10-01
    alone = cycle_usage.Ledger.build([_run("p", "a" * 12, plan=rolled), _call("p", 0.25)])
    assert cycle_usage.usage_for(alone, "a" * 12).plan_share == []
    with_rate = cycle_usage.Ledger.build(_history() + [_run("p", "a" * 12, plan=rolled), _call("p", 0.25)])
    assert _share(cycle_usage.usage_for(with_rate, "a" * 12))["seven_day"] == ("estimated", 0.005, None, 2)
    # Nor does such a cycle teach a rate: its move undercounts the cycle.
    assert cycle_usage.rate_samples(cycle_usage.Ledger.build(
        [_run("r", "c" * 12, plan=_plan(("seven_day", 0.1, 0.2), resets_at=1_759_276_800)), _call("r", 1.0)])) == {}
    # A whole run is judged by its last batch's end.
    rows = [_run("b1", "a" * 12, plan=_plan(("seven_day", 0.27, 0.27), resets_at=1_759_309_200), drain="d1",
                 batch=1, ts="2025-10-01T08:00:00.000Z"), _call("b1", 0.2, drain="d1"),
            _run("b2", "b" * 12, plan=_plan(("seven_day", 0.27, 0.30), resets_at=1_759_309_200), drain="d1",
                 batch=2, ts="2025-10-01T10:00:00.000Z"), _call("b2", 0.2, drain="d1")]
    assert cycle_usage.usage_for_drain(cycle_usage.Ledger.build(rows), "d1").plan_share == []


# --- the rate ------------------------------------------------------------- #


def test_the_rate_needs_two_cycles_that_moved_two_points_and_pools_them():
    small = [_run("s1", "5" * 12, plan=_plan(("seven_day", 0.10, 0.11))), _call("s1", 0.1)]
    one = cycle_usage.Ledger.build(_history()[:2] + small)
    assert cycle_usage.rates_of(cycle_usage.rate_samples(one)).get(("claude-plan", "seven_day")) is None
    rate, n = cycle_usage.rates_of(cycle_usage.rate_samples(cycle_usage.Ledger.build(_history() + small)))[
        ("claude-plan", "seven_day")]
    assert (round(rate, 6), n) == (0.02, 2)


def test_a_cycle_with_a_call_that_has_no_list_price_teaches_nothing():
    hist = _history() + [_call("e1", None)]
    samples = cycle_usage.rate_samples(cycle_usage.Ledger.build(hist))
    assert ("e1", "seven_day") not in samples and ("e2", "seven_day") in samples
    # A failed call carries no figure and does not spoil the size.
    assert cycle_usage.run_size([_call("x", 0.4), _call("x", None, ok=False)]) == 0.4
    assert cycle_usage.run_size([]) is None


def test_the_machine_wide_samples_reach_a_ledger_that_opens_at_the_run(monkeypatch):
    samples = cycle_usage.rate_samples(cycle_usage.Ledger.build(_history()))
    monkeypatch.setattr(cycle_usage, "_recent_samples", lambda: samples)
    ledger = cycle_usage.Ledger.build([_run("p", "a" * 12, plan=_plan(("seven_day", 0.27, 0.27))), _call("p", 0.25)])
    assert _share(cycle_usage.usage_for(ledger, "a" * 12))["seven_day"][0] == "estimated"


def test_recent_samples_read_the_ledger_dir_and_never_raise(monkeypatch, tmp_path):
    from api.services import telemetry

    monkeypatch.setenv("CICADA_HOME", str(tmp_path))
    cycle_usage.reset_cache()
    monkeypatch.setattr(telemetry, "read_events", lambda **kw: _history())
    assert ("e1", "seven_day") in _REAL_RECENT()
    cycle_usage.reset_cache()

    def boom(**kw):
        raise OSError("unreadable")

    monkeypatch.setattr(telemetry, "read_events", boom)
    assert _REAL_RECENT() == {}


# --- who gets a share ------------------------------------------------------ #


def test_a_metered_run_has_no_share_and_an_idle_plan_cycle_neither():
    ledger = cycle_usage.Ledger.build([
        _run("k", "a" * 12, engine="litellm", connection="byok-openai"),
        _call("k", 0.3, engine="litellm", connection="byok-openai"),
        _run("i", "b" * 12, plan=_plan(("seven_day", 0.2, 0.2)))])
    assert cycle_usage.usage_for(ledger, "a" * 12).plan_share == []
    assert cycle_usage.usage_for(ledger, "b" * 12).plan_share == []


def test_a_chatgpt_plan_run_has_no_size_so_it_is_measured_or_under_only():
    plan = _plan(("primary", 0.10, 0.10), ("secondary", 0.40, 0.42), connection="chatgpt-plan")
    ledger = cycle_usage.Ledger.build([
        _run("g", "a" * 12, plan=plan, engine="codex-cli", connection="chatgpt-plan"),
        _call("g", None, engine="codex-cli", connection="chatgpt-plan", i=0, o=0)])
    assert _share(cycle_usage.usage_for(ledger, "a" * 12)) == {
        "secondary": ("measured", 0.02, None, None), "primary": ("under", None, 0.01, None)}


def test_a_whole_run_is_measured_first_to_last_and_its_summary_carries_the_share():
    rows = [_run("b1", "a" * 12, plan=_plan(("seven_day", 0.27, 0.27)), drain="d1", batch=1),
            _call("b1", 0.2, drain="d1"),
            _run("b2", "b" * 12, plan=_plan(("seven_day", 0.27, 0.28)), drain="d1", batch=2),
            _call("b2", 0.29, drain="d1")]
    u = cycle_usage.usage_for_drain(cycle_usage.Ledger.build(rows), "d1")
    assert _share(u) == {"seven_day": ("measured", 0.01, None, None)}
    s = cycle_usage.summarize(u)
    assert [(x.window, x.basis) for x in s.plan_share] == [("seven_day", "measured")]
    assert s.equiv_cost_usd == pytest.approx(0.49)


def test_plan_share_is_pure_over_its_inputs():
    plan = CycleUsagePlan(connection="claude-plan", windows=[
        CycleUsagePlanWindow(window="five_hour", before=0.5, after=0.5)])
    assert cycle_usage.plan_share(plan, None, 1.0, {}) == []
    assert [s.basis for s in cycle_usage.plan_share(plan, "claude-plan", None, {})] == ["under"]
    rates = {("claude-plan", "five_hour"): (0.004, 3)}
    (s,) = cycle_usage.plan_share(plan, "claude-plan", 1.0, rates)
    assert (s.basis, s.share, s.under, s.samples) == ("estimated", 0.004, 0.01, 3)
    # More than a whole window from one run is no estimate at all.
    assert cycle_usage.plan_share(None, "claude-plan", 1.0, {("claude-plan", "five_hour"): (2.0, 3)}) == []


# --- the engine menu ------------------------------------------------------ #


def test_last_cycles_names_the_newest_plan_runs_share_and_its_list_price_equivalent():
    rows = [_run("b1", "a" * 12, plan=_plan(("seven_day", 0.27, 0.27)), drain="d1", batch=1,
                 ts="2026-10-02T00:00:00.000Z"),
            _call("b1", 0.2, drain="d1"),
            _run("b2", "b" * 12, plan=_plan(("seven_day", 0.27, 0.27)), drain="d1", batch=2,
                 ts="2026-10-02T00:10:00.000Z"),
            _call("b2", 0.29, drain="d1")]
    last = cycle_usage.last_cycles(rows)
    run = last["last-run"]["claude-plan"]
    assert [(s.window, s.basis, s.under) for s in run["share"]] == [("seven_day", "under", 0.01)]
    assert run["equiv_usd"] == pytest.approx(0.49) and run["as_of"] == "2026-10-02T00:10:00.000Z"
    assert "chatgpt-plan" not in last["last-run"]
    keyed = cycle_usage.last_cycles([_run("k", "c" * 12, engine="litellm", connection="byok-openai"),
                                     _call("k", 0.3, engine="litellm", connection="byok-openai")])
    assert "last-run" not in keyed
