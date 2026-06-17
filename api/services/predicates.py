"""Canonical predicate map + ``normalize_predicate`` (M5b Part 1).

The Sleep cycle's Stage-2 resolution normalizes open-vocabulary relation labels
(``built with``, ``worked at``, ``is associated with``, …) against a controlled
vocabulary so that contradiction-keying — ``(subject, predicate, context,
observer)`` — folds genuine synonyms together without collapsing distinct
beliefs. The map is hand-seeded conservatively (see
``docs/goals/m5-prep/predicates-seed.yaml`` and its rationale): fold a synonym
into a canonical ONLY when it is clearly the same relation in the same
direction; under-folding is safe, over-folding is the dangerous direction.

Runtime home: ``<memory>/_predicates.yaml`` (M5a seeds this as ``{}``). This
module installs the prep seed into it (without clobbering a populated map) and
exposes a ``normalize_predicate`` closure built from whatever map is on disk.

Normalization order for a raw label:
1. lowercase + collapse whitespace;
2. exact ``synonyms[label] -> canonical`` fold;
3. if already a canonical form, pass through;
4. otherwise **slugify and keep** — an unseen long-tail label is preserved
   (hyphenized), never silently dropped or guessed at. (Per the seed doc, the
   long tail is audited as a class via the normalization-audit nudge, not
   auto-folded here.)

``inverse_pairs`` (passive/reversed phrasings that REVERSE subject/object) are
intentionally NOT applied by this label-only normalizer — flipping an edge needs
the edge endpoints, which is the edge-seeder/Stage-2 caller's job, not a pure
``label -> canonical`` map. We expose ``inverse_pairs()`` so a caller that holds
the endpoints can flip-and-canonicalize; the seeder in this milestone seeds
edges as-authored (deterministic) and leaves inverse-flipping to the later Sleep
rewrite (M5e), to avoid silently mutating direction during a $0 backfill.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Callable

import yaml
from loguru import logger

# The prep seed lives at repo root (NOT inside the api package). Resolve it
# relative to this file: api/services/predicates.py -> repo root is parents[2].
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEED_PATH = _REPO_ROOT / "docs" / "goals" / "m5-prep" / "predicates-seed.yaml"

RUNTIME_FILE = "_predicates.yaml"

NormalizeFn = Callable[[str], str]


def _slugify_predicate(label: str) -> str:
    """Lowercase + hyphenize a raw predicate label (the canonical id shape)."""
    s = (label or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


@lru_cache(maxsize=1)
def _load_seed_map() -> dict:
    """Load the committed prep seed (canonical/synonyms/inverse_pairs/…)."""
    if not _SEED_PATH.exists():
        logger.warning(f"predicate seed not found at {_SEED_PATH}; using empty map")
        return {}
    try:
        return yaml.safe_load(_SEED_PATH.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.warning(f"malformed predicate seed, using empty map: {exc}")
        return {}


def install_predicate_map(memory_path: Path) -> Path:
    """Write the prep seed into ``<memory>/_predicates.yaml`` (runtime home).

    Idempotent and non-clobbering: an absent file or an empty ``{}`` placeholder
    (what M5a seeds) is populated with the full seed; an already-populated map
    (human-authored or previously installed) is left untouched so hand-edits and
    audit-folds survive.
    """
    memory_path = Path(memory_path)
    memory_path.mkdir(parents=True, exist_ok=True)
    runtime = memory_path / RUNTIME_FILE

    if runtime.exists():
        try:
            existing = yaml.safe_load(runtime.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            existing = None
        # Only the empty/placeholder map is replaced; a populated one is kept.
        if existing and (existing.get("canonical") or existing.get("synonyms")):
            return runtime

    seed = _load_seed_map()
    runtime.write_text(
        yaml.dump(seed, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return runtime


def _read_runtime_map(memory_path: Path) -> dict:
    runtime = Path(memory_path) / RUNTIME_FILE
    if not runtime.exists():
        return {}
    try:
        data = yaml.safe_load(runtime.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def load_normalizer(memory_path: Path) -> NormalizeFn:
    """Build a ``normalize_predicate(label) -> canonical`` closure for a memory dir.

    Reads ``<memory>/_predicates.yaml`` once and returns a pure function. When no
    runtime map is present, the function still works — it slugifies every label
    (so the seeder degrades gracefully rather than crashing).
    """
    data = _read_runtime_map(memory_path)
    synonyms = {
        str(k).strip().lower(): str(v)
        for k, v in (data.get("synonyms") or {}).items()
    }
    canonical = {str(c) for c in (data.get("canonical") or [])}

    def normalize(label: str) -> str:
        key = re.sub(r"\s+", " ", (label or "").strip().lower())
        if not key:
            return ""
        if key in synonyms:
            return synonyms[key]
        slug = _slugify_predicate(key)
        if slug in canonical:
            return slug
        # also fold a slugified synonym key (e.g. "built-with" form)
        if slug in synonyms:
            return synonyms[slug]
        return slug

    return normalize


def inverse_pairs(memory_path: Path) -> dict[str, str]:
    """``raw_inverse_label -> canonical_active`` map (for edge-flipping callers)."""
    data = _read_runtime_map(memory_path)
    return {
        str(k).strip().lower(): str(v)
        for k, v in (data.get("inverse_pairs") or {}).items()
    }


def normalize_predicate(memory_path: Path, label: str) -> str:
    """One-shot convenience: build the normalizer and apply it to ``label``."""
    return load_normalizer(memory_path)(label)
