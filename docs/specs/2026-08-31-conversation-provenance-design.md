# Conversation provenance + resume (G48)

**Status:** draft 2026-08-31 — synthesized from the four G48 research tracers (identity, plumbing,
resume, terminal), each verified against the live repo/machine (Claude Code v2.1.251, Ghostty 1.3.1).
**Goal:** every memory write knows which conversation produced it; the app lists recent
conversations — live MCP sessions and imported chats on one axis — and can reopen one in a
terminal via `claude --resume <id>`.

## 1. Session-id capture at the MCP seam

`mcp/server.py` mints one module-level identity at process start (stdio MCP = one process per
client conversation), reliability-ranked per the identity tracer:

1. **`CLAUDE_CODE_SESSION_ID`** (undocumented but verified: injected per-child at spawn, matches
   the actively-written transcript, survives `--resume`), paired with documented
   `CLAUDE_PROJECT_DIR`. When present: `session_id` = the uuid, `harness = "claude-code"`,
   `project_dir` = env. Sanity check (warn, don't drop): the transcript
   `~/.claude/projects/<slug(project_dir)>/<session_id>.jsonl` exists, slug = every
   non-alphanumeric char of the absolute path → `-`.
2. **`CICADA_SESSION_ID`** explicit override — works for any MCP client and doubles as a manual
   re-attach handle.
3. **Minted fallback** `ses_YYYY-MM-DD_<uuid4hex[:8]>` — still groups the conversation's
   episodes; simply never resumable (`harness = "unknown"`).

Rejected: transcript-mtime correlation (ambiguous under concurrent same-project sessions, ~1 min
lag under subagent load — unnecessary once the mint covers grouping); a SessionStart hook
(user-visible config, last-writer-wins); initialize `clientInfo` (name/version only). But the
`initialize` handler (server.py:310) stops discarding params: log `clientInfo` into telemetry refs.

## 2. Storage

### 2.1 Episode frontmatter — the primary carrier
`handle_save_episode` (mcp/server.py:1580-1588) adds `session_id`, plus `harness` and
`project_dir` when known; `handle_save_url` gets the same stamp. Verified inert to every existing
parser: origin_stats ignores unknown keys, import re-staging (`_stage_episodes` /
`_update_episode_in_place`) preserves them, markdown_parser round-trips dicts. Imported
conversations keep their existing per-conversation id — G20 `source_id` (export uuid) — untouched.

### 2.2 Commit trailer `Cicada-Session:` — additive, inert
`git_service.build_commit_message` (69-96) gains `sessions: list[str]` mirroring `authors=`: one
`Cicada-Session: <id>` line per distinct id after the `Cicada-Author:` block, with `_SESSION_RE`
+ `_parse_sessions` twins of the author machinery. Inert by the same contract that keeps
`Cicada-Author:` out of entity-line parsing (CLAUDE.md: "extend it, don't break it"). Call site
in this slice: `sleep_cycle._finalize` only — sessions = distinct `session_id`/`source_id` of
episodes consolidated that cycle, capped at 10. User-action commits (inbox_service.py:271,
entities.py) stay session-less: they are `Cicada-Author: user` writes with no conversation.

### 2.3 Propagation to entities/claims — read-time, transitive
No entity frontmatter change. Entities credit to conversations exactly like origins: entity →
`source_episodes` → episode `session_id or source_id` (origin_stats.py:61-69 pattern). Claims:
`handle_write_claim` threads `session_id` into its telemetry UsageEvent refs (server.py:1004-1009)
— the ledger becomes the model-attribution join key.

## 3. Aggregation: `GET /conversations/recent`

New `api/services/session_stats.py`, an origin_stats clone (~85 lines): group episodes by
`fm.get("session_id") or fm.get("source_id")` (skip episodes with neither — pre-G48 MCP episodes
simply don't appear; no backfill). Route lands in the already-mounted conversations router
(api/main.py:156):

    GET /conversations/recent?limit=20
    → [{conversation_id, kind: "mcp"|"import",   # which key matched
        harness, origin, title,                   # title = first episode's title (from the bank)
        first_seen, last_seen, episode_count, entity_ids,
        model,       # best-effort: latest telemetry event with refs.session_id == id; null otherwise
        resumable}]  # computed per-request, never cached — transcripts get retention-cleaned

Sorted by `last_seen` desc. ETag = `sync_service.etag_for(mp, "episodes", "entities")`
(origins.py:24 pattern); the `episodes` version-vector component already flips on any episode
write. `resumable` = id matches the strict UUID regex AND `transcript_exists(project_dir, id)` —
an injectable callable defaulting to `os.path.isfile` on
`~/.claude/projects/<slug>/<id>.jsonl`, top-level only (files under `<id>/subagents/` are never
sessions). Known ETag caveat: transcript deletion doesn't flip the version vector, so `resumable`
can be stale until the next non-304 refresh — acceptable because the resume endpoint re-validates.

## 4. App surface

Follows the G67 `/contributors/commits` precedent: on-demand fetch, **no new Store domain, no
SnapshotCache entry**. Home: UI-round-2 Task 8's ActivityView — `ActivitySection` gains a third
case, `conversations`, beside Usage and Contributors (@AppStorage-persisted like the rest). Row:
title, harness badge, relative last-write time, entity-count chip, and a Resume menu when
`resumable` (Resume in terminal / Copy command). Entity chips use existing entity navigation.

Click-through — "open the conversation that wrote this":
- `GET /entities/{id}/history` enriched commits gain `sessions` (parsed `Cicada-Session:`
  trailer); when a session resolves to a known conversation, the history row shows a
  "from conversation →" affordance that lands on Activity ▸ Conversations with that row selected.
- `/contributors/commits` drill-down rows get the same affordance from the same parsed trailer.
Pre-G48 commits and episodes carry no session, so the affordance simply doesn't render.

## 5. Resume action

`POST /conversations/{id}/resume` — keeps the G50 split (backend validates, app launches):
1. Gate `id` on `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` → 400 otherwise
   (minted `ses_…` ids are 400 by construction: not resumable).
2. Re-check transcript existence → 409 `{reason: "transcript_gone"}` when retention-cleaned.
3. Return `{mode: "terminal", argv: ["claude", "--resume", "<id>"], cwd: <project_dir>,
   display_command: "claude --resume <id>"}`. `cwd` comes from the stamped `project_dir`; it must
   exist and match a conservative charset (`^[A-Za-z0-9/_.~-]+$`) or it is omitted and the app
   uses `$HOME`. The binary name `claude` is a fixed literal, never API-configurable.

App launch ladder (mirrors `ConnectionsView.openInTerminal`, ConnectionsView.swift:62-89):
1. **Ghostty** (gate: `/Applications/Ghostty.app` exists) via its 1.3 AppleScript dictionary:
   `tell application "Ghostty" → activate → new window with configuration
   {command:"claude --resume <uuid>", initial working directory:"<cwd>"}` — targets the running
   instance, no second app, native cwd. One manual osascript verification required before wiring.
2. **Terminal.app**: `do script "cd <cwd> && claude --resume <uuid>"` — safe only because both
   interpolants passed the regex gates; nothing else is ever interpolated into AppleScript source.
3. **Clipboard**: copy `display_command` + toast (existing terminalFallback). iTerm skipped (not
   installed). Never `/bin/sh -c`; any future backend-side launch uses a fixed argv list
   (`open -na Ghostty.app --args …`) — see open questions.

## 6. Privacy / safety rails

- **Transcripts are never read.** The backend only `isfile()`s the path — no open, no parse; no
  transcript content ever enters a bank, an API response, a log line, or a telemetry event.
  Conversation titles come from episode titles already inside the bank.
- Only ids, timestamps, counts, and entity ids cross `/conversations/recent`; `project_dir` is
  returned solely by the resume endpoint (the app needs a cwd to launch).
- Nothing under `~/.claude/` is copied into a bank; `resumable` is computed per-request and never
  persisted to frontmatter.
- Both new endpoints require the standard Bearer token (not in the exempt set).
- `CICADA_TELEMETRY=off` unaffected: session refs ride existing UsageEvents only.

## 7. Testing (repo conventions: tmp_path banks, injected fetchers, `CICADA_API_AUTH=off`)

- **Stamp:** monkeypatched env → save_episode writes uuid + harness + project_dir; env absent →
  `ses_` mint; `CICADA_SESSION_ID` beats the mint; frontmatter round-trips through
  markdown_parser and survives import re-staging and Sleep's `processed: true` rewrite.
- **Trailer:** `build_commit_message(sessions=[…])` emit/parse round-trip; regression: a commit
  carrying both trailers still parses authors and entity lines unchanged.
- **Aggregation:** synthetic episodes (session_id only / source_id only / both keys / neither /
  shared entity) → grouping, kind, sort, counts; ETag → 304 on an unchanged bank.
- **Resumable:** injected `transcript_exists` over a fake root under tmp_path (real `~/.claude`
  never touched); uuid vs `ses_` ids; slug computation for `/` and `_`.
- **Resume endpoint:** 400 malformed and `ses_` ids; 409 missing transcript; 200 argv shape;
  bad-charset cwd omitted.
- **App:** FakeSyncAPI grows `fetchRecentConversations` / `resumeConversation`; ViewModel tests
  for the section rows and resumable gating; pure-function tests for the Ghostty/Terminal
  AppleScript source builders (exact string for a fixed uuid+cwd; unvalidated input unreachable).

## Appendix — verified facts relied on

- **Identity:** the live cicada MCP process carries `CLAUDE_CODE_SESSION_ID` (matching the
  actively-written transcript) and `CLAUDE_PROJECT_DIR`; injected at child spawn (the parent
  claude has neither in its own env); survives `--resume`. Undocumented — docs list only
  CLAUDE_PROJECT_DIR, and the hooks page explicitly denies a session env var. Verified v2.1.251.
- **Resume:** transcripts live at `~/.claude/projects/<slug>/<uuid>.jsonl`, slug = non-alnum → `-`
  (verified for `/` and `_`); appended within seconds; subagent transcripts under
  `<uuid>/subagents/` are not sessions; old transcripts persist ≥11 days but slug dirs show
  cleanup happens; `claude --resume <bad-id>` fails fast and cwd-agnostically with no model call;
  session ids are canonical UUIDs (`--session-id` requires one).
- **Plumbing:** server.py writes episodes directly to the filesystem (frontmatter at 1580-1588),
  discards initialize params, reads no CLAUDE_* var; the origin rail (capture-time stamp +
  read-time transitive credit via source_episodes + `etag_for(mp,'episodes','entities')`) is the
  template; trailer machinery is extension-safe by contract (git_service.py:25-110); G20
  `source_id` + entity_sources.py already map imports to whole conversations; the conversations
  router is mounted (main.py:156); `/contributors/commits` and askHistory are the no-domain /
  cache-only app precedents; no session concept exists anywhere today.
- **Terminal:** Ghostty 1.3.1 installed with an AppleScript sdef exposing `new window with
  configuration {command, initial working directory, environment variables, wait after command}`;
  macOS CLI launch unsupported (`open -na` only, second-instance caveat); iTerm absent;
  Terminal.app + clipboard fallback already shipped as G50's `openInTerminal`.