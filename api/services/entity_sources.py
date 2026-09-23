"""Resolve an entity to the primary sources that produced it:
entity.source_episodes -> episode chunk (+ source_id) -> full conversation in
the chat-export corpus. Degrades to chunks-only when the corpus is absent."""
from __future__ import annotations
import json
from pathlib import Path
from functools import lru_cache
from api.services import markdown_parser
from api.services.id_utils import bank_file


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
    # Task 5 review r1: both ids are joined onto a bank folder, so both go
    # through the one-segment guard — the entity id comes from the caller, and
    # an episode id from a page's frontmatter, which a remote
    # `cicada_write_claim(source_episode=...)` can seed.
    ent = bank_file(memory_path / "entities", entity_id)
    if ent is None or not ent.exists():
        return {"entity_id": entity_id, "episodes": [], "degraded": True}
    par = markdown_parser.parse(ent)
    ep_ids = par.frontmatter.get("source_episodes", []) or []
    convs = _load_claude_corpus(str(corpus_path)) if (mode == "full" and corpus_path) else {}
    degraded = mode == "full" and not convs

    episodes = []
    for ep_id in ep_ids:
        epf = bank_file(memory_path / "episodes", str(ep_id))
        if epf is None or not epf.exists():
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
