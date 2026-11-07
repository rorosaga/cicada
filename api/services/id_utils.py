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


def folder_tags(folder) -> set[str]:
    """The tags a save's ``folder`` (a playlist, board, collection, bookmark folder…) used to leave on its page.

    A list a save came from is provenance — the page's ``folder:`` / ``collections:`` — never a topic (owner
    2026-10-19): the media writer once added ``sanitize_id(folder)`` to ``tags`` (and the Netscape parser the raw
    name), so every list with enough saves became a tag hub. The writer, the hub tier and ``list_hub_repair`` all
    name them by this one rule.
    """
    raw = str(folder or "").strip()
    if not raw:
        return set()
    return {raw, sanitize_id(raw)} - {"unnamed"}


def page_lists(fm: dict) -> list[str]:
    """Every list a saved page came from, in the order it was saved from them: ``folder:`` (the first, kept for every
    reader that knows only it) and then ``collections:`` (owner 2026-10-19: a video in several playlists keeps them
    all). A page written before ``collections:`` existed holds its ``folder:`` alone."""
    raw = fm.get("collections")
    out: list[str] = []
    for value in [fm.get("folder"), *(raw if isinstance(raw, list) else [])]:
        name = str(value or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def _media(fm: dict) -> dict:
    media = fm.get("media")
    return media if isinstance(media, dict) else {}


def list_tags(fm: dict) -> set[str]:
    """The tags a page's lists left on it (:func:`folder_tags` of each), less the page's own media type — what
    ``list_hub_repair`` takes off a page."""
    out: set[str] = set()
    for name in page_lists(fm):
        out |= folder_tags(name)
    return out - {str(_media(fm).get("media_type") or "")}


#: Tags a capture door stamps to say where a media page came from, on pages older than their ``origin:`` field
#: (``bookmark_sync._tag_origin``'s ``<browser>-bookmark``, ``safari_tabs.ORIGIN``, the generic ``bookmark``).
_DOOR_TAG = re.compile(r"[a-z0-9]+-bookmark|bookmark|safari-tab")


def provenance_tags(fm: dict) -> set[str]:
    """The tags on a page that say only where it came from or what kind of file it is — never what it is about.

    The page's lists (:func:`list_tags`), and on a ``media`` page its own media type, kind and origin
    (``youtube``, ``paper``, ``chrome-bookmark``, ``youtube-playlist``…) and a door's stamp: each repeats a field
    the page already holds (``media.media_type``, ``media.kind``, ``origin:``, ``folder:``). The hub tier never
    gathers a page into a tag hub by one of them (owner 2026-10-19: provenance is "a property of the markdown"); a
    tag the person or Sleep wrote for meaning is none of these and still makes its hub.
    """
    out = list_tags(fm)
    if str(fm.get("type") or "") == "media":
        media = _media(fm)
        out |= {str(media.get("media_type") or ""), str(media.get("kind") or ""), str(fm.get("origin") or "")}
        tags = fm.get("tags") if isinstance(fm.get("tags"), list) else []
        out |= {str(t) for t in tags if _DOOR_TAG.fullmatch(str(t))}
    return out - {""}


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


#: The longest file name the filesystems a bank lives on accept (APFS, ext4: 255 bytes).
MAX_NAME_BYTES = 255


def is_page(path: Path | None) -> bool:
    """``path`` is an existing file — ``False``, never an error, for a name no filesystem can hold.

    2026-10-23 (live test): a claim's object or a wikilink target is sometimes a whole sentence (a bookmark's
    description, a pasted history list), and ``Path.exists()`` raises ``OSError: [Errno 63] File name too long``
    for a component past 255 bytes instead of answering ``False``. Ask's retrieval resolved such an object as a page
    and the error threw away every hit, so a page recall found was answered "no page exists"; Sleep's wikilink step
    failed the same way. A name that long is never a page, so it is refused before the filesystem is asked."""
    if path is None or len(path.name.encode("utf-8", "surrogatepass")) > MAX_NAME_BYTES:
        return False
    try:
        return path.exists()
    except (OSError, ValueError):
        return False


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
    if is_page(direct):
        return on_disk(direct)

    sanitized = entities_dir / f"{sanitize_id(raw)}.md"
    if is_page(sanitized):
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
    # 4. an id a merge or a rename retired (`page_redirects`): the page it became.
    from api.services import page_redirects

    for key in dict.fromkeys((raw, sanitize_id(raw))):
        moved = page_redirects.resolve(memory_path, key)
        if moved is not None:
            return entities_dir / f"{moved}.md"
    return None


def build_name_index(entities_dir: Path) -> dict[str, str]:
    """Map every resolvable key -> ``filepath.stem`` (the authoritative id).

    181 of the live entity files have filenames that do not round-trip through
    ``sanitize_id(name)`` (e.g. ``atlético-de-madrid.md``,
    ``algorithms-&-data-structures.md``), so the invariant
    ``entity_id == sanitize_id(name)`` is false. Building one bulk index lets
    wikilink/context/MCP resolution be O(refs) instead of O(refs * files).

    Keys: lowercased frontmatter ``name``, ``sanitize_id(name)``, the stem
    itself, and ``stem.replace('-', ' ')``. A page's own id always wins its key
    over another page's name (G227: a saved link titled like a tool page once
    took the tool's id by listing order). A key two or more pages answer to by
    name is recorded in ``ambiguous`` (``NameIndex``) with every one of them, so
    :func:`resolve_entity_id` never silently picks one — :func:`link_targets`
    names them all.
    """
    from api.services import markdown_parser

    index = NameIndex()
    if not entities_dir.exists():
        return index
    stems: dict[str, str] = {}
    by_name: dict[str, set[str]] = {}
    for filepath in sorted(entities_dir.glob("*.md")):
        stem = filepath.stem
        try:
            fm = markdown_parser.parse(filepath).frontmatter
        except Exception:
            fm = {}
        name = str((fm or {}).get("name", "") or "").strip()
        stems.setdefault(stem.lower(), stem)
        if str((fm or {}).get("status") or "") != "dropped":
            for key in {stem.replace("-", " ").lower(), *((name.lower(), sanitize_id(name)) if name else ())}:
                by_name.setdefault(key, set()).add(stem)
        else:
            for key in {stem.replace("-", " ").lower(), *((name.lower(), sanitize_id(name)) if name else ())}:
                by_name.setdefault(key, set())
                index.setdefault(key, stem)
    for key, held in by_name.items():
        if held:
            index[key] = min(held)
        if len(held) > 1:
            index.ambiguous[key] = tuple(sorted(held))
    index.update(stems)
    return index


class NameIndex(dict):
    """``build_name_index``'s answer: key -> stem, plus ``ambiguous`` — key -> every stem two or more pages that are
    not dropped answer to by name (G227)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ambiguous: dict[str, tuple[str, ...]] = {}


def link_targets(entities_dir: Path, ref: str, name_index: dict[str, str] | None = None) -> list[str]:
    """Every page a link's target text can mean (G227): ``[stem]`` for a page's own id (spelled exactly) or a name
    one page holds; every page when two or more share the name; ``[]`` when none. A link resolves by id, never by a
    bare title two pages share."""
    raw = (ref or "").strip()
    if not raw:
        return []
    if name_index is None:
        name_index = build_name_index(entities_dir)
    if name_index.get(raw.lower()) == raw:
        return [raw]                       # the page's own id, as written
    ambiguous = getattr(name_index, "ambiguous", {})
    for key in (raw.lower(), sanitize_id(raw), raw.lower().replace(" ", "-")):
        if key in ambiguous:
            return list(ambiguous[key])
    one = resolve_entity_id(entities_dir, raw, name_index)
    return [one] if one else []


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
    # G227: a name two or more pages share is never resolved to one of them — unless it is a page's own id, spelled.
    ambiguous = getattr(name_index, "ambiguous", {})
    if name_index.get(lower) != raw and any(k in ambiguous for k in (lower, sanitize_id(raw), lower.replace(" ", "-"))):
        return None
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
    if is_page(direct):
        return direct.stem
    sanitized = entities_dir / f"{sanitize_id(raw)}.md"
    if is_page(sanitized):
        return sanitized.stem
    return None
