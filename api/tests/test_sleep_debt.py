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
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from api.services import git_service, markdown_parser, predicates, sleep_debt


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
    """`Z`-suffixed UTC — the realistic on-disk shape (review M1): the live
    bank's actual episodes use this format, not naive local time. The
    ORIGINAL version of this fixture wrote `datetime.now().isoformat()`
    (naive local) and so encoded the exact same wrong assumption
    `_parse_episode_timestamp` made — which is why the M1 timezone bug
    shipped with a green test suite. Every test below now exercises the
    real bug path.
    """
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    markdown_parser.write(
        memory / "episodes" / f"{ep_id}.md",
        {"id": ep_id, "processed": processed, "source": "mcp", "timestamp": ts},
        f"Episode {ep_id} body.",
    )


# --------------------------------------------------------------------------- #
# M1 regression: Z-suffixed UTC timestamps must not be misread as local time
# --------------------------------------------------------------------------- #


def test_parse_episode_timestamp_reads_z_suffix_as_utc_not_naive_local():
    """The bug, directly: the old code did `raw.replace("Z", "")` before
    `fromisoformat`, discarding the UTC marker so a `...Z` timestamp was
    parsed as naive LOCAL time — on a machine east of UTC (CEST, say) a
    just-captured episode reported hours old. The fix must produce a value
    that, compared against local `now()`, reads as "now" — not the same
    digits with `Z` merely stripped, which would drift by the local UTC
    offset (0 only by coincidence, e.g. on a UTC machine)."""
    now_utc = datetime.now(timezone.utc)
    z_ts = now_utc.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

    parsed = sleep_debt._parse_episode_timestamp(z_ts)

    assert parsed is not None
    assert abs((parsed - datetime.now()).total_seconds()) < 5, (
        f"parsed {parsed} should read as ~now in LOCAL time, not now()'s "
        f"UTC digits taken as-is"
    )


def test_a_just_written_z_suffixed_episode_reports_near_zero_age(tmp_path):
    """End to end, through `compute()`: this is the exact assertion that
    would have caught M1 before it shipped — the original fixture wrote
    naive-local timestamps, which never exercised the `Z` code path at all."""
    memory = _init_bank(tmp_path)
    _write_episode(memory, "ep_just_now", hours_ago=0.0)

    debt = asyncio.run(sleep_debt.compute(memory, SimpleNamespace()))

    assert debt.oldest_unprocessed_age_hours is not None
    assert debt.oldest_unprocessed_age_hours == pytest.approx(0.0, abs=0.05)
    assert debt.age_pct == 0


def test_parse_episode_timestamp_still_handles_naive_local_input():
    """MCP capture writes naive local time (`datetime.now().isoformat()`,
    no explicit tz) — the OTHER real on-disk shape. Must pass through
    unchanged rather than being (wrongly) assumed UTC."""
    naive = datetime.now().replace(microsecond=0)
    parsed = sleep_debt._parse_episode_timestamp(naive.isoformat())
    assert parsed == naive


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
# M2: `_last_cycle_at`'s git-log read is cached, invalidated on HEAD change
# --------------------------------------------------------------------------- #


def _spy_on_run_git(monkeypatch):
    calls = {"n": 0}
    orig = git_service._run_git

    async def counting(*args, **kwargs):
        calls["n"] += 1
        return await orig(*args, **kwargs)

    monkeypatch.setattr(git_service, "_run_git", counting)
    return calls


def test_last_cycle_at_spawns_git_only_once_across_repeated_calls(tmp_path, monkeypatch):
    """review M2: a `git log` subprocess on every call — the SSE loop calls
    `compute()` once a second, per connected client — was pure waste, since
    `rested_pct` can only move roughly once every 43 minutes. HEAD unchanged
    between calls must mean zero additional subprocess spawns."""
    memory = _init_bank(tmp_path)
    _git(memory, "add", "-A")
    _git(memory, "commit", "--allow-empty", "-q", "-m", "Sleep cycle 2026-08-30")
    calls = _spy_on_run_git(monkeypatch)

    first = asyncio.run(sleep_debt._last_cycle_at(memory))
    after_first = calls["n"]
    assert after_first >= 1, "the first call must actually read git"

    second = asyncio.run(sleep_debt._last_cycle_at(memory))
    third = asyncio.run(sleep_debt.compute(memory, SimpleNamespace()))

    assert calls["n"] == after_first, (
        f"expected no additional git log spawns with HEAD unchanged "
        f"({after_first} -> {calls['n']})"
    )
    assert second == first
    assert third.hours_since_last_cycle is not None


