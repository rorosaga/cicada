"""Stage 5: Inbox Generation, Clarification Queue & Versioning."""

from datetime import date
from pathlib import Path

import yaml

from api.services import decay_policy, inbox_questions, markdown_parser, predicates
from api.services.conflict_resolver import apply_changes
from api.services.id_utils import sanitize_id

# Options with no claim behind them (the synthetic "both"/"neither" rows) always
# sort last, so a merged-in competing value lands among the real answers.
_SYNTHETIC_KEYS = {"both", "neither"}


def dedup_key(kind: str, fm: dict) -> tuple[str, str]:
    """The open-item identity for a kind (§2.2).

    - ``conflict``          -> ``(entity_id, predicate)``; entity-path conflicts
      carry no predicate and key on the literal ``"description"``.
    - ``clarification``     -> ``(entity_id, uncertainty_type)``
    - ``merge_suggestion``  -> the **sorted** pair of entity ids, so the same
      duplicate pair keys identically regardless of which side was seen first.
    - anything else         -> ``(entity_id, "")``
    """
    entity_id = str(fm.get("entity_id", "") or "")
    if kind == "conflict":
        return (entity_id, str(fm.get("predicate", "") or "description"))
    if kind == "clarification":
        return (entity_id, str(fm.get("uncertainty_type", "") or ""))
    if kind == "merge_suggestion":
        other = str(fm.get("merge_target_hint", "") or "")
        pair = sorted([entity_id, other])
        return (pair[0], pair[1])
    return (entity_id, "")


def find_open(
    memory_path: Path, kind: str, entity_id: str, predicate: str | None = None
) -> Path | None:
    """Return the open (``status: pending``) item of ``kind`` on the same key.

    ``predicate`` carries the second key component for every kind: the
    predicate for conflicts, the uncertainty type for clarifications, the OTHER
    entity id for merge suggestions. Returns the OLDEST match (lowest inbox
    number) so a collision always merges into the original question.
    """
    inbox_dir = memory_path / "inbox"
    if not inbox_dir.exists():
        return None
    target = dedup_key(
        kind,
        {
            "entity_id": entity_id,
            "predicate": predicate,
            "uncertainty_type": predicate,
            "merge_target_hint": predicate,
        },
    )
    for filepath in sorted(inbox_dir.glob("inbox-*.md")):
        try:
            fm = markdown_parser.parse(filepath).frontmatter
        except Exception:
            continue
        if str(fm.get("kind", "")) != kind:
            continue
        if str(fm.get("status", "pending") or "pending") != "pending":
            continue
        if dedup_key(kind, fm) == target:
            return filepath
    return None


def merge_options_into(path: Path, new_options: list[dict], today: str) -> bool:
    """Merge competing values into an already-open question (§2.2).

    A value already present (matched case-insensitively on ``label``) has its
    ``last_referenced`` bumped and its ``claim_id`` refreshed; a value not
    present is appended with a fresh unique key, ahead of the synthetic
    ``both``/``neither`` rows. ``question`` and ``created_date`` are preserved;
    ``updated_date`` is set to ``today``. Returns whether anything changed.
    """
    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter
    existing = inbox_questions.normalize_options(fm.get("options"))
    by_label = {str(o.get("label", "")).strip().lower(): o for o in existing}
    used_keys = {str(o.get("key", "")) for o in existing}
    changed = False

    for incoming in inbox_questions.normalize_options(new_options):
        label = str(incoming.get("label", "")).strip()
        if not label:
            continue
        current = by_label.get(label.lower())
        if current is not None:
            bumped = incoming.get("last_referenced") or incoming.get("observed_at")
            if bumped and str(bumped) > str(current.get("last_referenced") or ""):
                current["last_referenced"] = str(bumped)
                changed = True
            # Always adopt the incoming claim id, never only when missing:
            # Stage-1 claim ids are date-keyed, so the same value re-mentioned
            # on a later day arrives as a DIFFERENT open claim. Keeping the old
            # (often already-closed) id would leave the option ageing forever
            # while being mentioned daily, and would make a later resolution
            # close a dead claim while the live one stayed open.
            if incoming.get("claim_id") and incoming["claim_id"] != current.get(
                "claim_id"
            ):
                current["claim_id"] = incoming["claim_id"]
                changed = True
            continue
        option = dict(incoming)
        key = str(option.get("key", "")) or "x"
        while key in used_keys:
            key += "x"
        option["key"] = key
        used_keys.add(key)
        existing.append(option)
        by_label[label.lower()] = option
        changed = True

    if not changed:
        return False

    real = [o for o in existing if str(o.get("key")) not in _SYNTHETIC_KEYS]
    synthetic = [o for o in existing if str(o.get("key")) in _SYNTHETIC_KEYS]
    fm["options"] = real + synthetic
    fm["updated_date"] = today
    markdown_parser.write(path, fm, parsed.body)
    return True


