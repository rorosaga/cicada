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

import re
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


def resolve_entity_file(memory_path: Path, name_or_slug: str) -> Path | None:
    """Map an entity slug or display name to its markdown file, tolerantly.

    Merge targets and ``related`` references are sometimes stored as display
    names ("AI-powered data migration service") rather than slugs. This walks a
    few strategies so a slug *or* a name resolves to the same file:

    1. exact slug — ``entities/<name_or_slug>.md`` as given;
    2. sanitized — ``entities/<sanitize_id(name_or_slug)>.md``;
    3. case-insensitive stem scan over ``entities/*.md``.

    Returns the resolved ``Path`` or ``None`` when nothing matches.
    """
    raw = (name_or_slug or "").strip()
    if not raw:
        return None
    entities_dir = Path(memory_path) / "entities"

    direct = entities_dir / f"{raw}.md"
    if direct.exists():
        return direct

    sanitized = entities_dir / f"{sanitize_id(raw)}.md"
    if sanitized.exists():
        return sanitized

    if not entities_dir.exists():
        return None
    target = raw.lower()
    sanitized_target = sanitize_id(raw)
    for filepath in entities_dir.glob("*.md"):
        stem = filepath.stem.lower()
        if stem == target or stem == sanitized_target:
            return filepath
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
    direct = entities_dir / f"{raw}.md"
    if direct.exists():
        return direct.stem
    sanitized = entities_dir / f"{sanitize_id(raw)}.md"
    if sanitized.exists():
        return sanitized.stem
    return None
