"""Conversation-level provenance aggregation (G48) — "which conversation
produced this memory".

An ``origin_stats.py`` clone, one axis over: where that module groups episodes
by *capture origin* (mcp / telegram / claude-export), this one groups them by
*conversation* — the ``session_id`` an MCP client stamped at capture, or G20's
``source_id`` for an imported chat thread. Entities are credited transitively
through ``source_episodes``, exactly as in ``origin_stats.aggregate_origins``,
PLUS (PR #20 review fix) any entity whose in-page ``claims`` block carries a
claim stamped with a matching ``session_id`` — the durable trail a direct
``cicada_write_claim`` against an EXISTING entity leaves when it has no
source episode to record in frontmatter.

PRIVACY: transcripts are NEVER read. The only filesystem contact with
``~/.claude`` in this entire feature is the ``os.path.isfile`` inside
:func:`default_transcript_exists`. No transcript content, and no transcript
path, is returned, logged, or written to a bank.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from api.services import bank_index
from api.services.claims import parse_claims

# A Claude Code session id is a canonical UUID (`--session-id` requires one).
# Anything else — notably a minted `ses_YYYY-MM-DD_xxxxxxxx` id — can never
# reach a filesystem probe or a resume launch.
SESSION_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

# Cap on the entity ids carried by ONE conversation row. Mirrors
# ``git_service.MAX_COMMIT_ENTITIES``: the app renders a tappable chip per id,
# so an uncapped list is both a fat payload and a big layout pass. The honest
# count rides alongside as ``entity_count``, so the app says "+N more".
MAX_CONVERSATION_ENTITIES = 12


def is_uuid(value: str) -> bool:
    return bool(SESSION_UUID_RE.match((value or "").strip()))


def project_slug(project_dir: str) -> str:
    """Claude Code's transcript directory name for a project.

    Every non-alphanumeric character of the ABSOLUTE path becomes ``-``
    (verified for ``/``, ``_`` and ``.``).
    """
    return re.sub(r"[^A-Za-z0-9]", "-", project_dir or "")


def transcripts_root() -> Path:
    return Path.home() / ".claude" / "projects"


def default_transcript_exists(
    project_dir: str | None, session_id: str, *, root: Path | None = None
) -> bool:
    """True when a resumable transcript file exists for this session.

    ``os.path.isfile`` ONLY — never opened, never parsed. Top-level only: a
    ``<uuid>/subagents/`` directory is a subagent's transcript store, not a
    session, and ``isfile`` rejects a directory for free.
    """
    if not project_dir or not is_uuid(session_id):
        return False
    base = root if root is not None else transcripts_root()
    return os.path.isfile(base / project_slug(project_dir) / f"{session_id}.jsonl")


def _group(memory_path: Path) -> dict[str, dict]:
    """conversation id -> raw group state (INCLUDING project_dir)."""
    episodes_dir = memory_path / "episodes"
    if not episodes_dir.exists():
        return {}

    groups: dict[str, dict] = {}
    episode_conversation: dict[str, str] = {}

    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter
        session_id = str(fm.get("session_id") or "").strip()
        source_id = str(fm.get("source_id") or "").strip()
        conversation_id = session_id or source_id
        if not conversation_id:
            # Pre-G48 MCP episodes and every non-conversation capture
            # (bookmarks, RSS, media) simply don't appear. No backfill.
            continue

        episode_id = str(fm.get("id") or f.stem)
        episode_conversation[episode_id] = conversation_id

        group = groups.setdefault(
            conversation_id,
            {"conversation_id": conversation_id,
             "kind": "mcp" if session_id else "import",
             "entity_ids": set(),
             "episodes": []},
        )
        group["episodes"].append((str(fm.get("timestamp") or ""), episode_id, fm))

    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter
        entity_id = str(fm.get("id") or f.stem)
        entity_conversations: set[str] = set()
        for ep_id in fm.get("source_episodes", []) or []:
            conversation_id = episode_conversation.get(ep_id)
            if conversation_id:
                entity_conversations.add(conversation_id)
        # PR #20 review fix: a direct `cicada_write_claim` against an
        # EXISTING entity never touches this entity's frontmatter
        # `source_episodes` (only page CREATION does), so an episode-less
        # write would otherwise never connect this conversation to the
        # entity it changed. The claim itself carries the writing session
        # (Claim.session_id, stamped by agentic_write.write_claim) — credit
        # it here, but only to a conversation that already has an episode
        # group (never manufacture a phantom conversation row from a claim
        # alone).
        for claim in parse_claims(f.body()):
            sid = (claim.session_id or "").strip()
            if sid and sid in groups:
                entity_conversations.add(sid)
        for conversation_id in entity_conversations:
            groups[conversation_id]["entity_ids"].add(entity_id)

    for group in groups.values():
        # Sort by (timestamp, episode id) so an episode without a timestamp
        # still lands deterministically instead of by filesystem order.
        group["episodes"].sort(key=lambda e: (e[0], e[1]))
        first_ts, _first_id, first_fm = group["episodes"][0]
        last_ts, _last_id, last_fm = group["episodes"][-1]

        group["title"] = str(first_fm.get("title") or "") or "Untitled"
        group["first_seen"] = first_ts
        group["last_seen"] = last_ts
        group["episode_count"] = len(group["episodes"])
        group["origin"] = str(last_fm.get("origin") or "").strip()
        group["harness"] = next(
            (str(fm.get("harness") or "").strip()
             for _ts, _id, fm in group["episodes"] if str(fm.get("harness") or "").strip()),
            "",
        )
        group["project_dir"] = next(
            (str(fm.get("project_dir") or "").strip()
             for _ts, _id, fm in group["episodes"] if str(fm.get("project_dir") or "").strip()),
            None,
        )
        del group["episodes"]

    return groups


def project_conversation(group: dict, *, transcript_exists) -> dict:
    """One group -> the public row. ``project_dir`` is deliberately dropped.

    Shared by ``aggregate_conversations`` (the list) and
    ``GET /conversations/{id}`` (the by-id lookup), so both serialise a
    conversation exactly the same way.
    """
    entity_ids = sorted(group["entity_ids"])
    return {
        "conversation_id": group["conversation_id"],
        "kind": group["kind"],
        "harness": group["harness"],
        "origin": group["origin"],
        "title": group["title"],
        "first_seen": group["first_seen"],
        "last_seen": group["last_seen"],
        "episode_count": group["episode_count"],
        "entity_ids": entity_ids[:MAX_CONVERSATION_ENTITIES],
        "entity_count": len(entity_ids),
        # RESERVED, always None in this slice. Nothing that writes memory
        # records a model against a conversation id: the only producer of a
        # ``session_id`` telemetry ref (MCP ``agentic_write``) has no model to
        # record, so any ledger join here would be a guaranteed-empty scan of
        # the whole ledger on every request. The field stays on the wire so the
        # app keeps decoding unchanged once engine calls carry session refs
        # (G49).
        "model": None,
        # Computed per request, NEVER cached or persisted: transcripts get
        # retention-cleaned behind our back.
        "resumable": bool(
            transcript_exists(group.get("project_dir"), group["conversation_id"])
        ),
    }


def aggregate_conversations(
    memory_path: Path,
    *,
    limit: int = 20,
    transcript_exists=default_transcript_exists,
) -> list[dict]:
    """Recent conversations, newest write first.

    Returns snake_case dicts matching ``schemas.ConversationSummary``'s field
    names (``CamelModel`` has ``populate_by_name=True``, so
    ``ConversationSummary(**row)`` just works). ``project_dir`` is NOT included
    — only the resume endpoint ever sees it.
    """
    groups = _group(Path(memory_path))
    rows = [
        project_conversation(g, transcript_exists=transcript_exists)
        for g in groups.values()
    ]
    rows.sort(key=lambda r: (r["last_seen"], r["conversation_id"]), reverse=True)
    return rows[: max(1, int(limit or 20))]


def find_conversation(memory_path: Path, conversation_id: str) -> dict | None:
    """One conversation's raw group, INCLUDING ``project_dir``. ``None`` if unknown."""
    group = _group(Path(memory_path)).get((conversation_id or "").strip())
    if group is None:
        return None
    return dict(group)
