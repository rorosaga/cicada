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


# --- OPTIONAL #2: sleep history lists files for the root commit --------------


def test_sleep_history_root_commit_lists_files(repo):
    """The initial (parentless) sleep-cycle commit must still report its files."""
    _write_entity(repo, "alpha", "v1")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle 2026-06-15",
            body_lines=["entities/alpha.md: created (trigger: sleep/extraction)"],
            authors=["gpt-5.4-mini"],
        ),
    )
    history = run(git_service.get_sleep_history(repo))
    assert history
    root = history[-1]  # log is newest-first; the root commit is last
    assert "entities/alpha.md" in root.files_changed


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


# --- MUST-FIX #1: argument injection via commit_hash ------------------------


def test_entity_commit_diff_rejects_flag_like_commit_hash_no_file_write(repo, tmp_path):
    """A commit_hash beginning with '-' must NOT be parsed by git as a flag.

    Reproduces the reported arg-injection: `git show --output=<path>` would write
    an arbitrary file. A malformed/hostile hash must yield an empty diff and write
    nothing.
    """
    _write_entity(repo, "alpha", "alpha v1\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    pwned = tmp_path / "PWNED"
    assert not pwned.exists()

    diff = run(git_service.get_entity_commit_diff("alpha", f"--output={pwned}", repo))

    # No file written, and the call degrades to an empty diff rather than 500ing.
    assert not pwned.exists()
    assert diff.added == "" and diff.removed == ""


def test_entity_commit_diff_rejects_non_hex_commit_hash(repo):
    """Anything that isn't a 7-40 char hex sha is rejected -> empty diff."""
    _write_entity(repo, "alpha", "alpha v1\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    for bad in ["HEAD", "main..HEAD", "../etc", "zzzzzzz", "a" * 41, "abc"]:
        diff = run(git_service.get_entity_commit_diff("alpha", bad, repo))
        assert diff.added == "" and diff.removed == "", bad


# --- MUST-FIX #2: diff output must be bounded -------------------------------


def test_entity_commit_diff_is_bounded(repo):
    """A huge rewrite must not produce an unbounded payload; output is capped
    and flagged truncated."""
    _write_entity(repo, "alpha", "seed\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    big = "\n".join(f"line {i}" for i in range(5000)) + "\n"
    _write_entity(repo, "alpha", big)
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )

    diff = run(git_service.get_entity_commit_diff("alpha", sha, repo))
    added_lines = diff.added.splitlines()
    # Capped well below the 5000 added lines.
    assert len(added_lines) <= git_service.DIFF_MAX_LINES + 1
    assert diff.truncated is True
    assert any("truncat" in ln.lower() for ln in added_lines[-2:])


def test_entity_commit_diff_small_diff_not_truncated(repo):
    _write_entity(repo, "alpha", "alpha v1\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    _write_entity(repo, "alpha", "alpha v2\n")
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )
    diff = run(git_service.get_entity_commit_diff("alpha", sha, repo))
    assert diff.truncated is False


# --- OPTIONAL #3: non-UTF-8 file degrades gracefully (no 500) ----------------


def test_entity_history_non_utf8_file_does_not_raise(repo):
    """A non-UTF-8 entity file must not blow up blame parsing with a 500."""
    (repo / "entities" / "bin.md").write_bytes(b"valid line\n\xff\xfe binary\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/bin.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    # Must not raise UnicodeDecodeError.
    history = run(git_service.get_entity_history("bin", repo))
    assert isinstance(history, list)
    assert history and history[0].author == "gpt-5.4-mini"


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
