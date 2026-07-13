"""Tests for the ask_memory service (auditable NL synthesis over memory).

Hermetic: both retrieval and the LLM are injected (``retrieve_fn`` / ``llm_fn``),
so no embedding model, no network, no API key. The flagship behaviours under
test are (a) a grounded answer whose citations map back to retrieved entities,
(b) the honest-gap path when retrieval is empty (admits ignorance, low
confidence, non-empty gaps — never hallucinates), and (c) the response shape.
"""

from __future__ import annotations

import json

from api.services import ask_service, markdown_parser


def _make_entity(entities_dir, stem, name, etype, body, **extra_fm):
    fm = {
        "name": name,
        "type": etype,
        "status": "active",
        "confidence": 0.8,
        **extra_fm,
    }
    markdown_parser.write(entities_dir / f"{stem}.md", fm, body)


def _retrieve_from(hits):
    """Build a retrieve_fn returning a fixed hit list (search_entities shape)."""

    def _retrieve(query, top_k):
        return hits[:top_k]

    return _retrieve


def _hit(entity_id, name, etype="tool", status="active", confidence=0.8, score=0.7):
    return {
        "score": score,
        "text": f"{name} text",
        "metadata": {
            "entity_id": entity_id,
            "entity_name": name,
            "type": etype,
            "status": status,
            "confidence": confidence,
            "file_path": "",  # filled by the service from disk where needed
        },
    }


def _llm(payload: dict):
    """Build an llm_fn that returns a fixed JSON payload as a raw string."""

    def _call(prompt: str) -> str:
        return json.dumps(payload)

    return _call


def test_normal_answer_has_citations_mapping_to_retrieved_entities(tmp_path):
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _make_entity(
        entities_dir, "fastapi", "FastAPI", "tool",
        "A python web framework. The backend is built with it.",
        source_episodes=["ep_2026-01-01_001"],
    )
    _make_entity(
        entities_dir, "swiftui", "SwiftUI", "tool",
        "The macOS companion app frontend framework.",
        source_episodes=["ep_2026-02-02_002"],
    )

    retrieve_fn = _retrieve_from([_hit("fastapi", "FastAPI"), _hit("swiftui", "SwiftUI")])
    llm_fn = _llm({
        "answer": "The backend uses FastAPI and the app frontend uses SwiftUI.",
        "confidence": 0.82,
        "used_entities": ["fastapi", "swiftui"],
        "gaps": [],
    })

    result = ask_service.answer_query(
        tmp_path, "what is the stack", top_k=6, retrieve_fn=retrieve_fn, llm_fn=llm_fn
    )

    assert "FastAPI" in result["answer"]
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["used_entities"] == ["fastapi", "swiftui"]

    citations = result["citations"]
    assert len(citations) == 2
    by_id = {c["entity_id"]: c for c in citations}
    assert set(by_id) == {"fastapi", "swiftui"}
    # Citations carry provenance read from the markdown frontmatter + body.
    assert by_id["fastapi"]["entity_name"] == "FastAPI"
    assert by_id["fastapi"]["source_episodes"] == ["ep_2026-01-01_001"]
    assert by_id["fastapi"]["file_path"].endswith("fastapi.md")
    assert by_id["fastapi"]["snippet"], "snippet should be a non-empty body excerpt"


def test_empty_retrieval_yields_honest_gap_answer(tmp_path):
    """No retrieval => admit ignorance, low confidence, gaps populated, NO LLM call."""
    (tmp_path / "entities").mkdir()

    llm_calls: list[str] = []

    def llm_fn(prompt: str) -> str:
        llm_calls.append(prompt)
        return json.dumps({"answer": "hallucinated", "confidence": 0.99, "gaps": []})

    result = ask_service.answer_query(
        tmp_path,
        "who is the CFO of a company never mentioned",
        top_k=6,
        retrieve_fn=_retrieve_from([]),
        llm_fn=llm_fn,
    )

    assert llm_calls == [], "must not call the LLM when there is nothing to ground on"
    assert result["citations"] == []
    assert result["used_entities"] == []
    assert result["gaps"], "gaps must be non-empty on the honest-ignorance path"
    assert result["confidence"] <= 0.2
    # Answer should admit it does not know rather than fabricate.
    assert "don't" in result["answer"].lower() or "do not" in result["answer"].lower() \
        or "no information" in result["answer"].lower()


