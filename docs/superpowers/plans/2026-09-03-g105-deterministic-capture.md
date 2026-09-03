# G105 Deterministic Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make capture a property of the system, not of a model's diligence. Every Claude Code (and Codex) session writes exactly one episode to the bank through a deterministic, engine-free, block-level extractor fired from the harness's own hook — the person's turns and the agent's final reply per turn, never a tool call, tool output, code fence or secret — and the Sleep queue shows where every episode came from.

**Architecture:** Five slices on one branch, each a shippable commit. (1) `transcript_extract` — a pure function over JSONL lines implementing the G105 ruling (block filter, final-reply-per-turn, fence strip, caps, secret scrubber) for Claude Code and Codex. (2) `POST /capture/transcript` + `transcript_capture` — the backend validates the transcript path against the harness root, extracts, and writes ONE episode per session in the importer's exact body shape, updating it in place on every later firing (the G104-safe path) and recording a counts-only `capture` ledger event. (3) The hook — a stdlib-only script that forwards the harness's stdin JSON to the endpoint in ≤ 3 s and always exits 0, plus a stdlib-only settings-merge registry that `install.sh` / `--uninstall` / `make doctor` drive. (4) Swift — the Sleep queue rows and the "Catching up on" block wear the source's mark. (5) Docs.

**Tech Stack:** Python 3 / FastAPI / Pydantic (`api/`), YAML frontmatter + git (`memory/`), bash (`install.sh`, `scripts/doctor.sh`), SwiftUI + XCTest (`app/CicadaApp`).

**Spec:** `docs/goals/memory-evolution.md` row **G105** (the RULING of 2026-09-03 is binding) and the G48 rail as restated there. Base commit `72af78a` on `dev`.

## Global Constraints

- Work ONLY in `/Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105` (branch `feat/deterministic-capture`). Every shell command is `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && <cmd>` with absolute paths (`zoxide` hijacks relative `cd`; ignore its stderr banner). No `grep --include=*.ext` (zsh globbing breaks it). In zsh `echo =====` is an `=cmd` expansion — never use a bare `=`-prefixed word.
- Python tests: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`. Full suite `api/tests`: the baseline has **exactly 8 date-dependent failures in `test_calendar_registry.py`** plus `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` (order-dependent, pre-existing). Everything else must be green.
- Swift: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and `swift test 2>&1 | tail -20` must report 0 failures (SourceKit diagnostics naming OTHER worktrees are noise). Only Task 4 touches Swift. NEVER run `make dev`, `make install-app`, `swift run`, or launch/kill the Cicada app — the owner's installed app is live.
- **Never read** `/Users/rorosaga/Documents/roros_lab/cicada/memory` (any bank), `~/.cicada`, `~/Library/Safari`, `~/.claude/projects`, or `~/.codex/sessions`. The schema peek that informed this plan is already done and recorded below; the implementation reads NO real transcript. All fixtures are synthetic (`alpha-project`, `bob-example`, `example.com`).
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`, `.claude/settings.json`, `api/.venv`, `*-report.md`. No push, no new branches/worktrees, no subagents. Ignore Devin / PR comments.
- **Privacy rule for docs (CLAUDE.md, standing 2026-09-02):** nothing personal in `docs/goals/`, `CLAUDE.md`, this plan, commit messages or PR bodies — placeholders only.
- **Sleep-safety:** no LLM anywhere in this track; every new read path is engine-free. **Secrets** only ever in `~/.cicada/secrets.env` / `~/.cicada/api_token`; the hook reads the token file, never an env-embedded key. **Portability:** no owner name, no author-machine path in code or docs — every path is derived from `$HOME`, `$CICADA_HOME`, or the repo root at install time.
- `telemetry.record()` must never raise into the capture path (it already swallows — keep it that way). The ledger row carries ids, enums and counts only — never a turn's text, a title, or a cwd.
- Cicada docstrings explain WHY, citing the G-row or review that motivated a rule. Match that density.
- Read code at the cited `file:line` before editing — anchors are from base commit `72af78a` and may drift a few lines as tasks land.
- Do NOT touch `mcp/server.py` or `SKILL.md` — a parallel track (G49/G53/G75 primer hook) owns them.

## Verified facts this plan rests on (read, not guessed)

**Claude Code transcript (`~/.claude/projects/<slug>/<sessionId>.jsonl`, one JSON object per line).** Schema peek of one real file, key names only: top-level `type` ∈ {`user`, `assistant`, `system`, `summary`, `attachment`, `file-history-snapshot`, `queue-operation`, …}; `uuid`, `parentUuid`, `timestamp` (ISO `Z`), `sessionId`, `cwd`, `isSidechain`, `isMeta`, `isCompactSummary`, `isApiErrorMessage`; `message.role` ∈ {`user`, `assistant`}; `message.content` is a **string** (524 of 2,471 user lines) or a **list of blocks** `{type: text | tool_use | tool_result | thinking | image}`. Assistant lines carry ~one block each (821 `text`, 1,905 `tool_use`, 1,088 `thinking` across 3,814 lines). **User-role lines are mostly not the person:** 1,905 carry a `tool_result` block; 378 string bodies start with `<task-notification>`; `isMeta: true` bodies (68) and `<command-name>` / `<local-command-stdout>` / `<local-command-caveat>` / `<command-message>` bodies are harness plumbing; `<system-reminder>…</system-reminder>` spans are appended inside otherwise-real user text. Only ~100 of 2,471 user lines were the person's own words. The file was 85 MB; `attachment` + `file-history-snapshot` lines are the bulk.

**Codex session (`~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl`).** Every line is `{timestamp, type, payload}`; `type` ∈ {`session_meta`, `turn_context`, `event_msg`, `response_item`}. `session_meta.payload` has `id`, `cwd`, `timestamp`, `git{branch, commit_hash, repository_url}`. `response_item.payload.type` ∈ {`message`, `function_call`, `function_call_output`, `reasoning`}; a `message` has `role` ∈ {`user`, `assistant`, `developer`} and `content: [{type: input_text | output_text, text}]`. `developer` messages and user `input_text` blocks beginning `<environment_context>`, `<permissions>`, `<apps_instructions>`, `<skills_instructions>`, `<plugins_instructions>` are harness-injected; one user message carried `[<environment_context>, plain prompt]` as two blocks — so tag filtering is **per block**, never on the joined message. `event_msg` `user_message` / `agent_message` duplicate the `response_item` messages and are ignored.

