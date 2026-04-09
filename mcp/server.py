"""Cicada MCP Server — Bookworm tool for LLM-memory integration.

Registers as an MCP server that any compatible client (Claude Desktop, Claude Code,
Cursor) can connect to. Provides tools for:
1. Querying the knowledge graph
2. Capturing episodes from conversations
3. Checking pending nudges/clarifications
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# MCP protocol uses JSON-RPC 2.0 over stdin/stdout


def main():
    """Main loop: read JSON-RPC requests from stdin, write responses to stdout."""
    # Server capabilities
    tools = [
        {
            "name": "cicada_recall",
            "description": "Search Cicada's knowledge graph for entities related to a topic. Returns relevant entities with their context, relationships, and confidence scores. Use this at the start of conversations to check what Cicada already knows about the topic being discussed.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The topic, person, project, or concept to search for",
                    }
                },
                "required": ["query"],
            },
        },
        {
            "name": "cicada_save_episode",
            "description": "Save a conversation snippet as an episode for Cicada's memory. The episode will be processed during the next Sleep cycle to extract entities and relationships. Use this when the conversation contains important information worth remembering.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The conversation content to save as an episode",
                    },
                    "title": {
                        "type": "string",
                        "description": "A short title for this episode",
                    },
                },
                "required": ["content"],
            },
        },
        {
            "name": "cicada_check_nudges",
            "description": "Check if there are pending nudges or clarifications in Cicada's memory system. Returns items that need user attention — decaying entities, conflicts, or ambiguous mentions. Use this proactively when a conversation touches topics that might have pending items.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Optional topic to filter nudges/clarifications by relevance",
                    }
                },
            },
        },
    ]

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            respond(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "cicada-bookworm",
                    "version": "0.1.0",
                },
            })

        elif method == "notifications/initialized":
            # Client acknowledged init — no response needed
            pass

        elif method == "tools/list":
            respond(req_id, {"tools": tools})

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            try:
                result = handle_tool(tool_name, arguments)
                respond(req_id, {
                    "content": [{"type": "text", "text": result}],
                })
            except Exception as e:
                respond(req_id, {
                    "content": [{"type": "text", "text": f"Error: {e}"}],
                    "isError": True,
                })

        elif req_id is not None:
            # Unknown method with an id — return error
            respond_error(req_id, -32601, f"Method not found: {method}")


def respond(req_id, result):
    """Send a JSON-RPC success response."""
    response = {"jsonrpc": "2.0", "id": req_id, "result": result}
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def respond_error(req_id, code, message):
    """Send a JSON-RPC error response."""
    response = {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


# --- Tool Handlers ---

def get_memory_path() -> Path:
    """Resolve the memory directory path."""
    import os
    env_path = os.environ.get("CICADA_MEMORY_PATH")
    if env_path:
        return Path(env_path)
    return Path.home() / "cicada" / "memory"


def handle_tool(name: str, arguments: dict) -> str:
    if name == "cicada_recall":
        return handle_recall(arguments.get("query", ""))
    elif name == "cicada_save_episode":
        return handle_save_episode(
            arguments.get("content", ""),
            arguments.get("title"),
        )
    elif name == "cicada_check_nudges":
        return handle_check_nudges(arguments.get("topic"))
    else:
        raise ValueError(f"Unknown tool: {name}")


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter without requiring pyyaml. Simple key: value parsing."""
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    fm = {}
    current_key = None
    current_list = None

    for line in parts[1].strip().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_key:
            if current_list is None:
                current_list = []
                fm[current_key] = current_list
            current_list.append(stripped[2:].strip().strip("'\""))
            continue

        current_list = None
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip().strip("'\"")
            current_key = key
            if value.startswith("[") and value.endswith("]"):
                # Inline list: [a, b, c]
                items = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
                fm[key] = items
            elif value:
                # Try to parse numbers
                try:
                    fm[key] = float(value) if "." in value else int(value)
                except ValueError:
                    fm[key] = value
            else:
                fm[key] = None

    return fm, parts[2].strip()


