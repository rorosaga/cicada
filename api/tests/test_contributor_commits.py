"""G67 §2.2 — per-author commit listing for the Contributors drill-down.

Hermetic: every test builds a throwaway git repo with hand-crafted
``Cicada-Author:`` trailers. The real memory/ bank is never read.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.services import git_service


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


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, subject: str, lines: list[str], authors: list[str] | None) -> str:
    _git(repo, "add", "-A")
    message = (
        git_service.build_commit_message(subject, lines, authors=authors)
        if authors is not None
        else f"{subject}\n\n" + "\n".join(lines)
    )
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


class _FakeSettings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path


# --- trailer filtering ------------------------------------------------------


def test_only_commits_trailered_with_that_author_are_returned(repo):
    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"], ["gpt-5.4-mini"])
    _write(repo, "entities/beta.md", "v1")
    _commit(repo, "Inbox resolution", ["entities/beta.md: updated"], ["user"])

    mine = run(git_service.get_contributor_commits(repo, "gpt-5.4-mini"))
    theirs = run(git_service.get_contributor_commits(repo, "user"))

    assert [c.subject for c in mine] == ["Sleep cycle"]
    assert [c.subject for c in theirs] == ["Inbox resolution"]


def test_a_co_authored_commit_appears_for_every_trailered_author(repo):
    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"],
            ["gpt-5.4-mini", "gpt-5.4-nano"])

    for author in ("gpt-5.4-mini", "gpt-5.4-nano"):
        assert len(run(git_service.get_contributor_commits(repo, author))) == 1


def test_an_untrailered_commit_belongs_to_unknown(repo):
    _write(repo, "entities/gamma.md", "v1")
    _commit(repo, "Sleep cycle legacy", ["entities/gamma.md: created"], None)

    unknown = run(git_service.get_contributor_commits(repo, git_service.UNKNOWN_AUTHOR))
    assert [c.subject for c in unknown] == ["Sleep cycle legacy"]
    assert run(git_service.get_contributor_commits(repo, "gpt-5.4-mini")) == []


def test_the_reserved_cicada_system_author_is_listable(repo):
    _write(repo, "inbox/inbox-001.md", "x")
    _commit(repo, "Collapse duplicate open inbox questions",
            ["inbox/: 1 duplicate merged (trigger: inbox/dedup)"], ["cicada"])

    commits = run(git_service.get_contributor_commits(repo, "cicada"))
    assert len(commits) == 1
    assert commits[0].entities == [], "no entity files touched"
    assert commits[0].files_changed == 1


# --- shape ------------------------------------------------------------------


def test_a_commit_reports_its_hash_date_subject_entities_and_file_count(repo):
    _write(repo, "entities/alpha.md", "v1")
    _write(repo, "entities/beta.md", "v1")
    _write(repo, "graph_edges.yaml", "edges: []")
    sha = _commit(repo, "Sleep cycle 2026-08-31",
                  ["entities/alpha.md: created"], ["gpt-5.4-mini"])

    commit = run(git_service.get_contributor_commits(repo, "gpt-5.4-mini"))[0]

    assert commit.commit_hash == sha
    assert commit.date == _git(repo, "log", "-1", "--format=%ad", "--date=short").strip()
    assert commit.subject == "Sleep cycle 2026-08-31"
    assert commit.entities == ["alpha", "beta"], "entity STEMS, sorted"
    assert commit.files_changed == 3, "every changed file, entities or not"


def test_the_root_commit_still_lists_its_files(repo):
    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"], ["gpt-5.4-mini"])

    commit = run(git_service.get_contributor_commits(repo, "gpt-5.4-mini"))[0]
    assert commit.entities == ["alpha"]


def test_non_entity_paths_never_leak_into_entities(repo):
    _write(repo, "episodes/ep_1.md", "x")
    _write(repo, "entities/nested/deep.md", "x")
    _commit(repo, "Sleep cycle", ["episodes/ep_1.md: created"], ["gpt-5.4-mini"])

    commit = run(git_service.get_contributor_commits(repo, "gpt-5.4-mini"))[0]
    assert commit.entities == ["deep"]


def test_the_entity_chip_list_is_capped_but_the_total_is_honest(repo):
    """H1: a real Sleep cycle touches hundreds of pages; the wire list is capped.

    The app renders a tappable chip per id, so an uncapped `entities` is a
    render-time blow-up — but `entities_total` must still report the truth so
    the row can say "+N more".
    """
    n = git_service.MAX_COMMIT_ENTITIES + 7
    for i in range(n):
        _write(repo, f"entities/page-{i:03d}.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/page-000.md: created"], ["gpt-5.4-mini"])

    commit = run(git_service.get_contributor_commits(repo, "gpt-5.4-mini"))[0]

    assert len(commit.entities) == git_service.MAX_COMMIT_ENTITIES
    assert commit.entities_total == n
    assert commit.files_changed == n
    # The cap keeps the FIRST ids of the sorted list, so it is stable across
    # fetches rather than an arbitrary sample.
    assert commit.entities == [f"page-{i:03d}" for i in range(git_service.MAX_COMMIT_ENTITIES)]


def test_a_small_commit_reports_entities_total_equal_to_its_entities(repo):
    _write(repo, "entities/alpha.md", "v1")
    _write(repo, "entities/beta.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"], ["gpt-5.4-mini"])

    commit = run(git_service.get_contributor_commits(repo, "gpt-5.4-mini"))[0]

    assert commit.entities == ["alpha", "beta"]
    assert commit.entities_total == 2, "no phantom '+N more' for an uncapped commit"


def test_the_history_walk_is_bounded_by_the_log_window(repo, monkeypatch):
    """M3: `git log --name-only` materialises every commit it walks.

    The window is the documented bound: an author whose only commit is older
    than it does not appear in the drill-down. Shrunk here rather than writing
    500 commits.
    """
    monkeypatch.setattr(git_service, "CONTRIBUTOR_LOG_WINDOW_MULTIPLIER", 1)
    monkeypatch.setattr(git_service, "CONTRIBUTOR_LOG_WINDOW_MIN", 2)

    _write(repo, "entities/ancient.md", "v1")
    _commit(repo, "ancient cycle", ["entities/ancient.md: created"], ["cicada"])
    for i in range(3):
        _write(repo, "entities/alpha.md", f"v{i}")
        _commit(repo, f"cycle {i}", ["entities/alpha.md: updated"], ["gpt-5.4-mini"])

    # window = max(limit * 1, 2) = 2 -> only the two newest commits are read.
    assert run(git_service.get_contributor_commits(repo, "cicada", limit=2)) == []
    assert len(run(git_service.get_contributor_commits(repo, "gpt-5.4-mini", limit=2))) == 2
    # A larger limit widens the window and the rare author reappears.
    assert len(run(git_service.get_contributor_commits(repo, "cicada", limit=10))) == 1


def test_commits_are_newest_first(repo):
    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "first", ["entities/alpha.md: created"], ["gpt-5.4-mini"])
    _write(repo, "entities/alpha.md", "v2")
    _commit(repo, "second", ["entities/alpha.md: updated"], ["gpt-5.4-mini"])

    assert [c.subject for c in run(git_service.get_contributor_commits(repo, "gpt-5.4-mini"))] == [
        "second", "first",
    ]


def test_limit_bounds_the_listing(repo):
    for i in range(6):
        _write(repo, "entities/alpha.md", f"v{i}")
        _commit(repo, f"cycle {i}", ["entities/alpha.md: updated"], ["gpt-5.4-mini"])

    assert len(run(git_service.get_contributor_commits(repo, "gpt-5.4-mini", limit=2))) == 2


def test_a_multi_line_body_never_breaks_the_record_parse(repo):
    _write(repo, "entities/alpha.md", "v1")
    _commit(
        repo,
        "Sleep cycle",
        [
            "entities/alpha.md: created (source: ep_1, trigger: sleep/extraction)",
            "entities/beta.md: updated (source: ep_2, trigger: sleep/promotion)",
            "",
            "a stray blank line and some prose",
        ],
        ["gpt-5.4-mini"],
    )
    commits = run(git_service.get_contributor_commits(repo, "gpt-5.4-mini"))
    assert len(commits) == 1
    assert commits[0].subject == "Sleep cycle"


# --- degradation --------------------------------------------------------


def test_a_non_git_directory_returns_empty(tmp_path):
    assert run(git_service.get_contributor_commits(tmp_path / "nope", "user")) == []


def test_a_blank_author_returns_empty(repo):
    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"], ["gpt-5.4-mini"])
    assert run(git_service.get_contributor_commits(repo, "   ")) == []


def test_an_unknown_author_returns_empty(repo):
    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"], ["gpt-5.4-mini"])
    assert run(git_service.get_contributor_commits(repo, "claude-opus-5")) == []


# --- router -----------------------------------------------------------------


def test_router_returns_the_authors_commits(repo):
    from api.routers import contributors as contributors_router

    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"], ["gpt-5.4-mini"])

    resp = run(
        contributors_router.get_contributor_commits(
            author="gpt-5.4-mini", limit=50, settings=_FakeSettings(repo)
        )
    )
    assert resp.author == "gpt-5.4-mini"
    assert [c.subject for c in resp.commits] == ["Sleep cycle"]


def test_router_accepts_a_model_id_containing_a_slash(repo):
    from api.routers import contributors as contributors_router

    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"], ["anthropic/claude-opus-4"])

    resp = run(
        contributors_router.get_contributor_commits(
            author="anthropic/claude-opus-4", limit=50, settings=_FakeSettings(repo)
        )
    )
    assert len(resp.commits) == 1


def test_router_rejects_a_blank_author(repo):
    from api.routers import contributors as contributors_router

    with pytest.raises(HTTPException) as exc:
        run(
            contributors_router.get_contributor_commits(
                author="  ", limit=50, settings=_FakeSettings(repo)
            )
        )
    assert exc.value.status_code == 400


def test_router_clamps_an_absurd_limit(repo):
    from api.routers import contributors as contributors_router

    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"], ["gpt-5.4-mini"])

    resp = run(
        contributors_router.get_contributor_commits(
            author="gpt-5.4-mini", limit=99999, settings=_FakeSettings(repo)
        )
    )
    assert len(resp.commits) == 1  # clamped, not an error
