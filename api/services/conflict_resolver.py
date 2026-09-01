"""Stage 3: Conflict Resolution & Temporal Decay."""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import litellm
from loguru import logger
from tqdm import tqdm

from api.config import Settings
from api.models.schemas import DecayClass
from api.services import decay_policy, engine_errors, entity_body, json_parse, markdown_parser
from api.services.providers import resolve_llm_fn

# Confidence floor a decaying/archived entity is restored to when it is
# mentioned again (G66 §1.6) — high enough to clear `decay_nudge_threshold`
# (0.4) and `archive_threshold` (0.2) with room to spare, low enough that a
# single passing mention doesn't outrank a well-established belief.
RECOVERY_CONFIDENCE = 0.6

# G85 §2 / Wave-1 1.8: a single decay pass never charges more than one
# week's worth of decay, regardless of how many days have actually elapsed
# since the baseline. `decay_rate` is defined per-week, so a week is the
# natural unit. This is a safety rail INDEPENDENT of the one-shot
# `decayed_through` backfill migration (`decay_migration.py`) — a future gap
# (a paused schedule, a laptop off for a month, an engine outage) must
# degrade gracefully over several cycles instead of charging the whole gap
# as if it were user disinterest in one cliff. The watermark advances by
# only the CAPPED amount, so the remaining "debt" persists and gets worked
# off on subsequent cycles rather than being silently dropped.
MAX_DECAY_DAYS_PER_CYCLE = 7


