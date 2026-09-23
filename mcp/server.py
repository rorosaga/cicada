"""Cicada MCP Server — Bookworm tool for LLM-memory integration.

Registers as an MCP server that any compatible client (Claude Desktop, Claude Code,
Cursor) can connect to. Provides tools for:
1. Querying the knowledge graph
2. Capturing episodes from conversations
3. Checking pending nudges/clarifications
"""

import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Allow importing sibling packages (api.services.vector_index) when run as a script
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Hoisted to module level (not lazy-local like most api.services imports below)
# so tests can monkeypatch `server.agentic_write.write_claim`. Since G135 R-R2
# the body that calls it is `mcp_tools.write_claim`, but `server.agentic_write`
# IS the module object `mcp_tools` calls through, so a patch of its attribute
# still lands. The same holds for the two below.
from api.services import agentic_write  # noqa: E402,F401
# G135 R-R11: a claim write commits its own page under the harness that wrote
# it. Hoisted beside `agentic_write` for the same reason (patchable here).
from api.services import agent_commits  # noqa: E402,F401
# Pure filesystem + datetime, no bank/config state — safe to hoist alongside.
from api.services import episode_ids  # noqa: E402,F401
# Track P R8/R9 — the legacy observer value is protocol and must stay in the
# `cicada_write_claim` schema (CLAUDE.md R12: a description naming an argument
# the schema would reject is a bug), but it is a person's name, the repo is
# public and the install is portable. Imported from its one documented home
# rather than retyped, so `mcp/` holds no name literal of its own.
from api.services.owner_identity import LEGACY_OBSERVER  # noqa: E402

# G140 Q-R11: one pattern, not an enum — JSON Schema ANDs an `enum` with a
# `pattern`, and the librarian skill's `external:<name>` (a named third party)
# must be a value the schema accepts (R5 §2 defect 4, G75 R12). The legacy
# value stays accepted and unadvertised (Track P R8), imported, never typed.
OBSERVER_PATTERN = (
    rf"^(owner|agent|external|{re.escape(LEGACY_OBSERVER)}|external:[a-z0-9][a-z0-9-]{{0,63}})$"
)

# G135 R-R2: every remote-capable tool body lives in `api/services/mcp_tools.py`.
from api.services import mcp_tools  # noqa: E402
# Re-exported for callers that CALL them (tests, back-compat). Tests that PATCH
# a moved helper patch it on `mcp_tools`, where the bodies look it up.
from api.services.mcp_tools import (  # noqa: E402,F401
    _entity_id_for_name,
    _relevant_inbox,
    _rrf_fuse,
    render_question,
)

# MCP protocol uses JSON-RPC 2.0 over stdin/stdout

# --- G48: conversation identity ---------------------------------------------
#
# stdio MCP is ONE process per client conversation, so a single module-level
# identity resolved at import time IS the conversation id. Ranked by
# reliability (see the G48 spec, "Session-id capture at the MCP seam"):
#
#   1. CLAUDE_CODE_SESSION_ID (+ CLAUDE_PROJECT_DIR) — undocumented but
#      verified on Claude Code v2.1.251: injected per-child at spawn, matches
#      the actively-written transcript, survives `--resume`. Gated on the
#      strict UUID regex so a future non-uuid value can never reach the
#      resume path.
#   2. CICADA_SESSION_ID — explicit override for any MCP client; doubles as a
#      manual re-attach handle. CICADA_SESSION_HARNESS names the harness.
#   3. A minted `ses_YYYY-MM-DD_<uuid4hex[:8]>` — still groups this
#      conversation's episodes; simply never resumable.
#
# NOTHING here reads a transcript. The only filesystem contact anywhere in
# this feature is an isfile() check, and it lives in main(), not here.

SESSION_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


@dataclass(frozen=True)
class SessionIdentity:
    session_id: str
    harness: str
    project_dir: str | None = None


def resolve_session_identity(env: dict | None = None) -> SessionIdentity:
    """Resolve this process's conversation identity. Pure — pass ``env`` in tests."""
    env = os.environ if env is None else env

    claude_id = (env.get("CLAUDE_CODE_SESSION_ID") or "").strip()
    if SESSION_UUID_RE.match(claude_id):
        return SessionIdentity(
            session_id=claude_id,
            harness="claude-code",
            project_dir=(env.get("CLAUDE_PROJECT_DIR") or "").strip() or None,
        )

    explicit = (env.get("CICADA_SESSION_ID") or "").strip()
    if explicit:
        return SessionIdentity(
            session_id=explicit,
            harness=(env.get("CICADA_SESSION_HARNESS") or "").strip() or "unknown",
            project_dir=(env.get("CLAUDE_PROJECT_DIR") or "").strip() or None,
        )

    return SessionIdentity(
        session_id=f"ses_{date.today().isoformat()}_{uuid.uuid4().hex[:8]}",
        harness="unknown",
        project_dir=None,
    )


SESSION = resolve_session_identity()

# Filled in by the `initialize` handler from the client's own `clientInfo`
# (name/version only — the MCP protocol carries nothing else there).
CLIENT_INFO: dict = {}

# G53/G75 (R13): recall's `cicada-hints` carries the now-view ONCE per
# process — stdio MCP is one process per conversation (G48), so a module
# flag IS "once per conversation", the same shape G115's ask gate uses.
# Flipped only when a hints block that carried the cursor was actually
# emitted: `_hints_block` returns "" when there is nothing to suggest, and
# an unsent cursor is not consumed.
_STATE_HINT_SENT: bool = False
# G75 contract item 2, `skip=true`: inbox ids the agent declined to ask this
# session. In-process and never persisted — a skip is not the person's
# verdict, so it must not become a write (the backend's `action: skip` IS a
# resolution and is not this). Cleared when the MCP process restarts, which
# is what "that session" means for a stdio server.
_SKIPPED_INBOX_IDS: set[str] = set()


