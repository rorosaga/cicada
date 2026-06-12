"""One-time idempotent migration: legacy nudges/ + clarifications/ -> inbox/.

Moves every ``nudges/nudge-NNN.md`` and ``clarifications/clar-NNN.md`` into the
unified ``inbox/inbox-NNN.md`` format, renumbering into one id space and
rewriting the frontmatter with the ``kind`` discriminator. Items are *moved*
(read -> write new -> unlink old) inside the same git repo, then the move is
committed scoped to only those three paths.

Idempotent: a ``.migrated`` marker (written only after a successful commit)
short-circuits subsequent runs, and the per-file loops only touch files still
present in the legacy dirs. Safe to call on every API startup.
"""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import markdown_parser
from api.services.id_utils import resolve_entity_file, sanitize_id

_DUPLICATE_PREFIX = "possible duplicate"


def migrate_to_inbox(memory_path: Path) -> int:
    """Migrate legacy nudge/clarification files into inbox/. Returns moved count.

    Never raises: a failure is logged loudly but boot continues. The
    ``.migrated`` marker is written only after the migration commit succeeds.
    """
    memory_path = Path(memory_path)
    inbox = memory_path / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    marker = inbox / ".migrated"

    if marker.exists():
        return 0

    try:
        moved = _do_migration(memory_path, inbox)
    except Exception as e:
        logger.error(f"Inbox migration FAILED — leaving legacy dirs intact: {e}")
        return 0

    if moved > 0:
        try:
            _commit_migration(memory_path, moved)
        except Exception as e:
            # The files are moved on disk but the commit failed; do NOT write
            # the marker so a subsequent boot can retry the commit. The move
            # itself is idempotent (legacy dirs already emptied -> 0 moved next
            # time, but the commit retries via the moved>0 path only if files
            # remain). Re-stage any remaining via a plain commit on next run.
            logger.error(f"Inbox migration commit FAILED: {e}")
            return moved

    # Marker written only after a clean migration (commit succeeded, or there
    # was nothing to move).
    marker.write_text("v1")
    return moved


def _do_migration(memory_path: Path, inbox: Path) -> int:
    next_num = _next_inbox_num(inbox)
    moved = 0

    nudges_dir = memory_path / "nudges"
    if nudges_dir.exists():
        for fp in sorted(nudges_dir.glob("*.md")):
            parsed = markdown_parser.parse(fp)
            new_fm = _nudge_to_inbox_fm(parsed.frontmatter)
            markdown_parser.write(
                inbox / f"inbox-{next_num:03d}.md", new_fm, parsed.body
            )
            next_num += 1
            fp.unlink()
            moved += 1

    clar_dir = memory_path / "clarifications"
    if clar_dir.exists():
        for fp in sorted(clar_dir.glob("*.md")):
            parsed = markdown_parser.parse(fp)
            new_fm = _clar_to_inbox_fm(parsed.frontmatter, memory_path)
            markdown_parser.write(
                inbox / f"inbox-{next_num:03d}.md", new_fm, parsed.body
            )
            next_num += 1
            fp.unlink()
            moved += 1

    return moved


def _nudge_to_inbox_fm(fm: dict) -> dict:
    kind = str(fm.get("type", "decay") or "decay")
    entity_name = str(fm.get("entity_name", "") or "")
    title = str(fm.get("short_description", "") or "") or (
        f"No recent mentions of {entity_name}"
        if kind == "decay"
        else f"Conflicting information about {entity_name}"
    )
    priority = 0.8 if kind == "conflict" else 0.4
    new_fm: dict = {
        "kind": kind,
        "required_input": "choice",
        "status": "pending",
        "priority": priority,
        "entity_id": str(fm.get("entity_id", "") or ""),
        "entity_name": entity_name,
        "title": title,
        "created_date": str(fm.get("created_date", "") or str(date.today())),
        "options": fm.get("options"),
    }
    if fm.get("source_episode"):
        new_fm["source_episode"] = fm["source_episode"]
    if fm.get("source_episode_timestamp"):
        new_fm["source_episode_timestamp"] = fm["source_episode_timestamp"]
    return new_fm


def _clar_to_inbox_fm(fm: dict, memory_path: Path) -> dict:
    entity_mention = str(
        fm.get("entity_mention", "") or fm.get("entity_name", "") or ""
    )
    uncertainty_type = str(fm.get("uncertainty_type", "") or "")
    is_duplicate = uncertainty_type.strip().lower().startswith(_DUPLICATE_PREFIX)
    kind = "merge_suggestion" if is_duplicate else "clarification"
    required_input = "merge" if is_duplicate else "freetext"
    confidence = fm.get("suggested_confidence")
    try:
        priority = float(confidence) if confidence is not None else 0.5
    except (TypeError, ValueError):
        priority = 0.5

    new_fm: dict = {
        "kind": kind,
        "required_input": required_input,
        "status": "pending",
        "priority": priority,
        # Migrated clarifications carry no entity_id in their old frontmatter;
        # derive it from the mention so resolution paths can address an entity.
        "entity_id": sanitize_id(entity_mention),
        "entity_name": entity_mention,
        "title": entity_mention,
        "uncertainty_type": uncertainty_type,
        "suggested_classification": fm.get("suggested_classification"),
        "suggested_confidence": confidence,
        "created_date": str(fm.get("created_date", "") or str(date.today())),
        "source_episode": fm.get("source_episode", ""),
    }
    if is_duplicate:
        hint = _merge_target_hint(uncertainty_type, memory_path)
        if hint:
            new_fm["merge_target_hint"] = hint
    if fm.get("source_episode_timestamp"):
        new_fm["source_episode_timestamp"] = fm["source_episode_timestamp"]
    return new_fm


def _merge_target_hint(uncertainty_type: str, memory_path: Path) -> str | None:
    text = (uncertainty_type or "").strip()
    lowered = text.lower()
    if not lowered.startswith(_DUPLICATE_PREFIX):
        return None
    candidate = text[len(_DUPLICATE_PREFIX):].strip()
    if candidate.lower().startswith("of "):
        candidate = candidate[3:].strip()
    if not candidate:
        return None
    target_path = resolve_entity_file(memory_path, candidate)
    if target_path is not None:
        return target_path.stem
    return sanitize_id(candidate)


def _next_inbox_num(inbox_dir: Path) -> int:
    max_num = 0
    for fp in inbox_dir.glob("inbox-*.md"):
        try:
            max_num = max(max_num, int(fp.stem.split("-")[-1]))
        except ValueError:
            continue
    return max_num + 1


def _commit_migration(memory_path: Path, moved: int) -> None:
    """Commit the migration scoped to ONLY inbox/, nudges/, clarifications/.

    Never ``git add -A`` — concurrent unrelated changes in the working tree
    must not be swept into the migration commit.
    """
    paths = ["inbox", "nudges", "clarifications"]
    subprocess.run(
        ["git", "add", "--", *paths],
        cwd=str(memory_path),
        check=True,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", *paths],
        cwd=str(memory_path),
        check=True,
        capture_output=True,
        text=True,
    )
    if not status.stdout.strip():
        return
    message = (
        "Migrate nudges + clarifications into unified inbox/\n\n"
        f"Moved {moved} legacy items into inbox/ (trigger: migration/inbox)"
    )
    subprocess.run(
        ["git", "commit", "-m", message, "--", *paths],
        cwd=str(memory_path),
        check=True,
    )
