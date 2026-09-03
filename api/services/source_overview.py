"""One row per memory source — the Sources page's grid (G124).

Where ``origin_stats`` answers "which capture origin" and ``session_stats``
answers "which conversation", this module answers the question the person
asks first: *which of my sources fed this memory, how much, and when last?*
It joins three facts that already exist on disk — episode frontmatter
(``origin``, ``harness``, ``session_id``/``source_id``), entity
``source_episodes`` credits, and ``GET /sources/channels`` state — into one
list. Pure filesystem read; no git, no network, no LLM.

Identity (R1): a closed ``CATALOG`` names every known channel/origin and maps
it to the channel id the app already knows, plus two open families —
``harness:<name>`` for MCP harnesses and ``origin:<id>`` for an origin the
catalog has never heard of — so a new harness or importer appears the day it
ships instead of vanishing into "other". Entity credit is ``source_episodes``
only (R3): ``session_stats`` also credits claims stamped with a session, at
the cost of a body parse per entity; this list counts the way ``/origins``
does and the per-harness conversation rows keep the richer credit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from api.services import bank_index

KIND_ORDER = ("harness", "browser", "social", "feed", "messaging", "import")


@dataclass(frozen=True)
class SourceSpec:
    id: str
    label: str
    kind: str
    mark: str            # an OriginIconography key on the app side
    origins: tuple[str, ...]
    channel: str | None  # GET /sources/channels id, when the source is a channel


# Every origin below is one a real writer stamps today (see R1 in the G124
# plan for the file:line of each). Two rows deliberately carry NO origins:
# `files` (`POST /sources/save`, `cicada_save_url` and the RSS poll all build a
# bare `RawItem` — their pages have no `origin:`, so the app shows nil-origin
# items under Files & links) and `rss` (same cause; its evidence is the
# subscription registry alone until `ingest_feed` stamps one — follow-up on
# the G124 row).
CATALOG: tuple[SourceSpec, ...] = (
    SourceSpec("chat-export:claude", "Claude export", "harness", "claude-export", ("claude-export",), "chat-export:claude"),
    SourceSpec("chat-export:chatgpt", "ChatGPT export", "harness", "chatgpt-export", ("chatgpt-export",), "chat-export:chatgpt"),
    # conversations.py — the Gemini Takeout importer; no channel row exists
    # for it yet, so channel=None and its evidence is its episodes.
    SourceSpec("chat-export:gemini", "Gemini export", "harness", "gemini-export", ("gemini-export",), None),
    SourceSpec("chrome-bookmarks", "Chrome bookmarks", "browser", "chrome-bookmark", ("chrome-bookmark",), "chrome-bookmarks"),
    SourceSpec("safari-bookmarks", "Safari bookmarks", "browser", "safari-bookmark", ("safari-bookmark",), "safari-bookmarks"),
    SourceSpec("safari-tabs", "Safari iCloud tabs", "browser", "safari-tab", ("safari-tab",), "safari-tabs"),
    SourceSpec("pinterest", "Pinterest", "social", "pinterest", ("pinterest",), "pinterest"),
    SourceSpec("reddit", "Reddit", "social", "reddit-saved", ("reddit-saved",), "reddit"),
    SourceSpec("x", "X", "social", "x-bookmarks", ("x-bookmarks",), "x"),
    SourceSpec("instagram", "Instagram", "social", "instagram-saved", ("instagram-saved",), None),
    SourceSpec("youtube", "YouTube", "social", "youtube-playlist", ("youtube-playlist",), None),
    SourceSpec("linkedin", "LinkedIn", "social", "linkedin-saved", ("linkedin-saved",), None),
    SourceSpec("tiktok", "TikTok", "social", "tiktok-saved", ("tiktok-saved", "tiktok-history"), None),
    SourceSpec("rss", "RSS feeds", "feed", "rss", (), "rss"),            # no origin stamped today — see R1
    SourceSpec("calendar", "Calendars", "feed", "calendar", ("calendar",), "calendar"),
    SourceSpec("telegram", "Telegram", "messaging", "telegram", ("telegram",), "telegram"),
    SourceSpec("notes", "Apple Notes", "import", "apple-notes", ("apple-notes",), "notes"),
    SourceSpec("files", "Files & links", "import", "bookmark", (), "files"),  # nil-origin pages — see R1
)
_BY_ID = {spec.id: spec for spec in CATALOG}
_ORIGIN_TO_ID = {origin: spec.id for spec in CATALOG for origin in spec.origins}

# Display names for harness ids an MCP client stamps (mcp/server.py SESSION).
# Generic on purpose — portability means no owner-specific client here; an
# unlisted harness reads as its id.
HARNESS_LABELS = {
    "claude-code": "Claude Code",
    "claude-desktop": "Claude Desktop",
    "cursor": "Cursor",
    "codex": "Codex",
    "unknown": "Other agents",
}
UNKNOWN = "unknown"


def source_key(fm: dict) -> str:
    """Which source row an episode belongs to.

    A ``session_id`` or ``origin: mcp`` means an agent conversation, so the
    row is the harness (R4: legacy ``mcp`` episodes with no session still
    belong to ``harness:unknown`` — they ARE conversations, just uncounted
    ones). Otherwise the origin looks itself up in the catalog and falls back
    to the open ``origin:`` family.
    """
    origin = str(fm.get("origin") or "").strip()
    if fm.get("session_id") or origin == "mcp":
        return "harness:" + (str(fm.get("harness") or "").strip() or UNKNOWN)
    if not origin:
        return f"origin:{UNKNOWN}"
    return _ORIGIN_TO_ID.get(origin, f"origin:{origin}")


def _new_state(key: str) -> dict:
    if key.startswith("harness:"):
        harness = key.split(":", 1)[1]
        label, kind, mark, origins, channel = (
            HARNESS_LABELS.get(harness, harness), "harness", harness, [], None)
    elif key in _BY_ID:
        spec = _BY_ID[key]
        label, kind, mark, origins, channel = spec.label, spec.kind, spec.mark, list(spec.origins), spec.channel
        harness = None
    else:
        origin = key.split(":", 1)[1]
        label, kind, mark, origins, channel, harness = origin, "import", origin, [origin], None, None
    return {
        "id": key, "label": label, "kind": kind, "mark": mark,
        "conversations": set(), "episodes": 0, "entities": set(),
        "items": 0, "last_activity_at": "", "connected": False,
        "last_error": None, "actions": [], "channel_id": channel,
        "origins": origins, "harness": harness,
    }


def build_overview(memory_path: Path, *, channels: list[dict]) -> list[dict]:
    """Every source with evidence (R2), ordered by kind then newest activity.

    ``channels`` is ``channel_registry.build_channels(...)``'s output — passed
    in, not recomputed, so the router computes it once for both the ETag's
    connector tag and this payload.
    """
    memory_path = Path(memory_path)
    states: dict[str, dict] = {}
    episode_key: dict[str, str] = {}

    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter
        key = source_key(fm)
        episode_key[str(fm.get("id") or f.stem)] = key
        state = states.setdefault(key, _new_state(key))
        state["episodes"] += 1
        conversation = str(fm.get("session_id") or fm.get("source_id") or "").strip()
        if conversation:
            state["conversations"].add(conversation)
        ts = str(fm.get("timestamp") or "")
        if _sortable(ts) > _sortable(state["last_activity_at"]):
            state["last_activity_at"] = ts

    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter
        entity_id = str(fm.get("id") or f.stem)
        for ep_id in fm.get("source_episodes", []) or []:
            key = episode_key.get(str(ep_id))
            if key:
                states[key]["entities"].add(entity_id)

    for channel in channels:
        spec = _BY_ID.get(channel["id"])
        if spec is None:
            continue
        state = states.setdefault(spec.id, _new_state(spec.id))
        state["items"] = int(channel.get("count") or 0)
        state["connected"] = bool(channel.get("connected"))
        state["last_error"] = channel.get("last_error")
        state["actions"] = list(channel.get("actions") or [])
        last_sync = str(channel.get("last_sync") or "")
        # By instant, not lexically: a `Z` sync stamp and a `+00:00` episode
        # stamp differ in shape and would otherwise compare by string length.
        if _sortable(last_sync) > _sortable(state["last_activity_at"]):
            state["last_activity_at"] = last_sync

    rows = []
    for state in states.values():
        conversations = len(state["conversations"])
        if state["channel_id"] is None:
            # No channel to be "connected" to: a harness or import-only source
            # is connected exactly when it has fed memory.
            state["connected"] = state["episodes"] > 0
        if not (state["connected"] or state["episodes"] or conversations or state["items"]):
            continue  # R2
        rows.append({
            **state,
            "conversations": conversations,
            "entities": len(state["entities"]),
            "last_activity_at": state["last_activity_at"] or None,
        })
    rows.sort(key=lambda r: (KIND_ORDER.index(r["kind"]), -_sortable(r["last_activity_at"]), r["id"]))
    return rows


def _sortable(ts: str | None) -> float:
    """ISO timestamps compare lexically only within one shape; normalise
    ``Z``/``+00:00`` and bare dates to a float so a sync stamp and an episode
    stamp order by instant, never by string length."""
    if not ts:
        return 0.0
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()
