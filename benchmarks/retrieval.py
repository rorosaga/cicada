"""Retrieval functions for the three Table 1 conditions.

- :func:`retrieve_full` is Condition A. Calls the same ``handle_recall``
  path the MCP Bookworm tool uses — semantic entity search, keyword entity
  fallback, one-hop wikilink traversal, episode LEANN excerpts, and
  proactive nudges/clarifications. The condition-A retrieval IS the
  full product behavior; we do not reimplement it.

- :func:`retrieve_episodes_only` is Condition B. Queries only the raw
  episode LEANN index. No entity pages, no keyword fallback, no wikilink
  hops, no nudges, no clarifications. This is the clean episodic
  baseline the ablation in experiments.tex asks for — it isolates "what
  does Cicada look like with zero consolidation."

- Condition C (commercial baseline) is deliberately NOT automated. The
  Table 1 runner writes stub rows for Condition C so the user can paste
  in ChatGPT/Claude answers by hand before scoring.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from benchmarks._bootstrap import REPO_ROOT  # noqa: F401 — side-effect import


@dataclass
class Retrieval:
    """Uniform return shape for both retrieval paths.

    ``context`` is the text that gets fed to the answer-synthesis LLM.
    ``hits`` holds any structured hit records that would be useful for
    debugging or per-question inspection. ``notes`` is a short tag
    describing which retrieval path was taken.
    """

    context: str
    hits: list[dict] = field(default_factory=list)
    notes: str = ""


def retrieve_full(memory_path: Path, query: str) -> Retrieval:
    """Condition A — call the MCP Bookworm ``handle_recall`` path.

    Sets ``CICADA_MEMORY_PATH`` so the ``get_memory_path()`` call inside
    ``mcp.server`` resolves to the target memory dir. The env var is
    per-process, so this is safe to call with different paths in the
    same session.
    """
    os.environ["CICADA_MEMORY_PATH"] = str(memory_path)

    # Lazy import so sys.path is already set up by _bootstrap and the env
    # var above is visible to the first get_memory_path() call.
    from mcp.server import handle_recall

    context = handle_recall(query) or ""
    return Retrieval(
        context=context,
        hits=[],
        notes="condition_a/full_bookworm",
    )


def retrieve_episodes_only(
    memory_path: Path,
    query: str,
    top_k: int = 5,
) -> Retrieval:
    """Condition B — raw LEANN episode search, nothing else.

    Returns the top-k episode chunks joined into a single context string
    that the answerer can use. If the episode LEANN index doesn't exist
    or the search fails, returns an empty-context Retrieval so the
    downstream answerer can still report a clean "insufficient
    information" answer instead of crashing.
    """
    from api.services.leann_indexer import LeannIndexer

    indexer = LeannIndexer(memory_path)
    try:
        hits = indexer.search_episodes(query, top_k=top_k)
    except Exception as e:
        return Retrieval(
            context="(episode search failed)",
            hits=[],
            notes=f"condition_b/error:{type(e).__name__}",
        )

    if not hits:
        return Retrieval(
            context="(no episodes retrieved)",
            hits=[],
            notes="condition_b/empty",
        )

    chunks: list[str] = []
    for i, hit in enumerate(hits, 1):
        meta = hit.get("metadata") or {}
        ep_id = meta.get("episode_id", "unknown")
        text = (hit.get("text") or "").strip()
        chunks.append(f"[{i}] (episode: {ep_id})\n{text}")

    return Retrieval(
        context="\n\n".join(chunks),
        hits=hits,
        notes="condition_b/episodes_only",
    )
