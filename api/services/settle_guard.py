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
  and another writer's thread never does) **every writer reports each path it writes, removes or renames**: it calls
  :func:`writing` before (the exact bytes and mode the path holds then are its picture, taken once, at the settle's first
  word about it) and :func:`wrote` after (what it left, as git's blob hash; ``None``: absent), or :func:`renamed` for a move.
  The page writers' one funnel (``markdown_parser._replace`` and ``write_new``) does it for every page, ledger line, YAML
  file and look record it writes; the writers that do not use it do it themselves (``claims_ledger.remove`` and ``move``,
  ``merge_rejections``, ``same_name_doubts``, ``predicates.update_runtime_map``, ``pending_store.save``,
  ``entity_picture``'s moves and removal, ``merge_closes.close``, ``entity_merge``'s removal of the loser,
  ``role_people.rename``'s page move, ``inbox_service._git_move`` and ``_git_remove``, ``undo``'s writes), plus the settle's own
  question and record (:func:`declare`). At the commit the paths the resolver names for it are reported too
  (:func:`reported`, called by ``git_service``'s commit functions before they stage anything): such a path no writer saw is the
  settle's only if it differs from the picture; one that equals it was not written by it. ``test_settle_guard_gate`` is the
  standing check: it stops every branch of ``apply`` and ``undo`` at its commit and fails on any in-scope path that changed
  and was reported by no writer.
* :func:`put_back` is called when the settle did not commit. A path the settle wrote goes back to its pictured bytes
  **only if its bytes still equal what the settle left**; one that changed again since (another writer got there) is left
  alone and counted. A path the settle did not write is never touched, whatever its state: not another writer's
  ``sync_state.json``, not an answer's new inbox file, not an episode, not the indexes. A path the settle staged has its
  index entry set back to what it was (an earlier staged blob, or unstaged); nothing else in the index is touched. A
  restored file keeps the mode it has (the page writers keep a page's mode), or the mode it had when it is brought back.

**A page and its claims ledger are one unit** (:func:`partner_of`: ``entities/<id>.md`` and ``entities/<id>.claims.jsonl``;
a page write moves claims between them). A partial restore of the two is worse than none: a page back without its ledger has
lost claims. So when one of them is put back, the other goes back with it if, at restore time, it differs from what it held
before the settle (the person's own uncommitted bytes when it was dirty, else HEAD's) although no writer reported it; that is
logged as an unreported write (ids only) and its index entry is set back too. When either half was changed by another writer
since the settle left it, both are left. Anything else unreported stays untouched, as before.

**The scope** is what a resolution can rewrite: ``entities/``, ``inbox/``, ``nudges/``, ``clarifications/``, the person's
uploaded pictures a merge moves or removes (``assets/pictures/``), the look records a merge repoints (``design/<id>.md``, never
a screenshot) and the few root files its resolvers own (``_redirects.yaml``, ``_merge_rejected.yaml``,
``_same_name_doubts.yaml``, ``_predicates.yaml``, ``graph_edges.yaml``, ``pending_entities.jsonl``). ``episodes/``,
``sync_state.json``, ``_state.md``, the indexes and every other root file are never in a settle's set (the one thing a
settle writes there, the episode that holds the person's own quoted words, is removed by the resolver itself when it fails).

**A commit that landed is never undone here.** ``git_service``'s commit functions call :func:`landed` the moment git's
``commit`` returns, and from then on the settle is a fact: nothing of it is put back whatever raises after (``apply``,
``undo_committed`` and :func:`guarded` log the error by class, never its message, and report that the settle landed; a stop, a
``BaseException`` that is not an ``Exception``, still propagates). When only an earlier commit moved HEAD (the "kept apart"
commit of an unsaved edit of the person's on a page the settle also writes: a real commit of their own bytes, which stays), a path
whose bytes equal what HEAD now holds is left alone, and only a path that differs from HEAD and from the picture goes back to its
picture. A path another writer wrote *between* the settle's own write and its commit is indistinguishable from the settle's and
is put back only if its bytes still equal the settle's; the page lock closes that window for the writers that take it. A writer
that does not report is a hole the gate names; the pair rule above is what keeps such a hole from making the restore worse than
none for the one case that has been found, the ledger.
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
                              "pending_entities.jsonl", "_same_name_doubts.yaml"})
#: The folders a merge writes besides the pages: a person's uploaded picture it moves or removes, and the look records it
#: repoints (``design/<id>.md``; never a screenshot, which a merge does not write).
_PICTURE_DIR = "assets/pictures/"
_LOOK_DIR = "design/"

_UNSET = object()
_ZERO_SHA = "0" * 40
#: git's well-known empty tree: what a bank with no commit yet is compared against.
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbd53f9d"


class TreeUnreadable(Exception):
    """The bank's changed paths cannot be read, so a failed settle could not be put back: nothing is settled."""


def in_scope(rel: str) -> bool:
    """The paths a settle can own: a path under one of the touchable folders or a root file a resolver writes. Never a
    conversation (``episodes/``) and never a root file another writer owns."""
    return (rel.startswith(git_service._TOUCHABLE_DIRS) or rel in OWNED_ROOT_FILES or rel.startswith(_PICTURE_DIR)
            or (rel.startswith(_LOOK_DIR) and rel.endswith(".md") and rel.count("/") == 1))


def partner_of(rel: str) -> str | None:
    """The other half of a page and its claims ledger: ``entities/<id>.claims.jsonl`` for ``entities/<id>.md`` and the
    reverse, else ``None``. The two are one unit (``claims_ledger``): a page write moves claims between them."""
    from api.services import claims_ledger

    ledger = claims_ledger.rel_for(rel)
    if ledger is not None:
        return ledger
    if rel.startswith("entities/") and rel.endswith(claims_ledger.SUFFIX) and rel.count("/") == 1:
        return rel[:-len(claims_ledger.SUFFIX)] + ".md"
    return None


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
    #: A commit of this settle's own paths ran to its end (set by ``git_service``'s commit functions the moment git's
    #: ``commit`` returned). From then on the settle is a fact: nothing of it is put back, whatever fails after.
    landed: bool = False
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


def wrote_now(path) -> None:
    """:func:`wrote` for a writer that moved or replaced a file with bytes it never held: what the path holds now is what
    the settle left (read only inside a settle; a no-op anywhere else)."""
    mark = _ACTIVE.get()
    if mark is None:
        return
    try:
        rel = mark.rel(path)
        if rel is not None:
            with mark.lock:
                mark.recs.setdefault(rel, _Rec()).left = blob_sha(_read(mark.memory_path / rel)[0])
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"settle guard: a write was not noted ({type(exc).__name__})")


def renamed(src, dst) -> None:
    """A writer renamed ``src`` to ``dst`` (after it called :func:`writing` on both): ``src`` is left absent, ``dst`` holds
    the moved bytes."""
    wrote(src, None)
    wrote_now(dst)


def landed() -> None:
    """``git_service``'s commit functions call this the moment git's ``commit`` returned: the settle's commit is a fact."""
    mark = _ACTIVE.get()
    if mark is not None:
        mark.landed = True


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
    and counted. Returns how many paths could not be put back (logged as a count, never a name). Never raises.

    **A page and its claims ledger are one unit** (:func:`partner_of`): when one of the two is put back, the other is put
    back with it if it differs from what it held before the settle (what the settle left it, written by a writer that did
    not report; logged as an unreported write, ids only); and when one of them was changed by another writer since, both
    are left. A path the settle's own commit (or one commit made apart) already holds is left as it is: only a path that
    differs from what HEAD now holds is put back."""
    from api.services import bank_index, markdown_parser

    memory_path = mark.memory_path
    failed = diverged = 0
    unreported: list[str] = []
    with mark.lock:
        recs = {rel: rec for rel, rec in mark.recs.items() if rec.left is not _UNSET or rec.declared}
    try:
        with git_service.write_lock(memory_path):
            moved = _moved(mark)
            left_alone: set[str] = set()   # another writer's since, or already in a commit: not ours to put back
            for rel in sorted(recs):
                rec = recs[rel]
                if rec.left is not _UNSET and blob_sha(_read(memory_path / rel)[0]) != rec.left:
                    left_alone.add(rel)
                    diverged += 1
            for rel in sorted(recs):
                other = partner_of(rel)
                if rel not in left_alone and other in left_alone:
                    left_alone.add(rel)   # one unit: not put back when the other half is another writer's now
                    diverged += 1
            staged_by_settle: list[str] = []
            for rel in sorted(recs):
                if rel in left_alone:
                    continue
                rec = recs[rel]
                try:
                    target = memory_path / rel
                    cur = _read(target)[0]
                    if rel in moved and cur == git_service.head_blob_sync(memory_path, rel):
                        continue   # a commit holds exactly these bytes: it is not the settle's to take back
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
                    # The other half of a page and its ledger, written by a writer that did not say so.
                    other = partner_of(rel)
                    if other is not None and other not in recs and _put_back_partner(mark, other, moved):
                        unreported.append(other)
                        staged_by_settle.append(other)
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
    if unreported:
        logger.warning("A settle wrote a claims ledger or a page without reporting it; it was put back with its unit "
                       f"({', '.join(sorted(Path(rel).name.split('.')[0] for rel in unreported))})")
    if failed:
        logger.warning(f"A settle that did not commit could not be fully put back ({failed} path(s)); the tree needs a look")
    if diverged:
        logger.info(f"A settle that did not commit left {diverged} path(s) as another writer changed them since")
    return failed


def _put_back_partner(mark: Mark, rel: str, moved: frozenset[str]) -> bool:
    """The unit's other half, which no writer reported: if it differs from what it held before the settle (the person's own
    uncommitted bytes when it was dirty, else what HEAD holds) it goes back to that. ``True`` when it was changed. Write lock held."""
    memory_path = mark.memory_path
    target = memory_path / rel
    cur = _read(target)[0]
    head = git_service.head_blob_sync(memory_path, rel)
    if rel in moved and cur == head:
        return False
    want, mode = mark.pictured.get(rel, (head, None))
    if cur == want:
        return False
    if want is None:
        target.unlink(missing_ok=True)
    else:
        _write_back(target, want, mode)
    with mark.lock:
        mark.recs[rel] = _Rec(first=(want, mode), left=blob_sha(cur))   # its index entry goes back with the rest
    return True


@contextmanager
def guarded(memory_path: Path) -> Iterator[Mark]:
    """``with guarded(bank):`` — whatever the body writes is put back if it raises before its commit landed (a failed
    commit, a stop). A step that raises after the commit landed leaves the settle as the commit holds it: the error is
    logged (its class, never its message) and the body ends as if it had returned. The body that returns normally is the
    caller's to judge (``put_back(mark)`` when its commit did not land)."""
    mark = take(memory_path)
    with activate(mark):
        try:
            yield mark
        except BaseException as exc:
            if not mark.landed:
                put_back(mark)
                raise
            after_landing(exc)


def after_landing(exc: BaseException) -> None:
    """A step failed after the settle's commit landed: the settle stands, so nothing is put back. A stop (a ``BaseException``
    that is not an ``Exception``) still propagates; any other error is logged by class and swallowed."""
    if not isinstance(exc, Exception):
        raise exc
    logger.warning(f"A step after a settle's commit failed ({type(exc).__name__}); the settle landed and stays")
