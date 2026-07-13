"""Stage 4: Pattern Detection & Skill Extraction.

The job here is to find procedural patterns — preferences, workflows, recurring
relationships — that span multiple conversations. Unlike the earlier version
this gets the actual change data and entity co-occurrence graph so it can spot
patterns rather than rubber-stamping the first thing the model guesses.
"""

import json

import litellm
from loguru import logger

from api.config import Settings
from api.services.providers import resolve_llm_fn

SKILL_DETECTION_PROMPT = """You are analyzing patterns in a personal knowledge graph to extract procedural skills and preferences.

ENTITY CHANGES THIS CYCLE:
{changes}

FREQUENTLY CO-OCCURRING ENTITIES (appeared together in 3+ conversations):
{cooccurrences}

RELATED EXISTING ENTITIES:
{existing}

Look for:
1. WORKFLOW PATTERNS — recurring sequences of actions or tools used together.
   Example: "Always checks GitHub before answering questions about projects."
2. PREFERENCE PATTERNS — consistent choices or styles across conversations.
   Example: "Prefers concise summaries over detailed explanations."
3. RELATIONSHIP PATTERNS — entities that are consistently discussed together.
   Example: "Career conversations always involve both Figure AI and robotics."

Output valid JSON:
{{
  "skills": [
    {{
      "name": "Descriptive Skill Name",
      "description": "1-2 sentence procedural description written as an instruction or observation",
      "evidence_entities": ["Entity A", "Entity B"],
      "confidence": 0.7
    }}
  ]
}}

Only extract skills with clear evidence from multiple conversations. Do not speculate. If there is no strong pattern, return {{"skills": []}}."""

COOCCURRENCE_MIN_COUNT = 3
MAX_CHANGES_IN_PROMPT = 40
MAX_EXISTING_IN_PROMPT = 30
EXISTING_BODY_CHAR_BUDGET = 1200


async def detect_patterns(
    changes: list[dict],
    existing: list[dict],
    settings: Settings,
    episode_cooccurrences: dict[str, list[str]] | None = None,
) -> list[dict]:
    """Detect recurring patterns across entities and emit skill entities."""
    if not changes:
        return []

    cooccurrences = _build_frequent_cooccurrences(episode_cooccurrences or {})
    change_payload = _format_changes(changes)
    existing_payload = _format_existing(existing, changes)

    prompt = SKILL_DETECTION_PROMPT.format(
        changes=change_payload,
        cooccurrences=_format_cooccurrences(cooccurrences),
        existing=existing_payload,
    )

    try:
        # Route through the provider factory (CQA-H3) so llm_mode="local"
        # (ollama) and consolidation_model overrides apply here too — the
        # completion callable stays litellm.acompletion, so this is still an
        # async call, byte-identical when neither override is configured.
        llm_fn = resolve_llm_fn(
            settings, model=settings.effective_consolidation_model, completion=litellm.acompletion
        )
        response = await llm_fn(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        parsed = json.loads(content)
        return parsed.get("skills", [])
    except Exception as e:
        logger.error(f"Skill extraction failed: {type(e).__name__}: {e}")
        return []


# ---------- Formatting helpers ----------


def _build_frequent_cooccurrences(
    episode_cooccurrences: dict[str, list[str]],
) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for names in episode_cooccurrences.values():
        unique = list(dict.fromkeys(names))  # preserve order, drop duplicates
        for i, a in enumerate(unique):
            for b in unique[i + 1:]:
                pair = tuple(sorted([a, b]))
                counts[pair] = counts.get(pair, 0) + 1
    return {pair: c for pair, c in counts.items() if c >= COOCCURRENCE_MIN_COUNT}


def _format_cooccurrences(pairs: dict[tuple[str, str], int]) -> str:
    if not pairs:
        return "(none)"
    lines = []
    for (a, b), count in sorted(pairs.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {a} + {b}: {count} conversations")
    return "\n".join(lines[:30])


def _format_changes(changes: list[dict]) -> str:
    payload = []
    for change in changes[:MAX_CHANGES_IN_PROMPT]:
        entity = change.get("entity", {}) or {}
        payload.append({
            "name": entity.get("name", change.get("id", "unknown")),
            "type": entity.get("type"),
            "action": change.get("action"),
            "description": (entity.get("description") or "")[:320],
            "history_entries": entity.get("history_entries", []) or [],
        })
    return json.dumps(payload, indent=2)


def _format_existing(existing: list[dict], changes: list[dict]) -> str:
    """Include related existing entities with real content, not just names."""
    touched_ids = {c["id"] for c in changes if "id" in c}
    related: list[dict] = []
    for entity_data in existing:
        if entity_data["id"] in touched_ids:
            related.append(entity_data)
    if not related:
        related = existing[:MAX_EXISTING_IN_PROMPT]

    lines = []
    for entity_data in related[:MAX_EXISTING_IN_PROMPT]:
        fm = entity_data.get("frontmatter", {}) or {}
        name = fm.get("name", entity_data.get("id", "unknown"))
        etype = fm.get("type", "unknown")
        body = (entity_data.get("body") or "")[:EXISTING_BODY_CHAR_BUDGET]
        lines.append(f"### {name} ({etype})\n{body}")
    return "\n\n".join(lines) if lines else "(none)"
