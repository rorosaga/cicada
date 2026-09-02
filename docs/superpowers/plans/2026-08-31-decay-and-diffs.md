# Decay Classes + Commit-Diff Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every entity a semantic `decay_class` (evergreen/durable/active/volatile) that the agent estimates, both decay engines honor and the user can override, and make git commit diffs visible in the app — tappable entity-history rows and a contributor → commits → entity → diff drill-down.

**Architecture:** One resolver module (`api/services/decay_policy.py`) becomes the single source of truth for "how fast does this entity fade" — every writer that used to hardcode a `decay_rate` float now asks it, both the entity engine (`conflict_resolver`) and the claim engine (`claim_reconciler`) consult it, and a one-shot startup migration backfills the live bank. On the diff side, the already-shipped per-commit diff endpoint gets one sibling (`GET /contributors/commits`) and the SwiftUI app gets one shared `DiffView` + pure `DiffModel` used by both the entity History tab and the Contributors drill-down.

**Tech Stack:** Python 3 / FastAPI / Pydantic v2 (`api/`, venv at `api/.venv`, tests `api/.venv/bin/python -m pytest api/tests -q`); SwiftUI macOS 14 / SwiftPM (`app/CicadaApp`, tests `cd app/CicadaApp && swift test`); git as the versioning + provenance layer; markdown+YAML frontmatter as the store.

**Spec:** `docs/superpowers/specs/2026-08-31-decay-policy-and-history-diffs-design.md` — the authority. Read it alongside this plan.

## Global Constraints

- **Never touch `.claude/settings.json`.** It is modified in the working tree already; leave it alone and never stage it.
- **Never `git add -A`.** Every commit stages explicit paths. (The one pre-existing `git add -A` inside `git_service.commit_changes` is out of scope — new code uses `git_service.commit_paths` or an explicitly-scoped `subprocess` call.)
- **Nothing under `memory/` may appear in any commit on this branch.** The startup backfill migration writes the *bank's own* git repo at runtime; it is never run against the repo you are developing in, and no bank content is committed here.
- **Every commit message ends with these two trailer lines** (after a blank line):
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
  ```
- **Migration commits (written into a bank at runtime) author `cicada`** via `git_service.build_commit_message(subject, body_lines, authors=["cicada"])` — the reserved literal for system-maintenance writes with no model and no user in the loop.
- **User override commits carry `Cicada-Author: user`** and trigger `user/companion_app`.
- **Stage-1 extraction may NEVER emit `evergreen`.** The anti-pollution rail mirrors `PRODUCIBLE_ENTITY_TYPES`: the extractor may propose `durable|active|volatile` only; an over-eager extractor must never be able to stop the graph from archiving.
- **`decay_class` is additive on the wire.** Every new field on `EntityResponse`, `GraphNode`, and the Swift models must decode from an *old* payload/snapshot that omits it (`decodeIfPresent ?? .active` on Swift, a defaulted Pydantic field on Python). Old `SnapshotCache` files on disk must still decode.
- **`has_logo` is the precedent for a new graph-node field:** declare it additive+defaulted on `GraphNode`, populate it in `graph_builder._build_full`, and fold it into the per-node `synthetic_hash(...)` line so the app's `GraphDiff` repaints the node when it changes.
- **Swift views stay `Store` projections.** Snapshot-backed data (graph, contributors) keeps flowing through `Store`; *on-demand* fetches (per-commit diffs, contributor commits, the decay PUT) may call `APIClient` directly from the view/view model — the `LogoStore` / `EntitySource` precedent — and are tested with an injected `URLSession` via `MockURLProtocol` (defined in `Tests/CicadaAppTests/EntitySourceTests.swift`).
- **Python tests are hermetic and `tmp_path`-only.** No test reads the live `memory/` bank, makes an LLM call, or touches the network. The suite's `conftest.py` already forces `CICADA_API_AUTH=off`, `CICADA_ALLOW_LOGO_FETCH=off`, `CICADA_TELEMETRY=off`.
- Backend test command: `api/.venv/bin/python -m pytest api/tests -q`. App test command: `cd app/CicadaApp && swift test`.

---

## File Structure

**Created**

| File | Responsibility |
|---|---|
| `api/services/decay_policy.py` | The single decay resolver: class↔rate mapping, frontmatter resolution, per-writer defaults, the Stage-1 evergreen rail, and a memoised per-bank class lookup for the claim engine. |
| `api/services/decay_migration.py` | The one-shot, marker-guarded startup backfill (media→evergreen, skills→durable) that commits into the bank as `cicada`. |
| `api/tests/test_decay_policy.py` | Resolver precedence, legacy inference, rail, lookup. |
| `api/tests/test_decay_writers.py` | Every writer's frontmatter now carries a class from the resolver; Stage-1 sanitizer. |
| `api/tests/test_decay_engines.py` | Entity engine skips evergreen / recovery promotion; claim engine multiplier. |
| `api/tests/test_decay_migration.py` | Backfill counts, restoration, idempotence, commit author. |
| `api/tests/test_decay_endpoint.py` | `PUT /entities/{id}/decay` + `decay_class` on `EntityResponse`/graph nodes. |
| `api/tests/test_contributor_commits.py` | `get_contributor_commits` trailer filtering + entity extraction + router. |
| `app/CicadaApp/Sources/CicadaApp/Views/Common/DiffView.swift` | Pure `DiffModel` + the shared GitHub-style `DiffView` used by both drill-downs. |
| `app/CicadaApp/Tests/CicadaAppTests/DiffModelTests.swift` | `DiffModel` parsing/kind/truncation + `fetchEntityCommitDiff` over the fake transport. |
| `app/CicadaApp/Tests/CicadaAppTests/ContributorCommitTests.swift` | `ContributorCommit` decoding + `fetchContributorCommits` over the fake transport. |
| `app/CicadaApp/Tests/CicadaAppTests/DecayClassTests.swift` | `DecayClass` decode tolerance + `setDecayClass` PUT wiring. |

**Modified**

| File | Change |
|---|---|
| `api/models/schemas.py` | `DecayClass` enum, `DECAY_CLASS_RATES`, `CLAIM_DECAY_MULTIPLIERS`, `AGENT_PRODUCIBLE_DECAY_CLASSES`; `EntityResponse.decay_class`; `EntityDecayUpdate`; `GraphNode.decay_class`; `ContributorCommit` / `ContributorCommitsResponse`. |
| `api/services/media_ingestor.py:1047-1060` | Literal `0.03` → resolver (`evergreen`). |
| `api/services/inbox_generator.py:255-267` | Literal `0.02` → resolver (`durable`). |
| `api/services/conflict_resolver.py:133-139, 197-211, 222-233, 305-310` | Create-branch class from Stage-1/resolver; decay loop skips evergreen; update branch promotes back on re-mention. |
| `api/services/entity_extractor.py:16-110, 313-322` | Stage-1 JSON schema + prompt paragraph for `decay_class`; `sanitize_decay_class` rail applied per extracted entity. |
| `api/services/agentic_write.py:169-182` | Literal `0.05` → resolver. |
| `api/services/inbox_service.py:592-606` | Literal `0.05` → resolver. |
| `api/services/claim_reconciler.py:410, 428-474` | `_decay_claims` takes a class-lookup fn; `reconcile_stage3` gains `decay_class_fn`. |
| `api/services/graph_builder.py:160-176, 268-273` | `decay_class` on entity nodes, folded into `content_hash`. |
| `api/routers/entities.py:61-78` + new endpoint | `decay_class` on the response; `PUT /entities/{id}/decay`. |
| `api/routers/contributors.py` | `GET /contributors/commits`. |
| `api/services/git_service.py` | `get_contributor_commits`. |
| `api/main.py:39, 108-113` | Wire the backfill into the lifespan. |
| `app/CicadaApp/Sources/CicadaApp/Models/Entity.swift:74-98, 160-200, 451-539, 666-765` | `DecayClass`; `Entity.decayClass`; `GraphNode.decayClass`; `ContributorCommit`/`ContributorCommitsResponse`. |
| `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift:815-828, 918-924` | `fetchContributorCommits`, `setDecayClass`. |
| `app/CicadaApp/Sources/CicadaApp/ViewModels/GraphViewModel.swift:184-206` | Seed the stub entity's `decayClass` from the node. |
| `app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift:748-802, 804-883, 1108-1127` | Decay chip + picker in the metadata strip; tappable history rows with on-demand diffs. |
| `app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorsView.swift` | Expandable contributor rows → commits → entity chips → `DiffView`. |
| `CLAUDE.md`, `docs/goals/memory-evolution.md` | Endpoints, decay-class section, G66/G67 → ✅. |

**Deliberately unchanged (spec §1.9 — do not "fix" these while passing through):**
- `media_ingestor`'s feed-relevance math (its own local `decay_rate` read at line 873) — for an evergreen bookmark the recency term becomes a flat `confidence × 1.0`, which is acceptable: the Feed badge already hides itself when the rendered percentages are uniform (PR #16), and real query relevance is a separate backlog item (G65c).
- Graph node fading (`STATUS_ALPHA` in `Resources/graph/graph.js`) — evergreen entities simply stay `active`, so nothing about the fading rule needs to change.
- `git_service.commit_changes`'s internal `git add -A` — pre-existing, out of scope; all NEW commits in this plan go through `commit_paths` or an explicitly scoped `subprocess` call.

---

### Task 1: `DecayClass` vocabulary + the `decay_policy` resolver

**Files:**
- Modify: `api/models/schemas.py:59-70` (insert after `EntityStatus`, before `NudgeType`)
- Create: `api/services/decay_policy.py`
- Test: `api/tests/test_decay_policy.py`

**Interfaces:**
- Consumes: `api.services.markdown_parser.parse(filepath) -> ParsedMarkdown` (`.frontmatter: dict`, `.body: str`).
- Produces (every later task depends on these exact names):
  - `schemas.DecayClass` — `str, Enum` with members `evergreen | durable | active | volatile`.
  - `schemas.DECAY_CLASS_RATES: dict[DecayClass, float]` = `{evergreen: 0.0, durable: 0.02, active: 0.05, volatile: 0.15}`.
  - `schemas.CLAIM_DECAY_MULTIPLIERS: dict[DecayClass, float]` = `{evergreen: 0.0, durable: 0.5, active: 1.0, volatile: 2.0}`.
  - `schemas.AGENT_PRODUCIBLE_DECAY_CLASSES: frozenset[DecayClass]` = `{durable, active, volatile}`.
  - `decay_policy.DEFAULT_RATE: float` = `0.05`.
  - `decay_policy.coerce(value) -> DecayClass | None` — tolerant parse of any frontmatter/LLM value.
  - `decay_policy.agent_class(value) -> DecayClass | None` — the Stage-1 rail: `coerce` then drop `evergreen`.
  - `decay_policy.resolve(fm: dict) -> tuple[DecayClass, float]`.
  - `decay_policy.default_class_for(entity_type: str | None, source: str = "extraction") -> DecayClass`.
  - `decay_policy.rate_for(cls: DecayClass) -> float`.
  - `decay_policy.claim_multiplier(cls: DecayClass) -> float`.
  - `decay_policy.frontmatter_fields(cls: DecayClass) -> dict` → `{"decay_class": cls.value, "decay_rate": rate_for(cls)}`.
  - `decay_policy.class_lookup(memory_path) -> Callable[[str], DecayClass]` — memoised per call, unknown id → `DecayClass.active`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_decay_policy.py`:

```python
"""G66 — the one decay resolver: class vocabulary, precedence, rail, lookup."""

from __future__ import annotations

from api.models.schemas import (
    AGENT_PRODUCIBLE_DECAY_CLASSES,
    CLAIM_DECAY_MULTIPLIERS,
    DECAY_CLASS_RATES,
    DecayClass,
)
from api.services import decay_policy, markdown_parser


# --- vocabulary -------------------------------------------------------------


def test_rates_and_multipliers_cover_every_class():
    assert set(DECAY_CLASS_RATES) == set(DecayClass)
    assert set(CLAIM_DECAY_MULTIPLIERS) == set(DecayClass)
    assert DECAY_CLASS_RATES == {
        DecayClass.evergreen: 0.0,
        DecayClass.durable: 0.02,
        DecayClass.active: 0.05,
        DecayClass.volatile: 0.15,
    }
    assert CLAIM_DECAY_MULTIPLIERS == {
        DecayClass.evergreen: 0.0,
        DecayClass.durable: 0.5,
        DecayClass.active: 1.0,
        DecayClass.volatile: 2.0,
    }


def test_agent_producible_set_excludes_evergreen():
    assert AGENT_PRODUCIBLE_DECAY_CLASSES == frozenset(
        {DecayClass.durable, DecayClass.active, DecayClass.volatile}
    )


# --- coerce / agent_class ---------------------------------------------------


def test_coerce_accepts_exact_values_and_sloppy_casing():
    assert decay_policy.coerce("evergreen") is DecayClass.evergreen
    assert decay_policy.coerce("  Durable ") is DecayClass.durable
    assert decay_policy.coerce(DecayClass.volatile) is DecayClass.volatile


def test_coerce_rejects_junk_silently():
    for bad in [None, "", "forever", "0.05", 3, "unlimited"]:
        assert decay_policy.coerce(bad) is None, bad


def test_agent_class_drops_evergreen_but_keeps_the_other_three():
    assert decay_policy.agent_class("evergreen") is None
    assert decay_policy.agent_class("EVERGREEN") is None
    assert decay_policy.agent_class("volatile") is DecayClass.volatile
    assert decay_policy.agent_class("durable") is DecayClass.durable
    assert decay_policy.agent_class("active") is DecayClass.active
    assert decay_policy.agent_class("nonsense") is None


# --- resolve ----------------------------------------------------------------


def test_explicit_class_wins_over_legacy_type_inference():
    cls, rate = decay_policy.resolve({"type": "media", "decay_class": "volatile"})
    assert cls is DecayClass.volatile
    assert rate == 0.15


def test_explicit_numeric_rate_wins_over_the_class_map_for_decaying_classes():
    cls, rate = decay_policy.resolve(
        {"type": "concept", "decay_class": "durable", "decay_rate": 0.07}
    )
    assert cls is DecayClass.durable, "the class stays as the label"
    assert rate == 0.07, "an explicit numeric that differs from the map wins"


def test_evergreen_always_resolves_to_a_zero_rate():
    # An evergreen page carrying a stale legacy numeric must still never fade:
    # the class contract is absolute, so it pins the rate.
    cls, rate = decay_policy.resolve(
        {"type": "media", "decay_class": "evergreen", "decay_rate": 0.03}
    )
    assert (cls, rate) == (DecayClass.evergreen, 0.0)


def test_legacy_media_page_infers_evergreen():
    cls, rate = decay_policy.resolve({"type": "media", "decay_rate": 0.03})
    assert (cls, rate) == (DecayClass.evergreen, 0.0)


def test_legacy_skill_page_infers_durable_keeping_its_own_rate():
    cls, rate = decay_policy.resolve({"type": "skill", "decay_rate": 0.02})
    assert (cls, rate) == (DecayClass.durable, 0.02)


def test_everything_else_infers_active_with_the_pages_existing_rate():
    assert decay_policy.resolve({"type": "person", "decay_rate": 0.05}) == (
        DecayClass.active,
        0.05,
    )
    assert decay_policy.resolve({"type": "project", "decay_rate": 0.09}) == (
        DecayClass.active,
        0.09,
    )


def test_missing_rate_falls_back_to_the_default():
    assert decay_policy.resolve({"type": "tool"}) == (DecayClass.active, 0.05)
    assert decay_policy.resolve({}) == (DecayClass.active, 0.05)


def test_unparseable_rate_never_raises():
    assert decay_policy.resolve({"type": "tool", "decay_rate": "fast"}) == (
        DecayClass.active,
        0.05,
    )


# --- default_class_for ------------------------------------------------------


def test_ingest_writers_default_to_evergreen():
    for source in ["media", "bookmark", "rss", "pdf", "ingest"]:
        assert decay_policy.default_class_for("media", source) is DecayClass.evergreen


def test_skill_defaults_to_durable_and_media_type_to_evergreen():
    assert decay_policy.default_class_for("skill") is DecayClass.durable
    assert decay_policy.default_class_for("media") is DecayClass.evergreen


def test_everything_else_defaults_to_active():
    for t in ["person", "project", "company", "concept", "tool", "location", "directory"]:
        assert decay_policy.default_class_for(t) is DecayClass.active
    assert decay_policy.default_class_for(None) is DecayClass.active


def test_volatile_is_never_a_default():
    assert DecayClass.volatile not in {
        decay_policy.default_class_for(t)
        for t in ["person", "project", "skill", "media", "tool", None]
    }


# --- frontmatter_fields -----------------------------------------------------


def test_frontmatter_fields_pairs_the_label_with_its_mapped_rate():
    assert decay_policy.frontmatter_fields(DecayClass.evergreen) == {
        "decay_class": "evergreen",
        "decay_rate": 0.0,
    }
    assert decay_policy.frontmatter_fields(DecayClass.durable) == {
        "decay_class": "durable",
        "decay_rate": 0.02,
    }


# --- class_lookup -----------------------------------------------------------


def _page(memory, entity_id: str, fm_extra: dict) -> None:
    ents = memory / "entities"
    ents.mkdir(parents=True, exist_ok=True)
    fm = {"name": entity_id, "type": "concept", "status": "active", "confidence": 0.7}
    fm.update(fm_extra)
    markdown_parser.write(ents / f"{entity_id}.md", fm, "Body.")


def test_class_lookup_reads_pages_and_defaults_unknown_ids_to_active(tmp_path):
    _page(tmp_path, "bookmark", {"type": "media"})
    _page(tmp_path, "preference", {"type": "skill"})
    _page(tmp_path, "job", {"decay_class": "volatile"})

    lookup = decay_policy.class_lookup(tmp_path)

    assert lookup("bookmark") is DecayClass.evergreen
    assert lookup("preference") is DecayClass.durable
    assert lookup("job") is DecayClass.volatile
    assert lookup("never-heard-of-it") is DecayClass.active


def test_class_lookup_memoises_so_one_sleep_cycle_reads_a_page_once(tmp_path, monkeypatch):
    _page(tmp_path, "job", {"decay_class": "volatile"})
    calls: list[str] = []
    real_parse = markdown_parser.parse

    def counting_parse(path):
        calls.append(str(path))
        return real_parse(path)

    monkeypatch.setattr(decay_policy.markdown_parser, "parse", counting_parse)
    lookup = decay_policy.class_lookup(tmp_path)
    assert lookup("job") is DecayClass.volatile
    assert lookup("job") is DecayClass.volatile
    assert len(calls) == 1


def test_class_lookup_on_a_missing_entities_dir_never_raises(tmp_path):
    lookup = decay_policy.class_lookup(tmp_path / "nope")
    assert lookup("anything") is DecayClass.active
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_decay_policy.py -q`
Expected: FAIL — `ImportError: cannot import name 'DecayClass' from 'api.models.schemas'`.

- [ ] **Step 3: Add the vocabulary to `api/models/schemas.py`**

Insert immediately after the `EntityStatus` class (currently ends at line 63) and before `class NudgeType` (line 66):

