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

# Allow importing sibling packages (api.services.leann_indexer) when run as a script
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# MCP protocol uses JSON-RPC 2.0 over stdin/stdout


def main():
    """Main loop: read JSON-RPC requests from stdin, write responses to stdout."""
    # Server capabilities
    tools = [
        {
            "name": "cicada_recall",
            "description": "Search Cicada's knowledge graph for entities related to a topic. Returns concise summaries (Pass 1). Pending nudges and clarifications are surfaced first when relevant. Use this at the start of conversations to check what Cicada already knows about the topic being discussed.",
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
            "name": "cicada_recall_detail",
            "description": "Return the FULL entity page for a specific entity. Use this as Pass 2 after cicada_recall when you need the complete description and history — not a summary.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "The entity ID (e.g. 'figure-ai') or entity name from a cicada_recall result.",
                    }
                },
                "required": ["entity_id"],
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
    elif name == "cicada_recall_detail":
        return handle_recall_detail(arguments.get("entity_id", ""))
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


SHORT_TYPES = {"deadline", "skill"}
MEDIUM_TYPES = {"person", "location"}
MEDIUMLONG_TYPES = {"tool", "concept"}


def handle_recall(query: str) -> str:
    """Two-source retrieval with progressive disclosure.

    Pass 1 (this tool): summaries + proactive nudges/clarifications.
    Pass 2: cicada_recall_detail for the full page of a specific entity.
    """
    memory_path = get_memory_path()
    entities_dir = memory_path / "entities"

    if not entities_dir.exists():
        return "No entities found. The knowledge graph is empty."

    output_parts: list[str] = []

    # === Proactive: pending nudges & clarifications related to the query ===
    nudge_blurbs = _relevant_nudges(memory_path, query)
    if nudge_blurbs:
        output_parts.append(
            "**Pending nudges relevant to this query:**\n" + "\n".join(nudge_blurbs)
        )

    clar_blurbs = _relevant_clarifications(memory_path, query)
    if clar_blurbs:
        output_parts.append(
            "**Pending clarifications — you may be able to resolve these:**\n"
            + "\n".join(clar_blurbs)
        )

    # === Source 1: LEANN semantic search over entities ===
    semantic = _leann_search_entities(memory_path, query, top_k=5)

    # === Source 2: keyword fallback for exact-name matches ===
    keyword = _keyword_search_entities(entities_dir, query, top_k=5)

    # Merge by entity_id while preserving order
    seen_ids: set[str] = set()
    merged: list[dict] = []
    for hit in semantic + keyword:
        eid = hit.get("entity_id") or hit.get("id")
        if not eid or eid in seen_ids:
            continue
        seen_ids.add(eid)
        merged.append(hit)

    if not merged and not nudge_blurbs and not clar_blurbs:
        return f"No entities found matching '{query}'."

    # === Render type-aware entity summaries ===
    entity_blocks: list[str] = []
    for hit in merged[:7]:
        block = _render_entity_summary(entities_dir, hit)
        if block:
            entity_blocks.append(block)

    if entity_blocks:
        output_parts.append("\n\n".join(entity_blocks))

    # === Wikilink traversal: one hop out from the top entities ===
    hop_blurbs: list[str] = []
    for hit in merged[:3]:
        eid = hit.get("entity_id") or hit.get("id")
        if not eid:
            continue
        entity_path = entities_dir / f"{eid}.md"
        if not entity_path.exists():
            continue
        fm, _ = parse_frontmatter(entity_path.read_text(encoding="utf-8"))
        related = fm.get("related", []) or []
        if not isinstance(related, list):
            continue
        for related_name in related[:3]:
            related_id = _entity_id_for_name(entities_dir, related_name)
            if not related_id or related_id in seen_ids:
                continue
            seen_ids.add(related_id)
            related_path = entities_dir / f"{related_id}.md"
            if not related_path.exists():
                continue
            r_fm, r_body = parse_frontmatter(related_path.read_text(encoding="utf-8"))
            hop_blurbs.append(
                f"- **{r_fm.get('name', related_id)}** (via [[{fm.get('name', eid)}]]): "
                f"{r_body[:240].strip()}"
            )
    if hop_blurbs:
        output_parts.append("**Related (one hop out):**\n" + "\n".join(hop_blurbs))

    # === Related conversation excerpts from LEANN episode index ===
    episode_hits = _leann_search_episodes(memory_path, query, top_k=3)
    if episode_hits:
        ep_lines = ["**Related conversation excerpts:**"]
        for ep in episode_hits:
            meta = ep.get("metadata", {}) or {}
            ep_id = meta.get("episode_id", "unknown")
            snippet = (ep.get("text") or "")[:400].strip().replace("\n", " ")
            ep_lines.append(f"- [{ep_id}] {snippet}")
        output_parts.append("\n".join(ep_lines))

    return "\n\n".join(output_parts).strip() or f"No entities found matching '{query}'."