def _refresh_hint(path: Path, hint: str | None) -> None:
    """Refresh the ``hint`` on an already-open item after a merge (G61).

    A merge-on-collision keeps the original item, so a source added after it
    was first written would otherwise never surface. ``None`` leaves the
    existing hint untouched — a merge with no computable hint should not
    erase one set by an earlier cycle.
    """
    if hint is None:
        return
    parsed = markdown_parser.parse(path)
    if parsed.frontmatter.get("hint") == hint:
        return
    parsed.frontmatter["hint"] = hint
    markdown_parser.write(path, parsed.frontmatter, parsed.body)


async def generate(
    changes: list[dict],
    skills: list[dict],
    memory_path: Path,
    relationships: list[dict] | None = None,
) -> None:
    """Generate inbox items, apply entity changes, persist relationships."""
    inbox_dir = memory_path / "inbox"
    entities_dir = memory_path / "entities"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    # Apply entity file changes (create, update, archive, decay)
    apply_changes(changes, memory_path)

    # Persist relationships to graph_edges.yaml (merge with existing)
    if relationships:
        _write_graph_edges(memory_path, relationships)

    # Also update each entity's `related` field based on new relationships
    if relationships:
        _update_related_fields(entities_dir, relationships)

    # Generate inbox items for decay and conflict changes. Seed from max-id+1
    # so deletions (resolved items) never cause an id collision — the old bug
    # used len(glob), which reset after files were removed.
    next_num = _next_inbox_num(inbox_dir)

    for change in changes:
        action = change.get("action", "")

        if action == "decay_nudge":
            entity_id = change["id"]
            entity_path = entities_dir / f"{entity_id}.md"
            entity_name = entity_id.replace("-", " ").title()
            if entity_path.exists():
                parsed = markdown_parser.parse(entity_path)
                entity_name = parsed.frontmatter.get("name", entity_name)

            item_id = f"inbox-{next_num:03d}"
            next_num += 1
            new_confidence = float(change.get("new_confidence", 0) or 0)
            frontmatter = {
                "kind": "decay",
                "required_input": "choice",
                "status": "pending",
                "priority": new_confidence,
                "entity_id": entity_id,
                "entity_name": entity_name,
                "title": f"No recent mentions of {entity_name}",
                "created_date": str(date.today()),
                "options": None,
            }
            body = (
                f"{entity_name} hasn't been mentioned recently and its confidence "
                f"has dropped to {new_confidence:.2f}. "
                f"Should we keep tracking it or archive it?"
            )
            markdown_parser.write(inbox_dir / f"{item_id}.md", frontmatter, body)

        elif action == "conflict_nudge":
            entity_id = change["id"]
            entity_name = change.get("entity", {}).get("name", entity_id.replace("-", " ").title())
            hint = None
            try:
                from api.services import fact_sources

                # Entity-path conflicts carry no predicate (key on the literal
                # "description"), so ANY url-kind source is a match here.
                hint = fact_sources.hint_for(memory_path, entity_id, "description")
            except Exception:
                hint = None
            open_path = find_open(memory_path, "conflict", entity_id, "description")
            if open_path is not None:
                merge_options_into(open_path, change.get("options") or [], str(date.today()))
                _refresh_hint(open_path, hint)
                continue
            item_id = f"inbox-{next_num:03d}"
            next_num += 1
            frontmatter = {
                "kind": "conflict",
                "required_input": "choice",
                "status": "pending",
                "priority": 0.8,
                "entity_id": entity_id,
                "entity_name": entity_name,
                "title": change.get("question") or f"Conflicting information about {entity_name}",
                "created_date": str(date.today()),
                "options": change.get("options", []),
                "predicate": "description",
                "question": change.get("question"),
                "allow_other": True,
                "allow_defer": True,
                "hint": hint,
                # G97: `conflict_resolver` already puts the raising episode on
                # the change (`conflict_resolver.py:137`); the entity path used
                # to drop it at the write, so the card had no cause to show.
                "source_episode": change.get("source_episode") or None,
            }
            body = change.get("conflict_context", f"New information conflicts with existing data for {entity_name}.")
            markdown_parser.write(inbox_dir / f"{item_id}.md", frontmatter, body)

    # Create skill entities — sanitize_id keeps skills in lockstep with the
    # entity path so names like "AI/ML project framing" don't try to write to
    # a non-existent `ai/` subdirectory and crash Stage 5.
    for skill in skills:
        skill_id = sanitize_id(skill["name"])
        skill_path = entities_dir / f"{skill_id}.md"
        if not skill_path.exists():
            frontmatter = {
                "name": skill["name"],
                "type": "skill",
                "status": "active",
                "confidence": skill.get("confidence", 0.5),
                "created": str(date.today()),
                "last_referenced": str(date.today()),
                **decay_policy.frontmatter_fields(
                    decay_policy.default_class_for("skill")
                ),
                "source_episodes": [],
                "tags": [],
                "related": [],
                "version": 1,
            }
            markdown_parser.write(skill_path, frontmatter, skill.get("description", ""))