def handle_recall(query: str) -> str:
    """Search the knowledge graph for entities matching the query."""
    memory_path = get_memory_path()
    entities_dir = memory_path / "entities"

    if not entities_dir.exists():
        return "No entities found. The knowledge graph is empty."

    query_lower = query.lower()
    matches = []

    for filepath in sorted(entities_dir.glob("*.md")):
        content = filepath.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)

        name = fm.get("name", filepath.stem.replace("-", " "))
        tags = fm.get("tags", []) if isinstance(fm.get("tags"), list) else []
        related = fm.get("related", []) if isinstance(fm.get("related"), list) else []

        relevance = 0
        if query_lower in name.lower():
            relevance += 10
        if any(query_lower in t.lower() for t in tags):
            relevance += 5
        if any(query_lower in r.lower() for r in related):
            relevance += 3
        if query_lower in body.lower():
            relevance += 2

        if relevance > 0:
            matches.append((relevance, {
                "id": filepath.stem,
                "name": name,
                "type": fm.get("type", "unknown"),
                "status": fm.get("status", "unknown"),
                "confidence": fm.get("confidence", 0),
                "tags": tags,
                "related": related,
                "content": body[:500],
            }))

    matches.sort(key=lambda x: -x[0])

    if not matches:
        return f"No entities found matching '{query}'."

    lines = [f"Found {len(matches)} relevant entities:\n"]
    for _, entity in matches[:5]:
        lines.append(f"**{entity['name']}** ({entity['type']}, {entity['status']}, confidence: {entity['confidence']})")
        lines.append(f"  Tags: {', '.join(entity['tags'])}")
        lines.append(f"  Related: {', '.join(entity['related'])}")
        lines.append(f"  {entity['content'][:200]}...")
        lines.append("")

    return "\n".join(lines)


def handle_save_episode(content: str, title: str | None) -> str:
    """Save content as a new episode for the next Sleep cycle."""
    import hashlib

    memory_path = get_memory_path()
    episodes_dir = memory_path / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    existing = list(episodes_dir.glob(f"ep_{today}_*.md"))
    next_num = len(existing) + 1
    episode_id = f"ep_{today}_{next_num:03d}"

    content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]

    # Check for duplicates
    for filepath in episodes_dir.glob("*.md"):
        text = filepath.read_text(encoding="utf-8")
        if f"content_hash: {content_hash}" in text:
            return f"Episode already exists (duplicate detected by content hash)."

    frontmatter = f"""---
id: {episode_id}
timestamp: '{datetime.now().isoformat()}Z'
source: mcp
title: {title or 'MCP capture'}
processed: false
content_hash: {content_hash}
---"""

    filepath = episodes_dir / f"{episode_id}.md"
    filepath.write_text(f"{frontmatter}\n\n{content}\n", encoding="utf-8")

    return f"Episode saved as {episode_id}. It will be processed during the next Sleep cycle."


def handle_check_nudges(topic: str | None) -> str:
    """Check for pending nudges and clarifications."""
    memory_path = get_memory_path()
    results = []

    # Check nudges
    nudges_dir = memory_path / "nudges"
    if nudges_dir.exists():
        for filepath in sorted(nudges_dir.glob("*.md")):
            content = filepath.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(content)

            if topic:
                # Filter by relevance to topic
                combined = f"{fm.get('entity_name', '')} {fm.get('short_description', '')} {body}".lower()
                if topic.lower() not in combined:
                    continue

            results.append(
                f"**Nudge ({fm.get('type', 'unknown')})**: {fm.get('entity_name', 'Unknown')} — {fm.get('short_description', '')}\n  {body[:200]}"
            )

    # Check clarifications
    clar_dir = memory_path / "clarifications"
    if clar_dir.exists():
        for filepath in sorted(clar_dir.glob("*.md")):
            content = filepath.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(content)

            if topic:
                combined = f"{fm.get('entity_mention', '')} {body}".lower()
                if topic.lower() not in combined:
                    continue

            results.append(
                f"**Clarification**: {fm.get('entity_mention', 'Unknown')} — {fm.get('uncertainty_type', '')}\n  {body[:200]}"
            )

    if not results:
        return "No pending nudges or clarifications" + (f" related to '{topic}'" if topic else "") + "."

    return f"Found {len(results)} pending items:\n\n" + "\n\n".join(results)


if __name__ == "__main__":
    main()
