"""Deterministic claim seeding from ``graph_edges.yaml`` (M5b Part 1, $0 LLM).

TFG's free-conversion insight: the entire relational layer already exists as
labeled edges in ``<memory>/graph_edges.yaml``. Each ``{source, target, label}``
edge maps mechanically to a seed :class:`~api.services.claims.Claim`
(``subject=source, predicate=normalize(label), object=target``) with the
agent/general/explicit/agent_extracted perspective defaults and
``origin='seed' / authored_by='seed'``. Claims are grouped by subject and
written INTO ``entities/<subject>.md`` via ``write_claims`` (which preserves all
surrounding prose — the page stays the human-readable source of truth), then the
derived claims index is rebuilt.

**Idempotent.** Re-running yields the same claims with the same ids and no
duplicates: claim ids are a deterministic function of
``(subject, predicate, object)`` + ``valid_from``, and an edge whose
``(subject, predicate, object, observer, context)`` key already has a claim on
the page is skipped rather than re-appended.

**Safety.** Operates only on the passed ``memory_path``. Tests pass a tmp
workspace; the live ``memory/`` must never be seeded by the test suite (mirrors
the benchmark safety rails). The ``python -m api.scripts.seed_claims`` entrypoint
is the only intended way to seed real memory, run manually.
"""

from __future__ import annotations

import datetime
import hashlib
from collections import OrderedDict
from pathlib import Path

from loguru import logger

from api.services import markdown_parser, predicates
from api.services.claims import Claim, parse_claims, write_claims
from api.services.vector_index import EmbedFn, SqliteVecIndexer


def _today() -> str:
    return datetime.date.today().isoformat()


def _claim_key(subject: str, predicate: str, obj: str, observer: str, context: str) -> tuple:
    """The dedup identity of a seed claim on a page (NOT the same as its id)."""
    return (subject, predicate, obj, observer, context)


def _seed_claim_id(subject: str, predicate: str, obj: str, valid_from: str) -> str:
    """A stable, collision-resistant id for a seed claim.

    Deterministic in ``(subject, predicate, object)`` so re-running the seeder
    produces byte-identical ids — the foundation of idempotency. Shaped like the
    architecture's ``clm_<date>_<seq>`` but with a content hash as the suffix so
    no global counter (which would be order-dependent and non-idempotent) is
    needed.
    """
    digest = hashlib.sha1(
        f"{subject}\x00{predicate}\x00{obj}".encode("utf-8")
    ).hexdigest()[:8]
    return f"clm_{valid_from}_seed_{digest}"


def _page_created(memory_path: Path, subject: str) -> str | None:
    """Read ``created`` from the subject's page frontmatter, if it has one."""
    page = memory_path / "entities" / f"{subject}.md"
    if not page.exists():
        return None
    try:
        fm = markdown_parser.parse(page).frontmatter or {}
    except Exception:
        return None
    created = fm.get("created")
    return str(created) if created else None


def _load_edges(memory_path: Path) -> list[dict]:
    import yaml

    edges_file = memory_path / "graph_edges.yaml"
    if not edges_file.exists():
        return []
    try:
        data = yaml.safe_load(edges_file.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"could not read graph_edges.yaml: {exc}")
        return []
    return list(data.get("edges", []) or [])


def seed_claims_from_edges(
    memory_path: Path,
    *,
    today: str | None = None,
    embed_fn: EmbedFn | None = None,
    rebuild_index: bool = True,
) -> dict:
    """Seed in-page claims from ``graph_edges.yaml`` and rebuild the claims index.

    Args:
        memory_path: the memory workspace to operate on (tmp in tests).
        today: ``valid_from`` fallback for subjects without a ``created`` date
            (defaults to the system date).
        embed_fn: injected deterministic embedder for tests; ``None`` resolves
            the production embedder (only on real runs).
        rebuild_index: rebuild the derived ``claims`` index after writing
            (default True).

    Returns a summary dict: ``{subjects, edges_total, claims_written, indexed}``.
    ``claims_written`` counts NEW claims added this run (0 on a re-run).
    """
    memory_path = Path(memory_path)
    today = today or _today()
    entities_dir = memory_path / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)

    # Ensure the runtime predicate map exists, then build the normalizer once.
    predicates.install_predicate_map(memory_path)
    normalize = predicates.load_normalizer(memory_path)

    edges = _load_edges(memory_path)

    # Group edges by subject, preserving first-seen order for stable output.
    by_subject: "OrderedDict[str, list[dict]]" = OrderedDict()
    for edge in edges:
        source = str(edge.get("source", "") or "").strip()
        target = str(edge.get("target", "") or "").strip()
        label = str(edge.get("label", "") or "").strip()
        if not source or not target:
            continue
        if source == target:  # skip self-loops (no meaningful claim)
            continue
        by_subject.setdefault(source, []).append(
            {"target": target, "label": label}
        )

    claims_written = 0
    for subject, subject_edges in by_subject.items():
        page = entities_dir / f"{subject}.md"

        if page.exists():
            parsed = markdown_parser.parse(page)
            frontmatter = parsed.frontmatter or {}
            body = parsed.body
        else:
            # No page yet — create a minimal one so the relation has a home.
            frontmatter = {
                "name": subject.replace("-", " ").title(),
                "type": "concept",
                "status": "active",
                "created": today,
            }
            body = ""

        valid_from = _page_created(memory_path, subject) or str(
            frontmatter.get("created") or today
        )

        existing = parse_claims(body)
        existing_keys = {
            _claim_key(c.subject, c.predicate, c.object, c.observer, c.context)
            for c in existing
        }

        new_for_subject: list[Claim] = []
        for edge in subject_edges:
            predicate = normalize(edge["label"]) or "relates-to"
            obj = edge["target"]
            key = _claim_key(subject, predicate, obj, "agent", "general")
            if key in existing_keys:
                continue  # idempotent: this exact claim is already on the page
            existing_keys.add(key)
            claim = Claim(
                id=_seed_claim_id(subject, predicate, obj, valid_from),
                text=_seed_text(subject, predicate, obj),
                subject=subject,
                predicate=predicate,
                object=obj,
                object_kind="node",
                observer="agent",
                context="general",
                epistemic="explicit",
                source_trust="agent_extracted",
                confidence=0.5,
                valid_from=valid_from,
                valid_to=None,
                recorded_at=today,
                authored_by="seed",
                origin="seed",
            )
            new_for_subject.append(claim)

        if not new_for_subject:
            continue

        merged = existing + new_for_subject
        new_body = write_claims(body, merged)
        markdown_parser.write(page, frontmatter, new_body)
        claims_written += len(new_for_subject)

    indexed = 0
    if rebuild_index:
        indexer = SqliteVecIndexer(memory_path, embed_fn=embed_fn)
        indexed = indexer.index_claims()

    summary = {
        "subjects": len(by_subject),
        "edges_total": len(edges),
        "claims_written": claims_written,
        "indexed": indexed,
    }
    logger.info(
        "claim seeding: {subjects} subjects, {claims_written} new claims, "
        "{indexed} indexed".format(**summary)
    )
    return summary


def _seed_text(subject: str, predicate: str, obj: str) -> str:
    """The embedded string for a seed claim — a readable subject-predicate-object."""
    subj_h = subject.replace("-", " ")
    pred_h = predicate.replace("-", " ")
    obj_h = obj.replace("-", " ")
    return f"{subj_h} {pred_h} {obj_h}".strip()
