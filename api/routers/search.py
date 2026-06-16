"""GET /search — ranked entity search backed by LEANN, degrading to substring.

The graph toolbar's search-as-you-type is the first consumer. When LEANN is
unavailable (fresh install, cold index, missing key) the endpoint falls back to
a substring/name match over entity frontmatter so search still works — mirroring
the MCP server's graceful-degrade pattern.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from api.config import Settings, get_settings
from api.models.schemas import SearchHit, SearchResponse
from api.services import markdown_parser

router = APIRouter()


def _snippet(body: str, limit: int = 160) -> str:
    text = " ".join((body or "").split())
    return (text[:limit] + "…") if len(text) > limit else text


def _hit_from_file(filepath: Path, score: float) -> SearchHit | None:
    try:
        parsed = markdown_parser.parse(filepath)
    except Exception:
        return None
    fm = parsed.frontmatter or {}
    return SearchHit(
        id=filepath.stem,
        name=str(fm.get("name", filepath.stem.replace("-", " ").title())),
        type=str(fm.get("type", "concept") or "concept"),
        status=str(fm.get("status", "active") or "active"),
        confidence=float(fm.get("confidence", 0.5) or 0.0),
        score=score,
        snippet=_snippet(parsed.body),
    )


def _vector_search(memory_path: Path, query: str, top_k: int) -> list[SearchHit] | None:
    """Return sqlite-vec entity hits, or None if unavailable (caller degrades).

    Degrades to None on any failure (cold index, missing embedding model, etc.)
    so ``search`` falls back to substring matching — same graceful pattern the
    MCP server uses.
    """
    try:
        from api.services.vector_index import SqliteVecIndexer
    except Exception:
        return None
    try:
        indexer = SqliteVecIndexer(memory_path)
        raw = indexer.search_entities(query, top_k=top_k)
    except Exception:
        return None
    if not raw:
        return None

    entities_dir = memory_path / "entities"
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for r in raw:
        meta = r.get("metadata", {}) or {}
        eid = meta.get("entity_id")
        if not eid or eid in seen:
            continue
        seen.add(eid)
        filepath = entities_dir / f"{eid}.md"
        if not filepath.exists():
            continue
        hit = _hit_from_file(filepath, float(r.get("score", 0.0) or 0.0))
        if hit:
            hits.append(hit)
    return hits or None


def _substring_search(memory_path: Path, query: str, top_k: int) -> list[SearchHit]:
    q = query.lower().strip()
    entities_dir = memory_path / "entities"
    if not q or not entities_dir.exists():
        return []
    scored: list[tuple[int, SearchHit]] = []
    for filepath in sorted(entities_dir.glob("*.md")):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue
        fm = parsed.frontmatter or {}
        name = str(fm.get("name", filepath.stem.replace("-", " "))).lower()
        tags = [str(t).lower() for t in (fm.get("tags", []) or [])]
        relevance = 0
        if q in name:
            relevance += 10
        if any(q in t for t in tags):
            relevance += 5
        if q in (parsed.body or "").lower():
            relevance += 2
        if relevance > 0:
            hit = _hit_from_file(filepath, float(relevance))
            if hit:
                scored.append((relevance, hit))
    scored.sort(key=lambda x: -x[0])
    return [h for _, h in scored[:top_k]]


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str,
    top_k: int = 8,
    indexes: str = "entities",
    settings: Settings = Depends(get_settings),
):
    memory_path = settings.memory_path
    hits = _vector_search(memory_path, q, top_k)
    if hits is None:
        hits = _substring_search(memory_path, q, top_k)
    return SearchResponse(results=hits[:top_k])
