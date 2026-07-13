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

# Allow importing sibling packages (api.services.vector_index) when run as a script
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# MCP protocol uses JSON-RPC 2.0 over stdin/stdout

# Tool list advertised via `tools/list` and dispatched via `tools/call`. Kept at
# module scope (not local to main()) so both main() and other modules (e.g. a
# future cicada_sources tool, and tests like test_mcp_tool_descriptions.py) can
# reference the same TOOLS constant without re-running the JSON-RPC loop.
TOOLS = [
    {
        "name": "cicada_recall",
        "description": "Search Cicada's knowledge graph for entities related to a topic. Returns concise summaries (Pass 1). Pending inbox items are surfaced first when relevant. Use this at the start of conversations to check what Cicada already knows about the topic being discussed. If a fact might exist, call cicada_recall_detail on the top suggested entity before concluding it is absent. State only facts present in tool results; do not add adjacent details from general knowledge.",
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
        "name": "cicada_ask",
        "description": "Ask Cicada's memory a natural-language question and get a synthesized answer that CITES the entities it used and explicitly states what it could NOT answer (gaps). Grounded only in stored memory — it says 'I don't know' rather than guessing. Use when you want a direct answer rather than a list of entities to read yourself. Prefer this tool for direct factual questions — it reads full entity pages and claims and returns an answer with citations and an explicit gap list.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The natural-language question to ask of memory.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "How many entities to retrieve as grounding context (default 6).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "cicada_get_perspective",
        "description": "Return a subject's currently-valid claims from a specific PERSPECTIVE — optionally filtered by observer (who holds the belief: 'agent', 'rodrigo', or 'external:<name>') and/or context (e.g. 'engineering', 'family', 'career'). Use when you need to know who believes what about a subject, or want only one facet of a subject (e.g. engineer-Rodrigo vs family-Rodrigo). Each claim carries its observer, context, source_trust, confidence, and valid-from date so you can attribute beliefs honestly.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "The subject entity id or name (e.g. 'rodrigo', 'cicada').",
                },
                "observer": {
                    "type": "string",
                    "description": "Optional. Filter to one observer: 'agent', 'rodrigo', or 'external:<name>'.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional. Filter to one context facet (e.g. 'engineering', 'family', 'career').",
                },
            },
            "required": ["subject"],
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
    {
        "name": "cicada_sources",
        "description": "Return the primary source conversation chunks that produced an entity "
                       "(the episodes it was consolidated from). Use this to ground or verify a "
                       "fact against what the user actually said, or to show provenance.",
        "inputSchema": {
            "type": "object",
            "properties": {"entity_id": {"type": "string",
                "description": "The entity id (e.g. 'diego-sanmartin') to fetch sources for."}},
            "required": ["entity_id"],
        },
    },
    {
        "name": "cicada_write_claim",
        "description": "Write ONE atomic fact into Cicada's memory as a structured, observer-tagged claim (subject-predicate-object), reusing the same trust-gated reconciliation the nightly Sleep cycle uses. Tag observer='rodrigo' ONLY for something the USER explicitly stated themselves — this claim becomes trust-protected and can never be silently overwritten by a later agent claim. Tag observer='agent' for something YOU inferred, deduced, or noticed yourself. Tag observer='external' for a fact attributed to a third party. Write ONE claim per atomic fact — never bundle multiple facts into a single call. If the subject has no entity page yet, a minimal one is created automatically. A lower-trust claim never overwrites a higher-trust one; it either coexists (flagged) or is held back for a nudge.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "The entity the claim is about (e.g. 'Rodrigo', 'Cicada').",
                },
                "predicate": {
                    "type": "string",
                    "description": "The relation/verb (e.g. 'works-at', 'prefers', 'uses').",
                },
                "object": {
                    "type": "string",
                    "description": "The value or target entity of the claim (e.g. 'Figure AI', 'concise summaries').",
                },
                "observer": {
                    "type": "string",
                    "enum": ["rodrigo", "agent", "external"],
                    "description": "Who holds this belief. 'rodrigo' = the user stated this themselves (trust-protected). 'agent' = you inferred/extracted this. 'external' = attributed to a third party. Defaults to 'agent'.",
                },
                "confidence": {
                    "type": "number",
                    "description": "Optional confidence 0.0-1.0 (default 0.7).",
                },
                "context": {
                    "type": "string",
                    "description": "Optional facet this claim belongs to (e.g. 'engineering', 'family', 'career'). Default 'general'.",
                },
                "source_episode": {
                    "type": "string",
                    "description": "Optional episode id this claim was grounded in (e.g. from cicada_save_episode or cicada_pending).",
                },
                "force_new_entity": {
                    "type": "boolean",
                    "description": "Only set true after an 'ambiguous subject' response, when none of the suggested near-match entities is the intended subject — creates a genuinely new entity page despite the near-matches. Default false.",
                },
            },
            "required": ["subject", "predicate", "object"],
        },
    },
    {
        "name": "cicada_pending",
        "description": "List Cicada episodes not yet consolidated into the knowledge graph (processed: false). Use this to see what raw conversation material is waiting, then use cicada_write_claim to consolidate atomic facts out of it yourself, and cicada_mark_processed once you're done with an episode — this lets an agent do its own lightweight consolidation between Sleep cycles.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max number of unprocessed episodes to return (default 50).",
                },
            },
        },
    },
    {
        "name": "cicada_mark_processed",
        "description": "Mark episodes as processed (processed: true) after you have consolidated their facts via cicada_write_claim. Only mark an episode processed once you have actually extracted what's worth keeping from it — an unmarked episode is still picked up by the next Sleep cycle as a safety net.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "episode_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The episode ids to mark processed (e.g. ['ep_2026-07-02_001']).",
                },
            },
            "required": ["episode_ids"],
        },
    },
    {
        "name": "cicada_repo_context",
        "description": "Return live git context (branch, ahead/behind, dirty files, worktrees, last commit) for a repo Cicada knows about — either an entity that declares a `repos:` link, or a raw filesystem path. Use when the user asks about the state of a project's git repo/checkout, or before suggesting git actions, so you're grounded in what's actually on disk right now rather than guessing. Degrades gracefully (e.g. 'repo context unavailable (...)') when the path is missing, not a git repo, or belongs to a different device.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "An entity id or name that declares a `repos:` link (e.g. 'cicada'). Exactly one of entity_id/path is required.",
                },
                "path": {
                    "type": "string",
                    "description": "A raw filesystem path to a git repo (e.g. '~/Documents/roros_lab/cicada'). Exactly one of entity_id/path is required.",
                },
            },
        },
    },
]


