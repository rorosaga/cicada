import contextvars
import datetime
import errno
import os
import pickle
import re
import secrets
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import yaml

# The fences `write` emits: `---` alone on the first line, then `---` alone on a
# later line. L final review (finding 2): the old `content.split("---", 2)` cut
# at the first two `---` ANYWHERE, so a frontmatter value holding one — a folder
# file's relpath or H2 heading, a meeting title, a chat title — split mid-scalar
# and raised a YAML ScannerError. `bank_index` then skipped the episode as
# malformed, the stager never saw it, and every later edit minted another
# unreadable copy. Anchored to whole lines, the split is exact for every writer.
# The frontmatter group is optional so an empty block (`---\n---`) still parses.
_FENCED = re.compile(r"---[ \t]*\r?\n(?:(.*?)\r?\n)?---[ \t]*(?:\r?\n|$)(.*)", re.S)


# libyaml's C parser when PyYAML was built with it, else the pure-Python one.
# Both are the SAFE loader (same SafeConstructor, same output as safe_load);
# only the scanner differs. Why it matters: G118 slice 2 (R-PB4) writes a
# per-message `turns: [{offset, ts, speaker}]` list into imported episodes'
# frontmatter, and a 20-entry list costs ~1.35 ms per parse in pure Python vs
# ~0.15 ms without it. Every full episode scan pays that — measured on 2,000
# imported episodes, `sleep_cycle.list_all_episodes` went 0.41 s -> 2.88 s and
# `transcript_capture._find_session_episode` 0.38 s -> 2.99 s, against the Stop
# hook's 3 s timeout. With CSafeLoader the same scan is ~0.42 s (final review).
# `write` keeps `yaml.dump`: a different emitter would reformat pages already
# in a bank's git history, and writes are not on a scan path.
_SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def load_yaml(text: str):
    """``yaml.safe_load`` on the libyaml scanner when PyYAML has it — same constructor, same output, raises the same
    ``YAMLError``. For a bank file read whole on a hot path: `graph_edges.yaml` grows with the claims (3.7 MB, 35k
    edges on a 2,000-page synthetic bank) and costs ~3.8 s in pure Python against ~0.9 s here."""
    return yaml.load(text, Loader=_SAFE_LOADER)  # noqa: S506 — a SAFE loader


#: path -> ((st_ino, st_mtime_ns, st_size), pickled data): what :func:`load_yaml_file` parsed or :func:`write_yaml`
#: wrote, held as one pickle (a few MB for a 36k-edge ``graph_edges.yaml``, against ~30 MB of live objects).
_yaml_files: dict[str, tuple[tuple[int, int, int], bytes]] = {}
_yaml_files_lock = threading.Lock()


def _file_stamp(path: Path) -> tuple[int, int, int]:
    st = os.stat(path)
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def load_yaml_file(filepath: Path):
    """:func:`load_yaml` of a whole YAML file, parsed once per change of the file (2026-10-16 perf). One Sleep batch
    reads ``graph_edges.yaml`` (~5 MB, 36k edges at owner scale: ~1.1 s a parse) about five times, each read but the
    first straight after another step's :func:`write_yaml` — which leaves what it wrote here, so the next read is a
    copy, not a parse. Every caller gets its own copy (a pickle round trip, ~30 ms for that file), so a caller that
    edits what it read never edits what the next one sees. Keyed on the file's inode, mtime and size: any write — a
    replace, an in-place rewrite, a ``git checkout`` — is parsed afresh. Raises what reading and parsing raise."""
    path = Path(filepath)
    stamp = _file_stamp(path)
    with _yaml_files_lock:
        hit = _yaml_files.get(str(path))
    if hit is not None and hit[0] == stamp:
        return pickle.loads(hit[1])
    text = path.read_text(encoding="utf-8")
    data = load_yaml(text)
    try:
        if _file_stamp(path) == stamp:   # unchanged while it was read: the parse is this stamp's
            with _yaml_files_lock:
                _yaml_files[str(path)] = (stamp, pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL))
    except (OSError, pickle.PicklingError):
        pass
    return data


_SAFE_DUMPER = getattr(yaml, "CSafeDumper", yaml.SafeDumper)


