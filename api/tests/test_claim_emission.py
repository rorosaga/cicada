"""Tests for M5e Stage-1 claim emission + origin propagation.

``entity_extractor.entities_to_claims`` turns the existing entity/relationship
extraction shape (the back-compatible default) into perspectival :class:`Claim`
objects with ``observer=agent, context=general, epistemic=explicit,
source_trust=agent_extracted`` and ``origin`` propagated from the episode (per
``docs/goals/m5-prep/origin-and-harness-sync.md``). No LLM call — the conversion
is deterministic over the already-extracted dicts.
"""

from __future__ import annotations

from api.services.entity_extractor import entities_to_claims


def test_relationship_becomes_claim_with_perspective_defaults():
    extracted = [
        {
            "episode_id": "ep_2026-04-16_001",
            "origin": "claude-code",
            "entities": [
                {"name": "Rodrigo", "type": "person", "source_episode": "ep_2026-04-16_001"},
                {"name": "Acme", "type": "company", "source_episode": "ep_2026-04-16_001"},
            ],
            "relationships": [
                {
                    "source": "Rodrigo",
                    "target": "Acme",
                    "label": "works at",
                    "source_episode": "ep_2026-04-16_001",
                    "source_episode_timestamp": "2026-04-16T10:00:00Z",
                }
            ],
        }
    ]
    claims = entities_to_claims(extracted, memory_path=None)
    rel_claims = [c for c in claims if c.object]
    assert rel_claims, "a relationship should produce a claim"
    c = rel_claims[0]
    assert c.subject == "rodrigo"
    assert c.object == "acme"
    # predicate normalized ("works at" -> works-at) when a map is available;
    # with memory_path=None it slugifies to works-at deterministically.
    assert c.predicate == "works-at"
    assert c.observer == "agent"
    assert c.context == "general"
    assert c.epistemic == "explicit"
    assert c.source_trust == "agent_extracted"
    assert c.origin == "claude-code"
    assert c.source_episodes == ["ep_2026-04-16_001"]
    assert c.valid_from == "2026-04-16"


def test_origin_defaults_to_unknown_when_absent():
    extracted = [
        {
            "episode_id": "ep_x",
            "entities": [],
            "relationships": [
                {"source": "A", "target": "B", "label": "uses", "source_episode": "ep_x"}
            ],
        }
    ]
    claims = entities_to_claims(extracted, memory_path=None)
    assert claims[0].origin == "unknown"


def test_predicate_raw_is_carried_for_audit():
    extracted = [
        {
            "episode_id": "ep_x",
            "origin": "claude-code",
            "entities": [],
            "relationships": [
                {"source": "Cicada", "target": "FastAPI", "label": "built with",
                 "source_episode": "ep_x"}
            ],
        }
    ]
    claims = entities_to_claims(extracted, memory_path=None)
    c = claims[0]
    # built-with slugifies to built-with with no map; the raw label is carried so
    # Stage 3 can emit the normalization-audit nudge if it folded.
    assert getattr(c, "predicate_raw", None) == "built with"


def test_claim_id_is_deterministic():
    extracted = [
        {
            "episode_id": "ep_2026-04-16_001",
            "origin": "claude-code",
            "entities": [],
            "relationships": [
                {"source": "Rodrigo", "target": "Acme", "label": "works at",
                 "source_episode": "ep_2026-04-16_001",
                 "source_episode_timestamp": "2026-04-16T10:00:00Z"}
            ],
        }
    ]
    a = entities_to_claims(extracted, memory_path=None)
    b = entities_to_claims(extracted, memory_path=None)
    assert [c.id for c in a] == [c.id for c in b]
    assert a[0].id.startswith("clm_")
