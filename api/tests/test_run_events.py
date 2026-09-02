from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from api.config import Settings
from api.services import git_service, sleep_cycle, telemetry


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    mem = tmp_path / "memory"
    (mem / "entities").mkdir(parents=True)
    _git(mem, "init", "-q")
    _git(mem, "config", "user.email", "t@t")
    _git(mem, "config", "user.name", "t")
    # `CICADA_MEMORY_PATH`/`CICADA_MEMORY_ROOT` (via validation_alias) beat the
    # `memory_root=` constructor kwarg once anything in the process has loaded
    # a real `.env` (e.g. importing `litellm`, which auto-loads one at import
    # time). Every other test in the suite points Settings at its tmp bank via
    # this env var rather than the init kwarg for exactly that reason.
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(mem))
    return mem


def test_commit_changes_returns_hash(repo):
    (repo / "entities" / "a.md").write_text("---\ntype: concept\n---\n")
    sha = asyncio.run(git_service.commit_changes(repo, "first"))
    assert sha and sha == _git(repo, "rev-parse", "HEAD").strip()
    assert asyncio.run(git_service.commit_changes(repo, "nothing")) is None


def test_finalize_records_sleep_run_event(repo):
    (repo / "entities" / "a.md").write_text("---\ntype: concept\n---\n")
    settings = Settings(memory_root=repo, litellm_model="gpt-5.4-mini")
    sleep_cycle._state.episodes_processed = 3
    sleep_cycle._state.entities_created = 1
    changes = [{"id": "a", "action": "created", "source_episode": "ep1", "trigger": "sleep/extraction"}]
    asyncio.run(sleep_cycle._finalize(repo, "sleep_test", changes, settings, started=0.0))
    events = [e for e in telemetry.read_events() if e.kind == "sleep_run"]
    assert len(events) == 1
    ev = events[0]
    assert ev.stage == "structural" and ev.model == "gpt-5.4-mini" and ev.bank == "memory"
    assert ev.refs["cycle_id"] == "sleep_test" and ev.refs["episodes_processed"] == 3
    assert ev.refs["commit"] == _git(repo, "rev-parse", "HEAD").strip()
    assert ev.duration_ms is not None and ev.duration_ms > 0


def test_agentic_write_event(repo, monkeypatch):
    from mcp import server

    monkeypatch.setattr(server, "get_memory_path", lambda: repo)
    # Pin the identity instead of comparing against the live module-level
    # SESSION (which reads this machine's real env at import time) — a fixed
    # value makes the session_id/harness assertions falsifiable.
    monkeypatch.setattr(server, "SESSION",
                        server.SessionIdentity(session_id="ses_test_fixed", harness="claude-code",
                                               project_dir=None))
    monkeypatch.setattr(server.agentic_write, "write_claim",
                        lambda *a, **k: {"action": "written", "entity_id": "a", "claim_id": "c1", "subject": "a", "observer": "agent"},
                        raising=False)
    server.handle_write_claim("a", "uses", "b", None, None, None, "ep1")
    events = [e for e in telemetry.read_events() if e.kind == "agentic_write"]
    assert len(events) == 1
    assert events[0].connection == "session" and events[0].engine == "mcp-client"
    assert events[0].refs == {
        "entity_id": "a",
        "claim_id": "c1",
        "episode_id": "ep1",
        "action": "written",
        # G48: conversation identity + client info threaded into every
        # agentic_write event's refs (see mcp/server.py::handle_write_claim).
        "session_id": "ses_test_fixed",
        "harness": "claude-code",
        "client_name": None,
        "client_version": None,
    }
    assert events[0].cost_usd is None and events[0].billing == "subscription"
