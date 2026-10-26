"""What a remote connector is allowed to be (G135): apps, scopes, tools.

SDK-free and bank-free on purpose — the store, the runtime, the schemas, the
management router and the app all read these tables, and none of them should
have to import an HTTP stack to learn a scope name.

Scopes fail closed (R-R3): a connector holds a subset of ``SCOPES``; an
unknown string in a stored row is dropped, never granted, and an empty set
reaches no tool at all — not even ``cicada_handshake``. Three stdio tools are
never remote and have no entry here: ``cicada_pending`` and
``cicada_mark_processed`` (flipping ``processed: true`` hides an episode from
Sleep — an effective soft delete) and ``cicada_repo_context`` (it runs ``git``
against any path the caller names).

The app list is pinned against the Swift side by
``api/tests/fixtures/remote_catalog.json`` (the Track V pattern): add an app on
one side only and the other side's test goes red. Harness labels (R-R26) are
what the app's episodes, commits and Sources card carry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

SCOPES = ("search", "read", "record", "sources", "answer", "ask")
DEFAULT_SCOPES = frozenset({"search", "read", "record"})

TOOL_SCOPE: dict[str, str | None] = {
    "cicada_handshake": None,
    "cicada_recall": "search",
    "cicada_open_hub": "search",
    "cicada_recall_detail": "read",
    "cicada_get_perspective": "read",
    "cicada_check_nudges": "read",
    "cicada_timeline": "read",
    "cicada_project": "read",
    "cicada_backlog": "read",   # G150 R-B13
    "cicada_video_queue": "read",   # G162: the person's own hand-off; read-only, takes no lease
    "cicada_reading_queue": "read",   # G166: the asks the person made; the URL is their own hand-off
    "cicada_save_episode": "record",
    "cicada_write_claim": "record",
    "cicada_retract_claim": "record",
    "cicada_add_source": "record",
    "cicada_change_source": "record",   # G61 S3-a: only an entry this connection added
    "cicada_save_url": "record",
    "cicada_record_watch": "record",
    "cicada_video_claim": "record",   # G162: leases queued videos; touches only the queue file
    "cicada_record_check": "record",   # G61 S3: a report on a listed source; settles nothing
    "cicada_record_read": "record",   # G166: what an agent's browser read; never the person's words
    "cicada_note_progress": "record",   # G141 R-PJ23: a write, never the person's own words
    "cicada_add_backlog_item": "record",
    "cicada_add_backlog_note": "record",   # G150: the harness writes, never the person
    # Ruling 32 (owner 2026-10-19): a hookless app (claude.ai, ChatGPT, their phone apps) relays each turn.
    # Remote only: a stdio harness is captured by its own hook (G105), never by a model's call.
    "cicada_capture_turns": "record",
    "cicada_sources": "sources",
    "cicada_resolve_inbox": "answer",
    "cicada_ask": "ask",
}
# G110 slice 1a: `cicada_continue` reads the person's verbatim words for a folder
# the caller names; slice 4 (G135) decides whether and under which scope it goes remote.
# Design taste (2026-10-14): the two board tools are stdio-only in their first slice — `image_path` reads a file the
# local agent saved, and which scope a remote picture belongs under is the owner's open question.
# G198: page edits are stdio and command line only in their first slice — the trust list names local harnesses, and
# whether a remote app may ever edit a page is the owner's open question.
NEVER_REMOTE = frozenset({"cicada_pending", "cicada_mark_processed", "cicada_repo_context", "cicada_continue",
                          "cicada_save_design", "cicada_design_search", "cicada_edit_page",
                          # G166 exploring (2026-10-14): stdio only in slice 1 — the record reads image files the agent
                          # saved, and a run starts only from the person in a local conversation (D5: never remote).
                          "cicada_explore_queue", "cicada_explore_claim", "cicada_record_capture",
                          "cicada_explore_start", "cicada_site_map",
                          # G61, ruling 26: a tracked source's re-check reads in the person's own browser session —
                          # a local agent's job; a remote one is the owner's open question.
                          "cicada_refresh_claim", "cicada_record_refresh",
                          # G71 (2026-10-16): the person's YouTube lists, read in their own browser session by a local
                          # agent — the same seat as a tracked source's re-check.
                          "cicada_record_youtube_list",
                          # G206 (2026-10-22): the person's saved lists on X, Instagram and LinkedIn — the same seat.
                          "cicada_record_saved_list",
                          # 2026-10-16: one person's LinkedIn profile, read in the person's own browser session by a
                          # local agent the person asked — the same seat.
                          "cicada_record_profile",
                          # The Skills page (2026-10-15): skills live in this Mac's agent folders, and a remote app is
                          # no coding agent here; whether one may ever ask for a skill is the owner's open question.
                          "cicada_skills", "cicada_propose_skill", "cicada_create_skill"})
#: Tools only the remote connector serves — a stdio harness has a hook for what they do.
REMOTE_ONLY = frozenset({"cicada_capture_turns"})
WRITE_TOOLS = frozenset({"cicada_save_episode", "cicada_capture_turns", "cicada_write_claim", "cicada_retract_claim",
                         "cicada_save_url", "cicada_record_watch", "cicada_record_read", "cicada_record_check", "cicada_add_source",
                         "cicada_change_source",
                         "cicada_note_progress", "cicada_add_backlog_item", "cicada_add_backlog_note",
                         "cicada_video_claim"})
READ_TOOLS = frozenset({"cicada_recall", "cicada_open_hub", "cicada_recall_detail", "cicada_get_perspective",
                        "cicada_check_nudges", "cicada_timeline", "cicada_project", "cicada_sources",
                        "cicada_ask", "cicada_backlog", "cicada_reading_queue", "cicada_video_queue"})

TOKEN_RE = re.compile(r"^cic_rc_([a-z0-9]{8})_([A-Za-z0-9_-]{43})$")
#: G213: an agent token — a connector row made for an agent that speaks HTTP, not MCP (`auth == "api"`). It opens the
#: `/v1` agent API only (on the backend's port and on this listener), never `/mcp`; the same scopes, expiry and revoke.
API_TOKEN_RE = re.compile(r"^cic_api_([a-z0-9]{8})_([A-Za-z0-9_-]{43})$")
#: What every agent token's episodes stamp as `harness` (an enum, so the telemetry rule holds); the agent's own name
#: rides as `Cicada-Author: api:<name>` (`Connector.author`).
API_HARNESS = "agent-api"
API_AUTHOR_PREFIX = "api:"
PRM_PATH = "/.well-known/oauth-protected-resource"
DEFAULT_PORT = 8765
EXPIRY_CHOICES = (7, 30, 90)


@dataclass(frozen=True)
class RemoteApp:
    id: str
    label: str
    harness: str
    delivery: str  # "link" | "header" | "both"


APPS: dict[str, RemoteApp] = {a.id: a for a in (
    RemoteApp("claude", "Claude", "claude-web", "link"),
    RemoteApp("chatgpt", "ChatGPT", "chatgpt", "link"),
    RemoteApp("perplexity", "Perplexity", "perplexity", "link"),
    # Round 4 C8 (R-AG7): Grok runs on xAI's servers, so the connector is its only
    # way to this Mac, and it registers a server from a chat message — a link.
    RemoteApp("grok", "Grok", "grok", "link"),
    RemoteApp("claude-code", "Claude Code", "claude-code-remote", "header"),
    RemoteApp("codex", "Codex", "codex-remote", "header"),
    RemoteApp("cursor", "Cursor", "cursor", "header"),
    RemoteApp("vscode", "GitHub Copilot", "vscode", "header"),   # in VS Code (owner, 2026-10-26)
    RemoteApp("gemini-cli", "Gemini CLI", "gemini-cli", "header"),
    RemoteApp("other", "Other app", "remote-app", "both"),
)}


def clean_scopes(raw) -> frozenset[str]:
    return frozenset(s for s in (raw or ()) if s in SCOPES)


def tool_names_for(scopes) -> frozenset[str]:
    held = clean_scopes(scopes)
    if not held:
        return frozenset()
    return frozenset(tool for tool, scope in TOOL_SCOPE.items() if scope is None or scope in held)


@dataclass(frozen=True)
class Connector:
    """One connector row — ids, enums and timestamps; ``label`` is the one
    owner-typed field (R-R30). Never carries the token or its hash."""

    id: str
    label: str
    app: str
    scopes: frozenset[str]
    created_at: str
    expires_at: str | None = None
    revoked_at: str | None = None
    last_used_at: str | None = None
    last_client: str | None = None
    use_count: int = 0
    #: How the app holds it: ``link`` (a shown-once ``cic_rc_`` secret) or ``oauth`` (ruling 32: the app signed
    #: in through Cicada's authorization server and holds short-lived access and rotating refresh tokens), or ``api``
    #: (G213: a shown-once ``cic_api_`` secret for an agent that speaks HTTP; it opens `/v1` only).
    auth: str = "link"

    @property
    def harness(self) -> str:
        if self.auth == "api":
            return API_HARNESS
        return (APPS.get(self.app) or APPS["other"]).harness

    @property
    def author(self) -> str | None:
        """G213: an agent token's ``Cicada-Author`` — ``api:`` and the agent's name as the person typed it, reduced to
        ``[a-z0-9-]`` (at most 32), so a commit says which agent wrote it. ``None`` for every other connector: its
        author is its harness, as before."""
        if self.auth != "api":
            return None
        slug = re.sub(r"[^a-z0-9]+", "-", self.label.casefold()).strip("-")[:32].strip("-")
        return API_AUTHOR_PREFIX + (slug or "agent")

    def state(self, now: datetime | None = None) -> str:
        if self.revoked_at:
            return "revoked"
        if self.expires_at:
            try:
                expires = datetime.fromisoformat(self.expires_at)
            except ValueError:
                return "expired"  # an unreadable expiry fails closed
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= (now or datetime.now(timezone.utc)):
                return "expired"
        return "active"