```python
class DecayClass(str, Enum):
    """How fast a belief about a life should fade when it stops being mentioned (G66).

    Decay models "absence of mention is a signal" for *beliefs*. A bookmark is an
    *artifact*, not a belief — it does not become less true by going unmentioned,
    so it is ``evergreen`` and never decays at all.
    """

    evergreen = "evergreen"   # never fades — artifacts (media/bookmarks) + user pins
    durable = "durable"       # fades slowly — stable preferences, skills, long-lived concepts
    active = "active"         # the default for a belief about the user's life
    volatile = "volatile"     # expected to change within weeks (role, status, current focus)


# Per-week confidence drop used by the ENTITY decay engine
# (``conflict_resolver.resolve_and_prune``).
DECAY_CLASS_RATES: dict[DecayClass, float] = {
    DecayClass.evergreen: 0.0,
    DecayClass.durable: 0.02,
    DecayClass.active: 0.05,
    DecayClass.volatile: 0.15,
}

# Multiplier applied to the CLAIM decay engine's per-epistemic x source_trust
# rate (``claim_reconciler._decay_claims``), keyed by the SUBJECT entity's class.
# An evergreen subject's claims never decay (0.0).
CLAIM_DECAY_MULTIPLIERS: dict[DecayClass, float] = {
    DecayClass.evergreen: 0.0,
    DecayClass.durable: 0.5,
    DecayClass.active: 1.0,
    DecayClass.volatile: 2.0,
}

# ANTI-POLLUTION RAIL, mirroring ``PRODUCIBLE_ENTITY_TYPES`` above: Stage-1
# extraction may PROPOSE only these three. ``evergreen`` is reserved for the
# ingest writers and for the user, so an over-eager extractor can never stop the
# graph from archiving.
AGENT_PRODUCIBLE_DECAY_CLASSES: frozenset[DecayClass] = frozenset(
    {DecayClass.durable, DecayClass.active, DecayClass.volatile}
)
```

- [ ] **Step 4: Write `api/services/decay_policy.py`**

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_decay_policy.py -q`
Expected: PASS (26 tests).

- [ ] **Step 6: Run the whole backend suite for regressions**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS — nothing consumes the new names yet, so this is a pure addition.

- [ ] **Step 7: Commit**

```bash
git add api/models/schemas.py api/services/decay_policy.py api/tests/test_decay_policy.py
git commit -m "$(cat <<'EOF'
feat(decay): DecayClass vocabulary + the one decay_policy resolver (G66)

evergreen|durable|active|volatile with per-class entity rates and claim
multipliers, a tolerant frontmatter resolver (explicit class wins, legacy
type inference behind it), per-writer defaults, the Stage-1 anti-pollution
rail (agents may never propose evergreen), and a memoised per-bank class
lookup for the claim engine.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 2: Every writer through the resolver + Stage-1 estimates a class

**Files:**
- Modify: `api/services/media_ingestor.py:1047-1060`
- Modify: `api/services/inbox_generator.py:255-267`
- Modify: `api/services/conflict_resolver.py:193-211`
- Modify: `api/services/agentic_write.py:169-182`
- Modify: `api/services/inbox_service.py:592-606`
- Modify: `api/services/entity_extractor.py:16-110` (prompt) and `:313-322` (stamping loop)
- Test: `api/tests/test_decay_writers.py`

**Interfaces:**
- Consumes: `decay_policy.default_class_for(entity_type, source)`, `decay_policy.frontmatter_fields(cls)`, `decay_policy.agent_class(value)`, `schemas.DecayClass` (all from Task 1).
- Produces:
  - `entity_extractor.sanitize_decay_class(entity: dict) -> None` — mutates one extracted entity dict in place, keeping `decay_class` only when `agent_class` accepts it.
  - Every created page now carries a `decay_class:` frontmatter key beside `decay_rate:`.
  - `conflict_resolver`'s `create` branch honors `change["entity"]["decay_class"]` (already sanitized by Stage-1) and falls back to `default_class_for(type)`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_decay_writers.py`:

```python
"""G66 — every entity writer stamps a decay_class from the resolver, and
Stage-1 may never propose `evergreen`."""

from __future__ import annotations

from pathlib import Path

from api.models.schemas import DecayClass
from api.services import (
    agentic_write,
    conflict_resolver,
    entity_extractor,
    inbox_generator,
    markdown_parser,
    media_ingestor,
)


def _fm(memory: Path, entity_id: str) -> dict:
    return markdown_parser.parse(memory / "entities" / f"{entity_id}.md").frontmatter


# --- Stage-1 rail -----------------------------------------------------------


def test_stage1_sanitizer_drops_an_evergreen_proposal(tmp_path):
    entity = {"name": "Some Bookmark", "decay_class": "evergreen"}
    entity_extractor.sanitize_decay_class(entity)
    assert "decay_class" not in entity


def test_stage1_sanitizer_keeps_the_three_producible_classes():
    for value in ["volatile", "durable", "active"]:
        entity = {"name": "X", "decay_class": value}
        entity_extractor.sanitize_decay_class(entity)
        assert entity["decay_class"] == value


def test_stage1_sanitizer_drops_junk_and_leaves_a_missing_key_missing():
    entity = {"name": "X", "decay_class": "forever"}
    entity_extractor.sanitize_decay_class(entity)
    assert "decay_class" not in entity

    bare = {"name": "X"}
    entity_extractor.sanitize_decay_class(bare)
    assert bare == {"name": "X"}


def test_extraction_prompt_offers_the_three_and_forbids_evergreen():
    prompt = entity_extractor.EXTRACTION_SYSTEM_PROMPT
    assert "durable|active|volatile" in prompt
    assert "never evergreen" in prompt.lower()


# --- media ingest -----------------------------------------------------------


def test_media_entity_is_written_evergreen(tmp_path):
    entities_dir = tmp_path / "entities"
    item = media_ingestor.RawItem(url="https://example.com/post", title="A Post")
    meta = media_ingestor.MediaMeta(title="A Post", media_type="bookmark")

    media_ingestor.write_media_entity(entities_dir, "media-a-post", item, meta, "ep_1")

    fm = markdown_parser.parse(entities_dir / "media-a-post.md").frontmatter
    assert fm["decay_class"] == "evergreen"
    assert fm["decay_rate"] == 0.0


# --- skills -----------------------------------------------------------------


def test_skill_entity_is_written_durable(tmp_path):
    (tmp_path / "entities").mkdir(parents=True)
    (tmp_path / "inbox").mkdir(parents=True)

    inbox_generator.generate(
        [], [{"name": "Prefers concise summaries", "description": "Keep it short.",
              "confidence": 0.6}],
        tmp_path,
    )

    fm = _fm(tmp_path, "prefers-concise-summaries")
    assert fm["decay_class"] == "durable"
    assert fm["decay_rate"] == 0.02


# --- Sleep create branch ----------------------------------------------------


def test_created_entity_defaults_to_active(tmp_path):
    (tmp_path / "entities").mkdir(parents=True)
    conflict_resolver.apply_changes(
        [{"id": "acme", "action": "create",
          "entity": {"name": "Acme", "type": "company", "confidence": 0.6}}],
        tmp_path,
    )
    fm = _fm(tmp_path, "acme")
    assert fm["decay_class"] == "active"
    assert fm["decay_rate"] == 0.05


def test_created_entity_honors_a_stage1_volatile_estimate(tmp_path):
    (tmp_path / "entities").mkdir(parents=True)
    conflict_resolver.apply_changes(
        [{"id": "current-role", "action": "create",
          "entity": {"name": "Current Role", "type": "concept",
                     "decay_class": "volatile"}}],
        tmp_path,
    )
    fm = _fm(tmp_path, "current-role")
    assert fm["decay_class"] == "volatile"
    assert fm["decay_rate"] == 0.15


def test_created_entity_ignores_an_evergreen_estimate_that_slipped_through(tmp_path):
    """Defense in depth: even if a payload reaches the writer with `evergreen`,
    the create branch refuses it — the rail is enforced at BOTH ends."""
    (tmp_path / "entities").mkdir(parents=True)
    conflict_resolver.apply_changes(
        [{"id": "mongodb", "action": "create",
          "entity": {"name": "MongoDB", "type": "tool", "decay_class": "evergreen"}}],
        tmp_path,
    )
    fm = _fm(tmp_path, "mongodb")
    assert fm["decay_class"] == "active"


def test_created_skill_page_is_durable_even_from_the_sleep_create_branch(tmp_path):
    (tmp_path / "entities").mkdir(parents=True)
    conflict_resolver.apply_changes(
        [{"id": "concise", "action": "create",
          "entity": {"name": "Concise", "type": "skill"}}],
        tmp_path,
    )
    assert _fm(tmp_path, "concise")["decay_class"] == "durable"


# --- agentic write ----------------------------------------------------------


def test_agentic_created_page_is_active(tmp_path):
    filepath, _entity_id = agentic_write._ensure_subject_page(
        tmp_path, "Some New Thing", "works-at", "ep_1"
    )
    fm = markdown_parser.parse(filepath).frontmatter
    assert fm["decay_class"] == "active"
    assert fm["decay_rate"] == 0.05
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_decay_writers.py -q`
Expected: FAIL — `AttributeError: module 'api.services.entity_extractor' has no attribute 'sanitize_decay_class'`, and `KeyError: 'decay_class'` in the writer tests.

- [ ] **Step 3: Add the Stage-1 schema line, prompt paragraph and sanitizer**

In `api/services/entity_extractor.py`, inside `EXTRACTION_SYSTEM_PROMPT`, add one key to the JSON schema block — after the `"confidence": 0.7,` line (currently line 36):

```
      "decay_class": "durable|active|volatile",
```

Then add this paragraph immediately before `EXTRACTION GUIDELINES:` (currently line 90):

```
DECAY CLASS (optional, per entity) — how fast this belief should fade if it stops
being mentioned:
- volatile: a fact you expect to change within weeks (a current role, a status, a
  current focus, an in-flight decision).
- durable: a stable preference, a skill, or a long-lived concept that rarely moves.
- active: everything else — the default. Omit the field when unsure.
- NEVER emit "evergreen". Only ingested artifacts (bookmarks, saved media) and the
  user may be evergreen; an extraction may never mark a belief as never-fading.
```

Add the module-level import at the top of the file (after `from api.config import Settings`, line 14):

```python
from api.services import decay_policy
```

Add the sanitizer right after `_parse_json_lenient` (i.e. before `_chunk_content`, currently line 198):

```python
def sanitize_decay_class(entity: dict) -> None:
    """Stage-1 anti-pollution rail, applied to ONE extracted entity dict.

    The extractor may PROPOSE ``durable|active|volatile``. Anything else — junk,
    a missing key, or ``evergreen`` (reserved for the ingest writers and the
    user) — is removed so the downstream writer falls back to its own default.
    Mutates in place; never raises.
    """
    if "decay_class" not in entity:
        return
    cls = decay_policy.agent_class(entity.pop("decay_class"))
    if cls is not None:
        entity["decay_class"] = cls.value
```

Call it in the per-entity stamping loop inside `extract`'s `_do_process` (currently lines 315-318), so every entity is sanitized before it reaches the resolver/writer:

```python
                ep_origin = episode.get("origin", "unknown")
                for entity in all_entities:
                    entity["source_episode"] = ep_id
                    entity["source_episode_timestamp"] = episode.get("timestamp")
                    entity["origin"] = ep_origin
                    sanitize_decay_class(entity)
```

- [ ] **Step 4: Route the four remaining writers through the resolver**

`api/services/media_ingestor.py` — add `decay_policy` to the service imports at the top of the file, then replace the literal at line 1054 inside `write_media_entity`'s `frontmatter` dict:

```python
        "last_referenced": today.strftime("%Y-%m-%d"),
        **decay_policy.frontmatter_fields(
            decay_policy.default_class_for("media", source="media")
        ),
        "source_episodes": [episode_id],
```

`api/services/inbox_generator.py` — add `decay_policy` to the imports, then replace line 262 in the skill-creation block:

```python
                "last_referenced": str(date.today()),
                **decay_policy.frontmatter_fields(
                    decay_policy.default_class_for("skill")
                ),
                "source_episodes": [],
```

`api/services/conflict_resolver.py` — add `decay_policy` to the `from api.services import ...` line (currently line 13), then in `apply_changes`'s `create` branch replace line 204:

```python
        if action == "create":
            entity = change.get("entity", {})
            created_date = _earliest_change_date(change) or str(date.today())
            last_referenced = _latest_change_date(change) or created_date
            entity_type = entity.get("type", "concept")
            # Stage-1 may PROPOSE a class; `agent_class` re-applies the rail here
            # so an `evergreen` that slipped past extraction can never be written.
            decay_class = (
                decay_policy.agent_class(entity.get("decay_class"))
                or decay_policy.default_class_for(entity_type)
            )
            frontmatter = {
                "name": entity.get("name", entity_id.replace("-", " ").title()),
                "type": entity_type,
                "status": "active",
                "confidence": entity.get("confidence", 0.5),
                "created": created_date,
                "last_referenced": last_referenced,
                **decay_policy.frontmatter_fields(decay_class),
                "source_episodes": _change_source_episodes(change),
```

(The rest of the dict — `tags`, `aliases`, `related`, `version`, `layout_version` — is unchanged.)

`api/services/agentic_write.py` — add `decay_policy` to the service imports, then replace line 176:

```python
        "created": today,
        "last_referenced": today,
        **decay_policy.frontmatter_fields(
            decay_policy.default_class_for(_infer_entity_type(predicate))
        ),
        "source_episodes": [source_episode] if source_episode else [],
```

`_infer_entity_type(predicate)` is already computed for the `"type"` key, so hoist it into a local and call it once. The whole `frontmatter` block (lines 169-182) becomes:

```python
    entity_type = _infer_entity_type(predicate)
    frontmatter = {
        "name": display_name,
        "type": entity_type,
        "status": "active",
        "confidence": 0.5,
        "created": today,
        "last_referenced": today,
        **decay_policy.frontmatter_fields(decay_policy.default_class_for(entity_type)),
        "source_episodes": [source_episode] if source_episode else [],
        "tags": [],
        "related": [],
        "version": 1,
        "layout_version": 2,
    }
```

`api/services/inbox_service.py` — add `decay_policy` to `from api.services import inbox_questions, markdown_parser` (line 18), then in the clarification `answer` branch's create-page dict replace line 601:

```python
            entity_type = str(
                parsed.frontmatter.get("suggested_classification", "concept")
            ).split(" ")[0].lower()
            frontmatter = {
                "name": entity_mention,
                "type": entity_type,
                "status": "active",
                "confidence": parsed.frontmatter.get("suggested_confidence", 0.5),
                "created": source_date,
                "last_referenced": source_date,
                **decay_policy.frontmatter_fields(
                    decay_policy.default_class_for(entity_type)
                ),
                "source_episodes": [source_episode] if source_episode else [],
```

- [ ] **Step 5: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_decay_writers.py -q`
Expected: PASS (11 tests).

- [ ] **Step 6: Run the whole backend suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS. If `api/tests/test_extractor_robustness.py` or `api/tests/test_entity_media.py` assert on an exact frontmatter dict, update those assertions to expect the added `decay_class` key — the key is additive, so the fix is to add it to the expected dict, never to drop it from the writer.

- [ ] **Step 7: Commit**

```bash
git add api/services/entity_extractor.py api/services/media_ingestor.py \
        api/services/inbox_generator.py api/services/conflict_resolver.py \
        api/services/agentic_write.py api/services/inbox_service.py \
        api/tests/test_decay_writers.py
git commit -m "$(cat <<'EOF'
feat(decay): every entity writer stamps a resolved decay_class (G66)

media ingest -> evergreen, skills -> durable, Sleep/agentic/clarification
creates -> active. Stage-1 gains an optional decay_class in its JSON schema
plus one prompt paragraph, sanitized by the evergreen rail at extraction AND
re-checked in the create branch, so an over-eager extractor can never mark a
belief as never-fading.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 3: The entity engine honors the class, and re-mention finally restores

**Files:**
- Modify: `api/services/conflict_resolver.py:121-171` (decay loop), `:222-233` (update branch)
- Test: `api/tests/test_decay_engines.py` (first half; Task 4 appends to the same file)

