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

from datetime import date
from pathlib import Path

from loguru import logger

from api.services import git_service, markdown_parser
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
    must not be swept into the migration commit. Through ``git_service`` so it
    queues on the bank's one write lock (F2-back R-B1).
    """
    message = (
        "Migrate nudges + clarifications into unified inbox/\n\n"
        f"Moved {moved} legacy items into inbox/ (trigger: migration/inbox)"
    )
    git_service.commit_paths_sync(memory_path, message, ["inbox", "nudges", "clarifications"])


_DEDUP_MARKER = ".deduped"


def dedup_open_items(memory_path: Path) -> int:
    """Collapse pre-existing duplicate OPEN inbox items (G60 §2.2). Idempotent.

    Groups every ``status: pending`` item by ``(kind, dedup_key)``, keeps the
    one with the lowest inbox number (the oldest question, so ``created_date``
    and any user-visible history survive), merges every other member's options
    into it with :func:`inbox_generator.merge_options_into`, and deletes the
    rest. Commits scoped to ``inbox/`` only — never ``git add -A``.

    Never raises: a failure is logged and boot continues. Returns the number of
    duplicate files removed.
    """
    from api.services.inbox_generator import dedup_key, merge_options_into

    memory_path = Path(memory_path)
    inbox = memory_path / "inbox"
    if not inbox.exists():
        return 0
    marker = inbox / _DEDUP_MARKER
    if marker.exists():
        return 0

    try:
        groups: dict[tuple[str, tuple[str, str]], list[Path]] = {}
        for filepath in sorted(inbox.glob("inbox-*.md")):
            try:
                fm = markdown_parser.parse(filepath).frontmatter
            except Exception:
                continue
            if str(fm.get("status", "pending") or "pending") != "pending":
                continue
            kind = str(fm.get("kind", "") or "")
            if kind not in ("conflict", "clarification", "merge_suggestion"):
                continue
            groups.setdefault((kind, dedup_key(kind, fm)), []).append(filepath)

        removed = 0
        today = str(date.today())
        for (kind, _key), members in groups.items():
            if len(members) < 2:
                continue
            survivor, duplicates = members[0], members[1:]
            for dup in duplicates:
                try:
                    dup_fm = markdown_parser.parse(dup).frontmatter
                except Exception:
                    dup_fm = {}
                if kind == "conflict":
                    merge_options_into(survivor, dup_fm.get("options") or [], today)
                else:
                    parsed = markdown_parser.parse(survivor)
                    parsed.frontmatter["updated_date"] = today
                    markdown_parser.write(survivor, parsed.frontmatter, parsed.body)
                dup.unlink()
                removed += 1
    except Exception as e:
        logger.error(f"Inbox dedup FAILED — leaving inbox/ untouched: {e}")
        return 0

    if removed:
        try:
            _commit_dedup(memory_path, removed)
        except Exception as e:
            # Files are collapsed on disk but the commit failed (or this isn't
            # a git repo). Do NOT write the marker so a later boot retries; the
            # collapse itself is idempotent (0 duplicates left => 0 next time).
            logger.warning(f"Inbox dedup commit skipped: {e}")
            return removed

    marker.write_text("v1")
    return removed


def _dedup_message(removed: int) -> str:
    return git_service.build_commit_message(
        "Collapse duplicate open inbox questions",
        [f"inbox/: {removed} duplicate item(s) merged into their oldest sibling (trigger: inbox/dedup)"],
        authors=["cicada"],
    )


def _commit_dedup(memory_path: Path, removed: int) -> None:
    """Commit the dedup scoped to ONLY inbox/ (never ``git add -A``), under the
    bank's write lock (F2-back R-B1)."""
    git_service.commit_paths_sync(memory_path, _dedup_message(removed), ["inbox"])


_DECAY_DEDUP_MARKER = ".deduped_decay"


