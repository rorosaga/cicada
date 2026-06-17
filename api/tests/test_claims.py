"""Tests for the M5a in-page claims foundation.

Three concerns, all hermetic (no real models, no network):

1. ``Claim`` schema — sensible defaults, ``to_dict``/``from_dict`` round-trip.
2. The in-page ` ```claims ` fenced block parser/writer in ``markdown_parser``:
   round-trip preserving surrounding prose verbatim, legacy pages (no fence)
   yielding ``[]``, malformed fences degrading gracefully to ``[]``.
3. The derived ``claims`` vector-index kind (``index_claims``/``search_claims``)
   over tmp entity pages, with an injected deterministic ``embed_fn``:
   valid-only filtering, observer/context post-filter, superseded excluded.
"""

from __future__ import annotations

import numpy as np

from api.services import markdown_parser
from api.services.claims import Claim, parse_claims, write_claims
from api.services.vector_index import SqliteVecIndexer

# Reuse the bag-of-words fake from the vector-index tests so claim texts that
# share words land close together under cosine geometry.
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


# --------------------------------------------------------------------------- #
# 1. Claim schema
# --------------------------------------------------------------------------- #


def test_minimal_claim_is_valid_with_defaults():
    c = Claim(id="clm_2026-06-17_001", text="Cicada uses sqlite-vec.")
    assert c.id == "clm_2026-06-17_001"
    assert c.text == "Cicada uses sqlite-vec."
    # sensible defaults for the perspective/trust axes
    assert c.observer == "agent"
    assert c.context == "general"
    assert c.epistemic == "explicit"
    assert c.source_trust == "agent_extracted"
    assert c.object_kind == "node"
    assert c.valid_to is None  # currently valid
    assert c.superseded_by is None
    assert c.supersedes is None
    assert c.source_episodes == []
    assert c.premises == []
    assert 0.0 <= c.confidence <= 1.0


def test_claim_to_dict_from_dict_roundtrip():
    c = Claim(
        id="clm_2026-06-17_002",
        text="Cicada's index is built on sqlite-vec.",
        subject="cicada",
        predicate="uses",
        object="sqlite-vec",
        observer="rodrigo",
        context="engineering",
        epistemic="explicit",
        source_trust="user_stated",
        confidence=0.95,
        valid_from="2026-05-05",
        valid_to=None,
        supersedes="clm_2026-01-15_002",
        recorded_at="2026-05-05",
        source_episodes=["ep_2026-05-05_003"],
        premises=[],
        authored_by="gpt-5.4-mini",
        origin="claude-code",
    )
    d = c.to_dict()
    assert d["subject"] == "cicada"
    assert d["origin"] == "claude-code"
    back = Claim.from_dict(d)
    assert back == c


def test_claim_from_dict_tolerates_missing_fields():
    """A sparse YAML record still produces a usable Claim with defaults."""
    c = Claim.from_dict({"id": "clm_x", "text": "something"})
    assert c.id == "clm_x"
    assert c.observer == "agent"
    assert c.source_episodes == []


# --------------------------------------------------------------------------- #
# 2. In-page ```claims block parse/write
# --------------------------------------------------------------------------- #

_PROSE_BEFORE = """# Cicada

Cicada is a personal agent-memory system.

## facet: engineering
- Uses **sqlite-vec** for its semantic index.
"""

_PROSE_AFTER = """
## Related
![[rodrigo#engineering]]
"""


def test_legacy_page_without_fence_yields_no_claims():
    body = _PROSE_BEFORE + _PROSE_AFTER
    assert parse_claims(body) == []


def test_write_then_parse_claims_roundtrip():
    body = _PROSE_BEFORE + _PROSE_AFTER
    claims = [
        Claim(
            id="clm_a",
            text="Cicada uses sqlite-vec.",
            subject="cicada",
            predicate="uses",
            object="sqlite-vec",
            context="engineering",
            confidence=0.95,
            valid_from="2026-05-05",
        ),
        Claim(
            id="clm_b",
            text="Cicada is a python web framework adjacent project.",
            subject="cicada",
            predicate="relates-to",
            object="fastapi",
            context="engineering",
            confidence=0.7,
        ),
    ]
    new_body = write_claims(body, claims)
    parsed = parse_claims(new_body)
    assert parsed == claims