**Interfaces:**
- Consumes: `decay_policy.resolve(fm) -> (DecayClass, float)`, `schemas.DecayClass` (Task 1).
- Produces: `resolve_and_prune` emits **no** change record at all for an evergreen entity; `apply_changes`'s `update` branch sets `status: active` and `confidence = max(current, 0.6)` when re-mentioning a `decaying`/`archived` page (never a `dropped` one).

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_decay_engines.py`:

```python
"""G66 — both decay engines honor the class, and re-mention restores.

Hermetic: `resolve_and_prune` is driven with an EMPTY `resolved` list so the
synthesis/contradiction LLM path is never entered (it iterates only over
`action == "update"` changes). No network, no model.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path

from api.models.schemas import DecayClass
from api.services import conflict_resolver, markdown_parser


class _FakeSettings:
    memory_path = None
    archive_threshold = 0.2
    decay_nudge_threshold = 0.4


def run(coro):
    return asyncio.run(coro)


def _existing(entity_id: str, days_ago: int = 35, **fm) -> dict:
    """One unreferenced existing entity. 35 days = 5 weeks by default, chosen so
    volatile floors to 0.0 while active and durable both stay above zero — the
    three classes are then distinguishable in one assertion."""
    base = {
        "name": entity_id.replace("-", " ").title(),
        "type": "concept",
        "status": "active",
        "confidence": 0.7,
        "last_referenced": str(date.today() - timedelta(days=days_ago)),
    }
    base.update(fm)
    return {"id": entity_id, "frontmatter": base, "body": "Body."}


def _by_id(changes: list[dict]) -> dict[str, dict]:
    return {c["id"]: c for c in changes if c.get("action") != "conflict_nudge"}


# --- evergreen is skipped outright -----------------------------------------


def test_evergreen_entity_produces_no_decay_change_at_all():
    changes = run(
        conflict_resolver.resolve_and_prune(
            [], [_existing("media-a-post", type="media")], _FakeSettings()
        )
    )
    assert changes == [], "an evergreen entity must not decay, nudge or archive"


def test_evergreen_by_explicit_class_is_skipped_even_for_a_normal_type():
    changes = run(
        conflict_resolver.resolve_and_prune(
            [], [_existing("pinned", type="concept", decay_class="evergreen")],
            _FakeSettings(),
        )
    )
    assert changes == []


# --- the other three classes decay at their own rates -----------------------


def test_volatile_decays_faster_than_active_which_decays_faster_than_durable():
    existing = [
        _existing("vol", decay_class="volatile"),
        _existing("act", decay_class="active"),
        _existing("dur", decay_class="durable"),
    ]
    changes = _by_id(run(conflict_resolver.resolve_and_prune([], existing, _FakeSettings())))

    vol = changes["vol"]["new_confidence"]
    act = changes["act"]["new_confidence"]
    dur = changes["dur"]["new_confidence"]
    assert vol < act < dur
    # 35 days = 5 weeks from 0.7: volatile (0.15/wk) drops 0.75 and floors at
    # 0.0 -> archived; active drops 0.25; durable drops 0.10 and barely moves.
    assert vol == 0.0
    assert changes["vol"]["action"] == "archive"
    assert changes["act"]["action"] == "decay"
    assert changes["dur"]["action"] == "decay"


def test_an_explicit_numeric_rate_still_wins_for_a_decaying_class():
    changes = _by_id(
        run(
            conflict_resolver.resolve_and_prune(
                [], [_existing("slow", decay_class="active", decay_rate=0.0)],
                _FakeSettings(),
            )
        )
    )
    assert changes["slow"]["new_confidence"] == 0.7, "a 0.0 rate never moves confidence"


def test_a_legacy_page_with_no_class_decays_exactly_as_before():
    changes = _by_id(
        run(
            conflict_resolver.resolve_and_prune(
                [], [_existing("legacy", days_ago=140, decay_rate=0.05)], _FakeSettings()
            )
        )
    )
    # 140 days = 20 weeks * 0.05 = 1.0 drop -> floored at 0.0 -> archived,
    # exactly what the pre-G66 engine did for this page.
    assert changes["legacy"]["action"] == "archive"
    assert changes["legacy"]["new_confidence"] == 0.0


def test_archived_and_dropped_entities_are_still_skipped():
    existing = [
        _existing("gone", status="archived"),
        _existing("nope", status="dropped"),
    ]
    assert run(conflict_resolver.resolve_and_prune([], existing, _FakeSettings())) == []


# --- recovery on re-mention -------------------------------------------------


def _page(memory: Path, entity_id: str, **fm) -> Path:
    ents = memory / "entities"
    ents.mkdir(parents=True, exist_ok=True)
    base = {
        "name": entity_id.title(),
        "type": "concept",
        "status": "active",
        "confidence": 0.5,
        "created": "2026-01-01",
        "last_referenced": "2026-01-01",
        "decay_rate": 0.05,
        "source_episodes": [],
        "tags": [],
        "related": [],
        "version": 1,
    }
    base.update(fm)
    path = ents / f"{entity_id}.md"
    markdown_parser.write(path, base, "## Summary\n\nA thing.")
    return path


def _update(entity_id: str) -> dict:
    return {
        "id": entity_id,
        "action": "update",
        "entity": {"name": entity_id.title(), "type": "concept"},
        "source_episode": "ep_2026-08-31_001",
    }


def test_a_decaying_entity_is_promoted_back_on_re_mention(tmp_path):
    path = _page(tmp_path, "salesforce", status="decaying", confidence=0.32)
    conflict_resolver.apply_changes([_update("salesforce")], tmp_path)
    fm = markdown_parser.parse(path).frontmatter
    assert fm["status"] == "active"
    assert fm["confidence"] == 0.6


def test_an_archived_entity_is_promoted_back_on_re_mention(tmp_path):
    path = _page(tmp_path, "postgres", status="archived", confidence=0.05)
    conflict_resolver.apply_changes([_update("postgres")], tmp_path)
    fm = markdown_parser.parse(path).frontmatter
    assert fm["status"] == "active"
    assert fm["confidence"] == 0.6


def test_recovery_never_lowers_a_confidence_that_is_already_higher(tmp_path):
    path = _page(tmp_path, "cicada", status="decaying", confidence=0.85)
    conflict_resolver.apply_changes([_update("cicada")], tmp_path)
    fm = markdown_parser.parse(path).frontmatter
    assert fm["status"] == "active"
    assert fm["confidence"] == 0.85


def test_a_dropped_entity_is_never_resurrected(tmp_path):
    path = _page(tmp_path, "banished", status="dropped", confidence=0.1)
    conflict_resolver.apply_changes([_update("banished")], tmp_path)
    fm = markdown_parser.parse(path).frontmatter
    assert fm["status"] == "dropped", "user-dismissed means never resurfaced"
    assert fm["confidence"] == 0.1


def test_an_active_entity_keeps_its_confidence_on_re_mention(tmp_path):
    path = _page(tmp_path, "steady", status="active", confidence=0.45)
    conflict_resolver.apply_changes([_update("steady")], tmp_path)
    fm = markdown_parser.parse(path).frontmatter
    assert fm["status"] == "active"
    assert fm["confidence"] == 0.45, "recovery only fires for decaying/archived pages"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_decay_engines.py -q`
Expected: FAIL — the evergreen tests get a `decay`/`archive` change instead of `[]`, and the recovery tests still read `status: decaying`.

- [ ] **Step 3: Skip evergreen in the decay loop**

In `api/services/conflict_resolver.py`, replace the confidence/rate read inside `resolve_and_prune`'s decay loop (currently lines 132-139):

```python
        confidence = fm.get("confidence", 0.5)
        decay_class, decay_rate = decay_policy.resolve(fm)
        if decay_class is DecayClass.evergreen:
            # An artifact, not a belief: it does not become less true by going
            # unmentioned. No decay math, no decay nudge, never auto-archived.
            continue
        days_since = _days_since_last_referenced(fm.get("last_referenced"), now)
```

Add `DecayClass` to the imports at the top of the module:

```python
from api.models.schemas import DecayClass
```

(`decay_policy` was already added to the `from api.services import ...` line in Task 2.)

Also update the stale comment on line 109 so it names the resolver:

```python
    # Temporal decay for unreferenced entities. The per-week rate and the class
    # both come from `decay_policy.resolve` — evergreen entities are skipped.
```

- [ ] **Step 4: Promote back on re-mention**

In `apply_changes`, inside the `elif action == "update" and filepath.exists():` branch, insert the recovery immediately after the `last_referenced` / `version` bump (i.e. right after line 228's `parsed.frontmatter["version"] = ...`):

```python
            # Recovery (G66 §1.6): a re-mention is the counter-signal to decay.
            # CLAUDE.md has always promised "if mentioned again: promoted back,
            # confidence restored" — before this, only `last_referenced` moved.
            # `dropped` is deliberately excluded: the user dismissed that entity
            # and it is never resurfaced.
            if str(parsed.frontmatter.get("status", "active")) in ("decaying", "archived"):
                parsed.frontmatter["status"] = "active"
                parsed.frontmatter["confidence"] = max(
                    float(parsed.frontmatter.get("confidence", 0.0) or 0.0),
                    RECOVERY_CONFIDENCE,
                )
```

Add the constant just below the module's imports (after line 14):

```python
# Confidence floor a decaying/archived entity is restored to when it is
# mentioned again (G66 §1.6) — high enough to clear `decay_nudge_threshold`
# (0.4) and `archive_threshold` (0.2) with room to spare, low enough that a
# single passing mention doesn't outrank a well-established belief.
RECOVERY_CONFIDENCE = 0.6
```

- [ ] **Step 5: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_decay_engines.py -q`
Expected: PASS (12 tests).

- [ ] **Step 6: Run the whole backend suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS. Watch `api/tests/test_sleep_cycle_*.py` and `api/tests/test_conflict_resolver_human_safe.py` — if any fixture uses a `decaying` page and asserts the status is unchanged after an update, that assertion is now wrong by design; update it to expect the promotion.

- [ ] **Step 7: Commit**

```bash
git add api/services/conflict_resolver.py api/tests/test_decay_engines.py
git commit -m "$(cat <<'EOF'
feat(decay): entity engine honors decay_class; re-mention restores (G66)

The decay loop takes its per-week rate from decay_policy.resolve and skips
evergreen entities outright — no decay math, no decay nudge, never
auto-archived, so a bookmark can no longer generate a "still interested?"
question. The update branch finally implements the recovery half of "time as
a signal": a decaying/archived page mentioned again goes back to active with
confidence restored to at least 0.6. `dropped` is never resurrected.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 4: The claim engine weights decay by the subject's class

**Files:**
- Modify: `api/services/claim_reconciler.py:44-52` (docstring), `:317-324` (signature), `:410` (call site), `:428-450` (`_decay_claims`)
- Test: `api/tests/test_decay_engines.py` (append)

**Interfaces:**
- Consumes: `decay_policy.class_lookup(memory_path)`, `decay_policy.claim_multiplier(cls)`, `schemas.DecayClass` (Task 1).
- Produces:
  - `claim_reconciler.reconcile_stage3(..., decay_class_fn: DecayClassFn | None = None)` — keyword-only, defaults to `decay_policy.class_lookup(settings.memory_path)`.
  - `claim_reconciler.DecayClassFn = Callable[[str], DecayClass]` type alias.
  - `_decay_claims(reconciled, referenced_subjects, settings, nudges, today, decay_class_fn)` — positional `decay_class_fn` as the last parameter.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_decay_engines.py`:

```python
# --------------------------------------------------------------------------- #
# Claim engine — the subject's class multiplies the per-claim decay rate
# --------------------------------------------------------------------------- #

from api.services import predicates  # noqa: E402
from api.services.claim_reconciler import reconcile_stage3  # noqa: E402
from api.services.claims import Claim  # noqa: E402


class _ClaimSettings:
    def __init__(self, memory_path):
        self.memory_path = memory_path
        self.litellm_model = "test-model"
        self.archive_threshold = 0.2
        self.decay_nudge_threshold = 0.4


def _open_claim(subject: str, cid: str) -> Claim:
    return Claim(
        id=cid,
        text=f"{subject} uses postgres",
        subject=subject,
        predicate="uses",
        object="postgres",
        observer="agent",
        context="general",
        epistemic="explicit",          # _DECAY_BASE 0.02
        source_trust="agent_extracted",  # _DECAY_FACTOR 1.0
        confidence=0.9,
        valid_from="2026-01-01",
        recorded_at="2026-01-01",
    )


def _decayed_confidence(tmp_path, cls_value: str) -> float:
    predicates.install_predicate_map(tmp_path)
    claim = _open_claim("subj", "clm_1")
    reconciled, _nudges, _audit = reconcile_stage3(
        [],
        {"subj": [claim]},
        _ClaimSettings(tmp_path),
        cardinality_fn=lambda _p: True,
        now_date="2026-04-01",  # 90 days ~ 12.857 weeks
        decay_class_fn=lambda _sid: DecayClass(cls_value),
    )
    return reconciled["subj"][0].confidence


def test_an_evergreen_subjects_claims_never_decay(tmp_path):
    assert _decayed_confidence(tmp_path, "evergreen") == 0.9


def test_a_volatile_subjects_claims_decay_twice_as_fast_as_an_active_one(tmp_path):
    active_drop = 0.9 - _decayed_confidence(tmp_path, "active")
    volatile_drop = 0.9 - _decayed_confidence(tmp_path, "volatile")
    durable_drop = 0.9 - _decayed_confidence(tmp_path, "durable")

    assert active_drop > 0
    assert abs(volatile_drop - 2 * active_drop) < 1e-9
    assert abs(durable_drop - 0.5 * active_drop) < 1e-9


def test_the_default_lookup_reads_the_subjects_page_when_none_is_injected(tmp_path):
    predicates.install_predicate_map(tmp_path)
    _page(tmp_path, "bookmarked", type="media")

    reconciled, _n, _a = reconcile_stage3(
        [],
        {"bookmarked": [_open_claim("bookmarked", "clm_2")]},
        _ClaimSettings(tmp_path),
        cardinality_fn=lambda _p: True,
        now_date="2026-04-01",
    )
    assert reconciled["bookmarked"][0].confidence == 0.9, (
        "the media page resolves to evergreen, so its claims must not decay"
    )


def test_a_subject_with_no_page_decays_at_the_neutral_active_rate(tmp_path):
    predicates.install_predicate_map(tmp_path)
    reconciled, _n, _a = reconcile_stage3(
        [],
        {"ghost": [_open_claim("ghost", "clm_3")]},
        _ClaimSettings(tmp_path),
        cardinality_fn=lambda _p: True,
        now_date="2026-04-01",
    )
    assert reconciled["ghost"][0].confidence == _decayed_confidence(tmp_path, "active")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_decay_engines.py -q -k claim or subject`
Expected: FAIL — `TypeError: reconcile_stage3() got an unexpected keyword argument 'decay_class_fn'`.

- [ ] **Step 3: Thread the lookup through the reconciler**

In `api/services/claim_reconciler.py`, extend the imports (line 38) and add the type alias next to `CardinalityFn` (line 42):

```python
from api.services import decay_policy, inbox_questions, predicates
from api.models.schemas import DecayClass
```

```python
# A decay-class oracle: subject entity id -> the subject's DecayClass. Injected
# so this module stays pure trust/temporal logic with no filesystem dependency.
DecayClassFn = Callable[[str], DecayClass]
```

Extend the decay-table comment (lines 44-52) with the new factor:

```python
# source_trust multiplier — user_stated fades ~3x slower than routine extraction.
_DECAY_FACTOR = {
    "user_stated": 0.3,
    "agent_extracted": 1.0,
    "agent_reflected": 1.5,
    "external": 1.0,
}
# A THIRD factor (G66): the SUBJECT entity's decay class. An evergreen subject
# multiplies to 0.0 — its claims never decay — while a volatile subject's fade
# twice as fast. See ``schemas.CLAIM_DECAY_MULTIPLIERS``.
```

Add the parameter to `reconcile_stage3` (line 317-324):

```python
def reconcile_stage3(
    incoming_claims: list[Claim],
    existing_claims_by_subject: dict[str, list[Claim]],
    settings,
    *,
    cardinality_fn: CardinalityFn | None = None,
    now_date: str | None = None,
    decay_class_fn: DecayClassFn | None = None,
) -> tuple[dict[str, list[Claim]], list[dict], list[dict]]:
```

Document it in the existing docstring's Args block, after `cardinality_fn`:

```
        decay_class_fn: ``subject_id -> DecayClass``, multiplying each claim's
            decay by its subject entity's class (G66). Defaults to the
            filesystem lookup for ``settings.memory_path``; an evergreen subject
            means its claims never decay.
```

Default it beside `cardinality_fn` (after line 346):

```python
    if decay_class_fn is None:
        decay_class_fn = decay_policy.class_lookup(getattr(settings, "memory_path", "."))
```

Pass it at the call site (line 410):

```python
    _decay_claims(reconciled, referenced_subjects, settings, nudges, today, decay_class_fn)
```

- [ ] **Step 4: Apply the multiplier in `_decay_claims`**

Replace the signature (line 428-434) and the rate computation (lines 438-448):

```python
def _decay_claims(
    reconciled: dict[str, list[Claim]],
    referenced_subjects: set[str],
    settings,
    nudges: list[dict],
    today: str,
    decay_class_fn: DecayClassFn,
) -> None:
    archive_threshold = float(getattr(settings, "archive_threshold", 0.2) or 0.2)
    nudge_threshold = float(getattr(settings, "decay_nudge_threshold", 0.4) or 0.4)

    for subject, claims in reconciled.items():
        if subject in referenced_subjects:
            continue
        # One lookup per subject, not per claim.
        multiplier = decay_policy.claim_multiplier(decay_class_fn(subject))
        if multiplier <= 0:
            continue  # evergreen subject: its claims are artifacts, they don't fade
        for c in claims:
            if not open_(c):
                continue  # closed claims don't decay; they're history
            base = _DECAY_BASE.get(c.epistemic, 0.02)
            factor = _DECAY_FACTOR.get(c.source_trust, 1.0)
            ref = c.recorded_at or c.valid_from
            days = _days_since(ref, today)
            amount = base * factor * multiplier * (days / 7.0)
            if amount <= 0:
                continue
```

(The rest of the loop — `new_conf`, the equality guard, the two nudge branches — is unchanged.)

- [ ] **Step 5: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_decay_engines.py -q`
Expected: PASS (16 tests).

- [ ] **Step 6: Run the whole backend suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS. `api/tests/test_claim_reconciler.py` uses `_FakeSettings(tmp_path)` with a real `memory_path`, so the default lookup finds no entity pages and returns `active` (multiplier 1.0) — identical to the pre-change behavior.

- [ ] **Step 7: Commit**

```bash
git add api/services/claim_reconciler.py api/tests/test_decay_engines.py
git commit -m "$(cat <<'EOF'
feat(decay): claim engine multiplies decay by the subject's class (G66)

_decay_claims gains a third factor beside epistemic base and source_trust:
the SUBJECT entity's DecayClass, supplied by an injected lookup fn that
defaults to reading the bank. An evergreen subject multiplies to 0.0, so a
bookmark's claims never fade; a volatile subject's fade twice as fast.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 5: One-shot startup backfill migration

**Files:**
- Create: `api/services/decay_migration.py`
- Modify: `api/main.py:39` (import), `:108-116` (lifespan)
- Test: `api/tests/test_decay_migration.py`

**Interfaces:**
- Consumes: `decay_policy.frontmatter_fields(cls)`, `schemas.DecayClass` (Task 1); `git_service.build_commit_message(subject, body_lines, authors=[...])`.
- Produces: `decay_migration.backfill_decay_classes(memory_path) -> dict` returning `{"media": int, "skills": int, "restored": int}`; marker file `<memory>/.decay_classed`.

**Migration rules (spec §1.8), applied to every `entities/*.md`:**
- `type: media` → `decay_class: evergreen`, `decay_rate: 0.0`; and if `status` is `decaying` or `archived` (never `dropped`), restore `status: active` with `confidence = max(current, 0.7)`.
- `type: skill` → `decay_class: durable` (rate stays `0.02`).
- A page that already carries a parseable `decay_class:` is left alone (idempotence at the file level, on top of the marker).
- Commit is scoped to `entities` only, trigger `maintenance/decay_class_backfill`, `Cicada-Author: cicada`.
- The marker is written **only after** a successful commit (or when there was nothing to change), mirroring `inbox_migration.dedup_open_items`, so a failed commit retries on the next boot.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_decay_migration.py`:

```python
"""G66 §1.8 — the one-shot startup backfill (media -> evergreen, skills -> durable)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from api.services import decay_migration, markdown_parser


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def _init_memory(tmp_path: Path) -> Path:
    repo = tmp_path / "memory"
    (repo / "entities").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")
    return repo


def _page(repo: Path, entity_id: str, **fm) -> Path:
    base = {
        "name": entity_id.replace("-", " ").title(),
        "type": "concept",
        "status": "active",
        "confidence": 0.7,
        "created": "2026-01-01",
        "last_referenced": "2026-01-01",
        "decay_rate": 0.05,
        "source_episodes": [],
        "tags": [],
        "related": [],
        "version": 1,
    }
    base.update(fm)
    path = repo / "entities" / f"{entity_id}.md"
    markdown_parser.write(path, base, "## Summary\n\nA thing.")
    return path


def _fm(path: Path) -> dict:
    return markdown_parser.parse(path).frontmatter


