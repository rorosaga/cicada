"""F2-back R-B5 — a folder, paper or Wispr commit that git refuses keeps its
paths, says so on its channel, and lands on the same writer's next run (or at
the start of the next Sleep cycle) under its own author."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.services import folder_source as fs, git_service, sync_state


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path, monkeypatch):
    bank = tmp_path / "bank"
    for sub in ("entities", "episodes", "sources"):
        (bank / sub).mkdir(parents=True)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "test@example.com")
    _git(bank, "config", "user.name", "Cicada Test")
    (bank / "seed.md").write_text("seed\n", encoding="utf-8")
    _git(bank, "add", "seed.md")
    _git(bank, "commit", "-q", "-m", "seed")
    monkeypatch.setattr(git_service, "_sleep", lambda _delay: None)
    return bank


def _page(bank: Path, stem: str) -> str:
    (bank / "entities" / f"{stem}.md").write_text(f"{stem}\n", encoding="utf-8")
    return f"entities/{stem}.md"


def _papers_commit(bank: Path, paths: list[str]) -> bool:
    return asyncio.run(fs.commit_paths_for(bank, paths, subject="Paper details", trigger="papers/metadata",
                                           author="cicada", channel="papers"))


def _fail_once(bank: Path, rel: str) -> None:
    lock = bank / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    assert _papers_commit(bank, [rel]) is False
    lock.unlink()  # the other process finishes; it removes its own lock


def test_a_refused_commit_keeps_its_paths_and_says_so(bank):
    rel = _page(bank, "media-arxiv-2401-00001")
    lock = bank / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    assert _papers_commit(bank, [rel]) is False
    assert lock.exists()
    (entry,) = fs.pending_commits(bank).values()
    assert entry["paths"] == [rel]
    assert (entry["trigger"], entry["author"], entry["channel"]) == ("papers/metadata", "cicada", "papers")
    assert sync_state.read_sync_state(bank)["papers"]["last_error"] == fs.COMMIT_FAILED_MESSAGE


def test_the_ledger_lives_in_the_git_dir_never_in_the_tree(bank):
    _fail_once(bank, _page(bank, "media-arxiv-2401-00001"))
    assert (bank / ".git" / fs.PENDING_COMMITS_FILENAME).is_file()
    assert fs.PENDING_COMMITS_FILENAME not in _git(bank, "status", "--porcelain", "--untracked-files=all")


def test_the_same_writers_next_run_lands_them_under_its_own_author(bank):
    kept = _page(bank, "media-arxiv-2401-00001")
    _fail_once(bank, kept)
    fresh = _page(bank, "media-arxiv-2401-00002")
    assert _papers_commit(bank, [fresh]) is True
    assert fs.pending_commits(bank) == {}
    # Scoped to `entities`: `record_error` / `clear_error` write `sync_state.json` in
    # the bank root, which this fixture never committed (it shows as `??`).
    assert _git(bank, "status", "--porcelain", "--", "entities") == ""
    body = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: cicada" in body and kept in body and fresh in body
    assert "last_error" not in sync_state.read_sync_state(bank)["papers"]


def test_another_writer_never_takes_them(bank):
    kept = _page(bank, "media-arxiv-2401-00001")
    _fail_once(bank, kept)
    mine = _page(bank, "alpha-project")
    assert asyncio.run(fs.commit_paths_for(bank, [mine], subject="Folder sync (alpha-project)",
                                           trigger="folder/sync", author="user",
                                           channel="folder:alpha-project-abc123")) is True
    assert kept in _git(bank, "status", "--porcelain")
    assert [e["paths"] for e in fs.pending_commits(bank).values()] == [[kept]]


def test_overlapping_runs_of_one_writer_never_erase_each_others_kept_paths(bank):
    """R-B5: the ledger is edited by path. A run that lands drops only what it
    committed; a path another run of the same writer kept stays kept."""
    first = _page(bank, "media-arxiv-2401-00001")
    second = _page(bank, "media-arxiv-2401-00002")
    key = "papers/metadata|cicada|papers"
    fs._update_pending(bank, key, add=[first, second],
                       meta={"subject": "Paper details", "trigger": "papers/metadata",
                             "author": "cicada", "channel": "papers"})
    fs._update_pending(bank, key, drop=[first])
    assert fs.pending_commits(bank)[key]["paths"] == [second]
    fs._update_pending(bank, key, drop=[second])
    assert fs.pending_commits(bank) == {}
    assert not (bank / ".git" / fs.PENDING_COMMITS_FILENAME).exists()


def test_a_worktree_banks_ledger_is_its_own_not_the_common_dirs(tmp_path):
    """`bank_registry.git_dir` is this checkout's git dir, never the common dir
    `_git_dir` follows for `info/exclude`: two worktree banks share that one."""
    from api.services import bank_registry

    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q")
    _git(main, "config", "user.email", "test@example.com")
    _git(main, "config", "user.name", "Cicada Test")
    (main / "seed.md").write_text("seed\n", encoding="utf-8")
    _git(main, "add", "seed.md")
    _git(main, "commit", "-q", "-m", "seed")
    _git(main, "worktree", "add", "-q", str(tmp_path / "other"))
    own = bank_registry.git_dir(tmp_path / "other")
    assert own is not None and own != bank_registry.git_dir(main)
    assert own.parent.name == "worktrees", own


def test_a_flush_lands_every_kept_writer_under_its_own_author(bank):
    _fail_once(bank, _page(bank, "media-arxiv-2401-00001"))
    assert asyncio.run(fs.flush_pending_commits(bank)) == 1
    assert "Cicada-Author: cicada" in _git(bank, "log", "-1", "--format=%B")
    assert fs.pending_commits(bank) == {}


def test_a_sleep_cycle_flushes_before_any_stage_writes(monkeypatch, tmp_path):
    """`_finalize`'s `git add -A` is the sweeper this exists to beat."""
    from api.services import sleep_cycle

    order: list[str] = []

    async def flush(memory_path):
        order.append("flush")
        return 0

    async def stages(*_a, **_k):
        order.append("stages")
        return sleep_cycle._StageOutcome()

    async def tail(*_a, **_k):
        order.append("tail")

    monkeypatch.setattr(fs, "flush_pending_commits", flush)
    monkeypatch.setattr(sleep_cycle, "_run_stages", stages)
    monkeypatch.setattr(sleep_cycle, "_run_engine_independent_tail", tail)
    asyncio.run(sleep_cycle.run(SimpleNamespace(memory_path=tmp_path), "cycle-f2b"))
    assert order == ["flush", "stages", "tail"]


