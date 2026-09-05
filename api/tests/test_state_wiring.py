"""G53 wiring: Sleep's tail regenerates + commits `_state.md` as `cicada`,
`_finalize` never lets it ride in a model commit, `GET /state` refreshes
lazily with an ETag and commits its own rewrite as `cicada`, and an inbox
resolution refreshes + commits it best-effort — so no `git add -A` writer
ever finds the projection dirty (final review). Real git in a tmp bank
(mirrors test_agent_provenance.py); no model."""
from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.config import Settings
from api.services import git_service, markdown_parser, predicates, sleep_cycle, state_dictionary


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox", "hubs"):
        (memory / sub).mkdir(parents=True)
    predicates.install_predicate_map(memory)
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "Alpha Project", "type": "project", "status": "active", "confidence": 0.9,
                           "created": "2026-01-01", "last_referenced": "2026-09-01", "decay_rate": 0.05,
                           "source_episodes": [], "tags": [], "related": [], "version": 1},
                          "## Summary\nAlpha.\n")
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "t@example.com")
    _git(memory, "config", "user.name", "t")
    _git(memory, "add", ".")
    _git(memory, "commit", "-q", "-m", "seed")
    return memory


def _settings(memory: Path):
    return SimpleNamespace(memory_path=memory, litellm_model="gpt-5.4-mini",
                           litellm_disambiguation_model="gpt-5.4-nano", archive_threshold=0.2,
                           decay_nudge_threshold=0.4, link_enrich_enabled=False, inbox_stale_after_days=90)


@pytest.fixture(autouse=True)
def _tmp_home(tmp_path, monkeypatch):
    # `inputs_version` -> `sync_service.components()` stats `cicada_home()`;
    # never let a test create or read anything under the real `~/.cicada`.
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def _quiet_tail(monkeypatch):
    async def none(*a, **k):
        return None
    for name in ("_poll_connectors_safely", "_poll_feeds_and_calendars_safely",
                 "_backfill_links_safely", "_warm_logos_safely", "_refresh_questions_safely"):
        monkeypatch.setattr(sleep_cycle, name, none)