def test_last_cycle_at_recomputes_after_a_new_commit_lands(tmp_path, monkeypatch):
    """The cache must never show a stale answer past a REAL new commit —
    keyed on `git_head`, not a time-based TTL, so this is exact rather than
    an approximation that could lag."""
    memory = _init_bank(tmp_path)
    _git(memory, "add", "-A")
    _git(memory, "commit", "--allow-empty", "-q", "-m", "Sleep cycle 2026-08-30")
    calls = _spy_on_run_git(monkeypatch)

    first = asyncio.run(sleep_debt._last_cycle_at(memory))
    after_first = calls["n"]

    _git(memory, "commit", "--allow-empty", "-q", "-m", "Sleep cycle 2026-08-31")
    second = asyncio.run(sleep_debt._last_cycle_at(memory))

    assert calls["n"] > after_first, "a new commit must trigger a fresh read"
    assert second is not None and first is not None
    assert second >= first, "the newer commit's timestamp must win"


# --------------------------------------------------------------------------- #
# Devin PR #27 round 1, finding 5: the history scan pages past one batch
# --------------------------------------------------------------------------- #


def _commit(memory, subject, filename):
    (memory / filename).write_text("x")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", subject)


def test_last_cycle_at_finds_a_real_cycle_commit_beyond_the_first_page(tmp_path, monkeypatch):
    """A bank whose newest real Sleep-cycle commit is older than one page's
    worth of commits must still find it — not report `has_run_before=False`
    and lose the rested baseline. The page size is shrunk so the test
    doesn't need hundreds of real commits to prove the paging loop works."""
    monkeypatch.setattr(sleep_debt, "_HISTORY_PAGE_SIZE", 3)
    memory = _init_bank(tmp_path)
    _commit(memory, "Sleep cycle 2026-01-01", "a.txt")
    # More non-Sleep commits than one page's worth (3) — the real cycle
    # commit is now on page 2+.
    for i in range(5):
        _commit(memory, f"Manual edit {i}", f"b{i}.txt")

    result = asyncio.run(sleep_debt._last_cycle_at(memory))

    assert result is not None
    debt = asyncio.run(sleep_debt.compute(memory, SimpleNamespace()))
    assert debt.has_run_before is True


def test_last_cycle_at_returns_none_when_truly_never_run_across_many_pages(tmp_path, monkeypatch):
    """Control: exhausting every page with no match must still terminate
    and correctly report never-run, not hang or false-positive."""
    monkeypatch.setattr(sleep_debt, "_HISTORY_PAGE_SIZE", 3)
    memory = _init_bank(tmp_path)
    for i in range(8):   # more than two full pages, zero real cycle commits
        _commit(memory, f"Manual edit {i}", f"c{i}.txt")

    result = asyncio.run(sleep_debt._last_cycle_at(memory))

    assert result is None


def test_last_cycle_at_pages_efficiently_stopping_once_history_is_exhausted(tmp_path, monkeypatch):
    """The loop must stop as soon as a page comes back shorter than the
    page size (history exhausted) rather than always walking to
    `_HISTORY_MAX_PAGES` — asserted via a spy on the underlying git calls."""
    monkeypatch.setattr(sleep_debt, "_HISTORY_PAGE_SIZE", 3)
    memory = _init_bank(tmp_path)
    for i in range(4):   # seed commit + 4 = 5 total, less than 2 pages of 3
        _commit(memory, f"Manual edit {i}", f"d{i}.txt")
    calls = _spy_on_run_git(monkeypatch)

    asyncio.run(sleep_debt._last_cycle_at(memory))

    # 5 commits at page size 3: page 1 (3 commits, full -> keep going),
    # page 2 (2 commits, short -> stop). Exactly 2 git log calls, not
    # `_HISTORY_MAX_PAGES`.
    assert calls["n"] == 2


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