def write_yaml(filepath: Path, data) -> None:
    """Write a whole YAML file atomically: a temp file beside it, fsynced, then ``os.replace``d over it (the page
    rule, :func:`write`). For ``graph_edges.yaml`` (~4 MB on a real bank, four writers): ``write_text`` truncated
    first, so a write cut short left a torn file — unreadable, or worse, one that parses as a shorter file and loses
    its tail edges. A reader now sees the old file or the new one. Dumped by the libyaml safe dumper when PyYAML has
    it: for plain rows the same text ``yaml.dump`` writes, except that a character outside the Basic Multilingual Plane
    (an emoji) is written escaped (``"\U0001F389"``) — the first write after the change rewrites such a line once.
    The safe dumper refuses a value that is not a plain YAML type rather than writing a ``!!python/`` tag the safe
    loader could not read back."""
    text = yaml.dump(data, Dumper=_SAFE_DUMPER, default_flow_style=False, sort_keys=False, allow_unicode=True)
    path = Path(filepath)
    with _yaml_files_lock:
        _yaml_files.pop(str(path), None)
    stamp = _replace(path, text.encode("utf-8"))
    # What was written is what a parse of it returns (the safe dumper writes only plain YAML types, and quotes a
    # string that would read back as another type), so the next :func:`load_yaml_file` is a copy, not a parse. The
    # stamp is the written file's own (taken before its rename), never a later writer's.
    try:
        snapshot = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
    except pickle.PicklingError:
        return
    with _yaml_files_lock:
        _yaml_files[str(path)] = (stamp, snapshot)


@dataclass
class ParsedMarkdown:
    frontmatter: dict = field(default_factory=dict)
    body: str = ""


def split_frontmatter(content: str) -> tuple[str, str] | None:
    """`(frontmatter_text, body)` for a fenced document, else None.

    Line-anchored fences first (`_FENCED`); a file that starts with `---` but
    has no closing fence on its own line — hand-written, never ours — keeps the
    old first-two-`---` split, so nothing that parsed before stops parsing.
    """
    if not content.startswith("---"):
        return None
    m = _FENCED.match(content)
    if m:
        return (m.group(1) or ""), m.group(2)
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None
    return parts[1], parts[2]


class PageCache:
    """One Sleep batch's page parses (2026-10-16 perf, owner decision 1): every step of a batch re-reads the pages,
    ~19 whole-bank reads a batch at owner scale, nearly all of files no step has written since. Opened by
    :func:`page_cache` around one batch and dropped when it ends — never across batches, never for another bank.

    An entry is keyed on the file's path and serves only while the file's own (inode, mtime_ns, size) is unchanged —
    and, for a page whose claims overflowed into a ledger, the ledger's too (absent counts as a stamp) — the
    discipline of ``load_yaml_file`` (#324). Every write through this module drops its path first (:func:`_forget`),
    and a writer's admission ending (``write_admission``) empties the cache of its bank, so neither Sleep's own writes
    nor anything admitted between its steps is served stale. Each caller gets its own frontmatter (a pickle round
    trip); the body is a ``str``."""

    __slots__ = ("roots", "entries", "lock", "hits", "misses", "closed")

    def __init__(self, root) -> None:
        given = os.path.abspath(os.fspath(root))
        real = os.path.realpath(given)
        self.roots = tuple({given.rstrip(os.sep) + os.sep, real.rstrip(os.sep) + os.sep})
        #: abspath -> {ledger flag: (stamp, ledger path | None, ledger stamp, pickled frontmatter, body)}
        self.entries: dict[str, dict[bool, tuple]] = {}
        self.lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        #: Set when the batch ends. A task or worker thread that copied the batch's context and outlives it (a
        #: cancelled batch's thread, a task it spawned) then parses uncached: a closed cache is out of the registry,
        #: so no write would ever reach it again.
        self.closed = False

    def covers(self, path: str) -> bool:
        return path.startswith(self.roots)

    def clear(self) -> None:
        with self.lock:
            self.entries.clear()


