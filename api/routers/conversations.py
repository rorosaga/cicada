import hashlib
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from loguru import logger

from api.config import Settings, get_settings
from api.models.schemas import ConversationUploadResponse
from api.services import markdown_parser

router = APIRouter()


@router.post("/conversations/upload", response_model=ConversationUploadResponse)
async def upload_conversation(
    file: UploadFile,
    settings: Settings = Depends(get_settings),
):
    content = await file.read()
    filename = file.filename or ""
    logger.info(f"Upload: {filename} ({len(content)} bytes)")

    source = "unknown"
    try:
        if filename.endswith(".html"):
            episodes = _parse_chatgpt_html(content.decode("utf-8"))
            source = "chatgpt_html"
            logger.info(f"  Parsed as ChatGPT HTML: {len(episodes)} episodes")
        elif filename.endswith(".json"):
            data = json.loads(content)
            source = detect_source(data, filename)
            logger.info(f"  Detected source: {source}")
            if source == "anthropic":
                episodes = parse_anthropic_conversations(data)
            elif source == "anthropic_memories":
                episodes = parse_anthropic_memories(data)
            elif source == "anthropic_projects":
                episodes = parse_anthropic_projects(data)
            elif source == "chatgpt":
                episodes = parse_chatgpt_json(data)
            else:
                raise HTTPException(400, "Unrecognized JSON format")
        else:
            raise HTTPException(400, "Unsupported file format. Use .json or .html")
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(400, f"Failed to parse file: {e}")

    # Map source to human-readable labels
    source_labels = {
        "anthropic": "Claude — Conversations",
        "anthropic_memories": "Claude — Memories",
        "anthropic_projects": "Claude — Projects",
        "chatgpt": "ChatGPT — Conversations",
        "chatgpt_html": "ChatGPT — HTML Export",
    }

    created, updated, skipped = _stage_episodes(
        episodes, settings.memory_path / "episodes"
    )
    logger.info(
        f"  Staged {created} new, {updated} updated, {skipped} unchanged"
    )
    return ConversationUploadResponse(
        status="success",
        episodes_created=created,
        episodes_updated=updated,
        duplicates_skipped=skipped,
        message=f"Staged {created} new, {updated} updated, {skipped} unchanged",
        source=source_labels.get(source, source),
    )


# --- Source Detection ---


def detect_source(data, filename: str = "") -> str:
    """Detect export source from JSON structure."""
    # Anthropic memories.json
    if isinstance(data, list) and data and "conversations_memory" in data[0]:
        return "anthropic_memories"

    # Anthropic projects.json
    if isinstance(data, list) and data and "prompt_template" in data[0]:
        return "anthropic_projects"

    # Anthropic conversations.json — has uuid + chat_messages
    if isinstance(data, list) and data:
        first = data[0] if data else {}
        if "chat_messages" in first and "uuid" in first:
            return "anthropic"

    # ChatGPT — has mapping with message nodes
    if isinstance(data, list) and data:
        first = data[0] if data else {}
        if "mapping" in first:
            return "chatgpt"

    return "unknown"


# --- Anthropic / Claude Export ---


