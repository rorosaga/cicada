"""Per-bank cache of parsed markdown frontmatter, keyed by (mtime_ns, size).

`/status`, `/origins` and the Sleep queue used to re-parse every episode and
entity file on every call (2–3k YAML parses, ~1–3 s). One ``os.scandir`` per
directory (~5 ms) now decides what changed; only changed files are re-parsed,
bodies are read lazily. The cache is process-local and disposable.
"""
from __future__ import annotations

import contextvars
import hashlib
import os
import threading
from contextlib import contextmanager
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


#: Audit A10 — a per-tick memo of `_scan`, set only by `shared_scans()`. A ContextVar, not a thread-local: the SSE
#: ticker's version walk and its debt walk run in two `asyncio.to_thread` calls, which copy the caller's context, so
#: both see the same dict and `episodes/` is listed once per tick. Unset everywhere else: every other caller stays exact.
_SCAN_MEMO: contextvars.ContextVar[dict | None] = contextvars.ContextVar("bank_index_scan_memo", default=None)


@contextmanager
def shared_scans():
    """Within this block, each directory is listed and stat'ed once (audit A10)."""
    token = _SCAN_MEMO.set({}) if _SCAN_MEMO.get() is None else None
    try:
        yield
    finally:
        if token is not None:
            _SCAN_MEMO.reset(token)


def _scan(directory: Path) -> dict[str, tuple[int, int]]:
    memo = _SCAN_MEMO.get()
    if memo is not None:
        key = str(directory)
        if key not in memo:
            memo[key] = _scan_uncached(directory)
        return memo[key]
    return _scan_uncached(directory)


def _scan_uncached(directory: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.is_file() and entry.name.endswith(".md"):
                    st = entry.stat()
                    out[entry.name] = (st.st_mtime_ns, st.st_size)
    except OSError:
        # Missing, a plain file, unreadable: an empty listing, never a raise into
        # /sync/version or an ETag (the old max-mtime stamp's contract).
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


def stamps(memory_path: Path, subdir: str) -> dict[str, tuple[int, int]]:
    """``{filename: (mtime_ns, size)}`` for ``subdir``'s ``*.md`` files: one scandir, no parse.

    What a caller that needs to know *which* files exist and whether they moved — a freshness check, a
    name lookup — reads instead of :func:`files`, which parses every file it has not cached (the whole
    directory in a fresh process: ~2.4 s for ~5,900 files)."""
    return dict(_scan(Path(memory_path) / subdir))


def file(memory_path: Path, subdir: str, name: str) -> IndexedFile | None:
    """One file's cached entry, parsing only that file when its ``(mtime, size)`` moved or it was never
    read. ``name`` is the on-disk filename (``<stem>.md``); a missing or malformed file is ``None``.

    Shares :func:`files`' cache, so a long-lived process that has listed the directory answers from it,
    and a fresh one parses the one page a read needs instead of all of them."""
    global parse_count
    directory = Path(memory_path) / subdir
    path = directory / name
    try:
        st = os.stat(path)
    except OSError:
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    key = (str(memory_path), subdir)
    with _lock:
        hit = _cache.get(key, {}).get(name)
        if hit is not None and (hit.mtime_ns, hit.size) == stamp:
            return hit
    try:
        fm = markdown_parser.parse(path).frontmatter
    except Exception as exc:  # malformed file: skip, never crash a caller
        logger.warning(f"bank_index: skipping malformed {path}: {exc}")
        return None
    entry = IndexedFile(path=path, mtime_ns=stamp[0], size=stamp[1], frontmatter=fm)
    with _lock:
        try:
            st = os.stat(path)
            stamp_now = (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            stamp_now = None
        if stamp_now == stamp:
            # A partial directory cache is safe: `files()` parses whatever it lacks, and `is_warm`
            # compares the whole listing, so one entry never reads as "the directory is warm".
            parse_count += 1
            _cache.setdefault(key, {})[name] = entry
    return entry


def dir_stamp(memory_path: Path, subdir: str) -> tuple[int, int]:
    """(file count, max mtime_ns) — a cheap change stamp, no parsing."""
    current = _scan(Path(memory_path) / subdir)
    return len(current), max((m for m, _ in current.values()), default=0)


def fingerprint(entries) -> str:
    """``<count>.<hash>`` over ``(name, mtime_ns, size)`` rows — moves when any
    row is added, removed, renamed, resized or re-stamped. No ``:`` in it, so a
    component that appends ``:<extra>`` stays parseable."""
    h = hashlib.blake2b(digest_size=8)
    n = 0
    for name, mtime_ns, size in sorted(entries):
        h.update(f"{name}\0{mtime_ns}\0{size}\n".encode("utf-8", errors="surrogatepass"))
        n += 1
    return f"{n}.{h.hexdigest()}"


def dir_fingerprint(directory: Path) -> str:
    """A directory's ``*.md`` files as a change stamp (audit 2026-10-05 P2-9).

    "The newest mtime" missed an edit whenever any other file was dated later
    — a future-dated file, a clock that stepped back — so a version or an ETag
    built on it never moved. This fingerprints every file's name, size and
    nanosecond mtime instead, from the same scan everything else uses (one per
    directory per SSE tick under :func:`shared_scans`, audit A10). No parse."""
    current = _scan(Path(directory))
    return fingerprint((name, m, size) for name, (m, size) in current.items())


def is_warm(memory_path: Path, subdir: str) -> bool:
    """True when :func:`files` would answer from the cache without parsing a
    file: the subdir is cached and every file's (mtime, size) still matches its
    entry. One directory scan, no parse — the recall hook asks it so a cold
    cache never blows the hook's budget."""
    directory = Path(memory_path) / subdir
    with _lock:
        known = _cache.get((str(memory_path), subdir))
        if known is None:
            return False
        held = {n: (f.mtime_ns, f.size) for n, f in known.items()}
    return _scan(directory) == held