def _session_frontmatter() -> dict:
    """The session keys to merge into an episode's frontmatter.

    Additive and inert: origin_stats ignores unknown keys, import re-staging
    (`_stage_episodes` / `_update_episode_in_place`) preserves them, and
    markdown_parser round-trips them.
    """
    return _ctx().session_frontmatter()


def _warn_if_transcript_missing() -> None:
    """Warn (never drop) when a claude-code session has no transcript on disk.

    isfile() ONLY — the transcript is never opened, and its path is never
    printed, logged, or persisted. stderr, so the JSON-RPC stream on stdout
    stays clean.
    """
    if SESSION.harness != "claude-code" or not SESSION.project_dir:
        return
    slug = re.sub(r"[^A-Za-z0-9]", "-", SESSION.project_dir)
    path = Path.home() / ".claude" / "projects" / slug / f"{SESSION.session_id}.jsonl"
    if not path.is_file():
        print(
            f"cicada-mcp: no transcript found for session {SESSION.session_id} — "
            "episodes still group by conversation, but Resume may not work",
            file=sys.stderr,
        )


# Tool list advertised via `tools/list` and dispatched via `tools/call`. Kept at
# module scope (not local to main()) so both main() and other modules (e.g. a
# future cicada_sources tool, and tests like test_mcp_tool_descriptions.py) can
# reference the same TOOLS constant without re-running the JSON-RPC loop.
TOOLS = [
    {
        "name": "cicada_recall",
        "description": "Search Cicada's knowledge graph for entities related to a topic. Returns concise summaries (Pass 1). Pending inbox items are surfaced first when relevant. Use this at the start of conversations to check what Cicada already knows about the topic being discussed. If a fact might exist, call cicada_recall_detail on the top suggested entity before concluding it is absent. State only facts present in tool results; do not add adjacent details from general knowledge.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The topic, person, project, or concept to search for",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "cicada_recall_detail",
        "description": "Return the FULL entity page for a specific entity. Use this as Pass 2 after cicada_recall when you need the complete description and history — not a summary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The entity ID (e.g. 'alpha-project') or entity name from a cicada_recall result.",
                }
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "cicada_save_episode",
        "description": "Save a conversation snippet as an episode for Cicada's memory. The episode will be processed during the next Sleep cycle to extract entities and relationships. Use this when the conversation contains important information worth remembering.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The conversation content to save as an episode",
                },
                "title": {
                    "type": "string",
                    "description": "A short title for this episode",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "cicada_check_nudges",
        "description": "Check for pending inbox items in Cicada's memory system. Returns items that need user attention — decaying entities, conflicts, ambiguous mentions, or possible duplicates. Use this proactively when a conversation touches topics that might have pending items. After `cicada_recall`, pass its suggested entity ids as `entity_ids`.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Optional topic to filter inbox items by relevance",
                },
                "entity_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional entity ids (the `suggested_entities` from cicada_recall's hints) — only items whose entity_id is in this list are returned. Combine with topic freely.",
                },
            },
        },
    },
    {
        "name": "cicada_open_hub",
        "description": "Open a Cicada hub page (a topic or type index) and list its member entities with one-line summaries. Use after cicada_recall returns a relevant_hub, or to browse a topic. Pass a hub id like 'people', 'tools', or 'topic-robotics'.",
        "inputSchema": {
            "type": "object",
            "properties": {"hub": {"type": "string"}},
            "required": ["hub"],
        },
    },
    {
        "name": "cicada_ask",
        "description": "Ask Cicada's memory a natural-language question and get a synthesized answer that CITES the entities it used and explicitly states what it could NOT answer (gaps). Grounded only in stored memory — it says 'I don't know' rather than guessing. Use when you want a direct answer rather than a list of entities to read yourself. Prefer this tool for direct factual questions — it reads full entity pages and claims and returns an answer with citations and an explicit gap list.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The natural-language question to ask of memory.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "How many entities to retrieve as grounding context (default 6).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "cicada_get_perspective",
        "description": "Return a subject's currently-valid claims from a specific PERSPECTIVE — optionally filtered by observer (who holds the belief: 'agent', 'owner', or 'external:<name>') and/or context (e.g. 'engineering', 'family', 'career'). Use when you need to know who believes what about a subject, or want only one facet of it (e.g. the engineering facet of the owner vs the family facet). Each claim carries its observer, context, source_trust, confidence, and valid-from date so you can attribute beliefs honestly.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "The subject entity id or name (e.g. 'owner', 'cicada').",
                },
                "observer": {
                    "type": "string",
                    "description": "Optional. Filter to one observer: 'agent', 'owner', or 'external:<name>'.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional. Filter to one context facet (e.g. 'engineering', 'family', 'career').",
                },
                "history": {
                    "type": "boolean",
                    "description": "Optional. Also list the subject's earlier claims — replaced, withdrawn or ended — newest first, with when each stopped being current. Default false.",
                },
            },
            "required": ["subject"],
        },
    },
    {
        "name": "cicada_save_url",
        "description": "Save a URL (article, video, bookmark) into Cicada's memory as saved media. The link becomes a graph entity and connects to related topics after the next Sleep cycle. Use when the user shares a link worth remembering or says 'save this'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to save"},
                "note": {
                    "type": "string",
                    "description": "Optional note about why this was saved",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "cicada_record_watch",
        "description": "After you watch a video the person saved (with your own video tools — Cicada never downloads or watches one), record what it covers: a short summary and up to 12 short quotes with the time each is said. Cicada keeps one episode and a 'describes' claim on the video's page whose evidence points at your summary and at each quote, marked as the video's words — never the person's. Cite ≤240-character excerpts; never paste the transcript. A link that is not saved yet is saved first. The reply names the episode, to cite from cicada_write_claim.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The video's link as saved (http(s)://, or file:// for a local recording the app added)."},
                "summary": {"type": "string", "description": "Your faithful account of what the video covers, one paragraph (at most 1,500 characters)."},
                "excerpts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "t": {"type": "string", "description": "When it is said: m:ss or h:mm:ss (e.g. '12:34'), or whole seconds."},
                            "quote": {"type": "string", "description": "The words the video says, verbatim (at most 240 characters)."},
                        },
                        "required": ["t", "quote"],
                    },
                    "description": "Optional. Up to 12 short timestamped quotes — the video's own words.",
                },
                "chapters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"t": {"type": "string"}, "title": {"type": "string"}},
                        "required": ["t", "title"],
                    },
                    "description": "Optional. The video's chapters as {t, title}; stored only when the page has none.",
                },
            },
            "required": ["url", "summary"],
        },
    },
    {
        "name": "cicada_sources",
        "description": "Return the primary source conversation chunks that produced an entity "
                       "(the episodes it was consolidated from). Use this to ground or verify a "
                       "fact against what the user actually said, or to show provenance.",
        "inputSchema": {
            "type": "object",
            "properties": {"entity_id": {"type": "string",
                "description": "The entity id (e.g. 'bob-example') to fetch sources for."}},
            "required": ["entity_id"],
        },
    },
    {
        "name": "cicada_write_claim",
        "description": "Write ONE atomic fact into Cicada's memory as a structured, observer-tagged claim (subject-predicate-object), reusing the same trust-gated reconciliation the nightly Sleep cycle uses. Tag observer='owner' ONLY for something the USER explicitly stated themselves — this claim becomes trust-protected and can never be silently overwritten by a later agent claim. Tag observer='agent' for something YOU inferred, deduced, or noticed yourself. Tag observer='external' for a fact attributed to a third party. Write ONE claim per atomic fact — never bundle multiple facts into a single call. If the subject has no entity page yet, a minimal one is created automatically. A lower-trust claim never overwrites a higher-trust one; it either coexists (flagged) or is held back for a nudge.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "The entity the claim is about (e.g. 'the owner', 'Cicada').",
                },
                "predicate": {
                    "type": "string",
                    "description": "The relation/verb (e.g. 'works-at', 'prefers', 'uses').",
                },
                "object": {
                    "type": "string",
                    "description": "The value or target entity of the claim (e.g. 'alpha-project', 'concise summaries').",
                },
                "observer": {
                    "type": "string",
                    # The legacy observer value stays in the PATTERN (not just
                    # in the prose) so the schema itself keeps the
                    # compatibility promise — CLAUDE.md R12: a primer or
                    # schema naming an argument the schema itself would
                    # reject is a bug. `agentic_write.write_claim` already
                    # normalizes it to the resolved owner id (G117).
                    #
                    # Track P R8/R9 — imported from
                    # `owner_identity.LEGACY_OBSERVER` rather than retyped, so
                    # `mcp/` holds no person's name of its own (the repo is
                    # public, the install is portable), and it is NOT
                    # interpolated from a resolved owner: `TOOLS` is a module
                    # constant built at import, before any bank is known, and
                    # a tool description must not vary per bank (one prose
                    # source, G75 R12). It stops being ADVERTISED here — an
                    # agent should send 'owner'; the pattern keeps accepting
                    # the legacy value for old callers, and naming it only
                    # invites new ones. G140 Q-R11: `OBSERVER_PATTERN` above.
                    "pattern": OBSERVER_PATTERN,
                    "description": "Who holds this belief. 'owner' = the user stated this themselves (trust-protected). 'agent' = you inferred/extracted this. 'external' = attributed to a third party — or 'external:<name>' (lowercase letters, digits, hyphens) to name them. Defaults to 'agent'.",
                },
                "confidence": {
                    "type": "number",
                    "description": "Optional confidence 0.0-1.0 (default 0.7).",
                },
                "context": {
                    "type": "string",
                    "description": "Optional facet this claim belongs to (e.g. 'engineering', 'family', 'career'). Default 'general'.",
                },
                "source_episode": {
                    "type": "string",
                    "description": "Optional episode id this claim was grounded in (e.g. from cicada_save_episode or cicada_pending).",
                },
                "force_new_entity": {
                    "type": "boolean",
                    "description": "Only set true after an 'ambiguous subject' response, when none of the suggested near-match entities is the intended subject — creates a genuinely new entity page despite the near-matches. Default false.",
                },
                "sources": {
                    "type": "array",
                    "items": {"anyOf": [
                        {"type": "string"},
                        {"type": "object",
                         "properties": {
                             "ref": {"type": "string", "description": "A URL, a file path, or plain words."},
                             "access": {"type": "string", "enum": ["public", "signed_in", "local", "unknown"],
                                        "description": "Optional: 'public' when anyone can open it, 'signed_in' when it needs the person's login."},
                         },
                         "required": ["ref"]},
                    ]},
                    "description": "Optional 'where to check this fact' references the user gave you — a URL, a file path, or a plain-English instruction ('ask me, I announce job changes'); a plain string, or {ref, access} when you know whether it needs a login. Stored on the subject's entity page, attributed to you.",
                },
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "episode": {
                                "type": "string",
                                "description": "The episode the words are in — the id cicada_save_episode returned, or one listed by cicada_pending.",
                            },
                            "quote": {
                                "type": "string",
                                "description": "The exact words, copied verbatim from that episode (at most 240 characters). Never a paraphrase.",
                            },
                        },
                        "required": ["episode", "quote"],
                    },
                    "description": "Optional. WHERE this fact comes from: the passage(s) in a saved episode that state it. Cicada verifies each quote against the stored episode and records only its offsets (G118 — spans, not copies). Omit it when the claim is your own inference: it is then recorded as reasoning, never as an invented span. If you saved the conversation with cicada_save_episode, cite that episode.",
                },
                # G140 Q-R6: a stated end, never a future `valid_to` —
                # `claim_expiry` closes the claim on Sleep's tail after it.
                "expected_end": {
                    "type": "string",
                    "description": "Optional. The date this fact stops being true, when the person stated one — 'exams this weekend' → that Sunday, 'until Friday', a due date — as YYYY-MM-DD. The claim stays current through that day; Sleep closes it after. Nothing is deleted.",
                },
            },
            "required": ["subject", "predicate", "object"],
        },
    },
    {
        "name": "cicada_retract_claim",
        "description": "Withdraw ONE claim you wrote earlier with cicada_write_claim that turned out to be wrong — for example the person says 'that's not right' about something you recorded. Nothing is deleted: the claim stops being current, stays in its page's history, and a record keeps your reason (and, when you cite them, the person's exact words). You can only withdraw a claim this agent wrote — never one the person stated, one Sleep extracted, or another agent's; for those, record the correction as a new claim with cicada_write_claim.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "The entity the claim is on (the `entity` cicada_write_claim returned)."},
                "claim_id": {"type": "string", "description": "The claim id cicada_write_claim returned (e.g. 'clm_alpha-project_uses_38309bd1')."},
                "reason": {"type": "string", "description": "Why it is wrong, in one sentence (at most 240 characters)."},
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "episode": {"type": "string", "description": "The episode the words are in."},
                            "quote": {"type": "string", "description": "The exact words, copied verbatim (at most 240 characters)."},
                        },
                        "required": ["episode", "quote"],
                    },
                    "description": "Optional. The person's exact words showing it is wrong, from a saved episode — verified and stored as offsets, never copied.",
                },
            },
            "required": ["subject", "claim_id", "reason"],
        },
    },
    {
        "name": "cicada_add_source",
        "description": "Record WHERE a fact about a page can be checked — a web page, an app, a file or plain words the PERSON gave you ('the team page lists who works there') — when there is no new fact to write. Only a source the person named or one you already opened for them, never one you guessed or searched for. This is not cicada_sources, which lists the conversations a page was built from. With a fact to record, pass `sources` on cicada_write_claim instead. Cicada fetches nothing when you add one.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "The page the fact is on — its id (e.g. 'bob-example') or name."},
                "ref": {"type": "string", "maxLength": 2048, "description": "The source: an http(s) link, an app's name, a file path, or plain words saying where to look."},
                "predicate": {"type": "string", "description": "Optional: which fact it checks (e.g. 'works-at'). Leave it out when it covers the page as a whole."},
                "access": {"type": "string", "enum": ["public", "signed_in", "local", "unknown"], "description": "Optional: 'public' when anyone can open it, 'signed_in' when it needs the person's login, 'local' for a file or repo on this Mac. Left out, Cicada infers it."},
                "kind": {"type": "string", "enum": ["url", "path", "note", "app", "repo"], "description": "Optional: what the ref is. Left out, Cicada infers url, path or note; say 'app' or 'repo' yourself."},
            },
            "required": ["subject", "ref"],
        },
    },
    {
        "name": "cicada_pending",
        "description": "List Cicada episodes not yet consolidated into the knowledge graph (processed: false). Use this to see what raw conversation material is waiting, then use cicada_write_claim to consolidate atomic facts out of it yourself, and cicada_mark_processed once you're done with an episode — this lets an agent do its own lightweight consolidation between Sleep cycles.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max number of unprocessed episodes to return (default 50).",
                },
            },
        },
    },
    {
        "name": "cicada_mark_processed",
        "description": "Mark episodes as processed (processed: true) after you have consolidated their facts via cicada_write_claim. The mark is attributed — the episode is stamped processed_by with your harness name (or 'agent'), distinct from the 'sleep' stamp a Sleep cycle writes. Only mark an episode processed once you have actually extracted what's worth keeping from it — an unmarked episode is still picked up by the next Sleep cycle as a safety net.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "episode_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The episode ids to mark processed (e.g. ['ep_2026-07-02_001']).",
                },
            },
            "required": ["episode_ids"],
        },
    },
    {
        "name": "cicada_resolve_inbox",
        "description": "Answer a pending Cicada inbox question on the user's behalf, after they told you the answer in conversation. Use ONLY with an answer the user actually gave — never guess. Pass the option_key shown by cicada_check_nudges (e.g. 'a', 'b', 'both', 'neither'), or `answer` with free text when none of the options is right (this records a user-stated, trust-protected claim and closes the competing ones), or defer=true when the user says they're not sure and want to be asked later. Pass skip=true when the user did not answer at all: nothing is written and cicada_check_nudges stops returning the item for the rest of this session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "The inbox item id, e.g. 'inbox-001' (shown by cicada_check_nudges).",
                },
                "option_key": {
                    "type": "string",
                    "description": "The key of the option the user chose ('a', 'b', 'both', 'neither', …).",
                },
                "answer": {
                    "type": "string",
                    "description": "Free-text answer, when none of the options is correct. Recorded as a user-stated claim.",
                },
                "defer": {
                    "type": "boolean",
                    "description": "True when the user wants to be asked again later. Default false.",
                },
                "remind_days": {
                    "type": "integer",
                    "description": "With defer=true: how many days out to ask again (default 30).",
                },
                "skip": {
                    "type": "boolean",
                    "description": "True when the question went unanswered this session: no write, not re-asked until the MCP process restarts. Distinct from defer (which writes remind_after).",
                },
                "reject": {
                    "type": "boolean",
                    "description": "For a merge_suggestion: these are NOT the same entity — remember that and stop proposing it.",
                },
            },
            "required": ["id"],
        },
    },
    {
        "name": "cicada_repo_context",
        "description": "Return live git context (branch, ahead/behind, dirty files, worktrees, last commit) for a repo Cicada knows about — either an entity that declares a `repos:` link, or a raw filesystem path. Use when the user asks about the state of a project's git repo/checkout, or before suggesting git actions, so you're grounded in what's actually on disk right now rather than guessing. Degrades gracefully (e.g. 'repo context unavailable (...)') when the path is missing, not a git repo, or belongs to a different device.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "An entity id or name that declares a `repos:` link (e.g. 'cicada'). Exactly one of entity_id/path is required.",
                },
                "path": {
                    "type": "string",
                    "description": "A raw filesystem path to a git repo (e.g. '~/Documents/roros_lab/cicada'). Exactly one of entity_id/path is required.",
                },
            },
        },
    },
    {
        "name": "cicada_handshake",
        "description": "Return Cicada's connection primer: what Cicada is, the interaction contract (recall first, check nudges after recall, save episodes as you learn, write claims with evidence and sources, world facts are a cache), the bank's now-view (engine, current projects with live branches, pending inbox count, recent conversations with resume handles) and capability notes. Identical to the `instructions` field of the MCP initialize response — call it once at the start of a conversation if your harness does not surface server instructions. No arguments.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "cicada_timeline",
        "description": "What changed in Cicada's memory recently, day by day, read from its git history: episodes captured per source, pages Sleep created or updated, pages that faded or were archived, facts that reached their stated end, agent writes (and withdrawals), and inbox questions answered. Ids and counts only — open a page with cicada_recall_detail. Use when the person asks what's new, what happened this week, or what you missed since you last talked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "since": {
                    "type": "string",
                    "description": "Optional. A date (YYYY-MM-DD) or a number of days back (e.g. '7'). Default 7 days; at most 90.",
                },
            },
        },
    },
    {
        "name": "cicada_project",
        "description": "Where one of the person's projects stands: what is under way, what is next, what went quiet, what happened (dated, from whose words), and the people, tools, documents and sub-projects around it. Read-only. Use when the person asks how a project is going, what happened on it, or what's next.",
        "inputSchema": {"type": "object", "required": ["project"], "properties": {
            "project": {"type": "string", "description": "A project's id or name."},
            "since": {"type": "string", "description": "Optional: YYYY-MM-DD, or a number of days back. Default 90."},
            "tz": {"type": "string", "description": "Optional: the person's IANA timezone, for relative dates."}}},
    },
    {
        # G141 §5.2, verbatim: a write, `record` scope remotely (R-PJ23).
        "name": "cicada_note_progress",
        "description": "Record something that happened in one of the person's projects, something under way, or a milestone they planned — dated, with who and what took part. Quote the person's words in evidence. For a standing fact (a spec, who works where) use cicada_write_claim instead.",
        "inputSchema": {"type": "object", "required": ["project", "kind", "summary", "status"], "properties": {
            "project": {"type": "string", "description": "The project page (id or name). Use the person's own page for something outside any project."},
            "kind": {"type": "string", "enum": ["happened", "milestone"]},
            "summary": {"type": "string", "description": "One sentence, third person, naming each participant exactly as the person did. No relative time words."},
            "status": {"type": "string", "enum": ["ongoing", "done", "dropped", "planned", "missed"]},
            "when": {"type": "string", "description": "Optional: YYYY-MM-DD, or the person's own words ('yesterday'), resolved against the cited episode."},
            "target": {"type": "string", "description": "Milestone only: the planned date, YYYY-MM-DD."},
            "milestone": {"type": "string", "description": "Milestone only: an existing milestone's name or slug, to move it or mark it done."},
            "settles": {"type": "string", "description": "Optional: the claim id of an ongoing item this finishes or stops."},
            "participants": {"type": "array", "items": {"type": "object", "required": ["name", "role"], "properties": {
                "name": {"type": "string"},
                "role": {"type": "string", "enum": ["owner", "from", "with", "for", "about", "used", "document", "project"]},
                "url": {"type": "string"}}}},
            "evidence": {"type": "array", "items": {"type": "object", "required": ["episode", "quote"], "properties": {
                "episode": {"type": "string"}, "quote": {"type": "string"}}}}}},
    },
]


