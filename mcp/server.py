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
            "description": "Search Cicada's knowledge graph for entities related to a topic. Returns concise summaries (Pass 1). Pending inbox items are surfaced first when relevant. Use this at the start of conversations to check what Cicada already knows about the topic being discussed.",
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
            "description": "Check for pending inbox items in Cicada's memory system. Returns items that need user attention — decaying entities, conflicts, ambiguous mentions, or possible duplicates. Use this proactively when a conversation touches topics that might have pending items.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Optional topic to filter inbox items by relevance",
                    }
                },
            },
        },
        {
            "name": "cicada_open_hub",
            "description": "Open a Cicada hub page (a topic or type index) and list its member entities with one-line summaries. Use after cicada_recall returns a relevant_hub, or to browse a topic. Pass a hub id like 'people', 'tools', or 'topic-robotics'.",
            "inputSchema": {
                "type": "object",
                "properties": {"hub": {"type": "string"}},
                "required": ["hub"],
            },
        },
        {
            "name": "cicada_save_url",
            "description": "Save a URL (article, video, bookmark) into Cicada's memory as saved media. The link becomes a graph entity and connects to related topics after the next Sleep cycle. Use when the user shares a link worth remembering or says 'save this'.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to save"},
                    "note": {
                        "type": "string",
                        "description": "Optional note about why this was saved",
                    },
                },
                "required": ["url"],
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
    elif name == "cicada_open_hub":
        return handle_open_hub(arguments.get("hub", ""))
    elif name == "cicada_save_url":
        return handle_save_url(arguments.get("url", ""), arguments.get("note"))
    else:
        raise ValueError(f"Unknown tool: {name}")


