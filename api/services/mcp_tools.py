"""The Cicada MCP tools, one implementation for every server (G135 R-R2, R-R14).

Until G135 every tool body lived in `mcp/server.py` and read process globals —
`SESSION`, `CLIENT_INFO`, `_STATE_HINT_SENT`, `_SKIPPED_INBOX_IDS` — because a
stdio MCP server IS one conversation. The remote connector serves many
connectors and many conversations from one process, so the bodies now take a
`ToolContext` naming the caller for one call, and both servers call them: the
stdio server builds a context from its globals on every call
(`mcp/server.py::_ctx`), the remote runtime builds one per connector and
conversation handle (`api/remote/runtime.py`). One implementation keeps G75
R12 honest — one prose source for what a tool says.

Deliberately NOT here: `cicada_pending`, `cicada_mark_processed` and
`cicada_repo_context`. They stay in `mcp/server.py`, so the remote package
cannot even import them (R-R3: never remote). This module never imports the
`mcp` SDK — the stdio server loads it standalone.

Moved verbatim from `mcp/server.py` at `f2d31ef`; the only edits are the
context substitutions listed in the ToolContext docstring. The stdio replies
are pinned byte for byte by `api/tests/test_mcp_stdio_golden.py`.

The remote flags on `ToolContext` (`connector_id`, `available`,
`raw_excerpts`, `sources_limit`) came after the move (G135 Task 5). Every
default is stdio's behaviour, so the golden fixture still holds; a remote call
gets scope-gated excerpts and hints, capped sources, `remote:<id>` claims and
a commit per write under its app (R-R11, R-R22..R-R25, R-R28).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from api.services import agent_commits, agentic_write, episode_ids


def _loopback_post(url: str, payload: dict, headers: dict[str, str], timeout: float = 8) -> dict:
    import urllib.request

    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


@dataclass
class ToolContext:
    """Who is calling a tool, for one call.

    The substitutions the move made, and nothing else:
    `get_memory_path()` → `ctx.memory_path()` (resolved ONCE at the top of a
    body — still per call, so the split-brain rule holds); `SESSION.*` →
    `ctx.session_id/harness/project_dir`; `CLIENT_INFO.get(...)` →
    `ctx.client_name/client_version`; `_SKIPPED_INBOX_IDS` →
    `ctx.skipped_inbox_ids`; `_STATE_HINT_SENT` → `ctx.state_hint_sent` (the
    stdio wrapper writes it back); `_backend_post(...)` →
    `ctx.backend_post(...)`; `_backend_headers()` → `ctx.backend_headers()`;
    `"http://127.0.0.1:8000"` → `ctx.backend_url`; `_session_frontmatter()` →
    `ctx.session_frontmatter()`; the `read` ledger surfaces `"mcp"` /
    `"mcp-recall"` → `ctx.read_surface` / `f"{ctx.read_surface}-recall"`;
    and in `check_nudges` its inbox read cache, a local that was also called
    `ctx`, is renamed `inbox_ctx` so it cannot shadow this context.
    """

    memory_path: Callable[[], Path]
    session_id: str
    harness: str
    project_dir: str | None = None
    client_name: str | None = None
    client_version: str | None = None
    skipped_inbox_ids: set[str] = field(default_factory=set)
    state_hint_sent: bool = False
    post: Callable[[str, dict], dict] | None = None
    headers: Callable[[], dict[str, str]] | None = None
    backend_url: str = "http://127.0.0.1:8000"
    read_surface: str = "mcp"
    # G135 remote (R-R22..R-R25). Every default is the stdio server's behaviour,
    # so `mcp/server.py::_ctx` needs no change and the golden replies hold.
    connector_id: str | None = None
    available: frozenset[str] | None = None   # None = every tool (stdio)
    raw_excerpts: bool = True                 # recall's verbatim episode excerpts
    sources_limit: tuple[int | None, int] = (None, 2000)

    @property
    def is_remote(self) -> bool:
        return self.connector_id is not None

    @property
    def author(self) -> str:
        return agent_commits.author_for(self.harness)

    @property
    def trigger(self) -> str:
        return f"{'remote' if self.is_remote else 'mcp'}/{self.author}"

    @property
    def commit_subject(self) -> str:
        return "Remote write" if self.is_remote else "Agent write"

    @property
    def claim_origin(self) -> str | None:
        """R-R5/R-R23: a remote claim is user-shaped in nothing — `remote:<id>`
        can never earn `claim_reconciler.is_human` protection. Stdio keeps
        G71's derivation (`None`)."""
        return f"remote:{self.connector_id}" if self.is_remote else None

    def can(self, tool: str) -> bool:
        return self.available is None or tool in self.available

    def session_frontmatter(self) -> dict:
        """G48's episode keys — additive and inert (see the old
        `_session_frontmatter` docstring); key order kept for byte-identical YAML."""
        fm: dict = {"session_id": self.session_id}
        if self.harness and self.harness != "unknown":
            fm["harness"] = self.harness
        if self.project_dir:
            fm["project_dir"] = self.project_dir
        if self.connector_id:
            # R-R25: which connector wrote it — the app's own id, never a token.
            fm["connector"] = self.connector_id
        return fm

    def backend_headers(self) -> dict[str, str]:
        return self.headers() if self.headers is not None else {"Content-Type": "application/json"}

    def backend_post(self, path: str, payload: dict) -> dict:
        if self.post is not None:
            return self.post(path, payload)
        return _loopback_post(f"{self.backend_url}{path}", payload, self.backend_headers())


