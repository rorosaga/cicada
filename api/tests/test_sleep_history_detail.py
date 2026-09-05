"""G125 — the consolidation history the Sleep page opens (R4, R5).

Bodies are parsed server-side from a synthetic commit message shaped exactly
like `sleep_cycle._finalize` writes them; durations join the `sleep_run`
ledger by `refs.commit`; the detail endpoint resolves each `source: ep_…`
ref to its origin through the bank index. Real git for the endpoint tests
(mirrors test_sleep_connector_poll.py), no model, no network.
"""
from __future__ import annotations

import subprocess

import pytest

from api.services import git_service, markdown_parser, sleep_history, telemetry
from api.services.git_service import parse_cycle_body

BODY = """entities/alpha-project.md: created (source: ep_2026-09-01_001, trigger: sleep/extraction, sessions: ses_a)
entities/bob-example.md: updated (source: ep_2026-09-01_002, trigger: sleep/extraction)
entities/old-thing.md: updated (source: n/a, trigger: sleep/decay)
inbox/inbox-004.md: created (trigger: sleep/conflict_resolution)
_state.md: updated (trigger: sleep/state)

Cicada-Author: gpt-5.4-mini
Cicada-Engine: litellm
Cicada-Session: ses_a
Cicada-Session: ses_b"""


def test_parse_cycle_body_reads_the_manifest_and_trailers():
    m = parse_cycle_body("Sleep cycle 2026-09-01", BODY)
    assert [e["id"] for e in m.entities] == ["alpha-project", "bob-example", "old-thing"]
    assert m.entities[0] == {"id": "alpha-project", "action": "created",
                             "source_episode": "ep_2026-09-01_001", "trigger": "sleep/extraction"}
    assert m.entities[2]["source_episode"] is None          # `n/a` is not an episode
    assert m.episodes == ["ep_2026-09-01_001", "ep_2026-09-01_002"]
    assert m.files == ["entities/alpha-project.md", "entities/bob-example.md", "entities/old-thing.md",
                       "inbox/inbox-004.md", "_state.md"]
    assert m.inbox_changes == 1
    assert m.authors == ["gpt-5.4-mini"] and m.engine == "litellm" and m.sessions == ["ses_a", "ses_b"]


def test_parse_cycle_body_tolerates_an_empty_or_legacy_body():
    m = parse_cycle_body("Sleep cycle 2026-08-01", "")
    assert m.entities == [] and m.files == [] and m.authors == [] and m.engine is None


def test_attach_durations_joins_by_commit_prefix_and_never_guesses():
    entries = [
        _entry("abc1234deadbeef" + "0" * 25),
        _entry("fffff" + "1" * 35),
    ]
    events = [
        telemetry.UsageEvent(kind="sleep_run", duration_ms=4200, refs={"commit": "abc1234"}),
        telemetry.UsageEvent(kind="llm_call", duration_ms=1, refs={"commit": "fffff11111"}),  # wrong kind
        telemetry.UsageEvent(kind="sleep_run", duration_ms=9, refs={"commit": None}),
    ]
    sleep_history.attach_durations(entries, events)
    assert entries[0].duration_ms == 4200
    assert entries[1].duration_ms is None


def _entry(h):
    from api.models.schemas import SleepHistoryEntry
    return SleepHistoryEntry(commit_hash=h, date="2026-09-01", message="Sleep cycle 2026-09-01", files_changed=[])


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir()
    for i, origin in ((1, "claude-code"), (2, "safari-tab")):
        markdown_parser.write(
            memory / "episodes" / f"ep_2026-09-01_{i:03d}.md",
            {"id": f"ep_2026-09-01_{i:03d}", "timestamp": f"2026-09-01T0{i}:00:00Z",
             "source": "test", "origin": origin, "processed": True},
            "body",
        )
    (memory / "entities" / "alpha-project.md").write_text("---\ntype: project\n---\nbody\n")
    subprocess.run(["git", "init", "-q"], cwd=memory, check=True)
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "-A"], cwd=memory, check=True)
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
                    "-m", "Sleep cycle 2026-09-01\n\n" + BODY], cwd=memory, check=True)
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-m", "State snapshot 2026-09-02\n\nCicada-Author: cicada"], cwd=memory, check=True)
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-m", "Sleep cycle 2026-09-02 (decay)\n\nentities/old-thing.md: updated (source: n/a, trigger: sleep/decay)\n\nCicada-Author: cicada"],
                   cwd=memory, check=True)
    return memory