def test_write_claims_preserves_surrounding_prose_verbatim():
    body = _PROSE_BEFORE + _PROSE_AFTER
    claims = [Claim(id="clm_a", text="Cicada uses sqlite-vec.")]
    new_body = write_claims(body, claims)
    # every line of the original prose must still be present, untouched
    assert "# Cicada" in new_body
    assert "Cicada is a personal agent-memory system." in new_body
    assert "## facet: engineering" in new_body
    assert "- Uses **sqlite-vec** for its semantic index." in new_body
    assert "## Related" in new_body
    assert "![[rodrigo#engineering]]" in new_body


def test_write_claims_replaces_existing_block_not_duplicates():
    body = _PROSE_BEFORE + _PROSE_AFTER
    first = write_claims(body, [Claim(id="clm_a", text="first")])
    second = write_claims(first, [Claim(id="clm_b", text="second")])
    # exactly one claims fence
    assert second.count("```claims") == 1
    parsed = parse_claims(second)
    assert [c.id for c in parsed] == ["clm_b"]
    # prose still intact
    assert "## facet: engineering" in second


def test_empty_claims_list_writes_empty_block_and_parses_back():
    body = _PROSE_BEFORE
    new_body = write_claims(body, [])
    assert parse_claims(new_body) == []
    assert "# Cicada" in new_body


def test_malformed_claims_block_degrades_to_empty():
    body = (
        _PROSE_BEFORE
        + "\n```claims\n"
        + "this: is: not: valid: yaml: [unterminated\n"
        + "```\n"
        + _PROSE_AFTER
    )
    # tolerant: warn + [] rather than raise
    assert parse_claims(body) == []


def test_claims_block_with_non_list_yaml_degrades_to_empty():
    body = _PROSE_BEFORE + "\n```claims\nsubject: cicada\n```\n"
    assert parse_claims(body) == []


def test_crlf_page_round_trips_claims():
    """A page saved with CRLF line endings (Windows / git autocrlf, or a
    cross-harness sync per the D2 ADDENDUM) must still parse its claims block
    and round-trip — the closing fence sits on a `\\r\\n` line."""
    claims = [
        Claim(id="clm_a", text="Cicada uses sqlite-vec.", subject="cicada"),
        Claim(id="clm_b", text="Cicada relates to fastapi.", subject="cicada"),
    ]
    lf_body = write_claims(_PROSE_BEFORE + _PROSE_AFTER, claims)
    crlf_body = lf_body.replace("\n", "\r\n")
    assert parse_claims(crlf_body) == claims
    # prose survives too
    assert "## facet: engineering" in crlf_body


def test_write_claims_collapses_multiple_existing_fences_to_one():
    """A hand-edited / double-appended page with two ```claims fences must end
    with exactly one fence after a write — no stale orphan block left behind
    (which would be dead weight and is never the source of truth)."""
    body = (
        _PROSE_BEFORE
        + "\n```claims\n- id: clm_old1\n  text: old one\n```\n"
        + "\nmiddle prose\n"
        + "\n```claims\n- id: clm_old2\n  text: old two\n```\n"
        + _PROSE_AFTER
    )
    assert body.count("```claims") == 2  # precondition
    new_body = write_claims(body, [Claim(id="clm_new", text="new")])
    assert new_body.count("```claims") == 1
    parsed = parse_claims(new_body)
    assert [c.id for c in parsed] == ["clm_new"]
    # surrounding prose is preserved
    assert "## facet: engineering" in new_body
    assert "middle prose" in new_body


# --------------------------------------------------------------------------- #
# 3. Derived `claims` index kind
# --------------------------------------------------------------------------- #


def _write_page_with_claims(entities_dir, stem, name, claims, body_prose="A page."):
    body = write_claims(body_prose, claims)
    markdown_parser.write(
        entities_dir / f"{stem}.md",
        {"name": name, "type": "concept", "status": "active"},
        body,
    )