def test_gaps_from_llm_are_preserved(tmp_path):
    """When the LLM reports gaps on a grounded answer, they pass through."""
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _make_entity(entities_dir, "fastapi", "FastAPI", "tool", "Backend framework.")

    retrieve_fn = _retrieve_from([_hit("fastapi", "FastAPI")])
    llm_fn = _llm({
        "answer": "The backend is FastAPI.",
        "confidence": 0.6,
        "used_entities": ["fastapi"],
        "gaps": ["No information about the database choice."],
    })

    result = ask_service.answer_query(
        tmp_path, "what database", top_k=6, retrieve_fn=retrieve_fn, llm_fn=llm_fn
    )

    assert result["gaps"] == ["No information about the database choice."]
    assert result["confidence"] == 0.6


def test_response_shape_keys_present(tmp_path):
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _make_entity(entities_dir, "fastapi", "FastAPI", "tool", "Backend framework.")

    result = ask_service.answer_query(
        tmp_path,
        "stack",
        top_k=6,
        retrieve_fn=_retrieve_from([_hit("fastapi", "FastAPI")]),
        llm_fn=_llm({"answer": "FastAPI.", "confidence": 0.5, "used_entities": ["fastapi"], "gaps": []}),
    )

    for key in ("answer", "confidence", "citations", "gaps", "used_entities"):
        assert key in result, f"missing key {key}"
    assert isinstance(result["answer"], str)
    assert isinstance(result["confidence"], float)
    assert isinstance(result["citations"], list)
    assert isinstance(result["gaps"], list)
    assert isinstance(result["used_entities"], list)


def test_confidence_clamped_and_malformed_json_degrades_gracefully(tmp_path):
    """A non-JSON / junk LLM reply must not crash; degrade to a low-confidence gap."""
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _make_entity(entities_dir, "fastapi", "FastAPI", "tool", "Backend framework.")

    def llm_fn(prompt: str) -> str:
        return "this is not json at all"

    result = ask_service.answer_query(
        tmp_path,
        "stack",
        top_k=6,
        retrieve_fn=_retrieve_from([_hit("fastapi", "FastAPI")]),
        llm_fn=llm_fn,
    )

    assert 0.0 <= result["confidence"] <= 1.0
    assert result["gaps"], "a parse failure should surface as a gap, not a fabricated answer"


def test_llm_used_entities_filtered_to_actually_retrieved(tmp_path):
    """If the model cites an id that was not retrieved, it is dropped from citations."""
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _make_entity(entities_dir, "fastapi", "FastAPI", "tool", "Backend framework.")

    retrieve_fn = _retrieve_from([_hit("fastapi", "FastAPI")])
    llm_fn = _llm({
        "answer": "FastAPI and also Neo4j.",
        "confidence": 0.7,
        "used_entities": ["fastapi", "neo4j-hallucinated"],
        "gaps": [],
    })

    result = ask_service.answer_query(
        tmp_path, "stack", top_k=6, retrieve_fn=retrieve_fn, llm_fn=llm_fn
    )

    cited_ids = {c["entity_id"] for c in result["citations"]}
    assert "neo4j-hallucinated" not in cited_ids
    assert cited_ids == {"fastapi"}


