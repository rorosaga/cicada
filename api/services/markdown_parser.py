import datetime
import errno
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

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
    _replace(Path(filepath), text.encode("utf-8"))


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


def parse(filepath: Path, *, ledger: bool = True) -> ParsedMarkdown:
    """Parse a markdown file with YAML frontmatter delimited by --- fences.

    An entity page whose claims overflowed into its ledger (``claims_ledger``) comes back with the ledger's claims
    folded into its fence, so every reader sees the page's whole claim set. ``ledger=False`` — a frontmatter-only
    scan — never opens the ledger (the body is then the page file's own)."""
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


def _replace(filepath: Path, data: bytes) -> None:
    target = Path(os.path.realpath(filepath)) if os.path.islink(filepath) else Path(filepath)
    tmp = _stage(target, data)
    try:
        try:
            os.chmod(tmp, os.stat(target).st_mode & 0o7777)
        except FileNotFoundError:
            pass
        os.replace(tmp, target)
    except BaseException:
        _unlink_quietly(tmp)
        raise


def write_new(filepath: Path, frontmatter: dict, body: str) -> None:
    """Create ``filepath`` with this document, never replacing a file (audit K01).

    Raises ``FileExistsError`` when the name is taken. The staged temp file is
    hard-linked to the destination — ``link`` refuses an existing name
    atomically, across processes, with no lock — so the page appears complete
    or not at all. A filesystem without hard links falls back to an
    ``O_EXCL`` create, which still never replaces a file."""
    target = Path(filepath)
    data = _render(frontmatter, body)
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
