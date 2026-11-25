"""The graph's bubbles: one per list of saved things, its pages folded inside it (owner 2026-11-25).

A list of saved things (a site's bookmarks, likes or saved posts, a playlist, a browser's bookmarks, stars, a shelf, a
feed) is ONE bubble in the graph, wearing its source's mark and sized by what it holds; its pages are not drawn, laid
out or picked until the person opens it, and then they sit inside it, grouped by folder. Every saved thing keeps its
page (the graph is a view): a page that earned a place in the person's record (they talked about it, gave a reason, a
claim of theirs cites it, they tied it to a project) is drawn outside its bubble as before, joined to it by a line.

What sits inside and what earned a place is decided once, by ``list_pages.groups`` (the Sources work owns it, and
Clusters and Home read the same answer); this module only shapes that answer for the graph:

* top-level lists only: a folder (a playlist, a bookmark folder) is a ring inside its whole list's bubble, never a bubble
  of its own;
* members intersected with the graph's own nodes (a page that is no node — a post drawn as a row, a hidden page — is in
  no bubble);
* a page inside two lists sits in the first ``of_page`` names (the most specific list first);
* a list with fewer than ``MIN_INSIDE`` pages inside is no bubble: its pages draw as before.

Nodes are never changed: a bubble is its own array on the response, so search, the page-link index and every other
reader of the graph's nodes see every page as before. Derived on every build, never stored.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from api.models.schemas import GraphBubble, GraphBubbleFolder
from api.services import list_pages

#: Fewer pages inside than this and a list is no bubble: a bubble for two saves hides more than it tidies.
MIN_INSIDE = 6
#: A bubble's id in the graph: never a page id, so nothing that reads pages ever meets one.
PREFIX = "list:"


def bubble_id(list_key: str) -> str:
    return PREFIX + list_key


def _groups(memory_path: Path):
    """``list_pages.groups`` or None. Never raises: the graph without bubbles is the graph as it was."""
    try:
        return list_pages.groups(Path(memory_path))
    except Exception as exc:  # noqa: BLE001 - a failed grouping must never cost the graph its answer
        logger.warning("graph bubbles: grouping failed ({})", type(exc).__name__)
        return None


def stamp(memory_path: Path) -> str:
    """What a change check folds in for the bubbles, without building them (``list_pages.change_token``): the earned set
    and the table of list kinds. Membership is made of the pages' own headers, which the graph's cache key and ETag
    already follow (the ``entities`` listing). A save's record alone never moves it: every save also writes its page, and
    following the conversations folder would rebuild and resend the whole graph after every captured turn."""
    try:
        return str(list_pages.change_token(Path(memory_path)) or "")
    except Exception:  # noqa: BLE001 - a change check never fails a request
        return ""


def _top(lists: dict, key: str) -> str | None:
    """The whole list a list key belongs to: itself, or its parent's (a folder's parent is always its whole list)."""
    seen = set()
    while key in lists and key not in seen:
        seen.add(key)
        parent = getattr(lists[key], "parent", None)
        if not parent:
            return key
        key = parent
    return key if key in lists else None


def build(memory_path: Path, node_ids: set[str]) -> list[GraphBubble]:
    """The bubbles for a graph whose nodes are ``node_ids``, biggest first."""
    groups = _groups(memory_path)
    if groups is None:
        return []
    lists = getattr(groups, "lists", None) or {}
    of_page = getattr(groups, "of_page", None) or {}
    earned_of = getattr(groups, "earned_of", None) or {}

    # Each page inside a list goes to ONE top-level bubble: the whole list of the first list it is on that is big enough
    # to be a bubble at all (a page liked AND bookmarked, where the likes are three, sits with the bookmarks).
    reach: dict[str, set[str]] = {}
    for key, info in lists.items():
        if top := _top(lists, key):
            reach.setdefault(top, set()).update(p for p in getattr(info, "inside", ()) or () if p in node_ids)
    big = {top for top, pages in reach.items() if len(pages) >= MIN_INSIDE}
    home: dict[str, str] = {}
    for page_id, keys in of_page.items():
        if page_id not in node_ids:
            continue
        for key in keys or ():
            info = lists.get(key)
            if info is None or page_id not in set(getattr(info, "inside", ()) or ()):
                continue
            if (top := _top(lists, key)) in big:
                home[page_id] = top
                break

    # Members in the list's own order (newest first); each folder's rows, each page in the biggest folder it is in.
    folders_of: dict[str, list[str]] = {}
    for key, info in lists.items():
        if getattr(info, "parent", None) and (top := _top(lists, key)):
            folders_of.setdefault(top, []).append(key)
    out: list[GraphBubble] = []
    for top, info in lists.items():
        if getattr(info, "parent", None):
            continue
        rows_of = {key: [p for p in getattr(lists[key], "inside", ()) or () if home.get(p) == top]
                   for key in folders_of.get(top, [])}
        folders: list[GraphBubbleFolder] = []
        placed: set[str] = set()
        for key, rows in sorted(rows_of.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            rows = [p for p in rows if p not in placed]
            if not rows:
                continue
            placed.update(rows)
            folder = lists[key]
            name = str(getattr(folder, "folder", None) or getattr(folder, "label", None) or key)
            folders.append(GraphBubbleFolder(key=key, name=name, members=rows))
        ids = [p for p in getattr(info, "inside", ()) or () if home.get(p) == top]
        ids = list(dict.fromkeys(ids + [p for f in folders for p in f.members]))
        if len(ids) < MIN_INSIDE:
            continue
        outside = [p for p, keys in earned_of.items()
                   if p in node_ids and any(_top(lists, k) == top for k in keys or ())]
        page = top if getattr(info, "has_page", False) else None    # a list's key is its page's id (list_pages.page_id)
        out.append(GraphBubble(
            id=bubble_id(top), key=top, name=str(getattr(info, "name", "") or top),
            site=getattr(info, "site", None), mark=getattr(info, "mark", None),
            kind_noun=getattr(info, "kind_noun", None) or "pages", count=len(ids),
            page_id=page,
            members=ids, folders=folders, outside=sorted(outside)))
    out.sort(key=lambda b: (-b.count, b.id))
    return out


def filtered(bubbles: list[GraphBubble], node_ids: set[str]) -> list[GraphBubble]:
    """The bubbles of a filtered graph: members and outside pages that are still nodes, lists still big enough."""
    out = []
    for b in bubbles:
        ids = [p for p in b.members if p in node_ids]
        if len(ids) < MIN_INSIDE:
            continue
        keep = set(ids)
        folders = [f.model_copy(update={"members": [p for p in f.members if p in keep]}) for f in b.folders]
        out.append(b.model_copy(update={
            "members": ids, "count": len(ids), "folders": [f for f in folders if f.members],
            "outside": [p for p in b.outside if p in node_ids]}))
    return out