def test_get_sleep_history_returns_counts_kind_and_respects_limit(bank):
    import asyncio
    rows = asyncio.run(git_service.get_sleep_history(bank, limit=10))
    assert [r.kind for r in rows] == ["decay", "sleep"]      # newest first; the State snapshot is not a cycle
    cycle = rows[1]
    assert (cycle.entities_created, cycle.entities_updated, cycle.episodes, cycle.sessions) == (1, 2, 2, 2)
    assert cycle.authors == ["gpt-5.4-mini"] and cycle.engine == "litellm"
    assert cycle.files_changed[0] == "entities/alpha-project.md"
    assert cycle.duration_ms is None                          # telemetry is off in the suite
    assert len(asyncio.run(git_service.get_sleep_history(bank, limit=1))) == 1


def test_get_sleep_history_finds_cycles_behind_a_long_run_of_other_commits(bank):
    """Live-bank finding (2026-09-05): the top of history was a run of State
    snapshots / inbox / docs commits longer than the old `limit * 3` window,
    so `?limit=2` returned `[]` while `?limit=15` found cycles. `-n` must
    count MATCHING commits (git's own `--grep`), never a raw window."""
    import asyncio
    for i in range(12):
        subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
                        "--allow-empty", "-m", f"State snapshot 2026-09-{3 + i % 20:02d}\n\nCicada-Author: cicada"],
                       cwd=bank, check=True)
    rows = asyncio.run(git_service.get_sleep_history(bank, limit=1))
    assert [r.kind for r in rows] == ["decay"]
    rows = asyncio.run(git_service.get_sleep_history(bank, limit=2))
    assert [r.kind for r in rows] == ["decay", "sleep"]


def test_get_sleep_history_is_cached_per_head(bank, monkeypatch):
    import asyncio
    calls = []
    orig = git_service._run_git

    async def counting(memory_path, *args):
        calls.append(args[0])
        return await orig(memory_path, *args)

    monkeypatch.setattr(git_service, "_run_git", counting)
    asyncio.run(git_service.get_sleep_history(bank, limit=10))
    asyncio.run(git_service.get_sleep_history(bank, limit=10))
    assert calls.count("log") == 1


def test_cycle_detail_resolves_episode_origins_and_404s_for_non_cycles(bank):
    import asyncio
    rows = asyncio.run(git_service.get_sleep_history(bank, limit=10))
    detail = asyncio.run(git_service.get_sleep_cycle_detail(bank, rows[1].commit_hash))
    assert detail.episodes_by_origin == {"claude-code": 1, "safari-tab": 1}
    assert detail.entities[0].id == "alpha-project" and detail.truncated is False
    assert detail.inbox_changes == 1
    head = subprocess.run(["git", "rev-parse", "HEAD~1"], cwd=bank, capture_output=True, text=True).stdout.strip()
    assert asyncio.run(git_service.get_sleep_cycle_detail(bank, head)) is None      # the State snapshot


def test_history_endpoints(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main
    from api.services import bank_index

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_HOME", str(bank.parent / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    try:
        with TestClient(main.app) as client:
            rows = client.get("/sleep/history?limit=5").json()
            assert rows[1]["entitiesCreated"] == 1 and rows[1]["kind"] == "sleep"
            assert client.get("/sleep/history?limit=0").status_code == 422
            detail = client.get(f"/sleep/history/{rows[1]['commitHash']}").json()
            assert detail["episodesByOrigin"] == {"claude-code": 1, "safari-tab": 1}
            assert client.get("/sleep/history/0000000").status_code == 404
    finally:
        config.get_settings.cache_clear()