def ask(ctx: ToolContext, query: str, top_k: int = 6) -> str:
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
            f"{ctx.backend_url}/ask",
            data=payload,
            headers=ctx.backend_headers(),
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

            result = ask_service.answer_query(ctx.memory_path(), query, top_k=top_k)
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


def save_url(ctx: ToolContext, url: str, note: str | None) -> str:
    """Save a URL as media. Prefers the running backend (shared dedup index,
    background enrichment); falls back to direct ingestion via the api package."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return "Error: URL must start with http:// or https://"

    # Path 1: the FastAPI backend, if it's up.
    # R-R11: a remote save commits as its app; POST /sources/save would stamp
    # it as an MCP save from this Mac.
    if not ctx.is_remote:
        try:
            import urllib.request

            payload = json.dumps({
                "url": url,
                "note": note,
                "sessionId": ctx.session_id,
                "harness": ctx.harness,
                "projectDir": ctx.project_dir,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{ctx.backend_url}/sources/save",
                data=payload,
                headers=ctx.backend_headers(),
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

        memory_path = ctx.memory_path()
        (memory_path / "sources").mkdir(parents=True, exist_ok=True)
        (memory_path / "episodes").mkdir(parents=True, exist_ok=True)
        (memory_path / "entities").mkdir(parents=True, exist_ok=True)

        async def _save():
            item = media_ingestor.RawItem(
                url=url,
                note=note,
                # Byte-identical frontmatter to path 1's `POST /sources/save`,
                # so which path ran (backend up or down) never shows up as a
                # provenance difference.
                origin="saved-link",
                session_id=ctx.session_id,
                harness=ctx.harness,
                project_dir=ctx.project_dir,
            )
            idx = media_ingestor.load_url_index(memory_path)
            async with httpx.AsyncClient() as client:
                result = await media_ingestor.ingest_one(item, memory_path, client, idx)
            media_ingestor.save_url_index(memory_path, idx)
            return result

        result = asyncio.run(_save())
        if ctx.is_remote and result.status == "created":
            # R-R11: the three files this save wrote, committed on their own
            # under the app that saved them (the batch path's own path list).
            paths = ["sources/url_index.json", f"entities/{result.media_entity_id}.md",
                     f"episodes/{result.episode_id}.md"]
            agent_commits.commit_write(
                memory_path, subject=ctx.commit_subject,
                lines=[f"sources/url_index.json: updated (trigger: {ctx.trigger})",
                       f"entities/{result.media_entity_id}.md: created (source: {result.episode_id}, trigger: {ctx.trigger})",
                       f"episodes/{result.episode_id}.md: created (trigger: {ctx.trigger})"],
                paths=paths, author=ctx.author, session=ctx.session_id)
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


def recall(ctx: ToolContext, query: str) -> str:
    """Two-source retrieval with progressive disclosure.

    Pass 1 (this tool): summaries + proactive nudges/clarifications.
    Pass 2: cicada_recall_detail for the full page of a specific entity.
    """
    memory_path = ctx.memory_path()
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
    from api.services import telemetry  # G124 R11: a suggested page is a read (ids only)
    for _eid in suggested:
        telemetry.record_read(_eid, surface=f"{ctx.read_surface}-recall", bank=memory_path.name)
    if not suggested and hub_member_ids:
        suggested = hub_member_ids[:7]
    # G53/G75 (R13): the now-view cursor rides in the FIRST hints block this
    # process emits, and only there — a block that was never emitted (nothing
    # to suggest) does not consume it.
    state_hint = None if ctx.state_hint_sent else _state_hint(memory_path)
    hints_block = _hints_block(suggested, relevant_hub, hub_member_ids, state=state_hint,
                               can_read_detail=ctx.can("cicada_recall_detail"))
    if hints_block:
        output_parts.append(hints_block)
        if state_hint is not None:
            ctx.state_hint_sent = True

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
    # R-R22: the person's words verbatim — the "sources" scope, not "search".
    if ctx.raw_excerpts:
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
    suggested_entities: list[str],
    relevant_hub: str | None,
    hub_members: list[str],
    state: dict | None = None,
    can_read_detail: bool = True,
) -> str:
    """Render the machine-parseable ``cicada-hints`` fenced JSON block.

    Fenced with the literal info-string ``cicada-hints`` so a small model can
    locate it and ``json.loads`` deterministically. ``state`` (G53, R13) is
    an optional compact now-view added under the ``"state"`` key — additive,
    so a consumer that only knows the older keys is unaffected. The early
    ``return ""`` when there is nothing to suggest is a kept contract: the
    cursor rides in a block that exists, never in a block of its own.

    ``can_read_detail`` (G135 R-R22) is ``ctx.can("cicada_recall_detail")``
    — always true on stdio. A remote connection holding ``search`` but not
    ``read`` has no ``cicada_recall_detail``, and a hint naming it is G75
    R12's bug; it is pointed at ``cicada_open_hub`` instead, which shares
    recall's scope and so is always present when recall is.
    """
    if not suggested_entities and not relevant_hub:
        return ""
    if can_read_detail:
        next_tool = "cicada_recall_detail"
        note = "Call cicada_recall_detail with each suggested_entity id for full pages, or cicada_open_hub with relevant_hub for a topic index."
    else:
        next_tool = "cicada_open_hub"
        note = "Call cicada_open_hub with relevant_hub for a topic index."
    payload = {
        "suggested_entities": suggested_entities,
        "relevant_hub": relevant_hub,
        "hub_members_preview": hub_members[:8],
        "next_tool": next_tool,
        "note": note,
    }
    if state:
        payload["state"] = state
    return "```cicada-hints\n" + json.dumps(payload, indent=2) + "\n```"


def _state_hint(memory_path: Path) -> dict | None:
    """Compact now-view for ``cicada-hints.state`` (G53): engine, pending count,
    current project ids, and when it was generated. Read-only — never
    regenerates (R4): the MCP process never dirties the bank with a
    projection, and a stale cursor says so through ``as_of``. Ids and enums
    only, for harnesses that drop the ``initialize`` ``instructions``; the
    full primer is one ``cicada_handshake`` call away."""
    from api.services import state_dictionary

    state = state_dictionary.read_state(memory_path)
    if not state:
        return None
    return {
        "engine": (state.get("engine") or {}).get("engine"),
        "pending": (state.get("inbox") or {}).get("pending", 0),
        "projects": [p["id"] for p in state.get("projects") or []],
        "as_of": state.get("generated_at"),
        "next_tool": "cicada_handshake",
    }


def open_hub(ctx: ToolContext, hub: str) -> str:
    """Open a hub page and return its body verbatim (member list).

    Tries ``hubs/<hub>.md`` then ``hubs/topic-<sanitize_id(hub)>.md``. Returns
    the body verbatim — the MCP flat parser never parses the nested members
    frontmatter, so the wikilinked body bullet list is the member source.
    """
    if not hub:
        return "hub is required."
    memory_path = ctx.memory_path()
    hubs_dir = memory_path / "hubs"
    raw = hub.strip()
    if raw.endswith(".md"):
        raw = raw[:-3]
    if raw.startswith("hubs/"):
        raw = raw[len("hubs/"):]
    if raw.startswith("hub:"):
        raw = raw[len("hub:"):]

    from api.services.id_utils import bank_file

    candidates = [raw, f"topic-{_mcp_sanitize_id(raw)}", _mcp_sanitize_id(raw)]
    for cand in candidates:
        # Task 5 review r1: a hub id is one segment of hubs/, never a path out.
        path = bank_file(hubs_dir, cand)
        if path is not None and path.exists():
            _, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            return body or path.read_text(encoding="utf-8")
    return f"Hub '{hub}' not found."


def recall_detail(ctx: ToolContext, entity_id: str) -> str:
    """Return the full entity page for one entity (Pass 2)."""
    memory_path = ctx.memory_path()
    entities_dir = memory_path / "entities"
    if not entity_id:
        return "entity_id is required."

    candidate_ids = [entity_id]
    # Also try name -> id
    resolved = _entity_id_for_name(entities_dir, entity_id)
    if resolved and resolved != entity_id:
        candidate_ids.append(resolved)

    from api.services.id_utils import bank_file

    for cid in candidate_ids:
        # Task 5 review r1: `../episodes/<id>` or an absolute path is refused
        # here, not read — a raw episode is `sources`' to give (R-R22).
        path = bank_file(entities_dir, cid)
        if path is not None and path.exists():
            from api.services import telemetry  # G124 R11: ids only, never the page text
            telemetry.record_read(cid, surface=ctx.read_surface, bank=memory_path.name)
            return path.read_text(encoding="utf-8")

    return f"Entity '{entity_id}' not found."


def sources(ctx: ToolContext, entity_id: str) -> str:
    """Render the source episode chunks behind an entity (chunks mode)."""
    try:
        from api.services.entity_sources import gather_entity_sources
        bundle = gather_entity_sources(ctx.memory_path(), entity_id, mode="chunks")
    except Exception as exc:  # pragma: no cover
        return f"Could not gather sources for '{entity_id}': {exc}"
    eps = bundle.get("episodes", [])
    if not eps:
        return f"No source episodes found for '{entity_id}'."
    # R-R28: a remote connection sees at most 3 episodes x 1,000 characters;
    # stdio's (None, 2000) is the old behaviour. Cut before the header so the
    # count it prints is the count shown.
    max_episodes, max_chars = ctx.sources_limit
    eps = eps[:max_episodes] if max_episodes else eps
    parts = [f"**Sources for `{entity_id}`** ({len(eps)} episode(s)):"]
    for e in eps:
        parts.append(f"\n### episode {e['id']}\n{(e.get('chunk') or '').strip()[:max_chars]}")
    return "\n".join(parts)


def write_claim(
    ctx: ToolContext,
    subject: str,
    predicate: str,
    object_: str,
    observer: str | None,
    confidence,
    context: str | None,
    source_episode: str | None,
    force_new_entity: bool = False,
    sources: list | None = None,
    evidence: list | None = None,
) -> str:
    """Write one atomic fact as an observer-tagged claim (agentic write path).

    ``evidence`` (G118 slice 1) is the agent's ``[{episode, quote}]`` citation
    list; the reply names what happened to it — how many quotes verified into
    spans, and which episode a missed quote was NOT found in — so the agent
    can re-cite the exact words instead of silently leaving ``reasoning``.
    """
    # One bank resolution per call: the write, the ledger row and the commit
    # must all name the same bank even if the active bank flips mid-call.
    memory_path = ctx.memory_path()
    author = ctx.author
    result = agentic_write.write_claim(
        memory_path,
        subject,
        predicate,
        object_,
        observer=(observer or "agent"),
        confidence=confidence if confidence is not None else 0.7,
        context=(context or "general"),
        source_episode=source_episode,
        force_new_entity=force_new_entity,
        sources=sources,
        evidence=evidence,
        # PR #20 review fix: stamp the writing session on the claim itself so
        # an episode-less write (no source_episode) still records which
        # conversation touched this entity — see agentic_write.write_claim's
        # docstring and session_stats._group's claims fallback.
        session_id=ctx.session_id,
        # G135 R-R11: the claim carries its real author instead of the shim's
        # "mcp-agentic-write" placeholder.
        authored_by=author,
        # G135 R-R5/R-R23: a remote claim is `remote:<id>` and may never carry
        # the person's own observer; stdio passes None/False (unchanged).
        origin=ctx.claim_origin,
        forbid_owner_observer=ctx.is_remote,
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

    from api.services import telemetry

    refs = {
        "entity_id": result.get("entity_id"),
        "claim_id": result.get("claim_id"),
        "episode_id": source_episode,
        "action": result.get("action"),
        # G48: the ledger becomes the model<->conversation join key, and
        # `GET /conversations/recent` reads `refs.session_id` back out.
        "session_id": ctx.session_id,
        "harness": ctx.harness,
        "client_name": ctx.client_name,
        "client_version": ctx.client_version,
    }
    if ctx.is_remote:
        # Only on a remote write: `test_run_events.py` pins the stdio refs exactly.
        refs["connector_id"] = ctx.connector_id
    telemetry.record(telemetry.UsageEvent(
        kind="agentic_write", stage="driver", connection="session",
        engine="mcp-remote" if ctx.is_remote else "mcp-client",
        model=None, bank=memory_path.name, billing="subscription", invocations=1,
        refs=refs,
    ))

    # G135 R-R11: the page this write touched is committed on its own, under
    # the harness that wrote it — no longer swept into the next writer's
    # `git add -A` (the G85 smear).
    if result.get("path"):
        change = "created" if result.get("page_created") else "updated"
        agent_commits.commit_write(
            memory_path,
            subject=ctx.commit_subject,
            lines=[f"{result['path']}: {change} (source: {source_episode or 'n/a'}, trigger: {ctx.trigger})"],
            paths=[result["path"]],
            author=author,
            session=ctx.session_id,
        )

    action = result.get("action")
    verb = {
        "written": "Recorded",
        "coexist": "Recorded alongside an existing user-stated claim (flagged for review)",
        "superseded": "NOT written — an existing higher-trust claim already covers this",
    }.get(action, "Recorded")

    # G118: say what became of the citation. A verified span is the point of
    # the parameter; a missed quote is named by episode so the agent can fix
    # it; no quote at all is stated plainly as reasoning, never hidden.
    spans = result.get("evidence") or []
    verified = [e for e in spans if e.get("kind") != "reasoning"]
    if verified:
        ev_note = f"evidence: {len(verified)} span verified" + ("s" if len(verified) > 1 else "")
        if len(verified) < len(spans):
            missed = ", ".join(e.get("episode") or "?" for e in spans if e.get("kind") == "reasoning")
            ev_note += f"; quote not found in {missed}, recorded as reasoning"
    elif evidence:
        missed = ", ".join(e.get("episode") or "?" for e in spans) or "the named episode"
        ev_note = f"evidence: reasoning (quote not found in {missed} — cite the exact words, or omit evidence)"
    else:
        ev_note = "evidence: reasoning (no quote given)"

    return (
        f"{verb}: {subject} {predicate} {object_} "
        f"(entity `{result.get('entity_id')}`, claim `{result.get('claim_id')}`, "
        f"observer={result.get('observer')}, action={action}; {ev_note})."
    )


def get_perspective(
    ctx: ToolContext,
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

    memory_path = ctx.memory_path()
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


def _format_inbox_blurb(
    fm: dict, body: str, *, cause: dict | None = None, recommended_key: str | None = None
) -> str:
    """One proactive-recall line per pending item.

    ``cause``/``recommended_key`` are additive (G115 R9): a caller that has not
    resolved them yet renders exactly what it rendered before.
    """
    kind = str(fm.get("kind", fm.get("type", "")) or "")
    ename = fm.get("entity_name", fm.get("entity_mention", "Unknown"))
    if fm.get("question"):
        return f"- [{kind or 'item'}] **{ename}**\n" + render_question(
            fm, body, cause=cause, recommended_key=recommended_key
        )
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


def render_question(
    fm: dict,
    body: str,
    today: str | None = None,
    *,
    cause: dict | None = None,
    recommended_key: str | None = None,
) -> str:
    """Render an inbox item's question object for an agent to ask in-flow (§2.7, v2 in G115 Phase 1).

    Shape:

        Where does the owner work now?
          entity_id=owner · predicate=works-at
          Cause: “…the sentence that raised it…” — from "Title" · claude-code · 6 months ago
          a) MongoDB — 6 months ago
          b) Supahost — 5 days ago (Recommended)
          both) Both are true (different contexts)
          Other / Later — reply with any other answer, or ask to be reminded later; skip=true if unanswered
          Source to check: https://…

    The ``entity_id=`` line is what the NEXT ``cicada_check_nudges(entity_ids=…)``
    call needs (G75 contract item 2). The ``Cause:`` line is printed whenever a
    cause is passed — ``[ no source recorded ]`` included — so an agent quoting it
    (the primer's discipline) never quotes silence. ``(Recommended)`` marks the
    option Sleep proposed (the key ``_verdict`` grades ``agreed``, G115 R6) and
    nothing else; the ``a) Label — age`` prefix is unchanged so the G60 tests
    still hold. Falls back to the item body when there is no question, so legacy
    items still render something an agent can read out.

    **Each half of the ``Other / Later`` line is gated on its own flag** (final
    review H1). Decay only started rendering through this function in G115
    Phase 1, and its question object sets ``allow_other: False`` — offering
    "reply with any other answer" there invited an agent into a request the
    resolve path cannot honour: free text on a decay item used to land in
    ``_resolve_decay``'s ``else`` branch, which appended the prose to the entity
    body, left the page ``decaying`` at its decayed confidence and deleted the
    item — silently inverting a "yes, still relevant". A conflict (both flags
    true) renders the identical sentence it always did.
    """
    from datetime import date as _date

    from api.services import inbox_context, inbox_questions

    now = today or str(_date.today())
    lines = [str(fm.get("question") or fm.get("title") or "").strip() or (body or "").strip()]

    entity_id = str(fm.get("entity_id") or "").strip()
    if entity_id:
        header = f"  entity_id={entity_id}"
        if fm.get("predicate"):
            header += f" · predicate={fm['predicate']}"
        lines.append(header)
    if cause is not None:
        lines.append(f"  Cause: {inbox_context.cause_line(cause, now)}")

    for option in inbox_questions.normalize_options(fm.get("options")):
        age = inbox_questions.humanize_age(
            option.get("last_referenced") or option.get("observed_at"), now
        )
        suffix = f" — {age}" if age != "unknown" else ""
        marker = (
            " (Recommended)"
            if recommended_key and str(option.get("key")) == recommended_key
            else ""
        )
        lines.append(f"  {option.get('key')}) {option.get('label')}{suffix}{marker}")

    choices = []
    if fm.get("allow_other"):
        choices.append("reply with any other answer")
    if fm.get("allow_defer"):
        choices.append("ask to be reminded later")
    if choices:
        lines.append(
            "  Other / Later — " + ", or ".join(choices) + "; skip=true if unanswered"
        )
    if fm.get("hint"):
        lines.append(f"  Source to check: {fm['hint']}")
    return "\n".join(line for line in lines if line.strip())


def _inbox_ctx(memory_path: Path, today: str):
    """ONE :class:`InboxContext` per reader loop, not one per item (final review H3).

    ``InboxContext`` is a per-read cache whose first ``episode()``/``entity()``
    call scandirs and parses ``episodes/`` AND ``entities/`` whole. Constructing
    one inside the ``for`` in :func:`handle_check_nudges` / :func:`_relevant_inbox`
    re-ran both scans for every pending item: measured at 425 ms for 40 items on
    a synthetic 2,000-episode / 1,900-entity bank versus 9.3 ms warm — ~400 ms
    added to two calls that sit in the conversation loop. ``GET /inbox`` already
    builds exactly one per ``load_inbox``; this is the MCP half of that rule.

    Returns ``None`` when the api package is not importable (the MCP server runs
    standalone in harnesses that never installed it); :func:`_agent_question`
    then builds its own and degrades exactly as it did before.
    """
    try:
        from api.services import inbox_context

        return inbox_context.InboxContext(memory_path, today=today)
    except Exception:  # noqa: BLE001 — no api package is a supported degrade
        return None


def _agent_question(
    memory_path: Path, fm: dict, today: str, *, ctx=None
) -> tuple[dict, dict | None, str | None]:
    """What both MCP readers hand :func:`render_question` (G115 Phase 1, R9).

    Synthesises the decay question exactly as ``GET /inbox`` does
    (``decay_question`` over the subject page's ``last_referenced``, never
    written to the file — R5), resolves the cause through ``inbox_context``
    (three tiers, engine-free — R1/G74) and computes the recommended key from
    the shipped ``_verdict`` (R6) — so the agent is shown the same item the app
    is. Both readers keep today's raw file loop; routing them through
    ``inbox_service.load_inbox`` behind the ask gate is Phase 2, so until then
    this degrades to ``(fm, None, None)`` when the api package is not importable
    (the MCP server runs standalone in harnesses that never installed it).

    ``ctx`` is the caller's :func:`_inbox_ctx` — passed so a loop over N items
    pays for the episode/entity scan ONCE (final review H3). Omitting it keeps
    the old per-call behaviour, which is what the standalone degrade path and
    the single-item tests want.
    """
    try:
        from api.services import inbox_context, inbox_questions, inbox_service

        fm = dict(fm)
        if ctx is None:
            ctx = inbox_context.InboxContext(memory_path, today=today)
        entity_id = str(fm.get("entity_id") or "")
        options = inbox_questions.normalize_options(fm.get("options"))
        if str(fm.get("kind") or "") == "decay" and not options:
            question = inbox_questions.decay_question(
                str(fm.get("entity_name") or entity_id),
                ctx.entity_last_referenced(entity_id),
                today,
            )
            fm.update(question)
            options = inbox_questions.normalize_options(fm["options"])
        rec = inbox_service.recommended_key(str(fm.get("kind") or ""), fm, options)
        if rec:
            # Recommended-first on the wire, exactly as `GET /inbox` serves it;
            # the file on disk keeps its own order (R6).
            fm["options"] = [o for o in options if str(o.get("key")) == rec] + [
                o for o in options if str(o.get("key")) != rec
            ]
        return fm, ctx.cause_for(fm, options).to_wire(), rec
    except Exception:
        return fm, None, None


def resolve_inbox(
    ctx: ToolContext,
    item_id: str,
    option_key: str | None,
    answer: str | None,
    defer: bool,
    remind_days,
    *,
    skip: bool = False,
    reject: bool = False,
) -> str:
    """Resolve (or defer) one inbox item through the backend (§2.7).

    ``skip=True`` (G75 contract item 2, final review) is an in-process no-op:
    the id joins ``_SKIPPED_INBOX_IDS`` so ``handle_check_nudges`` stops
    returning it this session, and NOTHING is posted to the backend. Before
    this the primer named an argument the schema rejected (R12 — a bug), and
    an agent hitting the tool error could fall back to ``defer=true``, a
    real ``remind_after`` write the person never asked for.

    ``reject=True`` (G113 slice 3b) is a merge_suggestion-only verdict —
    "these are NOT the same entity" — that IS posted to the backend, which
    records the pair in ``_merge_rejected.yaml`` so it is never re-proposed;
    unlike ``skip`` it is a real, remembered answer, not a no-op.
    """
    if ctx.is_remote:
        answer = None  # R-R22: option picks only — an app never invents the person's words
    item_id = (item_id or "").strip()
    if not item_id:
        return "Error: id is required (e.g. 'inbox-001')."
    if ctx.is_remote and not _REMOTE_INBOX_ID_RE.match(item_id):
        # Task 5 review r1: the id is spliced into a loopback URL that carries
        # the backend's bearer token; a remote caller gets the schema's shape
        # and nothing else, so it can never steer that request elsewhere.
        return "Error: id must look like 'inbox-001'."

    if skip:
        ctx.skipped_inbox_ids.add(item_id)
        return f"Skipped {item_id} — not re-asked this session (nothing written)."

    if reject:
        payload: dict = {"action": "reject"}
    elif defer:
        payload = {"action": "defer"}
        if remind_days is not None:
            payload["remindDays"] = int(remind_days)
    else:
        payload = {"action": "resolve"}
        if option_key:
            payload["optionKey"] = str(option_key)
        if answer:
            payload["answer"] = str(answer)
        if not option_key and not answer:
            return ("Error: pass option_key, or defer=true." if ctx.is_remote
                    else "Error: pass option_key, answer, or defer=true.")

    try:
        result = ctx.backend_post(f"/inbox/{item_id}/resolve", payload)
    except Exception as e:
        return (
            f"Could not resolve {item_id} ({type(e).__name__}: {e}). "
            "Is the Cicada backend running on 127.0.0.1:8000?"
        )

    status = result.get("status", "unknown")
    if status == "deferred":
        return f"Deferred {item_id} until {result.get('remindAfter', 'later')}."
    return f"Inbox item {item_id}: {status}."


_REMOTE_INBOX_ID_RE = re.compile(r"^inbox-\d+$")


def _relevant_inbox(memory_path: Path, query: str) -> list[str]:
    from api.services import inbox_questions

    q = query.lower()
    blurbs: list[str] = []
    # One read cache and one clock for the whole loop (final review H3).
    today = str(date.today())
    ctx = _inbox_ctx(memory_path, today)
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
        # A deferred item is hidden everywhere it could be surfaced, the
        # proactive recall block included — the user asked to be reminded
        # later, not on the next unrelated question.
        if inbox_questions.is_deferred(fm, today):
            continue
        fm, cause, rec = _agent_question(memory_path, fm, today, ctx=ctx)
        blurbs.append(_format_inbox_blurb(fm, body, cause=cause, recommended_key=rec))
    return blurbs


def save_episode(ctx: ToolContext, content: str, title: str | None) -> str:
    """Save content as a new episode for the next Sleep cycle."""
    import hashlib

    from datetime import timezone

    memory_path = ctx.memory_path()
    episodes_dir = memory_path / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    # ID = max existing suffix + 1 (NOT count+1): count-based numbering collides
    # and overwrites if any same-day episode was deleted/consolidated away.
    # One rule for every writer lives in episode_ids (G114 R1).
    episode_id = episode_ids.next_episode_id(episodes_dir, today)

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
        # R-R25: `origin` stays in G9's closed vocabulary; `source` says remote.
        "source": "mcp-remote" if ctx.is_remote else "mcp",
        "origin": "mcp",
        "title": title or "MCP capture",
        "processed": False,
        "content_hash": content_hash,
        # G48: which conversation produced this episode. Additive + inert.
        **ctx.session_frontmatter(),
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

    if ctx.is_remote:
        # R-R11: a remote episode commits alone, under its app. Stdio's episode
        # save stays uncommitted (byte-identical to before G135, by ruling).
        agent_commits.commit_write(
            memory_path, subject=ctx.commit_subject,
            lines=[f"episodes/{episode_id}.md: created (trigger: {ctx.trigger})"],
            paths=[f"episodes/{episode_id}.md"], author=ctx.author, session=ctx.session_id)

    return f"Episode saved as {episode_id}. It will be processed during the next Sleep cycle."


def check_nudges(ctx: ToolContext, topic: str | None, entity_ids: list | None = None) -> str:
    """Check for pending inbox items (decay/conflict/clarification/merge).

    ``entity_ids`` (G75 R12) is an exact-match filter on ``entity_id`` so the
    primer's ``cicada_check_nudges(entity_ids=<recall ids>)`` is executable
    today — a primer that names an argument the tool schema rejects is a
    bug. The G115 Phase 2 gate (mode, vector score, asked set, cap) is not
    this. Combines with ``topic`` as an AND.

    Two more things the contract promises and this path therefore does
    (final review): ``normalization`` items never come back — they are
    app-only audit rows about a predicate fold, not a question a person can
    answer in conversation — and an id the agent ``skip``ped this session
    stays out (``_SKIPPED_INBOX_IDS``).
    """
    memory_path = ctx.memory_path()
    results = []
    wanted = {str(e).strip() for e in (entity_ids or []) if str(e).strip()}
    # One read cache and one clock for the whole loop (final review H3).
    # Named `inbox_ctx`, not `ctx` as in the stdio original: `ctx` is now the
    # caller's ToolContext and must not be shadowed (G135 R-R14).
    today = str(date.today())
    inbox_ctx = _inbox_ctx(memory_path, today)

    for filepath in _inbox_files(memory_path):
        if filepath.stem in ctx.skipped_inbox_ids:
            continue
        content = filepath.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)

        if str(fm.get("kind") or "") == "normalization":
            continue
        if wanted and str(fm.get("entity_id") or "") not in wanted:
            continue

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

        from api.services import inbox_questions

        if inbox_questions.is_deferred(fm, today):
            continue

        # Decay becomes a question object here, and every question object gains
        # its cause + `(Recommended)` marker, so the agent reads the same card
        # the app shows (G115 Phase 1, R9).
        fm, cause, rec = _agent_question(memory_path, fm, today, ctx=inbox_ctx)

        kind = str(fm.get("kind", fm.get("type", "")) or "")
        ename = fm.get("entity_name", fm.get("entity_mention", "Unknown"))
        if fm.get("question"):
            results.append(
                f"**{(kind or 'Item').title()}** `{filepath.stem}`: {ename}\n"
                + render_question(fm, body, cause=cause, recommended_key=rec)
                + f"\n  Resolve with cicada_resolve_inbox(id=\"{filepath.stem}\", option_key=…)"
            )
        elif kind in ("clarification", "merge_suggestion") or (
            not kind and fm.get("uncertainty_type")
        ):
            results.append(
                f"**Clarification** `{filepath.stem}`: {ename} — "
                f"{fm.get('uncertainty_type', '')}\n  {body[:200]}"
            )
        else:
            title = fm.get("title", fm.get("short_description", ""))
            results.append(
                f"**{kind or 'Item'}** `{filepath.stem}`: {ename} — {title}\n  {body[:200]}"
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

