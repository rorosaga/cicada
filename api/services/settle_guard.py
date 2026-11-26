"""A settle that does not commit leaves nothing behind (G98 / G113: Sleep's settles must be undoable, and one that never
landed has no record to undo).

Sleep settles a question through the person's own resolver, which writes several files (the question moves to
``inbox/settled/``, pages are edited, a held line is released, a rejection or an alias is recorded) and only then
commits them as one commit. When that commit fails (git's index is locked past the retries, a hook refuses, the disk is
full, the process is told to stop) the files stay as the resolver left them: nothing is committed, the record of what
Sleep settled does not exist, and the next writer's commit sweeps the half-settle in under its own name. This module is
the one mechanism that closes that, for every settle ``inbox_tend.apply`` makes and for ``undo``:

* :func:`take` is called inside the admitted write, before the first file is touched. It records what every changed path
  holds at that moment (the bytes of an uncommitted page, or its absence) and what is staged. A path git calls clean
  holds what HEAD holds, so HEAD is the rest of the picture and is read only if the settle failed.
* :func:`put_back` is called when the settle did not commit. Every path in scope that differs from that picture goes back
  to exactly what it held (a file that did not exist is removed, an uncommitted edit gets its own bytes, never what
  ``git checkout`` would bring), and what the settle staged is unstaged. A path outside the scope is never touched.

**Why the picture is the whole scope and not a list of paths.** The paths a resolver writes cannot be known before it
runs: a merge folds a page and rewrites every page that referred to it, a rename ``git mv``s, a release rewrites the
pending store and the page the held line lands on. So no rule can name its paths up front, and none is given a list to
trust: the picture is taken for the whole scope (``git_service``'s touchable set, the paths a resolution can rewrite:
``entities/``, ``inbox/``, ``nudges/``, ``clarifications/`` and the bank's root files), and a path is put back only if it
differs from it. ``episodes/`` and everything else are outside the scope on purpose: a capture lands there while a settle
runs, and a restore must never remove or rewrite it.

**What it does not do.** A commit that landed is never undone here (a failure after it is the caller's, and a failure
inside git after the commit ran leaves the tree as the commit has it: any path the moved HEAD changed is left as HEAD
holds it). An edit git committed apart first (``commit_touched_sync``'s "kept apart" commit of a path that was uncommitted
before the settle) is a real commit of the person's own bytes and stays. A path that was staged before the settle keeps
whatever the index held. A writer that is not behind the page lock may write an in-scope file while a settle runs; if the
settle then fails that file is put back with the settle's, which is why the threaded settles take the page lock first.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from loguru import logger

from api.services import git_service

#: git's well-known empty tree: what a bank with no commit yet is compared against.
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbd53f9d"


class TreeUnreadable(Exception):
    """The bank's changed paths cannot be read, so a failed settle could not be put back: nothing is settled."""


@dataclass(frozen=True)
class Mark:
    memory_path: Path
    #: Every in-scope path git reported as changed when the mark was taken, with the bytes it held (``None``: absent).
    uncommitted: dict[str, bytes | None] = field(default_factory=dict)
    #: Paths whose index entry already differed from HEAD: a restore never touches their staging.
    staged: frozenset[str] = frozenset()
    head: str = ""


def in_scope(rel: str) -> bool:
    """The paths a resolution can rewrite, as ``git_service.snapshot_dirty`` reads them: a root file or a path under one
    of the touchable folders. Never a conversation (``episodes/``)."""
    return "/" not in rel or rel.startswith(git_service._TOUCHABLE_DIRS)


def _bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def _staged(memory_path: Path) -> frozenset[str]:
    out = git_service._git_sync(memory_path, "diff", "--cached", "--name-only", "-z", "--no-renames")
    return frozenset(p for p in out.split("\0") if p)


def _head(memory_path: Path) -> str:
    try:
        return git_service._git_sync(memory_path, "rev-parse", "-q", "--verify", "HEAD").strip()
    except git_service.GitError:
        return ""   # no commit yet


def take(memory_path: Path) -> Mark:
    """The picture of the tree, taken inside the admitted write and before the first file is touched. Raises
    :class:`TreeUnreadable` when git cannot list the tree (the caller then settles nothing)."""
    memory_path = Path(memory_path)
    if not (memory_path / ".git").exists():
        raise TreeUnreadable("not a repository")
    try:
        with git_service.write_lock(memory_path):
            dirty = git_service.dirty_paths_sync(memory_path)
            staged = _staged(memory_path)
            head = _head(memory_path)
    except git_service.GitError as exc:
        raise TreeUnreadable(type(exc).__name__) from None
    return Mark(memory_path, {rel: _bytes(memory_path / rel) for rel in sorted(dirty) if in_scope(rel)}, staged, head)


def _moved(mark: Mark) -> frozenset[str]:
    """What the commits made since the mark changed: a landed commit's paths stay as HEAD holds them."""
    now = _head(mark.memory_path)
    if not now or now == mark.head:
        return frozenset()
    out = git_service._git_sync(mark.memory_path, "diff", "--name-only", "-z", "--no-renames", mark.head or _EMPTY_TREE, now)
    return frozenset(p for p in out.split("\0") if p)


def put_back(mark: Mark) -> int:
    """Put every in-scope path that differs from the picture back to exactly what it held, and unstage what the failed
    settle staged. Returns how many paths could not be put back (logged as a count, never a name). Never raises."""
    from api.services import bank_index, markdown_parser

    memory_path = mark.memory_path
    failed = 0
    try:
        with git_service.write_lock(memory_path):
            now = git_service.dirty_paths_sync(memory_path)
            moved = _moved(mark)
            candidates = sorted({rel for rel in now if in_scope(rel)} | set(mark.uncommitted))
            for rel in candidates:
                try:
                    want = (mark.uncommitted[rel] if rel in mark.uncommitted and rel not in moved
                            else git_service.head_blob_sync(memory_path, rel))
                    target = memory_path / rel
                    if _bytes(target) == want:
                        continue
                    if want is None:
                        target.unlink(missing_ok=True)
                    else:
                        git_service._write_atomically(target, want)
                except (OSError, git_service.GitError):
                    failed += 1
            unstage = sorted(rel for rel in _staged(memory_path) - mark.staged if in_scope(rel))
            if unstage:
                git_service.run_git_write_sync(memory_path, "reset", "-q", "HEAD", "--", *unstage)
    except (OSError, git_service.GitError):
        failed += 1
    bank_index.invalidate(memory_path)
    markdown_parser.invalidate_pages(os.path.realpath(memory_path))
    if failed:
        logger.warning(f"A settle that did not commit could not be fully put back ({failed} path(s)); the tree needs a look")
    return failed


@contextmanager
def guarded(memory_path: Path) -> Iterator[Mark]:
    """``with guarded(bank):`` — whatever the body writes is put back if it raises (a failed commit, a stop). The body
    that returns normally is the caller's to judge (``put_back(mark)`` when its commit did not land)."""
    mark = take(memory_path)
    try:
        yield mark
    except BaseException:
        put_back(mark)
        raise
