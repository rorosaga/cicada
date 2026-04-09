"""Stage 1: Entity & Relationship Extraction via litellm."""

import asyncio
import json

import litellm
from loguru import logger

from api.config import Settings

EXTRACTION_SYSTEM_PROMPT = """You are an entity extraction system for a personal knowledge graph.
Given a conversation transcript, extract meaningful entities and the relationships between them.

Output valid JSON with this exact structure:
{
  "entities": [
    {
      "name": "Entity Name",
      "type": "person|project|company|concept|tool|deadline|skill|location",
      "description": "Rich 3-6 sentence description with concrete details from the conversation: what it is, why it matters to the user, specific facts, decisions, or context discussed. Use wikilinks [[like this]] when referencing other entities.",
      "tags": ["relevant", "tags"],
      "confidence": 0.7
    }
  ],
  "relationships": [
    {
      "source": "Entity Name A",
      "target": "Entity Name B",
      "label": "specific relationship verb phrase"
    }
  ]
}

Rules:
- **Descriptions must be rich and contextual (3-6 sentences)** — include specific facts, decisions, quotes, or technical details actually mentioned. Don't write generic summaries.
- Use wikilinks `[[Entity Name]]` inside descriptions to reference other entities
- Only extract entities that are substantively discussed, not passing mentions
- Entity types must be exactly one of: person, project, company, concept, tool, deadline, skill, location
- **Relationships are critical** — capture every meaningful connection between entities with a specific verb phrase (e.g. "works at", "built with", "supervised by", "depends on", "evaluated against", "replaced by")
- Relationship labels should be short verb phrases, not full sentences
- Confidence 0.5-0.9 based on how substantive the discussion was"""

# Max concurrent LLM calls — stay under rate limits
MAX_CONCURRENCY = 10

# Chunk size in chars (~6K tokens). Long conversations get split into chunks
# so no information is lost. Each chunk gets its own extraction call.
CHUNK_SIZE = 24_000
CHUNK_OVERLAP = 500  # Overlap to avoid splitting mid-sentence


def _chunk_content(content: str) -> list[str]:
    """Split long content into overlapping chunks."""
    if len(content) <= CHUNK_SIZE:
        return [content]
    chunks = []
    start = 0
    while start < len(content):
        end = start + CHUNK_SIZE
        # Try to break at a newline near the boundary
        if end < len(content):
            newline_pos = content.rfind("\n", end - 200, end)
            if newline_pos > start:
                end = newline_pos + 1
        chunks.append(content[start:end])
        start = end - CHUNK_OVERLAP
    return chunks


async def _extract_chunk(
    ep_id: str, chunk: str, chunk_idx: int, total_chunks: int, settings: Settings
) -> dict:
    """Extract entities from a single chunk via LLM."""
    response = await litellm.acompletion(
        model=settings.litellm_model,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": chunk},
        ],
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    parsed = json.loads(raw)
    return parsed


async def extract(episodes: list[dict], settings: Settings) -> list[dict]:
    """Extract entities and relationships from unprocessed episodes (parallel)."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    results: list[dict | None] = [None] * len(episodes)
    success = 0
    failed = 0
    total = len(episodes)

    async def process_one(i: int, episode: dict):
        nonlocal success, failed
        ep_id = episode["id"]
        content = episode["content"]

        if not content.strip():
            return

        chunks = _chunk_content(content)

        async with semaphore:
            try:
                if len(chunks) > 1:
                    logger.info(f"  [{i+1}/{total}] {ep_id} — {len(content)} chars, split into {len(chunks)} chunks")
                else:
                    logger.info(f"  [{i+1}/{total}] {ep_id} — extracting ({len(content)} chars)")

                # Extract from all chunks and merge results
                all_entities = []
                all_relationships = []
                for ci, chunk in enumerate(chunks):
                    parsed = await _extract_chunk(ep_id, chunk, ci, len(chunks), settings)
                    all_entities.extend(parsed.get("entities", []))
                    all_relationships.extend(parsed.get("relationships", []))

                for entity in all_entities:
                    entity["source_episode"] = ep_id
                for rel in all_relationships:
                    rel["source_episode"] = ep_id

                results[i] = {
                    "episode_id": ep_id,
                    "entities": all_entities,
                    "relationships": all_relationships,
                }

                success += 1
                if all_entities:
                    names = [e["name"] for e in all_entities[:5]]
                    logger.info(f"    → {len(all_entities)} entities: {', '.join(names)}")

            except litellm.exceptions.RateLimitError:
                logger.warning(f"  [{i+1}/{total}] {ep_id} — rate limited, retrying in 10s...")
                await asyncio.sleep(10)
                # Retry once
                try:
                    response = await litellm.acompletion(
                        model=settings.litellm_model,
                        messages=[
                            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                            {"role": "user", "content": content},
                        ],
                        response_format={"type": "json_object"},
                    )
                    raw = response.choices[0].message.content
                    parsed = json.loads(raw)
                    entities = parsed.get("entities", [])
                    relationships = parsed.get("relationships", [])
                    for entity in entities:
                        entity["source_episode"] = ep_id
                    for rel in relationships:
                        rel["source_episode"] = ep_id
                    results[i] = {
                        "episode_id": ep_id,
                        "entities": entities,
                        "relationships": relationships,
                    }
                    success += 1
                except Exception as e:
                    failed += 1
                    logger.error(f"  [{i+1}/{total}] {ep_id} — retry failed: {e}")

            except litellm.exceptions.AuthenticationError as e:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — auth error (check API key): {e}")
            except litellm.exceptions.NotFoundError as e:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — model not found: {settings.litellm_model}")
            except Exception as e:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — {type(e).__name__}: {e}")

    # Fire all tasks with semaphore-controlled concurrency
    tasks = [process_one(i, ep) for i, ep in enumerate(episodes)]
    await asyncio.gather(*tasks)

    all_extracted = [r for r in results if r is not None]
    logger.info(f"Extraction done: {success} succeeded, {failed} failed out of {total}")
    return all_extracted
