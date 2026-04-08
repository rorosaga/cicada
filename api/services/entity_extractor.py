"""Stage 1: Entity & Relationship Extraction via litellm."""

import json

import litellm

from api.config import Settings

EXTRACTION_SYSTEM_PROMPT = """You are an entity extraction system for a personal knowledge graph.
Given a conversation transcript, extract entities and relationships mentioned.

Output valid JSON with this exact structure:
{
  "entities": [
    {
      "name": "Entity Name",
      "type": "person|project|company|concept|tool|deadline|skill|location",
      "description": "Brief description based on context",
      "confidence": 0.7
    }
  ],
  "relationships": [
    {
      "source": "Entity Name A",
      "target": "Entity Name B",
      "label": "relationship description"
    }
  ]
}

Rules:
- Only extract entities that are substantively discussed (not just passing mentions)
- Use the 8 entity types: person, project, company, concept, tool, deadline, skill, location
- Confidence reflects how certain you are about the extraction (0.0-1.0)
- Relationships should capture how entities relate to each other
- Keep descriptions concise (1-2 sentences)"""


async def extract(episodes: list[dict], settings: Settings) -> list[dict]:
    """Extract entities and relationships from unprocessed episodes."""
    all_extracted: list[dict] = []

    for episode in episodes:
        try:
            response = await litellm.acompletion(
                model=settings.litellm_model,
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": episode["content"]},
                ],
                response_format={"type": "json_object"},
                api_key=settings.litellm_api_key,
                api_base=settings.litellm_api_base,
            )

            content = response.choices[0].message.content
            parsed = json.loads(content)

            for entity in parsed.get("entities", []):
                entity["source_episode"] = episode["id"]
            for rel in parsed.get("relationships", []):
                rel["source_episode"] = episode["id"]

            all_extracted.append({
                "episode_id": episode["id"],
                "entities": parsed.get("entities", []),
                "relationships": parsed.get("relationships", []),
            })

        except Exception as e:
            print(f"Extraction failed for episode {episode['id']}: {e}")
            continue

    return all_extracted