#: The batch's cache in the task (and the worker threads ``asyncio.to_thread`` starts, which copy the context).
_page_cache_var: contextvars.ContextVar["PageCache | None"] = contextvars.ContextVar("page_cache", default=None)
#: Every open cache, so a write from any thread or task of this process reaches it.
_open_caches: set = set()
_open_caches_lock = threading.Lock()


@contextmanager
def page_cache(root) -> Iterator[PageCache]:
    """Serve :func:`parse` of files under ``root`` from a stat-checked cache for the length of the block (one Sleep
    batch). Only this context (and threads it starts with a copied context) reads through it; the memory is freed on
    exit, whichever way the block ends."""
    cache = PageCache(root)
    token = _page_cache_var.set(cache)
    with _open_caches_lock:
        _open_caches.add(cache)
    try:
        yield cache
    finally:
        cache.closed = True
        with _open_caches_lock:
            _open_caches.discard(cache)
        _page_cache_var.reset(token)
        cache.clear()


def invalidate_pages(root=None) -> None:
    """Empty every open page cache (of ``root``'s bank only, when given) — a writer outside this module's write path
    finished (``write_admission``'s release), so nothing it touched is served from before it."""
    with _open_caches_lock:
        caches = list(_open_caches)
    if root is not None:
        probe = os.path.abspath(os.fspath(root)).rstrip(os.sep) + os.sep
        real = os.path.realpath(probe.rstrip(os.sep)).rstrip(os.sep) + os.sep
        caches = [c for c in caches if probe in c.roots or real in c.roots]
    for cache in caches:
        cache.clear()


def _forget(filepath) -> None:
    """Drop ``filepath`` from every open page cache — called before any write through this module lands."""
    if not _open_caches:
        return
    with _open_caches_lock:
        caches = list(_open_caches)
    path = os.path.abspath(os.fspath(filepath))
    for cache in caches:
        with cache.lock:
            cache.entries.pop(path, None)


