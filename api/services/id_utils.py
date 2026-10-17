"""Shared helpers for deriving filesystem-safe IDs from entity names.

Previously ``_sanitize_id`` lived in ``entity_resolver.py`` and was the only
place that knew how to turn "Cicada / Thesis" into ``cicada-thesis``. The
Stage 5 skill writer had its own home-grown ``name.lower().replace(" ", "-")``,
which silently diverged: a skill named "AI/ML project framing from prior work"
became ``ai/ml-project-framing-from-prior-work`` and the pipeline tried to
write a file under a non-existent ``ai/`` subdirectory, crashing Sleep.

Every code path that turns an entity or skill name into a markdown filename
must go through :func:`sanitize_id` so the filesystem layout stays flat.
"""

import os
import re
import time
import unicodedata
from pathlib import Path


def sanitize_id(name: str) -> str:
    """Convert an entity or skill name to a safe filesystem ID.

    Lowercases the name, replaces filesystem-unsafe characters and whitespace
    with hyphens, collapses repeated hyphens, and strips leading/trailing
    hyphens. Returns ``"unnamed"`` as a fallback when the result would be
    empty.
    """
    safe = (name or "").lower()
    # Filesystem-unsafe characters (collapse runs into a single hyphen).
    safe = re.sub(r"[/\\:*?\"<>|.]+", "-", safe)
    safe = safe.replace(" ", "-")
    safe = re.sub(r"-+", "-", safe)
    safe = safe.strip("-")
    return safe or "unnamed"


def bank_file(directory: Path, stem: str) -> Path | None:
    """``<directory>/<stem>.md`` — or ``None`` when ``stem`` is not ONE path segment.

    G135 Task 5 review (round 1, high): the readers that join a caller's id
    onto a bank folder (``recall_detail``, ``open_hub``, ``get_perspective``,
    ``sources``) took ``../episodes/ep_x``, ``../../outside/note`` or an
    absolute path at its word, and pathlib lets an absolute right-hand side
    replace the base outright — so a remote connector holding only ``read``
    could pull a raw episode (the thing R-R22 keeps behind ``sources``) or
    any ``.md`` file the backend can open. Every bank folder is flat
    (``sanitize_id`` above exists to keep it so), so a stem with a separator
    is never a real id and is refused lexically: no ``resolve()``, so a bank
    that is itself a symlink, or a page that is one, still reads.
    """
    raw = str(stem or "")
    if not raw or raw in (".", "..") or any(ch in raw for ch in ("/", "\\", "\x00")):
        return None
    return Path(directory) / f"{raw}.md"