def _seed(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")


def test_media_pages_become_evergreen_with_a_zero_rate(tmp_path):
    repo = _init_memory(tmp_path)
    a = _page(repo, "media-one", type="media", decay_rate=0.03)
    b = _page(repo, "media-two", type="media", decay_rate=0.03)
    _seed(repo)

    counts = decay_migration.backfill_decay_classes(repo)

    assert counts["media"] == 2
    for path in (a, b):
        fm = _fm(path)
        assert fm["decay_class"] == "evergreen"
        assert fm["decay_rate"] == 0.0


def test_decayed_and_archived_media_are_restored_to_active(tmp_path):
    repo = _init_memory(tmp_path)
    decayed = _page(repo, "media-fading", type="media", status="decaying", confidence=0.31)
    archived = _page(repo, "media-gone", type="media", status="archived", confidence=0.05)
    high = _page(repo, "media-strong", type="media", status="archived", confidence=0.92)
    _seed(repo)

    counts = decay_migration.backfill_decay_classes(repo)

    assert counts["restored"] == 3
    assert _fm(decayed)["status"] == "active" and _fm(decayed)["confidence"] == 0.7
    assert _fm(archived)["status"] == "active" and _fm(archived)["confidence"] == 0.7
    assert _fm(high)["confidence"] == 0.92, "never lower a confidence that is already higher"


def test_a_dropped_media_page_is_never_restored(tmp_path):
    repo = _init_memory(tmp_path)
    dropped = _page(repo, "media-banished", type="media", status="dropped", confidence=0.1)
    _seed(repo)

    decay_migration.backfill_decay_classes(repo)

    fm = _fm(dropped)
    assert fm["status"] == "dropped", "user-dismissed means never resurfaced"
    assert fm["decay_class"] == "evergreen", "the class is still corrected"


def test_skill_pages_become_durable_keeping_their_rate(tmp_path):
    repo = _init_memory(tmp_path)
    skill = _page(repo, "prefers-brevity", type="skill", decay_rate=0.02)
    _seed(repo)

    counts = decay_migration.backfill_decay_classes(repo)

    assert counts["skills"] == 1
    fm = _fm(skill)
    assert fm["decay_class"] == "durable"
    assert fm["decay_rate"] == 0.02


def test_other_types_are_left_completely_untouched(tmp_path):
    repo = _init_memory(tmp_path)
    person = _page(repo, "rodrigo", type="person")
    before = person.read_text(encoding="utf-8")
    _seed(repo)

    decay_migration.backfill_decay_classes(repo)

    assert person.read_text(encoding="utf-8") == before


def test_a_page_that_already_has_a_class_is_not_rewritten(tmp_path):
    repo = _init_memory(tmp_path)
    pinned = _page(repo, "media-pinned", type="media", decay_class="volatile", decay_rate=0.15)
    before = pinned.read_text(encoding="utf-8")
    _seed(repo)

    counts = decay_migration.backfill_decay_classes(repo)

    assert counts["media"] == 0
    assert pinned.read_text(encoding="utf-8") == before


def test_the_commit_is_scoped_authored_cicada_and_tagged_with_its_trigger(tmp_path):
    repo = _init_memory(tmp_path)
    _page(repo, "media-one", type="media")
    _seed(repo)
    # An unrelated dirty file must NOT be swept into the migration commit.
    (repo / "scratch.txt").write_text("dirty", encoding="utf-8")

    decay_migration.backfill_decay_classes(repo)

    log = _git(repo, "log", "--format=%s%n%b", "-1")
    assert "Cicada-Author: cicada" in log
    assert "maintenance/decay_class_backfill" in log
    assert "scratch.txt" in _git(repo, "status", "--porcelain")


def test_the_migration_is_idempotent_and_marker_guarded(tmp_path):
    repo = _init_memory(tmp_path)
    _page(repo, "media-one", type="media")
    _page(repo, "skill-one", type="skill")
    _seed(repo)

    first = decay_migration.backfill_decay_classes(repo)
    assert first["media"] == 1 and first["skills"] == 1
    assert (repo / ".decay_classed").exists()

    second = decay_migration.backfill_decay_classes(repo)
    assert second == {"media": 0, "skills": 0, "restored": 0}


def test_nothing_to_migrate_still_writes_the_marker_and_makes_no_commit(tmp_path):
    repo = _init_memory(tmp_path)
    _page(repo, "rodrigo", type="person")
    _seed(repo)
    head_before = _git(repo, "rev-parse", "HEAD").strip()

    assert decay_migration.backfill_decay_classes(repo) == {
        "media": 0, "skills": 0, "restored": 0
    }
    assert (repo / ".decay_classed").exists()
    assert _git(repo, "rev-parse", "HEAD").strip() == head_before


def test_a_non_git_directory_still_migrates_on_disk_without_raising(tmp_path):
    plain = tmp_path / "no-git"
    (plain / "entities").mkdir(parents=True)
    path = _page(plain, "media-one", type="media")

    counts = decay_migration.backfill_decay_classes(plain)

    assert counts["media"] == 1
    assert _fm(path)["decay_class"] == "evergreen"


def test_an_unparseable_page_is_skipped_not_fatal(tmp_path):
    repo = _init_memory(tmp_path)
    (repo / "entities" / "broken.md").write_text("---\n: : :\n---\nbody", encoding="utf-8")
    good = _page(repo, "media-one", type="media")
    _seed(repo)

    counts = decay_migration.backfill_decay_classes(repo)

    assert counts["media"] == 1
    assert _fm(good)["decay_class"] == "evergreen"


def test_a_missing_entities_dir_never_raises(tmp_path):
    assert decay_migration.backfill_decay_classes(tmp_path / "nope") == {
        "media": 0, "skills": 0, "restored": 0
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_decay_migration.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.services.decay_migration'`.

- [ ] **Step 3: Write `api/services/decay_migration.py`**

```python
"""G66 §1.8 — one-shot, idempotent backfill of ``decay_class`` into a bank.

Runs on API startup, once per bank, guarded by a ``.decay_classed`` marker in
exactly the shape ``inbox_migration.dedup_open_items`` uses. It corrects the two
populations the old hardcoded rates got wrong:

- ``type: media`` (bookmarks, saved videos, images) -> ``evergreen`` /
  ``decay_rate: 0.0``. These are ARTIFACTS, not beliefs; they never should have
  decayed. Any of them already ``decaying``/``archived`` (never ``dropped`` —
  that is a user dismissal) is restored to ``active`` with
  ``confidence = max(current, 0.7)``.
- ``type: skill`` -> ``durable``; the rate stays where it was (0.02).

Every other type keeps decaying exactly as before and its file is not touched.

Never raises: a failure is logged loudly and boot continues. The marker is
written only after a clean run (commit succeeded, or nothing needed changing),
so a failed commit retries on the next boot.

This is a SYSTEM MAINTENANCE write — no model and no user in the loop — so the
commit is authored by the reserved ``cicada`` literal.
"""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

from loguru import logger

from api.models.schemas import DecayClass
from api.services import decay_policy, git_service, markdown_parser

_MARKER = ".decay_classed"

# Confidence floor for a media page the old decay engine wrongly faded.
RESTORE_CONFIDENCE = 0.7

TRIGGER = "maintenance/decay_class_backfill"


def backfill_decay_classes(memory_path) -> dict:
    """Backfill one bank. Returns ``{"media": n, "skills": n, "restored": n}``."""
    memory_path = Path(memory_path)
    empty = {"media": 0, "skills": 0, "restored": 0}
    entities_dir = memory_path / "entities"
    if not entities_dir.exists():
        return empty

    marker = memory_path / _MARKER
    if marker.exists():
        return empty

    try:
        counts = _rewrite_pages(entities_dir)
    except Exception as e:
        logger.error(f"Decay-class backfill FAILED — leaving entities/ untouched: {e}")
        return empty

    changed = counts["media"] + counts["skills"]
    if changed:
        try:
            _commit_backfill(memory_path, counts)
        except Exception as e:
            # Pages are corrected on disk but the commit failed (or this isn't a
            # git repo). Do NOT write the marker: the rewrite itself is
            # idempotent (already-classed pages are skipped), so a later boot
            # retries the commit with 0 further changes.
            logger.warning(f"Decay-class backfill commit skipped: {e}")
            return counts

    marker.write_text("v1", encoding="utf-8")
    return counts


def _rewrite_pages(entities_dir: Path) -> dict:
    counts = {"media": 0, "skills": 0, "restored": 0}

    for filepath in sorted(entities_dir.glob("*.md")):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue  # a malformed page is skipped, never fatal
        fm = parsed.frontmatter or {}
        if not isinstance(fm, dict):
            continue
        if decay_policy.coerce(fm.get("decay_class")) is not None:
            continue  # already classed — file-level idempotence

        entity_type = str(fm.get("type", "") or "").strip().lower()
        if entity_type == "media":
            fm.update(decay_policy.frontmatter_fields(DecayClass.evergreen))
            if str(fm.get("status", "active") or "active") in ("decaying", "archived"):
                fm["status"] = "active"
                fm["confidence"] = max(
                    float(fm.get("confidence", 0.0) or 0.0), RESTORE_CONFIDENCE
                )
                counts["restored"] += 1
            counts["media"] += 1
        elif entity_type == "skill":
            # The class is the label; the page keeps whatever rate it had (0.02).
            fm["decay_class"] = DecayClass.durable.value
            counts["skills"] += 1
        else:
            continue

        markdown_parser.write(filepath, fm, parsed.body)

    return counts


def _commit_backfill(memory_path: Path, counts: dict) -> None:
    """Commit scoped to ONLY ``entities`` (never ``git add -A``)."""
    subprocess.run(["git", "add", "--", "entities"], cwd=str(memory_path), check=True)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "entities"],
        cwd=str(memory_path), check=True, capture_output=True, text=True,
    )
    if not status.stdout.strip():
        return
    message = git_service.build_commit_message(
        f"Backfill decay classes {date.today().isoformat()}",
        [
            f"entities/: {counts['media']} media page(s) -> evergreen, "
            f"{counts['skills']} skill(s) -> durable, "
            f"{counts['restored']} restored to active (trigger: {TRIGGER})"
        ],
        authors=["cicada"],
    )
    subprocess.run(
        ["git", "commit", "-m", message, "--", "entities"],
        cwd=str(memory_path),
        check=True,
    )
```

- [ ] **Step 4: Wire it into the API lifespan**

In `api/main.py`, extend the import on line 39:

```python
from api.services.decay_migration import backfill_decay_classes
from api.services.inbox_migration import dedup_open_items, migrate_to_inbox
```

Then insert after the G60 dedup block (currently lines 108-112), before the entity/episode count log:

```python
    # G66: one-time backfill of `decay_class` for pages written before the
    # class vocabulary existed (media -> evergreen, skills -> durable). Same
    # never-crash-boot contract; marker-guarded, authored `cicada`.
    classed = backfill_decay_classes(settings.memory_path)
    if classed["media"] or classed["skills"]:
        logger.info(
            f"Backfilled decay classes: {classed['media']} media -> evergreen, "
            f"{classed['skills']} skills -> durable, "
            f"{classed['restored']} restored to active"
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_decay_migration.py -q`
Expected: PASS (12 tests).

- [ ] **Step 6: Run the whole backend suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add api/services/decay_migration.py api/main.py api/tests/test_decay_migration.py
git commit -m "$(cat <<'EOF'
feat(decay): one-shot startup backfill of decay_class into a bank (G66)

media pages -> evergreen/0.0 (and any that the old engine wrongly faded are
restored to active at confidence >= 0.7, except user-dropped ones), skills ->
durable. Marker-guarded like the inbox dedup migration, scoped to entities/
only, authored by the reserved `cicada` system literal, trigger
maintenance/decay_class_backfill. Never crashes boot.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 6: `decay_class` on the wire + `PUT /entities/{id}/decay`

**Files:**
- Modify: `api/models/schemas.py` (`EntityResponse` ~166-186, new `EntityDecayUpdate`, `GraphNode` ~407-443)
- Modify: `api/services/graph_builder.py:160-176`, `:268-273`
- Modify: `api/routers/entities.py:61-78` (response) and after line 192 (new endpoint)
- Test: `api/tests/test_decay_endpoint.py`

**Interfaces:**
- Consumes: `decay_policy.resolve(fm)`, `decay_policy.frontmatter_fields(cls)`, `schemas.DecayClass` (Task 1); `git_service.build_commit_message`, `git_service.commit_paths`.
- Produces:
  - `EntityResponse.decay_class: DecayClass = DecayClass.active` — wire key `decayClass`, additive.
  - `EntityDecayUpdate(CamelModel)` with the single field `decay_class: DecayClass` (wire key `decayClass`; `populate_by_name=True` means a snake_case body also works).
  - `GraphNode.decay_class: DecayClass = DecayClass.active` — wire key `decayClass`, folded into `content_hash`.
  - `PUT /entities/{entity_id}/decay` → `EntityResponse`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_decay_endpoint.py`:

```python
"""G66 §1.7 — decay_class on the wire + the user-override endpoint."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.models.schemas import DecayClass, EntityDecayUpdate
from api.routers import entities as entities_router
from api.services import graph_builder, markdown_parser


def run(coro):
    return asyncio.run(coro)


class _FakeSettings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def _memory(tmp_path: Path, **fm) -> Path:
    repo = tmp_path / "memory"
    (repo / "entities").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")
    base = {
        "name": "MongoDB",
        "type": "tool",
        "status": "active",
        "confidence": 0.8,
        "created": "2026-01-01",
        "last_referenced": "2026-08-01",
        "decay_rate": 0.05,
        "source_episodes": [],
        "tags": [],
        "related": [],
        "version": 1,
    }
    base.update(fm)
    markdown_parser.write(repo / "entities" / "mongodb.md", base, "## Summary\n\nA db.")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _fm(repo: Path) -> dict:
    return markdown_parser.parse(repo / "entities" / "mongodb.md").frontmatter


# --- GET surfaces the class -------------------------------------------------


def test_entity_response_carries_the_resolved_class(tmp_path):
    repo = _memory(tmp_path, decay_class="volatile", decay_rate=0.15)
    resp = run(entities_router.get_entity("mongodb", settings=_FakeSettings(repo)))
    assert resp.decay_class is DecayClass.volatile
    assert resp.decay_rate == 0.15


def test_entity_response_infers_the_class_for_a_legacy_page(tmp_path):
    repo = _memory(tmp_path, type="media", decay_rate=0.03)
    resp = run(entities_router.get_entity("mongodb", settings=_FakeSettings(repo)))
    assert resp.decay_class is DecayClass.evergreen
    assert resp.decay_rate == 0.0


def test_entity_response_serialises_the_field_as_camel_case(tmp_path):
    repo = _memory(tmp_path)
    resp = run(entities_router.get_entity("mongodb", settings=_FakeSettings(repo)))
    assert resp.model_dump(by_alias=True)["decayClass"] == "active"


# --- graph nodes ------------------------------------------------------------


def test_graph_nodes_carry_the_class_and_fold_it_into_the_content_hash(tmp_path):
    repo = _memory(tmp_path)
    graph_builder._CACHE["key"] = None
    before = {n.id: n for n in graph_builder.build_graph(repo).nodes}["mongodb"]
    assert before.decay_class is DecayClass.active

    fm = _fm(repo)
    fm["decay_class"] = "volatile"
    markdown_parser.write(repo / "entities" / "mongodb.md", fm, "## Summary\n\nA db.")
    graph_builder._CACHE["key"] = None
    after = {n.id: n for n in graph_builder.build_graph(repo).nodes}["mongodb"]

    assert after.decay_class is DecayClass.volatile
    assert after.content_hash != before.content_hash


# --- PUT /entities/{id}/decay -----------------------------------------------


def test_put_decay_writes_the_class_and_its_mapped_rate(tmp_path):
    repo = _memory(tmp_path)
    resp = run(
        entities_router.update_entity_decay(
            "mongodb",
            EntityDecayUpdate(decay_class=DecayClass.evergreen),
            settings=_FakeSettings(repo),
        )
    )
    assert resp.decay_class is DecayClass.evergreen
    fm = _fm(repo)
    assert fm["decay_class"] == "evergreen"
    assert fm["decay_rate"] == 0.0


def test_put_decay_maps_each_class_to_its_rate(tmp_path):
    for cls, rate in [
        (DecayClass.durable, 0.02),
        (DecayClass.active, 0.05),
        (DecayClass.volatile, 0.15),
    ]:
        repo = _memory(tmp_path / cls.value)
        run(
            entities_router.update_entity_decay(
                "mongodb", EntityDecayUpdate(decay_class=cls),
                settings=_FakeSettings(repo),
            )
        )
        fm = _fm(repo)
        assert fm["decay_class"] == cls.value
        assert fm["decay_rate"] == rate


def test_put_decay_commits_as_the_user_with_the_companion_app_trigger(tmp_path):
    repo = _memory(tmp_path)
    run(
        entities_router.update_entity_decay(
            "mongodb", EntityDecayUpdate(decay_class=DecayClass.volatile),
            settings=_FakeSettings(repo),
        )
    )
    log = _git(repo, "log", "--format=%s%n%b", "-1")
    assert "Cicada-Author: user" in log
    assert "user/companion_app" in log
    assert "entities/mongodb.md" in log


def test_put_decay_does_not_sweep_unrelated_dirty_files_into_its_commit(tmp_path):
    repo = _memory(tmp_path)
    (repo / "scratch.txt").write_text("dirty", encoding="utf-8")
    run(
        entities_router.update_entity_decay(
            "mongodb", EntityDecayUpdate(decay_class=DecayClass.durable),
            settings=_FakeSettings(repo),
        )
    )
    assert "scratch.txt" in _git(repo, "status", "--porcelain")


def test_put_decay_leaves_every_other_frontmatter_key_and_the_body_untouched(tmp_path):
    repo = _memory(tmp_path, tags=["database"], confidence=0.83)
    body_before = markdown_parser.parse(repo / "entities" / "mongodb.md").body
    run(
        entities_router.update_entity_decay(
            "mongodb", EntityDecayUpdate(decay_class=DecayClass.durable),
            settings=_FakeSettings(repo),
        )
    )
    fm = _fm(repo)
    assert fm["tags"] == ["database"]
    assert fm["confidence"] == 0.83
    assert fm["version"] == 1, "a decay override is not a content revision"
    assert markdown_parser.parse(repo / "entities" / "mongodb.md").body == body_before


def test_put_decay_404s_for_a_missing_entity(tmp_path):
    repo = _memory(tmp_path)
    with pytest.raises(HTTPException) as exc:
        run(
            entities_router.update_entity_decay(
                "nope", EntityDecayUpdate(decay_class=DecayClass.active),
                settings=_FakeSettings(repo),
            )
        )
    assert exc.value.status_code == 404


def test_the_request_model_rejects_an_unknown_class():
    with pytest.raises(Exception):
        EntityDecayUpdate(decay_class="unlimited")


def test_the_request_model_accepts_both_camel_and_snake_case_bodies():
    assert EntityDecayUpdate(**{"decayClass": "durable"}).decay_class is DecayClass.durable
    assert EntityDecayUpdate(**{"decay_class": "durable"}).decay_class is DecayClass.durable
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_decay_endpoint.py -q`
Expected: FAIL — `ImportError: cannot import name 'EntityDecayUpdate'`.

- [ ] **Step 3: Add the schema fields**

In `api/models/schemas.py`, add to `EntityResponse` immediately after `decay_rate: float` (line 174):

```python
    # G66 — the semantic decay class beside the numeric rate. Additive +
    # defaulted so an older client that doesn't decode it is unaffected, and a
    # legacy page with no `decay_class:` still gets a resolved value.
    decay_class: DecayClass = DecayClass.active
```

Add the request model directly after `EntityResponse` (before `# --- Location listing`, line 189):

```python
class EntityDecayUpdate(CamelModel):
    """Body of ``PUT /entities/{id}/decay`` — the user's decay override (G66).

    The field is named ``decay_class`` (``class`` is a Python keyword); the
    camelCase alias ``decayClass`` is what the app sends, and
    ``populate_by_name`` means a snake_case body works too. Pydantic rejects
    anything outside the ``DecayClass`` enum with a 422.
    """

    decay_class: DecayClass
```

Add to `GraphNode` immediately after `has_logo: bool = False` (line 443):

```python
    # G66: the entity's decay class, resolved server-side from frontmatter
    # (explicit key, else legacy type inference). Additive + defaulted, and
    # folded into `content_hash` below — the `has_logo` precedent — so the
    # companion app's delta repaints the node when the class changes.
    decay_class: DecayClass = DecayClass.active
```

- [ ] **Step 4: Populate it in the graph builder**

In `api/services/graph_builder.py`, add the import beside the existing service imports:

```python
from api.services import decay_policy
```

Then in `_build_full`'s entity-node construction (line 160-176), add the field after `has_logo`:

```python
                content_hash=content_hash(fm, body),
                has_logo=eid in logo_ids,
                decay_class=decay_policy.resolve(fm)[0],
            )
```

And fold it into the server-derived hash (line 268-273):

```python
    for node in nodes:
        if node.id in entity_ids:
            node.content_hash = synthetic_hash(
                node.content_hash, node.degree, node.has_pending, node.hub_id,
                node.has_logo, node.decay_class.value,
            )
```

- [ ] **Step 5: Surface it on `GET` and add the `PUT`**

In `api/routers/entities.py`, extend the schema import block (lines 12-29) with `DecayClass` and `EntityDecayUpdate`, and add `decay_policy` to the services import (line 30):

```python
from api.models.schemas import (
    ContextEpisodeExcerpt,
    ContextNeighbor,
    EntityContextResponse,
    EntityDecayUpdate,
    EntityDiff,
    EntityHistoryEntry,
    EntityMedia,
    EntityResponse,
    EntitySource,
    EntitySourceCreate,
    EntitySourceList,
    LocationEntry,
    LocationListing,
    RepoContext,
    RepoContextList,
    RepoInput,
    RepoUpdateRequest,
)
from api.services import (
    decay_policy,
    fact_sources,
    git_service,
    logo_service,
    markdown_parser,
    repo_context,
)
```

Rewrite `get_entity`'s body (lines 57-78) so the rate comes from the resolver and the class is surfaced:

```python
    parsed = markdown_parser.parse(entity_path)
    fm = parsed.frontmatter
    history = await git_service.get_entity_history(entity_id, settings.memory_path)
    decay_class, decay_rate = decay_policy.resolve(fm)

    return EntityResponse(
        id=entity_id,
        name=fm.get("name", entity_id.replace("-", " ").title()),
        type=fm.get("type", "concept"),
        status=fm.get("status", "active"),
        confidence=fm.get("confidence", 0.5),
        created=str(fm.get("created", "")),
        last_referenced=str(fm.get("last_referenced", "")),
        decay_rate=decay_rate,
        decay_class=decay_class,
        source_episodes=fm.get("source_episodes", []),
        tags=fm.get("tags", []),
        related=fm.get("related", []),
        version=fm.get("version", 1),
        markdown_content=parsed.body,
        raw_markdown=entity_path.read_text(encoding="utf-8"),
        history=history,
        media=_build_media_block(fm, parsed.body),
    )
```

Add the endpoint immediately after `get_entity_commit_diff` (after line 192):

```python
@router.put("/entities/{entity_id}/decay", response_model=EntityResponse)
async def update_entity_decay(
    entity_id: str,
    request: EntityDecayUpdate,
    settings: Settings = Depends(get_settings),
):
    """Set an entity's decay class — the user's override (G66 §1.7).

    Writes BOTH the semantic ``decay_class:`` and its mapped numeric
    ``decay_rate:`` so a page stays self-consistent for any reader that only
    knows the old numeric key. Every other frontmatter key and the body are left
    untouched, and ``version`` is deliberately NOT bumped: choosing how fast a
    belief fades is a policy decision about the page, not a revision of its
    content. Commits scoped to this one file — trigger ``user/companion_app``,
    ``Cicada-Author: user``.
    """
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")

    parsed = markdown_parser.parse(entity_path)
    parsed.frontmatter.update(decay_policy.frontmatter_fields(request.decay_class))
    markdown_parser.write(entity_path, parsed.frontmatter, parsed.body)

    message = git_service.build_commit_message(
        f"Set decay class {date.today().isoformat()}",
        [
            f"entities/{entity_id}.md: updated "
            f"(decay_class: {request.decay_class.value}, trigger: user/companion_app)"
        ],
        authors=["user"],
    )
    # Scoped, never ``git add -A``: a decay override must not sweep an unrelated
    # dirty file in memory/ into this commit.
    await git_service.commit_paths(
        settings.memory_path, message, [f"entities/{entity_id}.md"]
    )

    return await get_entity(entity_id, settings=settings)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_decay_endpoint.py -q`
Expected: PASS (12 tests).

- [ ] **Step 7: Run the whole backend suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS. `api/tests/test_graph_builder.py` may assert on an exact `content_hash` or on the full node field set — the hash change is intended; update any golden value.

- [ ] **Step 8: Commit**

```bash
git add api/models/schemas.py api/services/graph_builder.py api/routers/entities.py \
        api/tests/test_decay_endpoint.py
git commit -m "$(cat <<'EOF'
feat(decay): decayClass on EntityResponse + graph nodes, PUT /entities/{id}/decay (G66)

Both wire fields are additive and defaulted so old clients and cached
snapshots still decode; the graph node's class is folded into content_hash
(the has_logo precedent) so a class change repaints the node in the app's
delta. The PUT writes class + mapped rate, touches nothing else, does not bump
version, and commits scoped as Cicada-Author: user / user/companion_app.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 7: `get_contributor_commits` + `GET /contributors/commits`

**Files:**
- Modify: `api/models/schemas.py:124-129` (after `ContributorsResponse`)
- Modify: `api/services/git_service.py:6-11` (imports), after `get_contributors` (line 468)
- Modify: `api/routers/contributors.py`
- Test: `api/tests/test_contributor_commits.py`

**Interfaces:**
- Consumes: `git_service._parse_authors(body)`, `git_service.UNKNOWN_AUTHOR`, `git_service._run_git`, `git_service.GitError` (all existing).
- Produces:
  - `schemas.ContributorCommit(commit_hash: str, date: str, subject: str, entities: list[str] = [], files_changed: int = 0)`.
  - `schemas.ContributorCommitsResponse(author: str, commits: list[ContributorCommit] = [])`.
  - `git_service.MAX_CONTRIBUTOR_COMMITS = 200`.
  - `async git_service.get_contributor_commits(memory_path: Path, author: str, *, limit: int = 50) -> list[ContributorCommit]`.
  - `GET /contributors/commits?author=<str>&limit=<int>` → `ContributorCommitsResponse`.

**Implementation note (verified against a scratch repo):** one `git log` call with a record-delimited format PLUS `--name-only` yields, per record, `hash<US>date<US>subject<US>body<US>` followed by a blank line and the changed file paths — and the root (parentless) commit *does* list its files. That is the whole parse; no second `diff-tree` call per commit.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_contributor_commits.py`:

```python
"""G67 §2.2 — per-author commit listing for the Contributors drill-down.

Hermetic: every test builds a throwaway git repo with hand-crafted
``Cicada-Author:`` trailers. The real memory/ bank is never read.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.services import git_service


def run(coro):
    return asyncio.run(coro)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "memory"
    (r / "entities").mkdir(parents=True)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "test@cicada.local")
    _git(r, "config", "user.name", "Cicada Test")
    return r


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, subject: str, lines: list[str], authors: list[str] | None) -> str:
    _git(repo, "add", "-A")
    message = (
        git_service.build_commit_message(subject, lines, authors=authors)
        if authors is not None
        else f"{subject}\n\n" + "\n".join(lines)
    )
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


