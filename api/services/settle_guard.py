"""A settle that does not commit leaves nothing of its own behind (G98 / G113: Sleep's settles must be undoable, and one
that never landed has no record to undo).

Sleep settles a question through the person's own resolver, which writes several files (the question moves to
``inbox/settled/``, pages are edited, a held line is released, a rejection or an alias is recorded) and only then
commits them as one commit. When that commit fails (git's index is locked past the retries, a hook refuses, the disk is
full, the process is told to stop) the files stay as the resolver left them: nothing is committed, the record of what
Sleep settled does not exist, and the next writer's commit sweeps the half-settle in under its own name. This module is
the one mechanism that closes that, for every settle ``inbox_tend.apply`` makes and for ``undo``.

**It puts back what this settle wrote, and only that.** Other writers run while a settle does, without holding what it
holds (a source sync writes ``sync_state.json`` with no admission and no page lock; the person's answer to another
question runs under shared admission and mostly takes no page lock). A tree-wide sweep ("every in-scope path that differs
now goes back") would revert their files, which is worse than the defect it closes. So the settle says what it wrote:

* :func:`take` is called inside the admitted write, before the first file is touched. One ``git status`` gives the
  uncommitted in-scope paths (their bytes and modes are read), what the index held for a path staged before the settle,
  and HEAD. A path git calls clean holds what HEAD holds, so HEAD is the rest of the picture, read only on failure.
* While the settle runs (:func:`activate` puts the mark in the context, so a worker thread the settle starts carries it,
  and another writer's thread never does) each path it writes is **reported** by the writer, and what the settle left is
  recorded as a git blob hash: the page writers' one funnel (``markdown_parser._replace``, which also takes the exact
  pre-write picture of that path at its first write), the few writers that do not use it (the pending store, ``undo``'s
  writes, a merge's removal and ``git mv``), the settle's own question and record (:func:`declare`), and, at the commit,
  the paths the resolver reports for it (:func:`reported`, called by ``git_service``'s commit functions). A reported
  path no writer saw is the settle's only if it differs from the picture; one that equals it was not written by it.
* :func:`put_back` is called when the settle did not commit. A path the settle wrote goes back to its pictured bytes
  **only if its bytes still equal what the settle left**; one that changed again since (another writer got there) is left
  alone and counted. A path the settle did not write is never touched, whatever its state: not another writer's
  ``sync_state.json``, not an answer's new inbox file, not an episode, not the indexes. A path the settle staged has its
  index entry set back to what it was (an earlier staged blob, or unstaged); nothing else in the index is touched. A
  restored file keeps the mode it has (the page writers keep a page's mode), or the mode it had when it is brought back.

**The scope** is what a resolution can rewrite: ``entities/``, ``inbox/``, ``nudges/``, ``clarifications/`` and the few
root files its resolvers own (``_redirects.yaml``, ``_merge_rejected.yaml``, ``_predicates.yaml``, ``graph_edges.yaml``,
``pending_entities.jsonl``). ``episodes/``, ``sync_state.json``, ``_state.md``, the indexes and every other root file are
never in a settle's set.

**What it does not do.** A commit that landed is never undone here (a failure after it is the caller's, and a failure
inside git after the commit ran leaves the tree as the commit has it: any path the moved HEAD changed is left as HEAD
holds it). An edit git committed apart first (``commit_touched_sync``'s "kept apart" commit of a path that was uncommitted
before the settle) is a real commit of the person's own bytes and stays. A write nobody reported and no commit named (a
removal by a writer that does not say so, before an exception that skipped the commit) is not put back, because nothing
says the settle did it. A path another writer wrote *between* the settle's own write and its commit is indistinguishable
from the settle's and is put back only if its bytes still equal the settle's; the page lock closes that window for the
writers that take it.
"""
from __future__ import annotations

import contextvars
import hashlib
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from loguru import logger

from api.services import git_service

#: The bank's root files a resolver writes (a merge's redirects and edges, a "different" answer's rejection, the label map,
#: a release from the pending store). Every other root file belongs to another writer.
OWNED_ROOT_FILES = frozenset({"_redirects.yaml", "_merge_rejected.yaml", "_predicates.yaml", "graph_edges.yaml",
                              "pending_entities.jsonl"})

