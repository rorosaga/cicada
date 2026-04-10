"""Stage 3: Conflict Resolution & Temporal Decay."""

import json
import sys
from datetime import date, datetime

import litellm
from loguru import logger
from tqdm import tqdm

from api.config import Settings
from api.services import markdown_parser


async def resolve_and_prune(
    resolved: list[dict], existing: list[dict], settings: Settings
) -> list[dict]:
    """Apply conflict resolution and temporal decay to all entities."""
    changes: list[dict] = list(resolved)

    # IDs of entities referenced in this cycle
    referenced_ids = {r["id"] for r in resolved}

    # Synthesize updates and detect contradictions on update branches
    existing_by_id = {e["id"]: e for e in existing}
    update_changes = [c for c in resolved if c.get("action") == "update"]
    progress = tqdm(
        total=len(update_changes),
        desc="Stage 3: synth",
        unit="ent",
        file=sys.stderr,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
        leave=True,
        disable=len(update_changes) == 0,
    )
    conflicts_found = 0
    for change in update_changes:
        progress.update(1)
        if change.get("action") != "update":
            continue
        entity_id = change["id"]
        existing_entity = existing_by_id.get(entity_id)
        if not existing_entity:
            continue
        new_entity = change.get("entity", {}) or {}
        new_desc = (new_entity.get("description") or "").strip()
        new_history = new_entity.get("history_entries", []) or []
        if not new_desc and not new_history:
            continue

        existing_body = existing_entity.get("body", "")
        fm = existing_entity.get("frontmatter", {}) or {}
        entity_type = new_entity.get("type") or fm.get("type", "concept")
        entity_name = new_entity.get("name") or fm.get("name", entity_id)

        try:
            synthesized = await _synthesize_entity_update(
                entity_name=entity_name,
                entity_type=entity_type,
                existing_body=existing_body,
                new_description=new_desc,
                new_history_entries=new_history,
                source_reference_date=_latest_change_date(change),
                settings=settings,
            )
            if synthesized:
                change["synthesized_body"] = synthesized
        except Exception as e:
            logger.debug(f"Synthesis failed for {entity_id}: {e}")

        if not new_desc:
            continue

        try:
            contradiction = await _detect_contradiction(
                entity_name=entity_name,
                existing_body=existing_body,
                new_description=new_desc,
                settings=settings,
            )
        except Exception as e:
            logger.debug(f"Contradiction check failed for {entity_id}: {e}")
            contradiction = None

        if contradiction and contradiction.get("has_unresolvable_contradiction"):
            conflicts_found += 1
            progress.set_postfix_str(f"conflicts={conflicts_found}", refresh=False)
            changes.append({
                "id": entity_id,
                "action": "conflict_nudge",
                "entity": new_entity,
                "conflict_context": contradiction.get("contradiction", ""),
                "options": contradiction.get("options", []),
                "source_episode": change.get("source_episode", ""),
                "trigger": "sleep/conflict_resolution",
            })

    progress.close()

    # Temporal decay for unreferenced entities
    # decay_rate is a per-week rate — convert per-cycle decay to days-based decay
    now = datetime.now()
    decay_candidates = [e for e in existing if e["id"] not in referenced_ids]
    decay_progress = tqdm(
        total=len(decay_candidates),
        desc="Stage 3: decay",
        unit="ent",
        file=sys.stderr,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}",
        leave=True,
        disable=len(decay_candidates) == 0,
    )
    for entity_data in existing:
        entity_id = entity_data["id"]
        if entity_id in referenced_ids:
            continue
        decay_progress.update(1)

        fm = entity_data["frontmatter"]
        status = fm.get("status", "active")
        if status in ("archived", "dropped"):
            continue

        confidence = fm.get("confidence", 0.5)
        decay_rate = fm.get("decay_rate", 0.05)
        days_since = _days_since_last_referenced(fm.get("last_referenced"), now)
        if days_since is None:
            # Fallback: single step if we cannot determine last reference
            decay_amount = decay_rate
        else:
            decay_amount = decay_rate * (days_since / 7.0)
        new_confidence = max(0.0, confidence - decay_amount)

        if new_confidence < settings.archive_threshold:
            changes.append({
                "id": entity_id,
                "action": "archive",
                "new_confidence": new_confidence,
                "new_status": "archived",
                "source_episode": "",
                "trigger": "sleep/decay",
            })
        elif new_confidence < settings.decay_nudge_threshold:
            changes.append({
                "id": entity_id,
                "action": "decay_nudge",
                "new_confidence": new_confidence,
                "new_status": "decaying",
                "source_episode": "",
                "trigger": "sleep/decay",
            })
        else:
            changes.append({
                "id": entity_id,
                "action": "decay",
                "new_confidence": new_confidence,
                "new_status": status,
                "source_episode": "",
                "trigger": "sleep/decay",
            })

    decay_progress.close()
    return changes