class _FakeSettings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path


# --- trailer filtering ------------------------------------------------------


def test_only_commits_trailered_with_that_author_are_returned(repo):
    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"], ["gpt-5.4-mini"])
    _write(repo, "entities/beta.md", "v1")
    _commit(repo, "Inbox resolution", ["entities/beta.md: updated"], ["user"])

    mine = run(git_service.get_contributor_commits(repo, "gpt-5.4-mini"))
    theirs = run(git_service.get_contributor_commits(repo, "user"))

    assert [c.subject for c in mine] == ["Sleep cycle"]
    assert [c.subject for c in theirs] == ["Inbox resolution"]


def test_a_co_authored_commit_appears_for_every_trailered_author(repo):
    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"],
            ["gpt-5.4-mini", "gpt-5.4-nano"])

    for author in ("gpt-5.4-mini", "gpt-5.4-nano"):
        assert len(run(git_service.get_contributor_commits(repo, author))) == 1


def test_an_untrailered_commit_belongs_to_unknown(repo):
    _write(repo, "entities/gamma.md", "v1")
    _commit(repo, "Sleep cycle legacy", ["entities/gamma.md: created"], None)

    unknown = run(git_service.get_contributor_commits(repo, git_service.UNKNOWN_AUTHOR))
    assert [c.subject for c in unknown] == ["Sleep cycle legacy"]
    assert run(git_service.get_contributor_commits(repo, "gpt-5.4-mini")) == []


def test_the_reserved_cicada_system_author_is_listable(repo):
    _write(repo, "inbox/inbox-001.md", "x")
    _commit(repo, "Collapse duplicate open inbox questions",
            ["inbox/: 1 duplicate merged (trigger: inbox/dedup)"], ["cicada"])

    commits = run(git_service.get_contributor_commits(repo, "cicada"))
    assert len(commits) == 1
    assert commits[0].entities == [], "no entity files touched"
    assert commits[0].files_changed == 1


# --- shape ------------------------------------------------------------------


def test_a_commit_reports_its_hash_date_subject_entities_and_file_count(repo):
    _write(repo, "entities/alpha.md", "v1")
    _write(repo, "entities/beta.md", "v1")
    _write(repo, "graph_edges.yaml", "edges: []")
    sha = _commit(repo, "Sleep cycle 2026-08-31",
                  ["entities/alpha.md: created"], ["gpt-5.4-mini"])

    commit = run(git_service.get_contributor_commits(repo, "gpt-5.4-mini"))[0]

    assert commit.commit_hash == sha
    assert commit.date == _git(repo, "log", "-1", "--format=%ad", "--date=short").strip()
    assert commit.subject == "Sleep cycle 2026-08-31"
    assert commit.entities == ["alpha", "beta"], "entity STEMS, sorted"
    assert commit.files_changed == 3, "every changed file, entities or not"


def test_the_root_commit_still_lists_its_files(repo):
    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"], ["gpt-5.4-mini"])

    commit = run(git_service.get_contributor_commits(repo, "gpt-5.4-mini"))[0]
    assert commit.entities == ["alpha"]


def test_non_entity_paths_never_leak_into_entities(repo):
    _write(repo, "episodes/ep_1.md", "x")
    _write(repo, "entities/nested/deep.md", "x")
    _commit(repo, "Sleep cycle", ["episodes/ep_1.md: created"], ["gpt-5.4-mini"])

    commit = run(git_service.get_contributor_commits(repo, "gpt-5.4-mini"))[0]
    assert commit.entities == ["deep"]


def test_commits_are_newest_first(repo):
    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "first", ["entities/alpha.md: created"], ["gpt-5.4-mini"])
    _write(repo, "entities/alpha.md", "v2")
    _commit(repo, "second", ["entities/alpha.md: updated"], ["gpt-5.4-mini"])

    assert [c.subject for c in run(git_service.get_contributor_commits(repo, "gpt-5.4-mini"))] == [
        "second", "first",
    ]


def test_limit_bounds_the_listing(repo):
    for i in range(6):
        _write(repo, "entities/alpha.md", f"v{i}")
        _commit(repo, f"cycle {i}", ["entities/alpha.md: updated"], ["gpt-5.4-mini"])

    assert len(run(git_service.get_contributor_commits(repo, "gpt-5.4-mini", limit=2))) == 2


def test_a_multi_line_body_never_breaks_the_record_parse(repo):
    _write(repo, "entities/alpha.md", "v1")
    _commit(
        repo,
        "Sleep cycle",
        [
            "entities/alpha.md: created (source: ep_1, trigger: sleep/extraction)",
            "entities/beta.md: updated (source: ep_2, trigger: sleep/promotion)",
            "",
            "a stray blank line and some prose",
        ],
        ["gpt-5.4-mini"],
    )
    commits = run(git_service.get_contributor_commits(repo, "gpt-5.4-mini"))
    assert len(commits) == 1
    assert commits[0].subject == "Sleep cycle"


# --- degradation ------------------------------------------------------------


def test_a_non_git_directory_returns_empty(tmp_path):
    assert run(git_service.get_contributor_commits(tmp_path / "nope", "user")) == []


def test_a_blank_author_returns_empty(repo):
    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"], ["gpt-5.4-mini"])
    assert run(git_service.get_contributor_commits(repo, "   ")) == []


def test_an_unknown_author_returns_empty(repo):
    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"], ["gpt-5.4-mini"])
    assert run(git_service.get_contributor_commits(repo, "claude-opus-5")) == []


# --- router -----------------------------------------------------------------


def test_router_returns_the_authors_commits(repo):
    from api.routers import contributors as contributors_router

    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"], ["gpt-5.4-mini"])

    resp = run(
        contributors_router.get_contributor_commits(
            author="gpt-5.4-mini", limit=50, settings=_FakeSettings(repo)
        )
    )
    assert resp.author == "gpt-5.4-mini"
    assert [c.subject for c in resp.commits] == ["Sleep cycle"]


def test_router_accepts_a_model_id_containing_a_slash(repo):
    from api.routers import contributors as contributors_router

    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"], ["anthropic/claude-opus-4"])

    resp = run(
        contributors_router.get_contributor_commits(
            author="anthropic/claude-opus-4", limit=50, settings=_FakeSettings(repo)
        )
    )
    assert len(resp.commits) == 1


def test_router_rejects_a_blank_author(repo):
    from api.routers import contributors as contributors_router

    with pytest.raises(HTTPException) as exc:
        run(
            contributors_router.get_contributor_commits(
                author="  ", limit=50, settings=_FakeSettings(repo)
            )
        )
    assert exc.value.status_code == 400


def test_router_clamps_an_absurd_limit(repo):
    from api.routers import contributors as contributors_router

    _write(repo, "entities/alpha.md", "v1")
    _commit(repo, "Sleep cycle", ["entities/alpha.md: created"], ["gpt-5.4-mini"])

    resp = run(
        contributors_router.get_contributor_commits(
            author="gpt-5.4-mini", limit=99999, settings=_FakeSettings(repo)
        )
    )
    assert len(resp.commits) == 1  # clamped, not an error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_contributor_commits.py -q`
Expected: FAIL — `AttributeError: module 'api.services.git_service' has no attribute 'get_contributor_commits'`.

- [ ] **Step 3: Add the schemas**

In `api/models/schemas.py`, insert after `ContributorsResponse` (line 124-126):

```python
class ContributorCommit(CamelModel):
    """One commit attributed to a contributor (G67 §2.2).

    ``entities`` are the entity ids (file STEMS) this commit touched, so the app
    can render a chip per entity and fetch that entity's diff at this commit
    from ``GET /entities/{id}/history/{commit}/diff``. ``files_changed`` is a
    COUNT of every changed path (entities and everything else) — the ids
    themselves are already in ``entities``.
    """

    commit_hash: str
    date: str  # ISO date (YYYY-MM-DD)
    subject: str
    entities: list[str] = []
    files_changed: int = 0


class ContributorCommitsResponse(CamelModel):
    author: str
    commits: list[ContributorCommit] = []
```

- [ ] **Step 4: Add `get_contributor_commits` to `git_service`**

Extend the schema import at the top of `api/services/git_service.py` (lines 6-11):

```python
from api.models.schemas import (
    Contributor,
    ContributorCommit,
    EntityDiff,
    EntityHistoryEntry,
    SleepHistoryEntry,
)
```

Add the cap beside `DIFF_MAX_LINES` (line 38):

```python
# Hard cap on a contributor-commit listing, so a caller-supplied `limit` can't
# ask for the entire history of a bank with thousands of Sleep cycles.
MAX_CONTRIBUTOR_COMMITS = 200
```

Add the function immediately after `get_contributors` (after line 468):

```python
async def get_contributor_commits(
    memory_path: Path, author: str, *, limit: int = 50
) -> list[ContributorCommit]:
    """The commits one author wrote, newest first (G67 §2.2).

    Reuses the NUL-record ``git log`` + ``_parse_authors`` plumbing from
    :func:`get_contributors`, with ``--name-only`` folded into the SAME call so
    the listing costs one git invocation rather than one per commit. Records are
    ``hash <US> date <US> subject <US> body <US>`` followed by a blank line and
    the changed paths; ``git log --name-only`` lists the root (parentless)
    commit's files too, so no ``--root`` dance is needed.

    An author of ``"unknown"`` matches legacy untrailered commits. Returns ``[]``
    for a non-git dir, a blank author, or an author with no commits — the app
    renders an empty state, never an error.
    """
    author = (author or "").strip()
    if not author or not (memory_path / ".git").exists():
        return []

    limit = max(1, min(int(limit or 50), MAX_CONTRIBUTOR_COMMITS))
    sep = "\x1f"
    rec = "\x1e"
    try:
        out = await _run_git(
            memory_path,
            "log",
            f"--format={rec}%H{sep}%ad{sep}%s{sep}%b{sep}",
            "--date=short",
            "--name-only",
        )
    except GitError:
        return []

    commits: list[ContributorCommit] = []
    for record in out.split(rec):
        if not record.strip():
            continue
        fields = record.split(sep, 4)
        if len(fields) < 5:
            continue
        commit_hash, date_str, subject, body, tail = fields

        if author not in (_parse_authors(body) or [UNKNOWN_AUTHOR]):
            continue

        files = [line.strip() for line in tail.splitlines() if line.strip()]
        entities = sorted(
            {
                f[len("entities/"):-len(".md")].rsplit("/", 1)[-1]
                for f in files
                if f.startswith("entities/") and f.endswith(".md")
            }
        )
        commits.append(
            ContributorCommit(
                commit_hash=commit_hash.strip(),
                date=date_str.strip(),
                subject=subject.strip(),
                entities=entities,
                files_changed=len(files),
            )
        )
        if len(commits) >= limit:
            break

    return commits
```

- [ ] **Step 5: Add the router endpoint**

Rewrite `api/routers/contributors.py`'s imports and append the endpoint:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from api.config import Settings, get_settings
from api.models.schemas import ContributorCommitsResponse, ContributorsResponse
from api.services import git_service, sync_service
```

```python
@router.get("/contributors/commits", response_model=ContributorCommitsResponse)
async def get_contributor_commits(
    author: str = Query(..., description="Model id, 'user', 'cicada', or 'unknown'"),
    limit: int = Query(50, ge=1, le=git_service.MAX_CONTRIBUTOR_COMMITS),
    settings: Settings = Depends(get_settings),
):
    """Recent commits by one authoring agent (G67 §2.2).

    ``author`` is a QUERY parameter, not a path segment: model ids contain
    slashes (``anthropic/claude-opus-4``) that would split a path. On demand
    only — no ETag and no ``Store`` domain, because this is a drill-down the
    user opens deliberately, not a snapshot the app keeps live.
    """
    author = (author or "").strip()
    if not author:
        raise HTTPException(400, "author is required")
    commits = await git_service.get_contributor_commits(
        settings.memory_path, author, limit=limit
    )
    return ContributorCommitsResponse(author=author, commits=commits)
