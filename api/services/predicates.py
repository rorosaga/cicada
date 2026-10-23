"""Canonical predicate map + ``normalize_predicate`` (M5b Part 1).

The Sleep cycle's Stage-2 resolution normalizes open-vocabulary relation labels
(``built with``, ``worked at``, ``is associated with``, …) against a controlled
vocabulary so that contradiction-keying — ``(subject, predicate, context,
observer)`` — folds genuine synonyms together without collapsing distinct
beliefs. The map is hand-seeded conservatively (see
``api/data/predicates-seed.yaml``; rationale in ``docs/goals/m5-prep/predicates-rationale.md``): fold a synonym
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

import copy
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import Callable, NamedTuple

import yaml
from loguru import logger

from api.services.claims import event_cardinality

# The seed ships with the package (api/data/), so a release bundle that carries
# only api/ still has it (G182; it lived under docs/goals/m5-prep/ until then).
_SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "predicates-seed.yaml"

RUNTIME_FILE = "_predicates.yaml"
#: libyaml's scanner when PyYAML has it — the same safe constructor and output as ``yaml.safe_load``.
_SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

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
        # The one reader of the runtime map (stat-keyed parse cache, libyaml when present): a malformed or
        # non-mapping file reads as ``{}``, the placeholder this replaces. Only the empty/placeholder map is
        # replaced; a populated one is kept.
        existing = _read_runtime_map(memory_path)
        if existing.get("canonical") or existing.get("synonyms"):
            return runtime

    seed = _load_seed_map()
    runtime.write_text(
        yaml.dump(seed, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return runtime


#: path -> ((st_ino, st_mtime_ns, st_size), parsed map). Process-local and disposable: a write of the file (an
#: ``os.replace`` or an in-place rewrite) moves its stat, and the next read parses it again.
_runtime_cache: dict[str, tuple[tuple[int, int, int], dict]] = {}
_runtime_lock = threading.Lock()


def _read_runtime_map(memory_path: Path) -> dict:
    """The bank's ``_predicates.yaml``, parsed once per change of the file (2026-10-16 perf: ``GET /inbox`` asked
    ``cardinality`` once per conflict item and re-parsed the map each time — 121 parses, ~0.6 s of a 0.64 s inbox
    read on a 240-item synthetic inbox). Every caller gets its own deep copy, so a caller that edits what it read
    (``update_runtime_map``) never edits the cache. Every writer replaces the file (``update_runtime_map``'s
    ``os.replace``) or rewrites it (``install_predicate_map``), so its inode, mtime or size moves and the next read —
    in this process or another — parses the new file."""
    runtime = Path(memory_path) / RUNTIME_FILE
    try:
        st = runtime.stat()
    except OSError:
        return {}
    stamp = (st.st_ino, st.st_mtime_ns, st.st_size)
    key = str(runtime)
    with _runtime_lock:
        hit = _runtime_cache.get(key)
    if hit is not None and hit[0] == stamp:
        return copy.deepcopy(hit[1])
    try:
        data = yaml.load(runtime.read_text(encoding="utf-8"), Loader=_SAFE_LOADER) or {}
    except (OSError, yaml.YAMLError):
        return {}
    data = data if isinstance(data, dict) else {}
    with _runtime_lock:
        _runtime_cache[key] = (stamp, copy.deepcopy(data))
    return data


def update_runtime_map(memory_path: Path, mutate: Callable[[dict], bool]) -> bool:
    """Read-modify-write ``<memory>/_predicates.yaml`` as one critical section.

    G98/G115: an inbox answer writes the map (a confirmed fold, a split one),
    and two answers that both read before either wrote lost one of them. The
    bank's page lock (cross-process, re-entrant — a caller already holding it
    re-enters) spans the read and the write, and the write is atomic (temp
    file + ``os.replace``), so a reader never sees half a map. ``mutate``
    edits the map in place and returns whether it changed anything; nothing
    is written when it returns False. Returns what ``mutate`` returned.
    """
    import os
    import tempfile

    from api.services.page_lock import page_lock

    memory_path = Path(memory_path)
    with page_lock(memory_path):
        data = _read_runtime_map(memory_path)
        if not mutate(data):
            return False
        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        fd, tmp = tempfile.mkstemp(prefix=".predicates-", suffix=".tmp", dir=memory_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, memory_path / RUNTIME_FILE)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return True


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


def fold_key(raw_label: str, canonical: str) -> tuple[str, str]:
    """The identity of one predicate fold: ``(slug(raw), canonical)``.

    G98/G115: a fold is asked about once per pair per bank, so ``built with``
    and ``Built  With`` folding onto ``uses`` are the same question. A pair
    whose two sides are equal is no fold at all — the normalizer kept the
    label as its own slug.
    """
    return _slugify_predicate(raw_label), str(canonical or "").strip()


def confirmed_folds(memory_path: Path | None) -> dict[str, str]:
    """``raw_slug -> canonical`` folds the person confirmed ("Correct fold").

    Kept in ``<memory>/_predicates.yaml`` under ``confirmed_folds`` beside the
    synonyms they confirm; the inbox writer never asks about one again.
    """
    if memory_path is None:
        return {}
    raw = _read_runtime_map(memory_path).get("confirmed_folds")
    if not isinstance(raw, dict):
        return {}
    return {str(k).strip(): str(v).strip() for k, v in raw.items() if k and v}


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
    1. canonical is in the committed seed's ``multi_valued`` -> False;
    2. canonical is in the bank's ``single_valued`` -> True;
    3. canonical is in the bank's ``multi_valued`` -> False;
    4. **unseen predicate => default to multi-valued (coexist).** This is the safe
       default per §5/§9 — never auto-close on an uncertain cardinality. (The
       LLM-cardinality fallback for genuinely-new conflicting predicates is a
       documented, cached future extension; coexisting is correct in the meantime.)

    Step 1 is :func:`cardinality`'s "``multi`` wins" rule, applied here too:
    :func:`install_predicate_map` never refreshes a populated map, so a bank
    seeded before a predicate moved to ``multi_valued`` (``uses`` in ``e9a7c6b``,
    ``works-at`` on 2026-10-14) still lists it single-valued, and Stage 3 kept
    closing one value whenever another arrived while the inbox already called
    them a set. A seed and a bank that disagree are an uncertain cardinality, and
    an uncertain cardinality never auto-closes. The seed's ``single_valued`` is
    NOT imported: a bank with no map still coexists everything, as before.
    """
    data = _read_runtime_map(memory_path) if memory_path is not None else {}
    seed_multi = {str(p).strip().lower() for p in (_load_seed_map().get("multi_valued") or [])}
    single = {str(p).strip().lower() for p in (data.get("single_valued") or [])} - seed_multi
    multi = {str(p).strip().lower() for p in (data.get("multi_valued") or [])} | seed_multi

    def is_single_valued(predicate: str) -> bool:
        p = (predicate or "").strip().lower()
        if p in single:
            return True
        if p in multi:
            return False
        return False  # conservative: unseen => coexist, never auto-close

    return is_single_valued


