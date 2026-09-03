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


CardinalityFn = Callable[[str], bool]


def build_cardinality_fn(memory_path: Path | None) -> CardinalityFn:
    """Build a ``predicate -> is_single_valued`` oracle for Stage-3 reconciliation.

    Reads the seed's ``single_valued`` / ``multi_valued`` lists from
    ``<memory>/_predicates.yaml`` (the controlled vocabulary's contradiction
    semantics, ``predicates-seed.yaml``). The mechanical key needs to know whether
    a second valid object on the same key is a contradiction (single-valued) or
    normal coexistence (multi-valued).

    Resolution order (cheapest first, $0):
    1. canonical is in ``single_valued`` -> True;
    2. canonical is in ``multi_valued`` -> False;
    3. **unseen predicate => default to multi-valued (coexist).** This is the safe
       default per §5/§9 — never auto-close on an uncertain cardinality. (The
       LLM-cardinality fallback for genuinely-new conflicting predicates is a
       documented, cached future extension; coexisting is correct in the meantime.)
    """
    data = _read_runtime_map(memory_path) if memory_path is not None else {}
    single = {str(p).strip().lower() for p in (data.get("single_valued") or [])}
    multi = {str(p).strip().lower() for p in (data.get("multi_valued") or [])}

    def is_single_valued(predicate: str) -> bool:
        p = (predicate or "").strip().lower()
        if p in single:
            return True
        if p in multi:
            return False
        return False  # conservative: unseen => coexist, never auto-close

    return is_single_valued


def is_single_valued(memory_path: Path | None, predicate: str) -> bool:
    """One-shot convenience wrapper around :func:`build_cardinality_fn`."""
    return build_cardinality_fn(memory_path)(predicate)


def cardinality(memory_path: Path | None, predicate: str) -> str:
    """``"single"`` / ``"multi"`` / ``"unknown"`` for one canonical predicate.

    G98 / G115 Phase 1 (R4): the inbox must never ask for a winner on a predicate
    the vocabulary marks multi-valued (a tech stack is a set — seven true ``uses``
    values rendered as one conflict card on the live bank, 2026-09-03).

    This is NOT :func:`build_cardinality_fn`. That oracle answers "may a second
    value coexist?" for Stage 3 and collapses unseen → coexist, which is the
    right reconciler default and the wrong inbox rule: it reads a bank with no
    ``_predicates.yaml`` (``_read_runtime_map`` → ``{}``) as "every predicate is
    multi-valued" and would silence every conflict card.

    **Two sources, and ``multi`` wins across them** — deliberately not
    runtime-first. :func:`install_predicate_map` copies the seed once and then
    leaves a populated map alone forever, and commit ``e9a7c6b`` moved ``uses``
    from ``single_valued`` to ``multi_valued`` — so a bank seeded before that
    commit still asserts the false single-valued reading, on exactly the bank
    the G98 evidence came from. Letting the stale copy out-vote the committed
    vocabulary would ship the rule dead. A bank that genuinely wants a
    seed-multi predicate asked about gets that through Phase 2's
    ``_inbox_rules.yaml``, not here. Anything in neither list is ``unknown`` —
    ask as usual, fail open.
    """
    p = (predicate or "").strip().lower()
    if not p:
        return "unknown"
    sources = [_read_runtime_map(memory_path)] if memory_path is not None else []
    sources.append(_load_seed_map())
    single: set[str] = set()
    multi: set[str] = set()
    for data in sources:
        single |= {str(x).strip().lower() for x in (data.get("single_valued") or [])}
        multi |= {str(x).strip().lower() for x in (data.get("multi_valued") or [])}
    if p in multi:
        return "multi"
    if p in single:
        return "single"
    return "unknown"


def normalize_predicate(memory_path: Path, label: str) -> str:
    """One-shot convenience: build the normalizer and apply it to ``label``."""
    return load_normalizer(memory_path)(label)


# --------------------------------------------------------------------------- #
# G60 — predicate -> user-facing question template
# --------------------------------------------------------------------------- #

# Hand-written question phrasings for the canonical predicates that actually
# produce single-valued conflicts (see ``single_valued`` in predicates-seed.yaml)
# plus a few high-frequency multi-valued ones. Keyed by canonical predicate;
# ``{name}`` is the entity's display name. Anything absent falls back to the
# generic template — under-specifying is safe, a wrong verb is not.
PREDICATE_QUESTIONS: dict[str, str] = {
    "works-at": "Where does {name} work now?",
    "works-on": "What is {name} working on now?",
    "works-with": "Who does {name} work with now?",
    "located-in": "Where is {name} located now?",
    "takes-place-in": "Where does {name} take place?",
    "uses": "What does {name} use now?",
    "runs-on": "What does {name} run on now?",
    "depends-on": "What does {name} depend on now?",
    "part-of": "What is {name} part of now?",
    "is-a": "What kind of thing is {name}?",
    "implements": "What does {name} implement now?",
    "hosts": "What does {name} host now?",
    "provides": "What does {name} provide now?",
    "prefers": "What does {name} prefer now?",
    "description": "What is currently true about {name}?",
}

_GENERIC_QUESTION = "Which is true about {name} ({predicate})?"


def predicate_question(predicate: str, name: str) -> str:
    """One-sentence question for a ``(name, predicate)`` conflict.

    Template-only by design (§3 of the spec: no LLM call on the claim path).
    An unknown predicate gets the generic phrasing rather than a guessed verb.
    """
    key = (predicate or "").strip().lower()
    template = PREDICATE_QUESTIONS.get(key)
    if template:
        return template.format(name=name)
    return _GENERIC_QUESTION.format(name=name, predicate=key or "unknown")


# Hand-written grammatical sentence templates for the same canonical predicates,
# used to render a resolved claim as a plain-English sentence ("Rodrigo
# Sagastegui works at MongoDB") rather than a raw (subject, predicate, object)
# triple. Keyed the same way as ``PREDICATE_QUESTIONS``; unknown predicates fall
# back to a generic "{name} — {predicate}: {object}" rendering.
PREDICATE_PHRASES: dict[str, str] = {
    "works-at": "{name} works at {obj}",
    "works-on": "{name} is working on {obj}",
    "works-with": "{name} works with {obj}",
    "located-in": "{name} is located in {obj}",
    "takes-place-in": "{name} takes place in {obj}",
    "uses": "{name} uses {obj}",
    "runs-on": "{name} runs on {obj}",
    "depends-on": "{name} depends on {obj}",
    "part-of": "{name} is part of {obj}",
    "is-a": "{name} is a {obj}",
    "implements": "{name} implements {obj}",
    "hosts": "{name} hosts {obj}",
    "provides": "{name} provides {obj}",
    "prefers": "{name} prefers {obj}",
    "description": "{name} — {obj}",
}


def predicate_phrase(predicate: str, name: str, obj: str) -> str:
    """A grammatical sentence for a resolved ``(name, predicate, obj)`` claim.

    E.g. ``predicate_phrase("works-at", "Rodrigo Sagastegui", "MongoDB")`` ->
    ``"Rodrigo Sagastegui works at MongoDB"``. An unknown predicate falls back
    to a generic, still-readable rendering rather than guessing a verb.
    """
    key = (predicate or "").strip().lower()
    template = PREDICATE_PHRASES.get(key)
    if template:
        return template.format(name=name, obj=obj)
    return f"{name} — {predicate.replace('-', ' ').replace('_', ' ')}: {obj}"
