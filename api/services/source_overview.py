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
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path

from api.services import bank_index

KIND_ORDER = ("harness", "browser", "social", "feed", "messaging", "import")

# R-A16: the Memory-sources sparkline's window. Bounded so the payload cannot
# grow with the age of the bank, and keyed by ABSOLUTE dates so a 304'd
# response renders a day short rather than a day shifted.
ACTIVITY_DAYS = 30


def _activity_day(raw: str) -> str | None:
    """The UTC calendar day an episode was captured, as ``YYYY-MM-DD``.

    Banks hold three timestamp shapes and they are deliberately never
    migrated: aware ``+00:00`` (G114), legacy naive-LOCAL, and ``Z``-suffixed
    imports. ``raw[:10]`` would call a naive-local stamp a UTC day — off by
    one, invisibly, for exactly the rows nobody checks. A naive stamp means
    what the writer that produced it meant, LOCAL time, so ``astimezone()``
    (no argument) attaches the system zone before the UTC conversion. Same
    rule, same reason, as ``sleep_debt._parse_episode_timestamp``'s M1 lesson
    — do not write a fourth parser.

    Measured in ``api/.venv`` (CPython 3.12.11): ``datetime.fromisoformat``
    accepts all three shapes, ``Z`` included (3.11+), so there is exactly one
    parse call here and no hand-rolled ``Z`` -> ``+00:00`` rewrite.
    """
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).date().isoformat()


@dataclass(frozen=True)
class SourceSpec:
    id: str
    label: str
    kind: str
    mark: str            # an OriginIconography key on the app side
    origins: tuple[str, ...]
    channel: str | None  # GET /sources/channels id, when the source is a channel


# Every origin below is one a real writer stamps today (see R1 in the G124
# plan for the file:line of each). `saved-link` and `rss` were the G124
# follow-up: the three writers that built a bare `RawItem` — `POST
# /sources/save`, `cicada_save_url`'s backend-down path, and `ingest_feed` —
# now stamp one, so both rows can attribute an episode and an entity instead
# of resting on a count alone. Pages written before that stamp carry no
# `origin:` and still count under Files & links; see `build_overview`.
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
    SourceSpec("rss", "RSS feeds", "feed", "rss", ("rss",), "rss"),
    SourceSpec("calendar", "Calendars", "feed", "calendar", ("calendar",), "calendar"),
    SourceSpec("telegram", "Telegram", "messaging", "telegram", ("telegram",), "telegram"),
    SourceSpec("notes", "Apple Notes", "import", "apple-notes", ("apple-notes",), "notes"),
    SourceSpec("files", "Files & links", "import", "bookmark", ("saved-link",), "files"),
)
_BY_ID = {spec.id: spec for spec in CATALOG}
_ORIGIN_TO_ID = {origin: spec.id for spec in CATALOG for origin in spec.origins}
_FILES_ORIGINS = frozenset(_BY_ID["files"].origins)

# Final review F6 — the ONE predicate for "this media page is hidden from
# every read path". `GET /sources/{id}` filters its item list on it (a
# `remove` resolution from G129 slice 2 archives the page; `dropped` is
# never resurfaced; `junk` is a consent wall or login page that was retired
# without a byte fetched), and the `files` card's headline count is computed
# HERE, on a different walk — so the two must share the rule or the card
# reads "400 items" over a page listing 3. That count-vs-list mismatch is
# exactly what the "Final review M1" comment below already exists to
# prevent; `api/routers/sources.py` imports these rather than re-typing them.
HIDDEN_STATUSES = frozenset({"archived", "dropped"})
HIDDEN_ENRICHMENT = "junk"


def is_hidden(fm: dict) -> bool:
    """True when a media page must not be counted or listed anywhere."""
    return (
        str(fm.get("status", "active")) in HIDDEN_STATUSES
        or str(fm.get("enrichment_status") or "") == HIDDEN_ENRICHMENT
    )

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
        # Sparse ISO-UTC-day -> captures that day (R-A16); a silent day has no
        # key, so a gap can never be read as a zero the backend asserted.
        "activity": {},
        "items": 0, "last_activity_at": "", "connected": False,
        "last_error": None, "actions": [], "channel_id": channel,
        "origins": origins, "harness": harness,
    }


def build_overview(memory_path: Path, *, channels: list[dict], today: _date | None = None) -> list[dict]:
    """Every source with evidence (R2), ordered by kind then newest activity.

    ``channels`` is ``channel_registry.build_channels(...)``'s output — passed
    in, not recomputed, so the router computes it once for both the ETag's
    connector tag and this payload.

    ``today`` is injected so the ``activity`` window is testable without
    freezing the clock; it defaults to the real UTC day. Known and accepted
    (R-A16): the window moves at UTC midnight while no ETag component does, so
    a client holding a 304 keeps yesterday's window until the next real bank
    write — a day SHORT, never a day SHIFTED, which is exactly why the keys
    are absolute dates rather than a rolling array.
    """
    memory_path = Path(memory_path)
    states: dict[str, dict] = {}
    episode_key: dict[str, str] = {}
    today = today or datetime.now(timezone.utc).date()
    window_start = (today - timedelta(days=ACTIVITY_DAYS - 1)).isoformat()
    window_end = today.isoformat()

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
        # Bucketed in the loop that already reads this field for
        # `last_activity_at` — zero extra file reads, no body parse (R-A16).
        day = _activity_day(ts)
        if day is not None and window_start <= day <= window_end:
            state["activity"][day] = state["activity"].get(day, 0) + 1
        if _sortable(ts) > _sortable(state["last_activity_at"]):
            state["last_activity_at"] = ts

    # Final review M1: the `files` card must count what its page renders. The
    # page (ChannelSourceView.items) lists the Feed items whose page carries
    # no `origin:`, but `channel_registry`'s `files.count` is `len(url_index)`
    # — every item `ingest_batch` ever wrote, bookmarks/pins/iCloud tabs
    # included — so a bank with 400 imported bookmarks and 3 pasted links read
    # "400 items" on a card whose page showed 3. Counted here, on the same
    # entity walk as the credits, from the pages themselves.
    files_media = 0
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter
        entity_id = str(fm.get("id") or f.stem)
        origin = str(fm.get("origin") or "").strip()
        # Nil-origin OR `saved-link`: the writers stamp an origin now, but every
        # link saved before they did carries none, and both are the same card.
        # F6: skipping the hidden ones is what keeps this count equal to the
        # list `GET /sources/{id}` renders — the same predicate, one module.
        if fm.get("type") == "media" and (not origin or origin in _FILES_ORIGINS) and not is_hidden(fm):
            files_media += 1
        for ep_id in fm.get("source_episodes", []) or []:
            key = episode_key.get(str(ep_id))
            if key:
                states[key]["entities"].add(entity_id)

    for channel in channels:
        spec = _BY_ID.get(channel["id"])
        if spec is None:
            continue
        state = states.setdefault(spec.id, _new_state(spec.id))
        if spec.id == "files":
            # Items AND connected follow the set the page renders: a bank
            # holding only imported bookmarks has no Files & links evidence
            # (R2), so it gets no card rather than a connected one reading
            # "0 items". `channel_registry`'s `files.count` cannot serve here —
            # it is `len(url_index)`, every item `ingest_batch` ever wrote,
            # bookmarks and pins included. `rss` keeps its channel count on
            # purpose: that is the subscription count its page's state card
            # shows, and its origin now supplies the episode and entity credit
            # that count never could.
            state["items"] = files_media
            state["connected"] = files_media > 0
        else:
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
