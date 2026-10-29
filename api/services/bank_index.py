"""Per-bank cache of parsed markdown frontmatter, keyed by (mtime_ns, size).

`/status`, `/origins` and the Sleep queue used to re-parse every episode and
entity file on every call (2–3k YAML parses, ~1–3 s). One ``os.scandir`` per
directory (~5 ms) now decides what changed; only changed files are re-parsed,
bodies are read lazily. The cache is process-local and disposable.
"""
from __future__ import annotations

import contextvars
import hashlib
import itertools
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from loguru import logger

from api.services import markdown_parser

parse_count = 0
_lock = threading.Lock()
# (bank path, subdir) -> {filename: IndexedFile}
_cache: dict[tuple[str, str], dict[str, "IndexedFile"]] = {}


@dataclass
class IndexedFile:
    """One file's cached header. ``frontmatter`` never holds an episode's ``turns`` sidecar (2026-10-16 perf: it was
    ~90 % of the cache and of a cold scan's parse time); ``has_turns`` says the file has one, and :func:`with_turns`
    reads it for the few readers that place a span in its turn."""
    path: Path
    mtime_ns: int
    size: int
    frontmatter: dict = field(default_factory=dict)
    has_turns: bool = False

    @cached_property
    def stem(self) -> str:
        # Cached: a read model keys every page and episode by it, per request (`Path.stem` is ~1 µs; 13k a request).
        return self.path.stem

    def body(self) -> str:
        """The file's body as ``markdown_parser.parse`` returns it (a page's ledger folded in). The frontmatter this
        entry holds is the file's own while its ``(mtime, size)`` is unchanged, so its YAML is not parsed a second
        time (2026-10-16 perf: a cold ``GET /graph`` parsed every page's frontmatter twice, ~0.9 s of 4.6 s at 4,701
        pages); a file that moved since it was listed is parsed whole, as before."""
        try:
            content = self.path.read_text(encoding="utf-8")
            st = os.stat(self.path)
        except OSError:
            return markdown_parser.parse(self.path).body
        if (st.st_mtime_ns, st.st_size) != (self.mtime_ns, self.size):
            return markdown_parser.parse(self.path).body
        return markdown_parser.body_of(self.path, content, self.frontmatter)


#: (bank, subdir) -> the cache's generation: a number from one process-wide counter, taken anew whenever the folder's
#: cached headers change (a file parsed, dropped, or the bank invalidated), so a value derived from one generation's
#: entries (:func:`derived`) is exact while the generation holds. Never reused, so a cleared cache never matches.
_GEN: dict[tuple[str, str], int] = {}
_GEN_COUNTER = itertools.count(1)
#: (bank, subdir) -> (the listing last reconciled with the cache, the generation that left). A listing is never mutated
#: once made, so the same object again (a `shared_scans` memo, the SSE tick's seeded walk) at the same generation needs
#: no second comparison of ~9k stamps (source page speed, 2026-10-29).
_LISTED: dict[tuple[str, str], tuple[dict, int]] = {}
#: (bank, subdir) -> (generation, the cached entries sorted by name): one sort per change, not per call.
_SORTED: dict[tuple[str, str], tuple[int, list]] = {}
#: (bank, subdir, name) -> (generation, value) for :func:`derived`.
_DERIVED: dict[tuple[str, str, str], tuple[int, object]] = {}


def _bump(key: tuple[str, str]) -> None:
    """The folder's cached headers changed: a new generation. Called under ``_lock``."""
    _GEN[key] = next(_GEN_COUNTER)


def invalidate(memory_path: Path | None = None) -> None:
    with _lock:
        if memory_path is None:
            _cache.clear()
            for key in list(_GEN):
                _bump(key)
        else:
            for key in [k for k in _cache if k[0] == str(memory_path)]:
                _cache.pop(key, None)
            for key in [k for k in _GEN if k[0] == str(memory_path)]:
                _bump(key)


#: Audit A10 — a per-tick memo of `_scan`, set only by `shared_scans()`. A ContextVar, not a thread-local: the SSE
#: ticker's version walk and its debt walk run in two `asyncio.to_thread` calls, which copy the caller's context, so
#: both see the same dict and `episodes/` is listed once per tick. Unset everywhere else: every other caller stays exact.
_SCAN_MEMO: contextvars.ContextVar[dict | None] = contextvars.ContextVar("bank_index_scan_memo", default=None)