#: What an ending label does (``endings`` in the seed): ``over`` closes the open
#: belief on the same object; ``past`` reinforces it and never closes it.
ENDING_OVER, ENDING_PAST = "over", "past"

class Ending(NamedTuple):
    canonical: str     # the predicate whose belief the label ends
    mode: str          # ENDING_OVER | ENDING_PAST
    synonym: bool      # the label is itself a synonym of `canonical` ("previously worked at"), not "left"


EndingFn = Callable[[str], "Ending | None"]


def build_endings_fn(memory_path: Path | None) -> EndingFn:
    """A ``label -> Ending(canonical, "over" | "past", synonym) | None`` oracle over
    the seed's ``endings`` and the bank's (union; a bank may add labels, never
    remove one). ``synonym`` says the label folds into ``canonical`` through the
    vocabulary's synonyms (either source), so with nothing open it is still a
    statement about that predicate; "left" is not, and keeps its own label.

    A label that says a belief stopped being true — "left", "previously worked
    at" — is the only thing that ends a multi-valued place in Stage 3 besides a
    stated end and the person's own edit (2026-10-14). Labels compare slugged, so
    "Previously  Worked At" and ``previously-worked-at`` are one label. A label
    listed under two canonicals is ambiguous and dropped: when unsure, nothing
    closes. ``over`` wins over ``past`` for one canonical (the stronger reading
    is the curated one; both lists are hand-written)."""
    sources = [_load_seed_map()]
    if memory_path is not None:
        sources.append(_read_runtime_map(memory_path))
    found: dict[str, set[tuple[str, str]]] = {}
    folds: dict[str, set[str]] = {}
    roots: dict[str, set[str]] = {}   # a predicate slug -> the canonicals whose `over` labels end it
    dependents: dict[str, set[str]] = {}   # a predicate slug -> the canonicals it rests on (W7, 2026-10-23)
    for data in sources:
        for k, v in ((data.get("synonyms") or {}) if isinstance(data, dict) else {}).items():
            folds.setdefault(_slugify_predicate(str(k)), set()).add(_slugify_predicate(str(v)))
        raw = data.get("endings") if isinstance(data, dict) else None
        if not isinstance(raw, dict):
            continue
        for canonical, modes in raw.items():
            canon = _slugify_predicate(str(canonical))
            if not canon or not isinstance(modes, dict):
                continue
            roots.setdefault(canon, set()).add(canon)
            for member in modes.get("also_ends") or []:
                slug = _slugify_predicate(str(member))
                if slug:
                    roots.setdefault(slug, set()).add(canon)
            for member in modes.get("dependents") or []:
                slug = _slugify_predicate(str(member))
                if slug:
                    dependents.setdefault(slug, set()).add(canon)
            for mode in (ENDING_OVER, ENDING_PAST):
                for label in modes.get(mode) or []:
                    slug = _slugify_predicate(str(label))
                    if slug:
                        found.setdefault(slug, set()).add((canon, mode))
    table: dict[str, Ending] = {}
    for slug, hits in found.items():
        if len({c for c, _ in hits}) != 1:
            continue   # two canonicals claim one label: ambiguous, never closes
        canon = next(iter(hits))[0]
        table[slug] = Ending(canon, ENDING_OVER if (canon, ENDING_OVER) in hits else ENDING_PAST,
                             folds.get(slug) == {canon})

    def ending(label: str) -> Ending | None:
        return table.get(_slugify_predicate(label or ""))

    # Every `over` label, by the canonical it ends — Stage 3 looks for a departure already on the page.
    over: dict[str, set[str]] = {}
    for slug, hit in table.items():
        if hit.mode == ENDING_OVER:
            over.setdefault(hit.canonical, set()).add(slug)
    ending.over = over  # type: ignore[attr-defined]

    def _listed(table: dict[str, set[str]], predicate: str) -> str | None:
        slug = _slugify_predicate(predicate or "")
        if not slug:
            return None
        if slug in table:
            hits = table[slug]
        else:
            prefixes = [root for root in table if slug.startswith(root + "-")]
            if not prefixes:
                return None
            hits = table[max(prefixes, key=len)]
        return next(iter(hits)) if len(hits) == 1 else None

    def ended_by(predicate: str) -> str | None:
        """The canonical whose ``over`` labels also end a belief under ``predicate`` (2026-10-23): the canonical
        itself, a predicate its ``also_ends`` lists, or either one qualified by more words (``uses-for-sign-in``,
        ``stores-data-in-supabase-postgres``) — the longest listed prefix decides. ``None`` when nothing lists it or
        two canonicals do (when unsure, nothing closes)."""
        return _listed(roots, predicate)

    def depends_on(predicate: str) -> str | None:
        """The canonical a belief under ``predicate`` rests on (``dependents``, W7 2026-10-23): ``reports-to`` rests on
        ``works-at``, so it closes with the job its ``premises`` name. Same matching as :func:`ended_by`."""
        return _listed(dependents, predicate)

    ending.ended_by = ended_by  # type: ignore[attr-defined]
    ending.depends_on = depends_on  # type: ignore[attr-defined]
    return ending


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
    # G141 R-PJ5: the event predicates are multi in CODE — a bank seeded before
    # they existed must still never ask for a winner between two happenings.
    if event_cardinality(predicate):
        return "multi"
    from api.services.claims import is_value_predicate

    if is_value_predicate(predicate):
        return "single"     # a stated value: one at a time, by its own shape (claims.VALUE_PREFIX)
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


