# Conversation Provenance + Resume (G48) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every memory write knows which conversation produced it; the app lists recent conversations (live MCP sessions and imported chats on one axis) and can reopen a Claude Code session in a terminal via `claude --resume <id>`.

**Architecture:** Capture-time stamp + read-time transitive credit, exactly like the G9 `origin` rail. The MCP server mints one conversation identity per process and stamps `session_id` / `harness` / `project_dir` onto every episode it writes. A new `Cicada-Session:` git trailer (twin of `Cicada-Author:`) records which conversations a Sleep commit consolidated. A new `api/services/session_stats.py` (an `origin_stats.py` clone) groups episodes by `session_id or source_id` and credits entities through `source_episodes`. Two new endpoints on the already-mounted conversations router serve the list and a validated launch descriptor. The app renders a third segment inside ActivityView and launches Ghostty/Terminal/clipboard through a pure, regex-gated AppleScript builder.

**Tech Stack:** Python 3.12 / FastAPI / pydantic v2 (`api/`, venv at `api/.venv`), stdlib-only JSON-RPC MCP server (`mcp/server.py`), SwiftUI macOS 14 + SwiftPM (`app/CicadaApp`), XCTest.

**Spec:** `docs/superpowers/specs/2026-08-31-conversation-provenance-design.md` — the authority. Read it before Task 1.

**Test commands:**
- Backend: `api/.venv/bin/python -m pytest api/tests -q`
- App: `cd app/CicadaApp && swift test`

## Global Constraints

Every task's requirements implicitly include all of these.

