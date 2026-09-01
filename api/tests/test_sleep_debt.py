"""Sleep debt (G106 amendment): the deterministic, engine-free "how far
behind is Sleep" read exposed on `/sleep/status`.

Two layers of tests: the pure formula (`rested_components` /
`rested_pct_from_components`) asserted against exact values with no
filesystem or git involved, and `compute()` end to end against a seeded
bank (real git, no network, no model).
"""

from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from api.services import markdown_parser, predicates, sleep_debt


# --------------------------------------------------------------------------- #
# Pure formula
# --------------------------------------------------------------------------- #


def test_rested_components_empty_queue_is_zero_on_both_axes():
    volume_pct, age_pct = sleep_debt.rested_components(0, None, 25)
    assert (volume_pct, age_pct) == (0, 0)


def test_rested_components_volume_scales_linearly_to_the_reference():
    assert sleep_debt.rested_components(0, None, 20) == (0, 0)
    assert sleep_debt.rested_components(5, None, 20) == (25, 0)
    assert sleep_debt.rested_components(10, None, 20) == (50, 0)
    assert sleep_debt.rested_components(20, None, 20) == (100, 0)


def test_rested_components_volume_clamps_at_100_past_the_reference():
    volume_pct, _ = sleep_debt.rested_components(200, None, 20)
    assert volume_pct == 100


def test_rested_components_age_scales_to_72_hours():
    assert sleep_debt.AGE_REFERENCE_HOURS == 72.0
    _, age_pct = sleep_debt.rested_components(1, 36.0, 25)
    assert age_pct == 50
    _, age_pct = sleep_debt.rested_components(1, 72.0, 25)
    assert age_pct == 100
    _, age_pct = sleep_debt.rested_components(1, 144.0, 25)
    assert age_pct == 100, "age clamps at 100, never overshoots"


def test_rested_components_zero_or_none_age_is_zero_pct():
    assert sleep_debt.rested_components(3, None, 25) == (12, 0)
    assert sleep_debt.rested_components(3, 0.0, 25) == (12, 0)


def test_rested_pct_takes_the_worse_of_the_two_axes_not_an_average():
    # High volume, fresh episodes: volume dominates.
    assert sleep_debt.rested_pct_from_components(25, True, 100, 10) == 0
    # Low volume, one very old episode: age dominates.
    assert sleep_debt.rested_pct_from_components(1, True, 4, 100) == 0
    # Neither is bad: fully rested.
    assert sleep_debt.rested_pct_from_components(0, True, 0, 0) == 100


def test_rested_pct_is_none_only_when_queue_empty_and_never_run():
    assert sleep_debt.rested_pct_from_components(0, False, 0, 0) is None
    # Queue empty but Sleep HAS run before: a real, earned 100.
    assert sleep_debt.rested_pct_from_components(0, True, 0, 0) == 100
    # Queue non-empty, Sleep has NEVER run: still an honest number — the
    # oldest-episode age alone is enough, no cycle history required.
    assert sleep_debt.rested_pct_from_components(3, False, 12, 40) == 60


def test_rested_pct_worked_example_matches_the_docstring_shape():
    """A queue of 10 (cap 25) with an 18h-old oldest episode: volume=40%,
    age=25%, rested = 100 - max(40, 25) = 60%."""
    volume_pct, age_pct = sleep_debt.rested_components(10, 18.0, 25)
    assert (volume_pct, age_pct) == (40, 25)
    assert sleep_debt.rested_pct_from_components(10, True, volume_pct, age_pct) == 60


