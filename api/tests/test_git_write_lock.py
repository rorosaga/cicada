"""F2-back R-B1 … R-B4 — one git writer per bank, git's own index lock waited
out and never deleted, readers that never take it, and a lint that keeps every
mutating git command inside `git_service`."""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import pytest

from api.services import git_service

REPO = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path: Path) -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "test@example.com")
    _git(bank, "config", "user.name", "Cicada Test")
    (bank / "seed.md").write_text("seed\n", encoding="utf-8")
    _git(bank, "add", "seed.md")
    _git(bank, "commit", "-q", "-m", "seed")
    return bank


def _message(i: int, author: str) -> str:
    return git_service.build_commit_message(
        f"Write {i}", [f"entities/page-{i}.md: updated (trigger: test)"], authors=[author])


def _write_pages(bank: Path, n: int) -> None:
    for i in range(n):
        (bank / "entities" / f"page-{i}.md").write_text(f"page {i}\n", encoding="utf-8")


def _author_of(bank: Path, rel: str) -> str:
    return _git(bank, "log", "-1", "--format=%(trailers:key=Cicada-Author,valueonly)", "--", rel).strip()


# --- R-B1 / R-B4: one writer at a time ----------------------------------------


def test_concurrent_async_writers_all_land_under_their_own_authors(bank):
    """The incident, reproduced: eight tasks on one bank failed 5 of 5 trials with
    `index.lock: File exists` and left 6–7 pages dirty for the next `git add -A`."""
    _write_pages(bank, 8)

    async def one(i):
        await git_service.commit_paths(bank, _message(i, f"writer-{i}"), [f"entities/page-{i}.md"])

    async def all_writers():
        await asyncio.gather(*(one(i) for i in range(8)))

    asyncio.run(all_writers())
    assert _git(bank, "status", "--porcelain") == ""
    for i in range(8):
        assert _author_of(bank, f"entities/page-{i}.md") == f"writer-{i}"


def test_threads_bridges_and_tasks_queue_on_the_same_lock(bank):
    """Sync callers (migrations), `asyncio.run` bridges on threads (agent commits,
    calendar polls, the demo bank) and loop tasks are all one queue."""
    _write_pages(bank, 6)
    errors: list[BaseException] = []

    def in_thread(i):
        try:
            git_service.commit_paths_sync(bank, _message(i, f"thread-{i}"), [f"entities/page-{i}.md"])
        except BaseException as exc:  # noqa: BLE001 — surfaced by the assert below
            errors.append(exc)

    def bridged(i):
        try:
            asyncio.run(git_service.commit_paths(bank, _message(i, f"bridge-{i}"), [f"entities/page-{i}.md"]))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    workers = [threading.Thread(target=in_thread, args=(i,)) for i in (0, 1)]
    workers += [threading.Thread(target=bridged, args=(i,)) for i in (2, 3)]
    for w in workers:
        w.start()

    async def tasks():
        await asyncio.gather(*(git_service.commit_paths(bank, _message(i, f"task-{i}"), [f"entities/page-{i}.md"])
                               for i in (4, 5)))

    asyncio.run(tasks())
    for w in workers:
        w.join()
    assert errors == []
    assert _git(bank, "status", "--porcelain") == ""
    assert [_author_of(bank, f"entities/page-{i}.md") for i in range(6)] == [
        "thread-0", "thread-1", "bridge-2", "bridge-3", "task-4", "task-5"]


