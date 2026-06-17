"""Tests for M5b Part 1 — deterministic claim seeding ($0 LLM).

Two services, both hermetic (tmp workspace only, never the live ``memory/``):

1. ``predicates`` — installs the canonical predicate map from the M5 prep seed
   into ``<memory>/_predicates.yaml`` and exposes ``normalize_predicate(label)``
   (synonym folding + inverse-pair handling).
2. ``claim_seeder.seed_claims_from_edges`` — converts every ``graph_edges.yaml``
   stanza into an in-page seed ``Claim`` written into
   ``entities/<subject>.md`` via ``write_claims`` (PRESERVING prose), grouped by
   subject, idempotent, then rebuilds the derived claims index.

The seeder runs ONLY on a passed ``memory_path`` (a tmp workspace here) — it
must never touch the live ``memory/`` (benchmark safety rails).
"""

from __future__ import annotations

import numpy as np
import yaml

from api.services import markdown_parser, predicates
from api.services.claim_seeder import seed_claims_from_edges
from api.services.claims import parse_claims

_VOCAB = ["python", "web", "framework", "api", "database", "music", "guitar", "acoustic"]


def fake_embed(texts: list[str], *, is_query: bool = False) -> np.ndarray:
    rows = []
    for text in texts:
        low = text.lower()
        vec = np.array([float(low.count(word)) for word in _VOCAB], dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        rows.append(vec)
    return np.vstack(rows).astype(np.float32)


def _write_edges(memory_path, edges: list[dict]) -> None:
    (memory_path / "graph_edges.yaml").write_text(
        yaml.dump({"edges": edges}, sort_keys=False), encoding="utf-8"
    )


def _write_entity(memory_path, stem, name, body="A page.", created="2026-01-10"):
    entities_dir = memory_path / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(
        entities_dir / f"{stem}.md",
        {"name": name, "type": "concept", "status": "active", "created": created},
        body,
    )


# --------------------------------------------------------------------------- #
# 1. predicate normalization
# --------------------------------------------------------------------------- #


def test_install_predicates_seeds_runtime_file(tmp_path):
    predicates.install_predicate_map(tmp_path)
    runtime = tmp_path / "_predicates.yaml"
    assert runtime.exists()
    data = yaml.safe_load(runtime.read_text(encoding="utf-8")) or {}
    # the canonical/synonym/inverse structure from the prep seed is present
    assert "canonical" in data
    assert "synonyms" in data
    assert "uses" in data["canonical"]


def test_install_predicates_does_not_clobber_existing(tmp_path):
    runtime = tmp_path / "_predicates.yaml"
    runtime.write_text("{}\n", encoding="utf-8")  # M5a seeds it as {}
    predicates.install_predicate_map(tmp_path)
    data = yaml.safe_load(runtime.read_text(encoding="utf-8")) or {}
    # an empty {} placeholder IS replaced with the real seed (it carries no map)
    assert data.get("canonical")


def test_install_predicates_preserves_a_real_existing_map(tmp_path):
    runtime = tmp_path / "_predicates.yaml"
    runtime.write_text(
        yaml.dump({"canonical": ["uses"], "synonyms": {"my-custom": "uses"}}),
        encoding="utf-8",
    )
    predicates.install_predicate_map(tmp_path)
    data = yaml.safe_load(runtime.read_text(encoding="utf-8")) or {}
    # a human-authored / already-populated map is NOT overwritten
    assert data["synonyms"]["my-custom"] == "uses"


def test_normalize_predicate_folds_synonyms(tmp_path):
    predicates.install_predicate_map(tmp_path)
    norm = predicates.load_normalizer(tmp_path)
    assert norm("used") == "uses"
    assert norm("built with") == "uses"
    assert norm("worked at") == "works-at"
    assert norm("is associated with") == "relates-to"


def test_normalize_predicate_passes_canonical_through(tmp_path):
    predicates.install_predicate_map(tmp_path)
    norm = predicates.load_normalizer(tmp_path)
    assert norm("uses") == "uses"
    assert norm("relates-to") == "relates-to"


def test_normalize_predicate_unknown_label_is_slugified_not_dropped(tmp_path):
    predicates.install_predicate_map(tmp_path)
    norm = predicates.load_normalizer(tmp_path)
    # an unseen long-tail label is kept (slugified), never collapsed to a guess
    assert norm("enables interactive 3D axes in") == "enables-interactive-3d-axes-in"


def test_normalize_predicate_is_case_and_whitespace_insensitive(tmp_path):
    predicates.install_predicate_map(tmp_path)
    norm = predicates.load_normalizer(tmp_path)
    assert norm("  Used  ") == "uses"
    assert norm("WORKED AT") == "works-at"


def test_normalize_without_runtime_file_falls_back_gracefully(tmp_path):
    # no _predicates.yaml present at all -> normalizer still slugifies labels
    norm = predicates.load_normalizer(tmp_path)
    assert norm("uses") == "uses"
    assert norm("Some Raw Label") == "some-raw-label"


def test_cardinality_fn_reads_single_and_multi_lists(tmp_path):
    predicates.install_predicate_map(tmp_path)
    card = predicates.build_cardinality_fn(tmp_path)
    # from the seed's single_valued list
    assert card("works-at") is True
    assert card("located-in") is True
    # from the seed's multi_valued list
    assert card("relates-to") is False
    assert card("includes") is False
    # unseen predicate => conservative coexist (never auto-close)
    assert card("some-unseen-predicate") is False


def test_is_single_valued_convenience_and_no_map(tmp_path):
    predicates.install_predicate_map(tmp_path)
    assert predicates.is_single_valued(tmp_path, "works-at") is True
    # with no map at all, default to multi-valued (safe coexist)
    assert predicates.is_single_valued(tmp_path / "nope", "anything") is False


# --------------------------------------------------------------------------- #
# 2. seed_claims_from_edges
# --------------------------------------------------------------------------- #


def test_seed_creates_claims_grouped_by_subject(tmp_path):
    _write_entity(tmp_path, "cicada", "Cicada", created="2026-01-10")
    _write_entity(tmp_path, "rodrigo", "Rodrigo", created="2026-01-10")
    _write_edges(
        tmp_path,
        [
            {"source": "cicada", "target": "sqlite-vec", "label": "uses"},
            {"source": "cicada", "target": "fastapi", "label": "built with"},
            {"source": "rodrigo", "target": "cicada", "label": "works on"},
        ],
    )

    result = seed_claims_from_edges(tmp_path, embed_fn=fake_embed)
    assert result["claims_written"] == 3

    cicada_claims = parse_claims((tmp_path / "entities" / "cicada.md").read_text())
    assert {c.object for c in cicada_claims} == {"sqlite-vec", "fastapi"}
    # predicate normalization applied: "built with" -> uses
    assert {c.predicate for c in cicada_claims} == {"uses"}
    for c in cicada_claims:
        assert c.subject == "cicada"
        assert c.observer == "agent"
        assert c.context == "general"
        assert c.epistemic == "explicit"
        assert c.source_trust == "agent_extracted"
        assert c.object_kind == "node"
        assert c.authored_by == "seed"
        assert c.origin == "seed"
        # valid_from taken from the page's created date
        assert c.valid_from == "2026-01-10"

    rodrigo_claims = parse_claims((tmp_path / "entities" / "rodrigo.md").read_text())
    assert [c.object for c in rodrigo_claims] == ["cicada"]
    assert rodrigo_claims[0].predicate == "works-on"


def test_seed_preserves_existing_prose(tmp_path):
    body = "# Cicada\n\nCicada is a personal memory system.\n\n## facet: engineering\n- Uses sqlite-vec.\n"
    _write_entity(tmp_path, "cicada", "Cicada", body=body)
    _write_edges(tmp_path, [{"source": "cicada", "target": "sqlite-vec", "label": "uses"}])

    seed_claims_from_edges(tmp_path, embed_fn=fake_embed)

    new_body = (tmp_path / "entities" / "cicada.md").read_text()
    assert "# Cicada" in new_body
    assert "Cicada is a personal memory system." in new_body
    assert "## facet: engineering" in new_body
    assert "```claims" in new_body


def test_seed_is_idempotent_no_duplicate_claims(tmp_path):
    _write_entity(tmp_path, "cicada", "Cicada")
    _write_edges(
        tmp_path,
        [
            {"source": "cicada", "target": "sqlite-vec", "label": "uses"},
            {"source": "cicada", "target": "fastapi", "label": "uses"},
        ],
    )

    first = seed_claims_from_edges(tmp_path, embed_fn=fake_embed)
    first_body = (tmp_path / "entities" / "cicada.md").read_text()
    first_ids = [c.id for c in parse_claims(first_body)]

    second = seed_claims_from_edges(tmp_path, embed_fn=fake_embed)
    second_body = (tmp_path / "entities" / "cicada.md").read_text()
    second_ids = [c.id for c in parse_claims(second_body)]

    assert first_ids == second_ids
    assert len(second_ids) == 2  # no duplication
    # first run writes both claims; the idempotent re-run writes nothing new
    assert first["claims_written"] == 2
    assert second["claims_written"] == 0


def test_seed_creates_page_for_subject_without_entity_file(tmp_path):
    """An edge whose subject has no entity page still seeds — a page is created
    so the relational layer is captured (entities/*.md is the home)."""
    (tmp_path / "entities").mkdir(parents=True, exist_ok=True)
    _write_edges(tmp_path, [{"source": "newsubject", "target": "fastapi", "label": "uses"}])

    seed_claims_from_edges(tmp_path, embed_fn=fake_embed, today="2026-06-17")
    page = tmp_path / "entities" / "newsubject.md"
    assert page.exists()
    claims = parse_claims(page.read_text())
    assert len(claims) == 1
    assert claims[0].valid_from == "2026-06-17"  # today fallback


def test_seed_rebuilds_claims_index(tmp_path):
    _write_entity(tmp_path, "cicada", "Cicada")
    _write_edges(
        tmp_path,
        [{"source": "cicada", "target": "python-web-framework-api", "label": "uses"}],
    )
    result = seed_claims_from_edges(tmp_path, embed_fn=fake_embed)
    assert result["indexed"] == 1

    from api.services.vector_index import SqliteVecIndexer

    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed)
    hits = indexer.search_claims("python web framework api", top_k=5)
    assert hits
    assert hits[0]["metadata"]["subject"] == "cicada"


def test_seed_skips_self_loops_and_blank_endpoints(tmp_path):
    _write_entity(tmp_path, "cicada", "Cicada")
    _write_edges(
        tmp_path,
        [
            {"source": "cicada", "target": "cicada", "label": "relates-to"},  # self loop
            {"source": "cicada", "target": "", "label": "uses"},  # blank target
            {"source": "", "target": "fastapi", "label": "uses"},  # blank source
            {"source": "cicada", "target": "fastapi", "label": "uses"},  # the only good one
        ],
    )
    result = seed_claims_from_edges(tmp_path, embed_fn=fake_embed)
    assert result["claims_written"] == 1
    claims = parse_claims((tmp_path / "entities" / "cicada.md").read_text())
    assert [c.object for c in claims] == ["fastapi"]


def test_seed_no_edges_file_is_noop(tmp_path):
    (tmp_path / "entities").mkdir(parents=True, exist_ok=True)
    result = seed_claims_from_edges(tmp_path, embed_fn=fake_embed)
    assert result["claims_written"] == 0
