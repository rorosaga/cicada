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
    assert fm["type"] == "state" and fm["schema_version"] == state_dictionary.SCHEMA_VERSION
    assert fm["generated_at"] == NOW.isoformat()
    assert fm["bank"] == "memory" and "owner_id" not in fm
    assert fm["engine"] == {"mode": "byok", "engine": "litellm", "model": "gpt-5.4-mini", "connected": []}
    assert fm["sleep"]["last_at"].startswith("20") and fm["sleep"]["queue_depth"] == 1
    assert "next_at" not in fm["sleep"], "a clock, added per request by GET /state — never persisted"
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


def _observe(memory, path, *, branch="feat/x", when=NOW, device=None, status="ok", dirty=2, ahead=1, behind=0):
    from api.services import local_refs, repo_observations

    repo_observations.record(memory, [{"path": path, "device": device or local_refs.current_device_id(),
                                       "status": status, "current_branch": branch, "dirty_files": dirty,
                                       "ahead": ahead, "behind": behind}], now=when)


def test_the_default_resolver_reads_the_apps_last_look_and_never_runs_git(tmp_path, monkeypatch):
    """The backend never runs git in a declared folder: the block is the app's
    last observation (`repo_observations`), and a repo never observed is
    `unavailable`."""
    import subprocess

    from api.services import repo_context

    memory = _bank(tmp_path)
    _entity(memory, "eps-project", type="project", confidence=0.99, last_referenced="2026-09-03",
            repos=[{"path": "~/src/a"}, {"path": "~/src/b"}, {"path": "~/src/c", "device": "another-mac"}])
    _observe(memory, "~/src/a", when=NOW.replace(hour=8))
    _observe(memory, "~/src/alpha-project", branch="main", when=NOW.replace(hour=9), dirty=0)
    real_run = subprocess.run

    def only_the_bank(argv, *a, **k):
        assert "-C" not in argv, "no git -C into a declared repo"
        assert str(k.get("cwd") or "") == str(memory), "git runs in the bank and nowhere else"
        return real_run(argv, *a, **k)

    monkeypatch.setattr(subprocess, "run", only_the_bank)
    monkeypatch.setattr(repo_context, "run_repo_commands", lambda *a, **k: pytest.fail("the MCP runner ran"))
    fm, body = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW)
    repos = {r["path"]: r for p in fm["projects"] for r in p["repos"]}
    assert repos["~/src/a"] == {"path": "~/src/a", "branch": "feat/x", "dirty": 2, "ahead_behind": "1/0", "state": "ok"}
    assert repos["~/src/b"]["state"] == "unavailable" and repos["~/src/b"]["branch"] is None
    assert repos["~/src/c"]["state"] == "other_device"
    assert repos["~/src/alpha-project"]["branch"] == "main"
    assert fm["repos_probed_at"] == NOW.replace(hour=8).isoformat(), "the OLDEST rendered observation"
    assert "~/src/a@feat/x (dirty 2)" in body


def test_an_observation_older_than_a_week_is_stale(tmp_path):
    from datetime import timedelta

    memory = _bank(tmp_path)
    _observe(memory, "~/src/alpha-project", when=NOW - timedelta(days=8))
    fm, body = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW)
    block = fm["projects"][0]["repos"][0]
    assert block == {"path": "~/src/alpha-project", "branch": "feat/x", "dirty": 2, "ahead_behind": "1/0",
                     "state": "stale"}
    assert "~/src/alpha-project@feat/x (stale)" in body
    assert fm["repos_probed_at"] == (NOW - timedelta(days=8)).isoformat()
    _observe(memory, "~/src/alpha-project", when=NOW - timedelta(days=6))
    fm, _ = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW)
    assert fm["projects"][0]["repos"][0]["state"] == "ok"


def test_a_newer_look_at_the_same_branch_writes_nothing(tmp_path):
    """R1: no timestamp sits inside a block, and `repos_probed_at` is masked, so
    the app looking again changes nothing a forced rebuild compares."""
    from datetime import timedelta

    memory = _bank(tmp_path)
    settings = _settings(memory)
    _observe(memory, "~/src/alpha-project", when=NOW - timedelta(hours=2))
    assert state_dictionary.refresh(memory, settings, force=True, today=TODAY, now=NOW)["written"] is True
    before = (memory / "_state.md").read_bytes()
    _observe(memory, "~/src/alpha-project", when=NOW - timedelta(hours=1))
    again = state_dictionary.refresh(memory, settings, force=True, today=TODAY, now=NOW + timedelta(days=1))
    assert again["written"] is False and (memory / "_state.md").read_bytes() == before
    _observe(memory, "~/src/alpha-project", branch="feat/y", when=NOW)
    moved = state_dictionary.refresh(memory, settings, force=True, today=TODAY, now=NOW + timedelta(days=1))
    assert moved["written"] is True
    assert state_dictionary.read_state(memory)["projects"][0]["repos"][0]["branch"] == "feat/y"


def test_no_observation_means_no_probe_time(tmp_path):
    memory = _bank(tmp_path)
    fm, _ = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW)
    assert fm["projects"][0]["repos"][0]["state"] == "unavailable"
    assert fm["repos_probed_at"] is None


