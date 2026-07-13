"""Resolve an entity to the primary sources that produced it:
entity.source_episodes -> episode chunk (+ source_id) -> full conversation in
the chat-export corpus. Degrades to chunks-only when the corpus is absent."""
from __future__ import annotations
import json
from pathlib import Path
from functools import lru_cache
from api.services import markdown_parser


@lru_cache(maxsize=4)
def _load_claude_corpus(corpus_path_str: str) -> dict:
    p = Path(corpus_path_str) / "chat-exports" / "claude" / "conversations.json"
    if not p.exists():
        return {}
    try:
        return {c.get("uuid"): c for c in json.loads(p.read_text())}
    except Exception:
        return {}


def gather_entity_sources(memory_path: Path, entity_id: str, *, mode: str = "chunks",
                          corpus_path: Path | None = None) -> dict:
    ent = memory_path / "entities" / f"{entity_id}.md"
    if not ent.exists():
        return {"entity_id": entity_id, "episodes": [], "degraded": True}
    par = markdown_parser.parse(ent)
    ep_ids = par.frontmatter.get("source_episodes", []) or []
    convs = _load_claude_corpus(str(corpus_path)) if (mode == "full" and corpus_path) else {}
    degraded = mode == "full" and not convs

    episodes = []
    for ep_id in ep_ids:
        epf = memory_path / "episodes" / f"{ep_id}.md"
        if not epf.exists():
            continue
        eppar = markdown_parser.parse(epf)
        sid = eppar.frontmatter.get("source_id")
        episodes.append({
            "id": ep_id,
            "chunk": eppar.body,
            "source_id": sid,
            "conversation": convs.get(sid) if convs else None,
        })
    return {"entity_id": entity_id, "episodes": episodes, "degraded": degraded}
