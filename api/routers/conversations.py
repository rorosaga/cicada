import hashlib
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile

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

    try:
        if filename.endswith(".html"):
            episodes = _parse_chatgpt_html(content.decode("utf-8"))
        elif filename.endswith(".json"):
            data = json.loads(content)
            if _is_chatgpt_json(data):
                episodes = _parse_chatgpt_json(data)
            else:
                episodes = _parse_claude_json(data)
        else:
            raise HTTPException(400, "Unsupported file format. Use .json or .html")
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(400, f"Failed to parse file: {e}")

    created, skipped = _stage_episodes(episodes, settings.memory_path / "episodes")
    return ConversationUploadResponse(
        status="success",
        episodes_created=created,
        duplicates_skipped=skipped,
        message=f"Staged {created} episodes for next Sleep cycle",
    )


# --- Parsers ---


def _is_chatgpt_json(data) -> bool:
    """Detect ChatGPT JSON format by checking for 'mapping' in first conversation."""
    if isinstance(data, list) and len(data) > 0:
        return "mapping" in data[0]
    return False


def _parse_chatgpt_json(data: list) -> list[dict]:
    """Parse ChatGPT JSON export into episode chunks."""
    episodes: list[dict] = []
    for conversation in data:
        title = conversation.get("title", "Untitled")
        mapping = conversation.get("mapping", {})
        messages: list[dict] = []

        for node in mapping.values():
            msg = node.get("message")
            if msg and msg.get("content", {}).get("parts"):
                role = msg.get("author", {}).get("role", "unknown")
                text = "\n".join(str(p) for p in msg["content"]["parts"] if isinstance(p, str))
                if text.strip() and role in ("user", "assistant"):
                    timestamp = msg.get("create_time")
                    messages.append({"role": role, "text": text, "timestamp": timestamp})

        if messages:
            messages.sort(key=lambda m: m.get("timestamp") or 0)
            episodes.append({
                "title": title,
                "source": "chatgpt",
                "messages": messages,
                "timestamp": messages[0].get("timestamp"),
            })

    return episodes


def _parse_chatgpt_html(html: str) -> list[dict]:
    """Parse ChatGPT HTML export into episode chunks."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    episodes: list[dict] = []

    # ChatGPT HTML exports have conversation sections
    conversations = soup.find_all("div", class_="conversation")
    if not conversations:
        # Fallback: treat whole document as one conversation
        conversations = [soup]

    for conv in conversations:
        messages: list[dict] = []
        for msg_div in conv.find_all(["div", "p"], recursive=True):
            text = msg_div.get_text(strip=True)
            if text and len(text) > 10:
                messages.append({"role": "unknown", "text": text})

        if messages:
            episodes.append({
                "title": "Imported conversation",
                "source": "chatgpt",
                "messages": messages,
                "timestamp": None,
            })

    return episodes


def _parse_claude_json(data) -> list[dict]:
    """Parse Claude JSON export into episode chunks."""
    episodes: list[dict] = []

    conversations = data if isinstance(data, list) else [data]
    for conversation in conversations:
        messages: list[dict] = []
        chat_messages = conversation.get("chat_messages", [])
        for msg in chat_messages:
            role = msg.get("sender", "unknown")
            text = msg.get("text", "")
            if text.strip():
                messages.append({"role": role, "text": text})

        if messages:
            episodes.append({
                "title": conversation.get("name", "Imported conversation"),
                "source": "claude",
                "messages": messages,
                "timestamp": conversation.get("created_at"),
            })

    return episodes


# --- Staging ---


def _stage_episodes(episodes: list[dict], episodes_dir: Path) -> tuple[int, int]:
    """Write episode files to disk, deduplicating by content hash."""
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
    today = datetime.now().strftime("%Y-%m-%d")

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

        # Find next episode number for today
        existing_today = list(episodes_dir.glob(f"ep_{today}_*.md"))
        next_num = len(existing_today) + 1
        episode_id = f"ep_{today}_{next_num:03d}"

        ts = episode.get("timestamp")
        if isinstance(ts, (int, float)):
            ts = datetime.fromtimestamp(ts).isoformat()
        elif ts is None:
            ts = datetime.now().isoformat()

        frontmatter = {
            "id": episode_id,
            "timestamp": str(ts),
            "source": episode.get("source", "unknown"),
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
