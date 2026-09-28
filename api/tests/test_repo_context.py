"""Tests for the repo-link layer (backlog G-repo).

Covers, in order:

1. ``api.services.repo_context`` — the MCP tool's runner (``resolve_repo_context``)
   against a REAL throwaway git repo built in ``tmp_path`` (happy path, stale
   default-branch hint, other-device short-circuit, missing path, non-repo dir,
   git timeout, git unavailable, worktree ``is_main`` detection), and the pure
   ``parse_snapshot`` on recorded outputs (denied, missing, other_device, the
   common-dir string compare, a filesystem that must not be touched).
2. ``GET`` / ``PATCH /entities/{id}/repos`` (declarations only) and ``POST
   /entities/{id}/repos/observed`` (the app's outputs, parsed and summarised
   under ``$CICADA_HOME/repos/``) via direct router-function calls.
3. The read-time ``repo:<slug>`` synthetic nodes + ``has repo`` edges in
   ``api.services.graph_builder.build_graph``.

No real user paths, no network, no live ``memory/`` touched anywhere.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.models.schemas import (
    RepoCommandOutput,
    RepoInput,
    RepoObservation,
    RepoObservedRequest,
    RepoUpdateRequest,
)
from api.services import graph_builder, local_refs, markdown_parser, repo_context, repo_observations

FIXTURE = Path(__file__).parent / "fixtures" / "repo_commands.json"


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


# --- 1a. the command list is one list ----------------------------------------


def test_the_command_list_matches_the_shared_fixture():
    """The app's GitRunner reads the same file (GitRunnerTests): a command added
    on one side only turns the other red."""
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["prefix"] == list(repo_context.GIT_PREFIX)
    assert [(c["key"], c["args"]) for c in fixture["commands"]] == [
        (k, list(a)) for k, a in repo_context.REPO_COMMANDS
    ]
    assert fixture["commands"][0]["key"] == "inside", "the first command decides whether the rest run"
    read_only = {"rev-parse", "remote", "symbolic-ref", "status", "worktree", "log"}
    assert {c["args"][0] for c in fixture["commands"]} <= read_only
    assert ["remote", "get-url", "origin"] in [c["args"] for c in fixture["commands"]]
    assert ["worktree", "list", "--porcelain"] in [c["args"] for c in fixture["commands"]]


# --- 1b. the MCP runner against real git -------------------------------------


def test_resolve_repo_context_happy_path(tmp_path):
    project = tmp_path / "my-project"
    _init_git_repo(project)

    ctx = repo_context.resolve_repo_context({"path": str(project)})

    assert ctx["status"] == "ok"
    assert ctx["path"] == str(project)
    assert ctx["exists"] is True and ctx["is_git_repo"] is True
    assert ctx["current_branch"] == "main"
    assert ctx["dirty_files"] == 0
    assert ctx["stale_hint"] is None
    assert ctx["last_commit"]["subject"] == "initial commit"
    assert ctx["last_commit"]["author"] == "Cicada Test"
    assert len(ctx["last_commit"]["hash"]) >= 7
    # single-worktree repo: exactly one entry, and it must be the main one.
    assert len(ctx["worktrees"]) == 1
    assert ctx["worktrees"][0]["is_main"] is True
    assert ctx["worktrees"][0]["declared"] is False


def test_stale_hint_when_declared_default_branch_mismatches_observed(tmp_path):
    project = tmp_path / "my-project"
    _init_git_repo(project)
    # Fake an observed "origin HEAD" symref pointing at main, without needing a
    # real remote — only this ref is read, never validated.
    _git(project, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    ctx = repo_context.resolve_repo_context({"path": str(project), "default_branch": "master"})

    assert ctx["status"] == "ok"
    assert ctx["default_branch_declared"] == "master"
    assert ctx["default_branch_observed"] == "main"
    assert "master" in ctx["stale_hint"] and "main" in ctx["stale_hint"]


def test_no_stale_hint_when_declared_matches_observed(tmp_path):
    project = tmp_path / "my-project"
    _init_git_repo(project)
    _git(project, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    ctx = repo_context.resolve_repo_context({"path": str(project), "default_branch": "main"})

    assert ctx["stale_hint"] is None


def test_other_device_short_circuits_without_touching_git(tmp_path, monkeypatch):
    project = tmp_path / "my-project"
    _init_git_repo(project)  # a real, valid repo — must NOT be probed

    monkeypatch.setattr(local_refs, "current_device_id", lambda: "this-machine")

    def boom(*a, **k):
        raise AssertionError("git must not run for another device's repo")

    monkeypatch.setattr(repo_context.subprocess, "run", boom)
    ctx = repo_context.resolve_repo_context({"path": str(project), "device": "some-other-machine"})

    assert ctx["status"] == "other_device"
    assert ctx["device"] == "some-other-machine"
    assert ctx["exists"] is False
    assert ctx["is_git_repo"] is False
    assert ctx["current_branch"] is None
    assert ctx["last_commit"] is None


def test_matching_device_is_probed(tmp_path, monkeypatch):
    project = tmp_path / "my-project"
    _init_git_repo(project)
    monkeypatch.setattr(local_refs, "current_device_id", lambda: "this-machine")

    ctx = repo_context.resolve_repo_context({"path": str(project), "device": "this-machine"})

    assert ctx["status"] == "ok"
    assert ctx["current_branch"] == "main"


def test_missing_path(tmp_path):
    ctx = repo_context.resolve_repo_context({"path": str(tmp_path / "does-not-exist")})

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


def test_a_file_is_not_a_repo_and_never_raises(tmp_path):
    a_file = tmp_path / "notes.txt"
    a_file.write_text("x", encoding="utf-8")

    assert repo_context.resolve_repo_context({"path": str(a_file)})["status"] == "not_a_repo"


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


def test_no_git_binary_is_git_unavailable(tmp_path, monkeypatch):
    def _no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(repo_context.subprocess, "run", _no_git)

    assert repo_context.resolve_repo_context({"path": str(tmp_path)})["status"] == "git_unavailable"


def test_a_later_command_timing_out_drops_only_its_field(tmp_path, monkeypatch):
    project = tmp_path / "my-project"
    _init_git_repo(project)
    real_run = subprocess.run

    def slow_log(argv, *a, **k):
        if "log" in argv:
            raise subprocess.TimeoutExpired(cmd="git", timeout=2.0)
        return real_run(argv, *a, **k)

    monkeypatch.setattr(repo_context.subprocess, "run", slow_log)
    ctx = repo_context.resolve_repo_context({"path": str(project)})

    assert ctx["status"] == "ok" and ctx["current_branch"] == "main"
    assert ctx["last_commit"] is None


def test_the_runner_never_writes_the_index(tmp_path, monkeypatch):
    project = tmp_path / "my-project"
    _init_git_repo(project)
    seen: list[dict] = []
    real_run = subprocess.run

    def spy(argv, *a, **k):
        seen.append({"argv": argv, "env": k.get("env") or {}})
        return real_run(argv, *a, **k)

    monkeypatch.setattr(repo_context.subprocess, "run", spy)
    repo_context.resolve_repo_context({"path": str(project)})

    assert len(seen) == len(repo_context.REPO_COMMANDS)
    for call in seen:
        assert call["argv"][:5] == ["git", "-c", "core.fsmonitor=false", "-C", str(project)]
        assert call["env"].get("GIT_OPTIONAL_LOCKS") == "0"
        assert call["env"].get("LC_ALL") == "C"


def test_worktree_is_main_detection(tmp_path):
    project = tmp_path / "my-project"
    _init_git_repo(project)
    linked = tmp_path / "my-project-linked"
    try:
        _git(project, "worktree", "add", "-b", "feature", str(linked))
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        pytest.skip(f"git worktree add unavailable in this sandbox: {exc}")

    ctx = repo_context.resolve_repo_context({"path": str(project)})

    assert len(ctx["worktrees"]) == 2
    by_path = {w["path"]: w for w in ctx["worktrees"]}
    assert by_path[str(project)]["is_main"] is True
    assert by_path[str(linked)]["is_main"] is False
    assert by_path[str(linked)]["branch"] == "feature"

    # Querying FROM the linked worktree must agree on which one is main.
    from_linked = repo_context.resolve_repo_context({"path": str(linked)})
    by_path2 = {w["path"]: w for w in from_linked["worktrees"]}
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

    assert repo_context.resolve_repo_context({"path": str(project)})["dirty_files"] == 1


# --- 1c. parse_snapshot on recorded outputs (pure) ---------------------------

_HEAD = "0123456789abcdef0123456789abcdef01234567"
_RECORDED = {
    "inside": {"rc": 0, "stdout": "true\n"},
    "remote": {"rc": 0, "stdout": "git@example.com:alpha/alpha-project.git\n"},
    "branch": {"rc": 0, "stdout": "feat/x\n"},
    "origin_head": {"rc": 0, "stdout": "refs/remotes/origin/main\n"},
    "status": {"rc": 0, "stdout": "## feat/x...origin/feat/x [ahead 2, behind 1]\n M a.py\n?? b.txt\n"},
    "worktrees": {"rc": 0, "stdout": (
        "worktree /Users/example/src/alpha-project\nHEAD " + _HEAD + "\nbranch refs/heads/feat/x\n\n"
        "worktree /Users/example/src/alpha-wt\nHEAD " + _HEAD + "\ndetached\n\n"
    )},
    "common_dir": {"rc": 0, "stdout": "/Users/example/src/alpha-project/.git\n"},
    "last_commit": {"rc": 0, "stdout": f"{_HEAD}\x1fBob Example\x1f2026-09-20T10:00:00+02:00\x1fShip it\n"},
}


def test_parse_snapshot_reads_every_field_from_recorded_outputs():
    ctx = repo_context.parse_snapshot(_RECORDED, {"path": "~/src/alpha-project"}, this_device="mac-a")

    assert ctx["status"] == "ok" and ctx["device"] == "mac-a" and ctx["path"] == "~/src/alpha-project"
    assert ctx["remote"] == "git@example.com:alpha/alpha-project.git"
    assert ctx["current_branch"] == "feat/x"
    assert ctx["default_branch_observed"] == "main"
    assert (ctx["ahead"], ctx["behind"], ctx["dirty_files"]) == (2, 1, 2)
    assert ctx["last_commit"] == {"hash": _HEAD, "author": "Bob Example",
                                  "date": "2026-09-20T10:00:00+02:00", "subject": "Ship it"}
    by_path = {w["path"]: w for w in ctx["worktrees"]}
    assert by_path["/Users/example/src/alpha-project"]["is_main"] is True
    assert by_path["/Users/example/src/alpha-wt"] == {
        "path": "/Users/example/src/alpha-wt", "branch": None, "is_main": False, "is_dirty": None, "declared": False}


def test_the_main_worktree_is_a_string_compare_of_the_common_dir():
    outputs = dict(_RECORDED, common_dir={"rc": 0, "stdout": "/Users/example/src/alpha-wt/.git\n"})
    ctx = repo_context.parse_snapshot(outputs, {"path": "/x"}, this_device="mac-a")
    assert [w["path"] for w in ctx["worktrees"] if w["is_main"]] == ["/Users/example/src/alpha-wt"]
    # a bare repo's common dir is not named .git, and a relative one is not absolute: no main either way
    for raw in ("/srv/alpha.git\n", ".git\n"):
        bare = repo_context.parse_snapshot(dict(_RECORDED, common_dir={"rc": 0, "stdout": raw}), {"path": "/x"},
                                           this_device="mac-a")
        assert not any(w["is_main"] for w in bare["worktrees"])


def test_parse_snapshot_never_touches_the_filesystem(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the parser must not touch the filesystem")

    for name in ("resolve", "exists", "is_dir", "stat"):
        monkeypatch.setattr(Path, name, boom)
    monkeypatch.setattr(os, "scandir", boom)
    monkeypatch.setattr(os.path, "realpath", boom)
    monkeypatch.setattr(repo_context.subprocess, "run", boom)

    decl = {"path": "~/src/alpha-project", "worktrees": [{"path": "~/src/alpha-wt/"}]}
    ctx = repo_context.parse_snapshot(_RECORDED, decl, this_device="mac-a")
    assert ctx["status"] == "ok"
    assert {w["path"]: w["declared"] for w in ctx["worktrees"]} == {
        "/Users/example/src/alpha-project": False,
        "/Users/example/src/alpha-wt": os.path.expanduser("~/src/alpha-wt") == "/Users/example/src/alpha-wt",
    }


def test_a_refused_folder_is_denied():
    for msg in ("fatal: cannot change to '/Users/example/Documents/alpha': Operation not permitted\n",
                "fatal: cannot change to '/Users/example/Documents/alpha': Permission denied\n"):
        ctx = repo_context.parse_snapshot({"inside": {"rc": 128, "stdout": "", "stderr": msg}}, {"path": "/x"},
                                          this_device="mac-a")
        assert ctx["status"] == "denied" and ctx["exists"] is True and ctx["current_branch"] is None
    assert "denied" in repo_context.STATUSES


def test_a_missing_folder_and_a_plain_one_read_from_stderr():
    missing = {"inside": {"rc": 128, "stdout": "",
                          "stderr": "fatal: cannot change to '/nope': No such file or directory\n"}}
    plain = {"inside": {"rc": 128, "stdout": "",
                        "stderr": "fatal: not a git repository (or any of the parent directories): .git\n"}}
    in_git_dir = {"inside": {"rc": 0, "stdout": "false\n"}}
    assert repo_context.parse_snapshot(missing, {"path": "/nope"}, this_device="m")["status"] == "missing"
    assert repo_context.parse_snapshot(plain, {"path": "/x"}, this_device="m")["status"] == "not_a_repo"
    assert repo_context.parse_snapshot(in_git_dir, {"path": "/x"}, this_device="m")["status"] == "not_a_repo"


def test_run_errors_become_the_status():
    for error in repo_context.RUN_ERRORS:
        ctx = repo_context.parse_snapshot({}, {"path": "/x"}, error=error, this_device="m")
        assert ctx["status"] == error and ctx["exists"] is (error != "missing")


def test_other_device_ignores_whatever_was_posted():
    ctx = repo_context.parse_snapshot(_RECORDED, {"path": "/x", "device": "mac-b", "remote": "r",
                                                  "worktrees": [{"path": "/x", "primary": True}]},
                                      this_device="mac-a")
    assert ctx["status"] == "other_device" and ctx["device"] == "mac-b"
    assert ctx["current_branch"] is None and ctx["remote"] == "r"
    assert ctx["worktrees"] == [{"path": "/x", "branch": None, "is_main": True, "is_dirty": None, "declared": True}]


def test_malformed_outputs_degrade_field_by_field():
    outputs = {"inside": {"rc": 0, "stdout": "true"}, "branch": {"rc": 0, "stdout": "a\nb"},
               "status": "nope", "last_commit": {"rc": 0, "stdout": "only-two\x1fparts"},
               "worktrees": {"rc": 1, "stdout": "worktree /x"}}
    ctx = repo_context.parse_snapshot(outputs, {"path": "/x"}, this_device="m")
    assert ctx["status"] == "ok"
    assert ctx["current_branch"] is None and ctx["dirty_files"] is None
    assert ctx["last_commit"] is None and ctx["worktrees"] == []


def test_the_runner_and_the_parser_agree_on_real_git(tmp_path):
    """What the app would post (the fixture's commands, run for real) parses to
    exactly what the MCP runner reports."""
    project = tmp_path / "my-project"
    _init_git_repo(project)
    (project / "dirty.txt").write_text("x", encoding="utf-8")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}
    outputs = {}
    for c in fixture["commands"]:
        proc = subprocess.run(["git", *fixture["prefix"], "-C", str(project), *c["args"]],
                              capture_output=True, text=True, env=env)
        outputs[c["key"]] = {"rc": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    decl = {"path": str(project)}
    assert repo_context.parse_snapshot(outputs, decl) == repo_context.resolve_repo_context(decl)


# --- 2. the routes ------------------------------------------------------------


def _observed(path: str, outputs: dict | None = None, **kw) -> RepoObservation:
    return RepoObservation(path=path, outputs={k: RepoCommandOutput(**v) for k, v in (outputs or {}).items()}, **kw)


def test_get_entity_repos_serves_declarations_only(tmp_path, monkeypatch):
    memory = _init_memory(tmp_path)
    monkeypatch.setattr(local_refs, "current_device_id", lambda: "mac-a")
    _write_entity(
        memory, "alpha-project",
        {"name": "Alpha", "type": "project", "status": "active", "confidence": 0.9,
         "repos": [{"path": "~/src/alpha-project/", "device": "mac-a", "default_branch": "main",
                    "worktrees": [{"path": "~/src/alpha-wt", "branch": "feat", "primary": False}, "junk"]},
                   "not-a-dict", {"path": 42}, {"path": ""}, {"device": "mac-b"}, {"path": {"x": 1}}]},
        "A page.",
    )

    from api.routers import entities as entities_router

    def boom(*a, **k):
        raise AssertionError("GET must not run git")

    monkeypatch.setattr(repo_context, "run_repo_commands", boom)
    resp = run(entities_router.get_entity_repos("alpha-project", settings=_Settings(memory)))

    assert resp.entity_id == "alpha-project" and resp.this_device == "mac-a"
    assert [r.path for r in resp.repos] == ["~/src/alpha-project/", "42"], "the path exactly as written"
    first = resp.repos[0]
    assert first.device == "mac-a" and first.default_branch == "main"
    assert [(w.path, w.branch) for w in first.worktrees] == [("~/src/alpha-wt", "feat")]


def test_get_entity_repos_empty_when_no_repos_key(tmp_path):
    memory = _init_memory(tmp_path)
    _write_entity(memory, "no-repos", {"name": "No Repos", "type": "project", "status": "active",
                                       "confidence": 0.5}, "Nothing declared.")

    from api.routers import entities as entities_router

    assert run(entities_router.get_entity_repos("no-repos", settings=_Settings(memory))).repos == []


def test_get_entity_repos_404_when_entity_missing(tmp_path):
    memory = _init_memory(tmp_path)

    from api.routers import entities as entities_router

    with pytest.raises(HTTPException) as exc_info:
        run(entities_router.get_entity_repos("ghost", settings=_Settings(memory)))
    assert exc_info.value.status_code == 404


def test_post_observed_parses_and_keeps_only_a_summary_outside_the_bank(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CICADA_HOME", str(home))
    monkeypatch.setattr(local_refs, "current_device_id", lambda: "mac-a")
    memory = _init_memory(tmp_path)
    _write_entity(memory, "alpha-project",
                  {"name": "Alpha", "type": "project", "status": "active", "confidence": 0.9,
                   "repos": [{"path": "~/src/alpha-project"}, {"path": "~/src/beta", "device": "mac-b"}]},
                  "A page.")

    from api.routers import entities as entities_router

    request = RepoObservedRequest(repos=[_observed("~/src/alpha-project", _RECORDED),
                                         _observed("~/src/beta", _RECORDED, device="mac-b")])
    resp = run(entities_router.post_entity_repos_observed("alpha-project", request, settings=_Settings(memory)))

    alpha, beta = resp.repos
    assert alpha.status == "ok" and alpha.current_branch == "feat/x" and alpha.device == "mac-a"
    assert alpha.last_commit.subject == "Ship it" and len(alpha.worktrees) == 2
    assert beta.status == "other_device" and beta.current_branch is None

    kept = json.loads((home / "repos" / "memory.json").read_text(encoding="utf-8"))["observations"]
    assert len(kept) == 1, "another device's repo is not kept"
    row = kept[0]
    assert set(row) == {"path", "device", "status", "branch", "dirty", "ahead", "behind", "observed_at"}
    assert (row["path"], row["device"], row["branch"], row["dirty"], row["ahead"], row["behind"]) == (
        "~/src/alpha-project", "mac-a", "feat/x", 2, 2, 1)
    assert "Ship it" not in json.dumps(kept) and "example.com" not in json.dumps(kept)
    assert not list((memory).rglob("*.json")), "nothing lands in the bank"


def test_post_observed_refuses_a_path_the_page_does_not_declare(tmp_path):
    memory = _init_memory(tmp_path)
    _write_entity(memory, "alpha-project", {"name": "Alpha", "type": "project",
                                            "repos": [{"path": "~/src/alpha-project"}]}, "A page.")

    from api.routers import entities as entities_router

    for path in ("~/src/other", "/Users/example/src/alpha-project", "~/src/alpha-project/"):
        request = RepoObservedRequest(repos=[_observed(path, _RECORDED)])
        with pytest.raises(HTTPException) as exc_info:
            run(entities_router.post_entity_repos_observed("alpha-project", request, settings=_Settings(memory)))
        assert exc_info.value.status_code == 422


def test_post_observed_refuses_unknown_keys_and_a_missing_first_answer(tmp_path):
    memory = _init_memory(tmp_path)
    _write_entity(memory, "alpha-project", {"name": "Alpha", "type": "project",
                                            "repos": [{"path": "~/src/alpha-project"}]}, "A page.")

    from api.routers import entities as entities_router

    for outputs in ({"inside": {"rc": 0, "stdout": "true"}, "cat": {"rc": 0, "stdout": "secret"}},
                    {"branch": {"rc": 0, "stdout": "main"}}):
        request = RepoObservedRequest(repos=[_observed("~/src/alpha-project", outputs)])
        with pytest.raises(HTTPException) as exc_info:
            run(entities_router.post_entity_repos_observed("alpha-project", request, settings=_Settings(memory)))
        assert exc_info.value.status_code == 422
    ok = RepoObservedRequest(repos=[_observed("~/src/alpha-project", error="git_unavailable")])
    resp = run(entities_router.post_entity_repos_observed("alpha-project", ok, settings=_Settings(memory)))
    assert resp.repos[0].status == "git_unavailable"


def test_the_observed_body_is_bounded():
    with pytest.raises(ValidationError):
        RepoCommandOutput(rc=0, stdout="x" * (64 * 1024 + 1))
    with pytest.raises(ValidationError):
        RepoCommandOutput(rc="zero", stdout="")
    with pytest.raises(ValidationError):
        RepoObservedRequest(repos=[_observed("/x", error="git_unavailable")] * 51)
    with pytest.raises(ValidationError):
        RepoObservation(path="/x", error="exploded")


def test_patch_entity_repos_writes_frontmatter_and_commits(tmp_path, monkeypatch):
    memory = _init_memory(tmp_path)
    entity_path = _write_entity(memory, "cicada",
                                {"name": "Cicada", "type": "project", "status": "active", "confidence": 0.9},
                                "The capstone project.")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")

    from api.routers import entities as entities_router

    def boom(*a, **k):
        raise AssertionError("PATCH must not probe the declared repo")

    monkeypatch.setattr(repo_context, "run_repo_commands", boom)
    request = RepoUpdateRequest(repos=[RepoInput(path="~/src/alpha-project", default_branch="main")])
    resp = run(entities_router.update_entity_repos("cicada", request, settings=_Settings(memory)))

    assert [(r.path, r.default_branch) for r in resp.repos] == [("~/src/alpha-project", "main")]
    parsed = markdown_parser.parse(entity_path)
    assert parsed.frontmatter["repos"] == [{"path": "~/src/alpha-project", "default_branch": "main"}]
    # Other frontmatter keys + body untouched.
    assert parsed.frontmatter["name"] == "Cicada"
    assert parsed.body == "The capstone project."

    log = _git(memory, "log", "-1", "--format=%s%n%b")
    assert "trigger: user/companion_app" in log
    assert "Cicada-Author: user" in log


def test_patch_entity_repos_empty_list_removes_key(tmp_path):
    memory = _init_memory(tmp_path)
    entity_path = _write_entity(memory, "cicada",
                                {"name": "Cicada", "type": "project", "status": "active", "confidence": 0.9,
                                 "repos": [{"path": "/some/path"}]},
                                "The capstone project.")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")

    from api.routers import entities as entities_router

    resp = run(entities_router.update_entity_repos("cicada", RepoUpdateRequest(repos=[]),
                                                   settings=_Settings(memory)))

    assert resp.repos == []
    assert "repos" not in markdown_parser.parse(entity_path).frontmatter


def test_patch_entity_repos_404_when_entity_missing(tmp_path):
    memory = _init_memory(tmp_path)

    from api.routers import entities as entities_router

    with pytest.raises(HTTPException) as exc_info:
        run(entities_router.update_entity_repos("ghost", RepoUpdateRequest(repos=[]), settings=_Settings(memory)))
    assert exc_info.value.status_code == 404


# --- 2b. the observation cache -------------------------------------------------


def test_the_cache_read_never_creates_the_folder(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CICADA_HOME", str(home))
    assert repo_observations.read(tmp_path / "memory") == []
    lookup = repo_observations.resolver(tmp_path / "memory")
    assert lookup({"path": "~/src/alpha-project"})["status"] == "unavailable"
    assert not home.exists()


def test_the_cache_validates_what_it_keeps(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = tmp_path / "memory"
    from datetime import datetime, timezone

    now = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
    kept = repo_observations.record(memory, [
        {"path": "/a", "device": "mac-a", "status": "ok", "current_branch": "x" * 256, "dirty_files": -1,
         "ahead": True, "behind": 3},
        {"path": "/b", "device": "mac-a", "status": "exploded"},
        {"path": "/c", "device": "mac-b", "status": "other_device"},
        {"path": "/d", "device": "mac-a", "status": "denied"},
    ], now=now)
    assert kept == 2
    rows = {r["path"]: r for r in repo_observations.read(memory)}
    assert set(rows) == {"/a", "/d"}
    assert (rows["/a"]["branch"], rows["/a"]["dirty"], rows["/a"]["ahead"], rows["/a"]["behind"]) == (None, None, None, 3)
    assert rows["/d"]["status"] == "denied" and rows["/a"]["observed_at"] == now.isoformat()


def test_the_cache_upserts_by_path_and_device(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(local_refs, "current_device_id", lambda: "mac-a")
    memory = tmp_path / "memory"
    from datetime import datetime, timedelta, timezone

    t0 = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
    repo_observations.record(memory, [{"path": "/a", "device": "mac-a", "status": "ok", "current_branch": "one"}],
                             now=t0)
    repo_observations.record(memory, [{"path": "/a", "device": "mac-a", "status": "ok", "current_branch": "two"}],
                             now=t0 + timedelta(hours=1))
    assert [r["branch"] for r in repo_observations.read(memory)] == ["two"]
    got = repo_observations.resolver(memory)({"path": "/a"})
    assert got["current_branch"] == "two" and got["observed_at"] == t0 + timedelta(hours=1)
    assert repo_observations.resolver(memory)({"path": "/a", "device": "mac-b"})["status"] == "other_device"
    assert not list((tmp_path / "home" / "repos").glob(".repos-*")), "no temp file is left behind"


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


def test_a_friendly_device_name_or_this_macs_computer_name_is_this_mac(tmp_path, monkeypatch):
    """Device drift: a page that says `device: Mac`, or names this Mac by its computer
    name, is observed here — never `other_device` forever."""
    memory = _init_memory(tmp_path)
    monkeypatch.setattr(local_refs, "current_device_id", lambda: "mac-a.local")
    monkeypatch.setattr(local_refs, "this_device_names", lambda: frozenset({"maca", "alexsmacbookpro"}))
    _write_entity(
        memory, "alpha-project",
        {"name": "Alpha", "type": "project", "status": "active", "confidence": 0.9,
         "repos": [{"path": "~/src/a", "device": "Mac"}, {"path": "~/src/b", "device": "Alex's MacBook Pro"},
                   {"path": "~/src/c", "device": "MAC-A"}, {"path": "~/src/d", "device": "mac-b"},
                   {"path": "~/src/e"}]},
        "A page.",
    )
    from api.routers import entities as entities_router

    resp = run(entities_router.get_entity_repos("alpha-project", settings=_Settings(memory)))
    assert [(r.path, r.on_this_device) for r in resp.repos] == [
        ("~/src/a", True), ("~/src/b", True), ("~/src/c", True), ("~/src/d", False), ("~/src/e", True)]
    for decl in ({"path": "/x", "device": "Mac"}, {"path": "/x", "device": "Alex's MacBook Pro"}):
        assert not repo_context.is_other_device(decl)
        assert repo_context.parse_snapshot({}, decl, error="missing")["status"] == "missing"
    assert repo_context.is_other_device({"path": "/x", "device": "mac-b"})