def parse_anthropic_conversations(data: list) -> list[dict]:
    """Parse Anthropic conversations.json export.

    Real format (verified April 2026):
    - Each conversation has uuid, name, created_at, updated_at, chat_messages[]
    - Each message has uuid, sender ("human"|"assistant"), text, content[], created_at
    - content[] has start_timestamp, stop_timestamp, type, text, citations
    - Timestamps are ISO 8601 with microseconds: "2026-02-24T12:39:02.701295Z"
    """
    episodes: list[dict] = []

    for conv in data:
        messages = conv.get("chat_messages", [])
        if not messages:
            continue

        # Sort messages by their created_at timestamp
        messages.sort(key=lambda m: m.get("created_at", ""))

        parsed_msgs: list[dict] = []
        for msg in messages:
            sender = msg.get("sender", "unknown")
            # Normalize sender: "human" -> "user", keep "assistant"
            role = "user" if sender == "human" else sender
            text = msg.get("text", "")
            if not text or not text.strip():
                # Fall back to content blocks
                for block in msg.get("content", []):
                    if block.get("type") == "text" and block.get("text"):
                        text = block["text"]
                        break
            if not text or not text.strip():
                continue

            parsed_msgs.append({
                "role": role,
                "text": text.strip(),
                "timestamp": msg.get("created_at"),
            })

        if not parsed_msgs:
            continue

        # Use the conversation's own created_at as the episode timestamp
        conv_timestamp = conv.get("created_at", parsed_msgs[0].get("timestamp"))

        episodes.append({
            "title": conv.get("name", "Untitled"),
            "source": "claude",
            "messages": parsed_msgs,
            "timestamp": conv_timestamp,
            # Preserve original date for chronological staging
            "original_date": _extract_date(conv_timestamp),
            # G20 delta re-import: stable per-thread identity so a re-export of a
            # grown conversation updates its episode in place instead of forking.
            "source_id": conv.get("uuid"),
            "source_updated_at": conv.get("updated_at"),
        })

    # Sort episodes chronologically so they're staged in order
    episodes.sort(key=lambda e: e.get("timestamp", ""))
    return episodes


def parse_anthropic_memories(data: list) -> list[dict]:
    """Parse Anthropic memories.json as a bootstrapping source.

    Contains Claude's existing memory about the user — free entity seed data.
    Structure: [{conversations_memory: str, project_memories: {uuid: str, ...}}]
    """
    episodes: list[dict] = []

    for entry in data:
        # Conversations memory — global context Claude has built
        conv_memory = entry.get("conversations_memory", "")
        if conv_memory.strip():
            episodes.append({
                "title": "Claude Memory — Conversation Context",
                "source": "claude_memory",
                "messages": [{"role": "system", "text": conv_memory, "timestamp": None}],
                "timestamp": None,
                "original_date": None,
            })

        # Project memories — per-project context
        project_memories = entry.get("project_memories", {})
        if isinstance(project_memories, dict):
            for project_id, memory_text in project_memories.items():
                if memory_text and memory_text.strip():
                    episodes.append({
                        "title": f"Claude Memory — Project {project_id[:8]}",
                        "source": "claude_memory",
                        "messages": [{"role": "system", "text": memory_text, "timestamp": None}],
                        "timestamp": None,
                        "original_date": None,
                    })

    return episodes


def parse_anthropic_projects(data: list) -> list[dict]:
    """Parse Anthropic projects.json — project descriptions as knowledge episodes."""
    episodes: list[dict] = []

    for project in data:
        name = project.get("name", "")
        description = project.get("description", "") or ""
        prompt_template = project.get("prompt_template", "") or ""

        # Skip empty or default projects
        if not description.strip() or name == "How to use Claude":
            continue

        content_parts = [f"Project: {name}"]
        if description:
            content_parts.append(f"Description: {description}")
        if prompt_template:
            content_parts.append(f"Prompt template: {prompt_template}")

        content = "\n\n".join(content_parts)

        episodes.append({
            "title": f"Claude Project — {name}",
            "source": "claude_project",
            "messages": [{"role": "system", "text": content, "timestamp": project.get("created_at")}],
            "timestamp": project.get("created_at"),
            "original_date": _extract_date(project.get("created_at")),
        })

    return episodes


# --- ChatGPT Export ---


