from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from api.config import Settings, get_settings
from api.models.schemas import (
    ContextEpisodeExcerpt,
    ContextNeighbor,
    EntityContextResponse,
    EntityHistoryEntry,
    EntityResponse,
)
from api.services import git_service, markdown_parser
from api.services.hub_builder import _one_line_summary
from api.services.id_utils import build_name_index, resolve_entity_id
from api.services.wikilink_resolver import extract_wikilinks

router = APIRouter()


@router.get("/entities/{entity_id}", response_model=EntityResponse)
async def get_entity(
    entity_id: str,
    settings: Settings = Depends(get_settings),
):
    """Get full entity data including markdown content and history."""
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")

    parsed = markdown_parser.parse(entity_path)
    fm = parsed.frontmatter
    history = await git_service.get_entity_history(entity_id, settings.memory_path)

    return EntityResponse(
        id=entity_id,
        name=fm.get("name", entity_id.replace("-", " ").title()),
        type=fm.get("type", "concept"),
        status=fm.get("status", "active"),
        confidence=fm.get("confidence", 0.5),
        created=str(fm.get("created", "")),
        last_referenced=str(fm.get("last_referenced", "")),
        decay_rate=fm.get("decay_rate", 0.05),
        source_episodes=fm.get("source_episodes", []),
        tags=fm.get("tags", []),
        related=fm.get("related", []),
        version=fm.get("version", 1),
        markdown_content=parsed.body,
        raw_markdown=entity_path.read_text(encoding="utf-8"),
        history=history,
    )


@router.get("/entities/{entity_id}/history", response_model=list[EntityHistoryEntry])
async def get_entity_history(
    entity_id: str,
    settings: Settings = Depends(get_settings),
):
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")

    return await git_service.get_entity_history(entity_id, settings.memory_path)


@router.get("/entities/{entity_id}/context", response_model=EntityContextResponse)
async def get_entity_context(
    entity_id: str,
    top_k: int = 5,
    settings: Settings = Depends(get_settings),
):
    """Progressive-disclosure context for an entity.

    Returns the entity plus the cheap next-hops a small LLM needs to traverse
    without loading the whole graph: which hubs it belongs to, neighbors
    (LEANN + related + resolved wikilinks), source-episode excerpts, and an
    ordered ``next_hops`` action list. Degrades gracefully when LEANN is absent.
    """
    memory_path = settings.memory_path
    entities_dir = memory_path / "entities"

    name_index = build_name_index(entities_dir)
    resolved_id = resolve_entity_id(entities_dir, entity_id, name_index)
    if not resolved_id:
        raise HTTPException(404, f"Entity {entity_id} not found")
    entity_path = entities_dir / f"{resolved_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")

    parsed = markdown_parser.parse(entity_path)
    fm = parsed.frontmatter or {}
    name = str(fm.get("name", resolved_id.replace("-", " ").title()))

    hubs = _hubs_for_entity(memory_path, resolved_id)
    neighbors, ordered_ids = _build_neighbors(
        memory_path, entities_dir, resolved_id, name, parsed.body, name_index, top_k
    )
    episodes = _build_episodes(memory_path, name, fm.get("source_episodes", []) or [], top_k)

    return EntityContextResponse(
        id=resolved_id,
        name=name,
        type=str(fm.get("type", "concept") or "concept"),
        status=str(fm.get("status", "active") or "active"),
        confidence=float(fm.get("confidence", 0.5) or 0.0),
        markdown_content=parsed.body,
        hubs=hubs,
        neighbors=neighbors,
        episodes=episodes,
        next_hops=ordered_ids,
    )


def _hubs_for_entity(memory_path: Path, entity_id: str) -> list[str]:
    """Hub ids (``hub:<stem>``) whose member list includes this entity."""
    hubs_dir = memory_path / "hubs"
    if not hubs_dir.exists():
        return []
    out: list[str] = []
    for filepath in sorted(hubs_dir.glob("*.md")):
        try:
            fm = markdown_parser.parse(filepath).frontmatter or {}
        except Exception:
            continue
        if fm.get("type") != "hub":
            continue
        members = fm.get("members") or []
        if any(isinstance(m, dict) and m.get("id") == entity_id for m in members):
            out.append(f"hub:{filepath.stem}")
    return out