def test_used_entities_reflects_model_selection_not_full_retrieval(tmp_path):
    """used_entities must report what the model used, consistent with citations.

    Two entities are retrieved; the model says it used only one. The response's
    used_entities and citations must AGREE on that single entity — not silently
    widen to the full retrieved set (a provenance/auditability contract).
    """
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _make_entity(entities_dir, "fastapi", "FastAPI", "tool", "Backend framework.")
    _make_entity(entities_dir, "swiftui", "SwiftUI", "tool", "Frontend framework.")

    retrieve_fn = _retrieve_from([_hit("fastapi", "FastAPI"), _hit("swiftui", "SwiftUI")])
    llm_fn = _llm({
        "answer": "The backend is FastAPI.",
        "confidence": 0.7,
        "used_entities": ["fastapi"],
        "gaps": [],
    })

    result = ask_service.answer_query(
        tmp_path, "what is the backend", top_k=6, retrieve_fn=retrieve_fn, llm_fn=llm_fn
    )

    assert result["used_entities"] == ["fastapi"]
    cited_ids = {c["entity_id"] for c in result["citations"]}
    assert cited_ids == {"fastapi"}
    # citations and used_entities must not contradict each other
    assert set(result["used_entities"]) == cited_ids


def test_all_cited_ids_invalid_does_not_attribute_to_every_entity(tmp_path):
    """If every id the model cites is a hallucination, do NOT cite everything.

    The old ``used or retrieved_ids`` fallback attributed the answer to all
    retrieved entities even though the model claimed it used none of them — a
    provenance lie. With no valid grounding, this is a gap: no citations, empty
    used_entities, low confidence, populated gaps.
    """
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _make_entity(entities_dir, "fastapi", "FastAPI", "tool", "Backend framework.")
    _make_entity(entities_dir, "swiftui", "SwiftUI", "tool", "Frontend framework.")

    retrieve_fn = _retrieve_from([_hit("fastapi", "FastAPI"), _hit("swiftui", "SwiftUI")])
    llm_fn = _llm({
        "answer": "Postgres is the database.",
        "confidence": 0.9,
        "used_entities": ["postgres-hallucinated"],
        "gaps": [],
    })

    result = ask_service.answer_query(
        tmp_path, "what database", top_k=6, retrieve_fn=retrieve_fn, llm_fn=llm_fn
    )

    assert result["citations"] == [], "no valid grounding => no citations"
    assert result["used_entities"] == []
    assert result["gaps"], "ungrounded answer must surface a gap"
    assert result["confidence"] <= 0.2


def test_used_entities_omitted_by_model_falls_back_to_retrieved(tmp_path):
    """If the model omits used_entities entirely, fall back to retrieved (benign)."""
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _make_entity(entities_dir, "fastapi", "FastAPI", "tool", "Backend framework.")

    retrieve_fn = _retrieve_from([_hit("fastapi", "FastAPI")])
    llm_fn = _llm({
        "answer": "The backend is FastAPI.",
        "confidence": 0.7,
        "gaps": [],
    })

    result = ask_service.answer_query(
        tmp_path, "backend", top_k=6, retrieve_fn=retrieve_fn, llm_fn=llm_fn
    )

    assert result["used_entities"] == ["fastapi"]
    assert {c["entity_id"] for c in result["citations"]} == {"fastapi"}


def test_gaps_as_bare_string_is_not_shredded_into_characters(tmp_path):
    """A model returning gaps as a string (not list) must not become char-per-gap."""
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _make_entity(entities_dir, "fastapi", "FastAPI", "tool", "Backend framework.")

    retrieve_fn = _retrieve_from([_hit("fastapi", "FastAPI")])
    llm_fn = _llm({
        "answer": "The backend is FastAPI.",
        "confidence": 0.6,
        "used_entities": ["fastapi"],
        "gaps": "No information about the database choice.",
    })

    result = ask_service.answer_query(
        tmp_path, "what database", top_k=6, retrieve_fn=retrieve_fn, llm_fn=llm_fn
    )

    assert result["gaps"] == ["No information about the database choice."]
    # No single-character entries from iterating a string.
    assert all(len(g) > 1 for g in result["gaps"])


