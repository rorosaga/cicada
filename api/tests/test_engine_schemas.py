"""R-E14 — both engines' schemas are built from the rails, never a literal."""
from __future__ import annotations

import json

from api.models.schemas import AGENT_PRODUCIBLE_DECAY_CLASSES, PRODUCIBLE_ENTITY_TYPES
from api.services import engine_schemas

PROMPT_KEYS = ("name", "type", "aliases", "summary", "key_facts", "history_entries", "links",
               "open_questions", "tags", "confidence", "decay_class")


def _objects(node):
    if node.get("type") == "object":
        yield node
    for child in (node.get("properties") or {}).values():
        yield from _objects(child)
    if isinstance(node.get("items"), dict):
        yield from _objects(node["items"])


def test_the_claude_schema_is_draft07_declares_every_prompt_key_and_keeps_unknown_ones():
    schema = engine_schemas.extraction_schema(strict=False)
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    entity = schema["properties"]["entities"]["items"]
    assert set(PROMPT_KEYS) <= set(entity["properties"])
    assert all(node["additionalProperties"] is True for node in _objects(schema))
    assert entity["required"] == ["name", "type"]
    rel = schema["properties"]["relationships"]["items"]
    assert "evidence_quote" in rel["properties"] and "maxLength" not in rel["properties"]["evidence_quote"]


def test_every_strict_schema_is_openai_strict_compatible():
    for schema in (engine_schemas.extraction_schema(strict=True),
                   engine_schemas.disambiguation_schema(strict=True)):
        for node in _objects(schema):
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])


def test_the_enums_are_the_rails():
    for strict in (True, False):
        entity = engine_schemas.extraction_schema(strict=strict)["properties"]["entities"]["items"]
        assert set(entity["properties"]["type"]["enum"]) == {t.value for t in PRODUCIBLE_ENTITY_TYPES}
        decay = {v for v in entity["properties"]["decay_class"]["enum"] if v is not None}
        assert decay == {c.value for c in AGENT_PRODUCIBLE_DECAY_CLASSES}


def test_no_schema_can_carry_a_forbidden_value():
    blob = json.dumps([engine_schemas.extraction_schema(strict=True),
                       engine_schemas.extraction_schema(strict=False)])
    for word in ("evergreen", "deadline", "media"):
        assert f'"{word}"' not in blob


def test_the_strict_extraction_shape_matches_the_live_verified_one():
    """R2 §2.3 (codex-cli 0.154.0): nullable decay_class and evidence_quote."""
    schema = engine_schemas.extraction_schema(strict=True)
    entity = schema["properties"]["entities"]["items"]["properties"]
    rel = schema["properties"]["relationships"]["items"]["properties"]
    assert entity["decay_class"]["type"] == ["string", "null"] and None in entity["decay_class"]["enum"]
    assert rel["evidence_quote"] == {"type": ["string", "null"]}