**Claude Code hooks (code.claude.com/docs/en/hooks, fetched 2026-09-03).** Every hook gets JSON on stdin with `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `permission_mode`. `Stop` fires "when Claude finishes responding", supports no matcher, exit 2 blocks the stop (we always exit 0). `SessionEnd` fires on `clear | resume | logout | prompt_input_exit | other` and its hooks **share a 1.5 s budget**. Hooks in `~/.claude/settings.json` **merge** with project-level hooks. Config shape: `{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "...", "timeout": N}]}]}}`. **Codex** keeps the same shape in `~/.codex/hooks.json` (verified on this machine: `hooks.Stop[].hooks[].{type: "command", command}`); its Stop payload is NOT verified — R9 below.

**Cicada seams.** Importer body shape: `api/routers/conversations.py:792` writes `f"{msg['role']}: {msg['text']}"` lines joined by `\n`, hashes the joined body at `:794` (`sha256[:12]`), and `_update_episode_in_place` at `:915-934` keeps id/timestamp, rewrites the body, sets `content_hash`, flips `processed: False`. `evidence.speaker_kind` (`api/services/evidence.py:166`) reads `^(user|human|assistant|ai|system|unknown)\s*:` markers (`:64`). `episode_ids.next_episode_id` / `utc_now_iso` / `to_utc_iso` (`api/services/episode_ids.py`) are the one id and clock rule (G114). `agentic_write.mark_episodes_processed` (`api/services/agentic_write.py:490-532`) writes `processed_by` only beside `processed: true`. `session_stats.is_uuid` / `project_slug` / `transcripts_root` (`api/services/session_stats.py:43-58`) already encode the Claude Code transcript layout. `auth._STATIC_OPEN_PATHS` (`api/services/auth.py:46-49`) is the only auth exemption list — the new endpoint is NOT added to it. `telemetry.KINDS` / `FEEDBACK_KINDS` (`api/services/telemetry.py:21-31`), `record` (`:129`), `bank_name` (`:266`); `consumption_stats.stats` filters spend rows at `api/services/consumption_stats.py:213` by `FEEDBACK_KINDS`. `connections/base.scrubbed_env` (`api/services/connections/base.py:85-86`) is the env every Cicada CLI spawn — including Sleep's `claude -p` — runs under. `install.sh` step 5 (MCP) is at `:254-279`, `--uninstall` at `:88-111`, the summary at `:355-369`, and `-h` prints the header comment via `sed -n '3,24p'` (`:57`); `scripts/doctor.sh` already has **eleven** checks — check 10 (the `claude -p` probe) ends at `:168`, check 11 (stray `ANTHROPIC_API_KEY`) at `:177`, and the `FAILURES` summary starts at `:179` — so the hook check is **check 12**. Swift: `EpisodeQueueItem` (`app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift:718-745`) already carries `origin`; `EpisodeRow` (`Views/Sleep/SleepView.swift:662-728`); `SleepDebtBreakdown.sourceRow` (`Views/Sleep/SleepDebtBreakdown.swift:148-161`); `OriginIconography` (`Views/Capture/OriginIconography.swift:19`); `LogoImage(name:size:)` + `LogoImage.exists(name:)` (`Views/Common/LogoImage.swift:16-60, 118-120`); `SafariGlyph` / `ChromeGlyph` (`Views/Capture/Sheets/ImportFamilies.swift:163, 192`); bundled logos in `Resources/logos/`: `claude-code`, `claude-desktop`, `codex`, `cursor`, `gemini-cli`, `hermes`, `instagram`, `linkedin`, `openclaw`, `pinterest`, `reddit`, `telegram`, `tiktok`, `x`, `youtube` (no `chatgpt`, no `safari`, no `chrome`).

## Rulings (binding — do not re-derive)

- **R1 — `Stop`, not `SessionEnd`.** The hook is registered under `hooks.Stop`. `SessionEnd` only fires on a graceful exit (`clear | resume | logout | prompt_input_exit | other`) — a closed terminal window or a killed process never fires it — and its hooks share a 1.5 s budget. `Stop` fires after every reply, so the LAST Stop of a session is the session's end for capture purposes whatever way it ended. G76's "Stop hooks deliberately excluded — volume without judgment" was about an agent-in-the-loop design; here the extractor is deterministic and the endpoint is idempotent by content hash (R3), so volume is cost, not noise. Cost is bounded by a cheap line prefilter (R6) and by the hash short-circuit. `SessionEnd` is NOT also registered: it would add a second read of the same transcript with nothing new in it.
- **R2 — The backend reads the file; the hook never does.** The hook forwards the harness's own stdin JSON (`session_id`, `transcript_path`, `cwd`, `hook_event_name`) and nothing else. The endpoint refuses any path that, after `expanduser` + `resolve()` (symlinks), is not under the harness root (`~/.claude/projects` for `claude-code`, `~/.codex/sessions` for `codex`), is not a `.jsonl` regular file, exceeds `MAX_TRANSCRIPT_BYTES` (256 MiB), or — for `claude-code` — whose stem is not byte-equal to the `session_id` (that stem IS the id the MCP seam already keys `isfile()` on, `session_stats.py:72`); for `codex` the filename must contain the `session_id`. A refusal is a `400` with an enum reason and a ledger row; nothing is written. This is the G48 rail restated: the only transcript read is the one the harness just handed us, for the session that just ended.
- **R3 — One episode per session, keyed `(capture_kind: transcript, session_id)`.** First firing creates `ep_<date>_NNN` via `episode_ids.next_episode_id`; every later firing for the same `session_id` finds that file and, if the body hash differs, rewrites the body in place, keeps `id`/`timestamp`/`session_id`/`harness`/`project_dir`, refreshes `content_hash`/`captured_at`/`turns`/`title`, sets `processed: false` and **pops `processed_by`** (G114 R6 says the stamp is written only beside `processed: true`; a re-queued episode carrying a stale `sleep` stamp would read as consolidated). Same hash → `unchanged`, no write, no git noise. An MCP `cicada_save_episode` from the same session carries the same `session_id` but no `capture_kind`, so it is a different, deliberate episode and is never touched. Body = `"\n".join(f"{role}: {text}")`, hash = `sha256(body)[:12]` — byte-identical to `conversations.py:792-794`, so G118 spans and `speaker_kind` work unchanged.
- **R4 — Turn boundary = any user-role message that carries no `tool_result` block, kept or not.** A `tool_result` message is mid-turn (tool output wearing the user role) and is neither kept nor a boundary. At a boundary the pending assistant text is flushed as the previous turn's final reply. Inside a turn, a `tool_use` block (Codex: `function_call`) resets the pending assistant text — everything said before a tool call is interstitial narration and is dropped by construction. `thinking` / `reasoning` blocks neither reset nor flush.
- **R5 — Harness-injected user text is dropped per block by leading tag; `<system-reminder>` spans are stripped from within real text.** Claude Code tag set: `task-notification, command-name, command-message, command-args, command-stdout, local-command-stdout, local-command-caveat, system-reminder, ide_opened_file, ide_selection, ide_diagnostics`. Codex: `environment_context, user_instructions, permissions, apps_instructions, skills_instructions, plugins_instructions, turn_aborted, collaboration_mode`. `isMeta`, `isSidechain`, `isCompactSummary`, `isApiErrorMessage` lines are dropped whole. Anything else the person typed — including text that merely contains a `<`-tag later on — is kept.
- **R6 — Cleaning order per kept turn: strip fenced code → scrub secrets → per-turn cap (2,000 chars) → session cap (100,000 chars, head-stable).** Fences first because code is the densest secret carrier; scrub before the cap so a truncated token cannot escape; the session cap keeps the FIRST turns and flags `session_cap_hit` so the episode head is stable across firings (a G118 span into an early turn stays valid; a tail-keeping cap would move every offset on every Stop). Claude Code lines are prefiltered with `"type"\s*:\s*"(?:user|assistant)"` before `json.loads` — the 85 MB file is mostly `attachment` / `file-history-snapshot` lines that never need parsing; a line of another type that happens to contain the substring is parsed and then dropped by type, so the prefilter changes cost, never output (tested).
- **R7 — One flag: `Settings.capture_assistant_replies` (`CICADA_CAPTURE_ASSISTANT_REPLIES`, default `true`).** `false` keeps only the person's turns (the owner's stated fallback). It is read by the endpoint, not the hook, so flipping it needs no re-registration.
- **R8 — Cicada's own `claude -p` runs never capture.** `connections/base.scrubbed_env()` sets `CICADA_CAPTURE=off` in the env of every CLI Cicada spawns (Sleep's agent engine, doctor probes, login flows); the hook exits 0 immediately when it sees that variable. Without this, a Sleep cycle on the Max plan would fire the Stop hook on its own extraction prompts and write them back into the bank as episodes — a feedback loop. Belt and braces: the agent engine already runs with `--no-session-persistence` (`agent_engine.py:52`), so there is no transcript to read either.
- **R9 — Codex: extractor, endpoint and registration ship; the hook payload is unverified, so the hook is tolerant.** `install.sh` registers the same script with `--harness codex` in `~/.codex/hooks.json` only when `codex` is on `PATH`. If Codex's Stop payload lacks `transcript_path` the hook logs `skipped: no transcript_path` and exits 0 — nothing breaks, and the log line is the verification signal. Claude Desktop / ChatGPT keep their export importers.
- **R10 — Ledger row is `kind: capture`, counts only, excluded from spend rollups.** `refs = {harness, status, session_id, turns_user, turns_assistant, dropped_blocks{…}, dropped_messages{…}, truncated_turns, scrubbed, session_cap_hit}`. `capture` joins a new `NON_SPEND_KINDS` tuple beside `FEEDBACK_KINDS` so `consumption_stats.stats` never shows it as an "unknown" connection (the G113 R7 problem, same fix).
- **R11 — Swift: `OriginIconography.logoName(for:)` + `brandGlyph(for:)` + one `OriginMark` view.** Used by `EpisodeRow` and `SleepDebtBreakdown.sourceRow`. Precedence: bundled PNG → drawn glyph (Safari/Chrome) → the existing SF Symbol, mirroring `MemberMark`. Labels added: `codex → "Codex"`, `claude-desktop → "Claude Desktop"`, `cursor → "Cursor"`, `gemini-cli → "Gemini CLI"`. `mcp → "MCP"` stays byte-for-byte (Activity strip compat). `EpisodeQueueItem` is not changed — `origin` is already on the wire.
- **R12 — Episode title = the first kept user turn's first line, ≤ 72 chars, else `"<Product> session"`.** Bank content, not docs — the body already holds the words; a title that is the opening question makes the queue legible.
- **R13 — `capture_kind: transcript` is the discriminator**, plus `harness`, `session_id`, `project_dir` (= hook `cwd`), `captured_at`, `turns`. `source` and `origin` are both the harness id (`claude-code` / `codex`) — `sleep_cycle._derive_origin` passes them through, `OriginIconography` already labels `claude-code`.
- **R14 — Hook and registry are stdlib-only and run by path, not `-m`.** `api/hooks/capture.py` and `api/hooks/registry.py` import nothing from `api.*`, so they run under the venv interpreter from any cwd (a hook has no cwd guarantee) and the registered command is `"<venv python>" "<repo>/api/hooks/capture.py" --harness claude-code`. Both are unit-tested through their `main(argv, …)` with injected stdin / poster / clock.

## Not in scope

- MCP changes (`mcp/server.py`), `SKILL.md`, the SessionStart primer hook (G49/G53/G75 — parallel track).
- Cursor / Gemini CLI / other harness parsers; a backfill over historical transcripts (the only read is the session that just ended, R2).
- Any inbox change; any Sleep pipeline change (Sleep sees a normal `processed: false` episode).
- `SessionEnd` / `PreCompact` registration (R1).
- Codex hook payload verification (R9 — a manual check in the final verification, not code).
- `_update_episode_in_place` / importer refactor — the new writer mirrors its shape; it does not call it (the importer's `source_id` key means a different thing).
- App-side display of `capture_kind`, `turns`, or hook health; a Settings toggle for R7 (env var only).

---

## File map

| File | Responsibility |
|---|---|
| `api/services/transcript_extract.py` (new) | `Turn`, `Conversation`, `extract_claude_code`, `extract_codex`, `extract`, `strip_code_fences`, `scrub_secrets` — pure, engine-free |
| `api/tests/test_transcript_extract.py` (new) | synthetic-transcript tests for the ruling |
| `api/services/transcript_capture.py` (new) | path validation, one-episode-per-session writer, ledger row |
| `api/routers/capture.py` | `POST /capture/transcript` |
| `api/config.py` | `capture_assistant_replies` |
| `api/services/telemetry.py`, `api/services/consumption_stats.py` | `capture` kind, `NON_SPEND_KINDS` |
| `api/tests/test_capture_transcript.py` (new) | endpoint + writer tests |
| `api/hooks/__init__.py`, `api/hooks/capture.py`, `api/hooks/registry.py` (new) | the hook, the settings merge |
| `api/services/connections/base.py` | `CICADA_CAPTURE=off` in `scrubbed_env` |
| `api/tests/test_capture_hook.py`, `api/tests/test_hooks_registry.py` (new) | hook + merge tests |
| `install.sh`, `scripts/doctor.sh` | register / unregister / report |
| `app/CicadaApp/Sources/CicadaApp/Views/Capture/OriginIconography.swift`, `Views/Common/OriginMark.swift` (new), `Views/Sleep/SleepView.swift`, `Views/Sleep/SleepDebtBreakdown.swift` | source marks |
| `app/CicadaApp/Tests/CicadaAppTests/OriginIconographyTests.swift` (new) | mark map tests |
| `CLAUDE.md`, `docs/goals/memory-evolution.md`, `docs/goals/TODO.md` | docs |

---

### Task 1: `transcript_extract` — the ruling as a pure function

**Files:**
- Create: `api/services/transcript_extract.py`
- Test: `api/tests/test_transcript_extract.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class Turn: role: str; text: str; ts: str | None
  @dataclass
  class Conversation: harness: str; session_id: str | None; cwd: str | None; started_at: str | None; ended_at: str | None; turns: list[Turn]; summary: dict
  def extract_claude_code(lines: Iterable[str], *, keep_assistant: bool = True, turn_cap: int = TURN_CAP_CHARS, session_cap: int = SESSION_CAP_CHARS) -> Conversation
  def extract_codex(lines: Iterable[str], *, keep_assistant=True, turn_cap=..., session_cap=...) -> Conversation
  def extract(harness: str, lines: Iterable[str], **kw) -> Conversation   # dispatch; ValueError on unknown harness
  def strip_code_fences(text: str) -> str
  def scrub_secrets(text: str) -> tuple[str, int]
  HARNESSES = ("claude-code", "codex"); TURN_CAP_CHARS = 2000; SESSION_CAP_CHARS = 100_000
  ```
- `summary` shape (counts only, R10): `{"kept": {"user": n, "assistant": n}, "dropped_blocks": {…}, "dropped_messages": {…}, "truncated_turns": n, "scrubbed": n, "session_cap_hit": bool}`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_transcript_extract.py
"""G105: the block-level extractor, on synthetic transcripts only.

Every fixture is built here from placeholder content (alpha-project,
bob-example, example.com). No real transcript is ever read by this suite.
"""
from __future__ import annotations

import json

import pytest

from api.services import transcript_extract as tx

SID = "11111111-2222-4333-8444-555555555555"


# --- Claude Code fixture builders --------------------------------------------


def _line(typ: str, content, *, ts: str = "2026-09-03T10:00:00.000Z", **extra) -> str:
    obj = {
        "type": typ,
        "uuid": f"u-{len(json.dumps(content))}",
        "parentUuid": None,
        "timestamp": ts,
        "sessionId": SID,
        "cwd": "/home/example/alpha-project",
        "message": {"role": typ, "content": content},
    }
    obj.update(extra)
    return json.dumps(obj)


def user(text: str, **extra) -> str:
    return _line("user", text, **extra)


def user_blocks(blocks: list[dict], **extra) -> str:
    return _line("user", blocks, **extra)


def asst_text(text: str, **extra) -> str:
    return _line("assistant", [{"type": "text", "text": text}], **extra)


def asst_tool(name: str = "Bash", **extra) -> str:
    return _line("assistant", [{"type": "tool_use", "id": "t1", "name": name, "input": {"command": "ls"}}], **extra)


def asst_thinking(**extra) -> str:
    return _line("assistant", [{"type": "thinking", "thinking": "private"}], **extra)


def tool_result(text: str = "file contents", **extra) -> str:
    return _line("user", [{"type": "tool_result", "tool_use_id": "t1", "content": text}], **extra)


def attachment_line() -> str:
    # A non-turn line whose body contains the user/assistant substring the
    # prefilter keys on — must be parsed-then-dropped, never kept (R6).
    return json.dumps({"type": "attachment", "attachment": {"text": '"type":"user" quoted'}})


# --- Claude Code: what is kept ----------------------------------------------


def test_person_turn_and_final_reply_kept_interstitial_and_tools_dropped():
    lines = [
        user("What did bob-example say about alpha-project?"),
        asst_text("Let me look that up."),          # interstitial narration
        asst_tool(),
        tool_result("bob-example: ship it"),         # tool output wearing the user role
        asst_thinking(),
        asst_text("bob-example said to ship alpha-project."),  # the final reply
        user("Thanks."),
    ]
    conv = tx.extract_claude_code(lines)
    assert conv.session_id == SID
    assert conv.cwd == "/home/example/alpha-project"
    assert [(t.role, t.text) for t in conv.turns] == [
        ("user", "What did bob-example say about alpha-project?"),
        ("assistant", "bob-example said to ship alpha-project."),
        ("user", "Thanks."),
    ]
    s = conv.summary
    assert s["kept"] == {"user": 2, "assistant": 1}
    assert s["dropped_blocks"]["tool_use"] == 1
    assert s["dropped_blocks"]["tool_result"] == 1
    assert s["dropped_blocks"]["thinking"] == 1
    assert s["dropped_blocks"]["interstitial"] == 1


def test_final_reply_may_span_several_text_lines_after_the_last_tool_call():
    lines = [
        user("Summarise."),
        asst_text("Narration one."),
        asst_tool(),
        tool_result(),
        asst_text("Part one of the answer."),
        asst_text("Part two of the answer."),
    ]
    conv = tx.extract_claude_code(lines)
    assert conv.turns[-1].role == "assistant"
    assert conv.turns[-1].text == "Part one of the answer.\n\nPart two of the answer."
    assert conv.summary["dropped_blocks"]["interstitial"] == 1


def test_user_message_with_text_blocks_is_kept_and_image_counted():
    lines = [user_blocks([{"type": "text", "text": "Look at this."}, {"type": "image", "source": {}}])]
    conv = tx.extract_claude_code(lines)
    assert [t.text for t in conv.turns] == ["Look at this."]
    assert conv.summary["dropped_blocks"]["image"] == 1


# --- Claude Code: what is never kept (R5) ------------------------------------


@pytest.mark.parametrize("body", [
    "<task-notification>\n<task-id>x</task-id>\n</task-notification>",
    "<command-name>/clear</command-name>",
    "<local-command-stdout>ok</local-command-stdout>",
    "<local-command-caveat>Caveat.</local-command-caveat>",
    "<command-message>x</command-message>",
])
def test_harness_tagged_user_bodies_are_dropped(body):
    conv = tx.extract_claude_code([user(body)])
    assert conv.turns == []
    assert conv.summary["dropped_messages"]["harness_tag"] == 1


def test_meta_sidechain_compact_and_api_error_lines_are_dropped():
    lines = [
        user("meta text", isMeta=True),
        user("sidechain text", isSidechain=True),
        user("compact text", isCompactSummary=True),
        _line("assistant", [{"type": "text", "text": "API error"}], isApiErrorMessage=True),
        user("real text"),
    ]
    conv = tx.extract_claude_code(lines)
    assert [t.text for t in conv.turns] == ["real text"]
    dm = conv.summary["dropped_messages"]
    assert dm["meta"] == 1 and dm["sidechain"] == 1 and dm["compact_summary"] == 1 and dm["api_error"] == 1


def test_system_reminder_span_is_stripped_from_real_user_text():
    body = "Please rename alpha-project.<system-reminder>\ninjected\n</system-reminder>"
    conv = tx.extract_claude_code([user(body)])
    assert [t.text for t in conv.turns] == ["Please rename alpha-project."]


def test_tag_filter_is_per_block_not_per_message():
    lines = [user_blocks([
        {"type": "text", "text": "<ide_opened_file>x.py</ide_opened_file>"},
        {"type": "text", "text": "Real question about alpha-project."},
    ])]
    conv = tx.extract_claude_code(lines)
    assert [t.text for t in conv.turns] == ["Real question about alpha-project."]


def test_tool_result_is_not_a_turn_boundary_but_a_meta_user_line_is():
    # Narration → tool → result → final: the result must NOT flush the
    # narration as a reply; a meta user line between two replies must.
    lines = [
        user("Q1"),
        asst_text("narration"), asst_tool(), tool_result(),
        asst_text("A1"),
        user("meta", isMeta=True),
        asst_text("A2"),
    ]
    conv = tx.extract_claude_code(lines)
    assert [(t.role, t.text) for t in conv.turns] == [("user", "Q1"), ("assistant", "A1"), ("assistant", "A2")]


def test_prefilter_changes_cost_never_output():
    lines = [attachment_line(), user("kept"), json.dumps({"type": "file-history-snapshot", "snapshot": {}})]
    conv = tx.extract_claude_code(lines)
    assert [t.text for t in conv.turns] == ["kept"]
    assert conv.summary["dropped_messages"]["other_type"] == 2


def test_bad_json_and_blank_lines_are_counted_not_raised():
    # The broken line carries the prefilter substring so it reaches the
    # parser (a line without it is counted as other_type, never parsed).
    conv = tx.extract_claude_code(["", '{"type":"user", not json', user("ok")])
    assert [t.text for t in conv.turns] == ["ok"]
    assert conv.summary["dropped_messages"]["bad_json"] == 1


# --- Cleaning (R6) -------------------------------------------------------------


def test_code_fences_are_stripped_including_an_unterminated_one():
    text = "Use this:\n```python\nprint('x')\n```\nthen done.\n```\ntrailing"
    assert tx.strip_code_fences(text) == "Use this:\n[code omitted]\nthen done.\n[code omitted]"


@pytest.mark.parametrize("secret", [
    "sk-abcdefghijklmnopqrstuvwxyz123456",
    "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123",
    "xoxb-123456789012-abcdefghijkl",
    "AKIAABCDEFGHIJKLMNOP",
    "Bearer abcdefghijklmnopqrstuvwxyz0123456789",
    "api_key=abcdefghijklmnop1234",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnopqrstuv",
    "0123456789abcdef0123456789abcdef0123456789abcdef",
    "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----",
])
def test_scrubber_redacts_secret_shapes(secret):
    out, n = tx.scrub_secrets(f"here: {secret} end")
    assert secret.split()[0] not in out and secret[-8:] not in out
    assert "[redacted]" in out
    assert n >= 1


def test_scrubber_leaves_prose_paths_and_short_hashes_alone():
    text = "See https://example.com/alpha-project/docs/getting-started/install-guide-for-users at commit abc1234 with bob-example."
    out, n = tx.scrub_secrets(text)
    assert out == text and n == 0


def test_per_turn_cap_truncates_and_counts():
    # Prose, not a single-character run: 5,000 x's IS a 64+ char base64 run
    # and the scrubber would (correctly) redact it to "[redacted]" before
    # the cap is ever reached.
    conv = tx.extract_claude_code([user("word " * 1000)], turn_cap=100)
    assert len(conv.turns[0].text) == 100
    assert conv.turns[0].text.endswith("…")
    assert conv.summary["truncated_turns"] == 1


def test_session_cap_keeps_the_head_and_flags():
    # Word runs, not "a" * 60 — sixty hex characters match the 32+ hex rule
    # and would be redacted. After strip(): 59 + 59 fits 130, + 63 does not.
    lines = [user("alpha " * 10), asst_text("bravo " * 10), user("charlie " * 8)]
    conv = tx.extract_claude_code(lines, session_cap=130)
    assert [t.text[0] for t in conv.turns] == ["a", "b"]
    assert conv.summary["session_cap_hit"] is True


def test_secrets_inside_code_fences_never_survive_and_scrub_runs_before_cap():
    body = "Token:\n```\nsk-abcdefghijklmnopqrstuvwxyz123456\n```\nand also sk-zyxwvutsrqponmlkjihgfedcba654321 here"
    conv = tx.extract_claude_code([user(body)], turn_cap=40)
    assert "sk-" not in conv.turns[0].text
    assert conv.summary["scrubbed"] == 1