def parse_chatgpt_json(data: list) -> list[dict]:
    """Parse ChatGPT conversations.json export.

    Known format:
    - Each conversation has title, create_time (unix), mapping (tree of message nodes)
    - Each node has message.author.role, message.content.parts[], message.create_time
    """
    episodes: list[dict] = []

    for conversation in data:
        title = conversation.get("title", "Untitled")
        mapping = conversation.get("mapping", {})
        messages: list[dict] = []

        for node in mapping.values():
            msg = node.get("message")
            if not msg:
                continue
            parts = msg.get("content", {}).get("parts", [])
            if not parts:
                continue

            role = msg.get("author", {}).get("role", "unknown")
            text = "\n".join(str(p) for p in parts if isinstance(p, str))
            if not text.strip() or role not in ("user", "assistant"):
                continue

            create_time = msg.get("create_time")
            timestamp = None
            if isinstance(create_time, (int, float)) and create_time > 0:
                timestamp = datetime.fromtimestamp(create_time).isoformat() + "Z"

            messages.append({"role": role, "text": text.strip(), "timestamp": timestamp})

        if not messages:
            continue

        messages.sort(key=lambda m: m.get("timestamp") or "")

        # Conversation-level timestamp
        conv_time = conversation.get("create_time")
        if isinstance(conv_time, (int, float)) and conv_time > 0:
            conv_timestamp = datetime.fromtimestamp(conv_time).isoformat() + "Z"
        else:
            conv_timestamp = messages[0].get("timestamp")

        # G20 delta re-import: stable per-thread identity. ChatGPT exports key on
        # conversation_id (or a bare id); update_time is a unix epoch float, so
        # render it ISO+"Z" with the same idiom used for create_time above.
        source_id = conversation.get("conversation_id") or conversation.get("id")
        update_time = conversation.get("update_time")
        source_updated_at = None
        if isinstance(update_time, (int, float)) and update_time > 0:
            source_updated_at = datetime.fromtimestamp(update_time).isoformat() + "Z"

        episodes.append({
            "title": title,
            "source": "chatgpt",
            "messages": messages,
            "timestamp": conv_timestamp,
            "original_date": _extract_date(conv_timestamp),
            "source_id": source_id,
            "source_updated_at": source_updated_at,
        })

    episodes.sort(key=lambda e: e.get("timestamp", ""))
    return episodes


def _parse_chatgpt_html(html: str) -> list[dict]:
    """Parse ChatGPT HTML export. Fallback — less structured than JSON."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    episodes: list[dict] = []

    conversations = soup.find_all("div", class_="conversation")
    if not conversations:
        conversations = [soup]

    for conv in conversations:
        messages: list[dict] = []
        for msg_div in conv.find_all(["div", "p"], recursive=True):
            text = msg_div.get_text(strip=True)
            if text and len(text) > 10:
                messages.append({"role": "unknown", "text": text, "timestamp": None})

        if messages:
            episodes.append({
                "title": "Imported conversation",
                "source": "chatgpt",
                "messages": messages,
                "timestamp": None,
                "original_date": None,
            })

    return episodes


# --- Gemini (Google Takeout MyActivity) Export ---


# Month-name -> number map for the Takeout activity timestamp format, which is
# locale-rendered (e.g. "Feb 24, 2026, 12:39:02 PM PST") rather than ISO.
_GEMINI_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_gemini_timestamp(raw: str) -> str | None:
    """Parse a Takeout MyActivity timestamp into an ISO ``YYYY-MM-DDTHH:MM:SSZ``.

    Google renders these as ``"Feb 24, 2026, 12:39:02 PM PST"`` (note the
    narrow no-break space and trailing tz abbreviation). We only need date +
    wall-clock for backdating, so the tz abbreviation is dropped. Returns
    ``None`` if the string can't be parsed (the episode then falls back to
    ``datetime.now()`` in staging).
    """
    if not raw:
        return None
    import re

    text = raw.replace(" ", " ").replace("\xa0", " ").strip()
    m = re.search(
        r"([A-Za-z]{3,})\s+(\d{1,2}),\s+(\d{4}),\s+(\d{1,2}):(\d{2}):(\d{2})\s*([AP]M)?",
        text,
    )
    if not m:
        return None
    mon_name, day, year, hh, mm, ss, ampm = m.groups()
    month = _GEMINI_MONTHS.get(mon_name[:3].lower())
    if not month:
        return None
    hour = int(hh)
    if ampm:
        ampm = ampm.upper()
        if ampm == "PM" and hour != 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
    try:
        dt = datetime(int(year), month, int(day), hour, int(mm), int(ss))
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def parse_gemini_myactivity(html: str) -> list[dict]:
    """Parse a Google Takeout ``Gemini Apps/MyActivity.html`` export.

    Each activity entry is an ``outer-cell`` ``mdl-card`` whose body holds the
    prompt text plus a rendered timestamp. We treat each entry as a single
    backdated episode (``origin=gemini-export``), preserving the activity's own
    timestamp so the Sleep cycle sees true chronology.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    episodes: list[dict] = []

    cells = soup.find_all("div", class_="outer-cell")
    if not cells:
        # Fallback for snippets without the full Takeout chrome.
        cells = soup.find_all("div", class_="content-cell")

    for cell in cells:
        content = cell.find("div", class_="content-cell") or cell
        text = content.get_text(separator="\n", strip=True)
        if not text:
            continue

        # The timestamp is the trailing date-looking line within the cell text.
        ts: str | None = None
        for line in reversed(text.split("\n")):
            parsed = _parse_gemini_timestamp(line)
            if parsed:
                ts = parsed
                # Strip the timestamp line from the prompt body.
                text = text.replace(line, "").strip()
                break

        if not text:
            continue

        episodes.append({
            "title": "Gemini activity",
            "source": "gemini_export",
            "origin": "gemini-export",
            "messages": [{"role": "user", "text": text, "timestamp": ts}],
            "timestamp": ts,
            "original_date": _extract_date(ts),
        })

    episodes.sort(key=lambda e: e.get("timestamp") or "")
    return episodes


