"""G132 phase 1 B — the replica's apply (ruling 51a/e2): the first copy from a bundle, then fast-forwards only — the
ancestry checked by the copy itself, a dirty copy refused, every file written atomically, nothing committed by the
copy, the caches and the words index caught up, the meaning index from the changed episode stems only; and the guard
lets nothing else write. Synthetic banks only."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from _sync_home import git, hand_commit
from _synthetic_bank import _bank
from api.services import git_service, markdown_parser, replica, replica_guard


@pytest.fixture
def pair(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    home = _bank(tmp_path)
    return home, tmp_path


def _bundle(home: Path, out: Path, have: str | None = None) -> Path:
    args = ["git", "bundle", "create", "-q", str(out), "HEAD"] + ([f"^{have}"] if have else [])
    subprocess.run(args, cwd=str(home), check=True, capture_output=True)
    return out


def _copy(home: Path, tmp: Path) -> Path:
    target = tmp / "replica-root" / "banks" / "memory"
    with replica_guard.applying():
        git_service.bootstrap_from_bundle_sync(target, _bundle(home, tmp / "full.bundle"))
    return target


def test_a_first_copy_then_fast_forwards_and_the_copy_never_commits(pair):
    home, tmp = pair
    copy = _copy(home, tmp)
    assert git(copy, "rev-parse", "HEAD") == git(home, "rev-parse", "HEAD")
    assert (copy / "entities" / "alpha-project.md").read_bytes() == (home / "entities" / "alpha-project.md").read_bytes()
    old = git(copy, "rev-parse", "HEAD").strip()
    hand_commit(home, "entities/new-page.md", "new\n")
    hand_commit(home, "entities/beta-project.md", "rewritten\n")
    git(home, "rm", "-q", "entities/gamma-project.md")
    git(home, "commit", "-q", "-m", "remove")
    with replica_guard.applying():
        out = git_service.fast_forward_sync(copy, _bundle(home, tmp / "ff.bundle", have=old))
    assert out["old"] == old and out["head"] == git(home, "rev-parse", "HEAD").strip()
    assert set(out["changed"]) == {"entities/new-page.md", "entities/beta-project.md"}
    assert out["removed"] == ["entities/gamma-project.md"] and not (copy / "entities" / "gamma-project.md").exists()
    assert (copy / "entities" / "beta-project.md").read_text() == "rewritten\n"
    assert git(copy, "status", "--porcelain") == ""
    # The copy made no commit of its own: its history is the home's, commit for commit.
    assert git(copy, "log", "--format=%H") == git(home, "log", "--format=%H")


def test_a_head_that_does_not_descend_from_the_copy_is_refused(pair):
    home, tmp = pair
    copy = _copy(home, tmp)
    git(home, "commit", "-q", "--amend", "-m", "rewritten by hand")
    before = git(copy, "rev-parse", "HEAD")
    with replica_guard.applying(), pytest.raises(git_service.NotFastForward):
        git_service.fast_forward_sync(copy, _bundle(home, tmp / "rw.bundle"))
    assert git(copy, "rev-parse", "HEAD") == before
    # Only the person's "copy again" writes the home's tree over the copy.
    with replica_guard.applying():
        out = git_service.fast_forward_sync(copy, _bundle(home, tmp / "rw2.bundle"), rewrite=True)
    assert out["head"] == git(home, "rev-parse", "HEAD").strip() and git(copy, "status", "--porcelain") == ""


def test_a_dirty_copy_is_never_overwritten(pair):
    home, tmp = pair
    copy = _copy(home, tmp)
    old = git(copy, "rev-parse", "HEAD").strip()
    (copy / "entities" / "alpha-project.md").write_text("changed outside the apply\n")
    hand_commit(home, "entities/alpha-project.md", "home's\n")
    with replica_guard.applying(), pytest.raises(git_service.DirtyCopy):
        git_service.fast_forward_sync(copy, _bundle(home, tmp / "d.bundle", have=old))
    assert (copy / "entities" / "alpha-project.md").read_text() == "changed outside the apply\n"


def test_every_file_is_written_atomically(pair, monkeypatch):
    home, tmp = pair
    copy = _copy(home, tmp)
    old = git(copy, "rev-parse", "HEAD").strip()
    for i in range(5):
        hand_commit(home, f"entities/page-{i}.md", f"page {i}\n" * 200)
    replaced, opened = [], []
    real_replace, real_open = os.replace, open

    def spy_replace(src, dst, *a, **k):
        replaced.append(Path(dst).name)
        return real_replace(src, dst, *a, **k)

    def spy_open(file, mode="r", *a, **k):
        if "w" in str(mode):
            opened.append(Path(file).name)
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(git_service.os, "replace", spy_replace)
    monkeypatch.setattr("builtins.open", spy_open)
    with replica_guard.applying():
        git_service.fast_forward_sync(copy, _bundle(home, tmp / "a.bundle", have=old))
    names = {f"page-{i}.md" for i in range(5)}
    assert names <= set(replaced)
    assert not (names & set(opened))        # never opened for writing in place: a temp file beside it, then replaced


def test_on_a_replica_nothing_but_the_apply_writes(pair, monkeypatch):
    home, tmp = pair
    copy = _copy(home, tmp)
    monkeypatch.setenv("CICADA_REPLICA_OF", "https://home.example.ts.net")
    assert replica_guard.active()
    with pytest.raises(replica_guard.ReplicaReadOnly):
        markdown_parser.write(copy / "entities" / "x.md", {"name": "X"}, "x")
    with pytest.raises(replica_guard.ReplicaReadOnly):
        markdown_parser.write_new(copy / "entities" / "y.md", {"name": "Y"}, "y")
    from api.services import episode_ids, state_dictionary

    with pytest.raises(replica_guard.ReplicaReadOnly):
        episode_ids.create_episode(copy / "episodes", {"id": "ep_2026-10-29_001", "timestamp": "2026-10-29T09:00:00Z"},
                                   "user: x")
    (copy / "entities" / "z.md").write_text("z\n")
    with pytest.raises(git_service.GitError) as refused:
        git_service.commit_paths_sync(copy, "write", ["entities/z.md"])
    assert isinstance(refused.value, replica_guard.ReplicaReadOnly)
    assert state_dictionary.refresh(copy)["reason"] == "replica"
    assert not (copy / "_state.md").exists() or git(copy, "status", "--porcelain", "--", "_state.md") == ""
    # The capture writer is refused too (Awake capture on a copy goes to the home instead).
    from api.services import transcript_capture as tc

    with pytest.raises(replica_guard.ReplicaReadOnly):
        tc.capture_posted(copy, harness="claude-code", session_id="11111111-2222-4333-8444-555555555555",
                          conversation={"kept": [{"role": "user", "text": "x"}], "gap": None, "summary": {}},
                          transcript_bytes=10, transcript_size=10, cwd="/home/example/a", keep_assistant=True)
    (copy / "entities" / "z.md").unlink()
    # The apply itself still writes.
    old = git(copy, "rev-parse", "HEAD").strip()
    hand_commit(home, "entities/new.md", "new\n")
    with replica_guard.applying():
        git_service.fast_forward_sync(copy, _bundle(home, tmp / "g.bundle", have=old))
    assert (copy / "entities" / "new.md").exists()


def test_the_caches_and_indexes_catch_up_and_vectors_take_only_changed_stems(pair, monkeypatch):
    from api.services import bank_index, search_index

    home, tmp = pair
    copy = _copy(home, tmp)
    search_index.ensure_fresh(copy, wait=True)
    assert len(bank_index.files(copy, "episodes")) == 2
    old = git(copy, "rev-parse", "HEAD").strip()
    hand_commit(home, "episodes/ep_2026-09-03_001.md",
                "---\nid: ep_2026-09-03_001\ntimestamp: '2026-09-03T09:00:00+00:00'\nprocessed: false\n---\n"
                "user: the zanzibarish launch\n")
    seen = []

    class FakeIndexer:
        def __init__(self, path, **kw):
            pass

        def index_episode_stems(self, stems):
            seen.append(list(stems))

    import api.services.vector_index as vi

    monkeypatch.setattr(vi, "SqliteVecIndexer", FakeIndexer)
    with replica_guard.applying():
        out = git_service.fast_forward_sync(copy, _bundle(home, tmp / "i.bundle", have=old))
    replica._index_after(copy, changed=out["changed"])
    for t in list(__import__("threading").enumerate()):
        if t.name == "cicada-replica-vectors":
            t.join(10)
    assert len(bank_index.files(copy, "episodes")) == 3
    assert search_index.ensure_fresh(copy) == "ready"
    import sqlite3

    db = sqlite3.connect(search_index.db_path(copy))
    assert db.execute("SELECT count(*) FROM docs WHERE ref = 'ep_2026-09-03_001'").fetchone()[0] >= 1
    assert seen == [["ep_2026-09-03_001"]]


@pytest.mark.parametrize("cut_at", ["update-ref", "reset"])
def test_an_apply_cut_short_is_finished_by_the_next_one(pair, monkeypatch, cut_at):
    """Review of #566: the process dies (or git refuses) after the files are written but before HEAD moved, or before
    the index followed. The journal says so; the next apply finishes it — never a dirty copy, never `diverged`."""
    home, tmp = pair
    copy = _copy(home, tmp)
    old = git(copy, "rev-parse", "HEAD").strip()
    first = hand_commit(home, "entities/alpha-project.md", "the home's change\n")
    real = git_service._git_sync

    def dies(memory_path, *args):
        if args and args[0] == cut_at:
            raise git_service.GitError(f"{cut_at} cut short")
        return real(memory_path, *args)

    monkeypatch.setattr(git_service, "_git_sync", dies)
    with replica_guard.applying(), pytest.raises(git_service.GitError):
        git_service.fast_forward_sync(copy, _bundle(home, tmp / "cut.bundle", have=old))
    monkeypatch.setattr(git_service, "_git_sync", real)
    assert (copy / ".git" / git_service.APPLY_JOURNAL).exists()
    assert (copy / "entities" / "alpha-project.md").read_text() == "the home's change\n"   # files new, git behind
    if cut_at == "update-ref":
        assert git(copy, "rev-parse", "HEAD").strip() == old
    # The next apply — with the home one more commit ahead — finishes the first and goes on.
    second = hand_commit(home, "entities/new-page.md", "new\n")
    with replica_guard.applying():
        out = git_service.fast_forward_sync(copy, _bundle(home, tmp / "next.bundle", have=old))
    assert out["head"] == second and git(copy, "rev-parse", "HEAD").strip() == second
    assert git(copy, "status", "--porcelain") == "" and not (copy / ".git" / git_service.APPLY_JOURNAL).exists()
    assert first in git(copy, "log", "--format=%H")


def test_a_restart_finishes_a_journalled_apply_before_following(pair, monkeypatch):
    home, tmp = pair
    copy = _copy(home, tmp)
    old = git(copy, "rev-parse", "HEAD").strip()
    new = hand_commit(home, "entities/alpha-project.md", "the home's change\n")
    real = git_service._git_sync
    monkeypatch.setattr(git_service, "_git_sync", lambda mp, *a: (_ for _ in ()).throw(git_service.GitError("dead"))
                        if a and a[0] == "update-ref" else real(mp, *a))
    with replica_guard.applying(), pytest.raises(git_service.GitError):
        git_service.fast_forward_sync(copy, _bundle(home, tmp / "cut.bundle", have=old))
    monkeypatch.setattr(git_service, "_git_sync", real)
    with replica_guard.applying():                     # what the follower does first after a start
        assert git_service.finish_interrupted_apply_sync(copy) == new
    assert git(copy, "rev-parse", "HEAD").strip() == new and git(copy, "status", "--porcelain") == ""