def test_a_resolver_that_raises_degrades_one_block(tmp_path):
    memory = _bank(tmp_path)

    def boom(decl, **_):
        raise RuntimeError("x")

    fm, _ = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW, repo_resolver=boom)
    assert fm["projects"][0]["repos"] == [{"path": "~/src/alpha-project", "branch": None, "dirty": None,
                                           "ahead_behind": None, "state": "unavailable"}]


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


def test_idle_night_with_a_schedule_writes_nothing(tmp_path):
    """R1 under the LIVE configuration (final review): a schedule is enabled
    and the forced rebuild runs the next day. The old in-file `next_at`
    advanced with the date and made every idle night a commit."""
    from datetime import timedelta

    from api.models.schemas import ScheduleConfig
    from api.services import sleep_scheduler

    memory = _bank(tmp_path)
    settings = _settings(memory)
    sleep_scheduler.save_schedule(memory, ScheduleConfig(enabled=True, hour=3, minute=0))
    first = state_dictionary.refresh(memory, settings, force=True, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert first["written"] is True
    text = (memory / "_state.md").read_text()
    assert "next_at" not in text
    next_night = NOW + timedelta(days=1)
    again = state_dictionary.refresh(memory, settings, force=True, today=TODAY + timedelta(days=1),
                                     now=next_night, repo_resolver=_ok_repo)
    assert again == {"written": False, "reason": "content unchanged", "path": str(memory / "_state.md")}
    assert (memory / "_state.md").read_text() == text


def test_default_clock_drives_both_now_and_today(tmp_path, monkeypatch):
    """`build` derives `today` from the same instant as `generated_at`, so an
    injected clock (the wiring test's "next night") moves both together."""
    fake = datetime(2026, 12, 24, 23, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(state_dictionary, "_now", lambda: fake)
    memory = _bank(tmp_path)
    fm, _ = state_dictionary.build(memory, _settings(memory), repo_resolver=_ok_repo)
    assert fm["generated_at"] == fake.isoformat()


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


# --- G140 Q-R13: standing and current, read off the decay classes -----------


def test_standing_focus_and_how_to_work_with_me(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "local-first", type="concept", decay_class="durable", confidence=0.9,
            last_referenced="2026-01-01", body="## Summary\nKeeps data on the device.\n")
    _entity(memory, "pinned-tool", type="tool", decay_class="evergreen", confidence=0.5)
    _entity(memory, "exam-week", type="concept", decay_class="volatile", confidence=0.4,
            last_referenced="2026-09-01")
    _entity(memory, "old-interest", type="concept", confidence=0.9, last_referenced="2026-07-01")
    _entity(memory, "saved-link", type="media", decay_class="evergreen", confidence=0.9)
    _entity(memory, "ask-first", type="skill", confidence=0.4, tags=["autonomy"],
            body="## Summary\nAsk before acting on anything irreversible.\n")
    fm, body = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert fm["schema_version"] == state_dictionary.SCHEMA_VERSION
    assert [s["id"] for s in fm["standing"]] == ["local-first", "pinned-tool"], "confidence alone, no recency"
    assert [f["id"] for f in fm["focus"]] == ["exam-week"], "active/volatile, touched in 14 days"
    assert [p["id"] for p in fm["preferences"]] == ["ask-first", "concise-summaries"], "a working tag sorts first"
    assert "saved-link" not in str(fm["standing"]) + str(fm["focus"]), "an artifact is never a belief row"
    for heading in ("## In focus (last 14 days)", "## How to work with me", "## Standing"):
        assert heading in body


def test_the_owner_row_comes_from_the_one_resolver(tmp_path):
    memory = _bank(tmp_path)
    fm, body = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert "owner_id" not in fm
    from api.services import owner_identity
    owner_identity.save_owner({"entity_id": "bob-example"})
    fm, body = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert fm["owner_id"] == "bob-example", "G117's owner.json, not only the env override"
    assert fm["owner_one_liner"].startswith("Bob Example is a synthetic fixture")
    assert "## The person" in body


def test_the_schema_is_an_input(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    before = state_dictionary.inputs_version(memory)
    monkeypatch.setattr(state_dictionary, "SCHEMA_VERSION", 99)
    assert state_dictionary.inputs_version(memory) != before, "an upgraded backend rebuilds a v1 file once"


def test_the_size_cap_gives_up_current_before_standing_and_keeps_the_agreements(tmp_path):
    memory = _bank(tmp_path)
    long = "## Summary\n" + "A long synthetic line " * 8 + ".\n"
    for i in range(40):
        _entity(memory, f"focus-{i:02d}", type="concept", decay_class="volatile", last_referenced="2026-09-02", body=long)
        _entity(memory, f"standing-{i:02d}", type="concept", decay_class="durable", confidence=0.9, body=long)
        _entity(memory, f"person-{i:02d}", type="person", confidence=0.9, body=long)
    settings = _settings(memory, state_people=40, state_focus=40, state_standing=40)
    fm, body = state_dictionary.build(memory, settings, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert len(state_dictionary.render(fm, body).encode("utf-8")) <= state_dictionary.MAX_BYTES
    assert not fm["people"] and not fm["focus"], "current rows go first"
    assert fm["preferences"] and fm["projects"], "the working agreements and the projects stay"
