"""G48 §4 — a commit's conversations reach the history + contributors views.

Hermetic: a throwaway git repo per test with hand-crafted trailers. The real
memory/ bank is never read.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.services import git_service

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
    _commit(
        repo, "entities/mongodb.md", "---\nid: mongodb\n---\n\n# MongoDB\n",
        "Sleep cycle 2026-08-31",
        ["entities/mongodb.md: created (source: ep_1, trigger: sleep/extraction)"],
        authors=["gpt-5.4-mini"], sessions=[UUID_A, UUID_B],
    )

    entries = run(git_service.get_entity_history("mongodb", repo))
    assert len(entries) == 1
    assert entries[0].author == "gpt-5.4-mini"
    assert entries[0].sessions == [UUID_A, UUID_B]
    assert entries[0].change_type == "created", "entity-line parsing still works"


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


def test_a_user_commit_has_no_sessions(repo):
    _commit(
        repo, "entities/cicada.md", "---\nid: cicada\n---\n\n# Cicada\n",
        "Add fact source", ["entities/cicada.md: updated (trigger: user/companion_app)"],
        authors=["user"],
    )
    commits = run(git_service.get_contributor_commits(repo, "user"))
    assert commits[0].sessions == []