def test_used_entities_as_bare_string_is_not_shredded(tmp_path):
    """A model returning used_entities as a string must not iterate char-by-char."""
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _make_entity(entities_dir, "fastapi", "FastAPI", "tool", "Backend framework.")

    retrieve_fn = _retrieve_from([_hit("fastapi", "FastAPI")])
    llm_fn = _llm({
        "answer": "The backend is FastAPI.",
        "confidence": 0.6,
        "used_entities": "fastapi",
        "gaps": [],
    })

    result = ask_service.answer_query(
        tmp_path, "backend", top_k=6, retrieve_fn=retrieve_fn, llm_fn=llm_fn
    )

    # "fastapi" the string must be treated as one id, not the chars f,a,s,...
    assert result["used_entities"] == ["fastapi"]
    assert {c["entity_id"] for c in result["citations"]} == {"fastapi"}


def test_empty_query_short_circuits_without_retrieval_or_llm(tmp_path):
    """A blank/whitespace query must not burn a retrieval + LLM round-trip."""
    (tmp_path / "entities").mkdir()

    retrieve_calls: list[str] = []
    llm_calls: list[str] = []

    def retrieve_fn(query, top_k):
        retrieve_calls.append(query)
        return [_hit("fastapi", "FastAPI")]

    def llm_fn(prompt):
        llm_calls.append(prompt)
        return json.dumps({"answer": "x", "confidence": 0.9, "gaps": []})

    result = ask_service.answer_query(
        tmp_path, "   ", top_k=6, retrieve_fn=retrieve_fn, llm_fn=llm_fn
    )

    assert retrieve_calls == [], "blank query must not run retrieval"
    assert llm_calls == [], "blank query must not call the LLM"
    assert result["citations"] == []
    assert result["gaps"]
    assert result["confidence"] <= 0.2


def test_cold_index_falls_back_to_substring_over_disk(tmp_path):
    """When the vector index returns nothing but entities exist on disk, the
    service must substring-match rather than falsely claim ignorance."""
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _make_entity(
        entities_dir, "fastapi", "FastAPI", "tool",
        "FastAPI is the backend web framework.",
        source_episodes=["ep_2026-01-01_001"],
    )

    # Cold index: retrieval yields nothing.
    retrieve_fn = _retrieve_from([])
    llm_fn = _llm({
        "answer": "The backend is FastAPI.",
        "confidence": 0.7,
        "used_entities": ["fastapi"],
        "gaps": [],
    })

    result = ask_service.answer_query(
        tmp_path, "fastapi", top_k=6, retrieve_fn=retrieve_fn, llm_fn=llm_fn
    )

    # Entity exists on disk and the query matches its name => must be grounded,
    # not a false "I don't know".
    assert {c["entity_id"] for c in result["citations"]} == {"fastapi"}
    assert "FastAPI" in result["answer"]


def test_citation_falls_back_to_index_text_when_file_missing(tmp_path):
    """If the index points at an entity whose .md is gone, the citation degrades
    to the indexed text (honest, no dangling file) instead of disappearing."""
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    # No fastapi.md written — file is missing on purpose.

    hit = _hit("fastapi", "FastAPI")
    hit["text"] = "FastAPI backend framework from the stale index."
    retrieve_fn = _retrieve_from([hit])
    llm_fn = _llm({
        "answer": "The backend is FastAPI.",
        "confidence": 0.6,
        "used_entities": ["fastapi"],
        "gaps": [],
    })

    result = ask_service.answer_query(
        tmp_path, "backend", top_k=6, retrieve_fn=retrieve_fn, llm_fn=llm_fn
    )

    citations = result["citations"]
    assert len(citations) == 1
    cite = citations[0]
    assert cite["entity_id"] == "fastapi"
    assert cite["source_episodes"] == [], "missing file => no episodes, degrade honestly"
    assert cite["snippet"], "snippet should fall back to the indexed text"
