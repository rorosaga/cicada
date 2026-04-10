"""Fresh temporary memory workspace for benchmark runs.

The live ``memory/`` directory is already consolidated — running a sleep
cycle against it would overwrite real entity pages. To benchmark the
sleep cycle honestly we need a clean slate seeded from raw episodes only.

``create_workspace`` copies every episode from ``source_memory/episodes``
into a fresh temp dir, rewrites each episode's ``processed:`` field to
``false``, creates the sibling dirs the sleep cycle expects
(``entities/``, ``nudges/``, ``clarifications/``), and initializes a
standalone git repo so ``git_service.commit_changes`` has something to
commit against.

Workspaces live under ``/tmp/cicada_bench_*``. They are intentionally
NOT cleaned up automatically — post-run inspection is the whole point.
Delete them with ``rm -rf /tmp/cicada_bench_*`` when finished.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from benchmarks._bootstrap import LIVE_MEMORY_PATH


_PROCESSED_RE = re.compile(r"^processed:\s*true\b", re.MULTILINE)


def create_workspace(
    name: str,
    episode_limit: int | None = None,
    source_memory: Path | None = None,
) -> Path:
    """Seed a fresh memory workspace from the live ``memory/episodes`` dir.

    Parameters
    ----------
    name
        Short label, used in the temp dir prefix so multiple workspaces
        are easy to tell apart on disk.
    episode_limit
        If set, copy at most N episodes. Useful for smoke tests.
    source_memory
        Override the source memory root. Defaults to the repo's live
        ``memory/`` dir.

    Returns
    -------
    Path
        Absolute path to the new workspace root. Caller is responsible
        for any cleanup.
    """
    source = Path(source_memory) if source_memory else LIVE_MEMORY_PATH
    source_episodes = source / "episodes"
    if not source_episodes.exists():
        raise FileNotFoundError(f"No episodes dir at {source_episodes}")

    root = Path(tempfile.mkdtemp(prefix=f"cicada_bench_{name}_"))
    (root / "episodes").mkdir()
    (root / "entities").mkdir()
    (root / "nudges").mkdir()
    (root / "clarifications").mkdir()

    src_files = sorted(source_episodes.glob("*.md"))
    if episode_limit is not None:
        src_files = src_files[:episode_limit]

    copied = 0
    for src in src_files:
        text = src.read_text(encoding="utf-8")
        text = _PROCESSED_RE.sub("processed: false", text, count=1)
        (root / "episodes" / src.name).write_text(text, encoding="utf-8")
        copied += 1

    _git_init(root)
    print(
        f"[workspace] {name}: {copied} episodes copied to {root}",
        file=sys.stderr,
    )
    return root


def destroy_workspace(path: Path) -> None:
    """Remove a workspace created by :func:`create_workspace`.

    Refuses to touch any path that doesn't look like a benchmark workspace
    as a last-line safety rail against accidentally nuking real data.
    """
    path = Path(path)
    if not path.exists():
        return
    if "cicada_bench_" not in path.name:
        raise RuntimeError(
            f"Refusing to destroy {path} — not a benchmark workspace"
        )
    shutil.rmtree(path, ignore_errors=True)


def _git_init(root: Path) -> None:
    """Initialize a standalone git repo at ``root`` with a seed commit."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "bench@cicada.local"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "cicada-bench"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "benchmark workspace seed"],
        cwd=root,
        check=True,
    )