def initialize_result(params: dict) -> dict:
    """The MCP `initialize` result — G48's inbound capture plus G75's outbound primer.

    `instructions` is the spec's optional hint-to-the-model field (schema
    2024-11-05: "MAY be added to the system prompt"). It is the SAME text
    `cicada_handshake` returns, built from `_state.md` as it is on disk —
    never refreshed here (R4): connect latency is one file read, and a
    stale now-view says so via its `generated_at`. Any failure to build it
    degrades to no `instructions` at all rather than a failed connect.

    G48: the client names itself here, and nowhere else. Name/version only;
    bounded so a hostile client can't grow a telemetry line without limit.
    """
    client = params.get("clientInfo")
    if isinstance(client, dict):
        CLIENT_INFO.clear()
        CLIENT_INFO.update({
            "name": str(client.get("name") or "")[:64],
            "version": str(client.get("version") or "")[:32],
        })
    result = {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "cicada-bookworm", "version": "0.1.0"},
    }
    try:
        result["instructions"] = _handshake_text(delivery="initialize")
    except Exception as exc:  # never fail a connect over a primer
        print(f"cicada-mcp: handshake unavailable: {exc}", file=sys.stderr)
    return result


def _handshake_text(*, delivery: str) -> str:
    """Build (or load from cache) the primer for the captured client and record
    one `handshake` ledger row (R14 — ids/enums only; `record` never raises).
    `delivery` names which surface asked: `initialize` or `tool`."""
    from api.services import handshake

    memory_path = get_memory_path()
    text, meta = handshake.load_or_build(memory_path, CLIENT_INFO.get("name"))
    handshake.record(delivery, meta, bank=memory_path.name, harness=SESSION.harness,
                     client_name=CLIENT_INFO.get("name") or None)
    return text


