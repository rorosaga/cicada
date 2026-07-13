"""Server-side ``![[…]]`` transclusion resolver (M5b Part 2).

Resolves the four Cicada embed selectors into a
:class:`~api.models.schemas.TransclusionPayload` the companion app's
``TranscludingMarkdownView`` (and, later, ``ask_service``) render inline:

| ref form                       | kind     | resolves to                                  |
|--------------------------------|----------|----------------------------------------------|
| ``subject``                    | entity   | the subject's generated one-liner summary    |
| ``subject#facet``              | facet    | that facet's currently-valid claims          |
| ``claim:<id>``                 | claim    | one rendered claim                           |
| ``subject?context=<c>``        | facet    | all valid claims of that subject in context  |

Three hard guards (the prior-art sweep, d2-architecture-final §"Inline
transclusion"):

- **Depth cap = 3.** Beyond depth 3 a nested embed degrades to an unresolved
  stub instead of recursing.
- **Cycle guard.** A per-render ``visited`` set keyed on the resolved ref; an
  ``A ![[B]]`` / ``B ![[A]]`` cycle degrades to a stub at the boundary, never
  loops.
- **Soft "not found".** A missing subject/claim returns ``resolved=False`` (the
  UI renders ``⚠ ![[ref]] not found``) — this function NEVER raises.

This milestone resolves one ref to its payload (the app recurses one level via
``TransclusionCard``). The depth/visited parameters are threaded so a future
server-side multi-level expansion (``ask_service`` prompt inlining) reuses the
exact same guards.
"""

from __future__ import annotations

from pathlib import Path

from api.models.schemas import ClaimModel, TransclusionPayload
from api.services import markdown_parser
from api.services.claims import Claim, parse_claims
from api.services.hub_builder import _one_line_summary
from api.services.id_utils import resolve_entity_file

# d2: Markdown Preview Enhanced's proven safe limit.
MAX_DEPTH = 3


def _to_model(claim: Claim) -> ClaimModel:
    return ClaimModel(
        id=claim.id,
        text=claim.text,
        subject=claim.subject,
        predicate=claim.predicate,
        object=claim.object,
        object_kind=claim.object_kind,
        observer=claim.observer,
        context=claim.context,
        epistemic=claim.epistemic,
        source_trust=claim.source_trust,
        confidence=claim.confidence,
        valid_from=claim.valid_from or "",
        valid_to=claim.valid_to,
        superseded_by=claim.superseded_by,
        supersedes=claim.supersedes,
        source_episodes=claim.source_episodes,
        premises=claim.premises,
        authored_by=claim.authored_by or "unknown",
        origin=claim.origin,
    )


def _stub(ref: str, kind: str = "entity") -> TransclusionPayload:
    """A soft "not found" payload — never raised, rendered as a warning stub."""
    return TransclusionPayload(kind=kind, ref=ref, title="", summary="", claims=[], resolved=False)


def _parse_ref(ref: str) -> tuple[str, str, str]:
    """Split a transclusion ref into ``(kind, subject_or_id, selector)``.

    Returns one of:
    - ``("claim", claim_id, "")``
    - ``("facet", subject, facet_name)``        for ``subject#facet``
    - ``("facet", subject, context)``           for ``subject?context=<c>``  (selector is the context)
    - ``("entity", subject, "")``               for a bare subject
    """
    ref = (ref or "").strip()
    if not ref:
        return ("entity", "", "")
    if ref.startswith("claim:"):
        return ("claim", ref[len("claim:"):].strip(), "")
    if "?context=" in ref:
        subject, _, context = ref.partition("?context=")
        return ("facet", subject.strip(), context.strip())
    if "#" in ref:
        subject, _, facet = ref.partition("#")
        return ("facet", subject.strip(), facet.strip())
    return ("entity", ref.strip(), "")


def _is_valid(claim: Claim) -> bool:
    """Currently-valid = open window and not flagged superseded."""
    return claim.valid_to is None and not claim.superseded_by


