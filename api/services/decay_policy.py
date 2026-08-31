"""G66 — the ONE decay resolver.

Before this module, ``decay_rate`` was a hardcoded per-writer float (0.05 in
extraction, 0.03 in media ingest, 0.02 for skills) that no agent reasoned about
and no user could change. Now every writer asks here, both decay engines read
here, and the user can override the answer.

The vocabulary lives in ``api.models.schemas`` (``DecayClass``,
``DECAY_CLASS_RATES``, ``CLAIM_DECAY_MULTIPLIERS``); this module owns the
*policy*: precedence, legacy inference, per-writer defaults, and the Stage-1
rail.

Precedence in :func:`resolve`:

1. An explicit, parseable ``decay_class:`` in frontmatter wins.
2. Otherwise infer from ``type``: ``media`` -> evergreen, ``skill`` -> durable,
   everything else -> active (legacy pages keep working untouched).
3. The rate is the class's mapped rate, EXCEPT that an explicit numeric
   ``decay_rate:`` that differs from the map wins for the three decaying classes
   (the class stays as the human-readable label). ``evergreen`` pins its rate to
   ``0.0`` unconditionally: the class contract is "never fades", and returning a
   nonzero rate for it would make any future consumer of ``resolve()`` wrong.

``decay_rate = 0.0`` is mechanically safe everywhere in the codebase: nothing
divides by it, ``exp(0) == 1``, and a 0-rate entity never decay-nudges or
archives via the entity engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from api.models.schemas import (
    AGENT_PRODUCIBLE_DECAY_CLASSES,
    CLAIM_DECAY_MULTIPLIERS,
    DECAY_CLASS_RATES,
    DecayClass,
)
from api.services import markdown_parser

# The historical extraction default, kept as the fallback for a page whose
# frontmatter carries neither a class nor a usable numeric rate.
DEFAULT_RATE = 0.05

# Writer "source" tags whose output is an ARTIFACT of the outside world rather
# than a belief about the user's life. Anything captured through these paths is
# evergreen: a saved bookmark does not become less true by going unmentioned.
INGEST_SOURCES = frozenset({"media", "bookmark", "rss", "pdf", "ingest"})


def coerce(value) -> DecayClass | None:
    """Parse any frontmatter / LLM value into a ``DecayClass``, else ``None``.

    Tolerant by design: an unknown or malformed value is DROPPED (never raised,
    never guessed at), so a bad extraction can't corrupt a page.
    """
    if isinstance(value, DecayClass):
        return value
    if not isinstance(value, str):
        return None
    try:
        return DecayClass(value.strip().lower())
    except ValueError:
        return None


def agent_class(value) -> DecayClass | None:
    """The Stage-1 rail: coerce, then refuse ``evergreen``.

    Stage-1 extraction may propose ``durable|active|volatile`` only. Anything
    else — including ``evergreen`` — is silently dropped so the caller falls back
    to its own default.
    """
    cls = coerce(value)
    if cls is None or cls not in AGENT_PRODUCIBLE_DECAY_CLASSES:
        return None
    return cls


def rate_for(cls: DecayClass) -> float:
    return DECAY_CLASS_RATES[cls]


def claim_multiplier(cls: DecayClass) -> float:
    return CLAIM_DECAY_MULTIPLIERS[cls]


def frontmatter_fields(cls: DecayClass) -> dict:
    """The two frontmatter keys a writer should stamp for ``cls``."""
    return {"decay_class": cls.value, "decay_rate": rate_for(cls)}


def _legacy_class(entity_type: str | None) -> DecayClass:
    t = (entity_type or "").strip().lower()
    if t == "media":
        return DecayClass.evergreen
    if t == "skill":
        return DecayClass.durable
    return DecayClass.active


def resolve(fm: dict) -> tuple[DecayClass, float]:
    """``(class, per-week rate)`` for one entity's frontmatter. Never raises."""
    fm = fm or {}
    cls = coerce(fm.get("decay_class")) or _legacy_class(fm.get("type"))
    if cls is DecayClass.evergreen:
        return cls, 0.0

    try:
        explicit = float(fm["decay_rate"])
    except (KeyError, TypeError, ValueError):
        explicit = None

    if explicit is None:
        # No usable numeric: an inferred `active` keeps the historical default,
        # an inferred/explicit durable|volatile takes its mapped rate.
        return cls, rate_for(cls) if cls is not DecayClass.active else DEFAULT_RATE
    return cls, max(0.0, explicit)


def default_class_for(entity_type: str | None, source: str = "extraction") -> DecayClass:
    """The class a WRITER should stamp on a page it is creating.

    ``volatile`` is never a default — it is assigned only when Stage-1
    explicitly says so, or when the user picks it.
    """
    if (source or "").strip().lower() in INGEST_SOURCES:
        return DecayClass.evergreen
    return _legacy_class(entity_type)


def class_lookup(memory_path) -> Callable[[str], DecayClass]:
    """A memoised ``entity_id -> DecayClass`` reader for one bank.

    Injected into the claim engine so it can weight a claim by its SUBJECT's
    class without the reconciler growing a filesystem dependency. Unknown /
    unreadable ids resolve to ``DecayClass.active`` (the neutral 1.0 multiplier),
    so a page-less subject decays exactly as it did before this existed.
    """
    entities_dir = Path(memory_path) / "entities"
    cache: dict[str, DecayClass] = {}

    def lookup(entity_id: str) -> DecayClass:
        eid = str(entity_id or "")
        if eid in cache:
            return cache[eid]
        cls = DecayClass.active
        filepath = entities_dir / f"{eid}.md"
        if filepath.exists():
            try:
                cls = resolve(markdown_parser.parse(filepath).frontmatter or {})[0]
            except Exception:
                cls = DecayClass.active
        cache[eid] = cls
        return cls

    return lookup
