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

from api.services import bank_index, folder_source

# G134: meetings and dictation are their own section, VOICE & MEETINGS (R-LS25).
KIND_ORDER = ("harness", "browser", "social", "feed", "messaging", "voice", "import")

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
    # conversations.py — the Gemini Takeout importer; its channel row counts
    # `gemini-export` (Track I).
    SourceSpec("chat-export:gemini", "Gemini export", "harness", "gemini-export", ("gemini-export",), "chat-export:gemini"),
    SourceSpec("chrome-bookmarks", "Chrome bookmarks", "browser", "chrome-bookmark", ("chrome-bookmark",), "chrome-bookmarks"),
    SourceSpec("safari-bookmarks", "Safari bookmarks", "browser", "safari-bookmark", ("safari-bookmark",), "safari-bookmarks"),
    SourceSpec("safari-tabs", "Safari iCloud tabs", "browser", "safari-tab", ("safari-tab",), "safari-tabs"),
    # Round 4 (C9): the Chromium family beyond Chrome — Chrome's parser, their own origin.
    SourceSpec("brave-bookmarks", "Brave bookmarks", "browser", "brave-bookmark", ("brave-bookmark",), "brave-bookmarks"),
    SourceSpec("vivaldi-bookmarks", "Vivaldi bookmarks", "browser", "vivaldi-bookmark", ("vivaldi-bookmark",), "vivaldi-bookmarks"),
    SourceSpec("comet-bookmarks", "Comet bookmarks", "browser", "comet-bookmark", ("comet-bookmark",), "comet-bookmarks"),
    SourceSpec("dia-bookmarks", "Dia bookmarks", "browser", "dia-bookmark", ("dia-bookmark",), "dia-bookmarks"),
    # Round 4 (G160 first slice): Chrome's open tab groups — one snapshot episode per group.
    SourceSpec("chrome-tab-groups", "Chrome tab groups", "browser", "chrome-tab-group", ("chrome-tab-group",), "chrome-tab-groups"),
    SourceSpec("pinterest", "Pinterest", "social", "pinterest", ("pinterest",), "pinterest"),
    SourceSpec("reddit", "Reddit", "social", "reddit-saved", ("reddit-saved",), "reddit"),
    # `x-likes`: the X archive's like.js (saved_exports); bookmarks come from the connector.
    SourceSpec("x", "X", "social", "x-bookmarks", ("x-bookmarks", "x-likes"), "x"),
    SourceSpec("instagram", "Instagram", "social", "instagram-saved", ("instagram-saved",), None),
    SourceSpec("youtube", "YouTube", "social", "youtube-playlist", ("youtube-playlist",), None),
    # G71 (2026-10-16): `youtube-history` — the day episodes of what was watched (Takeout, Chrome, the agent). Its own
    # row since Sources v3 (review of #347): watch history is never a save, so it is captured, never counted as saved.
    SourceSpec("youtube-history", "YouTube history", "social", "youtube-history", ("youtube-history",), None),
    SourceSpec("linkedin", "LinkedIn", "social", "linkedin-saved", ("linkedin-saved",), None),
    SourceSpec("tiktok", "TikTok", "social", "tiktok-saved", ("tiktok-saved",), None),
    SourceSpec("tiktok-history", "TikTok history", "social", "tiktok-history", ("tiktok-history",), None),
    SourceSpec("rss", "RSS feeds", "feed", "rss", ("rss",), "rss"),
    SourceSpec("calendar", "Calendars", "feed", "calendar", ("calendar",), "calendar"),
    # G142 (round 4): Apple Calendar through EventKit, so its episodes never read as a raw id.
    SourceSpec("calendar-local", "Apple Calendar", "feed", "calendar-local", ("calendar-local",), "calendar-local"),
    SourceSpec("telegram", "Telegram", "messaging", "telegram", ("telegram",), "telegram"),
    # G179: the Messages conversations the person ticked — one episode per sitting.
    SourceSpec("imessage", "Messages", "messaging", "imessage", ("imessage",), "imessage"),
    SourceSpec("wispr-flow", "Wispr Flow", "voice", "wispr-flow", ("wispr-flow",), "wispr-flow"),
    SourceSpec("notes", "Apple Notes", "import", "apple-notes", ("apple-notes",), "notes"),
    SourceSpec("files", "Files & links", "import", "bookmark", ("saved-link",), "files"),
    # 2026-10-23: a note typed on a paired phone (`/capture/note`, `origin: phone`) or another device (`note`), so
    # neither reads as its raw id ("phone").
    SourceSpec("phone", "Phone", "import", "phone", ("phone",), None),
    SourceSpec("device-notes", "Notes from your devices", "import", "note", ("note",), None),
)
#: Sources v3 (owner 2026-10-19): "where did my stuff come from" — the sources whose items the person saved on purpose
#: (a bookmark, a saved post, a pin, a Watch later, a link they pasted) are `saved`; everything Cicada captures on its
#: own (agent conversations, chat exports, watch history days, messages, calendars, feeds, notes, folders, open tabs)
#: is `captured`. A fact of the catalog, served on every row as `intent`, so every client groups the same way.
SAVED_SOURCES = frozenset({
    "chrome-bookmarks", "safari-bookmarks", "brave-bookmarks", "vivaldi-bookmarks", "comet-bookmarks", "dia-bookmarks",
    "pinterest", "reddit", "x", "instagram", "youtube", "linkedin", "tiktok", "files",
})
INTENTS = ("saved", "captured")
#: Folded into `/sources/overview`'s ETag: bump it when the body changes for the same bank files (v3: `intent`;
#: v4: `waiting`, `faces`/`faces_more`, and check records left out; v5: a nil-origin save on Files & links, the Phone
#: and device-notes rows).
SHAPE = "overview-v5"

