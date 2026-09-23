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
    "cicada_save_episode": "record",
    "cicada_write_claim": "record",
    "cicada_retract_claim": "record",
    "cicada_add_source": "record",
    "cicada_save_url": "record",
    "cicada_record_watch": "record",
    "cicada_sources": "sources",
    "cicada_resolve_inbox": "answer",
    "cicada_ask": "ask",
}
NEVER_REMOTE = frozenset({"cicada_pending", "cicada_mark_processed", "cicada_repo_context"})
WRITE_TOOLS = frozenset({"cicada_save_episode", "cicada_write_claim", "cicada_retract_claim",
                         "cicada_save_url", "cicada_record_watch", "cicada_add_source"})
READ_TOOLS = frozenset({"cicada_recall", "cicada_open_hub", "cicada_recall_detail", "cicada_get_perspective",
                        "cicada_check_nudges", "cicada_timeline", "cicada_sources", "cicada_ask"})

TOKEN_RE = re.compile(r"^cic_rc_([a-z0-9]{8})_([A-Za-z0-9_-]{43})$")
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
    RemoteApp("claude-code", "Claude Code", "claude-code-remote", "header"),
    RemoteApp("codex", "Codex", "codex-remote", "header"),
    RemoteApp("cursor", "Cursor", "cursor", "header"),
    RemoteApp("vscode", "VS Code", "vscode", "header"),
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

    @property
    def harness(self) -> str:
        return (APPS.get(self.app) or APPS["other"]).harness

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