def _stamp_or_none(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def parse(filepath: Path, *, ledger: bool = True) -> ParsedMarkdown:
    """Parse a markdown file with YAML frontmatter delimited by --- fences.

    An entity page whose claims overflowed into its ledger (``claims_ledger``) comes back with the ledger's claims
    folded into its fence, so every reader sees the page's whole claim set. ``ledger=False`` — a frontmatter-only
    scan — never opens the ledger (the body is then the page file's own).

    Inside :func:`page_cache` (one Sleep batch), a file unchanged since its last parse is a copy, not a parse."""
    cache = _page_cache_var.get()
    if cache is not None and not cache.closed:
        path = os.path.abspath(os.fspath(filepath))
        if cache.covers(path):
            return _parse_cached(cache, filepath, path, ledger)
    return _parse(filepath, ledger=ledger)


def _parse_cached(cache: PageCache, filepath: Path, path: str, ledger: bool) -> ParsedMarkdown:
    stamp = _stamp_or_none(path)
    if stamp is not None:
        with cache.lock:
            hit = cache.entries.get(path, {}).get(ledger)
        if hit is not None and hit[0] == stamp and (hit[1] is None or _stamp_or_none(hit[1]) == hit[2]):
            cache.hits += 1
            return ParsedMarkdown(frontmatter=pickle.loads(hit[3]), body=hit[4])
    cache.misses += 1
    ledger_path = ledger_stamp = None
    if ledger and stamp is not None:
        from api.services import claims_ledger

        if claims_ledger.is_page(Path(path)):
            ledger_path = os.fspath(claims_ledger.path_for(Path(path)))
            ledger_stamp = _stamp_or_none(ledger_path)   # taken BEFORE the read: a later change re-parses
    parsed = _parse(filepath, ledger=ledger)
    if stamp is None or not isinstance(parsed.frontmatter, dict):
        return parsed
    try:
        if _stamp_or_none(path) != stamp:   # moved while it was read: the parse may be either version's
            return parsed
        snapshot = pickle.dumps(parsed.frontmatter, protocol=pickle.HIGHEST_PROTOCOL)
    except (pickle.PicklingError, TypeError, AttributeError):
        return parsed
    with cache.lock:
        cache.entries.setdefault(path, {})[ledger] = (stamp, ledger_path, ledger_stamp, snapshot, parsed.body)
    return parsed


def _parse(filepath: Path, *, ledger: bool = True) -> ParsedMarkdown:
    content = filepath.read_text(encoding="utf-8")
    split = split_frontmatter(content)
    if split is None:
        return ParsedMarkdown(body=content)

    fm = yaml.load(split[0].strip(), Loader=_SAFE_LOADER) or {}
    _normalize_dates(fm)
    body = split[1].strip()
    if ledger and isinstance(fm, dict) and _LEDGER_STAMP in fm:
        from api.services import claims_ledger

        if claims_ledger.is_page(filepath):
            body = claims_ledger.fold(filepath, fm, body).strip()
    return ParsedMarkdown(frontmatter=fm, body=body)


_LEDGER_STAMP = "claims_ledger"   # `claims_ledger.STAMP`, spelled here so a plain parse imports nothing

#: An episode's per-message ``turns: [{offset, ts, speaker, …}]`` sidecar (R-PB4), a top-level key its writers keep
#: last. ``header`` parses a frontmatter without it.
_TURNS_LINE = re.compile(r"^turns:[ \t]*(.*)$", re.M)


def header(filepath: Path) -> tuple[dict, bool]:
    """A file's frontmatter WITHOUT its ``turns`` sidecar, and whether it had one — for a cache of every episode's
    header (``bank_index``), which the sidecar would otherwise dominate (2026-10-16 perf: 99,844 rows, 53 MB and
    3.6 s of a cold parse over 3,850 synthetic episodes; 5.5 MB and 0.5 s without). Every other key is exactly what
    :func:`parse` returns; a reader that needs the sidecar parses the file (``bank_index.with_turns``)."""
    return header_of(filepath.read_text(encoding="utf-8"))


def header_of(content: str) -> tuple[dict, bool]:
    split = split_frontmatter(content)
    if split is None:
        return {}, False
    text = split[0]
    match = _TURNS_LINE.search(text)
    if match is None:
        fm = yaml.load(text.strip(), Loader=_SAFE_LOADER) or {}
        _normalize_dates(fm)
        return fm, False
    # The block runs to the next line that opens another top-level key: a block sequence's `- ` items sit at column
    # 0 or deeper, every continuation is indented, and a blank line belongs to it.
    end = len(text)
    i = text.find("\n", match.start())
    i = len(text) if i == -1 else i + 1
    while i < len(text):
        j = text.find("\n", i)
        j = len(text) if j == -1 else j
        line = text[i:j]
        if line.strip() and line[0] not in " \t-":
            end = i
            break
        i = j + 1
    cut = text[:match.start()] + text[end:]
    try:
        fm = yaml.load(cut.strip(), Loader=_SAFE_LOADER) or {}
    except yaml.YAMLError:
        fm = None
    if not isinstance(fm, dict):   # an unusual layout: the whole parse, the sidecar dropped after
        fm = yaml.load(text.strip(), Loader=_SAFE_LOADER) or {}
    if isinstance(fm, dict):
        fm.pop("turns", None)
        _normalize_dates(fm)
    return fm, True


def body_of(filepath: Path, content: str, frontmatter: dict) -> str:
    """``parse(filepath).body`` for ``content`` already read, given the frontmatter already parsed from that same
    content (``bank_index``'s cached entry) — the split and the ledger fold, without a second YAML parse. The fold's
    read mark goes on a copy, never on the caller's dict."""
    split = split_frontmatter(content)
    if split is None:
        return content
    body = split[1].strip()
    if isinstance(frontmatter, dict) and _LEDGER_STAMP in frontmatter:
        from api.services import claims_ledger

        if claims_ledger.is_page(filepath):
            body = claims_ledger.fold(filepath, dict(frontmatter), body).strip()
    return body


def _split_ledger(filepath: Path, frontmatter: dict, body: str) -> tuple[dict, str, bytes | None]:
    """An entity page's write: the claims its ledger holds, and the oldest of an over-budget fence, go to the ledger
    (``claims_ledger.split``); every other file is written as given."""
    from api.services import claims_ledger

    if not claims_ledger.is_page(filepath):
        return frontmatter, body, None
    return claims_ledger.split(filepath, frontmatter, body)


def _render(frontmatter: dict, body: str) -> bytes:
    fm_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{fm_str}\n---\n\n{body}\n".encode("utf-8")


def _stage(target: Path, data: bytes) -> str:
    """The whole document in a hidden sibling temp file, fsynced (audit A02).

    ``.<name>.<random>.tmp`` never matches a ``*.md`` scan. Created with mode
    ``0o666`` so the umask applies exactly as it did for ``Path.write_text``.
    A failed write removes the temp file and re-raises."""
    tmp = str(target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp"))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        _unlink_quietly(tmp)
        raise
    return tmp


def _unlink_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def write(filepath: Path, frontmatter: dict, body: str) -> None:
    """Write a markdown file with YAML frontmatter — atomically (audit A02).

    ``Path.write_text`` truncated the destination first, so an interrupted
    write (a full disk, a killed process, a body that cannot be encoded) left
    an empty or torn page where the old one was. The document is staged in a
    temp file beside it and ``os.replace``d over it, so a reader sees the old
    page or the new one, never half of either. An existing page keeps its
    permission bits; a symlinked page is replaced at its target, so the link
    survives as it did with ``write_text``. The file is fsynced; the directory
    is not (the guarantee is "never a torn page", not "the rename survives a
    power cut").

    An entity page's claims are split with its ledger (``claims_ledger``): lines the ledger gains are written before
    the page and lines it loses after it (``claims_ledger.write_plan``), so a crash between the two leaves a claim in
    both files, never in neither."""
    frontmatter, body, ledger = _split_ledger(Path(filepath), frontmatter, body)
    before = after = None
    if ledger is not None:
        from api.services import claims_ledger

        before, after = claims_ledger.write_plan(filepath, ledger)
        if before:
            _replace(claims_ledger.path_for(filepath), before)
    _replace(filepath, _render(frontmatter, body))
    if after == b"":   # the writer kept no line in the ledger: the page holds them all now
        _unlink_quietly(str(claims_ledger.path_for(filepath)))
    elif after:
        _replace(claims_ledger.path_for(filepath), after)


def write_document(filepath: Path, text: str) -> None:
    """Replace a page with ``text`` exactly as given — atomically, like :func:`write`, but without re-rendering the
    frontmatter. For a writer whose change must leave every other byte of the page as it was (G148's recovery)."""
    _replace(filepath, text.encode("utf-8"))


def _replace(filepath: Path, data: bytes) -> tuple[int, int, int]:
    """Atomically replace ``filepath`` with ``data``. Returns the written file's own (inode, mtime_ns, size), taken
    from the staged file before the rename (which keeps both), so a caller that caches on it never stamps another
    writer's file that replaced this one a moment later."""
    target = Path(os.path.realpath(filepath)) if os.path.islink(filepath) else Path(filepath)
    _forget(filepath)
    if target != Path(filepath):
        _forget(target)
    tmp = _stage(target, data)
    try:
        try:
            os.chmod(tmp, os.stat(target).st_mode & 0o7777)
        except FileNotFoundError:
            pass
        st = os.stat(tmp)
        os.replace(tmp, target)
    except BaseException:
        _unlink_quietly(tmp)
        raise
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def write_new(filepath: Path, frontmatter: dict, body: str) -> None:
    """Create ``filepath`` with this document, never replacing a file (audit K01).

    Raises ``FileExistsError`` when the name is taken. The staged temp file is
    hard-linked to the destination — ``link`` refuses an existing name
    atomically, across processes, with no lock — so the page appears complete
    or not at all. A filesystem without hard links falls back to an
    ``O_EXCL`` create, which still never replaces a file."""
    target = Path(filepath)
    data = _render(frontmatter, body)
    _forget(target)
    tmp = _stage(target, data)
    try:
        os.link(tmp, target)
    except FileExistsError:
        raise
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV, errno.EMLINK):
            raise
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
    finally:
        _unlink_quietly(tmp)


def _normalize_dates(fm: dict) -> None:
    """Convert datetime.date values to strings (PyYAML auto-parses dates)."""
    for key, value in fm.items():
        if isinstance(value, (datetime.date, datetime.datetime)):
            fm[key] = str(value)