#: Sources v4 (owner 2026-10-19: "I don't understand how Sleep is also a source on the page"). A check record is the
#: episode Cicada writes as the citation for a question a check settled — `web_settle` (a web lookup Sleep or an agent
#: ran, `source: web-check`; Sleep's has `origin: sleep` and read as a source called "sleep") and `check_record` (an
#: agent's check of a tracked source, `source: source-check`). Nothing came in through it: its home is the Inbox's
#: "Settled by a check" list and the claim it cites, so no source row counts it. Pinned to the writers' constants by
#: `test_source_overview`.
CHECK_RECORD_SOURCES = frozenset({"web-check", "source-check"})
#: Sources v4 (owner 2026-10-19: "the first three and then a fourth circle in the back that says '+N more'") — how many
#: faces a row carries: the chats that fed Messages, the sites a saved source's things came from.
MAX_FACES = 3
FACE_CHAT_SOURCES = frozenset({"imessage"})


def is_check_record(fm: dict) -> bool:
    """True for the citation episode a settled check writes — never something that came in (``CHECK_RECORD_SOURCES``)."""
    return str((fm or {}).get("source") or "").strip() in CHECK_RECORD_SOURCES


def intent_of(key: str) -> str:
    """``saved`` for a source of things the person saved on purpose, else ``captured`` (harnesses, folders and an
    origin the catalog does not know are captured: nothing says the person picked each item)."""
    return "saved" if key in SAVED_SOURCES else "captured"


_BY_ID = {spec.id: spec for spec in CATALOG}
_ORIGIN_TO_ID = {origin: spec.id for spec in CATALOG for origin in spec.origins}
_FILES_ORIGINS = frozenset(_BY_ID["files"].origins)
#: The saved rows with no channel: their `items` is their saved media pages, counted here (the list's own set).
_SAVED_LIST_ROWS = frozenset(spec.id for spec in CATALOG if spec.channel is None and spec.id in SAVED_SOURCES)

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
    # G135 R-R26 — a remote connector's app, as its episodes stamp it.
    "claude-web": "Claude",
    "chatgpt": "ChatGPT",
    "perplexity": "Perplexity",
    "grok": "Grok",                     # round 4 R-AG7
    "claude-code-remote": "Claude Code (remote)",
    "codex-remote": "Codex (remote)",
    "vscode": "VS Code",
    "gemini-cli": "Gemini CLI",
    "remote-app": "Other remote app",
    "agent-api": "Agents over HTTP",   # G213: an agent token's episodes (`catalog.API_HARNESS`)
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
    # G133: one card per watched folder, not one "folder" card for all of them.
    if origin == folder_source.ORIGIN and fm.get("folder_id"):
        return folder_source.channel_id(str(fm["folder_id"]))
    if not origin:
        # A save's episode written before origins were stamped, or from a bookmarks file imported through Files and
        # links (2026-10-23: it read as a row called "unknown"): the Files & links card, where its nil-origin page is
        # already counted (`_FILES_ORIGINS`).
        if fm.get("media_entity_id"):
            return "files"
        return f"origin:{UNKNOWN}"
    return _ORIGIN_TO_ID.get(origin, f"origin:{origin}")


