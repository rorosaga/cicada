"""G141 PJ-0b acceptance (R-HP12): across two real Sleep cycles, what Stage 1
heard about a name with no page is held with its pending entity, and lands on
the page the second conversation's promotion creates — span current, the
first conversation credited, the pending line gone — and every step is a
count on the Sleep state and the `sleep_run` row.

Real: Stage 2 (`entity_resolver.resolve` — no LLM call, since nothing shares a
token), Stage 5's page write, Stage 5.56 and the pending store. Fakes:
extraction, Stage 3's legacy entity pass, Stage 4, git, and the vector index
(the pending-vector rebuild needs an embedder). Synthetic names only."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from api.config import Settings
from api.services import (entity_resolver, evidence, git_service, markdown_parser, pending_store, predicates,
                          sleep_cycle, telemetry)
from api.services.claims import parse_claims

EP_A, TS_A = "ep_2026-09-20_001", "2026-09-20T10:00:00+00:00"
EP_B, TS_B = "ep_2026-09-22_001", "2026-09-22T10:00:00+00:00"
QUOTE = "Zed Unknown recommends Gamma Board"


def _settings(memory: Path) -> SimpleNamespace:
    # `inbox_stale_after_days`: without it 5.56's question refresh raises after
    # the claim write (harmless, but the stage would end in a warning).
    return SimpleNamespace(memory_path=memory, litellm_model="gpt-5.4-mini",
                           litellm_disambiguation_model="gpt-5.4-nano", archive_threshold=0.2,
                           decay_nudge_threshold=0.4, sleep_promotion_threshold=2,
                           link_enrich_enabled=False, inbox_stale_after_days=90)


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    predicates.install_predicate_map(memory)
    return memory


def _episode(memory: Path, ep: str, ts: str, body: str) -> None:
    markdown_parser.write(memory / "episodes" / f"{ep}.md",
                          {"id": ep, "processed": False, "source": "mcp", "timestamp": ts}, body)


def _entity(name: str, kind: str, ep: str, ts: str) -> dict:
    # confidence 0.6: under Stage 2's substantive bar (0.75) and over the
    # clarification threshold (0.5) — the name is parked, not promoted or asked about.
    return {"name": name, "type": kind, "confidence": 0.6, "description": "Mentioned once.",
            "source_episode": ep, "source_episode_timestamp": ts, "tags": [], "history_entries": []}


def _patch(monkeypatch, queue: list[list[dict]]) -> None:
    async def fake_extract(episodes, settings, **_kw):
        return queue.pop(0)

    async def fake_detect(changes, existing, settings, **_kw):
        return []

    async def fake_resolve_and_prune(resolved, existing, settings):
        return list(resolved)

    async def fake_commit(_path, _message):
        return None

    async def fake_porcelain(_path):
        return ""

    class _FakeIndexer:
        def __init__(self, *_a, **_k):
            pass

        def index_entities(self):
            return 0

        def index_episodes(self):
            return 0

        def index_claims(self):
            return 0

    # Stage 2 keeps the REAL indexer class (bound at its import) and so the real
    # pending store; only the pending-vector rebuild, which embeds, is stubbed.
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    monkeypatch.setattr("api.services.entity_extractor.extract", fake_extract)
    monkeypatch.setattr("api.services.skill_extractor.detect_patterns", fake_detect)
    monkeypatch.setattr("api.services.conflict_resolver.resolve_and_prune", fake_resolve_and_prune)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    monkeypatch.setattr(git_service, "porcelain_status", fake_porcelain)
    monkeypatch.setattr("api.services.vector_index.SqliteVecIndexer", _FakeIndexer)


def test_two_conversations_hold_then_write_a_claim_about_a_name_that_had_no_page(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _episode(memory, EP_A, TS_A, "user: Zed Unknown recommends Gamma Board for the lab.\nassistant: Noted.")
    span = evidence.verify(None, EP_A, QUOTE, text=evidence.source_text(memory, EP_A))
    assert span.is_span()
    first = [{"episode_id": EP_A, "episode_timestamp": TS_A, "origin": "claude-code",
              "entities": [_entity("Zed Unknown", "person", EP_A, TS_A), _entity("Gamma Board", "tool", EP_A, TS_A)],
              "relationships": [{"source": "Zed Unknown", "target": "Gamma Board", "label": "recommends",
                                 "source_episode": EP_A, "source_episode_timestamp": TS_A,
                                 "evidence": [span.to_dict()]}]}]
    second = [{"episode_id": EP_B, "episode_timestamp": TS_B, "origin": "claude-code",
               "entities": [_entity("Zed Unknown", "person", EP_B, TS_B)], "relationships": []}]
    _patch(monkeypatch, [first, second])

    # Conversation 1: both names are parked; the claim waits with "Zed Unknown".
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="pj0b_1"))
    state = sleep_cycle.get_sleep_state()
    assert (state.claims_held, state.claims_page_less, state.claims_released, state.claims_waiting) == (1, 0, 0, 1)
    assert list((memory / "entities").glob("*.md")) == []
    (line,) = [e for e in pending_store.load(memory) if e.held_claims]
    assert line.name == "Zed Unknown" and line.held_claims[0]["evidence"] == [span.to_dict()]

    # Conversation 2 names it again: Stage 2 promotes it, Stage 5 writes the
    # page, Stage 5.56 releases the held claim onto it.
    _episode(memory, EP_B, TS_B, "user: I met Zed Unknown again today.\nassistant: Good.")
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="pj0b_2"))
    state = sleep_cycle.get_sleep_state()
    assert (state.claims_held, state.claims_released, state.claims_waiting) == (0, 1, 0)

    page = markdown_parser.parse(memory / "entities" / "zed-unknown.md")
    (claim,) = parse_claims(page.body)
    assert (claim.subject, claim.predicate, claim.object) == ("zed-unknown", "recommends", "gamma-board")
    assert (claim.observer, claim.source_trust, claim.valid_from, claim.valid_to) == (
        "agent", "agent_extracted", "2026-09-20", None)
    (ev,) = claim.evidence
    assert ev == span
    text = evidence.source_text(memory, EP_A)
    assert text[ev.start:ev.end] == QUOTE
    assert evidence.span_status(text, end=ev.end, hash=ev.hash) == evidence.SPAN_CURRENT
    assert page.frontmatter["source_episodes"] == [EP_B, EP_A]
    assert [e.name for e in pending_store.load(memory)] == ["Gamma Board"]


def test_the_sleep_run_row_carries_the_hold_counts(tmp_path, monkeypatch):
    events: list = []

    async def fake_status(_path):
        return ""

    async def fake_commit(_path, _message):
        return "abc1234"

    monkeypatch.setattr(git_service, "porcelain_status", fake_status)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    monkeypatch.setattr(telemetry, "record", events.append)
    for key, value in (("claims_held", 4), ("claims_released", 3), ("claims_hold_capped", 2),
                       ("claims_waiting", 7)):
        monkeypatch.setattr(sleep_cycle._state, key, value)
    asyncio.run(sleep_cycle._finalize(
        tmp_path, "sleep_1", [], Settings(llm_mode="agent"),
        engine="claude-cli", connection="claude-plan", billing="subscription", authors=["claude-sonnet-5"],
    ))
    (row,) = [e for e in events if e.kind == "sleep_run"]
    assert {k: row.refs[k] for k in ("claims_held", "claims_released", "claims_hold_capped", "claims_waiting")} == {
        "claims_held": 4, "claims_released": 3, "claims_hold_capped": 2, "claims_waiting": 7}
