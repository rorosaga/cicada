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

    created, skipped = _stage_episodes(episodes, settings.memory_path / "episodes")
    logger.info(f"  Staged {created} episodes, {skipped} duplicates skipped")
    return ConversationUploadResponse(
        status="success",
        episodes_created=created,
        duplicates_skipped=skipped,
        message=f"Staged {created} episodes for next Sleep cycle",
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

        episodes.append({
            "title": title,
            "source": "chatgpt",
            "messages": messages,
            "timestamp": conv_timestamp,
            "original_date": _extract_date(conv_timestamp),
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


# --- Helpers ---


def _extract_date(timestamp: str | None) -> str | None:
    """Extract YYYY-MM-DD from an ISO timestamp string."""
    if not timestamp:
        return None
    return timestamp[:10]


# --- Staging ---


def _stage_episodes(episodes: list[dict], episodes_dir: Path) -> tuple[int, int]:
    """Write episode files to disk with chronological IDs, deduplicating by content hash."""
    episodes_dir.mkdir(parents=True, exist_ok=True)

    # Collect existing content hashes
    existing_hashes: set[str] = set()
    for filepath in episodes_dir.glob("*.md"):
        parsed = markdown_parser.parse(filepath)
        h = parsed.frontmatter.get("content_hash")
        if h:
            existing_hashes.add(h)

    created = 0
    skipped = 0

    # Track episode counts per date for sequential numbering
    date_counts: dict[str, int] = {}
    # Count existing episodes per date
    for filepath in episodes_dir.glob("ep_*.md"):
        parts = filepath.stem.split("_")
        if len(parts) >= 4:
            date_key = f"{parts[1]}-{parts[2]}-{parts[3].split('_')[0]}"
            # Actually the format is ep_YYYY-MM-DD_NNN
            date_key = "-".join(parts[1:4]) if len(parts) >= 4 else ""
    for filepath in episodes_dir.glob("ep_*.md"):
        # ep_2026-04-08_001.md -> date = 2026-04-08
        stem = filepath.stem  # ep_2026-04-08_001
        date_part = stem[3:13]  # 2026-04-08
        date_counts[date_part] = date_counts.get(date_part, 0) + 1

    for episode in episodes:
        # Build content string for hashing
        content_lines: list[str] = []
        for msg in episode.get("messages", []):
            content_lines.append(f"{msg['role']}: {msg['text']}")
        content_str = "\n".join(content_lines)

        content_hash = hashlib.sha256(content_str.encode()).hexdigest()[:12]
        if content_hash in existing_hashes:
            skipped += 1
            continue

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

        markdown_parser.write(
            episodes_dir / f"{episode_id}.md",
            frontmatter,
            content_str,
        )
        existing_hashes.add(content_hash)
        created += 1

    return created, skipped