def main():
    """Main loop: read JSON-RPC requests from stdin, write responses to stdout."""
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
            respond(req_id, {"tools": TOOLS})

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
    """Resolve the *active memory bank* directory.

    ``CICADA_MEMORY_PATH`` names the memory **root** (the container of
    ``banks.yaml`` + ``banks/<name>/``), not a bank. The API resolves the active
    bank from that root via ``bank_registry.resolve_active_bank_path``; the MCP
    MUST do the same or it serves a different graph than the app/Sleep cycle
    (the "split-brain" bug — recall reads the stale legacy root while the vector
    index + fresh episodes live in the active bank). We import the API resolver
    and fall back to the raw root only if it is unavailable, so a bank switch
    (which rewrites ``banks.yaml``, not the env var) takes effect live.
    """
    import os
    env_path = os.environ.get("CICADA_MEMORY_PATH")
    root = Path(env_path) if env_path else Path.home() / "cicada" / "memory"
    try:
        from api.services.bank_registry import resolve_active_bank_path

        return resolve_active_bank_path(root)
    except Exception:
        # Registry not importable / no banks.yaml → root IS the bank
        # (identical to pre-banks behavior).
        return root


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
    elif name == "cicada_ask":
        return handle_ask(arguments.get("query", ""), arguments.get("top_k", 6))
    elif name == "cicada_get_perspective":
        return handle_get_perspective(
            arguments.get("subject", ""),
            arguments.get("observer"),
            arguments.get("context"),
        )
    elif name == "cicada_save_url":
        return handle_save_url(arguments.get("url", ""), arguments.get("note"))
    elif name == "cicada_sources":
        return handle_sources(arguments.get("entity_id", ""))
    elif name == "cicada_write_claim":
        return handle_write_claim(
            arguments.get("subject", ""),
            arguments.get("predicate", ""),
            arguments.get("object", ""),
            arguments.get("observer", "agent"),
            arguments.get("confidence"),
            arguments.get("context"),
            arguments.get("source_episode"),
            bool(arguments.get("force_new_entity", False)),
        )
    elif name == "cicada_pending":
        return handle_pending(arguments.get("limit"))
    elif name == "cicada_mark_processed":
        return handle_mark_processed(arguments.get("episode_ids"))
    elif name == "cicada_repo_context":
        return handle_repo_context(arguments.get("entity_id"), arguments.get("path"))
    else:
        raise ValueError(f"Unknown tool: {name}")