def _leann_entity_neighbors(memory_path: Path, query: str, top_k: int) -> list[dict]:
    """LEANN entity hits, or [] when LEANN is unavailable (caller degrades)."""
    try:
        from api.services.leann_indexer import LeannIndexer
    except Exception:
        return []
    try:
        indexer = LeannIndexer(memory_path)
        raw = indexer.search_entities(query, top_k=top_k)
    except Exception:
        return []
    out: list[dict] = []
    for r in raw or []:
        meta = r.get("metadata", {}) or {}
        eid = meta.get("entity_id")
        if eid:
            out.append({"id": eid, "score": float(r.get("score", 0.0) or 0.0)})
    return out


def _neighbor_from_id(
    entities_dir: Path, eid: str, via: str, score: float | None
) -> ContextNeighbor | None:
    filepath = entities_dir / f"{eid}.md"
    if not filepath.exists():
        return None
    try:
        parsed = markdown_parser.parse(filepath)
    except Exception:
        return None
    fm = parsed.frontmatter or {}
    return ContextNeighbor(
        id=eid,
        name=str(fm.get("name", eid.replace("-", " ").title())),
        type=str(fm.get("type", "concept") or "concept"),
        confidence=float(fm.get("confidence", 0.5) or 0.0),
        summary=_one_line_summary(parsed.body),
        via=via,
        score=score,
    )


def _build_neighbors(
    memory_path: Path,
    entities_dir: Path,
    entity_id: str,
    name: str,
    body: str,
    name_index: dict[str, str],
    top_k: int,
) -> tuple[list[ContextNeighbor], list[str]]:
    """Merge LEANN + related + resolved wikilinks, deduped, with an ordered id list."""
    fm = markdown_parser.parse(entities_dir / f"{entity_id}.md").frontmatter or {}

    # (id, via, score) candidates in priority order: LEANN, related, wikilink.
    candidates: list[tuple[str, str, float | None]] = []
    query = f"{name} {body[:200]}".strip()
    for hit in _leann_entity_neighbors(memory_path, query, top_k):
        candidates.append((hit["id"], "leann", hit["score"]))
    for ref in fm.get("related", []) or []:
        rid = resolve_entity_id(entities_dir, str(ref), name_index)
        if rid:
            candidates.append((rid, "related", None))
    for display in extract_wikilinks(body):
        wid = resolve_entity_id(entities_dir, display, name_index)
        if wid:
            candidates.append((wid, "wikilink", None))

    neighbors: list[ContextNeighbor] = []
    ordered_ids: list[str] = []
    seen: set[str] = {entity_id}
    cap = top_k * 2
    for nid, via, score in candidates:
        if nid in seen or len(neighbors) >= cap:
            continue
        neighbor = _neighbor_from_id(entities_dir, nid, via, score)
        if not neighbor:
            continue
        seen.add(nid)
        neighbors.append(neighbor)
        ordered_ids.append(nid)
    return neighbors, ordered_ids


def _build_episodes(
    memory_path: Path, name: str, source_episodes: list, top_k: int
) -> list[ContextEpisodeExcerpt]:
    """Excerpts from source_episodes plus a couple of LEANN episode hits."""
    episodes_dir = memory_path / "episodes"
    out: list[ContextEpisodeExcerpt] = []
    seen: set[str] = set()

    for ep_id in source_episodes:
        ep_id = str(ep_id)
        if not ep_id or ep_id in seen:
            continue
        filepath = episodes_dir / f"{ep_id}.md"
        if not filepath.exists():
            continue
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue
        seen.add(ep_id)
        excerpt = " ".join((parsed.body or "").split())[:400]
        out.append(
            ContextEpisodeExcerpt(
                episode_id=ep_id,
                timestamp=str((parsed.frontmatter or {}).get("timestamp", "") or ""),
                excerpt=excerpt,
            )
        )

    # Top-2 LEANN episode hits not already covered.
    try:
        from api.services.leann_indexer import LeannIndexer

        indexer = LeannIndexer(memory_path)
        for r in indexer.search_episodes(name, top_k=2) or []:
            meta = r.get("metadata", {}) or {}
            ep_id = str(meta.get("episode_id", "") or "")
            if not ep_id or ep_id in seen:
                continue
            seen.add(ep_id)
            excerpt = " ".join((r.get("text") or "").split())[:400]
            out.append(
                ContextEpisodeExcerpt(
                    episode_id=ep_id,
                    timestamp=str(meta.get("timestamp", "") or ""),
                    excerpt=excerpt,
                )
            )
    except Exception:
        pass

    return out
