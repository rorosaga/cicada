"""What a click on a queued episode copies, and the day the row shows (Sleep › Details › What's waiting).

Owner 2026-10-05: "clicking on sleep queue entries should copy whatever it is we are consolidating to the clipboard"
— a conversation's id, a page's link — and the row ends with "a day when it was added/last modified for
conversations". Pure over an episode's frontmatter; the folder registry is read only for a folder file's full path
(the registry's own stored string — nothing is opened or statted).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

#: The kinds a row can copy. The app words each one ("Conversation ID copied", "Link copied", …).
LINK, LINKS, CONVERSATION, PATH, EPISODE = "link", "links", "conversation", "path", "episode"

_URL = re.compile(r"https?://[^\s<>()\[\]\"']+")
_TRAILING = ".,;:!?"


def tab_links(body: str) -> list[str]:
    """The tab group's links, in order, once each (its frontmatter carries none; the body lists them)."""
    seen: list[str] = []
    for match in _URL.finditer(body or ""):
        url = match.group(0).rstrip(_TRAILING)
        if url not in seen:
            seen.append(url)
    return seen


def copy_target(fm: Mapping[str, Any], body: str = "",
                folder_root: Optional[Callable[[str], Optional[str]]] = None) -> tuple[str, str]:
    """``(kind, text)`` for one episode: its page link, else its conversation's session id, else a tab group's
    links, else a folder file's path, else the episode's own id."""
    url = str(fm.get("url") or "").strip()
    if url:
        return LINK, url
    session = str(fm.get("session_id") or "").strip()
    if session:
        return CONVERSATION, session
    origin = str(fm.get("origin") or "")
    if origin == "chrome-tab-group":
        links = tab_links(body)
        if links:
            return (LINK, links[0]) if len(links) == 1 else (LINKS, "\n".join(links))
    relpath = str(fm.get("relpath") or "").strip()
    if relpath:
        root = folder_root(str(fm.get("folder_id") or "")) if folder_root else None
        return PATH, str(Path(root) / relpath) if root else relpath
    return EPISODE, str(fm.get("id") or "")


def changed_at(fm: Mapping[str, Any]) -> str:
    """The day a row shows: a captured conversation's last capture (it grows in place), else when it was added."""
    if str(fm.get("session_id") or "").strip() and fm.get("captured_at"):
        return str(fm["captured_at"])
    return str(fm.get("timestamp") or "")


def folder_roots(memory_path: Path) -> Callable[[str], Optional[str]]:
    """A memoised folder-id → registered root path lookup for one listing."""
    from api.services import folder_source

    cache: dict[str, Optional[str]] = {}

    def root(folder_id: str) -> Optional[str]:
        if not folder_id:
            return None
        if folder_id not in cache:
            try:
                record = folder_source.get_folder(memory_path, folder_id)
            except Exception:  # noqa: BLE001 - a broken registry costs the full path, never the row
                record = None
            cache[folder_id] = str(record.get("path")) if record and record.get("path") else None
        return cache[folder_id]

    return root
