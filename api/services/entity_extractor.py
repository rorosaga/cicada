"""Stage 1: Entity & Relationship Extraction via litellm."""

import asyncio
import json
import sys

import litellm
from loguru import logger
from tqdm import tqdm

from api.config import Settings

EXTRACTION_SYSTEM_PROMPT = """You are an entity extraction system for a personal knowledge graph.
Given a conversation transcript, extract meaningful entities and the relationships between them.

Output valid JSON with this exact structure:
{
  "entities": [
    {
      "name": "Entity Name",
      "type": "person|project|company|concept|tool|deadline|skill|location",
      "aliases": ["Mongo", "the db"],
      "summary": "1-3 sentence orientation. See SUMMARY LENGTH BY TYPE below.",
      "key_facts": ["atomic fact", "another atomic fact"],
      "history_entries": [
        {"date": "YYYY-MM-DD", "event": "What happened"}
      ],
      "links": [
        {"url": "https://...", "title": "Human title", "note": "what it is / why it came up"}
      ],
      "open_questions": ["unresolved point about this entity"],
      "tags": ["relevant", "tags"],
      "confidence": 0.7,
      "description": "Optional. Same content as summary; kept only for backward compatibility."
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

The entity body is rendered as ordered markdown sections: ## Summary, ## Key Facts,
## History, ## Links, ## Open Questions. The fields above map directly onto those
sections. ## Related is generated from `relationships` — do NOT emit a related field.

SUMMARY (## Summary) — the orientation line, "what is this and why does the user care":
- deadline: 1-2 sentences. What is due, when, current status.
- skill: 1-2 sentences. Procedural rule or preference, written as an instruction.
- location: 2-3 sentences. Where it is, why it's relevant to the user.
- person: 2-4 sentences. Who they are, relationship to user, key context.
- tool: 2-4 sentences. What it is, how the user uses it, why it matters.
- concept: 3-4 sentences. Definition, relevance to user's work.
- project: 3-5 sentences. What it is, user's role, current status, goal.
- company: 3-5 sentences. What they do, user's relationship, relevance.
Do NOT cram every fact into the summary — atomic facts belong in key_facts.

KEY FACTS (## Key Facts) — this is where density lives:
- Emit every concrete, atomic fact stated about the entity: roles, stack components,
  dates-as-facts, identifiers, quantities, prices, versions, capacities, locations,
  affiliations, contact handles.
- One fact per bullet. Do NOT re-narrate the summary.
- Prefer 3-8 facts for project/company/tool; 2-5 for person/concept; 1-3 for
  deadline/location. key_facts may be empty ONLY for skill.
- key_facts is REQUIRED (emit when any relevant content exists) for project, company, tool.

HISTORY ENTRIES (## History):
- Include dated events extracted from the conversation, one sentence each.
- Always emit history_entries for project, company, and deadline when any dated event
  is present. Never silently drop a date you saw.
- For person entities, include key interaction dates when present.
- For concept/tool/skill/location: only when the conversation contains specific dated
  events. Otherwise leave history_entries as an empty array.

LINKS (## Links):
- Extract EVERY URL mentioned in connection with this entity into links[] with a human
  title and a one-line note (what it is / why it came up). Never drop a URL into prose only.
- For tool entities, links is REQUIRED when any URL (docs, repo, homepage) appears.

OPEN QUESTIONS (## Open Questions):
- Capture unresolved points the user or system still needs to settle about this entity
  (an unconfirmed identity, an undecided choice, a missing date). Leave empty if none.

EXTRACTION GUIDELINES:
- Extract entities that are meaningful to the user's life, work, or goals. Skip trivial mentions.
- Confidence reflects how certain you are about the entity's attributes, not how important it is.
- If an entity is mentioned but you lack context to classify it confidently (e.g., a bare name
  with no role), still extract it but set confidence below 0.5.
- aliases: list any alternate surface forms used for the entity ("Mongo" for MongoDB,
  "the database", a nickname). Leave empty if there is only one name.
- Use wikilinks `[[Entity Name]]` inside summary and key_facts to reference other entities.
  Do NOT fabricate links bullets — those come only from real URLs in the source.
- Entity types must be exactly one of: person, project, company, concept, tool, deadline, skill, location.
- Relationships are critical — capture every meaningful connection between entities with a specific
  verb phrase (e.g. "works at", "built with", "supervised by", "depends on", "evaluated against",
  "replaced by"). Use short verb phrases, not full sentences or generic "related to"."""

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

    progress = tqdm(
        total=total,
        desc="Stage 1: extract",
        unit="ep",
        file=sys.stderr,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]",
        leave=True,
    )
    entities_so_far = 0

    async def _do_process(i: int, episode: dict) -> None:
        nonlocal success, failed, entities_so_far
        ep_id = episode["id"]
        content = episode["content"]

        if not content.strip():
            return

        chunks = _chunk_content(content)

        async with semaphore:
            try:
                # Extract from all chunks and merge results
                all_entities = []
                all_relationships = []
                for ci, chunk in enumerate(chunks):
                    parsed = await _extract_chunk(ep_id, chunk, ci, len(chunks), settings)
                    all_entities.extend(parsed.get("entities", []))
                    all_relationships.extend(parsed.get("relationships", []))

                for entity in all_entities:
                    entity["source_episode"] = ep_id
                    entity["source_episode_timestamp"] = episode.get("timestamp")
                for rel in all_relationships:
                    rel["source_episode"] = ep_id
                    rel["source_episode_timestamp"] = episode.get("timestamp")

                results[i] = {
                    "episode_id": ep_id,
                    "episode_timestamp": episode.get("timestamp"),
                    "entities": all_entities,
                    "relationships": all_relationships,
                }

                success += 1
                entities_so_far += len(all_entities)
                progress.set_postfix_str(
                    f"ok={success} fail={failed} entities={entities_so_far}",
                    refresh=False,
                )

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
                        entity["source_episode_timestamp"] = episode.get("timestamp")
                    for rel in relationships:
                        rel["source_episode"] = ep_id
                        rel["source_episode_timestamp"] = episode.get("timestamp")
                    results[i] = {
                        "episode_id": ep_id,
                        "episode_timestamp": episode.get("timestamp"),
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

    async def process_one(i: int, episode: dict) -> None:
        try:
            await _do_process(i, episode)
        finally:
            progress.update(1)

    # Fire all tasks with semaphore-controlled concurrency
    try:
        tasks = [process_one(i, ep) for i, ep in enumerate(episodes)]
        await asyncio.gather(*tasks)
    finally:
        progress.close()

    all_extracted = [r for r in results if r is not None]
    logger.info(f"Extraction done: {success} succeeded, {failed} failed out of {total}")
    return all_extracted
