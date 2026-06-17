"""Hermetic tests for git-provenance contributors + per-entity authoring + diffs.

Every test builds a throwaway git repo in a tmp dir with hand-crafted commits
carrying ``Cicada-Author:`` trailers. The real ``memory/`` and the repo's own
git history are never touched.
"""

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.services import git_service


def run(coro):
    """Drive an async git_service call from a sync test (no anyio dependency)."""
    return asyncio.run(coro)


# --- tiny git harness -------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")
    (repo / "entities").mkdir(exist_ok=True)


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def _write_entity(repo: Path, entity_id: str, body: str) -> None:
    (repo / "entities" / f"{entity_id}.md").write_text(body, encoding="utf-8")


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "memory"
    _init_repo(r)
    return r


# --- commit message builder -------------------------------------------------


def test_build_commit_message_appends_single_author_trailer():
    msg = git_service.build_commit_message(
        "Sleep cycle 2026-06-17",
        body_lines=["entities/foo.md: created (source: ep_1, trigger: sleep/extraction)"],
        authors=["gpt-5.4-mini"],
    )
    assert msg.startswith("Sleep cycle 2026-06-17\n\n")
    assert "entities/foo.md: created" in msg
    assert "Cicada-Author: gpt-5.4-mini" in msg


def test_build_commit_message_dedupes_and_lists_multiple_authors():
    msg = git_service.build_commit_message(
        "Sleep cycle",
        body_lines=["entities/foo.md: updated"],
        authors=["gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.4-mini"],
    )
    # one trailer per distinct author, order preserved, no dupes
    trailers = [ln for ln in msg.splitlines() if ln.startswith("Cicada-Author:")]
    assert trailers == [
        "Cicada-Author: gpt-5.4-mini",
        "Cicada-Author: gpt-5.4-nano",
    ]


def test_build_commit_message_no_authors_omits_trailer():
    msg = git_service.build_commit_message("Subject", body_lines=["x: y"], authors=[])
    assert "Cicada-Author" not in msg


# --- contributors aggregation ----------------------------------------------


def test_contributors_aggregates_models_and_user(repo):
    _write_entity(repo, "alpha", "v1")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle 2026-06-15",
            body_lines=["entities/alpha.md: created (trigger: sleep/extraction)"],
            authors=["gpt-5.4-mini"],
        ),
    )
    _write_entity(repo, "beta", "v1")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle 2026-06-16",
            body_lines=["entities/beta.md: created (trigger: sleep/extraction)"],
            authors=["gpt-5.4-mini", "gpt-5.4-nano"],
        ),
    )
    _write_entity(repo, "alpha", "v2 user edit")
    _commit(
        repo,
        git_service.build_commit_message(
            "Inbox resolution (decay) 2026-06-17",
            body_lines=["entities/alpha.md: updated (trigger: user/companion_app)"],
            authors=["user"],
        ),
    )

    contributors = run(git_service.get_contributors(repo))
    by_author = {c.author: c for c in contributors}

    assert set(by_author) == {"gpt-5.4-mini", "gpt-5.4-nano", "user"}
    assert by_author["gpt-5.4-mini"].commit_count == 2
    assert by_author["gpt-5.4-nano"].commit_count == 1
    assert by_author["user"].commit_count == 1
    # gpt-5.4-mini authored alpha (created) + beta -> 2 distinct entities
    assert by_author["gpt-5.4-mini"].entity_count == 2
    # user touched only alpha
    assert by_author["user"].entity_count == 1
    assert "entities/alpha.md" in by_author["user"].files
    # last-active timestamps are ISO date strings, newest commit wins for user
    assert by_author["user"].last_active >= by_author["gpt-5.4-mini"].last_active


def test_contributors_untrailered_commit_attributed_to_unknown(repo):
    _write_entity(repo, "gamma", "v1")
    # plain commit, no trailer at all
    _commit(repo, "Sleep cycle legacy\n\nentities/gamma.md: created")

    contributors = run(git_service.get_contributors(repo))
    by_author = {c.author: c for c in contributors}
    assert "unknown" in by_author
    assert by_author["unknown"].commit_count == 1


def test_contributors_on_non_git_dir_returns_empty(tmp_path):
    assert run(git_service.get_contributors(tmp_path / "nope")) == []


# --- per-entity authoring ---------------------------------------------------


def test_entity_history_carries_authoring_model(repo):
    _write_entity(repo, "alpha", "line one\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle 2026-06-15",
            body_lines=["entities/alpha.md: created (trigger: sleep/extraction)"],
            authors=["gpt-5.4-mini"],
        ),
    )
    _write_entity(repo, "alpha", "line one\nline two by user\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Inbox resolution 2026-06-17",
            body_lines=["entities/alpha.md: updated (trigger: user/manual_edit)"],
            authors=["user"],
        ),
    )

    history = run(git_service.get_entity_history("alpha", repo))
    authors = {e.author for e in history}
    # both the model and the user appear as authors of alpha's current lines
    assert "gpt-5.4-mini" in authors
    assert "user" in authors


def test_entity_history_missing_entity_is_empty(repo):
    assert run(git_service.get_entity_history("does-not-exist", repo)) == []


# --- per-commit diff --------------------------------------------------------


def test_entity_commit_diff_returns_added_and_removed(repo):
    _write_entity(repo, "alpha", "alpha v1\nshared\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    _write_entity(repo, "alpha", "alpha v2\nshared\n")
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )

    diff = run(git_service.get_entity_commit_diff("alpha", sha, repo))
    assert "alpha v2" in diff.added
    assert "alpha v1" in diff.removed
    # unchanged context line is not double-counted as add/remove
    assert "shared" not in diff.added
    assert "shared" not in diff.removed


def test_entity_commit_diff_missing_commit_returns_empty(repo):
    _write_entity(repo, "alpha", "alpha v1\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    diff = run(git_service.get_entity_commit_diff("alpha", "deadbeef" * 5, repo))
    assert diff.added == "" and diff.removed == ""


def test_entity_history_include_diff_populates_diff_field(repo):
    _write_entity(repo, "alpha", "first\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    history = run(git_service.get_entity_history("alpha", repo, include_diff=True))
    assert history
    assert any(e.diff is not None and "first" in e.diff.added for e in history)


# --- router wiring (endpoint functions called directly, no live app) ---------


class _FakeSettings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path


def test_contributors_router_returns_response(repo):
    from api.routers import contributors as contributors_router

    _write_entity(repo, "alpha", "v1")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    resp = run(contributors_router.get_contributors(settings=_FakeSettings(repo)))
    assert [c.author for c in resp.contributors] == ["gpt-5.4-mini"]


def test_entities_history_router_include_diff(repo):
    from api.routers import entities as entities_router

    _write_entity(repo, "alpha", "first\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    history = run(
        entities_router.get_entity_history(
            "alpha", include_diff=True, settings=_FakeSettings(repo)
        )
    )
    assert history
    assert history[0].author == "gpt-5.4-mini"
    assert history[0].diff is not None and "first" in history[0].diff.added


def test_entities_commit_diff_router(repo):
    from api.routers import entities as entities_router

    _write_entity(repo, "alpha", "first\n")
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    diff = run(
        entities_router.get_entity_commit_diff(
            "alpha", sha, settings=_FakeSettings(repo)
        )
    )
    assert "first" in diff.added