def dedup_decay_items(memory_path: Path) -> int:
    """Collapse the pile of open decay items a long drain left behind. Idempotent.

    The one-shot :func:`dedup_open_items` never looked at kind ``decay`` (and
    its marker is already set on every bank that ran it), yet before Track B
    every Sleep cycle wrote a fresh "Still tracking X?" item for each page still
    below the threshold. Groups every ``status: pending`` decay item by entity,
    keeps the oldest (the question keeps its age), folds every sibling's claim
    ids into the survivor's ``claim_ids`` and its lowest ``priority`` into it,
    and deletes the rest. Its own marker, so a bank whose earlier dedup already
    ran is still cleaned. Commits scoped to ``inbox/`` only.

    Never raises. Returns the number of duplicate files removed.
    """
    from api.services.inbox_generator import decay_claim_ids, dedup_key

    memory_path = Path(memory_path)
    inbox = memory_path / "inbox"
    if not inbox.exists():
        return 0
    marker = inbox / _DECAY_DEDUP_MARKER
    if marker.exists():
        return 0

    try:
        groups: dict[tuple[str, str], list[Path]] = {}
        for filepath in sorted(inbox.glob("inbox-*.md")):
            try:
                fm = markdown_parser.parse(filepath).frontmatter
            except Exception:
                continue
            if str(fm.get("kind", "") or "") != "decay":
                continue
            if str(fm.get("status", "pending") or "pending") != "pending":
                continue
            groups.setdefault(dedup_key("decay", fm), []).append(filepath)

        removed = 0
        today = str(date.today())
        for members in groups.values():
            if len(members) < 2:
                continue
            survivor, duplicates = members[0], members[1:]
            parsed = markdown_parser.parse(survivor)
            fm = parsed.frontmatter
            covered = decay_claim_ids(fm)
            priorities = [fm.get("priority")]
            for dup in duplicates:
                try:
                    dup_fm = markdown_parser.parse(dup).frontmatter
                except Exception:
                    dup_fm = {}
                covered += [c for c in decay_claim_ids(dup_fm) if c not in covered]
                priorities.append(dup_fm.get("priority"))
            lowest = min(
                (float(p) for p in priorities if isinstance(p, (int, float))),
                default=None,
            )
            if lowest is not None:
                fm["priority"] = lowest
            if not fm.get("claim_id") and covered:
                fm["claim_id"] = covered[0]
            extra = [c for c in covered if c != fm.get("claim_id")]
            if extra:
                fm["claim_ids"] = extra
            fm["updated_date"] = today
            markdown_parser.write(survivor, fm, parsed.body)
            for dup in duplicates:
                dup.unlink()
                removed += 1
    except Exception as e:
        logger.error(f"Decay inbox dedup FAILED — leaving inbox/ untouched: {e}")
        return 0

    if removed:
        try:
            _commit_dedup(memory_path, removed)
        except Exception as e:
            # Same contract as dedup_open_items: no marker on a failed commit.
            logger.warning(f"Decay inbox dedup commit skipped: {e}")
            return removed

    marker.write_text("v1")
    return removed


_FOLD_DEDUP_MARKER = ".deduped_normalization"


def dedup_normalization_items(memory_path: Path) -> int:
    """Clear the predicate-fold questions Sleep raised before G98/G115. Idempotent.

    Until then Stage 3 raised "Confirm a predicate fold" for a label's own slug
    (``uses dataset`` -> ``uses-dataset``, a formatting change, no fold at all)
    and once per claim for a real fold. Every ``status: pending`` normalization
    item whose two sides are the same slug is deleted — it never asked a real
    question and its claim is untouched; the rest are grouped by their
    ``(raw -> canonical)`` pair, the oldest kept (it keeps its age) with every
    sibling's claims folded into its ``covered_claims``. An item carrying no
    pair is left alone. Its own marker.

    **Admitted and isolated (review round 1, G183).** It deletes inbox files, so
    it is a write-admitted transaction: it takes the bank's write admission
    (refused while Sleep holds the pages, and a window cannot open under it),
    then the page lock, then git's write lock — the documented order — through
    its commit, so an inbox answer racing it waits and it plans on what that
    left. A busy bank (or an admission lock that cannot be opened) is deferred
    with no marker: the next activation or boot does it. **A transaction:** every file it will delete or rewrite is
    snapshotted first; a failure while changing them or committing restores
    them byte for byte (and their index entries), and the marker is written only
    after the commit. It commits exactly the files it changed — an uncommitted
    edit already on one is committed apart first, unauthored; any other inbox
    edit stays uncommitted. Never raises. Returns the number of files removed.
    """
    memory_path = Path(memory_path)
    inbox = memory_path / "inbox"
    if not inbox.exists() or (inbox / _FOLD_DEDUP_MARKER).exists():
        return 0
    try:
        return _dedup_normalization_locked(memory_path, inbox)
    except Exception as e:
        logger.error(f"Predicate-fold inbox cleanup FAILED — inbox/ restored as it was: {e}")
        return 0


def _plan_fold_cleanup(inbox: Path) -> tuple[list[Path], dict[Path, tuple[dict, str]]]:
    """What the cleanup would do, read now: files to delete, survivors to rewrite."""
    from api.services.inbox_generator import fold_claims
    from api.services.predicates import fold_key

    deletes: list[Path] = []
    rewrites: dict[Path, tuple[dict, str]] = {}
    groups: dict[tuple[str, str], list[tuple[Path, dict, str]]] = {}
    for filepath in sorted(inbox.glob("inbox-*.md")):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue
        fm = parsed.frontmatter
        if str(fm.get("kind", "") or "") != "normalization":
            continue
        if str(fm.get("status", "pending") or "pending") != "pending":
            continue
        key = fold_key(str(fm.get("raw_predicate") or ""), str(fm.get("canonical_predicate") or ""))
        if not (key[0] and key[1]):
            continue
        if key[0] == key[1]:
            deletes.append(filepath)
            continue
        groups.setdefault(key, []).append((filepath, fm, parsed.body))

    today = str(date.today())
    for members in groups.values():
        if len(members) < 2:
            continue
        (survivor, fm, body), duplicates = members[0], members[1:]
        covered = fold_claims(fm)
        for _dup, dup_fm, _ in duplicates:
            covered += [c for c in fold_claims(dup_fm) if c not in covered]
        fm = dict(fm)
        extra = [{"entity_id": e, "claim_id": c} for e, c in covered[1:]]
        if extra:
            fm["covered_claims"] = extra
        fm["updated_date"] = today
        rewrites[survivor] = (fm, body)
        deletes += [dup for dup, _, _ in duplicates]
    return deletes, rewrites