def test_a_bank_without_its_own_git_commits_and_records_nothing(tmp_path):
    bank = tmp_path / "plain"
    (bank / "entities").mkdir(parents=True)
    assert _papers_commit(bank, [_page(bank, "alpha-project")]) is True
    assert fs.pending_commits(bank) == {}
    assert sync_state.read_sync_state(bank) == {}


def test_a_paper_run_whose_commit_failed_never_stamps_success(bank, monkeypatch):
    from api.services import paper_metadata as pm

    async def refused(memory_path, paths, **kw):
        sync_state.record_error(memory_path, kw["channel"], fs.COMMIT_FAILED_MESSAGE)
        return False

    async def resolve(memory_path, *, report, **kw):
        report["resolved"] = 1

    monkeypatch.setattr(fs, "commit_paths_for", refused)
    monkeypatch.setattr(pm, "resolve", resolve)
    asyncio.run(pm.run_locked(bank))
    assert sync_state.read_sync_state(bank)["papers"]["last_error"] == fs.COMMIT_FAILED_MESSAGE


def test_clear_error_drops_only_the_error_it_names(tmp_path):
    sync_state.record_error(tmp_path, "papers", "Crossref HTTP 503")
    sync_state.clear_error(tmp_path, "papers", fs.COMMIT_FAILED_MESSAGE)
    assert sync_state.read_sync_state(tmp_path)["papers"]["last_error"] == "Crossref HTTP 503"
    sync_state.record_error(tmp_path, "papers", fs.COMMIT_FAILED_MESSAGE)
    sync_state.clear_error(tmp_path, "papers", fs.COMMIT_FAILED_MESSAGE)
    assert "last_error" not in sync_state.read_sync_state(tmp_path)["papers"]
