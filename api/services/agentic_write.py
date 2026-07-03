"""Agentic write path (D2/M-agentic) — an agent writes structured, observer-
tagged memory directly, reusing the existing claim layer (``claims.py`` +
``claim_reconciler.reconcile_stage3``).

This is the keystone for the "user's own agent, via MCP, writes memory" flow:
:func:`write_claim` resolves (or minimally creates) the subject entity page,
builds a single perspectival :class:`~api.services.claims.Claim`, and runs it
through the SAME deterministic, trust-gated Stage-3 reconciler the nightly
Sleep cycle uses (see ``claim_pipeline.run_claim_pipeline`` for the batch
sibling of this single-claim path). The trust invariant holds identically
here: an ``agent``/``external`` claim can never silently overwrite a claim the
user stated themselves (``observer=rodrigo`` -> ``source_trust=user_stated`` +
``origin=manual_edit``, which is the origin-gated human-protection predicate
``claim_reconciler.is_human`` recognizes) — it COEXISTs (flagged) or is
blocked and surfaces a nudge on the next Sleep cycle's inbox pass instead.

Also home to the pending-episode helpers the agent's own consolidation loop
uses: :func:`list_unprocessed_episodes` / :func:`mark_episodes_processed`, so
an agent can read what Cicada hasn't consolidated yet and check work off
without waiting for the nightly Sleep cycle.

Nothing here ever raises on a normal (even malformed) input — a bad call from
an agent degrades to an ``action: "error"`` result, never a crashed MCP tool
call.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import entity_body, markdown_parser
from api.services.claim_reconciler import reconcile_stage3
from api.services.claims import Claim, parse_claims, write_claims
from api.services.id_utils import resolve_entity_file, sanitize_id

_EP_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# Loose predicate -> entity-type signals for the create-page path. Deliberately
# conservative (mirrors the spirit of promote_targets._PERSON_LABEL_SIGNALS):
# under-inferring to "concept" is safe, over-inferring a wrong type is not.
_TYPE_SIGNALS: list[tuple[str, tuple[str, ...]]] = [
    ("person", (
        "reports-to", "reports to", "manager", "managed-by", "works-with",
        "works-at", "employed-by", "employed at", "interned-at", "interned at",
        "colleague", "co-worker", "knows", "met", "mentor", "supervisor",
        "advisor", "friend", "collaborat", "hired", "recruit", "interview",
        "contact", "founder", "founded", "led-by", "led by", "married-to",
        "sibling-of", "parent-of", "child-of",
    )),
    ("company", (
        "acquired-by", "acquired", "headquartered-in", "headquartered in",
        "subsidiary-of", "competitor-of",
    )),
    ("tool", (
        "uses", "built-with", "built with", "depends-on", "runs-on",
        "integrates-with", "powered-by",
    )),
    ("location", (
        "lives-in", "lives in", "located-in", "located in", "based-in",
        "based in", "born-in",
    )),
    ("deadline", ("due-by", "due by", "deadline")),
]


def _infer_entity_type(predicate: str) -> str:
    """Infer a closed-set entity type from the predicate label, else 'concept'."""
    p = (predicate or "").strip().lower()
    for etype, signals in _TYPE_SIGNALS:
        if any(sig in p for sig in signals):
            return etype
    return "concept"


def _date_from_episode_id(source_episode: str | None) -> str | None:
    """Recover a YYYY-MM-DD date from an episode id/string, else None."""
    if not source_episode:
        return None
    m = _EP_DATE_RE.search(str(source_episode))
    return m.group(1) if m else None


@dataclass
class _ReconcileSettings:
    """Minimal settings shim satisfying claim_reconciler.reconcile_stage3's
    duck-typed ``settings`` argument (memory_path / litellm_model / thresholds).
    """

    memory_path: Path
    litellm_model: str = "mcp-agentic-write"
    archive_threshold: float = 0.2
    decay_nudge_threshold: float = 0.4


def _ensure_subject_page(
    memory_path: Path, subject: str, predicate: str, source_episode: str | None
) -> tuple[Path, str]:
    """Resolve the subject's entity page, creating a minimal v2 stub if absent.

    Returns ``(filepath, entity_id)``. Reuses the same create-page shape the
    Sleep cycle's conflict_resolver uses (``layout_version: 2`` +
    ``entity_body.compose_body_v2``), so an agent-created page is
    indistinguishable in structure from a Sleep-created one.
    """
    entities_dir = memory_path / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)

    existing = resolve_entity_file(memory_path, subject)
    if existing is not None and existing.exists():
        # resolve_entity_file can echo the CALLER's casing (not the true
        # on-disk stem) on a case-insensitive filesystem (macOS APFS) — the
        # same gotcha id_utils.resolve_entity_id documents. Recover the real
        # stem via a case-insensitive directory scan so entity_id always
        # matches the actual filename Claim.subject / K() key off of.
        real = next(
            (f for f in entities_dir.glob("*.md") if f.name.lower() == existing.name.lower()),
            existing,
        )
        return real, real.stem

    entity_id = sanitize_id(subject)
    filepath = entities_dir / f"{entity_id}.md"
    if filepath.exists():
        return filepath, entity_id

    today = str(date.today())
    display_name = subject.strip() or entity_id.replace("-", " ").title()
    frontmatter = {
        "name": display_name,
        "type": _infer_entity_type(predicate),
        "status": "active",
        "confidence": 0.5,
        "created": today,
        "last_referenced": today,
        "decay_rate": 0.05,
        "source_episodes": [source_episode] if source_episode else [],
        "tags": [],
        "related": [],
        "version": 1,
        "layout_version": 2,
    }
    body = entity_body.compose_body_v2(
        summary=f"{display_name} — created via agentic write.",
        key_facts=[],
        history_entries=[],
        related=[],
        links=[],
        open_questions=[],
    )
    markdown_parser.write(filepath, frontmatter, body)
    return filepath, entity_id


def _claim_id(entity_id: str, predicate_slug: str, obj: str, observer: str) -> str:
    """A stable slug: same (subject, predicate, object, observer) => same id,
    so a re-issued identical write is idempotent through reconciliation's
    dedup/reinforce path rather than piling up duplicate claim ids."""
    digest = hashlib.sha1(
        f"{entity_id}\x00{predicate_slug}\x00{obj}\x00{observer}".encode("utf-8")
    ).hexdigest()[:8]
    return f"clm_{entity_id}_{predicate_slug}_{digest}"


def _determine_action(
    claim_id: str, reconciled_claims: list[Claim], nudges: list[dict], audit: list[dict]
) -> str:
    """Map Stage-3's outcome for THIS claim onto the tri-state contract.

    - "written": the claim (or its reinforced duplicate) is live in the page.
    - "coexist": trust protection kept a human claim intact; ours was added
      alongside it, flagged (COEXIST_FLAG / ``shadowed_by_human``).
    - "superseded": our claim did NOT make it onto the page — an existing
      claim already tops it (REJECT) or the two are tied and need a human
      call (CONFLICT_NUDGE); the existing claim stands unchanged.
    """
    for c in reconciled_claims:
        if c.id == claim_id:
            if getattr(c, "_status_note", None) == "shadowed_by_human":
                return "coexist"
            return "written"
    if any(a.get("dropped") == claim_id for a in audit):
        return "superseded"
    if any(n.get("claim_id") == claim_id for n in nudges):
        return "superseded"
    # Not present anywhere and no audit/nudge trail => it was folded into an
    # existing claim as a reinforcing duplicate (same object, same key).
    return "written"


def write_claim(
    memory_path: Path,
    subject: str,
    predicate: str,
    object: str,  # noqa: A002 - matches the domain vocabulary (subject/predicate/object)
    *,
    observer: str,
    confidence: float = 0.7,
    context: str = "general",
    source_episode: str | None = None,
    object_kind: str = "node",
    text: str | None = None,
) -> dict:
    """Write one atomic fact as a Claim, reusing the Sleep cycle's Stage-3
    trust-gated reconciler for dedup/supersession. Never raises.

    Returns ``{subject, entity_id, claim_id, action, observer}`` on success,
    or ``{subject, entity_id: None, claim_id: None, action: "error", observer,
    error}`` on any failure/bad input — the caller (MCP tool handler) can
    render either shape without a try/except of its own.
    """
    subject_raw = (subject or "").strip()
    predicate_raw = (predicate or "").strip()
    object_raw = (object or "").strip()
    observer = (observer or "agent").strip() or "agent"

    if not subject_raw or not predicate_raw or not object_raw:
        return {
            "subject": subject_raw,
            "entity_id": None,
            "claim_id": None,
            "action": "error",
            "observer": observer,
            "error": "subject, predicate, and object are all required.",
        }

    try:
        memory_path = Path(memory_path)
        page, entity_id = _ensure_subject_page(
            memory_path, subject_raw, predicate_raw, source_episode
        )

        predicate_slug = sanitize_id(predicate_raw) or "relates-to"
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.7
        confidence = max(0.0, min(1.0, confidence))

        source_trust = "user_stated" if observer == "rodrigo" else "agent_extracted"
        # Origin-gated human protection (claim_reconciler.is_human): only a
        # manual/clarification origin makes a user_stated claim overwrite-
        # protected. An explicit observer=rodrigo write through this tool IS
        # that manual-assertion channel.
        origin = "manual_edit" if observer == "rodrigo" else "mcp"

        claim_id = _claim_id(entity_id, predicate_slug, object_raw, observer)
        new_claim = Claim(
            id=claim_id,
            text=text or f"{subject_raw} {predicate_raw} {object_raw}",
            subject=entity_id,
            predicate=predicate_slug,
            object=object_raw,
            object_kind=object_kind or "node",
            observer=observer,
            context=context or "general",
            epistemic="explicit",
            source_trust=source_trust,
            confidence=confidence,
            valid_from=_date_from_episode_id(source_episode),
            source_episodes=[source_episode] if source_episode else [],
            origin=origin,
        )

        parsed = markdown_parser.parse(page)
        existing_claims = parse_claims(parsed.body)

        settings = _ReconcileSettings(memory_path=memory_path)
        reconciled, nudges, audit = reconcile_stage3(
            [new_claim],
            {entity_id: existing_claims},
            settings,
        )
        reconciled_claims = reconciled.get(entity_id, existing_claims)

        action = _determine_action(claim_id, reconciled_claims, nudges, audit)

        new_body = write_claims(parsed.body, reconciled_claims)
        if new_body != parsed.body:
            markdown_parser.write(page, parsed.frontmatter, new_body)

        return {
            "subject": subject_raw,
            "entity_id": entity_id,
            "claim_id": claim_id,
            "action": action,
            "observer": observer,
        }
    except Exception as exc:  # never raise on a normal input
        logger.warning(
            f"agentic write_claim failed for subject={subject_raw!r} "
            f"predicate={predicate_raw!r}: {type(exc).__name__}: {exc}"
        )
        return {
            "subject": subject_raw,
            "entity_id": None,
            "claim_id": None,
            "action": "error",
            "observer": observer,
            "error": f"{type(exc).__name__}: {exc}",
        }


def list_unprocessed_episodes(memory_path: Path, limit: int = 50) -> list[dict]:
    """Return ``[{id, title, content}]`` for episodes with ``processed: false``.

    Missing ``processed`` key defaults to unprocessed (matches the episode
    schema's documented default). Never raises: a single malformed episode
    file is skipped, not fatal to the rest of the listing.
    """
    memory_path = Path(memory_path)
    episodes_dir = memory_path / "episodes"
    if not episodes_dir.exists():
        return []

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 50
    if limit <= 0:
        limit = 50

    out: list[dict] = []
    for filepath in sorted(episodes_dir.glob("*.md")):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception as exc:
            logger.warning(f"skipping unreadable episode {filepath.name}: {exc}")
            continue
        fm = parsed.frontmatter or {}
        if fm.get("processed", False):
            continue
        out.append({
            "id": fm.get("id", filepath.stem),
            "title": fm.get("title", filepath.stem),
            "content": parsed.body,
        })
        if len(out) >= limit:
            break
    return out


def mark_episodes_processed(memory_path: Path, ids: list[str]) -> int:
    """Set ``processed: true`` on the named episodes. Returns the count matched.

    Matches by frontmatter ``id`` (falling back to the filename stem), so it
    tolerates whatever id shape :func:`list_unprocessed_episodes` handed back.
    Never raises: an unreadable/unwritable file is skipped, not fatal.
    """
    memory_path = Path(memory_path)
    episodes_dir = memory_path / "episodes"
    if not episodes_dir.exists() or not ids:
        return 0

    id_set = {str(i) for i in ids if i}
    if not id_set:
        return 0

    count = 0
    for filepath in episodes_dir.glob("*.md"):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception as exc:
            logger.warning(f"skipping unreadable episode {filepath.name}: {exc}")
            continue
        fm = parsed.frontmatter or {}
        ep_id = str(fm.get("id", filepath.stem))
        if ep_id not in id_set:
            continue
        try:
            fm["processed"] = True
            markdown_parser.write(filepath, fm, parsed.body)
            count += 1
        except Exception as exc:
            logger.warning(f"could not mark {filepath.name} processed: {exc}")
    return count
