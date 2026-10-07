"""One bank's entity pages: the critical section for a claim write (audit 2026-10-05 P1-2).

``markdown_parser.write`` is atomic, so one write never tears a page — but a
claim write is read → reconcile → write, and two writers that both read before
either writes each report ``written`` while the second replaces the first.
The writers are separate processes (the stdio MCP server and the backend, or
two MCP servers), so the guard is :func:`episode_ids.dir_lock` on the bank's
directory: an ``flock`` every process contends for, re-entrant
within a thread, nothing created inside the bank for git to see.

**What holds it.** Every agent-surface write of a page: ``agentic_write``'s
claim write and withdrawal, ``progress``'s event writes, ``fact_sources``'
source writes, ``paper_metadata``'s page updates, ``entity_merge`` (the dedup
sweep holds it across each merge's commit too), the app's decay-class and
repo-link rewrites, and the inbox's normalization answer (its pages, the
predicate map and its commit — G98/G115). The MCP tools hold it across the write AND its
``agent_commits.commit_write``, so a page is committed as the writer left it. **Lock order:** the bank's write
admission (``write_admission``, G183) first, then this lock, then git's
per-bank write lock (taken inside the commit), then ``episode_lock`` — never
the reverse; nothing that holds the git write lock or ``episode_lock`` may ask
for this one. **Hold it short:** one page operation and its commit — never a
network call, a Sleep probe or a Sleep stage. ``flock`` waits without a
timeout, and some holders are ``async`` backend routes and the inbox's
follow-up resolver, which wait on the event loop. **Not here yet:** Sleep's own
page writes (they run inside the write window, which every guarded writer waits
out or refuses through ``write_admission``) and the inbox's other resolvers — disclosed in
``docs/architecture/storage.md``.

The lock is an ``flock`` on the bank directory itself (``entities/`` may not
exist yet on a new bank); a bank directory that does not exist is not locked
and not created.
"""
from __future__ import annotations

import functools
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from api.services.episode_ids import dir_lock, dir_lock_held


def _dir(memory_path) -> Path:
    return Path(memory_path)


@contextmanager
def page_lock(memory_path) -> Iterator[None]:
    """Exclusive, cross-process, re-entrant lock on one bank's entity pages."""
    if not _dir(memory_path).is_dir():
        yield   # no bank, nothing to race on — and never a directory made by a lock
        return
    with dir_lock(_dir(memory_path)):
        yield


def held(memory_path) -> bool:
    """Does this process hold the bank's page lock? (a test seam)"""
    return dir_lock_held(_dir(memory_path))


def locked(fn):
    """Run ``fn(memory_path, ...)`` holding the bank's page lock — for a writer
    whose first argument (or ``memory_path=``) is the bank."""
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        memory_path = args[0] if args else kwargs["memory_path"]
        with page_lock(memory_path):
            return fn(*args, **kwargs)
    return inner