```

Note for the implementer: `limit` is declared with `ge`/`le`, so FastAPI itself clamps out-of-range values with a 422 for live HTTP callers; `git_service.get_contributor_commits` clamps again for direct callers (which is what `test_router_clamps_an_absurd_limit` exercises).

- [ ] **Step 6: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_contributor_commits.py -q`
Expected: PASS (17 tests).

- [ ] **Step 7: Run the whole backend suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add api/models/schemas.py api/services/git_service.py api/routers/contributors.py \
        api/tests/test_contributor_commits.py
git commit -m "$(cat <<'EOF'
feat(contributors): GET /contributors/commits for the diff drill-down (G67)

git_service.get_contributor_commits reuses the NUL-record git log +
Cicada-Author trailer parsing from get_contributors, folding --name-only into
the same call so a listing costs one git invocation. Each commit reports its
hash, date, subject, the entity ids it touched (for per-entity diff chips) and
a changed-file count. author is a query param because model ids contain
slashes; on-demand only, no ETag, no Store domain.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 8: `DiffModel` + `DiffView` + tappable entity-history rows

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Common/DiffView.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift:804-883`
- Test: `app/CicadaApp/Tests/CicadaAppTests/DiffModelTests.swift`

**Interfaces:**
- Consumes: `EntityDiff` (`Models/Entity.swift:74-98`, fields `added: String`, `removed: String`, `truncated: Bool`); `APIClient.fetchEntityCommitDiff(id:commitHash:) async throws -> EntityDiff` (`Services/APIClient.swift:826`); `EntityHistoryEntry.commitHash` (`Models/Entity.swift:109`); `MockURLProtocol` (`Tests/CicadaAppTests/EntitySourceTests.swift:10`).
- Produces (Task 9 reuses all of these verbatim):
  - `DiffModel` — `init(_ diff: EntityDiff)`, `let lines: [DiffLine]`, `var isEmpty: Bool`, `let truncated: Bool`, `static let truncationMarker = "... [diff truncated]"`.
  - `DiffLine` — `Identifiable`, `Equatable`; `let kind: Kind` (`.removed`/`.added`/`.truncation`), `let text: String`, `var gutter: String`.
  - `DiffView` — `init(diff: EntityDiff)`, plus `DiffView.loading` and `DiffView.empty` static views for the two non-content states.

**On what is tested here:** the app's test target has no view-hosting harness (no ViewInspector; every existing test — `GraphDiffTests`, `InboxQuestionTests`, `ConsumptionDecodingTests`, … — exercises models, utilities and `APIClient` over the fake transport). So the row-expansion `@State` toggle itself is not unit-testable in this setup; the testable seams are `DiffModel` (all the rendering decisions) and `fetchEntityCommitDiff` (the network contract), and both are covered below. Do not add a view-testing dependency for this task.

- [ ] **Step 1: Write the failing test**

Create `app/CicadaApp/Tests/CicadaAppTests/DiffModelTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G67 — the pure diff model behind the shared `DiffView`. Everything the view
/// renders (order, gutter glyphs, coloring bucket, the truncation notice) is
/// decided here so it can be tested without a view hierarchy.
final class DiffModelTests: XCTestCase {

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    // MARK: - Parsing

    func testRemovedLinesComeFirstThenAddedLines() {
        let model = DiffModel(EntityDiff(added: "new one\nnew two", removed: "old one"))

        XCTAssertEqual(model.lines.map(\.kind), [.removed, .added, .added])
        XCTAssertEqual(model.lines.map(\.text), ["old one", "new one", "new two"])
    }

    func testGutterGlyphsAreMinusAndPlus() {
        let model = DiffModel(EntityDiff(added: "a", removed: "r"))

        XCTAssertEqual(model.lines[0].gutter, "\u{2212}")  // real minus sign, not a hyphen
        XCTAssertEqual(model.lines[1].gutter, "+")
    }

    func testAnEmptyDiffProducesNoLines() {
        let model = DiffModel(EntityDiff(added: "", removed: ""))

        XCTAssertTrue(model.lines.isEmpty)
        XCTAssertTrue(model.isEmpty)
    }

    func testAOneSidedDiffIsNotEmpty() {
        XCTAssertFalse(DiffModel(EntityDiff(added: "only additions", removed: "")).isEmpty)
        XCTAssertFalse(DiffModel(EntityDiff(added: "", removed: "only removals")).isEmpty)
    }

    func testBlankLinesInsideAHunkArePreservedAsContent() {
        let model = DiffModel(EntityDiff(added: "first\n\nthird", removed: ""))

        XCTAssertEqual(model.lines.count, 3)
        XCTAssertEqual(model.lines[1].text, "")
    }

    func testATrailingNewlineDoesNotProduceAPhantomLine() {
        let model = DiffModel(EntityDiff(added: "one\ntwo\n", removed: ""))

        XCTAssertEqual(model.lines.map(\.text), ["one", "two"])
    }

    func testLineIdentityIsStableAndUniqueAcrossSides() {
        // Both sides can carry the exact same text (a line moved within the
        // file); ForEach must not collapse them into one row.
        let model = DiffModel(EntityDiff(added: "same", removed: "same"))

        XCTAssertEqual(model.lines.count, 2)
        XCTAssertNotEqual(model.lines[0].id, model.lines[1].id)
    }

    // MARK: - Truncation

    func testTheBackendTruncationMarkerBecomesItsOwnKindNotAContentLine() {
        let model = DiffModel(EntityDiff(
            added: "kept\n\(DiffModel.truncationMarker)",
            removed: "",
            truncated: true
        ))

        XCTAssertEqual(model.lines.map(\.kind), [.added, .truncation])
        XCTAssertTrue(model.truncated)
    }

    func testTheTruncationMarkerHasNoGutterGlyph() {
        let model = DiffModel(EntityDiff(added: DiffModel.truncationMarker, removed: "",
                                         truncated: true))

        XCTAssertEqual(model.lines[0].gutter, "")
    }

    func testTruncatedFlagIsCarriedEvenWhenNoMarkerLineIsPresent() {
        // The backend only appends the marker to a NON-EMPTY side, so a diff can
        // be flagged truncated with the marker on the other side only.
        let model = DiffModel(EntityDiff(added: "kept", removed: "", truncated: true))

        XCTAssertTrue(model.truncated)
        XCTAssertEqual(model.lines.map(\.kind), [.added])
    }

    func testTheMarkerStringMatchesTheBackendConstant() {
        // git_service._DIFF_TRUNCATION_MARKER — keep these two in lockstep.
        XCTAssertEqual(DiffModel.truncationMarker, "... [diff truncated]")
    }

    // MARK: - APIClient.fetchEntityCommitDiff

    func testFetchEntityCommitDiffGETsTheCommitPathAndDecodes() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(
                request.url?.path,
                "/entities/mongodb/history/abc1234/diff"
            )
            let body = """
            {"added": "line b", "removed": "line a", "truncated": false}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                            httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let diff = try await APIClient(session: MockURLProtocol.makeSession())
            .fetchEntityCommitDiff(id: "mongodb", commitHash: "abc1234")

        XCTAssertEqual(DiffModel(diff).lines.map(\.text), ["line a", "line b"])
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/CicadaApp && swift test --filter DiffModelTests`
Expected: FAIL — `cannot find 'DiffModel' in scope`.

- [ ] **Step 3: Write `DiffView.swift`**

Create `app/CicadaApp/Sources/CicadaApp/Views/Common/DiffView.swift`:

```swift
import SwiftUI

// G67 — the shared commit-diff renderer.
//
// One component, two call sites: the entity detail card's History tab (a tapped
// commit row expands into it) and the Contributors drill-down (a tapped entity
// chip on a commit). The parsing/ordering/gutter decisions live in `DiffModel`
// so they are testable without a view hierarchy; `DiffView` only paints.
//
// The backend hands us two newline-joined blocks (`added` / `removed`) produced
// from `git show --unified=0`, so the original interleaving is already lost.
// We render removals first, then additions — the same order the old inline
// renderer used, and the order a reader expects for "what this commit changed".

/// One rendered diff row.
struct DiffLine: Identifiable, Equatable {
    enum Kind: Equatable {
        case removed
        case added
        /// The backend's "diff clipped" notice — not file content.
        case truncation
    }

    let id: Int
    let kind: Kind
    let text: String

    /// The leading glyph. A real minus sign (U+2212) rather than a hyphen so it
    /// optically matches `+` at the same monospaced width.
    var gutter: String {
        switch kind {
        case .removed: "\u{2212}"
        case .added: "+"
        case .truncation: ""
        }
    }
}

/// Pure, testable projection of an `EntityDiff` into rows.
struct DiffModel {
    /// Mirrors `git_service._DIFF_TRUNCATION_MARKER`. Keep the two in lockstep:
    /// the backend appends this line to a clipped side, and we promote it out of
    /// the content stream into its own `.truncation` row.
    static let truncationMarker = "... [diff truncated]"

    let lines: [DiffLine]
    let truncated: Bool

    var isEmpty: Bool { lines.isEmpty }

    init(_ diff: EntityDiff) {
        var out: [DiffLine] = []
        var next = 0

        func append(_ block: String, as kind: DiffLine.Kind) {
            guard !block.isEmpty else { return }
            // `separator:omittingEmptySubsequences: false` keeps blank lines that
            // are real file content; the trailing-newline artifact is dropped.
            var raw = block.components(separatedBy: "\n")
            if raw.last == "" { raw.removeLast() }
            for text in raw {
                let isMarker = text == Self.truncationMarker
                out.append(DiffLine(id: next, kind: isMarker ? .truncation : kind, text: text))
                next += 1
            }
        }

        append(diff.removed, as: .removed)
        append(diff.added, as: .added)

        self.lines = out
        self.truncated = diff.truncated
    }
}

/// GitHub-style inline diff: monospaced, `+`/`−` gutters, green/red text on a
/// tinted row background.
struct DiffView: View {
    let model: DiffModel

    init(diff: EntityDiff) {
        self.model = DiffModel(diff)
    }

    private static let addedColor = Color(hex: 0x22C55E)
    private static let removedColor = Color(hex: 0xEF4444)

    var body: some View {
        if model.isEmpty {
            Self.empty
        } else {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(model.lines) { line in
                    row(line)
                }
                if model.truncated {
                    Text("Diff clipped — this commit changed more than we show here.")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .padding(.horizontal, CicadaTheme.spacingSM)
                        .padding(.vertical, CicadaTheme.spacingXS)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CicadaTheme.surfaceHover.opacity(0.5))
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
        }
    }

    @ViewBuilder
    private func row(_ line: DiffLine) -> some View {
        switch line.kind {
        case .truncation:
            Text(line.text)
                .font(CicadaTheme.monoFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .padding(.horizontal, CicadaTheme.spacingSM)
                .padding(.vertical, 1)
                .frame(maxWidth: .infinity, alignment: .leading)
        case .added, .removed:
            let color = line.kind == .added ? Self.addedColor : Self.removedColor
            HStack(alignment: .top, spacing: CicadaTheme.spacingXS) {
                Text(line.gutter)
                    .font(CicadaTheme.monoFont)
                    .foregroundStyle(color.opacity(0.8))
                    .frame(width: 10, alignment: .leading)
                Text(line.text)
                    .font(CicadaTheme.monoFont)
                    .foregroundStyle(color)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .padding(.vertical, 1)
            .background(color.opacity(0.10))
        }
    }

    /// Shown while a per-commit diff is in flight.
    static var loading: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            ProgressView().controlSize(.small)
            Text("Loading diff…")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .padding(CicadaTheme.spacingSM)
    }

    /// Shown when the commit did not change this file (or the fetch failed).
    static var empty: some View {
        Text("No line changes for this entity in this commit.")
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .padding(CicadaTheme.spacingSM)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app/CicadaApp && swift test --filter DiffModelTests`
Expected: PASS (12 tests).

- [ ] **Step 5: Make the entity History rows tappable**

In `EntityDetailCard.swift`, add the diff state beside the other `@State` properties (after `sources` / `newSourceRef`, line 28-29):

```swift
    // G67 — per-commit diffs in the History tab, fetched on demand and cached
    // per commit hash for the life of this card. `expanded` is the set of
    // commits the user has opened; `loading` guards against a second fetch
    // while the first is in flight.
    @State private var expandedCommits: Set<String> = []
    @State private var commitDiffs: [String: EntityDiff] = [:]
    @State private var loadingCommits: Set<String> = []
```

Replace the whole `historyTab` body (lines 806-883) with a version whose row is a `Button`:

```swift
    private var historyTab: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(entity.history.reversed().enumerated()), id: \.element.id) { index, entry in
                HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                    // Timeline
                    VStack(spacing: 0) {
                        Circle()
                            .fill(index == 0
                                  ? Color(hex: 0x22C55E)
                                  : Color(hex: UInt32(entry.changeType.color, radix: 16) ?? 0x999999))
                            .frame(width: 10, height: 10)

                        if index < entity.history.count - 1 {
                            Rectangle()
                                .fill(CicadaTheme.border)
                                .frame(width: 1)
                                .frame(maxHeight: .infinity)
                        }
                    }
                    .frame(width: 10)

                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        historyRowButton(entry)

                        // The diff for an EXPANDED commit. `entry.diff` (present
                        // only when history was fetched with includeDiff=true)
                        // wins so we never re-fetch what we already hold.
                        if isExpanded(entry) {
                            if let inline = entry.diff {
                                DiffView(diff: inline)
                            } else if let fetched = commitDiffs[entry.commitHash] {
                                DiffView(diff: fetched)
                            } else if loadingCommits.contains(entry.commitHash) {
                                DiffView.loading
                            } else {
                                DiffView.empty
                            }
                        }
                    }
                    .padding(.bottom, CicadaTheme.spacingLG)

                    Spacer()
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
    }

    private func isExpanded(_ entry: EntityHistoryEntry) -> Bool {
        !entry.commitHash.isEmpty && expandedCommits.contains(entry.commitHash)
    }

    /// The tappable summary line. A row with no `commitHash` (an older backend
    /// that didn't surface one) renders as plain, un-tappable text rather than a
    /// button that could never do anything.
    @ViewBuilder
    private func historyRowButton(_ entry: EntityHistoryEntry) -> some View {
        if entry.commitHash.isEmpty {
            historyRowLabel(entry, expandable: false)
        } else {
            Button {
                toggleCommit(entry.commitHash)
            } label: {
                historyRowLabel(entry, expandable: true)
            }
            .buttonStyle(.plain)
            .help("Show what changed in this commit")
            .accessibilityLabel("Commit \(entry.date) by \(entry.author)")
        }
    }

    private func historyRowLabel(_ entry: EntityHistoryEntry, expandable: Bool) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingXS) {
                if expandable {
                    Image(systemName: isExpanded(entry) ? "chevron.down" : "chevron.right")
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                Text(entry.date)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                // M3 (backlog A2): who authored this commit.
                if !entry.author.isEmpty {
                    Text(entry.author)
                        .font(CicadaTheme.captionFont)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 1)
                        .background(
                            (entry.author == "user"
                             ? Color(hex: 0x3B82F6)
                             : Color(hex: 0x8B5CF6)).opacity(0.18)
                        )
                        .clipShape(Capsule())
                        .foregroundStyle(entry.author == "user"
                                         ? Color(hex: 0x3B82F6)
                                         : Color(hex: 0x8B5CF6))
                }
            }

            Text(entry.description)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
    }

    /// Collapse, or expand + fetch. On-demand only (the `LogoStore`/
    /// `EntitySource` precedent): a commit diff is not snapshot state, so it
    /// goes straight to `APIClient` and is cached per hash for this card.
    private func toggleCommit(_ commitHash: String) {
        if expandedCommits.contains(commitHash) {
            expandedCommits.remove(commitHash)
            return
        }
        expandedCommits.insert(commitHash)
        guard commitDiffs[commitHash] == nil,
              !loadingCommits.contains(commitHash) else { return }
        loadingCommits.insert(commitHash)
        Task {
            let diff = try? await APIClient.shared.fetchEntityCommitDiff(
                id: entity.id, commitHash: commitHash
            )
            loadingCommits.remove(commitHash)
            if let diff { commitDiffs[commitHash] = diff }
        }
    }
```

Also reset the per-entity diff state when the card swaps entity, inside the existing `.task(id: entity.id)` reset block (lines 250-253):

```swift
            locationListing = nil
            repoContexts = []
            sources = []
            newSourceRef = ""
            expandedCommits = []
            commitDiffs = [:]
            loadingCommits = []
```

- [ ] **Step 6: Build and run the app suite**

Run: `cd app/CicadaApp && swift build && swift test`
Expected: PASS. `swift build` must succeed — `EntityDetailCard.swift` and `ContributorsView.swift` carry "NOT BUILD-VERIFIED" comments from earlier waves, so a pre-existing compile error there is possible; fix it if it appears (it is in the path of this change) rather than working around it.

- [ ] **Step 7: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Views/Common/DiffView.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift \
        app/CicadaApp/Tests/CicadaAppTests/DiffModelTests.swift
git commit -m "$(cat <<'EOF'
feat(app): shared DiffView + tappable entity history rows (G67)

A pure DiffModel decides ordering, gutter glyphs and the truncation row so the
renderer is testable without a view hierarchy; DiffView paints it GitHub-style
(green/red on tinted rows, monospaced, +/- gutters, a "diff clipped" notice).
Each commit row in the History tab is now a Button that expands an inline
diff, fetched on demand from /entities/{id}/history/{commit}/diff and cached
per commit hash for the life of the card.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 9: Contributors → commits → entity → diff drill-down

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/Entity.swift:198-200` (after `ContributorsResponse`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift:918-924`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorsView.swift`
- Test: `app/CicadaApp/Tests/CicadaAppTests/ContributorCommitTests.swift`

**Interfaces:**
- Consumes: `DiffView(diff:)`, `DiffView.loading`, `DiffView.empty` (Task 8); `APIClient.fetchEntityCommitDiff(id:commitHash:)`; `MockURLProtocol`; `Contributor` (`Models/Entity.swift:163`).
- Produces:
  - `ContributorCommit: Identifiable, Codable` — `commitHash`, `date`, `subject`, `entities: [String]`, `filesChanged: Int`; `var id: String { commitHash }`.
  - `ContributorCommitsResponse: Codable` — `author: String`, `commits: [ContributorCommit]`.
  - `APIClient.fetchContributorCommits(author:limit:) async throws -> [ContributorCommit]`.

- [ ] **Step 1: Write the failing test**

Create `app/CicadaApp/Tests/CicadaAppTests/ContributorCommitTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G67 §2.3 — the Contributors drill-down's wire types and fetch.
final class ContributorCommitTests: XCTestCase {

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    // MARK: - Decoding

    func testContributorCommitDecodesTheCamelCaseWirePayload() throws {
        let json = """
        {
            "commitHash": "abc1234def",
            "date": "2026-08-31",
            "subject": "Sleep cycle 2026-08-31",
            "entities": ["mongodb", "cicada"],
            "filesChanged": 4
        }
        """.data(using: .utf8)!

        let commit = try JSONDecoder().decode(ContributorCommit.self, from: json)

        XCTAssertEqual(commit.commitHash, "abc1234def")
        XCTAssertEqual(commit.id, "abc1234def")
        XCTAssertEqual(commit.date, "2026-08-31")
        XCTAssertEqual(commit.subject, "Sleep cycle 2026-08-31")
        XCTAssertEqual(commit.entities, ["mongodb", "cicada"])
        XCTAssertEqual(commit.filesChanged, 4)
    }

    func testContributorCommitToleratesAnOlderBackendMissingTheOptionalFields() throws {
        let json = """
        {"commitHash": "abc1234", "date": "2026-08-31", "subject": "Sleep cycle"}
        """.data(using: .utf8)!

        let commit = try JSONDecoder().decode(ContributorCommit.self, from: json)

        XCTAssertEqual(commit.entities, [])
        XCTAssertEqual(commit.filesChanged, 0)
    }

    func testContributorCommitsResponseDecodesTheEnvelope() throws {
        let json = """
        {"author": "gpt-5.4-mini", "commits": [
            {"commitHash": "a1b2c3d", "date": "2026-08-31", "subject": "Sleep cycle",
             "entities": ["mongodb"], "filesChanged": 1}
        ]}
        """.data(using: .utf8)!

        let payload = try JSONDecoder().decode(ContributorCommitsResponse.self, from: json)

        XCTAssertEqual(payload.author, "gpt-5.4-mini")
        XCTAssertEqual(payload.commits.count, 1)
        XCTAssertEqual(payload.commits[0].entities, ["mongodb"])
    }

    // MARK: - APIClient.fetchContributorCommits

    func testFetchContributorCommitsSendsTheAuthorAsAQueryParam() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/contributors/commits")
            let query = request.url?.query ?? ""
            XCTAssertTrue(query.contains("author=gpt-5.4-mini"), query)
            XCTAssertTrue(query.contains("limit=50"), query)

            let body = """
            {"author": "gpt-5.4-mini", "commits": [
                {"commitHash": "a1b2c3d", "date": "2026-08-31", "subject": "Sleep cycle",
                 "entities": ["mongodb"], "filesChanged": 1}
            ]}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                            httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let commits = try await APIClient(session: MockURLProtocol.makeSession())
            .fetchContributorCommits(author: "gpt-5.4-mini")