# --- ChatGPT export (stub) ---


def parse_chatgpt_export(data) -> list[dict]:
    """ChatGPT export entry point (origin=chatgpt-export).

    The real OpenAI export is the same ``conversations.json`` mapping-tree shape
    already handled by :func:`parse_chatgpt_json`; this thin wrapper stamps the
    ``origin`` for the banks-import contract and exists as the seam for the
    pending real export. Accepts the parsed JSON list.
    """
    episodes = parse_chatgpt_json(data if isinstance(data, list) else [])
    for ep in episodes:
        ep["origin"] = "chatgpt-export"
    return episodes


# --- Import dispatch (banks M7) ---


# Maps the parsed ``source`` (from detect_source / file extension) to the
# wire ``format`` field in the banks-import response.
_IMPORT_FORMAT = {
    "anthropic": "claude",
    "anthropic_memories": "claude_memories",
    "anthropic_projects": "claude_projects",
    "chatgpt": "chatgpt",
    "chatgpt_html": "chatgpt",
    "gemini": "gemini",
}


def parse_export_bytes(content: bytes, filename: str) -> tuple[list[dict], str]:
    """Detect + parse a chat-export file (or .zip) into episodes + a format tag.

    Handles a raw ``conversations.json`` (Claude / ChatGPT), ``MyActivity.html``
    (Gemini), a ChatGPT HTML export, or a ``.zip`` wrapping any of the above
    (Claude data export, Gemini Takeout, ChatGPT export). Returns
    ``(episodes, format)`` where ``format`` is the wire tag. Raises
    ``HTTPException`` on unrecognized input.
    """
    name = (filename or "").lower()

    if name.endswith(".zip"):
        return _parse_zip(content)

    if name.endswith(".html") or name.endswith(".htm"):
        text = content.decode("utf-8", errors="replace")
        # Gemini Takeout MyActivity vs a generic ChatGPT HTML export.
        if "MyActivity" in (filename or "") or "mdl-typography" in text or "outer-cell" in text:
            return parse_gemini_myactivity(text), "gemini"
        return _parse_chatgpt_html(text), "chatgpt"

    if name.endswith(".json") or not name:
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise HTTPException(400, f"Failed to parse file: {e}")
        source = detect_source(data, filename)
        if source == "anthropic":
            return _stamp_origin(parse_anthropic_conversations(data), "claude-export"), "claude"
        if source == "anthropic_memories":
            return _stamp_origin(parse_anthropic_memories(data), "claude-export"), "claude_memories"
        if source == "anthropic_projects":
            return _stamp_origin(parse_anthropic_projects(data), "claude-export"), "claude_projects"
        if source == "chatgpt":
            return parse_chatgpt_export(data), "chatgpt"
        raise HTTPException(400, "Unrecognized JSON export format")

    raise HTTPException(400, "Unsupported file format. Use .json, .html, or .zip")


