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

import copy
from pathlib import Path

from api.services import bank_index, episode_time

UNKNOWN_ORIGIN = "unknown"


#: bank -> ((episodes fingerprint, entities fingerprint), result). Process-local and disposable (speed 2026-10-29: Home
#: asks on every arrival, and the answer is a pure function of those two folders' headers).
_MEMO: dict[str, tuple[tuple[str, str], list[dict]]] = {}


def aggregate_origins(memory_path: Path) -> list[dict]:
    """:func:`_aggregate`, remembered while neither folder moved (the stamps are the ``/origins`` ETag's own)."""
    memory_path = Path(memory_path)
    with bank_index.shared_scans():
        key = (bank_index.dir_fingerprint(memory_path / "episodes"), bank_index.dir_fingerprint(memory_path / "entities"))
        hit = _MEMO.get(str(memory_path))
        if hit is not None and hit[0] == key:
            return copy.deepcopy(hit[1])
        out = _aggregate(memory_path)
    _MEMO[str(memory_path)] = (key, copy.deepcopy(out))
    return out


def _aggregate(memory_path: Path) -> list[dict]:
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

    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter
        episode_id = str(fm.get("id") or f.stem)
        origin = str(fm.get("origin") or "").strip() or UNKNOWN_ORIGIN
        # CIC8 (ruling 39): `lastSeen` is when Cicada last got an episode of this origin — an import channel's
        # `last_sync` — never the item's own date.
        delivered = episode_time.delivered_at(fm)

        episode_origin[episode_id] = origin

        state = agg.setdefault(
            origin, {"episode_count": 0, "entity_ids": set(), "last_seen": ""}
        )
        state["episode_count"] += 1
        if episode_time.is_later(delivered, state["last_seen"]):
            state["last_seen"] = delivered

    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter
        entity_id = str(fm.get("id") or f.stem)
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
