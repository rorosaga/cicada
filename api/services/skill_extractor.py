"""Stage 4: Pattern Detection & Skill Extraction."""

import json

import litellm

from api.config import Settings

SKILL_DETECTION_PROMPT = """You are analyzing entity changes in a personal knowledge graph to detect
recurring behavioral patterns, preferences, and workflows.

Given the entity changes from this Sleep cycle and the existing entities, identify any
procedural knowledge (skills) that should be stored. These are things like:
- User preferences ("prefers concise summaries", "always uses TypeScript over JavaScript")
- Workflows ("reviews PRs before morning standup")
- Recurring patterns ("explores new tools every weekend")

Output valid JSON:
{
  "skills": [
    {
      "name": "Skill or preference name",
      "description": "What this pattern/preference is",
      "confidence": 0.7
    }
  ]
}

If no patterns are detected, return {"skills": []}."""


async def detect_patterns(
    changes: list[dict], existing: list[dict], settings: Settings
) -> list[dict]:
    """Detect recurring patterns and extract skills."""
    if not changes:
        return []

    # Build context from changes and existing entities
    context = _build_context(changes, existing)

    try:
        response = await litellm.acompletion(
            model=settings.litellm_model,
            messages=[
                {"role": "system", "content": SKILL_DETECTION_PROMPT},
                {"role": "user", "content": context},
            ],
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        parsed = json.loads(content)
        return parsed.get("skills", [])

    except Exception as e:
        from loguru import logger
        logger.error(f"Skill extraction failed: {type(e).__name__}: {e}")
        return []


def _build_context(changes: list[dict], existing: list[dict]) -> str:
    """Build a text summary of changes and existing state for the LLM."""
    lines: list[str] = ["## Recent Changes"]
    for change in changes[:20]:
        entity = change.get("entity", {})
        name = entity.get("name", change.get("id", "unknown"))
        action = change.get("action", "unknown")
        lines.append(f"- {name}: {action}")

    lines.append("\n## Existing Entities")
    for entity in existing[:30]:
        fm = entity.get("frontmatter", {})
        name = fm.get("name", entity.get("id", "unknown"))
        etype = fm.get("type", "unknown")
        lines.append(f"- {name} ({etype})")

    return "\n".join(lines)
