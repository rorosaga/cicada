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

import math
from datetime import date
from pathlib import Path
from typing import Callable, NamedTuple

from api.models.schemas import (
    AGENT_PRODUCIBLE_DECAY_CLASSES,
    CLAIM_DECAY_MULTIPLIERS,
    DECAY_CLASS_RATES,
    DecayClass,
)
from api.services import decay_tuning, episode_ids, markdown_parser

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



# --------------------------------------------------------------------------- #
# G147 — spacing: how often a page came up sets how fast its silence counts
# --------------------------------------------------------------------------- #

# Before G147 the weekly rate was flat per class from the last reference, so a
# page mentioned in fifty separate conversations faded exactly as fast as one
# mentioned twice — while CLAUDE.md promised decay "proportional to how
# frequently it used to be referenced". Frequency is counted in DISTINCT ISO
# WEEKS (plan R-FD2): fifty mentions in one afternoon are one burst, twelve
# weeks of mentions are twelve spaced reviews. The curve is plan R-FD1:
# f(12) ≈ 0.40, f(52) ≈ 0.30, the floor only near 148 weeks, so spacing keeps
# paying across a bank's whole realistic life.
SPACING_ALPHA = 0.6
SPACING_FLOOR = 0.25
# A mis-set env var must never freeze decay: a floor of 0 would make every
# well-mentioned page effectively evergreen — the class the anti-pollution
# rail reserves for ingest writers and the person, one page at a time.
_ALPHA_MAX = 5.0
_FLOOR_MIN = 0.05

# The decay question's "keep" answer is the person's own act: it counts as a
# week the page came up (plan R-FD3). Dates, deduped, capped at a year of
# weekly keeps; written only by `inbox_service._resolve_decay`.
KEPT_ON_KEY = "kept_on"
KEPT_ON_CAP = 52


class EffectiveDecay(NamedTuple):
    """The pace Sleep charges one page, and every factor that made it (G147).

    ONE spelling of ``base x f(w) x pace`` (plan R-FD11): the Stage-3 pass
    charges ``rate`` and ``GET /entities/{id}`` serves it, so the card can never
    describe a pace the pass does not charge.
    """

    decay_class: DecayClass
    base_rate: float        # the class's rate, or the page's explicit `decay_rate:` (G66)
    mention_weeks: int      # distinct ISO weeks it came up in (+1 for any unparseable id)
    stability: float        # f(mention_weeks)
    type_multiplier: float  # the per-type pace the person approved (1.0 = none)
    rate: float             # base x stability x type_multiplier; 0.0 for evergreen


def _as_list(value) -> list:
    """A frontmatter list, tolerant of a hand-edited scalar: ``ep_x`` is one id,
    never iterated character by character."""
    if value is None:
        return []
    if isinstance(value, (str, bytes, date)):
        return [value]
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return []


def _week_of(value) -> str | None:
    """``YYYY-Www`` — the ISO 8601 week of a date-ish value, else ``None``.

    ISO weeks, so the boundary is the calendar's (Dec 29 can open next year's
    W01), not a 7-day bucket from an arbitrary epoch. ``str()`` of a ``date``
    or ``datetime`` starts with its ISO day, which is all this reads.
    """
    try:
        day = date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def mention_weeks(episode_refs, kept_on=()) -> int:
    """Distinct ISO weeks among episode ids (``ep_<date>_<n>``, G114) and kept dates.

    An id that does not parse — a legacy stem, an impossible date — is still a
    mention: all of them together count ONCE as an unknown week (R-FD2), so a
    legacy page gets bounded credit, never zero and never one week per id.
    """
    weeks: set[str] = set()
    unknown = False
    for ref in _as_list(episode_refs):
        stem = str(ref or "").strip()
        if not stem:
            continue
        parsed = episode_ids.parse_episode_id(stem)
        week = _week_of(parsed[0]) if parsed else None
        if week is None:
            unknown = True
        else:
            weeks.add(week)
    for day in _as_list(kept_on):
        week = _week_of(day)
        if week is not None:
            weeks.add(week)
    return len(weeks) + (1 if unknown else 0)


def stability(weeks: int, *, alpha: float = SPACING_ALPHA, floor: float = SPACING_FLOOR) -> float:
    """``f(w) = max(floor, 1 / (1 + alpha·ln w))``; ``1.0`` for ``w <= 1`` — a page
    heard in one week (or never dated) decays exactly as it did before G147."""
    if weeks <= 1:
        return 1.0
    return max(floor, 1.0 / (1.0 + alpha * math.log(weeks)))


