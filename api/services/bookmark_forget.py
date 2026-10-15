"""Remove a bookmark from Cicada on the person's click (G191 v3, owner 2026-10-15).

The menu bar's bookmark history opens a bookmark's page in the app, where the person can remove it. Cicada forgets it
the way it already forgets a bookmark the person removed in the browser (G129 slice 2's ``remove`` answer): the media
page is **archived, never deleted** (it may be claim-linked; git keeps every version), and the bookmark's episode is
stamped ``source_deleted_at`` — the tombstone every source-keyed writer uses for a deletion, never an unlink. The
person's earlier answers stay on the episode: what they once said about it is still what they said.

The browser's own copy is the app's business: the backend never opens a browser or its files (the ``~/Library``
rail). The app removes it from Chrome through Apple Events after asking, and says Safari cannot be edited by another
app. A link saved again later comes back (``bookmark_sync._revive``).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from api.services import episode_ids, episode_staging, markdown_parser, saved_why

#: The commit trigger.
TRIGGER = "user/bookmark_remove"
#: The stamp on the episode (``episode_staging``'s tombstone key) and on the archived page.
TOMBSTONE = "source_deleted_at"


def forget(memory_path: Path, *, url: str) -> dict:
    """Archive the saved link's media page and tombstone its episode. Returns ``episode_id``, ``media_entity_id``,
    ``status`` and ``paths`` (memory-relative, what changed — the caller commits them inside its write admission).
    :class:`saved_why.SavedWhyError` 404 for a link Cicada does not hold, 422 for a URL that is not one."""
    memory_path = Path(memory_path)
    episode_id, media_entity_id, path = saved_why.find_episode(memory_path, url)
    now = episode_ids.utc_now_seconds()
    paths: list[str] = []
    entity_path = memory_path / "entities" / f"{media_entity_id}.md"
    if media_entity_id and entity_path.is_file():
        parsed = markdown_parser.parse(entity_path)
        fm = dict(parsed.frontmatter)
        if str(fm.get("status") or "active") not in ("archived", "dropped"):
            fm["status"] = "archived"
            fm["last_referenced"] = str(date.today())
            fm["removed_at"] = now
            markdown_parser.write(entity_path, fm, parsed.body)
            paths.append(f"entities/{media_entity_id}.md")
    if _tombstone(path, now):
        paths.append(f"episodes/{episode_id}.md")
    return {"episode_id": episode_id, "media_entity_id": media_entity_id, "status": "archived", "paths": paths}


def _tombstone(path: Path, at: str) -> bool:
    """Stamp ``source_deleted_at`` unless the episode already carries one. Frontmatter only: the body, its hash and
    every evidence span into it stay as they were, and the queue is untouched (nothing new was said)."""
    with episode_staging.STAGE_LOCK, episode_ids.episode_lock(Path(path).parent):
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        if fm.get(TOMBSTONE):
            return False
        fm[TOMBSTONE] = at
        if "turns" in fm:
            fm["turns"] = fm.pop("turns")  # R-PB4: the sidecar stays the last key
        markdown_parser.write(path, fm, parsed.body)
        return True


def clear_removed(path: Path) -> bool:
    """The link was saved again: the episode loses its removal stamp. Returns whether it changed."""
    with episode_staging.STAGE_LOCK, episode_ids.episode_lock(Path(path).parent):
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        if not fm.get(TOMBSTONE):
            return False
        fm.pop(TOMBSTONE, None)
        markdown_parser.write(path, fm, parsed.body)
        return True


def commit_message(paths: list[str]) -> str:
    from api.services import git_service

    return git_service.build_commit_message(
        "Removed a bookmark", [f"{p}: updated (trigger: {TRIGGER})" for p in paths],
        authors=[git_service.USER_AUTHOR])
