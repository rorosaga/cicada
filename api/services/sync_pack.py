"""The home's pack: the git objects a replica lacks, as a bundle (G132 phase 1, ruling 51a).

``have`` is the newest commit a replica holds (a published sha, ``sync_log``); the pack is ``have..HEAD`` — or the
whole history for a first copy. ``git bundle create`` is read-only on the bank: no ref, no index, no lock, no working
tree file. A bundle carries only committed objects, so an untracked file, the derived indexes (``vector_index.db``,
``search_index.db``, kept out of git by ``.git/info/exclude``) and the capture markers never travel.

The bundle is written to a private temporary folder outside every bank (0700), capped at :data:`MAX_BYTES`
(``CICADA_SYNC_PACK_MAX_MB``), served once and removed. Only its size and seq are logged.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from api.services import sync_log

MAX_BYTES = int(os.environ.get("CICADA_SYNC_PACK_MAX_MB", "2048") or "2048") * 1024 * 1024
_TIMEOUT_S = 600


class UnknownBase(Exception):
    """``have`` is not a commit this home published."""


class TooLarge(Exception):
    pass


@dataclass
class Pack:
    path: Path | None      # None: nothing new since ``have``
    folder: Path | None
    seq: int
    sha: str
    size: int

    def cleanup(self) -> None:
        if self.folder is not None:
            shutil.rmtree(self.folder, ignore_errors=True)


def build(memory_path, have: str | None = None) -> Pack:
    """The bundle for ``have..HEAD`` (``have`` None: the whole history). Raises :class:`UnknownBase`,
    :class:`TooLarge`, ``sync_log.HistoryRewritten`` or ``sync_log.Unavailable``."""
    mp = Path(memory_path)
    head = sync_log.update(mp)
    have_sha = None
    if have:
        seq = sync_log.seq_of(mp, have)
        if seq is None:
            raise UnknownBase()
        have_sha = _full(mp, have)
        if have_sha == head.sha:
            return Pack(None, None, head.seq, head.sha, 0)
    if not head.sha:
        return Pack(None, None, 0, "", 0)
    folder = Path(tempfile.mkdtemp(prefix="cicada-pack-"))
    os.chmod(folder, 0o700)
    out = folder / "pack.bundle"
    try:
        # A commit that lands meanwhile rides in under HEAD; the seq answered is the bundle's own head, read back and
        # published (``seq_of`` catches the log up), never the head read before.
        args = ["git", "bundle", "create", "-q", str(out), "HEAD"]
        if have_sha:
            args.append(f"^{have_sha}")
        proc = subprocess.run(args, cwd=str(mp), capture_output=True, timeout=_TIMEOUT_S)
        if proc.returncode != 0:
            raise sync_log.Unavailable()
        bundled = _bundle_head(mp, out)
        seq = sync_log.seq_of(mp, bundled) if bundled else None
        if seq is None:
            raise sync_log.Unavailable()
        size = out.stat().st_size
        if size > MAX_BYTES:
            raise TooLarge()
        logger.info(f"sync pack: seq {seq}, {size} bytes{' (first copy)' if not have_sha else ''}")
        return Pack(out, folder, seq, bundled, size)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def _full(memory_path: Path, sha: str) -> str:
    proc = subprocess.run(["git", "rev-parse", "--verify", "-q", f"{sha}^{{commit}}"], cwd=str(memory_path),
                          capture_output=True, timeout=30)
    if proc.returncode != 0:
        raise UnknownBase()
    return proc.stdout.decode().strip()


def _bundle_head(memory_path: Path, bundle: Path) -> str | None:
    proc = subprocess.run(["git", "bundle", "list-heads", str(bundle)], cwd=str(memory_path), capture_output=True,
                          timeout=60)
    for line in proc.stdout.decode(errors="replace").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == "HEAD":
            return parts[0]
    return None
