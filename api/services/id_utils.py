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
