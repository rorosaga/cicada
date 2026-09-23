import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, UploadFile
from loguru import logger
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import ConversationSummary, ConversationUploadResponse, ResumeDescriptor
from api.services import episode_ids, episode_scrub, episode_staging, session_stats, sync_service

router = APIRouter()

# Injectable seam: tests replace this with a fake so no test ever probes the
# real ``~/.claude``. Production always resolves to the isfile() probe.
transcript_exists = session_stats.default_transcript_exists

# The binary name is a FIXED LITERAL. Never read from settings, env, or a
# request body: it is the head of an argv list the app executes.
CLAUDE_BINARY = "claude"

# Conservative cwd charset. A path that fails this is dropped rather than
# sanitised, because it is about to be interpolated into AppleScript source
# on the app side.
CWD_SAFE_RE = re.compile(r"^[A-Za-z0-9/_.~-]+$")


@router.post("/conversations/upload", response_model=ConversationUploadResponse)
async def upload_conversation(
    file: UploadFile,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    """Deprecated shim (Track I T2, R-IA10) — the app imports through
    ``POST /intake/import``. Kept for external callers, now on the ONE pipeline:
    a Claude export uploaded here is stamped ``claude-export`` (it read
    "Unattributed" on the Sources page before, R7 §1.2 defect 1), a zip is
    accepted, and a Gemini page reaches the Gemini parser instead of ChatGPT's
    scraper (defect 2). Synchronous by contract — its callers expect counts."""
    from api.routers import intake  # deferred: intake imports this module

    response.headers["Deprecation"] = "true"
    content = await file.read()
    logger.info(f"Upload (deprecated shim): {file.filename or ''} ({len(content)} bytes)")
    result = await run_in_threadpool(intake.import_bytes, content, file.filename or "", settings)
    return ConversationUploadResponse(
        status="success",
        episodes_created=result.created,
        episodes_updated=result.updated,
        duplicates_skipped=result.skipped,
        message=f"Staged {result.created} new, {result.updated} updated, {result.skipped} unchanged",
        source=intake.source_label(result.parsed),
    )


@router.get("/conversations/recent", response_model=list[ConversationSummary])
async def recent_conversations(
    request: Request,
    response: Response,
    limit: int = Query(20, ge=1, le=200),
    harness: str | None = Query(None, max_length=64),
    origin: str | None = Query(None, max_length=64),
    q: str | None = Query(None, max_length=200),
    settings: Settings = Depends(get_settings),
):
    """Conversations that wrote to memory, newest write first (G48).

    Live MCP sessions and imported chat threads on one axis. Only ids,
    timestamps, counts and entity ids cross the wire — never a transcript,
    never a transcript path, never ``project_dir``.

    ETag covers exactly what the rows are built from — ``episodes`` and
    ``entities``. KNOWN CAVEAT: deleting a transcript flips no version-vector
    component, so ``resumable`` can read stale until the next non-304 refresh —
    acceptable because ``POST /conversations/{id}/resume`` re-validates.

    This list is capped (``limit`` ≤ 200), so it is NOT a membership test for a
    bank: use ``GET /conversations/{id}`` to answer "does this bank know that
    conversation".

    ``harness`` / ``origin`` (G124 R5) narrow the list to one source BEFORE the
    cap, so the Sources page's per-harness view is complete up to ``limit``.
    Both fold into the ETag: they change the body without moving any component.

    ``q`` (G136) is a title filter, also applied BEFORE the cap and folded
    into the ETag the same way; whitespace-only is no filter. The ``|q=``
    part is appended only when a filter is present, so every existing
    client's ETag stays byte-identical. The query is never logged — it is
    the person's words (K9); ``api/main.py`` strips it from uvicorn's
    access log (G136 R22).
    """
    q = (q or "").strip() or None
    extra = f"limit={limit}|harness={harness or ''}|origin={origin or ''}"
    if q:
        extra += f"|q={q}"
    etag = sync_service.etag_for(settings.memory_path, "episodes", "entities", extra=extra)
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early

    rows = await run_in_threadpool(
        session_stats.aggregate_conversations,
        settings.memory_path,
        limit=limit,
        transcript_exists=transcript_exists,
        harness=harness,
        origin=origin,
        q=q,
    )
    return [ConversationSummary(**row) for row in rows]


@router.get("/conversations/{conversation_id}", response_model=ConversationSummary)
async def get_conversation(
    conversation_id: str,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    """One conversation by id — the exact-lookup twin of ``/recent`` (G48).

    ``/conversations/recent`` is a capped, recency-sorted page: a bank with
    more conversations than the cap will not contain an older one, and the app
    must never read that absence as "this bank forgot it". This route resolves
    the id against the WHOLE bank and 404s only when the bank genuinely has no
    episode carrying it.

    Same serialization as ``/recent`` (``session_stats.project_conversation``),
    same auth (bearer, like every route outside ``auth._OPEN_PATHS``), same
    privacy: no transcript, no transcript path, no ``project_dir``.
    """
    conversation_id = (conversation_id or "").strip()

    etag = sync_service.etag_for(
        settings.memory_path, "episodes", "entities", extra=f"id={conversation_id}"
    )
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early

    convo = await run_in_threadpool(
        session_stats.find_conversation, settings.memory_path, conversation_id
    )
    if convo is None:
        raise HTTPException(404, "unknown conversation")

    row = session_stats.project_conversation(convo, transcript_exists=transcript_exists)
    return ConversationSummary(**row)


@router.post("/conversations/{conversation_id}/resume", response_model=ResumeDescriptor)
async def resume_conversation(
    conversation_id: str,
    settings: Settings = Depends(get_settings),
):
    """Validate a conversation and hand the app a launch descriptor (G48 §5).

    400 — not a canonical session uuid (a minted ``ses_`` id lands here by
    construction). 404 — this bank has never seen that conversation, so there
    is no ``project_dir`` and therefore no transcript path to check. 409 —
    the transcript was retention-cleaned since the list was fetched.

    No transcript is opened. Nothing about the transcript beyond "it exists"
    influences the response.
    """
    conversation_id = (conversation_id or "").strip()
    if not session_stats.is_uuid(conversation_id):
        raise HTTPException(400, "not a resumable conversation id")

    convo = await run_in_threadpool(
        session_stats.find_conversation, settings.memory_path, conversation_id
    )
    if convo is None:
        raise HTTPException(404, "unknown conversation")

    project_dir = (convo.get("project_dir") or "").strip()
    if not transcript_exists(project_dir, conversation_id):
        raise HTTPException(409, {"reason": "transcript_gone"})

    cwd = None
    if (
        project_dir
        and (project_dir.startswith("/") or project_dir.startswith("~"))
        and CWD_SAFE_RE.match(project_dir)
        and Path(project_dir).expanduser().is_dir()
    ):
        cwd = project_dir

    return ResumeDescriptor(
        mode="terminal",
        argv=[CLAUDE_BINARY, "--resume", conversation_id],
        cwd=cwd,
        display_command=f"{CLAUDE_BINARY} --resume {conversation_id}",
    )


# --- Source Detection ---


def detect_source(data, filename: str = "") -> str:
    """Detect export source from JSON structure.

    Only a list whose first item is an object is an export: ``"key" in 1``
    raised TypeError (a stray ``[1, 2]`` 500'd a whole zip), and ``"key" in
    "a string"`` is a substring test that could misread a list of strings
    (Track I final review, finding 8)."""
    if not (isinstance(data, list) and data and isinstance(data[0], dict)):
        return "unknown"
    first = data[0]
    if "conversations_memory" in first:
        return "anthropic_memories"
    if "prompt_template" in first:
        return "anthropic_projects"
    if "chat_messages" in first and "uuid" in first:
        return "anthropic"
    if "mapping" in first:
        return "chatgpt"
    return "unknown"


# --- Anthropic / Claude Export ---


def parse_anthropic_conversations(data: list) -> list[dict]:
    """Parse Anthropic conversations.json export.

    Real format (verified April 2026):
    - Each conversation has uuid, name, created_at, updated_at, chat_messages[]
    - Each message has uuid, sender ("human"|"assistant"), text, content[], created_at
    - content[] has start_timestamp, stop_timestamp, type, text, citations
    - Timestamps are ISO 8601 with microseconds: "2026-02-24T12:39:02.701295Z"
    """
    episodes: list[dict] = []

    for conv in data:
        messages = conv.get("chat_messages", [])
        if not messages:
            continue

        # Sort messages by their created_at timestamp
        messages.sort(key=lambda m: m.get("created_at", ""))

        parsed_msgs: list[dict] = []
        for msg in messages:
            sender = msg.get("sender", "unknown")
            # Normalize sender: "human" -> "user", keep "assistant"
            role = "user" if sender == "human" else sender
            text = msg.get("text", "")
            if not text or not text.strip():
                # Fall back to content blocks
                for block in msg.get("content", []):
                    if block.get("type") == "text" and block.get("text"):
                        text = block["text"]
                        break
            if not text or not text.strip():
                continue

            parsed_msgs.append({
                "role": role,
                "text": text.strip(),
                "timestamp": msg.get("created_at"),
            })

        if not parsed_msgs:
            continue

        # Use the conversation's own created_at as the episode timestamp
        conv_timestamp = conv.get("created_at", parsed_msgs[0].get("timestamp"))

        episodes.append({
            "title": conv.get("name", "Untitled"),
            "source": "claude",
            "messages": parsed_msgs,
            "timestamp": conv_timestamp,
            # Preserve original date for chronological staging
            "original_date": _extract_date(conv_timestamp),
            # G20 delta re-import: stable per-thread identity so a re-export of a
            # grown conversation updates its episode in place instead of forking.
            "source_id": conv.get("uuid"),
            "source_updated_at": conv.get("updated_at"),
        })

    # Sort episodes chronologically so they're staged in order
    episodes.sort(key=lambda e: e.get("timestamp", ""))
    return episodes


def parse_anthropic_memories(data: list) -> list[dict]:
    """Parse Anthropic memories.json as a bootstrapping source.

    Contains Claude's existing memory about the user — free entity seed data.
    Structure: [{conversations_memory: str, project_memories: {uuid: str, ...}}]
    """
    episodes: list[dict] = []

    for entry in data:
        # G114 R2: the entry's own date when the export carries one (an
        # `updated_at`/`created_at` ISO string or epoch), so the episode is
        # backdated like every other import. `None` when it doesn't —
        # `_write_new_episode` then stamps `utc_now_iso()` at write time,
        # so a file never carries `timestamp: None`.
        entry_ts = _export_entry_timestamp(entry)
        entry_date = _extract_date(entry_ts)

        # Conversations memory — global context Claude has built
        conv_memory = entry.get("conversations_memory", "")
        if conv_memory.strip():
            episodes.append({
                "title": "Claude Memory — Conversation Context",
                "source": "claude_memory",
                "messages": [{"role": "system", "text": conv_memory, "timestamp": entry_ts}],
                "timestamp": entry_ts,
                "original_date": entry_date,
            })

        # Project memories — per-project context
        project_memories = entry.get("project_memories", {})
        if isinstance(project_memories, dict):
            for project_id, memory_text in project_memories.items():
                if memory_text and memory_text.strip():
                    episodes.append({
                        "title": f"Claude Memory — Project {project_id[:8]}",
                        "source": "claude_memory",
                        "messages": [{"role": "system", "text": memory_text, "timestamp": entry_ts}],
                        "timestamp": entry_ts,
                        "original_date": entry_date,
                    })

    return episodes


def _export_entry_timestamp(entry: dict) -> str | None:
    """Best-known date of an export entry as aware-UTC ISO, or ``None``.

    Checks the update stamp first (a memory's content is as of its last
    edit), then creation, in both the Anthropic (``*_at`` ISO string) and
    ChatGPT (``*_time`` epoch) spellings. Anything unparseable is ``None`` —
    never a guess — so the writer falls back to "now" honestly.
    """
    if not isinstance(entry, dict):
        return None
    for key in ("updated_at", "update_time", "created_at", "create_time"):
        value = entry.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return episode_ids.to_utc_iso(value)
        if isinstance(value, str) and value.strip():
            try:
                return episode_ids.to_utc_iso(datetime.fromisoformat(value.strip()))
            except ValueError:
                continue
    return None


def parse_anthropic_projects(data: list) -> list[dict]:
    """Parse Anthropic projects.json — project descriptions as knowledge episodes."""
    episodes: list[dict] = []

    for project in data:
        name = project.get("name", "")
        description = project.get("description", "") or ""
        prompt_template = project.get("prompt_template", "") or ""

        # Skip empty or default projects
        if not description.strip() or name == "How to use Claude":
            continue

        content_parts = [f"Project: {name}"]
        if description:
            content_parts.append(f"Description: {description}")
        if prompt_template:
            content_parts.append(f"Prompt template: {prompt_template}")

        content = "\n\n".join(content_parts)

        episodes.append({
            "title": f"Claude Project — {name}",
            "source": "claude_project",
            "messages": [{"role": "system", "text": content, "timestamp": project.get("created_at")}],
            "timestamp": project.get("created_at"),
            "original_date": _extract_date(project.get("created_at")),
        })

    return episodes


# --- ChatGPT Export ---


def parse_chatgpt_json(data: list) -> list[dict]:
    """Parse ChatGPT conversations.json export.

    Known format:
    - Each conversation has title, create_time (unix), mapping (tree of message nodes)
    - Each node has message.author.role, message.content.parts[], message.create_time
    """
    episodes: list[dict] = []

    for conversation in data:
        title = conversation.get("title", "Untitled")
        mapping = conversation.get("mapping", {})
        messages: list[dict] = []

        for node in mapping.values():
            msg = node.get("message")
            if not msg:
                continue
            parts = msg.get("content", {}).get("parts", [])
            if not parts:
                continue

            role = msg.get("author", {}).get("role", "unknown")
            text = "\n".join(str(p) for p in parts if isinstance(p, str))
            if not text.strip() or role not in ("user", "assistant"):
                continue

            create_time = msg.get("create_time")
            timestamp = None
            if isinstance(create_time, (int, float)) and create_time > 0:
                # G114 R2: epoch -> aware UTC. The old naive `fromtimestamp`
                # + a bare "Z" suffix rendered LOCAL time and labelled it
                # UTC, shifting every imported message by the machine's offset.
                timestamp = episode_ids.to_utc_iso(create_time)

            messages.append({"role": role, "text": text.strip(), "timestamp": timestamp})

        if not messages:
            continue

        messages.sort(key=lambda m: m.get("timestamp") or "")

        # Conversation-level timestamp
        conv_time = conversation.get("create_time")
        if isinstance(conv_time, (int, float)) and conv_time > 0:
            conv_timestamp = episode_ids.to_utc_iso(conv_time)
        else:
            conv_timestamp = messages[0].get("timestamp")

        # G20 delta re-import: stable per-thread identity. ChatGPT exports key on
        # conversation_id (or a bare id); update_time is a unix epoch float, so
        # render it with the same aware-UTC helper used for create_time above.
        source_id = conversation.get("conversation_id") or conversation.get("id")
        update_time = conversation.get("update_time")
        source_updated_at = None
        if isinstance(update_time, (int, float)) and update_time > 0:
            source_updated_at = episode_ids.to_utc_iso(update_time)

        episodes.append({
            "title": title,
            "source": "chatgpt",
            "messages": messages,
            "timestamp": conv_timestamp,
            "original_date": _extract_date(conv_timestamp),
            "source_id": source_id,
            "source_updated_at": source_updated_at,
        })

    episodes.sort(key=lambda e: e.get("timestamp", ""))
    return episodes


def _parse_chatgpt_html(html: str) -> list[dict]:
    """Parse ChatGPT HTML export. Fallback — less structured than JSON.

    Only ChatGPT's legacy export, whose threads sit in `div.conversation`
    blocks. The old `[soup]` fallback turned any page — a bookmarks file, the
    `chat.html` viewer — into role-less messages dated today (Track I D7); a
    page without those blocks is not a chat export.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    episodes: list[dict] = []

    conversations = soup.find_all("div", class_="conversation")
    if not conversations:
        return []

    for conv in conversations:
        messages: list[dict] = []
        for msg_div in conv.find_all(["div", "p"], recursive=True):
            text = msg_div.get_text(strip=True)
            if text and len(text) > 10:
                messages.append({"role": "unknown", "text": text, "timestamp": None})

        if messages:
            episodes.append({
                "title": "Imported conversation",
                "source": "chatgpt",
                "messages": messages,
                "timestamp": None,
                "original_date": None,
            })

    return episodes


# --- Gemini (Google Takeout MyActivity) Export ---


# Month-name -> number map for the Takeout activity timestamp format, which is
# locale-rendered (e.g. "Feb 24, 2026, 12:39:02 PM PST") rather than ISO.
_GEMINI_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_gemini_timestamp(raw: str) -> str | None:
    """Parse a Takeout MyActivity timestamp into aware-UTC ISO (G114 R2).

    Google renders these as ``"Feb 24, 2026, 12:39:02 PM PST"`` (note the
    narrow no-break space and trailing tz abbreviation). We only need date +
    wall-clock for backdating, so the tz abbreviation is dropped and the
    wall-clock is taken as UTC — the same reading the old ``+ "Z"`` suffix
    gave it, now in the one ``+00:00`` shape every writer emits. Returns
    ``None`` if the string can't be parsed (the episode then falls back to
    ``episode_ids.utc_now_iso()`` in staging).
    """
    if not raw:
        return None
    import re

    text = raw.replace(" ", " ").replace("\xa0", " ").strip()
    m = re.search(
        r"([A-Za-z]{3,})\s+(\d{1,2}),\s+(\d{4}),\s+(\d{1,2}):(\d{2}):(\d{2})\s*([AP]M)?",
        text,
    )
    if not m:
        return None
    mon_name, day, year, hh, mm, ss, ampm = m.groups()
    month = _GEMINI_MONTHS.get(mon_name[:3].lower())
    if not month:
        return None
    hour = int(hh)
    if ampm:
        ampm = ampm.upper()
        if ampm == "PM" and hour != 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
    try:
        dt = datetime(int(year), month, int(day), hour, int(mm), int(ss))
    except ValueError:
        return None
    return episode_ids.to_utc_iso(dt)


_GEMINI_VERB = re.compile(r"^(?:Prompted|Asked|Said)[\s\u00a0]+")
_GEMINI_TITLE_MAX = 60


def _gemini_title(prompt: str) -> str:
    first = prompt.split("\n", 1)[0].strip()
    if not first:
        return "Gemini activity"
    return first if len(first) <= _GEMINI_TITLE_MAX else first[: _GEMINI_TITLE_MAX - 1].rstrip() + "…"


def _gemini_legacy_hashes(legacy_text: str) -> list[str]:
    """The hashes a pre-Track-I Gemini episode can carry: its one ``user:``
    line hashed raw (every stager before G133), and hashed after the scrub
    (dev's ``episode_staging`` scrubs before it hashes, R-N3). Both, because a
    bank may hold either; one entry when no scrub rule fired."""
    if not legacy_text:
        return []
    raw = episode_staging.content_hash(f"user: {legacy_text}")
    scrubbed = episode_staging.content_hash(f"user: {episode_scrub.scrub(legacy_text)[0]}")
    return list(dict.fromkeys((raw, scrubbed)))


def parse_gemini_myactivity(html: str) -> list[dict]:
    """Parse a Google Takeout ``Gemini Apps/MyActivity.html`` export (Track I, R-IA9).

    One episode per activity cell. The first content cell reads
    ``Prompted <prompt>``, the activity's rendered timestamp, then Gemini's
    reply; the old parser kept all of it as ONE ``user`` message, so Gemini's
    words were credited to the person, and titled every entry "Gemini
    activity". Now the cell is split at its (last) timestamp line: the prompt
    — minus Google's own verb, which is not the person's words — is ``user``,
    what follows is ``assistant``, and the title is the prompt's first line.

    Each entry also carries ``legacy_hashes``: the ``content_hash`` values the
    old parser's body could have been stored under (see
    ``_gemini_legacy_hashes``). ``api/routers/intake.plan`` counts one already
    in the bank as unchanged, so a Takeout re-imported after this change
    duplicates nothing (``episode_staging.draft_from_export`` never carries
    the key into a file).
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    episodes: list[dict] = []

    cells = soup.find_all("div", class_="outer-cell")
    if not cells:
        # Fallback for snippets without the full Takeout chrome.
        cells = soup.find_all("div", class_="content-cell")

    for cell in cells:
        content = cell.find("div", class_="content-cell") or cell
        text = content.get_text(separator="\n", strip=True)
        if not text:
            continue
        lines = text.split("\n")
        ts: str | None = None
        at: int | None = None
        for i in range(len(lines) - 1, -1, -1):
            parsed = _parse_gemini_timestamp(lines[i])
            if parsed:
                ts, at = parsed, i
                break
        # Byte-for-byte what the pre-Track-I parser kept as the body.
        legacy_text = text.replace(lines[at], "").strip() if at is not None else text
        prompt_lines, reply_lines = (lines[:at], lines[at + 1:]) if at is not None else (lines, [])
        prompt = _GEMINI_VERB.sub("", "\n".join(prompt_lines).strip())
        reply = "\n".join(reply_lines).strip()
        if not prompt and not reply:
            continue
        messages = []
        if prompt:
            messages.append({"role": "user", "text": prompt, "timestamp": ts})
        if reply:
            messages.append({"role": "assistant", "text": reply, "timestamp": ts})
        episodes.append({
            "title": _gemini_title(prompt),
            "source": "gemini_export",
            "origin": "gemini-export",
            "messages": messages,
            "timestamp": ts,
            "original_date": _extract_date(ts),
            "legacy_hashes": _gemini_legacy_hashes(legacy_text),
        })

    episodes.sort(key=lambda e: e.get("timestamp") or "")
    return episodes


# --- ChatGPT export (stub) ---


def parse_chatgpt_export(data) -> list[dict]:
    """ChatGPT export entry point (origin=chatgpt-export).

    The real OpenAI export is the same ``conversations.json`` mapping-tree shape
    already handled by :func:`parse_chatgpt_json`; this thin wrapper stamps the
    ``origin`` for the banks-import contract and exists as the seam for the
    pending real export. Accepts the parsed JSON list.
    """
    episodes = parse_chatgpt_json(data if isinstance(data, list) else [])
    for ep in episodes:
        ep["origin"] = "chatgpt-export"
    return episodes


# --- Import dispatch (banks M7) ---


# Maps the parsed ``source`` (from detect_source / file extension) to the
# wire ``format`` field in the banks-import response.
_IMPORT_FORMAT = {
    "anthropic": "claude",
    "anthropic_memories": "claude_memories",
    "anthropic_projects": "claude_projects",
    "chatgpt": "chatgpt",
    "chatgpt_html": "chatgpt",
    "gemini": "gemini",
}


def parse_export_bytes(content: bytes, filename: str) -> tuple[list[dict], str]:
    """The old 2-tuple, kept for its callers (Track I T2, R-IA7). The one parser
    is ``api.routers.intake.parse_export`` — every zip member it knows, named
    skips, an origin on every path — and this returns its episodes and format.
    Deferred import: ``intake`` imports this module."""
    from api.routers import intake

    parsed = intake.parse_export(content, filename)
    return parsed.episodes, parsed.format


def _stamp_origin(episodes: list[dict], origin: str) -> list[dict]:
    """Tag each episode with an import-provenance ``origin`` (in place)."""
    for ep in episodes:
        ep["origin"] = origin
    return episodes


# --- Helpers ---


def _extract_date(timestamp: str | None) -> str | None:
    """Extract YYYY-MM-DD from an ISO timestamp string."""
    if not timestamp:
        return None
    return timestamp[:10]


# --- Staging (G20) — the service owns it now (R-F1 seam) ---------------------
#
# These four names stay because `api/routers/banks.py:28,232` and
# `api/tests/test_conversations.py` call them; each is a thin wrapper over
# `api.services.episode_staging`, so the chat importers stage exactly as before
# (and now scrub). Each message's own time rides beside the body as the G118
# slice-2 `turns: [{offset, ts, speaker}]` sidecar (R-PB4) — written by the
# stager now, outside `content_hash`; `episode_staging.MAX_TURN_STAMPS` is the
# cap that used to live here.


def _stage_episodes(episodes: list[dict], episodes_dir: Path) -> tuple[int, int, int]:
    drafts = [episode_staging.draft_from_export(e) for e in episodes]
    return episode_staging.stage(drafts, episodes_dir, bank=episodes_dir.parent.name).as_tuple()


def _normalise_import_timestamp(ts) -> str | None:
    return episode_staging.normalise_timestamp(ts)


def _write_new_episode(episode: dict, episodes_dir: Path, content_str: str, content_hash: str,
                       date_counts: dict[str, int]) -> Path:
    draft = episode_staging.draft_from_export(episode)
    return episode_staging.write_new(draft, episodes_dir, content_str, content_hash,
                                     episode_staging.stamps_for(draft, content_str), date_counts)


def _update_episode_in_place(path: Path, episode: dict, content_str: str, content_hash: str) -> None:
    draft = episode_staging.draft_from_export(episode)
    episode_staging.update_in_place(path, draft, content_str, content_hash,
                                    episode_staging.stamps_for(draft, content_str))