def test_one_writers_sequence_never_interleaves_with_another(bank, monkeypatch):
    """R-B4: the lock covers add → status → commit, so a `status` check and its
    commit can never straddle another writer's `add`."""
    _write_pages(bank, 2)
    order: list[int] = []
    real = git_service._spawn

    def slow(memory_path, args):
        order.append(threading.get_ident())
        time.sleep(0.02)
        return real(memory_path, args)

    monkeypatch.setattr(git_service, "_spawn", slow)
    workers = [threading.Thread(target=git_service.commit_paths_sync,
                                args=(bank, _message(i, f"w-{i}"), [f"entities/page-{i}.md"]))
               for i in range(2)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    assert len(order) == 6
    assert sum(1 for a, b in zip(order, order[1:]) if a != b) == 1, order
    assert _git(bank, "status", "--porcelain") == ""


def test_the_lock_is_one_per_resolved_bank(bank, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(bank)
    assert git_service.write_lock(bank) is git_service.write_lock(f"{bank}/")
    assert git_service.write_lock(bank) is git_service.write_lock(alias)
    assert git_service.write_lock(bank) is not git_service.write_lock(tmp_path)


def test_commit_changes_still_returns_the_new_head_or_none(bank):
    _write_pages(bank, 1)
    head = asyncio.run(git_service.commit_changes(bank, _message(0, "writer-0")))
    assert head == _git(bank, "rev-parse", "HEAD").strip()
    assert asyncio.run(git_service.commit_changes(bank, "nothing to say")) is None


# --- R-B2: another process's index lock ---------------------------------------


def test_an_external_index_lock_is_waited_out_and_never_deleted(bank, monkeypatch):
    """The owner's terminal holds the index for a moment: the writer waits, and
    the lock is removed by the process that owns it — never by Cicada."""
    _write_pages(bank, 1)
    lock = bank / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    waits: list[float] = []

    def the_other_git_finishes(delay):
        waits.append(delay)
        lock.unlink()

    monkeypatch.setattr(git_service, "_sleep", the_other_git_finishes)
    git_service.commit_paths_sync(bank, _message(0, "writer-0"), ["entities/page-0.md"])
    assert waits == [git_service.INDEX_LOCK_BACKOFF_S[0]]
    assert _author_of(bank, "entities/page-0.md") == "writer-0"


def test_a_lock_that_stays_fails_after_five_tries_and_is_left_in_place(bank, monkeypatch):
    _write_pages(bank, 1)
    lock = bank / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    waits: list[float] = []
    monkeypatch.setattr(git_service, "_sleep", waits.append)
    with pytest.raises(git_service.GitError, match="index.lock"):
        git_service.commit_paths_sync(bank, _message(0, "writer-0"), ["entities/page-0.md"])
    assert waits == list(git_service.INDEX_LOCK_BACKOFF_S), "five tries, four waits"
    assert lock.exists(), "Cicada never deletes another process's index lock"
    lock.unlink()
    # `--untracked-files=all`: the page was never added, and plain porcelain folds a
    # wholly-untracked directory into `?? entities/`.
    assert "entities/page-0.md" in _git(bank, "status", "--porcelain", "--untracked-files=all")


def test_only_the_index_lock_refusal_is_retried(bank, monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(git_service, "_sleep", waits.append)
    with pytest.raises(git_service.GitError):
        git_service.commit_paths_sync(bank, "x", ["entities/does-not-exist.md"])
    assert waits == []


# --- R-B3: readers ------------------------------------------------------------


def test_a_read_never_takes_gits_optional_index_lock(bank, monkeypatch):
    seen: dict = {}
    real = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        seen["env"] = kwargs.get("env")
        return await real(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    asyncio.run(git_service._run_git(bank, "status", "--porcelain"))
    assert seen["env"]["GIT_OPTIONAL_LOCKS"] == "0"


def test_a_write_through_run_git_takes_the_bank_lock_and_a_read_does_not(bank, monkeypatch):
    """`inbox_service`'s `git mv` / `git rm` go through `_run_git`: they queue too."""
    calls: list[tuple] = []
    monkeypatch.setattr(git_service, "run_git_write_sync", lambda path, *args: calls.append(args) or "")
    asyncio.run(git_service._run_git(bank, "rm", "-f", "seed.md"))
    asyncio.run(git_service._run_git(bank, "log", "-1"))
    assert calls == [("rm", "-f", "seed.md")]


# --- The lint (R-B1's durable half) -------------------------------------------

_WRITE_LITERAL = re.compile(
    r"""["']git["']\s*,\s*(?:["']-C["']\s*,\s*[^,\]]+,\s*)?["']("""
    + "|".join(sorted(re.escape(s) for s in git_service.WRITE_SUBCOMMANDS))
    + r""")["']""")


def _python_files():
    for root in (REPO / "api", REPO / "mcp"):
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in {".venv", "tests", "__pycache__"}]
            for name in filenames:
                if name.endswith(".py"):
                    yield Path(dirpath) / name


def test_the_lint_catches_what_it_is_for():
    assert _WRITE_LITERAL.search('subprocess.run(["git", "add", "--", *rel], cwd=x)')
    assert _WRITE_LITERAL.search("run(['git', '-C', str(bank), 'commit', '-m', m])")
    assert not _WRITE_LITERAL.search('subprocess.run(["git", "init"], cwd=x)')
    assert not _WRITE_LITERAL.search('subprocess.run(["git", *args], cwd=x)')


def test_no_module_spawns_a_git_write_outside_git_service():
    """A writer that spawns `git add`/`commit`/`rm`/… itself bypasses the one lock,
    as the seven migrations and the expiry restore did before this track."""
    hits = [str(p.relative_to(REPO)) for p in _python_files()
            if p.name != "git_service.py" and _WRITE_LITERAL.search(p.read_text(encoding="utf-8"))]
    assert hits == []
