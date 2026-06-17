"""M5f acceptance: the claim layer is LOAD-BEARING in the live ``sleep_cycle.run``.

This drives the *real* 5-stage ``sleep_cycle.run`` with the LLM/embedding/git
boundaries replaced by fakes (no network, no real model, no real git), and proves
end-to-end:

* the entity path still creates the entity page (baseline unaffected — additive);
* Stage 5.56 wrote a ```claims block onto that page from the extracted relations;
* the trust invariant holds IN THE WIRED CYCLE — an agent extraction does not
  close a pre-existing human ``user_stated`` + clarification claim on the page;
* Stage 5.7 projected the valid claim into a merged graph edge.

Hermetic: ``extract`` / ``resolve`` / ``detect_patterns`` are stubbed with the
exact shapes the cycle consumes; git commit + the vector indexer are no-ops.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import yaml

from api.services import git_service, markdown_parser, predicates, sleep_cycle
from api.services.claims import Claim, parse_claims, write_claims


def _seed_bank(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    # One unprocessed episode so the cycle does not early-return.
    markdown_parser.write(
        memory / "episodes" / "ep_2026-06-17_001.md",
        {"id": "ep_2026-06-17_001", "processed": False, "source": "mcp",
         "timestamp": "2026-06-17T10:00:00"},
        "Cicada uses sqlite-vec for retrieval.",
    )
    return memory


def _patch_boundaries(monkeypatch, memory, *, extracted, resolved_changes, resolved_edges):
    async def fake_extract(episodes, settings):
        return extracted

    async def fake_resolve(extracted_arg, existing, settings):
        return {"changes": resolved_changes, "relationships": resolved_edges,
                "episode_cooccurrences": {}}

    async def fake_detect(changes, existing, settings, **kw):
        return []

    async def fake_resolve_and_prune(resolved, existing, settings):
        return list(resolved)

    async def fake_commit(memory_path, message):
        return None

    async def fake_porcelain(memory_path):
        return ""

    # Stub the vector indexer entirely (no embeddings).
    class _FakeIndexer:
        def __init__(self, *_a, **_k):
            pass

        def index_entities(self):
            return 0

        def index_episodes(self):
            return 0

        def index_claims(self):
            return 0

    monkeypatch.setattr("api.services.entity_extractor.extract", fake_extract)
    monkeypatch.setattr("api.services.entity_resolver.resolve", fake_resolve)
    monkeypatch.setattr("api.services.skill_extractor.detect_patterns", fake_detect)
    monkeypatch.setattr(
        "api.services.conflict_resolver.resolve_and_prune", fake_resolve_and_prune
    )
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    monkeypatch.setattr(git_service, "porcelain_status", fake_porcelain)
    monkeypatch.setattr("api.services.vector_index.SqliteVecIndexer", _FakeIndexer)


def _settings(memory):
    return SimpleNamespace(
        memory_path=memory,
        litellm_model="gpt-5.4-mini",
        litellm_disambiguation_model="gpt-5.4-nano",
        archive_threshold=0.2,
        decay_nudge_threshold=0.4,
        link_enrich_enabled=False,  # offline: no network in the wired test
    )


def test_live_cycle_writes_claims_and_keeps_entity_path(tmp_path, monkeypatch):
    memory = _seed_bank(tmp_path)
    extracted = [{
        "episode_id": "ep_2026-06-17_001",
        "episode_timestamp": "2026-06-17T10:00:00",
        "origin": "claude-code",
        "entities": [{"name": "Cicada", "type": "project", "source_episode": "ep_2026-06-17_001"}],
        "relationships": [{
            "source": "Cicada", "target": "sqlite-vec", "label": "uses",
            "source_episode": "ep_2026-06-17_001",
            "source_episode_timestamp": "2026-06-17T10:00:00",
        }],
    }]
    # The entity path CREATES the cicada page (baseline behavior).
    resolved_changes = [{
        "id": "cicada", "action": "create", "source_episode": "ep_2026-06-17_001",
        "source_episodes": ["ep_2026-06-17_001"], "trigger": "sleep/extraction",
        "entity": {"name": "Cicada", "type": "project", "confidence": 0.8,
                   "key_facts": ["Built on sqlite-vec."]},
    }]
    resolved_edges = [{"source": "cicada", "target": "sqlite-vec", "label": "uses"}]
    _patch_boundaries(monkeypatch, memory, extracted=extracted,
                      resolved_changes=resolved_changes, resolved_edges=resolved_edges)

    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="2026-06-17_test"))

    # Baseline: the entity page exists with the extracted prose (entity path ran).
    page = memory / "entities" / "cicada.md"
    assert page.exists()
    parsed = markdown_parser.parse(page)
    assert "Built on sqlite-vec." in parsed.body

    # M5f: a ```claims block was written by Stage 5.56.
    claims = parse_claims(parsed.body)
    assert any(c.predicate == "uses" and c.object == "sqlite-vec" for c in claims)

    # Stage 5.7 projected the valid claim into a graph edge.
    edges = yaml.safe_load((memory / "graph_edges.yaml").read_text())["edges"]
    assert any(
        e.get("source") == "cicada" and e.get("target") == "sqlite-vec" and e.get("claim_id")
        for e in edges
    )


def test_live_cycle_trust_invariant_agent_cannot_close_human(tmp_path, monkeypatch):
    memory = _seed_bank(tmp_path)
    # Pre-seed an EXISTING human claim on rodrigo's page (single-valued works-at).
    human = Claim(
        id="clm_human_employer", text="Rodrigo works at acme", subject="rodrigo",
        predicate="works-at", object="acme", observer="agent", context="general",
        source_trust="user_stated", origin="clarification", valid_from="2026-06-01",
        confidence=0.95,
    )
    markdown_parser.write(
        memory / "entities" / "rodrigo.md",
        {"name": "Rodrigo", "type": "person", "human_edited": True},
        write_claims("## Summary\nThe user.", [human]),
    )

    extracted = [{
        "episode_id": "ep_2026-06-17_001",
        "episode_timestamp": "2026-06-17T10:00:00",
        "origin": "claude-code",
        "entities": [],
        "relationships": [{
            "source": "Rodrigo", "target": "globex", "label": "works at",
            "source_episode": "ep_2026-06-17_001",
            "source_episode_timestamp": "2026-06-17T10:00:00",
        }],
    }]
    # rodrigo already exists; the cycle resolves it as an update (no new prose).
    resolved_changes = [{
        "id": "rodrigo", "action": "update", "source_episode": "ep_2026-06-17_001",
        "source_episodes": ["ep_2026-06-17_001"], "trigger": "sleep/extraction",
        "entity": {"name": "Rodrigo", "type": "person"},
    }]
    _patch_boundaries(monkeypatch, memory, extracted=extracted,
                      resolved_changes=resolved_changes, resolved_edges=[])

    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="2026-06-17_test2"))

    parsed = markdown_parser.parse(memory / "entities" / "rodrigo.md")
    by_id = {c.id: c for c in parse_claims(parsed.body)}
    # The human claim is STILL OPEN — the wired agent extraction never closed it.
    assert by_id["clm_human_employer"].valid_to is None
    assert by_id["clm_human_employer"].superseded_by is None
    # And a divergence nudge landed in the inbox (soft, not a silent overwrite).
    inbox = list((memory / "inbox").glob("inbox-*.md"))
    kinds = {markdown_parser.parse(f).frontmatter.get("kind") for f in inbox}
    assert "divergence" in kinds
