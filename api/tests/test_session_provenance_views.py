"""G48 §4 — a commit's conversations reach the history + contributors views.

Hermetic: a throwaway git repo per test with hand-crafted trailers. The real
memory/ bank is never read.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.services import git_service, sleep_cycle

UUID_A = "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
UUID_B = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


def run(coro):
    return asyncio.run(coro)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "memory"
    (r / "entities").mkdir(parents=True)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "test@cicada.local")
    _git(r, "config", "user.name", "Cicada Test")
    return r


def _commit(repo: Path, rel: str, text: str, subject: str, lines: list[str],
            authors=None, sessions=None) -> str:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", "--", rel)
    message = git_service.build_commit_message(
        subject, lines, authors=authors, sessions=sessions
    )
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def test_entity_history_carries_the_commits_sessions(repo):
    """The entity's OWN manifest-line ``sessions: ...`` clause is what history
    reports (PR #20 round-2 review fix: no more falling back to the
    commit-wide ``Cicada-Session:`` trailers at the entity level — see
    ``test_a_decay_change_reports_no_sessions_even_with_commit_wide_trailers``
    below for the case this replaces)."""
    _commit(
        repo, "entities/mongodb.md", "---\nid: mongodb\n---\n\n# MongoDB\n",
        "Sleep cycle 2026-08-31",
        [f"entities/mongodb.md: created (source: ep_1, trigger: sleep/extraction, "
         f"sessions: {UUID_A},{UUID_B})"],
        authors=["gpt-5.4-mini"], sessions=[UUID_A, UUID_B],
    )

    entries = run(git_service.get_entity_history("mongodb", repo))
    assert len(entries) == 1
    assert entries[0].author == "gpt-5.4-mini"
    assert entries[0].sessions == [UUID_A, UUID_B]
    assert entries[0].change_type == "created", "entity-line parsing still works"


def test_a_decay_change_reports_no_sessions_even_with_commit_wide_trailers(repo):
    """PR #20 round-2 review fix — 'decay changes claim unrelated conversations'.

    The commit carries commit-wide ``Cicada-Session:`` trailers (this Sleep
    cycle also touched other conversations), but THIS entity's own manifest
    line has no ``sessions:`` clause (a decay/archive change has no source
    episode). History must report NO sessions for it — never fall back to
    the commit-wide trailer set, which would wrongly claim conversations that
    never touched this entity.
    """
    _commit(
        repo, "entities/old-tool.md", "---\nid: old-tool\n---\n\n# Old Tool\n",
        "Sleep cycle 2026-08-31",
        ["entities/old-tool.md: archive (source: n/a, trigger: sleep/decay)"],
        authors=["gpt-5.4-mini"], sessions=[UUID_A, UUID_B],
    )

    entries = run(git_service.get_entity_history("old-tool", repo))
    assert len(entries) == 1
    assert entries[0].sessions == [], (
        "no per-entity sessions clause means NO known sessions, not the "
        "commit-wide fallback"
    )


def test_entity_history_of_a_pre_g48_commit_has_no_sessions(repo):
    _commit(
        repo, "entities/mongodb.md", "---\nid: mongodb\n---\n\n# MongoDB\n",
        "Sleep cycle 2026-01-01",
        ["entities/mongodb.md: created (source: ep_1, trigger: sleep/extraction)"],
        authors=["gpt-5.4-mini"],
    )
    entries = run(git_service.get_entity_history("mongodb", repo))
    assert entries[0].sessions == []


def test_contributor_commits_carry_the_sessions(repo):
    _commit(
        repo, "entities/cicada.md", "---\nid: cicada\n---\n\n# Cicada\n",
        "Sleep cycle 2026-08-31",
        ["entities/cicada.md: updated (source: ep_1, trigger: sleep/extraction)"],
        authors=["gpt-5.4-mini"], sessions=[UUID_A],
    )

    commits = run(git_service.get_contributor_commits(repo, "gpt-5.4-mini"))
    assert len(commits) == 1
    assert commits[0].sessions == [UUID_A]
    assert commits[0].entities == ["cicada"]


def test_two_conversation_cycle_each_entity_reports_only_its_own_session(tmp_path, monkeypatch):
    """PR #20 review fix — 'batched sessions overclaim entity provenance'.

    One Sleep cycle consolidates episodes from TWO conversations and creates
    one entity from each. Even though both conversations land in the SAME
    commit (and thus the same commit-level Cicada-Session trailers), each
    entity's own history row must report ONLY the conversation whose episode
    actually touched it — never its sibling's.

    A third entity in the SAME commit is decayed (no source episode at all,
    as ``conflict_resolver.apply_decay`` produces — ``source_episode: ""``).
    PR #20 round-2 review fix: that entity's history must report NO sessions
    at all, never the commit-wide fallback — otherwise a decay/archive change
    would claim BOTH unrelated conversations just because they happened to
    land in the same batched commit.
    """
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")

    (memory / "entities" / "postgres.md").write_text(
        "---\nid: postgres\n---\n\n# Postgres\n", encoding="utf-8"
    )
    (memory / "entities" / "sqlite.md").write_text(
        "---\nid: sqlite\n---\n\n# SQLite\n", encoding="utf-8"
    )
    (memory / "entities" / "old-tool.md").write_text(
        "---\nid: old-tool\n---\n\n# Old Tool\n", encoding="utf-8"
    )
    changes = [
        {"id": "postgres", "action": "created", "source_episode": "ep_1",
         "source_episodes": ["ep_1"], "trigger": "sleep/extraction"},
        {"id": "sqlite", "action": "created", "source_episode": "ep_2",
         "source_episodes": ["ep_2"], "trigger": "sleep/extraction"},
        {"id": "old-tool", "action": "archive", "new_confidence": 0.1,
         "new_status": "archived", "source_episode": "", "trigger": "sleep/decay"},
    ]

    run(sleep_cycle._finalize(
        memory, "cycle-two-convos", changes, None,
        sessions=[UUID_A, UUID_B],
        episode_sessions={"ep_1": UUID_A, "ep_2": UUID_B},
    ))

    postgres_history = run(git_service.get_entity_history("postgres", memory))
    sqlite_history = run(git_service.get_entity_history("sqlite", memory))
    old_tool_history = run(git_service.get_entity_history("old-tool", memory))

    assert postgres_history[0].sessions == [UUID_A]
    assert sqlite_history[0].sessions == [UUID_B]
    assert UUID_B not in postgres_history[0].sessions, "must not overclaim its sibling's conversation"
    assert UUID_A not in sqlite_history[0].sessions, "must not overclaim its sibling's conversation"
    assert old_tool_history[0].sessions == [], (
        "a decay/archive change with no per-entity sessions clause must report "
        "NO sessions — never the commit-wide fallback"
    )


def test_a_user_commit_has_no_sessions(repo):
    _commit(
        repo, "entities/cicada.md", "---\nid: cicada\n---\n\n# Cicada\n",
        "Add fact source", ["entities/cicada.md: updated (trigger: user/companion_app)"],
        authors=["user"],
    )
    commits = run(git_service.get_contributor_commits(repo, "user"))
    assert commits[0].sessions == []