async def resolve_and_prune(
    resolved: list[dict], existing: list[dict], settings: Settings, *, now: datetime | None = None
) -> list[dict]:
    """Apply conflict resolution and temporal decay to all entities.

    ``now``: decay reference time; defaults to ``datetime.now()``. Mirrors
    ``claim_reconciler.reconcile_stage3``'s ``now_date`` — injectable so a test
    can simulate elapsed time without monkeypatching the stdlib clock.
    """
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
        except engine_errors.EngineError:
            # G74(a), M2: an ENGINE failure is not "nothing to synthesize" —
            # flattening it here let a partial throttle silently skip
            # synthesis for every entity while the cycle still committed and
            # reported "Completed". Propagate so the cycle stops with the
            # episode queue intact, same contract as the resolver's judge.
            raise
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
        except engine_errors.EngineError:
            # Same reasoning as the synthesis branch above: an engine failure
            # must not be read as "no contradiction found".
            raise
        except Exception as e:
            logger.debug(f"Contradiction check failed for {entity_id}: {e}")
            contradiction = None

        if contradiction and contradiction.get("has_unresolvable_contradiction"):
            conflicts_found += 1
            progress.set_postfix_str(f"conflicts={conflicts_found}", refresh=False)
            today_str = str(date.today())
            built = build_entity_question(entity_name, contradiction, today_str)
            changes.append({
                "id": entity_id,
                "action": "conflict_nudge",
                "entity": new_entity,
                "conflict_context": contradiction.get("contradiction", ""),
                "predicate": "description",
                "question": built["question"],
                "options": built["options"],
                "allow_other": True,
                "allow_defer": True,
                "source_episode": change.get("source_episode", ""),
                "trigger": "sleep/conflict_resolution",
            })

    progress.close()

    # Temporal decay for unreferenced entities. The per-week rate and the class
    # both come from `decay_policy.resolve` — evergreen entities are skipped.
    now = now or datetime.now()
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
        decay_class, decay_rate = decay_policy.resolve(fm)
        if decay_class is DecayClass.evergreen:
            # An artifact, not a belief: it does not become less true by going
            # unmentioned. No decay math, no decay nudge, never auto-archived.
            continue
        # G85 §2 / Wave-1 1.1: decay must be charged exactly once per elapsed
        # interval. The write branch below stamps `decayed_through` on every
        # decay pass; read it back here and measure `days_since` from
        # whichever is more recent — `last_referenced` (moved forward by an
        # actual re-mention) or `decayed_through` (moved forward by the last
        # decay pass itself, referenced or not). Without this, an unreferenced
        # entity's `last_referenced` never advances and every Sleep run
        # re-subtracts the SAME full interval from the already-decayed value.
        baseline = _max_date(
            _extract_date_string(fm.get("last_referenced")),
            _extract_date_string(fm.get("decayed_through")),
        )
        days_since = _days_since_last_referenced(baseline, now)
        if days_since is None:
            # Fallback: single step if we cannot determine last reference
            decay_amount = decay_rate
            decay_today = now.date().isoformat()
        else:
            # Wave-1 1.8: cap the charge at MAX_DECAY_DAYS_PER_CYCLE and
            # advance the watermark by only that capped amount — a long gap
            # (outage, paused schedule) works off gradually over several
            # cycles instead of hitting the whole gap in one.
            charged_days = min(days_since, MAX_DECAY_DAYS_PER_CYCLE)
            decay_amount = decay_rate * (charged_days / 7.0)
            baseline_date = date.fromisoformat(baseline) if baseline else now.date()
            decay_today = min(
                now.date(), baseline_date + timedelta(days=charged_days)
            ).isoformat()
        new_confidence = max(0.0, confidence - decay_amount)

        if new_confidence < settings.archive_threshold:
            changes.append({
                "id": entity_id,
                "action": "archive",
                "new_confidence": new_confidence,
                "new_status": "archived",
                "source_episode": "",
                "trigger": "sleep/decay",
                "decayed_through": decay_today,
            })
        elif new_confidence < settings.decay_nudge_threshold:
            changes.append({
                "id": entity_id,
                "action": "decay_nudge",
                "new_confidence": new_confidence,
                "new_status": "decaying",
                "source_episode": "",
                "trigger": "sleep/decay",
                "decayed_through": decay_today,
            })
        else:
            changes.append({
                "id": entity_id,
                "action": "decay",
                "new_confidence": new_confidence,
                "new_status": status,
                "source_episode": "",
                "trigger": "sleep/decay",
                "decayed_through": decay_today,
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
            entity_type = entity.get("type", "concept")
            # Stage-1 may PROPOSE a class; `agent_class` re-applies the rail here
            # so an `evergreen` that slipped past extraction can never be written.
            decay_class = (
                decay_policy.agent_class(entity.get("decay_class"))
                or decay_policy.default_class_for(entity_type)
            )
            frontmatter = {
                "name": entity.get("name", entity_id.replace("-", " ").title()),
                "type": entity_type,
                "status": "active",
                "confidence": entity.get("confidence", 0.5),
                "created": created_date,
                "last_referenced": last_referenced,
                **decay_policy.frontmatter_fields(decay_class),
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

            # Recovery (G66 §1.6): a re-mention is the counter-signal to decay.
            # CLAUDE.md has always promised "if mentioned again: promoted back,
            # confidence restored" — before this, only `last_referenced` moved.
            # `dropped` is deliberately excluded: the user dismissed that entity
            # and it is never resurfaced.
            if str(parsed.frontmatter.get("status", "active")) in ("decaying", "archived"):
                parsed.frontmatter["status"] = "active"
                parsed.frontmatter["confidence"] = max(
                    float(parsed.frontmatter.get("confidence", 0.0) or 0.0),
                    RECOVERY_CONFIDENCE,
                )

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
            # G85 §2 / Wave-1 1.1: stamp the watermark so the NEXT decay pass
            # charges only the interval elapsed since today, not the whole
            # span back to `last_referenced` again. Uses the SAME reference
            # date the decay pass computed against (falls back to the real
            # today for a change dict built outside `resolve_and_prune`).
            parsed.frontmatter["decayed_through"] = change.get("decayed_through") or str(date.today())
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
        settings, model=settings.effective_consolidation_model,
        completion=litellm.acompletion, stage="merge",
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
  "question": "ONE short question, in the user's voice, that resolves it (e.g. 'Where does Rodrigo work now?'). Empty when there is no contradiction.",
  "options": [
    {{"label": "the existing claim, 1-4 words", "description": "one short clause saying where this came from and when"}},
    {{"label": "the new claim, 1-4 words", "description": "one short clause saying where this came from and when"}},
    {{"label": "Both are true (different contexts)", "description": "Keep both, each tagged with its context"}}
  ]
}}

If there is no contradiction, set has_unresolvable_contradiction to false, question to "", and options to []."""


_BOTH_OPTION = {
    "key": "both",
    "label": "Both are true (different contexts)",
    "description": "Keep both claims, each tagged with its context",
    "claim_id": None,
}


def build_entity_question(entity_name: str, raw: dict | None, today: str) -> dict:
    """Normalize an LLM contradiction payload into the G60 question object.

    The entity path has no claims behind its options (it compares page bodies),
    so every option carries ``claim_id: None`` and the item keys on the literal
    predicate ``"description"``. A missing/blank ``question`` or a flat
    ``options: [str]`` payload degrades to the deterministic template rather
    than producing a card with no question — under-specifying is safe here.
    """
    from api.services import predicates

    raw = raw or {}
    question = str(raw.get("question", "") or "").strip()
    if not question:
        question = predicates.predicate_question("description", entity_name)

    options: list[dict] = []
    for key, item in zip(("a", "b"), raw.get("options") or []):
        if isinstance(item, dict):
            label = str(item.get("label", "") or "").strip()
            description = str(item.get("description", "") or "").strip()
        else:
            label = str(item).strip()
            description = ""
        if not label or label == _BOTH_OPTION["label"]:
            continue
        options.append({
            "key": key,
            "label": label,
            "description": description or f"Described on the page as of {today}",
            "claim_id": None,
            "observed_at": today,
            "last_referenced": today,
        })

    options.append(dict(_BOTH_OPTION))
    return {"question": question, "options": options}


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
        settings, model=settings.effective_consolidation_model,
        completion=litellm.acompletion, stage="conflict",
    )
    response = await llm_fn(
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    return json_parse.parse_json_object(raw)