@contextmanager
def shared_scans(seed: dict | None = None):
    """Within this block, each directory is listed and stat'ed once (audit A10). Yields the memo (directory ->
    listing), so a caller can keep what one block listed.

    ``seed``: listings to answer from without a ``scandir`` — only for a caller that KNOWS those directories have not
    changed since they were listed (the SSE tick, between file-change events: ``sync_ticker``). Ignored inside an
    outer block, which keeps its own memo."""
    outer = _SCAN_MEMO.get()
    token = _SCAN_MEMO.set(dict(seed or {})) if outer is None else None
    try:
        yield _SCAN_MEMO.get()
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
    ledgers: dict[str, tuple[int, int]] = {}
    try:
        with os.scandir(directory) as it:
            for entry in it:
                name = entry.name
                if name.endswith(".md"):
                    if entry.is_file():
                        st = entry.stat()
                        out[name] = (st.st_mtime_ns, st.st_size)
                elif name.endswith(LEDGER_SUFFIX) and entry.is_file():
                    st = entry.stat()
                    ledgers[name] = (st.st_mtime_ns, st.st_size)
    except OSError:
        # Missing, a plain file, unreadable: an empty listing, never a raise into
        # /sync/version or an ETag (the old max-mtime stamp's contract).
        pass
    with _lock:
        seen = _LEDGERS.setdefault(str(directory), [])
        seen.append((out, ledgers))
        del seen[:-_LEDGERS_KEPT]
    return out


#: ``claims_ledger.SUFFIX``: a page's claims past 64k characters (`entities/<id>.claims.jsonl`).
LEDGER_SUFFIX = ".claims.jsonl"
#: directory -> the last few (listing, {ledger file: (mtime_ns, size)}) the scan saw together. The same scan stats both,
#: so a listing shared under :func:`shared_scans` — or seeded from the SSE tick's walk — has its ledgers for free.
_LEDGERS: dict[str, list[tuple[dict, dict[str, tuple[int, int]]]]] = {}
_LEDGERS_KEPT = 4


def ledger_fingerprint(directory: Path) -> str:
    """The folder's claims ledgers as a change stamp (``""`` for none), seen by the same scan as its pages.

    A page write moves the page first and shrinks its ledger just after (``markdown_parser.write``: lines the ledger
    loses go after the page, so a crash never loses a claim). A read between the two folds a line the page now holds,
    and a cache keyed on the page's stamp alone would keep that read (review of #518). A key that holds this stamp
    moves when the ledger does."""
    listing = _scan(Path(directory))
    with _lock:
        ledgers = next((led for seen, led in _LEDGERS.get(str(directory), ()) if seen is listing), None)
    if ledgers is None:
        _scan_uncached(Path(directory))   # a listing too old to have its ledgers kept: read them now
        with _lock:
            ledgers = (_LEDGERS.get(str(directory)) or [({}, {})])[-1][1]
    return fingerprint((n, m, size) for n, (m, size) in ledgers.items()) if ledgers else ""


def files(memory_path: Path, subdir: str) -> list[IndexedFile]:
    """Return the cached, up-to-date ``IndexedFile`` list for ``subdir``.

    Parsing happens outside ``_lock`` so a cold scan (or a Sleep cycle's mass
    rewrite) doesn't serialise every other caller behind it — only the cheap
    bookkeeping (deciding what changed, storing results) holds the lock.
    Concurrent callers may both parse the same changed file; that's a wasted
    parse, never torn state, since each caller only stores what it itself
    parsed and only if the file hasn't moved again since.
    """
    return list(_files(memory_path, subdir)[0])


def _files(memory_path: Path, subdir: str) -> tuple[list[IndexedFile], int]:
    """:func:`files`' entries (a shared list: callers copy it) and the generation they belong to, read together."""
    global parse_count
    directory = Path(memory_path) / subdir
    key = (str(memory_path), subdir)
    current = _scan(directory)

    to_parse: list[tuple[str, int, int]] = []
    with _lock:
        if key not in _GEN:
            _bump(key)
        listed = _LISTED.get(key)
        if listed is not None and listed[0] is current and listed[1] == _GEN[key]:
            # The same listing, reconciled at this generation: nothing to compare (2026-10-29).
            return _SORTED[key][1], listed[1]
        known = _cache.setdefault(key, {})
        gone = [n for n in known if n not in current]
        for name in gone:
            known.pop(name)
        if gone:
            _bump(key)
        for name, (mtime_ns, size) in current.items():
            hit = known.get(name)
            if hit is not None and hit.mtime_ns == mtime_ns and hit.size == size:
                continue
            to_parse.append((name, mtime_ns, size))
        # `exact`: the cache will match this listing exactly once the parses below are stored — false when one is not
        # stored, or another caller changed the cache meanwhile (the generation moved under us).
        exact, mine = True, _GEN[key]

    for name, mtime_ns, size in to_parse:
        path = directory / name
        try:
            fm, has_turns = markdown_parser.header(path)
        except Exception as exc:  # malformed file: skip, never crash a caller
            logger.warning(f"bank_index: skipping malformed {path}: {exc}")
            with _lock:
                exact = False
                stale = _cache.get(key)
                if stale is not None and stale.pop(name, None) is not None:
                    _bump(key)
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
                store[name] = IndexedFile(path=path, mtime_ns=mtime_ns, size=size, frontmatter=fm,
                                          has_turns=has_turns)
                exact = exact and _GEN[key] == mine
                _bump(key)
                mine = _GEN[key]
            else:
                exact = False

    with _lock:
        gen = _GEN[key]
        held = _SORTED.get(key)
        if held is not None and held[0] == gen:
            entries = held[1]   # every change to the cache moves the generation: still its entries, sorted
        else:
            known = _cache.setdefault(key, {})
            entries = [known[n] for n in sorted(known)]
            _SORTED[key] = (gen, entries)
        # Remembered only when the cache now matches this listing exactly, so the same listing again skips the
        # comparison; a file that moved while it was parsed, or a change another caller made, is compared next time.
        if exact and gen == mine:
            _LISTED[key] = (current, gen)
        return entries, gen