def spacing_params(settings) -> tuple[float, float]:
    """``(alpha, floor)`` from ``Settings``, clamped (R-FD1).

    Only a real number is read: a test double without the fields, or a mock
    whose attributes are not numbers, gets the ruled defaults.
    """

    def _number(name: str, default: float) -> float:
        value = getattr(settings, name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        return float(value)

    alpha = min(_ALPHA_MAX, max(0.0, _number("decay_spacing_alpha", SPACING_ALPHA)))
    floor = min(1.0, max(_FLOOR_MIN, _number("decay_spacing_floor", SPACING_FLOOR)))
    return alpha, floor


def entity_type(fm: dict) -> str:
    """The key a per-type pace is filed under — the page's ``type``, ``concept``
    when absent (the default `GET /entities/{id}` has always served)."""
    return str((fm or {}).get("type") or "concept").strip().lower()


def kept_dates(fm: dict) -> list[str]:
    """The page's ``kept_on:`` as ISO days, deduped, junk dropped."""
    out: list[str] = []
    for value in _as_list((fm or {}).get(KEPT_ON_KEY)):
        day = str(value).strip()[:10]
        if _week_of(day) is not None and day not in out:
            out.append(day)
    return out


def record_keep(fm: dict, today: str) -> list[str]:
    """``kept_on`` after one more "keep" today — idempotent within a day, capped."""
    kept = kept_dates(fm)
    if today not in kept:
        kept.append(today)
    return kept[-KEPT_ON_CAP:]


def effective(
    fm: dict,
    *,
    alpha: float = SPACING_ALPHA,
    floor: float = SPACING_FLOOR,
    tuning: dict[str, float] | None = None,
) -> EffectiveDecay:
    """``base x f(w) x pace`` for one page's frontmatter. Never raises."""
    fm = fm or {}
    cls, base = resolve(fm)
    weeks = mention_weeks(fm.get("source_episodes"), kept_dates(fm))
    factor = stability(weeks, alpha=alpha, floor=floor)
    pace = float((tuning or {}).get(entity_type(fm), 1.0))
    rate = 0.0 if cls is DecayClass.evergreen else base * factor * pace
    return EffectiveDecay(cls, base, weeks, factor, pace, rate)


def default_class_for(entity_type: str | None, source: str = "extraction") -> DecayClass:
    """The class a WRITER should stamp on a page it is creating.

    ``volatile`` is never a default — it is assigned only when Stage-1
    explicitly says so, or when the user picks it.
    """
    if (source or "").strip().lower() in INGEST_SOURCES:
        return DecayClass.evergreen
    return _legacy_class(entity_type)


class SubjectDecay(NamedTuple):
    """What the claim engine needs about a claim's SUBJECT page (G147, R-FD13)."""

    decay_class: DecayClass
    entity_type: str
    kept_on: tuple[str, ...]
    type_multiplier: float


# An unknown or unreadable subject: the neutral 1.0 class multiplier, no keeps,
# no pace — a page-less subject decays exactly as it did before G66 and G147.
NEUTRAL_SUBJECT = SubjectDecay(DecayClass.active, "", (), 1.0)


def subject_lookup(memory_path, *, tuning: dict[str, float] | None = None) -> Callable[[str], SubjectDecay]:
    """A memoised ``entity_id -> SubjectDecay`` reader for one bank.

    One parse per subject yields the class (G66), the type (the key of the
    per-type pace, R-FD5) and the page's kept weeks (R-FD3), so the claim
    engine never walks the same files twice. ``tuning=None`` reads the bank's
    ``_decay_tuning.yaml`` lazily, on the first page found — an MCP write, whose
    one subject is always referenced, never reads it.
    """
    entities_dir = Path(memory_path) / "entities"
    cache: dict[str, SubjectDecay] = {}
    pace: list[dict[str, float]] = [] if tuning is None else [dict(tuning)]

    def pace_for(etype: str) -> float:
        if not pace:
            pace.append(decay_tuning.load(memory_path))
        return float(pace[0].get(etype, 1.0))

    def lookup(entity_id: str) -> SubjectDecay:
        eid = str(entity_id or "")
        if eid in cache:
            return cache[eid]
        found = NEUTRAL_SUBJECT
        filepath = entities_dir / f"{eid}.md"
        if eid and filepath.exists():
            try:
                fm = markdown_parser.parse(filepath).frontmatter or {}
                etype = entity_type(fm)
                found = SubjectDecay(resolve(fm)[0], etype, tuple(kept_dates(fm)), pace_for(etype))
            except Exception:
                found = NEUTRAL_SUBJECT
        cache[eid] = found
        return found

    return lookup


def class_lookup(memory_path) -> Callable[[str], DecayClass]:
    """A memoised ``entity_id -> DecayClass`` reader for one bank.

    Injected into the claim engine so it can weight a claim by its SUBJECT's
    class without the reconciler growing a filesystem dependency. Unknown /
    unreadable ids resolve to ``DecayClass.active`` (the neutral 1.0
    multiplier). Since G147 it is :func:`subject_lookup`'s class column; the
    empty ``tuning`` means a class-only caller never reads the pace file.
    """
    subject = subject_lookup(memory_path, tuning={})
    return lambda entity_id: subject(entity_id).decay_class


def claim_mention_weeks(claim, kept_on=()) -> int:
    """Distinct ISO weeks a claim was stated or restated in (R-FD4): its
    ``source_episodes`` and the ``ep_*`` documents its evidence cites (a ``page``
    span cites an entity, not a conversation), plus the subject's kept weeks.
    Session ids carry no date and ``recorded_at`` moves on every restatement,
    so neither counts. Duck-typed on ``Claim`` to keep this module import-light.
    """
    refs = list(getattr(claim, "source_episodes", None) or [])
    for ev in getattr(claim, "evidence", None) or []:
        doc = str(getattr(ev, "episode", "") or "")
        if doc.startswith("ep_"):
            refs.append(doc)
    return mention_weeks(refs, kept_on)