def apply_changes(changes: list[dict], memory_path) -> None:
    """Write entity changes to disk."""
    entities_dir = memory_path / "entities"

    write_progress = tqdm(
        total=len(changes),
        desc="Stage 5: write",
        unit="ent",
        file=sys.stderr,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}",
        leave=True,
        disable=len(changes) == 0,
    )
    for change in changes:
        write_progress.update(1)
        entity_id = change["id"]
        action = change["action"]
        filepath = entities_dir / f"{entity_id}.md"

        if action == "create":
            entity = change.get("entity", {})
            created_date = _earliest_change_date(change) or str(date.today())
            last_referenced = _latest_change_date(change) or created_date
            frontmatter = {
                "name": entity.get("name", entity_id.replace("-", " ").title()),
                "type": entity.get("type", "concept"),
                "status": "active",
                "confidence": entity.get("confidence", 0.5),
                "created": created_date,
                "last_referenced": last_referenced,
                "decay_rate": 0.05,
                "source_episodes": _change_source_episodes(change),
                "tags": entity.get("tags", []) or [],
                "related": [],
                "version": 1,
            }
            description = entity.get("description", "") or ""
            history_entries = entity.get("history_entries", []) or []
            body = _compose_entity_body(description, history_entries)
            markdown_parser.write(filepath, frontmatter, body)

        elif action == "update" and filepath.exists():
            parsed = markdown_parser.parse(filepath)
            parsed.frontmatter["last_referenced"] = _max_date(
                str(parsed.frontmatter.get("last_referenced", "")) or None,
                _latest_change_date(change),
            ) or str(date.today())
            parsed.frontmatter["version"] = parsed.frontmatter.get("version", 1) + 1
            episodes = parsed.frontmatter.get("source_episodes", [])
            for source_ep in _change_source_episodes(change):
                if source_ep and source_ep not in episodes:
                    episodes.append(source_ep)
            parsed.frontmatter["source_episodes"] = episodes

            # Merge new tags
            new_entity = change.get("entity", {})
            new_tags = new_entity.get("tags", []) or []
            if new_tags:
                existing_tags = set(parsed.frontmatter.get("tags", []) or [])
                parsed.frontmatter["tags"] = sorted(existing_tags | set(new_tags))

            # LLM-synthesized merge of existing body with new information.
            # Falls back to a simple merge if the synthesizer is unavailable.
            synthesized_body = change.get("synthesized_body")
            if synthesized_body is None:
                synthesized_body = _fallback_merge_body(
                    existing_body=parsed.body,
                    new_description=new_entity.get("description", "") or "",
                    new_history_entries=new_entity.get("history_entries", []) or [],
                )
            markdown_parser.write(filepath, parsed.frontmatter, synthesized_body)

        elif action in ("decay", "decay_nudge", "archive") and filepath.exists():
            parsed = markdown_parser.parse(filepath)
            parsed.frontmatter["confidence"] = change.get("new_confidence", 0.0)
            if "new_status" in change:
                parsed.frontmatter["status"] = change["new_status"]
            markdown_parser.write(filepath, parsed.frontmatter, parsed.body)

    write_progress.close()


