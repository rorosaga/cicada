"""A merge closes the question it answers (owner 2026-11-06).

"Is A the same as B?" stayed open after the person (or an agent on their word) merged A into B through
``cicada_merge_pages``: the merge is the answer, yet the card sat in the inbox until Sleep's tending retired it, if
ever. The one merge primitive (:func:`entity_merge.merge_entities`) calls this, so every door that merges — the app,
MCP, the CLI, an inbox answer, a placeholder person folded into a named one, the dedup sweep — closes the same
questions in the same commit as the merge.

Only a pending ``merge_suggestion`` whose two ends are exactly the two pages (either direction, by page id or by the
name the mention was held under) is closed. A "Which X is this?" question over several pages, a clarification about one
page and every other kind are left to their own resolvers. The card leaves ``inbox/``; git keeps it, and undoing the
join restores it with the pages.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from api.services import markdown_parser
from api.services.id_utils import sanitize_id

KIND = "merge_suggestion"


def _ends(memory_path: Path, page_id: str) -> set[str]:
    """The ids a question may name this page by: its file id, its title as a held mention would be slugged, and every id
    that became it (``page_redirects.former_ids``: a question raised about a page merged away earlier still names it by
    that id — "A or P?" after A went into W and W into P, 2026-11-24). **Never an id that has a page of its own now**: a
    stale redirect left by a split or a re-promotion must not close the live page's own question, so such an id names
    that page, not this one."""
    from api.services import page_redirects

    entities = Path(memory_path) / "entities"

    def lives(eid: str) -> bool:
        return eid != page_id and (entities / f"{eid}.md").is_file()

    ends = {page_id, *(e for e in page_redirects.former_ids(memory_path, page_id) if not lives(e))}
    page = entities / f"{page_id}.md"
    try:
        name = str(markdown_parser.parse(page).frontmatter.get("name") or "")
    except Exception:  # noqa: BLE001 — an unreadable page names itself by its id only
        name = ""
    if name.strip() and not lives(sanitize_id(name)):
        ends.add(sanitize_id(name))
    return ends


def open_questions(memory_path: Path, a_id: str, b_id: str, *, a_ends: set[str] | None = None,
                   b_ends: set[str] | None = None) -> list[str]:
    """Memory-relative paths of the pending "same as?" questions between page ``a_id`` and page ``b_id``."""
    memory_path = Path(memory_path)
    inbox = memory_path / "inbox"
    if not inbox.is_dir():
        return []
    a_ends = a_ends if a_ends is not None else _ends(memory_path, a_id)
    b_ends = b_ends if b_ends is not None else _ends(memory_path, b_id)
    out: list[str] = []
    for path in sorted(inbox.glob("inbox-*.md")):
        try:
            fm = markdown_parser.parse(path).frontmatter
        except Exception:  # noqa: BLE001 — an unreadable card is left as it is
            continue
        if str(fm.get("kind") or "") != KIND or str(fm.get("status") or "pending") != "pending":
            continue
        one, other = str(fm.get("entity_id") or ""), str(fm.get("merge_target_hint") or "")
        if len(fm.get("same_title") or ()) >= 2:
            continue
        if (one in a_ends and other in b_ends) or (one in b_ends and other in a_ends):
            out.append(path.relative_to(memory_path).as_posix())
    return out


def footprint(memory_path: Path, loser_id: str, winner_id: str) -> list[str]:
    """What :func:`close` would remove, computed without writing (``entity_merge.merge_footprint``)."""
    return open_questions(memory_path, loser_id, winner_id)


def close(memory_path: Path, loser_id: str, winner_id: str, *, loser_ends: set[str] | None = None,
          winner_ends: set[str] | None = None) -> list[str]:
    """Remove every open question the merge answers; the memory-relative paths removed. Call before the loser's page
    is deleted (its title names the question) — ``loser_ends`` / ``winner_ends`` may carry the ids read earlier."""
    from api.services import settle_guard   # inside a Sleep settle each question removed is reported to it

    paths = open_questions(memory_path, loser_id, winner_id, a_ends=loser_ends, b_ends=winner_ends)
    for rel in paths:
        settle_guard.writing(Path(memory_path) / rel)
        try:
            (Path(memory_path) / rel).unlink()
        except FileNotFoundError:
            continue
        settle_guard.wrote(Path(memory_path) / rel, None)
    if paths:
        logger.info(f"merge_closes: {loser_id} into {winner_id} closed {len(paths)} question(s)")
    return paths