        XCTAssertEqual(commits.map(\.commitHash), ["a1b2c3d"])
    }

    func testFetchContributorCommitsPercentEncodesASlashedModelId() async throws {
        MockURLProtocol.handler = { request in
            // The slash must survive as an ENCODED query value, never split the path.
            XCTAssertEqual(request.url?.path, "/contributors/commits")
            XCTAssertTrue(
                (request.url?.query ?? "").contains("author=anthropic%2Fclaude-opus-4"),
                request.url?.query ?? ""
            )
            let body = #"{"author": "anthropic/claude-opus-4", "commits": []}"#.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                            httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let commits = try await APIClient(session: MockURLProtocol.makeSession())
            .fetchContributorCommits(author: "anthropic/claude-opus-4")

        XCTAssertTrue(commits.isEmpty)
    }

    func testFetchContributorCommitsReturnsEmptyAgainstABackendWithoutTheEndpoint() async throws {
        MockURLProtocol.handler = { request in
            let response = HTTPURLResponse(url: request.url!, statusCode: 404,
                                            httpVersion: nil, headerFields: nil)!
            return (response, Data("Not Found".utf8))
        }

        let commits = try await APIClient(session: MockURLProtocol.makeSession())
            .fetchContributorCommits(author: "user")

        XCTAssertTrue(commits.isEmpty, "a 404 means 'no drill-down yet', not an error")
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/CicadaApp && swift test --filter ContributorCommitTests`
Expected: FAIL — `cannot find 'ContributorCommit' in scope`.

- [ ] **Step 3: Add the models**

In `app/CicadaApp/Sources/CicadaApp/Models/Entity.swift`, insert after `ContributorsResponse` (line 198-200):

```swift
// G67 — one commit in a contributor's drill-down. `entities` are entity ids,
// each of which can be handed to `/entities/{id}/history/{commit}/diff` to show
// exactly what this author changed on that page in this commit.
struct ContributorCommit: Identifiable, Codable {
    var id: String { commitHash }
    let commitHash: String
    let date: String
    let subject: String
    let entities: [String]
    let filesChanged: Int

    enum CodingKeys: String, CodingKey {
        case commitHash, date, subject, entities, filesChanged
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        commitHash = try c.decode(String.self, forKey: .commitHash)
        date = try c.decodeIfPresent(String.self, forKey: .date) ?? ""
        subject = try c.decodeIfPresent(String.self, forKey: .subject) ?? ""
        entities = try c.decodeIfPresent([String].self, forKey: .entities) ?? []
        filesChanged = try c.decodeIfPresent(Int.self, forKey: .filesChanged) ?? 0
    }

    init(commitHash: String, date: String, subject: String,
         entities: [String] = [], filesChanged: Int = 0) {
        self.commitHash = commitHash
        self.date = date
        self.subject = subject
        self.entities = entities
        self.filesChanged = filesChanged
    }
}

struct ContributorCommitsResponse: Codable {
    let author: String
    let commits: [ContributorCommit]
}
```

- [ ] **Step 4: Add the APIClient call**

In `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift`, add below `fetchContributors` (line 921-924):

```swift
    /// `GET /contributors/commits?author=&limit=` (G67) — one author's recent
    /// commits, for the Contributors drill-down. `author` is a QUERY value
    /// because model ids contain slashes (`anthropic/claude-opus-4`); it is
    /// percent-encoded so the slash never splits the path. On demand only — no
    /// Store domain, no ETag. Returns `[]` on any failure (including a backend
    /// that hasn't shipped the endpoint) so the row shows an empty state rather
    /// than an error banner.
    func fetchContributorCommits(author: String, limit: Int = 50) async throws -> [ContributorCommit] {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&+=?/#")
        let a = author.addingPercentEncoding(withAllowedCharacters: allowed) ?? author
        do {
            let resp: ContributorCommitsResponse = try await get(
                "/contributors/commits?author=\(a)&limit=\(limit)"
            )
            return resp.commits
        } catch {
            return []
        }
    }
```

- [ ] **Step 5: Make contributor rows expand into commits → entity chips → diff**

In `ContributorsView.swift`, change the row loop to pass a binding-free expansion callback and add the drill-down. Replace the `ForEach` inside the `ScrollView` (lines 29-32):

```swift
                ScrollView {
                    VStack(spacing: CicadaTheme.spacingSM) {
                        ForEach(viewModel.contributors) { c in
                            ContributorRow(
                                contributor: c,
                                totalCommits: viewModel.totalCommits,
                                isExpanded: expandedAuthor == c.author,
                                onToggle: { toggle(c.author) }
                            )
                        }
                    }
                }
```

Add the state and toggle to `ContributorsView` (after the `@Environment` line 10):

```swift
    /// At most one contributor is expanded at a time — the drill-down is tall
    /// and two open at once makes the list unreadable.
    @State private var expandedAuthor: String?

    private func toggle(_ author: String) {
        expandedAuthor = expandedAuthor == author ? nil : author
    }
```

Extend `ContributorRow` with the new inputs and the drill-down body. Replace its stored properties (lines 58-59) and `body` (lines 83-121):

```swift
private struct ContributorRow: View {
    let contributor: Contributor
    let totalCommits: Int
    let isExpanded: Bool
    let onToggle: () -> Void

    // G67 — the drill-down: this author's recent commits, each listing the
    // entities it touched. Fetched once per row on first expand and kept for
    // the life of the view; `commitDiffs` caches per (entity, commit).
    @State private var commits: [ContributorCommit]?
    @State private var isLoadingCommits = false
    @State private var openDiff: DiffKey?
    @State private var commitDiffs: [String: EntityDiff] = [:]
    @State private var loadingDiffs: Set<String> = []

    /// Which entity chip is open, on which commit.
    private struct DiffKey: Equatable {
        let entityId: String
        let commitHash: String
        var cacheKey: String { "\(entityId)@\(commitHash)" }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Button(action: onToggle) { summary }
                .buttonStyle(.plain)
                .accessibilityLabel("\(contributor.author), \(contributor.commitCount) commits")

            if isExpanded { drillDown }
        }
        .padding(CicadaTheme.spacingMD)
        .background(CicadaTheme.surfaceHover.opacity(0.4))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
        .task(id: isExpanded) {
            guard isExpanded, commits == nil, !isLoadingCommits else { return }
            isLoadingCommits = true
            commits = (try? await APIClient.shared.fetchContributorCommits(
                author: contributor.author
            )) ?? []
            isLoadingCommits = false
        }
    }

    private var summary: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack {
                Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textTertiary)
                ContributorAvatar(contributor: contributor, kind: kind)
                Text(contributor.author)
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Spacer()
                Text("\(contributor.commitCount) commits")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }

            HStack(spacing: CicadaTheme.spacingMD) {
                Text("\(contributor.entityCount) entities")
                Text("\(contributor.fileCount) files")
                if !contributor.lastActive.isEmpty {
                    Text("last \(contributor.lastActive)")
                }
            }
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textTertiary)

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 2)
                        .fill(CicadaTheme.border)
                        .frame(height: 4)
                    RoundedRectangle(cornerRadius: 2)
                        .fill(accent)
                        .frame(width: geo.size.width * share, height: 4)
                }
            }
            .frame(height: 4)
        }
        .contentShape(Rectangle())
    }

    @ViewBuilder
    private var drillDown: some View {
        if isLoadingCommits {
            HStack(spacing: CicadaTheme.spacingXS) {
                ProgressView().controlSize(.small)
                Text("Loading commits…")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        } else if let commits, commits.isEmpty {
            Text("No commits found for this author.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        } else if let commits {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                ForEach(commits) { commit in
                    commitRow(commit)
                }
            }
            .padding(.leading, CicadaTheme.spacingMD)
        }
    }

    private func commitRow(_ commit: ContributorCommit) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Text(commit.date)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                Text(commit.subject)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1)
                Spacer()
                Text("\(commit.filesChanged) files")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }

            if commit.entities.isEmpty {
                Text("No entity pages changed in this commit.")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else {
                FlowLayout(spacing: 6) {
                    ForEach(commit.entities, id: \.self) { entityId in
                        entityChip(entityId, commit: commit)
                    }
                }
            }

            if let key = openDiff, key.commitHash == commit.commitHash {
                if let diff = commitDiffs[key.cacheKey] {
                    DiffView(diff: diff)
                } else if loadingDiffs.contains(key.cacheKey) {
                    DiffView.loading
                } else {
                    DiffView.empty
                }
            }
        }
        .padding(CicadaTheme.spacingSM)
        .background(CicadaTheme.surface.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    private func entityChip(_ entityId: String, commit: ContributorCommit) -> some View {
        let key = DiffKey(entityId: entityId, commitHash: commit.commitHash)
        let isOpen = openDiff == key
        return Button {
            openEntityDiff(key)
        } label: {
            Text(entityId)
                .font(.system(size: 11))
                .lineLimit(1)
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(isOpen ? CicadaTheme.accent.opacity(0.22)
                                   : CicadaTheme.accent.opacity(0.10))
                .foregroundStyle(CicadaTheme.accent)
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
        .help("Show what changed on \(entityId) in this commit")
    }

    private func openEntityDiff(_ key: DiffKey) {
        if openDiff == key {
            openDiff = nil
            return
        }
        openDiff = key
        guard commitDiffs[key.cacheKey] == nil,
              !loadingDiffs.contains(key.cacheKey) else { return }
        loadingDiffs.insert(key.cacheKey)
        Task {
            let diff = try? await APIClient.shared.fetchEntityCommitDiff(
                id: key.entityId, commitHash: key.commitHash
            )
            loadingDiffs.remove(key.cacheKey)
            if let diff { commitDiffs[key.cacheKey] = diff }
        }
    }
```

(Keep `kind`, `accent` and `share` — lines 61-81 — exactly as they are.)

`FlowLayout` is currently `private` to `EntityDetailCard.swift`. Change its declaration there from `private struct FlowLayout: Layout {` to `struct FlowLayout: Layout {` so both views share the one implementation rather than duplicating it. Update the doc comment above it to say it is shared by the entity card's tag/related pills and the Contributors entity chips.

- [ ] **Step 6: Build and run the app suite**

Run: `cd app/CicadaApp && swift build && swift test`
Expected: PASS (`ContributorCommitTests`: 6 tests).

- [ ] **Step 7: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Models/Entity.swift \
        app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorsView.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift \
        app/CicadaApp/Tests/CicadaAppTests/ContributorCommitTests.swift
git commit -m "$(cat <<'EOF'
feat(app): contributor -> commits -> entity -> diff drill-down (G67)

A contributor row now expands into that author's recent commits
(/contributors/commits, author percent-encoded so slashed model ids survive);
each commit lists the entity pages it touched as chips, and tapping one shows
the shared DiffView for that entity at that commit. Loading/empty/error states
per row; diffs cached per (entity, commit). FlowLayout is promoted from
EntityDetailCard-private to shared so the chips reuse it.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 10: Decay chip + picker in the entity card

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/Entity.swift` (new `DecayClass` enum; `Entity` 451-539; `GraphNode` 666-765)
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift:795-797`
- Modify: `app/CicadaApp/Sources/CicadaApp/ViewModels/GraphViewModel.swift:184-206`, `:424-432`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift:748-802`, `:1108-1127`
- Test: `app/CicadaApp/Tests/CicadaAppTests/DecayClassTests.swift`

**Interfaces:**
- Consumes: `PUT /entities/{id}/decay` with body `{"decayClass": "<value>"}` returning a full `EntityResponse` (Task 6); `MockURLProtocol`; `Store.invalidateEntity(_:)` (`Sync/Store.swift:499`).
- Produces:
  - `DecayClass: String, Codable, CaseIterable, Identifiable` — `evergreen | durable | active | volatile`, plus `var label: String`, `var blurb: String`, `var chipText: String`, `var icon: String`.
  - `Entity.decayClass: DecayClass` (defaulted `.active`, decode-tolerant).
  - `GraphNode.decayClass: DecayClass` (defaulted `.active`, decode-tolerant).
  - `APIClient.setDecayClass(entityId:_:) async throws -> Entity`.
  - `GraphViewModel.reloadEntity(id:) async` — invalidate + reload, so the card shows the server's truth after a write.

- [ ] **Step 1: Write the failing test**

Create `app/CicadaApp/Tests/CicadaAppTests/DecayClassTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G66 §1.7 — the decay class on the app side: decode tolerance (old cached
/// snapshots must still load), the chip copy, and the override PUT.
final class DecayClassTests: XCTestCase {

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    // MARK: - Copy

    func testEveryClassHasAHumanChipStringMatchingTheSpec() {
        XCTAssertEqual(DecayClass.evergreen.chipText, "evergreen · never fades")
        XCTAssertEqual(DecayClass.durable.chipText, "durable · fades slowly")
        XCTAssertEqual(DecayClass.active.chipText, "active")
        XCTAssertEqual(DecayClass.volatile.chipText, "volatile · expected to change")
    }

    func testAllFourClassesArePickable() {
        XCTAssertEqual(
            DecayClass.allCases.map(\.rawValue),
            ["evergreen", "durable", "active", "volatile"]
        )
    }

    // MARK: - Decode tolerance

    func testEntityDecodesTheDecayClassFromTheWire() throws {
        let json = """
        {"id": "mongodb", "name": "MongoDB", "type": "tool", "status": "active",
         "confidence": 0.8, "created": "2026-01-01", "lastReferenced": "2026-08-01",
         "decayRate": 0.15, "decayClass": "volatile", "version": 1,
         "markdownContent": "", "history": []}
        """.data(using: .utf8)!

        let entity = try JSONDecoder().decode(Entity.self, from: json)

        XCTAssertEqual(entity.decayClass, .volatile)
    }

    func testEntityFromAnOlderBackendDefaultsToActive() throws {
        let json = """
        {"id": "mongodb", "name": "MongoDB", "type": "tool", "status": "active",
         "confidence": 0.8, "created": "2026-01-01", "lastReferenced": "2026-08-01",
         "decayRate": 0.05, "version": 1, "markdownContent": "", "history": []}
        """.data(using: .utf8)!

        XCTAssertEqual(try JSONDecoder().decode(Entity.self, from: json).decayClass, .active)
    }

    func testAnUnknownFutureClassNeverFailsTheDecode() throws {
        let json = """
        {"id": "x", "name": "X", "type": "tool", "status": "active", "confidence": 0.5,
         "created": "2026-01-01", "lastReferenced": "2026-01-01", "decayRate": 0.05,
         "decayClass": "glacial", "version": 1, "markdownContent": "", "history": []}
        """.data(using: .utf8)!

        XCTAssertEqual(try JSONDecoder().decode(Entity.self, from: json).decayClass, .active)
    }

    func testGraphNodeDecodesTheClassAndToleratesAnOldCachedSnapshot() throws {
        let withClass = """
        {"id": "a", "name": "A", "type": "concept", "status": "active",
         "confidence": 0.5, "decayClass": "durable"}
        """.data(using: .utf8)!
        let without = """
        {"id": "a", "name": "A", "type": "concept", "status": "active", "confidence": 0.5}
        """.data(using: .utf8)!

        XCTAssertEqual(try JSONDecoder().decode(GraphNode.self, from: withClass).decayClass,
                       .durable)
        XCTAssertEqual(try JSONDecoder().decode(GraphNode.self, from: without).decayClass,
                       .active)
    }

    // MARK: - APIClient.setDecayClass

    func testSetDecayClassPUTsTheCamelCaseBodyAndReturnsTheUpdatedEntity() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "PUT")
            XCTAssertEqual(request.url?.path, "/entities/mongodb/decay")

            let bodyData = request.httpBodyStream.map { stream -> Data in
                stream.open()
                defer { stream.close() }
                var data = Data()
                var buffer = [UInt8](repeating: 0, count: 1024)
                while stream.hasBytesAvailable {
                    let read = stream.read(&buffer, maxLength: 1024)
                    if read <= 0 { break }
                    data.append(buffer, count: read)
                }
                return data
            } ?? request.httpBody ?? Data()
            let payload = try? JSONSerialization.jsonObject(with: bodyData) as? [String: Any]
            XCTAssertEqual(payload?["decayClass"] as? String, "evergreen")

            let body = """
            {"id": "mongodb", "name": "MongoDB", "type": "tool", "status": "active",
             "confidence": 0.8, "created": "2026-01-01", "lastReferenced": "2026-08-01",
             "decayRate": 0.0, "decayClass": "evergreen", "version": 1,
             "markdownContent": "", "history": []}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                            httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let entity = try await APIClient(session: MockURLProtocol.makeSession())
            .setDecayClass(entityId: "mongodb", .evergreen)

        XCTAssertEqual(entity.decayClass, .evergreen)
        XCTAssertEqual(entity.decayRate, 0.0)
    }

    func testSetDecayClassPercentEncodesALegacyEntityId() async throws {
        MockURLProtocol.handler = { request in
            // Assert on absoluteString, NOT `url.path`: Foundation decodes
            // percent-escapes out of `.path`, so the encoding is invisible there.
            XCTAssertTrue(
                request.url?.absoluteString.hasSuffix("/entities/atle%CC%81tico/decay") == true,
                request.url?.absoluteString ?? "nil"
            )
            let body = """
            {"id": "atlético", "name": "Atletico", "type": "company", "status": "active",
             "confidence": 0.5, "created": "2026-01-01", "lastReferenced": "2026-01-01",
             "decayRate": 0.05, "decayClass": "active", "version": 1,
             "markdownContent": "", "history": []}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                            httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        _ = try await APIClient(session: MockURLProtocol.makeSession())
            .setDecayClass(entityId: "atle\u{0301}tico", .active)
    }

    func testSetDecayClassPropagatesAnHTTPFailure() async {
        MockURLProtocol.handler = { request in
            let response = HTTPURLResponse(url: request.url!, statusCode: 404,
                                            httpVersion: nil, headerFields: nil)!
            return (response, Data("Entity nope not found".utf8))
        }

        do {
            _ = try await APIClient(session: MockURLProtocol.makeSession())
                .setDecayClass(entityId: "nope", .durable)
            XCTFail("a 404 must surface so the picker can revert")
        } catch {
            // expected — the caller reverts the optimistic chip
        }
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/CicadaApp && swift test --filter DecayClassTests`
Expected: FAIL — `cannot find 'DecayClass' in scope`.

- [ ] **Step 3: Add the `DecayClass` model + the two fields**

In `app/CicadaApp/Sources/CicadaApp/Models/Entity.swift`, add the enum right after `EntityStatus` (line 48):

```swift
/// G66 — how fast a belief fades when it stops being mentioned.
///
/// Decode-tolerant everywhere: an unknown future value, or an older backend
/// that omits the field entirely, resolves to `.active` (the neutral default)
/// rather than failing the whole entity/graph decode.
enum DecayClass: String, Codable, CaseIterable, Identifiable {
    case evergreen, durable, active, volatile

    var id: String { rawValue }

    var label: String { rawValue.capitalized }

    /// One-line "what this means" for the picker menu.
    var blurb: String {
        switch self {
        case .evergreen: "Never fades. For artifacts — saved links, media — and anything you want kept."
        case .durable: "Fades slowly. For stable preferences, skills, long-lived concepts."
        case .active: "The default. Fades if it stops coming up."
        case .volatile: "Expected to change within weeks — a role, a status, a current focus."
        }
    }

    /// The chip text in the entity card's metadata strip.
    var chipText: String {
        switch self {
        case .evergreen: "evergreen · never fades"
        case .durable: "durable · fades slowly"
        case .active: "active"
        case .volatile: "volatile · expected to change"
        }
    }

    var icon: String {
        switch self {
        case .evergreen: "infinity"
        case .durable: "tortoise.fill"
        case .active: "clock"
        case .volatile: "hare.fill"
        }
    }
}
```

Add to `Entity` after `var decayRate: Double` (line 459):

```swift
    /// G66 — the semantic class beside the numeric rate. Server-resolved (an
    /// explicit `decay_class:`, else inferred from the entity type), so this is
    /// always populated for a real entity; `.active` for a graph-node stub.
    var decayClass: DecayClass = .active
```

Add `decayClass` to `Entity.CodingKeys` (line 505):

```swift
        case decayRate, decayClass, sourceEpisodes, tags, related, version
```

Decode it tolerantly in `Entity.init(from:)` after `decayRate` (line 520):

```swift
        decayRate = try c.decode(Double.self, forKey: .decayRate)
        decayClass = (try? c.decode(DecayClass.self, forKey: .decayClass)) ?? .active
```

Add a trailing defaulted parameter to `Entity`'s memberwise init (line 480-501) so existing call sites still compile:

```swift
    init(
        id: String, name: String, type: EntityType, status: EntityStatus,
        confidence: Double, created: String, lastReferenced: String,
        decayRate: Double, sourceEpisodes: [String], tags: [String],
        related: [String], version: Int, markdownContent: String,
        history: [EntityHistoryEntry], decayClass: DecayClass = .active
    ) {
        self.id = id
        self.name = name
        self.type = type
        self.status = status
        self.confidence = confidence
        self.created = created
        self.lastReferenced = lastReferenced
        self.decayRate = decayRate
        self.decayClass = decayClass
        self.sourceEpisodes = sourceEpisodes
        self.tags = tags
        self.related = related
        self.version = version
        self.markdownContent = markdownContent
        self.history = history
    }
```

Add the same field to `GraphNode` after `let hasLogo: Bool` (line 700):

```swift
    /// G66: the entity's decay class, resolved server-side. Lets the detail
    /// card show the right chip on the very first frame, before the full entity
    /// arrives. Decode-tolerant so an old on-disk `SnapshotCache` still loads.
    let decayClass: DecayClass
```

Add it to `GraphNode.CodingKeys` (line 706):

```swift
        case summary, contentHash, hasLogo, decayClass
```

Add the defaulted memberwise parameter — change the init's last parameter line (line 715) from

```swift
        summary: String? = nil, contentHash: String = "", hasLogo: Bool = false
    ) {
```

to

```swift
        summary: String? = nil, contentHash: String = "", hasLogo: Bool = false,
        decayClass: DecayClass = .active
    ) {
```

and add one assignment at the end of that init's body, immediately after `self.hasLogo = hasLogo` (line 735):

```swift
        self.decayClass = decayClass
```

(`GraphNode` is constructed in only two places outside its own file — `GraphDiffTests.swift:7` and `GraphPushTests.swift:29` — and both use the memberwise init with trailing defaults, so neither needs a change.)

And the tolerant decode (after line 763):

```swift
        hasLogo = try c.decodeIfPresent(Bool.self, forKey: .hasLogo) ?? false
        decayClass = (try? c.decode(DecayClass.self, forKey: .decayClass)) ?? .active
```

- [ ] **Step 4: Add the APIClient write + the view-model reload hook**

In `APIClient.swift`, add below `fetchEntity` (line 795-797):

```swift
    /// `PUT /entities/{id}/decay` (G66 §1.7) — the user's decay override.
    /// The backend writes the class plus its mapped numeric rate and commits as
    /// `Cicada-Author: user`, then returns the refreshed entity. Errors
    /// propagate so the picker can revert its optimistic selection.
    func setDecayClass(entityId: String, _ decayClass: DecayClass) async throws -> Entity {
        return try await put(
            "/entities/\(encodedID(entityId))/decay",
            body: ["decayClass": decayClass.rawValue]
        )
    }
```

In `GraphViewModel.swift`, seed the stub entity's class from the node — replace the `Entity(...)` construction at lines 190-205 with:

```swift
            Entity(
                id: node.id,
                name: node.name,
                type: node.type,
                status: node.status,
                confidence: node.confidence,
                created: "",
                lastReferenced: "",
                decayRate: 0,
                sourceEpisodes: [],
                tags: node.tags,
                related: [],
                version: 0,
                markdownContent: node.summary ?? "",
                history: [],
                decayClass: node.decayClass
            )
```

And add the post-write reload beside `loadFullEntity` (after line 432):

```swift
    /// Drop the memoised body and re-read it, so a write through `APIClient`
    /// (the decay override) is reflected by the card instead of showing the
    /// pre-write cached entity.
    func reloadEntity(id: String) async {
        store.invalidateEntity(id)
        await loadFullEntity(id: id)
    }
```

- [ ] **Step 5: Render the chip + picker**

In `EntityDetailCard.swift`, add the optimistic-selection state beside the other `@State` (after line 29):

```swift
    /// G66 — the decay class the user just picked, shown immediately while the
    /// PUT is in flight. Cleared once the reload lands (or on failure, so the
    /// chip snaps back to the server's truth).
    @State private var pendingDecayClass: DecayClass?
```

Replace the created/lastReferenced `HStack` at the bottom of `metadataSection` (lines 792-800) with a version that includes the chip:

```swift
            HStack(spacing: CicadaTheme.spacingLG) {
                Label(entity.created, systemImage: "calendar")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)

                Label(entity.lastReferenced, systemImage: "clock")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)

                decayChip

                Spacer()
            }
```

Add the chip + picker below `metadataSection` (before `// MARK: - History Tab`, line 804):

```swift
    // MARK: - Decay chip (G66 §1.7)
    //
    // The raw `decay_rate` number was never meaningful to a reader ("0.05" says
    // nothing); the class does. Tapping the chip opens a picker that PUTs the
    // override — the user's authority over how fast the agent forgets.

    private var shownDecayClass: DecayClass { pendingDecayClass ?? entity.decayClass }

    private var decayChip: some View {
        Menu {
            ForEach(DecayClass.allCases) { option in
                Button {
                    setDecay(option)
                } label: {
                    Label(
                        "\(option.label) — \(option.blurb)",
                        systemImage: option == shownDecayClass ? "checkmark" : option.icon
                    )
                }
            }
        } label: {
            HStack(spacing: 4) {
                Image(systemName: shownDecayClass.icon)
                    .font(.system(size: 9))
                Text(shownDecayClass.chipText)
                    .font(CicadaTheme.captionFont)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(decayChipTint.opacity(0.15))
            .foregroundStyle(decayChipTint)
            .clipShape(Capsule())
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .help("How fast this entity fades when it stops being mentioned")
        .accessibilityLabel("Decay class: \(shownDecayClass.label)")
    }

    private var decayChipTint: Color {
        switch shownDecayClass {
        case .evergreen: Color(hex: 0x22C55E)
        case .durable: Color(hex: 0x4A9EFF)
        case .active: CicadaTheme.textSecondary
        case .volatile: Color(hex: 0xF59E0B)
        }
    }

    private func setDecay(_ option: DecayClass) {
        guard option != entity.decayClass else { return }
        pendingDecayClass = option  // optimistic: the chip flips immediately
        Task {
            do {
                _ = try await APIClient.shared.setDecayClass(entityId: entity.id, option)
                await graphVM.reloadEntity(id: entity.id)
            } catch {
                // Leave the server's value in place rather than lying about it.
            }
            pendingDecayClass = nil
        }
    }
```

Finally, surface the class in the fallback frontmatter reconstruction (`buildFullMarkdown`, line 1119):

```swift
        decay_rate: \(entity.decayRate)
        decay_class: \(entity.decayClass.rawValue)
```

Also reset `pendingDecayClass = nil` in the `.task(id: entity.id)` reset block alongside the other per-entity state.

- [ ] **Step 6: Build and run the app suite**

Run: `cd app/CicadaApp && swift build && swift test`
Expected: PASS (`DecayClassTests`: 9 tests). `GraphDiffTests`/`GraphPushTests`/`SnapshotCacheTests` construct `GraphNode` with the memberwise init and decode cached snapshots — both paths are defaulted, so they must stay green untouched.

- [ ] **Step 7: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Models/Entity.swift \
        app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift \
        app/CicadaApp/Sources/CicadaApp/ViewModels/GraphViewModel.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift \
        app/CicadaApp/Tests/CicadaAppTests/DecayClassTests.swift
git commit -m "$(cat <<'EOF'
feat(app): decay chip + picker in the entity card (G66)

The metadata strip stops showing a bare decay_rate number nobody can read and
shows the class instead — "evergreen · never fades", "durable · fades slowly",
"active", "volatile · expected to change" — as a menu that PUTs the override
to /entities/{id}/decay, flipping optimistically and reverting on failure.
Entity and GraphNode gain a decode-tolerant decayClass (old cached snapshots
still load), and the graph stub seeds it so the chip is right on frame one.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 11: Documentation + backlog

**Files:**
- Modify: `CLAUDE.md` (Entity Schema section, API Design endpoint block, Key Design Decisions)
- Modify: `docs/goals/memory-evolution.md:586-587` (G66, G67)

**Interfaces:**
- Consumes: everything shipped in Tasks 1-10. No code changes; docs must match the code exactly.

- [ ] **Step 1: Document the class in the Entity Schema section**

In `CLAUDE.md`, add `decay_class` to the frontmatter example in **Entity Schema**, immediately after the `decay_rate` line:

```yaml
decay_rate: 0.05           # per-entity, not global
decay_class: active        # evergreen | durable | active | volatile (G66)
```

Then add this subsection immediately after the **Status lifecycle** line in that same section:

```markdown
### Decay classes (G66)
Every entity carries a semantic `decay_class:` beside the numeric `decay_rate:`,
resolved by the one resolver `api/services/decay_policy.py`:

| Class | Entity rate/wk | Claim multiplier | Meaning |
|---|---|---|---|
| `evergreen` | 0.0 | 0.0 | Never fades. Artifacts (media/bookmarks) + anything the user pins. |
| `durable` | 0.02 | 0.5 | Fades slowly. Stable preferences, skills, long-lived concepts. |
| `active` | 0.05 | 1.0 | The default for a belief about the user's life. |
| `volatile` | 0.15 | 2.0 | Expected to change within weeks (role, status, current focus). |

`decay_policy.resolve(fm)` returns `(class, rate)`: an explicit `decay_class:`
wins; otherwise the class is inferred from `type` (`media` → evergreen, `skill`
→ durable, everything else → active) so legacy pages keep working untouched. An
explicit numeric `decay_rate:` that differs from the class map still wins for
the three decaying classes (the class stays as the label); `evergreen` pins its
rate to `0.0` unconditionally.

**Anti-pollution rail (mirrors `PRODUCIBLE_ENTITY_TYPES`):** Stage-1 extraction
may PROPOSE `durable|active|volatile` and **never `evergreen`**
(`AGENT_PRODUCIBLE_DECAY_CLASSES` in `schemas.py`, enforced by
`decay_policy.agent_class` at extraction AND again in the create branch).
Evergreen is reserved for the ingest writers and the user, so an over-eager
extractor can never stop the graph from archiving.

**Both engines honor it.** The entity engine
(`conflict_resolver.resolve_and_prune`) takes its rate from the resolver and
skips evergreen entities outright — no decay math, no decay nudge, never
auto-archived, so a bookmark can no longer generate a "still interested?"
question. The claim engine (`claim_reconciler._decay_claims`) multiplies its
per-epistemic × source_trust rate by the SUBJECT's class multiplier, supplied by
an injected `decay_class_fn` (default: `decay_policy.class_lookup(memory_path)`).

**Recovery.** A `decaying`/`archived` entity mentioned again is promoted back to
`active` with `confidence = max(current, 0.6)` — the counter-signal half of
"time as a signal", promised in this file long before it existed. `dropped` is
never resurrected.

**Migration.** `api/services/decay_migration.backfill_decay_classes` runs once
per bank on API startup (marker `.decay_classed`, scoped to `entities/`, author
`cicada`, trigger `maintenance/decay_class_backfill`): media → evergreen/0.0
with any wrongly-faded page restored to `active` at confidence ≥ 0.7, skills →
durable.
```

- [ ] **Step 2: Add the endpoints to the API Design block**

In `CLAUDE.md`'s API Design endpoint listing, add these two lines — the decay one after `PATCH /entities/{id}/repos`, the commits one after `GET /contributors`:

```
PUT  /entities/{id}/decay                 → set decay class {decayClass: evergreen|durable|active|volatile}
GET  /contributors/commits?author=&limit= → one author's recent commits (+ entities touched) for the diff drill-down
```

Also extend the `GET /entities/{id}/history/{commit}/diff` line so it records that the app now consumes it:

```
GET  /entities/{id}/history/{commit}/diff → added/removed lines for that entity file at that commit
                                            (rendered inline by the app's shared DiffView — entity History rows
                                             and the Contributors drill-down both expand into it)
```

- [ ] **Step 3: Add the design decision**

In `CLAUDE.md`'s **Key Design Decisions** table, add one row:

| Decision | Rationale |
|----------|-----------|
| Decay class over a bare per-writer rate | A hardcoded `decay_rate` float was invisible to the agent and unchangeable by the user, and it decayed bookmarks — artifacts that never become less true. A four-value class the agent estimates, both engines honor and the user overrides makes the policy legible and correctable. |

- [ ] **Step 4: Mark the backlog items shipped**

In `docs/goals/memory-evolution.md`, change G66's status cell (line 586) from `🔲 spec ready` to `✅` and append to its description:

```
**Shipped 2026-08-31:** `DecayClass` + `DECAY_CLASS_RATES`/`CLAIM_DECAY_MULTIPLIERS`/`AGENT_PRODUCIBLE_DECAY_CLASSES` in `schemas.py`; the one resolver `api/services/decay_policy.py`; every writer (media/skills/Sleep-create/agentic/clarification) through it; Stage-1 estimates a class behind the evergreen rail; `conflict_resolver` skips evergreen and promotes back on re-mention; `claim_reconciler` multiplies decay by the subject's class; `PUT /entities/{id}/decay`; `decayClass` on `EntityResponse` + graph nodes (folded into `content_hash`); the decay chip + picker in `EntityDetailCard`; and the one-shot `decay_migration` backfill on startup.
```

And G67's (line 587) from `🔲 spec ready` to `✅` with:

```
**Shipped 2026-08-31:** `git_service.get_contributor_commits` + `GET /contributors/commits?author=&limit=` (author as a query param — model ids contain slashes), a shared `DiffView` with a pure testable `DiffModel` (`Views/Common/DiffView.swift`), tappable commit rows with on-demand per-commit diffs in the entity History tab, and the Contributors row → commits → entity chip → diff drill-down.
```

- [ ] **Step 5: Verify the docs match the code**

Run:
```bash
grep -n "decay_class\|decayClass\|contributors/commits" CLAUDE.md
api/.venv/bin/python -c "
from api.main import app
paths = sorted(r.path for r in app.routes)
assert '/entities/{entity_id}/decay' in paths, paths
assert '/contributors/commits' in paths, paths
print('both endpoints mounted')
"
```
Expected: the grep shows the new schema key, the two endpoint lines and the design-decision row; the Python check prints `both endpoints mounted`.

- [ ] **Step 6: Run both suites one final time**

Run:
```bash
api/.venv/bin/python -m pytest api/tests -q
cd app/CicadaApp && swift test
```
Expected: PASS, PASS.

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md docs/goals/memory-evolution.md
git commit -m "$(cat <<'EOF'
docs: decay classes + commit-diff views; G66/G67 shipped

CLAUDE.md gains a Decay classes section (the four-value table, the resolver's
precedence, the Stage-1 evergreen rail, both engines, recovery, the startup
migration), the two new endpoints, and one Key Design Decisions row. Backlog
G66 and G67 flip to shipped with what actually landed.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

## Verification (whole plan)

After Task 11, the full gate is:

```bash
api/.venv/bin/python -m pytest api/tests -q     # backend, all green
cd app/CicadaApp && swift build && swift test   # app builds and all green
git status --porcelain                          # nothing under memory/, .claude/settings.json untouched
git log --oneline -11                           # 11 commits, one per task
```

Live smoke checks the spec calls for (manual, against the running app — not automated, and not a gate for any task):
- A `type: media` bookmark's detail card shows an "evergreen · never fades" chip.
- MongoDB's History tab has tappable rows that expand into a real red/green diff.
- The Contributors page expands a model into its commits, and an entity chip shows that page's diff at that commit.
- The backend log on first boot after this branch reports the decay-class backfill counts for the live bank.