def handle_handshake() -> str:
    """`cicada_handshake` — the primer for harnesses that drop `instructions`."""
    return _handshake_text(delivery="tool")


def main():
    """Main loop: read JSON-RPC requests from stdin, write responses to stdout."""
    _warn_if_transcript_missing()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            # G48 capture + G75 primer, both in initialize_result so the
            # tests can drive it without the stdio loop.
            respond(req_id, initialize_result(params))

        elif method == "notifications/initialized":
            # Client acknowledged init — no response needed
            pass

        elif method == "tools/list":
            respond(req_id, {"tools": TOOLS})

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            try:
                result = handle_tool(tool_name, arguments)
                respond(req_id, {
                    "content": [{"type": "text", "text": result}],
                })
            except Exception as e:
                respond(req_id, {
                    "content": [{"type": "text", "text": f"Error: {e}"}],
                    "isError": True,
                })

        elif req_id is not None:
            # Unknown method with an id — return error
            respond_error(req_id, -32601, f"Method not found: {method}")


def respond(req_id, result):
    """Send a JSON-RPC success response."""
    response = {"jsonrpc": "2.0", "id": req_id, "result": result}
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def respond_error(req_id, code, message):
    """Send a JSON-RPC error response."""
    response = {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


# --- Tool Handlers ---

def get_memory_path() -> Path:
    """Resolve the *active memory bank* directory.

    ``CICADA_MEMORY_PATH`` names the memory **root** (the container of
    ``banks.yaml`` + ``banks/<name>/``), not a bank. The API resolves the active
    bank from that root via ``bank_registry.resolve_active_bank_path``; the MCP
    MUST do the same or it serves a different graph than the app/Sleep cycle
    (the "split-brain" bug — recall reads the stale legacy root while the vector
    index + fresh episodes live in the active bank). We import the API resolver
    and fall back to the raw root only if it is unavailable, so a bank switch
    (which rewrites ``banks.yaml``, not the env var) takes effect live.
    """
    import os
    env_path = os.environ.get("CICADA_MEMORY_PATH")
    root = Path(env_path) if env_path else Path.home() / "cicada" / "memory"
    try:
        from api.services.bank_registry import resolve_active_bank_path

        return resolve_active_bank_path(root)
    except Exception:
        # Registry not importable / no banks.yaml → root IS the bank
        # (identical to pre-banks behavior).
        return root


def handle_tool(name: str, arguments: dict) -> str:
    if name == "cicada_recall":
        return handle_recall(arguments.get("query", ""))
    elif name == "cicada_recall_detail":
        return handle_recall_detail(arguments.get("entity_id", ""))
    elif name == "cicada_save_episode":
        return handle_save_episode(
            arguments.get("content", ""),
            arguments.get("title"),
        )
    elif name == "cicada_check_nudges":
        return handle_check_nudges(arguments.get("topic"), arguments.get("entity_ids"))
    elif name == "cicada_handshake":
        return handle_handshake()
    elif name == "cicada_timeline":
        return handle_timeline(arguments.get("since"))
    elif name == "cicada_project":
        return handle_project(arguments.get("project", ""), arguments.get("since"), arguments.get("tz"))
    elif name == "cicada_note_progress":
        return handle_note_progress(arguments)
    elif name == "cicada_open_hub":
        return handle_open_hub(arguments.get("hub", ""))
    elif name == "cicada_ask":
        return handle_ask(arguments.get("query", ""), arguments.get("top_k", 6))
    elif name == "cicada_get_perspective":
        return handle_get_perspective(
            arguments.get("subject", ""),
            arguments.get("observer"),
            arguments.get("context"),
            bool(arguments.get("history", False)),
        )
    elif name == "cicada_save_url":
        return handle_save_url(arguments.get("url", ""), arguments.get("note"))
    elif name == "cicada_record_watch":
        return handle_record_watch(arguments.get("url", ""), arguments.get("summary", ""),
                                   arguments.get("excerpts"), arguments.get("chapters"))
    elif name == "cicada_sources":
        return handle_sources(arguments.get("entity_id", ""))
    elif name == "cicada_write_claim":
        return handle_write_claim(
            arguments.get("subject", ""),
            arguments.get("predicate", ""),
            arguments.get("object", ""),
            arguments.get("observer", "agent"),
            arguments.get("confidence"),
            arguments.get("context"),
            arguments.get("source_episode"),
            bool(arguments.get("force_new_entity", False)),
            arguments.get("sources"),
            arguments.get("evidence"),
            expected_end=arguments.get("expected_end"),
        )
    elif name == "cicada_retract_claim":
        return handle_retract_claim(
            arguments.get("subject", ""),
            arguments.get("claim_id", ""),
            arguments.get("reason", ""),
            arguments.get("evidence"),
        )
    elif name == "cicada_add_source":
        return handle_add_source(
            arguments.get("subject", ""),
            arguments.get("ref", ""),
            arguments.get("predicate"),
            arguments.get("access"),
            arguments.get("kind"),
        )
    elif name == "cicada_pending":
        return handle_pending(arguments.get("limit"))
    elif name == "cicada_mark_processed":
        return handle_mark_processed(arguments.get("episode_ids"))
    elif name == "cicada_repo_context":
        return handle_repo_context(arguments.get("entity_id"), arguments.get("path"))
    elif name == "cicada_resolve_inbox":
        return handle_resolve_inbox(
            arguments.get("id", ""),
            arguments.get("option_key"),
            arguments.get("answer"),
            bool(arguments.get("defer", False)),
            arguments.get("remind_days"),
            skip=bool(arguments.get("skip", False)),
            reject=bool(arguments.get("reject", False)),
        )
    else:
        raise ValueError(f"Unknown tool: {name}")


def _backend_headers() -> dict[str, str]:
    """Bearer token for the local backend (api/services/auth.py)."""
    token = (os.environ.get("CICADA_API_TOKEN") or "").strip()
    if not token:
        home = Path(os.environ.get("CICADA_HOME") or Path.home() / ".cicada").expanduser()
        try:
            token = (home / "api_token").read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _ctx() -> mcp_tools.ToolContext:
    """This stdio process's caller, rebuilt on EVERY call from the module
    globals, so the G48 identity and a test that rebinds `SESSION`,
    `_SKIPPED_INBOX_IDS`, `get_memory_path` or `_backend_post` are seen by the
    moved body. The lambdas look the names up at call time on purpose."""
    return mcp_tools.ToolContext(
        memory_path=lambda: get_memory_path(),
        session_id=SESSION.session_id,
        harness=SESSION.harness,
        project_dir=SESSION.project_dir,
        client_name=CLIENT_INFO.get("name") or None,
        client_version=CLIENT_INFO.get("version") or None,
        skipped_inbox_ids=_SKIPPED_INBOX_IDS,
        state_hint_sent=_STATE_HINT_SENT,
        post=lambda path, payload: _backend_post(path, payload),
        headers=lambda: _backend_headers(),
    )


def handle_recall(query: str) -> str:
    global _STATE_HINT_SENT
    ctx = _ctx()
    try:
        return mcp_tools.recall(ctx, query)
    finally:
        _STATE_HINT_SENT = ctx.state_hint_sent


def handle_recall_detail(entity_id: str) -> str:
    return mcp_tools.recall_detail(_ctx(), entity_id)


def handle_open_hub(hub: str) -> str:
    return mcp_tools.open_hub(_ctx(), hub)


def handle_sources(entity_id: str) -> str:
    return mcp_tools.sources(_ctx(), entity_id)


def handle_timeline(since=None) -> str:
    return mcp_tools.timeline(_ctx(), since)


def handle_project(project, since=None, tz=None) -> str:
    """`cicada_project` (G141 PJ-2) — read-only, engine-free."""
    return mcp_tools.project(_ctx(), project, since, tz)


def handle_note_progress(arguments: dict) -> str:
    """`cicada_note_progress` (G141 PJ-3a) — every §5.2 property, mapped once."""
    return mcp_tools.note_progress(
        _ctx(), str(arguments.get("project") or ""), str(arguments.get("kind") or ""),
        str(arguments.get("summary") or ""), str(arguments.get("status") or ""),
        when=arguments.get("when"), target=arguments.get("target"), milestone=arguments.get("milestone"),
        settles=arguments.get("settles"), participants=arguments.get("participants"),
        evidence=arguments.get("evidence"))


def handle_write_claim(subject, predicate, object_, observer, confidence, context, source_episode,
                       force_new_entity=False, sources=None, evidence=None, expected_end=None) -> str:
    return mcp_tools.write_claim(_ctx(), subject, predicate, object_, observer, confidence, context,
                                 source_episode, force_new_entity, sources, evidence,
                                 expected_end=expected_end)


def handle_retract_claim(subject, claim_id, reason, evidence=None) -> str:
    return mcp_tools.retract_claim(_ctx(), subject, claim_id, reason, evidence)


def handle_add_source(subject, ref, predicate=None, access=None, kind=None) -> str:
    return mcp_tools.add_source(_ctx(), subject, ref, predicate, access, kind)


def handle_get_perspective(subject, observer=None, context=None, history=False) -> str:
    return mcp_tools.get_perspective(_ctx(), subject, observer, context, history)


def handle_check_nudges(topic, entity_ids=None) -> str:
    return mcp_tools.check_nudges(_ctx(), topic, entity_ids)


def handle_resolve_inbox(item_id, option_key, answer, defer, remind_days, *, skip=False, reject=False) -> str:
    return mcp_tools.resolve_inbox(_ctx(), item_id, option_key, answer, defer, remind_days, skip=skip, reject=reject)


def handle_save_episode(content, title) -> str:
    return mcp_tools.save_episode(_ctx(), content, title)


def handle_save_url(url, note) -> str:
    return mcp_tools.save_url(_ctx(), url, note)


def handle_record_watch(url, summary, excerpts=None, chapters=None) -> str:
    return mcp_tools.record_watch(_ctx(), url, summary, excerpts, chapters)


def handle_ask(query, top_k=6) -> str:
    return mcp_tools.ask(_ctx(), query, top_k)


def handle_pending(limit) -> str:
    """List unprocessed episodes for the agent's own consolidation loop."""
    from api.services import agentic_write

    try:
        limit = int(limit) if limit is not None else 50
    except (TypeError, ValueError):
        limit = 50

    episodes = agentic_write.list_unprocessed_episodes(get_memory_path(), limit=limit)
    if not episodes:
        return "No unprocessed episodes pending."

    lines = [f"{len(episodes)} unprocessed episode(s):"]
    for ep in episodes:
        snippet = (ep.get("content") or "")[:300].strip().replace("\n", " ")
        lines.append(f"- `{ep.get('id')}` — {ep.get('title', '')}: {snippet}")
    return "\n".join(lines)


def handle_mark_processed(episode_ids) -> str:
    """Flip processed:true on the given episode ids.

    Stamps ``processed_by`` with this process's harness name (G48 session
    identity — ``claude-code``, or whatever ``CICADA_SESSION_HARNESS`` said)
    so the episode records WHICH agent surface consolidated it, not just that
    one did (G114 R6). ``"unknown"`` is G48's placeholder, not an identity, so
    it falls back to the generic ``"agent"`` rather than being recorded.
    """
    from api.services import agentic_write

    if not isinstance(episode_ids, list) or not episode_ids:
        return "episode_ids is required (a non-empty array of episode ids)."

    harness = (SESSION.harness or "").strip()
    by = harness if harness and harness != "unknown" else "agent"
    count = agentic_write.mark_episodes_processed(get_memory_path(), episode_ids, by=by)
    return f"Marked {count} episode(s) as processed (processed_by: {by})."


def handle_repo_context(entity_id: str | None, path: str | None) -> str:
    """Live git context for a repo Cicada knows about (backlog G-repo).

    Exactly one of ``entity_id`` / ``path`` is required. ``entity_id`` reads
    the resolved entity's own declared ``repos:`` frontmatter and renders one
    or more contexts (an entity can declare more than one repo); ``path``
    probes that filesystem path directly with no declared metadata to compare
    against. Always returns rendered text — never raw JSON — and degrades to a
    human-readable "repo context unavailable (...)" line on any non-ok status.
    """
    entity_id = (entity_id or "").strip()
    path = (path or "").strip()

    if bool(entity_id) == bool(path):
        return "Exactly one of entity_id or path is required."

    from api.services import repo_context

    if path:
        ctx = repo_context.resolve_repo_context({"path": path})
        return _render_repo_context(path, [ctx])

    memory_path = get_memory_path()
    entities_dir = memory_path / "entities"
    resolved_id = _entity_id_for_name(entities_dir, entity_id) or entity_id
    entity_path = entities_dir / f"{resolved_id}.md"
    if not entity_path.exists():
        return f"Entity '{entity_id}' not found."

    try:
        from api.services import markdown_parser

        parsed = markdown_parser.parse(entity_path)
    except Exception as e:
        return f"Could not read '{entity_id}': {e}"

    declared = parsed.frontmatter.get("repos") or []
    declared = [d for d in declared if isinstance(d, dict) and d.get("path")]
    if not declared:
        return f"Entity '{resolved_id}' has no declared repos."

    contexts = [repo_context.resolve_repo_context(d) for d in declared]
    return _render_repo_context(resolved_id, contexts)


def _render_repo_context(label: str, contexts: list[dict]) -> str:
    """Render one or more ``RepoContext`` dicts as human-readable text."""
    blocks = []
    for ctx in contexts:
        if ctx.get("status") != "ok":
            blocks.append(
                f"repo context unavailable for `{ctx.get('path')}` "
                f"(status: {ctx.get('status')})"
            )
            continue

        lines = [f"**{ctx.get('path')}**"]
        branch = ctx.get("current_branch") or "(detached)"
        lines.append(f"- branch: {branch}")
        ahead, behind = ctx.get("ahead"), ctx.get("behind")
        if ahead is not None or behind is not None:
            lines.append(f"- ahead/behind origin: {ahead or 0}/{behind or 0}")
        dirty = ctx.get("dirty_files")
        if dirty is not None:
            lines.append(f"- dirty files: {dirty}")
        commit = ctx.get("last_commit")
        if commit:
            lines.append(
                f"- last commit: {commit.get('hash', '')[:8]} "
                f"by {commit.get('author')} ({commit.get('date')}): {commit.get('subject')}"
            )
        worktrees = ctx.get("worktrees") or []
        if len(worktrees) > 1:
            wt_lines = ", ".join(
                f"{w.get('path')} ({w.get('branch') or 'detached'}"
                f"{', main' if w.get('is_main') else ''})"
                for w in worktrees
            )
            lines.append(f"- worktrees: {wt_lines}")
        if ctx.get("stale_hint"):
            lines.append(f"- note: {ctx['stale_hint']}")
        blocks.append("\n".join(lines))

    header = f"Repo context for `{label}`:" if len(contexts) > 1 or contexts[0].get("path") != label else ""
    body = "\n\n".join(blocks)
    return f"{header}\n\n{body}".strip() if header else body


def _backend_post(path: str, payload: dict) -> dict:
    """POST JSON to the local backend and return the decoded response."""
    import urllib.request

    req = urllib.request.Request(
        f"http://127.0.0.1:8000{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=_backend_headers(),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


if __name__ == "__main__":
    main()
