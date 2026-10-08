"""G112 (1): a skill Stage 4 detects becomes a page with provenance, or no page.

Stage 4 (``skill_extractor.detect_patterns``) answers ``{name, description, evidence_entities, confidence}``. The old
writer (``inbox_generator.generate``) kept the name and the description and dropped the rest: every skill page was
born with ``source_episodes: []``, ``created`` = the day the cycle ran, no section provenance and no ``related``; it
was written only when absent, so a pattern detected again never moved its page, and the spacing factor of decay (G147,
``decay_policy.mention_weeks``) read zero weeks from it forever.

Here the answer becomes an ordinary Stage-5 change, written by ``conflict_resolver.apply_changes`` like any page
Stage 1 found — no new writer, no model call:

* **Evidence.** Each ``evidence_entities`` name is matched, without a model, to the conversations of THIS batch it was
  extracted from (Stage 1's names, Stage 2's ``name_to_id``, the change's own ``source_episodes``). The conversations
  kept are those where at least two of the named entities came up together (one when the skill names one), which is
  what the detection prompt was asked to see. A skill none of whose evidence came up in this batch is written
  NOWHERE: it fails the prompt's own contract ("clear evidence from multiple conversations"), and a later batch that
  shows the pattern with evidence writes it then.
* **Dates.** ``created`` / ``last_referenced`` come from those conversations' timestamps (``apply_changes``'s
  rule for every page); a memory export entry gives none (``untimed``).
* **Provenance.** The summary's section-provenance row cites each of those conversations as ``reasoning``: the
  skill is an inference across them, never a quotation of one (G118 R6).
* **Related.** Each evidence entity with a page gets a ``draws on`` edge, so ``related`` names it.
* **Again.** A skill whose name is already a ``type: skill`` page updates that page — sources merged,
  last mention moved, a decaying page recovered — instead of being a silent no-op. A page of another type, an
  installed agent skill's page (``skill_tag``), a dropped page, or a page another change of this batch already
  writes is left alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from api.services import evidence, markdown_parser, section_provenance
from api.services.id_utils import build_name_index, resolve_entity_id, sanitize_id
from api.services.skill_tag import is_agent_skill

TRIGGER = "sleep/skills"
EDGE_LABEL = "draws on"


@dataclass
class _Episode:
    timestamp: str | None = None
    untimed: bool = True
    names: set[str] = field(default_factory=set)   # lowercased Stage-1 names
    ids: set[str] = field(default_factory=set)     # the page ids those names resolved to


def _episode_index(extracted: list[dict], name_to_id: dict[str, str]) -> dict[str, _Episode]:
    index: dict[str, _Episode] = {}
    for extraction in extracted or []:
        ep_id = str(extraction.get("episode_id") or "")
        if not ep_id:
            continue
        ep = index.setdefault(ep_id, _Episode())
        for entity in extraction.get("entities", []) or []:
            name = str(entity.get("name") or "").strip()
            if not name:
                continue
            ep.names.add(name.lower())
            ep.ids.add(name_to_id.get(name.lower()) or sanitize_id(name))
            # Every entity of one conversation carries that conversation's timing (`entity_extractor`).
            if not entity.get("untimed"):
                ep.untimed = False
                ep.timestamp = ep.timestamp or entity.get("source_episode_timestamp")
    return index


def _reasoning_rows(memory_path: Path, episode_ids: list[str]) -> list[dict]:
    """One ``reasoning`` row per conversation, with the hash of its text so a reader can still open it (R6). A
    conversation whose file cannot be read is not cited — a row without its hash is not a valid record."""
    rows = []
    for ep_id in episode_ids:
        text = evidence.source_text(memory_path, ep_id)
        if text is not None:
            rows.append(evidence.reasoning(ep_id, hash=evidence.body_hash(text)).to_dict())
    return rows


def _evidence_ids(name: str, name_to_id: dict[str, str], name_index: dict[str, str], entities_dir: Path) -> set[str]:
    key = name.strip().lower()
    ids = {sanitize_id(name)}
    if key in name_to_id:
        ids.add(name_to_id[key])
    resolved = resolve_entity_id(entities_dir, name, name_index)
    if resolved:
        ids.add(resolved)
    return ids


def ground(
    skills: list[dict],
    changes: list[dict],
    extracted: list[dict],
    memory_path: Path,
    *,
    name_to_id: dict[str, str] | None = None,
) -> list[dict]:
    """Stage 4's answer as ``create``/``update`` changes for ``apply_changes``; the ungrounded ones are dropped
    (logged as a count). Each change carries ``evidence_ids`` for :func:`edges`. Reads the bank, writes nothing."""
    name_to_id = {str(k).lower(): v for k, v in (name_to_id or {}).items()}
    entities_dir = Path(memory_path) / "entities"
    name_index = build_name_index(entities_dir)
    episodes = _episode_index(extracted, name_to_id)
    written_ids = {c.get("id") for c in changes if c.get("action") in ("create", "update")}
    created_ids = {c.get("id") for c in changes if c.get("action") == "create"}
    change_eps: dict[str, set[str]] = {}
    for c in changes:
        if c.get("action") in ("create", "update"):
            eps = set(c.get("source_episodes") or []) | ({c["source_episode"]} if c.get("source_episode") else set())
            change_eps.setdefault(c["id"], set()).update(e for e in eps if e in episodes)

    known_ids = set(name_index.values()) | created_ids
    out: dict[str, dict] = {}
    ungrounded = skipped = 0
    for skill in skills or []:
        if not isinstance(skill, dict):
            continue
        name = str(skill.get("name") or "").strip()
        description = str(skill.get("description") or "").strip()
        if not name or not description:
            continue
        support: dict[str, set[int]] = {}
        evidence_ids: set[str] = set()
        hits = 0
        named = skill.get("evidence_entities") or []
        for i, raw in enumerate([named] if isinstance(named, str) else named if isinstance(named, list) else []):
            ev_name = str(raw or "").strip()
            if not ev_name:
                continue
            ids = _evidence_ids(ev_name, name_to_id, name_index, entities_dir)
            seen = {ep_id for ep_id, ep in episodes.items() if ev_name.lower() in ep.names or ids & ep.ids}
            for ev_id in ids:
                seen |= change_eps.get(ev_id, set())
            if not seen:
                continue
            hits += 1
            for ep_id in seen:
                support.setdefault(ep_id, set()).add(i)
            evidence_ids |= ids & known_ids
        need = min(2, hits)
        chosen = sorted(ep_id for ep_id, by in support.items() if need and len(by) >= need)
        if not chosen:
            ungrounded += 1
            continue

        target = resolve_entity_id(entities_dir, name, name_index)
        action = "create"
        if target is not None:
            fm = markdown_parser.parse(entities_dir / f"{target}.md").frontmatter or {}
            if str(fm.get("type") or "") != "skill" or is_agent_skill(fm) or fm.get("status") == "dropped":
                skipped += 1
                continue
            action = "update"
        skill_id = target or sanitize_id(name)
        if skill_id in written_ids:
            skipped += 1
            continue

        timed = [ep_id for ep_id in chosen if not episodes[ep_id].untimed]
        stamps = sorted({episodes[ep_id].timestamp for ep_id in timed if episodes[ep_id].timestamp})
        rows = _reasoning_rows(memory_path, chosen)
        try:
            confidence = min(1.0, max(0.0, float(skill.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        evidence_ids.discard(skill_id)
        prior = out.get(skill_id)
        if prior is not None:   # two answers of one batch landing on one page: one change, both credits
            prior["source_episodes"] = sorted(set(prior["source_episodes"]) | set(chosen))
            prior["source_episode_timestamps"] = sorted(set(prior["source_episode_timestamps"]) | set(stamps))
            prior["evidence_ids"] = sorted(set(prior["evidence_ids"]) | evidence_ids)
            prior["untimed"] = prior["untimed"] and not timed
            continue
        out[skill_id] = {
            "id": skill_id,
            "action": action,
            "entity": {
                "name": name, "type": "skill", "summary": description, "description": description,
                "confidence": confidence, "tags": [], "aliases": [],
                section_provenance.INPUTS: [
                    {"field": "summary", "text": description, "evidence": rows},
                    {"field": "description", "text": description, "evidence": rows},
                ] if rows else [],
            },
            "source_episode": chosen[-1],
            "source_episodes": chosen,
            "source_episode_timestamp": stamps[-1] if stamps else None,
            "source_episode_timestamps": stamps,
            "untimed": not timed,
            "trigger": TRIGGER,
            "evidence_ids": sorted(evidence_ids),
        }
    if ungrounded or skipped:
        logger.info(f"Stage 4: {ungrounded} skill(s) with no evidence in this batch not written; "
                    f"{skipped} left to the page that already holds the name")
    return list(out.values())


def edges(skill_changes: list[dict]) -> list[dict]:
    """``skill -draws on-> evidence page`` for every grounded skill (``inbox_generator._write_graph_edges`` shape)."""
    return [{"source": c["id"], "target": ev_id, "label": EDGE_LABEL}
            for c in skill_changes for ev_id in c.get("evidence_ids") or []]


def without_decay_of(changes: list[dict], skill_changes: list[dict]) -> list[dict]:
    """``changes`` less Stage 3's decay of a page a skill change of this batch writes: Stage 3 could not know Stage 4
    would find the pattern again, and a page that came up is not charged for silence (``resolve_and_prune``)."""
    ids = {c["id"] for c in skill_changes}
    return [c for c in changes if not (c.get("id") in ids and c.get("trigger") == "sleep/decay")]