def _stamp_origin(episodes: list[dict], origin: str) -> list[dict]:
    """Tag each episode with an import-provenance ``origin`` (in place)."""
    for ep in episodes:
        ep["origin"] = origin
    return episodes


def _parse_zip(content: bytes) -> tuple[list[dict], str]:
    """Extract a chat-export .zip in a temp dir and parse the contained file.

    Locates (in priority order) a Gemini ``MyActivity.html``, a Claude/ChatGPT
    ``conversations.json``, or any ``*.html``/``*.json`` and recurses into it.
    """
    import io
    import tempfile
    import zipfile

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise HTTPException(400, f"Invalid zip file: {e}")

    names = [n for n in zf.namelist() if not n.endswith("/")]

    def _first(pred):
        return next((n for n in names if pred(n.lower())), None)

    target = (
        _first(lambda n: n.endswith("myactivity.html"))
        or _first(lambda n: n.endswith("conversations.json"))
        or _first(lambda n: n.endswith(".html"))
        or _first(lambda n: n.endswith(".json"))
    )
    if not target:
        raise HTTPException(400, "Zip contains no recognizable export file")

    with tempfile.TemporaryDirectory() as tmp:
        extracted = zf.extract(target, tmp)
        with open(extracted, "rb") as f:
            inner = f.read()
    return parse_export_bytes(inner, Path(target).name)


# --- Helpers ---


def _extract_date(timestamp: str | None) -> str | None:
    """Extract YYYY-MM-DD from an ISO timestamp string."""
    if not timestamp:
        return None
    return timestamp[:10]


# --- Staging ---


def _stage_episodes(
    episodes: list[dict], episodes_dir: Path
) -> tuple[int, int, int]:
    """Stage episode files, delta-aware by stable source identity (G20).

    Returns ``(created, updated, skipped)``:
    - ``created``  — new episode files written (unseen source_id, or a no-id
      format whose content hash wasn't already on disk).
    - ``updated``  — existing episodes rewritten IN PLACE because the same
      ``source_id`` was re-exported with changed content (a grown/edited
      thread). Same episode id + filename; body, ``content_hash``,
      ``source_updated_at`` refreshed and ``processed`` flipped back to
      ``False`` so the next Sleep cycle re-consolidates only it.
    - ``skipped``  — unchanged (same source_id + same content, or a no-id
      episode whose content hash already exists).

    Episodes WITHOUT a ``source_id`` keep the pre-G20 content-hash behaviour
    exactly (create or skip, never update).
    """
    episodes_dir.mkdir(parents=True, exist_ok=True)

    # Single pre-scan of the episodes dir:
    #  - source_index: source_id -> {path, content_hash, source_updated_at}
    #  - existing_hashes: all known content hashes (no-id fallback dedup)
    #  - date_counts: per-date episode counts for sequential id numbering
    source_index: dict[str, dict] = {}
    existing_hashes: set[str] = set()
    date_counts: dict[str, int] = {}
    for filepath in episodes_dir.glob("*.md"):
        parsed = markdown_parser.parse(filepath)
        fm = parsed.frontmatter
        h = fm.get("content_hash")
        if h:
            existing_hashes.add(h)
        sid = fm.get("source_id")
        if sid:
            source_index[sid] = {
                "path": filepath,
                "content_hash": h,
                "source_updated_at": fm.get("source_updated_at"),
            }
    for filepath in episodes_dir.glob("ep_*.md"):
        # ep_2026-04-08_001.md -> date = 2026-04-08
        date_part = filepath.stem[3:13]
        date_counts[date_part] = date_counts.get(date_part, 0) + 1

    created = 0
    updated = 0
    skipped = 0

    for episode in episodes:
        # Build content string for hashing
        content_lines: list[str] = []
        for msg in episode.get("messages", []):
            content_lines.append(f"{msg['role']}: {msg['text']}")
        content_str = "\n".join(content_lines)
        content_hash = hashlib.sha256(content_str.encode()).hexdigest()[:12]

        source_id = episode.get("source_id")

        # Truthy check (not ``is not None``) mirrors the pre-scan's ``if sid:``
        # so an empty-string id falls through to content-hash dedup instead of
        # forking a fresh file on every re-import.
        if source_id:
            existing = source_index.get(source_id)
            if existing is None:
                # Brand-new thread -> CREATE.
                path = _write_new_episode(
                    episode, episodes_dir, content_str, content_hash, date_counts
                )
                existing_hashes.add(content_hash)
                # Track so a same-id repeat later in this batch updates in place
                # rather than forking a second file.
                source_index[source_id] = {
                    "path": path,
                    "content_hash": content_hash,
                    "source_updated_at": episode.get("source_updated_at"),
                }
                created += 1
                continue

            if existing.get("content_hash") == content_hash:
                # Same thread, unchanged content -> SKIP.
                skipped += 1
                continue

            # Same thread, changed content -> UPDATE IN PLACE.
            _update_episode_in_place(
                existing["path"], episode, content_str, content_hash
            )
            existing_hashes.add(content_hash)
            existing["content_hash"] = content_hash
            existing["source_updated_at"] = episode.get("source_updated_at")
            updated += 1
            continue

        # No stable source id -> pre-G20 content-hash dedup (create or skip).
        if content_hash in existing_hashes:
            skipped += 1
            continue
        _write_new_episode(
            episode, episodes_dir, content_str, content_hash, date_counts
        )
        existing_hashes.add(content_hash)
        created += 1

    return created, updated, skipped