# ---------- Helpers ----------


def _compose_entity_body(description: str, history_entries: list[dict]) -> str:
    """Assemble an entity page body from description + history entries."""
    parts: list[str] = []
    if description.strip():
        parts.append(description.strip())

    if history_entries:
        lines = ["## History"]
        # Sort by date when possible
        def _sort_key(entry):
            return str(entry.get("date", ""))
        for entry in sorted(history_entries, key=_sort_key):
            event_date = str(entry.get("date", "")).strip()
            event = str(entry.get("event", "")).strip()
            if not event:
                continue
            if event_date:
                lines.append(f"- {event_date}: {event}")
            else:
                lines.append(f"- {event}")
        if len(lines) > 1:
            parts.append("\n".join(lines))

    return "\n\n".join(parts).strip()


def _fallback_merge_body(
    existing_body: str, new_description: str, new_history_entries: list[dict]
) -> str:
    """Non-LLM merge used when synthesis is disabled or fails."""
    body = existing_body

    new_desc = (new_description or "").strip()
    if new_desc and len(new_desc) > 50 and new_desc not in body:
        # Insert before any ## History section so prose stays grouped.
        if "## History" in body:
            head, _, tail = body.partition("## History")
            body = f"{head.rstrip()}\n\n{new_desc}\n\n## History{tail}"
        else:
            body = f"{body.rstrip()}\n\n{new_desc}"

    if new_history_entries:
        body = _merge_history_entries(body, new_history_entries)

    return body.strip()


def _merge_history_entries(body: str, new_entries: list[dict]) -> str:
    """Append new history entries to the body's ## History section."""
    new_lines: list[str] = []
    for entry in new_entries:
        event_date = str(entry.get("date", "")).strip()
        event = str(entry.get("event", "")).strip()
        if not event:
            continue
        line = f"- {event_date}: {event}" if event_date else f"- {event}"
        if line in body:
            continue
        new_lines.append(line)

    if not new_lines:
        return body

    if "## History" in body:
        return body.rstrip() + "\n" + "\n".join(new_lines) + "\n"

    return body.rstrip() + "\n\n## History\n" + "\n".join(new_lines) + "\n"


def _change_source_episodes(change: dict) -> list[str]:
    episodes = list(change.get("source_episodes", []) or [])
    fallback = change.get("source_episode", "")
    if fallback and fallback not in episodes:
        episodes.append(fallback)
    return [ep for ep in episodes if ep]