_UNSET = object()
_ZERO_SHA = "0" * 40
#: git's well-known empty tree: what a bank with no commit yet is compared against.
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbd53f9d"


class TreeUnreadable(Exception):
    """The bank's changed paths cannot be read, so a failed settle could not be put back: nothing is settled."""


def in_scope(rel: str) -> bool:
    """The paths a settle can own: a path under one of the touchable folders or a root file a resolver writes. Never a
    conversation (``episodes/``) and never a root file another writer owns."""
    return rel.startswith(git_service._TOUCHABLE_DIRS) or rel in OWNED_ROOT_FILES


def blob_sha(data: bytes | None) -> str | None:
    """git's own hash of a file's bytes (``None``: the file is absent)."""
    if data is None:
        return None
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _read(path: Path) -> tuple[bytes | None, int | None]:
    """What a file holds and its permission bits (``(None, None)``: absent or unreadable)."""
    try:
        if not path.is_file():
            return None, None
        return path.read_bytes(), path.stat().st_mode & 0o7777
    except OSError:
        return None, None


@dataclass
class _Rec:
    """One path this settle wrote."""
    #: What the path held before the settle's first write, with its mode.
    first: tuple[bytes | None, int | None] | None = None
    #: git's hash of what the settle last left there (``None``: it left the path absent); unset until known.
    left: object = _UNSET
    #: The settle's own question: put back without a hash gate when no commit named it.
    declared: bool = False


@dataclass
class Mark:
    memory_path: Path
    root: str = ""
    head: str = ""
    #: Every uncommitted in-scope path when the mark was taken: its bytes and mode (``None``: absent).
    pictured: dict[str, tuple[bytes | None, int | None]] = field(default_factory=dict)
    #: Index entries that already differed from HEAD: ``(mode, blob)``, or ``None`` for a staged removal.
    staged: dict[str, tuple[str, str] | None] = field(default_factory=dict)
    recs: dict[str, _Rec] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def rel(self, path) -> str | None:
        """``path`` relative to the bank when it is a path a settle can own, else ``None``."""
        try:
            real = os.path.realpath(os.fspath(path))
        except (OSError, ValueError, TypeError):
            return None
        if not real.startswith(self.root + os.sep):
            return None
        rel = real[len(self.root) + 1:]
        return rel if in_scope(rel) else None


_ACTIVE: contextvars.ContextVar[Mark | None] = contextvars.ContextVar("settle_guard", default=None)


def active() -> Mark | None:
    return _ACTIVE.get()


@contextmanager
def activate(mark: Mark) -> Iterator[Mark]:
    """Every writer in this context (and in a thread it starts with ``asyncio.to_thread``) reports to ``mark``."""
    token = _ACTIVE.set(mark)
    try:
        yield mark
    finally:
        _ACTIVE.reset(token)


# --------------------------------------------------------------------------- the picture


def _parse_status(out: str) -> tuple[str, dict[str, tuple[str, str] | None], set[str]]:
    """``git status --porcelain=v2 -z --branch``: HEAD (``""`` before the first commit), the index entry of every path staged
    differently from HEAD, and every changed path."""
    head, staged, dirty = "", {}, set()
    for rec in out.split("\0"):
        if not rec:
            continue
        if rec.startswith("# branch.oid "):
            oid = rec.split(" ", 2)[2]
            head = "" if oid == "(initial)" else oid
        elif rec.startswith("#"):
            continue
        elif rec.startswith("1 "):
            _, xy, _sub, _mh, mi, _mw, _hh, hi, path = rec.split(" ", 8)
            dirty.add(path)
            if xy[0] != ".":
                staged[path] = None if hi == _ZERO_SHA or xy[0] == "D" else (mi, hi)
        elif rec.startswith("? "):
            dirty.add(rec[2:])
        elif rec.startswith("u "):
            dirty.add(rec.split(" ", 10)[10])
    return head, staged, dirty