def handle_ask(query: str, top_k: int = 6) -> str:
    """Answer a NL question over memory with citations + explicit gaps.

    Prefers the running FastAPI backend (POST /ask) so the synthesis uses the
    configured litellm model + sqlite-vec index. Falls back to calling the
    ask_service directly when the backend is down (degrades like cicada_save_url).
    The rendered text always shows the answer, what it could NOT answer (gaps),
    and the entity citations — the auditable-synthesis contract.
    """
    query = (query or "").strip()
    if not query:
        return "query is required."
    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        top_k = 6

    result: dict | None = None

    # Path 1: the FastAPI backend, if it's up (has the LLM wired).
    try:
        import urllib.request

        payload = json.dumps({"query": query, "topK": top_k}).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:8000/ask",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # API serializes camelCase; normalize back to the service dict shape.
        result = {
            "answer": data.get("answer", ""),
            "confidence": data.get("confidence", 0.0),
            "citations": [
                {
                    "entity_id": c.get("entityId", c.get("entity_id", "")),
                    "entity_name": c.get("entityName", c.get("entity_name", "")),
                    "source_episodes": c.get("sourceEpisodes", c.get("source_episodes", [])),
                }
                for c in data.get("citations", []) or []
            ],
            "gaps": data.get("gaps", []) or [],
            "used_entities": data.get("usedEntities", data.get("used_entities", [])) or [],
        }
    except Exception:
        result = None

    # Path 2: direct service call (backend down). Uses the configured litellm
    # model + local sqlite-vec index via the service defaults.
    if result is None:
        try:
            from api.services import ask_service

            result = ask_service.answer_query(get_memory_path(), query, top_k=top_k)
        except Exception as e:
            return f"Error: could not answer ({type(e).__name__}: {e})"

    return _render_ask(result)


def _render_ask(result: dict) -> str:
    lines = [result.get("answer", "").strip()]
    confidence = result.get("confidence", 0.0)
    try:
        lines.append(f"\n_Confidence: {float(confidence):.2f}_")
    except (TypeError, ValueError):
        pass

    gaps = result.get("gaps", []) or []
    if gaps:
        lines.append("\n**Could not answer / missing from memory:**")
        lines.extend(f"- {g}" for g in gaps)

    citations = result.get("citations", []) or []
    if citations:
        lines.append("\n**Citations:**")
        for c in citations:
            name = c.get("entity_name", c.get("entity_id", "?"))
            eps = c.get("source_episodes", []) or []
            ep_note = f" (episodes: {', '.join(eps)})" if eps else ""
            lines.append(f"- [[{name}]]{ep_note}")

    return "\n".join(lines).strip()


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


def _rrf_fuse(*ranked_lists, k: int = 60) -> list[dict]:
    """Reciprocal-rank fusion over hit lists keyed by entity_id.

    score(id) = sum over lists of 1/(k + rank). Rewards ids that rank well in
    multiple sources (a strong keyword AND vector hit reinforce). Keeps the
    first-seen hit dict per id.
    """
    scores: dict[str, float] = {}
    keep: dict[str, dict] = {}
    for lst in ranked_lists:
        for rank, hit in enumerate(lst):
            eid = hit.get("entity_id") or hit.get("id")
            if not eid:
                continue
            scores[eid] = scores.get(eid, 0.0) + 1.0 / (k + rank)
            keep.setdefault(eid, hit)
    ordered = sorted(scores, key=lambda e: -scores[e])
    return [keep[e] for e in ordered]


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

    # === Sources 1+2: semantic + keyword, rank-fused ===
    semantic = _leann_search_entities(memory_path, query, top_k=8)
    keyword = _keyword_search_entities(entities_dir, query, top_k=8)
    merged = _rrf_fuse(semantic, keyword)
    seen_ids: set[str] = {h.get("entity_id") or h.get("id") for h in merged}

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


