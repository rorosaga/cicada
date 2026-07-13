"""Tests for the repo-link layer (backlog G-repo).

Covers, in order:

1. ``api.services.repo_context`` — ``git_repo_snapshot`` / ``resolve_repo_context``
   against a REAL throwaway git repo built in ``tmp_path`` (happy path, stale
   default-branch hint, other-device short-circuit, missing path, non-repo dir,
   git timeout, worktree ``is_main`` detection).
2. ``GET`` / ``PATCH /entities/{id}/repos`` via direct router-function calls
   (mirrors ``test_merge_direction_and_location.py``'s harness — a real
   git-backed ``memory/`` in ``tmp_path``, no FastAPI TestClient needed).
3. The read-time ``repo:<slug>`` synthetic nodes + ``has repo`` edges in
   ``api.services.graph_builder.build_graph`` (mirrors
   ``test_graph_claim_overlay.py``'s harness).

No real user paths, no network, no live ``memory/`` touched anywhere.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.models.schemas import RepoInput, RepoUpdateRequest
from api.services import graph_builder, local_refs, markdown_parser, repo_context


def run(coro):
    """Drive an async call from a sync test (no anyio dependency)."""
    return asyncio.run(coro)


# --- tiny git harness (mirrors test_merge_direction_and_location.py) --------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def _init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial commit")


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path


def _init_memory(tmp_path: Path) -> Path:
    repo = tmp_path / "memory"
    (repo / "entities").mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")
    return repo


def _write_entity(repo: Path, eid: str, frontmatter: dict, body: str) -> Path:
    path = repo / "entities" / f"{eid}.md"
    markdown_parser.write(path, frontmatter, body)
    return path


# --- 1. repo_context service -------------------------------------------------


def test_snapshot_happy_path(tmp_path):
    project = tmp_path / "my-project"
    _init_git_repo(project)

    snap = repo_context.git_repo_snapshot(str(project))

    assert snap["status"] == "ok"
    assert snap["exists"] is True
    assert snap["is_git_repo"] is True
    assert snap["current_branch"] == "main"
    assert snap["dirty_files"] == 0
    assert snap["last_commit"] is not None
    assert snap["last_commit"]["subject"] == "initial commit"
    assert snap["last_commit"]["author"] == "Cicada Test"
    assert len(snap["last_commit"]["hash"]) >= 7
    # single-worktree repo: exactly one entry, and it must be the main one.
    assert len(snap["worktrees"]) == 1
    assert snap["worktrees"][0]["is_main"] is True
    assert snap["worktrees"][0]["declared"] is False


def test_resolve_repo_context_happy_path(tmp_path):
    project = tmp_path / "my-project"
    _init_git_repo(project)

    ctx = repo_context.resolve_repo_context({"path": str(project)})

    assert ctx["status"] == "ok"
    assert ctx["path"] == str(project)
    assert ctx["current_branch"] == "main"
    assert ctx["stale_hint"] is None


def test_stale_hint_when_declared_default_branch_mismatches_observed(tmp_path):
    project = tmp_path / "my-project"
    _init_git_repo(project)
    # Fake an observed "origin HEAD" symref pointing at main, without needing a
    # real remote — resolve_repo_context only reads this ref, it never
    # validates that the target actually resolves.
    _git(project, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    ctx = repo_context.resolve_repo_context(
        {"path": str(project), "default_branch": "master"}
    )

    assert ctx["status"] == "ok"
    assert ctx["default_branch_declared"] == "master"
    assert ctx["default_branch_observed"] == "main"
    assert ctx["stale_hint"] is not None
    assert "master" in ctx["stale_hint"] and "main" in ctx["stale_hint"]


def test_no_stale_hint_when_declared_matches_observed(tmp_path):
    project = tmp_path / "my-project"
    _init_git_repo(project)
    _git(project, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    ctx = repo_context.resolve_repo_context(
        {"path": str(project), "default_branch": "main"}
    )

    assert ctx["stale_hint"] is None


def test_other_device_short_circuits_without_touching_git(tmp_path, monkeypatch):
    project = tmp_path / "my-project"
    _init_git_repo(project)  # a real, valid repo — must NOT be probed

    monkeypatch.setattr(local_refs, "current_device_id", lambda: "this-machine")

    ctx = repo_context.resolve_repo_context(
        {"path": str(project), "device": "some-other-machine"}
    )

    assert ctx["status"] == "other_device"
    assert ctx["exists"] is False
    assert ctx["is_git_repo"] is False
    assert ctx["current_branch"] is None
    assert ctx["last_commit"] is None


def test_matching_device_is_probed(tmp_path, monkeypatch):
    project = tmp_path / "my-project"
    _init_git_repo(project)
    monkeypatch.setattr(local_refs, "current_device_id", lambda: "this-machine")

    ctx = repo_context.resolve_repo_context(
        {"path": str(project), "device": "this-machine"}
    )

    assert ctx["status"] == "ok"
    assert ctx["current_branch"] == "main"


def test_missing_path(tmp_path):
    ghost = tmp_path / "does-not-exist"

    ctx = repo_context.resolve_repo_context({"path": str(ghost)})

    assert ctx["status"] == "missing"
    assert ctx["exists"] is False
    assert ctx["is_git_repo"] is False


def test_not_a_repo(tmp_path):
    plain_dir = tmp_path / "plain_dir"
    plain_dir.mkdir()

    ctx = repo_context.resolve_repo_context({"path": str(plain_dir)})

    assert ctx["status"] == "not_a_repo"
    assert ctx["exists"] is True
    assert ctx["is_git_repo"] is False


def test_git_timeout_degrades_gracefully(tmp_path, monkeypatch):
    project = tmp_path / "my-project"
    _init_git_repo(project)

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=2.0)

    monkeypatch.setattr(repo_context.subprocess, "run", _raise_timeout)

    ctx = repo_context.resolve_repo_context({"path": str(project)}, timeout_s=0.1)

    assert ctx["status"] == "timeout"
    assert ctx["is_git_repo"] is False
    assert ctx["last_commit"] is None


def test_worktree_is_main_detection(tmp_path):
    project = tmp_path / "my-project"
    _init_git_repo(project)
    linked = tmp_path / "my-project-linked"
    try:
        _git(project, "worktree", "add", "-b", "feature", str(linked))
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        pytest.skip(f"git worktree add unavailable in this sandbox: {exc}")

    snap = repo_context.git_repo_snapshot(str(project))

    assert len(snap["worktrees"]) == 2
    by_path = {w["path"]: w for w in snap["worktrees"]}
    assert by_path[str(project)]["is_main"] is True
    assert by_path[str(linked)]["is_main"] is False
    assert by_path[str(linked)]["branch"] == "feature"

    # Querying FROM the linked worktree must agree on which one is main.
    snap_from_linked = repo_context.git_repo_snapshot(str(linked))
    by_path2 = {w["path"]: w for w in snap_from_linked["worktrees"]}
    assert by_path2[str(project)]["is_main"] is True
    assert by_path2[str(linked)]["is_main"] is False


def test_declared_worktree_gets_declared_flag(tmp_path):
    project = tmp_path / "my-project"
    _init_git_repo(project)

    ctx = repo_context.resolve_repo_context(
        {"path": str(project), "worktrees": [{"path": str(project), "branch": "main", "primary": True}]}
    )

    assert ctx["worktrees"][0]["declared"] is True


def test_dirty_files_counted(tmp_path):
    project = tmp_path / "my-project"
    _init_git_repo(project)
    (project / "untracked.txt").write_text("x", encoding="utf-8")

    snap = repo_context.git_repo_snapshot(str(project))

    assert snap["dirty_files"] == 1


# --- 2. GET / PATCH /entities/{id}/repos router ------------------------------


def test_get_entity_repos_happy_path(tmp_path):
    memory = _init_memory(tmp_path)
    project = tmp_path / "cicada-checkout"
    _init_git_repo(project)
    _write_entity(
        memory, "cicada",
        {"name": "Cicada", "type": "project", "status": "active", "confidence": 0.9,
         "repos": [{"path": str(project)}]},
        "The capstone project.",
    )

    from api.routers import entities as entities_router

    resp = run(entities_router.get_entity_repos("cicada", settings=_Settings(memory)))

    assert resp.entity_id == "cicada"
    assert len(resp.repos) == 1
    assert resp.repos[0].status == "ok"
    assert resp.repos[0].current_branch == "main"


def test_get_entity_repos_empty_when_no_repos_key(tmp_path):
    memory = _init_memory(tmp_path)
    _write_entity(
        memory, "no-repos",
        {"name": "No Repos", "type": "project", "status": "active", "confidence": 0.5},
        "Nothing declared.",
    )

    from api.routers import entities as entities_router

    resp = run(entities_router.get_entity_repos("no-repos", settings=_Settings(memory)))

    assert resp.repos == []


def test_get_entity_repos_404_when_entity_missing(tmp_path):
    memory = _init_memory(tmp_path)

    from fastapi import HTTPException

    from api.routers import entities as entities_router

    with pytest.raises(HTTPException) as exc_info:
        run(entities_router.get_entity_repos("ghost", settings=_Settings(memory)))
    assert exc_info.value.status_code == 404


def test_patch_entity_repos_writes_frontmatter_and_commits(tmp_path):
    memory = _init_memory(tmp_path)
    project = tmp_path / "cicada-checkout"
    _init_git_repo(project)
    entity_path = _write_entity(
        memory, "cicada",
        {"name": "Cicada", "type": "project", "status": "active", "confidence": 0.9},
        "The capstone project.",
    )
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")

    from api.routers import entities as entities_router

    request = RepoUpdateRequest(
        repos=[RepoInput(path=str(project), default_branch="main")]
    )
    resp = run(entities_router.update_entity_repos("cicada", request, settings=_Settings(memory)))

    assert len(resp.repos) == 1
    assert resp.repos[0].status == "ok"

    parsed = markdown_parser.parse(entity_path)
    assert parsed.frontmatter["repos"] == [{"path": str(project), "default_branch": "main"}]
    # Other frontmatter keys + body untouched.
    assert parsed.frontmatter["name"] == "Cicada"
    assert parsed.body == "The capstone project."

    log = _git(memory, "log", "-1", "--format=%s%n%b")
    assert "trigger: user/companion_app" in log
    assert "Cicada-Author: user" in log


def test_patch_entity_repos_empty_list_removes_key(tmp_path):
    memory = _init_memory(tmp_path)
    entity_path = _write_entity(
        memory, "cicada",
        {"name": "Cicada", "type": "project", "status": "active", "confidence": 0.9,
         "repos": [{"path": "/some/path"}]},
        "The capstone project.",
    )
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")

    from api.routers import entities as entities_router

    request = RepoUpdateRequest(repos=[])
    resp = run(entities_router.update_entity_repos("cicada", request, settings=_Settings(memory)))

    assert resp.repos == []
    parsed = markdown_parser.parse(entity_path)
    assert "repos" not in parsed.frontmatter


def test_patch_entity_repos_404_when_entity_missing(tmp_path):
    memory = _init_memory(tmp_path)

    from fastapi import HTTPException

    from api.routers import entities as entities_router

    with pytest.raises(HTTPException) as exc_info:
        run(
            entities_router.update_entity_repos(
                "ghost", RepoUpdateRequest(repos=[]), settings=_Settings(memory)
            )
        )
    assert exc_info.value.status_code == 404


# --- 3. graph synthetic repo nodes -------------------------------------------


def _write_graph_entity(memory_path, stem, name, **fm_extra):
    entities_dir = memory_path / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    fm = {"name": name, "type": "project", "status": "active", "confidence": 0.8}
    fm.update(fm_extra)
    markdown_parser.write(entities_dir / f"{stem}.md", fm, "A page.")


def test_graph_gets_repo_node_and_has_repo_edge(tmp_path):
    _write_graph_entity(
        tmp_path, "cicada", "Cicada",
        repos=[{"path": "/Users/someone/Documents/cicada"}],
    )

    resp = graph_builder.build_graph(tmp_path)

    repo_nodes = [n for n in resp.nodes if n.type == "repo"]
    assert len(repo_nodes) == 1
    assert repo_nodes[0].id == "repo:cicada"
    assert repo_nodes[0].name == "cicada"

    repo_links = [l for l in resp.links if l.label == "has repo"]
    assert len(repo_links) == 1
    assert repo_links[0].source == "cicada"
    assert repo_links[0].target == "repo:cicada"


def test_graph_dedupes_repo_node_across_multiple_owning_entities(tmp_path):
    _write_graph_entity(
        tmp_path, "cicada-app", "Cicada App",
        repos=[{"path": "/Users/someone/Documents/cicada"}],
    )
    _write_graph_entity(
        tmp_path, "cicada-api", "Cicada API",
        repos=[{"path": "/Users/someone/Documents/cicada"}],
    )

    resp = graph_builder.build_graph(tmp_path)

    repo_nodes = [n for n in resp.nodes if n.type == "repo"]
    assert len(repo_nodes) == 1

    repo_links = [l for l in resp.links if l.label == "has repo"]
    assert {l.source for l in repo_links} == {"cicada-app", "cicada-api"}
    assert all(l.target == "repo:cicada" for l in repo_links)


def test_graph_without_repos_key_has_no_repo_nodes(tmp_path):
    _write_graph_entity(tmp_path, "plain", "Plain")

    resp = graph_builder.build_graph(tmp_path)

    assert [n for n in resp.nodes if n.type == "repo"] == []
    assert [l for l in resp.links if l.label == "has repo"] == []
