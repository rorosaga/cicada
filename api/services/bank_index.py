"""Per-bank cache of parsed markdown frontmatter, keyed by (mtime_ns, size).

`/status`, `/origins` and the Sleep queue used to re-parse every episode and
entity file on every call (2–3k YAML parses, ~1–3 s). One ``os.scandir`` per
directory (~5 ms) now decides what changed; only changed files are re-parsed,
bodies are read lazily. The cache is process-local and disposable.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from api.services import markdown_parser

parse_count = 0
_lock = threading.Lock()
# (bank path, subdir) -> {filename: IndexedFile}
_cache: dict[tuple[str, str], dict[str, "IndexedFile"]] = {}


@dataclass
class IndexedFile:
    path: Path
    mtime_ns: int
    size: int
    frontmatter: dict = field(default_factory=dict)

    @property
    def stem(self) -> str:
        return self.path.stem

    def body(self) -> str:
        return markdown_parser.parse(self.path).body


def invalidate(memory_path: Path | None = None) -> None:
    with _lock:
        if memory_path is None:
            _cache.clear()
        else:
            for key in [k for k in _cache if k[0] == str(memory_path)]:
                _cache.pop(key, None)


def _scan(directory: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.is_file() and entry.name.endswith(".md"):
                    st = entry.stat()
                    out[entry.name] = (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        pass
    return out


def files(memory_path: Path, subdir: str) -> list[IndexedFile]:
    """Return the cached, up-to-date ``IndexedFile`` list for ``subdir``.

    Parsing happens outside ``_lock`` so a cold scan (or a Sleep cycle's mass
    rewrite) doesn't serialise every other caller behind it — only the cheap
    bookkeeping (deciding what changed, storing results) holds the lock.
    Concurrent callers may both parse the same changed file; that's a wasted
    parse, never torn state, since each caller only stores what it itself
    parsed and only if the file hasn't moved again since.
    """
    global parse_count
    directory = Path(memory_path) / subdir
    key = (str(memory_path), subdir)
    current = _scan(directory)

    to_parse: list[tuple[str, int, int]] = []
    with _lock:
        known = _cache.setdefault(key, {})
        for name in [n for n in known if n not in current]:
            known.pop(name)
        for name, (mtime_ns, size) in current.items():
            hit = known.get(name)
            if hit is not None and hit.mtime_ns == mtime_ns and hit.size == size:
                continue
            to_parse.append((name, mtime_ns, size))

    for name, mtime_ns, size in to_parse:
        path = directory / name
        try:
            fm = markdown_parser.parse(path).frontmatter
        except Exception as exc:  # malformed file: skip, never crash a caller
            logger.warning(f"bank_index: skipping malformed {path}: {exc}")
            with _lock:
                stale = _cache.get(key)
                if stale is not None:
                    stale.pop(name, None)
            continue
        with _lock:
            store = _cache.setdefault(key, {})
            # The file may have changed again since we scanned/parsed it — in
            # that case leave the cache alone (stale or absent) and let the
            # next call pick up the newer copy rather than storing data that
            # no longer matches what's on disk.
            try:
                st = os.stat(path)
                stamp_now = (st.st_mtime_ns, st.st_size)
            except FileNotFoundError:
                stamp_now = None
            if stamp_now == (mtime_ns, size):
                parse_count += 1
                store[name] = IndexedFile(path=path, mtime_ns=mtime_ns, size=size, frontmatter=fm)

    with _lock:
        known = _cache.setdefault(key, {})
        return [known[n] for n in sorted(known)]


def dir_stamp(memory_path: Path, subdir: str) -> tuple[int, int]:
    """(file count, max mtime_ns) — a cheap change stamp, no parsing."""
    current = _scan(Path(memory_path) / subdir)
    return len(current), max((m for m, _ in current.values()), default=0)