def write_claim_nudges(nudges: list[dict], memory_path: Path) -> dict:
    """Fold M5f Stage-3 claim-reconciler nudges into the inbox (additive).

    The claim reconciler (``claim_reconciler.reconcile_stage3``) emits nudges in
    the inbox-generator change shape: ``conflict_nudge`` (hard, single-valued
    contradiction), ``divergence_nudge`` (soft — an agent extraction disagrees
    with a protected human claim; the human stays authoritative), and
    ``normalization_audit`` (a predicate was auto-folded — D2 mandatory). Plus the
    per-epistemic decay ``decay_nudge``. This writer turns each into a companion-app
    inbox item, **reusing the same ``inbox-NNN`` allocator** so it never collides
    with the legacy entity-path nudges written earlier in the same Stage 5.

    Returns ``{"written": n, "merged": m, "skipped_multi_valued": s}`` —
    ``written`` counts inbox items newly created, ``merged`` counts conflict
    nudges folded into an already-open item on the same ``(entity, predicate)``
    key instead of spawning a duplicate, and ``skipped_multi_valued`` counts
    conflict nudges dropped by the G98 rule below. A subject without an entity
    page still gets a nudge (the page may be promoted next cycle).
    """
    if not nudges:
        return {"written": 0, "merged": 0, "skipped_multi_valued": 0}
    inbox_dir = memory_path / "inbox"
    entities_dir = memory_path / "entities"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    next_num = _next_inbox_num(inbox_dir)
    written = 0
    merged = 0
    skipped_multi = 0

    for nudge in nudges:
        action = nudge.get("action", "")
        entity_id = str(nudge.get("id", "") or "")
        entity_name = nudge.get("entity", {}).get(
            "name", entity_id.replace("-", " ").title()
        )
        # Prefer the page's display name when it exists.
        entity_path = entities_dir / f"{entity_id}.md"
        if entity_path.exists():
            try:
                entity_name = markdown_parser.parse(entity_path).frontmatter.get(
                    "name", entity_name
                )
            except Exception:
                pass

        hint = None
        if action == "conflict_nudge":
            predicate = str(nudge.get("predicate", "") or "description")
            try:
                from api.services import fact_sources

                hint = fact_sources.hint_for(memory_path, entity_id, predicate)
            except Exception:
                hint = None
            # G98 (2026-09-03 evidence): a predicate the vocabulary marks
            # multi-valued never opens a conflict — seven true `uses` values
            # are a set, not a contradiction. The reconciler already gates on
            # its cardinality oracle; this is the belt for a legacy caller or a
            # bank map that predates the seed. Counted, never silent.
            if predicates.cardinality(memory_path, predicate) == "multi":
                skipped_multi += 1
                continue
            open_path = find_open(memory_path, "conflict", entity_id, predicate)
            if open_path is not None:
                merge_options_into(open_path, nudge.get("options") or [], str(date.today()))
                _refresh_hint(open_path, hint)
                merged += 1
                continue
            kind, priority, required = "conflict", 0.8, "choice"
            title = nudge.get("question") or f"Conflicting beliefs about {entity_name}"
        elif action == "divergence_nudge":
            kind, priority, required = "divergence", 0.5, "choice"
            title = f"I'm reading something different about {entity_name}"
        elif action == "normalization_audit":
            kind, priority, required = "normalization", 0.3, "choice"
            title = f"Confirm a predicate fold for {entity_name}"
        elif action == "decay_nudge":
            kind, priority, required = "decay", float(
                nudge.get("new_confidence", 0) or 0
            ), "choice"
            title = f"No recent mentions of {entity_name}"
        else:
            continue

        item_id = f"inbox-{next_num:03d}"
        next_num += 1
        frontmatter = {
            "kind": kind,
            "required_input": required,
            "status": "pending",
            "priority": priority,
            "entity_id": entity_id,
            "entity_name": entity_name,
            "title": title,
            "created_date": str(date.today()),
            "options": nudge.get("options"),
            # G60 question object (present on conflicts; absent elsewhere).
            "predicate": nudge.get("predicate"),
            "question": nudge.get("question"),
            "allow_other": bool(nudge.get("allow_other", False)),
            "allow_defer": bool(nudge.get("allow_defer", False)),
            # claim provenance so the companion app can resolve a specific belief.
            "claim_id": nudge.get("claim_id"),
            "existing_claim_id": nudge.get("existing_claim_id"),
            # G97: the conversation that raised this question, persisted so the
            # card's cause survives the claim being closed later.
            "source_episode": nudge.get("source_episode"),
            "trigger": nudge.get("trigger", "sleep/conflict_resolution"),
            # G61 — which declared source refreshes this fact, "conflict"-only.
            "hint": hint,
            # G113 slice 3 — "normalization"-only; null for every other kind,
            # the same way `predicate`/`question`/`hint` already go null for
            # kinds that don't use them (`markdown_parser.write` does not
            # strip `None` values, and that's fine and consistent).
            "raw_predicate": nudge.get("raw_predicate"),
            "canonical_predicate": nudge.get("canonical_predicate"),
        }
        body = nudge.get("conflict_context") or (
            f"{entity_name} hasn't been mentioned recently; confidence dropped to "
            f"{float(nudge.get('new_confidence', 0) or 0):.2f}."
            if action == "decay_nudge"
            else f"Review beliefs about {entity_name}."
        )
        markdown_parser.write(inbox_dir / f"{item_id}.md", frontmatter, body)
        written += 1

    return {"written": written, "merged": merged, "skipped_multi_valued": skipped_multi}


