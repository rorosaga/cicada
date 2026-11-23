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


#: Where an episode's original lives (owner 2026-11-23: "when I right click on a specific episode, I'd like the option
#: for it to take me to that app/website/claude code session"). The app words each one and opens it on the click.
WEB, SESSION, NOTE, FILE = "web", "session", "note", "file"

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z", re.IGNORECASE)
#: Notes' own id for a note — the same form `channel_items` answers a place with.
_NOTE_ID = re.compile(r"x-coredata://[A-Za-z0-9._/-]+\Z")
#: An imported conversation's own page at its provider, by the export's `source` word. Only for a bare conversation
#: uuid (`source_id`); a project's or a memory entry's id (`claude-project:…`) names no page.
_EXPORT_PAGE = {"claude": "https://claude.ai/chat/{}", "chatgpt": "https://chatgpt.com/c/{}"}


def open_target(fm: Mapping[str, Any], body: str = "",
                folder_root: Optional[Callable[[str], Optional[str]]] = None) -> Optional[tuple[str, str]]:
    """``(kind, value)`` naming where one episode's original can be opened, else None: a note in Notes (its own id),
    a page (its link, a tab group's one link, an imported conversation's page at its provider), a Claude Code session
    (its id — the app asks ``POST /conversations/{id}/resume`` on the click, which checks it), a folder file (its
    full path, only when the folder's root is known). Pure over the frontmatter; nothing is opened or statted here.
    A chat names nothing: the bank holds a hash of it, never the app's own id — the app opens the chat's app."""
    note = str(fm.get("note_id") or "").strip()
    if _NOTE_ID.match(note):
        return NOTE, note
    url = str(fm.get("url") or "").strip()
    if url.lower().startswith(("https://", "http://")):
        return WEB, url
    session = str(fm.get("session_id") or "").strip()
    if session:
        if str(fm.get("harness") or "") == "claude-code" and _UUID.match(session):
            return SESSION, session
        return None
    page = _EXPORT_PAGE.get(str(fm.get("source") or ""))
    source_id = str(fm.get("source_id") or "").strip()
    if page and _UUID.match(source_id):
        return WEB, page.format(source_id.lower())
    if str(fm.get("origin") or "") == "chrome-tab-group":
        links = tab_links(body)
        if len(links) == 1:
            return WEB, links[0]
    relpath = str(fm.get("relpath") or "").strip()
    if relpath and folder_root:
        root = folder_root(str(fm.get("folder_id") or ""))
        if root:
            return FILE, str(Path(root) / relpath)
    return None


#: A chat sitting's title ends with its day and starts with its service: "Messages · <group> · 2026-11-20".
_SITTING_TITLE = re.compile(r"^[^·]+ · (?P<name>.+) · \d{4}-\d{2}-\d{2}$")
_CONVERSATION = re.compile(r"[0-9a-f]{16,64}\Z")
#: `agent_detectors.UNNAMED`, spelled here so this module stays a leaf (it imports no service).
_UNNAMED = "Unnamed conversation"


def chat_of(fm: Mapping[str, Any]) -> Optional[dict]:
    """The chat one sitting belongs to (owner 2026-11-23: "shouldn't it be just one chat … and per chat the number of
    new messages in total"), for a Messages, WhatsApp or Telegram sitting: ``{id, name, messages, group}`` — ``id``
    the chat's hash (the bank never holds its address), ``name`` the correspondent's as the sitting recorded it, a
    group's from its title, None when the chat has none; ``messages`` this sitting's count. None for anything else.
    Pure over the frontmatter."""
    cid = str(fm.get("conversation") or "")
    if not _CONVERSATION.match(cid) or "message_count" not in fm:
        return None
    name: Optional[str] = None
    correspondent = fm.get("correspondent")
    if isinstance(correspondent, Mapping):
        name = str(correspondent.get("name") or "").strip() or None
        if name == _UNNAMED:
            name = None   # a sender with no name on record: the app says so in its own words
    elif not fm.get("self_chat") and (m := _SITTING_TITLE.match(str(fm.get("title") or ""))):
        name = m.group("name").strip()
        if name == "group":
            name = None
    try:
        messages = max(int(fm.get("message_count") or 0), 0)
    except (TypeError, ValueError):
        messages = 0
    return {"id": cid, "name": name, "messages": messages, "group": bool(fm.get("group")),
            "self_chat": bool(fm.get("self_chat"))}


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