# --------------------------------------------------------------------------- #
# compute() end to end
# --------------------------------------------------------------------------- #


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def _init_bank(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    return memory


def _write_episode(memory, ep_id, *, hours_ago: float, processed: bool = False):
    ts = (datetime.now() - timedelta(hours=hours_ago)).isoformat()
    markdown_parser.write(
        memory / "episodes" / f"{ep_id}.md",
        {"id": ep_id, "processed": processed, "source": "mcp", "timestamp": ts},
        f"Episode {ep_id} body.",
    )


def test_compute_on_a_never_run_empty_bank_has_no_baseline(tmp_path):
    memory = _init_bank(tmp_path)
    debt = asyncio.run(sleep_debt.compute(memory, SimpleNamespace()))
    assert debt.unprocessed_count == 0
    assert debt.has_run_before is False
    assert debt.rested_pct is None
    assert debt.hours_since_last_cycle is None


def test_compute_counts_only_unprocessed_and_finds_the_oldest(tmp_path):
    memory = _init_bank(tmp_path)
    _write_episode(memory, "ep_a", hours_ago=1.0)
    _write_episode(memory, "ep_b", hours_ago=40.0)
    _write_episode(memory, "ep_c", hours_ago=5.0, processed=True)  # excluded

    debt = asyncio.run(
        sleep_debt.compute(memory, SimpleNamespace(sleep_max_episodes_per_cycle=25))
    )
    assert debt.unprocessed_count == 2
    assert debt.oldest_unprocessed_age_hours == pytest.approx(40.0, abs=0.05)
    assert debt.volume_pct == 8    # round(100 * 2/25)
    assert debt.age_pct == round(100 * 40.0 / 72.0)


def test_compute_finds_the_most_recent_real_sleep_cycle_commit(tmp_path):
    memory = _init_bank(tmp_path)
    (memory / "entities" / "e1.md").write_text("---\nid: e1\n---\nbody")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "Sleep cycle 2026-08-30\n\nentities/e1.md: created")

    debt = asyncio.run(sleep_debt.compute(memory, SimpleNamespace()))
    assert debt.has_run_before is True
    assert debt.hours_since_last_cycle is not None
    assert debt.hours_since_last_cycle < 1.0   # just committed


def test_compute_ignores_inbox_resolution_and_decay_only_commits(tmp_path):
    """Neither commit shape represents Sleep actually running — see
    `sleep_debt._last_cycle_at`'s docstring."""
    memory = _init_bank(tmp_path)
    (memory / "inbox").mkdir(parents=True)
    (memory / "inbox" / "inbox-001.md").write_text("---\nid: i1\n---\nbody")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "Inbox resolution 2026-08-30\n\ninbox/inbox-001.md: resolved")

    (memory / "entities" / "e1.md").write_text("---\nid: e1\n---\nbody")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "Sleep cycle 2026-08-30 (decay)\n\nentities/e1.md: updated")

    debt = asyncio.run(sleep_debt.compute(memory, SimpleNamespace()))
    assert debt.has_run_before is False
    assert debt.hours_since_last_cycle is None


def test_compute_with_no_git_repo_at_all_degrades_to_never_run(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)

    debt = asyncio.run(sleep_debt.compute(memory, SimpleNamespace()))
    assert debt.has_run_before is False
    assert debt.unprocessed_count == 0


def test_compute_falls_back_to_the_default_cap_when_settings_lacks_the_field(tmp_path):
    """A `SimpleNamespace` settings stand-in without `sleep_max_episodes_per_cycle`
    (the same shape several sleep_cycle tests already use) must not raise."""
    memory = _init_bank(tmp_path)
    _write_episode(memory, "ep_a", hours_ago=1.0)

    debt = asyncio.run(sleep_debt.compute(memory, SimpleNamespace()))
    assert debt.volume_pct == round(100 * 1 / sleep_debt.DEFAULT_VOLUME_REFERENCE)


def test_compute_accepts_settings_none(tmp_path):
    """`compute`'s `settings` param is optional — a caller with no Settings
    instance at all (unlikely today, but the signature allows it) still gets
    the default volume reference rather than a crash."""
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    debt = asyncio.run(sleep_debt.compute(memory, None))
    assert debt.unprocessed_count == 0


# --------------------------------------------------------------------------- #
# Router: /sleep/status carries the debt block
# --------------------------------------------------------------------------- #


def test_sleep_status_carries_the_debt_block():
    from fastapi.testclient import TestClient

    from api import main

    body = TestClient(main.app).get("/sleep/status").json()
    assert "debt" in body
    debt = body["debt"]
    assert "unprocessedCount" in debt
    assert "volumePct" in debt
    assert "agePct" in debt
    assert "restedPct" in debt
    assert "hasRunBefore" in debt


def test_sleep_episodes_carries_the_origin_field(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import main
    from api.config import Settings

    memory = _init_bank(tmp_path)
    _write_episode(memory, "ep_a", hours_ago=1.0)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))

    body = TestClient(main.app).get("/sleep/episodes").json()
    assert len(body) == 1
    assert body[0]["origin"] == "claude-code"   # source "mcp" -> origin "claude-code"