def test_index_claims_indexes_only_valid_claims(tmp_path):
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _write_page_with_claims(
        entities_dir,
        "cicada",
        "Cicada",
        [
            Claim(
                id="clm_valid",
                text="Cicada uses a python web framework api.",
                subject="cicada",
                predicate="uses",
                object="fastapi",
                context="engineering",
                valid_to=None,
            ),
            Claim(
                id="clm_closed",
                text="Cicada used an old database approach.",
                subject="cicada",
                predicate="uses",
                object="postgres",
                context="engineering",
                valid_from="2026-01-15",
                valid_to="2026-05-05",  # closed -> excluded
                superseded_by="clm_valid",
            ),
        ],
    )

    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed)
    count = indexer.index_claims()
    assert count == 1  # only the currently-valid claim

    hits = indexer.search_claims("python web framework api", top_k=5)
    ids = {h["metadata"]["claim_id"] for h in hits}
    assert ids == {"clm_valid"}
    top = hits[0]["metadata"]
    assert top["subject"] == "cicada"
    assert top["context"] == "engineering"
    assert top["observer"] == "agent"


def test_search_claims_missing_index_returns_empty(tmp_path):
    (tmp_path / "entities").mkdir()
    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed)
    assert indexer.search_claims("anything", top_k=5) == []


def test_index_claims_no_entities_dir_returns_zero(tmp_path):
    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed)
    assert indexer.index_claims() == 0


def test_search_claims_missing_table_returns_empty(tmp_path):
    """db exists (another kind was indexed) but the `claims` table was never
    built — search must degrade to [] via the OperationalError guard, not the
    missing-db guard."""
    episodes_dir = tmp_path / "episodes"
    episodes_dir.mkdir()
    markdown_parser.write(
        episodes_dir / "ep_2026-06-17_001.md",
        {"id": "ep_2026-06-17_001", "timestamp": "2026-06-17T00:00:00"},
        "A python web framework conversation.",
    )
    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed)
    indexer.index_episodes()  # creates the db, but no `claims` table
    assert indexer.db_path.exists()
    assert indexer.search_claims("python web framework", top_k=5) == []


def test_search_claims_observer_and_context_postfilter(tmp_path):
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _write_page_with_claims(
        entities_dir,
        "rodrigo",
        "Rodrigo",
        [
            Claim(
                id="clm_eng",
                text="In engineering Rodrigo values python web framework speed.",
                subject="rodrigo",
                predicate="values",
                object="speed",
                observer="agent",
                context="engineering",
            ),
            Claim(
                id="clm_fam",
                text="With family Rodrigo values python web framework presence.",
                subject="rodrigo",
                predicate="values",
                object="presence",
                observer="rodrigo",
                context="family",
            ),
        ],
    )
    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed)
    assert indexer.index_claims() == 2

    # no filter: both come back
    both = indexer.search_claims("python web framework", top_k=5)
    assert {h["metadata"]["claim_id"] for h in both} == {"clm_eng", "clm_fam"}

    # context post-filter
    eng = indexer.search_claims("python web framework", top_k=5, context="engineering")
    assert {h["metadata"]["claim_id"] for h in eng} == {"clm_eng"}

    # observer post-filter
    fam = indexer.search_claims("python web framework", top_k=5, observer="rodrigo")
    assert {h["metadata"]["claim_id"] for h in fam} == {"clm_fam"}


def test_search_claims_excludes_superseded_by_default(tmp_path):
    """A still-`valid_to=None` claim flagged with a superseded marker is hidden
    by default but surfaced with include_superseded=True."""
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _write_page_with_claims(
        entities_dir,
        "cicada",
        "Cicada",
        [
            Claim(
                id="clm_live",
                text="Cicada uses a python web framework api today.",
                subject="cicada",
                context="engineering",
            ),
            Claim(
                id="clm_super",
                text="Cicada uses a python web framework api variant.",
                subject="cicada",
                context="engineering",
                superseded_by="clm_live",  # superseded marker, still valid_to None
            ),
        ],
    )
    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed)
    indexer.index_claims()

    default_hits = indexer.search_claims("python web framework api", top_k=5)
    assert {h["metadata"]["claim_id"] for h in default_hits} == {"clm_live"}

    all_hits = indexer.search_claims(
        "python web framework api", top_k=5, include_superseded=True
    )
    assert "clm_super" in {h["metadata"]["claim_id"] for h in all_hits}


def test_index_claims_records_model_and_dim(tmp_path):
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _write_page_with_claims(
        entities_dir,
        "cicada",
        "Cicada",
        [Claim(id="clm_a", text="python web framework api claim.", subject="cicada")],
    )
    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed, model_name="fake-test-v1")
    indexer.index_claims()
    info = indexer.index_info()
    assert info["model"] == "fake-test-v1"
    assert info["dim"] == len(_VOCAB)