def handle_sources(entity_id: str) -> str:
    """Render the source episode chunks behind an entity (chunks mode)."""
    try:
        from api.services.entity_sources import gather_entity_sources
        bundle = gather_entity_sources(get_memory_path(), entity_id, mode="chunks")
    except Exception as exc:  # pragma: no cover
        return f"Could not gather sources for '{entity_id}': {exc}"
    eps = bundle.get("episodes", [])
    if not eps:
        return f"No source episodes found for '{entity_id}'."
    parts = [f"**Sources for `{entity_id}`** ({len(eps)} episode(s)):"]
    for e in eps:
        parts.append(f"\n### episode {e['id']}\n{(e.get('chunk') or '').strip()[:2000]}")
    return "\n".join(parts)


def handle_write_claim(
    subject: str,
    predicate: str,
    object_: str,
    observer: str | None,
    confidence,
    context: str | None,
    source_episode: str | None,
    force_new_entity: bool = False,
) -> str:
    """Write one atomic fact as an observer-tagged claim (agentic write path)."""
    from api.services import agentic_write

    result = agentic_write.write_claim(
        get_memory_path(),
        subject,
        predicate,
        object_,
        observer=(observer or "agent"),
        confidence=confidence if confidence is not None else 0.7,
        context=(context or "general"),
        source_episode=source_episode,
        force_new_entity=force_new_entity,
    )

    if result.get("action") == "ambiguous_subject":
        lines = [
            f"NOT written — ambiguous subject '{subject}'. Existing entities are close matches:"
        ]
        for cand in result.get("candidates", []):
            lines.append(f"  - {cand['entity_id']} (match {cand['score']})")
        lines.append(
            "Re-issue cicada_write_claim with the intended entity_id as the subject, "
            "or force_new_entity=true if this is genuinely a different, new entity."
        )
        return "\n".join(lines)

    if result.get("action") == "error" or result.get("error"):
        return f"Could not write claim: {result.get('error', 'unknown error')}"

    action = result.get("action")
    verb = {
        "written": "Recorded",
        "coexist": "Recorded alongside an existing user-stated claim (flagged for review)",
        "superseded": "NOT written — an existing higher-trust claim already covers this",
    }.get(action, "Recorded")

    return (
        f"{verb}: {subject} {predicate} {object_} "
        f"(entity `{result.get('entity_id')}`, claim `{result.get('claim_id')}`, "
        f"observer={result.get('observer')}, action={action})."
    )


def handle_pending(limit) -> str:
    """List unprocessed episodes for the agent's own consolidation loop."""
    from api.services import agentic_write

    try:
        limit = int(limit) if limit is not None else 50
    except (TypeError, ValueError):
        limit = 50

    episodes = agentic_write.list_unprocessed_episodes(get_memory_path(), limit=limit)
    if not episodes:
        return "No unprocessed episodes pending."

    lines = [f"{len(episodes)} unprocessed episode(s):"]
    for ep in episodes:
        snippet = (ep.get("content") or "")[:300].strip().replace("\n", " ")
        lines.append(f"- `{ep.get('id')}` — {ep.get('title', '')}: {snippet}")
    return "\n".join(lines)


def handle_mark_processed(episode_ids) -> str:
    """Flip processed:true on the given episode ids."""
    from api.services import agentic_write

    if not isinstance(episode_ids, list) or not episode_ids:
        return "episode_ids is required (a non-empty array of episode ids)."

    count = agentic_write.mark_episodes_processed(get_memory_path(), episode_ids)
    return f"Marked {count} episode(s) as processed."