def _write_new_episode(
    episode: dict,
    episodes_dir: Path,
    content_str: str,
    content_hash: str,
    date_counts: dict[str, int],
) -> Path:
    """Write a fresh episode file with a chronological id. Returns its path."""
    # Use the episode's original date for the ID, preserving chronological order
    ep_date = episode.get("original_date") or datetime.now().strftime("%Y-%m-%d")
    date_counts[ep_date] = date_counts.get(ep_date, 0) + 1
    next_num = date_counts[ep_date]
    episode_id = f"ep_{ep_date}_{next_num:03d}"

    # Use the precise timestamp from the conversation
    ts = episode.get("timestamp")
    if ts is None:
        ts = datetime.now().isoformat() + "Z"

    frontmatter = {
        "id": episode_id,
        "timestamp": str(ts),
        "source": episode.get("source", "unknown"),
        "title": episode.get("title", "Untitled"),
        "processed": False,
        "content_hash": content_hash,
    }
    # Carry the import provenance tag (e.g. claude-export / gemini-export /
    # chatgpt-export) when the parser stamped one. Absent for live capture
    # and the legacy upload path, so frontmatter stays unchanged there.
    if episode.get("origin"):
        frontmatter["origin"] = episode["origin"]
    # G20: stable per-thread identity, written ONLY when the format provides it
    # so existing-format frontmatter is unchanged. Inert to all other parsing.
    if episode.get("source_id") is not None:
        frontmatter["source_id"] = episode["source_id"]
        frontmatter["source_updated_at"] = episode.get("source_updated_at")

    path = episodes_dir / f"{episode_id}.md"
    markdown_parser.write(path, frontmatter, content_str)
    return path


def _update_episode_in_place(
    path: Path, episode: dict, content_str: str, content_hash: str
) -> None:
    """Rewrite an existing episode for a grown/edited thread (G20).

    Keeps the SAME episode id + filename. Preserves the original
    id/timestamp/source/origin frontmatter, refreshes the title, overwrites the
    body, updates content_hash + source_updated_at, and flips ``processed`` back
    to ``False`` so the next Sleep cycle re-consolidates only this episode.
    """
    fm = dict(markdown_parser.parse(path).frontmatter)
    # Preserve id + original timestamp + source; refresh the rest.
    fm["title"] = episode.get("title", fm.get("title", "Untitled"))
    fm["content_hash"] = content_hash
    fm["source_updated_at"] = episode.get("source_updated_at")
    fm["source_id"] = episode.get("source_id")
    fm["processed"] = False
    if episode.get("origin"):
        fm["origin"] = episode["origin"]
    markdown_parser.write(path, fm, content_str)
