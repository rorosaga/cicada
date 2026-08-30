from __future__ import annotations

import asyncio
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from api.services import consumption_stats as cs
from api.services import telemetry as tm

TODAY = date(2026, 8, 28)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    repo = tmp_path / "memory"
    (repo / "entities").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    # two attributed commits on 2026-08-27, one legacy commit on 2026-08-20
    for day, msg in [("2026-08-20T03:00:00", "legacy\n"),
                     ("2026-08-27T03:00:00", "Sleep cycle 2026-08-27\n\nx\n\nCicada-Author: gpt-5.4-mini\n"),
                     ("2026-08-27T04:00:00", "Inbox resolution\n\nx\n\nCicada-Author: user\n")]:
        (repo / "entities" / f"{day[:10]}-{len(msg)}.md").write_text(msg)
        _git(repo, "add", "-A")
        subprocess.run(["git", "commit", "-q", "-m", msg], cwd=repo, check=True,
                       env={**__import__("os").environ, "GIT_AUTHOR_DATE": day, "GIT_COMMITTER_DATE": day})
    # ledger
    tm.record(tm.UsageEvent(ts="2026-08-27T03:10:00.000Z", kind="llm_call", stage="extraction", model="gpt-5.4-mini",
                            connection="byok-openai", input_tokens=1000, output_tokens=100, cost_usd=0.01, equiv_cost_usd=0.01))
    tm.record(tm.UsageEvent(ts="2026-08-27T03:11:00.000Z", kind="llm_call", stage="disambiguation", model="gpt-5.4-nano",
                            connection="byok-openai", input_tokens=500, output_tokens=50, cost_usd=0.002, equiv_cost_usd=0.002))
    tm.record(tm.UsageEvent(ts="2026-08-28T02:00:00.000Z", kind="llm_call", stage="driver", model="claude-sonnet-5",
                            connection="claude-plan", billing="subscription", engine="claude-cli",
                            input_tokens=20000, output_tokens=2000, cost_usd=None, equiv_cost_usd=0.4))
    tm.record(tm.UsageEvent(ts="2026-08-28T02:30:00.000Z", kind="sleep_run", stage="structural", model="claude-sonnet-5",
                            connection="claude-plan", billing="subscription", invocations=0, duration_ms=90000,
                            refs={"cycle_id": "sleep_x", "episodes_processed": 4}))
    tm.record(tm.UsageEvent(ts="2026-08-28T09:00:00.000Z", kind="agentic_write", stage="driver", connection="session",
                            engine="mcp-client", billing="subscription", refs={"entity_id": "a"}))
    tm.record(tm.UsageEvent(ts="2026-06-01T09:00:00.000Z", kind="llm_call", stage="ask", model="gpt-5.4-mini",
                            connection="byok-openai", input_tokens=10, output_tokens=10, cost_usd=0.5, equiv_cost_usd=0.5))
    return repo


def test_resolve_range():
    assert cs.resolve_range("30d", TODAY) == TODAY - timedelta(days=29)
    assert cs.resolve_range("month", TODAY) == date(2026, 8, 1)
    assert cs.resolve_range("all", TODAY) is None
    assert cs.resolve_range("7d", TODAY) == TODAY - timedelta(days=6)


def test_memory_write_days_counts_attributed_commits_only(env):
    days = asyncio.run(cs.memory_write_days(env))
    assert days == {"2026-08-27": 2}


def test_streaks():
    active = {"2026-08-28", "2026-08-27", "2026-08-25", "2026-08-24", "2026-08-23"}
    assert cs.streaks(active, TODAY) == (2, 3)
    assert cs.streaks({"2026-08-27"}, TODAY) == (1, 1)  # yesterday keeps the streak alive
    assert cs.streaks(set(), TODAY) == (0, 0)


def test_summary_month(env):
    s = asyncio.run(cs.summary(env, range_="month", today=TODAY))
    assert s["cost_usd"] == pytest.approx(0.012)
    assert s["equiv_cost_usd"] == pytest.approx(0.412)
    assert s["invocations"] == 3 and s["tokens"] == 23650
    assert s["memory_writes"] == 2 and s["sleep_runs"] == 1 and s["agentic_writes"] == 1
    assert (s["streak_current"], s["streak_best"]) == (2, 2)


def test_calendar_levels_and_merge(env):
    cal = asyncio.run(cs.calendar(env, weeks=2, today=TODAY))
    assert len(cal) == 14 and cal[-1]["date"] == "2026-08-28" and cal[0]["date"] == "2026-08-15"
    d27 = next(d for d in cal if d["date"] == "2026-08-27")
    d28 = next(d for d in cal if d["date"] == "2026-08-28")
    assert d27["memory_writes"] == 2 and d27["events"] == 2 and d27["cost_usd"] == pytest.approx(0.012)
    assert d28["memory_writes"] == 0 and d28["events"] == 3 and d28["tokens"] == 22000
    assert d28["level"] == 4 and d27["level"] >= 1
    assert all(d["level"] == 0 for d in cal if d["date"] not in ("2026-08-27", "2026-08-28"))


def test_stats_breakdowns(env):
    st = asyncio.run(cs.stats(env, range_="all", today=TODAY))
    models = {m["model"]: m for m in st["by_model"]}
    assert models["claude-sonnet-5"]["tokens"] == 22000 and models["claude-sonnet-5"]["cost_usd"] is None
    assert models["gpt-5.4-mini"]["cost_usd"] == pytest.approx(0.51)
    assert {s["stage"] for s in st["by_stage"]} >= {"extraction", "disambiguation", "driver", "ask"}
    assert st["favorite_model"] == "claude-sonnet-5" and st["lifetime_tokens"] == 23670
    assert st["hour_histogram"][2] == 2 and st["hour_histogram"][3] == 2 and len(st["hour_histogram"]) == 24
    assert st["peak_day"]["date"] == "2026-08-28"
    assert st["longest_sleep_run"]["duration_ms"] == 90000 and st["longest_sleep_run"]["cycle_id"] == "sleep_x"
    assert st["first_event"] == "2026-06-01"
    assert st["series"][-1]["date"] == "2026-08-28"


def test_per_connection_pricing(env):
    events = tm.read_events()
    statuses = [
        {"id": "claude-plan", "label": "Claude plan", "billing": "subscription", "priceUsdMonth": 200.0, "connected": True},
        {"id": "byok-openai", "label": "OpenAI API key", "billing": "usage", "priceUsdMonth": None, "connected": True},
    ]
    rows = {r["id"]: r for r in cs.per_connection(events, statuses)}
    assert rows["claude-plan"]["price_usd_month"] == 200.0 and rows["claude-plan"]["cost_usd"] is None
    assert rows["claude-plan"]["equiv_cost_usd"] == pytest.approx(0.4)
    assert rows["byok-openai"]["cost_usd"] == pytest.approx(0.512)
    assert {m["model"] for m in rows["byok-openai"]["by_model"]} == {"gpt-5.4-mini", "gpt-5.4-nano"}