def handle_repo_context(entity_id: str | None, path: str | None) -> str:
    """Live git context for a repo Cicada knows about (backlog G-repo).

    Exactly one of ``entity_id`` / ``path`` is required. ``entity_id`` reads
    the resolved entity's own declared ``repos:`` frontmatter and renders one
    or more contexts (an entity can declare more than one repo); ``path``
    probes that filesystem path directly with no declared metadata to compare
    against. Always returns rendered text — never raw JSON — and degrades to a
    human-readable "repo context unavailable (...)" line on any non-ok status.
    """
    entity_id = (entity_id or "").strip()
    path = (path or "").strip()

    if bool(entity_id) == bool(path):
        return "Exactly one of entity_id or path is required."

    from api.services import repo_context

    if path:
        ctx = repo_context.resolve_repo_context({"path": path})
        return _render_repo_context(path, [ctx])

    memory_path = get_memory_path()
    entities_dir = memory_path / "entities"
    resolved_id = _entity_id_for_name(entities_dir, entity_id) or entity_id
    entity_path = entities_dir / f"{resolved_id}.md"
    if not entity_path.exists():
        return f"Entity '{entity_id}' not found."

    try:
        from api.services import markdown_parser

        parsed = markdown_parser.parse(entity_path)
    except Exception as e:
        return f"Could not read '{entity_id}': {e}"

    declared = parsed.frontmatter.get("repos") or []
    declared = [d for d in declared if isinstance(d, dict) and d.get("path")]
    if not declared:
        return f"Entity '{resolved_id}' has no declared repos."

    contexts = [repo_context.resolve_repo_context(d) for d in declared]
    return _render_repo_context(resolved_id, contexts)


def _render_repo_context(label: str, contexts: list[dict]) -> str:
    """Render one or more ``RepoContext`` dicts as human-readable text."""
    blocks = []
    for ctx in contexts:
        if ctx.get("status") != "ok":
            blocks.append(
                f"repo context unavailable for `{ctx.get('path')}` "
                f"(status: {ctx.get('status')})"
            )
            continue

        lines = [f"**{ctx.get('path')}**"]
        branch = ctx.get("current_branch") or "(detached)"
        lines.append(f"- branch: {branch}")
        ahead, behind = ctx.get("ahead"), ctx.get("behind")
        if ahead is not None or behind is not None:
            lines.append(f"- ahead/behind origin: {ahead or 0}/{behind or 0}")
        dirty = ctx.get("dirty_files")
        if dirty is not None:
            lines.append(f"- dirty files: {dirty}")
        commit = ctx.get("last_commit")
        if commit:
            lines.append(
                f"- last commit: {commit.get('hash', '')[:8]} "
                f"by {commit.get('author')} ({commit.get('date')}): {commit.get('subject')}"
            )
        worktrees = ctx.get("worktrees") or []
        if len(worktrees) > 1:
            wt_lines = ", ".join(
                f"{w.get('path')} ({w.get('branch') or 'detached'}"
                f"{', main' if w.get('is_main') else ''})"
                for w in worktrees
            )
            lines.append(f"- worktrees: {wt_lines}")
        if ctx.get("stale_hint"):
            lines.append(f"- note: {ctx['stale_hint']}")
        blocks.append("\n".join(lines))

    header = f"Repo context for `{label}`:" if len(contexts) > 1 or contexts[0].get("path") != label else ""
    body = "\n\n".join(blocks)
    return f"{header}\n\n{body}".strip() if header else body


def handle_get_perspective(
    subject: str, observer: str | None = None, context: str | None = None
) -> str:
    """Return a subject's currently-valid claims, optionally filtered by perspective.

    The D2 ``get_perspective(subject, observer?, context?)`` Bookworm tool: reads
    the in-page ``claims`` block (the source of truth) for the resolved subject,
    keeps only currently-valid (open, non-superseded) claims, applies the optional
    ``observer`` / ``context`` post-filters, and renders each with its provenance
    so the agent can attribute "who believes what" honestly.
    """
    from api.services import markdown_parser
    from api.services.claims import parse_claims
    from api.services.id_utils import resolve_entity_file

    if not subject:
        return "subject is required."

    memory_path = get_memory_path()
    page = resolve_entity_file(memory_path, subject)
    if page is None or not page.exists():
        return f"No subject '{subject}' found in memory."

    try:
        parsed = markdown_parser.parse(page)
    except Exception as e:
        return f"Could not read '{subject}': {e}"

    claims = [
        c
        for c in parse_claims(parsed.body)
        if c.valid_to is None and not c.superseded_by
    ]
    if observer:
        claims = [c for c in claims if c.observer == observer]
    if context:
        claims = [c for c in claims if c.context == context]

    fm = parsed.frontmatter or {}
    title = str(fm.get("name", page.stem.replace("-", " ").title()))
    perspective = []
    if observer:
        perspective.append(f"observer={observer}")
    if context:
        perspective.append(f"context={context}")
    header = f"Perspective on {title}"
    if perspective:
        header += f" ({', '.join(perspective)})"

    if not claims:
        return f"{header}: no currently-valid claims match."

    lines = [f"{header} — {len(claims)} valid claim(s):", ""]
    for c in claims:
        prov = (
            f"{c.observer} · {c.context} · {c.source_trust} · "
            f"conf {c.confidence:.2f} · since {c.valid_from or 'undated'}"
        )
        lines.append(f"- {c.text}\n  _({prov})_")
    return "\n".join(lines)