def _write_graph_edges(memory_path: Path, new_edges: list[dict]) -> None:
    """Merge new edges into graph_edges.yaml (dedup by source+target+label)."""
    edges_file = memory_path / "graph_edges.yaml"

    existing_edges: list[dict] = []
    if edges_file.exists():
        try:
            data = yaml.safe_load(edges_file.read_text(encoding="utf-8")) or {}
            existing_edges = data.get("edges", [])
        except Exception:
            existing_edges = []

    # Dedup by (source, target, label)
    seen: set[tuple[str, str, str]] = set()
    merged: list[dict] = []
    for edge in existing_edges + new_edges:
        key = (edge.get("source", ""), edge.get("target", ""), edge.get("label", "").lower())
        if key not in seen:
            seen.add(key)
            merged.append({
                "source": edge.get("source", ""),
                "target": edge.get("target", ""),
                "label": edge.get("label", "related to"),
            })

    edges_file.write_text(
        yaml.dump({"edges": merged}, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _update_related_fields(entities_dir: Path, relationships: list[dict]) -> None:
    """Update each entity's `related` frontmatter field based on new relationships."""
    # Build map of entity_id -> set of related IDs
    related_map: dict[str, set[str]] = {}
    for rel in relationships:
        src = rel.get("source", "")
        tgt = rel.get("target", "")
        if src and tgt:
            related_map.setdefault(src, set()).add(tgt)
            related_map.setdefault(tgt, set()).add(src)

    for entity_id, related_ids in related_map.items():
        filepath = entities_dir / f"{entity_id}.md"
        if not filepath.exists():
            continue
        parsed = markdown_parser.parse(filepath)
        existing_related = set(parsed.frontmatter.get("related", []) or [])
        updated = sorted(existing_related | related_ids)
        parsed.frontmatter["related"] = updated
        markdown_parser.write(filepath, parsed.frontmatter, parsed.body)


def _next_inbox_num(inbox_dir: Path) -> int:
    """Next inbox number = max existing number + 1 (never count-based)."""
    max_num = 0
    for filepath in inbox_dir.glob("inbox-*.md"):
        try:
            max_num = max(max_num, int(filepath.stem.split("-")[-1]))
        except ValueError:
            continue
    return max_num + 1