def _extract_date_string(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _latest_change_date(change: dict) -> str | None:
    dates = [
        _extract_date_string(ts)
        for ts in list(change.get("source_episode_timestamps", []) or [])
    ]
    fallback = _extract_date_string(change.get("source_episode_timestamp"))
    if fallback:
        dates.append(fallback)
    dates = [d for d in dates if d]
    return max(dates) if dates else None


def _earliest_change_date(change: dict) -> str | None:
    dates = [
        _extract_date_string(ts)
        for ts in list(change.get("source_episode_timestamps", []) or [])
    ]
    fallback = _extract_date_string(change.get("source_episode_timestamp"))
    if fallback:
        dates.append(fallback)
    dates = [d for d in dates if d]
    return min(dates) if dates else None


def _max_date(left: str | None, right: str | None) -> str | None:
    candidates = [c for c in (left, right) if c]
    return max(candidates) if candidates else None


def _days_since_last_referenced(
    last_referenced: str | None, now: datetime
) -> int | None:
    """Return integer days between last_referenced and now, or None if unparseable."""
    if not last_referenced:
        return None
    try:
        # Accept plain dates and full ISO timestamps
        if "T" in str(last_referenced):
            last = datetime.fromisoformat(str(last_referenced).replace("Z", "+00:00"))
            last = last.replace(tzinfo=None)
        else:
            last = datetime.fromisoformat(str(last_referenced))
    except ValueError:
        return None
    delta = now - last
    return max(0, delta.days)


_SYNTHESIS_PROMPT = """You are updating an entity page in a personal knowledge graph.

ENTITY: {entity_name} (type: {entity_type})

EXISTING PAGE BODY:
{existing_body}

NEW INFORMATION TO INTEGRATE:
Description: {new_description}
New history entries (JSON): {new_history}
Source episode date: {source_reference_date}

INSTRUCTIONS:
1. Merge the new information into the existing page body.
2. The body has two sections: a description (prose paragraphs at the top) and an optional `## History` section (dated bullet entries).
3. For the description: integrate new facts, remove redundancy, and resolve contradictions by preferring newer information. Keep the description coherent — do not append disconnected paragraphs.
4. For the `## History` section: add new dated entries in chronological order. Do not duplicate existing entries. If the body has no History section yet and there are history entries, create one.
5. If a new fact contradicts an older fact, update the description to the current state and move the old fact into a history bullet (e.g., "2026-03-15: Previously used Postgres, switched to SQLite").
6. Preserve every wikilink ([[Entity Name]]) that appears in the existing body.
7. Preserve specific details — dates, names, numbers.
8. If the new information implies a change over time but the extraction did not provide an explicit dated history entry, you may use the source episode date as the fallback date for that change.

DESCRIPTION LENGTH GUIDELINES (by entity type):
- deadline, skill: 1-2 sentences
- location: 2-3 sentences
- person: 2-4 sentences
- tool: 3-5 sentences
- concept: 3-6 sentences
- project, company: 4-8 sentences (can be longer if history is rich)

Output ONLY the updated markdown body. Do not include YAML frontmatter, do not wrap in code fences, do not add commentary."""


async def _synthesize_entity_update(
    entity_name: str,
    entity_type: str,
    existing_body: str,
    new_description: str,
    new_history_entries: list[dict],
    source_reference_date: str | None,
    settings: Settings,
) -> str | None:
    """Call the LLM to merge an existing entity body with new extraction info."""
    if not existing_body.strip() and not new_description.strip():
        return None

    prompt = _SYNTHESIS_PROMPT.format(
        entity_name=entity_name,
        entity_type=entity_type,
        existing_body=existing_body[:6000] or "(empty)",
        new_description=new_description or "(none)",
        new_history=json.dumps(new_history_entries) if new_history_entries else "[]",
        source_reference_date=source_reference_date or "unknown",
    )
    response = await litellm.acompletion(
        model=settings.litellm_model,
        messages=[{"role": "user", "content": prompt}],
    )
    body = response.choices[0].message.content or ""
    body = body.strip()
    if body.startswith("```"):
        # Strip stray code fences
        body = body.strip("`")
        if body.lower().startswith("markdown"):
            body = body[len("markdown"):]
        body = body.strip()
    return body or None


_CONTRADICTION_PROMPT = """You are checking whether two descriptions of the same entity contain an unresolvable contradiction.

A contradiction is unresolvable when newer information alone does not make it obvious which statement is currently true. For example: two different stacks mentioned across two conversations with no date cue, or two different roles for the same person.

ENTITY: {entity_name}

EXISTING DESCRIPTION:
{existing_body}

NEW DESCRIPTION:
{new_description}

Respond with JSON only:
{{
  "has_unresolvable_contradiction": true | false,
  "contradiction": "one-sentence description of the contradiction, or empty",
  "options": ["Option A matching an existing claim", "Option B matching the new claim", "Both are true (different contexts)"]
}}

If there is no contradiction, set has_unresolvable_contradiction to false and options to []."""


async def _detect_contradiction(
    entity_name: str,
    existing_body: str,
    new_description: str,
    settings: Settings,
) -> dict | None:
    """Call the LLM to check whether existing and new descriptions contradict."""
    prompt = _CONTRADICTION_PROMPT.format(
        entity_name=entity_name,
        existing_body=existing_body[:4000],
        new_description=new_description[:2000],
    )
    response = await litellm.acompletion(
        model=settings.litellm_model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    return json.loads(raw)