def handle_save_url(url: str, note: str | None) -> str:
    """Save a URL as media. Prefers the running backend (shared dedup index,
    background enrichment); falls back to direct ingestion via the api package."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return "Error: URL must start with http:// or https://"

    # Path 1: the FastAPI backend, if it's up.
    try:
        import urllib.request

        payload = json.dumps({"url": url, "note": note}).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:8000/sources/save",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return (
            f"Saved \"{data.get('title', url)}\" as {data.get('mediaType', 'url')} media "
            f"(entity {data.get('mediaEntityId', '?')}). {data.get('message', '')}"
        )
    except Exception:
        pass

    # Path 2: direct ingestion (backend down). Enrichment degrades offline.
    try:
        import asyncio

        import httpx

        from api.services import media_ingestor

        memory_path = get_memory_path()
        (memory_path / "sources").mkdir(parents=True, exist_ok=True)
        (memory_path / "episodes").mkdir(parents=True, exist_ok=True)
        (memory_path / "entities").mkdir(parents=True, exist_ok=True)

        async def _save():
            item = media_ingestor.RawItem(url=url, note=note)
            idx = media_ingestor.load_url_index(memory_path)
            async with httpx.AsyncClient() as client:
                result = await media_ingestor.ingest_one(item, memory_path, client, idx)
            media_ingestor.save_url_index(memory_path, idx)
            return result

        result = asyncio.run(_save())
        if result.status == "duplicate":
            return f"Already saved: \"{result.title}\""
        return (
            f"Saved \"{result.title}\" as {result.media_type} media "
            f"(entity {result.media_entity_id}). It joins the graph after the next Sleep cycle."
        )
    except Exception as e:
        return f"Error: could not save URL ({type(e).__name__}: {e})"


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

    # === Hub-first cold-start check ===
    # Match the query against hub names/tags/types up front. Gives a reliable
    # answer even when LEANN is cold (fresh install, pre-rebuild) and seeds the
    # structured hints block with a relevant hub + its members.
    relevant_hub, hub_member_ids = _match_hub(memory_path, query)

    # === Proactive: pending inbox items related to the query ===
    inbox_blurbs = _relevant_inbox(memory_path, query)
    if inbox_blurbs:
        output_parts.append(
            "**Pending inbox items relevant to this query:**\n"
            + "\n".join(inbox_blurbs)
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

    # === Structured hints block (machine-parseable, emitted first) ===
    # A small model that ignores prose can json.loads this fenced block to get
    # an explicit action list of entity ids and the best-matching hub.
    suggested = [
        (h.get("entity_id") or h.get("id")) for h in merged[:7]
        if (h.get("entity_id") or h.get("id"))
    ]
    if not suggested and hub_member_ids:
        suggested = hub_member_ids[:7]
    hints_block = _hints_block(suggested, relevant_hub, hub_member_ids)
    if hints_block:
        output_parts.append(hints_block)

    if not merged and not inbox_blurbs and not relevant_hub:
        return f"No entities found matching '{query}'."

    # Surface the matched hub's member list when LEANN/keyword found nothing
    # (cold-start path) so the user still gets a navigable answer.
    if relevant_hub and not merged:
        hub_body = _read_hub_body(memory_path, relevant_hub)
        if hub_body:
            output_parts.append(
                f"**Relevant hub — `{relevant_hub}`:**\n{hub_body}"
            )

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


def _hub_files(memory_path: Path):
    hubs_dir = memory_path / "hubs"
    if not hubs_dir.exists():
        return
    for filepath in sorted(hubs_dir.glob("*.md")):
        yield filepath


def _parse_hub_header(content: str) -> dict:
    """Read only the scalar hub-identity keys, stopping at ``members:``.

    The hub frontmatter's ``members:`` is a nested YAML list of dicts that the
    flat ``parse_frontmatter`` cannot read (it would clobber the hub's real
    ``type``/``name`` with the last member's values). All scalar identity keys
    (``type``, ``name``, ``hub_kind``, ``source_tag``, ``source_type``) are
    written before ``members:``, so reading the header up to that line yields
    the correct hub identity without parsing nested YAML.
    """
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    fm: dict = {}
    for line in parts[1].strip().splitlines():
        stripped = line.strip()
        if stripped == "members:" or stripped.startswith("members:"):
            break
        if not stripped or stripped.startswith("#") or stripped.startswith("- "):
            continue
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            fm[key.strip()] = value.strip().strip("'\"")
    return fm


def _match_hub(memory_path: Path, query: str) -> tuple[str | None, list[str]]:
    """Find the hub whose name/source_tag/source_type best overlaps the query.

    Returns ``(relative_hub_path | None, member_ids)``. ``member_ids`` are read
    from the hub BODY's wikilinks via the entity name index — the flat
    pyyaml-free parser cannot read the nested ``members:`` frontmatter list, so
    the body is the authoritative member source on the MCP side.
    """
    q_tokens = _content_tokens(query)
    if not q_tokens:
        return None, []
    entities_dir = memory_path / "entities"
    best: tuple[int, Path | None] = (0, None)
    for filepath in _hub_files(memory_path):
        content = filepath.read_text(encoding="utf-8")
        fm = _parse_hub_header(content)
        if fm.get("type") != "hub":
            continue
        label = " ".join(
            str(fm.get(k, "") or "") for k in ("name", "source_tag", "source_type")
        )
        overlap = len(q_tokens & _content_tokens(label))
        if overlap > best[0]:
            best = (overlap, filepath)
    if not best[1]:
        return None, []
    hub_path = best[1]
    rel = f"hubs/{hub_path.name}"
    _, body = parse_frontmatter(hub_path.read_text(encoding="utf-8"))
    member_ids: list[str] = []
    import re as _re

    for raw in _re.findall(r"\[\[([^\]]+)\]\]", body or ""):
        display = raw.split("|", 1)[0].strip()
        eid = _entity_id_for_name(entities_dir, display)
        if eid and eid not in member_ids:
            member_ids.append(eid)
    return rel, member_ids


def _read_hub_body(memory_path: Path, rel_hub_path: str) -> str:
    """Return a hub file's body verbatim (member list with wikilinks)."""
    filepath = memory_path / rel_hub_path
    if not filepath.exists():
        return ""
    _, body = parse_frontmatter(filepath.read_text(encoding="utf-8"))
    return body


def _hints_block(
    suggested_entities: list[str], relevant_hub: str | None, hub_members: list[str]
) -> str:
    """Render the machine-parseable ``cicada-hints`` fenced JSON block.

    Fenced with the literal info-string ``cicada-hints`` so a small model can
    locate it and ``json.loads`` deterministically.
    """
    if not suggested_entities and not relevant_hub:
        return ""
    payload = {
        "suggested_entities": suggested_entities,
        "relevant_hub": relevant_hub,
        "hub_members_preview": hub_members[:8],
        "next_tool": "cicada_recall_detail",
        "note": "Call cicada_recall_detail with each suggested_entity id for full pages, or cicada_open_hub with relevant_hub for a topic index.",
    }
    return "```cicada-hints\n" + json.dumps(payload, indent=2) + "\n```"


def handle_open_hub(hub: str) -> str:
    """Open a hub page and return its body verbatim (member list).

    Tries ``hubs/<hub>.md`` then ``hubs/topic-<sanitize_id(hub)>.md``. Returns
    the body verbatim — the MCP flat parser never parses the nested members
    frontmatter, so the wikilinked body bullet list is the member source.
    """
    if not hub:
        return "hub is required."
    memory_path = get_memory_path()
    hubs_dir = memory_path / "hubs"
    raw = hub.strip()
    if raw.endswith(".md"):
        raw = raw[:-3]
    if raw.startswith("hubs/"):
        raw = raw[len("hubs/"):]
    if raw.startswith("hub:"):
        raw = raw[len("hub:"):]

    candidates = [raw, f"topic-{_mcp_sanitize_id(raw)}", _mcp_sanitize_id(raw)]
    for cand in candidates:
        path = hubs_dir / f"{cand}.md"
        if path.exists():
            _, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            return body or path.read_text(encoding="utf-8")
    return f"Hub '{hub}' not found."


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


def _mcp_sanitize_id(name: str) -> str:
    """pyyaml-free mirror of api.services.id_utils.sanitize_id.

    The MCP server can't reliably import api.* in every install, so the
    legacy-filename resolution logic is inlined. Keeps lookups tolerant of the
    181 live files whose stem != sanitize_id(name) (e.g. atlético-de-madrid).
    """
    import re

    safe = (name or "").lower()
    safe = re.sub(r"[/\\:*?\"<>|.]+", "-", safe)
    safe = safe.replace(" ", "-")
    safe = re.sub(r"-+", "-", safe)
    safe = safe.strip("-")
    return safe or "unnamed"


def _entity_id_for_name(entities_dir: Path, name: str) -> str | None:
    """Resolve a name-or-id ref to a real filepath.stem, multi-strategy.

    Tries, in order: exact file <ref>.md, file <sanitize_id(ref)>.md,
    file <ref.replace(' ','-')>.md, then a frontmatter-name / stem scan.
    Mirrors api.services.id_utils.resolve_entity_id without importing it.
    """
    raw = str(name).strip()
    if not raw:
        return None
    if not entities_dir.exists():
        return None

    target = raw.lower()
    sanitized_target = _mcp_sanitize_id(raw)
    slug_target = target.replace(" ", "-")

    # Scan glob stems first — they are the authoritative on-disk ids. A bare
    # Path.exists() check would lie on case-insensitive filesystems (macOS),
    # echoing the requested casing instead of the real stem.
    for filepath in entities_dir.glob("*.md"):
        stem = filepath.stem.lower()
        if stem in (target, sanitized_target, slug_target):
            return filepath.stem
        content = filepath.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter(content)
        if str(fm.get("name", "")).lower() == target:
            return filepath.stem
    return None


def _inbox_dirs(memory_path: Path) -> list[Path]:
    """Return the unified inbox dir, falling back to the legacy dirs.

    Keeps the MCP server correct before the API has run migration once (a stale
    checkout may still have nudges/ + clarifications/ but no inbox/).
    """
    inbox = memory_path / "inbox"
    if inbox.exists():
        return [inbox]
    legacy = [memory_path / "nudges", memory_path / "clarifications"]
    return [d for d in legacy if d.exists()]


def _inbox_files(memory_path: Path):
    for d in _inbox_dirs(memory_path):
        for filepath in sorted(d.glob("*.md")):
            yield filepath


def _format_inbox_blurb(fm: dict, body: str) -> str:
    kind = str(fm.get("kind", fm.get("type", "")) or "")
    ename = fm.get("entity_name", fm.get("entity_mention", "Unknown"))
    if kind in ("clarification", "merge_suggestion"):
        utype = fm.get("uncertainty_type", "unknown")
        suggestion = fm.get("suggested_classification", "unknown")
        return f"- **{ename}** (uncertain: {utype}, suggested: {suggestion})"
    # decay/conflict (and legacy nudges where kind lived in "type")
    if not kind and fm.get("uncertainty_type"):
        utype = fm.get("uncertainty_type", "unknown")
        suggestion = fm.get("suggested_classification", "unknown")
        return f"- **{ename}** (uncertain: {utype}, suggested: {suggestion})"
    title = fm.get("title", fm.get("short_description", ""))
    label = kind or "item"
    return f"- [{label}] **{ename}** — {title}"


def _relevant_inbox(memory_path: Path, query: str) -> list[str]:
    q = query.lower()
    blurbs: list[str] = []
    for filepath in _inbox_files(memory_path):
        content = filepath.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)
        haystack = (
            f"{fm.get('entity_name', '')} "
            f"{fm.get('entity_mention', '')} "
            f"{fm.get('title', '')} "
            f"{fm.get('short_description', '')} "
            f"{body}"
        ).lower()
        if not _topic_matches(q, haystack):
            continue
        blurbs.append(_format_inbox_blurb(fm, body))
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
    """Check for pending inbox items (decay/conflict/clarification/merge)."""
    memory_path = get_memory_path()
    results = []

    for filepath in _inbox_files(memory_path):
        content = filepath.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)

        if topic:
            combined = (
                f"{fm.get('entity_name', '')} "
                f"{fm.get('entity_mention', '')} "
                f"{fm.get('title', '')} "
                f"{fm.get('short_description', '')} "
                f"{fm.get('uncertainty_type', '')} "
                f"{body}"
            ).lower()
            if not _topic_matches(topic.lower(), combined):
                continue

        kind = str(fm.get("kind", fm.get("type", "")) or "")
        ename = fm.get("entity_name", fm.get("entity_mention", "Unknown"))
        if kind in ("clarification", "merge_suggestion") or (
            not kind and fm.get("uncertainty_type")
        ):
            results.append(
                f"**Clarification**: {ename} — {fm.get('uncertainty_type', '')}\n  {body[:200]}"
            )
        else:
            title = fm.get("title", fm.get("short_description", ""))
            results.append(
                f"**{kind or 'Item'}**: {ename} — {title}\n  {body[:200]}"
            )

    if not results:
        return "No pending inbox items" + (f" related to '{topic}'" if topic else "") + "."

    return f"Found {len(results)} pending inbox items:\n\n" + "\n\n".join(results)


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