def _fold(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


#: A directory listing is trusted while the directory's mtime is unchanged — and only once the listing was taken at
#: least this long after that mtime (git's "racy clean" rule): a filesystem whose clock is coarse (Linux stamps a
#: directory at jiffy granularity, up to 10 ms) can add an entry within the same tick a listing was taken, leaving the
#: mtime equal. Inside the window the folder is simply listed again.
_RACY_NS = 100_000_000

_LISTINGS: dict[str, tuple[int, int, frozenset[str]]] = {}
#: directory -> (the listing it was built from, lowercased ``*.md`` stem -> on-disk filename).
_STEMS: dict[str, tuple[frozenset[str], dict[str, str]]] = {}


def _listing(directory: Path) -> frozenset[str] | None:
    """A directory's names, re-read only when its mtime moves (an entry added, removed or renamed), so a caller that
    resolves many refs in a loop lists the folder once."""
    key = str(directory)
    try:
        stamp = os.stat(directory).st_mtime_ns
        cached = _LISTINGS.get(key)
        if cached is not None and cached[0] == stamp and cached[1] - stamp >= _RACY_NS:
            return cached[2]
        listed_at = time.time_ns()
        names = frozenset(os.listdir(directory))
    except OSError:
        return None
    _LISTINGS[key] = (stamp, listed_at, names)
    return names


def _stem_index(directory: Path) -> dict[str, str] | None:
    """``{stem.lower(): filename}`` over the directory's ``*.md`` entries, rebuilt only when :func:`_listing` changes
    (inbox lag, 2026-10-17). On a tie the first filename in sorted order wins, so the answer never depends on the
    order the filesystem lists entries in."""
    names = _listing(directory)
    if names is None:
        return None
    key = str(directory)
    cached = _STEMS.get(key)
    if cached is not None and (cached[0] is names or cached[0] == names):
        return cached[1]
    index: dict[str, str] = {}
    for name in sorted(names):
        if name.endswith(".md"):
            index.setdefault(name[: -len(".md")].lower(), name)
    _STEMS[key] = (names, index)
    return index


def on_disk(path: Path) -> Path:
    """``path`` spelled as its file is actually named in its directory (2026-10-14).

    macOS's filesystem ignores case (and Unicode normalization) when it looks a name up, so ``entities/Cicada.md``
    "exists" when the page is ``entities/cicada.md`` — and every caller that takes the returned stem as the page's
    id (``project_timeline``'s type lookup, the backlog, sources) then knew no page by that id: ``cicada_note_progress
    (project="Cicada")`` answered "Cicada is a page" about a project. The directory listing is the authority: the
    exact name when it is there, else the one entry equal to it ignoring case and normalization, else ``path`` as
    given (a case-sensitive filesystem already answered exactly)."""
    path = Path(path)
    names = _listing(path.parent)
    if names is None or path.name in names:
        return path
    want = _fold(path.name)
    matches = sorted(n for n in names if _fold(n) == want)
    return path.parent / matches[0] if matches else path


def resolve_entity_file(memory_path: Path, name_or_slug: str) -> Path | None:
    """Map an entity slug or display name to its markdown file, tolerantly.

    Merge targets and ``related`` references are sometimes stored as display
    names ("AI-powered data migration service") rather than slugs. This walks a
    few strategies so a slug *or* a name resolves to the same file:

    1. exact slug — ``entities/<name_or_slug>.md`` as given;
    2. sanitized — ``entities/<sanitize_id(name_or_slug)>.md``;
    3. case-insensitive stem match over ``entities/*.md`` (one cached listing, re-read when the folder changes).

    Returns the resolved ``Path`` — always spelled as the file is on disk (:func:`on_disk`) — or ``None`` when
    nothing matches.
    """
    raw = (name_or_slug or "").strip()
    if not raw:
        return None
    entities_dir = Path(memory_path) / "entities"

    direct = bank_file(entities_dir, raw)  # never a path out of the bank
    if direct is not None and direct.exists():
        return on_disk(direct)

    sanitized = entities_dir / f"{sanitize_id(raw)}.md"
    if sanitized.exists():
        return on_disk(sanitized)

    # The case-insensitive stem match reads one cached index of the folder, not a fresh `glob` per call: a caller
    # resolving many names that have no page (``load_inbox`` asks about every item's subject, most of them merged
    # away or renamed) listed 4,700 pages per name — 3.5 M paths and ~6 s per inbox read (inbox lag, 2026-10-17).
    index = _stem_index(entities_dir)
    if index is None:
        return None
    for key in (raw.lower(), sanitize_id(raw)):
        if key in index:
            return entities_dir / index[key]
    return None


def build_name_index(entities_dir: Path) -> dict[str, str]:
    """Map every resolvable key -> ``filepath.stem`` (the authoritative id).

    181 of the live entity files have filenames that do not round-trip through
    ``sanitize_id(name)`` (e.g. ``atlético-de-madrid.md``,
    ``algorithms-&-data-structures.md``), so the invariant
    ``entity_id == sanitize_id(name)`` is false. Building one bulk index lets
    wikilink/context/MCP resolution be O(refs) instead of O(refs * files).

    Keys: lowercased frontmatter ``name``, ``sanitize_id(name)``, the stem
    itself, and ``stem.replace('-', ' ')``. Last-writer-wins on collision —
    collisions are rare and either spelling resolves to a real file.
    """
    from api.services import markdown_parser

    index: dict[str, str] = {}
    if not entities_dir.exists():
        return index
    for filepath in entities_dir.glob("*.md"):
        stem = filepath.stem
        try:
            fm = markdown_parser.parse(filepath).frontmatter
        except Exception:
            fm = {}
        name = str((fm or {}).get("name", "") or "").strip()
        index[stem.lower()] = stem
        index[stem.replace("-", " ").lower()] = stem
        if name:
            index[name.lower()] = stem
            index[sanitize_id(name)] = stem
    return index


def resolve_entity_id(
    entities_dir: Path, ref: str, name_index: dict[str, str] | None = None
) -> str | None:
    """Resolve a name-or-id ref to a real ``filepath.stem``.

    Tries, in order: an exact file ``<ref>.md``, a file
    ``<sanitize_id(ref)>.md``, then ``name_index[ref.lower()]`` and
    ``name_index[sanitize_id(ref)]`` (building the index lazily if not passed).
    Returns ``None`` when unresolved so the caller decides 404 vs skip.
    """
    raw = (ref or "").strip()
    if not raw:
        return None
    if name_index is None:
        name_index = build_name_index(entities_dir)

    # The index is built from real glob stems, so it is the authoritative
    # source of the on-disk casing. Consult it before trusting Path.exists():
    # on a case-insensitive filesystem (macOS APFS) ``entities/Madrid.md``
    # reports as existing even when the real file is ``madrid.md``, and
    # ``.stem`` would echo the requested casing instead of the true id.
    lower = raw.lower()
    if lower in name_index:
        return name_index[lower]
    san = sanitize_id(raw)
    if san in name_index:
        return name_index[san]
    slug = lower.replace(" ", "-")
    if slug in name_index:
        return name_index[slug]

    # Fallback for files not covered by the index (e.g. a stem whose name
    # frontmatter is missing). Path.exists() is the last resort here.
    direct = bank_file(entities_dir, raw)
    if direct is not None and direct.exists():
        return direct.stem
    sanitized = entities_dir / f"{sanitize_id(raw)}.md"
    if sanitized.exists():
        return sanitized.stem
    return None
