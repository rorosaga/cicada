"""The entity card's History comes from ONE `git log` over the page (F3, benchmarks/scale).

`git blame --porcelain` plus one `git log -1` per surviving commit cost 1.0 s on a 3,500-claim page (41 commits) and
1.7 s at 6,000 (61); one log over the path is ~30 ms. The rows become "every commit that touched the page", newest
first — the rule `entity_commit_authors` already serves the provenance strip.
"""
from __future__ import annotations

from api.services import git_service
from api.tests.test_contributors import _commit, _init_repo, _write_entity, run

import pytest


@pytest.fixture
def repo(tmp_path):
    _init_repo(tmp_path / "memory")
    return tmp_path / "memory"


def _three_commits(repo):
    _write_entity(repo, "alpha-project", "first line\n")
    _commit(repo, git_service.build_commit_message(
        "Sleep cycle 2026-10-01", ["entities/alpha-project.md: created (trigger: sleep/extraction, sessions: ses_a)",
                                   "entities/beta-tool.md: created"], authors=["model-a"], sessions=["ses_a", "ses_b"]))
    _write_entity(repo, "alpha-project", "rewritten line\n")
    _commit(repo, git_service.build_commit_message(
        "Inbox resolution 2026-10-02", ["entities/alpha-project.md: status changed | archived"], authors=["user"]))
    _write_entity(repo, "alpha-project", "rewritten line\nsecond line\n")
    _commit(repo, git_service.build_commit_message(
        "Sleep cycle 2026-10-03", ["entities/alpha-project.md: updated (trigger: sleep, sessions: ses_c)"],
        authors=["model-b"]))


def test_history_lists_every_commit_that_touched_the_page_newest_first(repo):
    _three_commits(repo)
    history = run(git_service.get_entity_history("alpha-project", repo))
    assert [e.author for e in history] == ["model-b", "user", "model-a"]
    # The creating commit's line was overwritten; blame dropped it, the page's history keeps it.
    created = history[-1]
    assert created.change_type == "created"
    assert created.sessions == ["ses_a"]
    assert created.description.startswith("entities/alpha-project.md: created")
    assert history[1].change_type == "statusChange"
    assert history[1].description == "entities/alpha-project.md: status changed | archived"
    assert history[0].sessions == ["ses_c"]
    assert all(len(e.commit_hash) == 40 for e in history)


def test_history_is_one_git_call_and_bounded(repo, monkeypatch):
    _three_commits(repo)
    calls = []
    original = git_service._run_git

    async def counting(memory_path, *args):
        calls.append(args[0])
        return await original(memory_path, *args)

    monkeypatch.setattr(git_service, "_run_git", counting)
    monkeypatch.setattr(git_service, "MAX_PROVENANCE_COMMITS", 2)
    history = run(git_service.get_entity_history("alpha-project", repo))
    assert calls == ["log"]
    assert [e.author for e in history] == ["model-b", "user"]


def test_history_of_a_page_outside_git_is_empty(tmp_path):
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "alpha-project.md").write_text("x\n")
    assert run(git_service.get_entity_history("alpha-project", tmp_path)) == []
