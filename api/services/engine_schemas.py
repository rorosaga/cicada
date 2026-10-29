"""R-E14 — Stage-1 and Stage-2 output schemas, built from the rails.

One module for both plan engines so the enums can never drift from the
anti-pollution rails they enforce: entity types come from
``PRODUCIBLE_ENTITY_TYPES`` (no ``deadline``, no ``media`` — G17) and decay
classes from ``AGENT_PRODUCIBLE_DECAY_CLASSES`` (never ``evergreen`` — G66),
never from a literal list here. The post-hoc rails
(``entity_extractor.sanitize_decay_class``, the create-branch check) stay
authoritative; a schema is a first filter that saves a wasted retry.

Two dialects:

* ``strict=False`` — Claude's ``--json-schema`` (draft-07). Every key the
  prompt names is declared except the deprecated ``description`` (the prompt
  itself calls it optional, kept for backward compatibility — the open
  ``additionalProperties`` below still lets it through), ``evidence_quote``
  included (G118: a declared,
  typed field degrades fewer relationships to ``reasoning``), and
  ``additionalProperties`` stays true so a key the prompt adds later survives
  (the field-stripping fear recorded beside ``agent_engine.SCHEMA_BY_STAGE``).
  No ``maxLength``: an over-long quote would cost a schema retry, and the
  G118 locator already copes with length.
* ``strict=True`` — OpenAI structured outputs via ``codex exec
  --output-schema``: every object ``additionalProperties: false`` and
  ``required`` equal to all of its keys, optional values as nullable —
  verified live on codex-cli 0.154.0 (R2 §2.3: valid JSON, 5/5 evidence
  quotes exact).
"""
from __future__ import annotations

from api.models.schemas import AGENT_PRODUCIBLE_DECAY_CLASSES, PRODUCIBLE_ENTITY_TYPES

DRAFT_07 = "http://json-schema.org/draft-07/schema#"


def entity_types() -> list[str]:
    return sorted(t.value for t in PRODUCIBLE_ENTITY_TYPES)


def decay_classes() -> list[str]:
    return sorted(c.value for c in AGENT_PRODUCIBLE_DECAY_CLASSES)


def _object(properties: dict, required: list[str], *, strict: bool) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if strict else required,
        "additionalProperties": not strict,
    }


def extraction_schema(*, strict: bool) -> dict:
    text = {"type": "string"}
    texts = {"type": "array", "items": {"type": "string"}}
    history = _object({"date": text, "event": text}, ["date", "event"], strict=strict)
    link = _object({"url": text, "title": text, "note": text}, ["url"], strict=strict)
    decay = ({"type": ["string", "null"], "enum": [*decay_classes(), None]} if strict
             else {"type": "string", "enum": decay_classes()})
    quote = {"type": ["string", "null"]} if strict else {"type": "string"}
    website = {"type": ["string", "null"]} if strict else {"type": "string"}   # G61 S3-b: company/tool/project only
    # Ruling 42 (`application_page`): an event or program the person acted on; checked against the conversation.
    application = _object({"status": text, "by": text}, ["status"], strict=strict)
    if strict:
        application = {**application, "type": ["object", "null"]}
    entity = _object({
        "name": text,
        "type": {"type": "string", "enum": entity_types()},
        "aliases": texts,
        "summary": text,
        "key_facts": texts,
        "history_entries": {"type": "array", "items": history},
        "links": {"type": "array", "items": link},
        "open_questions": texts,
        "tags": texts,
        "confidence": {"type": "number"},
        "decay_class": decay,
        "website": website,
        "application": application,
    }, ["name", "type"], strict=strict)
    relationship = _object(
        {"source": text, "target": text, "label": text, "evidence_quote": quote},
        ["source", "target", "label"], strict=strict,
    )
    value = _object(
        {"entity": text, "attribute": text, "value": text, "evidence_quote": quote},
        ["entity", "attribute", "value"], strict=strict,
    )
    root = _object({
        "entities": {"type": "array", "items": entity},
        "relationships": {"type": "array", "items": relationship},
        "values": {"type": "array", "items": value},
    }, ["entities", "relationships"], strict=strict)
    return root if strict else {"$schema": DRAFT_07, **root}


def disambiguation_schema(*, strict: bool) -> dict:
    """The Codex twin of ``agent_engine.SCHEMA_BY_STAGE["disambiguation"]`` (a literal there): a one-pair
    ``decision`` or a batch's ``decisions``."""
    from api.services import entity_relations

    words = ["same", "different", "unsure", "related"]
    decision = {"type": "string", "enum": words}
    reason = {"type": ["string", "null"]} if strict else {"type": "string"}
    # 2026-10-29: a ``related`` answer names its relation (`entity_relations.RELATIONS`); any other leaves it out.
    kinds = list(entity_relations.RELATIONS)
    relation = ({"type": ["string", "null"], "enum": [*kinds, None]} if strict
                else {"type": "string", "enum": kinds})
    # Several candidates in one call (2026-10-20, `entity_resolver._llm_judge_batch`): a decision per entry. A
    # one-pair answer leaves `decisions` null, a batch answer `decision`; strict mode needs every key, so both are
    # nullable there.
    row = _object({"entry": {"type": "integer"}, "decision": decision, "relation": relation, "reason": reason},
                  ["entry", "decision"], strict=strict)
    if strict:
        return _object({"decision": {"type": ["string", "null"], "enum": [*words, None]}, "relation": relation,
                        "reason": reason, "decisions": {"type": ["array", "null"], "items": row}}, [], strict=True)
    return _object({"decision": decision, "relation": relation, "reason": reason,
                    "decisions": {"type": "array", "items": row}}, [], strict=False)