def _load_claims_for_subject(memory_path: Path, subject: str) -> tuple[list[Claim], Path | None]:
    page = resolve_entity_file(memory_path, subject)
    if page is None or not page.exists():
        return ([], None)
    try:
        parsed = markdown_parser.parse(page)
    except Exception:
        return ([], page)
    return (parse_claims(parsed.body), page)


def _entity_summary(memory_path: Path, page: Path) -> tuple[str, str]:
    """``(title, one-line summary)`` for a subject page (claims fence stripped)."""
    try:
        parsed = markdown_parser.parse(page)
    except Exception:
        return (page.stem, "")
    fm = parsed.frontmatter or {}
    title = str(fm.get("name", page.stem.replace("-", " ").title()))
    # Strip the machine claims block so the human-prose summary isn't YAML noise.
    prose = _strip_claims_fence(parsed.body)
    return (title, _one_line_summary(prose))


def _strip_claims_fence(body: str) -> str:
    from api.services.claims import _CLAIMS_BLOCK_RE

    return _CLAIMS_BLOCK_RE.sub("", body or "").strip()


def resolve_transclusion(
    memory_path: Path,
    ref: str,
    *,
    depth: int = 0,
    visited: set[str] | None = None,
) -> TransclusionPayload:
    """Resolve one ``![[ref]]`` to a :class:`TransclusionPayload`. Never raises.

    ``depth`` / ``visited`` enforce the depth-cap and cycle-guard; a caller that
    recurses (future server-side prompt inlining) passes ``depth+1`` and a
    ``visited`` union including the resolved ref.
    """
    visited = visited or set()
    ref = (ref or "").strip()
    if not ref:
        return _stub(ref)
    if depth >= MAX_DEPTH or ref in visited:
        # depth-cap / cycle boundary → degrade to a soft stub (the app shows a
        # "↻ cyclic / too deep" placeholder rather than recursing).
        kind, _, _ = _parse_ref(ref)
        return _stub(ref, kind=kind)

    kind, key, selector = _parse_ref(ref)

    if kind == "claim":
        return _resolve_claim(memory_path, ref, key)
    if kind == "facet":
        return _resolve_facet(memory_path, ref, key, selector)
    return _resolve_entity(memory_path, ref, key)


def _resolve_claim(memory_path: Path, ref: str, claim_id: str) -> TransclusionPayload:
    if not claim_id:
        return _stub(ref, kind="claim")
    entities_dir = memory_path / "entities"
    if not entities_dir.exists():
        return _stub(ref, kind="claim")
    for filepath in sorted(entities_dir.glob("*.md")):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue
        for claim in parse_claims(parsed.body):
            if claim.id == claim_id:
                return TransclusionPayload(
                    kind="claim",
                    ref=ref,
                    title=claim.subject or claim_id,
                    summary=claim.text,
                    claims=[_to_model(claim)],
                    resolved=True,
                )
    return _stub(ref, kind="claim")


def _resolve_facet(
    memory_path: Path, ref: str, subject: str, selector: str
) -> TransclusionPayload:
    claims, page = _load_claims_for_subject(memory_path, subject)
    if page is None:
        return _stub(ref, kind="facet")
    facet_claims = [
        c for c in claims if _is_valid(c) and (not selector or c.context == selector)
    ]
    title, _summary = _entity_summary(memory_path, page)
    label = f"{title} · {selector}" if selector else title
    summary = facet_claims[0].text if facet_claims else ""
    return TransclusionPayload(
        kind="facet",
        ref=ref,
        title=label,
        summary=summary,
        claims=[_to_model(c) for c in facet_claims],
        resolved=True,
    )


def _resolve_entity(memory_path: Path, ref: str, subject: str) -> TransclusionPayload:
    page = resolve_entity_file(memory_path, subject)
    if page is None or not page.exists():
        return _stub(ref, kind="entity")
    title, summary = _entity_summary(memory_path, page)
    return TransclusionPayload(
        kind="entity",
        ref=ref,
        title=title,
        summary=summary,
        claims=[],
        resolved=True,
    )
