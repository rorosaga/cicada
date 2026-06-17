import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from api.config import Settings, get_settings
from api.models.schemas import (
    ContextEpisodeExcerpt,
    ContextNeighbor,
    EntityContextResponse,
    EntityDiff,
    EntityHistoryEntry,
    EntityMedia,
    EntityResponse,
    LocationEntry,
    LocationListing,
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
        media=_build_media_block(fm, parsed.body),
    )


# Body section whose prose becomes EntityMedia.description (M4 media entities
# write a ``## Summary`` block; ``## Description``/``## Notes`` are secondary).
_SUMMARY_RE = re.compile(
    r"^##\s+Summary\s*$(.*?)(?=^##\s|\Z)", re.IGNORECASE | re.MULTILINE | re.DOTALL
)


def _build_media_block(frontmatter: dict, body: str) -> EntityMedia | None:
    """Build the structured ``media`` block for a ``type: media`` entity.

    Reads the nested ``media:`` frontmatter block written by
    ``media_ingestor.write_media_entity``; returns ``None`` for any entity that
    lacks a usable block (every non-media entity, plus a defensive guard for a
    ``type: media`` entity missing its block). ``description`` is lifted from the
    body's ``## Summary`` section when present. No key is invented — missing
    optionals stay ``None``.
    """
    media = frontmatter.get("media")
    if not isinstance(media, dict):
        return None
    url = media.get("url")
    media_type = media.get("media_type")
    if not url or not media_type:
        return None

    description = None
    match = _SUMMARY_RE.search(body or "")
    if match:
        text = match.group(1).strip()
        if text:
            description = text

    return EntityMedia(
        url=str(url),
        media_type=str(media_type),
        site=media.get("site") or None,
        channel=media.get("channel") or None,
        thumbnail=media.get("thumbnail") or None,
        description=description,
    )


@router.get("/entities/{entity_id}/history", response_model=list[EntityHistoryEntry])
async def get_entity_history(
    entity_id: str,
    include_diff: bool = False,
    settings: Settings = Depends(get_settings),
):
    """Entity history with per-commit author attribution.

    Pass ``?include_diff=true`` to inline the added/removed diff for each commit
    (opt-in so the default response stays small — backlog A1).
    """
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")

    return await git_service.get_entity_history(
        entity_id, settings.memory_path, include_diff=include_diff
    )


@router.get("/entities/{entity_id}/history/{commit_hash}/diff", response_model=EntityDiff)
async def get_entity_commit_diff(
    entity_id: str,
    commit_hash: str,
    settings: Settings = Depends(get_settings),
):
    """Added/removed lines for one entity file at one commit (backlog A1)."""
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")

    return await git_service.get_entity_commit_diff(
        entity_id, commit_hash, settings.memory_path
    )


# Bound on the number of immediate children returned, so a huge directory can
# never produce an unbounded payload.
LOCATION_MAX_ENTRIES = 200

# Detect an absolute filesystem path inside a location entity's body when no
# ``path:`` frontmatter key is present (TODO: Sleep should extract this into
# frontmatter — see ``get_entity_location``). POSIX-only, anchored at a slash
# or ``~/``; intentionally conservative.
_BODY_PATH_RE = re.compile(r"(?<!\S)(~?/[^\s`'\"()]+)")


def _detect_location_path(frontmatter: dict, body: str) -> str | None:
    """Resolve a location's declared path from the ENTITY only (never a request).

    Prefers an explicit ``path:`` frontmatter key; falls back to the first
    absolute/``~`` path found in the body. Returns the raw declared string
    (un-expanded) or ``None`` when nothing is declared.
    """
    declared = frontmatter.get("path")
    if declared:
        text = str(declared).strip()
        if text:
            return text
    match = _BODY_PATH_RE.search(body or "")
    return match.group(1) if match else None


@router.get("/entities/{entity_id}/location", response_model=LocationListing)
async def get_entity_location(
    entity_id: str,
    settings: Settings = Depends(get_settings),
):
    """Safe immediate-children listing for a ``type: location`` entity.

    Security model: the only path ever used is the one the ENTITY ITSELF declares
    (frontmatter ``path:`` if present, else a path detected in the body) — never a
    path supplied by the request — so there is no arbitrary-path traversal. Lists
    immediate children only (``os.scandir``, depth 1), reports name/isDir/size
    (stat metadata only, never file contents), bounds the count at
    ``LOCATION_MAX_ENTRIES``, and degrades gracefully: missing path →
    ``exists=False``; permission error → ``accessible=False``; both still 200.

    TODO (Sleep): the entity extractor should write a ``path:`` key into
    ``type: location`` frontmatter when a description names a directory, so this
    endpoint doesn't have to body-scan. Out of scope for this UI/UX pass.
    """
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")

    parsed = markdown_parser.parse(entity_path)
    fm = parsed.frontmatter or {}
    if str(fm.get("type", "")).lower() != "location":
        raise HTTPException(400, f"Entity {entity_id} is not a location")

    declared = _detect_location_path(fm, parsed.body)
    if not declared:
        return LocationListing(path=None, exists=False, entries=[])

    resolved = Path(os.path.expanduser(declared)).resolve()
    if not resolved.is_dir():
        # Missing, or points at a file rather than a listable directory.
        return LocationListing(path=declared, exists=False, entries=[])

    entries: list[LocationEntry] = []
    truncated = False
    try:
        with os.scandir(resolved) as it:
            raw = list(it)
    except PermissionError:
        return LocationListing(path=declared, exists=True, accessible=False, entries=[])
    except OSError:
        return LocationListing(path=declared, exists=True, accessible=False, entries=[])

    # Sort dirs-first, then by name (case-insensitive) for stable display.
    def _sort_key(d: os.DirEntry) -> tuple:
        try:
            is_dir = d.is_dir(follow_symlinks=False)
        except OSError:
            is_dir = False
        return (0 if is_dir else 1, d.name.lower())

    raw.sort(key=_sort_key)
    if len(raw) > LOCATION_MAX_ENTRIES:
        truncated = True
        raw = raw[:LOCATION_MAX_ENTRIES]

    for d in raw:
        try:
            is_dir = d.is_dir(follow_symlinks=False)
        except OSError:
            is_dir = False
        size = 0
        if not is_dir:
            try:
                size = d.stat(follow_symlinks=False).st_size
            except OSError:
                size = 0
        entries.append(LocationEntry(name=d.name, is_dir=is_dir, size=size))

    return LocationListing(
        path=declared, exists=True, accessible=True, truncated=truncated, entries=entries
    )


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
    """Vector entity hits, or [] when the index is unavailable (caller degrades)."""
    try:
        from api.services.vector_index import SqliteVecIndexer
    except Exception:
        return []
    try:
        indexer = SqliteVecIndexer(memory_path)
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

    # Top-2 episode hits not already covered.
    try:
        from api.services.vector_index import SqliteVecIndexer

        indexer = SqliteVecIndexer(memory_path)
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