def test_keep_assistant_false_drops_replies_only():
    lines = [user("Q"), asst_text("A")]
    conv = tx.extract_claude_code(lines, keep_assistant=False)
    assert [t.role for t in conv.turns] == ["user"]
    assert conv.summary["dropped_messages"]["assistant_by_flag"] == 1


def test_timestamps_bracket_the_kept_turns():
    lines = [user("Q", ts="2026-09-03T10:00:00.000Z"), asst_text("A", ts="2026-09-03T10:05:00.000Z")]
    conv = tx.extract_claude_code(lines)
    assert conv.started_at == "2026-09-03T10:00:00.000Z"
    assert conv.ended_at == "2026-09-03T10:05:00.000Z"
    assert conv.turns[1].ts == "2026-09-03T10:05:00.000Z"


# --- Codex ---------------------------------------------------------------------


def _cx(typ: str, payload: dict, ts: str = "2026-09-03T10:00:00.000Z") -> str:
    return json.dumps({"timestamp": ts, "type": typ, "payload": payload})


def cx_msg(role: str, texts: list[str]) -> str:
    kind = "output_text" if role == "assistant" else "input_text"
    return _cx("response_item", {"type": "message", "role": role, "content": [{"type": kind, "text": t} for t in texts]})


def test_codex_same_ruling_same_shape():
    lines = [
        _cx("session_meta", {"id": SID, "cwd": "/home/example/alpha-project", "timestamp": "2026-09-03T09:59:00Z"}),
        cx_msg("developer", ["<permissions>x</permissions>"]),
        cx_msg("user", ["<environment_context>cwd</environment_context>", "Rename alpha-project?"]),
        _cx("event_msg", {"type": "user_message", "message": "Rename alpha-project?"}),
        cx_msg("assistant", ["Checking."]),
        _cx("response_item", {"type": "function_call", "name": "shell", "arguments": "{}", "call_id": "c1"}),
        _cx("response_item", {"type": "function_call_output", "call_id": "c1", "output": "ok"}),
        _cx("response_item", {"type": "reasoning", "summary": []}),
        cx_msg("assistant", ["Yes — rename it."]),
        _cx("event_msg", {"type": "agent_message", "message": "Yes — rename it."}),
    ]
    conv = tx.extract_codex(lines)
    assert conv.harness == "codex"
    assert conv.session_id == SID
    assert conv.cwd == "/home/example/alpha-project"
    assert [(t.role, t.text) for t in conv.turns] == [("user", "Rename alpha-project?"), ("assistant", "Yes — rename it.")]
    s = conv.summary
    assert s["dropped_blocks"]["function_call"] == 1
    assert s["dropped_blocks"]["function_call_output"] == 1
    assert s["dropped_blocks"]["reasoning"] == 1
    assert s["dropped_blocks"]["interstitial"] == 1
    assert s["dropped_messages"]["developer"] == 1
    assert s["dropped_messages"]["other_type"] == 2  # the two event_msg duplicates


