"""Repo-wide origin provenance aggregation — "where did this memory come from".

Every episode is stamped at capture time with an ``origin`` in its frontmatter
(``mcp``, ``telegram``, ``chrome-bookmark``, ``safari-bookmark``,
``claude-export``, ...) — see ``mcp/server.py::handle_save_episode`` and the
connectors in ``api/services/telegram_capture.py`` / ``bookmark_sync.py``.
Entities don't carry their own origin directly; they inherit it transitively
through their ``source_episodes`` list.

This module aggregates, per origin: how many episodes came from it, how many
*distinct* entities are attributable to it (an entity counts toward an origin
if any of its source episodes carries that origin), and the most recent
episode timestamp seen for that origin. Pure filesystem read — no network, no
git — mirroring the shape of ``api/services/git_service.get_contributors``
but keyed on capture origin rather than authoring model.
"""

from pathlib import Path

from api.services import markdown_parser

UNKNOWN_ORIGIN = "unknown"


def aggregate_origins(memory_path: Path) -> list[dict]:
    """Aggregate episode/entity counts per capture origin.

    Returns a list of ``{"origin", "episodeCount", "entityCount", "lastSeen"}``
    dicts sorted by ``episodeCount`` descending (ties broken alphabetically by
    origin for a stable, deterministic order). Returns ``[]`` when the
    ``episodes/`` directory doesn't exist.
    """
    episodes_dir = memory_path / "episodes"
    if not episodes_dir.exists():
        return []

    # episode id -> origin, and origin -> {episode_count, last_seen}
    episode_origin: dict[str, str] = {}
    agg: dict[str, dict] = {}

    for filepath in sorted(episodes_dir.glob("*.md")):
        parsed = markdown_parser.parse(filepath)
        fm = parsed.frontmatter
        episode_id = str(fm.get("id") or filepath.stem)
        origin = str(fm.get("origin") or "").strip() or UNKNOWN_ORIGIN
        timestamp = str(fm.get("timestamp") or "")

        episode_origin[episode_id] = origin

        state = agg.setdefault(
            origin, {"episode_count": 0, "entity_ids": set(), "last_seen": ""}
        )
        state["episode_count"] += 1
        if timestamp > state["last_seen"]:
            state["last_seen"] = timestamp

    entities_dir = memory_path / "entities"
    if entities_dir.exists():
        for filepath in sorted(entities_dir.glob("*.md")):
            parsed = markdown_parser.parse(filepath)
            fm = parsed.frontmatter
            entity_id = str(fm.get("id") or filepath.stem)
            source_episodes = fm.get("source_episodes", []) or []

            # An entity's origins = the distinct origins of its source episodes.
            # Only episodes we actually saw on disk contribute (a dangling
            # source_episode reference doesn't manufacture a phantom origin).
            origins_for_entity = {
                episode_origin[ep_id]
                for ep_id in source_episodes
                if ep_id in episode_origin
            }
            for origin in origins_for_entity:
                state = agg.setdefault(
                    origin, {"episode_count": 0, "entity_ids": set(), "last_seen": ""}
                )
                state["entity_ids"].add(entity_id)

    results = [
        {
            "origin": origin,
            "episodeCount": state["episode_count"],
            "entityCount": len(state["entity_ids"]),
            "lastSeen": state["last_seen"],
        }
        for origin, state in agg.items()
    ]
    results.sort(key=lambda r: (-r["episodeCount"], r["origin"]))
    return results