LOCI = ("world", "artifact", "person")
# Most conservative first (plan R-AC29): `person` is never checked, `artifact`
# only recommends, `world` may settle — so a disagreement between the seed and a
# bank's map always resolves to the less settleable reading, the way `multi`
# wins for cardinality.
_LOCUS_PRECEDENCE = ("person", "artifact", "world")


def build_locus_fn(memory_path: Path | None) -> Callable[[str], str]:
    """A ``predicate -> world | artifact | person | unknown`` oracle, reading the
    seed and the bank's ``_predicates.yaml`` once (G61 phase 2 S1, spec R-AC8).

    Where a fact's truth lives decides whether a source may answer it: the
    inbox's checkability (``source_check``) and the extraction-time link attach
    (``fact_sources.attach_cited_urls``) both ask. Unseen is ``unknown``, never a
    guess.
    """
    sources = [_read_runtime_map(memory_path)] if memory_path is not None else []
    sources.append(_load_seed_map())
    sets: dict[str, set[str]] = {k: set() for k in LOCI}
    for data in sources:
        raw = data.get("locus") if isinstance(data, dict) else None
        if not isinstance(raw, dict):
            continue
        for k in LOCI:
            sets[k] |= {str(x).strip().lower() for x in (raw.get(k) or [])}

    def locus_of(predicate: str) -> str:
        p = (predicate or "").strip().lower()
        for k in _LOCUS_PRECEDENCE:
            if p and p in sets[k]:
                return k
        return "unknown"

    return locus_of


def locus(memory_path: Path | None, predicate: str) -> str:
    """One-shot convenience wrapper around :func:`build_locus_fn`."""
    return build_locus_fn(memory_path)(predicate)


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
# used to render a resolved claim as a plain-English sentence ("Bob Example
# works at Acme") rather than a raw (subject, predicate, object)
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

    E.g. ``predicate_phrase("works-at", "Bob Example", "Acme")`` ->
    ``"Bob Example works at Acme"``. An unknown predicate falls back
    to a generic, still-readable rendering rather than guessing a verb.
    """
    key = (predicate or "").strip().lower()
    template = PREDICATE_PHRASES.get(key)
    if template:
        return template.format(name=name, obj=obj)
    return f"{name} — {predicate.replace('-', ' ').replace('_', ' ')}: {obj}"