def _dedup_normalization_locked(memory_path: Path, inbox: Path) -> int:
    """Admission (refused while Sleep holds the pages), then the page lock, then
    git's write lock — the documented order — held through the commit (G183)."""
    from api.services import page_lock, write_admission

    marker = inbox / _FOLD_DEDUP_MARKER
    try:
        with write_admission.admitted(memory_path), page_lock.page_lock(memory_path), \
                git_service.write_lock(memory_path):
            return _dedup_normalization_admitted(memory_path, marker, inbox)
    except write_admission.SleepHolding:
        logger.info("Predicate-fold inbox cleanup deferred: Sleep is writing this bank")
        return 0


def _dedup_normalization_admitted(memory_path: Path, marker: Path, inbox: Path) -> int:
    if marker.exists():
        return 0
    deletes, rewrites = _plan_fold_cleanup(inbox)
    owned = list(dict.fromkeys([*deletes, *rewrites]))
    snapshot = {p: p.read_bytes() for p in owned}
    tracked = (memory_path / ".git").exists()
    rels = [p.relative_to(memory_path).as_posix() for p in owned]
    # An uncommitted edit already on a file it changes is committed apart first,
    # unauthored (`commit_touched_sync`'s `before`); nothing else in inbox/ is its.
    before = ({rel: (memory_path / rel).read_bytes() for rel in git_service.dirty_paths_sync(memory_path, *rels)}
              if owned and tracked else None)
    index = _index_entries(memory_path, rels) if owned and tracked else {}
    if any(stage != "0" for _mode, _sha, stage in index.values()):
        logger.info("Predicate-fold inbox cleanup deferred: an inbox item it would change is mid-merge")
        return 0
    head = _head(memory_path) if owned and tracked else None
    try:
        for path, (fm, body) in rewrites.items():
            markdown_parser.write(path, fm, body)
        for path in deletes:
            path.unlink()
        if owned and tracked:
            git_service.commit_touched_sync(memory_path, _dedup_message(len(deletes)), rels, before=before)
    except BaseException:
        _restore(memory_path, snapshot, index if tracked else None, head)
        raise
    try:
        marker.write_text("v1")
    except OSError as e:
        # The cleanup is committed; the next run finds nothing to do and marks it.
        logger.warning(f"Predicate-fold inbox cleanup marker not written: {e}")
    return len(deletes)


def _index_entries(memory_path: Path, rels: list[str]) -> dict[str, tuple[str, str, str]]:
    """``{rel: (mode, blob, stage)}`` for each owned path the index holds now — a
    path it does not hold is absent. Read before the transaction, so a rollback
    puts back exactly what was staged (never HEAD's entry in its place)."""
    out: dict[str, tuple[str, str, str]] = {}
    for record in git_service._git_sync(memory_path, "ls-files", "--stage", "-z", "--", *rels).split("\0"):
        if not record:
            continue
        meta, rel = record.split("\t", 1)
        mode, sha, stage = meta.split()
        out[rel] = (mode, sha, stage)
    return out


def _head(memory_path: Path) -> str | None:
    try:
        return git_service._git_sync(memory_path, "rev-parse", "-q", "--verify", "HEAD").strip() or None
    except Exception:
        return None   # an unborn branch


def _restore(memory_path: Path, snapshot: dict[Path, bytes],
             index: dict[str, tuple[str, str, str]] | None, head: str | None) -> None:
    """Put every file the cleanup touched back as it was — its bytes, and its
    index entry exactly as captured before the transaction (or its absence).

    HEAD is never moved back. The one commit that can have landed before a
    failure is the kept-apart one: it holds only edits that were already
    uncommitted on these files, never the cleanup's own change, and it stays —
    with the restored index the tree reads as before, relative to it."""
    for path, data in snapshot.items():
        path.write_bytes(data)
    if index is None or not snapshot:
        return
    try:
        for path in snapshot:
            rel = path.relative_to(memory_path).as_posix()
            if rel in index:
                mode, sha, _stage = index[rel]
                git_service._git_sync(memory_path, "update-index", "--add", "--cacheinfo", f"{mode},{sha},{rel}")
            else:
                git_service._git_sync(memory_path, "update-index", "--force-remove", "--", rel)
    except Exception as e:   # the files are back; a stale index entry is the next status's to show
        logger.warning(f"Predicate-fold inbox cleanup: index not restored: {e}")
    moved = _head(memory_path)
    if moved != head:
        logger.warning("Predicate-fold inbox cleanup failed after keeping earlier uncommitted inbox edits apart "
                       "in their own commit; that commit stands, the cleanup's change does not")