def handle_recall_detail(entity_id: str) -> str:
    """Return the full entity page for one entity (Pass 2)."""
    memory_path = get_memory_path()
    entities_dir = memory_path / "entities"
    if not entity_id:
        return "entity_id is required."

    candidate_ids = [entity_id]
    # Also try name -> id
    resolved = _entity_id_for_name(entities_dir, entity_id)
    if resolved and resolved != entity_id:
        candidate_ids.append(resolved)

    for cid in candidate_ids:
        path = entities_dir / f"{cid}.md"
        if path.exists():
            return path.read_text(encoding="utf-8")

    return f"Entity '{entity_id}' not found."


# ---------- Helpers: search sources ----------


def _leann_search_entities(memory_path: Path, query: str, top_k: int) -> list[dict]:
    try:
        from api.services.leann_indexer import LeannIndexer
    except Exception:
        return []
    try:
        indexer = LeannIndexer(memory_path)
        results = indexer.search_entities(query, top_k=top_k)
    except Exception:
        return []

    out: list[dict] = []
    for r in results:
        meta = r.get("metadata", {}) or {}
        eid = meta.get("entity_id")
        if not eid:
            continue
        out.append({
            "entity_id": eid,
            "source": "leann",
            "score": r.get("score", 0.0),
            "text": r.get("text", ""),
            "metadata": meta,
        })
    return out


def _leann_search_episodes(memory_path: Path, query: str, top_k: int) -> list[dict]:
    try:
        from api.services.leann_indexer import LeannIndexer
    except Exception:
        return []
    try:
        indexer = LeannIndexer(memory_path)
        return indexer.search_episodes(query, top_k=top_k)
    except Exception:
        return []


def _keyword_search_entities(entities_dir: Path, query: str, top_k: int) -> list[dict]:
    query_lower = query.lower()
    scored: list[tuple[int, dict]] = []
    for filepath in sorted(entities_dir.glob("*.md")):
        content = filepath.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)
        name = str(fm.get("name", filepath.stem.replace("-", " ")))
        tags = fm.get("tags", []) if isinstance(fm.get("tags"), list) else []
        related = fm.get("related", []) if isinstance(fm.get("related"), list) else []

        relevance = 0
        if query_lower in name.lower():
            relevance += 10
        if any(query_lower in str(t).lower() for t in tags):
            relevance += 5
        if any(query_lower in str(r).lower() for r in related):
            relevance += 3
        if query_lower in body.lower():
            relevance += 2

        if relevance > 0:
            scored.append((relevance, {
                "entity_id": filepath.stem,
                "source": "keyword",
                "score": float(relevance),
            }))

    scored.sort(key=lambda x: -x[0])
    return [s[1] for s in scored[:top_k]]


def _render_entity_summary(entities_dir: Path, hit: dict) -> str:
    eid = hit.get("entity_id")
    if not eid:
        return ""
    path = entities_dir / f"{eid}.md"
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)

    name = str(fm.get("name", eid.replace("-", " ")))
    etype = str(fm.get("type", "unknown"))
    status = str(fm.get("status", "unknown"))
    confidence = fm.get("confidence", 0)
    related = fm.get("related", []) or []

    truncated = _type_aware_truncate(body, etype)

    lines = [
        f"### {name} ({etype}, confidence: {confidence}, status: {status})",
    ]
    if related:
        lines.append(f"Related: {', '.join(str(r) for r in related)}")
    if truncated:
        lines.append("")
        lines.append(truncated)
    return "\n".join(lines)