def _new_state(key: str, labels: dict[str, str] | None = None) -> dict:
    if key.startswith("harness:"):
        harness = key.split(":", 1)[1]
        label, kind, mark, origins, channel = (
            HARNESS_LABELS.get(harness, harness), "harness", harness, [], None)
    elif key in _BY_ID:
        spec = _BY_ID[key]
        label, kind, mark, origins, channel = spec.label, spec.kind, spec.mark, list(spec.origins), spec.channel
        harness = None
    elif key.startswith(folder_source.CHANNEL_PREFIX):
        known = (labels or {})
        label, kind, mark, origins, channel = (
            known.get(key, "Folder (removed)"), "import", "folder", [folder_source.ORIGIN],
            key if key in known else None)
        harness = None
    else:
        origin = key.split(":", 1)[1]
        label, kind, mark, origins, channel, harness = origin, "import", origin, [origin], None, None
    return {
        "id": key, "label": label, "kind": kind, "mark": mark, "intent": intent_of(key),
        "conversations": set(), "episodes": 0, "entities": set(),
        # Sources v4 — this source's episodes still waiting for Sleep's read (`history_index.waits_for_model`, the
        # rule Sleep's own queue count uses), so the detail's "Consolidate now · N waiting" is the server's number.
        "waiting": 0,
        "faces": [], "faces_more": 0,
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
    labels = {folder_source.channel_id(f["id"]): str(f.get("label") or "Folder")
              for f in folder_source.list_folders(memory_path)}
    today = today or datetime.now(timezone.utc).date()
    window_start = (today - timedelta(days=ACTIVITY_DAYS - 1)).isoformat()
    window_end = today.isoformat()

    from api.services import history_index

    chats: dict[str, dict[str, tuple[float, str]]] = {}
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter
        if is_check_record(fm):
            continue   # Sources v4: a settled check's citation, not an intake (`CHECK_RECORD_SOURCES`)
        key = source_key(fm)
        episode_key[str(fm.get("id") or f.stem)] = key
        state = states.setdefault(key, _new_state(key, labels))
        state["episodes"] += 1
        if history_index.waits_for_model(fm):
            state["waiting"] += 1
        if key in FACE_CHAT_SOURCES and fm.get("conversation") and not fm.get("source_deleted_at"):
            _note_chat(chats.setdefault(key, {}), fm)
        conversation = str(fm.get("session_id") or fm.get("source_id") or "").strip()
        if conversation:
            state["conversations"].add(conversation)
        ts = str(fm.get("timestamp") or "")
        # Bucketed in the loop that already reads this field for
        # `last_activity_at` — zero extra file reads, no body parse (R-A16).
        day = _activity_day(ts)
        if day is not None and window_start <= day <= window_end:
            state["activity"][day] = state["activity"].get(day, 0) + 1
        # The row's last activity is the newest capture WRITE, not the conversation's first moment (2026-10-23, live
        # test: Claude Code read "1 day ago" right after a capture, since one session is one episode and its
        # `timestamp` is when it began). `captured_at` is the capture writer's stamp on every create and update,
        # `last_turn_at` the last kept turn's own time; the activity buckets above stay on `timestamp`.
        latest = max((str(fm.get(k) or "") for k in ("timestamp", "captured_at", "last_turn_at")), key=_sortable)
        if _sortable(latest) > _sortable(state["last_activity_at"]):
            state["last_activity_at"] = latest

    # Final review M1: the `files` card must count what its page renders. The
    # page (ChannelSourceView.items) lists the Feed items whose page carries
    # no `origin:`, but `channel_registry`'s `files.count` is `len(url_index)`
    # — every item `ingest_batch` ever wrote, bookmarks/pins/iCloud tabs
    # included — so a bank with 400 imported bookmarks and 3 pasted links read
    # "400 items" on a card whose page showed 3. Counted here, on the same
    # entity walk as the credits, from the pages themselves.
    files_media = 0
    # Sources v3 (review of #347): a saved source with no channel counts what its list lists — its live saved media
    # pages (`channel_items` lists them by these origins) — never its episodes, so a history day can never read "saved".
    saved_media: dict[str, int] = {}
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter
        entity_id = str(fm.get("id") or f.stem)
        origin = str(fm.get("origin") or "").strip()
        owner = _ORIGIN_TO_ID.get(origin)
        if (fm.get("type") == "media" and owner in _SAVED_LIST_ROWS and not is_hidden(fm)):
            saved_media[owner] = saved_media.get(owner, 0) + 1
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
        cid = channel["id"]
        spec = _BY_ID.get(cid)
        if spec is None and cid not in labels:
            continue
        state = states.setdefault(cid, _new_state(cid, labels))
        if spec is not None and spec.id == "files":
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

    for key, count in saved_media.items():
        state = states.setdefault(key, _new_state(key, labels))
        state["items"] = count

    # Sources v4 — the faces a row shows: the newest first, at most `MAX_FACES`, and how many more there are.
    photos = _chat_photos(memory_path) if chats else {}
    for key, by_chat in chats.items():
        if key in states:
            ordered = sorted(by_chat.items(), key=lambda kv: (kv[1][0], kv[0]), reverse=True)
            states[key]["faces"] = [{"kind": "chat", "id": cid, "label": label, "photo": photos.get(cid)}
                                    for cid, (_, label) in ordered[:MAX_FACES]]
            states[key]["faces_more"] = max(0, len(ordered) - MAX_FACES)
    # A saved row's faces come from the set its list lists, and only while its count says it holds something (review
    # of #358: "Nothing saved yet" beside three faces read as a contradiction) — never a bookmark that left the browser.
    from api.services import channel_items   # lazy: channel_items imports this module

    for key, state in states.items():
        if state["intent"] == "saved" and state["items"] > 0:
            faces, more = channel_items.saved_faces(memory_path, state["channel_id"] or key, limit=MAX_FACES)
            state["faces"] = [{"kind": "site", **face} for face in faces]
            state["faces_more"] = more

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


def _note_chat(by_chat: dict[str, tuple[float, str]], fm: dict) -> None:
    """Keep each chat's newest sitting: its instant and the name its correspondent record carries (G179)."""
    cid = str(fm.get("conversation") or "")
    when = _sortable(str(fm.get("sitting_last_at") or fm.get("timestamp") or ""))
    record = fm.get("correspondent") if isinstance(fm.get("correspondent"), dict) else {}
    label = " ".join(str(record.get("name") or "").split())[:80] or "Messages"
    held = by_chat.get(cid)
    if held is None or when >= held[0]:
        by_chat[cid] = (when, label)


def _chat_photos(memory_path: Path) -> dict[str, str]:
    """Each ticked chat's stored photo hash (`messages_photos`, outside every bank) — the face's `?v=`."""
    from api.services import logo_service, messages_photos, messages_source

    try:
        meta = messages_photos.read_meta(logo_service.bank_name(memory_path))
        ticked = {cid for cid, e in messages_source.load_settings(memory_path)["conversations"].items()
                  if e.get("ticked")}
    except Exception:  # noqa: BLE001 — a face without a photo draws its monogram
        return {}
    return {cid: str(e["sha"]) for cid, e in meta.items()
            if cid in ticked and isinstance(e, dict) and isinstance(e.get("sha"), str)}


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
