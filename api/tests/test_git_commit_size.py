"""A commit never fails on the size of its own message or on how many paths it names (G85, G181).

Linux refuses ONE argument over 128 KiB (`MAX_ARG_STRLEN`) and a whole argv past ~2 MiB; macOS refuses an argv plus its
environment past 1 MiB. A Sleep commit's message has one manifest line per file, so the product's writers could hand git
a 230 KB `-m` argument (about 2,500 pages) or a 1.4 MB argv (about 9,000). The Mac is on the right side of the per-argument
limit, so these tests assert what git is HANDED (Linux's numbers, stated below) and also run the real commit end to end.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from api.services import git_service

#: Linux's `MAX_ARG_STRLEN` (32 pages): one argument longer than this is `E2BIG` there, whatever the total.
LINUX_ONE_ARG = 131072
#: macOS's `ARG_MAX`, argv plus environment — the tighter of the two total limits (Linux's is about 2 MiB).
MAC_TOTAL = 1048576
LONG = "p" * 90   # a page id as long as the longest real ones; ~2,900 of these pass the module's total bound


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


@pytest.fixture
def argv_seen(monkeypatch):
    """Every git command `git_service` starts, as `(args, total)` — both spawn doors."""
    seen: list[list[str]] = []
    real = subprocess.run

    def watch(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            seen.append(list(cmd))
        return real(cmd, *a, **k)

    monkeypatch.setattr(git_service.subprocess, "run", watch)
    return seen


def _assert_inside_the_limits(seen):
    assert seen, "nothing was spawned"
    for argv in seen:
        sizes = [len(os.fsencode(a)) for a in argv]
        assert max(sizes) <= LINUX_ONE_ARG, f"git {argv[1]}: one argument of {max(sizes)} bytes"
        assert max(sizes) <= git_service.ARG_BYTES_MAX
        total = sum(s + 1 + 8 for s in sizes)
        assert total <= git_service.ARGV_BYTES_MAX < MAC_TOTAL // 2, f"git {argv[1]}: argv of {total} bytes"


def _pages(bank: Path, n: int) -> list[str]:
    rels = []
    for i in range(n):
        rel = f"entities/{LONG}-{i:05d}.md"
        (bank / rel).write_text(f"page {i}\n", encoding="utf-8")
        rels.append(rel)
    return rels


def _message(rels, subject="Sleep consolidation 2026-11-24"):
    return git_service.build_commit_message(
        subject, [f"{r}: updated (trigger: sleep/decay)" for r in rels],
        authors=["cicada"], sessions=["session-1"], engine="haiku")


N = 3200   # message ~ 380 KB (3x Linux's limit) and path list ~ 310 KB (past the module's total bound)


def test_a_path_scoped_commit_of_thousands_of_pages_fits_and_commits_exactly_its_paths(bank, argv_seen):
    rels = _pages(bank, N)
    (bank / "unrelated.md").write_text("staged by someone else\n", encoding="utf-8")
    _git(bank, "add", "unrelated.md")
    msg = _message(rels)
    assert len(msg.encode()) > 3 * LINUX_ONE_ARG

    git_service.commit_paths_sync(bank, msg, rels)

    _assert_inside_the_limits(argv_seen)
    assert _git(bank, "log", "-1", "--format=%B").rstrip("\n") == msg   # byte for byte, trailers included
    assert set(_git(bank, "show", "--format=", "--name-only", "HEAD").split()) == set(rels)
    assert _git(bank, "diff", "--cached", "--name-only").split() == ["unrelated.md"]   # the other staging stays staged
    assert _git(bank, "log", "-1", "--format=%(trailers:key=Cicada-Author,valueonly)").strip() == "cicada"
    assert _git(bank, "log", "-1", "--format=%(trailers:key=Cicada-Session,valueonly)").strip() == "session-1"


def test_commit_touched_commits_a_removal_and_the_rest_in_one_commit(bank, argv_seen):
    rels = _pages(bank, N)
    git_service.commit_paths_sync(bank, "first", rels)
    gone = rels[7]
    (bank / gone).unlink()
    for r in rels[8:20]:
        (bank / r).write_text("changed\n", encoding="utf-8")
    before = _git(bank, "rev-parse", "HEAD").strip()
    argv_seen.clear()
    msg = _message([*rels[8:20], gone])

    git_service.commit_touched_sync(bank, msg, [gone, *rels[8:20], *rels[100:]])

    _assert_inside_the_limits(argv_seen)
    assert _git(bank, "rev-list", "--count", f"{before}..HEAD").strip() == "1"
    assert set(_git(bank, "show", "--format=", "--name-status", "HEAD").splitlines()) == {
        f"D\t{gone}", *(f"M\t{r}" for r in rels[8:20])}
    assert _git(bank, "status", "--porcelain").strip() == ""


def test_commit_changes_and_a_kept_apart_commit_carry_a_giant_message(bank, argv_seen):
    rels = _pages(bank, 40)
    msg = _message([f"entities/{LONG}-{i:05d}.md" for i in range(N)])
    git_service.commit_changes_sync(bank, msg)
    assert _git(bank, "log", "-1", "--format=%B").rstrip("\n") == msg

    (bank / rels[0]).write_text("kept\n", encoding="utf-8")
    argv_seen.clear()
    assert git_service.commit_contents_sync(bank, {rels[0]: b"bytes\n"}, msg) is True   # commit-tree
    _assert_inside_the_limits(argv_seen)
    assert _git(bank, "log", "-1", "--format=%B").rstrip("\n") == msg
    assert _git(bank, "show", "HEAD:" + rels[0]) == "bytes\n"
    _assert_inside_the_limits(argv_seen)


#: Messages past the bound (~130 KB) in the endings git treats differently: a final newline or none, trailing blanks
#: and blank runs that git's own cleanup removes, a line that looks like a comment.
def _big_messages():
    body = "\n".join(f"entities/{LONG}-{i:05d}.md: updated (trigger: t)" for i in range(1400))
    return [f"Subject\n\n{body}\n\nCicada-Author: x", f"Subject\n\n{body}\n\nCicada-Author: x\n",
            f"Subject\n\n\n\n{body}   \n\n\n\n# not a comment  \n\nCicada-Author: x  \n\n", f"  {body}"]


def test_the_commit_objects_are_the_ones_dash_m_makes(bank, monkeypatch):
    """`-F <file>` hands git the same bytes: with the dates fixed the commit objects are identical to `-m`'s, for
    `commit-tree` and for a path-scoped `commit`."""
    for var in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"):
        monkeypatch.setenv(var, "2026-01-01T00:00:00Z")
    rels = _pages(bank, 3)
    _git(bank, "add", "-A")
    tree = _git(bank, "write-tree").strip()
    head = _git(bank, "rev-parse", "HEAD").strip()
    for msg in _big_messages():
        assert len(msg.encode()) > git_service.ARG_BYTES_MAX
        direct = _git(bank, "commit-tree", tree, "-p", head, "-m", msg).strip()
        through = git_service._git_env_sync(bank, dict(os.environ), "commit-tree", tree, "-p", head, "-m", msg).strip()
        assert through == direct, "commit-tree: the file form made a different commit object"

        _git(bank, "commit", "-q", "-m", msg, "--", *rels)
        wanted = _git(bank, "cat-file", "commit", "HEAD")
        _git(bank, "reset", "-q", "--soft", "HEAD~1")   # the pages stay in the index: the same state for the second try
        git_service.commit_paths_sync(bank, msg, rels)
        assert _git(bank, "cat-file", "commit", "HEAD") == wanted, "commit: the file form made a different commit"
        _git(bank, "reset", "-q", "--soft", "HEAD~1")


def test_a_refused_big_commit_leaves_the_index_as_the_small_one_does(bank):
    rels = _pages(bank, N)
    head = _git(bank, "rev-parse", "HEAD").strip()
    # The small form: a path git does not know — `git add` refuses the whole command and stages nothing.
    with pytest.raises(git_service.GitError):
        git_service.commit_paths_sync(bank, "small", [*rels[:3], "entities/never-existed.md"])
    small = (_git(bank, "diff", "--cached", "--name-only"), _git(bank, "rev-parse", "HEAD").strip())
    with pytest.raises(git_service.GitError) as err:
        git_service.commit_paths_sync(bank, _message(rels), [*rels, "entities/never-existed.md"])
    assert (_git(bank, "diff", "--cached", "--name-only"), _git(bank, "rev-parse", "HEAD").strip()) == small == ("", head)
    assert len(str(err.value)) < 5000   # the error names the command, never every path of it


def test_a_big_commit_waits_out_the_index_lock_with_the_same_files(bank, monkeypatch):
    rels = _pages(bank, N)
    real = git_service._spawn
    refused: list[bool] = []

    def lock_once(memory_path, args):
        if args[0] == "commit" and not refused:
            refused.append(True)
            return subprocess.CompletedProcess(args, 128, b"", b"fatal: Unable to create 'index.lock': File exists.")
        return real(memory_path, args)

    monkeypatch.setattr(git_service, "_spawn", lock_once)
    monkeypatch.setattr(git_service, "_sleep", lambda _s: None)
    git_service.commit_paths_sync(bank, _message(rels), rels)
    assert refused and set(_git(bank, "show", "--format=", "--name-only", "HEAD").split()) == set(rels)


def test_no_scratch_file_outlives_the_command(bank, tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    rels = _pages(bank, N)
    git_service.commit_paths_sync(bank, _message(rels), rels)
    with pytest.raises(git_service.GitError):
        git_service.commit_paths_sync(bank, _message(rels), [*rels, "nope.md"])
    assert list(scratch.iterdir()) == []


def test_a_listing_of_thousands_of_paths_is_read_in_pieces_and_joined(bank, argv_seen):
    rels = _pages(bank, N)
    git_service.commit_paths_sync(bank, "all", rels)
    (bank / rels[5]).write_text("dirty\n", encoding="utf-8")
    argv_seen.clear()

    tracked = git_service._git_sync(bank, "ls-files", "-z", "--", *rels, "entities")   # a path AND its directory
    assert [p for p in tracked.split("\0") if p] == sorted(set(rels))   # each once, as a single call lists it
    assert git_service.dirty_paths_sync(bank, *rels) == {rels[5]}
    assert git_service._git_sync(bank, "status", "--porcelain", "--", *rels).split() == ["M", rels[5]]
    _assert_inside_the_limits(argv_seen)
    assert len(argv_seen) > 3   # it did split
    assert git_service._git_sync(bank, "status", "--porcelain", "--", *rels[:3]) == ""   # a short one is one command


def test_a_short_command_is_spawned_exactly_as_before(bank, argv_seen):
    (bank / "entities" / "a.md").write_text("a\n", encoding="utf-8")
    git_service.commit_paths_sync(bank, "Write a\n\nCicada-Author: x", ["entities/a.md"])
    commit = [a for a in argv_seen if a[1] == "commit"]
    assert commit == [["git", "commit", "-m", "Write a\n\nCicada-Author: x", "--", "entities/a.md"]]
