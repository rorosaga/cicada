"""Sleep's tail keeps git's commit-graph current (owner via the coordinator, 2026-10-29).

A git-internal derived file with changed-path Bloom filters, so per-page history reads skip the commits that never
touched their page. Written under the bank's git lock; never a commit, never a tracked file; a history read answers
the same with it or without it.
"""
from __future__ import annotations

import asyncio
import subprocess

import pytest

from api.services import git_service, page_history, sleep_cycle
from api.tests.test_contributors import _commit, _init_repo, _write_entity, run


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "memory"
    _init_repo(r)
    for i in range(6):
        _write_entity(r, "alpha-place" if i % 2 else "beta-tool", f"line {i}\n")
        _commit(r, git_service.build_commit_message(
            f"Sleep cycle 2026-10-0{i + 1}",
            [f"entities/{'alpha-place' if i % 2 else 'beta-tool'}.md: updated (trigger: sleep/extraction)"],
            authors=["claude-haiku-4-5"]))
    return r


def _git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def test_it_writes_a_graph_with_changed_path_filters_and_no_commit(repo):
    head = _git(repo, "rev-parse", "HEAD")
    assert git_service.write_commit_graph_sync(repo) is True
    graph = repo / ".git" / "objects" / "info" / "commit-graph"
    assert graph.is_file()
    data = graph.read_bytes()
    assert b"BIDX" in data and b"BDAT" in data, "the changed-path Bloom filter chunks are present"
    _git(repo, "commit-graph", "verify")
    assert _git(repo, "rev-parse", "HEAD") == head, "never a commit"
    assert _git(repo, "status", "--porcelain") == "", "never a tracked file"


def test_a_history_read_answers_the_same_with_the_graph(repo):
    before, _ = run(page_history.page("alpha-place", repo))
    git_service.write_commit_graph_sync(repo)
    after, _ = run(page_history.page("alpha-place", repo))
    assert [r.commit_hash for r in after] == [r.commit_hash for r in before] and len(after) == 3
    # And again after new commits: a rewrite covers them (git reuses the filters it has).
    _write_entity(repo, "alpha-place", "line 9\n")
    _commit(repo, "Page edit 2026-10-09")
    git_service.write_commit_graph_sync(repo)
    assert len(run(page_history.page("alpha-place", repo))[0]) == 4


def test_it_runs_under_the_banks_write_lock(repo, monkeypatch):
    seen = []
    original = git_service._git_sync

    def spy(memory_path, *args):
        lock = git_service.write_lock(memory_path)
        seen.append((args[0], lock._is_owned()))
        return original(memory_path, *args)

    monkeypatch.setattr(git_service, "_git_sync", spy)
    git_service.write_commit_graph_sync(repo)
    assert seen == [("commit-graph", True)]
    assert "commit-graph" in git_service.WRITE_SUBCOMMANDS
    assert "commit-graph" not in git_service._TREE_WRITERS, "it touches no page, so no page cache starts over"


def test_a_bank_without_git_is_left_alone(tmp_path):
    (tmp_path / "entities").mkdir()
    assert git_service.write_commit_graph_sync(tmp_path) is False


def test_the_sleep_step_never_raises(repo, monkeypatch):
    def boom(_):
        raise git_service.GitError("disk full")

    monkeypatch.setattr(git_service, "write_commit_graph_sync", boom)
    asyncio.run(sleep_cycle._commit_graph_safely(repo))   # logged, not raised
    monkeypatch.undo()
    asyncio.run(sleep_cycle._commit_graph_safely(repo))
    assert (repo / ".git" / "objects" / "info" / "commit-graph").is_file()


def test_the_tail_ends_with_it():
    import inspect

    source = inspect.getsource(sleep_cycle._run_engine_independent_tail)
    assert source.rstrip().endswith("await _commit_graph_safely(memory_path)")
