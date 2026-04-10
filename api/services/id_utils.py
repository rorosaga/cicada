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
