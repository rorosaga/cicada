"""G53 wiring: Sleep's tail regenerates + commits `_state.md` as `cicada`,
`_finalize` never lets it ride in a model commit, `GET /state` refreshes
lazily with an ETag, and an inbox resolution refreshes it best-effort.
Real git in a tmp bank (mirrors test_agent_provenance.py); no model."""
from __future__ import annotations

import asyncio
import subprocess
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
    memory = _bank(tmp_path)
    _quiet_tail(monkeypatch)
    monkeypatch.setattr(state_dictionary, "REPO_BUDGET_S", 0.0)
    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-a"))
    head = _git(memory, "rev-parse", "HEAD")
    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-b"))
    assert _git(memory, "rev-parse", "HEAD") == head


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