# ---------- Helpers: search sources ----------


def _leann_search_entities(memory_path: Path, query: str, top_k: int) -> list[dict]:
    try:
        from api.services.vector_index import SqliteVecIndexer
    except Exception:
        return []
    try:
        indexer = SqliteVecIndexer(memory_path)
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
            "source": "vector",
            "score": r.get("score", 0.0),
            "text": r.get("text", ""),
            "metadata": meta,
        })
    return out


def _leann_search_episodes(memory_path: Path, query: str, top_k: int) -> list[dict]:
    try:
        from api.services.vector_index import SqliteVecIndexer
    except Exception:
        return []
    try:
        indexer = SqliteVecIndexer(memory_path)
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
    try:
        from api.services.entity_body import summarize_for_recall
        budget = 2000 if entity_type in MEDIUM_TYPES else 3200
        return summarize_for_recall(body, max_chars=budget)
    except Exception:
        # pyyaml-free fallback: faithful OLD behavior per entity type
        if entity_type in MEDIUM_TYPES:
            return body[:2000]
        if entity_type in MEDIUMLONG_TYPES:
            return body[:3200]
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

    from datetime import timezone

    memory_path = get_memory_path()
    episodes_dir = memory_path / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    # ID = max existing suffix + 1 (NOT count+1): count-based numbering collides
    # and overwrites if any same-day episode was deleted/consolidated away.
    max_num = 0
    for filepath in episodes_dir.glob(f"ep_{today}_*.md"):
        suffix = filepath.stem.rsplit("_", 1)[-1]
        if suffix.isdigit():
            max_num = max(max_num, int(suffix))
    episode_id = f"ep_{today}_{max_num + 1:03d}"

    content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]

    # Check for duplicates
    for filepath in episodes_dir.glob("*.md"):
        text = filepath.read_text(encoding="utf-8")
        if f"content_hash: {content_hash}" in text:
            return f"Episode already exists (duplicate detected by content hash)."

    # Real UTC timestamp — the previous `datetime.now().isoformat() + "Z"` stamped
    # naive LOCAL time but labeled it UTC, corrupting the temporal reasoning the
    # Sleep cycle + claim `valid_from` key on.
    timestamp = datetime.now(timezone.utc).isoformat()

    # Build frontmatter as a dict and let markdown_parser (pyyaml) serialize it.
    # A hand-rolled f-string breaks on any special char in `title` (e.g. a colon
    # — `title: Q3: roadmap` is invalid YAML), which then stalls the whole Sleep
    # cycle when the loader hits the malformed episode.
    frontmatter = {
        "id": episode_id,
        "timestamp": timestamp,
        "source": "mcp",
        "origin": "mcp",
        "title": title or "MCP capture",
        "processed": False,
        "content_hash": content_hash,
    }
    filepath = episodes_dir / f"{episode_id}.md"
    try:
        from api.services import markdown_parser

        markdown_parser.write(filepath, frontmatter, content)
    except Exception:
        # Fallback if the API package isn't importable: dump YAML directly so a
        # colon/quote in the title still can't produce invalid frontmatter.
        import yaml

        fm_str = yaml.safe_dump(frontmatter, default_flow_style=False, sort_keys=False).strip()
        filepath.write_text(f"---\n{fm_str}\n---\n\n{content}\n", encoding="utf-8")

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
