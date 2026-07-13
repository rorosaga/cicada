"""Stage 3: Conflict Resolution & Temporal Decay."""

import json
import sys
from datetime import date, datetime
from pathlib import Path

import litellm
from loguru import logger
from tqdm import tqdm

from api.config import Settings
from api.services import entity_body, markdown_parser
from api.services.providers import resolve_llm_fn


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
                "aliases": entity.get("aliases", []) or [],
                "related": [],
                "version": 1,
                "layout_version": 2,
            }
            body = entity_body.compose_body_v2(
                summary=_entity_summary(entity),
                key_facts=entity.get("key_facts", []) or [],
                history_entries=entity.get("history_entries", []) or [],
                related=[],
                links=entity.get("links", []) or [],
                open_questions=entity.get("open_questions", []) or [],
            )
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

            # Merge new aliases
            new_aliases = new_entity.get("aliases", []) or []
            if new_aliases or parsed.frontmatter.get("aliases"):
                existing_aliases = parsed.frontmatter.get("aliases", []) or []
                merged_aliases = list(existing_aliases)
                seen = {a.lower() for a in merged_aliases}
                for alias in new_aliases:
                    if alias and alias.lower() not in seen:
                        merged_aliases.append(alias)
                        seen.add(alias.lower())
                parsed.frontmatter["aliases"] = merged_aliases

            # M5e rule 3c (§8): on a HUMAN-EDITED page the agent may never
            # regenerate-away human prose. Detect human-editedness from the RAW
            # body (the lossy v2 lift folds non-canonical hand-added headings
            # into Key Facts, so the detector + preservation must run BEFORE the
            # lift). A page is human-edited if frontmatter says so, or the raw
            # body carries a non-canonical H2 the agent pipeline never emits.
            raw_sections = entity_body.parse_sections(parsed.body)
            human_edited = _is_human_edited(parsed.frontmatter, raw_sections)

            synthesized_body = change.get("synthesized_body")
            new_fields = {
                "summary": _entity_summary(new_entity),
                "key_facts": new_entity.get("key_facts", []) or [],
                "history_entries": new_entity.get("history_entries", []) or [],
                "links": new_entity.get("links", []) or [],
                "open_questions": new_entity.get("open_questions", []) or [],
            }
            if synthesized_body and not human_edited:
                # Agent-only page: the synthesis call returns a full v2 body;
                # re-parse so the Related reconciler runs against the canonical
                # section dict. Full synthesis behavior is unchanged here.
                sections = entity_body.parse_sections(synthesized_body)
            elif human_edited:
                # Additive-only merge over the RAW sections (preserving every
                # human-authored line, canonical or not, verbatim). The LLM
                # synthesis rewrite is suppressed entirely — the prose-level
                # mirror of "an agent claim may not close a human claim".
                sections = entity_body.merge_sections_human_safe(
                    raw_sections, new_fields, human_edited=True
                )
            else:
                # Agent-only page with no synthesis: deterministic section merge
                # over the lifted v2 sections (unchanged behavior).
                sections = entity_body.upgrade_legacy_to_v2(
                    parsed.body, str(parsed.frontmatter.get("type", "concept"))
                )
                sections = entity_body.merge_sections_fallback(sections, new_fields)
            parsed.frontmatter["layout_version"] = 2

            # Related reconciler — rebuild the ## Related block from the
            # related slug list + graph_edges.yaml so wikilinks stay in sync.
            related_block = _reconcile_related(entity_id, parsed.frontmatter, memory_path)
            if related_block:
                sections["Related"] = related_block
            else:
                sections.pop("Related", None)

            markdown_parser.write(
                filepath, parsed.frontmatter, entity_body.render_sections(sections)
            )

        elif action in ("decay", "decay_nudge", "archive") and filepath.exists():
            parsed = markdown_parser.parse(filepath)
            parsed.frontmatter["confidence"] = change.get("new_confidence", 0.0)
            if "new_status" in change:
                parsed.frontmatter["status"] = change["new_status"]
            markdown_parser.write(filepath, parsed.frontmatter, parsed.body)

    write_progress.close()


# ---------- Helpers ----------


def _is_human_edited(frontmatter: dict, sections: dict[str, str]) -> bool:
    """Detect a page the human authored/edited (rule 3c, §8).

    A page is treated as human-edited when EITHER the frontmatter carries an
    explicit ``human_edited: true`` flag (set by the manual-edit / companion-app
    write path) OR the lifted body contains a non-canonical hand-added H2 section
    (a heading the agent pipeline never emits). On such a page the agent merge is
    additive-only and the LLM synthesis rewrite is suppressed.
    """
    if bool((frontmatter or {}).get("human_edited", False)):
        return True
    for title in (sections or {}).keys():
        if title and title not in entity_body.CANONICAL_SECTIONS:
            return True
    return False


def _entity_summary(entity: dict) -> str:
    """The extractor's v2 output uses `summary`; older payloads use `description`."""
    return str(entity.get("summary") or entity.get("description") or "").strip()


def _reconcile_related(entity_id: str, frontmatter: dict, memory_path) -> str:
    """Rebuild the ``## Related`` block from `related` slugs + graph_edges.yaml.

    Related is a derived view — graph_edges.yaml is canonical. Display names
    are read only for the ids actually referenced, so per-entity cost stays
    proportional to its degree.
    """
    import yaml

    memory_path = Path(memory_path)
    related_slugs = frontmatter.get("related", []) or []

    edges: list[dict] = []
    edges_file = memory_path / "graph_edges.yaml"
    if edges_file.exists():
        try:
            data = yaml.safe_load(edges_file.read_text(encoding="utf-8")) or {}
            for edge in data.get("edges", []) or []:
                if edge.get("source") == entity_id:
                    edges.append(edge)
                elif edge.get("target") == entity_id:
                    # Mirror inbound edges so the block reads naturally.
                    edges.append({
                        "source": entity_id,
                        "target": edge.get("source", ""),
                        "label": edge.get("label", ""),
                    })
        except Exception:
            edges = []

    referenced = {str(e.get("target", "")) for e in edges} | {str(s) for s in related_slugs}
    id_to_name: dict[str, str] = {}
    entities_dir = memory_path / "entities"
    for ref in referenced:
        if not ref:
            continue
        filepath = entities_dir / f"{ref}.md"
        if not filepath.exists():
            continue
        try:
            fm = markdown_parser.parse(filepath).frontmatter or {}
            id_to_name[ref] = str(fm.get("name", ref.replace("-", " ").title()))
        except Exception:
            continue

    # Drop dangling references — an edge to a deleted entity shouldn't render.
    edges = [e for e in edges if str(e.get("target", "")) in id_to_name]
    related_slugs = [s for s in related_slugs if str(s) in id_to_name]
    return entity_body.render_related(related_slugs, edges, id_to_name)


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
    # Route through the provider factory (CQA-H3) so llm_mode="local" (ollama)
    # and consolidation_model overrides apply uniformly here too. completion
    # stays litellm.acompletion, so this is still awaited exactly as before.
    llm_fn = resolve_llm_fn(
        settings, model=settings.effective_consolidation_model, completion=litellm.acompletion
    )
    response = await llm_fn(
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
    llm_fn = resolve_llm_fn(
        settings, model=settings.effective_consolidation_model, completion=litellm.acompletion
    )
    response = await llm_fn(
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    return json.loads(raw)