def take(memory_path: Path) -> Mark:
    """The picture of the tree, taken inside the admitted write and before the first file is touched: one ``git status``.
    Raises :class:`TreeUnreadable` when git cannot list the tree (the caller then settles nothing)."""
    memory_path = Path(memory_path)
    if not (memory_path / ".git").exists():
        raise TreeUnreadable("not a repository")
    try:
        with git_service.write_lock(memory_path):
            out = git_service._git_sync(memory_path, "status", "--porcelain=v2", "-z", "--branch", "--no-renames",
                                        "--untracked-files=all")
    except git_service.GitError as exc:
        raise TreeUnreadable(type(exc).__name__) from None
    head, staged, dirty = _parse_status(out)
    mark = Mark(memory_path, root=os.path.realpath(memory_path), head=head)
    for rel in sorted(dirty):
        if in_scope(rel):
            mark.pictured[rel] = _read(memory_path / rel)
    mark.staged = {rel: entry for rel, entry in staged.items() if in_scope(rel)}
    return mark


# --------------------------------------------------------------------------- what the settle says it wrote


def _rec(mark: Mark, rel: str) -> _Rec:
    """The path's record; its picture is taken now if this is the settle's first word about it."""
    rec = mark.recs.get(rel)
    if rec is None:
        rec = mark.recs[rel] = _Rec(first=_read(mark.memory_path / rel))
    return rec


def declare(mark: Mark, *rels: str) -> None:
    """The settle's own question: its path by definition, pictured now, before the resolver runs."""
    for rel in rels:
        if in_scope(rel):
            with mark.lock:
                _rec(mark, rel).declared = True


def writing(path) -> None:
    """A writer is about to write, remove or move ``path``: the exact bytes and mode it holds now are that path's picture,
    taken once, at the settle's first write. A no-op outside a settle."""
    mark = _ACTIVE.get()
    if mark is None:
        return
    try:
        rel = mark.rel(path)
        if rel is not None:
            with mark.lock:
                _rec(mark, rel)
    except Exception as exc:  # noqa: BLE001 — reporting never fails a writer
        logger.debug(f"settle guard: a write was not noted ({type(exc).__name__})")


def wrote(path, data: bytes | None) -> None:
    """The writer left ``data`` at ``path`` (``None``: it removed it): what the settle left, as git hashes it."""
    mark = _ACTIVE.get()
    if mark is None:
        return
    try:
        rel = mark.rel(path)
        if rel is not None:
            with mark.lock:
                mark.recs.setdefault(rel, _Rec()).left = blob_sha(data)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"settle guard: a write was not noted ({type(exc).__name__})")


def reported(memory_path, paths) -> None:
    """The commit's own list of what the settle wrote, called by ``git_service``'s commit functions before they stage
    anything. A path a writer reported gets its hash now if it has none (a removal, a ``git mv``). A path no writer
    reported is the settle's only if it differs from the picture (one that equals it was never written by the settle).
    A no-op outside a settle."""
    mark = _ACTIVE.get()
    if mark is None:
        return
    try:
        unseen: list[str] = []
        for p in paths:
            rel = mark.rel(Path(memory_path) / str(p))
            if rel is None:
                continue
            with mark.lock:
                rec = mark.recs.get(rel)
                if rec is None:
                    unseen.append(rel)
                elif rec.left is _UNSET:
                    rec.left = blob_sha(_read(mark.memory_path / rel)[0])
        if not unseen:
            return
        changed = git_service.dirty_paths_sync(mark.memory_path, *unseen)   # one narrow status, only for such paths
        for rel in unseen:
            now = _read(mark.memory_path / rel)
            pic = mark.pictured.get(rel)
            if (now[0] != pic[0]) if pic is not None else (rel in changed):
                with mark.lock:
                    # Its picture: its own bytes if it was uncommitted before the settle, else HEAD's (read on failure).
                    mark.recs[rel] = _Rec(first=pic, left=blob_sha(now[0]))
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"settle guard: a commit's paths were not noted ({type(exc).__name__})")


# --------------------------------------------------------------------------- putting back


def _head_of(memory_path: Path) -> str:
    try:
        return git_service._git_sync(memory_path, "rev-parse", "-q", "--verify", "HEAD").strip()
    except git_service.GitError:
        return ""   # no commit yet


def _moved(mark: Mark) -> frozenset[str]:
    """What the commits made since the mark changed: a landed commit's paths stay as HEAD holds them."""
    now = _head_of(mark.memory_path)
    if not now or now == mark.head:
        return frozenset()
    out = git_service._git_sync(mark.memory_path, "diff", "--name-only", "-z", "--no-renames", mark.head or _EMPTY_TREE, now)
    return frozenset(p for p in out.split("\0") if p)


