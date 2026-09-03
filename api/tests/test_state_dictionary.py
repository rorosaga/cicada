"""G53 — `_state.md`, the live state dictionary.

A cursor into the graph, regenerated deterministically: ids, names and
one-liners already on entity pages, counts and enums — never claim text,
never a transcript, never a secret. Fixtures are synthetic (alpha-project,
bob-example, example.com); no test reads a real bank or the network.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from _synthetic_bank import _bank, _entity, _ok_repo, _settings

from api.services import markdown_parser, state_dictionary

TODAY = date(2026, 9, 3)
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _tmp_home(tmp_path, monkeypatch):
    # `inputs_version` goes through `sync_service.components()`, which stats
    # `cicada_home()` (logo index + telemetry file) — keep that under tmp so
    # no test creates or reads anything in the real `~/.cicada`.
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def test_build_schema_and_ranking(tmp_path):
    memory = _bank(tmp_path)
    fm, body = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW,
                                      repo_resolver=_ok_repo)
    assert fm["type"] == "state" and fm["schema_version"] == 1
    assert fm["generated_at"] == NOW.isoformat()
    assert fm["bank"] == "memory" and "owner_id" not in fm
    assert fm["engine"] == {"mode": "byok", "engine": "litellm", "model": "gpt-5.4-mini", "connected": []}
    assert fm["sleep"]["last_at"].startswith("20") and fm["sleep"]["queue_depth"] == 1
    assert fm["sleep"]["next_at"] is None
    # the deferred conflict is hidden from the pending count, like GET /inbox
    assert fm["inbox"] == {"pending": 1, "by_kind": {"decay": 1}}
    # recency × confidence, archived excluded
    assert [p["id"] for p in fm["projects"]] == ["alpha-project", "beta-project"]
    alpha = fm["projects"][0]
    assert alpha["name"] == "Alpha Project" and alpha["one_liner"].startswith("Alpha Project is a synthetic")
    assert alpha["repos"] == [{"path": "~/src/alpha-project", "branch": "feat/x", "dirty": 2,
                               "ahead_behind": "1/0", "state": "ok"}]
    assert [p["id"] for p in fm["people"]] == ["bob-example"]
    assert fm["conversations"][0]["id"] == "11111111-2222-4333-8444-555555555555"
    assert fm["conversations"][0]["harness"] == "claude-code"
    assert "resumable" not in fm["conversations"][0] and "project_dir" not in fm["conversations"][0]
    assert fm["preferences"] == [{"id": "concise-summaries", "name": "Concise Summaries",
                                  "one_liner": "Prefers concise summaries over long reports."}]
    assert fm["world_facts_note"] == state_dictionary.WORLD_FACTS_NOTE
    assert "[[Alpha Project]]" in body and "`alpha-project`" in body
    assert "## Projects" in body and "## Recent conversations" in body


def test_body_is_a_cursor_not_a_copy(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "delta-project", type="project", confidence=0.6,
            body="## Summary\nDelta.\n\n" + "`" * 3 + "claims\n- id: c1\n  text: secret claim text\n" + "`" * 3 + "\n")
    fm, body = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW, repo_resolver=_ok_repo)
    text = body + str(fm)
    assert "secret claim text" not in text
    assert "user: plan alpha" not in text  # never transcript content


def test_refresh_is_deterministic_and_debounced(tmp_path):
    memory = _bank(tmp_path)
    settings = _settings(memory)
    first = state_dictionary.refresh(memory, settings, force=True, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert first["written"] is True
    path = memory / "_state.md"
    before = path.read_bytes()
    later = NOW.replace(hour=11)
    second = state_dictionary.refresh(memory, settings, force=False, today=TODAY, now=later, repo_resolver=_ok_repo)
    assert second["written"] is False and second["reason"] == "inputs unchanged"
    assert path.read_bytes() == before
    third = state_dictionary.refresh(memory, settings, force=True, today=TODAY, now=later, repo_resolver=_ok_repo)
    assert third["written"] is False and third["reason"] == "content unchanged"
    assert path.read_bytes() == before  # generated_at alone never rewrites the file


def test_refresh_rebuilds_when_an_input_changes(tmp_path):
    memory = _bank(tmp_path)
    settings = _settings(memory)
    state_dictionary.refresh(memory, settings, force=True, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    (memory / "inbox" / "inbox-001.md").unlink()
    out = state_dictionary.refresh(memory, settings, force=False, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert out["written"] is True
    assert state_dictionary.read_state(memory)["inbox"]["pending"] == 0


def test_size_cap_trims_deterministically(tmp_path):
    memory = _bank(tmp_path)
    for i in range(60):
        _entity(memory, f"person-{i:02d}", type="person", confidence=0.9,
                body="## Summary\n" + ("Long summary sentence " * 12) + ".\n")
    for i in range(30):
        markdown_parser.write(memory / "episodes" / f"ep_2026-08-{i + 1:02d}_001.md",
                              {"id": f"ep_2026-08-{i + 1:02d}_001", "timestamp": f"2026-08-{i + 1:02d}T09:00:00+00:00",
                               "processed": True, "session_id": f"ses_2026-08-{i + 1:02d}_deadbeef",
                               "title": "T" * 300}, "x")
    settings = _settings(memory, state_people=60, state_conversations=30)
    fm, body = state_dictionary.build(memory, settings, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    rendered = state_dictionary.render(fm, body)
    assert len(rendered.encode("utf-8")) <= state_dictionary.MAX_BYTES
    assert len(fm["projects"]) == 2, "projects are trimmed last"
    assert all(len(c["title"]) <= state_dictionary.TITLE_LIMIT for c in fm["conversations"])


def test_repo_budget_degrades_to_unavailable(tmp_path):
    memory = _bank(tmp_path)
    # Must outrank alpha-project (0.99 vs 0.9 / (1 + 1/30) ≈ 0.871): repos are
    # probed in ranking order, and alpha's own declared repo would otherwise
    # spend the whole budget before `~/src/a` is reached.
    _entity(memory, "eps-project", type="project", confidence=0.99, last_referenced="2026-09-03",
            repos=[{"path": "~/src/a"}, {"path": "~/src/b"}, {"path": "~/src/c"}])
    calls: list[float] = []

    def slow(decl, *, timeout_s=2.0):
        calls.append(timeout_s)
        # spend the whole allowance the caller gave this probe
        state_dictionary._sleep_for_tests(timeout_s)
        return {"path": decl["path"], "status": "timeout"}

    fm, _ = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW,
                                   repo_resolver=slow, repo_budget_s=0.3)
    repos = {r["path"]: r["state"] for p in fm["projects"] for r in p["repos"]}
    assert repos["~/src/a"] == "timeout"
    assert repos["~/src/c"] == "unavailable", "a repo past the budget is never probed"
    assert all(t <= 0.3 for t in calls) and sum(calls) <= 0.31


def test_probe_repos_false_carries_previous_blocks_over(tmp_path):
    memory = _bank(tmp_path)
    settings = _settings(memory)
    state_dictionary.refresh(memory, settings, force=True, today=TODAY, now=NOW, repo_resolver=_ok_repo)

    def boom(decl, *, timeout_s=2.0):
        raise AssertionError("must not probe")

    (memory / "inbox" / "inbox-001.md").unlink()
    out = state_dictionary.refresh(memory, settings, force=False, probe_repos=False, today=TODAY, now=NOW,
                                   repo_resolver=boom)
    assert out["written"] is True
    state = state_dictionary.read_state(memory)
    assert state["projects"][0]["repos"][0]["branch"] == "feat/x"
    assert state["repos_probed_at"] == NOW.isoformat()


def test_no_git_and_no_settings_still_builds(tmp_path):
    memory = _bank(tmp_path, git=False)
    fm, body = state_dictionary.build(memory, None, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert fm["sleep"]["last_at"] is None
    assert fm["engine"]["mode"] == "byok" and fm["engine"]["engine"] == "litellm"


def test_engine_block_by_mode(tmp_path):
    memory = _bank(tmp_path)
    fm, _ = state_dictionary.build(memory, _settings(memory, llm_mode="agent"), today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert fm["engine"]["engine"] == "claude-cli" and fm["engine"]["model"] == "sonnet"
    fm, _ = state_dictionary.build(memory, _settings(memory, llm_mode="local"), today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert fm["engine"]["engine"] == "ollama" and fm["engine"]["model"] == "ollama/llama3.1"
    fm, _ = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW, repo_resolver=_ok_repo,
                                   connected_ids=["claude-plan"])
    assert fm["engine"]["connected"] == ["claude-plan"]


def test_owner_id_only_when_configured_and_present(tmp_path):
    memory = _bank(tmp_path)
    fm, _ = state_dictionary.build(memory, _settings(memory, observer_owner="bob-example"), today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert fm["owner_id"] == "bob-example"
    fm, _ = state_dictionary.build(memory, _settings(memory, observer_owner="nobody"), today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert "owner_id" not in fm


def test_builder_never_touches_the_llm_seam(tmp_path, monkeypatch):
    from api.services import providers

    def boom(*a, **k):
        raise AssertionError("LLM seam touched by the state builder")

    monkeypatch.setattr(providers, "resolve_llm_fn", boom)
    memory = _bank(tmp_path)
    state_dictionary.refresh(memory, _settings(memory), force=True, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert (memory / "_state.md").exists()


def test_next_run_at_moved_to_scheduler(tmp_path):
    from api.models.schemas import ScheduleConfig
    from api.routers import status
    from api.services import sleep_scheduler

    memory = _bank(tmp_path)
    assert sleep_scheduler.next_run_at(memory) is None
    sleep_scheduler.save_schedule(memory, ScheduleConfig(enabled=True, hour=3, minute=0))
    now = datetime(2026, 9, 3, 12, 0)
    assert sleep_scheduler.next_run_at(memory, now=now) == "2026-09-04T03:00:00"
    assert status._next_sleep_at(memory).startswith("20")