def derived(memory_path: Path, subdir: str, name: str, build):
    """``build(entries)`` over :func:`files`' entries for ``subdir``, kept until that folder's cached headers change —
    a per-folder index a read model would otherwise rebuild per request (e.g. ``channel_items``' episodes by origin:
    one source's list in time proportional to its items, 2026-10-29). ``build`` gets the entries (shared: never
    mutate them) and returns a value its callers treat as read-only. ``name`` keys it; process-local and disposable."""
    entries, gen = _files(memory_path, subdir)
    slot = (str(memory_path), subdir, name)
    with _lock:
        hit = _DERIVED.get(slot)
    if hit is not None and hit[0] == gen:
        return hit[1]
    value = build(entries)
    with _lock:
        _DERIVED[slot] = (gen, value)
    return value


def stamps(memory_path: Path, subdir: str, *, fresh: bool = False) -> dict[str, tuple[int, int]]:
    """``{filename: (mtime_ns, size)}`` for ``subdir``'s ``*.md`` files: one scandir, no parse.

    What a caller that needs to know *which* files exist and whether they moved — a freshness check, a
    name lookup — reads instead of :func:`files`, which parses every file it has not cached (the whole
    directory in a fresh process: ~2.4 s for ~5,900 files). ``fresh`` lists the directory now, ignoring
    a :func:`shared_scans` memo: a caller that compares the listing with state read LATER than the memo
    (the FTS index's stamps) must never hold a listing older than that state."""
    directory = Path(memory_path) / subdir
    return dict(_scan_uncached(directory) if fresh else _scan(directory))


def file(memory_path: Path, subdir: str, name: str) -> IndexedFile | None:
    """One file's cached entry, parsing only that file when its ``(mtime, size)`` moved or it was never
    read. ``name`` is the on-disk filename (``<stem>.md``); a missing or malformed file is ``None``.

    Shares :func:`files`' cache, so a long-lived process that has listed the directory answers from it,
    and a fresh one parses the one page a read needs instead of all of them. It reads the header exactly as
    :func:`files` does (``markdown_parser.header``): never a page's claims ledger, never the fold's read mark —
    :meth:`IndexedFile.body` folds the ledger only when a caller asks for the body."""
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
        fm, has_turns = markdown_parser.header(path)   # the cache never holds the sidecar (`IndexedFile`)
    except Exception as exc:  # malformed file: skip, never crash a caller
        logger.warning(f"bank_index: skipping malformed {path}: {exc}")
        return None
    entry = IndexedFile(path=path, mtime_ns=stamp[0], size=stamp[1], frontmatter=fm, has_turns=has_turns)
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
            _bump(key)
    return entry


def with_turns(entry: IndexedFile | None) -> dict:
    """``entry``'s frontmatter WITH its ``turns`` sidecar — what ``evidence.turn_stamps`` and ``agent_turns.stamps``
    read — parsed from the file (a small memo keyed on its stamp, so a request placing many spans in one episode
    parses it once). The cached header itself when the file has no sidecar; ``{}`` for no entry."""
    if entry is None:
        return {}
    if not entry.has_turns:
        return entry.frontmatter
    key = str(entry.path)
    hit = _TURNS.get(key)
    if hit is not None and hit[0] == (entry.mtime_ns, entry.size):
        return {**entry.frontmatter, "turns": hit[1]}
    try:
        full = markdown_parser.parse(entry.path, ledger=False).frontmatter
    except Exception:  # noqa: BLE001 — gone or unreadable since it was listed: no sidecar, as for a malformed one
        return entry.frontmatter
    turns = full.get("turns") if isinstance(full, dict) else None
    with _lock:
        while len(_TURNS) >= _TURNS_MAX:
            _TURNS.pop(next(iter(_TURNS)))
        _TURNS[key] = ((entry.mtime_ns, entry.size), turns)
    return {**entry.frontmatter, "turns": turns}


#: path -> ((mtime_ns, size), turns) for :func:`with_turns`, bounded.
_TURNS: dict[str, tuple[tuple[int, int], object]] = {}
_TURNS_MAX = 64


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
    key = str(directory)
    hit = _FINGERPRINTS.get(key)
    if hit is not None and hit[0] is current:   # the same listing object (a memo's): the same fingerprint
        return hit[1]
    stamp = fingerprint((name, m, size) for name, (m, size) in current.items())
    _FINGERPRINTS[key] = (current, stamp)
    return stamp


#: directory -> (the listing last fingerprinted, its fingerprint). A listing is never mutated once made, so the same
#: object — what a `shared_scans` memo seeded across SSE ticks hands back — needs no second hash (2026-10-16 perf).
_FINGERPRINTS: dict[str, tuple[dict, str]] = {}


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