- **Never touch `.claude/settings.json`.** Not in any task, not to add a permission, not to "make the probe easier".
- **Never `git add -A`.** Every commit stages the exact paths it changed (`git add <path> <path>`). `git_service.commit_changes` staging `-A` inside the *memory bank* is pre-existing behaviour and is out of scope; this rule is about **your** commits in the code repo.
- **Nothing under `memory/` in commits.** The live bank is not part of any commit in this plan.
- **Transcripts are NEVER read.** `os.path.isfile()` on the path is the only permitted operation. No `open()`, no parse, no line count. No transcript content — and no transcript *path* — is written into a memory bank, an API response body, a log line, or a telemetry event.
- **Resume ids are gated by the strict UUID regex** `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` before any filesystem or launch use. Minted `ses_…` ids fail this gate by construction and are never resumable.
- **The `claude` binary name is a fixed literal** in code (`CLAUDE_BINARY = "claude"`). Never read from settings, env, or a request body.
- **AppleScript interpolants only after regex gates.** A string reaches AppleScript source only after passing `isSafeCommand` / `isSafeCwd`. Nothing else is ever interpolated. Never `/bin/sh -c`.
- **Tests are `tmp_path`-only** with an injectable `transcript_exists`. No test may touch the real `~/.claude`, the real `~/.cicada`, or the real `memory/`.
- **Commit trailers** — every commit in this plan ends with:
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
  ```
- **Concurrency:** the UI round 2 plan (`docs/superpowers/plans/2026-08-31-ui-round-2.md`) executes on this same branch and finishes before Tasks 7–8 start. Do not rewrite files it rewrites (`ContentView.swift`, `Views/Sidebar/SidebarView.swift`, `Views/Usage/UsageView.swift`, `Views/Contributors/ContributorsView.swift`'s header, `CicadaApp.swift`) — touch them **additively** only.

---

## Ambiguities resolved (spec open questions → conservative calls)

| Spec question | Call made here | Why |
|---|---|---|
| Trailer cap ("capped at 10") | **No cap inside `build_commit_message`** (dedup + caller order, exactly like `authors=`). The cap lives at the `_finalize` call site: `git_service.MAX_SESSION_TRAILERS = 50`, applied after dedup + `sorted()`, with a `logger.warning` when it bites. | 10 silently drops real provenance on a busy night. 50 distinct conversations in one Sleep is effectively unreachable, and `/conversations/recent` — not the trailer — is the authoritative index. |
| `entity_ids` unbounded on a conversation row | **Capped at `MAX_CONVERSATION_ENTITIES = 12`**, with a true `entity_count` alongside. | Mirrors `ContributorCommit.entities` / `entities_total` (`git_service.MAX_COMMIT_ENTITIES = 12`) and its shipped "+N more" capsule. |
| ETag components for `/conversations/recent` | **`etag_for(mp, "episodes", "entities", "telemetry", extra=f"limit={limit}")`** — spec said two keys. | The response carries a telemetry-derived `model`; without the `telemetry` component the app would 304 forever on a stale model. The transcript-deletion staleness caveat stands (documented in the docstring); the resume endpoint re-validates. |
| Unknown id on `POST /conversations/{id}/resume` | **404 `unknown conversation`**, in addition to the spec's 400/409. | Without a bank-recorded `project_dir` there is no transcript path to check; scanning every `~/.claude/projects/*` slug dir to find one is filesystem crawling we do not need. 404 is honest. |
| `initialize` `clientInfo` → "telemetry refs" | **Stored in a module-level `CLIENT_INFO` and folded into the refs of the existing `agentic_write` event** in `handle_write_claim`. No new `telemetry.KINDS` member, no new event emitted at initialize. | Inventing a kind would land unclassified rows in the consumption ledger that `/consumption/*` does not know how to price or bucket. |
| App click-through "lands on Activity ▸ Conversations with that row selected" | **Delivered as an in-place popover** on the history/commit row showing that conversation's row + Resume menu — not a cross-tab navigation. | `selectedTab` is `@State` in `ContentView` threaded by `@Binding`, and both `ContentView.swift` and `SidebarView.swift` are being rewritten concurrently by UI round 2 Task 10. The popover delivers the same user value ("open the conversation that wrote this", with Resume) without editing those files. Recorded as an honest partial in the docs task. |
| `handle_save_url` "gets the same stamp" | Threaded through the **existing `origin` precedent**: `SourceSaveRequest` + `RawItem` gain three optional fields, `write_media_episode` stamps them when present. | The MCP tool's primary path is `POST /sources/save`; the episode is written backend-side by `media_ingestor`, so the stamp has to ride the request. |
| `/conversations/recent` response shape | **Bare `list[ConversationSummary]`**, as the spec's `→ [{…}]` shows. | Precedent: `GET /entities/{id}/history` returns a bare list. |
| Slug for a path containing `.` | Implemented as "every non-alphanumeric → `-`" (Task 3) and **verified live in Task 6**, which corrects `project_slug` + its test if the observation differs. | The spec appendix verified `/` and `_` only. |

---

## File Structure

### Backend (`api/`, `mcp/`)

| File | Responsibility | Task |
|---|---|---|
| `mcp/server.py` (modify) | Mint one `SessionIdentity` per process; stamp episodes + saved URLs; capture `clientInfo`; thread session into claim telemetry refs. | 1 |
| `api/services/media_ingestor.py` (modify) | `RawItem` carries session fields; `write_media_episode` stamps them (mirrors `origin`). | 1 |
| `api/routers/sources.py` (modify) | Thread the three optional request fields into `RawItem`. | 1 |
| `api/services/sleep_cycle.py` (modify) | Episode loader carries `session_id`/`source_id`; `_collect_session_ids`; `_finalize` emits session trailers. | 1, 2 |
| `api/services/git_service.py` (modify) | `Cicada-Session:` trailer emit/parse; `sessions` on history + contributor-commit rows. | 2, 4 |
| `api/services/session_stats.py` (**create**) | Group episodes into conversations; UUID gate; slug; injectable `transcript_exists`; telemetry model join. An `origin_stats.py` clone in shape and tone. | 3 |
| `api/routers/conversations.py` (modify) | `GET /conversations/recent`, `POST /conversations/{id}/resume`. The 700-line file is already a parser dump; the two routes go at the **top**, right under the existing upload route, with the injectable `transcript_exists` seam at module scope. | 3, 5 |
| `api/models/schemas.py` (modify) | `ConversationSummary`, `ResumeDescriptor`, `SourceSaveRequest` fields, `sessions` on `EntityHistoryEntry` + `ContributorCommit`. | 1, 3, 4, 5 |

New backend tests: `api/tests/test_session_identity.py`, `test_session_trailer.py`, `test_session_stats.py`, `test_session_provenance_views.py`, `test_conversation_resume.py`.

### App (`app/CicadaApp`)

| File | Responsibility | Task |
|---|---|---|
| `Sources/CicadaApp/Services/TerminalLauncher.swift` (**create**) | Pure, regex-gated AppleScript source builders + the Ghostty → Terminal → clipboard ladder. Injectable runner so every branch is unit-testable. | 6 |
| `Sources/CicadaApp/Models/Conversation.swift` (**create**) | `ConversationSummary`, `ResumeDescriptor` — tolerant camelCase decoding. | 7 |
| `Sources/CicadaApp/ViewModels/ConversationsViewModel.swift` (**create**) | Fetch + resume orchestration over `any SyncAPI`. | 7 |
| `Sources/CicadaApp/Views/Activity/ConversationsSection.swift` (**create**) | The section body + `ConversationRow` (reused by the popover). | 7 |
| `Sources/CicadaApp/Views/Activity/ActivityView.swift` (modify, additive) | Third `ActivitySection` case + switch arm + a11y label. | 7 |
| `Sources/CicadaApp/Services/APIClient.swift` (modify, additive) | `fetchRecentConversations`, `resumeConversation`. | 7 |
| `Sources/CicadaApp/Sync/SyncAPI.swift` (modify, additive) | Same two methods on the protocol (on-demand, **no** `SyncDomain`, no `SnapshotCache` entry). | 7 |
| `Sources/CicadaApp/Views/Activity/ConversationPopover.swift` (**create**) | Shared "from conversation →" popover content. | 8 |
| `Sources/CicadaApp/Models/Entity.swift` (modify, additive) | `sessions` on `EntityHistoryEntry` + `ContributorCommit`. | 8 |
| `Sources/CicadaApp/Views/Graph/EntityDetailCard.swift` (modify, additive) | Affordance on a history row. | 8 |
| `Sources/CicadaApp/Views/Contributors/ContributorsView.swift` (modify, additive) | Affordance on a commit row. | 8 |

New app tests: `Tests/CicadaAppTests/TerminalLaunchScriptTests.swift`, `ConversationsTests.swift`, `ConversationAffordanceTests.swift`. One additive edit to `Tests/CicadaAppTests/StoreTests.swift` (two `FakeSyncAPI` methods).

### Docs

`CLAUDE.md` (endpoint list + storage note), `docs/goals/memory-evolution.md` (G48 row → ✅ with honest partials). Task 9.

---

## Task 1: MCP session identity + episode/URL stamping

**Files:**
- Modify: `mcp/server.py` — new identity block after the `agentic_write` import (~line 25); `initialize` handler at `mcp/server.py:309-318`; `handle_write_claim` telemetry refs at `mcp/server.py:1004-1013`; `handle_save_url` at `mcp/server.py:551-608`; `handle_save_episode` at `mcp/server.py:1543-1602`
- Modify: `api/services/media_ingestor.py:50-69` (`RawItem`), `api/services/media_ingestor.py:962-988` (`write_media_episode`)
- Modify: `api/models/schemas.py:920-923` (`SourceSaveRequest`)
- Modify: `api/routers/sources.py:56-73` (`save_source`)
- Modify: `api/services/sleep_cycle.py:407-435` (`_get_unprocessed_episodes`)
- Test: `api/tests/test_session_identity.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `mcp.server.SessionIdentity` — frozen dataclass `(session_id: str, harness: str, project_dir: str | None)`
  - `mcp.server.resolve_session_identity(env: dict | None = None) -> SessionIdentity`
  - `mcp.server.SESSION: SessionIdentity` (module-level, resolved at import)
  - `mcp.server.CLIENT_INFO: dict` (`{"name": str, "version": str}`, populated by `initialize`)
  - `mcp.server._session_frontmatter() -> dict`
  - Episode frontmatter keys `session_id: str`, `harness: str` (omitted when `"unknown"`), `project_dir: str` (omitted when absent)
  - `media_ingestor.RawItem.session_id / .harness / .project_dir` (`str | None`, default `None`)
  - `schemas.SourceSaveRequest.session_id / .harness / .project_dir` (`Optional[str] = None`; wire aliases `sessionId` / `harness` / `projectDir`)
  - `sleep_cycle._get_unprocessed_episodes` dicts gain `"session_id"` and `"source_id"` (`str | None`)

- [ ] **Step 1: Write the failing identity tests**

Create `api/tests/test_session_identity.py`:

```python
"""G48 — the MCP server mints ONE conversation identity per process and stamps
it onto everything it writes. Hermetic: env is a plain dict, banks live under
tmp_path, and the real ~/.claude is never touched.
"""

from __future__ import annotations

import importlib
import re

server = importlib.import_module("mcp.server")


# --- resolve_session_identity (pure) ----------------------------------------


def test_claude_code_env_wins_and_carries_the_project_dir():
    ident = server.resolve_session_identity({
        "CLAUDE_CODE_SESSION_ID": "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b",
        "CLAUDE_PROJECT_DIR": "/Users/x/Documents/roros_lab/cicada",
    })
    assert ident.session_id == "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
    assert ident.harness == "claude-code"
    assert ident.project_dir == "/Users/x/Documents/roros_lab/cicada"


def test_a_non_uuid_claude_session_id_is_refused_and_falls_through():
    ident = server.resolve_session_identity({"CLAUDE_CODE_SESSION_ID": "not-a-uuid"})
    assert ident.session_id.startswith("ses_")
    assert ident.harness == "unknown"


def test_explicit_override_is_used_when_no_claude_session_id():
    ident = server.resolve_session_identity({
        "CICADA_SESSION_ID": "my-cursor-thread-7",
        "CICADA_SESSION_HARNESS": "cursor",
    })
    assert ident.session_id == "my-cursor-thread-7"
    assert ident.harness == "cursor"


def test_claude_session_id_beats_the_explicit_override():
    ident = server.resolve_session_identity({
        "CLAUDE_CODE_SESSION_ID": "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b",
        "CICADA_SESSION_ID": "loser",
    })
    assert ident.session_id == "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"


def test_mint_shape_groups_but_never_resumes():
    ident = server.resolve_session_identity({})
    assert re.match(r"^ses_\d{4}-\d{2}-\d{2}_[0-9a-f]{8}$", ident.session_id)
    assert ident.harness == "unknown"
    assert ident.project_dir is None


def test_two_mints_are_distinct():
    a = server.resolve_session_identity({})
    b = server.resolve_session_identity({})
    assert a.session_id != b.session_id


# --- frontmatter projection --------------------------------------------------


def test_frontmatter_omits_unknown_harness_and_absent_project_dir(monkeypatch):
    monkeypatch.setattr(
        server, "SESSION", server.SessionIdentity("ses_2026-08-31_deadbeef", "unknown", None)
    )
    assert server._session_frontmatter() == {"session_id": "ses_2026-08-31_deadbeef"}


def test_frontmatter_carries_harness_and_project_dir_when_known(monkeypatch):
    monkeypatch.setattr(
        server,
        "SESSION",
        server.SessionIdentity("0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b", "claude-code", "/tmp/p"),
    )
    assert server._session_frontmatter() == {
        "session_id": "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b",
        "harness": "claude-code",
        "project_dir": "/tmp/p",
    }
```

- [ ] **Step 2: Run them and watch them fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_session_identity.py -q`
Expected: FAIL — `AttributeError: module 'mcp.server' has no attribute 'resolve_session_identity'`.

- [ ] **Step 3: Add the identity block to `mcp/server.py`**

Insert immediately after the `from api.services import agentic_write  # noqa: E402` line (~line 25), before the `TOOLS` list. `dataclasses`, `re`, `uuid` are stdlib — add them to the existing import block at the top of the file.

```python
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
# this feature is an isfile() check, and it lives in the API, not here.

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


def _session_frontmatter() -> dict:
    """The session keys to merge into an episode's frontmatter.

    Additive and inert: origin_stats ignores unknown keys, import re-staging
    (`_stage_episodes` / `_update_episode_in_place`) preserves them, and
    markdown_parser round-trips them.
    """
    fm: dict = {"session_id": SESSION.session_id}
    if SESSION.harness and SESSION.harness != "unknown":
        fm["harness"] = SESSION.harness
    if SESSION.project_dir:
        fm["project_dir"] = SESSION.project_dir
    return fm
```

Add to the stdlib import block at the top of the file (`import json`, `import os`, `import sys` …):

```python
import re
import uuid
from dataclasses import dataclass
```

(`date` and `datetime` are already imported from `datetime`.)

- [ ] **Step 4: Run the identity tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_session_identity.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Write the failing stamping tests**

Append to `api/tests/test_session_identity.py`:

```python
# --- handle_save_episode stamps ---------------------------------------------

import pytest

from api.services import markdown_parser


@pytest.fixture
def mcp_bank(tmp_path, monkeypatch):
    """A throwaway memory root the MCP handlers write into."""
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setattr(
        server,
        "SESSION",
        server.SessionIdentity("0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b", "claude-code", "/tmp/p"),
    )
    return memory


def test_save_episode_stamps_the_session(mcp_bank):
    out = server.handle_save_episode("we picked sqlite-vec over LEANN", "Index choice")
    assert "Episode saved" in out

    written = list((mcp_bank / "episodes").glob("*.md"))
    assert len(written) == 1
    fm = markdown_parser.parse(written[0]).frontmatter
    assert fm["session_id"] == "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
    assert fm["harness"] == "claude-code"
    assert fm["project_dir"] == "/tmp/p"
    # Pre-existing keys are untouched.
    assert fm["origin"] == "mcp" and fm["processed"] is False


def test_a_minted_session_stamps_only_the_id(mcp_bank, monkeypatch):
    monkeypatch.setattr(
        server, "SESSION", server.SessionIdentity("ses_2026-08-31_deadbeef", "unknown", None)
    )
    server.handle_save_episode("a note", "Note")
    fm = markdown_parser.parse(next((mcp_bank / "episodes").glob("*.md"))).frontmatter
    assert fm["session_id"] == "ses_2026-08-31_deadbeef"
    assert "harness" not in fm and "project_dir" not in fm


def test_the_stamp_survives_the_sleep_loader_and_the_processed_rewrite(mcp_bank):
    from api.services import bank_index, sleep_cycle

    server.handle_save_episode("we picked sqlite-vec", "Index choice")
    bank_index.invalidate()

    queued = sleep_cycle._get_unprocessed_episodes(mcp_bank)
    assert len(queued) == 1
    assert queued[0]["session_id"] == "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
    assert queued[0]["source_id"] is None

    sleep_cycle._mark_episodes_processed(queued)
    fm = markdown_parser.parse(queued[0]["filepath"]).frontmatter
    assert fm["processed"] is True
    assert fm["session_id"] == "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
    assert fm["harness"] == "claude-code"


def test_an_imported_episode_reports_its_source_id_to_the_loader(mcp_bank):
    from api.services import bank_index, sleep_cycle

    (mcp_bank / "episodes" / "ep_2026-01-01_001.md").write_text(
        "---\nid: ep_2026-01-01_001\ntimestamp: '2026-01-01T00:00:00Z'\n"
        "processed: false\nsource_id: uuid-abc\n---\n\nimported\n",
        encoding="utf-8",
    )
    bank_index.invalidate()

    queued = {e["id"]: e for e in sleep_cycle._get_unprocessed_episodes(mcp_bank)}
    assert queued["ep_2026-01-01_001"]["source_id"] == "uuid-abc"
    assert queued["ep_2026-01-01_001"]["session_id"] is None


# --- write_media_episode stamps (the cicada_save_url path) -------------------


def test_media_episode_stamps_the_session_when_the_caller_supplies_one(tmp_path):
    from api.services.media_ingestor import MediaMeta, RawItem, write_media_episode

    item = RawItem(
        url="https://example.com/a",
        session_id="0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b",
        harness="claude-code",
        project_dir="/tmp/p",
    )
    meta = MediaMeta(title="A", media_type="url")
    ep_id = write_media_episode(tmp_path / "episodes", item, meta, "media-a")

    fm = markdown_parser.parse(tmp_path / "episodes" / f"{ep_id}.md").frontmatter
    assert fm["session_id"] == "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
    assert fm["harness"] == "claude-code"
    assert fm["project_dir"] == "/tmp/p"


def test_media_episode_without_a_session_is_byte_identical_to_before(tmp_path):
    from api.services.media_ingestor import MediaMeta, RawItem, write_media_episode

    ep_id = write_media_episode(
        tmp_path / "episodes", RawItem(url="https://example.com/a"),
        MediaMeta(title="A", media_type="url"), "media-a",
    )
    fm = markdown_parser.parse(tmp_path / "episodes" / f"{ep_id}.md").frontmatter
    assert "session_id" not in fm and "harness" not in fm and "project_dir" not in fm
```

- [ ] **Step 6: Run them and watch them fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_session_identity.py -q`
Expected: FAIL — `KeyError: 'session_id'` on the save-episode test and `TypeError: RawItem.__init__() got an unexpected keyword argument 'session_id'`.

- [ ] **Step 7: Stamp `handle_save_episode`**

In `mcp/server.py:1578-1587`, extend the frontmatter dict (keep every existing key and its comment):

```python
    frontmatter = {
        "id": episode_id,
        "timestamp": timestamp,
        "source": "mcp",
        "origin": "mcp",
        "title": title or "MCP capture",
        "processed": False,
        "content_hash": content_hash,
        # G48: which conversation produced this episode. Additive + inert.
        **_session_frontmatter(),
    }
```

- [ ] **Step 8: Stamp the saved-URL path**

`api/services/media_ingestor.py` — extend `RawItem` (after the `origin` field, `media_ingestor.py:69`):

```python
    # G48 conversation provenance, threaded from a live MCP client through
    # `POST /sources/save`. Same contract as `origin` above: written to the
    # episode ONLY when the caller supplies it, so every non-MCP capture path
    # (bookmarks, RSS, the app's paste field) produces byte-identical
    # frontmatter to before.
    session_id: str | None = None
    harness: str | None = None
    project_dir: str | None = None
```

`write_media_episode` (`media_ingestor.py:986-987`), right after the existing `if item.origin:` block:

```python
    if item.session_id:
        frontmatter["session_id"] = item.session_id
        if item.harness and item.harness != "unknown":
            frontmatter["harness"] = item.harness
        if item.project_dir:
            frontmatter["project_dir"] = item.project_dir
```

`api/models/schemas.py:920-923`:

```python
class SourceSaveRequest(CamelModel):
    url: str
    note: Optional[str] = None
    tags: list[str] = []
    # G48: conversation provenance from a live MCP client (`cicada_save_url`).
    # Optional — the menu-bar quick action and the app's paste field send none.
    session_id: Optional[str] = None
    harness: Optional[str] = None
    project_dir: Optional[str] = None
```

`api/routers/sources.py:69`:

```python
    item = RawItem(
        url=url,
        tags=request.tags,
        note=request.note,
        session_id=request.session_id,
        harness=request.harness,
        project_dir=request.project_dir,
    )
```

`mcp/server.py::handle_save_url` — the backend payload at `mcp/server.py:562` becomes:

```python
        payload = json.dumps({
            "url": url,
            "note": note,
            "sessionId": SESSION.session_id,
            "harness": SESSION.harness,
            "projectDir": SESSION.project_dir,
        }).encode("utf-8")
```

…and the offline fallback at `mcp/server.py:589`:

```python
            item = media_ingestor.RawItem(
                url=url,
                note=note,
                session_id=SESSION.session_id,
                harness=SESSION.harness,
                project_dir=SESSION.project_dir,
            )
```

- [ ] **Step 9: Carry the ids into the Sleep loader**

`api/services/sleep_cycle.py:420-427` — add two keys to the dict `_get_unprocessed_episodes` builds:

```python
            "timestamp": str(fm.get("timestamp", "") or ""),
            "filepath": f.path,
            # G48: which conversation produced this episode. `session_id` is
            # stamped by the MCP seam at capture; `source_id` is G20's
            # per-thread export id. `_finalize` turns the distinct set into
            # `Cicada-Session:` trailers.
            "session_id": str(fm.get("session_id") or "") or None,
            "source_id": str(fm.get("source_id") or "") or None,
```

- [ ] **Step 10: Run the whole file**

Run: `api/.venv/bin/python -m pytest api/tests/test_session_identity.py -q`
Expected: PASS (14 tests).

- [ ] **Step 11: Capture `clientInfo` and thread the session into claim telemetry**

`mcp/server.py:309` — the `initialize` branch keeps its exact response, gaining only the capture:

```python
        if method == "initialize":
            # G48: stop discarding params — the client names itself here, and
            # nowhere else. Name/version only; bounded so a hostile client
            # can't grow a telemetry line without limit.
            client = params.get("clientInfo")
            if isinstance(client, dict):
                CLIENT_INFO.clear()
                CLIENT_INFO.update({
                    "name": str(client.get("name") or "")[:64],
                    "version": str(client.get("version") or "")[:32],
                })
            respond(req_id, {
```

`mcp/server.py:1004-1013` — extend the existing `agentic_write` event's refs (do not add an event, do not add a `telemetry.KINDS` member):

```python
        refs={
            "entity_id": result.get("entity_id"),
            "claim_id": result.get("claim_id"),
            "episode_id": source_episode,
            "action": result.get("action"),
            # G48: the ledger becomes the model<->conversation join key, and
            # `GET /conversations/recent` reads `refs.session_id` back out.
            "session_id": SESSION.session_id,
            "harness": SESSION.harness,
            "client_name": CLIENT_INFO.get("name") or None,
            "client_version": CLIENT_INFO.get("version") or None,
        },
```

Also add the stderr sanity check, called **from `main()` only** (never at import, so no test touches `~/.claude`). Put the function next to `_session_frontmatter`:

```python
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
```

…and the first line of `main()` (`mcp/server.py:295`), before the stdin loop:

```python
def main():
    """Main loop: read JSON-RPC requests from stdin, write responses to stdout."""
    _warn_if_transcript_missing()
    for line in sys.stdin:
```

- [ ] **Step 12: Run the full backend suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS, no regressions (the MCP, sources, media, and sleep suites all exercise these files).

- [ ] **Step 13: Commit**

```bash
git add mcp/server.py api/services/media_ingestor.py api/services/sleep_cycle.py \
        api/routers/sources.py api/models/schemas.py api/tests/test_session_identity.py
git commit -m "$(cat <<'EOF'
feat(mcp): stamp conversation identity on every episode Cicada captures (G48)

One SessionIdentity per MCP process (CLAUDE_CODE_SESSION_ID -> CICADA_SESSION_ID
-> minted ses_ id), stamped as session_id/harness/project_dir on save_episode and
save_url episodes, carried into the Sleep loader, and joined into agentic_write
telemetry refs alongside the client's own clientInfo. Transcripts are never read.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

## Task 2: `Cicada-Session:` commit trailer + Sleep wiring

**Files:**
- Modify: `api/services/git_service.py:25-32` (constants), `api/services/git_service.py:69-110` (`build_commit_message`, `_parse_authors`)
- Modify: `api/services/sleep_cycle.py:372-379` (the `_finalize` call site), `api/services/sleep_cycle.py:524-626` (`_finalize`)
- Test: `api/tests/test_session_trailer.py` (create)

**Interfaces:**
- Consumes: `sleep_cycle._get_unprocessed_episodes` dicts carrying `"session_id"` / `"source_id"` (Task 1).
- Produces:
  - `git_service.SESSION_TRAILER = "Cicada-Session"`
  - `git_service.MAX_SESSION_TRAILERS = 50`
  - `git_service.build_commit_message(subject: str, body_lines: list[str], authors: list[str] | None = None, sessions: list[str] | None = None) -> str`
  - `git_service._parse_sessions(body: str) -> list[str]`
  - `sleep_cycle._collect_session_ids(episodes: list[dict]) -> list[str]`
  - `sleep_cycle._finalize(..., sessions: list[str] | None = None)` (keyword-only, defaults to `None`)

- [ ] **Step 1: Write the failing trailer tests**

Create `api/tests/test_session_trailer.py`:

```python
"""G48 — the `Cicada-Session:` commit trailer.

A twin of the `Cicada-Author:` machinery (git_service.py:25-110), and inert to
the entity-line parsing by the same contract: it carries no entity id. These
tests are the regression net for "extend it, don't break it".
"""

from __future__ import annotations

from api.services import git_service, sleep_cycle


# --- build_commit_message ----------------------------------------------------


def test_sessions_emit_one_trailer_line_each_after_the_authors():
    msg = git_service.build_commit_message(
        "Sleep cycle 2026-08-31",
        ["entities/cicada.md: updated (source: ep_1, trigger: sleep/extraction)"],
        authors=["gpt-5.4-mini"],
        sessions=["0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b", "uuid-abc"],
    )
    lines = msg.splitlines()
    assert lines[-3] == "Cicada-Author: gpt-5.4-mini"
    assert lines[-2] == "Cicada-Session: 0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
    assert lines[-1] == "Cicada-Session: uuid-abc"


def test_sessions_are_deduped_in_caller_order_and_blanks_dropped():
    msg = git_service.build_commit_message(
        "s", [], sessions=["b", "a", "b", "", "  ", "a"]
    )
    assert git_service._parse_sessions(msg) == ["b", "a"]


def test_no_sessions_means_a_byte_identical_message_to_before():
    with_none = git_service.build_commit_message("s", ["x: updated"], authors=["m"])
    with_empty = git_service.build_commit_message(
        "s", ["x: updated"], authors=["m"], sessions=[]
    )
    assert with_none == with_empty
    assert "Cicada-Session" not in with_none


def test_an_id_shared_between_an_author_and_a_session_is_not_swallowed():
    msg = git_service.build_commit_message("s", [], authors=["user"], sessions=["user"])
    assert git_service._parse_authors(msg) == ["user"]
    assert git_service._parse_sessions(msg) == ["user"]


# --- _parse_sessions ---------------------------------------------------------


def test_parse_sessions_is_empty_for_a_legacy_untrailered_body():
    assert git_service._parse_sessions("Sleep cycle 2026-01-01\n\nentities/a.md: updated") == []


def test_parse_sessions_dedups_and_preserves_order():
    body = "Cicada-Session: b\nCicada-Session: a\nCicada-Session: b\n"
    assert git_service._parse_sessions(body) == ["b", "a"]


# --- regression: both trailers coexist, entity parsing unaffected ------------


def test_a_commit_with_both_trailers_still_parses_authors_and_entity_lines():
    body_lines = ["entities/mongodb.md: created (source: ep_1, trigger: sleep/extraction)"]
    msg = git_service.build_commit_message(
        "Sleep cycle 2026-08-31", body_lines,
        authors=["gpt-5.4-mini", "gpt-5.4-nano"],
        sessions=["0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"],
    )
    subject, _, body = msg.partition("\n\n")

    assert git_service._parse_authors(body) == ["gpt-5.4-mini", "gpt-5.4-nano"]
    assert git_service._infer_change_type(subject, body, "mongodb") == "created"
    description = git_service._build_description(subject, body, "mongodb")
    assert "Cicada-Session" not in description


# --- _collect_session_ids ----------------------------------------------------


def test_collect_prefers_session_id_falls_back_to_source_id_and_skips_neither():
    ids = sleep_cycle._collect_session_ids([
        {"id": "ep_1", "session_id": "sess-b", "source_id": None},
        {"id": "ep_2", "session_id": None, "source_id": "uuid-a"},
        {"id": "ep_3", "session_id": "sess-b", "source_id": "uuid-z"},
        {"id": "ep_4", "session_id": None, "source_id": None},
        {"id": "ep_5"},
    ])
    assert ids == ["sess-b", "uuid-a"]


def test_collect_is_sorted_for_a_deterministic_commit_message():
    ids = sleep_cycle._collect_session_ids([
        {"session_id": "z"}, {"session_id": "a"}, {"session_id": "m"},
    ])
    assert ids == ["a", "m", "z"]


def test_collect_caps_at_max_session_trailers():
    episodes = [{"session_id": f"s{i:04d}"} for i in range(80)]
    ids = sleep_cycle._collect_session_ids(episodes)
    assert len(ids) == git_service.MAX_SESSION_TRAILERS
    assert ids[0] == "s0000"


# --- _finalize threads them through -----------------------------------------


def test_finalize_passes_the_collected_sessions_to_build_commit_message(monkeypatch, tmp_path):
    import asyncio

    seen: dict = {}

    def fake_build(subject, body_lines, authors=None, sessions=None):
        seen["authors"] = authors
        seen["sessions"] = sessions
        return "msg"

    async def fake_status(_mp):
        return ""

    async def fake_commit(_mp, _msg):
        return "abc1234"

    monkeypatch.setattr(git_service, "build_commit_message", fake_build)
    monkeypatch.setattr(git_service, "porcelain_status", fake_status)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)

    asyncio.run(sleep_cycle._finalize(
        tmp_path, "cycle-1", [], None, sessions=["sess-a", "sess-b"],
    ))

    assert seen["sessions"] == ["sess-a", "sess-b"]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_session_trailer.py -q`
Expected: FAIL — `TypeError: build_commit_message() got an unexpected keyword argument 'sessions'`.

- [ ] **Step 3: Add the trailer machinery to `git_service.py`**

Right after the `UNKNOWN_AUTHOR = "unknown"` line (`git_service.py:28`):

```python
# Conversation trailer (G48). A twin of ``Cicada-Author:`` recording WHICH
# CONVERSATION a write came from — a Claude Code session uuid, or G20's
# per-thread export id for an imported chat. Inert to the entity-line parsing
# by the same contract as the author trailer: it carries no entity id, so
# ``_infer_change_type`` / ``_build_description`` never see it.
SESSION_TRAILER = "Cicada-Session"
_SESSION_RE = re.compile(rf"^{SESSION_TRAILER}:\s*(.+?)\s*$")

# Cap on session trailers in ONE commit. `build_commit_message` does not cap —
# the call site does (sleep_cycle._collect_session_ids), so a caller that
# genuinely wants every id can have it. 50 distinct conversations consolidated
# in a single Sleep is effectively unreachable; when it happens, the trailer
# degrades (the click-through affordance loses the overflow) while
# `GET /conversations/recent` stays complete — it reads episodes, not commits.
MAX_SESSION_TRAILERS = 50
```

Replace `build_commit_message` (`git_service.py:69-96`) with:

```python
def build_commit_message(
    subject: str,
    body_lines: list[str],
    authors: list[str] | None = None,
    sessions: list[str] | None = None,
) -> str:
    """Assemble a structured commit message with optional trailers.

    ``subject`` is line 1, ``body_lines`` are the per-file manifest. Each
    distinct, non-empty ``authors`` entry becomes one ``Cicada-Author:`` line
    and each distinct, non-empty ``sessions`` entry one ``Cicada-Session:``
    line, in that order, in ONE trailer block after a blank line (git-trailer
    convention). Caller order is preserved and duplicates are dropped, per
    list independently — an author id equal to a session id emits both.
    """
    parts = [subject]
    if body_lines:
        parts.append("\n".join(body_lines))

    trailers: list[str] = []

    seen_authors: set[str] = set()
    for a in authors or []:
        name = (a or "").strip()
        if not name or name in seen_authors:
            continue
        seen_authors.add(name)
        trailers.append(f"{AUTHOR_TRAILER}: {name}")

    seen_sessions: set[str] = set()
    for s in sessions or []:
        sid = (s or "").strip()
        if not sid or sid in seen_sessions:
            continue
        seen_sessions.add(sid)
        trailers.append(f"{SESSION_TRAILER}: {sid}")

    if trailers:
        parts.append("\n".join(trailers))

    return "\n\n".join(parts)
```

And the parser twin, right after `_parse_authors` (`git_service.py:110`):

```python
def _parse_sessions(body: str) -> list[str]:
    """Extract conversation ids from ``Cicada-Session:`` trailer lines."""
    out: list[str] = []
    seen: set[str] = set()
    for line in body.splitlines():
        m = _SESSION_RE.match(line.strip())
        if m:
            sid = m.group(1).strip()
            if sid and sid not in seen:
                seen.add(sid)
                out.append(sid)
    return out
```

- [ ] **Step 4: Collect and thread the sessions in `sleep_cycle.py`**

Add the pure helper immediately above `_finalize` (`sleep_cycle.py:524`):

```python
def _collect_session_ids(episodes: list[dict]) -> list[str]:
    """Distinct conversation ids for the episodes consolidated this cycle.

    ``session_id`` (MCP capture, G48) wins over ``source_id`` (G20 export
    thread id); an episode with neither contributes nothing. Sorted so the
    commit message is deterministic, and capped at
    ``git_service.MAX_SESSION_TRAILERS`` so one enormous cycle can't grow the
    message without bound.
    """
    seen: set[str] = set()
    for ep in episodes:
        sid = str(ep.get("session_id") or ep.get("source_id") or "").strip()
        if sid:
            seen.add(sid)
    ids = sorted(seen)
    if len(ids) > git_service.MAX_SESSION_TRAILERS:
        logger.warning(
            f"{len(ids)} conversations in one cycle — recording the first "
            f"{git_service.MAX_SESSION_TRAILERS} as Cicada-Session trailers; "
            "GET /conversations/recent stays complete"
        )
        ids = ids[: git_service.MAX_SESSION_TRAILERS]
    return ids
```

Extend `_finalize`'s signature (`sleep_cycle.py:524-533`) with one keyword-only parameter:

```python
async def _finalize(
    memory_path: Path,
    cycle_id: str,
    changes: list,
    settings: Settings | None = None,
    *,
    organic_resolution_paths: set[str] | None = None,
    started: float | None = None,
    engine: str = "litellm",
    sessions: list[str] | None = None,
) -> None:
```

Add to its docstring, after the `organic_resolution_paths` paragraph:

```
    ``sessions`` (G48): the distinct conversation ids whose episodes this cycle
    consolidated, recorded as ``Cicada-Session:`` trailers. User-action commits
    (inbox_service, entities router) stay session-less by design — they are
    ``Cicada-Author: user`` writes with no conversation behind them.
```

Replace the `build_commit_message` call (`sleep_cycle.py:599-601`):

```python
    message = git_service.build_commit_message(
        f"Sleep cycle {date_str}", body_lines, authors=authors, sessions=sessions or []
    )
```

Add one ref to the existing `sleep_run` telemetry event (`sleep_cycle.py:617-625`) — a **count only**, never the ids, so the ledger stays small:

```python
            "skills_detected": _state.skills_detected,
            "session_count": len(sessions or []),
```

And the call site (`sleep_cycle.py:372-379`), right after `_mark_episodes_processed(processed_episodes)` computes `processed_episodes`:

```python
        await _finalize(
            memory_path,
            cycle_id,
            changes,
            settings,
            organic_resolution_paths=organic_resolution_paths,
            started=_state.started_monotonic,
            sessions=_collect_session_ids(processed_episodes),
        )
```

- [ ] **Step 5: Run the tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_session_trailer.py -q`
Expected: PASS (11 tests).

- [ ] **Step 6: Run the trailer-adjacent regression suites**

Run: `api/.venv/bin/python -m pytest api/tests/test_contributors.py api/tests/test_contributor_commits.py api/tests/test_sleep_cycle_claims_wired.py api/tests/test_run_events.py -q`
Expected: PASS — nothing about author parsing or entity-line parsing moved.

- [ ] **Step 7: Commit**

```bash
git add api/services/git_service.py api/services/sleep_cycle.py api/tests/test_session_trailer.py
git commit -m "$(cat <<'EOF'
feat(git): Cicada-Session commit trailer, written by the Sleep cycle (G48)

build_commit_message gains sessions= mirroring authors= (dedup, caller order,
one trailer block); _parse_sessions is its twin. _finalize records the distinct
session_id/source_id of the episodes it consolidated, capped at 50 and sorted.
Inert to entity-line parsing — the trailer carries no entity id.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

## Task 3: `session_stats.py` + `GET /conversations/recent`

**Files:**
- Create: `api/services/session_stats.py`
- Modify: `api/models/schemas.py` (append `ConversationSummary` after `OriginsResponse`, ~`schemas.py:214`)
- Modify: `api/routers/conversations.py` (imports at `conversations.py:1-13`; new route after the upload route, `conversations.py:73`)
- Test: `api/tests/test_session_stats.py` (create)

**Interfaces:**
- Consumes: episode frontmatter keys from Task 1 (`session_id`, `harness`, `project_dir`) and the pre-existing G20 `source_id`.
- Produces:
  - `session_stats.SESSION_UUID_RE`, `session_stats.is_uuid(value: str) -> bool`
  - `session_stats.project_slug(project_dir: str) -> str`
  - `session_stats.transcripts_root() -> Path`
  - `session_stats.default_transcript_exists(project_dir: str | None, session_id: str, *, root: Path | None = None) -> bool`
  - `session_stats.MAX_CONVERSATION_ENTITIES = 12`
  - `session_stats.aggregate_conversations(memory_path: Path, *, limit: int = 20, transcript_exists=default_transcript_exists, models: dict[str, str] | None = None) -> list[dict]` — snake_case dicts matching `ConversationSummary`'s field names
  - `session_stats.find_conversation(memory_path: Path, conversation_id: str) -> dict | None` — same keys **plus** `project_dir`
  - `schemas.ConversationSummary` (CamelModel)
  - `api.routers.conversations.transcript_exists` — module-level injectable seam
  - `GET /conversations/recent?limit=20` → `list[ConversationSummary]`, ETag'd

- [ ] **Step 1: Write the failing pure-aggregation tests**

Create `api/tests/test_session_stats.py`:

```python
"""G48 — grouping episodes into conversations.

Hermetic: throwaway banks under tmp_path, a fake transcript root under tmp_path,
and an injected `transcript_exists`. The real ~/.claude is never touched, and no
transcript is ever opened — this module only ever calls os.path.isfile.
"""

from __future__ import annotations

import pytest

from api.services import bank_index, session_stats

UUID_A = "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
UUID_B = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


def _episode(memory, episode_id, *, timestamp, session_id=None, source_id=None,
             harness=None, project_dir=None, origin=None, title="Untitled"):
    episodes_dir = memory / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"id: {episode_id}", f"timestamp: '{timestamp}'",
             f"title: {title}", "processed: true"]
    for key, value in (("session_id", session_id), ("source_id", source_id),
                       ("harness", harness), ("project_dir", project_dir),
                       ("origin", origin)):
        if value is not None:
            lines.append(f"{key}: {value}")
    lines += ["---", "", "body"]
    (episodes_dir / f"{episode_id}.md").write_text("\n".join(lines), encoding="utf-8")


def _entity(memory, entity_id, source_episodes):
    entities_dir = memory / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    eps = "\n".join(f"- {e}" for e in source_episodes) or "[]"
    (entities_dir / f"{entity_id}.md").write_text(
        f"---\nid: {entity_id}\ntype: concept\nstatus: active\n"
        f"source_episodes:\n{eps}\n---\n\n# {entity_id}\n",
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _fresh_index():
    bank_index.invalidate()
    yield
    bank_index.invalidate()


def _never(_project_dir, _session_id, *, root=None):
    return False


# --- grouping ----------------------------------------------------------------


def test_no_episodes_dir_is_an_empty_list(tmp_path):
    memory = tmp_path / "memory"
    memory.mkdir()
    assert session_stats.aggregate_conversations(memory, transcript_exists=_never) == []


def test_episodes_group_by_session_id_and_count(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A, title="First")
    _episode(memory, "ep_2", timestamp="2026-08-30T12:00:00Z", session_id=UUID_A, title="Second")
    _episode(memory, "ep_3", timestamp="2026-08-29T09:00:00Z", session_id=UUID_B, title="Other")

    rows = {r["conversation_id"]: r
            for r in session_stats.aggregate_conversations(memory, transcript_exists=_never)}

    assert rows[UUID_A]["episode_count"] == 2
    assert rows[UUID_A]["kind"] == "mcp"
    assert rows[UUID_A]["title"] == "First", "title comes from the EARLIEST episode"
    assert rows[UUID_A]["first_seen"] == "2026-08-30T10:00:00Z"
    assert rows[UUID_A]["last_seen"] == "2026-08-30T12:00:00Z"


def test_an_import_thread_groups_on_source_id_and_is_kind_import(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", source_id="uuid-abc",
             origin="claude-export", title="Thesis planning")

    row = session_stats.aggregate_conversations(memory, transcript_exists=_never)[0]
    assert row["conversation_id"] == "uuid-abc"
    assert row["kind"] == "import"
    assert row["origin"] == "claude-export"
    assert row["resumable"] is False


def test_session_id_wins_when_an_episode_carries_both_keys(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z",
             session_id=UUID_A, source_id="uuid-abc")

    rows = session_stats.aggregate_conversations(memory, transcript_exists=_never)
    assert [r["conversation_id"] for r in rows] == [UUID_A]
    assert rows[0]["kind"] == "mcp"


def test_an_episode_with_neither_key_simply_does_not_appear(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z")
    assert session_stats.aggregate_conversations(memory, transcript_exists=_never) == []


def test_rows_are_sorted_by_last_seen_descending(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-28T10:00:00Z", session_id=UUID_A)
    _episode(memory, "ep_2", timestamp="2026-08-31T10:00:00Z", session_id=UUID_B)

    rows = session_stats.aggregate_conversations(memory, transcript_exists=_never)
    assert [r["conversation_id"] for r in rows] == [UUID_B, UUID_A]


def test_limit_truncates_after_sorting(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-28T10:00:00Z", session_id=UUID_A)
    _episode(memory, "ep_2", timestamp="2026-08-31T10:00:00Z", session_id=UUID_B)

    rows = session_stats.aggregate_conversations(memory, limit=1, transcript_exists=_never)
    assert [r["conversation_id"] for r in rows] == [UUID_B]


def test_harness_and_project_dir_come_from_the_stamped_episodes(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A,
             harness="claude-code", project_dir="/Users/x/p", origin="mcp")

    row = session_stats.aggregate_conversations(memory, transcript_exists=_never)[0]
    assert row["harness"] == "claude-code"
    assert row["origin"] == "mcp"
    assert "project_dir" not in row, "project_dir never crosses /conversations/recent"


# --- entity credit -----------------------------------------------------------


def test_entities_are_credited_transitively_through_source_episodes(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)
    _episode(memory, "ep_2", timestamp="2026-08-30T11:00:00Z", session_id=UUID_B)
    _entity(memory, "sqlite-vec", ["ep_1", "ep_2"])
    _entity(memory, "cicada", ["ep_1"])
    _entity(memory, "ghost", ["ep_missing"])

    rows = {r["conversation_id"]: r
            for r in session_stats.aggregate_conversations(memory, transcript_exists=_never)}

    assert rows[UUID_A]["entity_ids"] == ["cicada", "sqlite-vec"]
    assert rows[UUID_A]["entity_count"] == 2
    assert rows[UUID_B]["entity_ids"] == ["sqlite-vec"]


def test_entity_ids_are_capped_with_an_honest_total(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)
    for i in range(30):
        _entity(memory, f"e{i:02d}", ["ep_1"])

    row = session_stats.aggregate_conversations(memory, transcript_exists=_never)[0]
    assert len(row["entity_ids"]) == session_stats.MAX_CONVERSATION_ENTITIES
    assert row["entity_count"] == 30


# --- slug + resumable --------------------------------------------------------


def test_project_slug_maps_every_non_alphanumeric_char_to_a_dash():
    assert session_stats.project_slug("<repo>/") == \
        "-Users-rorosaga-Documents-roros-lab-cicada"


def test_project_slug_handles_a_path_containing_a_dot():
    # Asserted from the "every non-alphanumeric -> '-'" rule. VERIFIED LIVE in
    # Task 6 of this plan; if the observation differs, Task 6 corrects BOTH
    # project_slug and this test.
    assert session_stats.project_slug("/Users/x/a.b/c") == "-Users-x-a-b-c"


def test_transcript_exists_is_isfile_only_under_the_injected_root(tmp_path):
    root = tmp_path / "projects"
    slug_dir = root / "-Users-x-p"
    slug_dir.mkdir(parents=True)
    (slug_dir / f"{UUID_A}.jsonl").write_text("", encoding="utf-8")

    assert session_stats.default_transcript_exists("/Users/x/p", UUID_A, root=root) is True
    assert session_stats.default_transcript_exists("/Users/x/p", UUID_B, root=root) is False
    assert session_stats.default_transcript_exists(None, UUID_A, root=root) is False


def test_a_subagent_transcript_directory_is_not_a_session(tmp_path):
    root = tmp_path / "projects"
    (root / "-Users-x-p" / f"{UUID_A}" / "subagents").mkdir(parents=True)
    assert session_stats.default_transcript_exists("/Users/x/p", UUID_A, root=root) is False


def test_a_minted_ses_id_is_never_resumable_even_with_a_file_present(tmp_path):
    root = tmp_path / "projects"
    slug_dir = root / "-Users-x-p"
    slug_dir.mkdir(parents=True)
    (slug_dir / "ses_2026-08-31_deadbeef.jsonl").write_text("", encoding="utf-8")

    assert session_stats.default_transcript_exists(
        "/Users/x/p", "ses_2026-08-31_deadbeef", root=root
    ) is False


def test_resumable_uses_the_injected_probe(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A,
             harness="claude-code", project_dir="/Users/x/p")
    _episode(memory, "ep_2", timestamp="2026-08-30T10:00:00Z", session_id=UUID_B,
             harness="claude-code", project_dir="/Users/x/p")

    def only_a(project_dir, session_id, *, root=None):
        return session_id == UUID_A

    rows = {r["conversation_id"]: r
            for r in session_stats.aggregate_conversations(memory, transcript_exists=only_a)}
    assert rows[UUID_A]["resumable"] is True
    assert rows[UUID_B]["resumable"] is False


# --- model join --------------------------------------------------------------


def test_model_comes_from_the_latest_telemetry_event_for_that_session(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)

    row = session_stats.aggregate_conversations(
        memory, transcript_exists=_never, models={UUID_A: "gpt-5.4-mini"}
    )[0]
    assert row["model"] == "gpt-5.4-mini"


def test_model_is_none_when_the_ledger_knows_nothing(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)
    row = session_stats.aggregate_conversations(memory, transcript_exists=_never, models={})[0]
    assert row["model"] is None


# --- find_conversation -------------------------------------------------------


def test_find_conversation_returns_the_project_dir(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A,
             harness="claude-code", project_dir="/Users/x/p")

    found = session_stats.find_conversation(memory, UUID_A)
    assert found is not None and found["project_dir"] == "/Users/x/p"
    assert session_stats.find_conversation(memory, UUID_B) is None
```

- [ ] **Step 2: Run them and watch them fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_session_stats.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.services.session_stats'`.

- [ ] **Step 3: Write `api/services/session_stats.py`**

```python
"""Conversation-level provenance aggregation (G48) — "which conversation
produced this memory".

An ``origin_stats.py`` clone, one axis over: where that module groups episodes
by *capture origin* (mcp / telegram / claude-export), this one groups them by
*conversation* — the ``session_id`` an MCP client stamped at capture, or G20's
``source_id`` for an imported chat thread. Entities are credited transitively
through ``source_episodes``, exactly as in ``origin_stats.aggregate_origins``.

PRIVACY: transcripts are NEVER read. The only filesystem contact with
``~/.claude`` in this entire feature is the ``os.path.isfile`` inside
:func:`default_transcript_exists`. No transcript content, and no transcript
path, is returned, logged, or written to a bank.
"""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from pathlib import Path

from api.services import bank_index

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

# How far back the telemetry ledger is read for the best-effort ``model``.
TELEMETRY_LOOKBACK_DAYS = 90


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


def models_by_session(lookback_days: int = TELEMETRY_LOOKBACK_DAYS) -> dict[str, str]:
    """conversation id -> model of the most recent telemetry event citing it.

    Best-effort by design: returns ``{}`` when telemetry is off, unreadable, or
    simply has nothing for a session. Never raises.
    """
    try:
        from api.services import telemetry

        events = telemetry.read_events(start=date.today() - timedelta(days=lookback_days))
    except Exception:
        return {}

    latest: dict[str, tuple[str, str]] = {}
    for ev in events:
        refs = ev.refs or {}
        sid = str(refs.get("session_id") or "").strip()
        model = (ev.model or "").strip()
        if not sid or not model:
            continue
        prev = latest.get(sid)
        if prev is None or ev.ts >= prev[0]:
            latest[sid] = (ev.ts, model)
    return {sid: model for sid, (_ts, model) in latest.items()}


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
        for ep_id in fm.get("source_episodes", []) or []:
            conversation_id = episode_conversation.get(ep_id)
            if conversation_id:
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


def _project(group: dict, *, transcript_exists, models: dict[str, str]) -> dict:
    """One group -> the public row. ``project_dir`` is deliberately dropped."""
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
        "model": models.get(group["conversation_id"]),
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
    models: dict[str, str] | None = None,
) -> list[dict]:
    """Recent conversations, newest write first.

    Returns snake_case dicts matching ``schemas.ConversationSummary``'s field
    names (``CamelModel`` has ``populate_by_name=True``, so
    ``ConversationSummary(**row)`` just works). ``project_dir`` is NOT included
    — only the resume endpoint ever sees it.
    """
    groups = _group(Path(memory_path))
    if models is None:
        models = models_by_session()
    rows = [
        _project(g, transcript_exists=transcript_exists, models=models)
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
```

- [ ] **Step 4: Run the pure tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_session_stats.py -q`
Expected: PASS (19 tests).

- [ ] **Step 5: Write the failing endpoint tests**

Append to `api/tests/test_session_stats.py`:

```python
# --- GET /conversations/recent ----------------------------------------------


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main
    from api.routers import conversations as conv

    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True, exist_ok=True)
    (memory / "entities").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setattr(conv, "transcript_exists", _never)
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_recent_endpoint_returns_camel_case_rows(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A,
             harness="claude-code", project_dir="/Users/x/p", title="Index choice")
    _entity(memory, "sqlite-vec", ["ep_1"])
    bank_index.invalidate()

    resp = client.get("/conversations/recent")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list) and len(body) == 1
    row = body[0]
    assert row["conversationId"] == UUID_A
    assert row["kind"] == "mcp"
    assert row["harness"] == "claude-code"
    assert row["title"] == "Index choice"
    assert row["episodeCount"] == 1
    assert row["entityIds"] == ["sqlite-vec"]
    assert row["entityCount"] == 1
    assert row["resumable"] is False
    assert "projectDir" not in row, "project_dir must never cross this endpoint"


def test_recent_endpoint_honours_limit(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    _episode(memory, "ep_1", timestamp="2026-08-28T10:00:00Z", session_id=UUID_A)
    _episode(memory, "ep_2", timestamp="2026-08-31T10:00:00Z", session_id=UUID_B)
    bank_index.invalidate()

    body = client.get("/conversations/recent?limit=1").json()
    assert [r["conversationId"] for r in body] == [UUID_B]


def test_recent_endpoint_304s_on_an_unchanged_bank(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)
    bank_index.invalidate()

    first = client.get("/conversations/recent")
    etag = first.headers["ETag"]
    second = client.get("/conversations/recent", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""


def test_a_different_limit_gets_a_different_etag(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)
    bank_index.invalidate()

    a = client.get("/conversations/recent?limit=5").headers["ETag"]
    b = client.get("/conversations/recent?limit=20").headers["ETag"]
    assert a != b
```

- [ ] **Step 6: Run them and watch them fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_session_stats.py -q`
Expected: FAIL — the endpoint tests get `404 Not Found` (and `AttributeError` on `conv.transcript_exists`).

- [ ] **Step 7: Add the schema**

`api/models/schemas.py`, right after `OriginsResponse` (~`schemas.py:214`):

```python
# --- Conversations (G48 conversation-level provenance) ---------------------


class ConversationSummary(CamelModel):
    """One conversation that wrote to memory — a live MCP session or an
    imported chat thread.

    ``conversation_id`` is the stamped ``session_id`` (kind ``"mcp"``) or G20's
    ``source_id`` (kind ``"import"``). ``entity_ids`` is CAPPED
    (``session_stats.MAX_CONVERSATION_ENTITIES``) with the honest total in
    ``entity_count``, so the app can say "+N more". ``project_dir`` is
    deliberately absent — it is returned only by the resume endpoint, which
    needs a cwd to launch. ``resumable`` is computed per request and never
    persisted.
    """

    conversation_id: str
    kind: str = "mcp"  # "mcp" | "import"
    harness: str = ""
    origin: str = ""
    title: str = ""
    first_seen: str = ""
    last_seen: str = ""
    episode_count: int = 0
    entity_ids: list[str] = []
    entity_count: int = 0
    model: Optional[str] = None
    resumable: bool = False
```

- [ ] **Step 8: Add the route**

`api/routers/conversations.py` — extend the import block at the top (`conversations.py:1-13`):

```python
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, UploadFile
from loguru import logger
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import ConversationSummary, ConversationUploadResponse
from api.services import markdown_parser, session_stats, sync_service

router = APIRouter()

# Injectable seam: tests replace this with a fake so no test ever probes the
# real ``~/.claude``. Production always resolves to the isfile() probe.
transcript_exists = session_stats.default_transcript_exists
```

Then, immediately after the `upload_conversation` route body ends (`conversations.py:73`, before the `# --- Source Detection ---` comment):

```python
@router.get("/conversations/recent", response_model=list[ConversationSummary])
async def recent_conversations(
    request: Request,
    response: Response,
    limit: int = Query(20, ge=1, le=200),
    settings: Settings = Depends(get_settings),
):
    """Conversations that wrote to memory, newest write first (G48).

    Live MCP sessions and imported chat threads on one axis. Only ids,
    timestamps, counts and entity ids cross the wire — never a transcript,
    never a transcript path, never ``project_dir``.

    ETag folds in ``telemetry`` because the row carries a telemetry-derived
    ``model``. KNOWN CAVEAT: deleting a transcript flips no version-vector
    component, so ``resumable`` can read stale until the next non-304 refresh —
    acceptable because ``POST /conversations/{id}/resume`` re-validates.
    """
    etag = sync_service.etag_for(
        settings.memory_path, "episodes", "entities", "telemetry", extra=f"limit={limit}"
    )
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early

    rows = await run_in_threadpool(
        session_stats.aggregate_conversations,
        settings.memory_path,
        limit=limit,
        transcript_exists=transcript_exists,
    )
    return [ConversationSummary(**row) for row in rows]
```

- [ ] **Step 9: Run the file, then the suite**

Run: `api/.venv/bin/python -m pytest api/tests/test_session_stats.py -q`
Expected: PASS (23 tests).

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add api/services/session_stats.py api/routers/conversations.py \
        api/models/schemas.py api/tests/test_session_stats.py
git commit -m "$(cat <<'EOF'
feat(api): GET /conversations/recent — memory grouped by conversation (G48)

session_stats.py is an origin_stats clone keyed on session_id or source_id:
live MCP sessions and imported threads on one axis, entities credited through
source_episodes, entity ids capped at 12 with an honest total. `resumable` is a
strict-UUID gate plus an injectable isfile() probe — transcripts are never read
and project_dir never crosses the wire. ETag'd, 304s on an unchanged bank.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

## Task 4: `sessions` on entity-history commits and contributor commits

**Files:**
- Modify: `api/models/schemas.py:127-139` (`EntityHistoryEntry`), `api/models/schemas.py:166-187` (`ContributorCommit`)
- Modify: `api/services/git_service.py:283-297` (`get_entity_history` entry construction), `api/services/git_service.py:544-567` (`get_contributor_commits` record loop)
- Test: `api/tests/test_session_provenance_views.py` (create)

**Interfaces:**
- Consumes: `git_service._parse_sessions(body: str) -> list[str]` (Task 2).
- Produces:
  - `schemas.EntityHistoryEntry.sessions: list[str] = []`
  - `schemas.ContributorCommit.sessions: list[str] = []`
  - Both populated from the commit body's `Cicada-Session:` trailer; `[]` for every pre-G48 commit.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_session_provenance_views.py`:

```python
"""G48 §4 — a commit's conversations reach the history + contributors views.

Hermetic: a throwaway git repo per test with hand-crafted trailers. The real
memory/ bank is never read.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.services import git_service

UUID_A = "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
UUID_B = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


def run(coro):
    return asyncio.run(coro)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "memory"
    (r / "entities").mkdir(parents=True)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "test@cicada.local")
    _git(r, "config", "user.name", "Cicada Test")
    return r


def _commit(repo: Path, rel: str, text: str, subject: str, lines: list[str],
            authors=None, sessions=None) -> str:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", "--", rel)
    message = git_service.build_commit_message(
        subject, lines, authors=authors, sessions=sessions
    )
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def test_entity_history_carries_the_commits_sessions(repo):
    _commit(
        repo, "entities/mongodb.md", "---\nid: mongodb\n---\n\n# MongoDB\n",
        "Sleep cycle 2026-08-31",
        ["entities/mongodb.md: created (source: ep_1, trigger: sleep/extraction)"],
        authors=["gpt-5.4-mini"], sessions=[UUID_A, UUID_B],
    )

    entries = run(git_service.get_entity_history("mongodb", repo))
    assert len(entries) == 1
    assert entries[0].author == "gpt-5.4-mini"
    assert entries[0].sessions == [UUID_A, UUID_B]
    assert entries[0].change_type == "created", "entity-line parsing still works"


def test_entity_history_of_a_pre_g48_commit_has_no_sessions(repo):
    _commit(
        repo, "entities/mongodb.md", "---\nid: mongodb\n---\n\n# MongoDB\n",
        "Sleep cycle 2026-01-01",
        ["entities/mongodb.md: created (source: ep_1, trigger: sleep/extraction)"],
        authors=["gpt-5.4-mini"],
    )
    entries = run(git_service.get_entity_history("mongodb", repo))
    assert entries[0].sessions == []


def test_contributor_commits_carry_the_sessions(repo):
    _commit(
        repo, "entities/cicada.md", "---\nid: cicada\n---\n\n# Cicada\n",
        "Sleep cycle 2026-08-31",
        ["entities/cicada.md: updated (source: ep_1, trigger: sleep/extraction)"],
        authors=["gpt-5.4-mini"], sessions=[UUID_A],
    )

    commits = run(git_service.get_contributor_commits(repo, "gpt-5.4-mini"))
    assert len(commits) == 1
    assert commits[0].sessions == [UUID_A]
    assert commits[0].entities == ["cicada"]


def test_a_user_commit_has_no_sessions(repo):
    _commit(
        repo, "entities/cicada.md", "---\nid: cicada\n---\n\n# Cicada\n",
        "Add fact source", ["entities/cicada.md: updated (trigger: user/companion_app)"],
        authors=["user"],
    )
    commits = run(git_service.get_contributor_commits(repo, "user"))
    assert commits[0].sessions == []
```

- [ ] **Step 2: Run them and watch them fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_session_provenance_views.py -q`
Expected: FAIL — `AttributeError: 'EntityHistoryEntry' object has no attribute 'sessions'`.

- [ ] **Step 3: Add the fields**

`api/models/schemas.py:137-139` — append to `EntityHistoryEntry`, after `diff`:

```python
    # G48: the conversations that produced this commit, parsed from its
    # ``Cicada-Session:`` trailers. Empty for every pre-G48 commit and for
    # user-action writes, so the app's "from conversation" affordance simply
    # doesn't render there.
    sessions: list[str] = []
```

`api/models/schemas.py:187` — append to `ContributorCommit`, after `files_changed`:

```python
    # G48: same trailer, same contract as EntityHistoryEntry.sessions.
    sessions: list[str] = []
```

- [ ] **Step 4: Populate them**

`api/services/git_service.py:290-297` — the `EntityHistoryEntry(...)` construction in `get_entity_history`:

```python
        entries.append(EntityHistoryEntry(
            date=date,
            change_type=change_type,
            description=description,
            author=author,
            commit_hash=commit_hash,
            diff=diff,
            sessions=_parse_sessions(body),
        ))
```

`api/services/git_service.py:557-567` — the `ContributorCommit(...)` construction in `get_contributor_commits`:

```python
        commits.append(
            ContributorCommit(
                commit_hash=commit_hash.strip(),
                date=date_str.strip(),
                subject=subject.strip(),
                # Capped for the wire; the honest count rides alongside it.
                entities=entities[:MAX_COMMIT_ENTITIES],
                entities_total=len(entities),
                files_changed=len(files),
                sessions=_parse_sessions(body),
            )
        )
```

- [ ] **Step 5: Run the tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_session_provenance_views.py api/tests/test_contributor_commits.py api/tests/test_contributors.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/models/schemas.py api/services/git_service.py api/tests/test_session_provenance_views.py
git commit -m "$(cat <<'EOF'
feat(api): entity history + contributor commits report their conversations (G48)

EntityHistoryEntry.sessions and ContributorCommit.sessions carry the parsed
Cicada-Session: trailer. Empty for pre-G48 and user-action commits, so the
click-through affordance simply doesn't render there.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

## Task 5: `POST /conversations/{id}/resume`

**Files:**
- Modify: `api/models/schemas.py` (append `ResumeDescriptor` after `ConversationSummary`)
- Modify: `api/routers/conversations.py` (new route directly under `recent_conversations`)
- Test: `api/tests/test_conversation_resume.py` (create)

**Interfaces:**
- Consumes: `session_stats.is_uuid`, `session_stats.find_conversation`, and the module-level injectable `conversations.transcript_exists` (Task 3).
- Produces:
  - `schemas.ResumeDescriptor` — `mode: str = "terminal"`, `argv: list[str] = []`, `cwd: Optional[str] = None`, `display_command: str = ""` (wire: `mode`, `argv`, `cwd`, `displayCommand`)
  - `conversations.CLAUDE_BINARY = "claude"`
  - `conversations.CWD_SAFE_RE`
  - `POST /conversations/{conversation_id}/resume` → 200 / 400 / 404 / 409

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_conversation_resume.py`:

```python
"""G48 §5 — the resume endpoint validates; the app launches.

Hermetic: a tmp_path bank plus an injected `transcript_exists`. The real
~/.claude is never probed, and nothing here ever opens a transcript.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.routers import conversations as conv
from api.services import bank_index

UUID_A = "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
UUID_B = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


def _episode(memory, episode_id, *, session_id, project_dir=None, timestamp="2026-08-30T10:00:00Z"):
    episodes_dir = memory / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"id: {episode_id}", f"timestamp: '{timestamp}'",
             "title: A chat", "processed: true", f"session_id: {session_id}",
             "harness: claude-code"]
    if project_dir is not None:
        lines.append(f"project_dir: {project_dir}")
    lines += ["---", "", "body"]
    (episodes_dir / f"{episode_id}.md").write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setattr(conv, "transcript_exists", lambda pd, sid, root=None: True)
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()
    bank_index.invalidate()


def test_malformed_id_is_400(client):
    c, _ = client
    assert c.post("/conversations/not-a-uuid/resume").status_code == 400


def test_a_minted_ses_id_is_400_by_construction(client):
    c, memory = client
    _episode(memory, "ep_1", session_id="ses_2026-08-31_deadbeef", project_dir=str(memory))
    bank_index.invalidate()
    assert c.post("/conversations/ses_2026-08-31_deadbeef/resume").status_code == 400


def test_an_unknown_conversation_is_404(client):
    c, _ = client
    assert c.post(f"/conversations/{UUID_B}/resume").status_code == 404


def test_a_retention_cleaned_transcript_is_409_transcript_gone(client, monkeypatch):
    c, memory = client
    _episode(memory, "ep_1", session_id=UUID_A, project_dir=str(memory))
    bank_index.invalidate()
    monkeypatch.setattr(conv, "transcript_exists", lambda pd, sid, root=None: False)

    resp = c.post(f"/conversations/{UUID_A}/resume")
    assert resp.status_code == 409
    assert resp.json()["detail"]["reason"] == "transcript_gone"


def test_a_live_session_returns_the_argv_descriptor(client):
    c, memory = client
    _episode(memory, "ep_1", session_id=UUID_A, project_dir=str(memory))
    bank_index.invalidate()

    body = c.post(f"/conversations/{UUID_A}/resume").json()
    assert body["mode"] == "terminal"
    assert body["argv"] == ["claude", "--resume", UUID_A]
    assert body["cwd"] == str(memory)
    assert body["displayCommand"] == f"claude --resume {UUID_A}"


def test_a_cwd_failing_the_charset_gate_is_omitted(client):
    c, memory = client
    _episode(memory, "ep_1", session_id=UUID_A, project_dir="/Users/x/weird$dir")
    bank_index.invalidate()

    body = c.post(f"/conversations/{UUID_A}/resume").json()
    assert body["cwd"] is None
    assert body["argv"] == ["claude", "--resume", UUID_A]


def test_a_cwd_that_no_longer_exists_is_omitted(client):
    c, memory = client
    _episode(memory, "ep_1", session_id=UUID_A, project_dir=str(memory / "gone"))
    bank_index.invalidate()

    assert c.post(f"/conversations/{UUID_A}/resume").json()["cwd"] is None


def test_a_relative_cwd_is_refused(client):
    c, memory = client
    _episode(memory, "ep_1", session_id=UUID_A, project_dir="relative/path")
    bank_index.invalidate()

    assert c.post(f"/conversations/{UUID_A}/resume").json()["cwd"] is None
```

- [ ] **Step 2: Run them and watch them fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_conversation_resume.py -q`
Expected: FAIL — every request 405/404 (no such route).

- [ ] **Step 3: Add the schema**

`api/models/schemas.py`, directly after `ConversationSummary`:

```python
class ResumeDescriptor(CamelModel):
    """How to reopen a conversation. The BACKEND validates; the APP launches.

    ``argv`` is a fixed list — never a shell string — whose head is the literal
    binary name ``claude`` (never API-configurable). ``cwd`` is present only
    when the stamped ``project_dir`` passed a conservative charset gate AND
    still exists; the app falls back to ``$HOME`` when it is null.
    """

    mode: str = "terminal"
    argv: list[str] = []
    cwd: Optional[str] = None
    display_command: str = ""
```

- [ ] **Step 4: Add the route**

`api/routers/conversations.py` — add two module-level constants next to the `transcript_exists` seam:

```python
# The binary name is a FIXED LITERAL. Never read from settings, env, or a
# request body: it is the head of an argv list the app executes.
CLAUDE_BINARY = "claude"

# Conservative cwd charset. A path that fails this is dropped rather than
# sanitised, because it is about to be interpolated into AppleScript source
# on the app side.
CWD_SAFE_RE = re.compile(r"^[A-Za-z0-9/_.~-]+$")
```

…add `import re` to the file's stdlib imports (`conversations.py:1-4` currently has `hashlib`, `json`, `datetime`, `pathlib`), extend the schema import to `from api.models.schemas import ConversationSummary, ConversationUploadResponse, ResumeDescriptor`, and add the route directly under `recent_conversations`:

```python
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
```

- [ ] **Step 5: Run the tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_conversation_resume.py -q`
Expected: PASS (8 tests).

- [ ] **Step 6: Confirm both new endpoints are token-gated**

Run: `api/.venv/bin/python -m pytest api/tests/test_auth.py -q`
Expected: PASS. Then confirm by inspection that `api/services/auth.py:28`'s `_OPEN_PATHS` still reads exactly `frozenset({"/healthz", "/capture/telegram"})` — neither new path may be added to it.

- [ ] **Step 7: Run the full suite and commit**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS.

```bash
git add api/routers/conversations.py api/models/schemas.py api/tests/test_conversation_resume.py
git commit -m "$(cat <<'EOF'
feat(api): POST /conversations/{id}/resume — validated launch descriptor (G48)

Strict-UUID gate (400), unknown conversation (404), retention-cleaned transcript
(409 transcript_gone), else a fixed argv list headed by the literal `claude`
plus a charset-gated, must-exist cwd. Transcripts are never opened.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

## Task 6: LIVE verification spike — Ghostty AppleScript + dot-path slug

This task is **manual-ish and machine-specific**: it runs on this Mac (Ghostty 1.3.1 at `/Applications/Ghostty.app`, Claude Code v2.1.251) and turns two unverified assumptions into verified constants. It must complete before Task 7 hard-wires either.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Services/TerminalLauncher.swift`
- Create: `app/CicadaApp/Tests/CicadaAppTests/TerminalLaunchScriptTests.swift`
- Possibly modify: `api/services/session_stats.py` (`project_slug`) and `api/tests/test_session_stats.py::test_project_slug_handles_a_path_containing_a_dot` — **only if** the live observation contradicts them.

**Interfaces:**
- Consumes: `session_stats.project_slug` (Task 3).
- Produces:
  - `TerminalLauncher.Outcome` — `enum { case ghostty, terminal, clipboard }`
  - `TerminalLauncher.ghosttyAppPath: String`
  - `TerminalLauncher.isSafeCommand(_ s: String) -> Bool`
  - `TerminalLauncher.isSafeCwd(_ s: String) -> Bool`
  - `TerminalLauncher.ghosttyScript(command: String, cwd: String?) -> String?`
  - `TerminalLauncher.terminalScript(command: String, cwd: String?) -> String?`
  - `TerminalLauncher.launch(command:cwd:ghosttyInstalled:run:) -> Outcome`
  - `TerminalLauncher.runAppleScript(_ source: String) -> Bool`

- [ ] **Step 1: Read Ghostty's AppleScript dictionary**

Run: `sdef /Applications/Ghostty.app`
Expected: XML containing a `new window` command with a `with configuration` record parameter. Note the **exact** property names it lists (the spec claims `command`, `initial working directory`, `environment variables`, `wait after command`). Write the observed names down — they go verbatim into Step 3.

- [ ] **Step 2: Probe the invocation once, with a harmless command**

Run variant **A** first:

```bash
osascript \
  -e 'tell application "Ghostty"' \
  -e 'activate' \
  -e 'new window with configuration {command:"echo cicada-test", initial working directory:"/tmp"}' \
  -e 'end tell'
```

Expected on success: a Ghostty window opens, prints `cicada-test`, `osascript` exits 0 with no stderr.

If it errors, try in order and record which one works:

```bash
# B — no cwd (isolate whether the cwd property name is the problem)
osascript -e 'tell application "Ghostty"' -e 'activate' \
          -e 'new window with configuration {command:"echo cicada-test"}' -e 'end tell'

# C — classic `make new` form
osascript -e 'tell application "Ghostty"' -e 'activate' \
          -e 'make new window with properties {command:"echo cicada-test"}' -e 'end tell'
```

Record the **first invocation that exits 0** verbatim. If none does, the ladder's first rung is dropped: Ghostty is skipped and `launch` starts at Terminal.app — note that in the file header comment and skip the Ghostty branch in Step 3's `launch`.

- [ ] **Step 3: Verify the dot-path slug**

```bash
mkdir -p ~/cicada.slug.probe
before=$(mktemp); after=$(mktemp)
ls ~/.claude/projects > "$before"
( cd ~/cicada.slug.probe && claude --resume 00000000-0000-0000-0000-000000000000 ; true )
ls ~/.claude/projects > "$after"
diff "$before" "$after" || true
```

`claude --resume <bad-id>` fails fast with no model call (spec appendix). If `diff` shows a new directory, that name **is** the slug — record it.

If `diff` shows nothing, the failed resume never created the project dir. Fall back to one tiny real call:

```bash
( cd ~/cicada.slug.probe && claude --print "cicada slug probe" )
ls ~/.claude/projects > "$after"; diff "$before" "$after" || true
```

Then clean up — the probe project dir now holds a transcript, which must not be read:

```bash
rm -rf ~/cicada.slug.probe
rm -rf ~/.claude/projects/<the-new-slug-dir>     # substitute the observed name
```

**Reconcile:** `~/cicada.slug.probe` under `/Users/<you>` should slug to `-Users-<you>-cicada-slug-probe`. If the observation matches, `session_stats.project_slug` and its dot test already agree — change nothing. If it differs (e.g. the dot survives, or a run of non-alphanumerics collapses to one dash), **edit `api/services/session_stats.py::project_slug` and `api/tests/test_session_stats.py::test_project_slug_handles_a_path_containing_a_dot` to match what you saw**, then run `api/.venv/bin/python -m pytest api/tests/test_session_stats.py -q` and confirm PASS.

- [ ] **Step 4: Write the failing launcher tests**

Create `app/CicadaApp/Tests/CicadaAppTests/TerminalLaunchScriptTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G48 §5 — the AppleScript source builders are PURE and REGEX-GATED.
/// Nothing reaches AppleScript that hasn't passed `isSafeCommand`/`isSafeCwd`.
final class TerminalLaunchScriptTests: XCTestCase {

    private let uuid = "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"

    // MARK: - Gates

    func testASafeResumeCommandAndCwdPass() {
        XCTAssertTrue(TerminalLauncher.isSafeCommand("claude --resume \(uuid)"))
        XCTAssertTrue(TerminalLauncher.isSafeCwd("<repo>/"))
        XCTAssertTrue(TerminalLauncher.isSafeCwd("~/Documents/roros_lab/cicada"))
    }

    func testQuotesBackslashesAndShellMetacharactersAreRefused() {
        for hostile in [
            #"claude --resume x" & do shell script "rm -rf ~" & ""#,
            #"claude --resume x\"#,
            "claude --resume x; rm -rf ~",
            "claude --resume $(whoami)",
            "claude --resume `id`",
            "claude --resume x\nactivate",
        ] {
            XCTAssertFalse(TerminalLauncher.isSafeCommand(hostile), hostile)
            XCTAssertNil(TerminalLauncher.ghosttyScript(command: hostile, cwd: nil), hostile)
            XCTAssertNil(TerminalLauncher.terminalScript(command: hostile, cwd: nil), hostile)
        }
    }

    func testARelativeOrHostileCwdIsRefused() {
        XCTAssertFalse(TerminalLauncher.isSafeCwd("relative/path"))
        XCTAssertFalse(TerminalLauncher.isSafeCwd("/Users/x/we ird"))
        XCTAssertFalse(TerminalLauncher.isSafeCwd(#"/Users/x/q"uote"#))
    }

    // MARK: - Exact source

    func testGhosttyScriptIsTheVerifiedInvocation() {
        let script = TerminalLauncher.ghosttyScript(
            command: "claude --resume \(uuid)", cwd: "/Users/x/p"
        )
        XCTAssertEqual(script, """
        tell application "Ghostty"
        activate
        new window with configuration {command:"claude --resume \(uuid)", \
        initial working directory:"/Users/x/p"}
        end tell
        """)
    }

    func testGhosttyScriptDropsAnUnsafeCwdButKeepsTheCommand() {
        let script = TerminalLauncher.ghosttyScript(
            command: "claude --resume \(uuid)", cwd: "/Users/x/we ird"
        )
        XCTAssertEqual(script, """
        tell application "Ghostty"
        activate
        new window with configuration {command:"claude --resume \(uuid)"}
        end tell
        """)
    }

    func testTerminalScriptComposesCdAndCommandFromValidatedPiecesOnly() {
        let script = TerminalLauncher.terminalScript(
            command: "claude --resume \(uuid)", cwd: "/Users/x/p"
        )
        XCTAssertEqual(
            script,
            "tell application \"Terminal\"\nactivate\n"
            + "do script \"cd /Users/x/p && claude --resume \(uuid)\"\nend tell"
        )
    }

    // MARK: - Ladder

    func testGhosttyIsPreferredWhenInstalled() {
        var ran: [String] = []
        let outcome = TerminalLauncher.launch(
            command: "claude --resume \(uuid)", cwd: "/Users/x/p",
            ghosttyInstalled: true, run: { ran.append($0); return true }
        )
        XCTAssertEqual(outcome, .ghostty)
        XCTAssertEqual(ran.count, 1)
        XCTAssertTrue(ran[0].contains("Ghostty"))
    }

    func testTerminalIsTheSecondRungWhenGhosttyIsAbsent() {
        var ran: [String] = []
        let outcome = TerminalLauncher.launch(
            command: "claude --resume \(uuid)", cwd: nil,
            ghosttyInstalled: false, run: { ran.append($0); return true }
        )
        XCTAssertEqual(outcome, .terminal)
        XCTAssertEqual(ran.count, 1)
        XCTAssertTrue(ran[0].contains("Terminal"))
    }

    func testTerminalIsTriedWhenGhosttyScriptFails() {
        var ran: [String] = []
        let outcome = TerminalLauncher.launch(
            command: "claude --resume \(uuid)", cwd: nil,
            ghosttyInstalled: true,
            run: { ran.append($0); return !$0.contains("Ghostty") }
        )
        XCTAssertEqual(outcome, .terminal)
        XCTAssertEqual(ran.count, 2)
    }

    func testEverythingFailingFallsBackToTheClipboard() {
        let outcome = TerminalLauncher.launch(
            command: "claude --resume \(uuid)", cwd: nil,
            ghosttyInstalled: true, run: { _ in false }
        )
        XCTAssertEqual(outcome, .clipboard)
    }

    func testAnUnsafeCommandNeverReachesAppleScriptAtAll() {
        var ran: [String] = []
        let outcome = TerminalLauncher.launch(
            command: #"claude --resume x" & ""#, cwd: nil,
            ghosttyInstalled: true, run: { ran.append($0); return true }
        )
        XCTAssertEqual(outcome, .clipboard)
        XCTAssertTrue(ran.isEmpty, "no AppleScript may be built from unvalidated input")
    }
}
```

- [ ] **Step 5: Run and watch them fail**

Run: `cd app/CicadaApp && swift test --filter TerminalLaunchScriptTests`
Expected: FAIL — `cannot find 'TerminalLauncher' in scope`.

- [ ] **Step 6: Write `TerminalLauncher.swift`**

Create `app/CicadaApp/Sources/CicadaApp/Services/TerminalLauncher.swift`. **Substitute the Step 2 invocation verbatim** into `ghosttyScript` if it differed from variant A, and update `testGhosttyScriptIsTheVerifiedInvocation` to match.

```swift
import AppKit
import Foundation

/// Launching a terminal for `claude --resume <uuid>` (G48 §5).
///
/// The backend validates and hands us a descriptor; this type only launches.
/// Ladder: Ghostty (when installed) -> Terminal.app -> clipboard, mirroring
/// `ConnectionsView.openInTerminal`'s shipped fallback shape.
///
/// SAFETY: a string reaches AppleScript source only after `isSafeCommand` /
/// `isSafeCwd`. Nothing else is ever interpolated, and `/bin/sh -c` is never
/// used. `terminalScript` composes `cd <cwd> && <command>` from two
/// independently validated pieces plus fixed literals.
///
/// The Ghostty invocation below was verified once against Ghostty 1.3.1's
/// AppleScript dictionary (`sdef /Applications/Ghostty.app`) with a harmless
/// `echo cicada-test` before being hard-wired here.
enum TerminalLauncher {

    enum Outcome: Equatable {
        case ghostty
        case terminal
        case clipboard
    }

    static let ghosttyAppPath = "/Applications/Ghostty.app"

    /// Letters, digits, space, and the punctuation a `claude --resume <uuid>`
    /// line legitimately needs. Deliberately excludes `"` `\` `$` `` ` `` `;`
    /// `&` `|` and every newline.
    private static let commandPattern = "^[A-Za-z0-9 ._:/@=-]+$"
    /// Same conservative charset the backend uses for `cwd`.
    private static let cwdPattern = "^[A-Za-z0-9/_.~-]+$"

    static func isSafeCommand(_ value: String) -> Bool {
        matches(value, commandPattern)
    }

    static func isSafeCwd(_ value: String) -> Bool {
        (value.hasPrefix("/") || value.hasPrefix("~")) && matches(value, cwdPattern)
    }

    private static func matches(_ value: String, _ pattern: String) -> Bool {
        guard !value.isEmpty else { return false }
        return value.range(of: pattern, options: .regularExpression) != nil
    }

    // MARK: - Pure script builders

    /// `nil` when the command fails the gate. An unsafe `cwd` is DROPPED (the
    /// window opens in Ghostty's default directory) rather than sanitised.
    static func ghosttyScript(command: String, cwd: String?) -> String? {
        guard isSafeCommand(command) else { return nil }
        var configuration = "command:\"\(command)\""
        if let cwd, isSafeCwd(cwd) {
            configuration += ", initial working directory:\"\(cwd)\""
        }
        return """
        tell application "Ghostty"
        activate
        new window with configuration {\(configuration)}
        end tell
        """
    }

    static func terminalScript(command: String, cwd: String?) -> String? {
        guard isSafeCommand(command) else { return nil }
        var full = command
        if let cwd, isSafeCwd(cwd) {
            full = "cd \(cwd) && \(command)"
        }
        return "tell application \"Terminal\"\nactivate\ndo script \"\(full)\"\nend tell"
    }

    // MARK: - Ladder

    @discardableResult
    static func launch(
        command: String,
        cwd: String?,
        ghosttyInstalled: Bool = FileManager.default.fileExists(atPath: ghosttyAppPath),
        run: (String) -> Bool = runAppleScript
    ) -> Outcome {
        if ghosttyInstalled, let script = ghosttyScript(command: command, cwd: cwd), run(script) {
            return .ghostty
        }
        if let script = terminalScript(command: command, cwd: cwd), run(script) {
            return .terminal
        }
        copyToClipboard(command)
        return .clipboard
    }

    static func runAppleScript(_ source: String) -> Bool {
        guard let script = NSAppleScript(source: source) else { return false }
        var error: NSDictionary?
        script.executeAndReturnError(&error)
        return error == nil
    }

    private static func copyToClipboard(_ value: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(value, forType: .string)
    }
}
```

- [ ] **Step 7: Run the tests**

Run: `cd app/CicadaApp && swift test --filter TerminalLaunchScriptTests`
Expected: PASS (10 tests).

- [ ] **Step 8: Run the whole app suite**

Run: `cd app/CicadaApp && swift test`
Expected: PASS.

- [ ] **Step 9: Commit**

Include the `session_stats.py` / `test_session_stats.py` paths **only if** Step 3 forced a correction.

```bash
git add app/CicadaApp/Sources/CicadaApp/Services/TerminalLauncher.swift \
        app/CicadaApp/Tests/CicadaAppTests/TerminalLaunchScriptTests.swift
git commit -m "$(cat <<'EOF'
feat(app): regex-gated Ghostty/Terminal/clipboard launcher for resume (G48)

Ghostty's `new window with configuration {command, initial working directory}`
verified once against its 1.3.1 AppleScript dictionary with `echo cicada-test`
before being hard-wired. Pure script builders; nothing reaches AppleScript that
hasn't passed isSafeCommand/isSafeCwd; never /bin/sh -c.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

## Task 7: App — Conversations section inside ActivityView

> **Read the code at HEAD first.** UI round 2 Task 8 created `Views/Activity/ActivityView.swift` with an `ActivitySection` enum (`.usage`, `.contributors`), `@AppStorage("cicada.activitySection")`, a segmented `Picker` in a `PageHeader`, an `originsStrip`, and a `switch section` dispatching to `UsageSection()` / `ContributorsSection()`. The snippets below match that plan. If HEAD differs (renamed cases, a different storage key, a different header shape), **trust HEAD** and adapt: the requirement is a third segment named `Conversations`, persisted the same way the other two are, rendering `ConversationsSection()`. Everything else in this task is new files.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Models/Conversation.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/ViewModels/ConversationsViewModel.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Activity/ConversationsSection.swift`
- Modify (additive): `app/CicadaApp/Sources/CicadaApp/Views/Activity/ActivityView.swift`
- Modify (additive): `app/CicadaApp/Sources/CicadaApp/Sync/SyncAPI.swift`
- Modify (additive): `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift`
- Modify (additive): `app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift` (two `FakeSyncAPI` methods)
- Test: `app/CicadaApp/Tests/CicadaAppTests/ConversationsTests.swift` (create)

**Interfaces:**
- Consumes: `GET /conversations/recent` (Task 3), `POST /conversations/{id}/resume` (Task 5), `TerminalLauncher.launch(command:cwd:ghosttyInstalled:run:)` (Task 6).
- Produces:
  - `struct ConversationSummary: Identifiable, Codable, Hashable` — `id == conversationId`; `conversationId, kind, harness, origin, title, firstSeen, lastSeen, episodeCount, entityIds, entityCount, model, resumable`; `var hiddenEntityCount: Int`
  - `struct ResumeDescriptor: Codable` — `mode, argv, cwd, displayCommand`
  - `SyncAPI.fetchRecentConversations(limit: Int) async throws -> [ConversationSummary]`
  - `SyncAPI.resumeConversation(id: String) async throws -> ResumeDescriptor`
  - `@Observable @MainActor final class ConversationsViewModel` — `init(api: any SyncAPI = APIClient.shared, launch: @escaping (String, String?) -> TerminalLauncher.Outcome = { TerminalLauncher.launch(command: $0, cwd: $1) })`, `conversations`, `hasLoaded`, `isLoading`, `errorMessage`, `selectedId`, `func load(limit: Int = 20) async`, `func resume(_ id: String) async -> ResumeOutcome`
  - `enum ResumeOutcome: Equatable { case launched(String), copied(String), gone, failed(String) }`
  - `struct ConversationRow: View` — `conversation: ConversationSummary`, `isSelected: Bool = false`, `onResume: () -> Void`, `onCopy: () -> Void` (memberwise init; `isSelected` is omittable, and Task 8's popover omits it)
  - `ConversationsViewModel.copyCommand(for: String) async -> ResumeOutcome`, `conversation(id: String) -> ConversationSummary?`, `canResume(_ id: String) -> Bool`
  - `ActivitySection.conversations` (raw value `"Conversations"`)

- [ ] **Step 1: Write the failing model + client tests**

Create `app/CicadaApp/Tests/CicadaAppTests/ConversationsTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G48 §3-§5 on the app side: the wire types, the two fetches, and the
/// view model's resumable gating.
@MainActor
final class ConversationsTests: XCTestCase {

    private let uuid = "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    // MARK: - Decoding

    func testConversationSummaryDecodesTheCamelCaseWirePayload() throws {
        let json = """
        {
            "conversationId": "\(uuid)",
            "kind": "mcp",
            "harness": "claude-code",
            "origin": "mcp",
            "title": "Index choice",
            "firstSeen": "2026-08-30T10:00:00Z",
            "lastSeen": "2026-08-30T12:00:00Z",
            "episodeCount": 2,
            "entityIds": ["sqlite-vec", "cicada"],
            "entityCount": 2,
            "model": "gpt-5.4-mini",
            "resumable": true
        }
        """.data(using: .utf8)!

        let convo = try JSONDecoder().decode(ConversationSummary.self, from: json)

        XCTAssertEqual(convo.id, uuid)
        XCTAssertEqual(convo.kind, "mcp")
        XCTAssertEqual(convo.harness, "claude-code")
        XCTAssertEqual(convo.title, "Index choice")
        XCTAssertEqual(convo.episodeCount, 2)
        XCTAssertEqual(convo.entityIds, ["sqlite-vec", "cicada"])
        XCTAssertEqual(convo.model, "gpt-5.4-mini")
        XCTAssertTrue(convo.resumable)
        XCTAssertEqual(convo.hiddenEntityCount, 0)
    }

    func testConversationSummaryToleratesAnOlderBackendMissingEverythingOptional() throws {
        let json = #"{"conversationId": "uuid-abc"}"#.data(using: .utf8)!
        let convo = try JSONDecoder().decode(ConversationSummary.self, from: json)

        XCTAssertEqual(convo.kind, "mcp")
        XCTAssertEqual(convo.title, "")
        XCTAssertEqual(convo.entityIds, [])
        XCTAssertEqual(convo.entityCount, 0)
        XCTAssertNil(convo.model)
        XCTAssertFalse(convo.resumable)
    }

    func testACappedEntityListReportsWhatTheBackendWithheld() throws {
        let json = """
        {"conversationId": "\(uuid)", "entityIds": ["a", "b"], "entityCount": 40}
        """.data(using: .utf8)!
        let convo = try JSONDecoder().decode(ConversationSummary.self, from: json)
        XCTAssertEqual(convo.hiddenEntityCount, 38)
    }

    func testAnOlderBackendWithoutEntityCountNeverShowsAPhantomMore() throws {
        let json = #"{"conversationId": "x", "entityIds": ["a", "b"]}"#.data(using: .utf8)!
        let convo = try JSONDecoder().decode(ConversationSummary.self, from: json)
        XCTAssertEqual(convo.entityCount, 2)
        XCTAssertEqual(convo.hiddenEntityCount, 0)
    }

    func testResumeDescriptorDecodes() throws {
        let json = """
        {"mode": "terminal", "argv": ["claude", "--resume", "\(uuid)"],
         "cwd": "/Users/x/p", "displayCommand": "claude --resume \(uuid)"}
        """.data(using: .utf8)!
        let descriptor = try JSONDecoder().decode(ResumeDescriptor.self, from: json)

        XCTAssertEqual(descriptor.mode, "terminal")
        XCTAssertEqual(descriptor.argv, ["claude", "--resume", uuid])
        XCTAssertEqual(descriptor.cwd, "/Users/x/p")
        XCTAssertEqual(descriptor.displayCommand, "claude --resume \(uuid)")
    }

    func testResumeDescriptorToleratesANullCwd() throws {
        let json = #"{"mode": "terminal", "argv": [], "cwd": null, "displayCommand": "x"}"#
            .data(using: .utf8)!
        XCTAssertNil(try JSONDecoder().decode(ResumeDescriptor.self, from: json).cwd)
    }

    // MARK: - APIClient

    func testFetchRecentConversationsSendsTheLimit() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/conversations/recent")
            XCTAssertTrue((request.url?.query ?? "").contains("limit=20"))
            let body = """
            [{"conversationId": "\(self.uuid)", "title": "Index choice", "resumable": true}]
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                           httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let rows = try await APIClient(session: MockURLProtocol.makeSession())
            .fetchRecentConversations(limit: 20)

        XCTAssertEqual(rows.map(\.id), [uuid])
    }

    func testFetchRecentConversationsIsEmptyAgainstABackendWithoutTheEndpoint() async throws {
        MockURLProtocol.handler = { request in
            let response = HTTPURLResponse(url: request.url!, statusCode: 404,
                                           httpVersion: nil, headerFields: nil)!
            return (response, Data("Not Found".utf8))
        }
        let rows = try await APIClient(session: MockURLProtocol.makeSession())
            .fetchRecentConversations(limit: 20)
        XCTAssertTrue(rows.isEmpty)
    }

    func testResumeConversationPostsToTheIdPath() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/conversations/\(self.uuid)/resume")
            let body = """
            {"mode": "terminal", "argv": ["claude", "--resume", "\(self.uuid)"],
             "cwd": "/Users/x/p", "displayCommand": "claude --resume \(self.uuid)"}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                           httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let descriptor = try await APIClient(session: MockURLProtocol.makeSession())
            .resumeConversation(id: uuid)

        XCTAssertEqual(descriptor.displayCommand, "claude --resume \(uuid)")
    }

    func testResumeConversationSurfacesA409() async throws {
        MockURLProtocol.handler = { request in
            let response = HTTPURLResponse(url: request.url!, statusCode: 409,
                                           httpVersion: nil, headerFields: nil)!
            return (response, Data(#"{"detail":{"reason":"transcript_gone"}}"#.utf8))
        }

        do {
            _ = try await APIClient(session: MockURLProtocol.makeSession())
                .resumeConversation(id: uuid)
            XCTFail("expected a 409")
        } catch APIError.httpError(let code, _) {
            XCTAssertEqual(code, 409)
        }
    }

    // MARK: - ViewModel

    func testLoadPublishesRowsAndMarksLoaded() async {
        let api = FakeSyncAPI()
        api.recentConversations = [
            ConversationSummary(conversationId: uuid, title: "Index choice", resumable: true),
        ]
        let vm = ConversationsViewModel(api: api)

        XCTAssertFalse(vm.hasLoaded)
        await vm.load()

        XCTAssertTrue(vm.hasLoaded)
        XCTAssertNil(vm.errorMessage)
        XCTAssertEqual(vm.conversations.map(\.id), [uuid])
    }

    func testLoadedAndEmptyIsNotAnError() async {
        let api = FakeSyncAPI()
        api.recentConversations = []
        let vm = ConversationsViewModel(api: api)
        await vm.load()

        XCTAssertTrue(vm.hasLoaded)
        XCTAssertNil(vm.errorMessage)
        XCTAssertTrue(vm.conversations.isEmpty)
    }

    func testAFailedLoadKeepsHasLoadedFalseAndSaysSo() async {
        let api = FakeSyncAPI()
        api.failRecentConversations = true
        let vm = ConversationsViewModel(api: api)
        await vm.load()

        XCTAssertFalse(vm.hasLoaded)
        XCTAssertEqual(vm.errorMessage, "Couldn't load conversations")
    }

    func testResumeLaunchesAndReportsTheApp() async {
        let api = FakeSyncAPI()
        api.resumeDescriptor = ResumeDescriptor(
            mode: "terminal", argv: ["claude", "--resume", uuid],
            cwd: "/Users/x/p", displayCommand: "claude --resume \(uuid)"
        )
        let vm = ConversationsViewModel(api: api, launch: { _, _ in .ghostty })

        let outcome = await vm.resume(uuid)
        XCTAssertEqual(outcome, .launched("Ghostty"))
    }

    func testResumeFallsBackToTheClipboardAndReportsTheCommand() async {
        let api = FakeSyncAPI()
        api.resumeDescriptor = ResumeDescriptor(
            mode: "terminal", argv: ["claude", "--resume", uuid],
            cwd: nil, displayCommand: "claude --resume \(uuid)"
        )
        let vm = ConversationsViewModel(api: api, launch: { _, _ in .clipboard })

        let outcome = await vm.resume(uuid)
        XCTAssertEqual(outcome, .copied("claude --resume \(uuid)"))
    }

    func testA409BecomesTheGoneOutcome() async {
        let api = FakeSyncAPI()
        api.resumeError = APIError.httpError(409, #"{"detail":{"reason":"transcript_gone"}}"#)
        let vm = ConversationsViewModel(api: api, launch: { _, _ in .ghostty })

        XCTAssertEqual(await vm.resume(uuid), .gone)
    }

    func testANonResumableIdIsNeverEvenSentToTheBackend() async {
        let api = FakeSyncAPI()
        api.recentConversations = [
            ConversationSummary(conversationId: "ses_2026-08-31_deadbeef", resumable: false),
        ]
        let vm = ConversationsViewModel(api: api, launch: { _, _ in .ghostty })
        await vm.load()

        XCTAssertFalse(vm.canResume("ses_2026-08-31_deadbeef"))
        XCTAssertTrue(vm.conversations[0].resumable == false)
    }

    // MARK: - Section persistence

    func testActivitySectionRoundTripsTheConversationsCase() {
        XCTAssertEqual(ActivitySection.restored(from: "Conversations"), .conversations)
        XCTAssertEqual(ActivitySection.conversations.rawValue, "Conversations")
        XCTAssertEqual(ActivitySection.restored(from: "Nonsense"), .usage)
        XCTAssertTrue(ActivitySection.allCases.contains(.conversations))
    }
}
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd app/CicadaApp && swift test --filter ConversationsTests`
Expected: FAIL — `cannot find type 'ConversationSummary' in scope`.

- [ ] **Step 3: Write `Models/Conversation.swift`**

```swift
import Foundation

/// One conversation that wrote to memory (G48 §3) — a live MCP session or an
/// imported chat thread. Wire is camelCase (`api/models/schemas.py::to_camel`),
/// and every field but `conversationId` is optional-with-a-default so an older
/// backend decodes instead of throwing.
struct ConversationSummary: Identifiable, Codable, Hashable {
    var id: String { conversationId }

    let conversationId: String
    let kind: String          // "mcp" | "import"
    let harness: String
    let origin: String
    let title: String
    let firstSeen: String
    let lastSeen: String
    let episodeCount: Int
    let entityIds: [String]
    let entityCount: Int
    let model: String?
    let resumable: Bool

    /// How many touched entities the backend withheld from `entityIds`.
    var hiddenEntityCount: Int { max(0, entityCount - entityIds.count) }

    /// A name for the row when the backend had no episode title to offer.
    var displayTitle: String { title.isEmpty ? "Untitled conversation" : title }

    init(
        conversationId: String,
        kind: String = "mcp",
        harness: String = "",
        origin: String = "",
        title: String = "",
        firstSeen: String = "",
        lastSeen: String = "",
        episodeCount: Int = 0,
        entityIds: [String] = [],
        entityCount: Int = 0,
        model: String? = nil,
        resumable: Bool = false
    ) {
        self.conversationId = conversationId
        self.kind = kind
        self.harness = harness
        self.origin = origin
        self.title = title
        self.firstSeen = firstSeen
        self.lastSeen = lastSeen
        self.episodeCount = episodeCount
        self.entityIds = entityIds
        self.entityCount = entityCount
        self.model = model
        self.resumable = resumable
    }

    enum CodingKeys: String, CodingKey {
        case conversationId, kind, harness, origin, title, firstSeen, lastSeen
        case episodeCount, entityIds, entityCount, model, resumable
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        conversationId = try c.decode(String.self, forKey: .conversationId)
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "mcp"
        harness = try c.decodeIfPresent(String.self, forKey: .harness) ?? ""
        origin = try c.decodeIfPresent(String.self, forKey: .origin) ?? ""
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        firstSeen = try c.decodeIfPresent(String.self, forKey: .firstSeen) ?? ""
        lastSeen = try c.decodeIfPresent(String.self, forKey: .lastSeen) ?? ""
        episodeCount = try c.decodeIfPresent(Int.self, forKey: .episodeCount) ?? 0
        let ids = try c.decodeIfPresent([String].self, forKey: .entityIds) ?? []
        entityIds = ids
        // Fall back to the ids we were sent so an older backend never produces
        // a phantom "+N more".
        entityCount = try c.decodeIfPresent(Int.self, forKey: .entityCount) ?? ids.count
        model = try c.decodeIfPresent(String.self, forKey: .model)
        resumable = try c.decodeIfPresent(Bool.self, forKey: .resumable) ?? false
    }
}

/// How to reopen a conversation (G48 §5). The backend validated everything in
/// here; `TerminalLauncher` re-gates before interpolating, as defence in depth.
struct ResumeDescriptor: Codable, Hashable {
    let mode: String
    let argv: [String]
    let cwd: String?
    let displayCommand: String

    init(mode: String = "terminal", argv: [String] = [],
         cwd: String? = nil, displayCommand: String = "") {
        self.mode = mode
        self.argv = argv
        self.cwd = cwd
        self.displayCommand = displayCommand
    }

    enum CodingKeys: String, CodingKey { case mode, argv, cwd, displayCommand }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mode = try c.decodeIfPresent(String.self, forKey: .mode) ?? "terminal"
        argv = try c.decodeIfPresent([String].self, forKey: .argv) ?? []
        cwd = try c.decodeIfPresent(String.self, forKey: .cwd)
        displayCommand = try c.decodeIfPresent(String.self, forKey: .displayCommand) ?? ""
    }
}
```

- [ ] **Step 4: Add the two API methods**

`Sync/SyncAPI.swift` — append inside the protocol, after `fetchEntity(id:)`:

```swift
    // G48 — on-demand, like `/contributors/commits`: no SyncDomain, no
    // SnapshotCache entry. On the protocol purely so tests can fake them.
    func fetchRecentConversations(limit: Int) async throws -> [ConversationSummary]
    func resumeConversation(id: String) async throws -> ResumeDescriptor
```

`Services/APIClient.swift` — add next to `fetchContributorCommits` (~line 962), following its exact shape:

```swift
    func fetchRecentConversations(limit: Int = 20) async throws -> [ConversationSummary] {
        do {
            return try await get("/conversations/recent?limit=\(limit)")
        } catch APIError.httpError(404, _) {
            return []
        }
    }

    func resumeConversation(id: String) async throws -> ResumeDescriptor {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        let encoded = id.addingPercentEncoding(withAllowedCharacters: allowed) ?? id
        var request = makeRequest("/conversations/\(encoded)/resume", method: "POST")
        request.httpBody = Data("{}".utf8)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }
        do {
            return try decoder.decode(ResumeDescriptor.self, from: data)
        } catch {
            throw APIError.decodingError("\(error)")
        }
    }
```

`Tests/CicadaAppTests/StoreTests.swift` — inside `FakeSyncAPI`, add the stored state next to the other `var`s and the two methods next to `fetchContributors`:

```swift
    var recentConversations: [ConversationSummary] = []
    var failRecentConversations = false
    var resumeDescriptor = ResumeDescriptor()
    var resumeError: (any Error)?

    func fetchRecentConversations(limit: Int) async throws -> [ConversationSummary] {
        if failRecentConversations { throw APIError.serverUnreachable }
        return recentConversations
    }

    func resumeConversation(id: String) async throws -> ResumeDescriptor {
        if let resumeError { throw resumeError }
        return resumeDescriptor
    }
```

- [ ] **Step 5: Write `ViewModels/ConversationsViewModel.swift`**

```swift
import AppKit
import Foundation

/// What happened when the user asked to reopen a conversation.
enum ResumeOutcome: Equatable {
    case launched(String)   // the terminal app that opened
    case copied(String)     // the command now on the clipboard
    case gone               // 409 — the transcript was retention-cleaned
    case failed(String)
}

/// G48 §4 — the Conversations section's state. On-demand fetch: no Store
/// domain and no SnapshotCache entry, following `/contributors/commits`.
@MainActor
@Observable
final class ConversationsViewModel {

    private(set) var conversations: [ConversationSummary] = []
    private(set) var hasLoaded = false
    private(set) var isLoading = false
    private(set) var errorMessage: String?
    var selectedId: String?

    private let api: any SyncAPI
    private let launch: (String, String?) -> TerminalLauncher.Outcome

    init(
        api: any SyncAPI = APIClient.shared,
        launch: @escaping (String, String?) -> TerminalLauncher.Outcome
            = { command, cwd in TerminalLauncher.launch(command: command, cwd: cwd) }
    ) {
        self.api = api
        self.launch = launch
    }

    func conversation(id: String) -> ConversationSummary? {
        conversations.first { $0.id == id }
    }

    /// A row can offer Resume only when the BACKEND said so. The app never
    /// decides resumability for itself.
    func canResume(_ id: String) -> Bool { conversation(id: id)?.resumable == true }

    func load(limit: Int = 20) async {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            conversations = try await api.fetchRecentConversations(limit: limit)
            hasLoaded = true
            errorMessage = nil
        } catch {
            errorMessage = "Couldn't load conversations"
        }
    }

    func resume(_ id: String) async -> ResumeOutcome {
        do {
            let descriptor = try await api.resumeConversation(id: id)
            switch launch(descriptor.displayCommand, descriptor.cwd) {
            case .ghostty: return .launched("Ghostty")
            case .terminal: return .launched("Terminal")
            case .clipboard: return .copied(descriptor.displayCommand)
            }
        } catch APIError.httpError(409, _) {
            return .gone
        } catch APIError.httpError(400, _) {
            return .failed("This conversation can't be resumed")
        } catch {
            return .failed("Couldn't reach Cicada's backend")
        }
    }

    /// "Copy command" — same 400/409 handling, no launch. The command was
    /// built backend-side from a UUID-gated id, so it is safe to put on the
    /// pasteboard verbatim.
    func copyCommand(for id: String) async -> ResumeOutcome {
        do {
            let descriptor = try await api.resumeConversation(id: id)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(descriptor.displayCommand, forType: .string)
            return .copied(descriptor.displayCommand)
        } catch APIError.httpError(409, _) {
            return .gone
        } catch APIError.httpError(400, _) {
            return .failed("This conversation can't be resumed")
        } catch {
            return .failed("Couldn't reach Cicada's backend")
        }
    }
}
```

- [ ] **Step 6: Write `Views/Activity/ConversationsSection.swift`**

```swift
import SwiftUI

/// G48 §4 — "Conversations" inside Activity: which conversations wrote to
/// memory, and a way back into the resumable ones.
struct ConversationsSection: View {
    @State private var viewModel = ConversationsViewModel()
    @State private var loadedOnce = false
    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if let message = viewModel.errorMessage {
                ContentUnavailableView(
                    "Couldn't load conversations",
                    systemImage: "bubble.left.and.exclamationmark.bubble.right",
                    description: Text(message)
                )
            } else if !viewModel.hasLoaded {
                ProgressView().controlSize(.small)
            } else if viewModel.conversations.isEmpty {
                ContentUnavailableView(
                    "No conversations yet",
                    systemImage: "bubble.left.and.bubble.right",
                    description: Text(
                        "Conversations appear here once an MCP client saves an episode, "
                        + "or you import a chat export."
                    )
                )
            } else {
                ForEach(viewModel.conversations) { conversation in
                    ConversationRow(
                        conversation: conversation,
                        isSelected: viewModel.selectedId == conversation.id,
                        onResume: { Task { await act(await viewModel.resume(conversation.id)) } },
                        onCopy: { Task { await act(await viewModel.copyCommand(for: conversation.id)) } }
                    )
                }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
        .task {
            guard !loadedOnce else { return }
            loadedOnce = true
            await viewModel.load()
        }
    }

    /// Report every outcome through the app-wide toast, so a clipboard
    /// fallback is never silent.
    private func act(_ outcome: ResumeOutcome) async {
        switch outcome {
        case .launched(let app):
            store.toast = "Reopening in \(app)…"
        case .copied(let command):
            store.toast = "Copied “\(command)” — paste it into any terminal"
        case .gone:
            store.toast = "That conversation's transcript is gone — nothing to resume"
            await viewModel.load()
        case .failed(let message):
            store.toast = message
        }
    }
}

/// One conversation. Reused verbatim inside `ConversationPopover` (Task 8).
struct ConversationRow: View {
    let conversation: ConversationSummary
    var isSelected: Bool = false
    let onResume: () -> Void
    let onCopy: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            VStack(alignment: .leading, spacing: 4) {
                Text(conversation.displayTitle)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)

                HStack(spacing: CicadaTheme.spacingXS) {
                    badge(conversation.harness.isEmpty
                          ? (conversation.kind == "import" ? "import" : "conversation")
                          : conversation.harness)
                    if let model = conversation.model { badge(model) }
                    Text("\(conversation.episodeCount) episode"
                         + (conversation.episodeCount == 1 ? "" : "s"))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                    if !conversation.lastSeen.isEmpty {
                        Text(RelativeTime.phrase(from: conversation.lastSeen))
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                }

                if conversation.entityCount > 0 {
                    HStack(spacing: 6) {
                        ForEach(conversation.entityIds, id: \.self) { badge($0) }
                        if conversation.hiddenEntityCount > 0 {
                            badge("+\(conversation.hiddenEntityCount) more")
                        }
                    }
                }
            }

            Spacer(minLength: CicadaTheme.spacingSM)

            if conversation.resumable {
                Menu("Resume") {
                    Button("Resume in terminal", action: onResume)
                    Button("Copy command", action: onCopy)
                }
                .menuStyle(.borderlessButton)
                .fixedSize()
                .help("Reopen this conversation with claude --resume")
            }
        }
        .padding(CicadaTheme.spacingSM)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(isSelected ? CicadaTheme.surfaceRaised : CicadaTheme.surface)
        )
        .accessibilityElement(children: .contain)
        .accessibilityLabel(
            "\(conversation.displayTitle), \(conversation.episodeCount) episodes"
            + (conversation.resumable ? ", resumable" : "")
        )
    }

    private func badge(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(Capsule().fill(CicadaTheme.surfaceRaised))
    }
}
```

**If a name here doesn't exist at HEAD** — `CicadaTheme.surfaceRaised`, `CicadaTheme.bodyFont`, `RelativeTime.phrase(from:)`, `store.toast` — grep for the nearest equivalent already used by `ContributorsView.swift` / `UsageView.swift` and use that instead. The tests in this task assert behaviour, not theme token names, so a substitution is safe.

- [ ] **Step 7: Add the third segment to `ActivityView.swift`**

Additive edits only:

```swift
enum ActivitySection: String, CaseIterable, Identifiable {
    case usage = "Usage"
    case contributors = "Contributors"
    case conversations = "Conversations"
```

```swift
            switch section {
            case .usage: UsageSection()
            case .contributors: ContributorsSection()
            case .conversations: ConversationsSection()
            }
```

…and widen the picker's label so VoiceOver stays truthful:

```swift
                    .accessibilityLabel("Show usage, contributors, or conversations")
```

`restored(from:)` needs no change — an unknown raw value already falls back to `.usage`.

- [ ] **Step 8: Run the tests**

Run: `cd app/CicadaApp && swift test --filter ConversationsTests`
Expected: PASS (17 tests).

- [ ] **Step 9: Run the whole app suite**

Run: `cd app/CicadaApp && swift test`
Expected: PASS — `StoreTests`, `MutationTests`, `StateCoverageTests`, `GraphPushTests` and `InboxQuestionTests` all compile against the widened `FakeSyncAPI`.

- [ ] **Step 10: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Models/Conversation.swift \
        app/CicadaApp/Sources/CicadaApp/ViewModels/ConversationsViewModel.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Activity/ConversationsSection.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Activity/ActivityView.swift \
        app/CicadaApp/Sources/CicadaApp/Sync/SyncAPI.swift \
        app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift \
        app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift \
        app/CicadaApp/Tests/CicadaAppTests/ConversationsTests.swift
git commit -m "$(cat <<'EOF'
feat(app): Activity gains a Conversations section with Resume (G48)

A third segment beside Usage and Contributors, persisted the same way: recent
conversations with harness/model badges, entity chips with an honest "+N more",
and a Resume menu on the rows the backend marked resumable. On-demand fetch —
no Store domain, no SnapshotCache entry, per the /contributors/commits
precedent. Clipboard fallback is toasted, never silent.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

## Task 8: App — "from conversation →" on history rows and contributor commits

> **Read the code at HEAD first.** UI round 2 Task 8 renamed `ContributorsView` → `ContributorsSection` and deleted its `header`. `ContributorRow` (a `private struct` in `Views/Contributors/ContributorsView.swift`) renders each commit via `private func commitRow(_ commit: ContributorCommit) -> some View`. `EntityDetailCard.swift` renders history rows via `private func historyRowLabel(_ entry: EntityHistoryEntry, expandable: Bool) -> some View`. If either has moved, put the affordance wherever that row's trailing metadata now lives — the requirement is a button on the row, not a specific insertion line.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Activity/ConversationPopover.swift`
- Modify (additive): `app/CicadaApp/Sources/CicadaApp/Models/Entity.swift` (`EntityHistoryEntry`, `ContributorCommit`)
- Modify (additive): `app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift`
- Modify (additive): `app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorsView.swift`
- Test: `app/CicadaApp/Tests/CicadaAppTests/ConversationAffordanceTests.swift` (create)

**Interfaces:**
- Consumes: `sessions` on both wire types (Task 4); `ConversationRow`, `ConversationsViewModel`, `ResumeOutcome` (Task 7).
- Produces:
  - `EntityHistoryEntry.sessions: [String]` (default `[]`), `ContributorCommit.sessions: [String]` (default `[]`)
  - `struct ConversationPopover: View` — `init(sessionIds: [String])`
  - `struct FromConversationButton: View` — `init(sessionIds: [String])`; renders **nothing** when `sessionIds` is empty

- [ ] **Step 1: Write the failing tests**

Create `app/CicadaApp/Tests/CicadaAppTests/ConversationAffordanceTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G48 §4 — a commit's conversations reach the app, and the affordance is
/// invisible wherever there is no conversation to open (pre-G48 history,
/// user-action commits).
@MainActor
final class ConversationAffordanceTests: XCTestCase {

    private let uuid = "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"

    func testEntityHistoryEntryDecodesSessions() throws {
        let json = """
        {"date": "2026-08-31", "changeType": "created", "description": "created",
         "author": "gpt-5.4-mini", "commitHash": "abc1234", "sessions": ["\(uuid)"]}
        """.data(using: .utf8)!

        let entry = try JSONDecoder().decode(EntityHistoryEntry.self, from: json)
        XCTAssertEqual(entry.sessions, [uuid])
    }

    func testAPreG48HistoryEntryHasNoSessions() throws {
        let json = """
        {"date": "2026-01-01", "changeType": "created", "description": "created"}
        """.data(using: .utf8)!

        let entry = try JSONDecoder().decode(EntityHistoryEntry.self, from: json)
        XCTAssertEqual(entry.sessions, [])
        XCTAssertEqual(entry.author, "unknown")
    }

    func testContributorCommitDecodesSessions() throws {
        let json = """
        {"commitHash": "abc1234", "date": "2026-08-31", "subject": "Sleep cycle",
         "entities": ["cicada"], "sessions": ["\(uuid)"]}
        """.data(using: .utf8)!

        let commit = try JSONDecoder().decode(ContributorCommit.self, from: json)
        XCTAssertEqual(commit.sessions, [uuid])
    }

    func testAUserActionCommitHasNoSessions() throws {
        let json = #"{"commitHash": "abc", "date": "2026-08-31", "subject": "Add source"}"#
            .data(using: .utf8)!
        XCTAssertEqual(try JSONDecoder().decode(ContributorCommit.self, from: json).sessions, [])
    }

    func testTheAffordanceIsHiddenWithoutSessionsAndShownWithThem() {
        XCTAssertFalse(FromConversationButton.shouldRender(sessionIds: []))
        XCTAssertTrue(FromConversationButton.shouldRender(sessionIds: [uuid]))
    }

    func testThePopoverOnlyOffersConversationsTheBackendKnows() async {
        let api = FakeSyncAPI()
        api.recentConversations = [
            ConversationSummary(conversationId: uuid, title: "Index choice", resumable: true),
        ]
        let vm = ConversationsViewModel(api: api)
        await vm.load()

        XCTAssertNotNil(vm.conversation(id: uuid))
        XCTAssertNil(vm.conversation(id: "a-session-this-bank-forgot"))
    }
}
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd app/CicadaApp && swift test --filter ConversationAffordanceTests`
Expected: FAIL — `value of type 'EntityHistoryEntry' has no member 'sessions'`.

- [ ] **Step 3: Add `sessions` to the two Swift models**

`Models/Entity.swift`, inside `EntityHistoryEntry` — add the property, the `CodingKeys` case, and the tolerant decode:

```swift
    // G48: the conversations that produced this commit (parsed Cicada-Session:
    // trailers). Empty for pre-G48 and user-action commits.
    let sessions: [String]
```

```swift
    enum CodingKeys: String, CodingKey {
        case date, changeType, description, author, commitHash, diff, sessions
    }
```

```swift
        sessions = try c.decodeIfPresent([String].self, forKey: .sessions) ?? []
```

The same three additions inside `ContributorCommit` (property, `CodingKeys` case, decode line). If `ContributorCommit` relies on the synthesized memberwise init anywhere in tests, give `sessions` a `= []` default in an explicit init so existing call sites keep compiling.

- [ ] **Step 4: Write `Views/Activity/ConversationPopover.swift`**

```swift
import SwiftUI

/// G48 §4 — "open the conversation that wrote this", from an entity-history
/// row or a contributor commit.
///
/// DEVIATION FROM THE SPEC (recorded deliberately): the spec described landing
/// on Activity ▸ Conversations with the row selected. `selectedTab` is `@State`
/// in `ContentView` threaded by `@Binding`, and both `ContentView.swift` and
/// `SidebarView.swift` were being rewritten by the UI round when this shipped,
/// so the conversation is shown IN PLACE instead — same row, same Resume menu,
/// no edits to files under concurrent rewrite. Cross-tab focus is a later
/// refinement, not a missing capability.
struct ConversationPopover: View {
    let sessionIds: [String]

    @State private var viewModel = ConversationsViewModel()
    @State private var loadedOnce = false
    @Environment(Store.self) private var store

    private var known: [ConversationSummary] {
        sessionIds.compactMap { viewModel.conversation(id: $0) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("Written by")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)

            if !viewModel.hasLoaded {
                ProgressView().controlSize(.small)
            } else if known.isEmpty {
                Text("This bank no longer has episodes for that conversation.")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            } else {
                ForEach(known) { conversation in
                    ConversationRow(
                        conversation: conversation,
                        onResume: { Task { await act(await viewModel.resume(conversation.id)) } },
                        onCopy: { Task { await act(await viewModel.copyCommand(for: conversation.id)) } }
                    )
                }
            }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(width: 420)
        .task {
            guard !loadedOnce else { return }
            loadedOnce = true
            await viewModel.load(limit: 200)
        }
    }

    private func act(_ outcome: ResumeOutcome) async {
        switch outcome {
        case .launched(let app): store.toast = "Reopening in \(app)…"
        case .copied(let command): store.toast = "Copied “\(command)”"
        case .gone: store.toast = "That conversation's transcript is gone — nothing to resume"
        case .failed(let message): store.toast = message
        }
    }
}

/// The row-level trigger. Renders NOTHING when there is no conversation behind
/// the commit, so every pre-G48 row looks exactly as it did.
struct FromConversationButton: View {
    let sessionIds: [String]

    @State private var isPresented = false

    /// Pure predicate, unit-tested — the view body is a thin wrapper over it.
    static func shouldRender(sessionIds: [String]) -> Bool { !sessionIds.isEmpty }

    var body: some View {
        if Self.shouldRender(sessionIds: sessionIds) {
            Button {
                isPresented = true
            } label: {
                Label("from conversation", systemImage: "bubble.left.and.bubble.right")
                    .font(CicadaTheme.captionFont)
                    .labelStyle(.titleAndIcon)
            }
            .buttonStyle(.plain)
            .foregroundStyle(CicadaTheme.textSecondary)
            .help("Show the conversation that wrote this, and reopen it")
            .accessibilityLabel("Show the conversation that wrote this")
            .popover(isPresented: $isPresented, arrowEdge: .bottom) {
                ConversationPopover(sessionIds: sessionIds)
            }
        }
    }
}
```

- [ ] **Step 5: Hang it on the two rows**

`Views/Graph/EntityDetailCard.swift` — inside `historyRowLabel`, after the author capsule in the row's trailing metadata `HStack`:

```swift
                FromConversationButton(sessionIds: entry.sessions)
```

`Views/Contributors/ContributorsView.swift` — inside `commitRow(_:)`, in the metadata line that already shows the subject and `filesChanged`:

```swift
                FromConversationButton(sessionIds: commit.sessions)
```

Both are single additive lines; nothing else in either file moves.

- [ ] **Step 6: Run the tests**

Run: `cd app/CicadaApp && swift test --filter ConversationAffordanceTests`
Expected: PASS (6 tests).

- [ ] **Step 7: Run the whole app suite**

Run: `cd app/CicadaApp && swift test`
Expected: PASS — `ContributorCommitTests` and `EntityHistoryStateTests` still pass, because `sessions` decodes with a default.

- [ ] **Step 8: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Views/Activity/ConversationPopover.swift \
        app/CicadaApp/Sources/CicadaApp/Models/Entity.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorsView.swift \
        app/CicadaApp/Tests/CicadaAppTests/ConversationAffordanceTests.swift
git commit -m "$(cat <<'EOF'
feat(app): "from conversation" on history rows and contributor commits (G48)

Entity history and contributor-commit rows now decode Cicada-Session trailers
and show a popover with that conversation's row plus its Resume menu. Renders
nothing when a commit has no session, so every pre-G48 row is unchanged.
Delivered in place rather than as a cross-tab jump — recorded in the file
header, since ContentView/SidebarView were under concurrent rewrite.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

## Task 9: Docs

**Files:**
- Modify: `CLAUDE.md` (the API endpoint block; the Storage Layer's Git subsection)
- Modify: `docs/goals/memory-evolution.md:531` (the G48 row's Status cell)

- [ ] **Step 1: Add the two endpoints to `CLAUDE.md`**

In the fenced endpoint list, directly under `POST /conversations/upload`:

```
GET  /conversations/recent                → conversations that wrote to memory (MCP sessions +
                                            imports), newest first; ETag'd; `resumable` per-request
POST /conversations/{id}/resume           → validated `claude --resume` descriptor (400 bad id /
                                            404 unknown / 409 transcript_gone). Transcripts are
                                            never read — isfile() only.
```

Also update the router-count sentence above the block if it names a count of mounted routers — the count is unchanged (both routes land on the already-mounted `conversations` router), so only add the two lines.

- [ ] **Step 2: Document the storage shape in `CLAUDE.md`**

In the **Git (Versioning & Provenance)** subsection, immediately after the `Cicada-Author:` paragraph:

```markdown
**Commit-session trailers (`Cicada-Session:`).** Alongside *which model* wrote a belief,
a Sleep commit records *which conversations* it consolidated: one `Cicada-Session: <id>`
line per distinct id, in the same trailer block, after the `Cicada-Author:` lines. The id
is a Claude Code session uuid (stamped at capture by the MCP seam) or G20's `source_id`
for an imported chat thread. Built by `git_service.build_commit_message(..., sessions=...)`
and parsed by `git_service._parse_sessions`; capped at `MAX_SESSION_TRAILERS` (50) by the
`sleep_cycle._finalize` call site, not by the builder. Inert to entity-line parsing by the
same contract as `Cicada-Author:` — it carries no entity id. Surfaced as `sessions` on
`GET /entities/{id}/history` entries and `GET /contributors/commits` rows. User-action
commits stay session-less: they are `Cicada-Author: user` writes with no conversation.
```

And in the **Awake Cycle** subsection, after the "Episode tracking" paragraph:

```markdown
**Conversation identity (G48).** An episode captured through MCP also carries `session_id`
(the client conversation), plus `harness` and `project_dir` when the client exposes them —
minted once per MCP process from `CLAUDE_CODE_SESSION_ID` → `CICADA_SESSION_ID` → a
`ses_YYYY-MM-DD_xxxxxxxx` fallback that groups but never resumes. Entities credit to
conversations transitively via `source_episodes`, exactly as they do for `origin`.
**Transcripts under `~/.claude/` are never read** — the only contact is an `isfile()` check
answering "is this session still resumable", computed per request and never persisted.
```

- [ ] **Step 3: Flip the G48 backlog row**

`docs/goals/memory-evolution.md:531` — change the trailing `| 🔲 |` to a status cell in the shipped format used by G51, honest about the partials:

```
| ✅ (session_id/harness/project_dir stamped at the MCP seam; `Cicada-Session:` trailer; `GET /conversations/recent` + `POST /conversations/{id}/resume`; Activity ▸ Conversations with Ghostty/Terminal/clipboard Resume; "from conversation" on entity-history + contributor-commit rows. PARTIALS: no backfill — pre-G48 MCP episodes carry no session and don't appear; only Claude Code is resumable (other harnesses group but have no deep link); the inverse-navigation affordance opens the conversation in a popover rather than jumping to Activity ▸ Conversations; `model` on a conversation row is best-effort from the telemetry ledger and null when `CICADA_TELEMETRY=off`) |
```

- [ ] **Step 4: Verify nothing else claims G48 is open**

Run: `grep -rn "G48" CLAUDE.md docs/goals/ docs/superpowers/`
Expected: the memory-evolution row now reads ✅; the G53 and subscription-first rows still reference G48 as a dependency (leave those unchanged); the spec and this plan are unchanged.

- [ ] **Step 5: Run both suites one final time**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Run: `cd app/CicadaApp && swift test`
Expected: PASS, PASS.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/goals/memory-evolution.md
git commit -m "$(cat <<'EOF'
docs: conversation provenance + resume endpoints; G48 shipped with partials

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

## Appendix — spec coverage map

| Spec section | Task |
|---|---|
| §1 Session-id capture at the MCP seam (env ladder, mint, `initialize` clientInfo) | 1 |
| §2.1 Episode frontmatter (save_episode + save_url) | 1 |
| §2.2 `Cicada-Session:` trailer + `_finalize` | 2 |
| §2.3 Read-time transitive propagation; `handle_write_claim` telemetry refs | 1 (refs), 3 (transitive credit) |
| §3 `GET /conversations/recent` (grouping, ETag, `resumable`, slug) | 3 |
| §4 App surface — third ActivitySection case, row, Resume menu | 7 |
| §4 Click-through from history + contributor commits | 4 (backend), 8 (app) |
| §5 `POST /conversations/{id}/resume` (gates, descriptor) | 5 |
| §5 App launch ladder (Ghostty → Terminal → clipboard) | 6 |
| §6 Privacy rails (isfile-only, no project_dir on the list, bearer-gated) | 3, 5 (+ Task 5 Step 6 asserts the exempt set) |
| §7 Testing (stamp, trailer, aggregation, resumable, resume endpoint, app) | 1, 2, 3, 5, 6, 7, 8 |
| Docs / backlog | 9 |