def test_extract_dispatch_and_unknown_harness():
    assert tx.extract("claude-code", [user("hi")]).turns[0].text == "hi"
    with pytest.raises(ValueError):
        tx.extract("cursor", [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && api/.venv/bin/python -m pytest api/tests/test_transcript_extract.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.services.transcript_extract'`.

- [ ] **Step 3: Implement `api/services/transcript_extract.py`**

```python
"""Deterministic, block-level transcript extraction (G105).

Capture used to be agent judgment: an episode existed only if a model chose
to call ``cicada_save_episode`` (measured: zero MCP tool invocations in 12
days; four episodes from one very long session — TODO.md ruling 6). This
module is the other rung of G80's ladder: a *parser* decides what is
conversation content, and it decides the same way every time.

The RULING (G105, 2026-09-03) is implemented literally:

* keep (a) the person's turns — ``user`` messages whose blocks are ``text``;
  a ``user`` message carrying a ``tool_result`` is tool output wearing the
  user role and is dropped without becoming a turn boundary (R4);
* keep (b) the agent's FINAL reply per turn — the ``text`` blocks after the
  last ``tool_use`` and before the next boundary; interstitial narration,
  every ``tool_use`` / ``tool_result`` / ``thinking`` block and every file
  dump are skipped by construction, not by heuristics;
* on what survives: fenced code stripped, secrets scrubbed, a per-turn cap
  and a head-stable session cap (R6);
* ``keep_assistant=False`` drops (b) — the owner's fallback if the assistant
  half proves noisy (R7).

The G48 rail is restated, not removed: tool output, code and secrets never
enter a bank. This module never opens a file — it takes lines — so the
only transcript read stays where R2 puts it (``transcript_capture``).

Pure: no bank state, no LLM, no I/O. ``summary`` carries counts only so it
can go straight into the ledger (R10).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

HARNESSES = ("claude-code", "codex")

#: ~2,000 chars is the ruling's per-turn cap: enough for a real question or
#: a real answer, small enough that a pasted log cannot become an episode.
TURN_CAP_CHARS = 2000
#: Head-stable session cap (R6): the first turns are kept, later ones
#: dropped and flagged, so an episode's byte offsets — which G118 spans
#: point into — do not move between two hook firings on the same session.
SESSION_CAP_CHARS = 100_000

REDACTED = "[redacted]"
CODE_OMITTED = "[code omitted]"

# Harness-injected user text, by the tag it opens with (R5). Verified against
# a real transcript's key names on 2026-09-03: these wear the user role but
# are the harness talking to the model, not the person.
CLAUDE_HARNESS_TAGS = frozenset({
    "task-notification", "command-name", "command-message", "command-args",
    "command-stdout", "local-command-stdout", "local-command-caveat",
    "system-reminder", "ide_opened_file", "ide_selection", "ide_diagnostics",
})
CODEX_HARNESS_TAGS = frozenset({
    "environment_context", "user_instructions", "permissions",
    "apps_instructions", "skills_instructions", "plugins_instructions",
    "turn_aborted", "collaboration_mode",
})

_SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
_LEADING_TAG_RE = re.compile(r"^\s*<([A-Za-z_][A-Za-z0-9_-]*)")
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_OPEN_FENCE_RE = re.compile(r"```.*\Z", re.DOTALL)
# Cheap pre-parse gate for Claude Code lines (R6): a user/assistant line
# always contains this; an attachment / file-history-snapshot line usually
# does not, and those are the bulk of a large transcript.
_CLAUDE_PREFILTER = re.compile(r'"type"\s*:\s*"(?:user|assistant)"')

# Secret shapes (R6). Ordered longest-context first so a PEM block is taken
# whole before its base64 body is chewed up piecemeal. The hex and base64
# runs are deliberately long (32 / 64) so a short git SHA or an ordinary
# word survives; a base64 candidate with three or more ``/`` is a path, not
# a token, and is kept (see ``_scrub_base64``).
_SECRET_RES: tuple[re.Pattern[str], ...] = tuple(re.compile(p, f) for p, f in (
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    (r"\bsk-[A-Za-z0-9_-]{16,}", 0),
    (r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}", 0),
    (r"\bgithub_pat_[A-Za-z0-9_]{20,}", 0),
    (r"\bxox[abopr]s?-[A-Za-z0-9-]{10,}", 0),
    (r"\bAKIA[0-9A-Z]{16}\b", 0),
    (r"\bAIza[0-9A-Za-z_-]{30,}", 0),
    (r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", 0),
    (r"\bbearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    (r"\b(?:api[_-]?key|access[_-]?token|secret[_-]?key|client[_-]?secret|password|passwd|token)\b\s*[=:]\s*['\"]?[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    (r"\b[0-9a-fA-F]{32,}\b", 0),
))
_BASE64_RUN_RE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{64,}={0,2}(?![A-Za-z0-9+/])")


@dataclass
class Turn:
    role: str  # "user" | "assistant"
    text: str
    ts: str | None


@dataclass
class Conversation:
    harness: str
    session_id: str | None
    cwd: str | None
    started_at: str | None
    ended_at: str | None
    turns: list[Turn] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# --- cleaning ----------------------------------------------------------------


def strip_code_fences(text: str) -> str:
    """Replace every ``` fenced block — and an unterminated trailing one —
    with ``[code omitted]``. Code is memorialised in the repo and its git
    history (G105: "Cicada storing a bash command duplicates git badly");
    what a fence held is also the densest place a secret hides."""
    out = _FENCE_RE.sub(CODE_OMITTED, text)
    out = _OPEN_FENCE_RE.sub(CODE_OMITTED, out)
    return out.strip()


def _scrub_base64(m: re.Match[str]) -> str:
    return m.group(0) if m.group(0).count("/") >= 3 else REDACTED


def scrub_secrets(text: str) -> tuple[str, int]:
    """Redact API keys, bearer tokens, vendor-prefixed tokens, JWTs, private
    keys, ``key=value`` credentials, and long hex / base64 runs. Returns the
    scrubbed text and how many replacements were made (a count for the
    ledger — never what was replaced)."""
    count = 0
    for rx in _SECRET_RES:
        text, n = rx.subn(REDACTED, text)
        count += n
    # The base64 pass keeps path-like runs (three or more ``/``), so count
    # only the matches that were actually replaced — ``subn`` would count
    # every match, kept or not.
    count += sum(1 for m in _BASE64_RUN_RE.finditer(text) if m.group(0).count("/") < 3)
    text = _BASE64_RUN_RE.sub(_scrub_base64, text)
    return text, count


def _first_tag(text: str) -> str | None:
    m = _LEADING_TAG_RE.match(text)
    return m.group(1).lower() if m else None


def _text_blocks(content) -> list[dict]:
    """A string body becomes one text block so both shapes flow through the
    same per-block filter (R5 — filtering is per block, never per message)."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


class _Builder:
    """Turn assembly shared by both harnesses: R4's boundary rule, the
    final-reply-per-turn pending buffer, R6's cleaning order and caps."""

    def __init__(self, harness: str, *, keep_assistant: bool, turn_cap: int, session_cap: int):
        self.harness = harness
        self.keep_assistant = keep_assistant
        self.turn_cap = turn_cap
        self.session_cap = session_cap
        self.turns: list[Turn] = []
        self.pending: list[tuple[str, str | None]] = []
        self.kept: Counter = Counter()
        self.dropped_blocks: Counter = Counter()
        self.dropped_messages: Counter = Counter()
        self.truncated_turns = 0
        self.scrubbed = 0
        self.session_cap_hit = False
        self.total_chars = 0
        self.started_at: str | None = None
        self.ended_at: str | None = None

    # -- counting -------------------------------------------------------------
    def count_block(self, kind: str, n: int = 1) -> None:
        self.dropped_blocks[kind or "unknown"] += n

    def count_msg(self, kind: str, n: int = 1) -> None:
        self.dropped_messages[kind] += n

    # -- turns ------------------------------------------------------------------
    def user(self, text: str, ts: str | None) -> None:
        self.boundary()
        self._add("user", text, ts)

    def assistant_text(self, text: str, ts: str | None) -> None:
        if text and text.strip():
            self.pending.append((text, ts))

    def assistant_tool_call(self) -> None:
        """A tool call means everything the agent said so far this turn was
        narration on the way to the tool, not the reply (R4)."""
        self.count_block("interstitial", len(self.pending))
        self.pending = []

    def boundary(self) -> None:
        if not self.pending:
            return
        joined = "\n\n".join(t for t, _ in self.pending)
        ts = self.pending[-1][1]
        self.pending = []
        if not self.keep_assistant:
            self.count_msg("assistant_by_flag")
            return
        self._add("assistant", joined, ts)

    def _add(self, role: str, text: str, ts: str | None) -> None:
        cleaned = strip_code_fences(text)
        cleaned, n = scrub_secrets(cleaned)
        self.scrubbed += n
        cleaned = cleaned.strip()
        if not cleaned:
            self.count_msg("empty")
            return
        if len(cleaned) > self.turn_cap:
            cleaned = cleaned[: self.turn_cap - 1] + "…"
            self.truncated_turns += 1
        if self.total_chars + len(cleaned) > self.session_cap:
            self.session_cap_hit = True
            return
        self.turns.append(Turn(role=role, text=cleaned, ts=ts))
        self.total_chars += len(cleaned)
        self.kept[role] += 1
        if ts:
            self.started_at = self.started_at or ts
            self.ended_at = ts

    def finish(self, session_id: str | None, cwd: str | None) -> Conversation:
        self.boundary()
        return Conversation(
            harness=self.harness,
            session_id=session_id,
            cwd=cwd,
            started_at=self.started_at,
            ended_at=self.ended_at,
            turns=self.turns,
            summary={
                "kept": {"user": self.kept["user"], "assistant": self.kept["assistant"]},
                "dropped_blocks": dict(self.dropped_blocks),
                "dropped_messages": dict(self.dropped_messages),
                "truncated_turns": self.truncated_turns,
                "scrubbed": self.scrubbed,
                "session_cap_hit": self.session_cap_hit,
            },
        )


def _parse(raw: str, b: _Builder) -> dict | None:
    try:
        obj = json.loads(raw)
    except ValueError:
        b.count_msg("bad_json")
        return None
    if not isinstance(obj, dict):
        b.count_msg("bad_json")
        return None
    return obj


# --- Claude Code -------------------------------------------------------------


def extract_claude_code(
    lines: Iterable[str],
    *,
    keep_assistant: bool = True,
    turn_cap: int = TURN_CAP_CHARS,
    session_cap: int = SESSION_CAP_CHARS,
) -> Conversation:
    """One Claude Code transcript (JSONL lines) → the ruling's conversation."""
    b = _Builder("claude-code", keep_assistant=keep_assistant, turn_cap=turn_cap, session_cap=session_cap)
    session_id: str | None = None
    cwd: str | None = None
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        if not _CLAUDE_PREFILTER.search(raw):
            b.count_msg("other_type")
            continue
        obj = _parse(raw, b)
        if obj is None:
            continue
        typ = obj.get("type")
        if typ not in ("user", "assistant"):
            b.count_msg("other_type")
            continue
        session_id = session_id or (str(obj.get("sessionId") or "") or None)
        cwd = cwd or (str(obj.get("cwd") or "") or None)
        if obj.get("isSidechain"):
            b.count_msg("sidechain")
            continue
        if obj.get("isCompactSummary"):
            b.count_msg("compact_summary")
            continue
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
        blocks = _text_blocks(msg.get("content"))
        ts = str(obj.get("timestamp") or "") or None

        if typ == "user":
            kinds = Counter(str(bk.get("type") or "") for bk in blocks)
            if kinds.get("tool_result"):
                # Tool output wearing the user role: dropped, and NOT a
                # boundary (R4) — the agent's turn is still in progress.
                b.count_block("tool_result", kinds["tool_result"])
                continue
            b.boundary()
            if obj.get("isMeta"):
                b.count_msg("meta")
                continue
            for k, n in kinds.items():
                if k != "text":
                    b.count_block(k, n)
            kept: list[str] = []
            tagged = 0
            for bk in blocks:
                if bk.get("type") != "text":
                    continue
                text = _SYSTEM_REMINDER_RE.sub("", str(bk.get("text") or ""))
                tag = _first_tag(text)
                if tag in CLAUDE_HARNESS_TAGS:
                    tagged += 1
                    continue
                if text.strip():
                    kept.append(text)
            if not kept:
                b.count_msg("harness_tag" if tagged else "empty")
                continue
            b.user("\n".join(kept), ts)
        else:
            if obj.get("isApiErrorMessage"):
                b.count_msg("api_error")
                continue
            for bk in blocks:
                k = str(bk.get("type") or "")
                if k == "text":
                    b.assistant_text(str(bk.get("text") or ""), ts)
                elif k == "tool_use":
                    b.count_block("tool_use")
                    b.assistant_tool_call()
                elif k in ("thinking", "redacted_thinking"):
                    b.count_block("thinking")
                else:
                    b.count_block(k)
    return b.finish(session_id, cwd)


# --- Codex ---------------------------------------------------------------------


def extract_codex(
    lines: Iterable[str],
    *,
    keep_assistant: bool = True,
    turn_cap: int = TURN_CAP_CHARS,
    session_cap: int = SESSION_CAP_CHARS,
) -> Conversation:
    """One Codex rollout (JSONL lines) → the same conversation shape.

    Only ``response_item`` lines carry turns; ``event_msg`` ``user_message`` /
    ``agent_message`` lines duplicate them and are counted as ``other_type``.
    ``function_call`` is Codex's ``tool_use`` (resets the pending reply);
    ``function_call_output`` its ``tool_result``; ``reasoning`` its thinking.
    """
    b = _Builder("codex", keep_assistant=keep_assistant, turn_cap=turn_cap, session_cap=session_cap)
    session_id: str | None = None
    cwd: str | None = None
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        obj = _parse(raw, b)
        if obj is None:
            continue
        typ = obj.get("type")
        payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
        ts = str(obj.get("timestamp") or "") or None
        if typ == "session_meta":
            session_id = session_id or (str(payload.get("id") or "") or None)
            cwd = cwd or (str(payload.get("cwd") or "") or None)
            continue
        if typ != "response_item":
            b.count_msg("other_type")
            continue
        ptype = str(payload.get("type") or "")
        if ptype == "message":
            role = str(payload.get("role") or "")
            texts = [
                str(bk.get("text") or "")
                for bk in (payload.get("content") or [])
                if isinstance(bk, dict) and bk.get("type") in ("input_text", "output_text")
            ]
            if role == "user":
                b.boundary()
                kept = [t for t in texts if _first_tag(t) not in CODEX_HARNESS_TAGS and t.strip()]
                if not kept:
                    b.count_msg("harness_tag" if texts else "empty")
                    continue
                b.user("\n".join(kept), ts)
            elif role == "assistant":
                b.assistant_text("\n".join(texts), ts)
            else:
                b.count_msg("developer")
        elif ptype == "function_call":
            b.count_block("function_call")
            b.assistant_tool_call()
        elif ptype == "function_call_output":
            b.count_block("function_call_output")
        elif ptype == "reasoning":
            b.count_block("reasoning")
        else:
            b.count_block(ptype)
    return b.finish(session_id, cwd)


def extract(harness: str, lines: Iterable[str], **kw) -> Conversation:
    if harness == "claude-code":
        return extract_claude_code(lines, **kw)
    if harness == "codex":
        return extract_codex(lines, **kw)
    raise ValueError(f"unknown harness {harness!r} (known: {', '.join(HARNESSES)})")
```

- [ ] **Step 4: Run the tests until green**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && api/.venv/bin/python -m pytest api/tests/test_transcript_extract.py -q -p no:cacheprovider`
Expected: all 33 pass (verified by the plan critic on 2026-09-03 with these exact files). Two traps if a fixture is edited: a long single-character run (`"x" * 5000`, `"a" * 60`) is a base64 / hex secret to the scrubber and comes back as `[redacted]` — cap tests must use word runs; and if `test_secrets_inside_code_fences_never_survive_and_scrub_runs_before_cap` fails on `scrubbed == 1`, the fence was not stripped BEFORE scrubbing (the fenced key must not be counted).

- [ ] **Step 5: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && git add api/services/transcript_extract.py api/tests/test_transcript_extract.py && git commit -m "feat(capture): block-level transcript extractor — person's turns + agent's final replies, tool blocks/code/secrets never (G105 R4–R6)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

### Task 2: `POST /capture/transcript` — one episode per session, updated in place

**Files:**
- Create: `api/services/transcript_capture.py`
- Modify: `api/routers/capture.py` (append the route after `capture_telegram`)
- Modify: `api/config.py:203-205` (add `capture_assistant_replies` before `model_config`)
- Modify: `api/services/telemetry.py:21-31` (`KINDS` + `NON_SPEND_KINDS`), `api/services/consumption_stats.py:213`
- Test: `api/tests/test_capture_transcript.py`

**Interfaces:**
- Produces:
  ```python
  class TranscriptRefused(Exception): reason: str   # enum: bad_harness | bad_session_id | outside_root | not_jsonl | not_a_file | too_large | stem_mismatch
  MAX_TRANSCRIPT_BYTES = 256 * 1024 * 1024
  def harness_root(harness: str) -> Path                 # monkeypatch target in tests
  def validate_transcript_path(harness: str, session_id: str, raw_path: str) -> Path
  @dataclass class CaptureResult: status: str; episode_id: str | None; turns_user: int; turns_assistant: int; summary: dict; reason: str | None = None
  def capture_transcript(memory_path: Path, *, harness: str, session_id: str, transcript_path: str, cwd: str | None, keep_assistant: bool, bank: str | None = None) -> CaptureResult
  ```
  `status` ∈ `created | updated | unchanged | empty | refused`.
- Route: `POST /capture/transcript` body `{harness, session_id, transcript_path, cwd?, hook_event?}` → `200 {status, episodeId, turnsUser, turnsAssistant, summary}`; `400 {detail: <reason>}` on refusal. Bearer-authed like every other endpoint (nothing added to `auth._STATIC_OPEN_PATHS`).

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_capture_transcript.py
"""G105 R2/R3/R10: the endpoint validates the path, writes ONE episode per
session in the importer's body shape, updates it in place on a later firing,
and records a counts-only ledger row. Synthetic transcripts only."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.services import markdown_parser, telemetry, transcript_capture as tc
from api.services.evidence import speaker_kind

SID = "11111111-2222-4333-8444-555555555555"


def _line(typ, content, ts="2026-09-03T10:00:00.000Z", **extra):
    o = {"type": typ, "uuid": "u", "timestamp": ts, "sessionId": SID, "cwd": "/home/example/alpha-project",
         "message": {"role": typ, "content": content}}
    o.update(extra)
    return json.dumps(o)


def _transcript(turns: list[tuple[str, str]]) -> str:
    lines = []
    for role, text in turns:
        lines.append(_line(role, text if role == "user" else [{"type": "text", "text": text}]))
    return "\n".join(lines) + "\n"


@pytest.fixture(autouse=True)
def _fresh_episode_cache(monkeypatch):
    # The writer's session -> path cache is process-global; every test gets
    # its own bank, so start each from an empty one (without this, test N
    # finds test N-1's episode file — it still exists under pytest's tmp).
    monkeypatch.setattr(tc, "_episode_cache", {})


@pytest.fixture
def roots(tmp_path, monkeypatch):
    claude = tmp_path / "claude-projects" / "-home-example-alpha-project"
    codex = tmp_path / "codex-sessions" / "2026" / "09" / "03"
    claude.mkdir(parents=True)
    codex.mkdir(parents=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: {"claude-code": claude.parent, "codex": codex.parent.parent.parent}[h])
    return {"claude": claude, "codex": codex}


@pytest.fixture
def memory(tmp_path):
    m = tmp_path / "memory"
    (m / "episodes").mkdir(parents=True)
    return m


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# --- validation (R2) -----------------------------------------------------------


def test_refuses_paths_outside_the_harness_root(roots, tmp_path):
    stray = _write(tmp_path / f"{SID}.jsonl", _transcript([("user", "hi")]))
    with pytest.raises(tc.TranscriptRefused) as e:
        tc.validate_transcript_path("claude-code", SID, str(stray))
    assert e.value.reason == "outside_root"


def test_refuses_symlink_that_escapes_the_root(roots, tmp_path):
    target = _write(tmp_path / "elsewhere.jsonl", _transcript([("user", "hi")]))
    link = roots["claude"] / f"{SID}.jsonl"
    os.symlink(target, link)
    with pytest.raises(tc.TranscriptRefused) as e:
        tc.validate_transcript_path("claude-code", SID, str(link))
    assert e.value.reason == "outside_root"


def test_refuses_stem_mismatch_non_jsonl_and_oversize(roots, monkeypatch):
    other = _write(roots["claude"] / "22222222-2222-4333-8444-555555555555.jsonl", "x")
    with pytest.raises(tc.TranscriptRefused) as e:
        tc.validate_transcript_path("claude-code", SID, str(other))
    assert e.value.reason == "stem_mismatch"
    txt = _write(roots["claude"] / f"{SID}.txt", "x")
    with pytest.raises(tc.TranscriptRefused) as e:
        tc.validate_transcript_path("claude-code", SID, str(txt))
    assert e.value.reason == "not_jsonl"
    big = _write(roots["claude"] / f"{SID}.jsonl", "x")
    monkeypatch.setattr(tc, "MAX_TRANSCRIPT_BYTES", 0)
    with pytest.raises(tc.TranscriptRefused) as e:
        tc.validate_transcript_path("claude-code", SID, str(big))
    assert e.value.reason == "too_large"


def test_refuses_bad_harness_and_bad_session_id(roots):
    with pytest.raises(tc.TranscriptRefused) as e:
        tc.validate_transcript_path("cursor", SID, "/x.jsonl")
    assert e.value.reason == "bad_harness"
    with pytest.raises(tc.TranscriptRefused) as e:
        tc.validate_transcript_path("claude-code", "../etc", "/x.jsonl")
    assert e.value.reason == "bad_session_id"


def test_codex_path_must_contain_the_session_id(roots):
    good = _write(roots["codex"] / f"rollout-2026-09-03T10-00-00-{SID}.jsonl", "{}")
    assert tc.validate_transcript_path("codex", SID, str(good)) == good.resolve()
    bad = _write(roots["codex"] / "rollout-2026-09-03T10-00-00-other.jsonl", "{}")
    with pytest.raises(tc.TranscriptRefused) as e:
        tc.validate_transcript_path("codex", SID, str(bad))
    assert e.value.reason == "stem_mismatch"


# --- writer (R3, R12, R13) ------------------------------------------------------


def test_first_firing_creates_one_episode_in_the_importer_shape(roots, memory):
    path = _write(roots["claude"] / f"{SID}.jsonl", _transcript([
        ("user", "Should alpha-project move to sqlite-vec?"),
        ("assistant", "Yes — bob-example agreed last week."),
    ]))
    r = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                              cwd="/home/example/alpha-project", keep_assistant=True)
    assert r.status == "created"
    assert r.episode_id == "ep_2026-09-03_001"
    parsed = markdown_parser.parse(memory / "episodes" / "ep_2026-09-03_001.md")
    fm = parsed.frontmatter
    assert fm["origin"] == "claude-code" and fm["source"] == "claude-code" and fm["harness"] == "claude-code"
    assert fm["session_id"] == SID and fm["project_dir"] == "/home/example/alpha-project"
    assert fm["capture_kind"] == "transcript" and fm["processed"] is False and fm["turns"] == 2
    assert fm["title"] == "Should alpha-project move to sqlite-vec?"
    assert fm["timestamp"] == "2026-09-03T10:00:00+00:00"
    assert "processed_by" not in fm
    body = parsed.body
    assert body == "user: Should alpha-project move to sqlite-vec?\nassistant: Yes — bob-example agreed last week."
    # G118: the marker shape the span endpoint's speaker_kind reads.
    assert speaker_kind(body, body.index("Yes")) == "assistant"
    assert speaker_kind(body, 0) == "user"


def test_second_firing_updates_in_place_and_requeues(roots, memory):
    path = _write(roots["claude"] / f"{SID}.jsonl", _transcript([("user", "Q1")]))
    first = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                                  cwd=None, keep_assistant=True)
    ep = memory / "episodes" / f"{first.episode_id}.md"
    # Sleep consolidated it in between.
    parsed = markdown_parser.parse(ep)
    fm = dict(parsed.frontmatter)
    fm["processed"] = True
    fm["processed_by"] = "sleep"
    markdown_parser.write(ep, fm, parsed.body)
    old_hash = fm["content_hash"]

    path.write_text(_transcript([("user", "Q1"), ("assistant", "A1"), ("user", "Q2")]), encoding="utf-8")
    second = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                                   cwd=None, keep_assistant=True)
    assert second.status == "updated" and second.episode_id == first.episode_id
    assert len(list((memory / "episodes").glob("ep_*.md"))) == 1
    fm2 = markdown_parser.parse(ep).frontmatter
    assert fm2["processed"] is False and "processed_by" not in fm2
    assert fm2["content_hash"] != old_hash and fm2["id"] == first.episode_id
    assert fm2["turns"] == 3

    third = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                                  cwd=None, keep_assistant=True)
    assert third.status == "unchanged"
    assert markdown_parser.parse(ep).frontmatter["processed"] is False


def test_mcp_episode_from_the_same_session_is_never_touched(roots, memory):
    mcp = memory / "episodes" / "ep_2026-09-03_001.md"
    markdown_parser.write(mcp, {"id": "ep_2026-09-03_001", "timestamp": "2026-09-03T09:00:00+00:00",
                                "source": "mcp", "origin": "mcp", "processed": True, "session_id": SID}, "user: saved via MCP")
    path = _write(roots["claude"] / f"{SID}.jsonl", _transcript([("user", "Q1")]))
    r = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                              cwd=None, keep_assistant=True)
    assert r.status == "created" and r.episode_id == "ep_2026-09-03_002"
    assert markdown_parser.parse(mcp).frontmatter["processed"] is True


def test_empty_conversation_writes_nothing(roots, memory):
    path = _write(roots["claude"] / f"{SID}.jsonl", _line("user", [{"type": "tool_result", "content": "x"}]) + "\n")
    r = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                              cwd=None, keep_assistant=True)
    assert r.status == "empty" and r.episode_id is None
    assert list((memory / "episodes").glob("*.md")) == []


def test_keep_assistant_false_writes_only_the_person(roots, memory):
    path = _write(roots["claude"] / f"{SID}.jsonl", _transcript([("user", "Q"), ("assistant", "A")]))
    r = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                              cwd=None, keep_assistant=False)
    body = markdown_parser.parse(memory / "episodes" / f"{r.episode_id}.md").body
    assert body == "user: Q"


# --- ledger (R10) ---------------------------------------------------------------


def test_ledger_row_is_counts_only(roots, memory, monkeypatch, tmp_path):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    path = _write(roots["claude"] / f"{SID}.jsonl", _transcript([("user", "secret words about alpha-project")]))
    tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                          cwd="/home/example/alpha-project", keep_assistant=True, bank="test-bank")
    events = [e for e in telemetry.read_events() if e.kind == "capture"]
    assert len(events) == 1
    ev = events[0]
    assert ev.stage == "claude-code" and ev.bank == "test-bank" and ev.connection is None
    assert ev.refs["status"] == "created" and ev.refs["turns_user"] == 1 and ev.refs["session_id"] == SID
    raw = ev.to_json()
    assert "secret words" not in raw and "alpha-project" not in raw
    assert "capture" in telemetry.KINDS and "capture" in telemetry.NON_SPEND_KINDS


# --- endpoint --------------------------------------------------------------------


@pytest.fixture
def client(memory, monkeypatch):
    # The suite's established pattern (test_telegram_capture._client): point
    # the env at tmp memory and drop the lru_cache — `memory_path` is a
    # property over `memory_root`, not a constructor field.
    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_endpoint_creates_then_refuses_bad_path(client, roots, memory):
    path = _write(roots["claude"] / f"{SID}.jsonl", _transcript([("user", "Q")]))
    r = client.post("/capture/transcript", json={"harness": "claude-code", "session_id": SID,
                                                   "transcript_path": str(path), "cwd": "/home/example/alpha-project"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "created" and r.json()["episodeId"] == "ep_2026-09-03_001"
    bad = client.post("/capture/transcript", json={"harness": "claude-code", "session_id": SID,
                                                     "transcript_path": "/etc/passwd"})
    assert bad.status_code == 400 and bad.json()["detail"] in ("outside_root", "not_jsonl")
    assert client.post("/capture/transcript", json={"harness": "cursor", "session_id": SID,
                                                    "transcript_path": str(path)}).status_code == 422


def test_endpoint_requires_bearer_token(memory, monkeypatch, tmp_path):
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    # Same as test_auth.py's `home` fixture: a developer's shell export must
    # not become the token the request is checked against.
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    from api import config, main
    config.get_settings.cache_clear()
    r = TestClient(main.app).post("/capture/transcript", json={"harness": "claude-code", "session_id": SID,
                                                                "transcript_path": "/x.jsonl"})
    config.get_settings.cache_clear()
    assert r.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && api/.venv/bin/python -m pytest api/tests/test_capture_transcript.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.services.transcript_capture'`.

- [ ] **Step 3: Settings flag, telemetry kind, spend filter**

`api/config.py` — insert before `model_config = {...}`:

```python
    # G105 R7 — the one switch on hook-driven capture. True keeps the person's
    # turns AND the agent's final reply per turn; false keeps only the
    # person's turns (the owner's stated fallback if the assistant half
    # proves noisy). Read by POST /capture/transcript, so flipping it needs
    # no hook re-registration.
    capture_assistant_replies: bool = True  # CICADA_CAPTURE_ASSISTANT_REPLIES
```

`api/services/telemetry.py` — change `KINDS` and add `NON_SPEND_KINDS`:

```python
KINDS = (
    "llm_call", "sleep_run", "agentic_write", "ask", "import", "throttle",
    "resolution", "audit", "dedup_verdict", "capture",
)
# G113: grounded-feedback rows — ... (existing comment unchanged)
FEEDBACK_KINDS = ("resolution", "audit", "dedup_verdict")
# G105 R10: a `capture` row (hook-driven transcript capture) is counts only
# and carries no spend or connection; like the feedback kinds it must never
# surface as an "unknown" connection in the cost rollup.
NON_SPEND_KINDS = FEEDBACK_KINDS + ("capture",)
```

`api/services/consumption_stats.py:213` — `spend = [e for e in events if e.kind not in telemetry.NON_SPEND_KINDS]`.

- [ ] **Step 4: Implement `api/services/transcript_capture.py`**

```python
"""Hook-driven transcript capture: validate, extract, write one episode per
session (G105 R2, R3, R10, R12, R13).

The hook (``api/hooks/capture.py``) forwards the harness's own stdin JSON;
THIS module is the only place a transcript is opened, and only after the
path has been proven to be the file the harness just named for the session
that just ended: under that harness's known root after symlink resolution,
a ``.jsonl`` regular file, within the size cap, and — for Claude Code —
named exactly ``<session_id>.jsonl`` (the same key the MCP seam's
``isfile()`` resumability check uses, ``session_stats.py:72``). Anything
else is refused with an enum reason and never read. That is the G48 rail
restated: transcripts are not a corpus Cicada mines; the one that just
ended is a stream intake, and what enters the bank is what the extractor
keeps.

Writes mirror the conversation importer byte-for-byte (``conversations.py``
``_stage_episodes`` / ``_update_episode_in_place``): the body is
``role: text`` lines, the hash is ``sha256(body)[:12]``, and a grown session
rewrites the same file with ``processed: false`` so Sleep re-consolidates
exactly one episode (the G104-safe path). Ids and stamps come from
``episode_ids`` (G114). No LLM anywhere.
"""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger

from api.services import episode_ids, markdown_parser, session_stats, telemetry
from api.services.transcript_extract import HARNESSES, Conversation, extract

#: 256 MiB. The largest transcript seen on the author's machine during the
#: 2026-09-03 schema peek was 85 MB; the cap is a ceiling against a runaway
#: file, not a budget.
MAX_TRANSCRIPT_BYTES = 256 * 1024 * 1024
TITLE_MAX = 72
CAPTURE_KIND = "transcript"
PRODUCT = {"claude-code": "Claude Code", "codex": "Codex"}

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
_lock = threading.Lock()
# (episodes_dir, harness, session_id) -> episode path, so a Stop firing on a
# long session does not rescan every episode file. Keyed by the episodes dir
# because the active bank can change under a running backend
# (``POST /banks/{name}/activate``) — a key without it would hand one bank's
# episode path to another bank's capture (plan critic 2026-09-03: the
# un-keyed cache also bled across the test suite's tmp banks). A hit is
# re-verified by parsing the one cached file — it must still be a transcript
# episode for this session, since a bank rename, duplicate or restore can
# leave a stale path behind.
_episode_cache: dict[tuple[str, str, str], Path] = {}


class TranscriptRefused(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def harness_root(harness: str) -> Path:
    """Where each harness keeps its transcripts. A function (not a constant)
    so tests can point it at ``tmp_path``; never derived from a request."""
    if harness == "claude-code":
        return session_stats.transcripts_root()
    if harness == "codex":
        return Path.home() / ".codex" / "sessions"
    raise TranscriptRefused("bad_harness")


def validate_transcript_path(harness: str, session_id: str, raw_path: str) -> Path:
    if harness not in HARNESSES:
        raise TranscriptRefused("bad_harness")
    sid = (session_id or "").strip()
    if not _SESSION_ID_RE.match(sid):
        raise TranscriptRefused("bad_session_id")
    root = harness_root(harness).expanduser().resolve()
    try:
        path = Path(raw_path or "").expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise TranscriptRefused("not_a_file")
    if not path.is_relative_to(root):
        raise TranscriptRefused("outside_root")
    if path.suffix != ".jsonl":
        raise TranscriptRefused("not_jsonl")
    if not path.is_file():
        raise TranscriptRefused("not_a_file")
    if harness == "claude-code" and path.stem != sid:
        raise TranscriptRefused("stem_mismatch")
    if harness == "codex" and sid not in path.name:
        raise TranscriptRefused("stem_mismatch")
    if path.stat().st_size > MAX_TRANSCRIPT_BYTES:
        raise TranscriptRefused("too_large")
    return path


@dataclass
class CaptureResult:
    status: str  # created | updated | unchanged | empty | refused
    episode_id: str | None
    turns_user: int
    turns_assistant: int
    summary: dict
    reason: str | None = None


def _utc(ts: str | None) -> str:
    """A transcript stamp (``…Z``) → the R2 ``+00:00`` shape; now() when absent."""
    if ts:
        try:
            return episode_ids.to_utc_iso(datetime.fromisoformat(ts.replace("Z", "+00:00")))
        except ValueError:
            pass
    return episode_ids.utc_now_iso()


def _body(conv: Conversation) -> str:
    return "\n".join(f"{t.role}: {t.text}" for t in conv.turns)


def _title(conv: Conversation, harness: str) -> str:
    for t in conv.turns:
        if t.role == "user":
            first = t.text.strip().splitlines()[0].strip()
            if first:
                return first if len(first) <= TITLE_MAX else first[: TITLE_MAX - 1] + "…"
    return f"{PRODUCT.get(harness, harness)} session"


def _is_session_episode(fp: Path, session_id: str) -> bool:
    try:
        fm = markdown_parser.parse(fp).frontmatter
    except Exception:  # noqa: BLE001 - one malformed episode must not block capture
        return False
    return fm.get("capture_kind") == CAPTURE_KIND and str(fm.get("session_id") or "") == session_id


def _find_session_episode(episodes_dir: Path, harness: str, session_id: str) -> Path | None:
    key = (str(episodes_dir.resolve()), harness, session_id)
    cached = _episode_cache.get(key)
    if cached is not None and cached.is_file() and _is_session_episode(cached, session_id):
        return cached
    _episode_cache.pop(key, None)
    for fp in sorted(episodes_dir.glob("ep_*.md")):
        if _is_session_episode(fp, session_id):
            _episode_cache[key] = fp
            return fp
    return None


def _record(harness: str, session_id: str, status: str, conv: Conversation | None, bank: str | None,
            reason: str | None = None) -> None:
    summary = conv.summary if conv else {}
    refs = {
        "harness": harness, "status": status, "session_id": session_id,
        "turns_user": summary.get("kept", {}).get("user", 0),
        "turns_assistant": summary.get("kept", {}).get("assistant", 0),
        "dropped_blocks": summary.get("dropped_blocks", {}),
        "dropped_messages": summary.get("dropped_messages", {}),
        "truncated_turns": summary.get("truncated_turns", 0),
        "scrubbed": summary.get("scrubbed", 0),
        "session_cap_hit": summary.get("session_cap_hit", False),
    }
    if reason:
        refs["reason"] = reason
    telemetry.record(telemetry.UsageEvent(kind="capture", stage=harness, bank=bank, billing="free",
                                          refs=refs, ok=status != "refused"))


def capture_transcript(
    memory_path: Path,
    *,
    harness: str,
    session_id: str,
    transcript_path: str,
    cwd: str | None,
    keep_assistant: bool,
    bank: str | None = None,
) -> CaptureResult:
    try:
        path = validate_transcript_path(harness, session_id, transcript_path)
    except TranscriptRefused as exc:
        _record(harness, session_id, "refused", None, bank, exc.reason)
        return CaptureResult("refused", None, 0, 0, {}, reason=exc.reason)

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        conv = extract(harness, fh, keep_assistant=keep_assistant)
    kept = conv.summary["kept"]

    with _lock:
        episodes_dir = memory_path / "episodes"
        episodes_dir.mkdir(parents=True, exist_ok=True)
        if not conv.turns:
            _record(harness, session_id, "empty", conv, bank)
            return CaptureResult("empty", None, 0, 0, conv.summary)

        body = _body(conv)
        content_hash = hashlib.sha256(body.encode()).hexdigest()[:12]
        existing = _find_session_episode(episodes_dir, harness, session_id)
        now = episode_ids.utc_now_iso()

        if existing is None:
            timestamp = _utc(conv.started_at)
            episode_id = episode_ids.next_episode_id(episodes_dir, timestamp[:10])
            fm = {
                "id": episode_id,
                "timestamp": timestamp,
                "source": harness,
                "origin": harness,
                "title": _title(conv, harness),
                "processed": False,
                "content_hash": content_hash,
                "session_id": session_id,
                "harness": harness,
                "capture_kind": CAPTURE_KIND,
                "captured_at": now,
                "turns": len(conv.turns),
            }
            if cwd:
                fm["project_dir"] = cwd
            path_out = episodes_dir / f"{episode_id}.md"
            markdown_parser.write(path_out, fm, body)
            _episode_cache[(str(episodes_dir.resolve()), harness, session_id)] = path_out
            _record(harness, session_id, "created", conv, bank)
            logger.info(f"capture: created {episode_id} from {harness} session ({len(conv.turns)} turns)")
            return CaptureResult("created", episode_id, kept["user"], kept["assistant"], conv.summary)

        fm = dict(markdown_parser.parse(existing).frontmatter)
        episode_id = str(fm.get("id") or existing.stem)
        if fm.get("content_hash") == content_hash:
            _record(harness, session_id, "unchanged", conv, bank)
            return CaptureResult("unchanged", episode_id, kept["user"], kept["assistant"], conv.summary)

        # R3: same file, same id, same original timestamp; new body, re-queued.
        # `processed_by` is written only beside `processed: true` (G114 R6),
        # so a re-queued episode must not carry a stale "sleep" stamp.
        fm["title"] = _title(conv, harness)
        fm["content_hash"] = content_hash
        fm["captured_at"] = now
        fm["turns"] = len(conv.turns)
        fm["processed"] = False
        fm.pop("processed_by", None)
        if cwd and not fm.get("project_dir"):
            fm["project_dir"] = cwd
        markdown_parser.write(existing, fm, body)
        _record(harness, session_id, "updated", conv, bank)
        logger.info(f"capture: updated {episode_id} from {harness} session ({len(conv.turns)} turns), re-queued")
        return CaptureResult("updated", episode_id, kept["user"], kept["assistant"], conv.summary)
```

- [ ] **Step 5: The route — append to `api/routers/capture.py`**

Add to the imports at the top of the file:

```python
import asyncio
from typing import Literal

from pydantic import BaseModel

from api.services import telemetry
from api.services.transcript_capture import capture_transcript
```

Append after `capture_telegram`:

```python
class TranscriptCaptureRequest(BaseModel):
    """What the Stop hook forwards — the harness's own stdin fields, nothing
    computed client-side. Snake_case on purpose: the sender is a stdlib
    script, not the app."""

    harness: Literal["claude-code", "codex"]
    session_id: str
    transcript_path: str
    cwd: str | None = None
    hook_event: str | None = None


@router.post("/capture/transcript")
async def capture_transcript_endpoint(
    req: TranscriptCaptureRequest,
    settings: Settings = Depends(get_settings),
):
    """G105: deterministic session capture from the harness's Stop hook.

    Bearer-authed like every other write path — the hook reads
    ``~/.cicada/api_token`` (the file the app and MCP server already use), so
    nothing is added to ``auth._STATIC_OPEN_PATHS``. The backend, not the
    hook, opens the transcript (R2): the path is validated against the
    harness root before a byte is read, and a refusal is a 400 carrying the
    enum reason plus a ledger row, never a partial write. One episode per
    session, updated in place on every later firing (R3); ``status`` says
    which of ``created | updated | unchanged | empty`` happened. Runs the
    read + parse off the event loop — an 85 MB transcript takes real time
    and must not stall SSE or the app.
    """
    result = await asyncio.to_thread(
        capture_transcript,
        settings.memory_path,
        harness=req.harness,
        session_id=req.session_id,
        transcript_path=req.transcript_path,
        cwd=req.cwd,
        keep_assistant=settings.capture_assistant_replies,
        bank=telemetry.bank_name(settings),
    )
    if result.status == "refused":
        raise HTTPException(status_code=400, detail=result.reason)
    return {
        "status": result.status,
        "episodeId": result.episode_id,
        "turnsUser": result.turns_user,
        "turnsAssistant": result.turns_assistant,
        "summary": result.summary,
    }
```

Verify `telemetry.bank_name(settings)` at `api/services/telemetry.py:266` accepts a `Settings` (it does today — read the three lines) before relying on it.

- [ ] **Step 6: Run the new tests, then the neighbours**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && api/.venv/bin/python -m pytest api/tests/test_capture_transcript.py api/tests/test_transcript_extract.py api/tests/test_telemetry.py api/tests/test_consumption_stats.py api/tests/test_auth.py api/tests/test_telegram_capture.py -q -p no:cacheprovider`
Expected: all pass (verified by the plan critic on 2026-09-03 against a scratch copy of `api/` with these exact files: 60/60 across the four new suites, and `test_auth`, `test_telemetry`, `test_consumption_stats`, `test_telegram_capture`, `test_feedback_ledger`, `test_connections_base` unchanged). `test_endpoint_requires_bearer_token` gets a 401, not a 422: `require_token` is an app-wide dependency (`api/main.py:134`, `dependencies=[Depends(require_token)]`) and FastAPI resolves dependencies before it validates the body.

- [ ] **Step 7: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && git add api/services/transcript_capture.py api/routers/capture.py api/config.py api/services/telemetry.py api/services/consumption_stats.py api/tests/test_capture_transcript.py && git commit -m "feat(capture): POST /capture/transcript — path-validated, one episode per session, updated in place, counts-only ledger row (G105 R2/R3/R10)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

### Task 3: The hook, the settings merge, install / uninstall / doctor

**Files:**
- Create: `api/hooks/__init__.py` (empty, one-line docstring), `api/hooks/capture.py`, `api/hooks/registry.py`
- Modify: `api/services/connections/base.py:85-86` (`scrubbed_env`)
- Modify: `install.sh` (`:26-48` paths, `:88-111` uninstall, after step 5 at `:279`, summary `:352-369`, usage comment `:10-14`)
- Modify: `scripts/doctor.sh` (new check 12 after check 11 — the file already has eleven; add `CLAUDE_SETTINGS` to its header's override list)
- Test: `api/tests/test_capture_hook.py`, `api/tests/test_hooks_registry.py`

**Interfaces:**
- `api/hooks/capture.py`: `main(argv: list[str] | None = None, *, stdin=None, environ=None, post=None, log_path: Path | None = None, token_path: Path | None = None) -> int` — always returns 0; `post(url, body_bytes, token, timeout) -> (status_code, text)` injectable; default uses `urllib.request`.
- `api/hooks/registry.py`: `MARKER = "api/hooks/capture.py"`; `load(path) -> dict`; `install(path, *, event, command, timeout=5) -> str` (`added | updated | present`); `uninstall(path) -> int`; `status(path, *, event, command) -> str` (`present | stale | absent`); `main(argv) -> int` (`install`/`uninstall` → 0 on success, 3 on unreadable JSON; `status` → 0 present, 1 absent, 2 stale).
- `scrubbed_env()` gains `CICADA_CAPTURE=off`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_capture_hook.py
"""G105 R8/R14: the Stop hook never blocks the harness, never reads the
transcript, never prints to stdout, and never fires from Cicada's own CLI
spawns. Everything is injected; no network, no real home dir."""
from __future__ import annotations

import io
import json
from pathlib import Path

from api.hooks import capture as hook
from api.services.connections import base

SID = "11111111-2222-4333-8444-555555555555"
PAYLOAD = {"session_id": SID, "transcript_path": "/home/example/.claude/projects/x/" + SID + ".jsonl",
           "cwd": "/home/example/alpha-project", "hook_event_name": "Stop"}


def _run(tmp_path, payload, *, environ=None, post=None, argv=("--harness", "claude-code")):
    token = tmp_path / "api_token"
    token.write_text("tok-123")
    log = tmp_path / "logs" / "capture.log"
    calls = []

    def default_post(url, body, tok, timeout):
        calls.append((url, json.loads(body), tok, timeout))
        return 200, '{"status":"created"}'

    rc = hook.main(list(argv), stdin=io.StringIO(json.dumps(payload) if isinstance(payload, dict) else payload),
                   environ=environ or {}, post=post or default_post, log_path=log, token_path=token)
    return rc, calls, log


def test_posts_the_harness_fields_with_bearer_and_3s_timeout(tmp_path, capsys):
    rc, calls, log = _run(tmp_path, PAYLOAD, environ={"CICADA_PORT": "8123"})
    assert rc == 0
    url, body, tok, timeout = calls[0]
    assert url == "http://127.0.0.1:8123/capture/transcript"
    assert body == {"harness": "claude-code", "session_id": SID, "transcript_path": PAYLOAD["transcript_path"],
                    "cwd": PAYLOAD["cwd"], "hook_event": "Stop"}
    assert tok == "tok-123" and timeout == 3.0
    assert capsys.readouterr().out == ""  # a Stop hook's stdout is parsed by the harness
    line = log.read_text().strip().splitlines()[-1]
    assert "claude-code" in line and SID[:8] in line and "created" in line
    assert PAYLOAD["transcript_path"] not in line  # the log names sessions, never paths


def test_exits_zero_and_logs_when_capture_is_off(tmp_path):
    rc, calls, log = _run(tmp_path, PAYLOAD, environ={"CICADA_CAPTURE": "off"})
    assert rc == 0 and calls == []
    assert "CICADA_CAPTURE=off" in log.read_text()


def test_exits_zero_on_bad_stdin_missing_fields_missing_token_and_post_failure(tmp_path):
    assert _run(tmp_path, "{not json")[0] == 0
    rc, calls, log = _run(tmp_path, {"session_id": SID})
    assert rc == 0 and calls == [] and "no transcript_path" in log.read_text()

    def boom(*a):
        raise OSError("connection refused")

    rc, _, log = _run(tmp_path, PAYLOAD, post=boom)
    assert rc == 0 and "connection refused" in log.read_text()
    (tmp_path / "api_token").unlink()
    rc = hook.main(["--harness", "codex"], stdin=io.StringIO(json.dumps(PAYLOAD)), environ={},
                   post=lambda *a: (200, ""), log_path=tmp_path / "l.log", token_path=tmp_path / "api_token")
    assert rc == 0 and "no api_token" in (tmp_path / "l.log").read_text()


def test_harness_arg_is_forwarded(tmp_path):
    _, calls, _ = _run(tmp_path, PAYLOAD, argv=("--harness", "codex"))
    assert calls[0][1]["harness"] == "codex"


def test_log_is_private_and_rotates(tmp_path):
    log = tmp_path / "logs" / "capture.log"
    log.parent.mkdir()
    log.write_text("x" * (hook.LOG_MAX_BYTES + 1))
    _run(tmp_path, PAYLOAD)
    assert (tmp_path / "logs" / "capture.log.1").exists()
    assert oct(log.stat().st_mode & 0o777) == "0o600"


def test_cicada_cli_spawns_carry_capture_off(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    env = base.scrubbed_env()
    assert env["CICADA_CAPTURE"] == "off" and "ANTHROPIC_API_KEY" not in env


def test_hook_module_imports_nothing_from_api(tmp_path):
    src = Path(hook.__file__).read_text()
    assert "from api" not in src and "import api" not in src
```

```python
# api/tests/test_hooks_registry.py
"""G105 R14: install.sh's settings.json merge — idempotent, never clobbers
other hooks or keys, refuses to touch a file it cannot parse."""
from __future__ import annotations

import json
from pathlib import Path

from api.hooks import registry as reg

CMD = '"/opt/example/api/.venv/bin/python" "/opt/example/api/hooks/capture.py" --harness claude-code'


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def test_install_creates_file_and_parent(tmp_path):
    p = tmp_path / ".claude" / "settings.json"
    assert reg.install(p, event="Stop", command=CMD) == "added"
    data = _read(p)
    assert data == {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": CMD, "timeout": 5}]}]}}
    assert reg.status(p, event="Stop", command=CMD) == "present"


def test_install_merges_and_preserves_other_hooks_and_keys(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "model": "opus",
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "/other/stop.sh"}]}],
            "SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "/other/start.sh"}]}],
        },
    }))
    assert reg.install(p, event="Stop", command=CMD) == "added"
    data = _read(p)
    assert data["model"] == "opus"
    assert data["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "/other/start.sh"
    cmds = [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]]
    assert cmds == ["/other/stop.sh", CMD]


def test_install_is_idempotent_and_updates_a_moved_repo(tmp_path):
    p = tmp_path / "settings.json"
    reg.install(p, event="Stop", command=CMD)
    assert reg.install(p, event="Stop", command=CMD) == "present"
    moved = CMD.replace("/opt/example", "/srv/example")
    assert reg.status(p, event="Stop", command=moved) == "stale"
    assert reg.install(p, event="Stop", command=moved) == "updated"
    cmds = [h["command"] for e in _read(p)["hooks"]["Stop"] for h in e["hooks"]]
    assert cmds == [moved]


def test_uninstall_removes_only_ours_and_prunes_empties(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/other/stop.sh"}]}]},
                             "permissions": {"allow": ["Bash(ls)"]}}))
    reg.install(p, event="Stop", command=CMD)
    assert reg.uninstall(p) == 1
    data = _read(p)
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "/other/stop.sh"
    assert data["permissions"] == {"allow": ["Bash(ls)"]}
    q = tmp_path / "only-ours.json"
    reg.install(q, event="Stop", command=CMD)
    reg.uninstall(q)
    assert _read(q) == {}
    assert reg.uninstall(tmp_path / "missing.json") == 0


def test_refuses_to_clobber_unparseable_settings(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{ not json")
    rc = reg.main(["install", "--settings", str(p), "--event", "Stop", "--command", CMD])
    assert rc == 3 and p.read_text() == "{ not json"


def test_cli_status_exit_codes(tmp_path):
    p = tmp_path / "settings.json"
    assert reg.main(["status", "--settings", str(p), "--event", "Stop", "--command", CMD]) == 1
    assert reg.main(["install", "--settings", str(p), "--event", "Stop", "--command", CMD]) == 0
    assert reg.main(["status", "--settings", str(p), "--event", "Stop", "--command", CMD]) == 0
    assert reg.main(["status", "--settings", str(p), "--event", "Stop", "--command", CMD + " --x"]) == 2
    assert reg.main(["uninstall", "--settings", str(p)]) == 0


def test_registry_module_imports_nothing_from_api():
    src = Path(reg.__file__).read_text()
    assert "from api" not in src and "import api" not in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && api/.venv/bin/python -m pytest api/tests/test_capture_hook.py api/tests/test_hooks_registry.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.hooks'`.

- [ ] **Step 3: `api/hooks/__init__.py`**

```python
"""Harness hooks (G105). Stdlib-only scripts run by path from the harness —
never import ``api.*`` here; see ``capture.py`` and ``registry.py``."""
```

- [ ] **Step 4: `api/hooks/capture.py`**

```python
#!/usr/bin/env python3
"""Cicada session-capture hook (G105 R1, R2, R8, R14).

Registered by ``install.sh`` under ``hooks.Stop`` in ``~/.claude/settings.json``
(and ``~/.codex/hooks.json`` when Codex is installed) as::

    "<venv python>" "<repo>/api/hooks/capture.py" --harness claude-code

The harness pipes its hook JSON to stdin (``session_id``, ``transcript_path``,
``cwd``, ``hook_event_name``); this script POSTs exactly those fields to
``POST /capture/transcript`` and exits 0 — always, within 3 s, printing
nothing to stdout (a Stop hook's stdout is parsed by the harness). It never
opens the transcript: the backend validates the path against the harness
root and does the one read (R2).

Stdlib only, run by path: a hook has no cwd guarantee and no venv on its
``sys.path``, so nothing here imports ``api.*`` (R14).

``CICADA_CAPTURE=off`` in the environment exits before any request: every
CLI Cicada itself spawns (Sleep's ``claude -p`` engine, doctor probes) runs
under ``connections/base.scrubbed_env()`` which sets it, so Cicada's own
extraction prompts are never captured back into the bank (R8).

One line per firing goes to ``~/.cicada/logs/capture.log`` (0600): a
timestamp, the harness, the first 8 characters of the session id, and the
outcome — never a path, never content.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT_S = 3.0
LOG_MAX_BYTES = 1024 * 1024


def _default_post(url: str, body: bytes, token: str, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - loopback only
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _log(path: Path, message: str) -> None:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            os.replace(path, path.with_suffix(".log.1"))
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {message}\n".encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass  # a log failure must never become a hook failure


def main(argv=None, *, stdin=None, environ=None, post=None, log_path=None, token_path=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ
    stdin = sys.stdin if stdin is None else stdin
    post = _default_post if post is None else post
    home = Path(environ.get("CICADA_HOME") or (Path.home() / ".cicada"))
    log_path = log_path or home / "logs" / "capture.log"
    token_path = token_path or home / "api_token"

    harness = "claude-code"
    if "--harness" in argv:
        try:
            harness = argv[argv.index("--harness") + 1]
        except IndexError:
            pass
    tag = f"{harness} ?"
    try:
        if str(environ.get("CICADA_CAPTURE", "")).strip().lower() == "off":
            _log(log_path, f"{tag} skipped: CICADA_CAPTURE=off")
            return 0
        try:
            payload = json.loads(stdin.read() or "{}")
        except ValueError:
            _log(log_path, f"{tag} skipped: stdin is not JSON")
            return 0
        if not isinstance(payload, dict):
            _log(log_path, f"{tag} skipped: stdin is not an object")
            return 0
        session_id = str(payload.get("session_id") or "")
        tag = f"{harness} {session_id[:8] or '?'}"
        transcript_path = payload.get("transcript_path")
        if not session_id or not transcript_path:
            _log(log_path, f"{tag} skipped: no transcript_path")
            return 0
        try:
            token = token_path.read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
        if not token:
            _log(log_path, f"{tag} skipped: no api_token at {token_path.name}")
            return 0
        port = str(environ.get("CICADA_PORT") or "8000")
        url = f"http://127.0.0.1:{port}/capture/transcript"
        body = json.dumps({
            "harness": harness,
            "session_id": session_id,
            "transcript_path": str(transcript_path),
            "cwd": payload.get("cwd"),
            "hook_event": payload.get("hook_event_name"),
        }).encode("utf-8")
        status, text = post(url, body, token, TIMEOUT_S)
        outcome = ""
        try:
            outcome = str(json.loads(text).get("status") or json.loads(text).get("detail") or "")
        except (ValueError, AttributeError):
            pass
        _log(log_path, f"{tag} http {status} {outcome}".rstrip())
    except Exception as exc:  # noqa: BLE001 - the harness must never see a failure
        _log(log_path, f"{tag} error: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: `api/hooks/registry.py`**

```python
#!/usr/bin/env python3
"""Idempotent hook registration in a harness settings file (G105 R14).

``install.sh`` calls this to add Cicada's Stop hook to
``~/.claude/settings.json`` (and ``~/.codex/hooks.json``, same shape —
verified 2026-09-03), ``--uninstall`` to remove it, and ``make doctor`` to
report it. The file is the user's own configuration, so the rules are:
merge, never replace — every other key and every other hook survives; a
file that does not parse is left untouched (exit 3), never rewritten as
``{}``; writes are atomic (temp file + ``os.replace``); an entry is OURS iff
its command contains :data:`MARKER`, so re-running install after the repo
moved UPDATES the path rather than adding a second hook.

Stdlib only; run by path (no ``api.*`` import).

    registry.py install   --settings <file> --event Stop --command "<cmd>"
    registry.py uninstall --settings <file>
    registry.py status    --settings <file> --event Stop --command "<cmd>"
        exit 0 present · 1 absent · 2 stale (present with another command)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

MARKER = "api/hooks/capture.py"
DEFAULT_TIMEOUT_S = 5


class RegistryError(Exception):
    pass


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except ValueError as exc:
        raise RegistryError(f"{path} is not valid JSON ({exc}); not touching it") from exc
    if not isinstance(data, dict):
        raise RegistryError(f"{path} is not a JSON object; not touching it")
    return data


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _ours(hook: dict) -> bool:
    return isinstance(hook, dict) and MARKER in str(hook.get("command") or "")


def _entries(data: dict, event: str) -> list:
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise RegistryError("'hooks' is not an object; not touching it")
    entries = hooks.setdefault(event, [])
    if not isinstance(entries, list):
        raise RegistryError(f"'hooks.{event}' is not a list; not touching it")
    return entries


def install(path: Path, *, event: str, command: str, timeout: int = DEFAULT_TIMEOUT_S) -> str:
    data = load(path)
    entries = _entries(data, event)
    found = [h for e in entries if isinstance(e, dict) for h in (e.get("hooks") or []) if _ours(h)]
    if found:
        if all(h.get("command") == command for h in found) and len(found) == 1:
            return "present"
        # Collapse to one, with the current command (a moved repo, a
        # duplicate from an older installer).
        for e in entries:
            if isinstance(e, dict):
                e["hooks"] = [h for h in (e.get("hooks") or []) if not _ours(h)]
        _prune(data, event)
        _entries(data, event).append({"hooks": [{"type": "command", "command": command, "timeout": timeout}]})
        _save(path, data)
        return "updated"
    entries.append({"hooks": [{"type": "command", "command": command, "timeout": timeout}]})
    _save(path, data)
    return "added"


def _prune(data: dict, event: str | None = None) -> None:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return
    for ev in list(hooks.keys()) if event is None else [event]:
        entries = hooks.get(ev)
        if isinstance(entries, list):
            hooks[ev] = [e for e in entries if not (isinstance(e, dict) and not e.get("hooks"))]
            if not hooks[ev]:
                del hooks[ev]
    if not hooks:
        del data["hooks"]


def uninstall(path: Path) -> int:
    if not path.exists():
        return 0
    data = load(path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    removed = 0
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for e in entries:
            if isinstance(e, dict) and isinstance(e.get("hooks"), list):
                keep = [h for h in e["hooks"] if not _ours(h)]
                removed += len(e["hooks"]) - len(keep)
                e["hooks"] = keep
    if removed:
        _prune(data)
        _save(path, data)
    return removed


def status(path: Path, *, event: str, command: str) -> str:
    try:
        data = load(path)
    except RegistryError:
        return "absent"
    entries = data.get("hooks", {}).get(event, []) if isinstance(data.get("hooks"), dict) else []
    ours = [h for e in entries if isinstance(e, dict) for h in (e.get("hooks") or []) if _ours(h)]
    if not ours:
        return "absent"
    return "present" if any(h.get("command") == command for h in ours) else "stale"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("install", "uninstall", "status"))
    ap.add_argument("--settings", required=True)
    ap.add_argument("--event", default="Stop")
    ap.add_argument("--command", default="")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    args = ap.parse_args(argv)
    path = Path(args.settings).expanduser()
    try:
        if args.action == "install":
            if not args.command:
                ap.error("--command is required for install")
            print(f"{install(path, event=args.event, command=args.command, timeout=args.timeout)}: {path}")
            return 0
        if args.action == "uninstall":
            print(f"removed {uninstall(path)} hook(s): {path}")
            return 0
        state = status(path, event=args.event, command=args.command)
        print(f"{state}: {path}")
        return {"present": 0, "absent": 1, "stale": 2}[state]
    except RegistryError as exc:
        print(str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: `scrubbed_env` (`api/services/connections/base.py:85-86`)**

```python
def scrubbed_env() -> dict[str, str]:
    """Provider keys stripped, and ``CICADA_CAPTURE=off`` set: every CLI
    Cicada spawns runs under this, and the G105 Stop hook exits on that
    variable — otherwise Sleep's own ``claude -p`` extraction prompts would
    be captured back into the bank as episodes (R8)."""
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED_ENV_KEYS}
    env["CICADA_CAPTURE"] = "off"
    return env
```

Run `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && api/.venv/bin/python -m pytest api/tests/test_connections_base.py api/tests/test_agent_engine.py -q -p no:cacheprovider` — `test_scrubbed_env_drops_provider_keys` (`:13-17`) asserts on absence only, so it must still pass.

- [ ] **Step 7: `install.sh`**

In the usage comment (`:10-14`) add after the `--uninstall` line:

```
#   Every full install also registers the G105 session-capture hook under
#   hooks.Stop in ~/.claude/settings.json (and ~/.codex/hooks.json when the
#   codex CLI is present) — merged in, never clobbering other hooks; re-run
#   after moving the repo. --uninstall removes it.
```

and to the "Test/override env vars" list (after the `CLAUDE_CLI` line, `:22`):

```
#   CLAUDE_SETTINGS      Claude Code settings  (default: ~/.claude/settings.json)
#   CODEX_HOOKS          Codex hooks file      (default: ~/.codex/hooks.json)
```

`-h` prints that header with `sed -n '3,24p'` (`:57`). The six inserted lines move the last comment line from `:23` to `:29`, so change the range to `'3,29p'` — otherwise the new lines push `CLAUDE_CLI` and the two new vars out of `--help` (today the range already over-reaches by one and prints `set -euo pipefail`; `'3,29p'` fixes that too).

In the paths block (after `CLAUDE_CLI=` at `:31`):

```bash
CLAUDE_SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
CODEX_HOOKS="${CODEX_HOOKS:-$HOME/.codex/hooks.json}"
```

and after `MCP_SERVER=` (`:41`):

```bash
HOOK_SCRIPT="$REPO/api/hooks/capture.py"
HOOKS_REGISTRY="$REPO/api/hooks/registry.py"
# The registered command, quoted per path so a space in $HOME survives the
# harness's `sh -c`. One function so install, uninstall and doctor agree.
hook_command() { printf '"%s" "%s" --harness %s' "$VENV_PY" "$HOOK_SCRIPT" "$1"; }
```

In the `--uninstall` block, before `ok "Memory dir left intact…"` (`:108`):

```bash
  if [ -x "$VENV_PY" ]; then
    step "Removing the session-capture hook"
    run "$VENV_PY" "$HOOKS_REGISTRY" uninstall --settings "$CLAUDE_SETTINGS" || true
    [ -f "$CODEX_HOOKS" ] && { run "$VENV_PY" "$HOOKS_REGISTRY" uninstall --settings "$CODEX_HOOKS" || true; }
    ok "Capture hook removed (if it existed)"
  else
    warn "venv missing — remove the api/hooks/capture.py entry from $CLAUDE_SETTINGS by hand"
  fi
```

After step 5's closing `fi` (`:279`), before `# --- 6. launchd backend ---`:

```bash
# --- 5b. Session-capture hook (G105) ---
# Stop, not SessionEnd: SessionEnd only fires on a graceful exit and shares a
# 1.5 s budget; Stop fires after every reply, and the endpoint is idempotent
# (same content hash = no write), so the LAST Stop is the session's end
# however it ended. The hook never reads the transcript — the backend does,
# after validating the path against the harness root.
hdr "5b. Session-capture hook"
if run "$VENV_PY" "$HOOKS_REGISTRY" install --settings "$CLAUDE_SETTINGS" --event Stop --command "$(hook_command claude-code)"; then
  ok "Claude Code Stop hook registered in $CLAUDE_SETTINGS (idempotent)"
else
  warn "Could not register the Stop hook in $CLAUDE_SETTINGS — fix the file and re-run ./install.sh"
fi
if command -v codex >/dev/null 2>&1; then
  if run "$VENV_PY" "$HOOKS_REGISTRY" install --settings "$CODEX_HOOKS" --event Stop --command "$(hook_command codex)"; then
    ok "Codex Stop hook registered in $CODEX_HOOKS"
  else
    warn "Could not register the Codex hook in $CODEX_HOOKS"
  fi
fi
```

In the summary (`:352-369`), after the `MCP:` lines:

```bash
echo "  capture hook:  $CLAUDE_SETTINGS (hooks.Stop → api/hooks/capture.py)"
```

Dry-run check: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && bash -n install.sh && CICADA_MEMORY_PATH=/tmp/x LAUNCH_AGENTS_DIR=/tmp/x CLAUDE_SETTINGS=/tmp/x/settings.json CODEX_HOOKS=/tmp/x/hooks.json ./install.sh --dry-run 2>&1 | grep -n "5b\|registry.py" ` — expect the `5b.` header and a printed `$ …registry.py install …` line; nothing is written under `--dry-run`. (`/tmp` here is a dry-run target only; no file is created.)

- [ ] **Step 8: `scripts/doctor.sh` — check 12**

The file already has eleven checks (check 11, `:170-177`, is the stray-`ANTHROPIC_API_KEY` check). Add to the header's override list (`:7-11`):

```
#   CLAUDE_SETTINGS      Claude Code settings (default: ~/.claude/settings.json)
```

Then after check 11's closing `fi` (`:177`), before the blank `echo` that opens the `FAILURES` summary (`:179`):

```bash
# 12. Session-capture hook registered (G105). `install.sh` registers it under
#     hooks.Stop; a moved repo shows as "stale" (exit 2) and is fixed by
#     re-running ./install.sh. Doctor is the loop-until-green target (G76).
CLAUDE_SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
HOOK_CMD=$(printf '"%s" "%s" --harness claude-code' "$VENV_PY" "$REPO/api/hooks/capture.py")
if [ -x "$VENV_PY" ] && "$VENV_PY" "$REPO/api/hooks/registry.py" status \
      --settings "$CLAUDE_SETTINGS" --event Stop --command "$HOOK_CMD" >/dev/null 2>&1; then
  pass "Session-capture Stop hook registered in $CLAUDE_SETTINGS"
else
  fail "Session-capture Stop hook not registered (or stale) in $CLAUDE_SETTINGS"
  note "run ./install.sh to register it — sessions are not captured until then"
fi
```

`bash -n scripts/doctor.sh` after. `HOOK_CMD` must be byte-equal to what `install.sh`'s `hook_command` registered — both use the same `printf '"%s" "%s" --harness %s'` format, and `registry.py status` compares the whole command string, so any drift between the two shows as `stale`.

- [ ] **Step 9: Run the tests**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && api/.venv/bin/python -m pytest api/tests/test_capture_hook.py api/tests/test_hooks_registry.py api/tests/test_connections_base.py -q -p no:cacheprovider && bash -n install.sh && bash -n scripts/doctor.sh && api/.venv/bin/python api/hooks/registry.py status --settings /nonexistent/settings.json --event Stop --command x; echo "exit=$?"`
Expected: tests pass (the two hook suites — 13 cases — and `scrubbed_env` were verified green by the plan critic with these exact files; `printf '{}' | python api/hooks/capture.py` exits 0, prints nothing, and appends `claude-code ? skipped: no transcript_path` to the log); both `bash -n` silent; the last line prints `absent: /nonexistent/settings.json` then `exit=1`.

- [ ] **Step 10: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && git add api/hooks/__init__.py api/hooks/capture.py api/hooks/registry.py api/services/connections/base.py install.sh scripts/doctor.sh api/tests/test_capture_hook.py api/tests/test_hooks_registry.py && git commit -m "feat(capture): Stop hook + idempotent settings.json registration; install.sh/--uninstall/doctor wire it; Cicada's own CLI spawns never capture (G105 R1/R8/R14)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

### Task 4: Sleep queue provenance — the source mark on every episode row

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Capture/OriginIconography.swift:19-…` (labels/symbol/color cases + `logoName(for:)` + `brandGlyph(for:)`)
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Common/OriginMark.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift:662-690` (`EpisodeRow`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepDebtBreakdown.swift:148-161` (`sourceRow`)
- Test: `app/CicadaApp/Tests/CicadaAppTests/OriginIconographyTests.swift`

**Interfaces:**
- `OriginIconography.logoName(for origin: String) -> String?` — a name under `Resources/logos/` or nil.
- `OriginIconography.brandGlyph(for origin: String) -> BrandGlyph?` — `.safari` / `.chrome` / nil.
- `struct OriginMark: View { let origin: String; var size: CGFloat = 14 }`.

- [ ] **Step 1: Write the failing tests**

```swift
// app/CicadaApp/Tests/CicadaAppTests/OriginIconographyTests.swift
import XCTest
@testable import CicadaApp

/// G105 companion: every episode origin resolves to a mark — a bundled PNG,
/// a drawn browser glyph, or its SF Symbol — and to a product name. Exact
/// values, so a renamed asset or a dropped case fails here, not on screen.
final class OriginIconographyTests: XCTestCase {

    func testHarnessOriginsHaveBundledLogos() {
        XCTAssertEqual(OriginIconography.logoName(for: "claude-code"), "claude-code")
        XCTAssertEqual(OriginIconography.logoName(for: "mcp"), "claude-code")
        XCTAssertEqual(OriginIconography.logoName(for: "codex"), "codex")
        XCTAssertEqual(OriginIconography.logoName(for: "claude-export"), "claude-desktop")
        XCTAssertEqual(OriginIconography.logoName(for: "telegram"), "telegram")
        XCTAssertEqual(OriginIconography.logoName(for: "pinterest"), "pinterest")
        XCTAssertEqual(OriginIconography.logoName(for: "reddit-saved"), "reddit")
        XCTAssertEqual(OriginIconography.logoName(for: "x-bookmarks"), "x")
        XCTAssertEqual(OriginIconography.logoName(for: "linkedin-saved"), "linkedin")
        XCTAssertEqual(OriginIconography.logoName(for: "tiktok-saved"), "tiktok")
        XCTAssertEqual(OriginIconography.logoName(for: "instagram-saved"), "instagram")
        XCTAssertEqual(OriginIconography.logoName(for: "youtube-playlist"), "youtube")
    }

    /// No `chatgpt.png` is bundled — the export origin must fall through to
    /// its SF Symbol rather than name an asset that does not exist.
    func testOriginsWithoutABundledLogoReturnNil() {
        XCTAssertNil(OriginIconography.logoName(for: "chatgpt-export"))
        XCTAssertNil(OriginIconography.logoName(for: "rss"))
        XCTAssertNil(OriginIconography.logoName(for: "unknown"))
        XCTAssertNil(OriginIconography.logoName(for: "safari-bookmark"))
    }

    /// Every name the map returns must exist in the bundle — the map is the
    /// only thing standing between a typo and a blank mark.
    func testEveryDeclaredLogoExistsInTheBundle() {
        let origins = ["claude-code", "mcp", "codex", "claude-export", "telegram", "pinterest",
                       "reddit-saved", "x-bookmarks", "linkedin-saved", "tiktok-saved",
                       "instagram-saved", "youtube-playlist", "cursor", "gemini-cli"]
        for origin in origins {
            guard let name = OriginIconography.logoName(for: origin) else { continue }
            XCTAssertTrue(LogoImage.exists(name: name), "\(origin) → \(name).png is not bundled")
        }
    }

    func testBrowsersUseDrawnGlyphs() {
        XCTAssertEqual(OriginIconography.brandGlyph(for: "safari-bookmark"), .safari)
        XCTAssertEqual(OriginIconography.brandGlyph(for: "safari-tab"), .safari)
        XCTAssertEqual(OriginIconography.brandGlyph(for: "chrome-bookmark"), .chrome)
        XCTAssertNil(OriginIconography.brandGlyph(for: "claude-code"))
    }

    func testProductLabelsForHarnessOrigins() {
        XCTAssertEqual(OriginIconography.label(for: "claude-code"), "Claude Code")
        XCTAssertEqual(OriginIconography.label(for: "codex"), "Codex")
        XCTAssertEqual(OriginIconography.label(for: "claude-desktop"), "Claude Desktop")
        XCTAssertEqual(OriginIconography.label(for: "cursor"), "Cursor")
        XCTAssertEqual(OriginIconography.label(for: "gemini-cli"), "Gemini CLI")
        // Byte-for-byte: the Activity origins strip keys on this label.
        XCTAssertEqual(OriginIconography.label(for: "mcp"), "MCP")
    }
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105/app/CicadaApp && swift build --build-tests 2>&1 | tail -5`
Expected: compile error — `type 'OriginIconography' has no member 'logoName'`.

- [ ] **Step 3: Extend `OriginIconography`**

In `label(for:)` add before `case "unknown"`:

```swift
        // G105: hook-driven harness capture. Product names, not ids — the
        // Sleep queue's "Catching up on" block reads these aloud.
        case "codex": "Codex"
        case "claude-desktop": "Claude Desktop"
        case "cursor": "Cursor"
        case "gemini-cli": "Gemini CLI"
```

In `symbol(for:)` add `case "codex", "cursor", "gemini-cli": "terminal"` and `case "claude-desktop": "bubble.left.and.bubble.right"`; in `color(for:)` add `case "codex", "cursor", "gemini-cli": CicadaTheme.textPrimary` and `case "claude-desktop": CicadaTheme.accent`. Then append inside the enum:

```swift
    /// The bundled PNG under `Resources/logos/` for an origin, or nil when
    /// there is none (ChatGPT, RSS, calendar, the browsers — which draw
    /// their own glyph, `brandGlyph(for:)`). `mcp` shares Claude Code's mark:
    /// it is the same harness under its legacy id. The map is exhaustive by
    /// test (`OriginIconographyTests.testEveryDeclaredLogoExistsInTheBundle`),
    /// so a typo here fails before it ships a blank mark.
    static func logoName(for origin: String) -> String? {
        switch origin {
        case "claude-code", "mcp": "claude-code"
        case "codex": "codex"
        case "claude-export", "claude-desktop": "claude-desktop"
        case "cursor": "cursor"
        case "gemini-cli": "gemini-cli"
        case "telegram": "telegram"
        case "pinterest": "pinterest"
        case "reddit-saved", "reddit": "reddit"
        case "x-bookmarks", "x": "x"
        case "linkedin-saved": "linkedin"
        case "tiktok-saved", "tiktok-history": "tiktok"
        case "instagram-saved": "instagram"
        case "youtube-playlist": "youtube"
        default: nil
        }
    }

    /// Drawn marks for the browsers (no brand asset is downloaded — R7 of
    /// the Safari import track), same precedence `MemberMark` uses.
    static func brandGlyph(for origin: String) -> BrandGlyph? {
        switch origin {
        case "safari-bookmark", "safari-tab": .safari
        case "chrome-bookmark": .chrome
        default: nil
        }
    }
```

- [ ] **Step 4: `OriginMark.swift`**

```swift
import SwiftUI

/// One origin, one mark, at any size: bundled PNG → drawn browser glyph →
/// the origin's SF Symbol in its color. The Sleep queue rows and the
/// "Catching up on" block both use it (G105 companion: "where did this
/// come from" answerable at a glance), so an episode reads the same in
/// both places and the same as its tile in the import catalog.
struct OriginMark: View {
    let origin: String
    var size: CGFloat = 14

    var body: some View {
        Group {
            if let name = OriginIconography.logoName(for: origin), LogoImage.exists(name: name) {
                LogoImage(name: name, size: size)
            } else if let glyph = OriginIconography.brandGlyph(for: origin) {
                switch glyph {
                case .safari: SafariGlyph(size: size)
                case .chrome: ChromeGlyph(size: size)
                }
            } else {
                Image(systemName: OriginIconography.symbol(for: origin))
                    .font(.system(size: size * 0.8, weight: .medium))
                    .foregroundStyle(OriginIconography.color(for: origin))
            }
        }
        .frame(width: size, height: size)
        .accessibilityLabel(OriginIconography.label(for: origin))
    }
}
```

Verified against the code (plan critic, 2026-09-03): `LogoImage`'s `bundledBody` (`LogoImage.swift:58-68`) draws a plain square image — the circle + ring is `entityBody` only; `SafariGlyph` (`ImportFamilies.swift:191`) and `ChromeGlyph` (`:163`) both take `size:`; `BrandGlyph` (`:82`) is `Equatable`, so the test's `XCTAssertEqual(…, .safari)` compiles; `LogoImage` reads `@Environment(Store.self)`, which the app injects at its root (`CicadaApp.swift:82,165`), so `OriginMark` needs no extra environment. This file plus the `OriginIconography` additions compiled and passed the five tests in a scratch copy of the package.

- [ ] **Step 5: Use it in `EpisodeRow` and `sourceRow`**

`SleepView.swift` `EpisodeRow.body` — insert the mark between the status dot and the text column so the dot keeps meaning "queued vs processed":

```swift
            Circle()
                .fill(item.processed ? CicadaTheme.textTertiary : CicadaTheme.accent)
                .frame(width: 8, height: 8)
                .padding(.top, 6)

            OriginMark(origin: item.origin, size: 16)
                .padding(.top, 2)
```

`SleepDebtBreakdown.sourceRow` — replace the `Image(systemName:)` block with:

```swift
            OriginMark(origin: row.origin, size: 16)
```

- [ ] **Step 6: Build and test**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20`
Expected: build succeeds; `swift test` reports 0 failures (`OriginIconographyTests` 5 cases green — verified in a scratch copy of the package by the plan critic, `Build complete!` + `Executed 5 tests, with 0 failures`; `SleepDebtBreakdownTests`, `ImportCatalogTests`, `ResourceBundleTests` unchanged).

- [ ] **Step 7: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && git add app/CicadaApp/Sources/CicadaApp/Views/Capture/OriginIconography.swift app/CicadaApp/Sources/CicadaApp/Views/Common/OriginMark.swift app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepDebtBreakdown.swift app/CicadaApp/Tests/CicadaAppTests/OriginIconographyTests.swift && git commit -m "feat(app): Sleep queue rows and Catching-up block wear the source mark; codex/claude-desktop/cursor/gemini-cli product labels (G105 companion, R11)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

### Task 5: Docs — CLAUDE.md, the G105 row, the TODO.md handoff

**Files:**
- Modify: `CLAUDE.md` (Input sources list; `POST /capture/…` line in the API list; the G114 paragraph's writer list)
- Modify: `docs/goals/memory-evolution.md` row `G105` (`:667`), row `G76` (`:638`, the hook half)
- Modify: `docs/goals/TODO.md` (Where things stand, Live environment, Pick up here)

Privacy rule applies: placeholders only, no episode titles, no paths beyond `~/…`.

- [ ] **Step 1: CLAUDE.md**

In the **Input sources** list, after the `MCP-native clients` bullet:

```markdown
- **Hook-driven session capture (G105, deterministic):** every Claude Code session — and every
  Codex session when the CLI is installed — is captured by the harness's own `Stop` hook
  (`api/hooks/capture.py`, registered by `install.sh` in `~/.claude/settings.json` /
  `~/.codex/hooks.json`, merged never clobbered, `make doctor` reports it). The hook forwards the
  harness's stdin fields to the bearer-authed `POST /capture/transcript`; **the backend reads the
  transcript**, and only after the path resolves under the harness root as `<session_id>.jsonl`
  within the size cap — anything else is refused unread. `api/services/transcript_extract.py` keeps
  exactly (a) the person's turns (`user` messages whose blocks are `text`; a `tool_result` wearing
  the user role is dropped) and (b) the agent's **final reply per turn** (the last assistant `text`
  after the last `tool_use`); interstitial narration, `tool_use`/`tool_result`/thinking blocks, file
  dumps, harness-injected `<task-notification>`/`<command-…>`/`<system-reminder>` text are skipped by
  construction. On what survives: code fences stripped, secrets scrubbed, a 2,000-char per-turn cap
  and a head-stable 100,000-char session cap. **One episode per session** (`capture_kind:
  transcript`, `origin: claude-code|codex`, `session_id`, `harness`, `project_dir`), body as
  `role: text` lines exactly like the importer so G118 spans cite it; every later Stop on the same
  session rewrites that episode in place and flips `processed: false` (`processed_by` popped) —
  never two episodes for one conversation (G104). `CICADA_CAPTURE_ASSISTANT_REPLIES=false` keeps only
  the person's turns. Cicada's own `claude -p` spawns run with `CICADA_CAPTURE=off` and are never
  captured. A counts-only `capture` ledger row per firing; the hook logs one line per firing to
  `~/.cicada/logs/capture.log`. Claude Desktop / ChatGPT stay export-based; Cursor and other
  harnesses have no hook yet.
```

In the API list, after `POST /capture/telegram`:

```
POST /capture/transcript                  → Stop-hook session capture (G105): validates the transcript
                                            path against the harness root, extracts, writes/updates
                                            ONE episode per session_id; 400 with an enum reason otherwise
```

In the **Episode tracking (G114)** paragraph's writer list, change "Every writer — importer, MCP, media, Telegram, calendar, notes —" to "Every writer — importer, MCP, media, Telegram, calendar, notes, the G105 transcript capture —".

In the **Companion App → Sync engine** paragraph, after "Sleep carries the episode queue": add ", each row wearing its source's mark (`OriginMark`: bundled logo → browser glyph → SF Symbol)".

- [ ] **Step 2: `docs/goals/memory-evolution.md`**

Append to the G105 row's text column, before the closing ` | 🔲 |`, and flip the status cell to `✅`:

```
**Shipped 2026-09-03 (PR #TBD, `feat/deterministic-capture`):** `api/services/transcript_extract.py` (R4 boundary rule: any user-role message without a `tool_result` is a boundary, a `tool_use` resets the pending reply; R5 harness-tag filter per block; R6 order fences → scrub → per-turn cap → head-stable session cap); `POST /capture/transcript` + `transcript_capture.py` (R2 path validation under the harness root, `<session_id>.jsonl`, 256 MiB cap; R3 one episode per `(capture_kind: transcript, session_id)`, updated in place with `processed: false` and `processed_by` popped; R10 counts-only `capture` ledger row); the `Stop` hook (R1 — `SessionEnd` never fires on a closed window and shares a 1.5 s budget; the last Stop is the end) with an idempotent settings-merge registry driven by `install.sh` / `--uninstall` / `make doctor`; R8 `CICADA_CAPTURE=off` on every Cicada CLI spawn so Sleep's own prompts are never captured; the Sleep queue's source marks. **Open:** Claude Desktop / ChatGPT stay export-based; Cursor and other harnesses have no hook; Codex's Stop payload is registered but unverified hands-on (the hook logs `skipped: no transcript_path` if it lacks the field); no backfill over past transcripts by design (the only read is the session that just ended). Owner's fallback if the assistant half is noisy: `CICADA_CAPTURE_ASSISTANT_REPLIES=false`.
```

In the G76 row, append to the text column: `**Hook half shipped by G105 (2026-09-03):** the Stop hook + settings merge + doctor check; the `install.md` paste-prompt half stays open.`

- [ ] **Step 3: `docs/goals/TODO.md`**

Under **Where things stand**, add a paragraph:

```markdown
**G105 deterministic capture — `feat/deterministic-capture` (worktree `.worktrees/g105`), PR #TBD against
`dev`.** Every Claude Code session is captured by its own `Stop` hook into one episode per session, block-level
(person's turns + agent's final replies; tool blocks, code and secrets never), updated in place on every later
Stop. **One manual step for an existing install:** re-run `./install.sh` (idempotent) to register the hook in
`~/.claude/settings.json`; `make doctor` check 12 says whether it is there. Then open any Claude Code session,
say one sentence, and `tail ~/.cicada/logs/capture.log` shows `claude-code <id> http 200 created`; the Sleep
page lists the episode with the Claude Code mark. Codex: registered when the CLI is present, payload not yet
verified — the same log line says `skipped: no transcript_path` if Codex's Stop hook does not pass one.
```

Under **Live environment**, add: "`install.sh` now also writes `hooks.Stop` into `~/.claude/settings.json` (merge, never clobber); `--uninstall` removes only Cicada's entry."

Under **Rulings** (`:97-116`, six today), append to ruling 6 ("Capture is agent-judgment and that is a measured problem", `:115-116`): " **Answered by the G105 hook (2026-09-03):** capture is now a property of the harness's Stop hook, not of a model's tool call — the MCP `cicada_save_episode` path stays as the deliberate, agent-chosen episode." Then add ruling 7: "**The Stop hook, not SessionEnd, is the capture trigger** (G105 R1) — SessionEnd never fires for a closed window or a killed process and shares a 1.5 s budget; the endpoint's content-hash short-circuit makes per-turn firing idempotent. Revisit only if per-turn transcript reads show up in `capture.log` latencies above the hook's 3 s timeout on the live bank."

Update **Pick up here** to name this branch and the manual step.

- [ ] **Step 4: Privacy scan of everything staged**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && git diff --cached --name-only; git diff dev --stat | tail -3; git diff dev -- CLAUDE.md docs/goals/ api/ app/ install.sh scripts/ | grep -n -i "rorosaga\|/Users/\|rodrigo" || echo "no owner name / author path in the diff"`
Expected: the final line `no owner name / author path in the diff`. (The G-row voice "Rodrigo 2026-09-01: …" pre-exists in `memory-evolution.md` and is not in this diff.)

- [ ] **Step 5: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && git add CLAUDE.md docs/goals/memory-evolution.md docs/goals/TODO.md && git commit -m "docs(goals): G105 shipped — hook-driven deterministic capture; CLAUDE.md input-sources + API; TODO.md handoff with the one re-run-install step

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

## Verification the orchestrator runs at the end

1. **Python, full suite:** `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105 && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -15` — expect only the 8 `test_calendar_registry.py` failures plus the one order-dependent `test_agent_provenance.py` case; every `test_transcript_extract`, `test_capture_transcript`, `test_capture_hook`, `test_hooks_registry`, `test_auth`, `test_telemetry`, `test_consumption_stats`, `test_connections_base` case green.
2. **Swift:** `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g105/app/CicadaApp && swift build 2>&1 | tail -3 && swift test 2>&1 | grep -E "Executed|failed" | tail -3` — 0 failures.
3. **Scripts:** `bash -n install.sh && bash -n scripts/doctor.sh`; `CICADA_MEMORY_PATH=/tmp/x LAUNCH_AGENTS_DIR=/tmp/x CLAUDE_SETTINGS=/tmp/x/s.json CODEX_HOOKS=/tmp/x/h.json ./install.sh --dry-run | grep -c registry.py` ≥ 1 and nothing created under `/tmp/x`.
4. **Registry on a scratch file:** `api/.venv/bin/python api/hooks/registry.py install --settings /private/tmp/claude-501/-Users-rorosaga-Documents-roros-lab-cicada/1d742a99-90a0-46a2-a0d9-4642052335bf/scratchpad/s.json --event Stop --command 'x api/hooks/capture.py'` → `added`; again → `present`; `status` → exit 0; `uninstall` → file is `{}`.
5. **Hook never blocks:** `printf '{}' | api/.venv/bin/python api/hooks/capture.py --harness claude-code; echo $?` → `0`, empty stdout, one `skipped: no transcript_path` line appended to `$CICADA_HOME/logs/capture.log` (set `CICADA_HOME` to the scratchpad for this check so the real home is untouched).
6. **Rails, by grep:** `grep -rn "\.claude\|\.codex" api/services/transcript_capture.py api/hooks/capture.py` shows only `harness_root` / docstrings — no other module opens a transcript; `grep -n "capture/transcript" api/services/auth.py` returns nothing (not exempt); `grep -rn "rorosaga\|/Users/" api/services/transcript_*.py api/hooks/ install.sh scripts/doctor.sh` returns nothing.
7. **Diff read** of the five commits, then the orchestrator installs (`make install-app`, re-runs `./install.sh`) and does the one live check from TODO.md: a fresh Claude Code session, one sentence, `tail -3 ~/.cicada/logs/capture.log`, the episode on the Sleep page with the Claude Code mark, and — the G76 open item — that `capture.log`'s session id prefix matches the `session_id` of the MCP-written episode in the same session (`GET /conversations/recent` groups them as one row). If Codex is installed: one Codex turn and the corresponding log line (`http 200 …` or `skipped: no transcript_path` — the latter closes R9's open verification as "Codex Stop passes no transcript path", to be recorded in the G105 row).
