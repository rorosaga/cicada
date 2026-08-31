"""G66 §1.8 -- one-shot, idempotent backfill of ``decay_class`` into a bank.

Runs once per bank -- on API startup for the boot-time bank and on
``POST /banks/{name}/activate`` for a bank switched to at runtime (both via
``bank_migrations.run_bank_migrations``) -- guarded by a ``.decay_classed``
marker in exactly the shape ``inbox_migration.dedup_open_items`` uses. It
corrects the two populations the old hardcoded rates got wrong:

- ``type: media`` (bookmarks, saved videos, images) -> ``evergreen`` /
  ``decay_rate: 0.0``. These are ARTIFACTS, not beliefs; they never should have
  decayed. Any of them already ``decaying``/``archived`` (never ``dropped`` --
  that is a user dismissal) is restored to ``active`` with
  ``confidence = max(current, 0.7)``.
- ``type: skill`` -> ``durable``; the rate stays where it was (0.02).

Every other type keeps decaying exactly as before and its file is not touched.

Never raises: a failure is logged loudly and boot continues. The marker is
written only after a clean run (commit succeeded, or nothing needed changing),
so a failed commit retries on the next boot.

This is a SYSTEM MAINTENANCE write -- no model and no user in the loop -- so the
commit is authored by the reserved ``cicada`` literal.
"""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

from loguru import logger

from api.models.schemas import DecayClass
from api.services import decay_policy, git_service, markdown_parser

_MARKER = ".decay_classed"

# Confidence floor for a media page the old decay engine wrongly faded.
# Distinct from the entity decay engine's RECOVERY (0.6) -- this is a one-shot
# correction of a class the page should never have decayed under in the first
# place, not an ordinary re-mention recovery.
RESTORE_CONFIDENCE = 0.7

TRIGGER = "maintenance/decay_class_backfill"


def backfill_decay_classes(memory_path) -> dict:
    """Backfill one bank. Returns ``{"media": n, "skills": n, "restored": n}``."""
    memory_path = Path(memory_path)
    empty = {"media": 0, "skills": 0, "restored": 0}
    entities_dir = memory_path / "entities"
    if not entities_dir.exists():
        return empty

    marker = memory_path / _MARKER
    if marker.exists():
        return empty

    try:
        counts, written = _rewrite_pages(entities_dir)
    except Exception as e:
        logger.error(f"Decay-class backfill FAILED — leaving entities/ untouched: {e}")
        return empty

    if written:
        try:
            _commit_backfill(memory_path, counts, written)
        except Exception as e:
            # Pages are corrected on disk but the commit failed (or this isn't
            # a git repo). Do NOT write the marker: the rewrite itself is
            # idempotent (already-classed pages are skipped), so a later boot
            # retries the commit with 0 further changes.
            logger.warning(f"Decay-class backfill commit skipped: {e}")
            return counts

    marker.write_text("v1", encoding="utf-8")
    return counts


def _rewrite_pages(entities_dir: Path) -> tuple[dict, list[Path]]:
    """Rewrite the pages that need a class. Returns ``(counts, written_paths)``.

    The path list is what makes the commit honest: the migration stages and
    commits EXACTLY the files it rewrote, so a pre-existing dirty edit (a hand
    edit, or a concurrent Sleep write) under ``entities/`` is never swept into a
    ``Cicada-Author: cicada`` commit.
    """
    counts = {"media": 0, "skills": 0, "restored": 0}
    written: list[Path] = []

    for filepath in sorted(entities_dir.glob("*.md")):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue  # a malformed page is skipped, never fatal
        fm = parsed.frontmatter or {}
        if not isinstance(fm, dict):
            continue
        if decay_policy.coerce(fm.get("decay_class")) is not None:
            continue  # already classed — file-level idempotence

        entity_type = str(fm.get("type", "") or "").strip().lower()
        if entity_type == "media":
            fm.update(decay_policy.frontmatter_fields(DecayClass.evergreen))
            if str(fm.get("status", "active") or "active") in ("decaying", "archived"):
                fm["status"] = "active"
                fm["confidence"] = max(
                    float(fm.get("confidence", 0.0) or 0.0), RESTORE_CONFIDENCE
                )
                counts["restored"] += 1
            counts["media"] += 1
        elif entity_type == "skill":
            # The class is the label; the page keeps whatever rate it had (0.02).
            fm["decay_class"] = DecayClass.durable.value
            counts["skills"] += 1
        else:
            continue

        markdown_parser.write(filepath, fm, parsed.body)
        written.append(filepath)

    return counts, written


def _commit_backfill(memory_path: Path, counts: dict, written: list[Path]) -> None:
    """Commit scoped to EXACTLY the pages this migration rewrote.

    Not ``git add -A``, and not even ``-- entities`` (the old form): a
    directory pathspec commits the working-tree state of every path under it,
    which would fold an unrelated dirty page — or a concurrent Sleep write —
    into this ``cicada``-authored commit and corrupt the provenance ledger.
    ``git add`` runs first so an as-yet-untracked page is matched by the
    ``git commit`` pathspec.
    """
    # One argv per call: the live bank's whole migratable population is ~612
    # pages (~30 KB of pathspec), two orders of magnitude under ARG_MAX, and a
    # partial `git commit -- <paths>` has to name all of them in one call
    # anyway, so there is nothing to gain from chunking the staging call.
    rel = [str(p.relative_to(memory_path)) for p in written]
    if not rel:
        return
    subprocess.run(["git", "add", "--", *rel], cwd=str(memory_path), check=True)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", *rel],
        cwd=str(memory_path), check=True, capture_output=True, text=True,
    )
    if not status.stdout.strip():
        return
    message = git_service.build_commit_message(
        f"Backfill decay classes {date.today().isoformat()}",
        [
            f"entities/: {counts['media']} media page(s) -> evergreen, "
            f"{counts['skills']} skill(s) -> durable, "
            f"{counts['restored']} restored to active (trigger: {TRIGGER})"
        ],
        authors=["cicada"],
    )
    subprocess.run(
        ["git", "commit", "-m", message, "--", *rel],
        cwd=str(memory_path),
        check=True,
    )
