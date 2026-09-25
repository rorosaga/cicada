"""G118 slice 1 — Stage-1 extraction cites the passage; the pipeline verifies.

Hermetic: `litellm.acompletion` is monkeypatched (the pattern from
test_extractor_robustness.py). The fake model returns `evidence_quote` values
that are exact, whitespace-mangled, absent, and fabricated, over a two-turn
synthetic episode, and the assertions are on offsets into the stored body.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from api.config import Settings
from api.services import entity_extractor as ex
from api.services import evidence
from api.services.claim_reconciler import _reinforce
from api.services.claims import Claim, Evidence

BODY = (
    "user: We moved alpha-project onto sqlite-vec in August.\n"
    "assistant: Understood. alpha-project depends on EmbeddingGemma for its vectors.\n"
    "user: And bob-example reviews every migration."
)


def _resp(payload: dict):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])


def _fake(payload: dict):
    async def fake_acompletion(**kw):
        return _resp(payload)
    return fake_acompletion


def _extract(monkeypatch, payload: dict, body: str = BODY) -> dict:
    monkeypatch.setattr(ex.litellm, "acompletion", _fake(payload))
    out = asyncio.run(ex.extract(
        [{"id": "ep_2026-09-01_001", "content": body, "timestamp": "2026-09-01T10:00:00+00:00", "origin": "claude-code"}],
        Settings(litellm_model="m"),
    ))
    assert len(out) == 1
    return out[0]


def test_prompt_asks_for_a_verbatim_evidence_quote_on_every_relationship():
    prompt = ex.EXTRACTION_SYSTEM_PROMPT
    assert '"evidence_quote"' in prompt
    assert "verbatim" in prompt.lower()
    assert "240" in prompt


def test_exact_quote_becomes_a_user_span_into_the_stored_body(monkeypatch):
    res = _extract(monkeypatch, {"entities": [], "relationships": [
        {"source": "alpha-project", "target": "sqlite-vec", "label": "uses",
         "evidence_quote": "moved alpha-project onto sqlite-vec"}]})
    (rel,) = res["relationships"]
    assert "evidence_quote" not in rel
    (ev,) = rel["evidence"]
    assert ev["episode"] == "ep_2026-09-01_001" and ev["kind"] == "user"
    assert BODY[ev["start"]:ev["end"]] == "moved alpha-project onto sqlite-vec"
    assert ev["hash"] == evidence.body_hash(BODY)


def test_assistant_turn_quote_is_labelled_assistant_and_normalised_whitespace_still_locates(monkeypatch):
    res = _extract(monkeypatch, {"entities": [], "relationships": [
        {"source": "alpha-project", "target": "EmbeddingGemma", "label": "depends on",
         "evidence_quote": "alpha-project   depends on\nEmbeddingGemma"}]})
    (ev,) = res["relationships"][0]["evidence"]
    assert ev["kind"] == "assistant"
    assert BODY[ev["start"]:ev["end"]] == "alpha-project depends on EmbeddingGemma"


def test_missing_or_fabricated_quote_records_reasoning_never_a_faked_span(monkeypatch):
    res = _extract(monkeypatch, {"entities": [], "relationships": [
        {"source": "bob-example", "target": "alpha-project", "label": "reviews"},
        {"source": "bob-example", "target": "sqlite-vec", "label": "prefers",
         "evidence_quote": "bob-example prefers sqlite-vec over everything"}]})
    kinds = [r["evidence"][0]["kind"] for r in res["relationships"]]
    assert kinds == ["reasoning", "reasoning"]
    for r in res["relationships"]:
        assert r["evidence"][0]["start"] == -1 and r["evidence"][0]["end"] == -1
        assert r["evidence"][0]["hash"] == evidence.body_hash(BODY)  # doc known -> hash kept


def test_chunked_episode_offsets_are_into_the_whole_body_not_the_chunk(monkeypatch):
    # Two chunks: the quote sits deep in chunk 2 (and also, as bait, at the very top).
    filler = ("user: filler line about nothing in particular.\n" * 400)
    body = "user: alpha-project uses sqlite-vec.\n" + filler + "assistant: Yes, alpha-project uses sqlite-vec."
    spans = ex._chunk_spans(body)
    assert len(spans) >= 2 and [body[s:e] for s, e in spans] == ex._chunk_content(body)
    calls = {"n": 0}

    async def fake(**kw):
        calls["n"] += 1
        chunk = kw["messages"][-1]["content"]
        if chunk.startswith("user: alpha-project"):
            return _resp({"entities": [], "relationships": []})
        return _resp({"entities": [], "relationships": [
            {"source": "alpha-project", "target": "sqlite-vec", "label": "uses",
             "evidence_quote": "alpha-project uses sqlite-vec"}]})

    monkeypatch.setattr(ex.litellm, "acompletion", fake)
    out = asyncio.run(ex.extract(
        [{"id": "ep_2026-09-01_002", "content": body, "timestamp": "t", "origin": "x"}], Settings(litellm_model="m")))
    rels = out[0]["relationships"]
    assert calls["n"] == len(spans) and len(rels) == len(spans) - 1
    (ev,) = rels[-1]["evidence"]
    # The window preferred the occurrence inside the LAST chunk, not the bait at offset 6.
    assert ev["start"] > spans[-1][0] and ev["kind"] == "assistant"
    assert body[ev["start"]:ev["end"]] == "alpha-project uses sqlite-vec"


def test_entities_to_claims_carries_evidence_and_merges_duplicate_ids():
    ev_a = {"episode": "ep_2026-09-01_001", "start": 9, "end": 44, "kind": "user", "hash": "h"}
    ev_b = {"episode": "ep_2026-09-01_001", "start": 80, "end": 100, "kind": "assistant", "hash": "h"}
    extracted = [{"episode_id": "ep_2026-09-01_001", "origin": "claude-code", "entities": [], "relationships": [
        {"source": "alpha-project", "target": "sqlite-vec", "label": "uses", "source_episode": "ep_2026-09-01_001",
         "source_episode_timestamp": "2026-09-01T10:00:00+00:00", "evidence": [ev_a]},
        {"source": "alpha-project", "target": "sqlite-vec", "label": "uses", "source_episode": "ep_2026-09-01_001",
         "source_episode_timestamp": "2026-09-01T10:00:00+00:00", "evidence": [ev_b]},
        {"source": "alpha-project", "target": "sqlite-vec", "label": "uses", "source_episode": "ep_2026-09-01_001",
         "source_episode_timestamp": "2026-09-01T10:00:00+00:00", "evidence": [ev_a]},
    ]}]
    (c,) = ex.entities_to_claims(extracted, memory_path=None)
    assert c.evidence == [Evidence.from_dict(ev_a), Evidence.from_dict(ev_b)]


def test_entities_to_claims_without_evidence_key_stays_legacy_shaped():
    extracted = [{"episode_id": "ep_2026-09-01_001", "origin": "claude-code", "entities": [], "relationships": [
        {"source": "alpha-project", "target": "sqlite-vec", "label": "uses", "source_episode": "ep_2026-09-01_001"}]}]
    (c,) = ex.entities_to_claims(extracted, memory_path=None)
    assert c.evidence == []


def test_reinforce_merges_spans_and_drops_a_redundant_reasoning_entry():
    span = Evidence(episode="ep_a", start=1, end=9, kind="user", hash="h1")
    existing = Claim(id="c1", text="t", subject="s", predicate="p", object="o", evidence=[span])
    incoming = Claim(id="c2", text="t", subject="s", predicate="p", object="o", evidence=[
        span,                                                              # duplicate -> once
        Evidence(episode="ep_a", start=-1, end=-1, kind="reasoning", hash="h1"),  # same doc, no span -> dropped
        Evidence(episode="ep_b", start=4, end=12, kind="assistant", hash="h2"),   # new span -> kept
        Evidence(episode="ep_c", start=-1, end=-1, kind="reasoning", hash=""),    # new doc reasoning -> kept
    ])
    _reinforce(existing, incoming)
    assert existing.evidence == [
        span,
        Evidence(episode="ep_b", start=4, end=12, kind="assistant", hash="h2"),
        Evidence(episode="ep_c", start=-1, end=-1, kind="reasoning", hash=""),
    ]