def _write_back(target: Path, data: bytes, mode: int | None) -> None:
    """Replace ``target`` atomically with the mode it had when the settle first touched it, else (a path nobody pictured:
    git's own clean file) the mode it has now."""
    if mode is None:
        try:
            mode = target.stat().st_mode & 0o7777
        except OSError:
            pass
    git_service._write_atomically(target, data, mode=mode)


def _restore_index(mark: Mark, rels: list[str]) -> None:
    """Set the index entry of every path the settle staged back to what it was before: the earlier staged blob, a staged
    removal, or no entry. An entry that is not what the settle staged (another writer staged it) is left as it is."""
    memory_path = mark.memory_path
    listing = git_service._git_sync(memory_path, "ls-files", "-s", "-z", "--", *rels)
    now: dict[str, tuple[str, str]] = {}
    for rec in listing.split("\0"):
        if rec:
            meta, _, path = rec.partition("\t")
            mode, sha, _stage = meta.split(" ")
            now[path] = (mode, sha)
    to_head: list[str] = []
    for rel in rels:
        left = mark.recs[rel].left
        entry = now.get(rel)
        if not ((entry is None) if left is None else (entry is not None and entry[1] == left)):
            continue
        if rel not in mark.staged:
            to_head.append(rel)   # it matched HEAD before: unstage it
            continue
        before = mark.staged[rel]
        if before == entry:
            continue
        if before is None:
            git_service.run_git_write_sync(memory_path, "update-index", "--force-remove", "--", rel)
        else:
            git_service.run_git_write_sync(memory_path, "update-index", "--add", "--cacheinfo",
                                           f"{before[0]},{before[1]},{rel}")
    if to_head:
        if mark.head:
            git_service.run_git_write_sync(memory_path, "reset", "-q", "HEAD", "--", *to_head)
        else:
            git_service.run_git_write_sync(memory_path, "rm", "-q", "--cached", "--ignore-unmatch", "--", *to_head)


def put_back(mark: Mark) -> int:
    """Put every path this settle wrote back to what it held, if it still holds what the settle left, and set the index entry
    of each back to what it was. A path the settle did not write is never touched; one another writer changed since is left
    and counted. Returns how many paths could not be put back (logged as a count, never a name). Never raises."""
    from api.services import bank_index, markdown_parser

    memory_path = mark.memory_path
    failed = diverged = 0
    with mark.lock:
        recs = {rel: rec for rel, rec in mark.recs.items() if rec.left is not _UNSET or rec.declared}
    try:
        with git_service.write_lock(memory_path):
            moved = _moved(mark)
            staged_by_settle: list[str] = []
            for rel in sorted(recs):
                rec = recs[rel]
                try:
                    target = memory_path / rel
                    cur = _read(target)[0]
                    if rec.left is not _UNSET and blob_sha(cur) != rec.left:
                        diverged += 1   # another writer got there since: not ours to put back
                        continue
                    if rec.first is not None:
                        want, mode = rec.first
                    elif rel in mark.pictured and rel not in moved:
                        want, mode = mark.pictured[rel]
                    else:
                        want, mode = git_service.head_blob_sync(memory_path, rel), None
                    if cur != want:
                        if want is None:
                            target.unlink(missing_ok=True)
                        else:
                            _write_back(target, want, mode)
                    if rec.left is not _UNSET:
                        staged_by_settle.append(rel)
                except (OSError, git_service.GitError):
                    failed += 1
            if staged_by_settle:
                try:
                    _restore_index(mark, staged_by_settle)
                except (OSError, git_service.GitError):
                    failed += 1
    except (OSError, git_service.GitError):
        failed += 1
    bank_index.invalidate(memory_path)
    markdown_parser.invalidate_pages(os.path.realpath(memory_path))
    if failed:
        logger.warning(f"A settle that did not commit could not be fully put back ({failed} path(s)); the tree needs a look")
    if diverged:
        logger.info(f"A settle that did not commit left {diverged} path(s) as another writer changed them since")
    return failed


@contextmanager
def guarded(memory_path: Path) -> Iterator[Mark]:
    """``with guarded(bank):`` — whatever the body writes is put back if it raises (a failed commit, a stop). The body
    that returns normally is the caller's to judge (``put_back(mark)`` when its commit did not land)."""
    mark = take(memory_path)
    with activate(mark):
        try:
            yield mark
        except BaseException:
            put_back(mark)
            raise