def _type_aware_truncate(body: str, entity_type: str) -> str:
    if not body:
        return ""
    if entity_type in SHORT_TYPES:
        return body
    if entity_type in MEDIUM_TYPES:
        return body[:2000]
    if entity_type in MEDIUMLONG_TYPES:
        return body[:3200]
    # project, company, etc — description + last 10 history entries
    return _truncate_to_desc_and_recent_history(body, max_history=10)


def _truncate_to_desc_and_recent_history(body: str, max_history: int = 10) -> str:
    if "## History" not in body:
        return body[:3200]
    head, _, tail = body.partition("## History")
    description = head.strip()
    history_lines = [
        line for line in tail.splitlines() if line.strip().startswith("- ")
    ]
    recent = history_lines[-max_history:]
    return f"{description}\n\n## History\n" + "\n".join(recent)


def _entity_id_for_name(entities_dir: Path, name: str) -> str | None:
    target = str(name).strip().lower()
    if not target:
        return None
    # Direct id match
    direct = entities_dir / f"{target.replace(' ', '-')}.md"
    if direct.exists():
        return direct.stem
    # Scan frontmatter names
    for filepath in entities_dir.glob("*.md"):
        content = filepath.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter(content)
        fm_name = str(fm.get("name", "")).lower()
        if fm_name == target or filepath.stem.lower() == target:
            return filepath.stem
    return None


def _relevant_nudges(memory_path: Path, query: str) -> list[str]:
    nudges_dir = memory_path / "nudges"
    if not nudges_dir.exists():
        return []
    q = query.lower()
    blurbs: list[str] = []
    for filepath in sorted(nudges_dir.glob("*.md")):
        content = filepath.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)
        haystack = (
            f"{fm.get('entity_name', '')} "
            f"{fm.get('short_description', '')} "
            f"{body}"
        ).lower()
        if not _topic_matches(q, haystack):
            continue
        ntype = fm.get("type", "unknown")
        ename = fm.get("entity_name", "Unknown")
        desc = fm.get("short_description", "")
        blurbs.append(f"- [{ntype}] **{ename}** — {desc}")
    return blurbs


def _relevant_clarifications(memory_path: Path, query: str) -> list[str]:
    clar_dir = memory_path / "clarifications"
    if not clar_dir.exists():
        return []
    q = query.lower()
    blurbs: list[str] = []
    for filepath in sorted(clar_dir.glob("*.md")):
        content = filepath.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)
        haystack = (
            f"{fm.get('entity_mention', '')} {body}"
        ).lower()
        if not _topic_matches(q, haystack):
            continue
        mention = fm.get("entity_mention", "Unknown")
        utype = fm.get("uncertainty_type", "unknown")
        suggestion = fm.get("suggested_classification", "unknown")
        blurbs.append(
            f"- **{mention}** (uncertain: {utype}, suggested: {suggestion})"
        )
    return blurbs


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
                if not _topic_matches(topic.lower(), combined):
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
                if not _topic_matches(topic.lower(), combined):
                    continue

            results.append(
                f"**Clarification**: {fm.get('entity_mention', 'Unknown')} — {fm.get('uncertainty_type', '')}\n  {body[:200]}"
            )

    if not results:
        return "No pending nudges or clarifications" + (f" related to '{topic}'" if topic else "") + "."

    return f"Found {len(results)} pending items:\n\n" + "\n\n".join(results)


def _topic_matches(query: str, haystack: str) -> bool:
    if not query:
        return True
    if query in haystack:
        return True
    return bool(_content_tokens(query) & _content_tokens(haystack))


def _content_tokens(text: str) -> set[str]:
    import re

    stopwords = {
        "the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "at",
        "de", "del", "la", "el", "los", "las", "with", "about",
    }
    raw = re.findall(r"[\w'-]+", (text or "").lower())
    return {token for token in raw if token not in stopwords and len(token) >= 2}


if __name__ == "__main__":
    main()