def test_idle_cycle_writes_and_commits_the_state_as_cicada(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _quiet_tail(monkeypatch)
    monkeypatch.setattr(state_dictionary, "REPO_BUDGET_S", 0.0)  # no git probes of user repos here

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-state"))

    assert (memory / "_state.md").exists()
    assert _git(memory, "status", "--porcelain").strip() == "", "the tail commits its own projection"
    body = _git(memory, "log", "-1", "--format=%B")
    assert body.startswith("State snapshot ")
    assert "_state.md: updated (trigger: sleep/state)" in body
    assert git_service._parse_authors(body) == ["cicada"]
    assert "Cicada-Engine:" not in body


def test_second_idle_cycle_makes_no_commit(tmp_path, monkeypatch):
    """The idle-night rail (R1) under the LIVE configuration: a Sleep schedule
    is enabled and the second cycle runs the next night. Before the final
    review the persisted `sleep.next_at` advanced with the date, so this only
    held with the schedule disabled and both cycles on the same day."""
    from api.models.schemas import ScheduleConfig
    from api.services import sleep_scheduler

    memory = _bank(tmp_path)
    sleep_scheduler.save_schedule(memory, ScheduleConfig(enabled=True, hour=3, minute=0))
    _git(memory, "add", "sleep_schedule.yaml")
    _git(memory, "commit", "-q", "-m", "schedule")
    _quiet_tail(monkeypatch)
    monkeypatch.setattr(state_dictionary, "REPO_BUDGET_S", 0.0)
    night_one = datetime(2026, 9, 3, 3, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(state_dictionary, "_now", lambda: night_one)
    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-a"))
    head = _git(memory, "rev-parse", "HEAD")
    assert "State snapshot" in _git(memory, "log", "-1", "--format=%s")
    monkeypatch.setattr(state_dictionary, "_now", lambda: night_one + timedelta(days=1))
    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-b"))
    assert _git(memory, "rev-parse", "HEAD") == head
    assert _git(memory, "status", "--porcelain").strip() == ""
    assert "next_at" not in (memory / "_state.md").read_text()


def test_finalize_splits_a_dirty_state_file_out_of_the_model_commit(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    memory = _bank(tmp_path)
    (memory / "_state.md").write_text("---\ntype: state\n---\n\nstale projection\n", encoding="utf-8")
    (memory / "entities" / "alpha-project.md").write_text(
        (memory / "entities" / "alpha-project.md").read_text() + "\nmore\n")
    changes = [{"id": "alpha-project", "action": "updated", "source_episode": "ep_1",
                "source_episodes": ["ep_1"], "trigger": "sleep/extraction"}]

    asyncio.run(sleep_cycle._finalize(memory, "cycle-1", changes, Settings(litellm_model="gpt-5.4-mini")))

    hashes = [h for h in _git(memory, "log", "--format=%H", "--reverse").splitlines() if h.strip()]
    assert len(hashes) == 3  # seed, state split, main
    state_msg = _git(memory, "log", "-1", "--format=%B", hashes[1])
    main_msg = _git(memory, "log", "-1", "--format=%B", hashes[2])
    assert "_state.md: updated (trigger: sleep/state)" in state_msg
    assert git_service._parse_authors(state_msg) == ["cicada"]
    assert "_state.md" not in main_msg
    assert "entities/alpha-project.md: updated" in main_msg


def test_infer_trigger_names_the_state_file():
    assert sleep_cycle._infer_trigger_for_path("_state.md") == "sleep/state"


@pytest.fixture
def api_bank(tmp_path: Path, monkeypatch) -> Path:
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    monkeypatch.setattr(state_dictionary, "REPO_BUDGET_S", 0.0)
    config.get_settings.cache_clear()
    yield memory
    config.get_settings.cache_clear()


def test_get_state_builds_lazily_and_serves_etag(api_bank):
    with TestClient(main.app) as client:
        r = client.get("/state")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["schema_version"] == 1 and data["bank"] == "memory"
        assert data["projects"][0]["id"] == "alpha-project"
        assert data["stale"] is False and data["conversations"] == []
        assert (api_bank / "_state.md").exists()
        etag = r.headers["ETag"]
        assert client.get("/state", headers={"If-None-Match": etag}).status_code == 304
        # an input change flips the ETag and the lazy refresh rebuilds
        markdown_parser.write(api_bank / "inbox" / "inbox-001.md",
                              {"kind": "decay", "status": "pending", "entity_id": "alpha-project",
                               "entity_name": "Alpha Project", "title": "Still?", "created_date": "2026-08-01"}, "c")
        r2 = client.get("/state", headers={"If-None-Match": etag})
        assert r2.status_code == 200 and r2.json()["inbox"]["pending"] == 1


def test_get_state_refresh_true_forces_a_rebuild_with_probes(api_bank, monkeypatch):
    from api.routers import state as state_router

    probes: list = []

    def fake_resolver(decl, *, timeout_s=2.0):
        probes.append(decl["path"])
        return {"path": decl["path"], "status": "ok", "current_branch": "main", "dirty_files": 0, "ahead": 0, "behind": 0}

    fm = markdown_parser.parse(api_bank / "entities" / "alpha-project.md")
    fm.frontmatter["repos"] = [{"path": "~/src/alpha"}]
    markdown_parser.write(api_bank / "entities" / "alpha-project.md", fm.frontmatter, fm.body)
    monkeypatch.setattr(state_dictionary, "REPO_BUDGET_S", 2.0)
    monkeypatch.setattr(state_router, "repo_resolver", fake_resolver)
    with TestClient(main.app) as client:
        assert client.get("/state").status_code == 200
        assert probes == [], "a lazy read never probes git"
        r = client.get("/state", params={"refresh": "true"})
        assert r.status_code == 200 and probes == ["~/src/alpha"]
        assert r.json()["projects"][0]["repos"][0]["branch"] == "main"


def test_get_state_read_commits_its_own_rewrite_as_cicada(api_bank):
    """Final review finding 1: a read-side refresh used to leave `_state.md`
    dirty for the next `git add -A` writer to sweep under its own author."""
    with TestClient(main.app) as client:
        assert client.get("/state").status_code == 200
    # app startup leaves its own untracked markers; the projection itself is clean
    assert _git(api_bank, "status", "--porcelain", "--", "_state.md").strip() == "", "the read commits what it wrote"
    body = _git(api_bank, "log", "-1", "--format=%B")
    assert body.startswith("State snapshot ") and git_service._parse_authors(body) == ["cicada"]
    assert "_state.md: updated (trigger: sleep/state)" in body
    head = _git(api_bank, "rev-parse", "HEAD")
    with TestClient(main.app) as client:
        assert client.get("/state").status_code == 200
    assert _git(api_bank, "rev-parse", "HEAD") == head, "a read that wrote nothing commits nothing"


def test_get_state_adds_next_at_per_request_and_never_persists_it(api_bank):
    from api.models.schemas import ScheduleConfig
    from api.services import sleep_scheduler

    sleep_scheduler.save_schedule(api_bank, ScheduleConfig(mode="daily", hour=3, minute=0))
    with TestClient(main.app) as client:
        data = client.get("/state").json()
    # `daily` needs no calibration inputs, so the bare call IS the right
    # answer here — unlike the two modes below, which is exactly why this
    # assertion alone used to hide the bug (it asserted the UNCALIBRATED
    # call, i.e. a regression net pointed backwards).
    assert data["sleep"]["next_at"] == sleep_scheduler.next_run_at(api_bank)
    assert data["sleep"]["next_at"].startswith("20")
    assert "next_at" not in (api_bank / "_state.md").read_text()


def test_interval_next_at_is_anchored_on_the_last_cycle_not_on_now(api_bank):
    """The uncalibrated call made `interval` read "N hours from now" on EVERY
    request, no matter when the last cycle ran, so an agent reading /state
    could never tell a schedule that just fired from one about to.
    `GET /status` already threads `last_cycle_at`; this makes the two agree
    (Track P R6 — one formula, two callers).

    `_bank` seeds one plain "seed" commit, so the fixture has NO cycle to
    anchor on and both calls would agree by accident. An aged, empty
    `Sleep cycle …` commit is what `sleep_debt._last_cycle_at` looks for
    (`--format=%aI`, subject `sleep cycle*`, `(decay)` excluded) — hence
    `--date`, which sets the AUTHOR date the scan reads.
    """
    from api.models.schemas import ScheduleConfig
    from api.services import sleep_scheduler

    _git(api_bank, "commit", "-q", "--allow-empty", "--date", "2026-09-01T00:00:00+00:00",
         "-m", "Sleep cycle 2026-09-01")
    sleep_scheduler.save_schedule(
        api_bank, ScheduleConfig(mode="interval", hour=3, minute=0, interval_hours=6)
    )
    with TestClient(main.app) as client:
        got = datetime.fromisoformat(client.get("/state").json()["sleep"]["next_at"])
    uncalibrated = datetime.fromisoformat(sleep_scheduler.next_run_at(api_bank))
    # Anchored on a cycle long past, `next_run_at` floors at `now`
    # (`max(candidate, current)`); the bare call anchors on `now` and returns
    # `now + 6 h`. Five hours of slack so a slow machine can't flake it.
    assert got < uncalibrated - timedelta(hours=5)


def test_after_import_next_at_is_an_instant_when_the_queue_is_not_empty(api_bank):
    """The uncalibrated call returns `None` for `after_import` — i.e. "no next
    run" — precisely when the settle probe is about to fire."""
    from api.models.schemas import ScheduleConfig
    from api.services import episode_ids, sleep_scheduler

    markdown_parser.write(
        api_bank / "episodes" / "ep_2026-09-01_001.md",
        {"id": "ep_2026-09-01_001", "timestamp": episode_ids.utc_now_iso(),
         "processed": False, "origin": "claude-code", "title": "Alpha project sync"},
        "user: ship alpha-project",
    )
    sleep_scheduler.save_schedule(api_bank, ScheduleConfig(mode="after_import", hour=3, minute=0))
    assert sleep_scheduler.next_run_at(api_bank) is None
    with TestClient(main.app) as client:
        assert client.get("/state").json()["sleep"]["next_at"] is not None


def test_get_state_adds_resumable_per_request_and_never_persists_it(api_bank, monkeypatch):
    from api.routers import conversations
    markdown_parser.write(api_bank / "episodes" / "ep_2026-09-02_001.md",
                          {"id": "ep_2026-09-02_001", "timestamp": "2026-09-02T09:00:00+00:00", "processed": True,
                           "session_id": "11111111-2222-4333-8444-555555555555", "harness": "claude-code",
                           "project_dir": "/tmp/alpha", "title": "Shipping alpha"}, "user: ship")
    monkeypatch.setattr(conversations, "transcript_exists", lambda project_dir, sid: True)
    with TestClient(main.app) as client:
        data = client.get("/state").json()
    assert data["conversations"][0]["resumable"] is True
    assert "resumable" not in (api_bank / "_state.md").read_text()
    assert "project_dir" not in (api_bank / "_state.md").read_text()


def test_inbox_resolution_refreshes_the_state_best_effort(api_bank, monkeypatch):
    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service
    markdown_parser.write(api_bank / "inbox" / "inbox-001.md",
                          {"kind": "decay", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "Alpha Project", "title": "Still?", "created_date": "2026-08-01"}, "c")
    settings = config.get_settings()
    state_dictionary.refresh(api_bank, settings, force=True)
    assert state_dictionary.read_state(api_bank)["inbox"]["pending"] == 1
    asyncio.run(inbox_service.resolve("inbox-001", InboxResolveRequest(action="keep_active"), settings))
    assert state_dictionary.read_state(api_bank)["inbox"]["pending"] == 0
    # ... and commits its own rewrite, alone, as `cicada` — after the person's commit
    assert _git(api_bank, "status", "--porcelain", "--", "_state.md").strip() == ""
    subjects = _git(api_bank, "log", "-2", "--format=%s").splitlines()
    assert subjects[0].startswith("State snapshot ") and subjects[1].startswith("Inbox resolution (decay)")
    assert "_state.md" not in _git(api_bank, "log", "-1", "--format=%B", "HEAD~1")


def test_a_user_write_never_sweeps_the_projection(api_bank):
    """The reproduction from the final review: read `/state` (rebuild), then
    resolve an inbox item. The resolution's `Cicada-Author: user` commit used
    to carry 13 lines of `_state.md`."""
    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service
    for n, eid in (("001", "alpha-project"), ("002", "alpha-project")):
        markdown_parser.write(api_bank / "inbox" / f"inbox-{n}.md",
                              {"kind": "decay", "status": "pending", "entity_id": eid,
                               "entity_name": "Alpha Project", "title": "Still?", "created_date": "2026-08-01"}, "c")
    settings = config.get_settings()
    with TestClient(main.app) as client:
        assert client.get("/state").json()["inbox"]["pending"] == 2
    asyncio.run(inbox_service.resolve("inbox-001", InboxResolveRequest(action="keep_active"), settings))
    with TestClient(main.app) as client:
        assert client.get("/state").json()["inbox"]["pending"] == 1
    asyncio.run(inbox_service.resolve("inbox-002", InboxResolveRequest(action="archive"), settings))
    for line in _git(api_bank, "log", "--format=%H %s").splitlines():
        sha, _, subject = line.partition(" ")
        files = _git(api_bank, "show", "--name-only", "--format=", sha).split()
        if subject.startswith("Inbox resolution"):
            assert "_state.md" not in files, f"user commit swept the projection: {subject}"
        if "_state.md" in files:
            assert subject.startswith("State snapshot "), subject
            assert files == ["_state.md"]
            assert git_service._parse_authors(_git(api_bank, "log", "-1", "--format=%B", sha)) == ["cicada"]
