"""G118 slice 2 / G93's output half — `/ask` citations carry their spans.

A claim-first hit already knew its `claim_id`; the router dropped it and no
span ever reached the wire. The spans are read from the page `_load_entity`
already holds (R-PB12), never from the claims index. The LLM is injected;
nothing here reaches a model.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.models.schemas import AskCitation
from api.services import ask_service, evidence, markdown_parser
from api.services.claims import Claim, Evidence, write_claims

EP = "ep_2026-09-01_001"
BODY = "user: I moved alpha-project onto sqlite-vec last week."
QUOTE = "moved alpha-project onto sqlite-vec"


def _bank(memory: Path) -> Evidence:
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    markdown_parser.write(memory / "episodes" / f"{EP}.md", {"id": EP}, BODY)
    s = BODY.index(QUOTE)
    ev = Evidence(episode=EP, start=s, end=s + len(QUOTE), kind="user", hash=evidence.body_hash(BODY))
    claim = Claim(id="clm_1", text="alpha-project uses sqlite-vec", subject="alpha-project",
                  source_episodes=[EP], evidence=[ev])
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "Alpha Project", "type": "project", "source_episodes": [EP]},
                          write_claims("# Alpha Project\nA project.", [claim]))
    return ev


def _llm(prompt: str) -> str:
    return json.dumps({"answer": "It uses sqlite-vec.", "confidence": 0.8,
                       "used_entities": ["alpha-project"], "gaps": []})


def test_a_claim_first_citation_carries_its_claim_id_and_spans(tmp_path):
    ev = _bank(tmp_path)
    hit = {"score": 0.9, "text": "alpha-project uses sqlite-vec",
           "metadata": {"entity_id": "alpha-project", "entity_name": "Alpha Project",
                        "claim_id": "clm_1", "observer": "agent"}}
    result = ask_service.answer_query(tmp_path, "what index", retrieve_fn=lambda q, k: [hit], llm_fn=_llm)
    [c] = result["citations"]
    assert c["claim_id"] == "clm_1" and c["evidence"] == [ev.to_dict()]
    assert c["source_episodes"] == [EP]
    assert AskCitation(**c).evidence[0].start == ev.start


def test_an_entity_only_citation_has_no_claim_and_no_spans(tmp_path):
    _bank(tmp_path)
    hit = {"score": 0.9, "text": "", "metadata": {"entity_id": "alpha-project", "entity_name": "Alpha Project"}}
    result = ask_service.answer_query(tmp_path, "what index", retrieve_fn=lambda q, k: [hit], llm_fn=_llm)
    [c] = result["citations"]
    assert "claim_id" not in c and "evidence" not in c
    wire = AskCitation(**c)
    assert wire.claim_id is None and wire.evidence == []


@pytest.fixture
def client_bank(tmp_path: Path, monkeypatch):
    memory = tmp_path / "memory"
    ev = _bank(memory)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    yield ev
    config.get_settings.cache_clear()


def test_the_wire_carries_claim_id_and_evidence(client_bank, monkeypatch):
    ev = client_bank
    monkeypatch.setattr(ask_service, "answer_query", lambda memory_path, query, top_k=6, **_kw: {
        "answer": "It uses sqlite-vec.", "confidence": 0.8, "gaps": [], "used_entities": ["alpha-project"],
        "citations": [{"entity_id": "alpha-project", "entity_name": "Alpha Project", "file_path": "",
                       "snippet": "", "source_episodes": [EP], "claim_id": "clm_1",
                       "evidence": [ev.to_dict()], "claim_provenance": {"claim_id": "clm_1"}}],
    })
    with TestClient(main.app) as client:
        r = client.post("/ask", json={"query": "what index"})
    assert r.status_code == 200, r.text
    c = r.json()["citations"][0]
    assert c["claimId"] == "clm_1" and c["evidence"][0]["start"] == ev.start
    assert c["sourceEpisodes"] == [EP] and "claimProvenance" not in c
